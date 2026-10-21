"""DOA3 (USA, Xbox) costume writer: re-encode a native costume XPR0 with replaced parts and textures.

Layout rules, measured on the 68 parseable owned costumes (lei04's descriptor table is not parsed yet) and pinned
by ``doa3_cast``:

* Header: ``XPR0``, total, header_size, ``{0x80000000, mdl_size}``, ``MDL\\0``, {obj_count, tex_count, unknown,
  obj_count}, the absolute OBJ pointer table and its zero terminator, then the OBJ records back to back (each
  4-aligned: a 2-byte pad follows an odd index count). ``mdl_size`` = end of the last OBJ record - 0x14 (68/68).
* OBJ record: ``OBJ\\0``, 0, 0, vertex groups (lo16 + hi16 = vertex count; 0 high group here), vertex count,
  absolute vertex offset, index count, absolute index offset, 12 zero words, a bounding sphere, the material chain,
  ``{0, 0x12345678}`` and the u16 index buffer.
* Strip packets {32*(n+2), index_off, n, flags}: the first strip of an OBJ starts at index 0, every later strip
  behind a two-index join (previous last index, own first index) that its packet points at; the draw is
  ``[index_off, index_off + n + 4)`` with fresh parity, so an OBJ with one strip keeps two trailing join indices.
* Header tail: one 12-byte D3DVertexBuffer {0x00800001, data offset, 0} per OBJ (data offsets are the cumulative
  vertex bytes), one 20-byte D3DTexture {0x00040001, data offset, 0, format, 0} per texture, 0xFFFFFFFF, then 0xAD
  fill to header_size (2048-aligned).
* Data region: the vertex buffers back to back from header_size, then the textures, each 128-aligned; the file
  ends 2048-aligned at the last texture's padded end.

Texture formats are NV2A words: 0x2A | colour << 8 | mip levels << 16 | log2(width) << 20 | log2(height) << 24,
colour 0x0C = DXT1, 0x0F = DXT5 (0x06 = swizzled A8R8G8B8 also occurs natively).

Nothing here writes outside the caller's output path; this module produces bytes only.
"""
from __future__ import annotations

import math
import struct
from collections import defaultdict

import numpy as np

from . import doa3_cast as C

HEADER_ALIGN = 2048
TEXTURE_ALIGN = 128
FILE_ALIGN = 2048
DXT1, DXT5, A8R8G8B8 = 0x0C, 0x0F, 0x06
FORMAT_BASE = 0x2A                       # DMA B, border bit, 2D (every native costume texture)
BYTES_PER_PIXEL_X8 = {DXT1: 4, DXT5: 8, A8R8G8B8: 32}   # bits per pixel
RECORD_PAD = b"\x77"                     # the 2-byte pad behind an odd index count is 0x7777 natively
MAT_PRESENT = 0x80000000
MAT_RENDER_DEFAULT = 0x400               # word 30 on 8,310 of the 9,960 stage-mode-1 materials


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


# ------------------------------------------------------------------------------------------------ textures

def texture_word(color: int, width: int, height: int, mips: int = 1) -> int:
    """The NV2A format word of a 2D costume texture."""
    if width & (width - 1) or height & (height - 1) or not (1 <= width <= 4096 and 1 <= height <= 4096):
        raise ValueError(f"texture size {width}x{height} is not a power of two")
    return (FORMAT_BASE | color << 8 | mips << 16 | int(math.log2(width)) << 20 | int(math.log2(height)) << 24)


