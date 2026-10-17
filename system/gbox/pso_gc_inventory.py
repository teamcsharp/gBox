"""Phantasy Star Online Episode I & II (GameCube, US GPOE8P) disc inventory.

Resolves the owned build (this runs against the "Return To Ragol V1.0.3 (Widescreen)" image, a community
build of PSO Ep I&II), verifies the platform label against the disc header, hashes the executables, and
enumerates the character model / texture / animation inventory with per-file sha256. Read-only on the
source image; the source_sha256 is recorded, never recomputed.

Layout facts (US GC build):
  - executables: PsoV3.dol (main), iwanaga.dol / iwanagaD.dol / switcher.dol / switcherD.dol (debug/tools)
  - per class letter A..Z: pl{X}bdy00.nj (body), pl{X}hedNN.nj (heads), pl{X}haiNN.nj (hairs),
    pl{X}capNN.nj (caps), pl{X}nj.bml (BML archive of the same parts), pl{X}smp.rel (samples),
    pl{X}tex.afs (PVR texture bank). Letters: A..I = DC-era classes, J=HUcaseal, K=RAmarl, L=FOmar,
    M..Z = extra/possibly-unused slots.
  - animations: PlyMotionData.rlc ("RelChunkVer0.20" motion chunk bank, 572 motions),
    PlyMotionNpcTown.cpt/.rel (NPC town motions), CharaMakingMot.bml (character creation motions),
    ItemMagMotion.dat, npc_xNN_data.rel, npcplayerchar.dat ("NOL" bundle)
  - models are Ninja chunk models (NJCM magic, big-endian on GC); textures GVM/GVR/GVP/TP/TPL/PRS; audio ADX/ACX
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from .gcdisc import GCDisc

CLASS_NAMES = {
    "A": "HUmar", "B": "HUnewearl", "C": "HUcast", "D": "RAmar", "E": "RAcast", "F": "RAcaseal",
    "G": "FOmarl", "H": "FOnewm", "I": "FOnewearl", "J": "HUcaseal", "K": "RAmarl", "L": "FOmar",
}
# M..Z exist on the disc (bdy/hed present) but are not part of the classic 12-class roster.

CHAR_RE = re.compile(r"^pl([a-z])(bdy|hed|hai|cap)(\d{2})\.nj$", re.I)
CHAR_EXTRA = re.compile(r"^pl([a-z])(nj\.bml|smp\.rel|tex\.afs|smpnj\.afs)$", re.I)
NPC_MOTION_RE = re.compile(r"^npc_[a-z]\d{2}_data\.rel$", re.I)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dol_info(dol: bytes) -> dict:
    """DOL section summary: entry point, bss, and the nonzero (offset, addr, size) sections."""
    text_off, text_addr = struct.unpack_from(">7I", dol, 0), struct.unpack_from(">7I", dol, 0x1C)
    data_off, data_addr = struct.unpack_from(">11I", dol, 0x38), struct.unpack_from(">11I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    bss_addr, bss_size = struct.unpack_from(">II", dol, 0xD8)
    entry = struct.unpack_from(">I", dol, 0xE8)[0]
    sections = []
    for offs, addrs, n in ((text_off, text_addr, 7), (data_off, data_addr, 11)):
        for i in range(n):
            s = sizes[i]
            if s:
                sections.append({"kind": "text" if n == 7 else "data", "offset": offs[i],
                                 "address": addrs[i], "size": s})
    return {"size": len(dol), "entry": entry, "bss": {"address": bss_addr, "size": bss_size},
            "sections": sections}


def _kind(name: str) -> str:
    n = name.lower()
    if n.endswith((".dol", ".elf")):
        return "executable"
    if CHAR_RE.match(n) or CHAR_EXTRA.match(n):
        return "character"
    if "plymotion" in n or "charamakingmot" in n or "itemmagmotion" in n or NPC_MOTION_RE.match(n) \
            or "npcplayerchar" in n or "gameshowchar" in n:
        return "animation"
    if n.endswith((".gvm", ".gvr", ".gvp", ".tpl", ".tp")) or "texture" in n or "netbanner" in n:
        return "texture"
    if n.endswith((".adx", ".acx")):
        return "audio"
    if n.endswith(".sfd"):
        return "video"
    if n.endswith(".gsl") or n.startswith("map_") or n.startswith("gsl_"):
        return "stage"
    if n.startswith("quest") or "/quest/" in n:
        return "quest"
    return "other"


def inventory(path, source_sha256: str | None = None, source_path: str | None = None) -> dict:
    with open(path, "rb") as f:
        header = f.read(0x100)
    if len(header) < 0x100:
        raise ValueError("not a GameCube disc: file too short")
    game_id = header[:6].decode("ascii", "replace")
    magic = header[0x1C:0x20].hex()
    if game_id[0] not in "GD" or magic != "c2339f3d":
        raise ValueError(f"not a GameCube disc: id={game_id} magic={magic}")
    platform = "gamecube"
    disc = GCDisc(path)
    title = disc.title

    execs = []
    characters: dict[str, dict] = {}
    groups: dict[str, list[dict]] = {"animation": [], "texture": [], "audio": [], "video": [],
                                     "stage": [], "quest": [], "other": []}
    totals: dict[str, int] = {}
    for name, (off, size) in sorted(disc.files.items()):
        rec = {"name": name, "size": size, "sha256": _sha(disc.read(name))}
        kind = _kind(name)
        totals[kind] = totals.get(kind, 0) + 1
        if kind == "executable":
            rec["dol"] = _dol_info(disc.read(name))
            execs.append(rec)
        elif kind == "character":
            if (m := CHAR_EXTRA.match(name)):
                letter = m.group(1).upper()
                field = {"nj.bml": "bml", "smp.rel": "smp", "tex.afs": "tex_afs",
                         "smpnj.afs": "smp_afs"}[m.group(2).lower()]
            else:
                m = CHAR_RE.match(name)
                letter, part, idx = m.group(1).upper(), m.group(2).lower(), int(m.group(3))
                field = {"bdy": "bodies", "hed": "heads", "hai": "hairs", "cap": "caps"}[part]
                rec["part"] = part
                rec["index"] = idx
            c = characters.setdefault(letter, {"class": CLASS_NAMES.get(letter), "files": {}})
            c["files"].setdefault(field, []).append(rec)
        else:
            groups[kind].append(rec)

    return {
        "game_id": game_id,
        "title": title,
        "platform": platform,
        "region": "USA" if game_id[3] in "8E" else game_id[3],
        "source_sha256": source_sha256,
        "source_path": source_path,
        "disc_magic": magic,
        "fst_file_count": len(disc.files),
        "executables": execs,
        "characters": {k: v for k, v in sorted(characters.items())},
        "assets": groups,
        "totals_by_kind": dict(sorted(totals.items())),
        "launch": {"core": "dolphin", "language_default": "english", "notes":
                   "GC disc boots under Dolphin/RetroArch-dolphin without IPL BIOS; agent tests use 2% audio"},
        "notes": [
            "models are big-endian Ninja chunk models (NJCM magic); textures PVR in AFS banks (GC AFS entry "
            "layout differs from the DC reader's and is analysis-stage work)",
            "PlyMotionData.rlc = 'RelChunkVer0.20' motion bank (572 motions); PlyMotionNpcTown.cpt is compressed",
            "pl{X}nj.bml archives hold the same parts as the loose pl{X}*.nj files (13 entries for class A)",
            "npcplayerchar.dat is a NOL-format bundle (magic 'NOL\\0')",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="GameCube ISO")
    ap.add_argument("--source-sha256", default=None)
    ap.add_argument("--source-path", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    m = inventory(args.src, source_sha256=args.source_sha256, source_path=args.source_path)
    Path(args.out).write_text(json.dumps(m, indent=2))
    print(json.dumps({k: v for k, v in m.items() if k != "assets"}, indent=2))


if __name__ == "__main__":
    main()
