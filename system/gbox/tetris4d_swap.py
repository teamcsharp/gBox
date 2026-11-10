"""Tetris 4D (Japan, Dreamcast) portrait writer: donor -> slot as a separate GDI mod.

The owned split GDI is never modified.  The mod directory gets a copy of the
track that holds the slot (patched in place, size-preserving) and hard links
for every other track plus a rewritten-nothing disc.gdi copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from gbox.gdrom import GDRom
from gbox.tetris4d_pvr import CHARACTER_SLOTS, donor_swap, parse_pvr

GAME_IDS = {"864538c6473a986e": "Tetris 4D (Japan)"}
SOURCE_CHD_SHA256 = "531a6ce7fb56c8bdb367d9c98eb724b13404d548f0e817e9958a6f55fb456058"


def slot_path(slot: str) -> str:
    s = slot.upper()
    if s.endswith(".PVR"):
        s = s[:-4]
    if s not in CHARACTER_SLOTS:
        raise ValueError("unknown portrait slot %r; choose from %s" % (slot, ", ".join(CHARACTER_SLOTS)))
    return "MENU/MENUMODEL/%s.PVR" % s


def _track_for(disc: GDRom, lba: int):
    for start, size, path in reversed(disc.tracks):
        if lba >= start:
            return start, size, path
    raise ValueError("LBA %d not in a data track" % lba)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_mod(gdi: str | Path, out_dir: str | Path, slot: str, donor_pvr: bytes) -> dict:
    """Write out_dir/disc.gdi (+tracks) with `slot` replaced by `donor_pvr`'s image."""
    gdi, out = Path(gdi), Path(out_dir)
    if out.resolve() == gdi.parent.resolve():
        raise ValueError("mod directory must differ from the owned disc directory")
    disc = GDRom(gdi)
    name = slot_path(slot)
    lba, size = disc.files[name]
    original = disc.read(name)
    new = donor_swap(original, donor_pvr)
    if len(new) != len(original):
        raise ValueError("size changed %d -> %d" % (len(original), len(new)))
    start, ssize, src_track = _track_for(disc, lba)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(gdi, out / gdi.name)
    for _s, _z, p in disc.tracks:
        if p == src_track:
            continue
        if not (out / p.name).exists():
            try:
                os.link(p, out / p.name)
            except OSError:
                shutil.copy2(p, out / p.name)
    dst = out / src_track.name
    shutil.copy2(src_track, dst)
    user = 16 if ssize == 2352 else 0
    with open(dst, "r+b") as f:
        for i in range((size + 2047) // 2048):
            chunk = new[i * 2048:(i + 1) * 2048]
            f.seek((lba + i - start) * ssize + user)
            f.write(chunk)          # a short last chunk leaves the sector's original padding intact
    # verify: re-read through the disc walker, compare
    check = GDRom(out / gdi.name)
    assert check.read(name) == new, "readback mismatch"
    for other in ("1ST_READ.BIN",):
        assert check.read(other) == disc.read(other)
    meta = {
        "game_id": next(iter(GAME_IDS)), "source_chd_sha256": SOURCE_CHD_SHA256, "slot": name,
        "lba": lba, "size": size, "gbix": parse_pvr(new).gbix,
        "original_sha256": hashlib.sha256(original).hexdigest(), "new_sha256": hashlib.sha256(new).hexdigest(),
        "patched_track": src_track.name, "patched_track_sha256": _sha(dst),
        "files": [name],
    }
    (out / ".gbox-mod.json").write_text(json.dumps(meta, indent=2))
    return meta
