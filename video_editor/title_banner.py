"""Title banner: the clip's title in a coloured box across the middle of the
frame, on screen for the whole clip, with the captions sitting right above
it (unless they are set to Top) — the "split-screen reaction" Shorts look:

            ai                 <- caption, as it is said
    +-----------------------+
    | WESLEY ALEMAO REVELOU |  <- title banner (whole clip)
    |   QUE TEM 270 CASAS   |
    +-----------------------+

Like the hook (video_editor/overlay.py) it is an extra ASS style + event
merged into the clip's caption file, so it burns through the same subtitles
plumbing: correct at final resolution, system fonts via libass.

Turned on per job or per clip by `title_banner: true` in the caption style;
the text is the clip's title (render option `title_text`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {
    "title_banner": False,
    "title_banner_color": "#E01B24",       # box
    "title_banner_text_color": "#FFFFFF",  # letters
    "title_banner_font": "Impact",
    "title_banner_y": 50,                  # banner centre, % of frame height
    "title_banner_x": 50,                  # banner centre, % of frame width
    "title_banner_size": 100,              # letter size, % of the default
    "title_banner_uppercase": True,
    "title_banner_text": "",               # the person's own words; else the clip's title
    "title_banner_seconds": 0,             # on screen from the start for this long; 0 = whole clip
    "title_banner_pad": 18,                # box around the letters, px at 1920 tall
    "title_banner_box": "lines",           # lines: a box per line | block: one box | none
    "title_banner_opacity": 100,           # the box, % (0 = see-through)
    "title_banner_outline": 0,             # outline round the letters, px at 1920 tall
    "title_banner_outline_color": "#000000",
    "title_banner_shadow": 0,              # drop shadow, px at 1920 tall
    "title_banner_italic": False,
    "title_banner_spacing": 0,             # extra space between letters, px
    "title_banner_tilt": 0,                # degrees, + leans up to the right
    # Letters fading top to bottom: the title colour at the top, through
    # the middle colour (optional) to this one at the bottom. "" = one colour.
    "title_banner_gradient": "",
    "title_banner_gradient_mid": "",
    "title_banner_shadow_color": "",       # "" = see-through black; else solid
}

# Ready-made looks: a preset sets these keys over the person's style (the
# UI offers the same list, BANNER_PRESETS in CaptionStyleControls.tsx).
PRESETS = {
    # Vice City sunset: yellow to pink to purple letters, a thick night-blue
    # outline and a hot pink drop shadow, slightly tilted. Made for thumbnails.
    "vice": {
        "title_banner": True,
        "title_banner_font": "Anton",
        "title_banner_box": "none",
        "title_banner_text_color": "#FFE27A",
        "title_banner_gradient_mid": "#FF5FA2",
        "title_banner_gradient": "#8B3DFF",
        "title_banner_outline": 8,
        "title_banner_outline_color": "#140A2E",
        "title_banner_shadow": 9,
        "title_banner_shadow_color": "#FF2E88",
        "title_banner_size": 150,
        "title_banner_tilt": 4,
        "title_banner_italic": False,
        "title_banner_spacing": 2,
        "title_banner_uppercase": True,
    },
}

# Calibrated for the 1080x1920 Shorts canvas; scaled to other frames.
_SIZES = ((78, 22), (66, 26), (58, 30))   # (font size, max chars per line)
_MAX_LINES = 3
_PAD = 18          # box padding around the letters (ASS outline in BorderStyle 3)
_LINE = 1.18       # line height / font size, Impact in libass
_GAP = 22          # space between the captions and the top of the box

_HASHTAG = re.compile(r"(^|\s)#\w+", re.UNICODE)
# Emoji and pictographs: the stock fonts have none, they burn as boxes.
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")


@dataclass
class Banner:
    text: str            # ASS-ready, lines joined with \N
    lines: int
    size: int            # font size at the canvas resolution
    center_y: int        # canvas px
    center_x: int        # canvas px
    top_y: int           # top edge of the box, canvas px: captions end above it
    seconds: float = 0.0  # how long it stays on screen; 0 = the whole clip
    pad: int = 18         # box padding, canvas px


def enabled(style: dict | None) -> bool:
    return bool((style or {}).get("title_banner"))


def clean_title(title: str, uppercase: bool = True) -> str:
    """The title as the banner shows it: no hashtags, no emoji, no ASS
    control characters, one space between words, upper case unless not."""
    text = _HASHTAG.sub(" ", title or "")
    text = _EMOJI.sub("", text)
    text = text.replace("\\", "").replace("{", "").replace("}", "")
    text = " ".join(text.split())
    return text.upper() if uppercase else text


def _pct(value, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _wrap(words: list[str], width: int) -> list[str]:
    lines: list[str] = []
    for word in words:
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def _balanced(words: list[str], width: int) -> list[str]:
    """Greedy wrap, then even out the lines: two lines of 12 and 10 read
    better on a banner than 21 and 1."""
    lines = _wrap(words, width)
    n = len(lines)
    if n < 2:
        return lines
    total = len(" ".join(words))
    for w in range(max(1, total // n), width + 1):
        trial = _wrap(words, w)
        if len(trial) == n:
            return trial
    return lines


def layout(title: str, canvas: tuple[int, int] = (1080, 1920), style: dict | None = None) -> Banner | None:
    """Where the banner goes and how its text breaks. None with no text."""
    opts = {**DEFAULTS, **(style or {})}
    # The person's own words for the banner win over the clip's title.
    own = str(opts.get("title_banner_text") or "").strip()
    text = clean_title(own or title, bool(opts.get("title_banner_uppercase", True)))
    if not text:
        return None
    words = text.split()
    scale = canvas[1] / 1920
    # Bigger letters fit fewer per line, smaller ones more.
    grow = _pct(opts.get("title_banner_size"), 100.0, 50.0, 200.0) / 100
    # Landscape frames are wider: let lines run longer there.
    widen = (canvas[0] / canvas[1]) / (1080 / 1920)
    lines: list[str] = []
    size = _SIZES[-1][0]
    for size, width in _SIZES:
        lines = _balanced(words, max(6, int(width * min(widen, 2.0) / grow)))
        if len(lines) <= 2:
            break
    if len(lines) > _MAX_LINES:
        lines = lines[:_MAX_LINES]
        lines[-1] = lines[-1].rstrip(".,;:!?") + "…"
    size_px = max(20, round(size * scale * grow))
    center = round(canvas[1] * _pct(opts.get("title_banner_y"), 50.0, 5.0, 95.0) / 100)
    center_x = round(canvas[0] * _pct(opts.get("title_banner_x"), 50.0, 10.0, 90.0) / 100)
    pad = max(2, round(_pct(opts.get("title_banner_pad"), _PAD, 0.0, 80.0) * scale))
    seconds = _pct(opts.get("title_banner_seconds"), 0.0, 0.0, 600.0)
    height = len(lines) * size_px * _LINE + 2 * pad
    top = round(center - height / 2)
    return Banner("\\N".join(lines), len(lines), size_px, center, center_x, top, seconds, pad)


def caption_anchor(banner: Banner, canvas: tuple[int, int] = (1080, 1920)) -> int:
    """The y the captions' baseline sits on: just above the box."""
    return max(0, banner.top_y - round(_GAP * canvas[1] / 1920))


