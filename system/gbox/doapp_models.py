"""Dead Or Alive ++ (arcade, Tecmo TPS) fighter model files: container, section expansion, meshes, batches, TIMs.

Format-level reader for the model files `doapp_inventory.FIGHTERS[*]["models"]` names (files 49-102). It decodes
everything that is established from the game's own code (docs/doapp_pipeline.md):

* container: u32 offset of the TIM run, then 14 sections `{u32 dest, u32 length, payload}` (4-byte aligned; dest 0 =
  absent, 4 bytes). Sections 0, 1, 2, 11, 13 are raw; 3-10 and 12 are packed and expanded by the fight loader's
  0x8006c718. unpack_model() runs that routine itself on gbox.zn_tps_boot's interpreter over the decoded program
  (doapp_inventory.decode_owned), so the expansion is the game's, byte for byte, not a re-implementation.
* sections 1 / 2: u16 vertex count / first vertex per drawn part, 13 per mesh slot (slot k = section 3 + k).
* mesh sections: `[0x42][header size][vertex block offset][group count]{count, chunk offsets}` + SVECTOR vertices.
  The renderer (overlay 0x800ab828) transforms part p's vertex batch with bone BONE_SLOTS[slot][p] (bone indices
  from the 13-byte tables at 0x80103ed0) and draws group p's chunks (`u16 count, u16 kind` + prebuilt GPU packets).
* the TIM run: standard PS1 TIMs back to back.

* chunk records -> primitives (primitives(); layouts from the draw routines, see CHUNK_LAYOUTS) and the TIMs as
  VRAM texture pages (vram(), texture_page()).

The skeleton is not in the model: the per-bone batches are in bone-local frames that the game's skeleton build
places. gbox.doapp_motion runs that build; gbox.doapp_chars assembles the rigged GLB (docs/doapp_pipeline.md).
"""
from __future__ import annotations

import struct

SECTION_COUNT = 14
PACKED_SECTIONS = frozenset({3, 4, 5, 6, 7, 8, 9, 10, 12})
MESH_SLOTS = 8                     # slot k = section 3 + k (body, then limbs / hands / feet, then accessories)
SLOT_ENTRIES = 13                  # 13 count/start entries and 13 bone bytes per slot
MESH_MARKER = 0x42                 # first word the expander writes
UNPACK_FN = 0x8006C718             # fight loader's section expander (a0 player, a1 src, a2 dest) -> new src
WORK_BASE = 0x801E8000             # where unpack_model() expands (scratch; the game's player 0 buffer is 0x801fe800 in
                                   # its 4 MiB RAM, 0x8008775c[0]; doapp_motion.Rig uses that one)
LOAD_AT = 0x80140000               # where unpack_model() places the file (free RAM during the fight loader)
BONE_TABLE_RAM = 0x80103ED0        # overlay: 13 bone bytes per slot; 0x80103f2c is the 10-part body variant
SCRATCH_VERTEX = 0x1F800000        # transformed vertex i lives at SCRATCH_VERTEX + 8 * i ...
SPILL_VERTEX = 0x802A6800          # ... and from index 126 on at SPILL_VERTEX + 8 * (i - 126)
SCRATCH_VERTICES = 126

# bone index per part, per slot, as the renderer selects it (0x800ab828): slots 2 and 4 draw ONE of three hand
# shapes (part chosen per frame) with a fixed bone; slot 0 uses the 10-entry variant when the body has 10 parts.
BONE_SLOTS = {
    0: (0, 1, 2, 6, 7, 12, 13, 4, 8, 10, 14, 3, 9),
    1: (4, 8),
    2: (5, 5, 5),
    3: (10, 14),
    4: (11, 11, 11),
    5: (3,),
    6: (9,),
    7: (15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 14),
}
BODY_10_PARTS = (0, 1, 2, 6, 7, 12, 13, 3, 9, 0)


class FormatError(ValueError):
    pass


def _u32(b: bytes, o: int) -> int:
    if o < 0 or o + 4 > len(b):
        raise FormatError(f"u32 at {o:#x} outside {len(b):#x} bytes")
    return struct.unpack_from("<I", b, o)[0]


