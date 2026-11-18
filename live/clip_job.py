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
from pathlib import Path

from core.models import ClipCandidate


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
    vid = payload["video_id"]
    channel = payload.get("channel", "")
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
    db.upsert_video(vid, channel_id=f"twitch:{channel}", title=f"{stream_title} (ao vivo)",
                    channel_name=channel, duration=duration)

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
            meta = generate_metadata_batch([candidate], segments, stream_title, llm)[0]
        except Exception as e:
            print(f"      Title from the model failed ({e}); using the stream's title")
    if meta is None or not meta.title:
        meta = ClipMetadata(title=stream_title[:90], description=stream_title, hashtags=[])

    opts: dict = {}
    if payload.get("caption_style"):
        opts["caption_style"] = payload["caption_style"]
    style = opts.get("caption_style") or cfg["clips"].get("caption_style") or {}
    if style.get("title_banner") and meta.title:
        opts["title_text"] = meta.title

    clip_dir = (data_dir / "clips" / pipeline._safe_name(channel, "unknown-channel")
                / f"ao vivo [{vid}]")
    final_path, opts_json = pipeline._render_files(source, candidate, segments, clip_dir, cfg,
                                                   opts or None, lang)
    pipeline._register_clip(db, vid, candidate, final_path, meta, opts_json, cfg)
    db.set_video_status(vid, "done")
