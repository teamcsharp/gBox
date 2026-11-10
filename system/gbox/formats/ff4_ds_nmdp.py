"""FF4 DS (YF4E) NMDP model container probe.

An NMDP file (after LZ10) is a 0x30 byte wrapper (count@0x10, type@0x14, body_size@0x18) around a stock Nitro
``BMD0`` (NSBMD) body at 0x30.  Type 2 bodies carry an MDL0 block (models); type 4 are textures (TEX0 in a
BTX0 body, not parsed here).  Offsets inside BMD0 are relative to the BMD0 magic (file offset 0x30).
"""
from __future__ import annotations

import struct

WRAP = 0x30


def parse_dict(b: bytes, off: int) -> dict:
    """Nitro name dictionary -> {names, data, size}; validates the size field against the layout."""
    count, size = b[off + 1], struct.unpack_from("<H", b, off + 2)[0]
    tree_end = off + 8 + (count + 1) * 4
    unit = struct.unpack_from("<H", b, tree_end)[0]
    data = tree_end + 4
    names_off = data + count * unit
    names = [b[names_off + 16 * i:names_off + 16 * i + 16].split(b"\0")[0].decode("ascii", "replace")
             for i in range(count)]
    vals = [b[data + i * unit:data + (i + 1) * unit] for i in range(count)]
    if names_off + 16 * count - off != size:
        raise ValueError(f"dict size mismatch at {off:#x}: {names_off + 16 * count - off} != {size}")
    return {"count": count, "names": names, "data": vals, "unit": unit}


def parse_nmdp(d: bytes) -> dict:
    if d[:4] != b"NMDP":
        raise ValueError("not NMDP")
    count, typ, body = struct.unpack_from("<III", d, 0x10)
    if body + WRAP != len(d):
        raise ValueError("body_size mismatch")
    out = {"count": count, "type": typ, "body_size": body}
    if typ != 2:
        return out
    bmd = d[WRAP:]
    if bmd[:4] != b"BMD0":
        raise ValueError("type 2 body is not BMD0")
    bom, ver, fsize, hsize, nblk = struct.unpack_from("<HHIHH", bmd, 4)
    if fsize != len(bmd):
        raise ValueError("BMD0 size mismatch")
    blocks = list(struct.unpack_from(f"<{nblk}I", bmd, 0x10))
    out.update(version=ver, blocks=blocks)
    mdl = blocks[0]
    if bmd[mdl:mdl + 4] != b"MDL0":
        raise ValueError("first block is not MDL0")
    md = parse_dict(bmd, mdl + 8)
    models = []
    for name, ptr in zip(md["names"], md["data"]):
        mo = mdl + struct.unpack("<I", ptr[:4])[0]
        size, sbc, mat, shp, evp = struct.unpack_from("<5I", bmd, mo)
        nodes = parse_dict(bmd, mo + 0x40)
        materials = parse_dict(bmd, mo + mat + 4)  # section head: u16 texdict, u16 paldict
        shapes = parse_dict(bmd, mo + shp)
        models.append({"name": name, "offset": mo, "size": size, "sbc": mo + sbc, "evp": mo + evp,
                       "nodes": nodes["names"], "materials": materials["names"], "shapes": shapes["names"]})
    out["models"] = models
    return out
