"""Live clipping routes: start / stop watching a channel, and its status.

Starting and stopping take the desktop session secret, like the other
routes that make the app act on its own (connected accounts, clip updates).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from plugins import session


class StartBody(BaseModel):
    channel: str = Field(min_length=2, max_length=200)
    options: dict = Field(default_factory=dict)


ALLOWED_OPTIONS = {"pre_seconds", "post_seconds", "min_votes", "chat_bursts", "max_clips", "buffer_seconds",
                   "height", "caption_style", "captions", "gaming", "gaming_layout", "audio_peaks"}


def install(app, *, config: dict, data_dir: Path, db, worker, broadcaster, accounts, session_secret: str):
    from live.platforms import parse_target
    from live.session import LiveSession

    sessions: dict[str, LiveSession] = {}
    lock = threading.Lock()

    def require_session(given: str | None = Header(default=None, alias=session.HEADER)):
        if not session.matches(session_secret, given):
            raise HTTPException(403, f"{session.HEADER} is required to start or stop live clipping.")

    def queue_clip(payload: dict) -> int:
        d = db()
        try:
            job = d.add_job("live_clip", json.dumps(payload), video_id=payload["video_id"],
                            title=f"{payload['channel']} ao vivo: {payload.get('reason', '')}"[:200])
        finally:
            d.close()
        broadcaster.publish({"type": "queue"})
        worker.notify()
        return job

    def youtube_credentials():
        """Fresh credentials of the default connected YouTube account, for
        reading a live's chat (read-only). None when none is connected."""
        from server import youtube_service as service

        d = db()
        try:
            channel_id = service.default_channel_id(d)
        finally:
            d.close()
        return service.make_publisher(config, data_dir, channel_id=channel_id).credentials()

    def has_youtube() -> bool:
        try:
            youtube_credentials()
            return True
        except Exception:
            return False

    @app.get("/live")
    def live_status():
        with lock:
            return {"sessions": [s.status() for s in sessions.values()]}

    @app.post("/live/start", dependencies=[Depends(require_session)])
    def live_start(body: StartBody):
        try:
            target = parse_target(body.channel)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        name = target.key
        options = {k: v for k, v in body.options.items() if k in ALLOWED_OPTIONS}
        with lock:
            old = sessions.get(name)
            if old and old.running:
                return old.status()
            from live.clip_job import forget_layout

            forget_layout(target.slug)
            yt = youtube_credentials if target.platform == "youtube" and has_youtube() else None
            s = LiveSession(target, config, data_dir, queue_clip, accounts=accounts,
                            publish=broadcaster.publish, options=options, youtube_credentials=yt)
            sessions[name] = s
        s.start()
        return s.status()

    @app.post("/live/{channel}/stop", dependencies=[Depends(require_session)])
    def live_stop(channel: str):
        with lock:
            # "kick:xqc", or a bare Twitch name as before.
            want = channel.lower()
            s = next((v for k, v in sessions.items() if k.lower() in (want, f"twitch:{want}")), None)
        if s is None:
            raise HTTPException(404, "That channel isn't being clipped live.")
        s.stop()
        return s.status()

    @app.on_event("shutdown")
    def _stop_all():
        with lock:
            for s in sessions.values():
                s.stop()

    return sessions
