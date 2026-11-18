"""Hot-window selection (analysis/hot_windows.py): heat -> windows, the start
damping, the fallbacks and the mode choice."""

import numpy as np

from analysis import chat_moments, highlights, hot_windows
from core.models import Segment


def _segments(total, step=10):
    return [Segment(start=float(t), end=float(t + step), text=f"line {t}.") for t in range(0, int(total), step)]


def _loudness(n, bursts, level=0.05, loud=0.6):
    x = np.full(n, level, dtype=np.float32)
    for b in bursts:
        x[b:b + 20] = loud
    return x


def test_windows_do_not_overlap_and_are_top_k():
    n = 4 * 3600
    bursts = [600, 3000, 3100, 7000, 11000, 13000]   # 3000 and 3100 are one hot stretch
    heat = hot_windows.heat_curve(n, loud_db=hot_windows.loudness_db(_loudness(n, bursts)))
    wins = hot_windows.pick_windows(heat, n, 150.0, 4)
    assert len(wins) == 4
    assert all(wins[i][1] <= wins[i + 1][0] for i in range(len(wins) - 1))
    assert all(abs((e - s) - 150.0) < 1e-6 for s, e in wins)
    # Every window sits on a burst; the stretch at 3000-3120 is taken once.
    assert all(any(s <= b + 10 <= e for b in bursts) for s, e in wins)
    assert sum(1 for s, e in wins if s <= 3050 <= e) == 1


def test_windows_clamped_inside_the_video():
    n = 1000
    heat = hot_windows.heat_curve(n, loud_db=hot_windows.loudness_db(_loudness(n, [5, 990])))
    for s, e in hot_windows.pick_windows(heat, n, 150.0, 2):
        assert 0.0 <= s and e <= n


def test_start_of_stream_chat_is_damped():
    n = 3600
    ratio = np.ones(n, dtype=np.float32)
    ratio[30:60] = 8.0        # "hi chat"
    ratio[1800:1830] = 8.0    # a real moment
    damped = chat_moments.damp_start(ratio, baseline=1.0)
    assert abs(damped[40] - (1 + 7 * chat_moments.START_DAMP)) < 1e-5
    assert damped[1810] == 8.0
    heat = hot_windows.heat_curve(n, chat_ratio=damped)
    wins = hot_windows.pick_windows(heat, n, 150.0, 1)
    assert wins[0][0] <= 1810 <= wins[0][1]
    # Undamped, the opening wins.
    wins = hot_windows.pick_windows(hot_windows.heat_curve(n, chat_ratio=ratio), n, 150.0, 2)
    assert any(s <= 45 <= e for s, e in wins)


def test_plan_none_without_signals():
    segs = _segments(7200)
    cfg = {"selection": {"hot_windows": "on"}}
    flat = {"loudness": np.full(7200, 0.05, dtype=np.float32)}
    assert hot_windows.plan(segs, cfg, audio_raw=flat) is None
    assert hot_windows.plan(segs, cfg, audio_raw={}) is None
    assert hot_windows.plan(segs, cfg, audio_raw=None, visual=np.zeros(0), audience=None, chat=None) is None


def test_plan_falls_back_when_windows_would_cover_everything():
    segs = _segments(400)
    cfg = {"selection": {"hot_windows": "on", "hot_window_seconds": 200, "hot_window_count": 5}}
    audio = {"loudness": _loudness(400, [50, 300])}
    assert hot_windows.plan(segs, cfg, audio_raw=audio) is None


def test_auto_threshold_and_modes():
    auto = hot_windows.settings({})
    assert auto["mode"] == "auto" and auto["min_minutes"] == 60 and auto["seconds"] == 150 and auto["count"] == 0
    assert not hot_windows.wanted(auto, 59 * 60)
    assert hot_windows.wanted(auto, 61 * 60)
    assert hot_windows.wanted(hot_windows.settings({"selection": {"hot_windows": "on"}}), 600)
    assert not hot_windows.wanted(hot_windows.settings({"selection": {"hot_windows": "off"}}), 10 * 3600)
    assert hot_windows.settings({"selection": {"hot_windows": False}})["mode"] == "off"
    assert hot_windows.settings({"selection": {"hot_windows": "nonsense"}})["mode"] == "auto"
    custom = hot_windows.settings({"selection": {"hot_windows_min_minutes": 20}})
    assert hot_windows.wanted(custom, 25 * 60)


def test_window_count_scales_with_clips():
    opts = hot_windows.settings({})
    assert hot_windows.window_count(opts, 3600, 2) == 12
    assert hot_windows.window_count(opts, 3600, 10) == 30
    assert hot_windows.window_count(hot_windows.settings({"selection": {"hot_window_count": 7}}), 3600, 10) == 7


def test_plan_and_markers_end_to_end():
    n = 4 * 3600
    segs = _segments(n)
    audio = {"loudness": _loudness(n, [5000, 9000])}
    ratio = np.ones(n, dtype=np.float32)
    ratio[9005:9015] = 3.4
    chat = chat_moments.ChatSignal(curve=np.zeros(n, dtype=np.float32), ratio=ratio)
    plan = hot_windows.plan(segs, {}, audio_raw=audio, chat=chat, clips_asked=0)
    assert plan is not None and 2 <= len(plan.windows) <= 20
    assert plan.covered < 0.2 * n
    tag = plan.markers(9005, 9015)
    assert "[LOUD +" in tag and "[CHAT 3.4x]" in tag
    assert plan.markers(100, 110) == ""
    assert "windows" in plan.summary() and "4h00m" in plan.summary()


def test_find_highlights_sends_only_hot_windows():
    n = 4 * 3600
    segs = _segments(n)
    plan = hot_windows.plan(segs, {}, audio_raw={"loudness": _loudness(n, [5000, 9000])})
    prompts = []

    class Fake:
        name = "fake"

        def generate(self, prompt, *a, **k):
            prompts.append(prompt)
            return '{"clips": []}'

    try:
        highlights.find_highlights(segs, Fake(), hot=plan, chunk_seconds=1200)
    except Exception:
        pass   # only what was sent matters here
    assert prompts
    sent = sum(p.count("line ") for p in prompts)
    assert sent < 0.2 * len(segs)
    assert any("[LOUD +" in p for p in prompts)
