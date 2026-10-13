"""Metal Gear Solid: The Twin Snakes (GC) - `.kms` models (stage file type 0x0a): decode, and encode a new body.

Format (big-endian; offsets marked "G" are relative to the mesh-group header whose file offset is at +0x5c; the
engine's loader (mgso.rel 0x806b6be8 / 0x806b6860) turns them into pointers, the draw loop is 0x806a2a6c):

  header (0x60)
    +0x00 u32 flags (0 for characters)      +0x04 u32 bone count   +0x08 u32 mesh count
    +0x0c u32 strcode of the texture set (.tri) the parts' textures come from (searched first)
    +0x10 u32 strcode of this model         +0x14 u32 3
    +0x18 f32 min[3], max[3]                +0x30 zero[3]
    +0x3c u16 envelope count, u16 mesh count     +0x40 u16 1, u16 position count
    +0x44 u16 normal count, u16 uv count        +0x48 u16 bone count, u16 0xfffe
    +0x4c G envelopes  +0x50 G positions  +0x54 G normals  +0x58 G uvs  +0x5c file offset of G
  bones (0x40 each, from 0x60): u32 flags, i32 parent, f32 local[3], f32 world[3] (bind pose, model space, mm),
    f32 min[4], max[4]. Every character in the game uses the same 21-bone MGS2 skeleton (BONE_NAMES).
  G (0x14): u32 ?, u32 ?, u16 mesh count, u16 part count, u32 G LOD sub-groups (0 = none; else 8 x 0x14 headers),
    u32 G mesh records
  mesh record (0x48): u32 0, u32 0, f32 min[3], max[3], local[3], world[3], u16 part count, i16 parent,
    u32 0x00abcdef (characters; props carry a strcode there), u16 ?, u16 ?, u32 G parts. Every mesh has its own matrix (the model object allocates 0x144
    bytes per mesh); mesh i < bone count is bone i, later meshes (hair, gear) ride their parent mesh rigidly.
    Envelope bone numbers are mesh numbers.
  part (0x24): u32 flags (0x1f8: bump-mapped), u32 tex[3] strcodes (bump, colour, specular when all three are set,
    else tex[0] is the colour), u16 strip count, u16 ?, u32 G uv list, u32 G uv list 2 (0 = the same),
    u32 3, u32 G strips
  strip (0x20): u32 G stream[7], u16 vertex count n, u16 envelope count m. A triangle strip (GX 0x98);
    vertex k: position = pos[s0[k]], uv = uv[uvlist[s1[k]]] (s1 = 0 -> s0), normal / binormal / tangent =
    nrm[s2[k]] / nrm[s3[k]] / nrm[s4[k]] (0 -> the previous stream), matrix = envelope s5[s6[k]] (m <= 10:
    GX's matrix palette).
  arrays: positions s16 x3 (mm, model space, bind pose); normals s8 x3 (64 = 1.0); uvs s16 x2 (4096 = 1.0);
    envelopes 8 bytes {u16 w0, u16 w1 (Q15), u8 bone[4] (0xff = none)}: the last listed bone gets 1 - w0 - w1.
  Face winding: the front face is clockwise in strip order (the stored normals point away from (a, b, c)).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MARK = 0x00ABCDEF
# the MGS2 21-bone skeleton (parents -1,0,1,2,3,4,5,2,7,8,9,2,11,0,13,14,15,0,17,18,19); the character faces +Z,
# its left is +X, so bones 3-6 (negative X) are the right arm and 13-16 the right leg.
BONE_NAMES = ["hip", "spine", "chest", "r_shoulder", "r_upperarm", "r_forearm", "r_hand", "l_shoulder", "l_upperarm",
              "l_forearm", "l_hand", "neck", "head", "r_thigh", "r_shin", "r_foot", "r_toe", "l_thigh", "l_shin",
              "l_foot", "l_toe"]
PARENTS = [-1, 0, 1, 2, 3, 4, 5, 2, 7, 8, 9, 2, 11, 0, 13, 14, 15, 0, 17, 18, 19]
ROLES = {"hip": "hip", "chest": "chest", "neck": "neck", "head": "head", "r_clav": "r_shoulder",
         "r_upper": "r_upperarm", "r_fore": "r_forearm", "r_hand": "r_hand", "l_clav": "l_shoulder",
         "l_upper": "l_upperarm", "l_fore": "l_forearm", "l_hand": "l_hand", "r_thigh": "r_thigh", "r_shin": "r_shin",
         "r_foot": "r_foot", "l_thigh": "l_thigh", "l_shin": "l_shin", "l_foot": "l_foot"}
ROLE_BONE = {r: BONE_NAMES.index(b) for r, b in ROLES.items()}
MM = 0.001                                               # the library frame is in metres


@dataclass
class Strip:
    streams: list            # 7 lists of u16 (s5 has m entries, the others n)
    n: int
    m: int


@dataclass
class Part:
    flags: int
    tex: tuple
    strips: list
    uvlist: list
    uvlist2: list
    raw: bytes               # the 0x24 record as stored


@dataclass
class Mesh:
    raw: bytes               # the 0x48 record
    parent: int
    parts: list = field(default_factory=list)
    world: tuple = (0.0, 0.0, 0.0)   # bind-pose position of the mesh's own matrix (= its bone's for i < bones)


@dataclass
class Kms:
    data: bytes
    flags: int
    tex_set: int
    name: int
    bones: list              # [{parent, local, world}]
    meshes: list
    pos: np.ndarray
    nrm: np.ndarray
    uv: np.ndarray
    env: list                # [(weights[4], bones[4])]
    g: int                   # file offset of G

    @property
    def colour_textures(self) -> list[int]:
        return sorted({colour_texture(p.tex) for m in self.meshes for p in m.parts} - {0})


def colour_texture(tex) -> int:
    t = [x if x not in (0, 1) else 0 for x in tex]
    return t[1] if t[1] and t[2] and t[0] else t[0] or t[1]


def _u16s(d: bytes, off: int, n: int) -> list[int]:
    return list(struct.unpack_from(f">{n}H", d, off)) if n else []


def parse(data: bytes) -> Kms:
    d = bytes(data)
    flags, nb, nm, tex_set, name = struct.unpack_from(">5I", d, 0)
    if not (0 < nb <= 256 and 0 < nm <= 512):
        raise ValueError(f"not a character model (bones {nb}, meshes {nm})")
    nenv, _nm2, _one, npos, nnrm, nuv = struct.unpack_from(">6H", d, 0x3C)
    o_env, o_pos, o_nrm, o_uv, g = struct.unpack_from(">5I", d, 0x4C)
    bones = []
    for i in range(nb if g >= 0x60 + 0x40 * nb else 0):            # props (flags 0x01b253a3) carry no bone table
        o = 0x60 + 0x40 * i
        _f, par = struct.unpack_from(">Ii", d, o)
        bones.append({"parent": par, "local": struct.unpack_from(">3f", d, o + 8),
                      "world": struct.unpack_from(">3f", d, o + 20)})
    nmesh, _nparts, sub, recs = struct.unpack_from(">HHII", d, g + 8)
    pos = np.frombuffer(d, ">i2", npos * 3, g + o_pos).reshape(-1, 3).astype(np.float64)
    nrm = np.frombuffer(d, "i1", nnrm * 3, g + o_nrm).reshape(-1, 3).astype(np.float64) / 64.0
    uv = np.frombuffer(d, ">i2", nuv * 2, g + o_uv).reshape(-1, 2).astype(np.float64) / 4096.0
    env = []
    for k in range(nenv):
        w0, w1, *b = struct.unpack_from(">HH4B", d, g + o_env + 8 * k)
        bl = [x for x in b if x != 0xFF]
        w = [w0 / 32768.0, w1 / 32768.0, 0.0, 0.0][:len(bl)]
        if len(bl) >= 2:
            w[len(bl) - 1] = max(0.0, 1.0 - sum(w[:len(bl) - 1]))
        elif len(bl) == 1:
            w = [1.0]
        env.append((w, bl))
    meshes = []
    for i in range(nmesh):
        mo = g + recs + 0x48 * i
        npart, par = struct.unpack_from(">Hh", d, mo + 0x38)
        _mk, _a, _b, poff = struct.unpack_from(">IHHI", d, mo + 0x3C)    # 0xabcdef on characters, a strcode on props
        if npart and not 0 < g + poff + 0x24 * npart <= len(d):
            raise ValueError(f"mesh {i}: parts outside the file")
        me = Mesh(d[mo:mo + 0x48], par)
        me.world = struct.unpack_from(">3f", d, mo + 0x2C)
        for k in range(npart):
            po = g + poff + 0x24 * k
            pflags, t0, t1, t2, nstrip, _x, ul, ul2, _three, so = struct.unpack_from(">4IHH4I", d, po)
            strips, maxs1 = [], 0
            for s in range(nstrip):
                q = g + so + 0x20 * s
                offs = list(struct.unpack_from(">7I", d, q))
                n, m = struct.unpack_from(">HH", d, q + 28)
                for a, b in ((1, 0), (2, 0), (3, 2), (4, 3)):
                    if not offs[a]:
                        offs[a] = offs[b]
                streams = [_u16s(d, g + o, m if j == 5 else n) if o else [] for j, o in enumerate(offs)]
                if streams[1]:
                    maxs1 = max(maxs1, max(streams[1]))
                strips.append(Strip(streams, n, m))
            uvl = _u16s(d, g + ul, maxs1 + 1)
            uvl2 = _u16s(d, g + ul2, maxs1 + 1) if ul2 else uvl
            me.parts.append(Part(pflags, (t0 & 0xFFFFFF, t1 & 0xFFFFFF, t2 & 0xFFFFFF), strips, uvl, uvl2, d[po:po + 0x24]))
        meshes.append(me)
    return Kms(d, flags, tex_set & 0xFFFFFF, name & 0xFFFFFF, bones, meshes, pos, nrm, uv, env, g)


def strip_triangles(n: int) -> list[tuple[int, int, int]]:
    """Strip vertex slots -> triangles in glTF (counter-clockwise front) order; degenerate ones are kept out later."""
    return [(k, k + 2, k + 1) if k % 2 == 0 else (k, k + 1, k + 2) for k in range(n - 2)]


def decode(m: Kms) -> list[dict]:
    """Model -> one primitive per (mesh, part): {mesh, part, tex (colour strcode), pos (n,3 mm), nrm, uv, J (n,4),
    W (n,4), tris}. Vertices are shared within a part when position, normal, uv and envelope agree."""
    prims = []
    for mi, me in enumerate(m.meshes):
        for pi, p in enumerate(me.parts):
            key_of, P, N, UV, J, W, tris = {}, [], [], [], [], [], []
            for s in p.strips:
                s0, s1, s2, _s3, _s4, s5, s6 = s.streams
                slots = []
                for k in range(s.n):
                    e = s5[s6[k]] if s5 and s6 and s6[k] < len(s5) else 0xFFFF
                    ui = p.uvlist[s1[k]] if s1 and s1[k] < len(p.uvlist) else s0[k]
                    key = (s0[k], s2[k], ui, e)
                    v = key_of.get(key)
                    if v is None:
                        v = key_of[key] = len(P)
                        P.append(m.pos[s0[k]])
                        N.append(m.nrm[s2[k]] if s2[k] < len(m.nrm) else (0, 1, 0))
                        UV.append(m.uv[ui] if ui < len(m.uv) else (0, 0))
                        w, b = m.env[e] if e < len(m.env) else ([1.0], [mi if mi < len(m.bones) else me.parent])
                        jj, ww = (list(b) + [0, 0, 0, 0])[:4], (list(w) + [0, 0, 0, 0])[:4]
                        J.append(jj)
                        W.append(ww)
                    slots.append(v)
                for a, b, c in strip_triangles(s.n):
                    t = (slots[a], slots[b], slots[c])
                    if len(set(t)) == 3 and len({tuple(P[x]) for x in t}) == 3:
                        tris.append(t)
            if not tris:
                continue
            W_ = np.array(W, np.float64)
            W_ /= np.maximum(W_.sum(1, keepdims=True), 1e-9)
            prims.append({"mesh": mi, "part": pi, "tex": colour_texture(p.tex), "textures": p.tex,
                          "pos": np.array(P, np.float64), "nrm": np.array(N, np.float64),
                          "uv": np.array(UV, np.float64), "J": np.array(J, np.int64), "W": W_,
                          "tris": np.array(tris, np.int64)})
    return prims


def stats(m: Kms) -> dict:
    strips = [s for me in m.meshes for p in me.parts for s in p.strips]
    return {"bones": len(m.bones), "meshes": len(m.meshes), "parts": sum(len(me.parts) for me in m.meshes),
            "strips": len(strips), "strip_vertices": sum(s.n for s in strips),
            "triangles": sum(max(0, s.n - 2) for s in strips), "positions": len(m.pos), "normals": len(m.nrm),
            "uvs": len(m.uv), "envelopes": len(m.env), "bytes": len(m.data)}


# ----------------------------------------------------------------------------------------------- encoder

MAX_PALETTE = 10                                          # GX position-matrix slots per strip (the draw loop's palette)


def _frame(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Binormal / tangent for unit normals (any perpendicular pair; the swap writes flat bump maps)."""
    a = np.where(np.abs(n[:, 1:2]) < 0.9, np.array([[0.0, 1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]]))
    t = np.cross(a, n)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    b = np.cross(n, t)
    return b, t


