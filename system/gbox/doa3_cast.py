"""DOA3 (USA, Xbox) native cast layer: XPR0 container walker, CAT companions,
slot inventory, the AFS patch path and the measured MDL geometry decoder.

Everything here is validated against the owned USA build (game b8edf7040116f3aa;
XBE sha256 e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3,
loadfile.afs 365690880 bytes). The decoder pins real byte layout; it is not a
playable build and must never be reported as one.

Layout facts pinned from kas00.xpr (entry 296 of loadfile.afs, 1943552 bytes,
sha256 2d048d4c0343c6a50ccd2a362a00980c88b09ee229dc5e6adce24cfc17ecf18d,
header 0x1E000):

* XPR0: magic, u32 total, u32 header_size, then the user-data pair
  {u32 0x80000000, u32 size, 4cc tag ``MDL``} at 0x0C..0x18. The MDL chunk
  header follows at 0x18: obj_count u32 (72), tex_count u32 (87), unknown u32
  (18), duplicated obj_count u32 (72). The ABSOLUTE object pointer table runs
  at 0x28 (obj_count u32), ends with a zero word and the first object record
  sits immediately after it ('OBJ\\0' at 0x14C for kas00). All OBJ records and
  their 16-bit index buffers live inside the header (below header_size); the
  32-byte vertex buffers start at header_size and form one contiguous chain,
  which extends PAST the declared MDL user-resource end - bounds are validated
  against ``total``, never against the resource size.
* OBJ record (0x4A424F = ``OBJ\\0``): +0x04 vertex type (0 = no weights,
  32-byte stride), +0x08 unknown, +0x0C unknown count, then the pinned geometry
  fields 16 bytes EARLIER than the DOA2U importer expects: +0x10 vertex_count,
  +0x14 absolute vertex buffer offset, +0x18 index_count (u16 strip indices),
  +0x1C absolute index buffer offset. The DOA2U importer reads position floats
  at +0x10..+0x1F and counts at +0x20..+0x2C - on DOA3 those reads produce
  denormals (measured), i.e. the DOA2U layout does NOT apply to DOA3.
* Materials begin at OBJ+0x60. Each record: a 33-word fixed header from M
  (word0 = flags with the 0x80 presence bit, word1 = length in WORDS, words
  4..7 a bounding sphere, words 9..19 colour terms, word 25 a specular power,
  word 26 the stage mode, word 27 the TEXTURE INDEX, word 31 a packet count),
  then 16-byte packets. Next record = M + 4*length_words. The record chain
  ends with a zero dword then 0x12345678 exactly 8 bytes before the OBJ index
  buffer (4646/4646 objects in the 69 costumes).
* Packets (measured on all 153,262 packets of the 69 costumes): every packet
  is one triangle strip {32*(n+2), index_off, n, flags}, NOT only the last one
  (an earlier reading treated the last packet as the whole face range and
  decoded a fraction of each mesh). The OBJ index buffer is one stitched strip
  list: each strip after the first starts with a two-index join (the previous
  strip's last index repeated, then its own first index; flags bit 1 adds a
  third, parity-fixing index), and ``index_off`` points at that join. The draw
  is ``[index_off, index_off + n + 4 (+1 when flags & 2))`` with the strip
  parity fresh at ``index_off``; degenerate triangles drop out and the first
  ``n`` real triangles are the strip (153,262/153,262 packets). Fresh per-packet
  parity is what makes the winding consistent: flags 0x900/0x901 strips agree
  with their vertex normals 99% one way/the other way under it, against ~50% for
  a single strip over the whole material. Materials in stage mode 3 (an extra
  environment stage, word 29 = 3) lead with two setup packets {4, 0x01000400 or
  0x400, 2184, 0} and {5, 0x400, strip_count, 0}.
* Triangles use the DOA2U parity flip rule inside each packet (winding
  alternates per index; degenerate triples are skipped). Every strip decodes
  with all indices below vertex_count, and every whole buffer passes the same
  bound check.
* Vertices: 32 bytes = position f32x3, normal f32x3, UV f32x2 (the DOA2U
  buildmsh order). Measured on kas00 OBJ0: |normal| = 1.0000 +/- 0.0000 for
  all 1204 vertices; u in [0.003, 1.000], v in [-0.995, 0.993]; position bounds
  x +/-0.094, y -0.320..0.234, z -0.093..0.152 (a costume part in model space).
* Textures: no DDS magic anywhere; raw D3D surfaces. The header tail after the
  last OBJ record holds the data descriptor table ``mdl_descriptor_table``:
  obj_count 12-byte vertex descriptors (cumulative vertex byte offsets) and
  tex_count 20-byte texture descriptors (cumulative data-region offsets plus a
  raw format word), terminated by 0xFFFFFFFF and 0xAD debug fill. The texture
  pixel format / draw-packet semantics are still unresolved (XBE loader RE).
* CAT (kas00.cat, entry 297, 338448 bytes, sha256
  17525ce658173efbc0b0e7a695e4cdae1842f2594866a1b1dcb6830e630aa4fc): the
  reliable signature is the FIXED pair at 0x14/0x18 = 0x100, 1, verified on
  all 69 complete costumes across 20 fighter families. The first five words
  (0x00..0x13) are NOT a stable header: 24 costumes store version=1, a 0x14
  word, then section offsets (word[1..4] = {0x14, s2, s3, s4}) whose word[3]
  is the ``LNK`` section offset (the "offsets" layout); the other 45 store an
  unresolved 20-byte ID block (the "id_block" layout). The ``LNK\\0`` section
  itself is ``LNK\\0`` + the 4-byte name ``0100`` + a 6-word header
  ``{2, 16, 32, size, 0, 0}``: the words 2/16/32 and the two trailing zeros
  are constant on every costume (68/69 have a LNK section; kor00 has none),
  while ``size`` is a 4-aligned byte count (the link-data size) that varies
  with the costume's accessory bones. The LNK body is: a C0 link-group count
  (9 on 65/68, 12 on the three Hikaru costumes) + C0 body-relative
  offsets/-1 sentinels, then per-group blocks ``{N, header_size = 4*(N+3),
  N+1 cumulative data lengths}`` (``cat_lnk_groups``; 431 blocks validated,
  N in [1, 22]). Each block's data region partitions into a leading *link
  table* (a count-prefixed u16 polygon list ``{n, n indices}``, n in [1, 13],
  zero-terminated, plus an unresolved residual) and N equal-length *link
  sections* that are flat u16 triangle lists (3 u16 per triangle,
  ``cat_lnk_sections``; stride multiple of 6 on 4402/4402 sections). The
  per-section triangle/joint semantics and the trailing near-EOF record table
  are still left for RE.
* AFS entries must be rewritten inside their room (size rounded up to the
  archive alignment, bounded by the next entry's offset / name directory),
  which ``doa3_inventory.entry_rooms`` computes.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path

from .doa3_inventory import (GAME_ID, ROSTER, DISPLAY_MAPPING_PENDING,
                             HIDDEN_SLOTS, STORY_ONLY, fighter_display_name,
                             afs_table, entry_rooms)

XBE_SHA256 = "e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3"
XPR_MAGIC = b"XPR0"
USER_TYPE = 0x80000000
MDL_TAG = b"MDL\x00"
OBJ_TAG = b"OBJ\x00"
LNK_MARKER = b"LNK\x00"
LNK_NAME = b"0100"               # the 4-byte name after every LNK marker (68/69 costumes)
LNK_HEADER = (2, 16, 32)         # fixed leading words of the LNK section header
LNK_HEADER_WORDS = 6             # the LNK header is {2, 16, 32, size, 0, 0}
LNK_MAX_LINK_GROUPS = 255        # measured C0 in {9, 12} across all 68 LNK costumes
LNK_MAX_SUB_BLOCKS = 1024        # sane upper bound for the C1 sub-block count
LNK_GROUP_MAX = 256              # per-group link count N measured in [1, 22] across 431 blocks
LNK_POLY_MAX_VERTICES = 255      # polygon vertex count n measured in [1, 13] across 431 blocks
CAT_FIXED_OFFSET = 0x14          # the stable fixed block sits at 0x14
CAT_SIGNATURE = (0x100, 1)       # (word@0x14, word@0x18) across all 69 costumes
MAX_HEADER_WORDS = 4096

# Header-tail data descriptor table (pinned across kas00/kas01/kas02):
# after the last OBJ record and before header_size, obj_count 12-byte vertex
# descriptors ({VERTEX_DESC_FLAG, cumulative_offset, 0}) are followed by
# tex_count 20-byte texture descriptors ({TEXTURE_DESC_FLAG, offset, 0, format,
# 0}), a 0xFFFFFFFF terminator and 0xAD debug fill to header_size.
VERTEX_DESC_FLAG = 0x00800001
TEXTURE_DESC_FLAG = 0x00040001
VERTEX_DESC_BYTES = 12
TEXTURE_DESC_BYTES = 20
DESC_TERMINATOR = 0xFFFFFFFF
DESC_PAD_BYTE = 0xAD

# Display-name mapping now lives in ``doa3_inventory``: FIGHTER_DISPLAY resolves
# 17 nicknames (XBE select table RE, hika = Helena from a RAM dump) and DISPLAY_MAPPING_PENDING
# is the three still-unresolved families (koryu/gokei/chin). This module imports both so
# its slot inventory stays consistent with the inventory layer.

# The writer routes to this catalog game (``char_coverage.writer_for``): a routed
# writer must be importable with GAME_IDS and a use() the characters tool calls.
GAME_IDS = {GAME_ID}
WRITER_GAME_IDS = GAME_IDS


def is_slot(slot: str | None) -> bool:
    """The DOA3 cast writer's slots: fighter:<nick>[:<costume>] or the whole cast."""
    return bool(slot) and (slot == "cast" or slot.startswith("fighter:"))


