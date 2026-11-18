"""A layout per stretch of a clip, for a stream that changes scene mid-clip.

One decision per clip (gaming/run.py) is right while the stream keeps one
scene. When the streamer switches scene inside a clip (to their camera
filling the frame, or the webcam moved to another corner), the clip's
webcam box would show an empty corner from then on. So the clip is split
where the picture changes (FFmpeg's scene score), and each stretch is asked
where the streamer is:

- at the clip's webcam            -> the clip's layout, as it is
- on a camera filling the frame   -> that camera, framed 9:16 on their head
- in a webcam somewhere else      -> the layout, with the webcam there
- nowhere                         -> the game alone

Neighbouring stretches with the same answer are one. A clip that never
changes is rendered exactly as before; one that does is still one encode:
every stretch's layout is composed over the whole clip and shown only
between its times (gaming/compose.render_stretches).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.binaries import ffmpeg

# FFmpeg scene score that counts as a cut. Low on purpose: a browser page
# switching to the streamer's camera, both dark, scored 0.15 (measured). Extra
# cuts cost a look each and merge back when nothing changed.
SCENE = 0.12
MIN_STRETCH = 2.5       # seconds: shorter stretches join their neighbour
CHECK_FPS = 2.0         # people sampled this often for the stretches
PRESENT = 0.5           # share of a stretch's samples someone must be seen in
FRAMES = 4              # frames per stretch for a moved webcam
# A webcam found somewhere else is only believed at webcam size: a character
# standing still in a trailer measured 0.34 of the frame.
MOVED_MAX_AREA = 0.15


@dataclass
class Stretch:
    start: float
    end: float
    kind: str = "cam"           # cam | camera | moved | game
    cam: tuple | None = None    # the webcam box for cam / moved
    head: tuple | None = None   # camera: (centre x, top, chin) px

    def same(self, other: "Stretch") -> bool:
        if self.kind != other.kind:
            return False
        if self.kind == "moved":
            return _near(self.cam, other.cam)
        return True


def _near(a, b, tol: float = 0.05) -> bool:
    return a is not None and b is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


# ---- where the picture changes ----------------------------------------------------


def cuts(clip: Path, threshold: float = SCENE) -> list[float]:
    """Times FFmpeg's scene score jumps over `threshold`, on a small copy of
    the picture (fast: no frames through Python)."""
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostats", "-i", str(clip), "-an",
         "-vf", f"scale=160:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace",
    )
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", result.stderr)]


# ---- who is where in a stretch -----------------------------------------------------


def _seen(track, a: float, b: float) -> list:
    """The person boxes of a track within [a, b)."""
    return [p for t, p in zip(track.times, track.person) if a <= t < b]


def _inside(box_px, cam_norm, w: int, h: int) -> float:
    x1, y1, x2, y2 = box_px
    cx, cy, cw, ch = cam_norm[0] * w, cam_norm[1] * h, cam_norm[2] * w, cam_norm[3] * h
    ix = max(0.0, min(x2, cx + cw) - max(x1, cx))
    iy = max(0.0, min(y2, cy + ch) - max(y1, cy))
    area = max(1.0, (x2 - x1) * (y2 - y1))
    return ix * iy / area


def _heads(track, a: float, b: float) -> list:
    return [hb for t, hb in track.seen if a <= t < b]


def merge(stretches: list[Stretch]) -> list[Stretch]:
    out: list[Stretch] = []
    for s in stretches:
        if out and out[-1].same(s):
            out[-1].end = s.end
        else:
            out.append(s)
    # A stretch too short to be a scene (a flash, a transition) takes its
    # neighbour's layout.
    i = 0
    while len(out) > 1 and i < len(out):
        if out[i].end - out[i].start < MIN_STRETCH:
            j = i - 1 if i > 0 else i + 1
            keep = out[j]
            keep.start, keep.end = min(keep.start, out[i].start), max(keep.end, out[i].end)
            del out[i]
            i = 0
            continue
        i += 1
    return out


def _labels(tracks: dict, cam, w: int, h: int, n: int, big: set) -> list[str]:
    """Per sample (CHECK_FPS): "camera" (one of `big` on screen), "cam"
    (somebody in the webcam) or "other"."""
    from gaming import detect

    at = [[] for _ in range(n)]
    for tid, tr in tracks.items():
        for t, p in zip(tr.times, tr.person):
            k = int(round(t * CHECK_FPS))
            if 0 <= k < n:
                at[k].append((tid, p))
    out = []
    for people in at:
        if any(tid in big for tid, _p in people):
            out.append("camera")
        elif cam and any(_inside(p, cam, w, h) >= detect.INSIDE for _tid, p in people):
            out.append("cam")
        else:
            out.append("other")
    return out


def _smooth(labels: list[str], width: int = 5) -> list[str]:
    """Majority over `width` samples: a missed detection isn't a scene."""
    half = width // 2
    out = []
    for i in range(len(labels)):
        window = labels[max(0, i - half): i + half + 1]
        out.append(max(set(window), key=window.count) if window.count(labels[i]) * 2 <= len(window)
                   else labels[i])
    return out


def _runs(labels: list[str]) -> list[list]:
    runs: list[list] = []
    for k, lab in enumerate(labels):
        if runs and runs[-1][0] == lab:
            runs[-1][2] = k + 1
        else:
            runs.append([lab, k, k + 1])
    return runs


