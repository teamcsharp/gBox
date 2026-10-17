"""Metroid Prime 2 - Echoes (GameCube, G2ME01 USA) -- owned-disc inventory for character-replacement work.

The assigned catalog game b1d99fc6a49a6d53 is the HyperSpin Dolphin image
"collections/Nintendo GameCube/roms/Metroid Prime 2 - Echoes (USA).iso"; the same bytes are also
present in the gc-iso QuickSwap2 library.  This module only READS the plain image through
`gcdisc.GCDisc` (the source is never modified); the executable is `default.dol` in the FST.

This is Retro Studios' proprietary engine (NOT Unreal: the assimilation fingerprint's "Unreal Engine
4/5 0.73" is wrong -- G2ME01 is a 2004 GameCube disc).  Container layout (215 files):

  *.pak              the "Prime pak" archive (version 0x00030005).  A pak is a section table of
                     [u32 FOURCC type][u32 id][u32 name_len][name bytes] entries (NO padding between
                     entries, so names are packed tightly and the next entry can start unaligned),
                     followed by the section payloads.  Section types seen on this disc:
                        CMDL model geometry, CSKR skeleton/rig, ANCS animation character set,
                        ANIM animation (nested inside ANCS), TXTR texture, CINF character bone info,
                        AFSM animation state machine, MLVL world level (the levels carry the bulk of
                        the character CMDL/CSKR/ANCS/TXTR data as nested resources, so the top-level
                        TOC under-counts the real character asset population).
  RelProd/*.rel      one REL module per actor/enemy (Metroid, DarkSamus, SpacePirate, Ing, ...) --
                     the actor code; its CMDL/CSKR/ANCS data is referenced from the MLVL levels.
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
    """Prime pak section table: (version, reserved, [(type, id, name, toc_offset)]).

    Entries are [u32 type][u32 id][u32 name_len][name] with NO inter-entry padding; names may end
    mid-word so the next entry starts unaligned.  The payload for the first section begins at the
    byte right after the last name (each section's own header carries its size).
    """
    if len(data) < 0x10:
        raise ValueError("pak too short for a header")
    version, reserved, count = struct.unpack_from(">III", data, 0)
    if version != PAK_VERSION:
        raise ValueError(f"pak version 0x{version:08x}, expected 0x{PAK_VERSION:08x}")
    off, entries = 0x0C, []
    for i in range(count):
        if off + 12 > len(data):
            raise ValueError(f"pak TOC overrun at entry {i} (offset {off:#x})")
        typ = data[off:off + 4].decode("latin-1")
        sid = struct.unpack_from(">I", data, off + 4)[0]
        nlen = struct.unpack_from(">I", data, off + 8)[0]
        if nlen > 256 or off + 12 + nlen > len(data):
            raise ValueError(f"pak entry {i} name length {nlen} runs past the file (offset {off:#x})")
        name = data[off + 12:off + 12 + nlen].decode("latin-1")
        entries.append((typ, sid, name, off))
        off += 12 + nlen          # no padding; next entry may be unaligned
    return version, reserved, entries


def section_types(data: bytes) -> Counter:
    """Count section FOURCC types in one pak's TOC."""
    c = Counter()
    for typ, _sid, _name, _o in parse_pak_toc(data)[2]:
        c[typ] += 1
    return c


def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(iso)
    hdr = disc_header(disc._r(0, 0x440))
    if hdr["disc_id"] != DISC_ID:
        raise ValueError(f"{iso}: disc id {hdr['disc_id']}, expected {DISC_ID}")
    dol = disc.dol()
    types: Counter = Counter()
    paks: list[dict] = []
    levels: list[dict] = []
    for name in sorted(n for n in disc.files if n.lower().endswith(".pak")):
        raw = disc.read(name)
        t = section_types(raw)
        types.update(t)
        paks.append({"file": name, "size": len(raw), "sections": sum(t.values()),
                     "types": dict(t), "sha256": _SHA(raw)})
        if "MLVL" in t:
            for typ, sid, sname, _o in parse_pak_toc(raw)[2]:
                if typ == "MLVL":
                    levels.append({"pak": name, "name": sname, "id": f"{sid:08x}"})
    # The REL modules are the actor (enemy/player) code; their models are level-nested resources.
    rels = sorted(n for n in disc.files if n.startswith("RelProd/") and n.endswith(".rel"))
    return {
        "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
        "source": {"path": str(source) if source else None, "sha256": source_sha256,
                   "format": "GameCube ISO (plain .iso)", "image": str(iso)},
        "disc": hdr, "files": len(disc.files),
        "dol": {"name": "default.dol", "size": len(dol), "sha256": _SHA(dol),
                "entry": hex(struct.unpack_from(">I", dol, 0xE0)[0])},
        "engine": "Retro Studios proprietary (pak/rel/dsp/thp); NOT Unreal -- assimilation fingerprint refuted",
        "section_types": dict(types),
        "character_sections": {t: types.get(t, 0) for t in CHAR_TYPES},
        "levels": levels, "actor_rels": len(rels), "actor_rel_examples": rels[:12],
        "launch": {"core": "dolphin", "prereq": "GameCube BIOS optional; Dolphin 5.0+ boots G2ME01",
                   "mod_base": "a mod rebuilds a copy of the ISO; the source image is never modified"},
    }


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