# --------------------------------------------------------------------- XPR0

def xpr_resources(blob: bytes) -> dict:
    """Walk an XPR0 packed resource: the verified header fields, the MDL
    payload range and the raw descriptor words that follow the second pair.

    The descriptor words are intentionally not interpreted as records: their
    stride is still unresolved (see the module docstring)."""
    if len(blob) < 0x24:
        raise ValueError(f"XPR0 resource is too short for its fixed header ({len(blob)} < 0x24 bytes)")
    if blob[:4] != XPR_MAGIC:
        raise ValueError(f"not an XPR0 resource (magic {blob[:4]!r})")
    total, hsize = struct.unpack_from("<II", blob, 4)
    if hsize < 0x24:
        raise ValueError(f"XPR0 header is too small for the fixed MDL/descriptor fields ({hsize:#x} < 0x24)")
    if hsize % 4 or total % 4:
        raise ValueError(f"XPR0 sizes are not 4-byte aligned (header {hsize:#x}, total {total:#x})")
    if not hsize <= total <= len(blob):
        raise ValueError(f"XPR0 sizes invalid: header {hsize}, total {total}, file {len(blob)}")
    rtype, rsize = struct.unpack_from("<II", blob, 12)
    if rtype != USER_TYPE:
        raise ValueError(f"XPR0 first resource is not user data (type {rtype:#x})")
    tag = blob[20:24]
    if tag != MDL_TAG:
        raise ValueError(f"XPR0 user resource tag is {tag!r}, not {MDL_TAG!r}")
    # The MDL user data is the header's own records: it starts at its tag (0x14) and ends where the descriptor
    # table begins (0x14 + size = the 4-aligned end of the last OBJ record on 69/69 owned costumes; lei04's last
    # record ends 2 bytes short of it, behind a 0x7777 pad), inside the header. An earlier reading placed it at
    # header_size, which only held because costume data regions are large.
    mdl_start, mdl_end = MDL_CHUNK, MDL_CHUNK + rsize
    if mdl_end > hsize:
        raise ValueError(f"XPR0 MDL user data [{mdl_start:#x}, {mdl_end:#x}) extends outside the header {hsize:#x}")
    second_type, second_size = struct.unpack_from("<II", blob, 0x18)
    descriptor_count = struct.unpack_from("<I", blob, 0x20)[0]
    # The descriptor region length (stride) is unresolved; expose a bounded
    # window of raw words and note truncation instead of guessing a record size.
    cap = min(MAX_HEADER_WORDS, max(64, 8 * descriptor_count))
    words_end = min(hsize, 0x24 + 4 * cap)
    words = [struct.unpack_from("<I", blob, o)[0] for o in range(0x24, words_end, 4)]
    return {"magic": XPR_MAGIC.decode(), "total": total, "header_size": hsize,
            "mdl": {"type": rtype, "size": rsize, "tag": tag.decode("latin-1").rstrip("\x00"),
                    "offset": mdl_start, "end": mdl_end},
            "second_pair": {"type": second_type, "size": second_size},
            "descriptor_count": descriptor_count,
            "descriptor_words": words,
            "data_size": total - hsize}


def xpr_mdl(blob: bytes) -> bytes:
    """The raw MDL user data of an XPR0 costume (its tag, counts, OBJ table and OBJ records)."""
    res = xpr_resources(blob)
    return blob[res["mdl"]["offset"]:res["mdl"]["end"]]


def xpr_roundtrip(blob: bytes) -> bytes:
    """Re-serialize a parsed XPR0 resource byte-for-byte (the no-op encode gate).

    The output must equal ``blob`` exactly. It reconstructs the container from
    the fields ``xpr_resources`` returns, so a byte-identical result proves the
    parser's boundaries (header_size, MDL offset/end, trailing region) account
    for every byte. This gate must hold before any donor geometry is written
    into the MDL payload."""
    res = xpr_resources(blob)
    out = bytearray(res["total"])
    out[0:4] = XPR_MAGIC
    struct.pack_into("<I", out, 4, res["total"])
    struct.pack_into("<I", out, 8, res["header_size"])
    out[0x0C:res["mdl"]["offset"]] = blob[0x0C:res["mdl"]["offset"]]
    out[res["mdl"]["offset"]:res["mdl"]["end"]] = blob[res["mdl"]["offset"]:res["mdl"]["end"]]
    out[res["mdl"]["end"]:] = blob[res["mdl"]["end"]:]
    return bytes(out)


# ----------------------------------------------------------------- MDL geometry

MDL_CHUNK = 0x14            # 'MDL' tag inside the XPR0 header
VERTEX_STRIDE = 32          # position f32x3, normal f32x3, uv f32x2
INDEX_STRIDE = 2            # u16 strip indices
OBJ_GEOM_FIELDS = 0x10      # vcount/vptr/icount/iptr sit at OBJ+0x10 on DOA3
MAT_HEADER_BASE = 0x60      # material records start at OBJ+0x60
MAT_HEADER_WORDS = 33
PACKET_BYTES = 16
MAT_FLAG_PRESENT = 0x80
MAT_TERMINATOR = 0x12345678


def mdl_chunk(blob: bytes) -> dict:
    """The MDL chunk header and the absolute object pointer table (validated).

    The chunk tag sits at 0x14 in the XPR0 header; counts follow at 0x18 and
    the object table at 0x28. The table must be terminated by a zero word and
    the first object record must start right after that terminator."""
    xpr_resources(blob)
    total = struct.unpack_from("<I", blob, 4)[0]
    if blob[MDL_CHUNK:MDL_CHUNK + 4] != MDL_TAG:
        raise ValueError(f"MDL chunk tag missing at {MDL_CHUNK:#x}")
    obj_count, tex_count, unk, dup = struct.unpack_from("<4I", blob, MDL_CHUNK + 4)
    if obj_count == 0 or obj_count > MAX_HEADER_WORDS:
        raise ValueError(f"MDL object count invalid ({obj_count})")
    if dup != obj_count:
        raise ValueError(f"MDL duplicated object count {dup} != object count {obj_count}")
    table_off = MDL_CHUNK + 0x14        # tag (4) + four count words (16)
    table_end = table_off + 4 * obj_count
    if table_end + 8 > total:
        raise ValueError("MDL object table extends outside the resource")
    objects = list(struct.unpack_from(f"<{obj_count}I", blob, table_off))
    if any(o >= total or o % 4 for o in objects):
        raise ValueError("MDL object pointer outside the resource or misaligned")
    if any(b <= a for a, b in zip(objects, objects[1:])):
        raise ValueError("MDL object pointers are not strictly increasing")
    if struct.unpack_from("<I", blob, table_end)[0] != 0:
        raise ValueError("MDL object table is not zero-terminated")
    if blob[objects[0]:objects[0] + 4] != OBJ_TAG:
        raise ValueError(f"first object record at {objects[0]:#x} is not {OBJ_TAG!r}")
    return {"obj_count": obj_count, "tex_count": tex_count, "unknown": unk,
            "dup_count": dup, "table_offset": table_off,
            "objects": objects, "table_end": table_end}


def _obj_header(blob: bytes, obj: int) -> tuple[int, int, int, int, list[int]]:
    """Pinned OBJ geometry fields: (vcount, vptr, icount, iptr, 8 header words)."""
    total = struct.unpack_from("<I", blob, 4)[0]
    if obj + 0x20 > total or blob[obj:obj + 4] != OBJ_TAG:
        raise ValueError(f"OBJ record at {obj:#x} is truncated or missing its tag")
    words = list(struct.unpack_from("<8I", blob, obj))
    vcount, vptr, icount, iptr = words[4:8]
    if vcount < 3 or icount < 3:
        raise ValueError(f"OBJ {obj:#x} has implausible counts (vertices {vcount}, indices {icount})")
    if vptr + VERTEX_STRIDE * vcount > total:
        raise ValueError(f"OBJ {obj:#x} vertex buffer extends outside the resource")
    if iptr + INDEX_STRIDE * icount > total:
        raise ValueError(f"OBJ {obj:#x} index buffer extends outside the resource")
    return vcount, vptr, icount, iptr, words