def tim_offset(model: bytes) -> int:
    off = _u32(model, 0)
    if not 4 < off < len(model) or off & 3:
        raise FormatError(f"TIM offset {off:#x} is not inside the {len(model):#x}-byte model")
    return off


def raw_sections(model: bytes) -> list[dict]:
    """Walk the section records up to the first packed one (its source length is only known by expanding it).
    Each entry: index, dest, length, payload offset, packed."""
    end = tim_offset(model)
    p, out = 4, []
    for s in range(SECTION_COUNT):
        p = (p + 3) & ~3
        dest = _u32(model, p)
        if dest == 0:
            out.append({"index": s, "dest": 0, "length": 0, "offset": p + 4, "packed": False})
            p += 4
            continue
        length = _u32(model, p + 4)
        rec = {"index": s, "dest": dest, "length": length, "offset": p + 8, "packed": s in PACKED_SECTIONS}
        out.append(rec)
        if rec["packed"]:
            break
        if p + 8 + length > end:
            raise FormatError(f"section {s} payload runs past the TIM run at {end:#x}")
        p += 8 + length
    return out


def unpack_model(model: bytes, program_ram: bytes, *, limit: int = 20_000_000) -> dict[int, bytes]:
    """{section index: expanded bytes} exactly as the fight loader leaves them in the player 0 work buffer.
    program_ram: decoded program + overlay (doapp_inventory.decode_owned()[1])."""
    from . import zn_tps_boot as Z
    end = tim_offset(model)
    if len(program_ram) < 0x200000:
        raise FormatError("program RAM image must be the full 2 MiB")
    mem = Z.ZNMemory(b"\0" * 16, b"", b"\0" * 8, b"\0" * 8)
    mem.ram[:] = program_ram[:0x200000]
    base = LOAD_AT & 0x1FFFFF
    if base + len(model) > (WORK_BASE & 0x1FFFFF):
        raise FormatError("model too large for the load window")
    mem.ram[base:base + len(model)] = model
    cpu = Z.R3000(mem)
    p, out = 4, {}
    for s in range(SECTION_COUNT):
        p = (p + 3) & ~3
        dest = _u32(model, p)
        if dest == 0:
            p += 4
            continue
        length = _u32(model, p + 4)
        if dest < 0x38 or (WORK_BASE & 0x1FFFFF) + dest + length > 0x1FFF00 - 0x1000:
            raise FormatError(f"section {s}: dest {dest:#x} length {length:#x} outside the work buffer")
        p += 8
        w = (WORK_BASE & 0x1FFFFF) + dest
        if s in PACKED_SECTIONS:
            q = cpu.call(UNPACK_FN, (0, LOAD_AT + p, WORK_BASE + dest), sp=0x801FFFE0, limit=limit) - LOAD_AT
            if not p < q <= end:
                raise FormatError(f"section {s}: expander stopped at {q:#x}, outside {p:#x}..{end:#x}")
            p = q
        else:
            if p + length > end:
                raise FormatError(f"section {s} payload runs past the TIM run")
            mem.ram[w:w + length] = model[p:p + length]
            p += length
        out[s] = bytes(mem.ram[w:w + length])
    return out