def split_palette(strip: list, bone_of, limit: int = MAX_PALETTE) -> list[list]:
    """One GX strip -> strips that each use at most `limit` distinct bones, drawing the same triangles with the same
    winding (a cut restarts on the last two vertices; an odd restart gets a leading duplicate to keep the parity)."""
    out, cur, bones = [], [], set()
    k = 0
    while k < len(strip):
        b = bone_of(strip[k])
        if b not in bones and len(bones) >= limit and len(cur) >= 3:
            out.append(cur)
            n = len(cur)
            keep = cur[-2:] if (n - 2) % 2 == 0 else [cur[-2]] + cur[-2:]
            cur, bones = list(keep), {bone_of(v) for v in keep}
            continue
        cur.append(strip[k])
        bones.add(b)
        k += 1
    out.append(cur)
    return [s for s in out if len(s) >= 3]


def _strips_for(faces: list[tuple], bone_of) -> list[list]:
    from .auf_gcm import stripify
    out = []
    for s in stripify(faces):
        out += split_palette(s, bone_of)
    return out


def encode(template: Kms, P, N, UV, B, F, mesh_of_face=None, keep_extra: bool = False) -> bytes:
    """A new model on the template's skeleton: P (n,3) model-space bind-pose positions (mm), N (n,3) unit normals,
    UV (n,2), B (n,) bone (= mesh matrix) per vertex (rigid), F (m,3) counter-clockwise faces (outward normals).

    Kept from the template: header (counts and offsets rewritten), bones, the mesh-group header, every mesh record
    (part count, vertex count, bounds and part pointer rewritten) and, for each mesh that gets triangles, its first
    part record (flags, texture strcodes, layer count). Faces go to the mesh of their first vertex's bone; meshes
    without faces (and, unless keep_extra, the meshes past the bones: gear) draw nothing. Envelopes are single-bone."""
    t = template
    d = t.data
    P = np.asarray(P, np.float64).reshape(-1, 3)
    N = np.asarray(N, np.float64).reshape(-1, 3)
    UV = np.asarray(UV, np.float64).reshape(-1, 2)
    B = np.asarray(B, np.int64).reshape(-1)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    nb, nm = len(t.bones), len(t.meshes)
    used = np.unique(F) if len(F) else np.zeros(0, np.int64)       # only the vertices the faces use
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    P, N, UV, B, F = P[used], N[used], UV[used], B[used], remap[F]
    if mesh_of_face is not None:
        mesh_of_face = np.asarray(mesh_of_face, np.int64)
    if len(B) and ((B < 0).any() or (B >= nb).any()):
        raise ValueError("vertex bone out of the skeleton")
    if len(P) and np.abs(P).max() > 32000:
        raise ValueError("positions exceed the s16 range")
    mof = np.asarray(mesh_of_face if mesh_of_face is not None else B[F[:, 0]], np.int64)
    pkey = np.round(P).astype(np.int32)
    _u, pfirst, pidx = np.unique(pkey, axis=0, return_index=True, return_inverse=True)
    pidx = pidx.reshape(-1)
    pos = pkey[pfirst]
    Nn = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    nkey = np.clip(np.round(Nn * 64), -127, 127).astype(np.int8)
    _u, nfirst, nidx = np.unique(nkey, axis=0, return_index=True, return_inverse=True)
    nidx = nidx.reshape(-1)
    nu = nkey[nfirst].astype(np.float64)
    nu /= np.maximum(np.linalg.norm(nu, axis=1, keepdims=True), 1e-9)
    bi, ta = _frame(nu)
    nbt = np.stack([nkey[nfirst], np.clip(np.round(bi * 64), -127, 127).astype(np.int8),
                    np.clip(np.round(ta * 64), -127, 127).astype(np.int8)], 1).reshape(-1, 3)   # N, B, T per normal
    ukey = np.clip(np.round(UV * 4096), -32768, 32767).astype(np.int16)
    _u, ufirst, uidx = np.unique(ukey, axis=0, return_index=True, return_inverse=True)
    uidx = uidx.reshape(-1)
    uvs = ukey[ufirst]
    bones_used = sorted(set(B.tolist())) or [0]
    env_of = {b: k for k, b in enumerate(bones_used)}
    if len(pos) > 0xFFFF or 3 * len(nbt) > 0xFFFF or len(uvs) > 0xFFFF:
        raise ValueError("too many vertices for u16 indices")
    meshes = []
    for mi in range(nm):
        faces = [tuple(int(x) for x in f) for f in F[mof == mi]]
        if not faces or (mi >= nb and not keep_extra) or not t.meshes[mi].parts:
            meshes.append(None)
            continue
        meshes.append(_strips_for(faces, lambda v: int(B[v])))
    G = t.g
    out = bytearray(d[:G])                                 # header + bones
    g_hdr = bytearray(d[G:G + 0x14])
    rec_end = 0x14 + 0x48 * nm
    body = bytearray()                                     # G-relative from rec_end

    def here() -> int:
        return rec_end + len(body)

    def put(b: bytes, align: int = 4) -> int:
        body.extend(bytes((-here()) % align))
        o = here()
        body.extend(b)
        return o
    n_parts = sum(1 for s in meshes if s)
    parts_off = put(bytes(0x24 * n_parts))
    part_slot = 0
    recs = []
    for mi, me in enumerate(t.meshes):
        rec = bytearray(me.raw)
        strips = meshes[mi]
        if not strips:
            struct.pack_into(">H", rec, 0x38, 0)
            struct.pack_into(">H", rec, 0x40, 0)
            struct.pack_into(">I", rec, 0x44, 0)
            recs.append(rec)
            continue
        verts = sorted({v for s in strips for v in s})
        local, uvlist = {}, []                             # s1: index into this part's uv list
        for v in verts:
            u = int(uidx[v])
            if u not in local:
                local[u] = len(uvlist)
                uvlist.append(u)
        ul_off = put(struct.pack(f">{len(uvlist)}H", *uvlist))
        strip_tab = put(bytes(0x20 * len(strips)))
        sdesc = bytearray()
        for s in strips:
            pal = []
            for v in s:
                e = env_of[int(B[v])]
                if e not in pal:
                    pal.append(e)
            s0 = [int(pidx[v]) for v in s]
            s1 = [local[int(uidx[v])] for v in s]
            s2 = [3 * int(nidx[v]) for v in s]
            s3 = [x + 1 for x in s2]
            s4 = [x + 2 for x in s2]
            s6 = [pal.index(env_of[int(B[v])]) for v in s]
            offs = [put(struct.pack(f">{len(a)}H", *a), 2) for a in (s0, s1, s2, s3, s4, pal, s6)]
            sdesc += struct.pack(">7IHH", *offs, len(s), len(pal))
        body[strip_tab - rec_end:strip_tab - rec_end + len(sdesc)] = sdesc
        upos = len({int(pidx[v]) for v in verts})
        part = bytearray(me.parts[0].raw)
        struct.pack_into(">HHII", part, 0x10, len(strips), upos, ul_off, 0)
        struct.pack_into(">I", part, 0x20, strip_tab)
        po = parts_off + 0x24 * part_slot
        body[po - rec_end:po - rec_end + 0x24] = part
        part_slot += 1
        q = P[verts] - np.asarray(me.world)                # bounds relative to the mesh's bind position (culling)
        lo0 = np.array(struct.unpack_from(">3f", rec, 0x08))
        hi0 = np.array(struct.unpack_from(">3f", rec, 0x14))
        lo, hi = np.minimum(lo0, q.min(0)), np.maximum(hi0, q.max(0))
        struct.pack_into(">6f", rec, 0x08, *lo.tolist(), *hi.tolist())
        struct.pack_into(">H", rec, 0x38, 1)
        struct.pack_into(">H", rec, 0x40, upos)
        struct.pack_into(">I", rec, 0x44, po)
        recs.append(rec)
    env = b"".join(struct.pack(">HH4B", 0x8000, 0, b, 0xFF, 0xFF, 0xFF) for b in bones_used)
    o_env = put(env, 32)
    o_pos = put(pos.astype(">i2").tobytes(), 32)
    o_nrm = put(nbt.astype(np.int8).tobytes(), 32)
    o_uv = put(uvs.astype(">i2").tobytes(), 32)
    body.extend(bytes((-here()) % 32))
    struct.pack_into(">HH", g_hdr, 0x08, nm, n_parts)
    struct.pack_into(">II", g_hdr, 0x0C, 0, 0x14)
    out += g_hdr
    for r in recs:
        out += r
    out += body
    struct.pack_into(">HH", out, 0x3C, len(bones_used), nm)
    struct.pack_into(">H", out, 0x42, len(pos))
    struct.pack_into(">HH", out, 0x44, len(nbt), len(uvs))
    struct.pack_into(">4I", out, 0x4C, o_env, o_pos, o_nrm, o_uv)
    return bytes(out)


def hide(data: bytes) -> bytes:
    """The same model drawing nothing: every mesh record's part count set to 0 (sizes and offsets unchanged)."""
    d = bytearray(data)
    g = struct.unpack_from(">I", d, 0x5C)[0]
    nmesh, _np, _sub, recs = struct.unpack_from(">HHII", d, g + 8)
    for i in range(nmesh):
        mo = g + recs + 0x48 * i
        if mo + 0x48 <= len(d):
            struct.pack_into(">H", d, mo + 0x38, 0)
    return bytes(d)
