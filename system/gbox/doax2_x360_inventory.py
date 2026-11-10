"""Owned-build inventory for Dead or Alive Xtreme 2 (Xbox 360, XDVDFS disc image).

Reads a raw XDVDFS image directly (no extractor), walks the directory tree, hashes the
``default.xex`` source executable and parses every ``.afs`` (little-endian CRI AFS, same layout
as the Xbox DOA3 archives, see :mod:`gbox.doa3_inventory`) in place.  ``chr.afs`` members are
grouped per character code (``vtn``, ``vks`` ...) by extension.  Reading an archive table is
not a model reader.  ``python -m gbox.doax2_x360_inventory ISO --out manifest.json``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

from gbox.doa3_inventory import afs_names, afs_table, sniff

SCHEMA = "gbox.doax2_x360_inventory/1"
MAGIC = b"MICROSOFT*XBOX*MEDIA"
BASES = (0x0, 0xFD90000, 0x2080000, 0x18300000)   # raw, XGD2, XGD1/ext, XGD3
SECTOR = 2048
MAX_FILES = 4096


class Unsupported(ValueError):
    pass


def sha256_range(f, offset: int, size: int, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    f.seek(offset)
    left = size
    while left:
        b = f.read(min(chunk, left))
        if not b:
            raise ValueError("short read while hashing")
        h.update(b)
        left -= len(b)
    return h.hexdigest()


def locate(f, size: int) -> dict:
    found = []
    for base in BASES:
        at = base + 0x10000
        if at + SECTOR > size:
            continue
        f.seek(at)
        blk = f.read(SECTOR)
        if blk[:20] == MAGIC and blk[-20:] == MAGIC:
            sector, length = struct.unpack_from("<II", blk, 20)
            if base + sector * SECTOR + length > size or length < 14:
                raise ValueError("XDVDFS root directory outside image")
            found.append({"base": base, "root_sector": sector, "root_bytes": length})
    if len(found) != 1:
        raise Unsupported("need exactly one XDVDFS volume descriptor")
    return found[0]


def walk(f, vol: dict) -> list[dict]:
    """Return [{path, offset, size}] for all files (absolute byte offsets)."""
    base = vol["base"]
    out: list[dict] = []
    seen: set[int] = set()

    def directory(sector: int, length: int, prefix: str, depth: int):
        if depth > 16 or sector in seen:
            raise ValueError("XDVDFS directory loop or excessive depth")
        seen.add(sector)
        f.seek(base + sector * SECTOR)
        data = f.read(length)
        stack, done = [0], set()
        while stack:
            off = stack.pop()
            if off in done or off + 14 > len(data):
                continue
            done.add(off)
            left, right, sec, sz, attr, nl = struct.unpack_from("<HHIIBB", data, off)
            if left == 0xFFFF and right == 0xFFFF and sec == 0xFFFFFFFF:
                continue
            name = data[off + 14:off + 14 + nl].decode("latin-1")
            if left:
                stack.append(left * 4)
            if right:
                stack.append(right * 4)
            path = prefix + name
            if attr & 0x10:
                if sz:
                    directory(sec, sz, path + "/", depth + 1)
            else:
                out.append({"path": path, "offset": base + sec * SECTOR, "size": sz})
            if len(out) > MAX_FILES:
                raise ValueError("too many files")
    directory(vol["root_sector"], vol["root_bytes"], "", 0)
    return sorted(out, key=lambda e: e["path"].lower())


def parse_xex(head: bytes) -> dict:
    if head[:4] != b"XEX2":
        raise ValueError("not an XEX2 executable")
    flags, pe_off, _, sec_off, nopt = struct.unpack_from(">IIIII", head, 4)
    opts = {}
    for i in range(nopt):
        key, val = struct.unpack_from(">II", head, 0x18 + 8 * i)
        opts[f"{key:#010x}"] = val
    return {"module_flags": f"{flags:#x}", "pe_offset": pe_off, "security_offset": sec_off,
            "optional_headers": opts}


def label(magic: str) -> str:
    return {"hex:43415400": "CAT", "hex:4d505600": "MPV"}.get(magic, magic)


def read_afs_at(f, offset: int, size: int) -> dict:
    f.seek(offset)
    head = f.read(16)
    if head[:4] != b"AFS\x00":
        raise ValueError(f"not AFS: {head[:4]!r}")
    n = struct.unpack_from("<I", head, 4)[0]
    f.seek(offset)
    t = afs_table(f.read(16 + 8 * n), size)
    nd = t["name_dir"]
    if nd is None and t["count"] and t["offsets"][0] >= 8:
        f.seek(offset + t["offsets"][0] - 8)
        o, z = struct.unpack("<II", f.read(8))
        if z == 48 * t["count"] and o + z <= size:
            nd = (o, z)
    names = None
    if nd and nd[0] + nd[1] <= size:
        f.seek(offset + nd[0])
        names = afs_names(f.read(nd[1]), t["count"])
    entries = []
    for i, (o, z) in enumerate(zip(t["offsets"], t["sizes"])):
        f.seek(offset + o)
        e = {"index": i, "offset": o, "size": z, "magic": label(sniff(f.read(min(z, 16))))}
        if names:
            e["name"] = names[i]["name"]
        entries.append(e)
    return {"count": t["count"], "name_dir": list(nd) if nd else None,
            "magics": dict(Counter(e["magic"] for e in entries).most_common()), "entries": entries}


def character_sets(entries: list[dict]) -> dict:
    """Group members per leading 3-letter code (``vtn1.tpr``, ``vay_ch_g_m``)."""
    groups: dict[str, dict] = defaultdict(lambda: {"files": []})
    for e in entries:
        name = e.get("name", "")
        code = name[:3].lower()
        if len(name) > 3 and code.isalpha():
            groups[code]["files"].append({"name": name, "magic": e["magic"], "size": e["size"]})
    return {k: {"count": len(v["files"]), "files": v["files"]} for k, v in sorted(groups.items())}


def inventory(iso: str | Path, hash_iso: bool = False) -> dict:
    p = Path(iso)
    size = p.stat().st_size
    with open(p, "rb") as f:
        vol = locate(f, size)
        files = walk(f, vol)
        by = {e["path"].lower(): e for e in files}
        xex = by.get("default.xex")
        if not xex:
            raise Unsupported("default.xex missing from XDVDFS root")
        f.seek(xex["offset"])
        xex_info = parse_xex(f.read(0x200))
        xex_info.update(path=xex["path"], size=xex["size"],
                        sha256=sha256_range(f, xex["offset"], xex["size"]))
        afs = {}
        for e in files:
            if e["path"].lower().endswith(".afs"):
                afs[e["path"]] = read_afs_at(f, e["offset"], e["size"])
        out = {"schema": SCHEMA, "platform": "xbox360", "image": p.name, "image_size": size,
               "volume": vol, "file_count": len(files), "executable": xex_info,
               "files": files, "afs": {k: {kk: vv for kk, vv in v.items() if kk != "entries"}
                                       for k, v in afs.items()}}
        chr_afs = next((v for k, v in afs.items() if k.lower().endswith("chr.afs")), None)
        if chr_afs:
            out["chr_sets"] = character_sets(chr_afs["entries"])
        if hash_iso:
            out["image_sha256"] = sha256_range(f, 0, size)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--out")
    ap.add_argument("--hash-iso", action="store_true")
    a = ap.parse_args(argv)
    text = json.dumps(inventory(a.iso, a.hash_iso), indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text)
        print(hashlib.sha256(text.encode()).hexdigest(), a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
