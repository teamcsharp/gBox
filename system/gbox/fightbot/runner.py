"""The frame-synced fight loop: one engine tick per game frame, keys out through a Sender.

The game's frame field (a counter, or a millisecond tick the title converts) is polled every POLL_S; when it moves the
world is read once (one batched RAM read) and ticked. A read that lands mid-frame is fine: the game wrote its frame
before advancing the clock. Frames the loop never saw are counted (frames_skipped): the reaction-latency figures are
only as good as that count is small."""
from __future__ import annotations

import threading
import time

from .title import DIRS

POLL_S = 0.0005
STALL_S = 5.0


class Sender:
    """Holds the wanted keys: only changes are sent, buttons up before directions, directions down before buttons.
    threaded: for a send that blocks (xdotool: 17-35 ms a call on the Spark), a thread sends the newest wanted set
    and the frame loop never waits; DOA3's virtual pad costs microseconds and sends inline."""

    def __init__(self, send, threaded: bool = False):
        self.send, self.threaded = send, threaded
        self.held: frozenset = frozenset()
        self.want: frozenset = frozenset()
        self.sent = 0
        self.errors = 0
        self.cond = threading.Condition()
        self.done = False
        if threaded:
            threading.Thread(target=self._loop, daemon=True, name="fightbot-sender").start()

    def _apply(self, keys: frozenset):
        up = sorted(self.held - keys, key=lambda k: (k in DIRS, k))
        down = sorted(keys - self.held, key=lambda k: (k not in DIRS, k))
        rows = [{"key": k, "down": False} for k in up] + [{"key": k, "down": True} for k in down]
        if rows:
            try:
                self.send(rows)
                self.sent += 1
            except Exception:                          # noqa: BLE001 - one lost send; the next change resends
                self.errors += 1
                return
        self.held = keys

    def _loop(self):
        while True:
            with self.cond:
                while self.want == self.held and not self.done:
                    self.cond.wait(0.5)
                if self.done and self.want == self.held:
                    return
                want = self.want
            errors = self.errors
            self._apply(want)
            if self.errors != errors:                  # a failing send: retry, but not in a tight loop
                time.sleep(0.02)
                if self.done and self.errors - errors:
                    return

    def hold(self, keys) -> None:
        keys = frozenset(keys)
        if not self.threaded:
            if keys != self.held:
                self._apply(keys)
            return
        with self.cond:
            self.want = keys
            self.cond.notify()

    def close(self) -> None:
        self.hold(())
        with self.cond:
            self.done = True
            self.cond.notify()


def fight(title, mem, sender: Sender, engine, stopped, clock=time.monotonic, sleep=time.sleep,
          stats: dict | None = None, poll_s: float = POLL_S, stall_s: float = STALL_S) -> str:
    """Tick the engine once per game frame until the screen leaves the fight (returns that screen), stopped()
    ("stopped"), or the frame field stops moving for stall_s ("stalled": a hang, a pause the map can't tell)."""
    stats = stats if stats is not None else {}
    for k in ("frames", "frames_skipped", "read_errors"):
        stats.setdefault(k, 0)
    last, moved = None, clock()
    try:
        while not stopped():
            try:
                f = title.frame(mem)
            except Exception:                          # noqa: BLE001 - a read during a load: try again
                stats["read_errors"] += 1
                if clock() - moved > stall_s:          # ... but not forever: a dead channel is a stall
                    return "stalled"
                sleep(0.01)
                continue
            now = clock()
            if f is None or f == last:
                if now - moved > stall_s:
                    return "stalled"
                sleep(poll_s)
                continue
            if last is not None and f > last + 1:
                stats["frames_skipped"] += f - last - 1
            last, moved = f, now
            t0 = clock()
            try:
                w = title.read(mem, now)
            except Exception:                          # noqa: BLE001
                stats["read_errors"] += 1
                continue
            if w.screen not in title.fight_screens:
                return w.screen
            sender.hold(engine.tick(w))
            stats["frames"] += 1
            stats["ram_progress"] = f                  # autoplay's black-frame watch trusts RAM that moves
            ms = (clock() - t0) * 1000
            stats["tick_ms"] = round(ms if "tick_ms" not in stats else stats["tick_ms"] * 0.95 + ms * 0.05, 3)
        return "stopped"
    finally:
        sender.hold(())
