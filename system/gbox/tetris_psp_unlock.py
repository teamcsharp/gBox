"""Tetris (PSP Minis, game_id 25da54968d78f816) unlock research gate and revision-pinned inventory.

Owned copy, verified 2026-10-21 by reading the shared HyperSpin library read-only:
  disc file    "Tetris (USA).cso"
  disc sha256  b0afb70a682c11c56f7660d39ea1224950b0b3eb33f2686970da5870bfa61bf2  (27622944 bytes, CISO v1 -> 170098688 bytes uncompressed)
  PARAM.SFO    TITLE=Tetris  DISC_ID=NPUZ00003  DISC_VERSION=1.00  BOOTABLE=1  CATEGORY=UG
  EBOOT.BIN    sha256 77f733ee047229ed40a5e5da90d51ce9e5fb5d9afff4487e3b7c7f9d58fcf701 (3032768 bytes, PSP "~PSP" self-contained executable)
  BOOT.BIN     sha256 02903a5b0701570df0697b5f2f0572e9ece616474dea4e68677affd59bf4c306 (3032424 bytes)

This module writes no memory and no save. The lock flags of this exact revision are
not proven yet, so gbox.game_unlocks reports an honest pending_research gate and
pre_launch can never reach a writer for this title.

What it does provide, derived from the owned disc itself:
  * a revision guard bound to the owned disc digest;
  * a read-only inventory of the content this title actually ships (game modes with
    their level and background packs, localisations and global resources), every
    entry recorded as unlocked / not_present / unknown with its evidence;
  * the evidence chain a future implementation has to attach before promotion.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

GAME_ID = "25da54968d78f816"
TITLE = "Tetris"
PLATFORM = "psp"
SYSTEM = "Sony Playstation Minis"

DISC_NAME = "Tetris (USA).cso"
DISC_SHA256 = "b0afb70a682c11c56f7660d39ea1224950b0b3eb33f2686970da5870bfa61bf2"
DISC_SIZE = 27622944
DISC_UNCOMPRESSED_SIZE = 170098688
PARAM_SFO_SHA256 = "33e6de4f57f381d125d0b182c82c41681c86899398804e0f4050c384ceeb0902"
EBOOT_SHA256 = "77f733ee047229ed40a5e5da90d51ce9e5fb5d9afff4487e3b7c7f9d58fcf701"
BOOT_SHA256 = "02903a5b0701570df0697b5f2f0572e9ece616474dea4e68677affd59bf4c306"
DISC_ID = "NPUZ00003"
PRODUCT_CODE = "NPUZ00003"
DISC_VERSION = "1.00"
PARAM_SFO = "PSP_GAME/PARAM.SFO"
EBOOT = "PSP_GAME/SYSDIR/EBOOT.BIN"

LANGUAGES = ("DE", "EN", "ES", "FR", "IT")
CATEGORIES = ("modes", "levels", "stages", "characters",
              "hidden_characters", "costumes", "items", "extras")

REQUIRED_EVIDENCE = ("owned_disc_sha256", "owned_executable_sha256",
                     "lock_flag_evidence", "save_or_progress_target",
                     "save_backup_receipt", "rollback_receipt",
                     "live_boot_and_selection_acceptance",
                     "second_launch_verification")

SAFETY = ("No live memory or save write exists for this title and none may be "
          "attempted without the full evidence chain above.",
          "Never test on the operator PC; only idle authorized test workers.",
          "Preserve the owned .cso and back up any save before changes.",
          "A queued task, an inventory or a code-only PR is not unlock completion.")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def disc_guard(path) -> dict:
    """Bind this profile to the owned revision; refuse anything else."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "expected": DISC_SHA256, "actual": None,
                "reason": f"owned disc not readable: {p}"}
    actual = sha256_file(p)
    return {"ok": actual == DISC_SHA256, "expected": DISC_SHA256, "actual": actual}


def _open(path):
    from .cso import CSO
    from .romexport import iso_files
    f = CSO(Path(path))
    return f, iso_files(f)


def _read(f, files, key):
    _rec, lba, size = files[key]
    f.seek(lba * 2048)
    return f.read(size)


def read_param_sfo(path) -> dict:
    """PARAM.SFO of the owned disc (TITLE / DISC_ID / DISC_VERSION ...)."""
    f, files = _open(path)
    sfo = _read(f, files, PARAM_SFO)
    kt, dt, n = struct.unpack_from("<III", sfo, 8)
    out = {}
    for i in range(n):
        ko, fmt, ln, _pad, do = struct.unpack_from("<HHIII", sfo[20 + 16 * i:36 + 16 * i])
        key = sfo[kt + ko:sfo.index(b"\x00", kt + ko)].decode("latin-1")
        v = sfo[dt + do:dt + do + ln]
        out[key] = struct.unpack("<I", v[:4])[0] if fmt == 0x0404 else v.rstrip(b"\x00").decode("latin-1")
    return out


