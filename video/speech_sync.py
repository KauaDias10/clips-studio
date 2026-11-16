"""Captions on the beat of the voice.

Whisper's word timestamps run EARLY where speech starts again after a pause:
the start of the first word is pulled back into the quiet before it, by a
few tenths of a second. On screen the caption then shows up before the
person opens their mouth, which reads as out of sync.

The audio says where the quiet really is (FFmpeg's silencedetect, as
analysis/tighten.py uses it). A word that starts inside a quiet stretch is
moved to where the quiet ends, never past the word's own end. Where no quiet
can be heard (music under the voice, a noisy room) nothing moves: the
timings stay exactly as Whisper gave them.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from pathlib import Path

from core.binaries import ffmpeg
from core.models import Segment

NOISE_DB = -32      # quieter than this is not speech
MIN_QUIET = 0.2     # a pause shorter than this is the gap between two words
MIN_LEFT = 0.06     # a word keeps at least this much of itself on screen


def quiet_spans(source: Path, start: float, end: float) -> list[tuple[float, float]]:
    """Quiet stretches between `start` and `end` of the source, in source
    seconds. Empty when FFmpeg can't tell (or isn't there)."""
    duration = max(0.0, end - start)
    if duration <= 0:
        return []
    cmd = [
        ffmpeg(), "-hide_banner", "-nostats",
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}",
        "-i", str(Path(source).resolve()), "-vn",
        # Speech lives above ~200 Hz; rumble and hum below it would hide the quiet.
        "-af", f"highpass=f=200,silencedetect=noise={NOISE_DB}dB:d={MIN_QUIET:g}",
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
        )
    except Exception:
        return []
    return parse(r.stderr or "", offset=start, length=duration)


def parse(log: str, offset: float = 0.0, length: float = float("inf")) -> list[tuple[float, float]]:
    """silencedetect's log as (start, end) pairs, shifted by `offset`."""
    out: list[tuple[float, float]] = []
    began = None
    for m in re.finditer(r"silence_(start|end):\s*(-?[\d.]+)", log):
        kind, value = m.group(1), float(m.group(2))
        if kind == "start":
            began = max(0.0, value)
        elif began is not None:
            out.append((offset + began, offset + value))
            began = None
    if began is not None:   # quiet to the end of the stretch
        out.append((offset + began, offset + length))
    return out


def snap(t: float, until: float, quiet: list[tuple[float, float]]) -> float:
    """`t` moved out of the quiet it falls in, to where the voice starts —
    as long as that leaves something before `until`."""
    for a, b in quiet:
        if a <= t < b:
            return b if b <= until - MIN_LEFT else t
    return t


def snap_segments(segments: list[Segment], quiet: list[tuple[float, float]]) -> list[Segment]:
    """The segments with every word that starts in a quiet stretch moved to
    where it is actually said. The originals are left as they are."""
    if not quiet:
        return segments
    out = []
    for seg in segments:
        if not seg.words:
            out.append(seg)
            continue
        words = [
            {**w, "start": snap(float(w["start"]), float(w["end"]), quiet)}
            for w in seg.words
        ]
        out.append(replace(seg, words=words))
    return out


def snap_lines(lines: list[dict] | None, quiet: list[tuple[float, float]]) -> list[dict] | None:
    """Caption lines (clip seconds) whose start is in a quiet stretch (clip
    seconds) start where the voice does. For lines a person saved: their
    words and grouping stay theirs, only the late start is fixed."""
    if not lines or not quiet:
        return lines
    out = []
    for line in lines:
        try:
            start, end = float(line["start"]), float(line["end"])
        except (KeyError, TypeError, ValueError):
            out.append(line)
            continue
        moved = snap(start, end, quiet)
        out.append({**line, "start": round(moved, 2)} if moved != start else line)
    return out
