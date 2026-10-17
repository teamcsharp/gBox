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


# --- stream health (docs/stream-stability.md) --------------------------------------------------------------------
STALL_LOG_S = 2.0      # a gap this long between two source frames is recorded and logged with wall-clock times
STALL_KEEP = 30        # stalls / encoder events kept per session
EVENT_KEYS = ("kind", "at", "stream", "silent_s", "gap_s", "restart", "returncode")


def _wall(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def note_frame(lv: dict, now: float | None = None, log: Callable[[str], None] = print) -> dict | None:
    """Call with lv["cond"] held, before storing a new source frame: records a stall when the previous frame is
    STALL_LOG_S or more old (the operator saw a frozen picture for that long). Returns the stall, if any."""
    now = time.time() if now is None else now
    prev = lv.get("ts") or 0
    if not prev or now - prev < STALL_LOG_S:
        return None
    stall = {"kind": "source_stall", "start": _wall(prev), "end": _wall(now), "seconds": round(now - prev, 2)}
    lv.setdefault("stalls", []).append(stall)
    del lv["stalls"][:-STALL_KEEP]
    log(f"gBox stream: {lv.get('sid', '?')} no new frame for {stall['seconds']} s "
        f"({stall['start']} -> {stall['end']})")
    return stall


def note_event(lv: dict, event: dict, log: Callable[[str], None] = print) -> dict:
    """An encoder event the worker reported (stall, exit, restart, slow frames); unknown keys are dropped."""
    kept = {k: str(event[k])[:80] if isinstance(event[k], str) else event[k] for k in EVENT_KEYS if k in event}
    kept["received"] = _wall(time.time())
    lv.setdefault("events", []).append(kept)
    del lv["events"][:-STALL_KEEP]
    log(f"gBox stream: {lv.get('sid', '?')} worker reported {kept.get('kind')} at {kept.get('at')}: "
        + ", ".join(f"{k}={v}" for k, v in kept.items() if k not in ("kind", "at", "received")))
    return kept


def health(lv: dict, state: str | None, now: float | None = None) -> dict:
    """What the client stream watchdog needs to tell a frozen picture from a quiet scene: the source frame age."""
    now = time.time() if now is None else now
    ts = lv.get("ts") or 0
    return {"state": state or "missing", "seq": lv.get("seq", 0), "age_s": round(now - ts, 2) if ts else None,
            "uploads": lv.get("uploads", 0),
            "stalls": list(lv.get("stalls") or [])[-10:], "events": list(lv.get("events") or [])[-10:]}
