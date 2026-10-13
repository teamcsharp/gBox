"""Stranglehold (PS3, BLUS30081) native model reader: cooked UE3 packages -> rigged, textured GLBs (#1410).

Source: StrangleholdGame/CookedPS3/char_*.xxx (UE3 v375, licensee 25 = Midway, chunked zlib; see
gbox/stranglehold_inventory.py for the package summary). One SkeletalMesh per character package: Tequila
(char_tequila*.xxx: the default outfit plus suit / jacket / sweater / jacket+sweater, each also as _MP), the enemy
classes of the four gangs (char_GK_ / char_DC_ / char_I9_ / char_RM_<class>_<n>_MP.xxx) and the named characters and
bosses (Damon and Vlad Zakarov, Jerry Ying, Wong, the tea-house boss, Captain Lee, ...).

SkeletalMesh export (after the 4-byte net index and the tagged properties):
  FBoxSphereBounds (7 floats), Materials TArray<obj>, Origin FVector, RotOrigin FRotator,
  RefSkeleton TArray<FMeshBone {FName, u32 flags, FQuat, FVector, i32 children, i32 parent}> (48 bytes),
  SkeletalDepth i32, i32 (0), LODModels TArray<FStaticLODModel>:
    Sections TArray<{u16 material, u16 chunk, u32 first index, u16 triangles}>, IndexBuffer TArray<u16> (empty on PS3),
    ActiveBoneIndices TArray<u16>, TArray<u8> (empty), Chunks TArray<{u32 first vertex, rigid TArray (empty),
    soft TArray (empty), Bones TArray<u16>, i32 rigid, i32 soft, i32 max influences}>, i32 size, i32 vertices,
    i32 (0), then the PS3 geometry: i32 chunk count, per chunk i32 segment count and the segments.

The geometry is cooked for the SPU in segments of <= ~740 vertices (Sony Edge-style partitions). A segment:
  16-byte SPU config (flags, command-buffer hole, 0xFF custom vertex formats, 0x31 = compressed indexes + skinning,
  u16 vertexes (padded to 8), u16 indexes, 0xFFFFFFFF), then u16 A (index block bytes), u16 B (explicit indexes),
  u16 C (delta bias), u16 D (bytes of the sequential bit stream), u8 E (bits per delta), u8 0;
  index block (A bytes): D bytes of 1 bit per index (0 = the next new vertex, 1 = explicit), 2 bits per triangle
  (0: shares edge (p0, p2) of the previous triangle, 1: (p2, p1), 2: (p1, p0), 3: three own indexes), B deltas of E
  bits; explicit index k = explicit index k-8 (0 for the first eight) + delta - C (eight interleaved delta chains:
  one SPU quadword of u16 lanes); the block ends with [u16 A][u32 0][u16 vertex bytes].
  vertex stream: 23 bytes per vertex: position 3 x half (mesh space, centimetres, -Y up, +Z front, +X = the
  character's left), 9 bytes of packed tangent frame (not decoded: normals are rebuilt from the triangles),
  2 x half UV0, 2 x half UV1; padded to 16 bytes.
  skin header (36 bytes): DMA sizes of the vertex stream, two matrix ranges (byte offsets / sizes of 48-byte bone
  matrices) and the weight-stream size; weights: 4 x (u8 weight, u8 palette slot) per vertex (sums 255), the slot
  indexing range 0 then range 1 of the RefSkeleton; then 8 bytes (SPU scratch sizes) and 30 zero bytes.
Textures: Texture2D tagged properties (SizeX/Y, Format 5 DXT1 / 7 DXT5 / 2 A8R8G8B8 ...), the source-art bulk
record, then TArray<FTexture2DMipMap {bulk record, SizeX, SizeY}>; the top mip of the 2048 atlases is not cooked
(bulk flags 0x21, size -1), the 1024 mip is stored inline. DXT blocks are in the usual little-endian layout.

CLI:  python -m gbox.stranglehold_models [CookedPS3 folder] [--out dir] [--only name,...]
"""
from __future__ import annotations

import io
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

from . import stranglehold_inventory as SI
from . import ue3

READER_VERSION = 1
GAME_ID = SI.GAME_ID
SCALE = 0.01                                  # centimetres -> metres
VERTEX_BYTES = 23
TEX_MAX = 1024                                # largest mip written into the GLBs

# Body roles on the shared "medium_skeleton" (HumanIK names; l_ = the character's own left = +X in mesh space).
ROLE_BONES = {"hip": "hips", "chest": "spine2", "neck": "neck", "head": "head",
              "l_clav": "leftshoulder", "l_upper": "leftarm", "l_fore": "leftforearm", "l_hand": "lefthand",
              "r_clav": "rightshoulder", "r_upper": "rightarm", "r_fore": "rightforearm", "r_hand": "righthand",
              "l_thigh": "leftupleg", "l_shin": "leftleg", "l_foot": "leftfoot",
              "r_thigh": "rightupleg", "r_shin": "rightleg", "r_foot": "rightfoot"}