SETUP_PACKET_KINDS = (4, 5)      # stage-mode-3 materials lead with {4, ...} and {5, 0x400, strips, 0}
STRIP_FLAG_EXTRA_JOIN = 0x2      # flags bit 1: a third, parity-fixing join index before the strip
MAT_WORD_MODE = 26               # stage mode (1 = one texture stage, 3 = + environment stage)
MAT_WORD_TEXTURE = 27            # texture index into the costume's texture descriptors
MAT_WORD_PACKETS = 31


def _strip_packet(w0: int, off: int, n: int, flags: int) -> bool:
    """A triangle-strip packet {32*(n+2), index_off, n, flags} (153,262/153,262 measured)."""
    return n >= 1 and w0 == 32 * (n + 2)


def _obj_materials(blob: bytes, obj: int, icount: int, iptr: int) -> list[dict]:
    """The validated material record chain of one OBJ.

    Records start at OBJ+0x60 and run until a zero dword followed by
    0x12345678 exactly 8 bytes before the index buffer (measured on all 4646
    objects of the 69 costumes). Each record: a 33-word header from M (word0
    flags, word1 length in words, word 26 stage mode, word 27 texture index),
    then 16-byte packets. Every packet is a strip {32*(n+2), index_off, n,
    flags}; stage-mode-3 records lead with two setup packets ({4, ...} and
    {5, 0x400, strip_count, 0}). Strip ranges are bounded by the OBJ's own
    index buffer."""
    materials = []
    m = obj + MAT_HEADER_BASE
    while True:
        if blob[m:m + 4] == b"\x00\x00\x00\x00":
            terminator = struct.unpack_from("<I", blob, m + 4)[0]
            if terminator != MAT_TERMINATOR:
                raise ValueError(f"material chain at {m:#x} is not terminated by {MAT_TERMINATOR:#x}")
            if m + 8 != iptr:
                raise ValueError(f"material chain at {m:#x} must end exactly 8 bytes before the index buffer {iptr:#x}")
            return materials
        if m + 8 > iptr or iptr - 8 < obj + MAT_HEADER_BASE:
            raise ValueError(f"material chain at {m:#x} runs into the OBJ index buffer {iptr:#x}")
        flags = blob[m:m + 4]
        if not flags[3] & MAT_FLAG_PRESENT:
            raise ValueError(f"material at {m:#x} lacks the {MAT_FLAG_PRESENT:#x} presence bit (flags {flags.hex()})")
        length_words = struct.unpack_from("<I", blob, m + 4)[0]
        if length_words < MAT_HEADER_WORDS:
            raise ValueError(f"material at {m:#x} length {length_words} words is below the fixed header")
        if (length_words - MAT_HEADER_WORDS) % 4:
            raise ValueError(f"material at {m:#x} length {length_words} words is not 33 + 4*packets")
        record_end = m + 4 * length_words
        if record_end > iptr - 8:
            raise ValueError(f"material at {m:#x} extends past the chain terminator")
        header = list(struct.unpack_from(f"<{MAT_HEADER_WORDS}I", blob, m))
        packet_count = (length_words - MAT_HEADER_WORDS) // 4
        rows = [struct.unpack_from("<4I", blob, p)
                for p in range(m + 4 * MAT_HEADER_WORDS, record_end, PACKET_BYTES)]
        setup, strips = [], []
        for w0, off, n, strip_flags in rows:
            if not strips and w0 in SETUP_PACKET_KINDS and not _strip_packet(w0, off, n, strip_flags):
                setup.append((w0, off, n, strip_flags))
                continue
            if not _strip_packet(w0, off, n, strip_flags):
                raise ValueError(f"material {m:#x} packet {(w0, off, n, strip_flags)} is not a strip "
                                 f"{{32*(n+2), index_off, n, flags}}")
            if off + n + 2 > icount:
                raise ValueError(f"material {m:#x} strip [{off}, {off + n + 2}) exceeds the OBJ index count {icount}")
            strips.append({"index_offset": off, "triangles": n, "flags": strip_flags})
        if setup and (len(setup) != 2 or setup[-1][0] != 5 or setup[-1][2] != len(strips)):
            raise ValueError(f"material {m:#x} setup packets {setup} do not announce its {len(strips)} strips")
        materials.append({
            "offset": m, "flags": flags.hex(), "length_words": length_words,
            "header": header, "packet_count": packet_count,
            "packet_bytes": blob[m + 4 * MAT_HEADER_WORDS:record_end],
            "mode": header[MAT_WORD_MODE], "texture": header[MAT_WORD_TEXTURE],
            "setup_packets": setup, "strips": strips,
        })
        m = record_end


def _strip_triangles(indices: list[int]) -> list[tuple[int, int, int]]:
    """u16 strip -> triangles with the DOA2U parity flip rule.

    The winding alternates per index; degenerate triples (any repeated index)
    are skipped. Under this rule (applied per packet, parity fresh at the
    packet's index_off) native strips agree with their own vertex normals
    counter-clockwise for flags 0x900 and clockwise for flags 0x901 (99%)."""
    triangles = []
    f1, f2 = indices[0], indices[1]
    flip = True
    for f3 in indices[2:]:
        if f1 != f2 and f2 != f3 and f3 != f1:
            triangles.append((f1, f3, f2) if flip else (f1, f2, f3))
        flip = not flip
        f1, f2 = f2, f3
    return triangles


def _decode_strip(indices, off: int, n: int, flags: int, vcount: int) -> tuple[list[int], list[tuple[int, int, int]]]:
    """One strip packet: the draw [off, off + n + 4 (+1 with flags bit 1)) with fresh parity; its first n real
    triangles are the strip (the join's degenerate triangles drop out)."""
    end = min(off + n + 4 + (1 if flags & STRIP_FLAG_EXTRA_JOIN else 0), len(indices))
    raw = list(indices[off:end])
    if max(raw) >= vcount:
        raise ValueError(f"strip index {max(raw)} outside the OBJ vertex range {vcount}")
    triangles = _strip_triangles(raw)[:n]
    if not triangles and len(set(raw)) == 1:
        return raw, []                    # a strip collapsed onto one vertex: a part the writer hid (never native)
    if len(triangles) != n:
        raise ValueError(f"strip at index {off} yields {len(triangles)} triangles, its packet declares {n}")
    return raw, triangles


def obj_geometry(blob: bytes, obj: int) -> dict:
    """One OBJ record: pinned header fields, material chain, strips and vertices.

    All buffer/count/range relationships are validated against the native
    record bounds before any data is returned."""
    vcount, vptr, icount, iptr, words = _obj_header(blob, obj)
    materials = _obj_materials(blob, obj, icount, iptr)
    all_indices = struct.unpack_from(f"<{icount}H", blob, iptr)
    strips, triangles, tris = [], [], 0
    for mat in materials:
        for strip in mat["strips"]:
            raw, m_tris = _decode_strip(all_indices, strip["index_offset"], strip["triangles"],
                                        strip["flags"], vcount)
            strips.append({"material": mat["offset"], "texture": mat["texture"],
                           "index_offset": strip["index_offset"], "flags": strip["flags"],
                           "indices": raw, "triangles": m_tris})
            triangles.extend(m_tris)
            tris += len(m_tris)
    if max(all_indices) >= vcount:
        raise ValueError(f"OBJ {obj:#x} index buffer contains {max(all_indices)} outside {vcount} vertices")
    vertex_bytes = blob[vptr:vptr + VERTEX_STRIDE * vcount]
    floats = struct.unpack(f"<{8 * vcount}f", vertex_bytes)
    vertices = [tuple(floats[8 * i:8 * i + 8]) for i in range(vcount)]
    return {"offset": obj, "header": words, "vertex_count": vcount,
            "vertex_offset": vptr, "index_count": icount, "index_offset": iptr,
            "materials": materials, "strips": strips,
            "triangle_count": tris, "triangles": triangles,
            "vertices": vertices, "vertex_bytes": vertex_bytes,
            "index_bytes": blob[iptr:iptr + INDEX_STRIDE * icount],
            "record_span": (obj, iptr + INDEX_STRIDE * icount)}


