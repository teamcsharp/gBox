"""TimeSplitters: Future Perfect (GameCube) P5CK .pak reader.

Proven on pak/chr.pak (disc G3FE69): header 'P5CK', then little-endian u32
directory offset and u32 directory length; the directory sits at the file tail
as 16-byte LE entries (crc32(path), offset, size, 0).  The sidecar .c2n lists
'0xCRC32  path' in the same order.  Member payloads are big-endian GameCube data.
.gcr (model) members start with BE u32 table offset (0x0c) and then 16-byte
texture refs (id24, id24, 0, x) that name 'textures/<id24 hex>.gct' members.
No geometry/skeleton parsing is claimed here.
"""
import struct, zlib
from pathlib import Path

MAGIC = b"P5CK"


def parse_c2n(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        crc, path = line.split(None, 1)
        rows.append((int(crc, 16), path.strip()))
    return rows


def parse_pak(data, c2n_rows=None):
    """Return list of dict(crc, offset, size, path|None).  Raises ValueError on bad layout."""
    if data[:4] != MAGIC:
        raise ValueError("not a P5CK pak")
    dir_off, dir_len = struct.unpack("<II", data[4:12])
    if dir_len % 16 or dir_off + dir_len > len(data):
        raise ValueError("directory out of range")
    out = []
    for i in range(dir_len // 16):
        crc, off, size, _z = struct.unpack_from("<4I", data, dir_off + 16 * i)
        if off + size > dir_off:
            raise ValueError("member %d overruns directory" % i)
        out.append({"crc": crc, "offset": off, "size": size, "path": None})
    if c2n_rows is not None:
        if len(c2n_rows) != len(out):
            raise ValueError("c2n row count %d != directory %d" % (len(c2n_rows), len(out)))
        for e, (crc, path) in zip(out, c2n_rows):
            if e["crc"] != crc or zlib.crc32(path.encode()) != crc:
                raise ValueError("crc mismatch for %s" % path)
            e["path"] = path
    return out


def member(data, entry):
    return data[entry["offset"]:entry["offset"] + entry["size"]]


def gcr_texture_refs(blob, known_ids=None):
    """Texture ids (24-bit ints) referenced by a .gcr member's leading table."""
    p = struct.unpack(">I", blob[:4])[0]
    ids = []
    while p + 16 <= len(blob):
        a, b = struct.unpack(">II", blob[p:p + 8])
        if a != b or a > 0xFFFFFF or (known_ids is not None and a not in known_ids):
            break
        ids.append(a)
        p += 16
    return ids


def texture_id(path):
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".gct") and len(name) == 10:
        return int(name[:6], 16)
    return None


def gct_header(blob):
    """First 8 BE words of a .gct (observed: 4x 0x100 on 256-wide texture, then 0x00010002)."""
    return struct.unpack(">8I", blob[:32])