def bottom_y(banner: Banner, canvas: tuple[int, int] = (1080, 1920)) -> int:
    """The bottom edge of the box, canvas px."""
    return banner.center_y + (banner.center_y - banner.top_y)


def caption_placement(
    banner: Banner, canvas: tuple[int, int] = (1080, 1920), style: dict | None = None
) -> dict:
    """What the caption style gets so its lines sit next to the banner:
    right above it, or right below it when it is too near the top of the
    frame for a caption to fit above. Nothing when the person chose to keep
    the captions where their own position puts them."""
    if (style or {}).get("title_banner_captions") == "keep":
        return {}
    gap = round(_GAP * canvas[1] / 1920)
    room = round(260 * canvas[1] / 1920)   # about two caption lines
    # A banner that leaves the screen hands the captions back to their own
    # position from then on (video/captions.py, the "Free" style).
    until = {"anchor_until": banner.seconds} if banner.seconds > 0 else {}
    if banner.top_y - gap >= room:
        return {"anchor_y": caption_anchor(banner, canvas), **until}
    return {"anchor_top_y": bottom_y(banner, canvas) + gap, **until}


def _ass_color(hex_rgb: str, fallback: str) -> str:
    h = (hex_rgb or "").lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        h = fallback.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


BOX_STYLES = ("lines", "block", "none")


