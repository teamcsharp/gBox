"""Offline research reader for the Sega Saturn build of Tetris Plus (USA).

Owned source (never mutated): /mnt/gbox/hyperspin/Arcade/collections/Sega Saturn/roms/Tetris Plus (USA).chd
Raw extraction (chdman extractcd) -> tp.bin, 591,523,296 B, sha256 f0df8cbe720881ff68d4dc08e5d1e8d27f47b32b19043a936dc0d543935a7fba.
Track 1 is MODE1/2352 (ISO9660); tracks 2-4 are CD-DA.

Status: RESEARCH ONLY. No unlock profile is registered: no lock check, save
flag or hidden content has been located yet (needs Ghidra on an x64 worker).
IP.BIN header: product T-5704H, V1.001, 1996-08-31, area U, title TETRIS_PLUS.
The disc has 33 ISO files; there is NO single-executable name table like
DOA: 0MAIN.BIN (LBA 24) is the boot/first-program, and per-mode overlays
(TITLE/MODE/NORMAL/PUZZLE/VSPUZ/EDIT/HOW_TO_*/RANKING/TDEMO) are loaded from CD.
"""
from __future__ import annotations

import hashlib
import struct

GAME_ID = "12f27d41296f2c33"
CHD_PATH = "/mnt/gbox/hyperspin/Arcade/collections/Sega Saturn/roms/Tetris Plus (USA).chd"
RAW_BIN_SHA256 = "f0df8cbe720881ff68d4dc08e5d1e8d27f47b32b19043a936dc0d543935a7fba"
PRODUCT = "T-5704H"
VERSION = "V1.001"
BOOT_FILE = "0MAIN.BIN"

# Verified ISO9660 manifest (name -> LBA, bytes).
ISO_FILES = {
    "0MAIN.BIN": {
        "lba": 24,
        "size": 121064
    },
    "EDIT.BIN": {
        "lba": 2666,
        "size": 102808
    },
    "EDIT_E.CHR": {
        "lba": 2491,
        "size": 356811
    },
    "HOW_N_E.CHR": {
        "lba": 893,
        "size": 40919
    },
    "HOW_P_E.CHR": {
        "lba": 971,
        "size": 148920
    },
    "HOW_TO_N.BIN": {
        "lba": 841,
        "size": 104984
    },
    "HOW_TO_P.BIN": {
        "lba": 913,
        "size": 117828
    },
    "HOW_TO_V.BIN": {
        "lba": 1044,
        "size": 134340
    },
    "HOW_V_E.CHR": {
        "lba": 1110,
        "size": 234438
    },
    "INIT_MAP.BIN": {
        "lba": 97,
        "size": 34
    },
    "INIT_MAP.CRT": {
        "lba": 98,
        "size": 438272
    },
    "JLOGO.BIN": {
        "lba": 554,
        "size": 15816
    },
    "JLOGO_E.CHR": {
        "lba": 527,
        "size": 53448
    },
    "LOGO_MAP.BIN": {
        "lba": 312,
        "size": 34
    },
    "LOGO_MAP.CRT": {
        "lba": 313,
        "size": 438272
    },
    "MODE.BIN": {
        "lba": 1287,
        "size": 15408
    },
    "MODE_E.CHR": {
        "lba": 1225,
        "size": 125559
    },
    "NORMAL.BIN": {
        "lba": 1760,
        "size": 67504
    },
    "NORMAL_E.CHR": {
        "lba": 1329,
        "size": 880883
    },
    "PUZZLE.BIN": {
        "lba": 2231,
        "size": 202672
    },
    "PUZZLE_E.CHR": {
        "lba": 1793,
        "size": 895279
    },
    "RANKING.BIN": {
        "lba": 1324,
        "size": 10008
    },
    "RANK_E.CHR": {
        "lba": 1295,
        "size": 58592
    },
    "SDDRVS.TSK": {
        "lba": 84,
        "size": 25556
    },
    "TDEMO.BIN": {
        "lba": 604,
        "size": 18992
    },
    "TDEMO_E.CHR": {
        "lba": 562,
        "size": 84823
    },
    "TET_ABS.TXT": {
        "lba": 22,
        "size": 16
    },
    "TET_BIB.TXT": {
        "lba": 23,
        "size": 16
    },
    "TET_CPY.TXT": {
        "lba": 21,
        "size": 24
    },
    "TITLE.BIN": {
        "lba": 774,
        "size": 135800
    },
    "TITLE_E.CHR": {
        "lba": 614,
        "size": 327315
    },
    "VSPUZ.BIN": {
        "lba": 2443,
        "size": 96944
    },
    "VSPUZ_E.CHR": {
        "lba": 2330,
        "size": 231038
    }
}

