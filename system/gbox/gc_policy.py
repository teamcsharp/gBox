"""Garbage collection of the long-running control plane (`gbox serve`).

Stream stalls on the Spark, 2026-10-27: the server stopped 0.4-0.9 s several times a minute and every MJPEG view (web
UI, desktop app, Pine Box feeds) froze with it. Per-thread CPU during each stall showed one thread running alone while
the event loop got ~30 ms; py-spy put that thread at a bytecode boundary right after a small call (store.all('notify')
decoding 247 entries, mercmode_status returning) for 0.7-0.8 s: CPython 3.12's full collection, which walks every
tracked object of the 5.8 GB process with the GIL held. With the default thresholds (700, 10, 10) a whole-kind decode
that lives through a few young collections is promoted to the old generation, and once those promotions reach 25 % of
the old generation a full collection runs: in a scratch copy of this heap shape almost every whole-kind decode set
one off.

Two settings, both standard for long-running CPython servers:
- a young-generation threshold of 20,000 allocations: a decode's objects are usually released before the second
  young collection, so they are never promoted (scratch: 52 full collections in 60 decode rounds -> 2);
- gc.freeze() once the server has warmed up: modules, routes, models and the caches built at startup move to the
  permanent generation, so a full collection no longer walks them (scratch: ~200 ms -> under 35 ms each).
Frozen objects are still freed by reference counting; only a reference cycle among them would outlive its use, so the
heap is frozen once, after a collection, never again. GBOX_GC_POLICY=0 keeps CPython's defaults.
"""
from __future__ import annotations

import gc
import os
import threading
import time

YOUNG_THRESHOLD = 20_000
FREEZE_AFTER_S = 300.0


def _print(message: str):
    print(message, flush=True)


def apply(*, freeze_after_s: float = FREEZE_AFTER_S, log=_print) -> threading.Thread | None:
    """Raise the young threshold now and freeze the warmed-up heap once, `freeze_after_s` later (a daemon thread).
    Returns that thread, or None when GBOX_GC_POLICY=0."""
    if os.environ.get("GBOX_GC_POLICY", "1").strip().lower() in ("0", "false", "off", "no"):
        return None
    young, middle, old = gc.get_threshold()
    if young and young < YOUNG_THRESHOLD:              # 0 means automatic collection is disabled: leave it so
        gc.set_threshold(YOUNG_THRESHOLD, middle, old)

    def freeze():
        time.sleep(freeze_after_s)
        t = time.perf_counter()
        gc.collect()                                   # garbage present now is collected, not frozen
        gc.freeze()
        log(f"gc: froze {gc.get_freeze_count()} long-lived objects after warm-up "
            f"({(time.perf_counter() - t) * 1000:.0f} ms); thresholds {gc.get_threshold()}")

    thread = threading.Thread(target=freeze, daemon=True, name="gc-freeze")
    thread.start()
    return thread
