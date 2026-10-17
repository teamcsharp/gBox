"""Inventory for 007: Agent Under Fire (USA) PS2, catalog game a911b8d231ef883a (#1599).

The catalog labels this entry ``windows_native`` / "Microsoft XBOX", but its only source path is the HyperSpin
PS2 collection file ``collections/Sony Playstation 2/roms/USA/007 - Agent Under Fire (USA).chd``: a CD-CHD v5
(one MODE1 track, 796,048 x 2048-byte frames) holding the PS2 DVD image.  ``chdman extractcd`` gives a plain
ISO9660 image (volume BONDAUF, system PLAYSTATION).  No Xbox or Windows files exist in it.

Disc layout (owned build):

  SYSTEM.CNF    BOOT2 = cdrom0:\\SLUS_202.65;1  (86 KB loader)
  ACTION.ELF    the FPS game, MIPS R5900 little-endian ELF, stripped (no .symtab), .text at 0x120000
  DRIVING.ELF   driving missions, DRIVING.DAT/*.VIV;  MOVIE.ELF; MODULES/*.IRX + IOPRP214.IMG
  MAPS/ACTDAT.VIV  EA "BIGF" bigfile: 16-byte header ("BIGF", u32, u32be count, u32be toc size), then
                   count x (u32be offset, u32be size, name\\0) records.  Holds fonts, globals, 66 dialog .asf and
                   the 38 level packages ``maps\\*.chk``.
  MAPS/MUSIC.VIV   music.

A ``.chk`` is the GameCube ``.ngc`` package (gbox.auf_ngc) in little-endian form: 32-byte-aligned chunks with a
0x20-byte header {char id[8], u32 size, f32 version, u32 compressed, u32 0xcdcdcdcd, u32 disk size, u32 mem size}.
Compressed chunks use the same BOA LZ stream (``auf_ngc.boa_expand``).  Chunks seen: snd_alb, sndbank, hashes,
shaders, restxtrs, dyntxtrs, bspfile, shockprf, restable.  ``restable`` is the level file system: u32 count, then
{name_off, data_off, size, hash} LE records from +0x10, sorted by HashString (h*65599+c, lower-cased), exactly as on
GameCube.  Actor models are ``models/actors/**.mdl`` (PS2 format; the GC ``.gcm`` reader does not apply) and
animations ``.a3d``; the actor names (bond_combat_l, bond_head_l, thug_uwb_l, ...) match the GameCube build.

Usage:
    python -m gbox.auf_ps2_inventory DISC.iso [--source-sha256 SHA] [--out inventory.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from dataclasses import dataclass

from .auf_ngc import boa_expand
from .formats import iso9660

GAME_ID = "a911b8d231ef883a"
SERIAL = "SLUS_202.65"
CHUNK_HEADER = 0x20


def hash_string(name: str) -> int:
    """HashString as used by FS_FindResource (h*65599+c over the lower-cased name)."""
    h = 0
    for ch in name.lower():
        h = (h * 65599 + ord(ch)) & 0xFFFFFFFF
    return h


def parse_bigf(head: bytes) -> list[tuple[str, int, int]]:
    """Records of an ACTDAT-style BIGF header: (name, offset, size)."""
    if head[:4] != b"BIGF":
        raise ValueError("missing BIGF magic")
    count, toc = struct.unpack_from(">II", head, 8)
    if toc > len(head):
        raise ValueError("BIGF TOC (%d bytes) is longer than the header read" % toc)
    out, pos = [], 16
    for i in range(count):
        off, size = struct.unpack_from(">II", head, pos)
        nz = head.index(b"\0", pos + 8)
        name = head[pos + 8:nz].decode("latin-1")
        if not name or any(ord(c) < 32 or ord(c) > 126 for c in name):
            raise ValueError("BIGF record %d has a bad name at byte %d" % (i, pos))
        out.append((name, off, size))
        pos = nz + 1
    if pos > toc:
        raise ValueError("BIGF records overrun the declared TOC size")
    return out


@dataclass
class Chunk:
    id: str
    offset: int
    size: int
    version: float
    compressed: int
    disk_size: int
    mem_size: int

    @property
    def data_offset(self) -> int:
        return self.offset + CHUNK_HEADER

    @property
    def end(self) -> int:
        return (self.data_offset + self.disk_size + 31) & ~31


def iter_chunks(data: bytes):
    pos = 0
    while pos + CHUNK_HEADER <= len(data):
        h = data[pos:pos + CHUNK_HEADER]
        size, ver, comp, _pad, disk, mem = struct.unpack("<IfIIII", h[8:])
        c = Chunk(h[:8].split(b"\0", 1)[0].decode("latin-1"), pos, size, ver, comp, disk, mem)
        if c.data_offset + disk > len(data):
            raise ValueError("chunk %r at %#x overruns the package" % (c.id, pos))
        yield c
        pos = c.end
    if pos != len(data):
        raise ValueError("package ends at %#x but chunks stop at %#x" % (len(data), pos))


def read_chunk(data: bytes, c: Chunk) -> bytes:
    raw = data[c.data_offset:c.data_offset + c.disk_size]
    if not c.compressed:
        return raw[:c.size]
    out, _ = boa_expand(raw, c.mem_size)
    return out[:c.size]


def parse_restable(table: bytes) -> list[tuple[str, int, int, int]]:
    count = struct.unpack_from("<I", table, 0)[0]
    if 0x10 + count * 16 > len(table):
        raise ValueError("restable: %d records overrun the table" % count)
    out = []
    for i in range(count):
        no, do, sz, hv = struct.unpack_from("<4I", table, 0x10 + i * 16)
        if do + sz > len(table):
            raise ValueError("resource %d overruns the table" % i)
        out.append((table[no:table.index(b"\0", no)].decode("latin-1"), do, sz, hv))
    return out


class ChkPackage:
    def __init__(self, data: bytes):
        self.data = data
        self.chunks = list(iter_chunks(data))
        self._cache: dict[str, bytes] = {}

    def payload(self, cid: str) -> bytes:
        if cid not in self._cache:
            c = next((c for c in self.chunks if c.id == cid), None)
            if c is None:
                raise KeyError(cid)
            self._cache[cid] = read_chunk(self.data, c)
        return self._cache[cid]

    def resources(self):
        return parse_restable(self.payload("restable"))

    def read(self, name: str) -> bytes:
        tab = self.payload("restable")
        for n, do, sz, _ in parse_restable(tab):
            if n.lower() == name.lower():
                return tab[do:do + sz]
        raise KeyError(name)


def restable_check(recs) -> list[str]:
    errs = [f"{n}: hash {hv:#x} != HashString" for n, _, _, hv in recs if hash_string(n) != hv]
    hs = [r[3] for r in recs]
    if hs != sorted(hs):
        errs.append("records are not sorted by hash")
    return errs


def package_summary(data: bytes) -> dict:
    pkg = ChkPackage(data)
    recs = pkg.resources()
    tab = pkg.payload("restable")
    actors = sorted(n for n, *_ in recs if n.startswith("models/actors/") and n.endswith(".mdl"))
    heads = Counter(tab[do:do + 4].hex() for n, do, _, _ in recs if n.endswith(".mdl"))
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "chunks": [{"id": c.id, "size": c.size, "version": c.version, "compressed": c.compressed,
                    "disk_size": c.disk_size, "mem_size": c.mem_size} for c in pkg.chunks],
        "resources": len(recs),
        "extensions": dict(Counter(n.rsplit(".", 1)[-1] for n, *_ in recs)),
        "restable_errors": restable_check(recs),
        "actor_models": actors,
        "mdl_first_words": dict(heads),
        "anims": sum(n.endswith(".a3d") for n, *_ in recs),
    }


def inventory(path: str, source_sha256: str | None = None, maps: list[str] | None = None) -> dict:
    with open(path, "rb") as f:
        rd = iso9660.file_reader(f)
        pvd = rd(16, 2048)
        info = iso9660.pvd_info(pvd)
        lba, size = iso9660.pvd_root(pvd)
        fs = {k.upper(): v for k, v in iso9660.files(rd, lba, size).items()}
        cnf = rd(*fs["SYSTEM.CNF"]).decode("latin-1")
        if SERIAL not in cnf:
            raise ValueError("SYSTEM.CNF does not boot %s: %r" % (SERIAL, cnf))
        exe = rd(*fs["ACTION.ELF"])
        if exe[:4] != b"\x7fELF" or struct.unpack_from("<H", exe, 18)[0] != 8:
            raise ValueError("ACTION.ELF is not a MIPS ELF")
        vlba, vsize = fs["MAPS/ACTDAT.VIV"]
        f.seek(vlba * 2048)
        head = f.read(16)
        toc = struct.unpack_from(">I", head, 12)[0]
        f.seek(vlba * 2048)
        recs = parse_bigf(f.read(toc))
        if max(o + s for _, o, s in recs) > vsize:
            raise ValueError("ACTDAT.VIV records overrun the file")
        out = {
            "game_id": GAME_ID,
            "catalog_platform_label": "windows_native / Microsoft XBOX (incorrect)",
            "actual_platform": "ps2",
            "source_sha256": source_sha256,
            "volume": info,
            "system_cnf": cnf.strip(),
            "files": {k: {"lba": v[0], "size": v[1]} for k, v in sorted(fs.items())},
            "executables": {n: hashlib.sha256(rd(*fs[n])).hexdigest()
                            for n in ("SLUS_202.65", "ACTION.ELF", "DRIVING.ELF", "MOVIE.ELF")},
            "actdat": {"records": len(recs), "extensions": dict(Counter(n.rsplit(".", 1)[-1] for n, *_ in recs))},
            "maps": {},
        }
        roster: Counter = Counter()
        for name, off, sz in recs:
            if not name.lower().endswith(".chk"):
                continue
            short = name.split("\\")[-1]
            if maps and short not in maps:
                continue
            f.seek(vlba * 2048 + off)
            summ = package_summary(f.read(sz))
            out["maps"][short] = summ
            roster.update(summ["actor_models"])
        out["actor_roster"] = {k: roster[k] for k in sorted(roster)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("disc")
    ap.add_argument("--source-sha256")
    ap.add_argument("--map", action="append", help="limit to these maps (e.g. dm1.chk)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    inv = inventory(a.disc, a.source_sha256, a.map)
    text = json.dumps(inv, indent=1, sort_keys=True)
    if a.out:
        open(a.out, "w").write(text)
    errs = {m: v["restable_errors"] for m, v in inv["maps"].items() if v["restable_errors"]}
    print(json.dumps({"maps": len(inv["maps"]), "actor_models": len(inv["actor_roster"]), "errors": errs}))
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
