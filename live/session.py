"""One channel being clipped live: recorder + chat + moments -> live_clip jobs."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from live.audio_peaks import AudioPeaks
from live.chat import TwitchChat
from live.group import group_for
from live.other_chats import NoChat, YouTubeChat
from live.platforms import Target, parse_target
from live.moments import LOOKBACK, Moment, MomentDetector
from live.recorder import Recorder

TICK = 3.0
CLIPS_POLL = 60.0


def channel_name(value: str) -> str:
    """'alanzoka', '#alanzoka' or 'https://www.twitch.tv/alanzoka' -> 'alanzoka'."""
    t = parse_target(value)
    if t.platform != "twitch":
        raise ValueError("Use a Twitch channel name or link, like twitch.tv/alanzoka.")
    return t.channel


class LiveSession:
    def __init__(self, channel: "str | Target", config: dict, data_dir: Path, queue_clip, *,
                 accounts=None, publish=None, options: dict | None = None, youtube_credentials=None):
        self.target = channel if isinstance(channel, Target) else parse_target(channel)
        self.platform = self.target.platform
        # Files, the live's video id and the layout cache go by this name.
        self.channel = self.target.slug
        self.config = config
        self.data_dir = Path(data_dir)
        self.queue_clip = queue_clip          # (payload dict) -> job id
        self.accounts = accounts
        self.publish = publish or (lambda event: None)
        o = options or {}
        self.options = o
        self.started = time.time()
        # Every clip of this live goes into one video (live/group.py).
        self.group_id = group_for(self.data_dir, self.channel, self.started)
        self.page_url = self.target.page_url
        if self.platform == "twitch":
            self.chat = TwitchChat(self.target.channel)
        elif self.platform == "youtube" and youtube_credentials is not None:
            self.chat = YouTubeChat(lambda: self.recorder.video_id, youtube_credentials)
        elif self.platform == "youtube":
            self.chat = NoChat("Connect a YouTube account in Settings to read this live's chat.")
        else:
            self.chat = NoChat("Kick only gives its chat to apps with a public web address, so "
                               "this live is clipped from its audio peaks.")
        self.recorder = Recorder(self.page_url, self.data_dir / "live" / self.channel / "buffer",
                                 keep_seconds=int(o.get("buffer_seconds", 600)),
                                 height=int(o.get("height", 720)))
        self.detector = MomentDetector(pre=float(o.get("pre_seconds", 25)),
                                       post=float(o.get("post_seconds", 8)),
                                       min_votes=int(o.get("min_votes", 3)),
                                       chat=bool(o.get("chat_bursts", True)))
        self.max_clips = int(o.get("max_clips", 40))
        # Loud stretches of the stream itself: on unless asked otherwise where
        # there is no chat to go by, off by default on Twitch.
        self.audio = (AudioPeaks(pre=float(o.get("pre_seconds", 25)), post=float(o.get("post_seconds", 8)))
                      if o.get("audio_peaks", self.platform != "twitch") else None)
        self.pending: list[Moment] = []
        self.log: list[dict] = []
        self.clips_queued = 0
        self.clips_error = ""
        self._stop = threading.Event()
        self._last_clips_poll = 0.0

    # ---- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self.chat.start()
        self.recorder.start()
        threading.Thread(target=self._loop, name=f"live-{self.channel}", daemon=True).start()
        self._note("started", f"Watching {self.target.label}")

    def stop(self) -> None:
        self._stop.set()
        self.chat.stop()
        self.recorder.stop()
        self._note("stopped", "Stopped")

    @property
    def running(self) -> bool:
        return not self._stop.is_set()

    def status(self) -> dict:
        now = time.time()
        recent = self.chat.since(now - 60)
        return {
            "channel": self.target.channel,
            "key": self.target.key,
            "platform": self.platform,
            "label": self.target.label,
            "page_url": self.page_url,
            "audio_peaks": self.audio is not None,
            "group_id": self.group_id,
            "running": self.running,
            "started": self.started,
            "recording": self.recorder.recording,
            "buffered_seconds": round(sum(s.seconds for s in self.recorder.segments)),
            "recorder_error": self.recorder.error,
            "chat_connected": self.chat.connected,
            "chat_error": self.chat.error,
            "chat_per_minute": len(recent),
            "stream_title": self.recorder.title,
            "pending": len(self.pending),
            "clips_queued": self.clips_queued,
            "max_clips": self.max_clips,
            "viewer_clips": (self.platform == "twitch" and self.accounts is not None
                             and bool(self._twitch_account())),
            "viewer_clips_error": self.clips_error,
            "log": self.log[-50:],
        }

    # ---- the loop -----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.wait(TICK):
            try:
                self._tick()
            except Exception as e:   # one bad reading never ends the session
                self._note("error", str(e)[:200])

    def _tick(self) -> None:
        now = time.time()
        # Nothing counts before the buffer holds video: a moment from before
        # the recording started can't be cut.
        if not self.recorder.segments:
            return
        oldest = self.recorder.segments[0].start
        messages = [m for m in self.chat.since(now - LOOKBACK) if m[0] >= oldest - 30]
        for m in self.detector.read_chat(messages, now):
            self._found(m)
        if self.audio is not None:
            for seg in list(self.recorder.segments):
                self.audio.feed(seg)
            for m in self.audio.detect():
                if self.detector.keep(m):
                    self._found(m)
        if now - self._last_clips_poll >= CLIPS_POLL:
            self._last_clips_poll = now
            for m in self._viewer_clips():
                self._found(m)
        self._cut_ready()

    def _found(self, m: Moment) -> None:
        self.pending.append(m)
        self._note("moment", m.reason, at=m.at, kind=m.kind)

    def _cut_ready(self) -> None:
        covered = self.recorder.covered_until()
        for m in list(self.pending):
            if m.end > covered:
                if time.time() - m.end > 120:
                    self.pending.remove(m)   # the recording missed it (a reconnect)
                    self._note("skipped", f"Not recorded: {m.reason}", kind=m.kind)
                continue              # its last seconds aren't recorded yet
            self.pending.remove(m)
            # Seconds from before the recording began can't be cut.
            if self.recorder.segments:
                m.start = max(m.start, self.recorder.segments[0].start)
            if m.end - m.start < 8:
                continue
            if self.clips_queued >= self.max_clips:
                self._note("skipped", f"Clip limit ({self.max_clips}) reached: {m.reason}")
                continue
            try:
                self._queue(m)
            except Exception as e:
                self._note("error", f"Could not cut {m.reason}: {e}"[:200])

    def _queue(self, m: Moment) -> None:
        stamp = datetime.fromtimestamp(m.at).strftime("%Y%m%d_%H%M%S")
        video_id = f"livecut_{self.channel}_{stamp}"   # this moment's seconds, until adopted
        source = self.data_dir / "downloads" / f"{video_id}.mp4"
        start, end = self.recorder.extract(m.start, m.end, source)
        m.extra["queued"] = True
        payload = {
            "video_id": video_id, "group_id": self.group_id, "start": start, "end": end, "channel": self.target.channel,
            "channel_key": self.channel, "platform": self.platform,
            "reason": m.reason, "kind": m.kind, "title": m.title,
            "stream_title": self.recorder.title, "at": m.at,
            "url": self.page_url, **({"clip_url": m.extra["url"]} if m.extra.get("url") else {}),
            **{k: self.options[k] for k in ("caption_style", "gaming", "gaming_layout", "captions")
               if k in self.options},
        }
        job = self.queue_clip(payload)
        self.clips_queued += 1
        self._note("queued", m.reason, at=m.at, kind=m.kind, job_id=job, video_id=self.group_id)

    # ---- clips viewers made on Twitch ---------------------------------------

    def _twitch_account(self) -> str | None:
        try:
            rows = [a for a in self.accounts.accounts("twitch") if a.get("status", "connected") == "connected"]
        except Exception:
            return None
        return rows[0]["id"] if rows else None

    def _viewer_clips(self) -> list[Moment]:
        if self.platform != "twitch":
            return []             # viewer clips are read from Twitch only
        account = self._twitch_account() if self.accounts is not None else None
        if not account:
            return []
        since = max(self.started, self.recorder.segments[0].start) - 60
        try:
            data = self.accounts.perform(
                account, "clips", broadcaster_login=self.target.channel, first=50,
                started_at=datetime.fromtimestamp(since, timezone.utc).isoformat().replace("+00:00", "Z"))
            self.clips_error = ""
        except Exception as e:
            self.clips_error = str(e)[:200]
            return []
        out = []
        for c in data.get("clips", []):
            try:
                created = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                continue
            m = self.detector.viewer_clip(c["id"], created, float(c.get("duration") or 30),
                                          c.get("title", ""), c.get("url", ""), c.get("creator_name", ""))
            if m:
                out.append(m)
        return out

    # ---- log ----------------------------------------------------------------

    def _note(self, event: str, text: str, **extra) -> None:
        entry = {"t": time.time(), "type": event, "text": text, **extra}
        self.log.append(entry)
        self.log = self.log[-200:]
        print(f"[live {self.channel}] {event}: {text}")
        self.publish({"type": "live", "channel": self.target.key, "entry": json.loads(json.dumps(entry))})
