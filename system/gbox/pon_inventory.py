"""The Matrix: Path of Neo (USA, PS2 SLUS-21273): exact build identity and asset inventory.

The catalog's windows_native entry b9ab2dd68f48dade is the PS2 disc ``collections/Sony Playstation 2/roms/USA/
Matrix, The - Path of Neo (USA).chd`` (HyperSpin files it under "Microsoft XBOX"; no PC install exists here), read
in place with ``gbox.chd``. Recovered from the disc and SLUS_212.73 (no community notes cover these formats):

* disc: volume ``SLUS_21273``, ``BOOT2 = cdrom0:\\SLUS_212.73;1`` / ``VER = 1.00``; ``WAD1.DFU`` 1,419,561,403 B
  (``WAD1_B.DFU`` is empty), 3,080 rows, nothing zlib-packed; streamed movies (``PS2\\?\\*.SFD``) and sound banks
  (``PS2\\SOUND\\*.WAD``) are plain ISO files.
* archive: Enter the Matrix's WAD1.DFU (gbox.shiny_dfu) with a second name hash (lookup ``0x1f5860``: ETM's hash +
  ``c << 8 * (i & 3)`` per character; every name without ``common`` is hashed as ``ps2\\`` + name). Names carry
  format versions: ``levels\\<level>.lvl_3``, ``levels\\%s.3d2_63``, ``levels\\%s.hdr_5``, ``levels\\rims\\%s.rim_5``,
  ``levels\\_global.rmp_5``, ``actors\\%s.dcs_11``.
* ``common\\misc\\ActorHeadersV11.Bin``: 444 x 0x140 actor records: three model paths (``char[64]`` each: LOD 0, 1, 2,
  ``actors\\<name>.dcn``) then ``+0xc4 char name[32]``.
* level packages ``levels\\<level>.lvl_3`` (58): ``u32 data start, u32 chunks, u32 0x000b003f, u32 0x00280007, u32,
  char author[32], char level[32]`` then at 0x80 ``chunks`` x ``{u32 id (CRC, routine 0x1f51b0), u32 offset, u32
  size, u32 type}``. Characters are not archive files: every level carries its own copies as type-3 chunks
  (``<model>.dcn_11``, a tagged successor of ETM's .dcn: ``_HEADER_`` / ``PATCHOBJ`` sections, not decoded yet);
  type 9 = animation sets (CORE, SHOOTING, STANCE_*), 4 = level geometry, 10 = Louie UI scripts (``SHINYBIN``).

    python -m gbox.pon_inventory <PoN.chd | PoN.iso> [--json out.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from .etm_inventory import open_disc, system_cnf
from .shiny_dfu import Dfu, DfuError

GAME_ID = "b9ab2dd68f48dade"
TITLE = "Matrix, The: Path of Neo (USA)"
SERIAL = "SLUS-21273"
ELF = "SLUS_212.73"
ELF_SIZE = 3525144
ELF_SHA256 = "e7d56d8df080e63f91627882d065b3c8290fe4c1d1c6f4dbf1eaeee94b3df3c1"
VOLUME = "SLUS_21273"
CHD_SHA1 = "217d206d156c8ce2117b211c14b3c38c67585864"
WAD_SIZES = (1419561403, 0)
DFU_COUNT = 3080
ACTOR_HEADERS = "common\\misc\\ActorHeadersV11.Bin"
ACTOR_REC = 0x140
LEVEL_FMT = "levels\\{}.lvl_3"
PKG_TABLE = 0x80
# chunk types identified from their contents (the rest are listed by number only)
CHUNK_TYPES = {1: "cluster list", 3: "model (.dcn_11)", 4: "level geometry", 8: "animation (.ach)",
               9: "animation set", 10: "Louie UI script (SHINYBIN)"}


class FormatError(ValueError):
    pass


def identify(disc) -> dict:
    cnf = system_cnf(disc)
    boot = cnf.get("BOOT2", "").split("\\")[-1].split(";")[0].upper()
    elf = disc.read(boot) if boot in disc.files else b""
    wads = tuple(disc.size(n) for n in ("WAD1.DFU", "WAD1_B.DFU") if n in disc.files)
    out = {"boot": boot, "version": cnf.get("VER"), "elf_size": len(elf),
           "elf_sha256": hashlib.sha256(elf).hexdigest() if elf else None, "wad_sizes": list(wads)}
    chd = getattr(disc, "chd", None)
    if chd is not None:
        out["chd_sha1"] = chd.h["sha1"]
    out["exact_build"] = bool(boot == ELF and out["elf_sha256"] == ELF_SHA256 and wads == WAD_SIZES)
    return out


def actors(dfu: Dfu) -> list[dict]:
    b = dfu.read(ACTOR_HEADERS)
    if len(b) % ACTOR_REC:
        raise FormatError("ActorHeadersV11 is not whole 0x140-byte records")
    out = []
    for i in range(0, len(b), ACTOR_REC):
        r = b[i:i + ACTOR_REC]
        models = [r[64 * k:64 * k + 64].split(b"\0")[0].decode("latin-1") for k in range(3)]
        name = r[0xC4:0xE4].split(b"\0")[0].decode("latin-1")
        if name or models[0]:
            out.append({"index": i // ACTOR_REC, "name": name, "models": [m for m in models if m]})
    return out


def parse_package(b: bytes) -> dict:
    """One level package: header, chunk rows (bounds-checked: inside the file, after the table, no overlap)."""
    if len(b) < PKG_TABLE:
        raise FormatError("shorter than the package header")
    start, count = struct.unpack_from("<2I", b)
    if not 0 < count < 4096 or not PKG_TABLE + 16 * count <= start <= len(b):
        raise FormatError(f"implausible package header (start 0x{start:x}, {count} chunks)")
    chunks, end = [], start
    for i in range(count):
        cid, off, size, typ = struct.unpack_from("<4I", b, PKG_TABLE + 16 * i)
        if off < start or off + size > len(b):
            raise FormatError(f"chunk {i} 0x{off:x}+0x{size:x} outside the package")
        c = {"index": i, "id": cid, "offset": off, "size": size, "type": typ, "kind": CHUNK_TYPES.get(typ, "?")}
        if typ == 3:                                       # the name field is 16 bytes: ".dcn_11" may be cut short
            mt = re.search(rb"([A-Za-z0-9_\-]{2,})\.d(?:c(?:n(?:_\d*)?)?)?\x00", b[off:off + 0x200])
            if mt:
                c["model"] = mt.group(1).decode("latin-1")
        chunks.append(c)
        end = max(end, off + size)
    return {"start": start, "count": count, "author": b[0x14:0x34].split(b"\0")[0].decode("latin-1"),
            "level": b[0x34:0x54].split(b"\0")[0].decode("latin-1"), "chunks": chunks, "end": end}


def levels(dfu: Dfu) -> list[dict]:
    """Every level package: found by its header shape, named from the level name it carries and confirmed by the
    archive's own hash of levels\\<level>.lvl_3."""
    out = []
    for e in dfu.entries:
        if e.size < PKG_TABLE or e.compressed:
            continue
        spans = dfu.spans(e, PKG_TABLE)
        head = b"".join(dfu.disc.read(p, o, n) for p, o, n in spans)
        start, count = struct.unpack_from("<2I", head)
        if not (0 < count < 4096 and PKG_TABLE + 16 * count <= start <= PKG_TABLE + 16 * count + 64):
            continue
        name = head[0x34:0x54].split(b"\0")[0].decode("latin-1")
        if not name or dfu.hash(LEVEL_FMT.format(name)) != e.hash:
            continue
        out.append({"level": name, "file": LEVEL_FMT.format(name), "size": e.size, "chunks": count})
    return sorted(out, key=lambda r: r["level"])


