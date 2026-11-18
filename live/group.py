"""One video per live: every clip of a broadcast kept together.

Each moment is cut from the live buffer on its own (a few dozen seconds),
rendered, and then *adopted* by the live's video: its seconds are appended
to data/downloads/<group>.mp4, its transcript to the group's transcript
(shifted by where it landed), and the clip is registered under the group at
those shifted times. The editor, re-render, captions and publishing then
see one video, "<stream title> (ao vivo)", with every clip of that live.

A session started again on the same channel within GAP_HOURS of the last
clip joins the same live (the app was restarted, the stream dropped).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

GAP_HOURS = 4.0
_LOCK = threading.Lock()


def _groups_file(data_dir: Path) -> Path:
    return Path(data_dir) / "live" / "groups.json"


def _read(data_dir: Path) -> dict:
    try:
        return json.loads(_groups_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data_dir: Path, groups: dict) -> None:
    f = _groups_file(data_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(groups, indent=1), encoding="utf-8")


def group_for(data_dir: Path, channel: str, now: float | None = None) -> str:
    """The video this channel's clips go into: the last one when it was used
    less than GAP_HOURS ago, else a new one named for now."""
    now = time.time() if now is None else now
    with _LOCK:
        groups = _read(data_dir)
        g = groups.get(channel)
        if g and now - float(g.get("last", 0)) < GAP_HOURS * 3600:
            return g["id"]
        gid = f"live_{channel}_{datetime.fromtimestamp(now).strftime('%Y%m%d_%H%M%S')}"
        groups[channel] = {"id": gid, "last": now}
        _write(data_dir, groups)
        return gid


def touch(data_dir: Path, channel: str, gid: str) -> None:
    with _LOCK:
        groups = _read(data_dir)
        groups[channel] = {"id": gid, "last": time.time()}
        _write(data_dir, groups)


def probe_seconds(path: Path) -> float:
    from core.binaries import ffprobe

    out = subprocess.run([ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _replace(src: Path, dst: Path, tries: int = 20) -> None:
    """os.replace, waiting a little while something (a preview) has dst open."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


def append_video(group_file: Path, piece: Path) -> float:
    """Put piece's seconds at the end of group_file. Returns where they start
    in it. The pieces all come from one stream, so a stream copy joins them."""
    if not group_file.exists():
        _replace(piece, group_file)
        return 0.0
    from core.binaries import ffmpeg

    offset = probe_seconds(group_file)
    tmp = group_file.with_name(group_file.stem + ".joining.mp4")
    lst = group_file.with_name(group_file.stem + ".joining.txt")
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in (group_file, piece)), encoding="utf-8")
    try:
        r = subprocess.run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
        if r.returncode != 0 or not tmp.exists():
            raise RuntimeError(f"Joining the live's seconds failed: {r.stderr.strip()[-300:]}")
        _replace(tmp, group_file)
    finally:
        lst.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    piece.unlink(missing_ok=True)
    return offset


def _shift(seg: dict, by: float) -> dict:
    out = {**seg, "start": round(seg["start"] + by, 3), "end": round(seg["end"] + by, 3)}
    if seg.get("words"):
        out["words"] = [{**w, "start": round(w["start"] + by, 3), "end": round(w["end"] + by, 3)}
                        for w in seg["words"]]
    return out


def append_transcript(transcripts: Path, gid: str, piece_id: str, offset: float) -> None:
    """The piece's transcript, shifted to where its seconds landed, at the
    end of the group's; the piece's own file goes."""
    piece_file = transcripts / f"{piece_id}.json"
    group_file = transcripts / f"{gid}.json"
    try:
        piece = json.loads(piece_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        piece = {"segments": []}
    try:
        group = json.loads(group_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        group = {"video_id": gid, "language": piece.get("language"), "segments": []}
    group["segments"] = [s for s in group.get("segments", []) if s["end"] <= offset + 0.01]
    group["segments"] += [_shift(s, offset) for s in piece.get("segments", [])]
    group.setdefault("language", piece.get("language"))
    group_file.write_text(json.dumps(group, ensure_ascii=False), encoding="utf-8")
    if piece_file.resolve() != group_file.resolve():
        piece_file.unlink(missing_ok=True)


def adopt(data_dir: Path, gid: str, piece_id: str) -> float:
    """Move a rendered piece's seconds and transcript into the live's video.
    Returns the offset to add to the piece's clip times."""
    data_dir = Path(data_dir)
    with _LOCK:
        offset = append_video(data_dir / "downloads" / f"{gid}.mp4", data_dir / "downloads" / f"{piece_id}.mp4")
        append_transcript(data_dir / "transcripts", gid, piece_id, offset)
    return offset
