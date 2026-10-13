"""007: Agent Under Fire (GameCube, GW7E69) .gcm model encoder and level texture edits.

The inverse of :mod:`gbox.auf_ngc`'s reader: a skinned triangle mesh in a target model's own skeleton becomes a .gcm
that ``NGCObject3D::FixupModelData`` / ``R_DrawGeomSection`` draw.  Every rule below was read from the owned disc's
Bond.elf (sha256 1a9c0d19..e716f, symbols kept) or measured on the 127 unique actor models of the 38 maps.

File = a chain of blocks ``{u32 type, u24 body size, u8 extra}`` + ``extra`` pad bytes + body, 8-byte aligned; the
object header block (type word ``0x484 << 20``) holds file-relative block offsets that ``C_Object3D::FixupModelData``
0x80183968 / ``FixupHeaderOff`` 0x80183AF4 relocate to block bodies:

    hdr+0x0C file size, +0x10 vec3 (kept), +0x20 bbox centre, +0x30 half extents, +0x40 radius = max |v - centre|
    (exact on the shipped models), +0x50 u16 bones, +0x54 u16 palette records (``ObjCntrl_AllocMatrices``), +0x56 u16
    morph targets, +0x58 u16 hit boxes, +0x5A u16 material names (``LoadMaterials`` 0x801773A4), +0x64 u32 vertex
    count, +0x68 u32 triangle count, +0x74 bones {s32 parent, u32 hash}, +0x78 rest pose {pos, pad, quat}, +0x7C
    palette {s16 a, s16 b (-2 = rigid), f32 w}, +0x80 NGC geometry, +0x84/+0x88 morphs, +0x8C hit boxes (64 bytes per
    bone box), +0x94 material names (64-byte strings; ``SHDR_GetIDFromString`` = HashString of the name = the section's
    shader id).

Palette (``BuildMatrixList`` 0x8017A674): record i = MtxFromQuat(slerp(q_b, q_a, w), pos_a) of the animated pose, i.e.
a vertex rotates about bone a's joint with a blend of a's and b's rotations.  Its matrices come from a per-frame bump
allocator (``ObjCntrl_AllocMatrices`` 0x8017A13C, 0x84 bytes each, no bounds check), so a rewritten model never uses
more records than the slot it replaces had (``max_palette``).

Geometry (``R_DrawGeomSection`` 0x80179C44): sections -> groups -> strips.  A group loads up to ten palette records
into GX position/normal matrix slots (ids 0, 3, ... 27 = PNMTX0..9, ``GXLoadPosMtxImm``/``GXLoadNrmMtxImm3x3``); a
strip is GX_TRIANGLESTRIP over u16 indices into ent_vtx {u16 pos, u16 nrm, u16 st} with either one current matrix
(byte 7 = slot) or a per-vertex PNMTXIDX from the u8 list (byte 7 = 0xFF).  Positions are s16 in the palette record's
local frame, dequantised by the 3x4 matrix at the start of the geometry body (``model+0x80`` in
``BuildViewMatrixList``); normals are s8 in the same local frame but go through ``R_BuildNormalMtx(view * palette)``,
i.e. without the dequantisation matrix (shipped normals have length 127); texture coordinates are s16 frac 11.

Textures (``TexMgr_LoadStaticTextures`` 0x80185EA8): the level's restxtrs chunk holds 0x44-byte records whose image
offsets are chunk-relative (``TexMgr_InitTexture`` 0x80185CFC), so a record can be pointed at new image data appended
to the chunk without moving anything else; the texture table has 512 entries (0x8032AD58, count at +0x180C, no bounds
check in ``TexMgr_AddTexture``), so this module never adds records, it re-points records only the replaced models use.
"""
from __future__ import annotations

import hashlib
import struct

import numpy as np

from . import auf_ngc as ngc
from .auf_ngc_writer import hash_string

HDR = 0x10                      # header block body (byte 7 of the first block is 8)
GX_SLOTS = tuple(range(0, 30, 3))   # PNMTX0..PNMTX9
NORMAL_SCALE = 127.0            # shipped s8 normals have length 126.9..128.1
UV_ONE = 2048.0                 # TEX0 s16 frac 11
BLOCK_PALETTE, BLOCK_NGC, BLOCK_NAMES = 0x7C, 0x80, 0x94
BLOCK_MORPHS = (0x84, 0x88)
BLOCK_FIELDS = (0x74, 0x78, 0x7C, 0x80, 0x84, 0x88, 0x8C, 0x90, 0x94)
WEIGHT_STEPS = (0.1, 0.25, 0.5)