# Roster: package stem -> (slug, name, role). Tequila's five outfits, the gang enemy classes, named characters.
GANGS = {"GK": "Golden Kane", "DC": "Dragon Claw", "I9": "Imperial 9", "RM": "Russian mob"}
ROSTER = [
    ("char_tequila", "stranglehold_tequila", "Inspector Tequila (Stranglehold)", "player"),
    ("char_tequila_suit", "stranglehold_tequila_suit", "Tequila, suit (Stranglehold)", "player"),
    ("char_tequila_jacket", "stranglehold_tequila_jacket", "Tequila, jacket (Stranglehold)", "player"),
    ("char_tequila_sweater", "stranglehold_tequila_sweater", "Tequila, sweater (Stranglehold)", "player"),
    ("char_tequila_jack_swtr", "stranglehold_tequila_jack_swtr", "Tequila, jacket + sweater (Stranglehold)", "player"),
] + [(f"char_{g}_{c}_MP", f"stranglehold_{g.lower()}_{c.lower()}", f"{GANGS[g]} {c.split('_')[0].lower()} "
      f"{c.split('_')[1]} (Stranglehold)", "enemy")
     for g, c in [("GK", "Assault_1"), ("GK", "Assault_3"), ("GK", "Elite_2"), ("GK", "Elite_4"), ("GK", "Lieutenant_1"),
                  ("GK", "Pistol_1"), ("DC", "Assault_3"), ("DC", "Lieutenant_2"), ("DC", "Melee_1"), ("DC", "SMG_4"),
                  ("DC", "SMG_5"), ("I9", "Assault_2"), ("I9", "Assault_4"), ("I9", "Lieutenant_2"),
                  ("I9", "Lieutenant_3"), ("I9", "Lieutenant_4"), ("I9", "Sniper_1"), ("RM", "Assault_2"),
                  ("RM", "Butcher_2"), ("RM", "Lieutenant_1"), ("RM", "Lieutenant_3"), ("RM", "Sniper_1")]] + [
    ("char_damonZakarov_MP", "stranglehold_damon_zakarov", "Damon Zakarov (Stranglehold)", "boss"),
    ("char_vladZakarov_MP", "stranglehold_vlad_zakarov", "Vladimir Zakarov (Stranglehold)", "boss"),
    ("char_jerryYing_MP", "stranglehold_jerry_ying", "Jerry Ying (Stranglehold)", "boss"),
    ("char_Wong_MP", "stranglehold_wong", "Wong (Stranglehold)", "boss"),
    ("char_TeaHouseBoss_MP", "stranglehold_teahouse_boss", "Tea house boss (Stranglehold)", "boss"),
    ("char_CaptainLee_MP", "stranglehold_captain_lee", "Captain Lee (Stranglehold)", "character"),
    ("char_chopperpilotLou_MP", "stranglehold_lou", "Chopper pilot Lou (Stranglehold)", "character"),
    ("char_hkCop_MP", "stranglehold_hk_cop", "HKPD officer (Stranglehold)", "character"),
    ("char_johnWoo_MP", "stranglehold_john_woo", "John Woo (Stranglehold)", "character"),
    ("char_junkCaptain_MP", "stranglehold_junk_captain", "Junk captain (Stranglehold)", "character"),
    ("char_lok_MP", "stranglehold_lok", "Lok (Stranglehold)", "character"),
    ("char_yung_MP", "stranglehold_yung", "Yung (Stranglehold)", "character"),
]


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- package access
def load_package(src) -> tuple[dict, bytes]:
    """(summary, logical package bytes) of a .xxx file (path or raw bytes): every chunk decompressed."""
    raw = Path(src).read_bytes() if not isinstance(src, (bytes, bytearray)) else bytes(src)
    s = SI.read_summary(raw[:4096])
    if s["layout"] == "fully_compressed":
        return s, ue3.unpack(raw)
    if s["layout"] == "raw":
        return s, raw
    out = bytearray(raw[:s["summary_size"]])
    for c in s["chunks"]:
        data = SI.decompress_chunk(raw[c["coff"]:c["coff"] + c["csize"]])
        if len(data) != c["usize"]:
            raise FormatError(f"chunk at {c['uoff']:#x} inflated to {len(data)} bytes, table says {c['usize']}")
        if len(out) < c["uoff"]:
            out += bytes(c["uoff"] - len(out))
        out[c["uoff"]:c["uoff"] + len(data)] = data
    return s, bytes(out)


class Package(ue3.Package):
    def cls(self, i: int) -> str:
        e = self.exports[i - 1]
        return self.ref(e["class"])[1] if e["class"] else "Class"

    def find(self, cls: str) -> list[int]:
        return [i for i in range(1, len(self.exports) + 1) if self.cls(i) == cls
                and not self.exports[i - 1]["name"].startswith("Default__")]