def parse_mesh(section: bytes) -> dict:
    """Header, part groups (chunk offsets) and vertices of an expanded mesh section."""
    if len(section) < 16 or _u32(section, 0) != MESH_MARKER:
        raise FormatError("not an expanded mesh section (marker 0x42)")
    hdr, vtx, ngroups = _u32(section, 4), _u32(section, 8), _u32(section, 12)
    if not 16 <= hdr <= len(section) or ngroups > 64:
        raise FormatError(f"bad mesh header (size {hdr:#x}, {ngroups} groups)")
    groups, p = [], 16
    for _ in range(ngroups):
        n = _u32(section, p)
        if n > 64 or p + 4 + 4 * n > hdr:
            raise FormatError("group list runs past the header")
        offs = list(struct.unpack_from(f"<{n}I", section, p + 4))
        if any(not hdr <= o < len(section) for o in offs):
            raise FormatError("chunk offset outside the section")
        groups.append(offs)
        p += 4 + 4 * n
    vertices = []
    if vtx:
        if not hdr <= vtx <= len(section) or (len(section) - vtx) % 8:
            raise FormatError(f"vertex block at {vtx:#x} does not hold whole SVECTORs")
        vertices = [struct.unpack_from("<3h", section, o) for o in range(vtx, len(section), 8)]
    chunks = [[chunk_header(section, o) for o in g] for g in groups]
    return {"header_size": hdr, "vertex_offset": vtx, "groups": groups, "chunks": chunks, "vertices": vertices}


def chunk_header(section: bytes, off: int) -> dict:
    """A chunk's u16 count + u16 kind (0x8018/0x8019/0x801a/0x801b/0x8038/0x8039/0x803a/0x803b/0x805a/0x29/...)."""
    if off < 0 or off + 4 > len(section):
        raise FormatError(f"chunk at {off:#x} outside the section")
    count, kind = struct.unpack_from("<HH", section, off)
    return {"offset": off, "count": count, "kind": kind}


# ---- chunk records -> primitives (layouts from the overlay's draw routines, dispatched by 0x800ab828) -------------
# Every record holds the same prebuilt GPU packet twice (double buffer), then the corner pointers into the
# transformed-vertex buffer, then per-kind data. kind -> record size, packet type, size of one packet copy, offset of
# the corner pointers, normal offsets (SVECTOR 4.12), culled (single-sided), the GPU code the drawer forces (None =
# the packet's own). 0x805a are the seam triangles joining two bones' batches (last group of slots 0, 1, 3); they
# reuse the vertices the slot's other batches already transformed and borrow neighbouring faces' lit colours through
# 3 x 2 colour pointers (+0x5c). Kind 1 (section 12 only) carries four inline SVECTOR corners and no vertex block.
SCRATCH_VERTEX_LIMIT = SCRATCH_VERTEX + 8 * SCRATCH_VERTICES
CHUNK_LAYOUTS = {
    0x8018: dict(size=0x54, packet="FT3", copy=0x20, ptrs=0x40, normals=(0x4C,), cull=True, code=None),
    0x8019: dict(size=0x68, packet="FT4", copy=0x28, ptrs=0x50, normals=(0x60,), cull=True, code=None),
    0x801A: dict(size=0x74, packet="GT3", copy=0x28, ptrs=0x50, normals=(0x5C, 0x64, 0x6C), cull=True, code=None),
    0x801B: dict(size=0x98, packet="GT4", copy=0x34, ptrs=0x68, normals=(0x78, 0x80, 0x88, 0x90), cull=True, code=None),
    0x803A: dict(size=0x74, packet="GT3", copy=0x28, ptrs=0x50, normals=(0x5C, 0x64, 0x6C), cull=False, code=0x34),
    0x803B: dict(size=0x98, packet="GT4", copy=0x34, ptrs=0x68, normals=(0x78, 0x80, 0x88, 0x90), cull=False,
                 code=0x3C),
    0x0029: dict(size=0x60, packet="FT4", copy=0x28, ptrs=0x50, normals=(), cull=False, code=0x2C),
    0x805A: dict(size=0x74, packet="GT3", copy=0x28, ptrs=0x50, normals=(), cull=True, code=0x34),
    0x0001: dict(size=0x70, packet="FT4", copy=0x28, ptrs=None, inline=0x50, normals=(), cull=False, code=None),
}
SEAM_KIND = 0x805A
_UV = {"FT3": (0x0C, 0x14, 0x1C), "FT4": (0x0C, 0x14, 0x1C, 0x24),
       "GT3": (0x0C, 0x18, 0x24), "GT4": (0x0C, 0x18, 0x24, 0x30)}
_TPAGE = {"FT3": 0x14, "FT4": 0x14, "GT3": 0x18, "GT4": 0x18}


