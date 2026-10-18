"""Enter the Matrix (USA, GameCube GMXE70, Disc 2): exact build identity and disc inventory.

The GameCube build uses a Shiny Entertainment archive, also used by PS2 SLUS-20454
(gbox.etm_inventory), named ``wad2.dfu`` (Disc 2) / ``wad2_b.dfu``, one hashed archive read by
``gbox.shiny_dfu``.  Two endian rules, recovered from the owned disc and verified against the files:

* the DFU archive header + directory are BIG-endian on the GameCube (PowerPC): the shared
  ``Dfu`` reader is called with ``endian=">"`` and ``parts=("wad2.dfu", "wad2_b.dfu")``.
* the tables INSIDE the archive (``Actors\\ActorHeadersV4.Bin``, ``Actors\\ModelHeadersV4.Bin``)
  use little-endian model indices and class fields. This observation does not establish the
  byte order or layout of the unresolved character assets themselves.

The exact owned Disc 2 exposes 5,874 archive entries, 288 model-path records and 387 named
actors in 404 actor records. These are inventory facts, not a verified GameCube model reader.
The named .dcn paths do not currently resolve with the existing ETM name hash. Whether this is a
name transformation, another hash, or another storage mapping remains unverified. No GameCube
model/skeleton/texture byte layout or character replacement is claimed by this module.

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

    offset_unit = 1  # FST offsets are bytes; PS2 ISO readers use 2048-byte sectors.

    def __init__(self, disc: GCDisc):
        self.disc = disc
        self.files = disc.files

    def size(self, name: str) -> int:
        return self.disc.files[name][1]

    def read(self, name: str, off: int, n: int) -> bytes:
        start, size = self.disc.files[name]
        if type(off) is not int or type(n) is not int or off < 0 or n < 0 or off + n > size:
            raise FormatError(f"{name}: read leaves the FST file")
        data = self.disc._r(start + off, n)
        if len(data) != n:
            raise FormatError(f"{name}: short read ({len(data)} of {n} bytes)")
        return data


def identify(disc: GCDisc) -> dict:
    # Bound the executable read before trusting its section offsets. The generic disc.dol()
    # follows the DOL header's extent; this inventory accepts only the known exact extent.
    header = disc._r(0, 0x440)
    if len(header) != 0x440:
        raise FormatError("short disc header")
    dol_offset = struct.unpack_from(">I", header, 0x420)[0]
    dh = disc._r(dol_offset, 0x100)
    if len(dh) != 0x100:
        raise FormatError("short DOL header")
    offsets, sizes = struct.unpack_from(">18I", dh, 0), struct.unpack_from(">18I", dh, 0x90)
    sections = [(o, n) for o, n in zip(offsets, sizes) if n]
    extent = max((o + n for o, n in sections), default=0)
    bounded = bool(sections) and all(o >= 0x100 and o + n <= DOL_SIZE for o, n in sections)
    dol = disc._r(dol_offset, DOL_SIZE) if bounded and extent == DOL_SIZE else b""
    digest = hashlib.sha256(dol).hexdigest() if len(dol) == DOL_SIZE else None
    wads = {n: disc.files[n][1] for n in DFU_PARTS if n in disc.files}
    return {"game_id": disc.game_id, "title": disc.title, "num_files": len(disc.files),
            "disc_number": header[6], "revision": header[7],
            "dol_size": extent, "dol_sha256": digest, "wad_sizes": wads,
            "exact_build": disc.game_id == GAME_ID and header[6:8] == b"\x01\x00"
            and digest == DOL_SHA256 and wads == {"wad2.dfu": 932722688, "wad2_b.dfu": 0}}


def roster_paths(dfu: Dfu) -> list[str]:
    """All model paths named by the (little-endian) ModelHeadersV4.Bin table."""
    m = dfu.read(MODEL_HEADERS, max_size=288 * MODEL_REC)
    if len(m) % MODEL_REC:
        raise FormatError("ModelHeadersV4.Bin is not whole 0x50 records")
    return [m[i:i + MODEL_REC].split(b"\0")[0].decode("latin-1")
            for i in range(0, len(m), MODEL_REC)]


def actors(dfu: Dfu) -> list[dict]:
    a = dfu.read(ACTOR_HEADERS, max_size=404 * ACTOR_REC)
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
    try:
        ident = identify(disc)
        if not ident["exact_build"]:
            raise FormatError(f"not the owned Disc 2 build: {ident}")
        try:
            dfu = Dfu(GcDisc(disc), "etm", endian=">", parts=DFU_PARTS)
            if (dfu.count, dfu.seeds, dfu.flags, dfu.base) != (DFU_COUNT, SEEDS, 0x20, 0x17000):
                raise FormatError("the archive directory differs from the owned Disc 2 layout")
            acts, paths = actors(dfu), roster_paths(dfu)
            if len(paths) != 288 or len(dfu.read(ACTOR_HEADERS, max_size=404 * ACTOR_REC)) != 404 * ACTOR_REC:
                raise FormatError("the header table counts differ from the owned Disc 2 layout")
            from . import etm_models as M
            roster = [r["model"] for r in M.roster()]
            content = [p for p in paths if p.lower().endswith(".dcn")]
            resolved = [p for p in content if p in dfu]
            return {
                "identity": ident,
                "archive": {"parts": dfu.parts, "sizes": dfu.part_sizes, "entries": dfu.count,
                            "endian": "big", "seeds": dfu.seeds, "flags": hex(dfu.flags),
                            "data_base": hex(dfu.base), "duplicate_hashes": dfu.duplicates,
                            "compressed": sum(e.compressed for e in dfu.entries),
                            "named_headers": [n for n in (ACTOR_HEADERS, MODEL_HEADERS,
                                "Animation\\AnimList.txt", "Levels\\LevelList.txt") if n in dfu]},
                "models": len(paths), "actors": len(acts), "character_models": content,
                "roster_matches": sorted(set(roster) & set(paths)),
                "resolved_model_names": resolved,
                "model_names_resolved": len(resolved),
                "capabilities": {"archive_inventory": True, "character_extraction": False,
                                 "character_replacement": False, "gameplay_verified": False},
                "gap": "GameCube model lookup/format and replacement remain unverified; "
                       "a path-table match is not an extracted character model",
            }
        except DfuError as error:
            raise FormatError(f"{DFU_PARTS[0]}: {error}") from None
    finally:
        disc.f.close()


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