EVIDENCE = {
    "C_Object3D::FixupModelData": 0x80183968,
    "C_Object3D::FixupHeaderOff": 0x80183AF4,
    "NGCObject3D::FixupNGCModelData": 0x8017AB18,
    "NGCObject3D::BuildMatrixList": 0x8017A674,
    "NGCObject3D::BuildViewMatrixList": 0x8017A5A4,
    "ObjCntrl_AllocMatrices": 0x8017A13C,
    "R_DrawGeomSection": 0x80179C44,
    "C_Q3Object3D::LoadMaterials": 0x801773A4,
    "SHDR_GetIDFromString": 0x801872E8,
    "SHDR_LookupIDX": 0x80187350,
    "TexMgr_LoadStaticTextures": 0x80185EA8,
    "TexMgr_AddTexture": 0x80185E54,
    "TexMgr_InitTexture": 0x80185CFC,
    "TexMgr_InitGXTex": 0x80186094,
}


# ----------------------------------------------------------------------------------------------- blocks

def blocks(gcm: bytes) -> list[dict]:
    """The block chain in file order: [{offset, type, size, extra, field}] (field = header pointer naming it)."""
    ptr = {struct.unpack_from(">I", gcm, HDR + f)[0]: f for f in BLOCK_FIELDS}
    out, pos = [], 0
    while pos + 8 <= len(gcm):
        w0, w1 = struct.unpack_from(">II", gcm, pos)
        extra, size = w1 & 0xFF, w1 >> 8
        out.append({"offset": pos, "type": w0, "size": size, "extra": extra, "field": ptr.get(pos) if pos else "header"})
        nxt = pos + 8 + extra + size
        if nxt <= pos or nxt > len(gcm):
            break
        pos = nxt
    return out


def _block(w0: int, body: bytes, extra: int = 0) -> bytes:
    body = body + b"\0" * (-len(body) % 8)
    return struct.pack(">II", w0, (len(body) << 8) | extra) + b"\0" * extra + body


# ----------------------------------------------------------------------------------------------- skeleton roles

def _kids(bones):
    k = {b["index"]: [] for b in bones}
    for b in bones:
        if b["parent"] >= 0:
            k[b["parent"]].append(b["index"])
    return k


def _subtree(k, i):
    out, todo = [], [i]
    while todo:
        j = todo.pop()
        out.append(j)
        todo += k[j]
    return out


def auto_roles(bones: list[dict]) -> dict[str, int]:
    """Body roles (gbox.sm64_swap.ORDER names) of an AUF skeleton from its topology and rest pose (Z up, the
    character faces +X, its left is +Y): hip = the bone with two descending leg chains, chest = the first spine bone
    with three children (neck + clavicles), arms/legs follow the longest chain.  Raises ValueError when the skeleton
    is not a biped."""
    if not bones:
        raise ValueError("no skeleton")
    k = _kids(bones)
    z = {b["index"]: b["world_pos"][2] for b in bones}
    y = {b["index"]: b["world_pos"][1] for b in bones}
    top = max(z.values())
    sub = {i: _subtree(k, i) for i in k}

    def main_chain(i, n):
        out = [i]
        while len(out) < n and k[out[-1]]:
            out.append(max(k[out[-1]], key=lambda c: len(sub[c])))
        return out
    hip = None
    for b in sorted(bones, key=lambda b: -len(sub[b["index"]])):
        i = b["index"]
        legs = [c for c in k[i] if min(z[j] for j in sub[c]) < z[i] - 0.4 * top]
        ups = [c for c in k[i] if max(z[j] for j in sub[c]) > z[i] + 0.1 * top]
        if len(legs) == 2 and ups:
            hip = i
            break
    if hip is None:
        raise ValueError("no hip bone with two legs")
    roles = {"hip": hip}
    legs = sorted((c for c in k[hip] if min(z[j] for j in sub[c]) < z[hip] - 0.4 * top), key=lambda c: y[c])
    for side, c in zip(("r", "l"), legs):
        ch = main_chain(c, 3)
        for role, j in zip(("thigh", "shin", "foot"), ch):
            roles[f"{side}_{role}"] = j
    spine = max((c for c in k[hip] if c not in legs), key=lambda c: max(z[j] for j in sub[c]))
    chest = spine
    while len(k[chest]) < 3:
        if not k[chest]:
            raise ValueError("spine has no shoulder branch")
        chest = max(k[chest], key=lambda c: len(sub[c]))
    roles["chest"] = chest
    neck = min(k[chest], key=lambda c: abs(y[c]) - z[c] * 1e-3)
    roles["neck"] = neck
    roles["head"] = max(k[neck], key=lambda c: z[c]) if k[neck] else neck
    arms = sorted((c for c in k[chest] if c != neck), key=lambda c: -len(sub[c]))[:2]   # not the leaf breast bones
    clavs = sorted(arms, key=lambda c: y[c])
    if len(clavs) < 2 or len(sub[clavs[0]]) < 3:
        raise ValueError("chest has no clavicles")
    for side, c in (("r", clavs[0]), ("l", clavs[-1])):
        ch = main_chain(c, 4)
        roles[f"{side}_clav"] = ch[0]
        for role, j in zip(("upper", "fore", "hand"), ch[1:]):
            roles[f"{side}_{role}"] = j
    return roles


