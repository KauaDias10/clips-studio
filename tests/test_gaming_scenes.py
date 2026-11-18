"""A layout per stretch when the stream changes scene mid-clip (gaming/scenes.py)."""

from gaming import compose, scenes
from gaming.detect import Track
from gaming.layout import OUT_H, OUT_W, Element, Plan

W, H = 1280, 720
CAM = (0.8, 0.05, 0.18, 0.3)


def _track(times, box):
    return Track(times=list(times), person=[box] * len(times), seen=[(t, box) for t in times],
                 head_cx=[(box[0] + box[2]) / 2 / W] * len(times))


def test_labels_follow_who_is_on_screen():
    in_cam = (1040, 50, 1240, 250)                 # inside the webcam box
    big = (300, 0, 1000, 720)                      # the camera filling the frame
    tracks = {1: _track([k / 2 for k in range(0, 20)], in_cam), 2: _track([k / 2 for k in range(20, 40)], big)}
    labels = scenes._labels(tracks, CAM, W, H, 40, big={2})
    assert labels[:20] == ["cam"] * 20 and labels[20:] == ["camera"] * 20


def test_a_missed_detection_is_not_a_scene():
    labels = ["cam"] * 10 + ["other"] + ["cam"] * 10
    assert scenes._smooth(labels) == ["cam"] * 21
    runs = scenes._runs(scenes._smooth(["cam"] * 10 + ["camera"] * 10))
    assert [r[0] for r in runs] == ["cam", "camera"]


def test_merge_joins_equal_neighbours_and_absorbs_flashes():
    s = [scenes.Stretch(0, 10, "cam", CAM), scenes.Stretch(10, 20, "cam", CAM),
         scenes.Stretch(20, 21, "game"), scenes.Stretch(21, 40, "camera")]
    out = scenes.merge(s)
    assert [(x.kind, x.start, x.end) for x in out] == [("cam", 0, 21), ("camera", 21, 40)]


def test_camera_crop_is_9x16_on_the_head_and_inside_the_frame():
    x, y, w, h = scenes.camera_crop((640, 150, 500), W, H)
    assert (y, h) == (0, 720) and abs(w / h - OUT_W / OUT_H) < 0.01
    assert abs((x + w / 2) - 640) <= 2
    x, _y, w, _h = scenes.camera_crop((1270, 150, 500), W, H)
    assert x + w <= W                               # a head at the edge keeps the crop inside


def test_one_encode_switches_layouts_at_the_stretch_times():
    a = Plan("split", (Element("game", (0, 0, 1280, 720), (0, 0, OUT_W, OUT_H)),))
    b = Plan("camera", (Element("cam", (236, 0, 404, 720), (0, 0, OUT_W, OUT_H)),))
    graph = compose.stretches_graph([(a, 0.0, 36.5), (b, 36.5, 59.5)], ass_name="c.ass")
    assert "overlay=0:0:enable='between(t,36.500,59.500)'" in graph
    assert graph.count("subtitles=") == 1 and graph.count("[v]") >= 2
    assert "[s0e0]" in graph and "[s1e0]" in graph          # each layout's own labels
    # One plan renders exactly as before.
    assert compose.filter_graph(a).startswith("[0:v]crop=2:2:0:0")