def vertex_index(ptr: int) -> int:
    """Transformed-vertex buffer address -> vertex index in the section's vertex block."""
    if SCRATCH_VERTEX <= ptr < SCRATCH_VERTEX_LIMIT and not ptr & 7:
        return (ptr - SCRATCH_VERTEX) >> 3
    if SPILL_VERTEX <= ptr < SPILL_VERTEX + 0x10000 and not ptr & 7:
        return SCRATCH_VERTICES + ((ptr - SPILL_VERTEX) >> 3)
    raise FormatError(f"{ptr:#010x} is not a transformed-vertex buffer address")


def tpage_fields(tp: int) -> dict:
    return {"x": (tp & 0xF) * 64, "y": ((tp >> 4) & 1) * 256, "semi": (tp >> 5) & 3,
            "bpp": (4, 8, 16, 16)[(tp >> 7) & 3], "raw": tp & 0xFFFF}


def clut_xy(cl: int) -> tuple[int, int]:
    return (cl & 0x3F) * 16, (cl >> 6) & 0x1FF


def primitives(section: bytes, chunk_offset: int) -> list[dict]:
    """The chunk at chunk_offset of an expanded mesh section -> primitives: kind, packet ('FT3'/'FT4'/'GT3'/'GT4'),
    code (GPU command as drawn), verts (vertex indices in drawing order; None for kind 1, which has `positions`),
    uv, clut (VRAM x, y), tpage (x, y, bpp, semi, raw), normals (4.12, one per corner or one per face),
    double_sided."""
    if chunk_offset < 0 or chunk_offset + 4 > len(section):
        raise FormatError(f"chunk at {chunk_offset:#x} outside the section")
    count, kind = struct.unpack_from("<HH", section, chunk_offset)
    lay = CHUNK_LAYOUTS.get(kind)
    if lay is None:
        raise FormatError(f"chunk at {chunk_offset:#x}: unknown kind {kind:#x}")
    if chunk_offset + 4 + count * lay["size"] > len(section):
        raise FormatError(f"chunk at {chunk_offset:#x}: {count} records run past the section")
    pk = lay["packet"]
    corners = 4 if pk.endswith("4") else 3
    out = []
    for r in range(count):
        o = chunk_offset + 4 + r * lay["size"]

        def w(off, o=o):
            return struct.unpack_from("<I", section, o + off)[0]
        prim = {"kind": kind, "packet": pk, "offset": o,
                "code": lay["code"] if lay["code"] is not None else section[o + 7],
                "uv": [(section[o + u], section[o + u + 1]) for u in _UV[pk]],
                "clut": clut_xy(w(0x0C) >> 16), "tpage": tpage_fields(w(_TPAGE[pk]) >> 16),
                "normals": [struct.unpack_from("<3h", section, o + n) for n in lay["normals"]],
                "double_sided": not lay["cull"], "verts": None, "positions": None}
        if lay["ptrs"] is not None:
            prim["verts"] = [vertex_index(w(lay["ptrs"] + 4 * k)) for k in range(corners)]
        else:
            prim["positions"] = [struct.unpack_from("<3h", section, o + lay["inline"] + 8 * k) for k in range(corners)]
        out.append(prim)
    return out


def chunk_end(section: bytes, chunk_offset: int) -> int:
    count, kind = struct.unpack_from("<HH", section, chunk_offset)
    if kind not in CHUNK_LAYOUTS:
        raise FormatError(f"chunk at {chunk_offset:#x}: unknown kind {kind:#x}")
    return chunk_offset + 4 + count * CHUNK_LAYOUTS[kind]["size"]


def corner_triangles(n: int) -> list[tuple[int, int, int]]:
    """Corner triangles with outward (counter-clockwise, glTF) winding. The GPU draws (0, 1, 2) and (1, 3, 2); in the
    game's right-handed y-down model frame that order's right-hand normal points into the mesh (it agrees with the
    stored lighting normals reversed for 36503 of 36531 lit triangles of the 44 costume models), so it is reversed."""
    return [(0, 2, 1)] if n == 3 else [(0, 2, 1), (1, 2, 3)]


