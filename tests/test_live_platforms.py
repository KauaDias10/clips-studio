"""Live links on Twitch, Kick and YouTube, and moments from audio peaks."""

import pytest

from live.audio_peaks import STEP, AudioPeaks
from live.platforms import parse_target


@pytest.mark.parametrize("link, key, page", [
    ("alanzoka", "twitch:alanzoka", "https://www.twitch.tv/alanzoka"),
    ("#Alanzoka", "twitch:alanzoka", "https://www.twitch.tv/alanzoka"),
    ("https://www.twitch.tv/Alanzoka/", "twitch:alanzoka", "https://www.twitch.tv/alanzoka"),
    ("https://kick.com/xQc", "kick:xqc", "https://kick.com/xqc"),
    ("kick.com/some-one", "kick:some-one", "https://kick.com/some-one"),
    ("https://www.youtube.com/@CazeTV/live", "youtube:@CazeTV", "https://www.youtube.com/@CazeTV/live"),
    ("https://youtube.com/@CazeTV", "youtube:@CazeTV", "https://www.youtube.com/@CazeTV/live"),
    ("https://www.youtube.com/watch?v=4t4AQ15yj1M", "youtube:4t4AQ15yj1M",
     "https://www.youtube.com/watch?v=4t4AQ15yj1M"),
    ("https://youtu.be/4t4AQ15yj1M", "youtube:4t4AQ15yj1M", "https://www.youtube.com/watch?v=4t4AQ15yj1M"),
    ("https://www.youtube.com/live/4t4AQ15yj1M?si=x", "youtube:4t4AQ15yj1M",
     "https://www.youtube.com/watch?v=4t4AQ15yj1M"),
])
def test_links(link, key, page):
    t = parse_target(link)
    assert (t.key, t.page_url) == (key, page)


def test_names_and_bad_links():
    assert parse_target("alanzoka").slug == "alanzoka"            # Twitch files keep their old names
    assert parse_target("kick.com/xqc").slug == "kick-xqc"
    assert parse_target("youtube.com/@Caze.TV").slug == "youtube-cazetv"
    for bad in ("not a channel!", "https://example.com/x", ""):
        with pytest.raises(ValueError):
            parse_target(bad)


def _readings(levels, t0=1000.0):
    return [(t0 + i * STEP, db) for i, db in enumerate(levels)]


def test_a_few_loud_seconds_are_a_moment_a_bang_is_not():
    calm = [-30.0] * 200                                   # 100 s of the usual level
    a = AudioPeaks(pre=20, post=5)
    a.add(_readings(calm + [-12.0] + calm[:20]))            # one loud half second
    assert a.detect() == []
    a = AudioPeaks(pre=20, post=5)
    a.add(_readings(calm + [-14.0, -12.0, -13.0, -11.0, -15.0, -13.0] + calm[:20]))
    found = a.detect()
    assert len(found) == 1 and found[0].kind == "audio"
    assert found[0].at == 1000.0 + 203 * STEP              # the loudest reading
    assert a.detect() == []                                # read once


def test_nothing_before_warmup_or_while_still_loud():
    a = AudioPeaks()
    a.add(_readings([-30.0] * 40 + [-10.0] * 6 + [-30.0] * 4))
    assert a.detect() == []                                # 25 s heard: too soon
    a = AudioPeaks()
    a.add(_readings([-30.0] * 200 + [-10.0] * 6))           # still going at the end
    assert a.detect() == []