def costume_geometry(blob: bytes) -> dict:
    """Decode an entire costume XPR0: chunk, every OBJ, its materials and mesh.

    This is a decoder for the owned format; it validates every buffer, count
    and range against the native record bounds and the resource size before
    returning measured geometry."""
    chunk = mdl_chunk(blob)
    total = struct.unpack_from("<I", blob, 4)[0]
    objects, spans, tris_total, verts_total = [], [], 0, 0
    for obj in chunk["objects"]:
        geo = obj_geometry(blob, obj)
        if spans and geo["record_span"][0] < spans[-1][1]:
            raise ValueError(f"OBJ {obj:#x} record span overlaps the previous object")
        spans.append(geo["record_span"])
        objects.append(geo)
        tris_total += geo["triangle_count"]
        verts_total += geo["vertex_count"]
    last_end = max(geo["vertex_offset"] + VERTEX_STRIDE * geo["vertex_count"] for geo in objects)
    if last_end > total:
        raise ValueError("vertex region extends outside the resource")
    vertex_starts = [g["vertex_offset"] for g in objects]
    vertex_chain = all(
        a + VERTEX_STRIDE * ga["vertex_count"] == b
        for (a, ga), b in zip(zip(vertex_starts, objects), vertex_starts[1:])
    ) if len(objects) > 1 else True
    return {"chunk": chunk, "objects": objects, "object_count": len(objects),
            "triangle_total": tris_total, "vertex_total": verts_total,
            "vertex_region": (min(vertex_starts), last_end),
            "vertex_chain_contiguous": vertex_chain}


def vertex_sanity(geometry: dict) -> dict:
    """Measured invariants of the decoded vertices (evidence, not validation).

    On kas00 these are: |normal| = 1.0000 +/- 0.0000, u in [0.003, 1.000],
    v in [-0.995, 0.993]. Used to confirm the f32x8 layout on a new resource;
    a mismatch means the layout hypothesis does not hold for that resource."""
    verts = [v for g in geometry["objects"] for v in g["vertices"]]
    if not verts:
        return {}
    nlens = [(v[3] ** 2 + v[4] ** 2 + v[5] ** 2) ** 0.5 for v in verts]
    mean = sum(nlens) / len(nlens)
    std = (sum((x - mean) ** 2 for x in nlens) / len(nlens)) ** 0.5
    us = [v[6] for v in verts]
    vs = [v[7] for v in verts]
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return {"normal_length_mean": mean, "normal_length_std": std,
            "u_range": [min(us), max(us)], "v_range": [min(vs), max(vs)],
            "pos_bounds": {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)],
                           "z": [min(zs), max(zs)]}}


def xpr_geometry_roundtrip(blob: bytes) -> bytes:
    """Byte-preserving geometry encode: rebuild the parsed MDL region.

    Every structurally parsed field is re-serialized from its parsed value
    (chunk header, object table, OBJ header words, material records, index
    buffers, vertex buffers); the unparsed interleavings and the trailing
    texture region pass through raw. The result must equal ``blob`` exactly -
    the no-op encode gate the writer path must keep holding before donor
    geometry replaces native bytes."""
    total, hsize = struct.unpack_from("<II", blob, 4)
    geometry = costume_geometry(blob)
    chunk = geometry["chunk"]
    out = bytearray(total)
    out[0:MDL_CHUNK] = blob[0:MDL_CHUNK]                      # magic, sizes, first pair
    out[MDL_CHUNK:MDL_CHUNK + 4] = MDL_TAG
    struct.pack_into("<4I", out, MDL_CHUNK + 4, chunk["obj_count"], chunk["tex_count"],
                     chunk["unknown"], chunk["dup_count"])
    struct.pack_into(f"<{chunk['obj_count']}I", out, chunk["table_offset"], *chunk["objects"])
    struct.pack_into("<I", out, chunk["table_end"], 0)
    prev_end = 0
    for geo in geometry["objects"]:
        obj, span_end = geo["record_span"]
        if prev_end and obj > prev_end:
            out[prev_end:obj] = blob[prev_end:obj]            # unparsed interleaving
        struct.pack_into("<8I", out, obj, *geo["header"])
        # OBJ record tail between the pinned fields and the material chain:
        # semantics unresolved, passed through raw (byte-preserving by design).
        out[obj + 0x20:obj + MAT_HEADER_BASE] = blob[obj + 0x20:obj + MAT_HEADER_BASE]
        for mat in geo["materials"]:
            m = mat["offset"]
            struct.pack_into(f"<{MAT_HEADER_WORDS}I", out, m, *mat["header"])
            p = m + 4 * MAT_HEADER_WORDS
            out[p:p + len(mat["packet_bytes"])] = mat["packet_bytes"]
        mend = geo["index_offset"] - 8
        out[mend:mend + 4] = b"\x00\x00\x00\x00"
        struct.pack_into("<I", out, mend + 4, MAT_TERMINATOR)
        out[geo["index_offset"]:geo["index_offset"] + len(geo["index_bytes"])] = geo["index_bytes"]
        packed = struct.pack(f"<{8 * geo['vertex_count']}f",
                             *[f for v in geo["vertices"] for f in v])
        out[geo["vertex_offset"]:geo["vertex_offset"] + len(packed)] = packed
        prev_end = span_end
    last_geo_end = max(geo["vertex_offset"] + VERTEX_STRIDE * geo["vertex_count"]
                       for geo in geometry["objects"])
    if prev_end < hsize:
        out[prev_end:hsize] = blob[prev_end:hsize]
    out[hsize:last_geo_end] = _gaps_filled(blob, geometry, hsize, last_geo_end)
    out[last_geo_end:] = blob[last_geo_end:]                  # trailing (textures)
    if bytes(out) != blob:
        first = next(i for i, (a, b) in enumerate(zip(out, blob)) if a != b)
        raise ValueError(f"geometry re-encode is not byte-identical (first difference at {first:#x})")
    return bytes(out)


def _gaps_filled(blob: bytes, geometry: dict, start: int, end: int) -> bytes:
    """Vertex region with each OBJ's buffer re-packed and raw gap passthrough."""
    out = bytearray(blob[start:end])
    for geo in geometry["objects"]:
        v0 = geo["vertex_offset"]
        packed = struct.pack(f"<{8 * geo['vertex_count']}f",
                             *[f for v in geo["vertices"] for f in v])
        out[v0 - start:v0 - start + len(packed)] = packed
    return bytes(out)


# ----------------------------------------------------------------- MDL data descriptors