def _with_alpha(colour: str, opacity_pct: float) -> str:
    """An &H00BBGGRR colour with its alpha set from an opacity in % (ASS alpha
    counts transparency: 00 is solid, FF is invisible)."""
    alpha = round(255 * (1 - max(0.0, min(100.0, opacity_pct)) / 100))
    return f"&H{alpha:02X}{colour[4:]}"


def _style_lines(banner: Banner, canvas: tuple[int, int], style: dict | None) -> list[str]:
    """The banner's two styles: the box (BannerBox) and the words (Banner).

    They are two events on two layers, the words above. In one event, libass
    draws the box of a line under the next line's box but not under the
    other lines' letters, so a thick box ran over the words of the line
    above it. Kept apart, a box can never cover a letter, and the words get
    their own outline and shadow."""
    opts = {**DEFAULTS, **(style or {})}
    from video.captions import FONTS

    font = opts.get("title_banner_font")
    font = font if font in FONTS else DEFAULTS["title_banner_font"]
    text = _ass_color(opts.get("title_banner_text_color"), DEFAULTS["title_banner_text_color"])
    box = _with_alpha(
        _ass_color(opts.get("title_banner_color"), DEFAULTS["title_banner_color"]),
        _pct(opts.get("title_banner_opacity"), 100.0, 0.0, 100.0),
    )
    outline_colour = _ass_color(opts.get("title_banner_outline_color"), DEFAULTS["title_banner_outline_color"])
    scale = canvas[1] / 1920
    outline = round(_pct(opts.get("title_banner_outline"), 0.0, 0.0, 16.0) * scale, 1)
    shadow = round(_pct(opts.get("title_banner_shadow"), 0.0, 0.0, 16.0) * scale, 1)
    spacing = round(_pct(opts.get("title_banner_spacing"), 0.0, -4.0, 24.0) * scale, 1)
    angle = _pct(opts.get("title_banner_tilt"), 0.0, -20.0, 20.0)
    italic = -1 if opts.get("title_banner_italic") else 0
    hidden = "&HFFFFFFFF"   # the box layer's own letters: never seen
    lines = []
    kind = opts.get("title_banner_box") if opts.get("title_banner_box") in BOX_STYLES else "lines"
    if kind == "lines":
        # BorderStyle 3: a box round each line, `Outline` px out from it.
        lines.append(
            f"Style: BannerBox,{font},{banner.size},{hidden},{hidden},{box},{box},"
            f"-1,{italic},0,0,100,100,{spacing:g},{angle:g},3,{banner.pad},0,5,40,40,0,1"
        )
    elif kind == "block":
        # BorderStyle 4 (libass): one box round the whole title, in
        # BackColour; the outline only sets how far out it reaches.
        lines.append(
            f"Style: BannerBox,{font},{banner.size},{hidden},{hidden},{hidden},{box},"
            f"-1,{italic},0,0,100,100,{spacing:g},{angle:g},4,{banner.pad},0,5,40,40,0,1"
        )
    shadow_hex = str(opts.get("title_banner_shadow_color") or "")
    shadow_colour = _ass_color(shadow_hex, "#000000") if shadow_hex else "&H80000000"
    lines.append(
        f"Style: Banner,{font},{banner.size},{text},{text},{outline_colour},{shadow_colour},"
        f"-1,{italic},0,0,100,100,{spacing:g},{angle:g},1,{outline:g},{shadow:g},5,40,40,0,1"
    )
    return lines


def _event(banner: Banner, canvas: tuple[int, int], name: str = "Banner", layer: int = 3) -> str:
    # The whole clip: an end past the file is simply never reached.
    return (
        f"Dialogue: {layer},0:00:00.00,{_ass_time(banner.seconds) if banner.seconds > 0 else '9:59:59.00'},{name},,0,0,0,,"
        f"{{\\an5\\pos({banner.center_x},{banner.center_y})}}{banner.text}"
    )


