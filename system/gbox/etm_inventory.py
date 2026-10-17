"""Enter the Matrix (USA, PS2 SLUS-20454): exact build identity and asset inventory.

The catalog's "Enter the Matrix (USA)" windows_native entry (3f43b79a68a60b41) is not a PC install: HyperSpin files
the PS2 disc ``collections/Sony Playstation 2/roms/USA/Enter the Matrix (USA).chd`` under its "Microsoft XBOX" system.
No PC install of either Matrix game exists on this PC or the share (searched 2026-10-13), so this module (and the
reader / writer built on it) works on that disc, read straight out of the CHD v5 with ``gbox.chd`` (no chdman).

Facts (recovered from the disc and SLUS_204.54; nothing below comes from community notes, which don't cover it):

* disc: ISO9660 volume ``SLUS_20454``, ``SYSTEM.CNF`` ``BOOT2 = cdrom0:\\SLUS_204.54;1`` / ``VER = 2.00``; one MODE1
  track of 1,921,376 sectors (CHD sha1 ``0d5fb095...``). Game data: ``WAD1.DFU`` (1,007,788,032 B) + ``WAD1_B.DFU``
  (1,425,079,296 B) = one hashed archive of 9,690 files (gbox.shiny_dfu); 964 of them zlib-packed.
* names: ``Actors\\ActorHeadersV4.Bin`` (404 x 0x60 actor records: ``u32 flags, char name[16]``, ``+0x14 model``,
  ``+0x1c class`` 10 = hero / 11 = NPC / 12 = story NPC / 13+ props, weapons, vehicles) and
  ``Actors\\ModelHeadersV4.Bin`` (288 x 0x50 ``char path[80]``: ``actors\\<name>.dcn|dci|dc2``) name every model;
  ``Animation\\AnimList.txt`` and ``Levels\\LevelList.txt`` name animation sets and levels.
* characters: ``actors\\*.dcn`` "DC patch models" (gbox.etm_models): bicubic Bezier quad patches, cubic Bezier
  triangle patches and plain triangles, skinned to one shared 89-joint skeleton (checksum ``0x002e5ea3``, the same in
  every human model; the animation sets ``animation\\_default*.asb`` carry the matching skeleton), PS2 4/8-bit
  palettised textures inside the model file. Animations: ``animation\\*.asb`` (``_default.asb`` 7.9 MB holds the
  shared moves; format not decoded).

    python -m gbox.etm_inventory <ETM.chd | ETM.iso> [--json out.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from .shiny_dfu import Dfu, DfuError

GAME_ID = "3f43b79a68a60b41"
TITLE = "Enter the Matrix (USA)"
SERIAL = "SLUS-20454"
ELF = "SLUS_204.54"
ELF_SIZE = 4165216
ELF_SHA256 = "3b076e25c94d3517a567ac17b0c62028991150d184a10171eec21574aae4e26e"
VOLUME = "SLUS_20454"
CHD_SHA1 = "0d5fb09505041295ac665cf53f4d391386adfa46"
WAD_SIZES = (1007788032, 1425079296)
DFU_COUNT = 9690
SKELETON_CHECKSUM = 0x002E5EA3
CATALOG_REL = "collections/Sony Playstation 2/roms/USA/Enter the Matrix (USA).chd"
ACTOR_HEADERS = "Actors\\ActorHeadersV4.Bin"
MODEL_HEADERS = "Actors\\ModelHeadersV4.Bin"
ACTOR_REC, MODEL_REC = 0x60, 0x50
CLASSES = {10: "hero", 11: "npc", 12: "story_npc"}


class FormatError(ValueError):
    pass


def open_disc(path):
    """A CHD (v5, read in place) or a plain ISO -> a reader with files/size/read."""
    p = Path(path)
    with open(p, "rb") as f:
        magic = f.read(8)
    if magic == b"MComprHD":
        from .chd import ChdDisc
        return ChdDisc(p)
    from .defjam_inventory import Iso
    return Iso(p)


def system_cnf(disc) -> dict:
    out = {}
    for line in disc.read("SYSTEM.CNF").decode("latin-1").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def identify(disc) -> dict:
    """Which build is this: volume id, boot ELF (name, size, sha256), archive shape; exact_build when every field
    matches the owned USA disc the formats were recovered from."""
    cnf = system_cnf(disc)
    boot = re.sub(r"^cdrom0:\\?", "", cnf.get("BOOT2", "")).split(";")[0].upper()
    elf = disc.read(boot) if boot in disc.files else b""
    vol = getattr(disc, "pvd", None)
    if vol is None and getattr(disc, "path", None):
        with open(disc.path, "rb") as f:
            f.seek(16 * 2048)
            vol = f.read(2048)
    volume = vol[40:72].decode("latin-1").strip() if vol else ""
    wads = tuple(disc.size(n) for n in ("WAD1.DFU", "WAD1_B.DFU") if n in disc.files)
    out = {"volume": volume, "boot": boot, "version": cnf.get("VER"), "elf_size": len(elf),
           "elf_sha256": hashlib.sha256(elf).hexdigest() if elf else None, "wad_sizes": list(wads)}
    chd = getattr(disc, "chd", None)
    if chd is not None:
        out["chd_sha1"] = chd.h["sha1"]
        out["chd_codecs"] = chd.codec_counts()
    out["exact_build"] = bool(boot == ELF and out["elf_sha256"] == ELF_SHA256 and wads == WAD_SIZES)
    return out


def actors(dfu: Dfu) -> list[dict]:
    a, m = dfu.read(ACTOR_HEADERS), dfu.read(MODEL_HEADERS)
    if len(a) % ACTOR_REC or len(m) % MODEL_REC:
        raise FormatError("actor / model header tables are not whole records")
    models = [m[i:i + MODEL_REC].split(b"\0")[0].decode("latin-1") for i in range(0, len(m), MODEL_REC)]
    out = []
    for i in range(0, len(a), ACTOR_REC):
        r = a[i:i + ACTOR_REC]
        flags = struct.unpack_from("<I", r, 0)[0]
        name = r[4:0x14].split(b"\0")[0].decode("latin-1")
        model, cls = struct.unpack_from("<i", r, 0x14)[0], struct.unpack_from("<i", r, 0x1C)[0]
        if not name:
            continue
        out.append({"index": i // ACTOR_REC, "name": name, "flags": flags, "class": cls,
                    "kind": CLASSES.get(cls, "prop"), "model": models[model] if 0 <= model < len(models) else None})
    return out


def models(dfu: Dfu) -> list[dict]:
    m = dfu.read(MODEL_HEADERS)
    out = []
    for i in range(0, len(m), MODEL_REC):
        path = m[i:i + MODEL_REC].split(b"\0")[0].decode("latin-1")
        e = dfu.entry(path)
        out.append({"index": i // MODEL_REC, "path": path, "present": e is not None,
                    "size": e.size if e else None, "packed": e.packed if e else None})
    return out


def named(dfu: Dfu, extra: list[str] = ()) -> dict[int, str]:
    """hash -> name for every archive file a known list or the executable names."""
    names = {ACTOR_HEADERS, MODEL_HEADERS, "Animation\\AnimList.txt", "Levels\\LevelList.txt", *extra}
    for r in models(dfu):
        names.add(r["path"])
    for t in ("Animation\\AnimList.txt", "Levels\\LevelList.txt"):
        if t in dfu:
            sub = "animation\\" if t.startswith("Anim") else "levels\\"
            for line in dfu.read(t).decode("latin-1").splitlines():
                if line.strip():
                    names.add(sub + line.strip())
    return {dfu.hash(n): n for n in names if n in dfu}


def inventory(path) -> dict:
    disc = open_disc(path)
    ident = identify(disc)
    try:
        dfu = Dfu(disc, "etm")
    except DfuError as e:
        raise FormatError(f"WAD1.DFU: {e}") from None
    acts = actors(dfu)
    mods = models(dfu)
    from . import etm_models as M
    chars = [{"model": r["path"], "size": r["size"], "packed": r["packed"],
              "actors": [a["name"] for a in acts if a["model"] == r["path"] and a["kind"] != "prop"]}
             for r in mods if r["present"] and r["path"].lower().endswith(".dcn")
             and any(a["model"] == r["path"] and a["kind"] != "prop" for a in acts)]
    nm = named(dfu)
    return {"identity": ident, "archive": {"parts": dfu.parts, "sizes": dfu.part_sizes, "entries": dfu.count,
                                           "seeds": dfu.seeds, "data_base": dfu.base, "duplicate_hashes": dfu.duplicates,
                                           "compressed": sum(e.compressed for e in dfu.entries), "named": len(nm)},
            "actors": len(acts), "models": len(mods), "character_models": chars,
            "roster": [r["model"] for r in M.roster()],
            "formats": {"character": "actors\\*.dcn (gbox.etm_models)", "skeleton_checksum": hex(SKELETON_CHECKSUM),
                        "animations": "animation\\*.asb (not decoded)", "textures": "inside each .dcn (4/8-bit CLUT)"}}


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    out = None
    if "--json" in a:
        i = a.index("--json")
        out = a[i + 1]
        del a[i:i + 2]
    if not a:
        print(__doc__)
        return 2
    inv = inventory(a[0])
    if out:
        Path(out).write_text(json.dumps(inv, indent=1, default=str))
    print(json.dumps({k: inv[k] for k in ("identity", "archive", "actors", "models")}, indent=1, default=str))
    print(f"{len(inv['character_models'])} character models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
