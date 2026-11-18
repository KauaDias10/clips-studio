"""Audio first: a long remote video's audio is fetched and analysed, then only
the chosen clips' ranges are downloaded.

yt-dlp and FFmpeg are replaced throughout: these tests check the planning
(ranges, offsets, when it applies), the fallbacks, and what each platform asks
yt-dlp for, never a real download.
"""

import json
import threading
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

pytest.importorskip("yt_dlp")

from core import cancel, pipeline
from core.models import ClipCandidate, Segment
from sources import dispatch, kick, twitch, youtube, ytdlp_common
from sources.ytdlp_common import Section, pad_and_merge

LONG = 3 * 3600.0
YT = "https://www.youtube.com/watch?v=abcdefghijk"
TW = "https://www.twitch.tv/videos/123456789"


# ---- ranges ---------------------------------------------------------------

def test_every_range_is_padded_and_clamped_to_the_video():
    assert pad_and_merge([(100, 130)], duration=1000) == [(92.0, 138.0)]
    assert pad_and_merge([(3, 20)], duration=25) == [(0.0, 25.0)]
    assert pad_and_merge([(3, 20)]) == [(0.0, 28.0)]  # length unknown: no end clamp


def test_overlapping_and_close_ranges_become_one_section():
    got = pad_and_merge([(100, 130), (125, 160), (170, 200), (1000, 1030)], duration=5000)
    # the first three touch once padded (and 10 s apart is under the merge gap)
    assert got == [(92.0, 208.0), (992.0, 1038.0)]


def test_unordered_input_is_sorted_and_a_long_chain_is_not_one_giant_file():
    assert pad_and_merge([(1000, 1030), (100, 130)], duration=5000) == [(92.0, 138.0), (992.0, 1038.0)]
    chain = [(i * 60.0, i * 60.0 + 50) for i in range(60)]   # an hour of back-to-back clips
    parts = pad_and_merge(chain, duration=LONG)
    assert len(parts) > 1
    assert all(hi - lo <= ytdlp_common.SECTION_MAX_SECONDS + 1 for lo, hi in parts)


# ---- time mapping ---------------------------------------------------------

def test_a_section_maps_whole_video_times_into_its_own_file():
    sec = Section(Path("s.mp4"), start=992.0, end=1038.0)
    assert sec.covers(1000, 1030.4)
    assert not sec.covers(980, 1030)
    c = ClipCandidate(1000.0, 1030.0, 80, hook="h")
    local = pipeline._shifted(c, sec.start)
    assert (local.start, local.end) == (8.0, 38.0) and local.hook == "h"
    assert (c.start, c.end) == (1000.0, 1030.0)   # the real candidate is never moved


def test_the_transcript_is_shifted_with_its_words_and_trimmed_to_the_clip():
    segs = [
        Segment(0, 5, "far before"),
        Segment(995, 1000, "just before", [{"start": 995.0, "end": 996.0, "word": "just"}]),
        Segment(1001, 1010, "inside", [{"start": 1001.5, "end": 1002.0, "word": "inside"}]),
        Segment(9000, 9005, "far after"),
    ]
    got = pipeline._shift_segments(segs, 992.0, 985.0, 1045.0)
    assert [s.text for s in got] == ["just before", "inside"]
    assert (got[1].start, got[1].end) == (9.0, 18.0)
    assert got[1].words == [{"start": 9.5, "end": 10.0, "word": "inside"}]
    assert segs[2].start == 1001   # the shared transcript is not changed


def test_a_clip_is_cut_from_its_section_at_shifted_time_and_named_by_the_whole_video(monkeypatch, tmp_path):
    seen = {}

    def fake_render(source, candidate, segments, clip_dir, config, opts, lang, name_times=None):
        seen.update(source=source, candidate=candidate, segments=segments, name_times=name_times)
        return clip_dir / "x.mp4", ""

    monkeypatch.setattr(pipeline, "_render_files", fake_render)
    sections = [Section(Path("a.mp4"), 0.0, 60.0), Section(Path("b.mp4"), 992.0, 1038.0)]
    c = ClipCandidate(1000.0, 1030.0, 80)
    pipeline._render_in_section(sections, c, [Segment(1001, 1010, "hi")], tmp_path, {}, None, "en")
    assert seen["source"] == Path("b.mp4")
    assert (seen["candidate"].start, seen["candidate"].end) == (8.0, 38.0)
    assert seen["segments"][0].start == 9.0
    assert seen["name_times"] == (1000.0, 1030.0)


