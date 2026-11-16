"""Face tracking, remembered.

Tracking (video/tracker.py compute_tracking) runs YOLO over the clip's frames,
which on a CPU is most of a render. The editor renders the same clip again and
again: Update preview, then Apply, then another preview after a font change.
None of those change what is in the frame, so the camera path comes out the
same every time, and is worked out again from scratch.

This keeps each result, keyed by what decides it: the exact pixels it ran on
(a hash of the cut clip file) and the tracking settings. A different trim,
speed, colour filter or source gives a different file, so a different key: a
stale path can never be reused. A result that can't be stored as JSON is
simply not kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

# Bump when compute_tracking's output for the same input changes meaning.
VERSION = 1
KEEP = 400            # results kept; the oldest go first
_CHUNK = 1 << 20


def _digest(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def key(clip_path: Path, **settings) -> str:
    """What a tracking result depends on: the clip's bytes and the settings."""
    blob = json.dumps({"v": VERSION, "file": _digest(clip_path), **settings}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def _plain(value):
    """JSON-safe copy (tuples -> lists, numpy scalars -> float/int)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "item") and callable(value.item):   # numpy scalar
        return value.item()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"not storable: {type(value).__name__}")


def _restore(value, key_name: str | None = None):
    """Back to the shapes the renderer reads: the path as (t, x) tuples,
    boxes as tuples."""
    if isinstance(value, dict):
        return {k: _restore(v, k) for k, v in value.items()}
    if isinstance(value, list):
        items = [_restore(v) for v in value]
        if key_name in ("webcam_box", "region") or (items and all(isinstance(i, (int, float)) for i in items)):
            return tuple(items)
        return items
    return value


def load(cache_dir: Path, k: str) -> dict | None:
    f = cache_dir / f"{k}.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        os.utime(f)   # recently used: last to be pruned
    except (OSError, ValueError):
        return None
    return _restore(data) if isinstance(data, dict) else None


def save(cache_dir: Path, k: str, tracking: dict) -> None:
    try:
        text = json.dumps(_plain(tracking))
    except (TypeError, ValueError):
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_dir / f"{k}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, cache_dir / f"{k}.json")
        _prune(cache_dir)
    except OSError:
        pass   # a cache that can't be written costs speed, never a render


def _prune(cache_dir: Path) -> None:
    files = sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in files[: max(0, len(files) - KEEP)]:
        try:
            old.unlink()
        except OSError:
            pass


def tracked(clip_path: Path, cache_dir: Path | None, compute, **settings) -> dict:
    """compute(**settings) for this clip, from the cache when it has run on
    exactly this file with exactly these settings before."""
    if cache_dir is None:
        return compute(**settings)
    try:
        k = key(clip_path, **settings)
    except OSError:
        return compute(**settings)
    hit = load(cache_dir, k)
    if hit is not None:
        print("      Tracking: reused from an earlier render of this clip")
        return hit
    result = compute(**settings)
    save(cache_dir, k, result)
    return result
