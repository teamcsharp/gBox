"""Metroid Prime 2 - Echoes (GameCube, G2ME01 USA) -- owned-disc inventory for character-replacement work.

The assigned catalog game b1d99fc6a49a6d53 is the HyperSpin Dolphin image
"collections/Nintendo GameCube/roms/Metroid Prime 2 - Echoes (USA).gcz"; a plain ISO also
exists in the QuickSwap2 library. This module reads either representation through
`gcdisc.GCDisc` (the source is never modified); the executable is `default.dol` in the FST.

This is Retro Studios' proprietary engine (NOT Unreal: the assimilation fingerprint's "Unreal Engine
4/5 0.73" is wrong -- G2ME01 is a 2004 GameCube disc).  Container layout (215 files):

  *.pak              Prime archives version 0x00030005: exported-name records are followed
                     by a separate resource table (flags, FOURCC, id, size, absolute offset).
                     Count model/rig/animation/texture assets from that resource table, not
                     just exported names. Payload decoding remains reader-stage work.
  RelProd/*.rel      one REL module per actor/enemy (Metroid, DarkSamus, SpacePirate, Ing, ...) --
                     the actor code; resource IDs link actor and level data.
  Audio/*.dsp        music/sfx; AudioGrp.pak carries AGSC/DGRP/STLC/ATBL audio tables.
  Video/*.thp        THP video; opening.bnr banner; Standard.ntwk network config.

`python -m gbox.prime_inventory ISO --source-sha256 SHA --out manifest.json` writes the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from .metroidprime_inventory import pak_directory, fourcc

GAME_IDS = {"b1d99fc6a49a6d53": "Metroid Prime 2 - Echoes (USA)"}
DISC_ID = "G2ME01"
GC_MAGIC = 0xC2339F3D
PAK_VERSION = 0x00030005
# The character/asset section FOURCCs present on this disc, grouped by role.
CHAR_TYPES = ("CMDL", "CSKR", "ANCS", "ANIM", "CINF", "AFSM")
MODEL_TYPES = ("CMDL", "CSKR", "ANCS")
TEX_TYPES = ("TXTR", "FONT")
LEVEL_TYPES = ("MLVL", "MREA")

_SHA = lambda b: hashlib.sha256(b).hexdigest()


def disc_header(head: bytes) -> dict:
    """Boot header (first 0x440 bytes) -> identity and DOL/FST location."""
    if len(head) < 0x430:
        raise ValueError("disc header too short")
    if struct.unpack_from(">I", head, 0x1C)[0] != GC_MAGIC:
        raise ValueError("not a GameCube disc (magic at 0x1C)")
    dol_off, fst_off, fst_size = struct.unpack_from(">III", head, 0x420)
    return {"disc_id": head[:6].decode("ascii", "replace"), "maker": head[4:6].decode("ascii", "replace"),
            "disc_number": head[6] + 1, "version": head[7],
            "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "dol_offset": dol_off, "fst_offset": fst_off, "fst_size": fst_size}


def parse_pak_toc(data: bytes) -> tuple[int, int, list[tuple[str, int, str, int]]]:
    """Exported names only, after validating the complete archive resource directory."""
    directory=pak_directory(data)
    off=12;names=[]
    for record in directory['names']:
        names.append((fourcc(record['type']),record['id'],record['name'],off))
        off+=12+len(record['name'].encode('latin-1'))
    return directory['version'],struct.unpack_from('>I',data,4)[0],names

def section_types(data: bytes) -> Counter:
    """Count all resource records, including assets without exported names."""
    return Counter(fourcc(r['type']) for r in pak_directory(data)['resources'])

def _source_hash(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None) -> dict:
    from .gcdisc import GCDisc

    actual_sha256=_source_hash(iso)
    if source_sha256 is not None and source_sha256.lower()!=actual_sha256:
        raise ValueError("Source SHA-256 mismatch")
    disc = GCDisc(iso)
    try:
        hdr = disc_header(disc._r(0, 0x440))
        if hdr["disc_id"] != DISC_ID:
            raise ValueError(f"{iso}: disc id {hdr['disc_id']}, expected {DISC_ID}")
        dol = disc.dol()
        types: Counter = Counter()
        paks: list[dict] = []
        levels: list[dict] = []
        for name in sorted(n for n in disc.files if n.lower().endswith(".pak")):
            if disc.files[name][1]>512*1024*1024:
                raise ValueError("PAK exceeds inventory read limit")
            raw = disc.read(name)
            directory=pak_directory(raw)
            t = Counter(fourcc(r["type"]) for r in directory["resources"])
            types.update(t)
            paks.append({"file": name, "size": len(raw), "sections": sum(t.values()),
                         "types": dict(t), "sha256": _SHA(raw), "exported_names":directory["name_count"]})
            for entry in directory["names"]:
                if fourcc(entry["type"])=="MLVL":
                    levels.append({"pak":name,"name":entry["name"],"id":f"{entry['id']:08x}"})
        # REL names are code-module inventory; model ownership needs resource-ID analysis.
        rels = sorted(n for n in disc.files if n.startswith("RelProd/") and n.endswith(".rel"))
        return {
            "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
            "source": {"path": str(iso), "sha256": actual_sha256, "label": str(source) if source else None,
                       "format": "Dolphin GCZ" if str(iso).lower().endswith(".gcz") else "GameCube ISO", "image": str(iso)},
            "disc": hdr, "files": len(disc.files),
            "dol": {"name": "default.dol", "size": len(dol), "sha256": _SHA(dol),
                    "entry": hex(struct.unpack_from(">I", dol, 0xE0)[0])},
            "engine": "Retro Studios proprietary (pak/rel/dsp/thp); NOT Unreal -- assimilation fingerprint refuted",
            "paks": paks,
            "section_types": dict(types),
            "character_sections": {t: types.get(t, 0) for t in CHAR_TYPES},
            "levels": levels, "actor_rels": len(rels), "actor_rel_examples": rels[:12],
            "launch": {"core": "dolphin", "prereq": "GameCube BIOS optional; Dolphin 5.0+ boots G2ME01",
                       "mod_base": "a mod rebuilds a copy of the ISO; the source image is never modified"},
        }
    finally:
        disc.f.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Metroid Prime 2 (G2ME01) owned-disc inventory manifest")
    ap.add_argument("iso", type=Path)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.iso, a.source, a.source_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