def _hex_rgb(value) -> tuple[int, int, int] | None:
    h = str(value or "").lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        return None
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def gradient_stops(style: dict | None) -> list[tuple[int, int, int]]:
    """The letters' colours top to bottom; one colour = no gradient."""
    opts = {**DEFAULTS, **(style or {})}
    top = _hex_rgb(opts.get("title_banner_text_color")) or _hex_rgb(DEFAULTS["title_banner_text_color"])
    bottom = _hex_rgb(opts.get("title_banner_gradient"))
    if bottom is None:
        return [top]
    mid = _hex_rgb(opts.get("title_banner_gradient_mid"))
    return [top, mid, bottom] if mid else [top, bottom]


def _mix(stops: list[tuple[int, int, int]], t: float) -> str:
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = stops[i], stops[i + 1]
    r, g, bl = (round(a[k] + (b[k] - a[k]) * f) for k in range(3))
    return f"&H{bl:02X}{g:02X}{r:02X}&"


# Where the capitals sit in a line, as fractions of its height from the top,
# when the font file can't be read (about right for Impact and Arial).
_CAP_TOP, _CAP_BOTTOM = 0.18, 0.83


def _font_file(name: str) -> Path | None:
    from video.captions import BUNDLED_FONTS, fonts_dir

    if name in BUNDLED_FONTS:
        where = fonts_dir()
        return where / BUNDLED_FONTS[name] if where else None
    return _system_fonts().get(name.lower())


_SYSTEM_FONTS: dict[str, Path] | None = None


def _system_fonts() -> dict[str, Path]:
    """Family name -> file for the Windows fonts folder, read once. The
    regular face is enough: only where the capitals sit is needed."""
    global _SYSTEM_FONTS
    if _SYSTEM_FONTS is None:
        import os

        found: dict[str, Path] = {}
        folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        try:
            from fontTools.ttLib import TTFont

            for f in sorted(folder.glob("*.tt[fc]")):
                try:
                    font = TTFont(f, fontNumber=0, lazy=True)
                    # Both the old family name ("Arial Black") and the
                    # typographic one ("Arial"): fonts are chosen by either.
                    names = {font["name"].getDebugName(1), font["name"].getBestFamilyName()}
                except Exception:
                    continue
                for family in filter(None, names):
                    found.setdefault(family.lower(), f)
        except ImportError:
            pass
        _SYSTEM_FONTS = found
    return _SYSTEM_FONTS


_CAPS: dict[str, tuple[float, float]] = {}


def cap_band(font: str) -> tuple[float, float]:
    """Top and bottom of the capitals in a line, fractions of its height.
    libass makes a line exactly as tall as the font's Windows ascent plus
    descent, so these place the gradient on the letters for any font."""
    if font not in _CAPS:
        band = (_CAP_TOP, _CAP_BOTTOM)
        try:
            from fontTools.ttLib import TTFont

            path = _font_file(font)
            if path is not None and path.exists():
                os2 = TTFont(path, fontNumber=0, lazy=True)["OS/2"]
                total = os2.usWinAscent + os2.usWinDescent
                cap = getattr(os2, "sCapHeight", 0) or round(0.7 * os2.usWinAscent)
                if total > 0:
                    band = ((os2.usWinAscent - cap) / total, os2.usWinAscent / total)
        except Exception:
            pass
        _CAPS[font] = band
    return _CAPS[font]


def _turn(x: float, y: float, cx: float, cy: float, degrees: float) -> tuple[int, int]:
    """(x, y) turned round (cx, cy) as \\frz turns text: + is anticlockwise."""
    import math

    a = math.radians(degrees)
    dx, dy = x - cx, y - cy
    return round(cx + dx * math.cos(a) + dy * math.sin(a)), round(cy - dx * math.sin(a) + dy * math.cos(a))


