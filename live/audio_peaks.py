"""Moments from the stream's own sound: the streamer screaming, the crowd
going off. For lives whose chat can't be read (Kick) and as an extra signal
anywhere.

Each recorded segment's loudness is measured every half second. A moment is
a stretch at least RISE_DB louder than the live's usual level (the median of
the last minutes) and above nearly everything heard lately, held for
MIN_SECONDS: one loud bang is not a moment, a few seconds of yelling is.
"""

from __future__ import annotations

import subprocess
from collections import deque

import numpy as np

from live.moments import Moment

STEP = 0.5            # seconds per loudness reading
HISTORY = 300.0       # seconds of readings kept
WARMUP = 60.0         # readings needed before anything counts
RISE_DB = 10.0
MIN_SECONDS = 1.5
RATE = 8000


def levels(path, start: float) -> list[tuple[float, float]]:
    """(wall clock, dBFS) every STEP seconds of a recorded segment."""
    from core.binaries import ffmpeg

    out = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
                          "-f", "s16le", "-"], capture_output=True)
    pcm = np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(RATE * STEP)
    res = []
    for i in range(len(pcm) // n):
        chunk = pcm[i * n:(i + 1) * n]
        rms = float(np.sqrt(np.mean(chunk * chunk)) + 1e-9)
        res.append((start + i * STEP, 20 * np.log10(rms)))
    return res


class AudioPeaks:
    def __init__(self, pre: float = 25.0, post: float = 8.0, rise_db: float = RISE_DB):
        self.pre, self.post, self.rise = pre, post, rise_db
        self.readings: deque = deque()
        self._fed: set[str] = set()
        self._done_until = 0.0

    def feed(self, segment) -> None:
        if segment.path.name in self._fed:
            return
        self._fed.add(segment.path.name)
        self.add(levels(segment.path, segment.start))

    def add(self, readings: list[tuple[float, float]]) -> None:
        self.readings.extend(readings)
        while self.readings and self.readings[-1][0] - self.readings[0][0] > HISTORY:
            self.readings.popleft()

    def detect(self) -> list[Moment]:
        if len(self.readings) < WARMUP / STEP:
            return []
        t = np.array([r[0] for r in self.readings])
        db = np.array([r[1] for r in self.readings])
        audible = db[db > -60]
        if len(audible) < WARMUP / STEP / 2:
            return []           # mostly silence: nothing to compare against
        threshold = max(float(np.median(audible)) + self.rise, float(np.percentile(audible, 97)))
        loud = db >= threshold
        out, i, need = [], 0, int(MIN_SECONDS / STEP)
        while i < len(loud):
            if not loud[i] or t[i] <= self._done_until:
                i += 1
                continue
            j = i
            while j + 1 < len(loud) and (loud[j + 1] or (j + 2 < len(loud) and loud[j + 2])):
                j += 1          # a breath in the middle doesn't end it
            if j == len(loud) - 1:
                break           # still going: read it once it has ended
            if j - i + 1 >= need:
                peak = i + int(np.argmax(db[i:j + 1]))
                at = float(t[peak])
                out.append(Moment(at=at, start=at - self.pre, end=min(max(at, float(t[j])), at + 10) + self.post,
                                  kind="audio", reason=f"Pico de áudio (+{db[peak] - np.median(audible):.0f} dB)",
                                  strength=1.0))
            self._done_until = float(t[j])
            i = j + 1
        return out