# ----------------------------------------------------------------------------------------------- palette

def _ancestors(bones, i):
    out = []
    p = bones[i]["parent"]
    while p >= 0 and p not in out:
        out.append(p)
        p = bones[p]["parent"]
    return out


def palette_records(bones, J: np.ndarray, W: np.ndarray, max_palette: int) -> tuple[list, np.ndarray, float]:
    """Per-vertex 2-bone influences -> (palette records [(a, b, w)], record per vertex, weight step used).

    a is the bone the record rotates about (its joint position), so of a parent/child pair the child is a; weights are
    quantised (0.1, then 0.25, 0.5, then rigid) until the records fit ``max_palette``."""
    J = np.asarray(J, int)
    W = np.asarray(W, float)
    anc = {i: set(_ancestors(bones, i)) for i in range(len(bones))}
    for step in WEIGHT_STEPS + (None,):
        recs, idx = {}, np.zeros(len(J), int)
        for v in range(len(J)):
            a, b, w = int(J[v, 0]), int(J[v, 1]), float(W[v])
            if b < 0 or b == a or step is None:
                key = (a, -2, 1.0)
            else:
                if a in anc[b]:                       # rotate about the child's joint
                    a, b, w = b, a, 1.0 - w
                q = round(round(w / step) * step, 4)
                if q >= 0.999:
                    key = (a, -2, 1.0)
                elif q <= 0.001:
                    key = (b, -2, 1.0)
                else:
                    key = (a, b, q)
            if key not in recs:
                recs[key] = len(recs)
            idx[v] = recs[key]
        if len(recs) <= max_palette:
            return list(recs), idx, step or 1.0
    raise ValueError("%d bones need more than %d palette records" % (len(set(J[:, 0].tolist())), max_palette))


def record_matrices(bones, records) -> list[tuple[np.ndarray, np.ndarray]]:
    """Rest-pose (R, T) of each record, exactly as gbox.auf_ngc.matrix_palette computes them."""
    out = []
    for a, b, w in records:
        q = bones[a]["world_quat"] if b == -2 else ngc._slerp(bones[b]["world_quat"], bones[a]["world_quat"], w)
        out.append((np.asarray(ngc._qmat(q), float), np.asarray(bones[a]["world_pos"], float)))
    return out


# ----------------------------------------------------------------------------------------------- strips

def stripify(faces: list[tuple]) -> list[list]:
    """CCW triangles over hashable vertex keys -> GX triangle strips.  A strip [v0, v1, v2, ...] draws (v1, v0, v2),
    (v1, v2, v3), (v3, v2, v4) ... in CCW order (gbox.auf_ngc.mesh flips even triangles the same way)."""
    edge: dict = {}
    for i, (a, b, c) in enumerate(faces):
        for u, v in ((a, b), (b, c), (c, a)):
            edge.setdefault((u, v), []).append(i)
    used = [False] * len(faces)

    def take(u, v):
        for i in edge.get((u, v), ()):
            if not used[i]:
                return i
        return None

    def third(i, u, v):
        f = faces[i]
        return next(x for x in f if x != u and x != v) if len(set(f)) == 3 else f[0]

    def grow(vs):
        got = []
        while True:
            k = len(vs) - 2
            x, y = vs[-2], vs[-1]
            i = take(x, y) if k & 1 else take(y, x)
            if i is None:
                return got
            used[i] = True
            got.append(i)
            vs.append(third(i, x, y))

    strips = []
    for i, (a, b, c) in enumerate(faces):
        if used[i]:
            continue
        best = None
        for rot in ((a, b, c), (b, c, a), (c, a, b)):
            used[i] = True
            vs = [rot[1], rot[0], rot[2]]
            got = grow(vs)
            for j in got:
                used[j] = False
            if best is None or len(vs) > len(best):
                best = vs
        used[i] = True
        vs = list(best[:3])                   # replay the longest rotation for real
        grow(vs)
        strips.append(vs)
    return strips