def texture_rect(prim: dict) -> tuple[int, int, int, int]:
    """Inclusive VRAM rectangle (16-bit units) the primitive's UVs sample."""
    tp = prim["tpage"]
    div = {4: 4, 8: 2, 16: 1}[tp["bpp"]]
    us = [u for u, _ in prim["uv"]]
    vs = [v for _, v in prim["uv"]]
    return tp["x"] + min(us) // div, tp["y"] + min(vs), tp["x"] + max(us) // div, tp["y"] + max(vs)


def vram(model: bytes):
    """A 1024 x 512 16-bit VRAM image (numpy uint16) with every TIM of the model file uploaded at its rectangle, and
    a same-sized bool mask of what was uploaded."""
    import numpy as np
    v = np.zeros((512, 1024), np.uint16)
    mask = np.zeros((512, 1024), bool)
    for t in tims(model):
        q = t["offset"] + 8
        for blk in ([t["clut"]] if t["clut"] else []) + [t["image"]]:
            size = struct.unpack_from("<I", model, q)[0]
            x, y, w, h = blk["x"], blk["y"], blk["w"], blk["h"]
            if x + w > 1024 or y + h > 512:
                raise FormatError(f"TIM at {t['offset']:#x}: block {x},{y} {w}x{h} outside VRAM")
            v[y:y + h, x:x + w] = np.frombuffer(model, "<u2", w * h, q + 12).reshape(h, w)
            mask[y:y + h, x:x + w] = True
            q += size
    return v, mask