def test_a_clip_no_section_covers_is_an_error_not_a_wrong_cut(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline._render_in_section([Section(Path("a.mp4"), 0, 60)], ClipCandidate(500, 530, 80),
                                    [], tmp_path, {}, None, "en")


def test_the_clip_file_name_comes_from_the_whole_video_not_the_section(monkeypatch, tmp_path):
    """A re-run must overwrite the same file whichever way the source came."""
    monkeypatch.setattr(pipeline, "cut_clip", lambda source, cand, out, *a, **k: Path(out).write_bytes(b"x"))
    config = {"clips": {"vertical": False, "captions": False, "outro": False},
              "paths": {"data_dir": str(tmp_path)}, "tracking": {}}
    c = ClipCandidate(8.0, 38.0, 80)
    path, _ = pipeline._render_files(Path("s.mp4"), c, [], tmp_path, config, None, "en",
                                     name_times=(1000.0, 1030.0))
    assert path.name == "clip_01000-01030.mp4"
    path, _ = pipeline._render_files(Path("s.mp4"), c, [], tmp_path, config, None, "en")
    assert path.name == "clip_00008-00038.mp4"


# ---- when it applies ------------------------------------------------------

def test_mode_defaults_and_spellings():
    assert dispatch.audio_first_mode({}) == "auto"
    assert dispatch.audio_first_mode(None) == "auto"
    for raw, want in [("on", "on"), ("OFF", "off"), (True, "on"), (False, "off"), ("nonsense", "auto")]:
        assert dispatch.audio_first_mode({"download": {"audio_first": raw}}) == want


def test_auto_applies_only_to_a_remote_video_known_to_be_over_the_threshold():
    cfg = {}
    assert dispatch.audio_first_min_seconds(cfg) == 90 * 60
    assert dispatch.wants_audio_first(cfg, "twitch", 91 * 60)
    assert not dispatch.wants_audio_first(cfg, "twitch", 89 * 60)
    assert not dispatch.wants_audio_first(cfg, "twitch", 0)       # length unknown
    assert not dispatch.wants_audio_first(cfg, "local", LONG)
    custom = {"download": {"audio_first_min_minutes": 30}}
    assert dispatch.wants_audio_first(custom, "youtube", 31 * 60)
    assert not dispatch.wants_audio_first({"download": {"audio_first_min_minutes": "bad"}}, "youtube", 80 * 60)


def test_on_and_off_ignore_the_length():
    assert dispatch.wants_audio_first({"download": {"audio_first": "on"}}, "youtube", 60)
    assert dispatch.wants_audio_first({"download": {"audio_first": "on"}}, "youtube", 0)
    assert not dispatch.wants_audio_first({"download": {"audio_first": "off"}}, "youtube", LONG)
    assert not dispatch.wants_audio_first({"download": {"audio_first": "on"}}, "local", LONG)


@pytest.mark.parametrize("option", ["whole", "pipeline", "rate", "understand", "edit", "sport",
                                    "vertical_live", "longform"])
def test_jobs_that_need_the_picture_are_not_audio_first(option):
    assert dispatch.audio_first_blocker({option: True}) is not None
    assert dispatch.audio_first_blocker({"gaming": True, "min_score": 50}) is None


# ---- the start of a job ---------------------------------------------------

@pytest.fixture
def start(monkeypatch, tmp_path):
    """_start_audio_first with the platform replaced; returns (call, state)."""
    state = {"probe": {"duration": LONG, "is_live": False, "title": "T", "channel": "C",
                       "games": [{"name": "G", "start": 0, "end": LONG}], "description": ""},
             "audio_calls": 0}

    def probe(url):
        if isinstance(state["probe"], Exception):
            raise state["probe"]
        return state["probe"]

    def download_audio(url, out):
        state["audio_calls"] += 1
        out.mkdir(parents=True, exist_ok=True)
        path = out / "abcdefghijk.audio.m4a"
        path.write_bytes(b"a")
        return path

    monkeypatch.setattr(dispatch, "probe", probe)
    monkeypatch.setattr(dispatch, "download_audio", download_audio)
    monkeypatch.setattr(pipeline, "_remote_renderer", lambda config: None)

    def call(config=None, url=YT):
        cfg = {"clips": {}, "paths": {"data_dir": str(tmp_path)}, **(config or {})}
        return pipeline._start_audio_first(url, cfg, tmp_path)

    return call, state


def test_a_long_video_starts_audio_first_with_the_platforms_metadata(start, tmp_path):
    call, state = start
    af = call()
    assert af is not None and state["audio_calls"] == 1
    assert af.video.path.name == "abcdefghijk.audio.m4a"
    assert af.video.duration == LONG and af.video.title == "T" and af.video.channel == "C"
    assert af.video.games[0]["name"] == "G"
    assert af.scratch == tmp_path / "downloads" / dispatch.AUDIO_FIRST_DIR / "abcdefghijk"


def test_a_short_or_unmeasured_video_downloads_as_always(start):
    call, state = start
    state["probe"] = {**state["probe"], "duration": 20 * 60}
    assert call() is None
    state["probe"] = {**state["probe"], "duration": 0}
    assert call() is None
    assert state["audio_calls"] == 0


def test_off_never_asks_the_platform_at_all(start, monkeypatch):
    call, _ = start
    monkeypatch.setattr(dispatch, "probe", MagicMock(side_effect=AssertionError("no probe when off")))
    assert call({"download": {"audio_first": "off"}}) is None


@pytest.mark.parametrize("why", [{"clips": {"sport": {"name": "soccer"}}}, {"clips": {"whole": True}},
                                 {"clips": {"pipeline": {"id": "x"}}}, {"clips": {"vertical_live": True}}])
def test_a_job_that_needs_the_picture_is_not_audio_first(start, why):
    call, state = start
    assert call(why) is None and state["audio_calls"] == 0


def test_a_video_already_on_disk_is_used_as_it_is(start, tmp_path):
    call, state = start
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "abcdefghijk.mp4").write_bytes(b"v")
    assert call() is None and state["audio_calls"] == 0


