"""Tetris DS (USA) archive-asset binding for the #2268 unlock work.

Tetris DS runs its mode logic from ARM9 overlay 0, but the per-mode payloads
live in NitroFS archive members inside the ROM (``ct.srl`` for Standard mode,
``od.srl`` / ``pt.srl`` for the other modes). Any cheat that unlocks
Standard-mode progress has to be bound to the exact owned revision, so this
module resolves those members from the parsed ROM, hashes them and compares
them with the digests pinned in ``profiles/tetris-ds-us.json``.

Read-only: it produces the build-binding evidence a later live probe needs and
never touches a running session.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "tetris-ds-us.json"

OVERLAY_ASSETS = {
    "ct.srl": "Standard mode data (Marathon / Line Clear / VS CPU)",
    "od.srl": "Option-mode data",
    "pt.srl": "Party-mode data",
}

SUPPORT_ASSETS = {
    "push1.pak": "Push-button layout archive",
    "quiz.dat": "Quiz data",
    "title.pak": "Title-screen archive",
}

TRACKED = dict(OVERLAY_ASSETS)
TRACKED.update(SUPPORT_ASSETS)


def _find(rom, name):
    for path in rom.paths():
        if path.lower() == name.lower():
            return path
    return None


def asset_digests(rom) -> dict:
    """Digest + size of every tracked NitroFS archive member present in the ROM."""
    out = {}
    for name, role in TRACKED.items():
        path = _find(rom, name)
        if path is None:
            continue
        blob = rom.read(path)
        out[name] = {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "role": role}
    return out


def rom_digests(rom_bytes: bytes) -> dict:
    """ROM and ARM9 digests plus the ARM9 load geometry from the NDS header."""
    arm9_off, arm9_entry, arm9_ram, arm9_size = struct.unpack_from("<IIII", rom_bytes, 0x20)
    arm9 = rom_bytes[arm9_off:arm9_off + arm9_size]
    return {
        "rom_sha256": hashlib.sha256(rom_bytes).hexdigest(),
        "arm9_sha256": hashlib.sha256(arm9).hexdigest(),
        "arm9_offset": arm9_off,
        "arm9_entry": arm9_entry,
        "arm9_ram": arm9_ram,
        "arm9_size": arm9_size,
    }


def pinned() -> dict:
    """The digests pinned in the Tetris DS profile."""
    prof = json.loads(PROFILE_PATH.read_text())
    return {"rom_sha256": prof.get("rom_sha256"), "arm9_sha256": prof.get("arm9_sha256"),
            "assets": prof.get("archive_assets", {})}


def verify(rom, rom_bytes: bytes) -> dict:
    """Compare measured ROM/ARM9/asset digests with the pinned values."""
    want = pinned()
    have = rom_digests(rom_bytes)
    assets = asset_digests(rom)
    mismatches = []
    for key in ("rom_sha256", "arm9_sha256"):
        if want.get(key) and have.get(key) != want[key]:
            mismatches.append({"field": key, "expected": want[key], "actual": have.get(key)})
    for name, pin in (want.get("assets") or {}).items():
        got = assets.get(name)
        if not got:
            mismatches.append({"field": name, "expected": (pin or {}).get("sha256"), "actual": None})
        elif got["sha256"] != (pin or {}).get("sha256"):
            mismatches.append({"field": name, "expected": (pin or {}).get("sha256"), "actual": got["sha256"]})
    return {"ok": not mismatches, "expected": want, "actual": have, "assets": assets,
            "mismatches": mismatches}
