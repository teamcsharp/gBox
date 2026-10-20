"""A save state of a live game taken through gBox's own slot: the operator's save slots are never written or left switched.

state_transfer op=snapshot uses it (autoplay coaching notes, gbox.coaching). op=export saves through the emulator's
working slot instead: on standalone Dolphin that is slot 1, the operator's own Save state / Load state slot, and on
RetroArch it leaves the emulator switched to the transfer slot, so the operator's next save lands there. Here:

- Dolphin (Windows and the Spark's flatpak): its demo slot 10 (adapter.jump_save, the jump-state slot no key loads). The
  slot file is copied out and removed, so Dolphin's undo-save backup (lastState.sav) is left alone as well; the operator
  keeps slot 1 and the checkpoint ring slot 8. jump_save refuses while fast-forward holds the hotkeys' lane key.
- RetroArch: gBox's slot 9 (state_transfer's and jumpstate's slot). The emulator is switched back to the operator's slot
  afterwards. Every slot file the switch passes over (the operator's slot up to slot 9, and their thumbnails) is copied
  aside first and put back after, so a dropped slot command that lands the save in another slot cannot cost a save;
  slot files the save created are removed. Without the content's name (which slot files are this game's) it refuses.
Any other emulator has no slot of gBox's own: Unsupported.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from .registry import Unsupported

SLOT = 9                     # RetroArch: gBox's slot (state_transfer's default, gbox.jumpstate.SLOT)


def take(ad, g: dict, states: Path | None = None) -> tuple[bytes, dict]:
    """(state bytes, details) of the game right now, saved through gBox's own slot. details: file, slot, via, ..."""
    if callable(getattr(type(ad), "jump_save", None)):
        return _dolphin(ad, g)
    if getattr(ad, "name", "") == "retroarch" and callable(getattr(ad, "_slot", None)):
        return _retroarch(ad, g, Path(states) if states is not None else Path(ad.state_dir()))
    raise Unsupported(f"{getattr(ad, 'name', '') or 'this emulator'} has no save slot of gBox's own "
                      "(a save would use the operator's slot)")


def _dolphin(ad, g: dict) -> tuple[bytes, dict]:
    slot = int(getattr(ad, "JUMP_SLOT", 10))
    with tempfile.TemporaryDirectory(prefix="gbox-snapshot-") as t:
        dest = Path(t) / f"snapshot.s{slot:02d}"
        ad.jump_save(dest)                         # Dolphin's demo slot, copied to dest; the slot file is removed
        data = dest.read_bytes() if dest.is_file() else b""
    if not data:
        raise RuntimeError("Dolphin did not write the snapshot")
    label = getattr(ad, "gecko_id", None) or g.get("game_id") or "game"
    return data, {"file": f"{label}.s{slot:02d}", "slot": slot, "operator_slot": 1,
                  "via": f"Dolphin slot {slot} (gBox's demo slot): your slot 1 and the rewind slot 8 were not touched"}


def _slot_name(stem: str, slot: int) -> str:
    return f"{stem}.state{slot if slot else ''}"   # RetroArch: slot 0 is <content>.state, slot n <content>.staten


def _identity(f: Path):
    try:
        st = f.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _named(root: Path, names: set[str]) -> dict[Path, tuple]:
    """Files under root (RetroArch may sort states into per-core folders) with one of these exact names."""
    out = {}
    if not names or not root.is_dir():
        return out
    for folder, _dirs, files in os.walk(root):
        for n in files:
            if n in names:
                f = Path(folder) / n
                if (ident := _identity(f)) is not None:
                    out[f] = ident
    return out


def _content_stem(ad, g: dict) -> str:
    rom = str(g.get("_rom_path") or "")
    if rom:
        return Path(rom).stem
    last = getattr(ad, "_last_state_path", None)            # an earlier verified save names this game's files
    m = re.match(r"(.+)\.state-?\d*$", Path(str(last)).name) if last else None
    return m[1] if m else ""


def _retroarch(ad, g: dict, states: Path) -> tuple[bytes, dict]:
    from .tools import _validate_state_container
    stem = _content_stem(ad, g)
    if not stem:
        raise RuntimeError("can't tell which RetroArch slot files belong to this game: no snapshot rather than risk "
                           "a save")
    prev = int(getattr(ad, "slot", 0) or 0)
    lo, hi = sorted((max(prev, 0), SLOT))
    names = {_slot_name(stem, k) + ext for k in range(lo, hi + 1) for ext in ("", ".png")}
    before = _named(states, names)
    with tempfile.TemporaryDirectory(prefix="gbox-snapshot-") as t:
        kept = {}
        for i, f in enumerate(before):
            kept[f] = Path(t) / f"{i}.bin"
            shutil.copy2(f, kept[f])
        try:
            try:
                saved = ad.save_state(SLOT)
            finally:
                if int(getattr(ad, "slot", prev) or 0) != prev:
                    ad._slot(prev)                       # the operator's Save / Load keep their slot
            saved = saved if isinstance(saved, dict) else {}
            path = Path(str(saved.get("path") or ""))
            if saved.get("verified") is not True or not saved.get("path") or not path.is_file():
                raise RuntimeError("RetroArch did not verify the snapshot's save file")
            if path.name not in names:
                raise RuntimeError("the snapshot's save file is not one of this game's slot files")
            data = path.read_bytes()
            _validate_state_container(data, "retroarch")
        finally:
            for f, copy in kept.items():                 # every slot file exactly as it was before
                if _identity(f) != before[f]:
                    shutil.copy2(copy, f)
            for f in _named(states, names):              # and none the snapshot created
                if f not in before:
                    f.unlink(missing_ok=True)
    actual = saved.get("slot", SLOT)
    out = {"file": path.name, "slot": actual, "requested_slot": SLOT, "operator_slot": prev,
           "via": f"RetroArch slot {SLOT} (gBox's slot): switched back to your slot {prev}, slot files kept as they were"}
    if actual != SLOT:
        out["warning"] = f"RetroArch saved to slot {actual}; that slot's file was put back as it was"
    return data, out
