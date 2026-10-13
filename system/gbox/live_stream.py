"""Operator MJPEG view of a live session.

A multipart response that ends leaves a browser <img> on its last picture (or black when it ended before the first
frame) until the view is rebuilt. The generator therefore re-sends the newest frame while the source pauses (state
saves, emulator pause, upload reconnects) and only ends when the session is gone or the source stayed silent for a
long time; the client stream watchdog (clients/web/viz/stream-watchdog.js) reconnects after either outcome.
"""
from __future__ import annotations

import time
from typing import Callable, Iterator

KEEPALIVE_S = 2.0      # re-send the newest frame at least this often while no new one arrives
IDLE_LIMIT_S = 600.0   # end the response after this long without any new source frame


def part(frame: bytes) -> bytes:
    return b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"


def mjpeg_parts(lv: dict, *, keepalive: float = KEEPALIVE_S, idle_limit: float = IDLE_LIMIT_S,
                alive: Callable[[], bool] = lambda: True, clock: Callable[[], float] = time.monotonic,
                wait: float = 1.0) -> Iterator[bytes]:
    """Yield one multipart part per new frame in `lv` ({"cond", "frame", "seq"}), plus keepalive repeats."""
    seq, last_new = -1, clock()
    last_sent = last_new
    while alive() and clock() - last_new < idle_limit:
        with lv["cond"]:
            lv["cond"].wait_for(lambda: lv["seq"] != seq and lv["frame"] is not None, min(wait, keepalive))
            frame, current = lv["frame"], lv["seq"]
        now = clock()
        if frame is None:
            continue
        if current != seq:
            seq, last_new, last_sent = current, now, now
            yield part(frame)
        elif now - last_sent >= keepalive:
            last_sent = now
            yield part(frame)
