"""Resident Evil: The Mercenaries 3D (Nintendo 3DS, MT Framework Mobile) inventory.

Inventory-stage reader for the owned .3ds dump:
  * little-endian MT Framework ARC v16 archives (12-byte header, 80-byte entries:
    name[64], type hash, compressed size, (flags<<29 | decompressed size), offset; zlib bodies);
  * the playable roster archives ``/archive/uPl( <Name> ).arc`` -> native ``plNNNN`` model ids;
  * MOD (v229) header summary: bone / mesh / material / vertex / index counts;
  * RomFS asset counts per character family (pl/em/om/it/wp) and file kind.

Nothing is written into the image.  ``python -m gbox.merc3d_inventory IMAGE --out m.json``.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from .ctr_romfs import CtrImage, blz_decompress

# MT Framework resource type hashes observed in this title's ARCs.
TYPES = {
    0x58A15856: "mod", 0x241F5DEB: "tex", 0x2749C8A8: "mrl", 0x76820D81: "lmt", 0x39C52040: "lcm",
    0x1A5444D9: "cad", 0x51120F02: "swp", 0x6E45FABB: "atp", 0x7A098625: "cwc", 0x67195A2E: "wav",
}
ROSTER_RE = re.compile(r"^/archive/uPl\( (?P<name>[A-Za-z0-9]+) \)\.arc$")


class ArcError(ValueError):
    pass


@dataclass
class ArcEntry:
    name: str
    type_hash: int
    comp_size: int
    raw: int  # flags << 29 | decompressed size
    offset: int

    @property
    def size(self) -> int:
        return self.raw & 0x1FFFFFFF

    @property
    def flags(self) -> int:
        return self.raw >> 29

    @property
    def kind(self) -> str:
        return TYPES.get(self.type_hash, f"{self.type_hash:08x}")


class Arc3ds:
    """MT Framework ARC, little endian, version 16 (3DS)."""

    HEADER = 12
    ENTRY = 80

    def __init__(self, data: bytes):
        if len(data) < self.HEADER or data[:4] != b"ARC\0":
            raise ArcError("not an MT ARC")
        self.data = data
        self.version, n = struct.unpack_from("<HH", data, 4)
        if self.version != 16:
            raise ArcError(f"unsupported ARC version {self.version}")
        if self.HEADER + n * self.ENTRY > len(data):
            raise ArcError("ARC table runs past end of file")
        self.entries: list[ArcEntry] = []
        for i in range(n):
            o = self.HEADER + i * self.ENTRY
            name = data[o:o + 64].split(b"\0")[0].decode("ascii")
            th, cs, raw, off = struct.unpack_from("<IIII", data, o + 64)
            if off + cs > len(data):
                raise ArcError(f"entry {name} runs past end of file")
            self.entries.append(ArcEntry(name, th, cs, raw, off))

    def read(self, e: ArcEntry) -> bytes:
        body = self.data[e.offset:e.offset + e.comp_size]
        out = zlib.decompress(body) if e.comp_size != e.size or body[:1] == b"\x78" else body
        if len(out) != e.size:
            raise ArcError(f"{e.name}: decompressed {len(out)} != {e.size}")
        return out

    def find(self, kind: str, stem: str | None = None) -> list[ArcEntry]:
        return [e for e in self.entries if e.kind == kind and (stem is None or e.name.endswith(stem))]


def mod_header(d: bytes) -> dict:
    if d[:4] != b"MOD\0":
        raise ArcError("not a MOD")
    ver, bones, meshes, mats, verts, idx = struct.unpack_from("<HHHHII", d, 4)
    return {"version": ver, "bones": bones, "meshes": meshes, "materials": mats, "vertices": verts,
            "indices": idx, "size": len(d)}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def roster(img: CtrImage, files=None) -> list[dict]:
    """Playable characters: one ``uPl( Name ).arc`` per costume, each carrying one ``plNNNN`` MOD."""
    files = files if files is not None else img.romfs_files()
    loose = {f.path: f for f in files}
    out = []
    for f in files:
        m = ROSTER_RE.match(f.path)
        if not m:
            continue
        arc = Arc3ds(img.read_file(f))
        mods = arc.find("mod")
        row = {"name": m["name"], "archive": f.path, "archive_sha256": _sha(arc.data), "entries": len(arc.entries),
               "kinds": dict(collections.Counter(e.kind for e in arc.entries)), "models": []}
        for e in mods:
            d = arc.read(e)
            pid = e.name.replace("\\", "/").rsplit("/", 1)[-1]
            lp = "/" + e.name.replace("\\", "/") + ".mod"
            lf = loose.get(lp)
            row["models"].append({"id": pid, "arc_path": e.name, "sha256": _sha(d), **mod_header(d),
                                  "textures": [x.name.rsplit("\\", 1)[-1] for x in arc.find("tex")
                                               if pid in x.name],
                                  "motions": len([x for x in arc.entries if x.kind == "lmt"]),
                                  "loose_copy": lp if lf else None,
                                  "loose_identical": (_sha(img.read_file(lf)) == _sha(d)) if lf else None})
        out.append(row)
    return out


def asset_counts(files) -> dict:
    fam = collections.defaultdict(lambda: collections.Counter())
    for f in files:
        m = re.match(r"^/(model|motion)/chara/(pl|em|om|it|wp)/([a-z]{2}[0-9a-f]{4})/", f.path)
        if m:
            fam[m[2]][f.path.rsplit(".", 1)[-1]] += 1
    ids = collections.defaultdict(set)
    for f in files:
        m = re.match(r"^/(?:model|motion)/chara/(pl|em|om|it|wp)/([a-z]{2}[0-9a-f]{4})/", f.path)
        if m:
            ids[m[1]].add(m[2])
    return {k: {"ids": sorted(ids[k]), **dict(v)} for k, v in sorted(fam.items())}


def manifest(path) -> dict:
    with CtrImage(path) as img:
        files = img.romfs_files()
        kinds = collections.Counter(f.path.rsplit(".", 1)[-1] for f in files if "." in f.path.rsplit("/", 1)[-1])
        code = img.exefs_file(".code") if ".code" in img.ncch.exefs_files else b""
        return {
            "image": str(path),
            "title_id": f"{img.ncch.title_id:016x}",
            "product_code": img.ncch.product_code,
            "region": img.region(),
            "smdh": img.smdh(),
            "exheader": img.exheader(),
            "decrypted": img.decrypted(),
            "ncch_nocrypto_flag": img.ncch.no_crypto_flag,
            "partitions": [{"index": i, "offset": o, "size": s} for i, o, s in img.partitions],
            "exefs": {k: {"offset": o, "size": s} for k, (o, s) in img.ncch.exefs_files.items()},
            "code_sha256": _sha(code) if code else None,
            "code_decompressed_sha256": (_sha(blz_decompress(code)) if code and img.exheader().get("code_compressed")
                                         else None),
            "romfs_files": len(files),
            "romfs_bytes": sum(f.size for f in files),
            "file_kinds": dict(kinds.most_common()),
            "families": asset_counts(files),
            "roster": roster(img, files),
        }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = manifest(a.image)
    s = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(s)
    else:
        sys.stdout.write(s + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
