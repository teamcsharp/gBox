"""Enter the Matrix (USA, GameCube GMXE70, Disc 2): exact build identity and disc inventory.

The GameCube build packs the same Shiny Entertainment content as the PS2 SLUS-20454 disc
(gbox.etm_inventory) into ``wad2.dfu`` (Disc 2) / ``wad2_b.dfu``, one hashed archive read by
``gbox.shiny_dfu``.  Two endian rules, recovered from the owned disc and verified against the files:

* the DFU archive header + directory are BIG-endian on the GameCube (PowerPC): the shared
  ``Dfu`` reader is called with ``endian=">"`` and ``parts=("wad2.dfu", "wad2_b.dfu")``.
* the tables INSIDE the archive (``Actors\\ActorHeadersV4.Bin``, ``Actors\\ModelHeadersV4.Bin``)
  are little-endian data, byte-for-byte the PC/PS2 authoring format; the archive directory is the
  only thing the GameCube executable stores in its native byte order.

Facts (Disc 2, ``Enter the Matrix (USA) (Disc 2).gcz``, sha256 043f94ad…):
  * disc header game id ``GMXE70``, title ``Enter The Matrix``; main.dol 4,074,880 B
    (sha256 43487093…); FST lists 197 files.
  * ``wad2.dfu`` 932,722,688 B + ``wad2_b.dfu`` 0 B (empty on Disc 2) = 5,874 entries, seeds
    (22313, 2067, 674), flags 0x20, data base 0x17000, 3 duplicate name-hashes.
  * ``movies/*.vid`` 34 files (``VID1`` container), ``text/*.bin`` 159 files (LE u32 offset tables),
    ``wad_adh.dfu`` 750,848 B (smallest part: 6,948 x 128-byte raw records), ``opening.bnr``.
  * roster: ``Actors\\ModelHeadersV4.Bin`` (288 x 0x50 path records) + ``Actors\\ActorHeadersV4.Bin``
    (404 x 0x60 records, LE ``flags / name[16] / model / class``).  Characters: Niobe (costumes
    1-5 + phase), Ghost, Trinity, Morpheus, AgentSmith, Seraph, Twins, Sparks, … (the same 69-entry
    roster as the PS2 build, gbox.etm_models.roster()).
  * model format ``actors\\*.dcn`` "DC patch models" (gbox.etm_models: bicubic Bezier quad /
    cubic Bezier triangle / plain-triangle patches, one 89-joint skeleton, checksum 0x002e5ea3,
    4/8-bit palettised textures in-model).  Animations ``animation\\*.asb``, levels ``levels\\*.3d2``.

Known gap (analysis stage): the header tables and list files resolve by their plaintext name-hash
(``Actors\\ActorHeadersV4.Bin`` etc.), but the *content* files (``actors\\*.dcn``, ``animation\\*.asb``,
``levels\\*.3d2``) do NOT resolve under their PS2 names on the GameCube — the content names hash
differently here, so the character models can be enumerated from ModelHeadersV4.Bin but not yet
extracted by name.  This is the next reverse-engineering step (recover the GameCube content-name
hash from ``main.dol``'s DFU lookup).

    python -m gbox.etm_gc_inventory <disc2.gcz> [--json out.json]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from .gcdisc import GCDisc
from .shiny_dfu import Dfu, DfuError

GAME_ID = "GMXE70"
TITLE = "Enter The Matrix"
SERIAL = "GMXE70"  # disc header game id; no distinct serial on the GC build
DOL_SIZE = 4074880
DOL_SHA256 = "4348709361c1c5eae482bd87f5df85d96b82125fd5e3533ed6c1332434b7b58f"
GCZ_SHA256 = "043f94addf428102fc832daa2937bc17e0d330242b5d8e50d844936821eb8d86"
DFU_PARTS = ("wad2.dfu", "wad2_b.dfu")
DFU_COUNT = 5874
SEEDS = (22313, 2067, 674)
ACTOR_HEADERS = "Actors\\ActorHeadersV4.Bin"
MODEL_HEADERS = "Actors\\ModelHeadersV4.Bin"
ACTOR_REC, MODEL_REC = 0x60, 0x50
CLASSES = {10: "hero", 11: "npc", 12: "story_npc"}


class FormatError(ValueError):
    pass


class GcDisc:
    """Adapt a read-only gbox.gcdisc.GCDisc to the shiny_dfu ``Dfu`` disc interface
    (``files {NAME: (off, size)}``, ``size(name)``, ``read(name, off, n)`` — byte offsets, no sectors)."""

    def __init__(self, disc: GCDisc):
        self.disc = disc
        self.files = disc.files

    def size(self, name: str) -> int:
        return self.disc.files[name][1]

    def read(self, name: str, off: int, n: int) -> bytes:
        return self.disc._r(self.disc.files[name][0] + off, n)


def identify(disc: GCDisc) -> dict:
    dol = disc.dol()
    wads = {n: disc.files[n][1] for n in DFU_PARTS if n in disc.files}
    return {"game_id": disc.game_id, "title": disc.title, "num_files": len(disc.files),
            "dol_size": len(dol), "dol_sha256": hashlib.sha256(dol).hexdigest(),
            "wad_sizes": wads,
            "exact_build": disc.game_id == GAME_ID and hashlib.sha256(dol).hexdigest() == DOL_SHA256
            and wads.get("wad2.dfu") == 932722688}


def roster_paths(dfu: Dfu) -> list[str]:
    """All model paths named by the (little-endian) ModelHeadersV4.Bin table."""
    m = dfu.read(MODEL_HEADERS)
    if len(m) % MODEL_REC:
        raise FormatError("ModelHeadersV4.Bin is not whole 0x50 records")
    return [m[i:i + MODEL_REC].split(b"\0")[0].decode("latin-1")
            for i in range(0, len(m), MODEL_REC)]


def actors(dfu: Dfu) -> list[dict]:
    a = dfu.read(ACTOR_HEADERS)
    if len(a) % ACTOR_REC:
        raise FormatError("ActorHeadersV4.Bin is not whole 0x60 records")
    models = roster_paths(dfu)
    out = []
    for i in range(0, len(a), ACTOR_REC):
        r = a[i:i + ACTOR_REC]
        name = r[4:0x14].split(b"\0")[0].decode("latin-1")
        if not name:
            continue
        model, cls = struct.unpack_from("<i", r, 0x14)[0], struct.unpack_from("<i", r, 0x1C)[0]
        out.append({"index": i // ACTOR_REC, "name": name, "class": cls,
                    "kind": CLASSES.get(cls, "prop"),
                    "model": models[model] if 0 <= model < len(models) else None})
    return out


def inventory(path) -> dict:
    disc = GCDisc(str(path))
    ident = identify(disc)
    if not ident["exact_build"]:
        raise FormatError(f"not the owned Disc 2 build: {ident}")
    try:
        dfu = Dfu(GcDisc(disc), "etm", endian=">", parts=DFU_PARTS)
    except DfuError as e:
        raise FormatError(f"{DFU_PARTS[0]}: {e}") from None
    acts = actors(dfu)
    paths = roster_paths(dfu)
    from . import etm_models as M
    roster = [r["model"] for r in M.roster()]
    # content-name hash does not resolve on GC: report which header tables do.
    return {
        "identity": ident,
        "archive": {"parts": dfu.parts, "sizes": dfu.part_sizes, "entries": dfu.count,
                    "seeds": dfu.seeds, "flags": hex(dfu.flags), "data_base": hex(dfu.base),
                    "duplicate_hashes": dfu.duplicates,
                    "compressed": sum(e.compressed for e in dfu.entries),
                    "named_headers": [n for n in (ACTOR_HEADERS, MODEL_HEADERS,
                                                  "Animation\\AnimList.txt", "Levels\\LevelList.txt")
                                      if n in dfu]},
        "models": len(paths), "actors": len(acts),
        "character_models": [p for p in paths if p.lower().endswith(".dcn")],
        "roster_matches": sorted(set(roster) & set(paths)),
        "formats": {"character": "actors\\*.dcn (gbox.etm_models, DC patch models)",
                    "animations": "animation\\*.asb (not decoded)",
                    "levels": "levels\\*.3d2", "movies": "movies\\*.vid (VID1)",
                    "skeleton_checksum": "0x002e5ea3"},
        "gap": "content names (.dcn/.asb/.3d2) do not resolve by PS2 name-hash on GC",
    }


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
    print(json.dumps({k: inv[k] for k in ("identity", "archive", "models", "actors")}, indent=1, default=str))
    print(f"{len(inv['character_models'])} character model paths, {len(inv['roster_matches'])} match the PS2 roster")
    return 0


if __name__ == "__main__":
    sys.exit(main())