def properties(pkg: ue3.Package, b: bytes, o: int = 4) -> tuple[dict, int]:
    """UE3 (v375) tagged properties from offset o -> ({name: value | [values]}, offset after the 'None' tag).
    Values: int / float / bool / object index / name / raw bytes (structs, arrays)."""
    out: dict = {}
    while True:
        ni, nn = struct.unpack_from(">ii", b, o)
        name = pkg._n(ni, nn)
        o += 8
        if name == "None":
            return out, o
        typ = pkg._n(struct.unpack_from(">i", b, o)[0])
        size, aidx = struct.unpack_from(">ii", b, o + 8)
        o += 16
        if typ == "StructProperty":
            o += 8
        if typ == "BoolProperty":
            val, o = struct.unpack_from(">i", b, o)[0] != 0, o + 4
        else:
            raw = b[o:o + size]
            o += size
            if typ in ("IntProperty", "ObjectProperty", "ComponentProperty", "ClassProperty") and size == 4:
                val = struct.unpack(">i", raw)[0]
            elif typ == "FloatProperty":
                val = struct.unpack(">f", raw)[0]
            elif typ == "NameProperty":
                val = pkg._n(*struct.unpack(">ii", raw))
            elif typ == "ByteProperty" and size == 1:
                val = raw[0]
            else:
                val = raw
        if aidx:
            prev = out.get(name)
            out[name] = (prev if isinstance(prev, list) else [prev]) + [val]
        else:
            out[name] = val


# ---------------------------------------------------------------------------------------------- Edge segments
def _bits(buf: bytes, start: int, width: int, n: int) -> list[int]:
    if n <= 0 or width <= 0:
        return [0] * max(n, 0)
    nbytes = (n * width + 7) // 8
    v = int.from_bytes(buf[start:start + nbytes], "big")
    total = nbytes * 8
    mask = (1 << width) - 1
    return [(v >> (total - (k + 1) * width)) & mask for k in range(n)]


EDGE_SHARE = {0: (0, 2), 1: (2, 1), 2: (1, 0)}