def _gradient_events(banner: Banner, canvas: tuple[int, int], stops, style: dict | None) -> list[str]:
    """The words cut in thin bands, each its own colour: libass has no
    gradient fill, but the same line drawn under a clip per band is one.

    Each line is its own event at a known spot (libass makes a line as tall
    as its font size), so every line gets the whole gradient across its
    capitals. A tilted title turns round the banner's centre, and so do the
    bands (a drawn clip).

    The outline and the shadow are drawn once per line, under the bands,
    and the bands are only the letters' fill (no border): a band's smoothed
    edge then blends into the next band's colour, never shows a dark line
    of outline between them."""
    opts = {**DEFAULTS, **(style or {})}
    from video.captions import FONTS

    font = opts.get("title_banner_font")
    font = font if font in FONTS else DEFAULTS["title_banner_font"]
    cap_top, cap_bottom = cap_band(font)
    angle = _pct(opts.get("title_banner_tilt"), 0.0, -20.0, 20.0)
    end = _ass_time(banner.seconds) if banner.seconds > 0 else "9:59:59.00"
    cx, cy = banner.center_x, banner.center_y
    line_h = banner.size
    texts = banner.text.split("\\N")
    band = max(2, round(3 * canvas[1] / 1920))
    reach = canvas[0] + canvas[1]   # past any edge, turned or not
    out = []
    for i, words in enumerate(texts):
        line_cy = cy + (i - (len(texts) - 1) / 2) * line_h
        at = f"\\an5\\pos({cx},{round(line_cy)})\\org({cx},{cy})"
        out.append(f"Dialogue: 3,0:00:00.00,{end},Banner,,0,0,0,,{{{at}\\1c{_mix(stops, 0.5)}}}{words}")
        y0 = line_cy - line_h / 2
        lo, hi = y0 + cap_top * line_h, y0 + cap_bottom * line_h
        edges = [lo + (hi - lo) * k / max(1, round((hi - lo) / band)) for k in range(round((hi - lo) / band) + 1)]
        for k in range(len(edges) - 1):
            a, b = edges[k], edges[k + 1]
            t = ((a + b) / 2 - lo) / (hi - lo)
            # The first and last band reach far out, for accents and the
            # bits of letters past the capitals; each band overlaps the next
            # a little, so their smoothed edges leave no gap.
            a = a - reach if k == 0 else a
            b = b + reach if k == len(edges) - 2 else b + canvas[1] / 1920
            corners = [_turn(x, y, cx, cy, angle) for x, y in
                       ((cx - reach, a), (cx + reach, a), (cx + reach, b), (cx - reach, b))]
            shape = "m {} {} l {} {} {} {} {} {}".format(*[v for c in corners for v in c])
            out.append(
                f"Dialogue: 4,0:00:00.00,{end},Banner,,0,0,0,,"
                f"{{{at}\\bord0\\shad0\\clip({shape})\\1c{_mix(stops, t)}}}{words}"
            )
    return out


def _events(
    banner: Banner, canvas: tuple[int, int], style_lines: list[str], style: dict | None = None
) -> list[str]:
    """The box under the words, when there is a box."""
    out = []
    if any(line.startswith("Style: BannerBox,") for line in style_lines):
        out.append(_event(banner, canvas, "BannerBox", 2))
    stops = gradient_stops(style)
    if len(stops) > 1:
        out.extend(_gradient_events(banner, canvas, stops, style))
    else:
        out.append(_event(banner, canvas, "Banner", 3))
    return out


_MINIMAL_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ensure_banner(
    ass_path: Path | None,
    target: Path,
    banner: Banner,
    canvas: tuple[int, int] = (1080, 1920),
    style: dict | None = None,
) -> Path:
    """Merge the banner into the clip's ASS file, or write one with only the
    banner to `target` when there are no captions. Returns the file to burn."""
    styles = _style_lines(banner, canvas, style)
    line = "\n".join(styles)
    event = "\n".join(_events(banner, canvas, styles, style))
    if ass_path is not None and ass_path.exists():
        content = ass_path.read_text(encoding="utf-8")
        content = content.replace("\n[Events]", f"\n{line}\n\n[Events]", 1)
        content = content.rstrip("\n") + "\n" + event + "\n"
        ass_path.write_text(content, encoding="utf-8")
        return ass_path
    target.write_text(
        _MINIMAL_HEADER.format(w=canvas[0], h=canvas[1], style=line) + event + "\n",
        encoding="utf-8",
    )
    return target


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"