# Mode overlays (code) by on-disc name; *_E.CHR are their paired graphics.
# Categories are evidence-only: nothing below is a claimed unlock.
MODE_OVERLAYS = {
    "TITLE.BIN": "title screen",
    "MODE.BIN": "mode select menu",
    "NORMAL.BIN": "Normal mode",
    "PUZZLE.BIN": "Puzzle mode",
    "VSPUZ.BIN": "versus puzzle",
    "EDIT.BIN": "puzzle Edit mode",
    "RANKING.BIN": "ranking screen",
    "TDEMO.BIN": "title demo",
    "HOW_TO_N.BIN": "how-to Normal",
    "HOW_TO_P.BIN": "how-to Puzzle",
    "HOW_TO_V.BIN": "how-to Versus",
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_sector(f, lba: int) -> bytes:
    """User data (2048 B) of a MODE1/2352 sector."""
    f.seek(lba * 2352 + 16)
    return f.read(2048)


def parse_iso(f) -> dict:
    pvd = read_sector(f, 16)
    if pvd[1:6] != b"CD001":
        raise ValueError("not ISO9660")
    root = pvd[156:190]
    out = {}

    def walk(lba, ln, prefix):
        d = b"".join(read_sector(f, lba + i) for i in range((ln + 2047) // 2048))
        o = 0
        while o < len(d):
            n = d[o]
            if n == 0:
                o = (o // 2048 + 1) * 2048
                continue
            r = d[o:o + n]
            o += n
            name = r[33:33 + r[32]].decode("latin1")
            if name in ("\x00", "\x01"):
                continue
            lb = struct.unpack("<I", r[2:6])[0]
            sz = struct.unpack("<I", r[10:14])[0]
            name = name.split(";")[0]
            if r[25] & 2:
                walk(lb, sz, prefix + name + "/")
            else:
                out[prefix + name] = {"lba": lb, "size": sz}

    walk(struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0], "")
    return out


def ip_header(f) -> dict:
    h = read_sector(f, 0)
    return {"magic": h[:16].decode("latin1").strip(),
            "product": h[0x20:0x2A].decode("latin1").strip(),
            "version": h[0x2A:0x30].decode("latin1").strip(),
            "date": h[0x30:0x38].decode("latin1"),
            "area": h[0x40:0x4A].decode("latin1").strip(),
            "title": h[0x60:0xD0].decode("latin1").strip()}


def inventory() -> dict:
    """Honest category inventory: static evidence only, no unlock claims."""
    cats = {c: [] for c in ("characters", "hidden_characters", "modes", "levels",
                           "stages", "costumes", "items", "extras")}
    cats["modes"] = [{"name": v, "file": k, "status": "present_unknown_lock"}
                     for k, v in MODE_OVERLAYS.items()]
    for c in ("characters", "hidden_characters", "costumes", "items"):
        cats[c] = [{"status": "not_present", "evidence": "no character/costume/item assets among the 33 ISO files (puzzle game)"}]
    for c in ("levels", "stages", "extras"):
        cats[c] = [{"status": "unknown", "evidence": "per-mode level tables inside overlays not yet traced"}]
    return {"game_id": GAME_ID, "status": "research_only", "categories": cats}