# ----------------------------------------------------------------------------------------------- encoder

def _rest(gcm: bytes):
    bones = ngc.skeleton(gcm)
    if not bones:
        raise ValueError("template has no skeleton")
    return bones


def encode_gcm(template: bytes, P, N, UV, J, W, faces, face_section, section_names, max_palette: int | None = None,
               scale_floor: float = 1e-6) -> tuple[bytes, dict]:
    """A new .gcm on ``template``'s skeleton, hit boxes and header.

    P/N (n,3): model-space rest pose (the reader's frame: Z up); UV (n,2) glTF-style (0,0 = top-left); J (n,2) bone
    indices (J[:,1] = -1 for rigid), W (n,) weight of J[:,0]; faces (m,3) CCW; face_section (m,) index into
    ``section_names`` (shader names that must exist in the level's shaders chunk).  Returns (bytes, report)."""
    bones = _rest(template)
    hdr = HDR
    P = np.asarray(P, float).reshape(-1, 3)
    N = np.asarray(N, float).reshape(-1, 3)
    UV = np.asarray(UV, float).reshape(-1, 2)
    faces = np.asarray(faces, int).reshape(-1, 3)
    face_section = np.asarray(face_section, int).reshape(-1)
    if not len(faces):
        raise ValueError("no triangles")
    if np.abs(UV).max(initial=0) >= 15.99:
        raise ValueError("texture coordinates beyond +-16 do not fit s16 frac 11")
    nb = struct.unpack_from(">H", template, hdr + 0x50)[0]
    J = np.asarray(J, int).reshape(-1, 2)
    if J.max() >= nb or J[:, 0].min() < 0:
        raise ValueError("bone index outside the %d-bone skeleton" % nb)
    max_palette = max_palette or struct.unpack_from(">H", template, hdr + 0x54)[0]
    recs, vrec, step = palette_records(bones, J, W, max_palette)
    mats = record_matrices(bones, recs)
    R = np.stack([mats[r][0] for r in vrec])
    T = np.stack([mats[r][1] for r in vrec])
    Lp = np.einsum("nji,nj->ni", R, P - T)             # R^T (P - T)
    Ln = np.einsum("nji,nj->ni", R, N)
    lo, hi = Lp.min(0), Lp.max(0)
    sc = np.maximum((hi - lo) / 65534.0, scale_floor)
    off = (hi + lo) / 2
    S16 = np.clip(np.rint((Lp - off) / sc), -32767, 32767).astype(int)
    ln = np.linalg.norm(Ln, axis=1, keepdims=True)
    Ln = np.where(ln > 1e-9, Ln / np.maximum(ln, 1e-9), [0.0, 0.0, 1.0])
    S8 = np.clip(np.rint(Ln * NORMAL_SCALE), -127, 127).astype(int)
    ST = np.clip(np.rint(UV * UV_ONE), -32767, 32767).astype(int)

    pos_ix, nrm_ix, st_ix, ent_ix = {}, {}, {}, {}
    vkey = []
    for v in range(len(P)):
        p = pos_ix.setdefault(tuple(S16[v]), len(pos_ix))
        n = nrm_ix.setdefault(tuple(S8[v]), len(nrm_ix))
        t = st_ix.setdefault(tuple(ST[v]), len(st_ix))
        e = ent_ix.setdefault((p, n, t), len(ent_ix))
        vkey.append((e, int(vrec[v])))
    if max(len(pos_ix), len(nrm_ix), len(st_ix), len(ent_ix)) > 0xFFFF:
        raise ValueError("more than 65535 vertices")

    u16, u8, strips, mmap, groups, sections = [], [], [], [], [], []
    for s in range(len(section_names)):
        fsel = [tuple(vkey[i] for i in f) for f, fs in zip(faces.tolist(), face_section.tolist()) if fs == s]
        fsel = [f for f in fsel if len(set(f)) == 3]
        g0 = len(groups)
        tris = sv = 0
        # greedy groups of <= 10 palette records
        buckets: dict = {}
        for f in fsel:
            buckets.setdefault(tuple(sorted({x[1] for x in f})), []).append(f)
        pending = sorted(buckets.items(), key=lambda kv: (-len(kv[0]), kv[0]))
        while pending:
            cur_recs, cur_faces = set(), []
            rest = []
            for key, fl in pending:
                if len(cur_recs | set(key)) <= len(GX_SLOTS):
                    cur_recs |= set(key)
                    cur_faces += fl
                else:
                    rest.append((key, fl))
            pending = rest
            slot = {r: GX_SLOTS[i] for i, r in enumerate(sorted(cur_recs))}
            m0 = len(mmap)
            mmap += [(r, slot[r]) for r in sorted(cur_recs)]
            s0 = len(strips)
            for vs in stripify(cur_faces):
                slots = {slot[x[1]] for x in vs}
                li, uo = len(u16), len(u8)
                u16 += [x[0] for x in vs]
                if len(slots) == 1:
                    strips.append((li, len(vs), 0, 0, slots.pop()))
                else:
                    u8 += [slot[x[1]] for x in vs]
                    strips.append((li, len(vs), uo, len(vs), 0xFF))
                tris += len(vs) - 2
                sv += len(vs)
            groups.append((m0, len(mmap) - m0, s0, len(strips) - s0))
        sections.append((0, hash_string(section_names[s]), g0, len(groups) - g0, min(tris, 0xFFFF), min(sv, 0xFFFF)))
    if len(u16) > 0xFFFF or len(u8) > 0xFFFF or len(strips) > 0xFFFF:
        raise ValueError("geometry exceeds the u16 strip/list indices")
    if any(r >= 256 for r, _s in mmap):
        raise ValueError("palette index above 255 (u8 in mtx_map)")

    def arr(fmt, rows):
        return b"".join(struct.pack(fmt, *r) for r in rows)
    pos_rows = sorted(pos_ix, key=pos_ix.get)
    nrm_rows = sorted(nrm_ix, key=nrm_ix.get)
    st_rows = sorted(st_ix, key=st_ix.get)
    ent_rows = sorted(ent_ix, key=ent_ix.get)
    data = [arr(">hhh", pos_rows), arr(">bbb", nrm_rows), arr(">hh", st_rows), arr(">HHH", ent_rows),
            arr(">H", [(x,) for x in u16]), bytes(u8), arr(">HHHBB", strips), arr(">BB", mmap),
            arr(">HHHH", groups), arr(">IIHHHH", sections)]
    counts = [len(pos_rows), len(nrm_rows), len(st_rows), len(ent_rows), len(u16), len(u8), len(strips), len(mmap),
              len(groups), len(sections)]
    tbody = ngc.gcm_info(template)["ngc_body"]
    f30 = template[tbody + 0x30:tbody + 0x34]
    D = [sc[0], 0.0, 0.0, off[0], 0.0, sc[1], 0.0, off[1], 0.0, 0.0, sc[2], off[2]]
    head = bytearray(struct.pack(">12f", *D) + f30 + b"\0" * (0x9C - 0x34))
    body = bytearray()
    pos = len(head)
    for i, (blob, n) in enumerate(zip(data, counts)):
        pos += -pos % 4
        body += b"\0" * (pos - len(head) - len(body))
        struct.pack_into(">II", head, ngc.NGC_ARRAYS[i][0], pos if n else 0, n)
        body += blob
        pos += len(blob)
    ngc_body = bytes(head) + bytes(body)
    pal_body = b"".join(struct.pack(">hhf", a, b, w) for a, b, w in recs)
    names = b"".join(n.encode("latin-1")[:63].ljust(64, b"\0") for n in section_names)

    # rebuild the block chain
    old = blocks(template)
    out = bytearray()
    where = {}
    for blk in old:
        f = blk["field"]
        raw = template[blk["offset"]:blk["offset"] + 8 + blk["extra"] + blk["size"]]
        if f in BLOCK_MORPHS:
            continue
        if f == BLOCK_PALETTE:
            raw = _block(blk["type"], pal_body, blk["extra"])
        elif f == BLOCK_NGC:
            raw = _block(blk["type"], ngc_body, blk["extra"])
        elif f == BLOCK_NAMES:
            raw = _block(blk["type"], names, blk["extra"])
        out += b"\0" * (-len(out) % 8)
        where[f] = len(out)
        out += raw
    out += b"\0" * (-len(out) % 32)
    for f in BLOCK_FIELDS:
        struct.pack_into(">I", out, hdr + f, where.get(f, 0))
    if BLOCK_NAMES not in where:
        raise ValueError("template has no material-name block")
    # header: sizes, counts, bounds
    used = np.unique(faces.reshape(-1))
    Pu = P[used]
    c = (Pu.min(0) + Pu.max(0)) / 2
    e = (Pu.max(0) - Pu.min(0)) / 2
    struct.pack_into(">I", out, hdr + 0x0C, len(out))
    struct.pack_into(">3f", out, hdr + 0x20, *c)
    struct.pack_into(">3f", out, hdr + 0x30, *e)
    struct.pack_into(">f", out, hdr + 0x40, float(np.linalg.norm(Pu - c, axis=1).max()))
    struct.pack_into(">H", out, hdr + 0x54, len(recs))
    struct.pack_into(">H", out, hdr + 0x56, 0)
    struct.pack_into(">H", out, hdr + 0x5A, len(section_names))
    struct.pack_into(">II", out, hdr + 0x64, len(pos_rows), sum(s[4] for s in sections))
    flags = struct.unpack_from(">I", out, hdr + 8)[0]
    struct.pack_into(">I", out, hdr + 8, flags & ~0x8000)
    rep = {"palette": len(recs), "palette_limit": max_palette, "weight_step": step, "positions": len(pos_rows),
           "normals": len(nrm_rows), "st": len(st_rows), "ent_vtx": len(ent_rows), "strips": len(strips),
           "strip_vertices": len(u16), "groups": len(groups), "sections": len(sections),
           "triangles": sum(s[4] for s in sections), "bytes": len(out),
           "max_quant_error": float(np.abs(S16 * sc + off - Lp).max())}
    return bytes(out), rep


