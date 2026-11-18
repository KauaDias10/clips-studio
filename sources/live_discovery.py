"""Find the biggest finished livestreams about a topic, so they can be clipped.

Channel watching (sources/channel_feed.py) answers "this creator posted"; this
answers "what are people streaming about X today, and which of it was big". It
only finds and vets: each result is a link that then goes through the same
queue a pasted one does.

YouTube only, on purpose. YouTube search takes a "Live" + upload-date filter
and yt-dlp can read the result page. Twitch has no category VOD listing that
yt-dlp (or sources/twitch.py) can read without Twitch's integrity check, and
Kick's only listing is per channel, so neither can answer "top streams about a
game" cleanly. Asking for them is refused with that said, not silently empty.

How it works: one cheap flat search for candidates, then a bounded number of
full looks, most-viewed first, to confirm each one really is a finished,
public, long-enough stream. Anything that fails or looks wrong is skipped on
its own; one bad entry never fails the search.

Every function that touches the network takes it as an argument, so tests
never do.
"""

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

SUPPORTED = ("youtube",)

# How many search results are read, and how many of them are opened for full
# metadata. The search is one request; each full look is another, so the second
# number is the cost that matters.
SEARCH_SIZE = 40
MAX_CHECKS = 15

# What YouTube says about a video nobody outside a group can watch.
_RESTRICTED = ("subscriber_only", "premium_only", "needs_auth", "private")

# A stream that is live, about to be, or just ended and still processing gives
# an incomplete file if it is downloaded now.
_NOT_FINISHED = ("is_live", "is_upcoming", "post_live", "not_live")


@dataclass
class FoundLive:
    url: str
    title: str = ""
    channel: str = ""
    platform: str = "youtube"
    duration_s: float = 0.0
    view_count: int = 0
    started_at: float = 0.0  # unix seconds; 0 when YouTube does not say
    reason_skipped: str | None = None


def _filter_param(max_age_hours: float) -> str:
    """YouTube's `sp=` value for results sorted by views, uploaded today (or
    this week for a longer window). Not the "Live" feature filter: that one
    means "on air right now", and a stream still on air cannot be clipped.
    Finished streams come back from this search marked `was_live`. It is a small protobuf message that YouTube
    base64-encodes; built here from its parts rather than pasted as an opaque
    string, so what each byte means stays readable."""
    date = 2 if max_age_hours <= 24 else 3  # 2 = today, 3 = this week
    # field 1 (sort) = 3 (view count); field 2 (filters) = {1: date}
    message = bytes([0x08, 0x03, 0x12, 0x02, 0x08, date])
    return quote(base64.urlsafe_b64encode(message).decode("ascii"), safe="")


def search_url(query: str, max_age_hours: float = 24) -> str:
    return (f"https://www.youtube.com/results?search_query={quote(query.strip())}"
            f"&sp={_filter_param(max_age_hours)}")


def check(info: dict, *, now: float, max_age_hours: float, min_duration_s: float) -> FoundLive | str:
    """A FoundLive when this full-metadata entry is a finished, public stream
    worth clipping, else the plain-English reason it is not."""
    status = info.get("live_status")
    if info.get("is_live") or status in _NOT_FINISHED:
        return "Still live, upcoming, or still processing."
    if status != "was_live":
        return "Not a livestream."
    if (info.get("age_limit") or 0) >= 18:
        return "Age-restricted."
    availability = info.get("availability")
    if availability in _RESTRICTED:
        return "Members-only or private."
    started = float(info.get("release_timestamp") or info.get("timestamp") or 0)
    if started and now - started > max_age_hours * 3600:
        return "Older than the search window."
    duration = float(info.get("duration") or 0)
    if duration < min_duration_s:
        return "Shorter than the minimum."
    url = info.get("webpage_url") or info.get("url") or ""
    if not url and info.get("id"):
        url = f"https://www.youtube.com/watch?v={info['id']}"
    if not url:
        return "No link."
    return FoundLive(
        url=url,
        title=info.get("title") or "",
        channel=info.get("channel") or info.get("uploader") or "",
        duration_s=duration,
        view_count=int(info.get("view_count") or 0),
        started_at=started,
    )


def find_top_lives(
    query: str,
    *,
    limit: int = 7,
    platforms: tuple[str, ...] | list[str] = ("youtube",),
    max_age_hours: float = 24,
    min_duration_minutes: float = 30,
    extract: Callable[..., dict | None] | None = None,
    clock: Callable[[], float] = time.time,
) -> list[FoundLive]:
    """The most-viewed finished livestreams about `query`, most viewed first.

    Raises ValueError for an empty query or when no requested platform is
    supported (see the module note). Everything else, a failed search or an
    unreadable entry, yields fewer results, never an exception.

    `extract(url, flat=bool, size=int)` is injectable so tests never touch the
    network."""
    text = (query or "").strip()
    if not text:
        raise ValueError("Say what to look for, such as a game or a topic.")
    wanted = [p.lower() for p in platforms]
    if not any(p in SUPPORTED for p in wanted):
        raise ValueError(
            "Only YouTube is supported for finding top streams: Twitch and Kick have no "
            "category listing that can be read.")
    limit = max(1, min(int(limit), 25))
    if extract is None:
        from sources.vod_finder import _extract as extract

    # Two searches: the topic as typed, and the topic plus "live", which
    # surfaces streams whose titles say so. Merged by video, most viewed first.
    entries: list[dict] = []
    ids: set[str] = set()
    for q in (text, f"{text} live"):
        try:
            listing = extract(search_url(q, max_age_hours), flat=True, size=SEARCH_SIZE) or {}
        except Exception:
            continue
        for e in listing.get("entries") or []:
            key = e and (e.get("id") or e.get("url"))
            if key and key not in ids:
                ids.add(key)
                entries.append(e)
    # The search listing already says which entries were streams. When it
    # does, spend the bounded full looks only on those; an entry that is
    # live right now or upcoming is never a candidate.
    entries = [e for e in entries if e.get("live_status") not in ("is_live", "is_upcoming")]
    if any(e.get("live_status") for e in entries):
        entries = [e for e in entries if e.get("live_status") == "was_live"]

    # Most viewed first, so the bounded number of full looks goes to the
    # streams most likely to make the list. A search entry that does not say
    # its views sorts last rather than being dropped.
    entries.sort(key=lambda e: int(e.get("view_count") or 0), reverse=True)
    now = clock()
    min_s = max(0.0, float(min_duration_minutes)) * 60
    found: list[FoundLive] = []
    seen: set[str] = set()
    for entry in entries[:MAX_CHECKS + limit]:
        if len(found) >= limit * 2 or len(seen) >= MAX_CHECKS:
            break
        target = entry.get("url") or entry.get("webpage_url")
        if not target and entry.get("id"):
            target = f"https://www.youtube.com/watch?v={entry['id']}"
        if not target or target in seen:
            continue
        seen.add(target)
        try:
            info = extract(target, flat=False)
        except Exception:
            continue  # private, removed, age-gated: skip it, keep the rest
        if not info:
            continue
        result = check(info, now=now, max_age_hours=max_age_hours, min_duration_s=min_s)
        if isinstance(result, FoundLive):
            found.append(result)
    found.sort(key=lambda f: f.view_count, reverse=True)
    return found[:limit]
