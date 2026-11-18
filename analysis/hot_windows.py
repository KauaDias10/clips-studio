"""Hot-window selection: send the model only the stretches worth reading.

On a 4-hour stream the model reads the whole transcript chunk by chunk, and a
small local model needs minutes per chunk. Most of that text is the streamer
talking over quiet play. The signals fusion already has (loudness above the
video's own baseline, chat bursts, audience hype, visual activity, laughter
and exclamations in the transcript) say where the moments are, so this builds
one heat value per second, smooths it, and takes the hottest non-overlapping
windows (~150 s each). analysis/highlights.py then sends only those windows'
transcript, each line tagged with why it is hot ([LOUD +11dB], [CHAT 3.4x]).

Settings (config selection:, all optional):
  hot_windows: "auto" (default; on when the video is longer than
               hot_windows_min_minutes) | "on" | "off"
  hot_windows_min_minutes: 60
  hot_window_seconds: 150
  hot_window_count: 0 (auto: max(12, 3 x the clips asked for); with no clip
               count, one window per 15 minutes of video, at least 12)

Never the reason for finding nothing: with no usable signal, or windows that
would cover nearly the whole video anyway, plan() returns None and the caller
reads the full transcript exactly as before.
"""

import re
from dataclasses import dataclass, field

import numpy as np

from analysis import chat_moments
from core.models import Segment

DEFAULT_MIN_MINUTES = 60.0
DEFAULT_WINDOW_SECONDS = 150.0
MIN_COUNT = 12

LOUD_FULL_DB = 12.0       # this far above the video's own level is full loudness heat
LOUD_NOTE_DB = 6.0        # ...and a line is tagged [LOUD] from here
CHAT_FULL_RATIO = 6.0     # chat at this multiple of its normal rate is full chat heat
CHAT_NOTE_RATIO = 2.0     # ...and a line is tagged [CHAT] from here
BASELINE_BLOCK = 300      # seconds per block of the loudness baseline (a stream's level drifts)
HEAT_SMOOTH = 15          # seconds the per-second heat is smoothed over
PEAK_SMOOTH = 30          # seconds a window's centre is judged over
MIN_HEAT = 0.02           # a stretch cooler than this is not hot at all
MAX_COVERAGE = 0.9        # windows covering more of the video than this select nothing

# How far each signal is trusted (combined as independent evidence, like
# fusion._soft_or: agreement raises the heat, a missing signal is just absent).
WEIGHTS = {"loud": 0.8, "chat": 0.9, "audience": 0.6, "visual": 0.4, "audio": 0.3, "text": 0.4}

_LAUGH = re.compile(r"\b(?:ha){2,}|\b(?:he){2,}|\bk{3,}|\b(?:rs){2,}|\blol\b|\blmao\b|\bkek|\bjaja|\bhaha|risos?\b",
                    re.IGNORECASE)
_CAPS_WORD = re.compile(r"\b[A-ZÀ-Ý]{3,}\b")


