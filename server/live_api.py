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
                   "height", "caption_style", "captions", "gaming", "gaming_layout"}


def install(app, *, config: dict, data_dir: Path, db, worker, broadcaster, accounts, session_secret: str):
    from live.session import LiveSession, channel_name

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

    @app.get("/live")
    def live_status():
        with lock:
            return {"sessions": [s.status() for s in sessions.values()]}

    @app.post("/live/start", dependencies=[Depends(require_session)])
    def live_start(body: StartBody):
        try:
            name = channel_name(body.channel)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        options = {k: v for k, v in body.options.items() if k in ALLOWED_OPTIONS}
        with lock:
            old = sessions.get(name)
            if old and old.running:
                return old.status()
            s = LiveSession(name, config, data_dir, queue_clip, accounts=accounts,
                            publish=broadcaster.publish, options=options)
            sessions[name] = s
        s.start()
        return s.status()

    @app.post("/live/{channel}/stop", dependencies=[Depends(require_session)])
    def live_stop(channel: str):
        with lock:
            s = sessions.get(channel.lower())
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