def test_a_live_stream_and_a_local_file_are_not_audio_first(start):
    call, state = start
    state["probe"] = {**state["probe"], "is_live": True}
    assert call() is None
    state["probe"]["is_live"] = False
    assert call(url="local:abcdefghijk") is None


def test_a_failed_probe_or_audio_download_falls_back_to_the_whole_video(start, monkeypatch):
    call, state = start
    state["probe"] = RuntimeError("offline")
    assert call() is None
    state["probe"] = {"duration": LONG, "is_live": False, "title": "", "channel": ""}
    monkeypatch.setattr(dispatch, "download_audio", MagicMock(side_effect=RuntimeError("403")))
    assert call() is None


def test_cancelling_during_the_audio_download_is_not_swallowed(start, monkeypatch):
    call, _ = start
    monkeypatch.setattr(dispatch, "download_audio", MagicMock(side_effect=cancel.CancelledError("abcdefghijk")))
    with pytest.raises(cancel.CancelledError):
        call()


def test_audio_the_prefetcher_already_fetched_is_reused(start, tmp_path):
    call, state = start
    scratch = tmp_path / "downloads" / dispatch.AUDIO_FIRST_DIR / "abcdefghijk"
    scratch.mkdir(parents=True)
    (scratch / "abcdefghijk.audio.m4a").write_bytes(b"a")
    af = call()
    assert af is not None and state["audio_calls"] == 0


# ---- sections, and falling back to the whole video ------------------------

def _candidates(*windows):
    return [ClipCandidate(s, e, 80) for s, e in windows]


@pytest.fixture
def sections(monkeypatch, tmp_path):
    state = {"asked": None, "error": None, "length": None}
    video = MagicMock(video_id="abcdefghijk", duration=LONG)
    af = pipeline._AudioFirst(video, tmp_path / "scratch")

    def download_sections(url, ranges, out, vertical=False):
        state["asked"] = list(ranges)
        if state["error"]:
            raise state["error"]
        return [Section(out / f"s{i}.mp4", lo, hi) for i, (lo, hi) in enumerate(ranges)]

    monkeypatch.setattr(dispatch, "download_sections", download_sections)
    monkeypatch.setattr(pipeline, "_whole_duration",
                        lambda path: state["length"] if state["length"] is not None else 10_000.0)
    return video, af, state


