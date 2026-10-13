"""007: Agent Under Fire (GameCube, GW7E69) level package (.ngc) and model (.gcm) probe.

Every layout below was read from the owned disc's ``/base.elf/Bond.elf``
(sha256 1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f), which
keeps its symbol table, so the functions are named and the offsets reproducible:

``maps/*.ngc`` -- ``RSRC_Load`` 0x80016AFC
    A sequence of 32-byte aligned chunks. ``GetChunkHeader`` 0x80010B6C aligns the
    file position to 32 and reads a 0x20-byte big-endian header::

        +0x00 char id[8]   two u32 words, each byte-reversed (``ChunkIDToStr`` 0x80010858)
        +0x08 u32 size     uncompressed payload size (``SkipChunkData`` 0x80010A54 seeks it)
        +0x0C f32 version
        +0x10 u32 compressed
        +0x14 u32 pad (0xCDCDCDCD)
        +0x18 u32 disk_size  bytes stored after the header (``ReadChunkData`` 0x80010A7C)
        +0x1C u32 mem_size   expanded buffer size (size rounded up to 32)

    Compressed payloads use ``BOA_ExpandInplace`` 0x8001094C: an LZ77 variant with
    an LSB-first flag byte per 8 tokens; a set bit is a literal byte, a clear bit a
    2-byte back-reference ``b0, b1``: ``length = (b0 & 15) + 2`` (length nibble 0 is a
    no-op), ``distance = (b0 >> 4) | (b1 << 4)``.  Known chunk ids and their
    consumers in RSRC_Load: ``restable`` (FS_UseResourceTable 0x801AEF64),
    ``restxtrs`` (RSRC_InitStaticTextures), ``dyntxtrs`` (RSRC_InitDynTextures),
    ``shaders`` (SHDR_Init), ``bspfile`` (BSP_Init), ``sndbank`` /
    ``snd_alb`` (AL_LoadSampleBankMem / AL_LoadPatchBankMem), ``shockprf``.

``restable`` -- ``FS_UseResourceTable`` 0x801AEF64
    The level's file system: u32 count, then from +0x10 ``count`` records of
    ``{u32 name_off, u32 data_off, u32 size, u32 hash}`` relative to the table.
    It holds the character models (``models/actors/**.gcm``), animations (``.gca``),
    entity definitions (``.men``) and scripts.

``.gcm`` -- ``NGCObject3D::FixupModelData`` 0x8017AA9C,
``C_Object3D::FixupModelData`` 0x80183968, ``FixupHeaderOff`` 0x80183AF4,
``NGCObject3D::FixupNGCModelData`` 0x8017AB18
    Blocks start with a header whose byte 7 is the extra header length; the
    block body starts at ``block + 8 + byte7``.  ``(u32[0] >> 20) & 0x4FF == 0x484``
    marks an object.  Body offsets +0x74..+0x94 are block offsets relative to the
    file; body+0x80 is the NGC geometry block.  Its body holds 13 ``{u32 off, u32
    count}`` pairs (offsets relative to that body) at +0x34..+0x94; the element sizes
    below are the ones that tile every character model exactly (see ``tile_check``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import asdict, dataclass

BOND_ELF_SHA256 = "1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f"
SOURCE_GCZ_SHA256 = "00a0ebbd99cf3934b626dbc0d5bfa0de53e91a1f717fbb1814cb6c93d393faac"

# Bond.elf functions (RAM addresses as linked; ET_EXEC, symbol table kept).
EVIDENCE = {
    "RSRC_Load": 0x80016AFC,
    "GetChunkHeader": 0x80010B6C,
    "ReadChunkData": 0x80010A7C,
    "SkipChunkData": 0x80010A54,
    "ChunkIDToStr": 0x80010858,
    "BOA_ExpandInplace": 0x8001094C,
    "FS_UseResourceTable": 0x801AEF64,
    "NGCObject3D::FixupModelData": 0x8017AA9C,
    "NGCObject3D::FixupNGCModelData": 0x8017AB18,
    "C_Object3D::FixupModelData": 0x80183968,
    "C_Object3D::FixupHeaderOff": 0x80183AF4,
    "C_Q3Object3D::CreateObjectFrom": 0x80178B4C,
    "ME_LoadTIKIfile": 0x80173C24,
    "ME_LoadModel": 0x801748B4,
    "NGCObject3D::BuildMatrixList": 0x8017A674,
    "C_Q3Object3D::AnimateSkeleton": 0x80177958,
}

CHUNK_HEADER = 0x20
OBJECT_MAGIC = 0x484

# NGC geometry body: (field offset of the pointer, name, element size).
# The u32 count follows each pointer.  Order and names come from
# FixupNGCModelData's RecoverPointer<T> calls.
NGC_ARRAYS = (
    (0x34, "vtx_pos", 6),        # NGC_EntVtxPos_s: s16 x,y,z
    (0x3C, "vtx_normal", 3),     # NGC_EntVtxNormal_s: s8 x,y,z
    (0x44, "vtx_st", 4),         # NGC_EntVtxST_s: s16 s,t
    (0x4C, "ent_vtx", 6),        # NGC_EntVtx_s: u16 pos, normal, st indices
    (0x54, "u16_list", 2),       # RecoverPointer<unsigned short>
    (0x5C, "u8_list", 1),        # RecoverPointer<unsigned char>
    (0x64, "tri_strip", 8),      # NGC_EntTriStrip_s
    (0x6C, "mtx_map", 2),        # NGC_EntMtxMap_s
    (0x74, "geom_group", 8),     # NGC_EntGeomGroup_s
    (0x7C, "geom_section", 16),  # NGC_EntGeomSection_s (+4 = shader id -> SHDR_LookupID)
    (0x84, "morph_delta", None),
    (0x8C, "morph_vtx", None),
    (0x94, "morph_group", 12),   # NGC_MorphGroup_s (+4 -> MorphVtx)
)


def chunk_id(raw: bytes) -> str:
    """Decode an 8-byte chunk id exactly like ChunkIDToStr (two byte-reversed words)."""
    w0, w1 = struct.unpack(">II", raw[:8])
    return (struct.pack("<I", w1) + struct.pack("<I", w0)).split(b"\0", 1)[0].decode("latin-1")


def encode_chunk_id(name: str) -> bytes:
    b = name.encode("latin-1").ljust(8, b"\0")[:8]
    w1 = struct.unpack("<I", b[:4])[0]
    w0 = struct.unpack("<I", b[4:])[0]
    return struct.pack(">II", w0, w1)


def boa_expand(src: bytes, size: int, pos: int = 0) -> tuple[bytes, int]:
    """BOA_ExpandInplace. Returns (expanded bytes, input bytes consumed)."""
    out = bytearray()
    i = pos
    n_src = len(src)
    while len(out) < size:
        if i >= n_src:
            raise ValueError("BOA stream truncated at %d/%d output bytes" % (len(out), size))
        flags = src[i]
        i += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags >> bit & 1:
                out.append(src[i])
                i += 1
                continue
            b0, b1 = src[i], src[i + 1]
            i += 2
            n = b0 & 15
            if not n:
                continue
            dist = (b0 >> 4) | (b1 << 4)
            start = len(out) - dist
            if dist == 0 or start < 0:
                raise ValueError("BOA back-reference before start (dist %d at %d)" % (dist, len(out)))
            for k in range(n + 2):
                out.append(out[start + k])
    return bytes(out[:size]), i - pos


def boa_store(data: bytes) -> bytes:
    """Encode ``data`` as an all-literal BOA stream (valid input for boa_expand)."""
    out = bytearray()
    for i in range(0, len(data), 8):
        block = data[i:i + 8]
        out.append(0xFF)
        out += block
    return bytes(out)


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
        size, ver, comp, _pad, disk, mem = struct.unpack(">IfIIII", h[8:])
        c = Chunk(chunk_id(h), pos, size, ver, comp, disk, mem)
        if c.data_offset + disk > len(data):
            raise ValueError("chunk %r at %#x overruns the file" % (c.id, pos))
        yield c
        pos = c.end


def read_chunk(data: bytes, c: Chunk) -> bytes:
    raw = data[c.data_offset:c.data_offset + c.disk_size]
    if not c.compressed:
        return raw[:c.size]
    out, _used = boa_expand(raw, c.mem_size)
    return out


@dataclass
class Resource:
    name: str
    offset: int
    size: int
    hash: int


def parse_restable(table: bytes) -> list[Resource]:
    count = struct.unpack_from(">I", table, 0)[0]
    out = []
    for i in range(count):
        no, do, sz, hv = struct.unpack_from(">4I", table, 0x10 + i * 16)
        end = table.index(b"\0", no)
        if do + sz > len(table):
            raise ValueError("resource %d overruns the table" % i)
        out.append(Resource(table[no:end].decode("latin-1"), do, sz, hv))
    return out


class NgcPackage:
    def __init__(self, data: bytes):
        self.data = data
        self.chunks = list(iter_chunks(data))
        self._table = None

    def chunk(self, cid: str) -> Chunk:
        for c in self.chunks:
            if c.id == cid:
                return c
        raise KeyError(cid)

    @property
    def table(self) -> bytes:
        if self._table is None:
            self._table = read_chunk(self.data, self.chunk("restable"))
        return self._table

    def resources(self) -> list[Resource]:
        return parse_restable(self.table)

    def read(self, name: str) -> bytes:
        for r in self.resources():
            if r.name.lower() == name.lower():
                return self.table[r.offset:r.offset + r.size]
        raise KeyError(name)


def _body(data: bytes, block: int) -> int:
    return block + 8 + data[block + 7]


def gcm_info(gcm: bytes) -> dict:
    """Header + NGC geometry array table of one .gcm object."""
    word0 = struct.unpack_from(">I", gcm, 0)[0]
    if (word0 >> 20) & 0x4FF != OBJECT_MAGIC:
        raise ValueError("not an NGCObject3D model (magic %#x)" % ((word0 >> 20) & 0x4FF))
    hdr = _body(gcm, 0)
    flags = struct.unpack_from(">I", gcm, hdr + 8)[0]
    file_size = struct.unpack_from(">I", gcm, hdr + 0x0C)[0]
    blocks = {}
    for off in (0x74, 0x78, 0x7C, 0x80, 0x84, 0x88, 0x8C, 0x90, 0x94):
        blocks[off] = struct.unpack_from(">I", gcm, hdr + off)[0]
    ngc_block = blocks[0x80]
    if not ngc_block:
        raise ValueError("no NGC geometry block")
    body = _body(gcm, ngc_block)
    arrays = []
    for field, name, esize in NGC_ARRAYS:
        off, count = struct.unpack_from(">II", gcm, body + field)
        arrays.append({"name": name, "field": field, "offset": off, "count": count,
                       "elem_size": esize, "file_offset": body + off if off else 0})
    return {"flags": flags, "file_size": file_size, "packed": bool(flags & 0x8000),
            "blocks": {"%#x" % k: v for k, v in blocks.items()},
            "ngc_block": ngc_block, "ngc_body": body, "arrays": arrays}


def tile_check(info: dict) -> list[str]:
    """Check the arrays are contiguous: each ends (with <=3 bytes of 4-byte padding)
    where the next present one starts.  Returns problems (empty = consistent)."""
    present = [a for a in info["arrays"] if a["offset"] and a["count"]]
    problems = []
    for a, b in zip(present, present[1:]):
        if a["elem_size"] is None:
            continue
        end = a["offset"] + a["count"] * a["elem_size"]
        gap = b["offset"] - end
        if not 0 <= gap <= 3:
            problems.append("%s ends at %#x but %s starts at %#x" % (a["name"], end, b["name"], b["offset"]))
    return problems


def positions(gcm: bytes, info: dict | None = None) -> list[tuple[int, int, int]]:
    """Raw s16 vertex positions (fixed point; the scale is a reader-stage item)."""
    info = info or gcm_info(gcm)
    a = info["arrays"][0]
    return [struct.unpack_from(">hhh", gcm, a["file_offset"] + 6 * i) for i in range(a["count"])]


def characters(pkg: NgcPackage) -> list[dict]:
    out = []
    for r in pkg.resources():
        if not (r.name.startswith("models/actors/") and r.name.endswith(".gcm")):
            continue
        g = pkg.table[r.offset:r.offset + r.size]
        row = {"name": r.name, "size": r.size, "sha256": hashlib.sha256(g).hexdigest()}
        try:
            info = gcm_info(g)
            row.update(vtx_pos=info["arrays"][0]["count"], ent_vtx=info["arrays"][3]["count"],
                       tri_strips=info["arrays"][6]["count"], sections=info["arrays"][9]["count"],
                       mtx_map=info["arrays"][7]["count"], tile_problems=tile_check(info))
        except (ValueError, struct.error) as e:
            row["error"] = str(e)
        out.append(row)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AUF GC .ngc level package / .gcm model probe")
    ap.add_argument("ngc")
    ap.add_argument("--gcm", help="dump one model's header/array table")
    ap.add_argument("--extract", help="write the named resource to this path", nargs=2,
                    metavar=("NAME", "OUT"))
    a = ap.parse_args(argv)
    pkg = NgcPackage(open(a.ngc, "rb").read())
    if a.extract:
        open(a.extract[1], "wb").write(pkg.read(a.extract[0]))
        return 0
    if a.gcm:
        info = gcm_info(pkg.read(a.gcm))
        info["tile_problems"] = tile_check(info)
        print(json.dumps(info, indent=1))
        return 0
    res = pkg.resources()
    print(json.dumps({"chunks": [asdict(c) for c in pkg.chunks], "resources": len(res),
                      "characters": characters(pkg)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
