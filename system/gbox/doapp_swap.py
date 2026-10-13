"""Dead Or Alive ++ (arcade, Tecmo TPS, MAME doapp): any collection character in a fighter's place (ticket #1340).

`characters op=use` routes the Japan set here (slot `<fighter>[:<costume 1-4>]`, or `player` = every costume of every
fighter, so whoever is picked is the character). Everything is built from the owned ROMs, the game's own code and the
collection model; the reverse of gbox.doapp_chars (docs/doapp_pipeline.md "Writer").

1. Target: gbox.doapp_motion.Rig runs the game's fight init and skeleton build for the fighter / costume; the bind
   frames are the 15 body-bone matrices of the stance loop's frame 0 (the reader's bind pose). Each bone's vertex
   batch lives in that bone's frame, so donor vertices are mapped with the inverse stance matrices (game units, y down).
2. Retarget: gbox.sm64_swap.load_rig + retarget (the generic rigid retarget) onto those 15 joints; every vertex
   follows one game bone. Triangles inside one bone become lit gouraud primitives (GT3 0x801a / GT4 0x801b, quads
   paired from triangles); triangles joining two bones of the body slot become the game's seam triangles (0x805a: no
   batch of their own, they reuse the transformed vertices and borrow the lit corner colours of a neighbouring
   primitive through 3 x 2 colour pointers; those primitives are flagged so the drawer lights them even when culled).
   Layout = the game's own 14-group body (Zack / Jann Lee costume 3): slot 0 holds all 13 body bones (arms and feet
   included, so shoulders, elbows, knees and ankles get seams), slots 2 / 4 the hands (three hand shapes sharing one
   mesh), slot 7 (accessory chains) keeps its part count with no geometry, sections 0 / 11 / 12 / 13 are kept.
3. Textures: one 8-bit 256 x H page at VRAM (704, 0) (tpage 0x8b) with a 256-colour CLUT at (0, 496), the costume's own
   texture area and palette row (player 2's copy is offset by the game: tpage |= 0x10, CLUT |= 0x200).
4. Packing: every mesh section is written in the expander's source form (gbox.doapp_swap.pack_mesh, the inverse of
   0x8006c718 chunk kind by chunk kind); expand_mesh is a byte-exact port used for sizes, and the build expands its own
   output with the game's 0x8006c718 on the interpreter and requires identical bytes. Budgets: the loader copies
   exactly the table's size (0x80050420), so a model fits min(file_room, original size); the expanded sections fit the
   player's 0x18000-byte work buffer (player 2's model file is loaded right after player 1's buffer); per-slot vertex
   counts stay within what the game's own models use (scratchpad + spill buffer). Over budget -> Blender decimate when
   the node has Blender, then per-bone vertex clustering, then a smaller texture page.
5. ROM: the model files are written over their table spans in the data ROMs (doapp-1.217 / doapp-2.218, zero padded
   to the table size); the rebuilt set is a new folder <mod>/doapp.zip (+ a copy of coh1002m.zip) - the owned zips are
   only read. Nothing checks the data ROMs: the TPS BIOS verifies only the SCEI licence of the (untouched) program ROMs
   and decodes the program; the game has no ROM test; MAME reports the two changed chips as "incorrect checksum" and
   runs the set.

  python -m gbox.doapp_swap build <dir with doapp.zip + coh1002m.zip> <character dir (meta.json)> <out dir> <slot>
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import time
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

from . import doapp_inventory as D
from . import doapp_models as M

GAME_IDS = {D.GAME_ID_JP: "Dead Or Alive ++ (Japan)"}
SET = "doapp"
M32 = 0xFFFFFFFF

# ---- budgets and VRAM (docs/doapp_pipeline.md "Writer") -------------------------------------------------------------
EXPANDED_LIMIT = 0x18000           # player work buffer: p1 0x801fe800 .. p2's model load 0x80216800; p2 .. spill buffer
FIRST_DEST = 0x3C                  # first section dest of every costume model (after the 14 section pointers)
SLOT_VERTEX_CAP = {0: 395, 2: 82, 4: 82, 7: 66}    # the most any of the 44 costume models uses per slot
TEX_X, TEX_Y = 704, 0              # the costume's texture area (all 44 models: x 704..959, y 0..255)
CLUT_X, CLUT_Y = 0, 496            # its 256-colour palette row (player 2: row 504)
TPAGE = (TEX_X // 64) | (1 << 7)   # 0x8b: page x 704, 8-bit
CLUT = (CLUT_X >> 4) | (CLUT_Y << 6)
CODE_GT3, CODE_GT4 = 0x34, 0x3C    # textured gouraud, opaque
HEIGHTS = (256, 192, 128, 96, 64)  # texture page heights tried (texels)
LEVELS = (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2)       # decimation targets, fractions of SLOT_VERTEX_CAP
QUAD_NORMAL_DOT = 0.9              # two triangles pair into a GT4 when their lighting normals on the edge agree this well
FOOT_BONES = (3, 9)

# game bone per collection role (doapp_chars.BODY); the body slot's part -> bone table (overlay 0x80103ed0)
ROLE_BONE = {"hip": 2, "chest": 0, "head": 1, "l_upper": 8, "l_fore": 4, "l_hand": 5, "r_upper": 14, "r_fore": 10,
             "r_hand": 11, "l_thigh": 6, "l_shin": 7, "l_foot": 3, "r_thigh": 12, "r_shin": 13, "r_foot": 9}
BONE_PARENT = {2: -1, 0: 2, 1: 0, 8: 0, 4: 8, 5: 4, 14: 0, 10: 14, 11: 10, 6: 2, 7: 6, 3: 7, 12: 2, 13: 12, 9: 13}
BODY_BONES = M.BONE_SLOTS[0]       # (0, 1, 2, 6, 7, 12, 13, 4, 8, 10, 14, 3, 9): 13 batches + the seam group
HAND_SLOT = {5: 2, 11: 4}
FLIP = np.array([1.0, -1.0, -1.0])  # game (x, y down, z) <-> retarget frame (left +X, up +Y, front +Z)


class WriterError(ValueError):
    pass


# =============================================================================================== packed stream codec
def put_var(out: bytearray, v: int) -> None:
    """One value of the expander's stream: an even 32-bit value, odd halfword = short form (< 0x10000)."""
    v &= M32
    if v & 1:
        raise WriterError(f"the expander's stream holds even values only ({v:#x})")
    if v < 0x10000:
        out += struct.pack("<H", v | 1)
    else:
        out += struct.pack("<HH", v & 0xFFFE, v >> 16)


def get_var(src, o: int) -> tuple[int, int]:
    h = struct.unpack_from("<H", src, o)[0]
    if h & 1:
        return h & 0xFFFE, o + 2
    return ((h & 0xFFFE) | (struct.unpack_from("<H", src, o + 2)[0] << 16)) & M32, o + 4


SCRATCH, SPILL_BASE = 0x1F800000, 0x802A6410     # vertex value v (= 8 * index): < 0x3f0 scratch, <= 0x803ef spill


def ptr_from_value(v: int) -> int:
    return (v + SCRATCH) & M32 if v < 0x3F0 else (v + SPILL_BASE) & M32 if v <= 0x803EF else v


def value_from_ptr(p: int) -> int:
    if SCRATCH <= p < SCRATCH + 0x3F0:
        return p - SCRATCH
    if SPILL_BASE + 0x3F0 <= p <= SPILL_BASE + 0x803EF:
        return p - SPILL_BASE
    if p > 0x803EF and not p & 1:
        return p
    raise WriterError(f"vertex pointer {p:#010x} has no stream form")


# packet templates of the expander (scratchpad 0x1f800000): tag, colour bytes, depth byte, field offsets, copy size
PACKETS = {
    "GT4": dict(tag=0x0C000000, rgb=(4, 0x10, 0x1C, 0x28), sort=0x13, clut=0x0E, tpage=0x1A, uv=(0x0C, 0x18, 0x24, 0x30),
                copy=0x34),
    "GT3": dict(tag=0x09000000, rgb=(4, 0x10, 0x1C), sort=0x13, clut=0x0E, tpage=0x1A, uv=(0x0C, 0x18, 0x24), copy=0x28),
    "FT4": dict(tag=0x09000000, rgb=(4,), sort=None, clut=0x0E, tpage=0x16, uv=(0x0C, 0x14, 0x1C, 0x24), copy=0x28),
    "FT3": dict(tag=0x07000000, rgb=(4,), sort=None, clut=0x0E, tpage=0x16, uv=(0x0C, 0x14, 0x1C), copy=0x20),
}
# source kind -> (packet, expanded record size, pointers, normals, extra); 0x8038 / 0x8039 expand as 0x8018 / 0x29
KINDS = {
    0x801B: ("GT4", 0x98, 4, 4, None), 0x803B: ("GT4", 0x98, 4, 4, None),
    0x801A: ("GT3", 0x74, 3, 3, None), 0x803A: ("GT3", 0x74, 3, 3, None),
    0x8019: ("FT4", 0x68, 4, 1, None), 0x8018: ("FT3", 0x54, 3, 1, None),
    0x0029: ("FT4", 0x60, 4, 0, None), 0x805A: ("GT3", 0x74, 3, 0, "colours"),
    0x0001: ("FT4", 0x70, 0, 0, "inline"), 0x0000: ("FT3", 0x58, 0, 0, "inline"),
}


