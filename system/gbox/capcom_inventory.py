"""Authoritative owned-build inventory: Capcom Generations (Europe) (Disc 1).

Platform / revision
    Sony PS1 (SCEH), disc 1, Europe (PSL-SLES-01811 family).  Boot executable
    SLES_018.81 (psx_exe, pc0=0x200000, t_addr=0x200100).  Game executables
    P1942.EXE / P1943.EXE / P1943K.EXE load at 0x80010000 (PSX offset base
    0x800).  Each game EXE holds a word-pointer table mapping slot index to
    ISO path (gbox.capcom_slots): P1943.EXE table @0x800623e8, 27 slots,
    0=CHAR.DEE 1=OBJ01.DEE ... 26=43CHAR7.DEE.

Container
    CHD -> ISO9660, 89 files, 2352-byte raw sectors, little-endian .DEE
    header: 3 x LE u32 (raw_len, comp_len, 0x00400001), payload at +0x0C is a
    byte-flag LZ77 stream decompressing to a PSX TIM sprite sheet
    (gbox.capcom_dee).

Assimilation fingerprint verification (ticket fingerprint)
    Fingerprint claimed "engine Capcom Dreamcast 2D (0.48); nearest Marvel
    vs. Capcom 2 (Dreamcast); start from gbox.mvc2_dat".  REJECTED against
    the owned build: it is PS1 (psx_exe headers, SLES_018.81 boot, PSX TIM
    sprites, LZ77 .DEE container).  gbox.mvc2_dat targets Dreamcast DAT
    archives and is incompatible; the verified reader for this build is
    gbox.capcom_dee.

Native target asset (character replacement)
    1943/OBJ01.DEE - P1943.EXE slot 1 - player-plane sprite sheet.
    1943/CHAR.DEE (slot 0, character/menu sheet) is recorded as alternate.
"""

import hashlib
import os

from gbox import capcom_dee as _dee
from gbox import capcom_slots as _slots

GAME_ID = "5a67d462464d2460"
TITLE = "Capcom Generations (Europe) (Disc 1)"
PLATFORM = "ps1"
REVISION = "SLES-01811 family (Disc 1, Europe)"
BOOT_EXE = "SLES_018.81"
LOAD_BASE = 0x80010000
OFFSET_BASE = 0x800
CONTAINER = "CHD -> ISO9660 (89 files, 2352-byte raw sectors)"

# Owned CHD source identity.  Streaming sha256, re-verified on this host by
# the 2026-11-10 local run (request checkpoint source_sha256).  The CHD file
# itself was not re-located in the follow-up run (full sweep of /mnt/gbox and
# /home/ehm_eckx non-gbox trees: no match).
CHD_SHA256 = "6159ec05950ee85bc202250bdec5b4f251fe23ecd01ac4d9e6a89165b9d14aa5"
CHD_PROVENANCE = (
    "stream sha256 of the owned CHD, re-verified on this host 2026-11-10 "
    "(request checkpoint); CHD path not re-located in this run"
)

FINGERPRINT_VERIFICATION = {
    "claimed": "engine Capcom Dreamcast 2D (0.48); nearest Marvel vs. Capcom 2 (Dreamcast); start from gbox.mvc2_dat",
    "verdict": "rejected",
    "evidence": [
        "boot EXE SLES_018.81 is a psx_exe (pc0=0x200000, t_addr=0x200100)",
        "assets are PSX TIM sprite sheets inside LZ77 .DEE containers",
        "game EXEs are PSX binaries loaded at 0x80010000 (offset base 0x800)",
        "gbox.capcom_dee decodes every owned .DEE TIM asset (see build_inventory decoded counts)",
    ],
    "reader": "gbox.capcom_dee (verified), not gbox.mvc2_dat (Dreamcast DAT-based, incompatible)",
}

TARGET = {
    "iso_path": "1943/OBJ01.DEE",
    "slot": 1,
    "exe": "P1943.EXE",
    "table_offset": 0x800623e8,
    "reason": "player-plane sprite sheet (in-game character, stage 1943)",
}
ALTERNATE = {
    "iso_path": "1943/CHAR.DEE",
    "slot": 0,
    "reason": "character/menu sprite sheet",
}


