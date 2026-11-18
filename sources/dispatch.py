"""Source dispatcher: route any pasted URL to the right platform module.

Adding a platform means one new source module and one branch here — nothing
downstream changes, because every source returns the same DownloadedVideo
and uses ids that can't collide (YouTube: 11-char, Twitch: tw_, Kick: kick_).
"""

from pathlib import Path

from core.models import DownloadedVideo
from sources import kick, twitch, youtube, ytdlp_common


def identify(url: str) -> tuple[str, str | None]:
    """(source_name, video_id) — video_id is None when the URL doesn't
    contain a recognizable video (e.g. a live-channel page)."""
    if url.startswith("local:"):
        # Uploaded file: "local:<video_id>". The file was already placed in
        # downloads/ by the upload endpoint — there is nothing to fetch.
        return "local", url.split(":", 1)[1]
    if twitch.is_twitch_url(url):
        return "twitch", twitch.extract_clip_id(url) or twitch.extract_vod_id(url)
    if kick.is_kick_url(url):
        return "kick", kick.extract_vod_id(url)
    return "youtube", youtube.extract_video_id(url)


# Hosts of the platforms a downloaded live's original link can point to. Only
# for recording where a file came from; nothing is fetched from them.
_PLATFORM_HOSTS = (
    ("youtube", ("youtube.com", "youtu.be")),
    ("twitch", ("twitch.tv",)),
    ("kick", ("kick.com",)),
    ("instagram", ("instagram.com",)),
    ("tiktok", ("tiktok.com",)),
)


def platform_of_link(url: str) -> str:
    """The platform an original link belongs to: youtube, twitch, kick,
    instagram, tiktok, or "other". Blank for anything that isn't a web link."""
    from urllib.parse import urlsplit

    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    for platform, domains in _PLATFORM_HOSTS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    return "other"


def _clear_stale_partials(output_dir: Path, video_id: str | None) -> None:
    """Remove leftover .part fragments from an earlier failed download of this
    video before starting a new one.

    A download that dies partway (a 403, a dropped connection) leaves yt-dlp
    .part / .part-Frag files — the 900 MB video stream can be most of the way
    done. yt-dlp cannot resume them: the platform's fragment URLs expire in
    hours, so the next attempt restarts from zero regardless and just orphans
    the old partial, which then sits on disk until a manual cleanup. Clearing
    them here means a re-download reclaims that space instead of doubling it.
    """
    if not video_id or not output_dir.is_dir():
        return
    for f in output_dir.iterdir():
        if not f.is_file() or not f.name.startswith(video_id):
            continue
        if f.suffix in (".part", ".ytdl") or ".part-Frag" in f.name:
            try:
                f.unlink()
            except OSError:
                pass  # locked or already gone — never block the download


def game_info(url: str) -> list[dict]:
    """The game(s) a video shows, from the platform, without downloading it
    (sources.ytdlp_common.games_from_info). For a cached file from before the
    games were recorded; empty for a local upload or on any failure."""
    source, _ = identify(url)
    if source == "local":
        return []
    try:
        from sources.ytdlp_common import extract_info, games_from_info

        info = extract_info(url, {"quiet": True, "no_warnings": True, "skip_download": True})
        return games_from_info(info, source)
    except Exception as e:
        print(f"      (could not ask the platform which game it is: {e})")
        return []


def description(url: str) -> str:
    """The video's own description, without downloading it, or "" (a local
    upload, offline, rate-limited). Only a download brings it
    (sources/youtube.py), so a job whose file was already on disk asks for it
    here when its sport reads it (basketball: the players' names, and who
    won)."""
    source, _ = identify(url)
    if source == "local":
        return ""
    try:
        from sources.ytdlp_common import extract_info

        info = extract_info(url, {"quiet": True, "no_warnings": True, "skip_download": True})
        return str(info.get("description") or "")
    except Exception as e:
        print(f"      (could not fetch the video's description: {e})")
        return ""