def _units(files):
    """USRDIR/TETRIS tree -> {unit: {lang|"_": {filename: (lba, size)}}}."""
    units = {}
    for key in files:
        parts = key.upper().split("/")
        if len(parts) < 5 or parts[0] != "PSP_GAME" or parts[1] != "USRDIR" or parts[2] != "TETRIS":
            continue
        unit = parts[3]
        if len(parts) == 5:
            lang, name = "_", parts[4]
        else:
            lang, name = parts[4], parts[5]
        units.setdefault(unit, {}).setdefault(lang, {})[name] = files[key.upper()]
    return units


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _background_pairs(units) -> dict:
    """Pair each level unit with its background unit (the disc abbreviates names).

    Every level pack on this disc has a matching background pack. The background units are
    exactly the ones whose name ends in BG, but the pairing is by the longest shared name
    prefix because the disc shortens some names (GRAVITY->GRAVBG, MAGNETIC->MAGBG,
    RADICAL->RADBG, SCANNER->SCANBG). System packs (CREDITS, INTRO, LVLOADER, LEDLOAD,
    RPLFILES, TEXTS, GLOBAL) have no background and are therefore not level modes.
    """
    bgs = sorted(u for u in units if u.endswith("BG"))
    plain = [u for u in units if not u.endswith("BG") and f"{u}.PSP" in units[u].get("_", {})]
    pairs = {}
    for bg in bgs:
        best, best_n = None, 0
        for u in plain:
            n = _common_prefix(u, bg)
            if n > best_n:
                best, best_n = u, n
        if best is not None and best_n >= 3 and best not in pairs:
            pairs[best] = bg
    return pairs


def inventory(path) -> dict:
    """Read-only content inventory of the owned Tetris (PSP Minis) disc."""
    f, files = _open(path)
    units = _units(files)
    pairs = _background_pairs(units)
    modes = []
    for unit in sorted(units):
        root = units[unit].get("_", {})
        if f"{unit}.PSP" not in root or unit not in pairs:
            continue
        _rec, lba, size = root[f"{unit}.PSP"]
        f.seek(lba * 2048)
        level = f.read(size)
        bg_unit = pairs[unit]
        bg = None
        bg_rec = units.get(bg_unit, {}).get("_", {}).get(f"{bg_unit}.PSP")
        if bg_rec:
            _r, blba, bsize = bg_rec
            f.seek(blba * 2048)
            bg = f.read(bsize)
        langs = sorted(l for l in units[unit] if l != "_")
        modes.append({
            "name": unit,
            "level_pack": f"PSP_GAME/USRDIR/TETRIS/{unit}/{unit}.PSP",
            "level_bytes": len(level),
            "level_sha256": hashlib.sha256(level).hexdigest(),
            "background_pack": (f"PSP_GAME/USRDIR/TETRIS/{bg_unit}/{bg_unit}.PSP" if bg else None),
            "background_sha256": hashlib.sha256(bg).hexdigest() if bg else None,
            "languages": langs,
            "lock_state": "unknown",
            "evidence": "pack present in the owned disc; the lock flag that gates "
                        "selection has not been located in this revision yet",
        })
    bg_names = set(pairs.values())
    resources = sorted(u for u in units if u not in {m["name"] for m in modes} and u not in bg_names)
    unknown = ("present in the owned disc but not yet decoded into an entry list; no proof "
               "of present or absent entries exists for this revision")
    categories = {
        "modes": {"status": "unknown", "entries": [m["name"] for m in modes],
                  "reason": "mode packs are proven present; their lock flags are not yet located"},
        "levels": {"status": "unknown", "entries": [m["name"] for m in modes],
                   "reason": "each mode ships its own level pack; per-level lock flags are not yet located"},
        "stages": {"status": "unknown", "entries": [], "reason": unknown},
        "characters": {"status": "unknown", "entries": [], "reason": unknown},
        "hidden_characters": {"status": "unknown", "entries": [], "reason": unknown},
        "costumes": {"status": "unknown", "entries": [], "reason": unknown},
        "items": {"status": "unknown", "entries": [], "reason": unknown},
        "extras": {"status": "unknown", "entries": [], "reason": unknown},
    }
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "disc_sha256": DISC_SHA256, "disc_size": DISC_SIZE,
        "param_sfo": read_param_sfo(path),
        "modes": modes,
        "resources": resources,
        "categories": categories,
        "files_on_disc": len(files),
    }


def locate_evidence(path, needles, limit=40) -> list:
    """Map text needles found in the image to the file that holds them."""
    f, files = _open(path)
    extents = sorted((lba * 2048, lba * 2048 + size, key)
                     for key, (_r, lba, size) in files.items())
    def owner(off):
        for start, end, key in extents:
            if start <= off < end:
                return key, off - start
        return None, None
    out = []
    needles = [n.lower() for n in needles]
    win = 1 << 22
    pos = 0
    prev = b""
    while True:
        f.seek(pos)
        buf = f.read(win)
        if not buf:
            break
        blob = prev + buf
        base = pos - len(prev)
        low = blob.lower()
        for nb in needles:
            i = low.find(nb)
            while i != -1:
                key, rel = owner(base + i)
                out.append({"needle": nb.decode("latin-1"), "file": key,
                            "offset_in_file": rel, "image_offset": base + i})
                i = low.find(nb, i + 1)
        prev = blob[-64:]
        pos += len(buf)
    return out


def profile_gate() -> dict:
    """Honest dispatch-surface record: research pending, nothing verified."""
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "status": "pending_research",
        "reason": ("The owned disc and executable are hash-pinned and the shipped content is "
                   "inventoried, but no lock flag, progress/save target or verified write routine "
                   "exists for this exact revision, so no writer is reachable from the Play path."),
        "owned_disc": {"name": DISC_NAME, "sha256": DISC_SHA256, "size": DISC_SIZE},
        "owned_executable": {"path": EBOOT, "sha256": EBOOT_SHA256},
        "param_sfo_sha256": PARAM_SFO_SHA256,
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "safety": list(SAFETY),
        "next_step": ("Run REA/Ghidra on the pinned EBOOT.BIN (MIPS, self-contained ~PSP) to locate "
                      "the mode-select lock check and the progress/save structure, bind the routine "
                      "to these digests, then verify it on an idle authorized worker with an "
                      "isolated save, a second launch and a rollback."),
    }
