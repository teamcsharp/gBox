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
FIRST_FRAME_LIMIT_S = 30.0  # end a response that never got a frame; the client watchdog reattaches it
ALIVE_CHECK_S = 1.0    # session-row lookups (a store query) at most this often, not once per frame


def part(frame: bytes) -> bytes:
    return b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"


def mjpeg_parts(lv: dict, *, keepalive: float = KEEPALIVE_S, idle_limit: float = IDLE_LIMIT_S,
                first_frame_limit: float = FIRST_FRAME_LIMIT_S, alive: Callable[[], bool] = lambda: True,
                clock: Callable[[], float] = time.monotonic, wait: float = 1.0) -> Iterator[bytes]:
    """Yield one multipart part per new frame in `lv` ({"cond", "frame", "seq"}), plus keepalive repeats.

    Starlette runs this generator in a worker thread and only notices a closed connection between items, so while
    no frame exists it yields b"" (sends nothing) after every `wait`: an abandoned or reattached view frees its
    thread within a second instead of holding it until a limit runs out."""
    seq, last_new = -1, clock()
    last_sent, check_at = last_new, last_new
    while clock() - last_new < (idle_limit if seq != -1 else first_frame_limit):
        if clock() >= check_at:
            if not alive():
                return
            check_at = clock() + ALIVE_CHECK_S
        with lv["cond"]:
            lv["cond"].wait_for(lambda: lv["seq"] != seq and lv["frame"] is not None, min(wait, keepalive))
            frame, current = lv["frame"], lv["seq"]
        now = clock()
        if frame is None:
            yield b""
        elif current != seq:
            seq, last_new, last_sent = current, now, now
            yield part(frame)
        elif now - last_sent >= keepalive:
            last_sent = now
            yield part(frame)
