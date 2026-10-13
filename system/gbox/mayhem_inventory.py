"""Owned-build inventory for WCW Mayhem (Europe, NWMP rev 0) on N64 (#1512, game 9cb579d94b6d2167).

    python -m gbox.mayhem_inventory ROM [--out manifest.json]

WCW Mayhem is a Kodiak Interactive / EA engine, unrelated to the AKI wrestling titles (gbox.aki_wcw).  The ROM is
boot code (0x1000-0x11C180) followed by one EA ``BIGF`` archive ("data.big", 34 members) that nests the other
archives (textures.big, models.big, motion.big, caw_n64.big, ...).  BIGF: ``"BIGF"``, u32 BE total size, u32 BE count,
u32 BE header size, then ``{u32 BE offset, u32 BE size, cstring name}``; offsets are relative to that archive.
Nearly every non-audio member is EA RefPack (``gbox.refpack``); the three code overlays (loaded/fe/game.ovr) too.

The wrestler roster is ``wrestler.nch`` (data.big/data.big, a ``KCHR`` file): after its binary per-wrestler records a name block gives
each of the 56 wrestlers three cstrings (full name, ring name, costume label) followed by 56 attribute bytes.  Models are ``*.n3o`` in
models.big: two-letter wrestler/CAW codes ``XX_n64.n3o`` plus arena/prop meshes; animations are ``motN.ncm`` in
motion.big; textures are ``*.ntl`` (textures.big, caw_n64.big) and ``*.tim``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

from . import n64_rom
from . import refpack
from .wcw_worldtour_inventory import container, header

GAME_ID = "9cb579d94b6d2167"
MASTER_OFFSET = 0x11C180
NCH_FIXED = 56          # wrestler name records in the Europe build
MIN_CHAIN = 8
WRESTLER_MODEL = re.compile(r"^([A-Za-z]{2})_n64\.n3o$")


def parse_bigf(buf: bytes, base: int = 0) -> list[tuple[str, int, int]]:
    """[(name, absolute offset, size)] for the BIGF archive at buf[base]."""
    if buf[base:base + 4] != b"BIGF":
        raise ValueError(f"no BIGF at {base:#x}")
    total, count, hsize = struct.unpack_from(">III", buf, base + 4)
    p, out = base + 16, []
    for _ in range(count):
        off, size = struct.unpack_from(">II", buf, p)
        e = buf.index(b"\0", p + 8)
        name = buf[p + 8:e].decode("latin-1")
        p = e + 1
        if base + off + size > len(buf):
            raise ValueError(f"BIGF member {name!r} overruns the buffer")
        # The u32 "total" can be smaller than the last member's end (master data.big: game.ovr ends 0x7C past it),
        # so it is not used as a bound.
        out.append((name, base + off, size))
    if p - base > hsize:
        raise ValueError("BIGF directory overruns its header size")
    return out


def walk(rom: bytes, base: int = MASTER_OFFSET) -> list[dict]:
    """Every leaf member of the master archive and its nested BIGFs, with RefPack status."""
    rows = []

    def visit(arc: str, off: int):
        for name, o, size in parse_bigf(rom, off):
            blob = rom[o:o + size]
            if blob[:4] == b"BIGF":
                visit(name, o)
                continue
            row = {"archive": arc, "name": name, "rom_offset": o, "size": size,
                   "ext": name.rsplit(".", 1)[-1].lower() if "." in name else ""}
            if refpack.is_refpack(blob):
                data, used = refpack.decompress_ex(blob)
                row.update(refpack=True, unpacked=len(data), slack=size - used,
                           sha256=hashlib.sha256(data).hexdigest())
            else:
                row.update(refpack=False, unpacked=size, sha256=hashlib.sha256(blob).hexdigest())
            rows.append(row)

    visit("data.big", base)
    return rows


def member(rom: bytes, rows: list[dict], name: str, archive: str | None = None) -> bytes:
    for r in rows:
        if r["name"] == name and (archive is None or r["archive"] == archive):
            b = rom[r["rom_offset"]:r["rom_offset"] + r["size"]]
            return refpack.decompress(b) if r["refpack"] else b
    raise KeyError(name)


def roster(nch: bytes) -> list[dict]:
    """Wrestler name records of a KCHR wrestler.nch: (full name, ring name, costume label, 56 attribute bytes)."""
    if nch[:4] != b"KCHR":
        raise ValueError("not a KCHR file")
    hsize, stride = struct.unpack_from(">II", nch, 4)

    def triplet(p):
        q, f = p, []
        for _ in range(3):
            e = nch.find(b"\0", q)
            s = nch[q:e] if e > 0 else b""
            if len(s) < 2 or any(c < 0x20 or c > 0x7E for c in s):
                return None
            f.append(s.decode("ascii")); q = e + 1
        return f, q

    def chain(p, need):
        for _ in range(need):
            t = triplet(p)
            if t is None:
                return False
            p = t[1] + 56
        return True

    # The name block follows the binary per-wrestler records; it is the first offset where a run of `MIN_CHAIN`
    # (name, ring name, costume) records with 56-byte attribute tails parses back to back.
    p = hsize
    while p < len(nch) and not chain(p, min(MIN_CHAIN, NCH_FIXED)):
        p += 1
    out = []
    while p < len(nch) and (t := triplet(p)) is not None:
        f, q = t
        out.append({"index": len(out), "name": f[0], "ring_name": f[1], "costume": f[2],
                    "nch_offset": p, "attrs": nch[q:q + 56].hex()})
        p = q + 56
    return out


def inventory(rom: bytes, source: Path | None = None) -> dict:
    rows = walk(rom)
    rp = [r for r in rows if r["refpack"]]
    nch = member(rom, rows, "wrestler.nch")
    names = roster(nch)
    models = [r for r in rows if r["ext"] == "n3o"]
    wmodels = sorted({WRESTLER_MODEL.match(r["name"]).group(1) for r in models if WRESTLER_MODEL.match(r["name"])},
                     key=str.lower)
    by_ext = Counter(f'{r["archive"]}:{r["ext"]}' for r in rows)
    return {
        "game_id": GAME_ID,
        "title": "WCW Mayhem (Europe)",
        "platform": "n64",
        "engine": "Kodiak Interactive / EA (BIGF + RefPack)",
        "source": container(source) if source else None,
        "header": header(rom),
        "launch": {"cic": header(rom)["cic"], "save": "Controller Pak (strings in loaded.ovr/fe.ovr)",
                   "rumble": "Rumble Pak strings present", "expansion_pak": "unverified",
                   "byte_order": "owned zip member named .z64 holds v64 data; read through n64_rom.read"},
        "layout": {"boot_code": [0x1000, MASTER_OFFSET], "master_bigf": MASTER_OFFSET,
                   "master_members": len(parse_bigf(rom, MASTER_OFFSET)),
                   "nested_archives": [n for n, o, s in parse_bigf(rom, MASTER_OFFSET) if rom[o:o + 4] == b"BIGF"],
                   "overlays": [r["name"] for r in rows if r["ext"] == "ovr"]},
        "refpack": {"members": len(rp), "exact": sum(1 for r in rp if r["slack"] == 0),
                    "raw_members": len(rows) - len(rp)},
        "counts_by_archive_ext": dict(sorted(by_ext.items())),
        "roster": {"file": "wrestler.nch", "kchr_stride": struct.unpack_from(">I", nch, 8)[0],
                   "count": len(names), "wrestlers": [{k: v for k, v in n.items() if k != "attrs"} for n in names]},
        "models": {"count": len(models), "wrestler_codes": wmodels,
                   "other": [r["name"] for r in models if not WRESTLER_MODEL.match(r["name"])],
                   "files": [{k: r[k] for k in ("name", "rom_offset", "size", "unpacked", "sha256")} for r in models]},
        "animations": {"count": sum(1 for r in rows if r["ext"] == "ncm"), "archive": "motion.big"},
        "textures": {"ntl": sum(1 for r in rows if r["ext"] == "ntl"), "tim": sum(1 for r in rows if r["ext"] == "tim")},
        "open": ["map wrestler.nch index -> XX_n64.n3o code (code table in loaded.ovr)",
                 "n3o mesh/skeleton format, ncm motion format, ntl texture format"],
        "members": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rom")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    src = Path(a.rom)
    m = inventory(n64_rom.read(src), src)
    txt = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    print(json.dumps({k: m[k] for k in ("header", "refpack", "layout")}, indent=1))
    print(f'roster {m["roster"]["count"]}, models {m["models"]["count"]} ({len(m["models"]["wrestler_codes"])} XX codes), '
          f'motions {m["animations"]["count"]}, textures {m["textures"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
