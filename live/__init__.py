"""Live clipping: watch a stream while it is live and make clips as it goes.

- recorder.py keeps the last few minutes of the stream on disk.
- chat.py reads the channel's chat (anonymously: no login needed).
- moments.py decides when something happened: chat bursting above its own
  normal rate (analysis/chat_moments.py, the same reading the VOD path uses),
  viewers typing !clip, and clips viewers made on Twitch.
- session.py ties them together and queues a "live_clip" job per moment.
- clip_job.py is that job: transcribe the few seconds, render one clip.
"""