def test_the_chosen_clips_are_downloaded_padded_and_merged(sections):
    video, af, state = sections
    got = pipeline._download_sections(
        YT, _candidates((100, 130), (125, 160), (5000, 5030)), video, af)
    assert state["asked"] == [(92.0, 168.4), (4992.0, 5038.4)]
    assert [(s.start, s.end) for s in got] == state["asked"]


def test_a_download_error_means_the_whole_video(sections):
    video, af, state = sections
    state["error"] = RuntimeError("This format cannot be partially downloaded")
    assert pipeline._download_sections(YT, _candidates((100, 130)), video, af) is None


def test_a_section_that_arrived_short_means_the_whole_video(sections):
    video, af, state = sections
    state["length"] = 5.0
    assert pipeline._download_sections(YT, _candidates((100, 130)), video, af) is None


def test_clips_covering_most_of_the_video_are_just_downloaded_whole(sections):
    video, af, state = sections
    video.duration = 600.0
    assert pipeline._download_sections(YT, _candidates((10, 580)), video, af) is None
    assert state["asked"] is None   # never asked for parts


def test_cancelling_during_the_sections_is_not_swallowed(sections):
    video, af, state = sections
    state["error"] = cancel.CancelledError("abcdefghijk")
    with pytest.raises(cancel.CancelledError):
        pipeline._download_sections(YT, _candidates((100, 130)), video, af)