def _new_template() -> bytearray:
    return bytearray(0x40)


def _expand_records(kind: int, count: int, src, o: int, out: bytearray, tm: bytearray, player: int,
                    colour_base: int) -> int:
    """One chunk's records, as the expander's per-kind routine writes them (template state included)."""
    pk, size, nptr, nnrm, extra = KINDS[kind]
    lay = PACKETS[pk]
    struct.pack_into("<I", tm, 0, lay["tag"])
    for c in lay["rgb"]:
        tm[c:c + 3] = b"\x80\x80\x80"
    nuv = len(lay["uv"])
    for _ in range(count):
        h = struct.unpack_from(f"<{3 + nuv}H", src, o)
        o += 2 * (3 + nuv)
        tm[7] = h[0] >> 8
        if lay["sort"] is not None:
            tm[lay["sort"]] = h[0] & 0xFF
        clut, tpage = h[1], h[2]
        if player:
            tpage |= 0x10
            if kind != 0x0001:
                clut |= 0x200
        struct.pack_into("<H", tm, lay["clut"], clut)
        struct.pack_into("<H", tm, lay["tpage"], tpage)
        for k, off in enumerate(lay["uv"]):
            struct.pack_into("<H", tm, off, h[3 + k])
        start = len(out)
        out += tm[:lay["copy"]] * 2
        for _k in range(nptr):
            v, o = get_var(src, o)
            out += struct.pack("<I", ptr_from_value(v))
        for k in range(nnrm):
            x, y, z = struct.unpack_from("<3h", src, o)
            o += 6
            pad = 0
            if pk in ("GT3", "GT4") and k == 1:
                pad = struct.unpack_from("<H", src, o)[0]
                o += 2
            out += struct.pack("<3hH", x, y, z, pad)
        if extra == "colours":
            for _k in range(6):
                v, o = get_var(src, o)
                out += struct.pack("<I", (v + colour_base) & M32)
        elif extra == "inline":
            for _k in range(nuv):
                out += struct.pack("<3hH", *struct.unpack_from("<3h", src, o), 0)
                o += 6
        if len(out) - start != size:
            raise AssertionError("record size")
    return o


def expand_mesh(src, off: int, dest_addr: int, player: int = 0, template: bytearray | None = None
                ) -> tuple[bytes, int]:
    """Byte-exact port of the section expander 0x8006c718 (a0 player, a1 source, a2 destination): -> (expanded section,
    source offset after it). template: the scratchpad packet template, carried from section to section like the game
    does (fresh zeros by default, which is what doapp_models.unpack_model's interpreter starts from)."""
    tm = template if template is not None else _new_template()
    out = bytearray(struct.pack("<I", 0x42))
    o = off
    hdr, o = get_var(src, o)
    s1, o = get_var(src, o)
    vtx, o = get_var(src, o)
    s3, o = get_var(src, o)
    out += struct.pack("<II", hdr, vtx)
    ng, o = get_var(src, o)
    ng >>= 2
    out += struct.pack("<I", ng)
    for _g in range(ng):
        n, o = get_var(src, o)
        n >>= 2
        out += struct.pack("<I", n)
        for _k in range(n):
            v, o = get_var(src, o)
            out += struct.pack("<I", v)
    colour_base = (dest_addr + hdr) & M32
    while s1:
        count, kind = struct.unpack_from("<HH", src, o)
        o += 4
        out_kind = {0x8038: 0x8018, 0x8039: 0x0029}.get(kind, kind)
        out += struct.pack("<HH", count, out_kind)
        run = {0x8038: 0x8018, 0x8039: 0x8019}.get(kind, kind)
        if run not in KINDS:
            s1 = (s1 - 4) & M32
            continue
        o = _expand_records(run, count, src, o, out, tm, player, colour_base)
        s1 = (s1 - count * KINDS[run][1] - 4) & M32
        if s1 > 0x7FFFFFFF:
            raise WriterError("chunk sizes overrun the section's chunk byte count")
    while s3:
        out += struct.pack("<3hH", *struct.unpack_from("<3h", src, o), 0)
        o += 6
        s3 = (s3 - 8) & M32
        if s3 > 0x7FFFFFFF:
            raise WriterError("vertex byte count is not a multiple of 8")
    return bytes(out), o


# ---- logical mesh <-> source / expanded -------------------------------------------------------------------------------
def record_fields(sec: bytes, kind: int, ro: int, dest_addr: int, hdr: int) -> dict:
    """The fields of one expanded record that its source form carries (player 1's values)."""
    pk, size, nptr, nnrm, extra = KINDS[kind]
    lay = PACKETS[pk]
    h0 = sec[ro + 7] << 8 | (sec[ro + lay["sort"]] if lay["sort"] is not None else 0)
    r = {"h0": h0, "clut": struct.unpack_from("<H", sec, ro + lay["clut"])[0],
         "tpage": struct.unpack_from("<H", sec, ro + lay["tpage"])[0],
         "uv": [struct.unpack_from("<H", sec, ro + u)[0] for u in lay["uv"]]}
    p = ro + 2 * lay["copy"]
    r["ptrs"] = [value_from_ptr(struct.unpack_from("<I", sec, p + 4 * k)[0]) for k in range(nptr)]
    p += 4 * nptr
    r["normals"], r["npad"] = [], 0
    for k in range(nnrm):
        x, y, z, pad = struct.unpack_from("<3hH", sec, p + 8 * k)
        r["normals"].append((x, y, z))
        if k == 1 and pk in ("GT3", "GT4"):
            r["npad"] = pad
    p += 8 * nnrm
    if extra == "colours":
        r["colours"] = [(struct.unpack_from("<I", sec, p + 4 * k)[0] - dest_addr - hdr) & M32 for k in range(6)]
    elif extra == "inline":
        r["inline"] = [struct.unpack_from("<3h", sec, p + 8 * k) for k in range(len(lay["uv"]))]
    return r


def mesh_from_expanded(sec: bytes, dest_addr: int) -> dict:
    """An expanded mesh section (player 1) -> {hdr, vtx, groups (chunk offsets), chunks [(kind, [records])],
    vertices}: everything its source form holds (the inverse of expand_mesh)."""
    if len(sec) < 16 or struct.unpack_from("<I", sec, 0)[0] != M.MESH_MARKER:
        raise WriterError("not an expanded mesh section (marker 0x42)")
    hdr, vtx, ng = struct.unpack_from("<III", sec, 4)
    p, groups = 16, []
    for _g in range(ng):
        n = struct.unpack_from("<I", sec, p)[0]
        groups.append(list(struct.unpack_from(f"<{n}I", sec, p + 4)))
        p += 4 + 4 * n
    end = vtx if vtx else len(sec)
    chunks = []
    while p < end:
        count, kind = struct.unpack_from("<HH", sec, p)
        if kind not in KINDS:
            raise WriterError(f"chunk kind {kind:#x} at {p:#x} has no source form here")
        size = KINDS[kind][1]
        chunks.append((kind, [record_fields(sec, kind, p + 4 + r * size, dest_addr, hdr) for r in range(count)]))
        p += 4 + count * size
    if p != end:
        raise WriterError(f"chunks end at {p:#x}, the vertex block starts at {end:#x}")
    if (len(sec) - end) % 8:
        raise WriterError("vertex block is not whole SVECTORs")
    vertices = [struct.unpack_from("<3h", sec, o) for o in range(end, len(sec), 8)] if vtx else []
    return {"hdr": hdr, "vtx": vtx, "groups": groups, "chunks": chunks, "vertices": vertices}


def chunk_bytes(chunks) -> int:
    return sum(4 + len(recs) * KINDS[kind][1] for kind, recs in chunks)


def pack_mesh(mesh: dict) -> bytes:
    """The expander's source form of a logical mesh (mesh_from_expanded's shape)."""
    out = bytearray()
    for v in (mesh["hdr"], chunk_bytes(mesh["chunks"]), mesh["vtx"], 8 * len(mesh["vertices"]), 4 * len(mesh["groups"])):
        put_var(out, v)
    for g in mesh["groups"]:
        put_var(out, 4 * len(g))
        for off in g:
            put_var(out, off)
    for kind, recs in mesh["chunks"]:
        pk, _size, nptr, nnrm, extra = KINDS[kind]
        nuv = len(PACKETS[pk]["uv"])
        out += struct.pack("<HH", len(recs), kind)
        for r in recs:
            out += struct.pack(f"<{3 + nuv}H", r["h0"], r["clut"], r["tpage"], *r["uv"])
            if len(r["ptrs"]) != nptr or len(r["normals"]) != nnrm:
                raise WriterError(f"kind {kind:#x}: {len(r['ptrs'])} pointers / {len(r['normals'])} normals")
            for v in r["ptrs"]:
                put_var(out, v)
            for k, n in enumerate(r["normals"]):
                out += struct.pack("<3h", *n)
                if k == 1 and pk in ("GT3", "GT4"):
                    out += struct.pack("<H", r.get("npad", 0))
            if extra == "colours":
                for v in r["colours"]:
                    put_var(out, v)
            elif extra == "inline":
                for v in r["inline"]:
                    out += struct.pack("<3h", *v)
    for v in mesh["vertices"]:
        out += struct.pack("<3h", *v)
    return bytes(out)


