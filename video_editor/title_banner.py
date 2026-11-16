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
    lines.append(
        f"Style: Banner,{font},{banner.size},{text},{text},{outline_colour},&H80000000,"
        f"-1,{italic},0,0,100,100,{spacing:g},{angle:g},1,{outline:g},{shadow:g},5,40,40,0,1"
    )
    return lines


def _event(banner: Banner, canvas: tuple[int, int], name: str = "Banner", layer: int = 3) -> str:
    # The whole clip: an end past the file is simply never reached.
    return (
        f"Dialogue: {layer},0:00:00.00,{_ass_time(banner.seconds) if banner.seconds > 0 else '9:59:59.00'},{name},,0,0,0,,"
        f"{{\\an5\\pos({banner.center_x},{banner.center_y})}}{banner.text}"
    )


def _events(banner: Banner, canvas: tuple[int, int], style_lines: list[str]) -> list[str]:
    """The box under the words, when there is a box."""
    out = []
    if any(line.startswith("Style: BannerBox,") for line in style_lines):
        out.append(_event(banner, canvas, "BannerBox", 2))
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
    event = "\n".join(_events(banner, canvas, styles))
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
