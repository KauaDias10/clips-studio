"""The title banner (video_editor/title_banner.py): the clip's title in a box
across the middle, captions right above it."""

from core.models import ClipCandidate, Segment
from video.captions import build_captions
from video_editor import title_banner as tb


def test_off_unless_asked():
    assert not tb.enabled(None)
    assert not tb.enabled({"position": "middle"})
    assert tb.enabled({"title_banner": True})


def test_title_cleaned_for_the_banner():
    assert tb.clean_title("Ele tem 270 casas 🏠🔥 #shorts #fyp") == "ELE TEM 270 CASAS"
    assert tb.clean_title("a {\\b1}b") == "A B1B"
    assert tb.layout("#shorts 🔥") is None


def test_short_title_one_line_long_title_wraps():
    assert tb.layout("Revelou tudo").lines == 1
    b = tb.layout("Wesley Alemao revelou que tem 270 casas")
    assert b.lines == 2 and "\\N" in b.text
    huge = tb.layout(" ".join(["palavra"] * 40))
    assert huge.lines <= 3 and huge.text.endswith("…")
    assert huge.size < b.size   # shrinks before it gives up


def test_centered_where_asked_and_clamped():
    assert tb.layout("x", style={"title_banner_y": 50}).center_y == 960
    assert tb.layout("x", style={"title_banner_y": 99}).center_y == round(1920 * 0.95)
    assert tb.layout("x", style={"title_banner_y": "nope"}).center_y == 960


def test_captions_sit_above_the_banner(tmp_path):
    b = tb.layout("Wesley Alemao revelou que tem 270 casas")
    anchor = tb.caption_anchor(b)
    assert anchor < b.top_y
    cand = ClipCandidate(0, 4, 90)
    segs = [Segment(0, 4, "ai ele falou", None)]
    style = {"title_banner": True, "position": "bottom", "anchor_y": anchor}
    path = build_captions(segs, cand, tmp_path / "c.ass", style=style)
    path = tb.ensure_banner(path, tmp_path / "c.ass", b, style=style)
    ass = path.read_text(encoding="utf-8")
    # Default style: bottom-anchored (2) with its baseline at the anchor.
    default = next(l for l in ass.splitlines() if l.startswith("Style: Default"))
    assert default.split(",")[-5:-1] == ["2", "60", "60", str(1920 - anchor)]
    assert "Style: Banner,Impact," in ass and ",3,18,0,5," in ass   # opaque box, centred
    assert "{\\an5\\pos(540,960)}WESLEY" in ass
    # Top captions stay at the top.
    top = build_captions(segs, cand, tmp_path / "t.ass", style={**style, "position": "top"})
    line = next(l for l in top.read_text(encoding="utf-8").splitlines() if l.startswith("Style: Default"))
    assert line.split(",")[-5] == "8"


def test_banner_alone_without_captions(tmp_path):
    b = tb.layout("So o titulo")
    path = tb.ensure_banner(None, tmp_path / "b.ass", b)
    ass = path.read_text(encoding="utf-8")
    assert "Style: Banner" in ass and "SO O TITULO" in ass and "Style: Default" not in ass


def test_moved_resized_and_own_words():
    b = tb.layout("Titulo da IA", style={
        "title_banner_x": 30, "title_banner_y": 70, "title_banner_size": 150,
        "title_banner_text": "Meu texto", "title_banner_uppercase": False,
    })
    assert b.text == "Meu texto"                 # the person's words, as typed
    assert (b.center_x, b.center_y) == (324, 1344)
    assert b.size == round(78 * 1.5)
    assert tb.layout("x", style={"title_banner_x": 0}).center_x == 108   # kept on screen
    # Bigger letters break the same title onto more lines.
    long = "Wesley Alemao revelou que tem 270 casas"
    assert tb.layout(long, style={"title_banner_size": 180}).lines > tb.layout(long).lines


def test_banner_font_from_the_list_only(tmp_path):
    b = tb.layout("x")
    ok = tb.ensure_banner(None, tmp_path / "a.ass", b, style={"title_banner_font": "Bahnschrift"})
    assert "Style: Banner,Bahnschrift," in ok.read_text(encoding="utf-8")
    bad = tb.ensure_banner(None, tmp_path / "b.ass", b, style={"title_banner_font": "Nope"})
    assert "Style: Banner,Impact," in bad.read_text(encoding="utf-8")


def test_captions_go_below_a_banner_near_the_top_or_stay_put():
    high = tb.layout("Um titulo", style={"title_banner_y": 8})
    place = tb.caption_placement(high)
    assert "anchor_top_y" in place and place["anchor_top_y"] > tb.bottom_y(high)
    mid = tb.layout("Um titulo")
    assert "anchor_y" in tb.caption_placement(mid)
    assert tb.caption_placement(mid, style={"title_banner_captions": "keep"}) == {}


def test_more_fonts_and_script_swap_still_works():
    from video.captions import FONTS, caption_font_for
    assert {"Bahnschrift", "Segoe UI Black", "Times New Roman", "Ink Free"} <= set(FONTS)
    assert caption_font_for("hi", "Bahnschrift") == "Nirmala UI"   # Latin-only font swapped
    assert caption_font_for("pt", "Bahnschrift") == "Bahnschrift"


def test_time_on_screen_and_thickness(tmp_path):
    b = tb.layout("Titulo", style={"title_banner_seconds": 4.5, "title_banner_pad": 40})
    assert b.seconds == 4.5 and b.pad == 40
    ass = tb.ensure_banner(None, tmp_path / "t.ass", b).read_text(encoding="utf-8")
    assert "Dialogue: 2,0:00:00.00,0:00:04.50,Banner" in ass
    assert ",3,40,0,5," in ass                       # thicker box
    assert tb.caption_placement(b)["anchor_until"] == 4.5
    whole = tb.layout("Titulo")
    assert "9:59:59.00" in tb._event(whole, (1080, 1920))
    assert "anchor_until" not in tb.caption_placement(whole)
    thin = tb.layout("Titulo", style={"title_banner_pad": 0})
    assert thin.top_y > whole.top_y                   # a thinner box is shorter


