"""A live channel's chat, read anonymously.

Twitch chat (IRC) lets anyone read a channel with a "justinfan" nick and no
password: no account, no token. Messages are kept in memory only, for the
few minutes the moment detector looks at, and never written to disk.
"""

from __future__ import annotations

import random
import socket
import threading
import time
from collections import deque

HOST, PORT = "irc.chat.twitch.tv", 6667
KEEP_SECONDS = 600


def parse(line: str):
    """(epoch seconds, author, text) for a PRIVMSG line with tags, else None."""
    # "@tags :nick!nick@nick.tmi.twitch.tv PRIVMSG #chan :text" (tags optional)
    if " PRIVMSG #" not in line:
        return None
    tags = ""
    if line.startswith("@"):
        tags, _, line = line.partition(" ")
    line = line.lstrip(":")
    who = line.split("!", 1)[0]
    _, sep, text = line.partition(" :")
    if not sep:
        return None
    sent = None
    for tag in tags.lstrip("@").split(";"):
        key, _, value = tag.partition("=")
        if key == "tmi-sent-ts" and value.isdigit():
            sent = int(value) / 1000.0
        elif key == "display-name" and value:
            who = value
    return (sent if sent is not None else time.time(), who, text.strip())


class TwitchChat:
    """Reads #channel on a background thread; reconnects when dropped."""

    def __init__(self, channel: str):
        self.channel = channel.lower().lstrip("#")
        self.messages: deque = deque()
        self.connected = False
        self.error = ""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"live-chat-{self.channel}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def since(self, t: float) -> list:
        with self._lock:
            return [m for m in self.messages if m[0] >= t]

    def _keep(self, msg) -> None:
        with self._lock:
            self.messages.append(msg)
            cutoff = time.time() - KEEP_SECONDS
            while self.messages and self.messages[0][0] < cutoff:
                self.messages.popleft()

    def _run(self) -> None:
        wait = 2.0
        while not self._stop.is_set():
            try:
                self._session()
                wait = 2.0
            except OSError as e:
                self.error = str(e)
            self.connected = False
            if self._stop.wait(wait):
                break
            wait = min(wait * 2, 60.0)

    def _session(self) -> None:
        sock = socket.create_connection((HOST, PORT), timeout=30)
        try:
            nick = f"justinfan{random.randint(10000, 99999)}"
            for line in ("CAP REQ :twitch.tv/tags", "PASS SCHMOOPIIE", f"NICK {nick}", f"JOIN #{self.channel}"):
                sock.sendall((line + "\r\n").encode())
            self.connected, self.error = True, ""
            buf = b""
            while not self._stop.is_set():
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    sock.sendall(b"PING :tmi.twitch.tv\r\n")
                    continue
                if not data:
                    return
                buf += data
                *lines, buf = buf.split(b"\r\n")
                for raw in lines:
                    line = raw.decode("utf-8", "replace")
                    if line.startswith("PING"):
                        sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                        continue
                    msg = parse(line)
                    if msg:
                        self._keep(msg)
        finally:
            sock.close()