def texture_info(word: int) -> dict:
    color, mips = (word >> 8) & 0xFF, (word >> 16) & 0xF
    width, height = 1 << ((word >> 20) & 0xF), 1 << ((word >> 24) & 0xF)
    bits = BYTES_PER_PIXEL_X8.get(color)
    size = None
    if bits is not None:
        size, w, h = 0, width, height
        for _ in range(max(mips, 1)):
            if color in (DXT1, DXT5):
                size += max(w // 4, 1) * max(h // 4, 1) * (8 if color == DXT1 else 16)
            else:
                size += w * h * 4
            w, h = max(w // 2, 1), max(h // 2, 1)
    return {"color": color, "mips": mips, "width": width, "height": height, "size": size,
            "kind": {DXT1: "DXT1", DXT5: "DXT5", A8R8G8B8: "A8R8G8B8"}.get(color)}


def _pow2_size(width: int, height: int, limit: int) -> tuple[int, int]:
    def fit(n):
        p = 1 << max(2, int(round(math.log2(max(n, 4)))))
        return min(p, limit)
    return fit(width), fit(height)


def encode_texture(rgba: np.ndarray, limit: int = 512) -> tuple[int, bytes]:
    """RGBA image -> (format word, DXT1 or DXT5 payload) at a power-of-two size no larger than ``limit``."""
    from PIL import Image
    from .stranglehold_swap import dxt_encode
    image = np.asarray(rgba)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("texture must be an RGB(A) image")
    if image.shape[2] == 3:
        image = np.concatenate([image, np.full(image.shape[:2] + (1,), 255, np.uint8)], 2)
    width, height = _pow2_size(image.shape[1], image.shape[0], limit)
    if (width, height) != (image.shape[1], image.shape[0]):
        image = np.asarray(Image.fromarray(image.astype(np.uint8), "RGBA").resize((width, height), Image.LANCZOS))
    alpha = bool((image[..., 3] < 250).any())
    color = DXT5 if alpha else DXT1
    data = dxt_encode(np.ascontiguousarray(image.astype(np.uint8)), 5 if alpha else 1)
    word = texture_word(color, width, height)
    if len(data) != texture_info(word)["size"]:
        raise AssertionError("DXT payload size does not match its format word")
    return word, data


def encode_texture_as(rgba: np.ndarray, word: int) -> bytes:
    """An RGBA image resampled and DXT-encoded to exactly a native slot's format word (same size, same bytes)."""
    from PIL import Image
    from .stranglehold_swap import dxt_encode
    info = texture_info(word)
    if info["kind"] not in ("DXT1", "DXT5") or info["mips"] != 1:
        raise ValueError(f"slot format {word:#x} is not a single-level DXT1/DXT5 texture")
    image = np.asarray(rgba)
    if image.shape[2] == 3:
        image = np.concatenate([image, np.full(image.shape[:2] + (1,), 255, np.uint8)], 2)
    image = np.asarray(Image.fromarray(image.astype(np.uint8), "RGBA").resize((info["width"], info["height"]),
                                                                                Image.LANCZOS))
    data = dxt_encode(np.ascontiguousarray(image), 1 if info["kind"] == "DXT1" else 5)
    if len(data) != info["size"]:
        raise AssertionError("slot payload size does not match its format word")
    return data


def placeholder_texture(word: int) -> tuple[int, bytes]:
    """A 4x4 stand-in with the same colour format (keeps a texture index valid at 8-64 bytes)."""
    color = (word >> 8) & 0xFF
    small = texture_word(color if color in BYTES_PER_PIXEL_X8 else DXT1, 4, 4)
    return small, bytes(texture_info(small)["size"])


# ------------------------------------------------------------------------------------------------ strips

def stripify(triangles) -> list[list[int]]:
    """Greedy strips for counter-clockwise (glTF) triangles under the costume's decode rule: a strip
    (s0, s1, s2, ...) drawn at an even step yields (s0, s2, s1), (s1, s2, s3), (s2, s4, s3), ... ."""
    tris = [tuple(int(v) for v in t) for t in np.asarray(triangles, int).reshape(-1, 3)
            if len({int(t[0]), int(t[1]), int(t[2])}) == 3]
    # directed edge (a, b) -> triangles containing it in that winding
    by_edge = defaultdict(list)
    for k, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            by_edge[e].append(k)
    used = [False] * len(tris)
    strips = []

    def walk(start: int, rotation: int, commit: bool) -> list[int]:
        a, b, c = tris[start][rotation:] + tris[start][:rotation]
        strip, taken = [a, c, b], {start}            # decodes (a, b, c) at an even step
        while True:
            # the next triangle sits at step len(strip) - 2: (p, q, r) decoded as (p, q, r) on odd steps and as
            # (p, r, q) on even ones, so its counter-clockwise winding holds the directed edge (p, q) / (q, p)
            p, q = strip[-2], strip[-1]
            odd = (len(strip) - 2) % 2 == 1
            edge = (p, q) if odd else (q, p)
            k = next((k for k in by_edge.get(edge, ()) if not used[k] and k not in taken), None)
            if k is None:
                break
            taken.add(k)
            strip.append(next(v for v in tris[k] if v not in (p, q)))
        if commit:
            for k in taken:
                used[k] = True
        return strip

    for start in range(len(tris)):
        if used[start]:
            continue
        best = max(range(3), key=lambda rotation: len(walk(start, rotation, False)))
        strips.append(walk(start, best, True))
    return strips


MAX_PACKETS = 128            # strips per material; natively up to 261 (lei00's face), kept well inside that
MAX_VERTICES = 16384         # vertices per OBJ (native vertices kept first + the donor's); natively up to 8877


def strip_buffer(strips: list[list[int]]) -> tuple[list[int], list[tuple[int, int]]]:
    """Index buffer + (index_off, triangle_count) per strip, stitched the native way."""
    indices, packets = [], []
    for k, strip in enumerate(strips):
        n = len(strip) - 2
        if n < 1:
            raise ValueError("a strip needs at least three indices")
        if k == 0:
            packets.append((0, n))
            indices.extend(strip)
        else:
            packets.append((len(indices), n))
            indices.extend((indices[-1], strip[0]))
            indices.extend(strip)
    if len(strips) == 1:
        indices.extend((indices[-1], indices[-1]))      # the first strip's draw reads n + 4 indices
    return indices, packets


def decode_buffer(indices: list[int], packets: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """The costume decode rule applied to a buffer this module wrote (for verification)."""
    out = []
    for off, n in packets:
        out.extend(C._strip_triangles(indices[off:off + n + 4])[:n])
    return out


# ------------------------------------------------------------------------------------------------ encode

def _sphere(positions: np.ndarray) -> tuple[float, float, float, float]:
    lo, hi = positions.min(0), positions.max(0)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(positions - center, axis=1).max()) if len(positions) else 0.0
    return float(center[0]), float(center[1]), float(center[2]), radius


def _material_template(geometry: dict, obj_index: int) -> list[int]:
    """A stage-mode-1 material header to clone: the replaced OBJ's own first one, else the costume's first."""
    candidates = [geometry["objects"][obj_index]] + geometry["objects"]
    for obj in candidates:
        for mat in obj["materials"]:
            if mat["mode"] == 1 and not mat["setup_packets"]:
                return list(mat["header"])
    raise ValueError("the costume has no single-stage material to clone")


def _part_record(geometry: dict, obj_index: int, part: dict, vertex_floor: int):
    """(vertex array (N, 8) float32, index list, materials [(header words, packets)], first donor vertex) for a
    replaced OBJ. The native vertices stay first, untouched and drawn by nothing: whatever the CAT addresses by
    native vertex number (the face / hand morph links, per-vertex lists) keeps landing on them, never on the donor.
    The donor's vertices follow and its strips index them from there."""
    donor = np.asarray(part["vertices"], np.float32).reshape(-1, 8)
    if not len(donor):
        raise ValueError(f"OBJ {obj_index} replacement has no vertices")
    native = np.frombuffer(geometry["objects"][obj_index]["vertex_bytes"], "<f4").reshape(-1, 8)
    base_vertex = len(native)
    vertices = np.concatenate([native, donor])
    if len(vertices) > MAX_VERTICES:
        raise ValueError(f"OBJ {obj_index} replacement needs {len(vertices)} vertices (native {base_vertex} + donor "
                         f"{len(donor)}); the writer keeps an OBJ within {MAX_VERTICES} (natively up to 8877)")
    template = _material_template(geometry, obj_index)
    indices, materials = [], []
    for group in part["materials"]:
        tris = np.asarray(group["triangles"], int).reshape(-1, 3)
        if not len(tris):
            continue
        if tris.min() < 0 or tris.max() >= len(donor):
            raise ValueError(f"OBJ {obj_index} triangle references a missing vertex")
        tris = tris + base_vertex
        all_strips = stripify(tris)
        # one material per MAX_PACKETS strips (same texture): no record outgrows what the native costumes carry
        for first in range(0, len(all_strips), MAX_PACKETS):
            strips = all_strips[first:first + MAX_PACKETS]
            local, packets = strip_buffer(strips)
            base = len(indices)
            if base:
                # stitch this material behind the previous one: its first strip gets a join as well, whose position
                # its packet points at; later strips keep their own joins, shifted by the base and the new join
                if len(strips) == 1:
                    local = local[:-2]                  # the trailing pair is only needed by an OBJ's first strip
                packets = [(base, packets[0][1])] + [(base + off + 2, n) for off, n in packets[1:]]
                local = [indices[-1], local[0]] + local
            indices.extend(local)
            header = list(template)
            positions = vertices[np.unique(np.concatenate([np.asarray(s) for s in strips])), :3]
            header[1] = C.MAT_HEADER_WORDS + 4 * len(packets)
            header[4:8] = list(struct.unpack("<4I", struct.pack("<4f", *_sphere(positions))))
            header[C.MAT_WORD_MODE] = 1
            header[C.MAT_WORD_TEXTURE] = int(group["texture"])
            header[28] = header[29] = 0
            header[C.MAT_WORD_PACKETS] = len(packets)
            header[32] = 0
            header[0] = MAT_PRESENT
            materials.append((header, packets))
    if not materials:
        raise ValueError(f"OBJ {obj_index} replacement has no triangles")
    # the last packet's draw must end inside the buffer, and an even count keeps the next record 4-aligned
    off, n = materials[-1][1][-1]
    while len(indices) < off + n + 4 or len(indices) % 2:
        indices.append(indices[-1])
    return vertices, indices, materials


def encode_costume(template: bytes, parts: dict[int, dict] | None = None, textures: list[tuple[int, bytes]] = (),
                   *, hide: set[int] = frozenset(), shrink_textures: set[int] = frozenset(),
                   texture_slots: dict[int, tuple[int, bytes]] | None = None) -> bytes:
    """Rebuild a costume XPR0.

    ``parts``: {OBJ index: {"vertices": (N, 8) pos/normal/uv in the OBJ's own joint frame, "materials":
    [{"texture": index, "triangles": (M, 3) counter-clockwise}]}} replaces that OBJ's drawing: its native vertices
    stay first (undrawn), the donor's follow. ``textures``: appended (format word, payload) pairs; their indices
    start at the native texture count. ``texture_slots``: {native index: (format word, payload)} puts a texture into
    a native slot instead (the costume keeps its texture count). ``hide``: OBJs whose strips collapse onto vertex 0
    (vertices and records kept). ``shrink_textures``: native texture indices replaced by 4x4 stand-ins."""
    parts = parts or {}
    texture_slots = texture_slots or {}
    geometry = C.costume_geometry(template)
    table = C.mdl_descriptor_table(template)
    chunk = geometry["chunk"]
    total0, hsize0 = struct.unpack_from("<II", template, 4)
    objects = geometry["objects"]
    for k in list(parts) + list(hide):
        if not 0 <= k < len(objects):
            raise ValueError(f"OBJ {k} is outside the costume's {len(objects)} objects")
    if set(parts) & set(hide):
        raise ValueError("an OBJ cannot be both replaced and hidden")

    # ---- per-OBJ payloads
    records, vertex_blobs = [], []
    for k, obj in enumerate(objects):
        if k in parts:
            vertices, indices, materials = _part_record(geometry, k, parts[k], obj["vertex_count"])
            mat_bytes = b"".join(struct.pack(f"<{C.MAT_HEADER_WORDS}I", *header)
                                 + b"".join(struct.pack("<4I", 32 * (n + 2), off, n, 0) for off, n in packets)
                                 for header, packets in materials)
            sphere = struct.pack("<4f", *_sphere(vertices[obj["vertex_count"]:, :3]))
            records.append({"vcount": len(vertices), "groups": len(vertices), "materials": mat_bytes,
                            "indices": indices, "sphere": sphere})
            vertex_blobs.append(vertices.astype("<f4").tobytes())
        else:
            start = obj["offset"]
            mat_bytes = template[start + C.MAT_HEADER_BASE:obj["index_offset"] - 8]
            indices = list(struct.unpack(f"<{obj['index_count']}H", obj["index_bytes"]))
            if k in hide:
                # every strip collapses onto vertex 0: nothing draws, and vertex data the CAT may still write
                # (morph links) can never pull a triangle back into view
                indices = [0] * len(indices)
            records.append({"vcount": obj["vertex_count"], "groups": obj["header"][3], "materials": mat_bytes,
                            "indices": indices, "sphere": template[start + 0x50:start + 0x60]})
            vertex_blobs.append(obj["vertex_bytes"])

    # ---- textures: native (raw, shrunk or slot-replaced) + appended
    native = table["texture_descriptors"]
    tex_payloads = []
    for k, desc in enumerate(native):
        end = native[k + 1]["offset"] if k + 1 < len(native) else total0 - hsize0
        raw = template[hsize0 + desc["offset"]:hsize0 + end]
        info = texture_info(desc["format"])
        if k in texture_slots:
            tex_payloads.append(texture_slots[k])
        elif k in shrink_textures:
            tex_payloads.append(placeholder_texture(desc["format"]))
        else:
            tex_payloads.append((desc["format"], raw[:info["size"]] if info["size"] else raw))
    tex_payloads.extend(textures)
    for word, data in list(textures) + list(texture_slots.values()):
        info = texture_info(word)
        if info["size"] is not None and len(data) != info["size"]:
            raise ValueError(f"appended texture payload {len(data)} bytes does not match its format ({info['size']})")

    # ---- header layout
    obj_count, tex_count = len(objects), len(tex_payloads)
    table_off = C.MDL_CHUNK + 0x14
    cursor = table_off + 4 * obj_count + 4
    offsets, layout = [], []
    for rec in records:
        offsets.append(cursor)
        mat_end = cursor + C.MAT_HEADER_BASE + len(rec["materials"])
        iptr = mat_end + 8
        end = iptr + 2 * len(rec["indices"])
        layout.append((cursor, iptr))
        cursor = _align(end, 4)
    last_end = layout[-1][1] + 2 * len(records[-1]["indices"])
    if last_end % 4:
        raise ValueError("the last OBJ record must end 4-aligned (native costumes all do)")
    tail = C.VERTEX_DESC_BYTES * obj_count + C.TEXTURE_DESC_BYTES * tex_count + 4
    hsize = _align(_align(last_end, 4) + tail, HEADER_ALIGN)

    # ---- data layout
    vertex_offsets, data_cursor = [], 0
    for vb in vertex_blobs:
        vertex_offsets.append(data_cursor)
        data_cursor += len(vb)
    tex_offsets = []
    for word, data in tex_payloads:
        data_cursor = _align(data_cursor, TEXTURE_ALIGN)
        tex_offsets.append(data_cursor)
        data_cursor += len(data)
    total = _align(hsize + data_cursor, FILE_ALIGN)

    out = bytearray(total)
    struct.pack_into("<4sII", out, 0, C.XPR_MAGIC, total, hsize)
    struct.pack_into("<II", out, 0x0C, C.USER_TYPE, last_end - C.MDL_CHUNK)
    out[C.MDL_CHUNK:C.MDL_CHUNK + 4] = C.MDL_TAG
    struct.pack_into("<4I", out, C.MDL_CHUNK + 4, obj_count, tex_count, chunk["unknown"], obj_count)
    struct.pack_into(f"<{obj_count}I", out, table_off, *offsets)
    for k, (rec, (start, iptr)) in enumerate(zip(records, layout)):
        out[start:start + 4] = C.OBJ_TAG
        struct.pack_into("<7I", out, start + 4, 0, 0, rec["groups"], rec["vcount"], hsize + vertex_offsets[k],
                         len(rec["indices"]), iptr)
        out[start + 0x50:start + 0x60] = rec["sphere"]
        m = start + C.MAT_HEADER_BASE
        out[m:m + len(rec["materials"])] = rec["materials"]
        struct.pack_into("<II", out, iptr - 8, 0, C.MAT_TERMINATOR)
        struct.pack_into(f"<{len(rec['indices'])}H", out, iptr, *rec["indices"])
        end = iptr + 2 * len(rec["indices"])
        out[end:_align(end, 4)] = RECORD_PAD * (_align(end, 4) - end)
    p = last_end
    for off in vertex_offsets:
        struct.pack_into("<3I", out, p, C.VERTEX_DESC_FLAG, off, 0)
        p += C.VERTEX_DESC_BYTES
    for (word, _), off in zip(tex_payloads, tex_offsets):
        struct.pack_into("<5I", out, p, C.TEXTURE_DESC_FLAG, off, 0, word, 0)
        p += C.TEXTURE_DESC_BYTES
    struct.pack_into("<I", out, p, C.DESC_TERMINATOR)
    p += 4
    out[p:hsize] = bytes([C.DESC_PAD_BYTE]) * (hsize - p)
    out[hsize:] = bytes([C.DESC_PAD_BYTE]) * (total - hsize)          # data-region alignment gaps are 0xAD too
    for vb, off in zip(vertex_blobs, vertex_offsets):
        out[hsize + off:hsize + off + len(vb)] = vb
    for (word, data), off in zip(tex_payloads, tex_offsets):
        out[hsize + off:hsize + off + len(data)] = data
    blob = bytes(out)
    # the result must decode under the same rules as a native costume
    check = C.costume_geometry(blob)
    C.mdl_descriptor_table(blob)
    if check["object_count"] != obj_count:
        raise AssertionError("re-encoded costume lost objects")
    return blob


# ------------------------------------------------------------------------------------------------ CAT

def disable_cat_links(cat: bytes) -> bytes:
    """Mark every CAT ``LNK`` link group absent (0xFFFFFFFF, as natively absent groups are).

    The link groups are vertex-indexed morph data for particular parts (the face's expressions on the head OBJ,
    the hands' poses on the hand OBJs): section 0 holds s16 base positions and the later sections per-pose deltas,
    addressed by the native vertex numbering. Applied to a replaced part they would pull its vertices back into the
    native shape, so a writer that replaces those parts turns them off. kor00 has no LNK section; returned as is."""
    body = C.cat_lnk_body(cat)
    if body is None:
        return bytes(cat)
    out = bytearray(cat)
    first = body["body_offset"] + 4
    struct.pack_into(f"<{body['link_group_count']}I", out, first, *([0xFFFFFFFF] * body["link_group_count"]))
    return bytes(out)


# ------------------------------------------------------------------------------------------------ AFS

AFS_ALIGN = 2048
NAME_RECORD = 48


def afs_layout(head: bytes, archive_size: int) -> dict:
    """The TOC and the CRI name directory of an AFS archive (the directory pair sits either right after the TOC or,
    as in DOA3's loadfile.afs, in the 8 bytes before the first entry)."""
    from .doa3_inventory import afs_table
    table = afs_table(head, archive_size)
    name_dir = table["name_dir"]
    first = min((o for o, z in zip(table["offsets"], table["sizes"]) if z), default=0)
    if name_dir is None and first >= 8 + 8 * table["count"] + 8 and first <= len(head):
        pair = struct.unpack_from("<II", head, first - 8)
        if pair[1] == NAME_RECORD * table["count"] and pair[0] + pair[1] <= archive_size:
            name_dir = pair
    table["name_dir"] = name_dir
    table["first_entry"] = first
    return table


def afs_rebuild(source, out, replacements: dict[int, bytes], progress=lambda *_: None, *,
                keep_layout: bool = True) -> dict:
    """Write ``out`` = ``source`` with entries replaced. ``source`` is only read.

    keep_layout (the default, what DOA3 needs): every replaced entry keeps its exact TOC size and position - the
    payload must not be larger than the original entry and is zero-padded to it; the TOC and the CRI name directory
    stay byte-identical. The owned loadfile.afs is packed back to back by 2048-byte sectors (1101/1101 entries) and
    DOA3's CRI ADXF loader breaks on anything else: builds that shrank an entry in place or moved one to the end
    crashed the game's file loading (the voice loader read another file's bytes), while same-size rewrites run.

    keep_layout=False: an entry that fits its room is rewritten in place, a larger one moves to the archive's end and
    its TOC offset follows; TOC and name-record sizes are updated (for AFS readers that honour the TOC)."""
    import os
    import shutil
    from pathlib import Path
    from .doa3_inventory import entry_rooms
    source, out = Path(source), Path(out)
    size = source.stat().st_size
    with source.open("rb") as stream:
        head = stream.read(8)
        count = struct.unpack_from("<I", head, 4)[0]
        stream.seek(0)
        head = stream.read(max(8 + 8 * count + 8, 0x100000))
    table = afs_layout(head, size)
    name_dir = table["name_dir"]
    barriers = (name_dir[0],) if name_dir else ()
    rooms = entry_rooms(table["offsets"], table["sizes"], size, barriers)
    tmp = out.with_name(out.name + ".part")
    progress(0, f"copying {source.name} ({size >> 20} MB)")
    shutil.copyfile(source, tmp)
    moved, inplace = [], []
    with tmp.open("r+b") as stream:
        end = stream.seek(0, 2)
        for index, data in sorted(replacements.items()):
            if not 0 <= index < table["count"] or not table["sizes"][index]:
                raise ValueError(f"AFS entry {index} is not a live entry")
            if keep_layout:
                original = table["sizes"][index]
                if len(data) > original:
                    raise ValueError(f"AFS entry {index}: {len(data)} bytes do not fit its original {original}; "
                                     "the game's loader needs every entry at its original size")
                stream.seek(table["offsets"][index])
                stream.write(data + bytes(rooms[index] - len(data)))
                inplace.append(index)
                continue
            if len(data) <= rooms[index]:
                offset = table["offsets"][index]
                stream.seek(offset)
                stream.write(data + bytes(rooms[index] - len(data)))
                inplace.append(index)
            else:
                offset = _align(end, AFS_ALIGN)
                stream.seek(offset)
                stream.write(data + bytes(_align(len(data), AFS_ALIGN) - len(data)))
                end = offset + _align(len(data), AFS_ALIGN)
                moved.append(index)
            stream.seek(8 + 8 * index)
            stream.write(struct.pack("<II", offset, len(data)))
            if name_dir:
                stream.seek(name_dir[0] + NAME_RECORD * index + 44)
                stream.write(struct.pack("<I", len(data)))
        stream.flush()
        os.fsync(stream.fileno())
    # verify every replaced entry reads back through the (rewritten or kept) TOC
    with tmp.open("rb") as stream:
        for index, data in replacements.items():
            stream.seek(8 + 8 * index)
            offset, length = struct.unpack("<II", stream.read(8))
            stream.seek(offset)
            want = data + bytes(table["sizes"][index] - len(data)) if keep_layout else data
            if length != len(want) or stream.read(length) != want:
                raise AssertionError(f"AFS entry {index} does not read back")
        if keep_layout:
            toc = 8 + 8 * table["count"] + 8
            stream.seek(0)
            if stream.read(toc) != head[:toc]:
                raise AssertionError("the AFS TOC changed although the layout was to be kept")
            if name_dir:
                with source.open("rb") as original:
                    original.seek(name_dir[0])
                    names = original.read(name_dir[1])
                stream.seek(name_dir[0])
                if stream.read(name_dir[1]) != names:
                    raise AssertionError("the AFS name directory changed although the layout was to be kept")
    os.replace(tmp, out)
    return {"in_place": inplace, "moved_to_end": moved, "size": out.stat().st_size}


def entry_index(entries: list[dict], name: str) -> int:
    """The AFS index of a uniquely named entry (``read_afs`` rows)."""
    hits = [e["index"] for e in entries if e.get("name") == name]
    if len(hits) != 1:
        raise ValueError(f"loadfile.afs has {len(hits)} entries named {name!r}")
    return hits[0]


# ------------------------------------------------------------------------------------------------ mod folder

def build_disc(disc_dir, mod_dir, afs_replacements: dict[int, bytes], *, name: str, game_id: str,
               record: dict | None = None, progress=lambda *_: None) -> dict:
    """A launchable DOA3 build: ``mod_dir/disc`` holds the whole disc (hard links to the unchanged files, copies
    where links cannot be made) with a rebuilt loadfile.afs, and ``.gbox-mod.json`` points the launcher at its
    default.xbe. The native runner treats the folder holding ``--xbe`` as the disc root."""
    import json
    import os
    import shutil
    import time
    from pathlib import Path
    from . import build_record
    disc_dir, mod_dir = Path(disc_dir), Path(mod_dir)
    if not (disc_dir / "default.xbe").is_file() or not (disc_dir / "loadfile.afs").is_file():
        raise ValueError(f"{disc_dir} is not an extracted DOA3 disc (default.xbe + loadfile.afs)")
    if mod_dir.exists():
        shutil.rmtree(mod_dir)
    disc = mod_dir / "disc"
    disc.mkdir(parents=True)
    linked = copied = 0
    for path in sorted(disc_dir.rglob("*")):
        rel = path.relative_to(disc_dir)
        target = disc / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if rel.as_posix().lower() == "loadfile.afs":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, target)
            linked += 1
        except OSError:
            shutil.copy2(path, target)
            copied += 1
    afs = afs_rebuild(disc_dir / "loadfile.afs", disc / "loadfile.afs", afs_replacements, progress)
    meta = {"name": name, "game_id": game_id, "image": "disc/default.xbe", "files": ["loadfile.afs"],
            "built": time.time(), "afs": afs, "linked_files": linked, "copied_files": copied,
            "gameplay_verified": False, **(record or {})}
    rows = [build_record.file_change("disc/loadfile.afs", "patched", afs["size"],
                                     (disc_dir / "loadfile.afs").stat().st_size,
                                     what=f"{len(afs_replacements)} costume entries rebuilt")]
    meta = build_record.stamp(meta, kind=meta.get("kind", "character"), file_changes=rows)
    (mod_dir / build_record.MARKER).write_text(json.dumps(meta), encoding="utf-8")
    return meta