def _big_people(clip: Path, tracks: dict, w: int, h: int, fps: float, duration: float) -> set:
    """Tracks that are the streamer's camera filling the frame: too big for a
    webcam, staying put (a game character walks around), on screen a few
    seconds, and TalkNet sure it is them speaking. A big person TalkNet can't
    vouch for (a character in a cutscene, a face in a watched video) is not."""
    from gaming import detect

    out = set()
    for tid, tr in tracks.items():
        if len(tr.times) < MIN_STRETCH * CHECK_FPS or not tr.head_cx:
            continue
        x1, y1, x2, y2 = np.median(np.array(tr.person, dtype=float), axis=0)
        if (x2 - x1) * (y2 - y1) / (w * h) <= detect.OVERLAY_MAX_AREA:
            continue
        if float(np.std(tr.head_cx)) > 0.08:
            continue
        scored = detect.speaking_scores(clip, tracks, [tid], duration, fps)
        if scored is None:
            continue
        scores, loud = scored
        _share, conf = detect.speaking(scores[tid], loud)
        if conf is not None and conf >= detect.CAMERA_CONFIDENCE:
            out.add(tid)
    return out


def _snap(t: float, at: list[float], within: float = 1.0) -> float:
    near = [c for c in at if abs(c - t) <= within]
    return min(near, key=lambda c: abs(c - t)) if near else t


def stretches(clip: Path, cam, model_name: str, duration: float | None = None) -> list[Stretch]:
    """The clip's stretches, merged. One stretch means: render as before.

    Who is on screen is read every half second (the person detector); the
    clip is split where that changes for longer than a moment, and each cut
    is moved to the nearest picture cut (FFmpeg's scene score) when there is
    one close by. A fade between two scenes has no clear cut, so the people
    decide and the scene score only sharpens the edge."""
    import cv2

    from gaming import detect
    from video.capture import video_capture

    tracks, w, h, fps, last_t, _n = detect.sample_tracks(clip, model_name, CHECK_FPS)
    if not w:
        return []
    duration = duration or last_t
    n = max(1, int(duration * CHECK_FPS) + 1)
    big = _big_people(clip, tracks, w, h, fps, duration)
    runs = _runs(_smooth(_labels(tracks, cam, w, h, n, big)))
    # Runs too short to be a scene join the longer neighbour.
    shortest = int(MIN_STRETCH * CHECK_FPS)
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[2] - r[1] < shortest:
                j = i - 1 if i == len(runs) - 1 or (i > 0 and runs[i - 1][2] - runs[i - 1][1]
                                                    >= runs[i + 1][2] - runs[i + 1][1]) else i + 1
                lo, hi = min(r[1], runs[j][1]), max(r[2], runs[j][2])
                runs[j][1], runs[j][2] = lo, hi
                del runs[i]
                merged = []
                for x in runs:
                    if merged and merged[-1][0] == x[0]:
                        merged[-1][2] = x[2]
                    else:
                        merged.append(x)
                runs = merged
                changed = True
                break
    if len(runs) < 2:
        return [Stretch(0.0, duration, "cam" if cam else "game", tuple(cam) if cam else None)]

    at = cuts(clip)
    edges = [0.0] + [_snap(r[1] / CHECK_FPS, at) for r in runs[1:]] + [duration]

    def frames_at(times: list) -> list:
        out = []
        with video_capture(clip, required=False) as cap:
            if cap is None:
                return out
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if ok:
                    out.append(frame)
        return out

    found = []
    for (lab, _k0, _k1), a, b in zip(runs, edges[:-1], edges[1:]):
        if lab == "cam":
            found.append(Stretch(a, b, "cam", tuple(cam)))
        elif lab == "camera":
            heads = [hb for tid in big for t, hb in tracks[tid].seen if a <= t < b]
            head = None
            if heads:
                hx1, hy1, hx2, hy2 = np.median(np.array(heads, dtype=float), axis=0)
                head = ((hx1 + hx2) / 2, hy1, hy2)
            found.append(Stretch(a, b, "camera", head=head))
        else:
            # Nobody seen in the webcam for a while. With a webcam, that is
            # usually the detector missing a turned head, not a new scene: it
            # only moves for a webcam found elsewhere, at webcam size.
            frames = frames_at([a + (i + 0.5) * (b - a) / FRAMES for i in range(FRAMES)])
            moved = detect._steady_cam(frames, model_name) if len(frames) >= 3 else None
            if moved is not None and moved[2] * moved[3] > MOVED_MAX_AREA:
                moved = None
            if moved is not None and not (cam and _near(moved, cam)):
                found.append(Stretch(a, b, "moved", tuple(moved)))
            elif cam:
                found.append(Stretch(a, b, "cam", tuple(cam)))
            else:
                found.append(Stretch(a, b, "game"))
    return merge(found)


def camera_crop(head, src_w: int, src_h: int) -> tuple:
    """A 9:16 source crop around a head on a camera filling the frame, the
    head a third of the way down (where a talking-head clip keeps it)."""
    from gaming.layout import OUT_H, OUT_W

    ch = src_h
    cw = min(src_w, int(round(ch * OUT_W / OUT_H)))
    cw -= cw % 2
    cx = head[0] if head else src_w / 2
    x = int(round(min(max(0.0, cx - cw / 2), src_w - cw)))
    return (x - x % 2, 0, cw, ch - ch % 2)