def metadata(url: str) -> tuple[str, str]:
    """(title, channel) for a URL, without downloading the video.

    For the case where the source file is already on disk but nothing is known
    about it — a database that was reset or moved, or a file copied into
    downloads/ by hand. Without this the title falls back to the raw video ID
    and the channel to an empty string, and an empty channel means the video is
    attached to no creator, so catchphrase learning and preference history
    never run on it.

    One metadata request rather than re-fetching several GB. Raises on failure
    rather than returning empty strings, so the caller can decide whether being
    offline is fatal — in the cached path it is not, and the ID is still a
    usable fallback.
    """
    source, _ = identify(url)
    if source == "local":
        # An imported file has no platform to ask; whatever the user typed at
        # import is all there ever was.
        raise ValueError("local uploads carry no remote metadata")

    from sources.ytdlp_common import extract_info

    info = extract_info(url, {"quiet": True, "no_warnings": True, "skip_download": True})

    return (
        info.get("title") or "",
        info.get("channel") or info.get("uploader") or "",
    )


def download(url: str, output_dir: Path, vertical: bool = False) -> DownloadedVideo:
    """`vertical`: the vertical version only, for Vertical Live. Files are
    imported as they are, so it makes no difference to them."""
    source, video_id = identify(url)
    if source == "local":
        # Only reachable if the imported copy in downloads/ was deleted.
        raise ValueError(
            "The uploaded video's imported copy is gone — upload the file again."
        )
    _clear_stale_partials(output_dir, video_id)
    try:
        if source == "twitch":
            return twitch.download(url, output_dir, vertical=vertical)
        if source == "kick":
            return kick.download(url, output_dir, vertical=vertical)
        return youtube.download(url, output_dir, vertical=vertical)
    except Exception as e:
        # Every platform's download passes through here, so the yt-dlp version
        # travels with the failure from one place rather than three.
        # `ytdlp_common.failure_note` decides when it belongs (it is left off
        # cancellations and off the failures the sources already explain).
        #
        # The exception is re-raised, not replaced: only its message grows, so
        # callers catching DownloadError, ValueError or Exception still do, and
        # the traceback still points at the platform that failed.
        note = ytdlp_common.failure_note(e)
        if note:
            e.args = (f"{e}\n\n{note}",)
        raise


# ---- audio first --------------------------------------------------------
#
# For a long remote video the pipeline downloads the audio, picks the moments
# from it, and then downloads only those ranges (core/pipeline.py). The
# decision, the probe it needs and the downloads live here, next to download().

AUDIO_FIRST_MODES = ("auto", "on", "off")
AUDIO_FIRST_MIN_MINUTES = 90.0
# Audio and section files are scratch: kept in their own folder, so they are
# never taken for the finished source file (core.paths.cached_source only reads
# files directly inside downloads/).
AUDIO_FIRST_DIR = "_audio_first"


def audio_first_mode(config: dict | None) -> str:
    """`download.audio_first` as "auto", "on" or "off". Anything else (a typo,
    a YAML true/false) is read as it was meant where that is clear, and as
    "auto" otherwise; a config with no such key is "auto"."""
    value = ((config or {}).get("download") or {}).get("audio_first", "auto")
    if value is True:
        return "on"
    if value is False:
        return "off"
    value = str(value).strip().lower()
    if value in ("true", "yes", "1"):
        return "on"
    if value in ("false", "no", "0"):
        return "off"
    return value if value in AUDIO_FIRST_MODES else "auto"


def audio_first_min_seconds(config: dict | None) -> float:
    """`download.audio_first_min_minutes` in seconds (default 90)."""
    raw = ((config or {}).get("download") or {}).get("audio_first_min_minutes", AUDIO_FIRST_MIN_MINUTES)
    try:
        minutes = float(raw)
    except (TypeError, ValueError):
        minutes = AUDIO_FIRST_MIN_MINUTES
    return max(0.0, minutes) * 60.0


def wants_audio_first(config: dict | None, source: str, duration: float | None) -> bool:
    """Whether this remote video is fetched audio first: never off, never a
    local file; "on" for any remote video; "auto" only when the platform's
    metadata gave a length and it is over the threshold (without a length
    there is nothing to say it is long, so it is downloaded as always)."""
    mode = audio_first_mode(config)
    if mode == "off" or source == "local":
        return False
    if mode == "on":
        return True
    return bool(duration) and float(duration) > audio_first_min_seconds(config)


