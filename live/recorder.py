"""The last few minutes of a live stream, kept on disk as short segments.

ffmpeg copies the stream (no re-encode, almost no CPU) into numbered
MPEG-TS segments; each segment's wall-clock start is noted as it appears, so
a moment chat dated at 21:14:03 is cut from the right seconds. Older
segments are deleted, so a stream left running all night uses a few hundred
MB, not gigabytes.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.binaries import ffmpeg as ffmpeg_path

SEGMENT_SECONDS = 4
# ffmpeg can stay open and stop writing (an ad break or a stream switch on
# Twitch's side): when nothing grows for this long it is restarted.
STALL_SECONDS = 20
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class Segment:
    path: Path
    start: float      # wall clock, seconds since the epoch
    seconds: float = SEGMENT_SECONDS


def stream_url(page_url: str, height: int = 720) -> tuple[list[str], str, str]:
    """The live HLS address(es) for a channel page, via yt-dlp (the one
    dependency that keeps up with Twitch / Kick / YouTube changes): one muxed
    stream, or YouTube's video and audio apart. Also the stream's title and
    the platform's id of the live."""
    import re

    from sources.ytdlp_common import extract_info

    opts = {"quiet": True, "no_warnings": True,
            "format": f"b[height<={height}]/bv*[height<={height}]+ba/b/bv*+ba"}
    if "kick.com" in page_url:
        from sources.kick import _impersonation

        opts.update(_impersonation())
    info = extract_info(page_url, opts)
    if not info.get("is_live", True):
        raise RuntimeError("This channel is not live right now.")
    parts = info.get("requested_formats") or [info]
    urls = [f.get("url") for f in parts if f.get("url")]
    if not urls:
        raise RuntimeError("Could not find the live video address.")
    if "twitch.tv" in page_url:
        title = info.get("description") or info.get("title") or ""   # Twitch's title is the description
    else:
        # yt-dlp dates a live's title ("… 2026-11-18 14:02"): not part of it.
        title = re.sub(r"\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", "", info.get("title") or "")
    return urls, title.strip(), info.get("id") or ""


class Recorder:
    def __init__(self, page_url: str, work_dir: Path, keep_seconds: int = 600, height: int = 720):
        self.page_url = page_url
        self.dir = Path(work_dir)
        self.keep_seconds = keep_seconds
        self.height = height
        self.segments: list[Segment] = []
        self.error = ""
        self.recording = False
        self.title = ""
        self.video_id = ""   # the platform's id of the live (YouTube: its video)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._run_n = 0

    def start(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._run, name="live-recorder", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    # ---- recording -------------------------------------------------------

    def _run(self) -> None:
        wait = 3.0
        while not self._stop.is_set():
            try:
                self._record_once()
                wait = 3.0
            except Exception as e:  # network, ended stream, yt-dlp change
                self.error = str(e)[:300]
                if "reconnecting" in self.error:
                    wait = 1.0       # a stall: straight back
            self.recording = False
            if self._stop.wait(wait):
                break
            wait = min(wait * 2, 60.0)

    def _record_once(self) -> None:
        urls, self.title, self.video_id = stream_url(self.page_url, self.height)
        self._run_n += 1
        prefix = f"r{self._run_n}_"
        pattern = str(self.dir / f"{prefix}%06d.ts")
        cmd = [
            ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin",
            # Each input reconnects on its own (input options go before each -i).
            *[x for u in urls for x in ("-reconnect", "1", "-reconnect_streamed", "1",
                                        "-reconnect_delay_max", "10", "-i", u)],
            # One input with both, or YouTube's video (0) and audio (1) apart.
            "-map", "0:v:0?", "-map", f"{len(urls) - 1}:a:0?", "-c", "copy",
            "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-segment_format", "mpegts",
            "-reset_timestamps", "1", pattern,
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      creationflags=_NO_WINDOW)
        errors: list[str] = []

        def drain(stream) -> None:   # an unread pipe would block ffmpeg once full
            for raw in iter(stream.readline, b""):
                errors.append(raw.decode("utf-8", "replace").strip())
                del errors[:-20]

        threading.Thread(target=drain, args=(self._proc.stderr,), daemon=True).start()
        self.recording, self.error = True, ""
        seen: set[str] = set()
        number = re.compile(re.escape(prefix) + r"(\d+)\.ts$")
        last_size, last_change = -1, time.time()
        while self._proc.poll() is None and not self._stop.is_set():
            time.sleep(1.0)
            self._collect(prefix, number, seen)
            size = sum(p.stat().st_size for p in self.dir.glob(f"{prefix}*.ts"))
            if size != last_size:
                last_size, last_change = size, time.time()
            elif time.time() - last_change > STALL_SECONDS:
                self._proc.terminate()
                self._collect(prefix, number, seen, final=True)
                raise RuntimeError("The live video stopped arriving; reconnecting.")
        self._collect(prefix, number, seen, final=True)
        if self._proc.returncode not in (0, None) and not self._stop.is_set():
            raise RuntimeError(errors[-1] if errors else f"ffmpeg stopped ({self._proc.returncode})")

    def _collect(self, prefix: str, number, seen: set, final: bool = False) -> None:
        """Segments ffmpeg finished: every file but the one it is writing.
        A segment's start is when ffmpeg opened it, i.e. when the one before
        it was closed: now minus its length, close enough for a 35 s clip."""
        files = sorted(p for p in self.dir.glob(f"{prefix}*.ts") if number.search(p.name))
        done = files if final else files[:-1]
        now = time.time()
        with self._lock:
            for p in done:
                if p.name in seen:
                    continue
                seen.add(p.name)
                start = (self.segments[-1].start + self.segments[-1].seconds
                         if self.segments and self.segments[-1].path.name.startswith(prefix)
                         else now - SEGMENT_SECONDS)
                self.segments.append(Segment(p, start))
            cutoff = now - self.keep_seconds
            while self.segments and self.segments[0].start + self.segments[0].seconds < cutoff:
                self.segments.pop(0).path.unlink(missing_ok=True)

    # ---- reading ---------------------------------------------------------

    def covered_until(self) -> float:
        with self._lock:
            return self.segments[-1].start + self.segments[-1].seconds if self.segments else 0.0

    def extract(self, t0: float, t1: float, out: Path) -> tuple[float, float]:
        """Joins the segments covering wall-clock [t0, t1] into out (an mp4,
        stream-copied). Returns (offset of t0 in it, offset of t1)."""
        with self._lock:
            parts = [s for s in self.segments if s.start + s.seconds > t0 and s.start < t1]
        if not parts:
            raise RuntimeError("Those seconds are no longer in the live buffer.")
        out.parent.mkdir(parents=True, exist_ok=True)
        listing = out.with_suffix(".txt")
        listing.write_text("".join(f"file '{p.path.as_posix()}'\n" for p in parts), encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(out)],
            check=True, creationflags=_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        listing.unlink(missing_ok=True)
        base = parts[0].start
        return max(0.0, t0 - base), max(0.0, t1 - base)

    def cleanup(self) -> None:
        with self._lock:
            for s in self.segments:
                s.path.unlink(missing_ok=True)
            self.segments.clear()