def stream_sha256(path, chunk=1 << 20):
    """Streaming SHA-256 of a file (no full read into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _fill_tim(entry, tim_bytes, info=None):
    """Record decoded TIM geometry in an asset entry."""
    if info is None:
        info = _dee.parse_tim(tim_bytes)
    img = info["image"]
    entry["tim"] = {
        "width": img["w"],
        "height": img["h"],
        "bpp": info["bpp"],
        "has_clut": "clut" in info,
        "clut_size": (info.get("clut") or {}).get("size"),
        "tim_len": len(tim_bytes),
    }


def asset_entry(path, iso_path):
    """Manifest entry for one owned .DEE: size, sha256, header, TIM meta.

    Handles the three payload classes found on the disc:
    compressed DEE + PSX TIM (51 files), uncompressed raw TIM
    (MENU/WARN2.DEE) and compressed non-TIM payloads (MENU/S14[.K].DEE).
    """
    with open(path, "rb") as f:
        data = f.read()
    entry = {
        "iso_path": iso_path,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "compressed": False,
        "raw_len": None,
        "comp_len": None,
        "word": None,
        "tim": None,
    }
    try:
        hdr = _dee.parse_dee(data)
    except ValueError:
        # not a standard compressed DEE container
        if data[:4] == b"\x10\x00\x00\x00":
            _fill_tim(entry, data)  # uncompressed raw TIM
        return entry
    entry.update({
        "compressed": True,
        "raw_len": hdr["raw_len"],
        "comp_len": hdr["comp_len"],
        "word": hdr["word"],
    })
    try:
        tim_bytes, info = _dee.decode_dee_tim(data)
        _fill_tim(entry, tim_bytes, info)
    except ValueError:
        pass  # compressed container with a non-TIM payload (S14/S14K)
    return entry


def _iso_path_from_name(name):
    """1943_43CHAR7.DEE -> 1943/43CHAR7.DEE (dump naming convention)."""
    if "_" in name:
        return name.split("_", 1)[0] + "/" + name.split("_", 1)[1]
    return name


def slot_map_from_exes(exe_dir, base=LOAD_BASE):
    """slot label -> index maps from the owned game EXEs (recomputed, not copied)."""
    maps = {}
    for exe in ("P1943.EXE", "P1942.EXE", "P1943K.EXE"):
        path = os.path.join(exe_dir, exe)
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        # slot_table() returns {slot_index: iso_path}; iterate items, not keys
        tbl = _slots.slot_table(data) or {}
        m = {}
        for slot, label in sorted(tbl.items(), key=lambda kv: kv[0]):
            if not isinstance(label, str) or not label:
                continue
            m[label] = slot
            m[label.rsplit("/", 1)[-1]] = slot  # basename fallback
        maps[exe] = m
    return maps


def build_inventory(dee_dir, exe_dir=None, source_sha256=None):
    """Build the authoritative owned-build manifest for the disc's .DEE assets.

    Returns a dict with source identity, container metadata, per-asset
    entries (sha256 + DEE header + decoded TIM geometry) and the identified
    native target asset for character replacement.
    """
    assets = []
    for name in sorted(os.listdir(dee_dir)):
        if not name.lower().endswith(".dee"):
            continue
        assets.append(asset_entry(os.path.join(dee_dir, name),
                                  _iso_path_from_name(name)))

    slot_maps = slot_map_from_exes(exe_dir) if exe_dir else {}
    primary = slot_maps.get("P1943.EXE", {})
    for a in assets:
        a["slot"] = primary.get(a["iso_path"])
        if a["slot"] is None:
            a["slot"] = primary.get(a["iso_path"].rsplit("/", 1)[-1])

    def _pick(iso_path):
        return next((a for a in assets if a["iso_path"] == iso_path), None)

    tgt = _pick(TARGET["iso_path"])
    alt = _pick(ALTERNATE["iso_path"])
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "revision": REVISION,
        "container": CONTAINER,
        "byte_order": "little-endian",
        "offset_base": OFFSET_BASE,
        "load_base": LOAD_BASE,
        "boot_exe": BOOT_EXE,
        "source_sha256": source_sha256 or CHD_SHA256,
        "source_provenance": CHD_PROVENANCE,
        "fingerprint_verification": FINGERPRINT_VERIFICATION,
        "slot_tables": {k: len(v) for k, v in slot_maps.items()},
        "assets": assets,
        "asset_count": len(assets),
        "decoded_count": sum(1 for a in assets if a["tim"]),
        "target": {**{k: TARGET[k] for k in ("iso_path", "slot", "exe",
                                            "table_offset", "reason")},
                   "sha256": tgt["sha256"] if tgt else None,
                   "tim": tgt["tim"] if tgt else None},
        "alternate": {**{k: ALTERNATE[k] for k in ("iso_path", "slot", "reason")},
                      "sha256": alt["sha256"] if alt else None,
                      "tim": alt["tim"] if alt else None},
    }


def main(argv=None):
    import json
    import sys
    dee_dir = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/ehm_eckx/.hermes/cache/scratch/capcom_gen/dee"
    exe_dir = sys.argv[2] if len(sys.argv) > 2 else \
        "/home/ehm_eckx/.hermes/cache/scratch/capcom_gen"
    out = sys.argv[3] if len(sys.argv) > 3 else \
        "/home/ehm_eckx/.hermes/cache/scratch/capcom_gen/inventory.json"
    inv = build_inventory(dee_dir, exe_dir)
    with open(out, "w") as f:
        json.dump(inv, f, indent=2)
    print("assets=%d decoded=%d target=%s slot=%s sha256=%s" % (
        inv["asset_count"], inv["decoded_count"], inv["target"]["iso_path"],
        inv["target"]["slot"], (inv["target"]["sha256"] or "")[:16]))
    print("manifest -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