def decode_indexes(blk: bytes, ntri: int, nexp: int, bias: int, seq_bytes: int, width: int) -> np.ndarray:
    """A segment's compressed index block -> (ntri, 3) local vertex indexes (see the module doc)."""
    seq = _bits(blk, 0, 1, seq_bytes * 8)
    codes = _bits(blk, seq_bytes, 2, ntri)
    deltas = _bits(blk, seq_bytes + (ntri * 2 + 7) // 8, width, nexp)
    exp = []
    for k, dv in enumerate(deltas):
        exp.append((exp[k - 8] if k >= 8 else 0) + dv - bias)
    xi = ei = nxt = 0
    tris = np.zeros((ntri, 3), np.int64)
    prev = None
    for t, c in enumerate(codes):
        def one():
            nonlocal xi, ei, nxt
            bit = seq[xi]
            xi += 1
            if bit == 0:
                nxt += 1
                return nxt - 1
            ei += 1
            return exp[ei - 1]
        if c == 3 or prev is None:
            tri = (one(), one(), one())
        else:
            a, b = EDGE_SHARE[c]
            tri = (prev[a], prev[b], one())
        tris[t] = tri
        prev = tri
    if ei != nexp:
        raise FormatError(f"index block used {ei} of {nexp} explicit indexes")
    return tris


def parse_segment(b: bytes, s: int) -> dict:
    """One SPU segment at offset s of the mesh export -> geometry + weights (palette resolved) + its byte size."""
    cfg = b[s:s + 16]
    if cfg[2:5] != b"\xff\xff\xff" or cfg[10:14] != b"\xff\xff\xff\xff":
        raise FormatError(f"no SPU segment config at {s:#x}: {cfg.hex()}")
    nv_pad, nidx = struct.unpack_from(">HH", cfg, 6)
    A, nexp, bias, seqb = struct.unpack_from(">HHHH", b, s + 16)
    width = b[s + 24]
    blk = b[s + 26:s + 26 + A]
    vbytes = struct.unpack_from(">H", blk, A - 2)[0]
    nv = vbytes // VERTEX_BYTES
    tris = decode_indexes(blk, nidx // 3, nexp, bias, seqb, width)
    if tris.size and (tris.min() < 0 or tris.max() >= nv):
        raise FormatError(f"segment {s:#x}: index out of range ({tris.min()}..{tris.max()} of {nv})")
    vs = s + 26 + A
    va = np.frombuffer(b, np.uint8, nv * VERTEX_BYTES, vs).reshape(nv, VERTEX_BYTES)
    pos = va[:, 0:6].copy().view(">f2").astype(np.float64)
    uv = va[:, 15:19].copy().view(">f2").astype(np.float64)
    uv1 = va[:, 19:23].copy().view(">f2").astype(np.float64)
    frame = va[:, 6:15].copy()
    sk = vs + vbytes
    hdr = b[sk:sk + 36]
    off0, off1, size0, size1, wsize = struct.unpack_from(">HHHHH", hdr, 16)
    n0, n1 = size0 // 48, size1 // 48
    palette = list(range(off0 // 48, off0 // 48 + n0)) + list(range(off1 // 48, off1 // 48 + n1))
    wa = np.frombuffer(b, np.uint8, nv * 8, sk + 36).reshape(nv, 4, 2)
    slots = wa[:, :, 1].astype(np.int64)
    if slots.max(initial=0) >= len(palette):
        raise FormatError(f"segment {s:#x}: weight slot {slots.max()} outside the {len(palette)}-matrix palette")
    joints = np.asarray(palette, np.int64)[slots] if palette else np.zeros_like(slots)
    weights = wa[:, :, 0].astype(np.float64) / 255.0
    end = sk + 36 + wsize + 8 + 30
    return {"offset": s, "size": end - s, "config": cfg, "nv": nv, "tris": tris, "pos": pos, "uv": uv, "uv1": uv1,
            "frame": frame, "joints": joints, "weights": weights, "palette": palette,
            "header": dict(A=A, nexp=nexp, bias=bias, seq_bytes=seqb, width=width, vbytes=vbytes, wsize=wsize,
                           scratch=b[sk + 36 + wsize:sk + 36 + wsize + 8].hex())}


# ---------------------------------------------------------------------------------------------- SkeletalMesh
def parse_mesh(pkg: Package, i: int) -> dict:
    """SkeletalMesh export i -> bones (bind pose), materials, sections, chunks and decoded segments (LOD 0)."""
    b = pkg.blob(i)
    props, o = properties(pkg, b, 4)

    def i32():
        nonlocal o
        o += 4
        return struct.unpack_from(">i", b, o - 4)[0]

    def u16s(n):
        nonlocal o
        o += 2 * n
        return list(struct.unpack_from(f">{n}H", b, o - 2 * n))
    bounds = struct.unpack_from(">7f", b, o)
    o += 28
    materials = [i32() for _ in range(i32())]
    origin = struct.unpack_from(">3f", b, o)
    rot_origin = struct.unpack_from(">3i", b, o + 12)
    o += 24
    nb = i32()
    if not 0 < nb < 512:
        raise FormatError(f"implausible bone count {nb}")
    bones = []
    for _ in range(nb):
        n, num, flags = struct.unpack_from(">iii", b, o)
        q = struct.unpack_from(">4f", b, o + 12)
        p = struct.unpack_from(">3f", b, o + 28)
        nch, par = struct.unpack_from(">ii", b, o + 40)
        o += 48
        bones.append({"name": pkg._n(n, num), "quat": q, "pos": p, "children": nch, "parent": par})
    depth = i32()
    i32()                                                  # Midway field, 0 in every shipped mesh
    nlod = i32()
    if nlod < 1:
        raise FormatError("no LOD models")
    lods = []
    for _ in range(nlod):
        lod = parse_lod(b, o)
        lods.append(lod)
        o = lod["end"]
    l0 = lods[0]
    return {"name": pkg.exports[i - 1]["name"], "export": i, "props": props, "bounds": bounds, "materials": materials,
            "origin": origin, "rot_origin": rot_origin, "bones": bones, "depth": depth, "lods": nlod, "lod": lods,
            "sections": l0["sections"], "active_bones": l0["active_bones"], "chunks": l0["chunks"],
            "vertices": l0["vertices"], "size_field": l0["size_field"], "geometry_offset": l0["geometry_offset"],
            "geometry_end": l0["geometry_end"], "groups": l0["groups"], "lods_end": o, "blob_size": len(b)}


def parse_lod(b: bytes, o: int) -> dict:
    """One FStaticLODModel at offset o (sections .. SPU geometry .. RequiredBones) -> fields + its byte range."""
    start = o

    def i32():
        nonlocal o
        o += 4
        return struct.unpack_from(">i", b, o - 4)[0]

    def u16s(n):
        nonlocal o
        o += 2 * n
        return list(struct.unpack_from(f">{n}H", b, o - 2 * n))
    sections = []
    for _ in range(i32()):
        m, ch, first, ntri = struct.unpack_from(">HHIH", b, o)
        o += 10
        sections.append({"material": m, "chunk": ch, "first_index": first, "triangles": ntri})
    if i32():
        raise FormatError("an index buffer on a PS3 mesh: not the SPU segment layout")
    active = u16s(i32())
    nbytes = i32()                                         # TArray<u8>, empty
    o += nbytes
    chunks = []
    for _ in range(i32()):
        first = i32()
        if i32() or i32():
            raise FormatError("rigid/soft vertex arrays present: not the PS3 SPU layout")
        bl = u16s(i32())
        nr, ns, mi = i32(), i32(), i32()
        chunks.append({"first_vertex": first, "bones": bl, "rigid": nr, "soft": ns, "max_influences": mi})
    size_field, nverts, _zero = i32(), i32(), i32()
    geo_offset = o
    groups = []
    for _ in range(i32()):
        segs = []
        for _ in range(i32()):
            sg = parse_segment(b, o)
            segs.append(sg)
            o += sg["size"]
        groups.append(segs)
    if len(groups) != len(chunks):
        raise FormatError(f"{len(groups)} segment groups for {len(chunks)} chunks")
    geo_end = o
    required = b[o + 4:o + 4 + struct.unpack_from(">i", b, o)[0]]
    o += 4 + len(required)
    return {"start": start, "end": o, "sections": sections, "active_bones": active, "chunks": chunks,
            "vertices": nverts, "size_field": size_field, "geometry_offset": geo_offset, "geometry_end": geo_end,
            "groups": groups, "required_bones": required,
            "triangles": sum(len(sg["tris"]) for g in groups for sg in g)}


def _qmat(q) -> np.ndarray:
    """UE3 FQuat -> 3x3 rotation for row vectors (v' = v @ R)."""
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
                     [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
                     [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]])


def bind_pose(bones: list[dict]) -> np.ndarray:
    """(n, 4, 4) column-vector world matrices of the reference skeleton in mesh space (centimetres)."""
    out = []
    for i, bn in enumerate(bones):
        R, t = _qmat(bn["quat"]), np.asarray(bn["pos"], float)
        if i and 0 <= bn["parent"] < i:
            PR, Pt = out[bn["parent"]]
            R, t = R @ PR, t @ PR + Pt
        out.append((R, t))
    M = np.zeros((len(out), 4, 4))
    for i, (R, t) in enumerate(out):
        M[i, :3, :3] = R.T
        M[i, :3, 3] = t
        M[i, 3, 3] = 1
    return M


GL = np.diag([1.0, -1.0, 1.0])                            # mesh space (-Y up) -> glTF (+Y up); a mirror, so winding flips


def to_gltf_points(p: np.ndarray) -> np.ndarray:
    return (np.asarray(p, float) @ GL) * SCALE


def to_gltf_matrices(M: np.ndarray) -> np.ndarray:
    S = np.diag([1.0, -1.0, 1.0, 1.0])
    out = S @ M @ S
    out[:, :3, 3] *= SCALE
    return out


def roles_of(bones: list[dict]) -> dict[str, str]:
    low = {bn["name"].lower(): bn["name"] for bn in bones}
    return {role: low[name] for role, name in ROLE_BONES.items() if name in low}


# ---------------------------------------------------------------------------------------------- textures
FORMATS = {2: "A8R8G8B8", 3: "G8", 5: "DXT1", 6: "DXT3", 7: "DXT5"}


def dxt_decode(data: bytes, w: int, h: int, kind: int) -> np.ndarray:
    """DXT1/3/5 blocks -> (h, w, 4) RGBA, vectorised."""
    bw, bh = max(w // 4, 1), max(h // 4, 1)
    bs = 8 if kind == 1 else 16
    a = np.frombuffer(data[:bw * bh * bs], np.uint8).reshape(bh * bw, bs)
    col = a[:, bs - 8:]
    c0 = col[:, 0].astype(np.uint32) | (col[:, 1].astype(np.uint32) << 8)
    c1 = col[:, 2].astype(np.uint32) | (col[:, 3].astype(np.uint32) << 8)

    def rgb(c):
        return np.stack([((c >> 11) & 31) * 255 / 31, ((c >> 5) & 63) * 255 / 63, (c & 31) * 255 / 31], -1)
    p0, p1 = rgb(c0), rgb(c1)
    four = (c0 > c1) | (kind != 1)
    p2 = np.where(four[:, None], (2 * p0 + p1) / 3, (p0 + p1) / 2)
    p3 = np.where(four[:, None], (p0 + 2 * p1) / 3, 0)
    pal = np.stack([p0, p1, p2, p3], 1)
    word = (col[:, 4].astype(np.uint32) | (col[:, 5].astype(np.uint32) << 8) | (col[:, 6].astype(np.uint32) << 16)
            | (col[:, 7].astype(np.uint32) << 24))
    idx = (word[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    px = np.take_along_axis(pal, idx[:, :, None].astype(np.int64).repeat(3, 2), 1)
    if kind == 1:
        alpha = np.where((~four[:, None]) & (idx == 3), 0.0, 255.0)
    elif kind == 5:
        a0, a1 = a[:, 0].astype(float), a[:, 1].astype(float)
        hi = (a0 > a1)[:, None]
        k = np.arange(1, 7)[None, :]
        t8 = ((7 - k) * a0[:, None] + k * a1[:, None]) / 7
        k4 = np.arange(1, 5)[None, :]
        t6 = np.concatenate([((5 - k4) * a0[:, None] + k4 * a1[:, None]) / 5, np.zeros((len(a), 1)),
                             np.full((len(a), 1), 255.0)], 1)
        tab = np.concatenate([a0[:, None], a1[:, None], np.where(hi, t8, t6)], 1)
        ab = np.zeros(len(a), np.uint64)
        for j in range(6):
            ab |= a[:, 2 + j].astype(np.uint64) << np.uint64(8 * j)
        ai = ((ab[:, None] >> (np.uint64(3) * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.int64)
        alpha = np.take_along_axis(tab, ai, 1)
    else:
        ab = np.zeros(len(a), np.uint64)
        for j in range(8):
            ab |= a[:, j].astype(np.uint64) << np.uint64(8 * j)
        alpha = (((ab[:, None] >> (np.uint64(4) * np.arange(16, dtype=np.uint64))) & np.uint64(15)) * 17).astype(float)
    rgba = np.concatenate([px, alpha[:, :, None]], 2).reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4)
    return np.clip(rgba.reshape(bh * 4, bw * 4, 4) + 0.5, 0, 255).astype(np.uint8)[:h, :w]


def texture_mips(pkg: Package, i: int) -> dict:
    """Texture2D export -> {size, format, mips: [(w, h, bytes | None)]} (None = not cooked inline)."""
    b = pkg.blob(i)
    props, o = properties(pkg, b, 4)
    o += 16                                                # SourceArt bulk record (empty)
    n = struct.unpack_from(">i", b, o)[0]
    o += 4
    mips = []
    for _ in range(n):
        flags, count, size, off = struct.unpack_from(">iiii", b, o)
        o += 16
        data = None
        if size > 0 and not flags & 1:
            data = b[o:o + size]
            o += size
        w, h = struct.unpack_from(">ii", b, o)
        o += 8
        mips.append((w, h, data))
    return {"name": pkg.exports[i - 1]["name"], "size": (props.get("SizeX"), props.get("SizeY")),
            "format": props.get("Format", 0), "mips": mips}


def texture_rgba(pkg: Package, i: int, max_size: int = TEX_MAX) -> np.ndarray | None:
    t = texture_mips(pkg, i)
    fmt = t["format"]
    for w, h, data in t["mips"]:
        if data is None or max(w, h) > max_size:
            continue
        if fmt in (5, 6, 7):
            return dxt_decode(data, w, h, {5: 1, 6: 3, 7: 5}[fmt])
        if fmt == 2:
            return np.frombuffer(data, np.uint8, w * h * 4).reshape(h, w, 4)[..., [1, 2, 3, 0]].copy()   # ARGB (BE)
        if fmt == 3:
            g = np.frombuffer(data, np.uint8, w * h).reshape(h, w)
            return np.stack([g, g, g, np.full_like(g, 255)], -1)
        return None
    return None


def material_textures(pkg: Package, ref: int, depth: int = 0) -> list[str]:
    """Texture names a material (MaterialInstanceConstant parameters, its parent, Material expressions) refers to,
    resolved to export or import object names."""
    if not ref or depth > 4:
        return []
    names: list[str] = []
    if ref < 0:
        return names
    cls = pkg.cls(ref)
    b = pkg.blob(ref)
    props, _ = properties(pkg, b, 4)
    if cls == "MaterialInstanceConstant":
        raw = props.get("TextureParameterValues")
        if isinstance(raw, (bytes, bytearray)) and len(raw) >= 4:
            n = struct.unpack_from(">i", raw, 0)[0]
            # each element: tagged properties (ParameterName, ParameterValue) terminated by None
            o = 4
            for _ in range(n):
                el, o = properties(pkg, raw, o)
                v = el.get("ParameterValue")
                if isinstance(v, int) and v:
                    names.append(pkg.ref(v)[1])
        names += material_textures(pkg, props.get("Parent", 0) if isinstance(props.get("Parent"), int) else 0, depth + 1)
    elif cls == "Material":
        for j in range(1, len(pkg.exports) + 1):
            if pkg.exports[j - 1]["outer"] == ref and pkg.cls(j).startswith("MaterialExpressionTextureSample"):
                tp, _ = properties(pkg, pkg.blob(j), 4)
                if isinstance(tp.get("Texture"), int) and tp["Texture"]:
                    names.append(pkg.ref(tp["Texture"])[1])
    return names


def pick_diffuse(pkg: Package, mesh: dict, mat_ref: int) -> int | None:
    """The Texture2D export to show for one material: its own *diffuse* texture, else the package's character atlas."""
    tex = {pkg.exports[j - 1]["name"].lower(): j for j in pkg.find("Texture2D")}
    try:
        cands = [n.lower() for n in material_textures(pkg, mat_ref)]
    except Exception:                                      # a material layout this reader doesn't know: fall back
        cands = []
    own = [n for n in cands if "diffuse" in n and not n.startswith("default") and n in tex]
    if own:
        return tex[own[0]]
    stem = mesh["name"].lower().split("_lod")[0]
    best = None
    for n, j in tex.items():
        if "diffuse" not in n or n.startswith("default") or "cube" in n or "decal" in n:
            continue
        size = texture_mips(pkg, j)["size"][0] or 0
        score = (n.startswith(stem[:6]), "_all_" in n or "body" in n, size)
        if best is None or score > best[0]:
            best = (score, j)
    return best[1] if best else None


# ---------------------------------------------------------------------------------------------- GLB
def png_bytes(rgba: np.ndarray) -> bytes:
    from PIL import Image
    bio = io.BytesIO()
    Image.fromarray(rgba).save(bio, "PNG", optimize=True)
    return bio.getvalue()


def smooth_normals(pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    n = np.zeros_like(pos)
    if len(tris):
        fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
        for k in range(3):
            np.add.at(n, tris[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return np.where(ln > 1e-12, n / np.maximum(ln, 1e-12), np.array([0.0, 1.0, 0.0]))


def write_glb(out: Path, prims: list[dict], bone_names: list[str], parents: list[int], world: np.ndarray,
              images: list[np.ndarray | None], name: str, extras: dict | None = None) -> Path:
    """Skinned glTF binary: one primitive per material ({pos, nrm, uv, joints (n,4), weights (n,4), tris, image}),
    joints at the bind-pose world matrices (glTF frame, metres)."""
    blob = bytearray()
    views, accs = [], []

    def view(data: bytes, target=None):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def acc(arr, ctype, typ, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        a = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    n = len(bone_names)
    nodes = []
    for i in range(n):
        lm = world[i] if parents[i] < 0 else np.linalg.inv(world[parents[i]]) @ world[i]
        nodes.append({"name": bone_names[i], "matrix": [float(v) for v in lm.T.reshape(-1)]})
    for i in range(n):
        ch = [j for j in range(n) if parents[j] == i]
        if ch:
            nodes[i]["children"] = ch
    roots = [i for i in range(n) if parents[i] < 0]
    ibm = np.stack([np.linalg.inv(w).T for w in world]).astype(np.float32)
    gl_prims, materials, textures, imgs = [], [], [], []
    for k, p in enumerate(prims):
        attrs = {"POSITION": acc(p["pos"].astype(np.float32), 5126, "VEC3", 34962, True),
                 "NORMAL": acc(p["nrm"].astype(np.float32), 5126, "VEC3", 34962),
                 "TEXCOORD_0": acc(p["uv"].astype(np.float32), 5126, "VEC2", 34962),
                 "JOINTS_0": acc(p["joints"].astype(np.uint16), 5123, "VEC4", 34962),
                 "WEIGHTS_0": acc(p["weights"].astype(np.float32), 5126, "VEC4", 34962)}
        ind = acc(p["tris"].reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963)
        mat = {"name": p.get("material") or f"{name}_{k}", "doubleSided": False,
               "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1}}
        img = images[p["image"]] if p.get("image") is not None else None
        if img is not None:
            imgs.append({"bufferView": view(png_bytes(img)), "mimeType": "image/png"})
            textures.append({"source": len(imgs) - 1, "sampler": 0})
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(textures) - 1}
            if p.get("alpha_mask"):
                mat["alphaMode"] = "MASK"
                mat["alphaCutoff"] = 0.4
                mat["doubleSided"] = True
        materials.append(mat)
        gl_prims.append({"attributes": attrs, "indices": ind, "material": len(materials) - 1})
    gl = {"asset": {"version": "2.0", "generator": "gbox.stranglehold_models", **({"extras": extras} if extras else {})},
          "scene": 0, "nodes": nodes + [{"name": name, "mesh": 0, "skin": 0}],
          "scenes": [{"nodes": roots + [n]}], "meshes": [{"name": name, "primitives": gl_prims}],
          "skins": [{"joints": list(range(n)), "inverseBindMatrices": acc(ibm.reshape(n, 16), 5126, "MAT4")}],
          "materials": materials}
    if imgs:
        gl["images"], gl["textures"] = imgs, textures
        gl["samplers"] = [{"magFilter": 9729, "minFilter": 9729}]
    while len(blob) % 4:
        blob.append(0)
    gl["accessors"], gl["bufferViews"], gl["buffers"] = accs, views, [{"byteLength": len(blob)}]
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A)
                          + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return Path(out)


def mesh_primitives(pkg: Package, mesh: dict, tex_max: int = TEX_MAX) -> tuple[list[dict], list]:
    """Segments grouped by material -> glTF-frame primitives + decoded textures."""
    chunk_mat = {s["chunk"]: s["material"] for s in mesh["sections"]}
    images, img_of_mat, prims = [], {}, {}
    for ci, segs in enumerate(mesh["groups"]):
        mi = chunk_mat.get(ci, 0)
        if mi not in img_of_mat:
            ref = mesh["materials"][mi] if mi < len(mesh["materials"]) else 0
            tj = pick_diffuse(pkg, mesh, ref) if ref > 0 else pick_diffuse(pkg, mesh, 0)
            img = texture_rgba(pkg, tj, tex_max) if tj else None
            images.append(img)
            img_of_mat[mi] = (len(images) - 1, pkg.exports[tj - 1]["name"] if tj else None,
                              pkg.ref(ref)[1] if ref else None)
        pr = prims.setdefault(mi, {"pos": [], "uv": [], "joints": [], "weights": [], "tris": [], "n": 0})
        for sg in segs:
            pr["pos"].append(sg["pos"])
            pr["uv"].append(sg["uv"])
            pr["joints"].append(sg["joints"])
            pr["weights"].append(sg["weights"])
            pr["tris"].append(sg["tris"] + pr["n"])
            pr["n"] += sg["nv"]
    out = []
    for mi, pr in sorted(prims.items()):
        pos = to_gltf_points(np.concatenate(pr["pos"]))
        tris = np.concatenate(pr["tris"])[:, [0, 2, 1]]    # the mirror into glTF reverses the winding
        img_i, tex_name, mat_name = img_of_mat[mi]
        img = images[img_i]
        out.append({"pos": pos, "nrm": smooth_normals(pos, tris), "uv": np.concatenate(pr["uv"]),
                    "joints": np.concatenate(pr["joints"]), "weights": np.concatenate(pr["weights"]), "tris": tris,
                    "image": img_i, "texture": tex_name, "material": mat_name,
                    "alpha_mask": img is not None and bool((img[..., 3] < 128).mean() > 0.02)})
    return out, images


def extract_package(path, out: Path, name: str | None = None, tex_max: int = TEX_MAX) -> dict:
    """One character package -> rigged, textured GLB + stats + body roles."""
    _s, data = load_package(path)
    pkg = Package(data)
    meshes = pkg.find("SkeletalMesh")
    if not meshes:
        raise FormatError(f"{Path(str(path)).name}: no SkeletalMesh export")
    mesh = parse_mesh(pkg, meshes[0])
    prims, images = mesh_primitives(pkg, mesh, tex_max)
    world = to_gltf_matrices(bind_pose(mesh["bones"]))
    names = [bn["name"] for bn in mesh["bones"]]
    parents = [bn["parent"] if i else -1 for i, bn in enumerate(mesh["bones"])]
    roles = roles_of(mesh["bones"])
    stats = {"mesh": mesh["name"], "bones": len(names), "vertices": int(sum(p["pos"].shape[0] for p in prims)),
             "triangles": int(sum(len(p["tris"]) for p in prims)),
             "segments": sum(len(g) for g in mesh["groups"]), "materials": len(prims),
             "textures": [p["texture"] for p in prims], "lod_vertices": mesh["vertices"],
             "height_m": float(np.ptp(np.concatenate([p["pos"] for p in prims])[:, 1]))}
    write_glb(out, prims, names, parents, world, images, name or mesh["name"],
              extras={"source": Path(str(path)).name, "mesh": mesh["name"], "reader": f"stranglehold_models v{READER_VERSION}"})
    return {"glb": Path(out), "roles": roles, "stats": stats, "mesh": mesh}


# ---------------------------------------------------------------------------------------------- characters DEDICATED
def roster() -> list[dict]:
    return [{"key": stem, "slug": slug, "name": name, "kind": "character", "role": role,
             "aliases": [name.replace(" (Stranglehold)", ""), stem.replace("char_", "")] +
                        (["Tequila", "Inspector Tequila"] if stem == "char_tequila" else [])}
            for stem, slug, name, role in ROSTER]


def cooked_root(ctx=None, game: dict | None = None) -> Path:
    """StrangleholdGame/CookedPS3 from the catalog entry's EBOOT.BIN, else the known QuickSwap mount points."""
    if ctx is not None and game is not None:
        try:
            from . import characters as C
            rom = C._rom(ctx, game)
            for up in [rom.parent] + list(rom.parents)[:3]:
                cand = up / "StrangleholdGame" / "CookedPS3"
                if cand.is_dir():
                    return cand
        except (OSError, ValueError):
            pass
    root = SI.find_root()
    if not root:
        raise FileNotFoundError("Stranglehold CookedPS3 folder not found (QuickSwap2 share)")
    return root


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract: one roster package -> skinned, textured .glb + 18 body roles."""
    root = cooked_root(ctx, game)
    src = root / f"{e['key']}.xxx"
    if not src.is_file():
        raise FileNotFoundError(f"{src} not found")
    out = Path(work) / f"{e['slug']}.glb"
    r = extract_package(src, out, e.get("name"))
    st = r["stats"]
    return {"files": [r["glb"]], "tool": "gbox.stranglehold_models", "roles": r["roles"],
            "source_files": [f"StrangleholdGame/CookedPS3/{src.name}: {st['mesh']}"],
            "notes": f"Stranglehold PS3 {src.name}: {st['bones']} bones, {st['vertices']} vertices, {st['triangles']} "
                     f"triangles in {st['segments']} SPU segments, {st['materials']} materials ({', '.join(filter(None, st['textures']))}); "
                     f"{st['height_m']:.2f} m tall",
            "extra": {"stranglehold_reader": READER_VERSION, "stranglehold_package": src.name, "role": e.get("role")}}


def extract_all(root=None, out_dir: Path = Path("."), only=None, progress=None) -> list[dict]:
    root = Path(root) if root else cooked_root()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, (stem, slug, name, role) in enumerate(ROSTER):
        if only and stem not in only and slug not in only:
            continue
        if progress:
            progress(k, len(ROSTER), stem)
        try:
            r = extract_package(root / f"{stem}.xxx", out_dir / f"{slug}.glb", name)
            rows.append({"slug": slug, "role": role, "glb": str(r["glb"]), "roles": len(r["roles"]), **r["stats"]})
        except Exception as ex:                            # one odd package must not hide the rest
            rows.append({"slug": slug, "role": role, "error": f"{type(ex).__name__}: {ex}"})
    return rows


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("stranglehold_models")
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    for v in (str(out), ",".join(only or [])):
        if v in args:
            args.remove(v)
    rows = extract_all(args[0] if args else None, out, only,
                       progress=lambda k, n, s: print(f"[{k + 1}/{n}] {s}", file=sys.stderr))
    (out / "stranglehold_models.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for r in rows:
        print(r.get("slug"), r.get("error") or f"{r['vertices']} v {r['triangles']} t {r['bones']} bones "
                                                   f"{r['roles']} roles {r['height_m']:.2f} m {r['textures']}")
    return 0 if all("error" not in r for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
