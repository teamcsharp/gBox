"""Boot jump states: autoplay starts in gameplay, not on a title screen (#2829, #2834).

Once autoplay has played a game for SAVE_AFTER seconds without needing a menu press for QUIET_FOR seconds while the
screen keeps moving, it saves an emulator state for that game and build (runtime/jumpstates/<game>-<build>.state).
The next autoplay start of the same game and build starts there: no logos, title screen or menus. A jump state
that lands on a still screen (autoplay had to press through a menu within CHECK_FOR seconds) is dropped, so an
attract demo or a menu saved by mistake does not stick; the next good stretch of play saves a new one.

How an emulator gets there (strategy()); the operator's own save slots are never written:
- "slot", RetroArch: its save goes to a numbered slot and reports the file it wrote, so the jump state uses its own
  slot (SLOT): save there to learn the slot's file, copy the stored jump state over it, load it when learned
  autoplay starts, then put the operator's slot back.
- "boot", standalone Dolphin (Windows and the Spark's flatpak): a launch that asks for a jump (launch_game jump=true:
  the screensaver and autoplay on launch, never a plain Play) boots straight into the state with Dolphin's
  --save_state (arm_boot), so not even a logo shows. The save goes through a demo slot of Dolphin's own
  (adapter.jump_save, slot 10; the operator keeps slot 1, the checkpoint ring slot 8). Nothing is loaded into a
  running Dolphin: a session that did not boot into its jump state keeps it for the next demo.
Any other emulator has no jump states.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

SLOT = 9
SAVE_AFTER, QUIET_FOR, CHECK_FOR = 45.0, 30.0, 45.0


def strategy(ad) -> str | None:
    """'boot' (boots into a jump state, saves one through a demo slot of its own: jump_boot / jump_save), 'slot'
    (RetroArch's numbered slots, borrowed and given back) or None (no jump states)."""
    if all(callable(getattr(type(ad), a, None)) for a in ("jump_boot", "jump_save")) and hasattr(ad, "config"):
        return "boot"
    if all(hasattr(ad, a) for a in ("_slot", "save_state", "load_state", "config")):
        return "slot"
    return None


def supported(ad) -> bool:
    return strategy(ad) is not None


def path_for(ad, g: dict) -> Path:
    build = re.sub(r"[^\w.-]", "_", str(g.get("mod") or "stock"))[:80]
    return Path(ad.config.runtime) / "jumpstates" / f"{g.get('game_id')}-{build}.state"


def arm_boot(ad, g: dict) -> dict:
    """A launch that asks for a jump: boot straight into this game and build's jump state when the emulator can and
    this PC has one. Called before the emulator starts; the result goes into the launch detail (session.detail.jump)."""
    if strategy(ad) != "boot":
        return {"booted": False, "why": "this emulator loads its jump state when autoplay starts"}
    p = path_for(ad, g)
    try:
        have = p.is_file() and p.stat().st_size > 0
    except OSError:
        have = False
    if not have:
        return {"booted": False, "why": "no jump state for this game and build on this PC yet"}
    ad.jump_boot(p)
    return {"booted": True, "file": p.name}


def booted(ad, g: dict | None = None) -> bool:
    """This session booted straight into its jump state (for g's game and build): it is past the title already."""
    src = getattr(ad, "jump_from", None)
    return bool(src) and (g is None or Path(src) == path_for(ad, g))


def drop_boot(ad) -> None:
    """A launch that booted into a jump state failed: drop the state, so the next launch boots the usual way."""
    src = getattr(ad, "jump_from", None)
    if src:
        Path(src).unlink(missing_ok=True)


def _keeping_slot(ad, fn):
    prev = int(getattr(ad, "slot", 0) or 0)
    try:
        return fn()
    finally:
        ad._slot(prev)                                   # the operator's own Save / Load keep their slot


def save(ad, dest: Path) -> int:
    if strategy(ad) == "boot":
        return int(ad.jump_save(dest))                  # its demo slot, copied to dest

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


def _ready(ad, kind) -> bool:
    # Dolphin's gBox hotkeys share their keys with the speed-limit key: no save while fast-forward holds it
    return kind != "boot" or not getattr(ad, "ff_on", False)


def watch(ad, g: dict, stuck, stats: dict, stopped, clock=time.time, sleep=time.sleep) -> None:
    """Beside the learned style (stats is play_style's: menu_at = its last menu press). Starts from the jump state
    (RetroArch loads it now; Dolphin booted into it), drops it if it lands on a menu, saves one after a good stretch
    of play. stats['jump'] says what happened."""
    p = path_for(ad, g)
    kind = strategy(ad)
    start, loaded_at, saved = clock(), None, False
    if kind == "boot":
        if booted(ad, g):
            loaded_at, stats["jump"] = start, "booted into it"
        elif p.is_file():                                # Dolphin loads one only at boot: kept for the next demo
            stats["jump"], saved = "kept: this launch did not boot into it", True
    elif p.is_file():
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
                and now - max(menu_at, start) > QUIET_FOR and now - stuck.changed < 3 and _ready(ad, kind):
            try:
                stats["jump_bytes"] = save(ad, p)
                stats["jump"] = "saved"
            except Exception as e:                       # noqa: BLE001
                stats["jump"] = f"save failed: {type(e).__name__}"
            saved = True
        sleep(1.0)