def level_models(dfu: Dfu, level: str) -> list[dict]:
    p = parse_package(dfu.read(LEVEL_FMT.format(level)))
    return [{"model": c["model"], "size": c["size"], "chunk": c["index"]} for c in p["chunks"] if c.get("model")]


def inventory(path, models_per_level: bool = True) -> dict:
    disc = open_disc(path)
    ident = identify(disc)
    try:
        dfu = Dfu(disc, "pon")
    except DfuError as e:
        raise FormatError(f"WAD1.DFU: {e}") from None
    acts = actors(dfu)
    lv = levels(dfu)
    cast: dict[str, list[str]] = {}
    if models_per_level:
        for r in lv:
            ms = level_models(dfu, r["level"])
            r["models"] = [m["model"] for m in ms]
            for m in ms:
                cast.setdefault(m["model"], []).append(r["level"])
    return {"identity": ident,
            "archive": {"parts": dfu.parts, "sizes": dfu.part_sizes, "entries": dfu.count, "seeds": dfu.seeds,
                        "data_base": dfu.base, "compressed": sum(e.compressed for e in dfu.entries)},
            "actors": len(acts), "actor_names": [a["name"] for a in acts], "levels": lv,
            "models": {k: sorted(v) for k, v in sorted(cast.items())},
            "status": "inventory only: characters are per-level .dcn_11 chunks (format not decoded), no reader / "
                      "writer yet"}


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
    print(json.dumps({k: inv[k] for k in ("identity", "archive", "actors")}, indent=1, default=str))
    print(f"{len(inv['levels'])} level packages, {len(inv['models'])} distinct models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
