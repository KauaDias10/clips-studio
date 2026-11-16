"""Hand-placed captions (video/captions.py, custom position) and the
tracking cache the editor's re-renders reuse (video/tracking_cache.py)."""

from core.models import ClipCandidate, Segment
from video import tracking_cache
from video.captions import build_captions


def _style_line(tmp_path, style):
    path = build_captions([Segment(0, 2, "oi tudo bem", None)], ClipCandidate(0, 2, 90),
                          tmp_path / "c.ass", style=style)
    return next(l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Style: Default"))


def test_custom_position_puts_the_caption_bottom_where_dragged(tmp_path):
    line = _style_line(tmp_path, {"position": "custom", "caption_y": 60})
    assert line.split(",")[-5:-1] == ["2", "60", "60", str(round(1920 * 0.4))]
    # Kept on screen, and a junk value falls back.
    assert _style_line(tmp_path, {"position": "custom", "caption_y": 150}).split(",")[-2] == str(round(1920 * 0.02))
    assert _style_line(tmp_path, {"position": "custom", "caption_y": "x"}).split(",")[-2] == str(round(1920 * 0.23))


def test_custom_position_wins_over_the_title_banner_anchor(tmp_path):
    line = _style_line(tmp_path, {"position": "custom", "caption_y": 60, "anchor_y": 800})
    assert line.split(",")[-2] == str(round(1920 * 0.4))


def test_tracking_cache_reuses_only_the_same_frames_and_settings(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"frames-one")
    calls = []

    def compute(**kw):
        calls.append(kw)
        return {"mode": "track", "path": [(0.0, 0.5), (1.0, 0.52)], "face_y": None}

    cache = tmp_path / "cache"
    first = tracking_cache.tracked(clip, cache, compute, sample_fps=8)
    again = tracking_cache.tracked(clip, cache, compute, sample_fps=8)
    assert len(calls) == 1 and again == first
    assert again["path"][1] == (1.0, 0.52)           # back as the renderer reads it
    tracking_cache.tracked(clip, cache, compute, sample_fps=4)     # other settings
    clip.write_bytes(b"frames-two")                                # other frames
    tracking_cache.tracked(clip, cache, compute, sample_fps=8)
    assert len(calls) == 3


def test_tracking_cache_never_breaks_a_render(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    odd = {"mode": "track", "path": [(0.0, 0.5)], "thing": object()}
    out = tracking_cache.tracked(clip, tmp_path / "c", lambda **kw: odd)
    assert out is odd                                  # not storable: just not kept
    assert tracking_cache.tracked(tmp_path / "missing.mp4", tmp_path / "c", lambda **kw: {"m": 1}) == {"m": 1}
    assert tracking_cache.tracked(clip, None, lambda **kw: {"m": 2}) == {"m": 2}