def test_bundled_fonts_are_known_and_found():
    from video.captions import BUNDLED_FONTS, FONTS, fonts_dir, subtitles_filter
    assert set(BUNDLED_FONTS) <= set(FONTS)
    where = fonts_dir()
    assert where is not None and all((where / f).exists() for f in BUNDLED_FONTS.values())
    assert list(where.glob("*.txt")) == []          # libass would try to load a licence as a font
    assert subtitles_filter("c.ass").startswith("subtitles=c.ass:fontsdir='")


def _styles(tmp_path, **style):
    b = tb.layout("Rockstar confirma detalhes do GTA 6", style=style)
    ass = tb.ensure_banner(None, tmp_path / "s.ass", b, style=style).read_text(encoding="utf-8")
    return ass, [l for l in ass.splitlines() if l.startswith("Dialogue")]


def test_the_box_never_covers_the_words(tmp_path):
    """The box and the words are two events, the words on the layer above:
    a thick box can't run over the line above it any more."""
    ass, events = _styles(tmp_path, title_banner_pad=60)
    assert [e.split(",")[0] for e in events] == ["Dialogue: 2", "Dialogue: 3"]
    assert [e.split(",")[3] for e in events] == ["BannerBox", "Banner"]
    box = next(l for l in ass.splitlines() if l.startswith("Style: BannerBox,"))
    assert box.split(",")[3] == "&HFFFFFFFF"         # its own letters are invisible
    assert ",3,60,0,5," in box


def test_box_styles_opacity_and_letter_styles(tmp_path):
    ass, events = _styles(tmp_path, title_banner_box="block", title_banner_opacity=50,
                          title_banner_color="#112233")
    box = next(l for l in ass.splitlines() if l.startswith("Style: BannerBox,"))
    assert ",4," in box and box.split(",")[6] == "&H80332211"   # one box, half see-through
    ass, events = _styles(tmp_path, title_banner_box="none")
    assert "BannerBox" not in ass and len(events) == 1
    ass, _ = _styles(tmp_path, title_banner_outline=6, title_banner_outline_color="#00FF00",
                     title_banner_shadow=4, title_banner_italic=True, title_banner_spacing=3,
                     title_banner_tilt=-8)
    words = next(l for l in ass.splitlines() if l.startswith("Style: Banner,")).split(",")
    assert words[5] == "&H0000FF00"                   # outline colour
    assert words[8] == "-1"                           # italic
    assert words[13:17] == ["3", "-8", "1", "6"]      # spacing, tilt, plain outline, its width
    assert words[17] == "4"                           # shadow
    # The box leans with the words.
    assert next(l for l in ass.splitlines() if l.startswith("Style: BannerBox,")).split(",")[14] == "-8"


def test_odd_values_fall_back(tmp_path):
    ass, _ = _styles(tmp_path, title_banner_box="weird", title_banner_opacity="x", title_banner_tilt=99)
    box = next(l for l in ass.splitlines() if l.startswith("Style: BannerBox,")).split(",")
    assert box[15] == "3" and box[6].startswith("&H00") and box[14] == "20"


def test_letters_fade_in_bands_over_one_outline(tmp_path):
    """A gradient title: per line, one outlined event underneath, then fill
    only bands on the layer above, top colour first, bottom colour last."""
    ass, events = _styles(tmp_path, title_banner_box="none", title_banner_text_color="#FF0000",
                          title_banner_gradient="#0000FF", title_banner_tilt=5)
    under = [e for e in events if e.startswith("Dialogue: 3")]
    bands = [e for e in events if e.startswith("Dialogue: 4")]
    lines = ass.count("Dialogue: 3")
    assert lines == 2 and len(bands) > 10 * lines
    assert all("\\bord0\\shad0\\clip(m " in b for b in bands)
    assert all("\\org(" in e for e in under + bands)      # turns round the banner centre
    first_line = under[0].split("}")[-1]
    mine = [b for b in bands if b.endswith("}" + first_line)]
    def rgb(event):   # ASS colours are &HBBGGRR&
        h = event.split("\\1c&H")[1][:6]
        return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)

    assert rgb(mine[0])[0] > 230 and rgb(mine[0])[2] < 25      # red at the top
    assert rgb(mine[-1])[2] > 230 and rgb(mine[-1])[0] < 25    # blue at the bottom
    assert "\\N" not in "".join(under + bands)             # a line per event


def test_no_gradient_keeps_one_event_and_shadow_colour(tmp_path):
    ass, events = _styles(tmp_path, title_banner_box="none", title_banner_shadow=4,
                          title_banner_shadow_color="#FF2E88")
    assert len(events) == 1
    words = next(l for l in ass.splitlines() if l.startswith("Style: Banner,")).split(",")
    assert words[6] == "&H00882EFF"                         # solid pink shadow
    ass, _ = _styles(tmp_path, title_banner_shadow=4)
    assert next(l for l in ass.splitlines() if l.startswith("Style: Banner,")).split(",")[6] == "&H80000000"


def test_vice_preset_and_cap_band():
    style = tb.PRESETS["vice"]
    assert len(tb.gradient_stops(style)) == 3 and style["title_banner_box"] == "none"
    top, bottom = tb.cap_band("Anton")
    assert 0.2 < top < bottom < 0.9
    assert tb.cap_band("No Such Font") == (tb._CAP_TOP, tb._CAP_BOTTOM)