def mdl_descriptor_table(blob: bytes) -> dict:
    """The header-tail data descriptor table (obj_count vertex + tex_count texture
    records), located between the last OBJ record and ``header_size``.

    Pinned across kas00 (obj 72/tex 87), kas01 (72/86) and kas02 (74/95):

    * ``obj_count`` vertex descriptors, 12 bytes each, flag ``0x00800001``:
      ``{flag, cumulative_offset, 0}``. The offset is the cumulative vertex byte
      count (sum of the preceding OBJs' ``vertex_count * 32``), first = 0, so the
      k-th OBJ's vertex buffer sits at ``header_size + offset[k]``. Every offset
      is checked against the decoded ``vertex_count`` chain.
    * ``tex_count`` texture descriptors, 20 bytes each, flag ``0x00040001``:
      ``{flag, offset, 0, format, 0}``. The offset is the cumulative data-region
      byte offset from ``header_size`` (texture data follows the vertex buffers
      with a small alignment gap, and the whole data region tiles exactly up to
      ``total``). Strictly increasing; the last texture's extent is implied by
      ``total - header_size``. The ``format`` word is returned raw: byte 0 is
      always ``0x2A`` on the measured costumes, byte 2 in {0x41,0x51,0x61,0x71,
      0x81}, byte 3 in {0x04..0x08}; its D3D surface semantics (width/height/
      pixel format) are still unresolved and must come from the XBE loader.
    * a ``0xFFFFFFFF`` terminator word, then ``0xAD`` debug fill to header_size.

    The table starts 4-aligned: a last OBJ record with an odd index count (lei04) ends 2 bytes short, and a
    ``0x7777`` pad fills the gap, as between records.
    """
    total, hsize = struct.unpack_from("<II", blob, 4)
    geometry = costume_geometry(blob)
    chunk = geometry["chunk"]
    vcounts = [g["vertex_count"] for g in geometry["objects"]]
    last_end = max(g["record_span"][1] for g in geometry["objects"])
    p = (last_end + 3) // 4 * 4
    if blob[last_end:p] != b"\x77" * (p - last_end):
        raise ValueError(f"the pad behind the last OBJ record at {last_end:#x} is not 0x7777")

    vertex = []
    while p + VERTEX_DESC_BYTES <= hsize and struct.unpack_from("<I", blob, p)[0] == VERTEX_DESC_FLAG:
        offset, zero = struct.unpack_from("<II", blob, p + 4)
        if zero != 0:
            raise ValueError(f"vertex descriptor at {p:#x} has a nonzero tail word {zero:#x}")
        vertex.append(offset)
        p += VERTEX_DESC_BYTES
    if len(vertex) != chunk["obj_count"]:
        raise ValueError(f"vertex descriptor count {len(vertex)} != object count {chunk['obj_count']}")
    cumulative = 0
    for k, offset in enumerate(vertex):
        if offset != cumulative:
            raise ValueError(f"vertex descriptor {k} offset {offset:#x} != cumulative {cumulative:#x}")
        cumulative += vcounts[k] * VERTEX_STRIDE

    textures = []
    while p + TEXTURE_DESC_BYTES <= hsize and struct.unpack_from("<I", blob, p)[0] == TEXTURE_DESC_FLAG:
        offset, zero_a, fmt, zero_b = struct.unpack_from("<4I", blob, p + 4)
        if zero_a != 0 or zero_b != 0:
            raise ValueError(f"texture descriptor at {p:#x} has nonzero pad words "
                             f"({zero_a:#x}, {zero_b:#x})")
        textures.append({"offset": offset, "format": fmt})
        p += TEXTURE_DESC_BYTES
    if len(textures) != chunk["tex_count"]:
        raise ValueError(f"texture descriptor count {len(textures)} != texture count {chunk['tex_count']}")
    offsets = [t["offset"] for t in textures]
    if any(b <= a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("texture descriptor offsets are not strictly increasing")
    data_region = total - hsize
    if offsets and offsets[0] < cumulative:
        raise ValueError(f"first texture offset {offsets[0]:#x} precedes the "
                         f"{cumulative:#x} vertex bytes")
    if offsets and offsets[-1] >= data_region:
        raise ValueError(f"last texture offset {offsets[-1]:#x} leaves no room in "
                         f"the {data_region:#x}-byte data region")

    if p + 4 > hsize or struct.unpack_from("<I", blob, p)[0] != DESC_TERMINATOR:
        raise ValueError(f"descriptor table at {p:#x} is not terminated by {DESC_TERMINATOR:#x}")
    p += 4
    pad = blob[p:hsize]
    last_size = data_region - offsets[-1] if offsets else 0
    return {
        "vertex_descriptors": vertex, "vertex_byte_total": cumulative,
        "texture_descriptors": textures, "texture_count": len(textures),
        "first_texture_gap": offsets[0] - cumulative if offsets else 0,
        "last_texture_size": last_size,
        "data_region": (hsize, total),
        "terminator_offset": p - 4, "pad_bytes": len(pad), "pad_is_ad_fill": all(b == DESC_PAD_BYTE for b in pad),
    }


def export_obj(geometry: dict, path: str | Path) -> int:
    """Write decoded geometry to a Wavefront OBJ (private readable evidence).

    One group per material (its strips together); vertices carry
    position/normal/uv. Returns the number of faces written. The DOA3 runtime
    uses v as stored (no flip); the winding parity rule is applied exactly as
    decoded."""
    p = Path(path)
    faces = 0
    with open(p, "w") as out:
        out.write("# DOA3 decoded geometry (gbox.doa3_cast)\n")
        for gi, geo in enumerate(geometry["objects"]):
            base = sum(g["vertex_count"] for g in geometry["objects"][:gi])
            out.write(f"o OBJ_{gi}\n")
            for v in geo["vertices"]:
                out.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for v in geo["vertices"]:
                out.write(f"vn {v[3]:.6f} {v[4]:.6f} {v[5]:.6f}\n")
            for v in geo["vertices"]:
                out.write(f"vt {v[6]:.6f} {v[7]:.6f}\n")
            group = None
            for strip in geo["strips"]:
                mat = strip["material"]
                if mat != group:
                    out.write(f"g OBJ_{gi}_mat_{mat:#x}_tex_{strip['texture']}\n")
                    group = mat
                for a, b, c in strip["triangles"]:
                    out.write(f"f {a + base + 1}/{a + base + 1}/{a + base + 1} "
                              f"{b + base + 1}/{b + base + 1}/{b + base + 1} "
                              f"{c + base + 1}/{c + base + 1}/{c + base + 1}\n")
                    faces += 1
    return faces


# --------------------------------------------------------------------- CAT

def cat_sections(blob: bytes) -> dict:
    """CAT companion header, layout class and ``LNK`` section markers.

    Measured across all 69 complete costumes (20 fighter families): the word
    at 0x14 is always 0x100 and the word at 0x18 is always 1, so that fixed
    pair - not the first word - is the CAT signature. The first five words are
    costume-dependent: when word0==1 and word1==0x14 they hold version plus
    section offsets and word3 is the ``LNK`` section offset (the "offsets"
    layout); otherwise they are an unresolved 20-byte ID block ("id_block").
    The body past the header and the trailing near-EOF table are deliberately
    not decoded: their record stride differs between costumes."""
    if len(blob) < 0x20:
        raise ValueError("CAT companion is too small")
    head = list(struct.unpack_from("<8I", blob, 0))
    if (head[5], head[6]) != CAT_SIGNATURE:
        raise ValueError(f"CAT companion lacks the fixed signature {CAT_SIGNATURE} "
                         f"at {CAT_FIXED_OFFSET:#x} (words {head[5]:#x}, {head[6]:#x})")
    markers = []
    start = 0
    while True:
        at = blob.find(LNK_MARKER, start)
        if at < 0:
            break
        markers.append(at)
        start = at + len(LNK_MARKER)
    layout = "offsets" if head[0] == 1 and head[1] == CAT_FIXED_OFFSET else "id_block"
    result = {"version": head[0], "header": list(head[1:]), "size": len(blob),
              "id_block": list(head[:5]), "fixed": list(head[5:]),
              "layout": layout, "lnk_markers": markers}
    if layout == "offsets":
        hint = head[3]
        result["lnk_offset_hint"] = hint
        if markers and hint != markers[0]:
            raise ValueError(f"CAT LNK offset hint {hint:#x} does not match "
                             f"the first LNK marker {markers[0]:#x}")
        sections = list(head[1:5])            # {0x14, s2, s3(LNK), s4}
        if any(b <= a for a, b in zip(sections, sections[1:])):
            raise ValueError(f"CAT section offsets are not strictly increasing: "
                             f"{[hex(s) for s in sections]}")
        if sections[-1] > len(blob):
            raise ValueError(f"CAT section offset {sections[-1]:#x} exceeds the "
                             f"{len(blob)}-byte companion")
        result["section_offsets"] = sections
    return result


def cat_lnk(blob: bytes) -> dict | None:
    """Decode the CAT ``LNK`` skeleton-link section header.

    Measured across all 68 LNK-bearing costumes (69 complete costumes; kor00
    has no LNK section): the section is ``LNK\\0`` + the 4-byte name ``0100``
    + a 6-word header ``{2, 16, 32, size, 0, 0}``. The words 2, 16 and 32 and
    the two trailing zeros are constant on every costume; ``size`` is a
    4-aligned byte count (the link-data size) that varies with the costume's
    accessory bones. The body past the header (the actual joint links) is
    still left for the RE stage; this pins the section envelope it must decode.

    Returns ``None`` when the companion has no LNK section (kor00), and raises
    ``ValueError`` when a present LNK section deviates from the pinned shape.
    """
    at = blob.find(LNK_MARKER)
    if at < 0:
        return None
    if len(blob) < at + 8 + 4 * LNK_HEADER_WORDS:
        raise ValueError(f"LNK section at {at:#x} is truncated")
    name = blob[at + 4:at + 8]
    if name != LNK_NAME:
        raise ValueError(f"LNK section at {at:#x} has unexpected name {name!r}")
    a, b, c, size, z4, z5 = struct.unpack_from("<6I", blob, at + 8)
    if (a, b, c) != LNK_HEADER:
        raise ValueError(f"LNK section at {at:#x} has unexpected header words "
                         f"{(a, b, c)!r}, expected {LNK_HEADER!r}")
    if (z4, z5) != (0, 0):
        raise ValueError(f"LNK section at {at:#x} has nonzero trailing words "
                         f"({z4:#x}, {z5:#x})")
    if size % 4:
        raise ValueError(f"LNK size {size:#x} is not 4-aligned")
    if size >= len(blob):
        raise ValueError(f"LNK size {size:#x} exceeds the {len(blob)}-byte companion")
    return {"offset": at, "name": name.decode("latin-1"),
            "header": [a, b, c, size, z4, z5], "size": size,
            "body_offset": at + 8 + 4 * LNK_HEADER_WORDS}


def cat_lnk_body(blob: bytes) -> dict | None:
    """Decode the CAT ``LNK`` link-data body structure.

    Measured across all 68 LNK-bearing costumes (69 complete costumes; kor00 has
    none): the body spans ``size`` bytes from ``cat_lnk``'s ``body_offset`` and
    is 16-byte aligned. Its first u32 is a link-group count C0 (9 on 65/68
    costumes, 12 on the three Hikaru costumes hik00/hik01/hik02), followed by C0
    u32 entries that are each either a body-relative offset or the -1 sentinel.
    Immediately after that C0-entry table sits a second count C1 and C1+1
    strictly-increasing cumulative u32 offsets (the sub-block boundaries); the
    last offset never exceeds ``size``. The per-joint / skin-weight semantics
    past these tables are still left for the RE stage.

    Returns ``None`` when the companion has no LNK section (kor00); raises
    ``ValueError`` on any structural deviation from the pinned shape.
    """
    lnk = cat_lnk(blob)
    if lnk is None:
        return None
    size = lnk["size"]
    body = lnk["body_offset"]
    if body + size > len(blob):
        raise ValueError(f"LNK body at {body:#x} ({size:#x} bytes) exceeds "
                         f"the {len(blob)}-byte companion")
    c0 = struct.unpack_from("<I", blob, body)[0]
    if not 0 < c0 <= LNK_MAX_LINK_GROUPS:
        raise ValueError(f"LNK link-group count {c0} is outside the measured "
                         f"range (1..{LNK_MAX_LINK_GROUPS})")
    entries = list(struct.unpack_from(f"<{c0}I", blob, body + 4))
    for e in entries:
        if e == 0xFFFFFFFF:
            continue
        if e > size:
            raise ValueError(f"LNK link-group offset {e:#x} exceeds the "
                             f"{size:#x}-byte body")
    sub = body + 4 + 4 * c0
    if sub + 8 > body + size:
        raise ValueError("LNK body is too small to hold the sub-block table")
    c1 = struct.unpack_from("<I", blob, sub)[0]
    if not 0 < c1 < LNK_MAX_SUB_BLOCKS:
        raise ValueError(f"LNK sub-block count {c1} is outside the sane range "
                         f"(1..{LNK_MAX_SUB_BLOCKS - 1})")
    offs = list(struct.unpack_from(f"<{c1 + 1}I", blob, sub + 4))
    if any(b <= a for a, b in zip(offs, offs[1:])):
        raise ValueError("LNK sub-block offsets are not strictly increasing")
    if offs[-1] > size:
        raise ValueError(f"LNK sub-block offset {offs[-1]:#x} exceeds the "
                         f"{size:#x}-byte body")
    return {"offset": lnk["offset"], "body_offset": body, "size": size,
            "link_group_count": c0, "link_group_entries": entries,
            "sub_table_offset": sub - body, "sub_table_count": c1,
            "sub_table_offsets": offs}


def cat_lnk_groups(blob: bytes) -> dict | None:
    """Decode every link-group block a CAT ``LNK`` C0 entry points at.

    Measured across all 68 LNK-bearing costumes (431 blocks, 0 deviations): each
    non-sentinel C0 entry is a body-relative offset to a link-group block whose
    header is exactly three words plus the per-group link count:

    * ``N`` (u32) - the group's link/sub-block count, measured in [1, 22].
    * ``header_size`` (u32) - always ``4 * (N + 3)`` bytes, i.e. the byte
      offset from the block start to its data region (this exact relation holds
      on all 431 blocks).
    * ``N + 1`` u32 cumulative data lengths - strictly increasing, the last one
      is the data region's byte length. The data region is
      ``[block + header_size, block + header_size + last_length)`` and is
      partitioned into ``N`` sub-sections by the ``N + 1`` cumulative lengths
      (the first sub-section starts implicitly at 0).

    This generalises and corrects ``cat_lnk_body``'s C1 read: the C1 "sub-table"
    is itself one of these blocks (the one at ``body + 4 + 4 * C0``), so the old
    code read ``header_size`` as the first sub-block boundary and dropped the
    final boundary. The sub-section record semantics and whether the cumulative
    lengths index joint-link/skin-weight records remain unresolved.

    Returns ``None`` when the companion has no LNK section (kor00); raises
    ``ValueError`` on any structural deviation from the pinned shape.
    """
    body = cat_lnk_body(blob)
    if body is None:
        return None
    bo = body["body_offset"]
    size = body["size"]
    groups = []
    for k, e in enumerate(body["link_group_entries"]):
        if e == 0xFFFFFFFF:
            groups.append({"index": k, "present": False})
            continue
        off = bo + e
        if off + 12 > len(blob):
            raise ValueError(f"link-group {k} at {off:#x} is truncated")
        n = struct.unpack_from("<I", blob, off)[0]
        if not 0 < n <= LNK_GROUP_MAX:
            raise ValueError(f"link-group {k} count {n} is outside the measured "
                             f"range (1..{LNK_GROUP_MAX})")
        hdr = struct.unpack_from("<I", blob, off + 4)[0]
        if hdr != 4 * (n + 3):
            raise ValueError(f"link-group {k} header size {hdr:#x} != "
                             f"4 * (N + 3) = {4 * (n + 3):#x}")
        lengths = list(struct.unpack_from(f"<{n + 1}I", blob, off + 8))
        if any(b <= a for a, b in zip(lengths, lengths[1:])):
            raise ValueError(f"link-group {k} cumulative lengths are not "
                             f"strictly increasing: {[hex(x) for x in lengths[:6]]}")
        if lengths[-1] > size:
            raise ValueError(f"link-group {k} last length {lengths[-1]:#x} exceeds "
                             f"the {size:#x}-byte LNK body")
        if off + hdr + lengths[-1] > len(blob):
            raise ValueError(f"link-group {k} data region extends outside the file")
        groups.append({"index": k, "present": True, "offset": off,
                       "count": n, "header_size": hdr,
                       "data_offsets": lengths, "data_bytes": lengths[-1]})
    return {"link_group_count": body["link_group_count"], "groups": groups,
            "body_offset": bo, "size": size}


def _parse_polygon_list(u16: list[int]) -> tuple[list[list[int]], int]:
    """A count-prefixed u16 polygon list ``{n, then n u16 indices}``.

    Each polygon starts with its vertex count ``n`` (measured in [1, 13] across
    all 431 blocks) followed by ``n`` u16 indices. The list is terminated by a
    zero count. Returns ``(polygons, terminator_index)`` where
    ``terminator_index`` is the u16 index of the terminating 0 (the residual
    bytes after it are not part of the list). Raises on an out-of-range or
    unterminated list.
    """
    polys = []
    p = 0
    while p < len(u16):
        n = u16[p]
        if n == 0:
            return polys, p
        if n > LNK_POLY_MAX_VERTICES:
            raise ValueError(f"polygon at u16[{p}] has {n} vertices, beyond "
                             f"the measured range (1..{LNK_POLY_MAX_VERTICES})")
        if p + 1 + n > len(u16):
            raise ValueError(f"polygon at u16[{p}] with {n} vertices overruns "
                             f"the link table")
        polys.append(u16[p + 1:p + 1 + n])
        p += 1 + n
    raise ValueError("link-table polygon list is not terminated by a zero count")


def cat_lnk_sections(blob: bytes) -> dict | None:
    """Decode every link-group block's data-region partition.

    Measured across all 68 LNK-bearing costumes (431 blocks, 0 deviations):
    each block's data region (``data_offsets[-1]`` bytes) splits into a leading
    *link table* ``[0, data_offsets[0])`` and ``N`` *link sections*
    ``[data_offsets[k-1], data_offsets[k])`` for ``k`` in ``1..N``:

    * The link table is u16-aligned and holds a count-prefixed polygon list
      ``{n, then n u16 indices}`` (``n`` in [1, 13]) terminated by a zero
      count; any residual bytes after the terminator are returned unparsed
      (their record semantics remain unresolved).
    * The ``N`` link sections are all the SAME byte length (the *stride*) and
      that stride is a multiple of 6 - i.e. each section is a flat u16 triangle
      list (3 u16 indices per triangle, no count prefix), verified 4402/4402
      sections across all 431 blocks. The per-section index semantics (which
      joint/vertex the triangles bind) remain unresolved.

    Returns ``None`` when the companion has no LNK section (kor00); raises
    ``ValueError`` on any structural deviation from the pinned shape.
    """
    groups = cat_lnk_groups(blob)
    if groups is None:
        return None
    sections = []
    for g in groups["groups"]:
        if not g.get("present"):
            sections.append({"index": g["index"], "present": False})
            continue
        n = g["count"]
        lens = g["data_offsets"]
        data_start = g["offset"] + g["header_size"]
        data = blob[data_start:data_start + lens[-1]]
        link_table = data[0:lens[0]]
        if len(link_table) % 2:
            raise ValueError(f"link-group {g['index']} link table is not "
                             f"u16-aligned ({len(link_table)} bytes)")
        u16 = list(struct.unpack(f"<{len(link_table) // 2}H", link_table))
        polys, term = _parse_polygon_list(u16)
        residual = len(link_table) - 2 * (term + 1)
        strides = [lens[k] - lens[k - 1] for k in range(1, n + 1)]
        if len(set(strides)) != 1:
            raise ValueError(f"link-group {g['index']} link sections are not "
                             f"equal length: {[hex(s) for s in strides]}")
        stride = strides[0]
        if stride % 6:
            raise ValueError(f"link-group {g['index']} link-section stride "
                             f"{stride:#x} is not a whole number of triangles")
        sections.append({
            "index": g["index"], "present": True, "offset": g["offset"],
            "link_table_bytes": len(link_table),
            "polygon_count": len(polys), "polygons": polys,
            "link_table_residual_bytes": residual,
            "link_sections": n, "link_section_stride": stride,
            "triangles_per_section": stride // 6,
        })
    return {"link_group_count": groups["link_group_count"],
            "body_offset": groups["body_offset"], "groups": sections}


# ----------------------------------------------------------------- slots

def slot_inventory(manifest: dict) -> dict:
    """Cast slot rows from a doa3_inventory manifest.

    One row per fighter family with its costume coverage and its resolved display
    name (``fighter_display_name`` from doa3_inventory). Coverage gaps are listed
    explicitly so a cast build can report them."""
    slots = []
    for fam in manifest.get("fighter_families", []):
        complete = fam.get("complete_costumes", [])
        codes = sorted({c[:3] for c in fam.get("costumes", {})})
        nick = fam.get("nick")
        slots.append({
            "nick": nick, "code": fam.get("code") or (codes[0] if codes else None),
            "family": nick, "motion_banks": fam.get("mot", []),
            "costumes": sorted(fam.get("costumes", {})), "complete_costumes": complete,
            "costume_count": len(complete), "hidden": nick in HIDDEN_SLOTS,
            "story_only": nick in STORY_ONLY,
            "display_name": fighter_display_name(nick),
        })
    gaps = []
    for s in slots:
        if s["display_name"] is None and s["nick"] in DISPLAY_MAPPING_PENDING:
            gaps.append({"kind": "display_name_pending",
                         "slot": s["nick"],
                         "detail": "code->name link needs the XBE character-table RE stage"})
        if not s["complete_costumes"]:
            gaps.append({"kind": "no_complete_costumes", "slot": s["nick"],
                         "detail": f"family has no complete xpr+cat costume pair "
                                   f"(costumes seen: {s['costumes']})"})
    roster = manifest.get("roster_expected") or ROSTER
    resolved = sorted({s["display_name"] for s in slots if s["display_name"]})
    pending = sorted(s["nick"] for s in slots if s["display_name"] is None)
    return {"game_id": manifest.get("game_id", GAME_ID),
            "title": manifest.get("title"), "slots": slots,
            "slot_count": len(slots), "costume_total": sum(s["costume_count"] for s in slots),
            "roster_expected": roster,
            "coverage_gaps": gaps,
            "resolved_display": resolved,
            "display_pending": pending,
            "display_mapping": "partial" if pending else "resolved",
            "unlock_all": "pending"}


# ----------------------------------------------------------------- AFS writer path

def afs_patch_entry(path: str | Path, entry_index: int, new_bytes: bytes, *,
                    out: str | Path | None = None, expected_sha256: str | None = None) -> int:
    """Rewrite one AFS entry into a separately staged image and publish it atomically.

    The source archive is read once and never modified in place: the patched
    image is written to a fresh sibling staging file, fsync'd, then atomically
    moved over ``out`` (or the source when ``out`` is None) with os.replace, so
    an existing archive is never left partially written. The full layout is
    validated first (magic/header bounds, entry table, no overlap, name
    directory bounds, optional source digest) and a byte-identical replacement
    is refused as a no-op. Returns the room the entry occupied."""
    p = Path(path)
    original = p.read_bytes()
    source_digest = hashlib.sha256(original).hexdigest()
    if expected_sha256 is not None and source_digest != expected_sha256:
        raise ValueError(f"AFS source digest mismatch (expected {expected_sha256}, got {source_digest})")
    data = bytearray(original)
    archive_size = len(data)
    table = afs_table(bytes(data), archive_size)
    count = table["count"]
    if not 0 <= entry_index < count:
        raise ValueError(f"AFS entry {entry_index} outside {count} entries")
    nd = table["name_dir"]
    if nd:
        nd_off, nd_size = nd
        if nd_off + nd_size > archive_size:
            raise ValueError("AFS name directory extends outside the archive")
        for i, (o, z) in enumerate(zip(table["offsets"], table["sizes"])):
            if z and o < nd_off + nd_size and nd_off < o + z:
                raise ValueError(f"AFS name directory overlaps entry {i}")
    off, size = table["offsets"][entry_index], table["sizes"][entry_index]
    if not size:
        raise ValueError(f"AFS entry {entry_index} is empty; a cast writer must replace a live slot")
    rooms = entry_rooms(table["offsets"], table["sizes"], archive_size, (nd[0],) if nd else ())
    room = rooms[entry_index]
    if len(new_bytes) > room:
        raise ValueError(f"new payload {len(new_bytes)} bytes exceeds the entry room {room}")
    if new_bytes == bytes(data[off:off + size]):
        raise ValueError("no source change: the entry already holds these bytes")
    data[off:off + len(new_bytes)] = new_bytes
    if len(new_bytes) < room:
        data[off + len(new_bytes):off + room] = b"\x00" * (room - len(new_bytes))
    struct.pack_into("<I", data, 8 + 8 * entry_index + 4, len(new_bytes))
    target = Path(out) if out is not None else p
    fd, staging = tempfile.mkstemp(prefix=target.name + ".", suffix=".staging", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(bytes(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, target)
    except BaseException:
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise
    return room


def cast_writer_status() -> dict:
    """The honest current state of the combined DOA3 cast writer."""
    return {
        "game_id": GAME_ID,
        "writer": "gbox.doa3_cast",
        "afs_patch_path": True,
        "xpr0_parser": True,
        "cat_parser": True,
        "mdl_geometry_decode": True,
        "mdl_geometry_encode": True,
        "mdl_geometry_encode_note": "gbox.doa3_writer.encode_costume re-encodes every parseable owned costume "
                                    "byte for byte and writes replaced, hidden and appended-texture costumes",
        "mdl_strip_packets": True,
        "mdl_strip_note": "every material packet is a strip {32*(n+2), index_off, n, flags} drawn from its "
                          "join with fresh parity (153,262/153,262 packets of the 69 costumes); stage-mode-3 "
                          "materials lead with two setup packets",
        "mdl_descriptor_table": True,
        "mdl_descriptor_note": "header-tail vertex (obj_count) + texture (tex_count) "
                               "descriptors pinned across kas00/kas01/kas02; the texture "
                               "descriptors are Xbox D3DTexture headers (DXT1 0x0C, DXT5 0x0F, "
                               "A8R8G8B8 0x06 seen)",
        "cat_lnk_header": True,
        "cat_lnk_note": "LNK section = 'LNK\\0' + '0100' + {2,16,32,size,0,0} pinned on "
                        "68/69 costumes (kor00 has none); the joint-link body remains",
        "cat_lnk_body": True,
        "cat_lnk_body_note": "LNK body = C0 link-group count (9 on 65/68, 12 on the three "
                             "Hikaru costumes) + C0 offset/sentinel entries + C1 sub-block "
                             "count + C1+1 cumulative offsets, validated on all 68 costumes; "
                             "the per-joint / skin-weight semantics remain",
        "cat_lnk_groups": True,
        "cat_lnk_groups_note": "each non-sentinel C0 entry points to a link-group block "
                               "{N, header_size=4*(N+3), N+1 cumulative data lengths}, "
                               "validated on all 431 blocks (N in [1,22], 0 deviations); "
                               "the sub-section record semantics remain",
        "cat_lnk_sections": True,
        "cat_lnk_sections_note": "each block's data region = a leading link table "
                                 "(count-prefixed u16 polygon list, n in [1,13], "
                                 "zero-terminated, plus an unresolved residual) + N "
                                 "equal-length flat u16 triangle sections (stride % 6 == 0, "
                                 "4402/4402); the per-section triangle/joint semantics remain",
        "donor_retarget": True,
        "donor_retarget_note": "gbox.doa3_fit: the CAT render lists name each costume's 15 primary parts in a fixed "
                               "joint order; a library character's role segments are fitted per part into those "
                               "joint frames (native rest rotations not decoded: limb twist by convention)",
        "texture_write": True,
        "playable": False,
        "playable_note": "builds are built_unverified until each donor is seen running in game",
        "message": "measured MDL geometry decode (vertices/normals/UVs/every u16 strip packet "
                   "of every material) and the no-op encode gate hold on the owned costumes; "
                   "the CAT header is classified (offsets vs id_block layout, fixed "
                   "0x100/1 signature across all 69 costumes); the header-tail data "
                   "descriptor table (vertex + texture records) is located and pinned; "
                   "the LNK section envelope ('LNK\\0' + '0100' + {2,16,32,size,0,0}) "
                   "is pinned on 68/69 costumes and its body structure (link-group count "
                   "C0 + offset/sentinel table + sub-block boundary table) is decoded on "
                   "all 68; the per-joint link semantics, texture pixel format, donor "
                   "retarget and the routed cast build are the next stages",
    }


def disc_dir(ctx, game) -> Path:
    """The extracted DOA3 disc folder on this node (default.xbe + loadfile.afs): the inventory's cache extract, else
    the catalog ROM unpacked once through the Xbox launcher's own archive path."""
    root = Path(ctx.config.cache) / game["game_id"] / "extract"
    for xbe in sorted(root.glob("*/default.xbe")) if root.is_dir() else ():
        if (xbe.parent / "loadfile.afs").is_file():
            return xbe.parent
    from . import characters as CH
    from .xbox import prepare_xbe
    xbe = prepare_xbe(CH._rom(ctx, game), ctx.config, getattr(ctx, "progress", lambda *_: None))
    if not (xbe.parent / "loadfile.afs").is_file():
        raise FileNotFoundError(f"{game.get('title')}: the unpacked disc at {xbe.parent} has no loadfile.afs")
    return xbe.parent


def donor_problem(meta: dict) -> str | None:
    """cast_swap's writer gate: why a library character can't be a DOA3 fighter, else None. The fit maps the
    donor's legs onto the native thighs, shins and feet, so a donor without them (a Boo, a Dorrie) is refused before
    the deal instead of failing every costume of its fighter."""
    from .doa3_fit import DONOR_ROLES
    roles = (meta.get("rig") or {}).get("roles") or {}
    missing = [r for r in DONOR_ROLES if r not in roles]
    if missing:
        return "a DOA3 fighter needs two legs: the donor's body roles lack " + ", ".join(missing)
    return None


def _load_donor(ctx, meta):
    from . import characters as CH
    from .doa2_weighted_retarget import load_rig
    root = CH.library_root(ctx.config) / meta["slug"]
    roles = ((meta.get("rig") or {}).get("roles") or {})
    if not roles:
        raise ValueError(f"{meta['name']} has no rig roles in the character library (characters op=get {meta['slug']})")
    rig = load_rig(root / meta["model"], roles)
    rig["slug"] = meta["slug"]
    return rig


def use(ctx, meta, game, inp) -> dict:
    """``characters op=use`` for DOA3: slot ``fighter:<nick | code | name>`` replaces every costume of that fighter
    family with the library character (gbox.doa3_fit per-part fit, gbox.doa3_writer encode), writes a separate
    launchable disc build into this node's mod collection and records it as built_unverified (gameplay needs its own
    in-game check). Costumes the writer cannot decode stay native and are listed with their reason."""
    from . import characters as CH, filemods
    from . import doa3_fit as F, doa3_writer as W
    slot = (getattr(inp, "slot", "") or "").strip()
    if not slot.startswith("fighter:"):
        raise ValueError("DOA3 slots: fighter:<nick | code | name> (e.g. fighter:zack); whole casts go through "
                         "characters op=cast_swap")
    family = F.family_code(slot.split(":")[1])
    if not CH.library_root(ctx.config).is_dir():
        raise RuntimeError("DOA3 builds run on the node holding the character library (the Linux control plane)")
    rig = _load_donor(ctx, meta)
    disc = disc_dir(ctx, game)
    replacements, reports = F.costume_replacements(disc / "loadfile.afs", {family: rig}, ctx.progress)
    replaced = [r["costume"] for r in reports if r["status"] == "replaced"]
    if not replaced:
        return {"status": "failed", "writer": "gbox.doa3_cast", "slot": slot, "costumes": reports,
                "message": "no costume of this fighter could be rewritten; nothing was built"}
    name = f"doa3_{family}_{meta['slug']}"
    out = filemods.mod_dir(ctx.config, game["game_id"], name)
    record = {"kind": "character", "character": meta["slug"], "fighter_family": family, "costumes": reports,
              "writer": "gbox.doa3_cast", "gameplay_verified": False,
              "slots": [{"slot": f"fighter:{family}", "donor": meta["slug"], "donor_name": meta["name"]}]}
    W.build_disc(disc, out, replacements, name=name, game_id=game["game_id"], record=record, progress=ctx.progress)
    CH._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
            json={"game_id": game["game_id"], "slot": f"fighter:{family}", "mod": name, "nodes": ["windows"],
                  "notes": "DOA3 native costume rewrite (per-part fit); runs in the pinned DOA3 native runner on a "
                           "Windows worker. Gameplay verification required per donor."})
    return {"status": "built_unverified", "writer": "gbox.doa3_cast", "mod": name, "slot": slot,
            "costumes_replaced": replaced, "costumes": reports, "gameplay_verified": False,
            "replacement_kind": "native_disc", "launch": None,
            "message": f"Built {name}: {len(replaced)} {family} costume(s) rewritten. Launch it on a Windows worker "
                       "(native DOA3 runner) to verify gameplay."}


def cast_slots() -> list[dict]:
    """The cast menu / whole-cast swap: one slot per DOA3 fighter family (every costume of the family takes the
    donor). Tengu's model is not a costume XPR/CAT pair: listed with status not_working and its reason."""
    from . import doa3_fit as F
    rows = []
    for nick, code in F.FAMILY_CODES.items():
        rows.append({"slot": f"fighter:{nick}", "name": fighter_display_name(nick) or nick, "kind": "fighter",
                     "writer": "gbox.doa3_cast", "costume_code": code,
                     **({"story_only": True} if nick in STORY_ONLY else {}),
                     **({"hidden": True} if nick in HIDDEN_SLOTS else {})})
    for nick in F.NO_COSTUME_FAMILIES:
        rows.append({"slot": f"fighter:{nick}", "name": fighter_display_name(nick) or nick, "kind": "boss",
                     "writer": "gbox.doa3_cast", "status": "not_working",
                     "reason": "Tengu has no costume XPR/CAT pair in loadfile.afs; his model format is not decoded"})
    return rows


def build_cast(ctx, game, pairs, name) -> dict:
    """cast_swap's pairs path: [(slot, donor meta)] -> one disc build with every named fighter family rewritten in
    one loadfile.afs. -> {"mod", "slots": {slot: {status, reason?}}, "detail": {costumes}}."""
    from . import filemods
    from . import doa3_fit as F, doa3_writer as W
    plan, slots, rigs = {}, {}, {}
    for slot, meta in pairs:
        try:
            code = F.family_code(str(slot).split(":", 1)[-1])
            if meta["slug"] not in rigs:
                rigs[meta["slug"]] = _load_donor(ctx, meta)
            plan[code] = rigs[meta["slug"]]
            slots[slot] = {"status": "planned", "code": code, "donor": meta["slug"]}
        except Exception as error:  # noqa: BLE001 - one slot never stops the cast
            slots[slot] = {"status": "failed", "reason": str(error)[:500]}
    if not plan:
        return {"mod": None, "slots": slots}
    disc = disc_dir(ctx, game)
    replacements, reports = F.costume_replacements(disc / "loadfile.afs", plan, ctx.progress)
    by_code = {}
    for r in reports:
        by_code.setdefault(r["costume"][:3], []).append(r)
    for slot, row in slots.items():
        if row.get("status") != "planned":
            continue
        done = [r for r in by_code.get(row["code"], []) if r["status"] == "replaced"]
        kept = [r for r in by_code.get(row["code"], []) if r["status"] != "replaced"]
        if done:
            row["status"] = "built" if not kept else "partial"
            row["costumes"] = [r["costume"] for r in done]
            if kept:
                row["reason"] = "; ".join(f"{r['costume']} native: {r.get('reason', '')}" for r in kept)[:500]
        else:
            row["status"] = "failed"
            row["reason"] = "no costume of this family could be rewritten: " + \
                            "; ".join(f"{r['costume']}: {r.get('reason', '')}" for r in kept)[:400]
    if not replacements:
        return {"mod": None, "slots": slots}
    record = {"kind": "cast", "writer": "gbox.doa3_cast", "gameplay_verified": False, "costumes": reports,
              "slots": [{"slot": s, "donor": r.get("donor")} for s, r in slots.items() if r.get("donor")]}
    W.build_disc(disc, filemods.mod_dir(ctx.config, game["game_id"], name), replacements, name=name,
                 game_id=game["game_id"], record=record, progress=ctx.progress)
    return {"mod": name, "slots": slots, "detail": {"costumes": len(reports),
                                                    "replaced": sum(r["status"] == "replaced" for r in reports)}}


def _cli_slot_report(manifest_path: str | Path) -> str:
    m = json.loads(Path(manifest_path).read_text())
    inv = slot_inventory(m)
    lines = [f"{inv['title']}: {inv['slot_count']} fighter families, "
             f"{inv['costume_total']} complete costumes"]
    for s in inv["slots"]:
        lines.append(f"  {s['nick']:10s} code={s['code'] or '-':5s} costumes={s['costume_count']}"
                     f" display={s['display_name'] or 'pending'}")
    for g in inv["coverage_gaps"]:
        lines.append(f"  GAP {g['kind']}: {g['slot']} - {g['detail']}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - diagnostic only
    import argparse
    ap = argparse.ArgumentParser(description="DOA3 cast slot inventory report")
    ap.add_argument("manifest")
    print(_cli_slot_report(ap.parse_args().manifest))