def texture_page(v, tpage: dict, clut: tuple[int, int]):
    """The 256 x 256 texel page a primitive samples, as RGBA uint8 (PS1 rules: texel 0x0000 is transparent, colour
    bits are 5:5:5 BGR). UV (u, v) of the primitive addresses pixel (u, v) of this page directly."""
    import numpy as np
    x0, y0, bpp = tpage["x"], tpage["y"], tpage["bpp"]
    if bpp == 16:
        cols = v[y0:y0 + 256, x0:x0 + 256]
        page = np.zeros((256, 256), np.uint16)
        page[:cols.shape[0], :cols.shape[1]] = cols
    else:
        per = 16 // bpp
        words = np.zeros((256, 256 // per), np.uint16)
        src = v[y0:y0 + 256, x0:x0 + 256 // per]
        words[:src.shape[0], :src.shape[1]] = src
        idx = np.zeros((256, 256), np.uint16)
        for k in range(per):
            idx[:, k::per] = (words >> (bpp * k)) & ((1 << bpp) - 1)
        cx, cy = clut
        pal = v[cy, cx:cx + (1 << bpp)]
        if len(pal) < (1 << bpp):
            pal = np.concatenate([pal, np.zeros((1 << bpp) - len(pal), np.uint16)])
        page = pal[idx]
    rgba = np.zeros((256, 256, 4), np.uint8)
    rgba[..., 0] = ((page & 0x1F) * 255 + 15) // 31
    rgba[..., 1] = (((page >> 5) & 0x1F) * 255 + 15) // 31
    rgba[..., 2] = (((page >> 10) & 0x1F) * 255 + 15) // 31
    rgba[..., 3] = np.where(page == 0, 0, 255)
    return rgba


def batches(counts: bytes, starts: bytes, slot: int, vertex_total: int, groups: int | None = None) -> list[dict]:
    """Vertex batches (count, first, bone) of mesh slot `slot` from the raw sections 1 (counts) and 2 (starts).
    `groups` (the mesh's group count, which the renderer uses as its part count) selects the 10-part body table."""
    if not 0 <= slot < MESH_SLOTS:
        raise FormatError(f"mesh slot {slot} outside 0..{MESH_SLOTS - 1}")
    n = min(len(counts), len(starts)) // 2
    if (slot + 1) * SLOT_ENTRIES > n:
        return []
    c = struct.unpack_from(f"<{SLOT_ENTRIES}H", counts, 2 * SLOT_ENTRIES * slot)
    s = struct.unpack_from(f"<{SLOT_ENTRIES}H", starts, 2 * SLOT_ENTRIES * slot)
    bones = BODY_10_PARTS if slot == 0 and groups == 10 else BONE_SLOTS[slot]
    out = []
    for i in range(SLOT_ENTRIES):
        if not c[i]:
            continue
        if s[i] + c[i] > vertex_total:
            raise FormatError(f"slot {slot} batch {i}: vertices {s[i]}+{c[i]} beyond {vertex_total}")
        out.append({"part": i, "first": s[i], "count": c[i], "bone": bones[i] if i < len(bones) else None})
    return out


def tims(model: bytes) -> list[dict]:
    """The PS1 TIMs after tim_offset(): mode, CLUT and image rectangles, byte span."""
    p, end, out = tim_offset(model), len(model), []
    while p + 8 <= end:
        magic, flags = struct.unpack_from("<II", model, p)
        if magic != 0x10:
            break
        q, tim = p + 8, {"offset": p, "bpp": (4, 8, 16, 24)[flags & 3], "clut": None}
        blocks = []
        for has in (bool(flags & 8), True):
            if not has:
                continue
            if q + 12 > end:
                raise FormatError(f"TIM at {p:#x}: block header past the end")
            size, x, y, w, h = struct.unpack_from("<IHHHH", model, q)
            if size < 12 or q + size > end:
                raise FormatError(f"TIM at {p:#x}: block of {size:#x} bytes past the end")
            blocks.append({"x": x, "y": y, "w": w, "h": h})
            q += size
        if flags & 8:
            tim["clut"] = blocks[0]
        tim["image"] = blocks[-1]
        tim["size"] = q - p
        out.append(tim)
        p = q
    return out


def model_summary(model: bytes, program_ram: bytes | None = None) -> dict:
    """Counts per section / slot; with program_ram also the expanded meshes and their bone batches."""
    out = {"size": len(model), "tim_offset": tim_offset(model), "tims": len(tims(model)),
           "raw_sections": raw_sections(model)}
    if program_ram is None:
        return out
    secs = unpack_model(model, program_ram)
    out["sections"] = {s: len(b) for s, b in secs.items()}
    meshes = {}
    for slot in range(MESH_SLOTS):
        sec = secs.get(3 + slot)
        if sec is None:
            continue
        m = parse_mesh(sec)
        bs = batches(secs.get(1, b""), secs.get(2, b""), slot, len(m["vertices"]), len(m["groups"]))
        meshes[slot] = {"section": 3 + slot, "vertices": len(m["vertices"]), "groups": len(m["groups"]),
                        "chunks": sum(len(g) for g in m["groups"]),
                        "kinds": sorted({hex(c["kind"]) for g in m["chunks"] for c in g}),
                        "batches": bs, "covered": sum(b["count"] for b in bs)}
    out["meshes"] = meshes
    return out


def main(argv=None) -> int:
    import argparse
    import json
    import os
    from . import doapp_inventory as D
    ap = argparse.ArgumentParser(prog="python -m gbox.doapp_models",
                                 description="Dead Or Alive ++ (doapp) fighter model analysis (no rig: see module doc)")
    ap.add_argument("src", help="directory with doapp.zip + coh1002m.zip")
    ap.add_argument("fighter", help="fighter name or id, e.g. tina, 'lei fang', 13")
    ap.add_argument("--costume", type=int, default=0, choices=range(D.COSTUMES))
    ap.add_argument("--expand", action="store_true", help="decode the program (~40 s) and expand the meshes")
    a = ap.parse_args(argv)
    f = D.fighter(a.fighter)
    index = f["models"][a.costume]
    if a.expand:
        banked, ram, _ = D.decode_owned(a.src)
    else:
        banked, ram = D.merge_parent(os.path.join(a.src, "doapp.zip")), None
    s = model_summary(D.read_file(banked, index), ram)
    print(json.dumps({"fighter": f["name"], "costume": a.costume, "file": index, **s}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