def empty_gcm(template: bytes, section_name: str | None = None) -> bytes:
    """A model that draws nothing: one zero-area triangle on the root bone (every array stays non-empty), the
    template's skeleton, hit boxes and header kept.  Used for a head whose body now carries the donor's head."""
    bones = _rest(template)
    if section_name is None:
        nb = struct.unpack_from(">I", template, HDR + BLOCK_NAMES)[0]
        section_name = template[ngc._body(template, nb):][:64].split(b"\0")[0].decode("latin-1") if nb else "none"
    p = np.asarray(bones[0]["world_pos"], float)
    data, _rep = encode_gcm(template, [p, p, p], [[0, 0, 1.0]] * 3, [[0, 0]] * 3, [[0, -1]] * 3, [1.0] * 3,
                            [[0, 1, 2]], [0], [section_name], max_palette=1)
    return data


def decode_check(gcm: bytes) -> dict:
    """Re-read an encoded model with the reader: arrays tile, every strip's matrix slot is loaded, mesh decodes."""
    info = ngc.gcm_info(gcm)
    probs = ngc.tile_check(info)
    m = ngc.mesh(gcm)
    return {"problems": probs, "triangles": len(m["faces"]), "vertices": len(m["positions"]), "mesh": m}


# ----------------------------------------------------------------------------------------------- textures

