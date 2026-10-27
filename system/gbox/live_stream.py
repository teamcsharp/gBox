"""Operator MJPEG view of a live session.

A multipart response that ends leaves a browser <img> on its last picture (or black when it ended before the first
frame) until the view is rebuilt. The generator therefore re-sends the newest frame while the source pauses (state
saves, emulator pause, upload reconnects) and only ends when the session is gone or the source stayed silent for a
long time; the client stream watchdog (clients/web/viz/stream-watchdog.js) reconnects after either outcome.
"""
from __future__ import annotations

import asyncio
import collections
import inspect
import time
from typing import Callable, Iterator

KEEPALIVE_S = 2.0      # re-send the newest frame at least this often while no new one arrives
IDLE_LIMIT_S = 600.0   # end the response after this long without any new source frame
FIRST_FRAME_LIMIT_S = 30.0  # end a response that never got a frame; the client watchdog reattaches it
ALIVE_CHECK_S = 1.0    # session-row lookups (a store query) at most this often, not once per frame


class BackgroundCheck:
    """Await the first authorization/state read, then refresh it without putting store latency on each viewer.

    One pending refresh is retained even if a database lock lasts several poll intervals. Confirmed false state
    remains false; a failed refresh keeps the last successful value until another read can complete.
    """
    def __init__(self, check):
        self.check, self.value, self.pending = check, None, None

    async def __call__(self):
        if self.value is None:
            self.value = await self.check()
        elif self.value and (self.pending is None or self.pending.done()):
            self.pending = asyncio.create_task(self._refresh())
        return self.value

    async def _refresh(self):
        try:
            self.value = await self.check()
        except Exception:
            pass

    def close(self):
        if self.pending is not None:
            self.pending.cancel()                       # reads have no late write that can resurrect a viewer


class BackgroundLease:
    """Coalesce renewable watch writes off the frame path, and clear only after an in-flight renewal finishes."""
    def __init__(self, renew, clear):
        self._renew, self._clear, self.pending, self.closed = renew, clear, None, False

    def renew(self):
        if self.closed or self.pending is not None and not self.pending.done():
            return False
        self.pending = asyncio.create_task(self._run_renew())
        return True

    async def _run_renew(self):
        try:
            await self._renew()
        except Exception:
            pass

    async def close(self):
        self.closed = True
        pending = self.pending
        async def clear_after_renew():
            if pending is not None:
                await pending
            await self._clear()
        # A cancelled HTTP body must not cancel the clear or allow a late put to recreate a closed watch lease.
        cleanup = asyncio.create_task(clear_after_renew())
        await asyncio.shield(cleanup)


def part(frame: bytes) -> bytes:
    return b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"


def notify_frame(lv: dict) -> None:
    """Wake existing readers after publishing a frame, with lv['cond'] held.

    Async viewers retain only an event and the shared newest JPEG. A slow HTTP consumer never accumulates a
    private queue of old pictures. The legacy condition still serves synchronous/internal consumers.
    """
    lv["cond"].notify_all()
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    for loop, event in tuple(lv.get("async_waiters", ())):
        try:
            if loop is current_loop:
                event.set()
            else:
                loop.call_soon_threadsafe(event.set)
        except RuntimeError:                            # the disconnected viewer's loop already closed
            pass


