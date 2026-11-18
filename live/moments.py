"""When something happened on a live stream, from what its audience did.

Three signals, strongest first:

- A clip a viewer made on Twitch: a person decided those seconds were worth
  keeping. Read from the official Helix API through the connected Twitch
  account (optional: without one, the other two still work).
- Viewers typing !clip (or !clipe): several different people within a few
  seconds of each other.
- Chat bursting far above its own normal rate, read by the same detector the
  VOD path uses (analysis/chat_moments.py), run over the last few minutes.

Chat reacts after the moment (stream delay + typing), so chat moments are
dated chat_lag_seconds earlier; a viewer clip already covers the seconds
before it was made.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

LOOKBACK = 240          # seconds of chat each reading looks at
WARMUP = 90             # chat needed before a burst means anything: right
                        # after joining, any minute looks like a spike
SETTLE = 4              # a burst is read once it is this many seconds old
COMMAND = re.compile(r"^!clip(e|a|ar)?\b", re.IGNORECASE)


@dataclass
class Moment:
    at: float            # wall clock of the moment itself
    start: float         # clip window, wall clock
    end: float
    kind: str            # "viewer_clip" | "command" | "chat"
    reason: str
    strength: float = 1.0
    title: str = ""
    extra: dict = field(default_factory=dict)


class MomentDetector:
    def __init__(self, *, pre: float = 25.0, post: float = 8.0, cooldown: float = 45.0,
                 min_votes: int = 3, vote_window: float = 20.0, lag: float | None = None,
                 classes: dict | None = None, ignore: list | None = None, chat: bool = True):
        if classes is None or lag is None or ignore is None:
            from analysis.gaming import knowledge

            k = knowledge()
            classes = k.get("chat_classes", {}) if classes is None else classes
            lag = float(k.get("chat_lag_seconds", 6)) if lag is None else lag
            ignore = k.get("chat_ignore", []) if ignore is None else ignore
        self.pre, self.post, self.cooldown = pre, post, cooldown
        self.min_votes, self.vote_window = min_votes, vote_window
        self.lag, self.classes, self.ignore = lag, classes, ignore
        self.use_chat = chat
        self.emitted: list[Moment] = []
        self._seen_chat: set[int] = set()
        self._votes_until = 0.0
        self._seen_clips: set[str] = set()

    # ---- the three signals -------------------------------------------------

    def read_chat(self, messages: list, now: float | None = None) -> list[Moment]:
        """messages: [(epoch, author, text)] of the last minutes."""
        now = time.time() if now is None else now
        found = self._votes(messages, now)
        if self.use_chat:
            found += self._bursts(messages, now)
        return [m for m in found if self._keep(m)]

    def viewer_clip(self, clip_id: str, created: float, duration: float, title: str = "",
                    url: str = "", creator: str = "") -> Moment | None:
        if clip_id in self._seen_clips:
            return None
        self._seen_clips.add(clip_id)
        m = Moment(at=created - 3, start=created - duration - 2, end=created + 2, kind="viewer_clip",
                   reason=f"Twitch clip by {creator or 'a viewer'}: {title}".strip(": "), strength=3.0,
                   title=title, extra={"url": url, "clip_id": clip_id})
        return m if self._keep(m, override=True) else None

    def _votes(self, messages: list, now: float) -> list[Moment]:
        recent = [(t, who) for t, who, text in messages
                  if t >= now - self.vote_window and t > self._votes_until and COMMAND.match(text or "")]
        voters = {}
        for t, who in recent:
            voters.setdefault(who.lower(), t)
        if len(voters) < self.min_votes:
            return []
        first = min(voters.values())
        self._votes_until = now
        at = first - self.lag
        return [Moment(at=at, start=at - self.pre, end=at + self.post, kind="command",
                       reason=f"{len(voters)} viewers typed !clip", strength=2.0)]

    def _bursts(self, messages: list, now: float) -> list[Moment]:
        from analysis.chat_moments import chat_signal

        if not messages or min(t for t, _w, _x in messages) > now - WARMUP:
            return []
        # Measured from the first message heard, never from before it: empty
        # seconds would make the first minute of chat look like a burst.
        t0 = max(now - LOOKBACK, min(t for t, _w, _x in messages))
        rel = [(t - t0, who, text) for t, who, text in messages if t >= t0]
        sig = chat_signal(rel, now - t0, self.classes, lag=self.lag, ignore=self.ignore)
        if sig is None:
            return []
        out = []
        for sec, text in sig.events:
            at = t0 + sec
            # Only bursts that have settled (the next readings would date them
            # the same) and that are not already handled.
            if at > now - self.lag - SETTLE or int(at) in self._seen_chat:
                continue
            if any(abs(int(at) - s) <= 10 for s in self._seen_chat):
                continue
            self._seen_chat.add(int(at))
            out.append(Moment(at=at, start=at - self.pre, end=at + self.post, kind="chat",
                              reason=text.replace("CHAT: ", "chat: "), strength=1.0))
        return out

    def keep(self, m: Moment) -> bool:
        """A moment found elsewhere (audio peaks): kept unless one is near."""
        return self._keep(m)

    # ---- one clip per moment ----------------------------------------------

    def _keep(self, m: Moment, override: bool = False) -> bool:
        """No two clips of the same moment. A viewer clip near a moment chat
        already gave widens that clip instead of making a second one."""
        for old in self.emitted:
            if abs(old.at - m.at) < self.cooldown:
                if override and m.strength > old.strength and not old.extra.get("queued"):
                    self.emitted.remove(old)
                    break
                return False
        self.emitted.append(m)
        self.emitted = self.emitted[-200:]
        return True
