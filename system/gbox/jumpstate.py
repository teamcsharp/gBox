"""Boot jump states: autoplay starts in gameplay, not on a title screen (#2829, #2834).

Once autoplay has played a game for SAVE_AFTER seconds without needing a menu press for QUIET_FOR seconds while the
screen keeps moving, it saves an emulator state for that game and build (runtime/jumpstates/<game>-<build>.state).
The next autoplay start of the same game and build loads it at once: no logos, title screen or menus. A jump state
that lands on a still screen (autoplay had to press through a menu within CHECK_FOR seconds) is dropped, so an
attract demo or a menu saved by mistake does not stick; the next good stretch of play saves a new one.

RetroArch only: its save goes to a numbered slot and reports the file it wrote, so the jump state uses its own slot
(SLOT): save there to learn the slot's file, copy the stored jump state over it, load it, then put the operator's
slot back. Dolphin's save is the operator's slot 1, so it is left alone.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

SLOT = 9
SAVE_AFTER, QUIET_FOR, CHECK_FOR = 45.0, 30.0, 45.0


def supported(ad) -> bool:
    return all(hasattr(ad, a) for a in ("_slot", "save_state", "load_state", "config"))


def path_for(ad, g: dict) -> Path:
    build = re.sub(r"[^\w.-]", "_", str(g.get("mod") or "stock"))[:80]
    return Path(ad.config.runtime) / "jumpstates" / f"{g.get('game_id')}-{build}.state"


def _keeping_slot(ad, fn):
    prev = int(getattr(ad, "slot", 0) or 0)
    try:
        return fn()
    finally:
        ad._slot(prev)                                   # the operator's own Save / Load keep their slot


def save(ad, dest: Path) -> int:
    def go():
        written = Path(ad.save_state(SLOT)["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        shutil.copyfile(written, tmp)
        tmp.replace(dest)
        return dest.stat().st_size
    return _keeping_slot(ad, go)


def load(ad, src: Path) -> None:
    def go():
        slot_file = Path(ad.save_state(SLOT)["path"])    # learns this session's file for SLOT
        shutil.copyfile(src, slot_file)
        ad.load_state(SLOT)
    _keeping_slot(ad, go)


def watch(ad, g: dict, stuck, stats: dict, stopped, clock=time.time, sleep=time.sleep) -> None:
    """Beside the learned style (stats is play_style's: menu_at = its last menu press). Loads the jump state at
    start, drops it if it lands on a menu, saves one after a good stretch of play. stats['jump'] says what happened."""
    p = path_for(ad, g)
    start, loaded_at, saved = clock(), None, False
    if p.is_file():
        try:
            load(ad, p)
            loaded_at = clock()
            stats["jump"] = "loaded"
        except Exception as e:                           # noqa: BLE001 - no jump: the game boots the usual way
            stats["jump"] = f"load failed: {type(e).__name__}"
    while not stopped():
        now = clock()
        menu_at = stats.get("menu_at") or 0.0
        if loaded_at is not None:
            if menu_at > loaded_at:                       # landed on a menu: not a gameplay moment
                p.unlink(missing_ok=True)
                stats["jump"], loaded_at = "dropped: landed on a menu", None
            elif now - loaded_at > CHECK_FOR:
                stats["jump"], loaded_at, saved = "loaded, playing", None, True
        elif not saved and stuck is not None and now - start > SAVE_AFTER \
                and now - max(menu_at, start) > QUIET_FOR and now - stuck.changed < 3:
            try:
                stats["jump_bytes"] = save(ad, p)
                stats["jump"] = "saved"
            except Exception as e:                       # noqa: BLE001
                stats["jump"] = f"save failed: {type(e).__name__}"
            saved = True
        sleep(1.0)
