"""GoldenEye 007 (Europe, NGEP) file-table, body-table and model-header probe.

Analysis-stage findings for the owned PAL cartridge (normalised z64 sha256
40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de):

* Assets and the main data segment are ``rarezip`` blocks: the two magic
  bytes ``0x11 0x72`` followed directly by a raw DEFLATE stream (no size
  field, no zlib header).  ``zlib.decompressobj(-15)`` inflates them.
* The game's data segment is the rarezip block at ROM 0x1F850.  It inflates
  to 0x32A50 bytes and is linked at VRAM 0x8001EC50 (every one of the 770
  file-table name pointers resolves to a NUL-terminated name with that base).
* The file resource table lives in that segment at VRAM 0x8003EAC4: 771
  entries of ``{u32 index, char *name, u32 rom_offset}`` (stride 12).  Entry
  0 is the empty sentinel, the last real entry is ``ob/ob_end.seg``; a
  file's compressed size is the next entry's ROM offset minus its own.
  Character files are named ``C<body>Z`` (bodies) and ``Chead<name>Z``.
* The character body table is at VRAM 0x80037A60: 80 entries of
  ``{ModelFileHeader *header, char *filename, f32 scale, f32 pov,
  u8 is_male, u8 is_head, u16 pad}`` (stride 0x14).  The ModelFileHeader
  lives in the data segment, NOT in the file: ``{RootNode* (filled at load),
  Skeleton*, Switches** (filled at load), s16 num_switches, s16
  num_records, f32 radius, s16 pad, s16 num_textures, ...}``.
* A loaded character file is segment 0x05-relative: ``num_switches`` u32
  switch-node pointers, ``num_textures`` 12-byte texture records
  ``{u32 texture_id, u8 w, u8 h, u8 fmt, u8 0, u8 s, u8 t, u8 ?, u8 0}``,
  then the node tree.  The root node (opcode 0x01) sits immediately after
  the texture records.  Nodes are 0x18 bytes:
  ``{u16 opcode, u16 pad, data*, parent*, next*, prev*, child*}``.
  Opcode 0x02 is a Position (bone) node and 0x18 a vertex display list.

Usage: python -m gbox.goldeneye_files ROM [--body CsuitbondZ] [--out x.json]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RAREZIP_MAGIC = b"\x11\x72"

# Pinned for the owned PAL build; validate() re-derives and checks them.
PAL_Z64_SHA256 = "40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de"
DATA_SEG_ROM = 0x1F850
DATA_SEG_SIZE = 0x32A50
DATA_VRAM = 0x8001EC50
FILE_TABLE_VRAM = 0x8003EAC4
FILE_TABLE_STRIDE = 12
BODY_TABLE_VRAM = 0x80037A60
BODY_TABLE_STRIDE = 0x14
FILE_SEGMENT = 0x05000000
CODE_SCAN_END = 0x110000  # end of the uncompressed MIPS code (entropy/opcode map)
NODE_SIZE = 0x18
TEXTURE_RECORD_SIZE = 12


class GoldenEyeFormatError(ValueError):
    pass


def rarezip_inflate(buf: bytes, offset: int, limit: int | None = None) -> tuple[bytes, int]:
    """Inflate the rarezip block at ``offset``; return (data, compressed_len)."""
    if buf[offset:offset + 2] != RAREZIP_MAGIC:
        raise GoldenEyeFormatError(f"no rarezip magic at 0x{offset:X}")
    end = len(buf) if limit is None else min(len(buf), offset + limit)
    d = zlib.decompressobj(-15)
    try:
        out = d.decompress(buf[offset + 2:end])
    except zlib.error as exc:
        raise GoldenEyeFormatError(f"bad rarezip stream at 0x{offset:X}: {exc}") from exc
    if not d.eof:
        raise GoldenEyeFormatError(f"truncated rarezip stream at 0x{offset:X}")
    used = (end - offset - 2) - len(d.unused_data)
    return out, used + 2


def _cstr(buf: bytes, off: int) -> str:
    if not 0 <= off < len(buf):
        raise GoldenEyeFormatError(f"string offset 0x{off:X} outside segment")
    end = buf.index(b"\0", off)
    return buf[off:end].decode("latin-1")


@dataclass
class FileEntry:
    index: int
    name: str
    rom_offset: int
    rom_size: int


@dataclass
class BodyEntry:
    index: int
    filename: str
    header_vram: int
    scale: float
    pov: float
    is_male: int
    is_head: int


@dataclass
class ModelHeader:
    vram: int
    root_node: int
    skeleton_vram: int
    switches: int
    num_switches: int
    num_matrices: int
    radius: float
    num_records: int
    num_textures: int
    skeleton_joints: int | None = None


@dataclass
class GoldenEyeROM:
    rom: bytes
    data: bytes = field(repr=False, default=b"")

    @classmethod
    def load(cls, path: str | Path) -> "GoldenEyeROM":
        p = Path(path)
        raw = p.read_bytes()
        if raw[:4] != b"\x80\x37\x12\x40":
            # Accept v64/n64 via the shared normaliser.
            from gbox import n64_rom
            raw = n64_rom.read(p)
        return cls.from_bytes(raw)

    @classmethod
    def from_bytes(cls, rom: bytes) -> "GoldenEyeROM":
        data, _ = rarezip_inflate(rom, DATA_SEG_ROM)
        if len(data) != DATA_SEG_SIZE:
            raise GoldenEyeFormatError(
                f"data segment inflated to 0x{len(data):X}, expected 0x{DATA_SEG_SIZE:X} (not the PAL build?)")
        return cls(rom=rom, data=data)

    # -- address helpers -------------------------------------------------
    def d_off(self, vram: int) -> int:
        off = vram - DATA_VRAM
        if not 0 <= off < len(self.data):
            raise GoldenEyeFormatError(f"VRAM 0x{vram:08X} outside data segment")
        return off

    def u32(self, vram: int) -> int:
        return struct.unpack_from(">I", self.data, self.d_off(vram))[0]

    # -- tables ----------------------------------------------------------
    def file_table(self) -> list[FileEntry]:
        base = self.d_off(FILE_TABLE_VRAM)
        raw = []
        k = base
        while k + FILE_TABLE_STRIDE <= len(self.data):
            idx, name_ptr, rom_off = struct.unpack_from(">III", self.data, k)
            if idx != len(raw):
                break
            raw.append((idx, name_ptr, rom_off))
            k += FILE_TABLE_STRIDE
        out = []
        for i, (idx, name_ptr, rom_off) in enumerate(raw):
            name = _cstr(self.data, self.d_off(name_ptr))
            nxt = raw[i + 1][2] if i + 1 < len(raw) else rom_off
            out.append(FileEntry(idx, name, rom_off, max(0, nxt - rom_off)))
        return out

    def file_by_name(self, name: str) -> FileEntry:
        for e in self.file_table():
            if e.name == name or e.name.rsplit("/", 1)[-1] == name:
                return e
        raise KeyError(name)

    def read_file(self, name: str) -> bytes:
        e = self.file_by_name(name)
        data, used = rarezip_inflate(self.rom, e.rom_offset, e.rom_size)
        if used > e.rom_size:
            raise GoldenEyeFormatError(f"{name}: stream overruns table size")
        return data

    def body_table(self) -> list[BodyEntry]:
        out = []
        k = self.d_off(BODY_TABLE_VRAM)
        while k + BODY_TABLE_STRIDE <= len(self.data):
            hdr, name_ptr, scale, pov, male, head, _pad = struct.unpack_from(">IIffBBH", self.data, k)
            try:
                name = _cstr(self.data, self.d_off(name_ptr))
                self.d_off(hdr)
            except GoldenEyeFormatError:
                break
            if not name.endswith("Z"):
                break
            out.append(BodyEntry(len(out), name, hdr, scale, pov, male, head))
            k += BODY_TABLE_STRIDE
        return out

    def model_header(self, vram: int) -> ModelHeader:
        # ModelFileHeader (bondtypes.h): {RootNode*, Skeleton*, Switches**,
        # s16 numSwitches, s16 numMatrices, f32 BoundingVolumeRadius,
        # s16 numRecords, s16 numTextures, ModelFileTextures*}.  The reader
        # used to call numMatrices "num_records" and drop numRecords (the pad
        # slot); both are now named to match the decomp.
        o = self.d_off(vram)
        root, skel, sw, nsw, nmat, radius, nrec, ntex = struct.unpack_from(">IIIhhfhh", self.data, o)
        joints = None
        if skel:
            joints = struct.unpack_from(">h", self.data, self.d_off(skel))[0]
        return ModelHeader(vram, root, skel, sw, nsw, nmat, radius, nrec, ntex, joints)


def walk_nodes(model: bytes, root_off: int) -> list[tuple[int, int, int]]:
    """Return (offset, opcode, data_ptr) for every node reachable from root."""
    out, stack, seen = [], [root_off + FILE_SEGMENT], set()
    while stack:
        a = stack.pop()
        if a == 0 or a in seen:
            continue
        o = a - FILE_SEGMENT
        if not 0 <= o <= len(model) - NODE_SIZE:
            raise GoldenEyeFormatError(f"node pointer 0x{a:08X} outside file")
        seen.add(a)
        op, _pad, dptr, _parent, nxt, _prev, child = struct.unpack_from(">HHIIIII", model, o)
        out.append((o, op, dptr))
        stack.extend((nxt, child))
    return out


def probe_character(ge: GoldenEyeROM, filename: str) -> dict:
    body = next((b for b in ge.body_table() if b.filename == filename), None)
    if body is None:
        raise KeyError(filename)
    hdr = ge.model_header(body.header_vram)
    entry = ge.file_by_name(filename)
    model = ge.read_file(filename)
    switches = [struct.unpack_from(">I", model, 4 * i)[0] for i in range(hdr.num_switches)]
    tex_off = 4 * hdr.num_switches
    textures = []
    for i in range(hdr.num_textures):
        tid, w, h, fmt = struct.unpack_from(">IBBB", model, tex_off + TEXTURE_RECORD_SIZE * i)
        textures.append({"id": tid, "w": w, "h": h, "fmt": fmt})
    root_off = tex_off + TEXTURE_RECORD_SIZE * hdr.num_textures
    root_op = struct.unpack_from(">H", model, root_off)[0]
    # Skinned bodies start with a 0x01 header node; heads hang their first
    # mesh/switch node (0x08/0x12/0x18) directly off the body's head bone.
    if body.is_head or not hdr.skeleton_vram:
        if not 0x01 <= (root_op & 0xFF) <= 0x18:
            raise GoldenEyeFormatError(f"{filename}: head root 0x{root_off:X} opcode 0x{root_op:04X}")
    elif root_op & 0xFF != 0x01:
        raise GoldenEyeFormatError(f"{filename}: root node at 0x{root_off:X} has opcode 0x{root_op:04X}")
    nodes = walk_nodes(model, root_off)
    ops = Counter(op & 0xFF for _, op, _ in nodes)
    for s in switches:
        if s and not (0 <= s - FILE_SEGMENT < len(model)):
            raise GoldenEyeFormatError(f"{filename}: switch 0x{s:08X} outside file")
    return {
        "filename": filename,
        "body_index": body.index,
        "file_index": entry.index,
        "rom_offset": entry.rom_offset,
        "rom_size": entry.rom_size,
        "inflated_size": len(model),
        "inflated_sha256": hashlib.sha256(model).hexdigest(),
        "header_vram": hdr.vram,
        "skeleton_vram": hdr.skeleton_vram,
        "skeleton_joints": hdr.skeleton_joints,
        "num_switches": hdr.num_switches,
        "num_matrices": hdr.num_matrices,
        "num_records": hdr.num_records,
        "radius": round(hdr.radius, 3),
        "num_textures": hdr.num_textures,
        "textures": textures,
        "root_offset": root_off,
        "node_count": len(nodes),
        "position_nodes": ops.get(0x02, 0),
        "vertex_dl_nodes": ops.get(0x18, 0),
        "opcodes": {f"0x{k:02X}": v for k, v in sorted(ops.items())},
        "pov": round(body.pov, 4),
        "is_male": body.is_male,
        "is_head": body.is_head,
    }


def find_lui_addiu_xrefs(rom: bytes, target: int, start: int = 0x1000, end: int = DATA_SEG_ROM) -> list[int]:
    """ROM offsets of ``lui rX,hi`` whose paired addiu/ori/load (same reg, within 16 insns) forms ``target``."""
    hi = ((target + 0x8000) >> 16) & 0xFFFF
    lo = target & 0xFFFF
    hits = []
    for o in range(start, end - 4, 4):
        w = struct.unpack_from(">I", rom, o)[0]
        if w >> 26 != 0x0F or (w & 0xFFFF) != hi:
            continue
        rt = (w >> 16) & 31
        for k in range(1, 17):
            q = o + 4 * k
            if q + 4 > end:
                break
            x = struct.unpack_from(">I", rom, q)[0]
            op = x >> 26
            if (x >> 21) & 31 == rt and (x & 0xFFFF) == lo and op in (0x09, 0x23, 0x2B, 0x21, 0x25, 0x20, 0x24, 0x31, 0x39):
                hits.append(o)
                break
    return hits


def find_code_xrefs(rom: bytes, target: int) -> list[dict]:
    """lui/lo xrefs to ``target`` in the uncompressed boot and game code, with the
    enclosing function's ROM start (nearest preceding ``addiu sp,sp,-N``)."""
    _, used = rarezip_inflate(rom, DATA_SEG_ROM)
    ranges = [(0x1000, DATA_SEG_ROM), ((DATA_SEG_ROM + used + 3) & ~3, CODE_SCAN_END)]
    out = []
    for start, end in ranges:
        for hit in find_lui_addiu_xrefs(rom, target, start, end):
            q = hit
            while q > max(start, hit - 0x4000):
                w = struct.unpack_from(">I", rom, q)[0]
                if w >> 16 == 0x27BD and w & 0x8000:
                    break
                q -= 4
            out.append({"rom": hit, "function_rom": q})
    return out


