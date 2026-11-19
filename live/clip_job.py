"""The live_clip job: one moment cut from a live stream, made like any clip.

The seconds were already cut from the live buffer into
data/downloads/<video_id>.mp4, so the clip is a normal clip of a short video
afterwards: the editor, re-render, captions, the title banner and publishing
all work on it as on any other.

No model picks the moment (the audience did), so the only model call is the
title, and a failed one falls back to the stream's title.
"""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path

from core.models import ClipCandidate


# The gaming settings found for each live channel, kept while the app runs.
_GAMING: dict[str, dict] = {}


def forget_layout(channel: str) -> None:
    """A live started again (maybe with another layout): look again."""
    _GAMING.pop(channel, None)


def _probe_seconds(path: Path) -> float:
    import subprocess

    from core.binaries import ffprobe

    out = subprocess.run([ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def run_live_clip(db, config: dict, payload: dict) -> None:
    from analysis.metadata import ClipMetadata, generate_metadata_batch
    from core import pipeline
    from transcription.transcriber import detected_language

    cfg = copy.deepcopy(config)
    data_dir = Path(cfg["paths"]["data_dir"])
    vid = payload["video_id"]                 # this moment's seconds
    gid = payload.get("group_id") or vid      # the live's video they join (live/group.py)
    channel = payload.get("channel", "")
    key = payload.get("channel_key") or channel          # live/group.py, the layout cache
    platform = payload.get("platform", "twitch")
    source = data_dir / "downloads" / f"{vid}.mp4"
    if not source.exists():
        raise FileNotFoundError(f"Live seconds missing: {source}")
    if "captions" in payload:
        cfg["clips"]["captions"] = bool(payload["captions"])
    if payload.get("gaming"):
        cfg["clips"]["gaming"] = True
        if payload.get("gaming_layout"):
            cfg["clips"]["gaming_layout"] = payload["gaming_layout"]

    stream_title = payload.get("stream_title") or f"{channel} ao vivo"
    duration = _probe_seconds(source)
    def save_video(video_id: str, seconds: float) -> None:
        db.upsert_video(video_id, channel_id=f"{platform}:{channel}", title=f"{stream_title} (ao vivo)",
                        channel_name=channel, duration=seconds)


    start = max(0.0, float(payload.get("start", 0)))
    end = min(float(payload.get("end", duration)), duration or float(payload.get("end", 0)))
    if end - start < 3:
        raise RuntimeError("The live seconds came out too short to clip.")
    print(f"[live] {channel}: {payload.get('reason', '')} ({end - start:.0f}s)")

    forced = (cfg.get("content_language") or "auto").lower()
    segments = pipeline.transcribe(
        source, vid, data_dir / "transcripts",
        model_size=cfg["whisper"]["model"], device=cfg["whisper"]["device"],
        language=None if forced == "auto" else forced,
        online=pipeline.online_transcription(cfg),
    )
    lang = forced if forced != "auto" else detected_language(vid, data_dir / "transcripts")

    strength = {"viewer_clip": 90, "command": 80}.get(payload.get("kind"), 70)
    candidate = ClipCandidate(start, end, strength, hook=payload.get("title") or "",
                              reason=payload.get("reason", ""), source="signal",
                              subscores={"live": payload.get("kind", "chat")})

    meta = None
    if payload.get("title"):
        meta = ClipMetadata(title=payload["title"], description=stream_title, hashtags=[])
    else:
        try:
            llm = pipeline.create_backend(pipeline._with_usable_model(cfg["llm"]))
            meta = generate_metadata_batch(
                [candidate], segments, stream_title, llm,
                language=(cfg.get("clips", {}).get("title_language") or "").strip() or lang,
            )[0]
        except Exception as e:
            print(f"      Title from the model failed ({e}); using the stream's title")
    if meta is None or not meta.title:
        meta = ClipMetadata(title=stream_title[:90], description=stream_title, hashtags=[])

    owner = vid
    if gid != vid:
        # Into the live's one video first: its seconds and transcript go on
        # the end of the live's, and the clip is made from there at the
        # times it has there (so every clip of the live has its own times
        # and file). Should that fail (the file held open too long), the
        # clip stays a video of its own rather than lost.
        from live.group import adopt, probe_seconds, touch

        try:
            offset = adopt(data_dir, gid, vid)
            source = data_dir / "downloads" / f"{gid}.mp4"
            candidate = dataclasses.replace(candidate, start=candidate.start + offset, end=candidate.end + offset)
            segments = pipeline.transcribe(
                source, gid, data_dir / "transcripts",
                model_size=cfg["whisper"]["model"], device=cfg["whisper"]["device"],
                language=None if forced == "auto" else forced,
                online=pipeline.online_transcription(cfg),
            )
            touch(data_dir, key, gid)
            owner = gid
            duration = probe_seconds(source)
        except Exception as e:
            print(f"      Could not add the clip to the live's video ({e}); keeping it on its own")
    save_video(owner, duration)

    opts: dict = {}
    if payload.get("caption_style"):
        opts["caption_style"] = payload["caption_style"]
    style = opts.get("caption_style") or cfg["clips"].get("caption_style") or {}
    if style.get("title_banner") and meta.title:
        opts["title_text"] = meta.title

    clip_dir = (data_dir / "clips" / pipeline._safe_name(channel, "unknown-channel")
                / f"ao vivo [{owner}]")
    if cfg["clips"].get("gaming"):
        # Gaming / Reaction: the webcam over the game, as for a video. Found
        # once per live (or the layout set up before starting), then reused;
        # each clip still follows scene changes (gaming/scenes.py).
        g = _GAMING.get(key)
        if g is None:
            g = pipeline._gaming_prepare(source, [candidate], clip_dir, cfg) or {}
            if (g.get("gaming") or {}).get("cam") or (g.get("gaming") or {}).get("by") == "user":
                _GAMING[key] = g
        opts.update(g)
    final_path, opts_json = pipeline._render_files(source, candidate, segments, clip_dir, cfg,
                                                   opts or None, lang)
    if cfg["clips"].get("gaming") and key not in _GAMING:
        # The webcam this clip found on its own, for the rest of the live.
        import json

        try:
            used = (json.loads(opts_json or "{}").get("gaming") or {}).get("used_cam")
        except ValueError:
            used = None
        if used:
            _GAMING[key] = {"gaming": {**(opts.get("gaming") or {}), "cam": used, "by": "video"}}
    pipeline._register_clip(db, owner, candidate, final_path, meta, opts_json, cfg)
    db.set_video_status(owner, "done")
