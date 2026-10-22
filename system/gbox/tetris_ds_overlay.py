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

# Digests of the owned Tetris DS (USA) revision, pinned in source so the check
# works without the profile file (profiles/*.json mirrors these values).
PINNED = {
    "rom_sha256": "4e443f9b03363900dda6fa308229a3b14631b0fedd14f1c2e4cc1d5b3224db68",
    "arm9_sha256": "395348597da9fdda6db2956f9e9f0fd1575f27f70e0c3e7afb2b90adb3edb4e4",
    "assets": {
        "ct.srl": {"size": 1022088, "sha256": "ba034cb067b35306aaf0a7443376570c4d1a98a6123e305887db9445f75adab5"},
        "od.srl": {"size": 1051784, "sha256": "83126c8e59bdce68137949f8f2c3d6d5a63408541755596ae0ca173937ba8dee"},
        "pt.srl": {"size": 883336, "sha256": "d701ab250b62d11226593a266b2a8102bfaa532e38f868ac701b2ade5fbae5eb"},
        "push1.pak": {"size": 197120, "sha256": "55fbe43d91fc622a83ba9bfdb2762028da3dfdaae7606bbec2e3e8bbc419bce8"},
        "quiz.dat": {"size": 4850, "sha256": "ab65703ad03ca26c2bb077053f0b6a5d9bdd9fc43871be18b12d87c0ab15725f"},
        "title.pak": {"size": 197120, "sha256": "251c67bb41fcfae0df018b75e7dd2bcb79b21fc526e937e907f1d96ef31212f7"},
    },
}

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
    """The digests pinned for the owned revision (source-pinned)."""
    return {"rom_sha256": PINNED["rom_sha256"], "arm9_sha256": PINNED["arm9_sha256"],
            "assets": dict(PINNED["assets"])}


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