@dataclass
class HotPlan:
    windows: list                      # [(start, end)] in time order
    loud_db: np.ndarray                # per second, dB above this video's own level
    chat_ratio: np.ndarray             # per second, x the chat's normal rate (start damped); empty if none
    audience: np.ndarray               # per second 0..1 (start damped); empty if none
    covered: float = 0.0               # seconds inside the windows
    duration: float = 0.0
    notes: dict = field(default_factory=dict)

    def markers(self, start: float, end: float) -> str:
        """Compact tags for a transcript line spanning start..end ('' when
        nothing stands out there)."""
        lo, hi = max(int(start), 0), int(end) + 1
        out = []
        db = _peak(self.loud_db, lo, hi)
        if db >= LOUD_NOTE_DB:
            out.append(f"[LOUD +{db:.0f}dB]")
        ratio = _peak(self.chat_ratio, lo, hi)
        if ratio >= CHAT_NOTE_RATIO:
            out.append(f"[CHAT {ratio:.1f}x]")
        elif self.chat_ratio.size == 0:
            top = _peak(self.audience, lo, hi)
            if top >= 0.9:
                out.append(f"[AUDIENCE top {max(1.0, (1.0 - top) * 100):.0f}%]")
        return " ".join(out)

    def summary(self) -> str:
        return (f"Hot-window selection: {len(self.windows)} windows "
                f"({_hms(self.covered)} of {_hms(self.duration)}) sent to the model")


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{max(s // 60, 1 if s else 0)} min"


def _peak(x: np.ndarray, lo: int, hi: int) -> float:
    if x.size == 0 or lo >= x.size:
        return 0.0
    return float(x[lo:min(hi, x.size)].max())


# ---- settings ---------------------------------------------------------------


def settings(config) -> dict:
    """selection.* from a run's settings, each with its default when absent or
    unreadable (config/settings.yaml may not list them)."""
    cfg = (config or {}).get("selection") if isinstance(config, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}

    def num(key, default, low):
        try:
            v = float(cfg.get(key, default))
            return v if v >= low else default
        except (TypeError, ValueError):
            return default

    mode = cfg.get("hot_windows", "auto")
    if mode is True:
        mode = "on"
    elif mode is False:   # YAML turns a bare off / on into a boolean
        mode = "off"
    mode = str(mode).strip().lower()
    if mode not in ("auto", "on", "off"):
        mode = "auto"
    return {
        "mode": mode,
        "min_minutes": num("hot_windows_min_minutes", DEFAULT_MIN_MINUTES, 0.0),
        "seconds": num("hot_window_seconds", DEFAULT_WINDOW_SECONDS, 30.0),
        "count": int(num("hot_window_count", 0, 0)),
    }


def wanted(opts: dict, duration: float) -> bool:
    """Whether this video gets hot-window selection: "on" always, "off" never,
    "auto" when it is longer than min_minutes."""
    if opts["mode"] == "off":
        return False
    if opts["mode"] == "on":
        return True
    return duration > opts["min_minutes"] * 60.0


def window_count(opts: dict, duration: float, clips_asked: int = 0) -> int:
    if opts["count"] > 0:
        return opts["count"]
    if clips_asked > 0:
        return max(MIN_COUNT, 3 * clips_asked)
    return max(MIN_COUNT, int(duration // 900))


# ---- the heat curve ---------------------------------------------------------


def _box(x: np.ndarray, width: int) -> np.ndarray:
    """Moving average over `width` seconds (edges average what exists)."""
    if x.size == 0 or width <= 1:
        return x.astype(np.float32, copy=True)
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    idx = np.arange(x.size)
    lo = np.maximum(idx - width // 2, 0)
    hi = np.minimum(idx + width // 2 + 1, x.size)
    return ((c[hi] - c[lo]) / (hi - lo)).astype(np.float32)


def loudness_db(loudness: np.ndarray) -> np.ndarray:
    """dB each second sits above this video's own level (the median of its
    block, so a stream whose volume drifts is judged against where it is);
    0 at or below it."""
    if loudness is None or np.size(loudness) == 0:
        return np.zeros(0, dtype=np.float32)
    x = _box(np.asarray(loudness, dtype=np.float32), 3)
    n = x.size
    centres, levels = [], []
    for lo in range(0, n, BASELINE_BLOCK):
        block = x[lo:lo + BASELINE_BLOCK]
        audible = block[block > 1e-6]
        if audible.size:
            centres.append(lo + block.size / 2)
            levels.append(float(np.median(audible)))
    if not levels:
        return np.zeros(n, dtype=np.float32)
    base = np.interp(np.arange(n), centres, levels)
    db = 20.0 * np.log10(np.maximum(x, 1e-6) / np.maximum(base, 1e-6))
    return np.clip(db, 0.0, 40.0).astype(np.float32)


def text_heat(segments: list[Segment], n: int) -> np.ndarray:
    """Laughter and exclamations in what is said, per second: "hahaha", "kkkk",
    "!", SHOUTED words. Capped per line so one long rant doesn't read as a moment."""
    out = np.zeros(n, dtype=np.float32)
    for s in segments:
        text = s.text or ""
        score = (0.5 * min(len(_LAUGH.findall(text)), 2)
                 + 0.2 * min(text.count("!"), 3)
                 + 0.2 * min(len(_CAPS_WORD.findall(text)), 2))
        if score <= 0:
            continue
        lo, hi = max(int(s.start), 0), min(int(s.end) + 1, n)
        if hi > lo:
            out[lo:hi] = np.maximum(out[lo:hi], min(score, 1.0))
    return out


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(n, dtype=np.float32)
    k = min(n, np.size(x))
    if k:
        out[:k] = np.asarray(x, dtype=np.float32)[:k]
    return out


def heat_curve(n: int, *, loud_db=None, chat_ratio=None, audience=None, visual=None,
               audio=None, text=None) -> np.ndarray:
    """One 0..1 value per second from whichever signals exist, smoothed.
    chat_ratio and audience are expected with the start already damped."""
    parts = []

    def add(name, sig):
        if sig is not None and np.size(sig):
            parts.append((_fit(np.clip(sig, 0.0, 1.0), n), WEIGHTS[name]))

    if loud_db is not None and np.size(loud_db):
        add("loud", np.asarray(loud_db) / LOUD_FULL_DB)
    if chat_ratio is not None and np.size(chat_ratio):
        add("chat", (np.asarray(chat_ratio) - 1.0) / (CHAT_FULL_RATIO - 1.0))
    if audience is not None and np.size(audience):
        add("audience", (np.asarray(audience) - 0.7) / 0.3)       # a 0..1 percentile: only its top stands out
    if visual is not None and np.size(visual):
        add("visual", (np.asarray(visual) - 0.8) / 0.2)
    if audio is not None and np.size(audio):
        add("audio", (np.asarray(audio) - 0.8) / 0.2)
    if text is not None and np.size(text):
        add("text", text)
    if not parts or n <= 0:
        return np.zeros(max(n, 0), dtype=np.float32)
    miss = np.ones(n, dtype=np.float32)
    for sig, w in parts:
        miss *= 1.0 - w * sig
    return _box(1.0 - miss, HEAT_SMOOTH)


def pick_windows(heat: np.ndarray, duration: float, seconds: float, count: int) -> list[tuple[float, float]]:
    """The `count` hottest non-overlapping windows of `seconds` each, in time
    order. Each is centred on the peak of the heat (smoothed over PEAK_SMOOTH)
    that no earlier pick covers, then clamped inside the video."""
    n = heat.size
    if n == 0 or count <= 0 or duration <= 0:
        return []
    seconds = min(seconds, duration)
    score = _box(heat, PEAK_SMOOTH)
    score[score < MIN_HEAT] = 0.0
    picked: list[tuple[float, float]] = []
    while len(picked) < count:
        centre = int(np.argmax(score))
        if score[centre] <= 0.0:
            break
        start = min(max(0.0, centre - seconds / 2), max(0.0, duration - seconds))
        end = min(duration, start + seconds)
        if any(start < e and end > s for s, e in picked):
            # Clamping at an edge pulled it onto a pick: this centre is spent.
            score[max(0, centre - int(seconds / 2)):centre + int(seconds / 2) + 1] = 0.0
            continue
        picked.append((float(start), float(end)))
        score[max(0, int(start)):min(n, int(end) + 1)] = 0.0
    return sorted(picked)


# ---- the plan ---------------------------------------------------------------


def plan(segments: list[Segment], config, *, audio_raw: dict | None = None, visual=None,
         audio=None, audience=None, chat=None, clips_asked: int = 0,
         duration: float | None = None) -> HotPlan | None:
    """The windows to send, or None to read the whole transcript as before:
    off, a video too short for "auto", no usable signal, or windows that would
    cover nearly all of it anyway."""
    opts = settings(config)
    if not segments:
        return None
    duration = float(duration or segments[-1].end)
    if not wanted(opts, duration):
        return None
    n = int(duration) + 1

    db = loudness_db((audio_raw or {}).get("loudness"))
    ratio = np.zeros(0, dtype=np.float32)
    if chat is not None and getattr(chat, "ratio", None) is not None and np.size(chat.ratio):
        ratio = chat_moments.damp_start(chat.ratio, baseline=1.0)
    aud = np.zeros(0, dtype=np.float32)
    if audience is not None and np.size(audience):
        aud = chat_moments.damp_start(audience)
    heat = heat_curve(n, loud_db=db, chat_ratio=ratio, audience=aud, visual=visual, audio=audio,
                      text=text_heat(segments, n))
    # Transcript-only heat (laughter, "!") is a weak guide on its own, but
    # still a signal; none at all means there is nothing to select by.
    if heat.size == 0 or float(heat.max()) < MIN_HEAT:
        return None

    seconds = opts["seconds"]
    windows = pick_windows(heat, duration, seconds, window_count(opts, duration, clips_asked))
    covered = sum(e - s for s, e in windows)
    if not windows or covered >= MAX_COVERAGE * duration:
        return None
    return HotPlan(windows=windows, loud_db=db, chat_ratio=ratio, audience=aud,
                   covered=covered, duration=duration)