def same_mesh(a: dict, b: dict) -> bool:
    """Logical equality: FT packets drop the low byte of their first halfword (the expander never reads it)."""
    def norm(m):
        ch = []
        for kind, recs in m["chunks"]:
            rr = []
            for r in recs:
                r = dict(r)
                if PACKETS[KINDS[kind][0]]["sort"] is None:
                    r["h0"] &= 0xFF00
                rr.append(r)
            ch.append((kind, rr))
        return {**m, "chunks": ch, "vertices": [tuple(v) for v in m["vertices"]]}
    return norm(a) == norm(b)


# =============================================================================================== model container
def walk_container(model: bytes) -> list[dict]:
    """The 14 section records: index, dest, length, start / end of the payload in the file, packed. Packed payload ends
    come from the expander port (the format stores only the expanded length)."""
    end = M.tim_offset(model)
    p, out, tm = 4, [], _new_template()
    for s in range(M.SECTION_COUNT):
        p = (p + 3) & ~3
        dest = struct.unpack_from("<I", model, p)[0]
        if dest == 0:
            out.append({"index": s, "dest": 0, "length": 0, "start": p + 4, "end": p + 4, "packed": False})
            p += 4
            continue
        length = struct.unpack_from("<I", model, p + 4)[0]
        q = p + 8
        if s in M.PACKED_SECTIONS:
            exp, e = expand_mesh(model, q, M.WORK_BASE + dest, template=tm)
            if len(exp) != length:
                raise WriterError(f"section {s}: expands to {len(exp):#x} bytes, the record says {length:#x}")
        else:
            e = q + length
        if e > end:
            raise WriterError(f"section {s} runs past the TIM run")
        out.append({"index": s, "dest": dest, "length": length, "start": q, "end": e, "packed": s in M.PACKED_SECTIONS})
        p = e
    return out


def expand_all(model: bytes, base: int = M.WORK_BASE) -> dict[int, bytes]:
    """{section: expanded bytes} with the expander port, sections in file order, work buffer at `base`
    (doapp_models.unpack_model's result for the default base)."""
    tm, out = _new_template(), {}
    for r in walk_container(model):
        if not r["dest"]:
            continue
        if r["packed"]:
            out[r["index"]] = expand_mesh(model, r["start"], base + r["dest"], template=tm)[0]
        else:
            out[r["index"]] = model[r["start"]:r["end"]]
    return out


GAME_WORK = 0x801FE800             # player 1's work buffer in the game's 4 MiB RAM (0x8008775c[0])
GAME_SOURCE = 0x80300000           # free RAM for the packed file (doapp_motion.Rig.MODEL_SOURCE)


def game_expand_all(model: bytes, program_ram: bytes) -> dict[int, bytes]:
    """{section: expanded bytes} by the game's own 0x8006c718 on gbox.zn_tps_boot's interpreter, in the 4 MiB board
    RAM at player 1's real work buffer, so the whole 0x18000-byte buffer is available (the fight loader's walk)."""
    from . import zn_tps_boot as Z
    mem = Z.ZNMemory(b"\0" * 16, b"", b"\0" * 8, b"\0" * 8, ram_size=0x400000)
    mem.ram[:len(program_ram)] = program_ram
    src = GAME_SOURCE & 0x3FFFFF
    mem.ram[src:src + len(model)] = model
    cpu = Z.R3000(mem)
    out = {}
    for r in walk_container(model):
        if not r["dest"]:
            continue
        if r["dest"] + r["length"] > EXPANDED_LIMIT:
            raise WriterError(f"section {r['index']} ends at {r['dest'] + r['length']:#x}, past the work buffer")
        w = (GAME_WORK + r["dest"]) & 0x3FFFFF
        if r["packed"]:
            q = cpu.call(M.UNPACK_FN, (0, GAME_SOURCE + r["start"], GAME_WORK + r["dest"]), sp=0x803FFF00,
                         limit=20_000_000) - GAME_SOURCE
            if q != r["end"]:
                raise WriterError(f"section {r['index']}: the game's expander stopped at {q:#x}, not {r['end']:#x}")
        else:
            mem.ram[w:w + r["length"]] = model[r["start"]:r["end"]]
        out[r["index"]] = bytes(mem.ram[w:w + r["length"]])
    return out


def build_container(sections: dict[int, tuple[int, bytes]], tim_run: bytes) -> bytes:
    """{section: (expanded length, payload as stored)} + TIM run -> model file: u32 TIM offset, 14 records
    {u32 dest, u32 length, payload} (4-byte aligned; dest 0 = absent), u32 expanded extent, u32 TIM bytes, TIMs.
    Dests are laid out from FIRST_DEST, 4-byte aligned."""
    out = bytearray(4)
    dest, extent = FIRST_DEST, 0
    for s in range(M.SECTION_COUNT):
        out += bytes(-len(out) % 4)
        if s not in sections:
            out += struct.pack("<I", 0)
            continue
        length, payload = sections[s]
        out += struct.pack("<II", dest, length) + payload
        extent = dest + length
        dest = (extent + 3) & ~3
    out += bytes(-len(out) % 4)
    out += struct.pack("<II", extent, len(tim_run))
    struct.pack_into("<I", out, 0, len(out))
    return bytes(out + tim_run)


def extent_of(sections: dict[int, tuple[int, bytes]]) -> int:
    dest = FIRST_DEST
    ext = 0
    for s in sorted(sections):
        ext = dest + sections[s][0]
        dest = (ext + 3) & ~3
    return ext


