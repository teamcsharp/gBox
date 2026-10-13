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

Not established, so not produced here: the skeleton (bone hierarchy + rest transforms). The per-bone vertex batches
are in bone-local frames whose axes differ per bone (thighs extend along -z, shins along +z), so the rest pose comes
from the motion evaluator, which has not been located. Without it there is no honest rigged GLB; this module is
therefore not registered as a characters.DEDICATED reader (see docs/doapp_pipeline.md "Status").
"""
from __future__ import annotations

import struct

SECTION_COUNT = 14
PACKED_SECTIONS = frozenset({3, 4, 5, 6, 7, 8, 9, 10, 12})
MESH_SLOTS = 8                     # slot k = section 3 + k (body, then limbs / hands / feet, then accessories)
SLOT_ENTRIES = 13                  # 13 count/start entries and 13 bone bytes per slot
MESH_MARKER = 0x42                 # first word the expander writes
UNPACK_FN = 0x8006C718             # fight loader's section expander (a0 player, a1 src, a2 dest) -> new src
WORK_BASE = 0x801E8000             # player 0 work buffer (0x8008775c[0]); 14 section pointers sit at its start
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
