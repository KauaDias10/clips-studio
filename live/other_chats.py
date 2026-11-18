"""Chat for the lives that aren't on Twitch.

YouTube: the official Data API (liveChatMessages.list) through the YouTube
account connected in Settings (its read-only permission). Each reading
costs 5 units of the project's daily 10,000, so it reads every
MIN_POLL seconds at most: about five hours of chat a day.

Kick: its official API gives chat only to apps with a public web address
(webhooks), which a desktop app hasn't got, so Kick lives are clipped from
audio peaks (live/audio_peaks.py) without chat.

Both keep the messages in memory only, like the Twitch reader.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime

from live.chat import KEEP_SECONDS

API = "https://www.googleapis.com/youtube/v3"
MIN_POLL = 10.0


class NoChat:
    """A live whose chat can't be read: says why, gives no messages."""

    connected = False

    def __init__(self, why: str):
        self.error = why

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def since(self, t: float) -> list:
        return []


class YouTubeChat:
    def __init__(self, video_id_of, credentials):
        """video_id_of(): the live's video id once the recorder found it
        (None until then). credentials(): fresh Google credentials."""
        self.video_id_of = video_id_of
        self.credentials = credentials
        self.messages: deque = deque()
        self.connected = False
        self.error = ""
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self._run, name="live-chat-youtube", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def since(self, t: float) -> list:
        with self._lock:
            return [m for m in self.messages if m[0] >= t]

    def _get(self, path: str, **params) -> dict:
        import requests

        creds = self.credentials()
        r = requests.get(f"{API}/{path}", params=params, timeout=20,
                         headers={"Authorization": f"Bearer {creds.token}"})
        if r.status_code == 403 and "quota" in r.text.lower():
            raise RuntimeError("YouTube's daily API quota is used up; chat comes back tomorrow.")
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = f"HTTP {r.status_code}"
            raise RuntimeError(f"YouTube chat: {msg}")
        return r.json()

    def _chat_id(self) -> str | None:
        vid = self.video_id_of()
        if not vid:
            return None
        items = self._get("videos", part="liveStreamingDetails", id=vid).get("items") or []
        chat = ((items[0] if items else {}).get("liveStreamingDetails") or {}).get("activeLiveChatId")
        if not chat:
            raise RuntimeError("This YouTube live has no chat (off, or for members only).")
        return chat

    def _run(self) -> None:
        chat_id, token, wait = None, None, 0.0
        while not self._stop.wait(wait):
            try:
                if chat_id is None:
                    chat_id = self._chat_id()
                    if chat_id is None:     # the recorder hasn't found the live yet
                        wait = 3.0
                        continue
                params = {"liveChatId": chat_id, "part": "snippet,authorDetails", "maxResults": 2000}
                if token:
                    params["pageToken"] = token
                data = self._get("liveChat/messages", **params)
                token = data.get("nextPageToken") or token
                self.connected, self.error = True, ""
                for item in data.get("items", []):
                    s, a = item.get("snippet") or {}, item.get("authorDetails") or {}
                    text = s.get("displayMessage") or ""
                    if not text:
                        continue
                    try:
                        at = datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00")).timestamp()
                    except (KeyError, ValueError):
                        at = time.time()
                    self._keep((at, a.get("displayName") or "?", text))
                wait = max(MIN_POLL, (data.get("pollingIntervalMillis") or 0) / 1000)
            except Exception as e:
                self.connected = False
                self.error = str(e)[:200]
                wait = 60.0

    def _keep(self, msg) -> None:
        with self._lock:
            self.messages.append(msg)
            cutoff = time.time() - KEEP_SECONDS
            while self.messages and self.messages[0][0] < cutoff:
                self.messages.popleft()