async def async_mjpeg_parts(lv: dict, *, keepalive: float = KEEPALIVE_S, idle_limit: float = IDLE_LIMIT_S,
                            first_frame_limit: float = FIRST_FRAME_LIMIT_S, alive=lambda: True,
                            clock=time.monotonic, wait: float = 1.0, max_fps: float = 0.0, sleep=asyncio.sleep):
    """Stream the newest available frame without dispatching a thread for every JPEG.

    HTTP backpressure suspends this generator. On resumption it reads the shared newest frame, dropping any
    intermediate pictures rather than replaying a backlog. Cancellation unregisters the viewer immediately.
    ``alive`` may be async so a session lookup never blocks the serving event loop.

    ``max_fps`` caps this viewer's frame rate: the newest frame at most that often, the frames in between skipped
    (operator 2026-10-27: the PiP over Wi-Fi played for seconds, then stopped - a 57 fps source of 32 KB JPEGs needs
    ~15 Mbps per viewer; at 30 a viewer needs half of that).
    """
    event, loop = asyncio.Event(), asyncio.get_running_loop()
    waiter = (loop, event)
    seq, last_new = -1, clock()
    last_sent, check_at = last_new, last_new
    gap = 1.0 / max_fps if max_fps and max_fps > 0 else 0.0
    with lv["cond"]:
        lv.setdefault("async_waiters", set()).add(waiter)
    try:
        while clock() - last_new < (idle_limit if seq != -1 else first_frame_limit):
            if clock() >= check_at:
                running = alive()
                if inspect.isawaitable(running):
                    running = await running
                if not running:
                    return
                check_at = clock() + ALIVE_CHECK_S
            with lv["cond"]:
                event.clear()                           # clear and snapshot together: no lost frame wakeup
                frame, current = lv["frame"], lv["seq"]
            now = clock()
            if frame is not None and current != seq:
                if gap and seq >= 0 and now - last_sent < gap:
                    await sleep(gap - (now - last_sent))     # the cap: then the newest frame, not this one
                    continue
                with lv["cond"]:
                    lv["viewer_frames"] = lv.get("viewer_frames", 0) + 1
                    if seq >= 0:
                        lv["viewer_skips"] = lv.get("viewer_skips", 0) + max(0, current - seq - 1)
                seq, last_new, last_sent = current, now, now
                yield part(frame)
                continue
            if frame is not None and now - last_sent >= keepalive:
                last_sent = now
                yield part(frame)
                continue
            try:
                await asyncio.wait_for(event.wait(), min(wait, keepalive))
            except asyncio.TimeoutError:
                pass
    finally:
        with lv["cond"]:
            lv["async_waiters"].discard(waiter)


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


def meter(lv: dict, now: float, source: str) -> None:
    """Call with lv["cond"] held, before a new source frame is stored: which path frames arrive by ("stream": the
    worker's encoder, "still": a native game's window stills) and a smoothed frame rate, for the broadcast feed list
    (gbox/broadcast.py). A long gap counts as at most 10 s so one stall does not hide the rate for minutes."""
    if source == "stream" or lv.get("source") != "stream":
        lv["source"] = source
    prev = lv.get("ts") or 0
    if prev and now > prev:
        dt = min(now - prev, 10.0)
        lv.setdefault("frame_gaps", collections.deque(maxlen=600)).append(now - prev)
        avg = lv.get("dt")
        lv["dt"] = dt if avg is None else avg + 0.1 * (dt - avg)
        lv["fps"] = 1.0 / lv["dt"] if lv["dt"] > 0 else None


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
    gaps = sorted(lv.get("frame_gaps") or ())
    pacing = ({"samples": len(gaps), "gap_p50_ms": round(gaps[(len(gaps) - 1) // 2] * 1000, 2),
               "gap_p95_ms": round(gaps[int((len(gaps) - 1) * .95)] * 1000, 2),
               "gap_max_ms": round(gaps[-1] * 1000, 2), "gaps_over_100ms": sum(g > .1 for g in gaps)}
              if gaps else {"samples": 0})
    return {"state": state or "missing", "seq": lv.get("seq", 0), "age_s": round(now - ts, 2) if ts else None,
            "uploads": lv.get("uploads", 0),
            "pacing": pacing,
            "delivery": {"viewers": len(lv.get("async_waiters") or ()), "frames": lv.get("viewer_frames", 0),
                         "skipped_frames": lv.get("viewer_skips", 0)},
            "stalls": list(lv.get("stalls") or [])[-10:], "events": list(lv.get("events") or [])[-10:]}