def boot_vram(rom_off: int) -> int:
    """Map a ROM offset in the uncompressed boot/main code to KSEG0 (entry 0x80000400 at ROM 0x1000)."""
    return 0x80000400 + (rom_off - 0x1000)


def manifest(ge: GoldenEyeROM, body: str = "CsuitbondZ") -> dict:
    files = ge.file_table()
    bodies = ge.body_table()
    chr_files = [f for f in files if f.name.startswith("C")]
    xrefs = {
        "file_table": find_code_xrefs(ge.rom, FILE_TABLE_VRAM),
        "body_table": find_code_xrefs(ge.rom, BODY_TABLE_VRAM),
    }
    return {
        "rom_sha256": hashlib.sha256(ge.rom).hexdigest(),
        "data_segment": {"rom": DATA_SEG_ROM, "size": len(ge.data), "vram": DATA_VRAM,
                         "sha256": hashlib.sha256(ge.data).hexdigest()},
        "file_table": {"vram": FILE_TABLE_VRAM, "entries": len(files), "last": files[-1].name},
        "character_files": [{"index": f.index, "name": f.name, "rom": f.rom_offset, "size": f.rom_size}
                            for f in chr_files],
        "body_table": {"vram": BODY_TABLE_VRAM, "entries": len(bodies),
                       "bodies": [{"index": b.index, "file": b.filename, "header": hex(b.header_vram),
                                   "pov": round(b.pov, 4), "is_head": b.is_head} for b in bodies]},
        "code_xrefs_rom": xrefs,
        "probe": probe_character(ge, body),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="GoldenEye PAL file/body table probe")
    ap.add_argument("rom")
    ap.add_argument("--body", default="CsuitbondZ")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = manifest(GoldenEyeROM.load(a.rom), a.body)
    text = json.dumps(m, indent=2)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({k: m[k] for k in ("rom_sha256", "file_table", "code_xrefs_rom", "probe")}, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