def tim8(x: int, y: int, idx: np.ndarray, clut: list[int], cx: int, cy: int) -> bytes:
    """An 8-bit PS1 TIM (flags 9: CLUT present) of an index image (h x w, w even) at VRAM (x, y), CLUT at (cx, cy)."""
    h, w = idx.shape
    if w % 2 or len(clut) != 256:
        raise WriterError("8-bit TIM: even width and a 256-entry CLUT")
    cl = struct.pack("<IHHHH", 12 + 512, cx, cy, 256, 1) + struct.pack("<256H", *clut)
    im = struct.pack("<IHHHH", 12 + w * h, x, y, w // 2, h) + np.ascontiguousarray(idx, np.uint8).tobytes()
    return struct.pack("<II", 0x10, 9) + cl + im


def tim_bytes(height: int) -> int:
    return 8 + 12 + 512 + 12 + 256 * height


# =============================================================================================== texture page
def _c15(rgb) -> int:
    r, g, b = (int(v) >> 3 for v in rgb[:3])
    return (r | g << 5 | b << 10) or 0x8000              # 0x0000 is see-through on the PS1: opaque black instead


class Page:
    """Donor materials -> one 256 x height RGBA page (textures scaled to share it, 1-texel borders, flat colours as
    4 x 4 cells), quantized to one 256-colour CLUT (index 0 = see-through when a material has cut-out alpha)."""

    def __init__(self, height: int):
        self.h = height
        self.rgba = np.zeros((height, 256, 4), np.uint8)
        self.used = np.zeros((height, 256), bool)
        self.mat: dict = {}

    @staticmethod
    def key(p: dict):
        t = p.get("tex")
        return (hashlib.sha1(np.ascontiguousarray(t).tobytes()).hexdigest() if t is not None else None,
                tuple(int(c) for c in p["color"][:4]))

    def build(self, prims: list[dict]) -> None:
        mats, uses = {}, Counter()
        for p in prims:
            k = self.key(p)
            mats.setdefault(k, p)
            uses[k] += len(p["tris"])
        tex = [k for k in mats if mats[k].get("tex") is not None]
        flat = [k for k in mats if mats[k].get("tex") is None]
        area = 256 * self.h - 36 * len(flat)
        sizes = {k: np.asarray(mats[k]["tex"]).shape[:2] for k in tex}
        need = sum((h + 2) * (w + 2) for h, w in sizes.values()) or 1
        s = min(1.0, (0.8 * area / need) ** 0.5)
        for _ in range(40):
            try:
                self._pack(mats, tex, flat, sizes, s)
                return
            except WriterError:
                s *= 0.85
        raise WriterError(f"{len(mats)} materials don't fit a 256 x {self.h} page")

    def _pack(self, mats, tex, flat, sizes, s) -> None:
        from PIL import Image
        self.rgba[:] = 0
        self.used[:] = False
        self.mat = {}
        x = y = row = 0
        dims = {}
        for k in tex:
            h, w = sizes[k]
            dims[k] = (max(2, min(128, int(h * s))), max(2, min(128, int(w * s))))
        order = sorted(tex, key=lambda k: -dims[k][0]) + flat
        for k in order:
            h, w = dims.get(k, (4, 4))
            bw, bh = (w + 2, h + 2) if k in dims else (4, 4)
            if x + bw > 256:
                x, y, row = 0, y + row, 0
            if y + bh > self.h:
                raise WriterError("page full")
            p = mats[k]
            col = np.array(p["color"][:4], float) / 255
            if k in dims:
                img = np.asarray(p["tex"], np.uint8)
                if img.ndim == 2:
                    img = np.stack([img] * 3 + [np.full_like(img, 255)], -1)
                if img.shape[2] == 3:
                    img = np.concatenate([img, np.full(img.shape[:2] + (1,), 255, np.uint8)], -1)
                img = np.asarray(Image.fromarray(img, "RGBA").resize((w, h), Image.BILINEAR), np.uint8).copy()
                img[..., :3] = (img[..., :3] * col[:3]).astype(np.uint8)
                self.rgba[y:y + bh, x:x + bw] = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
                self.mat[k] = ("tex", x + 1, y + 1, w, h, p.get("wrap", (10497, 10497)))
            else:
                self.rgba[y:y + 4, x:x + 4] = np.clip(np.r_[col[:3] * 255, 255], 0, 255).astype(np.uint8)
                self.mat[k] = ("flat", x + 1, y + 1)
            self.used[y:y + bh, x:x + bw] = True
            x += bw
            row = max(row, bh)

    def uv(self, key, uv: np.ndarray) -> np.ndarray:
        """Triangle UVs (n, 3, 2) of a material -> page texels (n, 3, 2). Repeat-wrapped triangles are shifted by whole
        tiles into [0, 1] when they span less than one tile (the PS1 has no wrap inside a page), then clamped."""
        m = self.mat[key]
        if m[0] == "flat":
            return np.tile(np.array([m[1] + 1, m[2] + 1]), (len(uv), 3, 1))
        _t, x, y, w, h, wrap = m
        uv = np.array(uv, float)
        for a in (0, 1):
            if wrap[a] != 33071:
                lo = np.floor(uv[:, :, a].min(1) + 1e-6)
                fits = uv[:, :, a].max(1) - lo <= 1 + 1e-6
                uv[:, :, a] -= np.where(fits, lo, 0)[:, None]
        uv = np.clip(uv, 0, 1)
        return np.stack([np.round(x + uv[..., 0] * (w - 1)), np.round(y + uv[..., 1] * (h - 1))], -1).astype(int)

    def indexed(self) -> tuple[np.ndarray, list[int]]:
        from PIL import Image
        cut = self.used & (self.rgba[..., 3] < 128)
        n = 255 if cut.any() else 256
        rgb = self.rgba[..., :3].copy()
        live = self.used & ~cut
        if live.any():                                    # unused texels don't spend palette entries
            rgb[~live] = rgb[live][0]
        q = Image.fromarray(np.ascontiguousarray(rgb), "RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()[:3 * n]
        cl = [_c15(pal[3 * i:3 * i + 3]) for i in range(len(pal) // 3)]
        cl += [0x8000] * (n - len(cl))
        idx = np.asarray(q, np.uint8).astype(np.int32)
        if n == 255:
            idx = np.where(cut, 0, idx + 1)
            cl = [0x0000] + cl
        return idx.astype(np.uint8), cl


# =============================================================================================== target (the game)
def game_matrix(m) -> np.ndarray:
    rot, t = m
    G = np.eye(4)
    G[:3, :3] = np.array(rot, float).reshape(3, 3) / 4096.0
    G[:3, 3] = t
    return G


def target(program_ram: bytes, banked: bytes, fighter: dict, costume: int, rig=None) -> dict:
    """The fighter / costume the character replaces: bind matrices (stance frame 0, the reader's bind pose), joint
    positions in the retarget frame, ground and head size of the original mesh, the original model and its sections."""
    from . import doapp_chars as R
    from . import doapp_motion as DM
    rig = rig or DM.Rig(program_ram, banked, fighter, costume)
    pose = rig.rest_pose()
    a = R.assemble(rig.sections(), rig.model, pose, rig.hand_shapes(), R.chains(program_ram, fighter["id"], costume))
    return target_from(pose, a["tris"], rig.model, fighter, costume)


def target_from(pose: list, tris: list[dict], model: bytes, fighter: dict, costume: int) -> dict:
    G = [game_matrix(m) for m in pose[:15]]
    T = np.array([G[b][:3, 3] * FLIP for b in range(15)])
    game_y = np.concatenate([t["pos"][:, 1] for t in tris])
    head = [t["pos"][k, 1] for t in tris for k in range(3) if t["bones"][k] == 1]
    return {"G": G, "T": T, "ground": float(-game_y.max()), "height": float(np.ptp(game_y)),
            "head_h": float(np.ptp(head)) if head else 250.0, "parent": [BONE_PARENT[b] for b in range(15)],
            "joints": 15, "model": model, "fighter": fighter, "costume": costume,
            "file": fighter["models"][costume]}


def fit_feet(prims: list[dict], tgt: dict) -> dict:
    """Soles on the fighter's ground: the retarget fits the head height and the limb directions, so a donor's feet can
    end below the floor or above it; each foot bone's vertices are scaled vertically about its ankle (0.5..1.5) so
    the lowest one lands on the original model's ground. -> {foot bone: scale}."""
    out = {}
    for bone in FOOT_BONES:
        ys = [np.asarray(p["pos"])[np.asarray(p["J"])[:, 0] == bone, 1] for p in prims]
        ys = np.concatenate(ys) if ys else np.zeros(0)
        if not len(ys):
            continue
        ankle, lo = float(tgt["T"][bone][1]), float(ys.min())
        if ankle - lo < 1 or abs(lo - tgt["ground"]) < 2:
            continue
        k = float(np.clip((ankle - tgt["ground"]) / (ankle - lo), 0.5, 1.5))
        for p in prims:
            m = np.asarray(p["J"])[:, 0] == bone
            if m.any():
                p["pos"] = np.array(p["pos"], float)
                p["pos"][m, 1] = ankle + (p["pos"][m, 1] - ankle) * k
        out[bone] = round(k, 3)
    return out


# =============================================================================================== geometry
def _slot_of(bone: int) -> int:
    return HAND_SLOT.get(bone, 0)


def triangles(prims: list[dict]) -> dict:
    """Retargeted prims -> per-triangle arrays: bone per corner (n, 3), game positions (n, 3, 3), game normals, and
    per prim its material and UVs (page texels come from page_uvs). Triangles spanning a hand and its forearm go
    rigidly to the majority bone (hands are their own slots, so only body-slot triangles can be seams)."""
    bones, pos, nrm, uvs, mats, keys = [], [], [], [], [], []
    for p in prims:
        t = np.asarray(p["tris"], int).reshape(-1, 3)
        if not len(t):
            continue
        J = np.asarray(p["J"])[:, 0] if np.ndim(p["J"]) == 2 else np.asarray(p["J"])
        k = Page.key(p)
        if k not in keys:
            keys.append(k)
        bones.append(J[t].astype(int))
        pos.append(np.asarray(p["pos"], float)[t] * FLIP)
        nrm.append(np.asarray(p["nrm"], float)[t] * FLIP)
        uvs.append(np.asarray(p["uv"], float)[t])
        mats.append(np.full(len(t), keys.index(k)))
    if not bones:
        raise WriterError("the character has no triangles")
    B, P, N, UV, MT = (np.concatenate(x) for x in (bones, pos, nrm, uvs, mats))
    if B.min() < 0 or B.max() >= 15:
        raise WriterError("a vertex follows no body bone")
    slots = np.vectorize(_slot_of)(B)
    mixed = ~((slots == slots[:, :1]).all(1))
    for i in np.nonzero(mixed)[0]:
        c = Counter(int(s) for s in slots[i])
        s = max(c, key=lambda k: (c[k], k == 0))
        keep = [int(b) for b in B[i] if _slot_of(int(b)) == s]
        B[i] = Counter(keep).most_common(1)[0][0]
    return {"bones": B, "pos": P, "nrm": N, "uv": UV, "mat": MT, "keys": keys, "moved_to_one_bone": int(mixed.sum())}


def page_uvs(tri: dict, page: Page) -> np.ndarray:
    out = np.zeros(tri["uv"].shape, int)
    for m, k in enumerate(tri["keys"]):
        sel = tri["mat"] == m
        if sel.any():
            out[sel] = page.uv(k, tri["uv"][sel])
    return out


def _quadric(n: np.ndarray, p: np.ndarray, w: float) -> np.ndarray:
    v = np.r_[n, -float(n @ p)]
    return np.outer(v, v) * w


def decimate(tri: dict, caps: dict[int, int], weld: float = 0.05) -> dict:
    """Quadric-error half-edge collapse (no Blender needed) until every slot's vertex count is within `caps`.
    Vertices are welded per bone (glTF splits them at UV / material seams), only edges inside one bone collapse (the
    rigid one-bone-per-vertex skinning and the seams between bones stay), a vertex always collapses onto a neighbour
    (no new positions), collapses that would flip a face are refused, open borders carry extra planes, and the moved
    corners take the texel / normal of their target from a removed face of the same material and UV chart."""
    import heapq
    B, P = tri["bones"], tri["pos"]
    n = len(B)
    key = np.concatenate([B.reshape(-1, 1), np.round(P.reshape(-1, 3) / weld).astype(np.int64)], 1)
    uniq, vid = np.unique(key, axis=0, return_inverse=True)
    vid = vid.reshape(n, 3)
    V = np.zeros((len(uniq), 3))
    V[vid.reshape(-1)] = P.reshape(-1, 3)
    vb = uniq[:, 0].astype(int)
    vslot = np.vectorize(_slot_of)(vb) if len(vb) else np.zeros(0, int)
    UV, NR, MT = tri["uv"].copy(), tri["nrm"].copy(), tri["mat"]
    F = [list(map(int, f)) for f in vid]
    alive = np.array([len(set(f)) == 3 for f in F])
    vf: list[set] = [set() for _ in range(len(V))]
    for i, f in enumerate(F):
        if alive[i]:
            for v in f:
                vf[v].add(i)
    Q = np.zeros((len(V), 4, 4))
    edges = Counter()
    for i, f in enumerate(F):
        if not alive[i]:
            continue
        a, b, c = V[f]
        nn = np.cross(b - a, c - a)
        area = np.linalg.norm(nn)
        if area < 1e-12:
            continue
        nn /= area
        K = _quadric(nn, a, area)
        for v in f:
            Q[v] += K
        for k in range(3):
            edges[tuple(sorted((f[k], f[(k + 1) % 3])))] += 1
    for (a, b), cnt in edges.items():                     # open borders: a plane through the edge, across the face
        if cnt != 1:
            continue
        i = next(iter(vf[a] & vf[b]))
        f = F[i]
        p0, p1, p2 = V[f]
        fn = np.cross(p1 - p0, p2 - p0)
        e = V[b] - V[a]
        bn = np.cross(e, fn)
        ln = np.linalg.norm(bn)
        if ln > 1e-12:
            K = _quadric(bn / ln, V[a], 10.0 * float(e @ e))
            Q[a] += K
            Q[b] += K
    live = np.zeros(len(V), bool)
    if alive.any():
        live[np.unique(np.array([F[i] for i in np.nonzero(alive)[0]]).reshape(-1))] = True
    count = {s: int((live & (vslot == s)).sum()) for s in (0, 2, 4)}
    ver = np.zeros(len(V), int)
    heap = []

    def cost(v, u):
        x = np.r_[V[u], 1.0]
        return float(x @ (Q[u] + Q[v]) @ x)

    def push(a, b):
        if a != b and vb[a] == vb[b]:
            heapq.heappush(heap, (cost(a, b), a, b, ver[a], ver[b]))
            heapq.heappush(heap, (cost(b, a), b, a, ver[b], ver[a]))
    for (a, b) in edges:
        push(a, b)
    collapses = 0
    while heap and any(count[s] > caps.get(s, 1 << 30) for s in count):
        _c, v, u, va, ua = heapq.heappop(heap)
        if not (live[v] and live[u]) or ver[v] != va or ver[u] != ua or count[vslot[v]] <= caps.get(vslot[v], 1 << 30):
            continue
        both = vf[v] & vf[u]
        if not both:
            continue
        ok = True
        for i in vf[v] - both:                            # the faces that move: no flips, no slivers
            f = F[i]
            a, b, c = V[f]
            n0 = np.cross(b - a, c - a)
            g = [u if x == v else x for x in f]
            a, b, c = V[g]
            n1 = np.cross(b - a, c - a)
            if float(n0 @ n1) <= 0.2 * np.linalg.norm(n0) * np.linalg.norm(n1) or np.linalg.norm(n1) < 1e-9:
                ok = False
                break
        if not ok:
            continue
        removed = [(MT[i], UV[i][F[i].index(v)], UV[i][F[i].index(u)], NR[i][F[i].index(u)]) for i in both]
        for i in vf[v] - both:
            k = F[i].index(v)
            for m, uvv, uvu, nu in removed:
                if m == MT[i] and np.abs(uvv - UV[i][k]).max() < 1e-4:
                    UV[i][k], NR[i][k] = uvu, nu
                    break
            F[i][k] = u
            vf[u].add(i)
        for i in both:
            alive[i] = False
            for x in F[i]:
                vf[x].discard(i)
        vf[v] = set()
        live[v] = False
        count[vslot[v]] -= 1
        Q[u] += Q[v]
        ver[u] += 1
        collapses += 1
        for w in {x for i in vf[u] for x in F[i]} - {u}:
            push(u, w)
    keep = np.nonzero(alive)[0]
    Fa = np.array([F[i] for i in keep], int).reshape(-1, 3)
    return {"bones": vb[Fa], "pos": V[Fa], "nrm": NR[keep], "uv": UV[keep], "mat": MT[keep], "keys": tri["keys"],
            "moved_to_one_bone": tri.get("moved_to_one_bone", 0), "collapses": collapses,
            "slot_vertices": count}


def quantize(tri: dict, tgt: dict, grid: int) -> dict:
    """Corners in their bone's frame (inverse bind matrix), clustered to `grid` game units: unique (bone, x, y, z)
    vertices, per-corner vertex ids, non-degenerate triangles, 4.12 corner normals; vertex count per slot."""
    frames = local_frames(tgt)
    B, P, N = tri["bones"], tri["pos"], tri["nrm"]
    Rinv = np.array([f[0] for f in frames])
    Tb = np.array([f[1] for f in frames])
    L = np.einsum("nkij,nkj->nki", Rinv[B], P - Tb[B])
    Q = np.clip(np.round(L / grid) * grid, -32768, 32767).astype(np.int64)
    LN = np.einsum("nkij,nkj->nki", Rinv[B], N)
    LN /= np.maximum(np.linalg.norm(LN, axis=2, keepdims=True), 1e-9)
    QN = np.clip(np.round(LN * 4096), -4096, 4096).astype(int)
    keys = np.concatenate([B[..., None], Q], 2).reshape(-1, 4)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1, 3)
    ok = (inv[:, 0] != inv[:, 1]) & (inv[:, 1] != inv[:, 2]) & (inv[:, 0] != inv[:, 2])
    used = np.unique(inv[ok])
    slot_of = np.vectorize(_slot_of)(uniq[used, 0]) if len(used) else np.zeros(0, int)
    counts = {s: int((slot_of == s).sum()) for s in (0, 2, 4)}
    return {"grid": grid, "uniq": uniq, "inv": inv, "ok": ok, "QN": QN, "counts": counts}


def local_frames(tgt: dict) -> list[tuple[np.ndarray, np.ndarray]]:
    """Per body bone: (inverse rotation, translation) of its bind matrix (game frame)."""
    return [(np.linalg.inv(G[:3, :3]), G[:3, 3]) for G in tgt["G"]]


def _close(n1, n2) -> bool:
    return n1 == n2 or float(np.dot(n1, n2)) >= QUAD_NORMAL_DOT * 4096 * 4096


def _mean_normal(n1, n2) -> tuple:
    if n1 == n2:
        return n1
    v = np.add(n1, n2, dtype=float)
    return tuple(int(x) for x in np.round(v / (np.linalg.norm(v) or 1) * 4096))


def pair_quads(tris: list[dict]) -> tuple[list[dict], list[dict]]:
    """Lit triangles of one bone (drawing order) -> (quads, leftover triangles). Two triangles sharing an edge with
    the same texels on it (and lighting normals within QUAD_NORMAL_DOT) become one GT4 drawn as (0, 1, 2) + (1, 3, 2):
    exactly the same two triangles, 0x98 expanded bytes instead of 2 x 0x74."""
    edges: dict = {}
    for i, t in enumerate(tris):
        for k in range(3):
            edges.setdefault((t["v"][k], t["v"][(k + 1) % 3]), []).append((i, k))
    used, quads, rest = set(), [], []
    for i, t in enumerate(tris):
        if i in used:
            continue
        hit = None
        for k in range(3):
            a, b = t["v"][k], t["v"][(k + 1) % 3]
            for j, kk in edges.get((b, a), []):
                q = tris[j]
                if j == i or j in used:
                    continue
                if q["uv"][kk] != t["uv"][(k + 1) % 3] or q["uv"][(kk + 1) % 3] != t["uv"][k]:
                    continue
                if not (_close(q["n"][kk], t["n"][(k + 1) % 3]) and _close(q["n"][(kk + 1) % 3], t["n"][k])):
                    continue
                hit = (k, j, kk)
                break
            if hit:
                break
        if not hit:
            rest.append(t)
            continue
        k, j, kk = hit
        q = tris[j]
        used |= {i, j}
        x, ia, ib, d = (k + 2) % 3, k, (k + 1) % 3, (kk + 2) % 3
        quads.append({"v": [t["v"][x], t["v"][ia], t["v"][ib], q["v"][d]],
                      "uv": [t["uv"][x], t["uv"][ia], t["uv"][ib], q["uv"][d]],
                      "n": [t["n"][x], _mean_normal(t["n"][ia], q["n"][(kk + 1) % 3]),
                            _mean_normal(t["n"][ib], q["n"][kk]), q["n"][d]]})
    return quads, rest


def _uvw(t) -> int:
    u, v = int(t[0]), int(t[1])
    return (u & 0xFF) | (v & 0xFF) << 8


def _lit_record(prim: dict, code: int, base: int) -> dict:
    n = len(prim["v"])
    uv = [_uvw(c) for c in prim["uv"]]
    if len(uv) != n:
        raise AssertionError("corner count")
    return {"h0": code << 8, "clut": CLUT, "tpage": TPAGE, "uv": uv,
            "ptrs": [8 * (base + v) for v in prim["v"]], "normals": [tuple(x) for x in prim["n"]], "npad": 0}


def build_geometry(tri: dict, UV: np.ndarray, q: dict, slot7_groups: int = 0) -> dict:
    """Triangles (triangles()), their page texels and a quantization (quantize()) -> the meshes of slots 0, 2, 4 (and
    an empty slot 7), the batch tables and a report."""
    grid, uniq, inv, ok, QN = q["grid"], q["uniq"], q["inv"], q["ok"], q["QN"]
    B = tri["bones"]
    # glTF counter-clockwise (a, b, c) -> drawing order (a, c, b) (doapp_models.corner_triangles)
    order = [0, 2, 1]
    per_bone_v: dict[int, dict[int, int]] = {b: {} for b in range(15)}
    vert_list: dict[int, list] = {b: [] for b in range(15)}

    def vid(u: int) -> tuple[int, int]:
        b = int(uniq[u, 0])
        d = per_bone_v[b]
        if u not in d:
            d[u] = len(vert_list[b])
            vert_list[b].append(tuple(int(x) for x in uniq[u, 1:]))
        return b, d[u]
    lit = {b: [] for b in range(15)}
    seams = []
    for i in np.nonzero(ok)[0]:
        cs = [vid(int(inv[i, k])) for k in order]
        uvs = [tuple(int(x) for x in UV[i, k]) for k in order]
        ns = [tuple(int(x) for x in QN[i, k]) for k in order]
        if len({c[0] for c in cs}) == 1:
            lit[cs[0][0]].append({"v": [c[1] for c in cs], "uv": uvs, "n": ns})
        else:
            seams.append({"c": cs, "uv": uvs})
    report = {"grid": grid, "source_triangles": int(len(B)), "degenerate": int((~ok).sum()),
              "moved_to_one_bone": tri.get("moved_to_one_bone", 0)}
    meshes, tables = {}, {}
    # ---- slot 0: 13 bone batches + the seam group
    first, base = {}, 0
    for b in BODY_BONES:
        first[b] = base
        base += len(vert_list[b])
    groups, chunks, recs_of = [], [], {}
    for p, b in enumerate(BODY_BONES):
        quads, rest = pair_quads(lit[b])
        g = []
        for kind, prims, code in ((0x801B, quads, CODE_GT4), (0x801A, rest, CODE_GT3)):
            if prims:
                recs = [_lit_record(q, code, first[b]) for q in prims]
                recs_of[(b, kind)] = (len(chunks), prims)
                g.append(len(chunks))
                chunks.append((kind, recs))
        groups.append(g)
    seam_recs = []
    corner_users: dict[tuple[int, int], list] = {}
    for (b, kind), (ci, prims) in recs_of.items():
        for ri, q in enumerate(prims):
            for k, v in enumerate(q["v"]):
                corner_users.setdefault((b, v), []).append((ci, ri, k))
    for s in seams:
        src = []
        for b, v in s["c"]:
            users = corner_users.get((b, v))
            if not users:                                 # nobody lights this vertex: the nearest lit corner of its bone
                cand = [((np.subtract(vert_list[bb][vv], vert_list[b][v]) ** 2).sum(), (bb, vv))
                        for (bb, vv) in corner_users if bb == b] or \
                       [((np.subtract(vert_list[bb][vv], vert_list[b][v]) ** 2).sum(), (bb, vv)) for (bb, vv) in corner_users]
                if not cand:
                    src = None
                    break
                users = corner_users[min(cand)[1]]
            src.append(users[0])
        if src is None:
            continue
        seam_recs.append({"h0": CODE_GT3 << 8, "clut": CLUT, "tpage": TPAGE, "uv": [_uvw(c) for c in s["uv"]],
                          "ptrs": [8 * (first[b] + v) for b, v in s["c"]], "normals": [], "npad": 0, "_src": src})
    if seam_recs:
        groups.append([len(chunks)])
        chunks.append((0x805A, seam_recs))
    meshes[0] = _layout(groups, chunks, [v for b in BODY_BONES for v in vert_list[b]])
    if seam_recs:                                         # colour pointers: the source corners' rgb, both packet copies
        mesh = meshes[0]
        offs = _chunk_offsets(mesh)
        for r in seam_recs:
            cols, src = [], r.pop("_src")
            for buf in (0, 1):
                for ci, ri, k in src:
                    kind = chunks[ci][0]
                    lay = PACKETS[KINDS[kind][0]]
                    ro = offs[ci] + 4 + ri * KINDS[kind][1]
                    cols.append(ro + buf * lay["copy"] + lay["rgb"][k] - mesh["hdr"])
                    chunks[ci][1][ri]["npad"] = 1        # lit even when culled: a seam borrows its colours
            r["colours"] = cols
    tables[0] = [(len(vert_list[b]), first[b]) for b in BODY_BONES]
    # ---- hands: three hand shapes drawing one mesh
    for bone, slot in HAND_SLOT.items():
        quads, rest = pair_quads(lit[bone])
        chunks = []
        for kind, prims, code in ((0x801B, quads, CODE_GT4), (0x801A, rest, CODE_GT3)):
            if prims:
                chunks.append((kind, [_lit_record(q, code, 0) for q in prims]))
        verts = vert_list[bone] or [(0, 0, 0)]
        meshes[slot] = _layout([list(range(len(chunks)))] * 3, chunks, verts)
        tables[slot] = [(len(verts), 0)] * 3
    if slot7_groups:                                      # accessory chains: the game's part count, nothing drawn
        meshes[7] = _layout([[] for _ in range(slot7_groups)], [], [(0, 0, 0)])
        tables[7] = [(1, 0)] * slot7_groups
    report.update(vertices={s: len(m["vertices"]) for s, m in meshes.items()},
                  triangles=sum(len(lit[b]) for b in range(15)) + len(seam_recs),
                  quads=sum(len(r) for s in (0,) for k, r in meshes[0]["chunks"] if k == 0x801B),
                  seam_triangles=len(seam_recs), seams_dropped=len(seams) - len(seam_recs),
                  bone_vertices={int(b): len(vert_list[b]) for b in range(15)})
    return {"meshes": meshes, "tables": tables, "report": report}


def _chunk_offsets(mesh: dict) -> list[int]:
    p, offs = mesh["hdr"], []
    for kind, recs in mesh["chunks"]:
        offs.append(p)
        p += 4 + len(recs) * KINDS[kind][1]
    return offs


def _layout(groups: list[list[int]], chunks: list, vertices: list) -> dict:
    """Groups of chunk indices -> a logical mesh with the expanded offsets filled in."""
    hdr = 16 + sum(4 + 4 * len(g) for g in groups)
    mesh = {"hdr": hdr, "groups": [], "chunks": chunks, "vertices": [tuple(v) for v in vertices]}
    offs = _chunk_offsets(mesh)
    mesh["groups"] = [[offs[c] for c in g] for g in groups]
    mesh["vtx"] = hdr + chunk_bytes(chunks)
    return mesh


def batch_tables(tables: dict[int, list], slots: int) -> tuple[bytes, bytes]:
    """Sections 1 / 2: u16 vertex count / first vertex per (slot, part), 13 per slot."""
    counts = [0] * (M.SLOT_ENTRIES * slots)
    starts = [0] * (M.SLOT_ENTRIES * slots)
    for slot, parts in tables.items():
        for p, (n, f) in enumerate(parts):
            counts[M.SLOT_ENTRIES * slot + p] = n
            starts[M.SLOT_ENTRIES * slot + p] = f
    return struct.pack(f"<{len(counts)}H", *counts), struct.pack(f"<{len(starts)}H", *starts)


def mesh_bytes(mesh: dict) -> int:
    """Expanded size of a logical mesh."""
    return mesh["vtx"] + 8 * len(mesh["vertices"])


# =============================================================================================== one model file
def model_file(geo: dict, tgt: dict, page: Page) -> tuple[bytes, dict]:
    """Geometry + page + the original model's kept sections -> the new model file and its sections (expanded)."""
    orig = tgt["model"]
    recs = {r["index"]: r for r in walk_container(orig)}
    sections: dict[int, tuple[int, bytes]] = {}
    for s in (0, 11, 12, 13):                            # physics offsets, raw data, effect quads: kept as they are
        r = recs[s]
        if r["dest"]:
            sections[s] = (r["length"], orig[r["start"]:r["end"]])
    nslots = recs[1]["length"] // (2 * M.SLOT_ENTRIES) if recs[1]["dest"] else 8
    c, f = batch_tables(geo["tables"], nslots)
    sections[1] = (len(c), c)
    sections[2] = (len(f), f)
    for slot, mesh in geo["meshes"].items():
        sections[3 + slot] = (mesh_bytes(mesh), pack_mesh(mesh))
    idx, clut = page.indexed()
    tim = tim8(TEX_X, TEX_Y, idx, clut, CLUT_X, CLUT_Y)
    data = build_container(sections, tim)
    return data, {"extent": extent_of(sections), "tim_bytes": len(tim)}


def budget(file_index: int) -> int:
    """Bytes a replacement model may use: the loader copies exactly the table's size (0x80050420), and the file can't
    grow past the next file either."""
    return min(D.file_room(file_index), D.FILE_TABLE[file_index][2])


def fit(prims: list[dict], tgt: dict, progress=lambda p, m: None) -> dict:
    """Retargeted prims -> the finest model that fits: vertex caps per slot, the work buffer, the file's bytes."""
    room = budget(tgt["file"])
    recs = {r["index"]: r for r in walk_container(tgt["model"])}
    slot7 = 0
    if recs[10]["dest"]:
        slot7 = len(M.parse_mesh(expand_all(tgt["model"])[10])["groups"])
    kept = sum(recs[s]["length"] for s in (0, 11, 12, 13) if recs[s]["dest"])
    last = None
    pages, levels = {}, []
    tri = triangles(prims)
    for heights in (HEIGHTS[:3], HEIGHTS[3:]):
        for k, level in enumerate(LEVELS):
            if k == len(levels):                          # decimate further from the previous level
                caps = {s: max(8, int(SLOT_VERTEX_CAP[s] * level)) for s in (0, 2, 4)}
                levels.append(decimate(levels[-1] if levels else tri, caps))
            dec = levels[k]
            q = quantize(dec, tgt, 1)
            if any(n > SLOT_VERTEX_CAP[s] for s, n in q["counts"].items()):
                last = {"level": level, "vertices": q["counts"], "caps": SLOT_VERTEX_CAP}
                continue
            for h in heights:
                if h not in pages:
                    pages[h] = Page(h)
                    pages[h].build(prims)
                page = pages[h]
                geo = build_geometry(dec, page_uvs(dec, page), q, slot7)
                rep = geo["report"]
                expanded = kept + sum(mesh_bytes(m) for m in geo["meshes"].values()) + 0x200
                if expanded > EXPANDED_LIMIT:
                    last = {"level": level, "expanded": expanded, "limit": EXPANDED_LIMIT}
                    break
                data, info = model_file(geo, tgt, page)
                if info["extent"] > EXPANDED_LIMIT:
                    last = {"level": level, "extent": info["extent"]}
                    break
                if len(data) <= room:
                    rep.update(bytes=len(data), budget=room, texture=[256, h], extent=info["extent"],
                               extent_limit=EXPANDED_LIMIT, tim_bytes=info["tim_bytes"], level=level,
                               collapses=dec.get("collapses", 0), donor_triangles=int(len(tri["bones"])))
                    progress(None, f"fits: {rep['triangles']} triangles ({len(tri['bones'])} in the donor), page "
                                   f"256x{h}, {len(data)} of {room} bytes")
                    return {"data": data, "geometry": geo, "page": page, "report": rep}
                last = {"level": level, "texture": h, "bytes": len(data), "budget": room}
    raise WriterError(f"the character doesn't fit {tgt['fighter']['name']} costume {tgt['costume'] + 1}: {last}")


# =============================================================================================== checks
def check_model(data: bytes, geo: dict, program_ram: bytes | None = None) -> dict:
    """The built file read back: the expander port and (with the decoded program) the game's own 0x8006c718 on the
    interpreter must expand every mesh to exactly the logical meshes the writer laid out."""
    port = expand_all(data, GAME_WORK)
    dests = {r["index"]: r["dest"] for r in walk_container(data)}
    out = {"sections": sorted(port), "port_matches_layout": True}
    for slot, mesh in geo["meshes"].items():
        got = mesh_from_expanded(port[3 + slot], GAME_WORK + dests[3 + slot])
        if not same_mesh(got, mesh):
            out["port_matches_layout"] = False
    if program_ram is not None:
        game = game_expand_all(data, program_ram)
        out["game_expander_identical"] = game == port
        if not out["game_expander_identical"]:
            out["game_expander_mismatch"] = [s for s in game if game[s] != port.get(s)]
    return out


def verify_read_back(program_ram: bytes, banked: bytes, fighter: dict, costume: int, height: float | None = None,
                     glb: Path | None = None, clips: dict | None = None) -> dict:
    """The rebuilt bankedroms through the reader: the game's fight loader walk, fight init and skeleton build with the
    new model (doapp_motion.Rig), then doapp_chars.assemble (every vertex on a bone, every primitive textured from the
    model's own TIM, seams, ground, height). ok = textured, seams <= 400 units, soles within 60 of the ground, height
    within 25 % of the original fighter's. glb: also write the read-back model (+ clips {name: motion}) there."""
    from . import doapp_chars as R
    from . import doapp_motion as DM
    rig = DM.Rig(program_ram, banked, fighter, costume)
    pose = rig.rest_pose()
    a = R.assemble(rig.sections(), rig.model, pose, rig.hand_shapes(), R.chains(program_ram, fighter["id"], costume))
    r = a["report"]
    out = {k: r[k] for k in ("triangles", "seam_triangles", "seam_max_edge", "ground", "height", "untextured_prims",
                             "inexact_texture", "joints", "textures")}
    out["ok"] = (r["untextured_prims"] == 0 and r["seam_max_edge"] <= R.SEAM_LIMIT and abs(r["ground"]) <= R.GROUND
                 and (height is None or abs(r["height"] - height) <= 0.25 * height))
    if glb is not None:
        frames = {n: rig.clip(m) for n, m in (clips or {}).items()}
        R.write_glb(glb, a, Path(glb).stem, frames, extras={"source": "gbox.doapp_swap read-back"})
        out["glb"] = str(glb)
    return out


# =============================================================================================== ROM set
def rebuild_set(src_dir, replacements: dict[int, bytes], out_dir) -> dict:
    """Write model files over their table spans (zero padded to the table size) in a copy of the doapp set:
    out_dir/doapp.zip (every member of the owned doapp.zip, the data chips that changed rebuilt) + coh1002m.zip
    (copied). The owned zips are only read. -> per chip: changed, sha1 before / after; per file: span."""
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    parent = src_dir / "doapp.zip"
    banked = bytearray(D.merge_parent(str(parent)))
    files = {}
    for idx, data in sorted(replacements.items()):
        start, size = D.file_span(idx)
        if len(data) > budget(idx):
            raise WriterError(f"file {idx}: {len(data):#x} bytes, room {budget(idx):#x}")
        banked[start:start + size] = data + bytes(size - len(data))
        files[idx] = {"offset": start, "size": size, "used": len(data), "chips": sorted({
            D.DATA_BANKS[(start // 0x400000) - 1], D.DATA_BANKS[((start + size - 1) // 0x400000) - 1]})}
    out_dir.mkdir(parents=True, exist_ok=True)
    chips = {}
    tmp = out_dir / f"{SET}.zip.part"
    with zipfile.ZipFile(parent) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in D.DATA_BANKS:
                k = D.DATA_BANKS.index(info.filename)
                new = bytes(banked[0x400000 * (k + 1):0x400000 * (k + 2)])[:len(data)]
                chips[info.filename] = {"changed": new != data, "sha1": hashlib.sha1(new).hexdigest(),
                                        "original_sha1": hashlib.sha1(data).hexdigest()}
                data = new
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
    tmp.replace(out_dir / f"{SET}.zip")
    bios = src_dir / f"{D.BIOS_SET}.zip"
    if bios.is_file() and bios.resolve() != (out_dir / bios.name).resolve():
        shutil.copyfile(bios, out_dir / bios.name)
    back = D.merge_parent(str(out_dir / f"{SET}.zip"))
    for idx, data in replacements.items():
        start, size = D.file_span(idx)
        if back[start:start + len(data)] != data or any(back[start + len(data):start + size]):
            raise AssertionError(f"file {idx} did not land in the rebuilt set")
    return {"zip": str(out_dir / f"{SET}.zip"), "chips": chips, "files": files, "bankedroms": back}


# =============================================================================================== slots + build
def parse_slot(slot: str) -> list[tuple[dict, int]]:
    """`<fighter>[:<costume 1-4>]` (also `fighter:<name>[:<costume>]`) -> [(fighter, costume index)]; `player` / `all`
    -> every costume of every fighter."""
    s = (slot or "player").strip()
    if s.casefold() in ("player", "all", "everyone", "roster"):
        return [(f, c) for f in D.FIGHTERS for c in range(D.COSTUMES)]
    parts = s.removeprefix("fighter:").split(":")
    if len(parts) > 2:
        raise WriterError("slot is <fighter> or <fighter>:<costume 1-4>")
    try:
        f = D.fighter(parts[0])
    except KeyError as e:
        raise WriterError(str(e)) from None
    if len(parts) == 1 or parts[1].strip().casefold() in ("", "all"):
        return [(f, c) for c in range(D.COSTUMES)]
    if not parts[1].strip().isdigit() or not 1 <= int(parts[1]) <= D.COSTUMES:
        raise WriterError(f"costume is 1..{D.COSTUMES}")
    return [(f, int(parts[1]) - 1)]


def is_slot(slot: str) -> bool:
    try:
        parse_slot(slot)
        return True
    except WriterError:
        return False


def cast_slots() -> list[dict]:
    out = [{"slot": "player", "name": "every fighter (whoever is picked)", "kind": "player"}]
    for f in D.FIGHTERS:
        key = f["name"].lower().replace(" ", "_")
        out.append({"slot": key, "name": f"{f['name'].title()} (all 4 costumes)", "kind": "fighter"})
    return out


def build(program_ram: bytes, banked: bytes, model_path: Path, roles: dict, jobs: list[tuple[dict, int]],
          work: Path, name: str, blender: str | None = None, progress=lambda p, m: None, scale=None, props=(),
          verify: bool = True, preview: Path | None = None) -> dict:
    """Collection model -> {file index: model bytes} for every (fighter, costume) job, with reports. verify: read every
    built model back through the game's fight init / skeleton build and the reader; preview: a folder for the
    read-back GLB + PNG of the first four jobs."""
    from .sm64_swap import load_rig, retarget
    from . import doapp_motion as DM
    rig_src = load_rig(Path(model_path), roles, props)
    out, reports = {}, {}
    for k, (f, c) in enumerate(jobs):
        lbl = f"{f['name'].title()} costume {c + 1}"
        progress(5 + 80 * k / len(jobs), f"Fitting {name} onto {lbl}")
        rig = DM.Rig(program_ram, banked, f, c)
        tgt = target(program_ram, banked, f, c, rig)
        prims, rrep = retarget(rig_src, tgt, scale, jmap=ROLE_BONE)
        rrep["feet_to_ground"] = fit_feet(prims, tgt)
        prims = _decimated(prims, tgt, work / f"{f['name'].lower().replace(' ', '_')}_{c + 1}", name, blender)
        r = fit(prims, tgt, progress)
        r["report"]["retarget"] = rrep
        r["report"]["check"] = check_model(r["data"], r["geometry"], program_ram)
        if not r["report"]["check"].get("game_expander_identical", True) or not r["report"]["check"]["port_matches_layout"]:
            raise WriterError(f"{lbl}: the packed sections don't expand to the layout: {r['report']['check']}")
        out[tgt["file"]] = r["data"]
        reports[tgt["file"]] = {"fighter": f["name"], "costume": c + 1, "original_height": round(tgt["height"], 1),
                                **r["report"]}
    if verify:
        b = bytearray(banked)
        for idx, data in out.items():
            start, size = D.file_span(idx)
            b[start:start + size] = data + bytes(size - len(data))
        for k, (f, c) in enumerate(jobs):
            progress(88, f"Reading {f['name'].title()} costume {c + 1} back through the reader")
            rep = reports[f["models"][c]]
            glb = Path(preview) / f"doapp_{f['name'].lower().replace(' ', '_')}_{c + 1}.glb" if preview and k < 4 else None
            rep["read_back"] = verify_read_back(program_ram, bytes(b), f, c, rep["original_height"], glb)
            if glb is not None:
                from .characters import render_preview
                rep["read_back"]["preview"] = str(render_preview(glb, glb.with_suffix(".png")))
    return {"files": out, "reports": reports}


def _decimated(prims: list[dict], tgt: dict, work: Path, name: str, blender: str | None) -> list[dict]:
    """With Blender on this node: edge-collapse the retargeted model to a triangle count the slot caps allow before
    clustering (gbox.re4gc_enemies.decimate); without it the vertex clustering in fit() does the reduction."""
    tris = sum(len(p["tris"]) for p in prims)
    want = 2 * sum(SLOT_VERTEX_CAP[s] for s in (0, 2, 4))
    if not blender or tris <= want:
        return prims
    from .re4gc_enemies import decimate
    from .sm64_swap import read_rigged, write_rigged
    work.mkdir(parents=True, exist_ok=True)
    src = write_rigged(prims, tgt, work / "rigged.gltf", name)
    out = read_rigged(decimate(src, work / f"rigged_d{want}.glb", float(want), blender))
    for p in out:
        p["J"] = np.stack([p["jid"]] + [np.zeros_like(p["jid"])] * 3, 1)
    return out


# =============================================================================================== characters op=use
def mod_name(meta: dict, slot: str) -> str:
    s = (slot or "player").strip().casefold().removeprefix("fighter:").replace(" ", "_").replace(":", "")
    return f"doapp_{meta['slug']}_{s or 'player'}"


def build_mod(ctx, meta: dict, game: dict, slot: str, progress=lambda p, m: None, root: Path | None = None) -> dict:
    from . import characters as Cm, doapp_chars as R, filemods
    cfg = ctx.config
    root = root or Cm.library_root(cfg)
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise WriterError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto the fighter")
    jobs = parse_slot(slot)
    src = R.source_dir(ctx, game)
    progress(2, "Decoding the program (cached after the first run)")
    ram, banked = R._program(ctx, src)
    gid, name = game["game_id"], mod_name(meta, slot)
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "doapp"
    shutil.rmtree(work, ignore_errors=True)
    b = build(ram, banked, root / meta["slug"] / meta["model"], roles, jobs, work, meta["name"], Cm._blender(cfg),
              progress, (meta.get("rig") or {}).get("scale"), [p["node"] for p in meta.get("props") or []])
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    progress(92, "Rebuilding the data ROMs into the mod's own doapp set")
    rs = rebuild_set(src, b["files"], d)
    mj = {"name": name, "game_id": gid, "image": f"{SET}.zip", "built": time.time(), "character": meta["slug"],
          "slot": slot, "files": [f"doapp.zip: {', '.join(sorted(k for k, v in rs['chips'].items() if v['changed']))} "
                                  f"(model files {sorted(b['files'])}, gbox.doapp_swap)"],
          "source": meta["model"], "reports": b["reports"], "launch": "MAME doapp from this folder (rompath = this "
          "folder: doapp.zip + coh1002m.zip); MAME reports the rebuilt chips as incorrect checksums and runs the set"}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": f"{SET}.zip", "chips": rs["chips"], "report": b["reports"]}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Dead Or Alive ++: build doapp_<slug>_<slot> if missing, record it, launch it."""
    from . import characters as Cm
    from .sm64_swap import _have_mod, _wait
    gid, slot = game["game_id"], inp.slot or "player"
    try:
        jobs = parse_slot(slot)
    except WriterError as e:
        return {"status": "failed", "error": str(e), "slots": [s["slot"] for s in cast_slots()]}
    name = mod_name(meta, slot)
    who = sorted({f["name"].title() for f, _c in jobs})
    replaces = (f"{', '.join(who)} ({len(jobs)} costume model{'s' if len(jobs) > 1 else ''}; the fighter's skeleton, "
                "motions and moves stay)")
    sess = Cm._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else Cm.HOST_OS
    built = None
    if inp.rebuild or not _have_mod(ctx, gid, name):
        if Cm.library_root(ctx.config).is_dir():
            built = build_mod(ctx, meta, game, slot, ctx.progress)
            tris = {f"{v['fighter']} {v['costume']}": v["triangles"] for v in built["report"].values()}
            Cm._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                    json={"game_id": gid, "slot": slot, "mod": name, "nodes": [Cm.HOST_OS],
                          "notes": f"replaces {replaces}; triangles {tris}; unverified in game: select the fighter"})
        else:
            cp = next((w["id"] for w in Cm._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the Dead Or Alive ++ mod on the control-plane node (the collection lives there)")
            j = Cm._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "slot": slot,
                                            "rebuild": inp.rebuild, "launch": False}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "build": built, "replaces": replaces, "gameplay_verified": False,
           "replacement_kind": "native_rom"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Dead Or Alive ++ with {meta['name']} (mod {name})")
    lj = _wait(ctx, Cm._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                          "node": node}}), 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"Dead Or Alive ++ is running with {meta['name']} as {', '.join(who)} (mod {name}): pick that fighter."
           if ok else f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else f"launch {lj.get('state')}",
                  "launch": launch, "message": msg}


def main(argv=None) -> int:
    import argparse
    from . import doapp_chars as R
    ap = argparse.ArgumentParser(prog="python -m gbox.doapp_swap", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="collection character -> a rebuilt doapp set")
    b.add_argument("src", help="directory with doapp.zip + coh1002m.zip")
    b.add_argument("character", help="collection entry folder (meta.json + model)")
    b.add_argument("out", help="output folder (gets doapp.zip + coh1002m.zip)")
    b.add_argument("slot", nargs="?", default="kasumi:1", help="<fighter>[:<costume 1-4>] | player")
    b.add_argument("--no-verify", action="store_true", help="skip reading the result back through the reader")
    a = ap.parse_args(argv)
    cdir = Path(a.character)
    meta = json.loads((cdir / "meta.json").read_text())
    ram, banked = R._program(None, Path(a.src))
    from .sm64_swap import _blender
    res = build(ram, banked, cdir / meta["model"], meta["rig"]["roles"], parse_slot(a.slot), Path(a.out) / "work",
                meta["name"], _blender(), lambda p, m: print(f"{p if p is not None else '':>5} {m}", flush=True),
                (meta.get("rig") or {}).get("scale"), [p["node"] for p in meta.get("props") or []],
                verify=not a.no_verify)
    rs = rebuild_set(a.src, res["files"], Path(a.out))
    shutil.rmtree(Path(a.out) / "work", ignore_errors=True)
    print(json.dumps({"zip": rs["zip"], "chips": rs["chips"], "reports": res["reports"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
