"""NSBMD/BMD0 (Nitro 3D model) container reader: header, block table and 3D-dict model names.

Layout (little endian): 'BMD0', u16 BOM 0xFEFF (bytes ff fe), u16 version, u32 file size,
u16 header size (0x10), u16 block count, u32 block offsets[n]. Each block starts with a 4-char tag
('MDL0' models, 'TEX0' embedded textures) and a u32 size. MDL0/TEX0 body starts with a Nitro 3D dict:
u8 dummy, u8 count, u16 dict size, then (u16 unitsize,u16 datasize,u32 ptr[count]) tree, name table.
"""
from __future__ import annotations

import struct


def _dict_names(blob: bytes, pos: int) -> tuple[list[str], list[int]]:
    count = blob[pos + 1]
    dsize = struct.unpack_from("<H", blob, pos + 2)[0]
    if count > 255 or pos + dsize > len(blob):
        raise ValueError("bad 3D dict")
    # root node (4 bytes) + count tree nodes (4 bytes each) precede the unit header
    # header: u8 dummy,u8 count,u16 size,u16 hdrsize,u16 totalsize,u32 const; tree: (count+1)*4; then units
    tree = pos + 8
    unit_hdr = tree + 4 * (count + 1)
    unit_size, data_size = struct.unpack_from("<HH", blob, unit_hdr)
    datas_at = unit_hdr + 4
    names_at = pos + dsize - 16 * count  # name table is the dict tail
    data_off = [struct.unpack_from("<I", blob, datas_at + data_size * i)[0] for i in range(count)]
    names = [blob[names_at + 16 * i:names_at + 16 * i + 16].split(b"\0")[0].decode("latin-1") for i in range(count)]
    return names, data_off


def parse(blob: bytes) -> dict:
    if blob[:4] != b"BMD0":
        raise ValueError("not BMD0")
    bom, ver, fsize, hsize, nblk = struct.unpack_from("<HHIHH", blob, 4)
    if bom != 0xFEFF or hsize != 0x10 or not 1 <= nblk <= 8 or fsize != len(blob):
        raise ValueError(f"bad BMD0 header bom={bom:#x} size={fsize} hdr={hsize} blocks={nblk}")
    offs = struct.unpack_from(f"<{nblk}I", blob, hsize)
    out = {"version": ver, "size": fsize, "blocks": {}}
    for o in offs:
        tag = blob[o:o + 4].decode("latin-1")
        bsize = struct.unpack_from("<I", blob, o + 4)[0]
        if o + bsize > len(blob):
            raise ValueError(f"block {tag} past end")
        out["blocks"][tag] = {"offset": o, "size": bsize}
    if "MDL0" not in out["blocks"]:
        raise ValueError("BMD0 without MDL0")
    mo = out["blocks"]["MDL0"]["offset"]
    out["models"], out["model_offsets"] = _dict_names(blob, mo + 8)
    return out
