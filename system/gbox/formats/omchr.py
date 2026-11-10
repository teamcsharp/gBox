"""Metroid: Other M (Wii) ``chr_misc`` container + embedded BRES reader.

Layout verified on the owned R3OJ01 build (big-endian, offsets container-relative):

* 0x00  ``chr_misc`` NUL/FF padded to 8 bytes, u32 0xFF000100 flags at 0x08
* 0x0C  u32 header size (0x30), 0x10 u32 total size, 0x14/0x18 u32 counts
* 0x30  u32[12] section table: [0]=0x60 table0, [1]=script/param, [2]=block,
        [3]=embedded BRES (``bres`` magic) or 0, [5]=``MMMM`` sound/aux or 0,
        [6]=trailer.  Zero means absent.

The embedded BRES is the Nintendo NW4R resource archive (folders such as
``3DModels(NW4R)`` / ``AnmScn(NW4R)`` / ``Textures(NW4R)``) walked here only
as far as names and data offsets; geometry decoding is a later stage.
"""
from __future__ import annotations

import struct

MAGIC = b"chr_"


class OmChrError(ValueError):
    pass


def parse_chr_misc(data: bytes) -> dict:
    if data[:4] != MAGIC or len(data) < 0x60:
        raise OmChrError("not a chr_ container")
    kind = data[:8].split(b"\xff")[0].rstrip(b"\0").decode("latin1")
    hdr_size, total = struct.unpack(">II", data[0x0C:0x14])
    if not (0 <= len(data) - total < 0x20):  # file is padded to 0x20
        raise OmChrError(f"size field {total} != {len(data)}")
    tbl = struct.unpack(">12I", data[0x30:0x60])
    names = {0: "table0", 1: "params", 2: "block", 3: "bres", 5: "mmmm", 6: "trailer"}
    sections = {}
    for i, n in names.items():
        off = tbl[i]
        if off and off >= len(data):
            raise OmChrError(f"section {n} offset {off:#x} out of range")
        if off:
            sections[n] = off
    out = {"kind": kind, "header_size": hdr_size, "size": total, "sections": sections}
    bo = sections.get("bres")
    if bo is not None:
        if data[bo:bo + 4] != b"bres":
            raise OmChrError("bres section lacks magic")
        blen = struct.unpack(">I", data[bo + 8:bo + 12])[0]
        out["bres_size"] = blen
        out["bres"] = bo
    return out


def _group(b: bytes, base: int) -> list[tuple[str, int]]:
    _size, n = struct.unpack(">II", b[base:base + 8])
    if n > 4096:
        raise OmChrError("implausible BRES group size")
    res = []
    for i in range(1, n + 1):
        o = base + 8 + 16 * i
        _id, _fl, _l, _r, no, do = struct.unpack(">HHHHII", b[o:o + 16])
        nl = struct.unpack(">I", b[base + no - 4:base + no])[0]
        res.append((b[base + no:base + no + nl].decode("latin1"), base + do))
    return res


def parse_bres(b: bytes) -> dict:
    """Return {folder: [(name, magic, offset), ...]} for a BRES blob."""
    if b[:4] != b"bres" or b[4:6] != b"\xfe\xff":
        raise OmChrError("not a big-endian BRES")
    root = struct.unpack(">H", b[0x0C:0x0E])[0]
    if b[root:root + 4] != b"root":
        raise OmChrError("missing BRES root")
    out = {}
    for fname, fo in _group(b, root + 8):
        out[fname] = [(n, b[o:o + 4].decode("latin1"), o) for n, o in _group(b, fo)]
    return out


def describe(data: bytes) -> dict:
    info = parse_chr_misc(data)
    if "bres" in info:
        bo = info["bres"]
        folders = parse_bres(data[bo:bo + info["bres_size"]])
        info["bres_folders"] = {k: [(n, m) for n, m, _ in v] for k, v in folders.items()}
    return info
