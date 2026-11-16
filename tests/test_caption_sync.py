"""Captions on the beat of the voice (video/speech_sync.py) and the
word-by-word reveal (video/captions.py)."""

from core.models import ClipCandidate, Segment
from video import speech_sync
from video.captions import build_captions

LOG = """
[silencedetect @ 0x1] silence_start: 2.07
[silencedetect @ 0x1] silence_end: 2.73 | silence_duration: 0.66
[silencedetect @ 0x1] silence_start: 4.13
[silencedetect @ 0x1] silence_end: 5.2 | silence_duration: 1.07
[silencedetect @ 0x1] silence_start: 9.5
"""


def test_parse_shifts_and_closes_the_last_span():
    spans = speech_sync.parse(LOG, offset=100, length=10)
    assert spans == [(102.07, 102.73), (104.13, 105.2), (109.5, 110)]


def test_word_started_in_the_quiet_moves_to_the_voice():
    quiet = [(4.13, 5.2)]
    assert speech_sync.snap(4.82, 5.6, quiet) == 5.2      # Whisper's early start
    assert speech_sync.snap(3.0, 3.5, quiet) == 3.0       # spoken: untouched
    assert speech_sync.snap(4.5, 5.21, quiet) == 4.5      # would leave nothing of the word


def test_segments_and_saved_lines_snap_and_originals_stay():
    seg = Segment(4.8, 6.0, "com a", [{"start": 4.82, "end": 5.6, "word": "com"},
                                       {"start": 5.6, "end": 6.0, "word": "a"}])
    out = speech_sync.snap_segments([seg], [(4.13, 5.2)])
    assert out[0].words[0]["start"] == 5.2 and seg.words[0]["start"] == 4.82
    lines = [{"start": 4.82, "end": 6.0, "text": "COM A"}, {"start": 1.0, "end": 2.0, "text": "X"}]
    snapped = speech_sync.snap_lines(lines, [(4.13, 5.2)])
    assert snapped[0]["start"] == 5.2 and snapped[1] is lines[1]
    assert speech_sync.snap_segments([seg], []) == [seg]   # no quiet heard: nothing moves


def _events(tmp_path, style):
    cand = ClipCandidate(0, 3, 90)
    seg = Segment(0, 3, "um dois tres", [
        {"start": 0.0, "end": 1.0, "word": "um"},
        {"start": 1.0, "end": 2.0, "word": "dois"},
        {"start": 2.0, "end": 3.0, "word": "tres"},
    ])
    path = build_captions([seg], cand, tmp_path / "c.ass", style={"words_per_caption": 3, **style})
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue")]


def test_reveal_hides_the_words_not_yet_said(tmp_path):
    ev = _events(tmp_path, {"reveal": True})
    assert len(ev) == 3
    assert ev[0].endswith("}UM")
    assert ev[1].endswith("}UM DOIS")
    assert ev[2].endswith("}UM DOIS TRES")
    assert ev[1].split(",")[1] == "0:00:01.00"


def test_plain_and_highlight_unchanged_by_reveal_off(tmp_path):
    assert len(_events(tmp_path, {})) == 1
    hi = _events(tmp_path, {"highlight": True})
    assert len(hi) == 3 and all("alpha" not in e for e in hi)


def test_captions_go_back_to_their_place_when_the_banner_leaves(tmp_path):
    cand = ClipCandidate(0, 6, 90)
    segs = [Segment(0, 6, "a b c d e f", None)]
    path = build_captions(segs, cand, tmp_path / "c.ass", style={
        "words_per_caption": 2, "anchor_y": 800, "anchor_until": 3.0})
    ass = path.read_text(encoding="utf-8")
    assert "Style: Free," in ass
    styles = [l.split(",")[3] for l in ass.splitlines() if l.startswith("Dialogue")]
    # 0-2s and 2-4s start while the banner is up (until 3s); 4-6s after it.
    assert styles == ["Default", "Default", "Free"]


def test_words_follow_a_cut_made_in_the_editor(tmp_path):
    """Lines are moved onto the edited timeline; the words they light up must
    be too, or the reveal shows a word before it is heard."""
    cand = ClipCandidate(0, 6, 90)
    seg = Segment(0, 6, "um dois tres", [
        {"start": 0.0, "end": 1.0, "word": "um"},
        {"start": 3.0, "end": 4.0, "word": "dois"},
        {"start": 4.0, "end": 5.0, "word": "tres"},
    ])
    # 1-3 s cut out: everything after it plays 2 s earlier.
    cut = lambda t: t if t <= 1 else (None if t < 3 else t - 2)
    lines = [{"start": 0.0, "end": 3.0, "text": "um dois tres"}]
    path = build_captions([seg], cand, tmp_path / "c.ass", style={"reveal": True},
                          lines=lines, word_map=cut)
    ev = [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue")]
    assert [e.split(",")[1] for e in ev] == ["0:00:00.00", "0:00:01.00", "0:00:02.00"]