# What the audio-first path cannot serve, as the job's own option names (the
# config's `clips` section and the queued job's payload use the same ones).
# Each reads the picture of the whole video, or hands it to something else:
# a whole-video clip, a plugin's pipeline or steps, a match (its scoreboard and
# its look at the frames), a stream already vertical, and Longform.
_NEEDS_THE_VIDEO = {
    "whole": "the whole video is the clip",
    "longform": "Longform cuts the whole video",
    "pipeline": "a plugin pipeline reads the video",
    "rate": "a plugin step reads the video",
    "understand": "a plugin step reads the video",
    "edit": "a plugin step reads the video",
    "sport": "a match is read from its picture",
    "vertical_live": "a Vertical Live keeps the whole stream",
}


def audio_first_blocker(options: dict | None) -> str | None:
    """Why a job cannot be fetched audio first (a sentence for the log), or
    None when it can. `options` is the config's `clips` section or a job
    payload."""
    for key, why in _NEEDS_THE_VIDEO.items():
        if (options or {}).get(key):
            return why
    return None


def scratch_dir(output_dir: Path, video_id: str) -> Path:
    """Where a video's audio and section files go while a job runs."""
    return output_dir / AUDIO_FIRST_DIR / video_id


def probe(url: str) -> dict:
    """What the platform says about a remote video, without downloading:
    {"duration", "is_live", "title", "channel"}. Raises like download() when
    the video is gone or the link is wrong."""
    source, _ = identify(url)
    if source == "local":
        raise ValueError("local uploads carry no remote metadata")
    try:
        if source == "kick":
            info, _web = kick.probe(url)
        else:
            from sources.ytdlp_common import extract_info

            opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            if source == "youtube":
                with youtube._friendly_errors():
                    info = extract_info(url, opts)
            else:
                info = extract_info(url, opts)
    except Exception as e:
        note = ytdlp_common.failure_note(e)
        if note:
            e.args = (f"{e}\n\n{note}",)
        raise
    return {
        "duration": float(info.get("duration") or 0),
        "is_live": bool(info.get("is_live")),
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "games": ytdlp_common.games_from_info(info, source),
        "description": str(info.get("description") or ""),
    }


def download_audio(url: str, output_dir: Path) -> Path:
    """Only the audio of a remote video, as a file in `output_dir`: the first
    step of the audio-first path. Same error handling as download()."""
    source, _ = identify(url)
    if source == "local":
        raise ValueError("A local file has nothing to download.")
    try:
        if source == "twitch":
            return twitch.download_audio(url, output_dir)
        if source == "kick":
            return kick.download_audio(url, output_dir)
        return youtube.download_audio(url, output_dir)
    except Exception as e:
        note = ytdlp_common.failure_note(e)
        if note:
            e.args = (f"{e}\n\n{note}",)
        raise


def download_sections(url: str, ranges: list[tuple[float, float]], output_dir: Path,
                      vertical: bool = False) -> list[ytdlp_common.Section]:
    """Only these [start, end] ranges (seconds into the whole video) of a
    remote video, one file per range, as Sections that record where each
    starts in the whole. Raises when a platform cannot do it, and the caller
    downloads the whole video instead. YouTube, Twitch VODs and Kick VODs do
    it (yt-dlp download_ranges); a local file and a viewer clip do not."""
    source, _ = identify(url)
    if source == "local":
        raise ValueError("A local file has nothing to download.")
    try:
        if source == "twitch":
            return twitch.download_sections(url, ranges, output_dir, vertical=vertical)
        if source == "kick":
            return kick.download_sections(url, ranges, output_dir, vertical=vertical)
        return youtube.download_sections(url, ranges, output_dir, vertical=vertical)
    except Exception as e:
        note = ytdlp_common.failure_note(e)
        if note:
            e.args = (f"{e}\n\n{note}",)
        raise