def test_the_gaming_webcam_search_runs_on_the_section_with_most_clips(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(pipeline, "_gaming_prepare",
                        lambda source, cands, clip_dir, config: seen.update(source=source, cands=cands) or {"gaming": {}})
    a, b = Section(Path("a.mp4"), 0, 100), Section(Path("b.mp4"), 992.0, 1200.0)
    cands = _candidates((10, 40), (1000, 1030), (1060, 1100))
    pipeline._gaming_prepare_in_sections([a, b], cands, tmp_path, {})
    assert seen["source"] == Path("b.mp4")
    assert [(c.start, c.end) for c in seen["cands"]] == [(8.0, 38.0), (68.0, 108.0)]


def test_scratch_is_removed_when_a_job_ends_however_it_ends(tmp_path, monkeypatch):
    scratch = tmp_path / "downloads" / dispatch.AUDIO_FIRST_DIR / "abcdefghijk"
    scratch.mkdir(parents=True)
    (scratch / "abcdefghijk.audio.m4a").write_bytes(b"a")
    monkeypatch.setattr(pipeline, "_process_video", MagicMock(side_effect=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        pipeline.process_video(YT, {"paths": {"data_dir": str(tmp_path)}}, MagicMock())
    assert not scratch.exists()


def test_a_normal_job_has_no_scratch_to_clean_and_returns_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_process_video", MagicMock(return_value=["clip"]))
    assert pipeline.process_video(YT, {"paths": {"data_dir": str(tmp_path)}}, MagicMock()) == ["clip"]


# ---- what each platform asks yt-dlp for -----------------------------------

class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: records options, writes the file."""

    seen: ClassVar[list[dict]] = []
    fail_times = 0

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def extract_info(self, url, download=False):
        if download:
            if FakeYDL.fail_times:
                FakeYDL.fail_times -= 1
                raise RuntimeError("Read timed out")
            ext = "m4a" if "postprocessors" in self.opts else "mp4"
            Path(self.opts["outtmpl"].replace("%(ext)s", ext)).write_bytes(b"x")
        return {"id": "x", "is_live": False, "title": "T", "duration": LONG}


@pytest.fixture
def ydl(monkeypatch):
    FakeYDL.seen, FakeYDL.fail_times = [], 0
    for module in (youtube, twitch, kick):
        monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(kick, "_impersonation", lambda: {})
    monkeypatch.setattr(ytdlp_common, "extract_info",
                        lambda url, opts, **kw: FakeYDL(opts).extract_info(url, **kw))
    monkeypatch.setattr(youtube, "extract_info", ytdlp_common.extract_info)
    return FakeYDL


def test_youtube_audio_is_audio_only_and_keeps_its_codec(ydl, tmp_path):
    path = dispatch.download_audio(YT, tmp_path)
    opts = ydl.seen[-1]
    assert path.name == "abcdefghijk.audio.m4a"
    assert opts["format"].startswith("bestaudio") and "download_ranges" not in opts
    assert opts["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}]
    assert opts["retries"] == 10 and opts["progress_hooks"]   # the shared retry and progress options


def test_twitch_audio_falls_back_to_the_smallest_rendition(ydl, tmp_path):
    path = dispatch.download_audio(TW, tmp_path)
    assert path.name == "tw_123456789.audio.m4a"
    assert ydl.seen[-1]["format"] == "bestaudio/worst"


def test_kick_audio_goes_through_the_same_lookup_as_the_video(ydl, tmp_path):
    url = "https://kick.com/video/0f0e0d0c-0b0a-0908-0706-050403020100"
    path = dispatch.download_audio(url, tmp_path)
    assert path.name == "kick_0f0e0d0c-0b0a-0908-0706-050403020100.audio.m4a"


@pytest.mark.parametrize(("url", "stem"), [
    (YT, "abcdefghijk"),
    (TW, "tw_123456789"),
    ("https://kick.com/video/0f0e0d0c-0b0a-0908-0706-050403020100", "kick_0f0e0d0c-0b0a-0908-0706-050403020100"),
])
def test_every_platform_downloads_one_file_per_range_with_its_offset(ydl, tmp_path, url, stem):
    got = dispatch.download_sections(url, [(92.0, 138.0), (992.0, 1038.0)], tmp_path)
    assert [(s.start, s.end) for s in got] == [(92.0, 138.0), (992.0, 1038.0)]
    assert [s.path.name for s in got] == [f"{stem}.sec000.mp4", f"{stem}.sec001.mp4"]
    for opts in ydl.seen[-2:]:
        assert opts["force_keyframes_at_cuts"] is True     # exact starts, so offsets hold
        assert callable(opts["download_ranges"])
    ranges = ydl.seen[-1]["download_ranges"]({}, None)
    assert [(r["start_time"], r["end_time"]) for r in ranges] == [(992.0, 1038.0)]


def test_a_section_is_tried_again_once_and_then_the_error_stands(ydl, tmp_path):
    ydl.fail_times = 1
    assert len(dispatch.download_sections(TW, [(0.0, 60.0)], tmp_path)) == 1
    ydl.fail_times = 5
    with pytest.raises(RuntimeError):
        dispatch.download_sections(TW, [(0.0, 60.0)], tmp_path)


def test_a_twitch_viewer_clip_cannot_be_downloaded_in_parts(ydl, tmp_path):
    with pytest.raises(ValueError, match="VOD"):
        dispatch.download_sections("https://clips.twitch.tv/SomeClipSlug", [(0.0, 10.0)], tmp_path)


def test_local_files_have_nothing_to_download(tmp_path):
    with pytest.raises(ValueError):
        dispatch.download_audio("local:abc", tmp_path)
    with pytest.raises(ValueError):
        dispatch.download_sections("local:abc", [(0, 1)], tmp_path)


def test_the_probe_reports_length_games_and_liveness(monkeypatch):
    info = {"duration": 7200, "is_live": False, "title": "A", "uploader": "U", "categories": ["Chess"]}
    monkeypatch.setattr(ytdlp_common, "extract_info", lambda url, opts, **kw: info)
    got = dispatch.probe(TW)
    assert got["duration"] == 7200.0 and got["channel"] == "U" and not got["is_live"]
    assert got["games"][0]["name"] == "Chess"


# ---- prefetch -------------------------------------------------------------

def _queue(db, payload=None):
    from core import queue

    db.set_flag(queue.PAUSED_KEY, "0")
    db.add_job("process", json.dumps({"url": YT, **(payload or {})}), video_id="abcdefghijk", title="t")


_RealThread = threading.Thread  # before any test replaces it


class _InlineThread:
    """Runs the prefetch to completion on a thread of its own, started and
    joined at once: the test sees the result, and the thread's progress tags
    ("prefetch") do not stay on the test's thread."""

    def __init__(self, target, args, **_kw):
        self._thread = _RealThread(target=target, args=args)

    def start(self):
        self._thread.start()
        self._thread.join()

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass


@pytest.fixture
def prefetch(db, tmp_path, monkeypatch):
    from core import prefetch as pf

    monkeypatch.setattr(pf.threading, "Thread", _InlineThread)
    calls = {"download": 0, "audio": 0}
    video = MagicMock(video_id="abcdefghijk", title="T", channel="C", duration=60.0)

    def download(url, out, vertical=False):
        calls["download"] += 1
        return video

    def download_audio(url, out):
        calls["audio"] += 1
        out.mkdir(parents=True, exist_ok=True)
        (out / "abcdefghijk.audio.m4a").write_bytes(b"a")
        return out / "abcdefghijk.audio.m4a"

    monkeypatch.setattr(dispatch, "download", download)
    monkeypatch.setattr(dispatch, "download_audio", download_audio)
    monkeypatch.setattr(dispatch, "probe", lambda url: {"duration": LONG, "is_live": False,
                                                        "title": "T", "channel": "C"})

    def make(config=None):
        return pf.Prefetcher(tmp_path / "state.db", tmp_path / "downloads", config)

    return make, calls


def test_the_next_long_video_is_prefetched_as_audio_only(db, prefetch):
    make, calls = prefetch
    _queue(db)
    make().maybe_start(db)
    assert calls == {"download": 0, "audio": 1}
    row = db.conn.execute("SELECT duration FROM videos WHERE video_id = 'abcdefghijk'").fetchone()
    assert row["duration"] == LONG       # the queue still gets its length estimate


def test_audio_that_is_already_prefetched_is_not_fetched_again(db, prefetch):
    make, calls = prefetch
    _queue(db)
    pf = make()
    pf.maybe_start(db)
    pf.maybe_start(db)
    assert calls["audio"] == 1 and calls["download"] == 0


def test_a_short_next_video_is_prefetched_whole_as_before(db, prefetch, monkeypatch):
    make, calls = prefetch
    monkeypatch.setattr(dispatch, "probe", lambda url: {"duration": 600.0, "is_live": False,
                                                        "title": "T", "channel": "C"})
    _queue(db)
    make().maybe_start(db)
    assert calls == {"download": 1, "audio": 0}


def test_with_audio_first_off_the_prefetch_is_exactly_the_old_one(db, prefetch, monkeypatch):
    make, calls = prefetch
    monkeypatch.setattr(dispatch, "probe", MagicMock(side_effect=AssertionError("no probe when off")))
    _queue(db)
    make({"download": {"audio_first": "off"}}).maybe_start(db)
    assert calls == {"download": 1, "audio": 0}


def test_a_job_that_needs_the_picture_is_prefetched_whole(db, prefetch):
    make, calls = prefetch
    _queue(db, {"sport": {"name": "soccer"}})
    make().maybe_start(db)
    assert calls == {"download": 1, "audio": 0}


def test_a_failed_audio_prefetch_is_ignored(db, prefetch, monkeypatch):
    make, calls = prefetch
    monkeypatch.setattr(dispatch, "download_audio", MagicMock(side_effect=RuntimeError("403")))
    _queue(db)
    make().maybe_start(db)     # best effort: nothing raised, the job downloads for itself
    assert calls["download"] == 0


# ---- a whole job ----------------------------------------------------------

@pytest.fixture
def job(db, tmp_path, monkeypatch):
    """process_video with everything heavy replaced: returns what each stage
    was handed, so the two paths can be compared."""
    import numpy as np

    seen = {"renders": [], "find": {}, "downloads": 0, "transcribed": None}
    config = {
        "paths": {"data_dir": str(tmp_path)},
        "clips": {"min_score": 50, "outro": False},
        "whisper": {"model": "tiny", "device": "cpu"},
        "llm": {"backend": "x"},
        "video": {"parallel_renders": 1},
        "scoring": {},
        "download": {"audio_first": "auto"},
    }
    segments = [Segment(4000.0, 4010.0, "a huge play")]
    cands = [ClipCandidate(4000.0, 4030.0, 90, hook="h")]
    full = MagicMock(video_id="abcdefghijk", title="T", channel="C", duration=LONG, games=[],
                     path=tmp_path / "downloads" / "abcdefghijk.mp4")

    monkeypatch.setattr(dispatch, "probe", lambda url: {"duration": LONG, "is_live": False, "title": "T",
                                                        "channel": "C", "games": [], "description": ""})

    def download_audio(url, out):
        out.mkdir(parents=True, exist_ok=True)
        (out / "abcdefghijk.audio.m4a").write_bytes(b"a")
        return out / "abcdefghijk.audio.m4a"

    def download_sections(url, ranges, out, vertical=False):
        if seen.get("sections_fail"):
            raise RuntimeError("cannot be partially downloaded")
        return [Section(out / f"s{i}.mp4", lo, hi) for i, (lo, hi) in enumerate(ranges)]

    def whole_download(url, data_dir, db_, vertical=False):
        seen["downloads"] += 1
        return full

    def transcribe(path, *a, **k):
        seen["transcribed"] = Path(path)
        return segments

    def find_clips(path, segs, llm, cfg, **kw):
        seen["find"] = {"path": Path(path), "kw": kw, "scoring": cfg.get("scoring")}
        return list(cands), []

    def render(sec_or_src, *a, **k):
        seen["renders"].append((Path(sec_or_src) if not isinstance(sec_or_src, list) else sec_or_src, a, k))
        return tmp_path / "clip.mp4", ""

    def metas(c, *a, **k):
        return [MagicMock(title="t", hashtags=[]) for _ in c]

    monkeypatch.setattr(dispatch, "download_audio", download_audio)
    monkeypatch.setattr(dispatch, "download_sections", download_sections)
    monkeypatch.setattr(pipeline, "_cached_or_download", whole_download)
    monkeypatch.setattr(pipeline, "transcribe", transcribe)
    monkeypatch.setattr(pipeline, "find_clips", find_clips)
    monkeypatch.setattr(pipeline, "create_backend", lambda cfg: MagicMock())
    monkeypatch.setattr(pipeline, "_with_usable_model", lambda cfg: cfg)
    monkeypatch.setattr(pipeline, "generate_metadata_batch", metas)
    monkeypatch.setattr(pipeline, "_render_files", lambda src, *a, **k: render(src, *a, **k))
    monkeypatch.setattr(pipeline, "_register_clip", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pipeline, "_check_length", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_made_seconds", lambda *a, **k: 30.0)
    monkeypatch.setattr(pipeline, "_remote_renderer", lambda config: None)
    monkeypatch.setattr(pipeline, "convert_slow_source", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_whole_duration", lambda path: 10_000.0)
    import analysis.audio_features as af_mod
    import analysis.hype as hype_mod
    import analysis.visual_features as vf_mod

    monkeypatch.setattr(af_mod, "extract_audio_features", lambda p: {"loudness": np.ones(4)})
    monkeypatch.setattr(vf_mod, "extract_visual_features",
                        lambda p: seen.setdefault("visual_for", Path(p)) and {"motion": np.ones(4)})
    monkeypatch.setattr(hype_mod, "audience_signals", lambda *a, **k: (None, []))
    return config, seen, db


def test_a_long_job_is_scored_from_audio_then_clips_come_from_sections(job, tmp_path):
    config, seen, db = job
    pipeline.process_video(YT, config, db)
    assert seen["downloads"] == 0                       # the whole video was never fetched
    assert seen["transcribed"].name == "abcdefghijk.audio.m4a"
    kw = seen["find"]["kw"]
    assert kw["signals"][1] == {} and kw["measure_reaction"] is False   # no picture: neutral, not penalised
    assert seen["find"]["scoring"]["look_at_game"] is False and seen["find"]["scoring"]["read_screen"] is False
    assert "visual_for" not in seen                      # frames were never decoded from the audio
    (source, args, kwargs), = seen["renders"]
    section = source
    assert section.name == "s0.mp4"
    candidate = args[0]
    assert (candidate.start, candidate.end) == (4000.0 - 3992.0, 4030.0 - 3992.0)   # 8 s pad before it
    assert kwargs["name_times"] == (4000.0, 4030.0)
    assert not (tmp_path / "downloads" / dispatch.AUDIO_FIRST_DIR / "abcdefghijk").exists()   # scratch gone


def test_a_failed_section_download_falls_back_to_the_normal_whole_video_path(job):
    config, seen, db = job
    seen["sections_fail"] = True
    pipeline.process_video(YT, config, db)
    assert seen["downloads"] == 1
    (source, args, kwargs), = seen["renders"]
    assert source.name == "abcdefghijk.mp4"
    assert (args[0].start, args[0].end) == (4000.0, 4030.0)      # whole-video times, no shift
    assert "name_times" not in kwargs


def test_with_audio_first_off_the_job_is_the_old_one(job):
    config, seen, db = job
    config["download"]["audio_first"] = "off"
    pipeline.process_video(YT, config, db)
    assert seen["downloads"] == 1
    assert "measure_reaction" not in seen["find"]["kw"]
    assert seen["find"]["kw"]["signals"][1] != {}
    assert seen["transcribed"].name == "abcdefghijk.mp4"
