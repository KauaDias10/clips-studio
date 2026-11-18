"""Live clipping (live/): reading chat and deciding when a moment happened."""

from live.chat import parse
from live.moments import MomentDetector
from live.session import channel_name

CLASSES = {"funny": {"label": "laughing", "patterns": ["^k{4,}$"]}}


def _detector(**kw):
    return MomentDetector(classes=CLASSES, lag=6, ignore=[], **kw)


def test_chat_line_with_tags():
    line = ("@badge-info=;display-name=Fulano;tmi-sent-ts=1763460000123 "
            ":fulano!fulano@fulano.tmi.twitch.tv PRIVMSG #alanzoka :KKKKKKK que isso")
    t, who, text = parse(line)
    assert (round(t, 3), who, text) == (1763460000.123, "Fulano", "KKKKKKK que isso")
    assert parse(":tmi.twitch.tv 001 justinfan1 :Welcome") is None


def test_channel_names():
    assert channel_name("https://www.twitch.tv/Alanzoka/") == "alanzoka"
    assert channel_name("#alanzoka") == "alanzoka"
    try:
        channel_name("not a channel!")
    except ValueError:
        pass
    else:
        raise AssertionError("bad names are refused")


def _chat(now, quiet=200, burst_at=30, burst=40):
    """A steady chat, then a wall of kkkk `burst_at` seconds ago."""
    msgs = [(now - quiet + i * 2.0, f"u{i % 30}", "boa tarde") for i in range(quiet // 2)]
    msgs += [(now - burst_at + i * 0.1, f"r{i}", "kkkkkkkk") for i in range(burst)]
    return sorted(msgs)


def test_a_chat_burst_is_a_moment_dated_before_chat_reacted():
    now = 1_000_000.0
    d = _detector()
    found = d.read_chat(_chat(now), now)
    assert len(found) == 1 and found[0].kind == "chat" and "laughing" in found[0].reason
    m = found[0]
    assert now - 30 - 6 - 2 <= m.at <= now - 30 - 6 + 2         # moved back by the lag
    assert (m.start, m.end) == (m.at - 25, m.at + 8)
    assert d.read_chat(_chat(now), now) == []                   # never twice


def test_right_after_joining_nothing_counts():
    now = 1_000_000.0
    assert _detector().read_chat(_chat(now, quiet=40, burst_at=10), now) == []


def test_steady_chat_is_not_a_moment():
    now = 1_000_000.0
    msgs = [(now - 200 + i * 0.5, f"u{i % 50}", "kkkk") for i in range(400)]
    assert _detector().read_chat(msgs, now) == []


def test_clip_votes_from_different_viewers():
    now = 1_000_000.0
    base = [(now - 200 + i, "u", "oi") for i in range(150)]
    one = base + [(now - 5, "ana", "!clip"), (now - 4, "ana", "!clip"), (now - 3, "ana", "!clipe")]
    assert _detector(chat=False).read_chat(one, now) == []        # one person spamming
    three = base + [(now - 5, "ana", "!clip"), (now - 4, "bia", "!CLIPE"), (now - 3, "caio", "!clip")]
    (m,) = _detector(chat=False).read_chat(three, now)
    assert m.kind == "command" and m.at == now - 5 - 6


def test_viewer_clip_wins_over_a_nearby_chat_moment_not_yet_cut():
    now = 1_000_000.0
    d = _detector()
    (chat,) = d.read_chat(_chat(now), now)
    clip = d.viewer_clip("Abc", created=chat.at + 10, duration=30, title="QUE ISSO", creator="ana")
    assert clip is not None and clip.kind == "viewer_clip" and clip.title == "QUE ISSO"
    assert clip.start == chat.at + 10 - 32 and chat not in d.emitted
    assert d.viewer_clip("Abc", created=chat.at + 10, duration=30) is None   # same clip again
    # Once a moment was already cut, a clip of it doesn't make a second one.
    clip.extra["queued"] = True
    assert d.viewer_clip("Other", created=clip.at + 5, duration=30) is None


def test_the_live_clip_job_makes_one_clip_of_the_seconds(monkeypatch, tmp_path):
    from analysis import metadata
    from core import pipeline
    from core.models import Segment
    from live import clip_job

    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "live_x_1.mp4").write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(clip_job, "_probe_seconds", lambda p: 40.0)
    monkeypatch.setattr(pipeline, "transcribe", lambda *a, **k: [Segment(0, 40, "kkkk que isso", None)])
    monkeypatch.setattr("transcription.transcriber.detected_language", lambda *a: "pt")
    monkeypatch.setattr(pipeline, "create_backend", lambda *a: None)
    monkeypatch.setattr(pipeline, "_with_usable_model", lambda c: c)
    monkeypatch.setattr(metadata, "generate_metadata_batch",
                        lambda c, s, title, llm: [metadata.ClipMetadata("Ele caiu do prédio", "d", ["#gta"])])

    def render(source, cand, segs, clip_dir, cfg, opts, lang):
        seen.update(window=(cand.start, cand.end), opts=opts, lang=lang)
        return clip_dir / "c.mp4", "{}"

    monkeypatch.setattr(pipeline, "_render_files", render)
    monkeypatch.setattr(pipeline, "_register_clip",
                        lambda db, vid, cand, path, meta, opts, cfg: seen.update(title=meta.title, vid=vid))

    class DB:
        def upsert_video(self, vid, **kw):
            seen["video"] = (vid, kw["title"], kw["channel_name"])

        def set_video_status(self, vid, status):
            seen["status"] = status

    cfg = {"paths": {"data_dir": str(tmp_path)}, "whisper": {"model": "small", "device": "cpu"},
           "llm": {}, "clips": {"caption_style": {"title_banner": True}}}
    clip_job.run_live_clip(DB(), cfg, {"video_id": "live_x_1", "start": 4.0, "end": 37.0, "channel": "x",
                                       "reason": "chat: laughing", "kind": "chat", "stream_title": "GTA RP"})
    assert seen["window"] == (4.0, 37.0) and seen["lang"] == "pt"
    assert seen["title"] == "Ele caiu do prédio" and seen["opts"]["title_text"] == "Ele caiu do prédio"
    assert seen["video"] == ("live_x_1", "GTA RP (ao vivo)", "x") and seen["status"] == "done"
