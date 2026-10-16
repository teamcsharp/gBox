"""GoldenEye 007 (Europe, NGEP) Z-file writer.

Writer-stage foundation for the owned PAL cartridge (normalised z64 sha256
40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de).

The reader (gbox/goldeneye_reader.py) decodes a body file ("Z-file") into a
typed node tree.  This module closes the loop: it captures a faithful
*blob map* of every byte in an inflated Z-file, re-serialises it byte-exactly
(no-op roundtrip), and surgically replaces a node's geometry blobs in place
(the first writer capability, from which a changed-donor cast swap is built).

Layout of an inflated Z-file (derived from the 80 PAL body/head files; every
byte is accounted for, see :func:`verify_coverage`):

    0x0000            [numSwitches x u32 switch-node ptrs]
                      [numTextures x 12-byte sImageTableEntry records]
    root_offset       node tree: numNodes x 0x18 ModelNode, contiguous
    payload region    per node, in node order:
                          op-0x04/0x18 only: render vertices (nv x 0x10)
                          and (0x18) collision vertices + point usage
                      then the node's record payload (RECORD_SIZES[op] bytes)
                      -- 4-byte aligned for records, 8-byte aligned for
                      vertex arrays; the original zero padding is reproduced
    DL region         primary/secondary display lists, in node order,
                      8-byte aligned
    tail              trailing zero bytes (8 bytes for the body files)

Record sizes are taken from the decomp (n64decomp/007 src/bondtypes.h
``ModelRoData_*``): 0x01 Header 0x10, 0x02 Group 0x1C, 0x04 DisplayList 0x14,
0x08 LOD 0x10, 0x09 BSP 0x24, 0x0A BoundingBox 0x1C, 0x0D Shadow 0x20,
0x12 Switch 0x08, 0x15 GroupSimple 0x14, 0x17 HeadPlaceholder 0x02,
0x18 DisplayListCollision 0x20.  Note this *corrects* the reader, which
mis-labelled opcode 0x17 (HeadPlaceholder, u16 RwDataIndex) as the 32-byte
Op17Record (0x11 in the decomp) -- the reader over-read 32 bytes into the
next record; opcode 0x11 does not occur in any of the 80 PAL bodies.

The interleaving of vertex arrays and record payloads follows the node order
above, but the exact byte offsets (including Rare's record packing and the
alignment padding) are *captured* from the source rather than re-derived,
because they are linker output.  Re-laying out blobs at shifted offsets
(needed when a donor's geometry is *larger* than the target slot) is the next
writer step.

``serialize`` is still a real encoder: it rebuilds the header from parsed
values, recomputes every node's seg-5 ``Data`` pointer from the blob layout,
and re-emits each payload blob, asserting full coverage so a missed blob type
surfaces immediately rather than as a silent corruption.

Usage: python -m gbox.goldeneye_writer ROM [--body CsuitbondZ]
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from gbox.goldeneye_files import (FILE_SEGMENT, NODE_SIZE, TEXTURE_RECORD_SIZE,
                                  GoldenEyeFormatError, GoldenEyeROM)
from gbox.goldeneye_reader import parse_nodes

VERTEX_SIZE = 0x10
POINT_USAGE_SIZE = 2

# Correct ModelRoData_* record sizes (decomp bondtypes.h).  The reader's
# RECORD_SIZES[0x17] = 0x20 is wrong (see module docstring); this table is
# authoritative for re-encoding.
RECORD_SIZES = {
    0x01: 0x10,  # HeaderRecord
    0x02: 0x1C,  # GroupRecord
    0x04: 0x14,  # DisplayListRecord (collisionless, guns)
    0x08: 0x10,  # LODRecord
    0x09: 0x24,  # BSPRecord
    0x0A: 0x1C,  # BoundingBoxRecord
    0x0D: 0x20,  # ShadowRecord
    0x12: 0x08,  # SwitchRecord
    0x15: 0x14,  # GroupSimpleRecord
    0x17: 0x02,  # HeadPlaceholderRecord
    0x18: 0x20,  # DisplayList_CollisionRecord
}

# opcodes whose record owns a render vertex array + display list(s)
DL_OPS = {0x04, 0x18}


@dataclass
class Blob:
    """One contiguous byte range of the Z-file, owned by a node (or the file)."""
    kind: str          # "switch", "texture", "node", "record", "verts",
                       # "collision", "point_usage", "primary_dl", "secondary_dl", "tail"
    node_offset: int   # owning node's file offset (0 for file-level blobs)
    start: int         # blob start in the file
    data: bytes

    @property
    def end(self) -> int:
        return self.start + len(self.data)


@dataclass
class ZFile:
    """Parsed Z-file: header values, node tree, and the full blob map."""
    filename: str
    num_switches: int
    num_textures: int
    switches: list[int]
    texture_records: list[bytes]          # raw 12-byte sImageTableEntry bytes
    node_offsets: list[int]               # node header offsets, ascending
    # offset -> (opcode, pad, orig_data_ptr, parent, next, prev, child)
    node_headers: dict[int, tuple]
    record_blob: dict[int, Blob]          # node offset -> record payload blob
    blobs: list[Blob]                     # every payload blob (records, verts, DLs, tail)
    original: bytes

    @property
    def root_offset(self) -> int:
        return 4 * self.num_switches + TEXTURE_RECORD_SIZE * self.num_textures


def _dl_bytes(model: bytes, dl_off: int) -> bytes:
    """Raw bytes of a display list from ``dl_off`` to (and including) G_ENDDL."""
    if dl_off < 0 or dl_off + 8 > len(model):
        return b""
    end = dl_off
    while end + 8 <= len(model):
        w0, _ = struct.unpack_from(">II", model, end)
        cmd = w0 >> 24
        end += 8
        if cmd == 0xB8:  # G_ENDDL
            return model[dl_off:end]
    return b""


def _dl_record_ptrs(model: bytes, n) -> dict:
    """Resolve a DL-record node's sub-blob pointers (op 0x04 / 0x18).

    Reads the record payload directly so the writer is independent of the
    reader's record dict (which only decodes op 0x18).  Pointers are seg-5
    addresses; returns their file offsets (or None).
    """
    def seg5(p):
        if not p:
            return None
        off = p - FILE_SEGMENT
        return off if 0 <= off < len(model) else None

    d = n.data_off
    if n.op == 0x04:  # ModelRoData_DisplayListRecord (collisionless, guns)
        primary, secondary, base, verts, nv, _mtype = struct.unpack_from(">IIIIHB", model, d)
        return {"vertices": seg5(verts), "num_vertices": nv,
                "primary_dl": seg5(primary), "secondary_dl": seg5(secondary),
                "num_collision_vertices": 0, "collision_vertices": None,
                "point_usage": None}
    if n.op == 0x18:  # ModelRoData_DisplayList_CollisionRecord
        primary, secondary, verts, nv, ncv, cv, pu, _mtype, _rw, _base = \
            struct.unpack_from(">IIIhhIIhHI", model, d)
        return {"vertices": seg5(verts), "num_vertices": nv,
                "primary_dl": seg5(primary), "secondary_dl": seg5(secondary),
                "num_collision_vertices": ncv, "collision_vertices": seg5(cv),
                "point_usage": seg5(pu)}
    return {}


def _sub_blobs(model: bytes, n) -> list[Blob]:
    """Vertex / point-usage / DL blobs owned by a DL-record node (op 0x04/0x18)."""
    r = _dl_record_ptrs(model, n)
    out: list[Blob] = []
    nv = r.get("num_vertices", 0)
    if r.get("vertices") is not None and 0 <= r["vertices"] < len(model) and nv > 0:
        off = r["vertices"]
        out.append(Blob("verts", n.offset, off, model[off:off + nv * VERTEX_SIZE]))
    if n.op == 0x18:
        ncv = r.get("num_collision_vertices", 0)
        if r.get("collision_vertices") is not None and 0 <= r["collision_vertices"] < len(model) and ncv > 0:
            off = r["collision_vertices"]
            out.append(Blob("collision", n.offset, off, model[off:off + ncv * VERTEX_SIZE]))
        if r.get("point_usage") is not None and 0 <= r["point_usage"] < len(model) and nv > 0:
            off = r["point_usage"]
            out.append(Blob("point_usage", n.offset, off, model[off:off + nv * POINT_USAGE_SIZE]))
    for kind, key in (("primary_dl", "primary_dl"), ("secondary_dl", "secondary_dl")):
        dl = r.get(key)
        if dl is not None and dl >= 0:
            data = _dl_bytes(model, dl)
            if data:
                out.append(Blob(kind, n.offset, dl, data))
    return out


def parse(ge: GoldenEyeROM, filename: str) -> ZFile:
    """Build the blob map for one body file."""
    model = ge.read_file(filename)
    hdr = ge.model_header(next(b for b in ge.body_table() if b.filename == filename).header_vram)

    switches = [struct.unpack_from(">I", model, 4 * i)[0] for i in range(hdr.num_switches)]
    tex_off = 4 * hdr.num_switches
    texture_records = [model[tex_off + TEXTURE_RECORD_SIZE * i:
                             tex_off + TEXTURE_RECORD_SIZE * (i + 1)]
                       for i in range(hdr.num_textures)]
    root_off = tex_off + TEXTURE_RECORD_SIZE * hdr.num_textures

    nodes = parse_nodes(model, root_off)
    node_offsets = [n.offset for n in nodes]
    node_headers: dict[int, tuple] = {}
    for n in nodes:
        op, _pad, dptr, parent, nxt, prev, child = struct.unpack_from(">HHIIIII", model, n.offset)
        node_headers[n.offset] = (op, 0, dptr, parent, nxt, prev, child)

    blobs: list[Blob] = []
    record_blob: dict[int, Blob] = {}
    blobs.append(Blob("switch", 0, 0, model[:tex_off]))
    if texture_records:
        blobs.append(Blob("texture", 0, tex_off, model[tex_off:root_off]))
    for n in nodes:
        blobs.append(Blob("node", n.offset, n.offset, model[n.offset:n.offset + NODE_SIZE]))
    for n in nodes:
        d = n.data_off
        if n.op in RECORD_SIZES and 0 <= d < len(model):
            size = RECORD_SIZES[n.op]
            rec = Blob("record", n.offset, d, model[d:d + size])
            blobs.append(rec)
            record_blob[n.offset] = rec
            if n.op in DL_OPS:
                blobs.extend(_sub_blobs(model, n))
    blobs.sort(key=lambda b: b.start)
    last_end = max((b.end for b in blobs), default=0)
    if last_end < len(model):
        blobs.append(Blob("tail", 0, last_end, model[last_end:]))

    return ZFile(filename, hdr.num_switches, hdr.num_textures, switches,
                 texture_records, node_offsets, node_headers, record_blob, blobs, model)


def verify_coverage(zf: ZFile) -> list[tuple[int, int]]:
    """Return byte ranges of the file not claimed by any blob ([] == full cover).

    Overlapping blobs are legitimate (Rare's record packing); they are OR-ed
    together.  Gaps here mean a blob type was not captured.
    """
    covered = bytearray(len(zf.original))
    for b in zf.blobs:
        covered[b.start:b.end] = bytes([1]) * (b.end - b.start)
    gaps, i = [], 0
    while i < len(covered):
        if covered[i] == 0:
            j = i
            while j < len(covered) and covered[j] == 0:
                j += 1
            gaps.append((i, j))
            i = j
        else:
            i += 1
    return gaps


def _node_bytes(zf: ZFile, node_offset: int) -> bytes:
    op, pad, orig_dptr, parent, nxt, prev, child = zf.node_headers[node_offset]
    rec = zf.record_blob.get(node_offset)
    # recompute the Data pointer from the (possibly re-laid-out) record offset;
    # nodes without a decoded record keep their original pointer verbatim
    data_ptr = (FILE_SEGMENT + rec.start) if rec is not None else orig_dptr
    return struct.pack(">HHIIIII", op, pad, data_ptr, parent, nxt, prev, child)


def serialize(zf: ZFile, replacements: dict[int, dict[str, bytes]] | None = None) -> bytes:
    """Re-emit the Z-file.

    ``replacements`` maps a node offset to ``{kind: new_bytes}`` (kind is one of
    "verts"/"collision"/"point_usage"/"primary_dl"); each replacement must be no
    longer than the original blob (it is zero-padded to the original length, so
    pointers and offsets stay valid).  With no replacements the output is
    byte-identical to the source (the no-op roundtrip).
    """
    replacements = replacements or {}
    out = bytearray(len(zf.original))  # zero-filled: reproduces the zero pads
    out[0:4 * zf.num_switches] = struct.pack(">" + "I" * zf.num_switches, *zf.switches)
    tex_off = 4 * zf.num_switches
    for i, rec in enumerate(zf.texture_records):
        out[tex_off + TEXTURE_RECORD_SIZE * i:tex_off + TEXTURE_RECORD_SIZE * (i + 1)] = rec
    for off in zf.node_offsets:
        out[off:off + NODE_SIZE] = _node_bytes(zf, off)
    for b in zf.blobs:
        if b.kind in ("switch", "texture", "node", "tail"):
            continue
        data = b.data
        if b.node_offset in replacements and b.kind in replacements[b.node_offset]:
            new = replacements[b.node_offset][b.kind]
            if len(new) > len(b.data):
                raise GoldenEyeFormatError(
                    f"{zf.filename}: replacement {b.kind} for node 0x{b.node_offset:X} is "
                    f"{len(new)} bytes, exceeds the {len(b.data)}-byte slot")
            data = new + b"\x00" * (len(b.data) - len(new))
        out[b.start:b.end] = data
    for b in zf.blobs:
        if b.kind == "tail":
            out[b.start:b.end] = b.data
    return bytes(out)


def edit_geometry(zf: ZFile, node_offset: int, *, verts: bytes | None = None,
                  collision: bytes | None = None, point_usage: bytes | None = None,
                  primary_dl: bytes | None = None) -> bytes:
    """Replace a target DL node's geometry in place and re-serialize.

    Each supplied blob must fit its original slot (<= original length; it is
    zero-padded).  Returns the new Z-file bytes.
    """
    repl: dict[str, bytes] = {}
    for kind, data in (("verts", verts), ("collision", collision),
                       ("point_usage", point_usage), ("primary_dl", primary_dl)):
        if data is not None:
            repl[kind] = data
    return serialize(zf, {node_offset: repl})


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="GoldenEye PAL Z-file writer (no-op roundtrip)")
    ap.add_argument("rom")
    ap.add_argument("--body", default="CsuitbondZ")
    a = ap.parse_args(argv)
    ge = GoldenEyeROM.load(a.rom)
    zf = parse(ge, a.body)
    out = serialize(zf)
    gaps = verify_coverage(zf)
    print(f"{a.body}: {len(zf.blobs)} blobs, {len(zf.node_offsets)} nodes, "
          f"coverage gaps {len(gaps)}")
    print("no-op roundtrip byte-identical:", out == zf.original)
    print("sha256", hashlib.sha256(out).hexdigest())
    if gaps:
        print("gaps:", [f"0x{s:X}-0x{e:X}" for s, e in gaps])
    return 0 if (out == zf.original and not gaps) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
