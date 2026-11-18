"""Which live a link points at: Twitch, Kick or YouTube.

A bare name is a Twitch channel (what the Live page took before the others).
Every live is keyed "<platform>:<channel>", so the same name on two sites
are two sessions, and several lives can be clipped at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TWITCH = re.compile(r"^[A-Za-z0-9_]{2,25}$")
_KICK = re.compile(r"^[A-Za-z0-9_-]{2,40}$")


@dataclass(frozen=True)
class Target:
    platform: str      # "twitch" | "kick" | "youtube"
    channel: str       # login / slug / @handle / UC… id / video id
    page_url: str      # what yt-dlp is given to find the live

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.channel}"

    @property
    def label(self) -> str:
        return {
            "twitch": f"twitch.tv/{self.channel}",
            "kick": f"kick.com/{self.channel}",
        }.get(self.platform, self.page_url.replace("https://www.", "").replace("/live", ""))

    @property
    def slug(self) -> str:
        """A name safe in file and video ids: twitch keeps the bare channel
        (as before), the others are prefixed."""
        clean = re.sub(r"[^a-z0-9_-]", "", self.channel.lower().lstrip("@"))
        return clean if self.platform == "twitch" else f"{self.platform}-{clean}"


def parse_target(value: str) -> Target:
    v = (value or "").strip()
    m = re.search(r"(?:^|//|\.)twitch\.tv/([A-Za-z0-9_]+)", v)
    if m or _TWITCH.match(v.lstrip("#@")) and "." not in v and "/" not in v:
        name = (m.group(1) if m else v.lstrip("#@")).lower()
        if not _TWITCH.match(name):
            raise ValueError("Use a Twitch channel name or link, like twitch.tv/alanzoka.")
        return Target("twitch", name, f"https://www.twitch.tv/{name}")
    m = re.search(r"(?:^|//|\.)kick\.com/([A-Za-z0-9_-]+)", v)
    if m:
        slug = m.group(1).lower()
        if not _KICK.match(slug):
            raise ValueError("Use a Kick channel link, like kick.com/channel.")
        return Target("kick", slug, f"https://kick.com/{slug}")
    m = (re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", v)
         or re.search(r"youtube\.com/(?:watch\?(?:.*&)?v=|live/|shorts/)([A-Za-z0-9_-]{11})", v))
    if m:
        return Target("youtube", m.group(1), f"https://www.youtube.com/watch?v={m.group(1)}")
    m = re.search(r"youtube\.com/(@[A-Za-z0-9._-]+|channel/UC[A-Za-z0-9_-]{22})", v)
    if m:
        part = m.group(1)
        name = part.split("/", 1)[1] if part.startswith("channel/") else part
        return Target("youtube", name, f"https://www.youtube.com/{part}/live")
    raise ValueError("Use a Twitch, Kick or YouTube live link (twitch.tv/…, kick.com/…, youtube.com/@…).")
