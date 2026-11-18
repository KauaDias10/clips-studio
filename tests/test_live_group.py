"""live/group.py: every clip of one live in one video."""

import json
import subprocess

import pytest

from core.binaries import ffmpeg
from live import group


def _piece(path, seconds):
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=d={seconds}", "-c:v", "libx264", "-c:a", "aac", "-shortest",
                    str(path)], check=True)


def test_same_live_within_the_gap_new_one_after(tmp_path):
    a = group.group_for(tmp_path, "alanzoka", now=1_000_000)
    assert group.group_for(tmp_path, "alanzoka", now=1_000_000 + 3600) == a
    group.touch(tmp_path, "alanzoka", a)
    assert group.group_for(tmp_path, "gaules", now=1_000_000) != a
    later = group.group_for(tmp_path, "alanzoka", now=10_000_000_000)
    assert later != a and later.startswith("live_alanzoka_")


def test_transcript_shifted_onto_the_end(tmp_path):
    t = tmp_path / "transcripts"
    t.mkdir()
    (t / "g.json").write_text(json.dumps({"video_id": "g", "language": "pt", "segments": [
        {"start": 1.0, "end": 2.0, "text": "a"}]}), encoding="utf-8")
    (t / "p.json").write_text(json.dumps({"language": "pt", "segments": [
        {"start": 0.5, "end": 1.5, "text": "b", "words": [{"start": 0.5, "end": 1.5, "word": "b"}]}]}),
        encoding="utf-8")
    group.append_transcript(t, "g", "p", 40.0)
    segs = json.loads((t / "g.json").read_text(encoding="utf-8"))["segments"]
    assert [(s["start"], s["text"]) for s in segs] == [(1.0, "a"), (40.5, "b")]
    assert segs[1]["words"][0]["end"] == 41.5
    assert not (t / "p.json").exists()


@pytest.mark.timeout(120)
def test_pieces_join_one_after_another(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "transcripts").mkdir()
    for name, secs in (("p1", 3), ("p2", 2)):
        _piece(tmp_path / "downloads" / f"{name}.mp4", secs)
    assert group.adopt(tmp_path, "g", "p1") == 0.0
    offset = group.adopt(tmp_path, "g", "p2")
    assert 2.9 < offset < 3.2
    assert 4.8 < group.probe_seconds(tmp_path / "downloads" / "g.mp4") < 5.3
    assert not (tmp_path / "downloads" / "p1.mp4").exists()
    assert not (tmp_path / "downloads" / "p2.mp4").exists()
