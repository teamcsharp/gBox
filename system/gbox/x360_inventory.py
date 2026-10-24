"""Bounded read-only inventory of an Xbox 360 XGD/GDF disc image (XDVDFS tree).

Walks the directory B-trees directly from the image bytes; never extracts or
modifies the source. Offsets are little-endian, relative to the volume base
(``base + sector * 2048``). Inventory only: this is not a model reader.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

MAGIC = b"MICROSOFT*XBOX*MEDIA"
SECTOR = 2048
# GDF volume descriptor bases: XSF/XGD1, XGD2, XGD3 (and plain XISO at 0).
BASES = (0, 0x0FD90000, 0x02080000, 0x18300000)
MAX_FILES = 100000
MAX_DEPTH = 32
MAGIC_PROBE = 16


def find_volume(stream, size: int) -> dict:
    found = []
    for base in BASES:
        at = base + 0x10000
        if at + SECTOR > size:
            continue
        stream.seek(at)
        block = stream.read(SECTOR)
        if block[:20] == MAGIC and block[-20:] == MAGIC:
            sector, length = struct.unpack_from("<II", block, 20)
            if length < 14 or base + sector * SECTOR + length > size:
                raise ValueError("root directory outside image")
            found.append({"base": base, "root_sector": sector, "root_bytes": length})
    if len(found) != 1:
        raise ValueError(f"expected exactly one XDVDFS volume, found {len(found)}")
    return found[0]


def _walk(stream, size, base, sector, length, prefix, out, depth, seen):
    if depth > MAX_DEPTH:
        raise ValueError("directory nesting too deep")
    if (sector, length) in seen:
        raise ValueError("directory cycle")
    seen.add((sector, length))
    start = base + sector * SECTOR
    if start + length > size:
        raise ValueError("directory outside image")
    stream.seek(start)
    data = stream.read(length)
    visited = set()
    stack = [0]
    while stack:
        off = stack.pop()
        if off in visited:
            raise ValueError("directory tree cycle")
        visited.add(off)
        if off + 14 > len(data):
            raise ValueError("directory entry out of range")
        left, right, sec, flen, attr, nlen = struct.unpack_from("<HHIIBB", data, off)
        if left == 0xFFFF and right == 0xFFFF and sec == 0xFFFFFFFF:
            continue  # empty padding
        if nlen == 0 or off + 14 + nlen > len(data):
            raise ValueError("bad directory name")
        name = data[off + 14:off + 14 + nlen].decode("latin-1")
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"unsafe name {name!r}")
        path = prefix + name
        if attr & 0x10:
            if flen:
                _walk(stream, size, base, sec, flen, path + "/", out, depth + 1, seen)
        else:
            if base + sec * SECTOR + flen > size:
                raise ValueError(f"file {path} outside image")
            out.append({"path": path, "sector": sec, "offset": sec * SECTOR, "size": flen})
        if len(out) > MAX_FILES:
            raise ValueError("too many files")
        for child in (left, right):
            if child:
                stack.append(child * 4)


def sha256_range(stream, start: int, length: int) -> str:
    digest = hashlib.sha256()
    stream.seek(start)
    left = length
    while left:
        chunk = stream.read(min(left, 4 * 1024 ** 2))
        if not chunk:
            raise ValueError("short read")
        digest.update(chunk)
        left -= len(chunk)
    return digest.hexdigest()


def inventory(path, probe_magic=True) -> dict:
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as stream:
        vol = find_volume(stream, size)
        files: list = []
        _walk(stream, size, vol["base"], vol["root_sector"], vol["root_bytes"], "", files, 0, set())
        magics: dict[str, int] = {}
        for f in files:
            f["magic"] = None
            if probe_magic and f["size"] >= 4:
                stream.seek(vol["base"] + f["offset"])
                head = stream.read(min(MAGIC_PROBE, f["size"]))
                f["magic"] = head[:4].hex()
                key = head[:4].decode("ascii") if all(32 <= c < 127 for c in head[:4]) else head[:4].hex()
                magics[key] = magics.get(key, 0) + 1
        exe = [f for f in files if f["path"].lower() == "default.xex"]
        if len(exe) == 1:
            exe[0]["sha256"] = sha256_range(stream, vol["base"] + exe[0]["offset"], exe[0]["size"])
    return {
        "image": str(path), "image_size": size, "volume": vol, "byte_order": "little (XDVDFS)",
        "offset_base": "base + sector*2048", "file_count": len(files),
        "total_bytes": sum(f["size"] for f in files), "default_xex": exe[0] if exe else None,
        "magic_census": dict(sorted(magics.items(), key=lambda kv: -kv[1])), "files": files,
    }


if __name__ == "__main__":
    import json, sys
    r = inventory(sys.argv[1])
    json.dump(r, open(sys.argv[2], "w"), indent=1) if len(sys.argv) > 2 else print(json.dumps({k: v for k, v in r.items() if k != "files"}, indent=1))