def _rgb565(px: np.ndarray) -> np.ndarray:
    px = np.asarray(px, float)
    return ((np.rint(px[..., 0] * 31 / 255).astype(int) << 11) | (np.rint(px[..., 1] * 63 / 255).astype(int) << 5)
            | np.rint(px[..., 2] * 31 / 255).astype(int))


def _from565(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, int)
    return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31], -1).astype(float)


def encode_cmpr(rgba: np.ndarray) -> bytes:
    """RGBA8 image (h, w, 4) -> one GX CMPR level (8x8 tiles of four big-endian DXT1 blocks; opaque 4-colour mode).
    Sizes below 8 are padded by edge replication (a GX CMPR level always occupies whole 8x8 tiles)."""
    img = np.asarray(rgba, np.uint8)[..., :3].astype(float)
    h, w = img.shape[:2]
    H, Wd = max(8, -(-h // 8) * 8), max(8, -(-w // 8) * 8)
    if (H, Wd) != (h, w):
        img = np.pad(img, ((0, H - h), (0, Wd - w), (0, 0)), mode="edge")
    blk = img.reshape(H // 4, 4, Wd // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(H // 4, Wd // 4, 16, 3)
    lum = blk @ np.array([0.299, 0.587, 0.114])
    hi_c = np.take_along_axis(blk, lum.argmax(-1)[..., None, None], 2)[:, :, 0]
    lo_c = np.take_along_axis(blk, lum.argmin(-1)[..., None, None], 2)[:, :, 0]
    c0, c1 = _rgb565(hi_c), _rgb565(lo_c)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    p0, p1 = _from565(c0), _from565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 2)            # (by, bx, 4, 3)
    d = ((blk[:, :, :, None, :] - pal[:, :, None, :, :]) ** 2).sum(-1)          # (by, bx, 16, 4)
    idx = d.argmin(-1)
    idx = np.where((c0 == c1)[..., None], 0, idx)
    bits = np.zeros(idx.shape[:2], np.uint64)
    for i in range(16):
        bits |= idx[..., i].astype(np.uint64) << np.uint64(30 - 2 * i)
    out = bytearray()
    for ty in range(H // 8):
        for tx in range(Wd // 8):
            for sy, sx in ((0, 0), (0, 1), (1, 0), (1, 1)):
                by, bx = 2 * ty + sy, 2 * tx + sx
                out += struct.pack(">HHI", int(c0[by, bx]), int(c1[by, bx]), int(bits[by, bx]))
    return bytes(out)


def mip_chain(rgba: np.ndarray, levels: int) -> list[np.ndarray]:
    out = [np.asarray(rgba, np.uint8)]
    for _ in range(levels - 1):
        a = out[-1].astype(float)
        h, w = a.shape[:2]
        if h < 2 or w < 2:
            break
        out.append(((a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) / 4).astype(np.uint8))
    return out


def encode_texture(rgba: np.ndarray, levels: int = 1, fmt: int = ngc.GX_CMPR) -> bytes:
    """A full GX mip chain (exactly gbox.auf_ngc.gx_chain_size bytes)."""
    if fmt == ngc.GX_CMPR:
        return b"".join(encode_cmpr(m) for m in mip_chain(rgba, levels))
    if fmt == ngc.GX_I8:
        out = bytearray()
        for m in mip_chain(rgba, levels):
            a = np.asarray(m, np.uint8)
            v = a[..., :3].mean(-1).astype(np.uint8) if a.ndim == 3 else a
            h, w = v.shape
            H, Wd = -(-h // 4) * 4, -(-w // 8) * 8
            v = np.pad(v, ((0, H - h), (0, Wd - w)), mode="edge")
            out += v.reshape(H // 4, 4, Wd // 8, 8).transpose(0, 2, 1, 3).tobytes()
        return bytes(out)
    raise ValueError("GX format %d not supported by the encoder" % fmt)


def texture_records(payload: bytes) -> tuple[int, int, int]:
    _ver, n, ido, reco = struct.unpack_from(">fIII", payload, 0)
    return n, ido, reco


def repoint_textures(payload: bytes, images: dict) -> bytes:
    """restxtrs payload with the records of ``images`` {texture id: rgba (h, w, 4)} pointed at new CMPR mip chains
    appended (32-aligned) to the chunk.  The record keeps its id, index, wrap modes and filters; a record with a second
    image plane gets a matching all-white I8 plane.  Nothing is moved, so every other record stays valid."""
    out = bytearray(payload)
    n, ido, reco = texture_records(payload)
    ids = {struct.unpack_from(">I", payload, ido + 4 * i)[0]: i for i in range(n)}
    for tid, rgba in images.items():
        if tid not in ids:
            raise KeyError("texture %08x is not in this level" % tid)
        r = reco + ids[tid] * 0x44
        h, w = rgba.shape[:2]
        levels = 1
        while (w >> levels) >= 8 and (h >> levels) >= 8 and levels < 6:
            levels += 1
        data = encode_texture(rgba, levels)
        out += b"\0" * (-len(out) % 32)
        off = len(out)
        out += data
        struct.pack_into(">IHH", out, r, ngc.GX_CMPR, w, h)
        struct.pack_into(">II", out, r + 0x10, off, len(data))
        if struct.unpack_from(">I", payload, r + 0x1C)[0]:
            plane = encode_texture(np.full((h, w), 255, np.uint8), levels, ngc.GX_I8)
            out += b"\0" * (-len(out) % 32)
            off2 = len(out)
            out += plane
            struct.pack_into(">III", out, r + 0x18, ngc.GX_I8, off2, len(plane))
        struct.pack_into(">f", out, r + 0x30, float(levels - 1))
        out[r + 0x3A] = 1 if levels > 1 else 0
        if levels == 1:
            struct.pack_into(">I", out, r + 0x28, 1)        # GX_LINEAR min filter without mips
    out += b"\0" * (-len(out) % 32)
    return bytes(out)


def write_texture_in_place(payload: bytes, tid: int, rgba: np.ndarray) -> bytes:
    """restxtrs payload with texture ``tid``'s pixels replaced by ``rgba`` (resized by the caller to the record's own
    width x height), re-encoded as the record's CMPR mip chain over its own bytes: same size, same offsets, the
    record and any second plane untouched, so the level's memory does not change."""
    n, ido, reco = texture_records(payload)
    ids = {struct.unpack_from(">I", payload, ido + 4 * i)[0]: i for i in range(n)}
    if tid not in ids:
        raise KeyError("texture %08x is not in this level" % tid)
    r = reco + ids[tid] * 0x44
    fmt, w, h = struct.unpack_from(">IHH", payload, r)
    off, size = struct.unpack_from(">II", payload, r + 0x10)
    if fmt != ngc.GX_CMPR:
        raise ValueError("texture %08x is GX format %d, not CMPR" % (tid, fmt))
    if tuple(rgba.shape[:2]) != (h, w):
        raise ValueError("texture %08x is %dx%d, image is %dx%d" % (tid, w, h, rgba.shape[1], rgba.shape[0]))
    mip = payload[r + 0x3A]
    levels = int(struct.unpack_from(">f", payload, r + 0x30)[0]) + 1 if mip else 1
    data = encode_texture(rgba, levels)
    if len(data) != size:
        raise ValueError("texture %08x: %d bytes encoded for a %d-byte chain" % (tid, len(data), size))
    out = bytearray(payload)
    out[off:off + size] = data
    return bytes(out)


def section_names(gcm: bytes) -> list[str]:
    nb = struct.unpack_from(">I", gcm, HDR + BLOCK_NAMES)[0]
    if not nb:
        return []
    body = ngc._body(gcm, nb)
    n = struct.unpack_from(">H", gcm, HDR + 0x5A)[0]
    return [gcm[body + 64 * i:body + 64 * i + 64].split(b"\0")[0].decode("latin-1") for i in range(n)]


def shader_users(pkg: "ngc.NgcPackage") -> dict[int, set]:
    """shader id -> restable names of the models that draw with it (by their section shader ids)."""
    users: dict = {}
    for r in pkg.resources():
        if not r.name.endswith(".gcm"):
            continue
        g = pkg.table[r.offset:r.offset + r.size]
        try:
            info = ngc.gcm_info(g)
            secs = ngc._array(g, info, 9, ">IIHHI")
        except (ValueError, struct.error):
            continue
        for s in secs:
            users.setdefault(s[1], set()).add(r.name.lower())
    return users


def free_shaders(pkg: "ngc.NgcPackage", replaced: set, users: dict | None = None, shd: dict | None = None,
                 tex: dict | None = None) -> list[dict]:
    """Shaders (and their textures) only the ``replaced`` models use, so their texture can carry a donor: drawn by no
    other model, not referenced by the BSP, one group with one textured pass, and a texture no other shader uses.
    Largest texture first.  [{name?, id, texture, size}]"""
    users = shader_users(pkg) if users is None else users
    shd = ngc.shaders(pkg) if shd is None else shd
    tex = ngc.textures(pkg) if tex is None else tex
    replaced = {x.lower() for x in replaced}
    bsp = pkg.payload("bspfile")
    tex_users: dict = {}
    for sid, groups in shd.items():
        for passes in groups:
            for _fl, tid in passes:
                tex_users.setdefault(tid, set()).add(sid)
    out = []
    for sid, us in users.items():
        if not us <= replaced or sid not in shd:
            continue
        groups = shd[sid]
        if len(groups) != 1 or len(groups[0]) != 1:
            continue
        tid = groups[0][0][1]
        if tid not in tex or tex_users.get(tid) != {sid} or struct.pack(">I", sid) in bsp:
            continue
        t = tex[tid]
        out.append({"id": sid, "texture": tid, "size": [t.width, t.height], "fmt": t.fmt})
    out.sort(key=lambda d: (-d["size"][0] * d["size"][1], d["id"]))
    return out


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
