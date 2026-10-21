"""Metal Arms: Glitch in the System (GameCube, GM5E7D) character models: read Glitch and the bots from the disc,
export glTF (skeleton, textures), write a library character into a bot's .ape/.tga in a copy of the disc image.
No third-party tools at run time.

Formats (reversed from main.dol with Ghidra, PowerPC:BE:32:default, r13 = 0x804BABE0, r2 = 0x804C2420; checked
against the USA disc; see docs/model_swaps.md "Metal Arms"):

  * mettlearms_gc.mst (the "master file", 358 MB, the last file on the full 1.36 GB disc): header 'GNAF'
    (FANG little-endian), +0x08 u32 file size, +0x0C u32 entry count (12048), entries from 0x6C, 36 bytes each:
    {char name[20], u32 offset, u32 size, u32 mtime, u32 crc}. Files are packed back to back (no free space).
    Resource types (FRes, registered with an extension): MESH 'ape' (create 0x802A63D4 -> fixup 0x8029DB68),
    TXTR 'tga' (create 0x802B7D14 -> 0x802B7474), animations 'mtx', tables 'csv', worlds 'wld', particles 'fpr'.
  * .ape (FMesh, big-endian, every pointer is a file offset the loader turns into an address, 0x8029DB68):
      0x00 name[16], 0x10 bound sphere, 0x20 bbox min/max, 0x3C u8 nSegBones, 0x3E u8 nBones, 0x40 u8 nSegments,
      0x44 u8 nMaterials, 0x45 u8 nCollTrees, 0x4C f32 lod distances[7],
      0x68 segBones* (24 bytes: sphere, u8 1, u8 bone), 0x6C bones* (0x138 bytes: name[32], boneToModel,
      modelToBone, parentToBone, boneToParent (4x4, row vectors), sphere, u8 parent, u8 nChildren, u8 firstChild),
      0x70 lights*, 0x74 skeleton index bytes*, 0x78 materials* (0x48 bytes: +0 shader regs*, +4 texture layers*,
      +8 u8 shader, +0x10 -> {packets*, u16 n}, +0x16 u8 texcoord sets; layer 0x1C: +0x18 u16 texture name offset), 0x7C collision trees*, 0x80 segments*,
      0x84 -> GC mesh {mesh*, sphere, u8 +0x15 nVB, +0x18 VBs*}.
      VB (0x1C): u32 nPos, u8 posType (1 S8 / 3 S16), u8 posDesc (3 = index16), u8 posStride, u8 posFrac, u16 nColor,
      u8 colorDesc, u8 ?, pos*, color* (RGBA8), st* (2 x S16, frac 8).
      Packet (0x18): u8 flags (0x80 = display list in streaming storage), u8 bone, ..., u8 +0xB VB, u32 dlSize,
      dl*, RGBA. Each packet is drawn with its bone's matrix (rigid): positions are in that bone's space.
      Display list: GX_DRAW_TRIANGLES 0x94 / TRIANGLE_STRIP 0x9C, u16 count, vertices {u16 pos, u16 normal (index
      into the engine's global S8 normal table, frac 6, generated at boot: normal_table() below), u8 color,
      u16 st x nTexSets}.
  * .tga (FTexData, 0x20 header): name[16], +0x14 u8 format (7 = CMPR colour + CMPR alpha in a second mip chain,
    6 = CMPR), +0x17 u8 mip count, +0x1C u16 width, +0x1E u16 height; then the GX image data.
  Coordinates: Y up, the model faces +Z, its left is -X (left-handed). glTF export mirrors X.
"""
from __future__ import annotations

import functools
import json
import math
import struct
import time
import types
from pathlib import Path

import numpy as np

GAME_IDS = {"7e103ec3aab47fa2": "Metal Arms - Glitch in the System (USA)"}
MST = "mettlearms_gc.mst"
SCALE = 0.25                                   # Fang units -> metres in the collection (Glitch ~1.5 m)
NORMAL_ENTRIES = 0x18060 // 3                  # 32800: the engine allocates 0x18060 bytes for the table
LIVE = {"normal_table": 0x804B90F4}
# Body roles on Glitch's skeleton (bone names); he's a robot: short thighs, long shins with a knee dummy, the right
# forearm is his gun arm (no right hand bone: AttachPoint_Primary / Off_R_Hand_Dummy sit where a hand would be).
GLITCH_ROLES = {"pelvis": "Groin", "hip": "Waist", "chest": "Torso", "neck": "Neck", "head": "Head",
                "l_upper": "L_Arm_Upper", "l_fore": "L_Arm_Lower", "l_hand": "L_Hand",
                "r_upper": "R_Shoulder", "r_fore": "R_Arm_Lower", "r_hand": "Off_R_Hand_Dummy",
                "l_thigh": "L_Leg_Upper", "l_shin": "L_Knee", "l_foot": "L_Foot_Back",
                "r_thigh": "R_Leg_Upper", "r_shin": "R_Knee", "r_foot": "R_Foot_Back"}
# other bots: the first bone name present per role
ROLE_CANDIDATES = {"pelvis": ["Groin"], "hip": ["Waist", "Groin"], "chest": ["Torso"], "neck": ["Neck", "NeckA"],
                   "head": ["Head"], "l_upper": ["L_Arm_Upper", "L_ArmB_Upper", "L_Shoulder"],
                   "l_fore": ["L_Arm_Lower", "L_ArmB_Lower"], "l_hand": ["L_Hand"],
                   "r_upper": ["R_Arm_Upper", "R_Shoulder", "R_ArmB_Upper"], "r_fore": ["R_Arm_Lower", "R_ArmB_Lower"],
                   "r_hand": ["R_Hand", "Off_R_Hand_Dummy"], "l_thigh": ["L_Leg_Upper", "L_Leg"],
                   "l_shin": ["L_Knee", "L_Leg_Middle", "L_Leg_Lower"], "l_foot": ["L_Foot_Back", "L_Foot", "L_Foot_Dummy"],
                   "r_thigh": ["R_Leg_Upper", "R_Leg"], "r_shin": ["R_Knee", "R_Leg_Middle", "R_Leg_Lower"],
                   "r_foot": ["R_Foot_Back", "R_Foot", "R_Foot_Dummy"]}
ROSTER = [  # (ape, slug, name, aliases)
    ("grdggltch00", "glitch", "Glitch", ["Glitch", "Metal Arms Glitch", "Metal Arms player"]),
    ("grmggrunt00", "ma_grunt", "Mil Grunt", ["Grunt", "Metal Arms Grunt", "Mil soldier"]),
    ("grdmminer00", "ma_miner", "Droid Miner", ["Miner", "Metal Arms Miner"]),
    ("grdkkrunk00", "ma_krunk", "Krunk", ["Krunk"]),
    ("grdzzobby00", "ma_zobby", "Zobby", ["Zobby"]),
    ("grdxexavo00", "ma_exavolt", "Exavolt", ["Exavolt"]),
    ("grmttitan00", "ma_titan", "Titan", ["Titan", "Mil Titan"]),
    ("grmggrunt01", "ma_grunt2", "Mil Grunt (variant)", ["Grunt 2"]),
]


# ---------------------------------------------------------------------------------------------------- master file
class Master:
    """The .mst directory inside a disc image (read-only; patches go through write_entry)."""

    def __init__(self, iso: Path):
        from .gcdisc import GCDisc
        self.iso = Path(iso)
        d = GCDisc(iso)
        try:
            self.base, self.size = d.files[MST]
            h = d._r(self.base, 0x10)
            if h[:4] != b"GNAF":
                raise ValueError(f"{MST}: not a Fang master file")
            n = struct.unpack_from(">I", h, 0xC)[0]
            raw = d._r(self.base + 0x6C, 36 * n)
        finally:
            d.f.close()
        self.entries: dict[str, dict] = {}
        for i in range(n):
            name = raw[36 * i:36 * i + 20].split(b"\0")[0].decode("latin-1")
            off, size, mtime, crc = struct.unpack_from(">4I", raw, 36 * i + 20)
            self.entries[name.lower()] = {"name": name, "index": i, "offset": off, "size": size, "crc": crc}

    def read(self, name: str) -> bytes:
        e = self.entries[name.lower()]
        with open(self.iso, "rb") as f:
            f.seek(self.base + e["offset"])
            return f.read(e["size"])

    def write_entry(self, f, name: str, data: bytes):
        """Overwrite one file in place in an open (r+b) image; it must fit its slot. The directory size is updated
        and the slot's tail zeroed."""
        e = self.entries[name.lower()]
        if len(data) > e["size"]:
            raise ValueError(f"{name}: {len(data)} bytes > its {e['size']}-byte slot in {MST}")
        f.seek(self.base + e["offset"])
        f.write(data + bytes(e["size"] - len(data)))
        f.seek(self.base + 0x6C + 36 * e["index"] + 24)
        f.write(struct.pack(">I", len(data)))


# ------------------------------------------------------------------------------------------------------------ mesh
def normal_table_s8() -> np.ndarray:
    """The engine's global normal table as it sits in RAM (the pointer at LIVE["normal_table"]): 32800 S8 xyz with
    6 fraction bits, rebuilt the way main.dol builds it at boot (0x8028E608, called from the mesh system's init).
    Nothing is read from the disc: the table is pure arithmetic, so it is regenerated here instead of shipping a RAM dump.

    Eight 4096-entry octant blocks, then the six axis normals, then 26 zero entries (the allocation is rounded up).
    Block 0 (+x, +y, +z): entry 0 is (0, 0, 0); then for theta = 1..90 degrees (y = 64 cos theta) a ring of
    theta entries with phi = 90 * j / theta for j = theta..1: x = 64 sin theta sin phi, z = 64 sin theta cos phi.
    1 + 1 + 2 + ... + 90 = 4096. The other blocks are the same ring set with the signs flipped per octant, in the
    order +++, -++, -+-, ++-, +-+, --+, ---, +--. Every product is rounded to float32 like the Gekko's fmuls, the
    angle scale is the float32 pi / 180 the binary holds (0x3C8EFA35) and each component is truncated toward zero
    (fctiwz), which is what makes the table match the RAM dump byte for byte (sin 30 degrees comes out as exactly
    32 only because the float32 rounding lands on 0.5)."""
    f32 = np.float32
    deg, sixty_four, ninety = f32(0.01745329238474369), f32(64.0), f32(90.0)
    block = np.zeros((4096, 3), np.int8)
    n = 1
    for k in range(1, 91):                                     # theta counts up by 1.0f from 0; theta 0 has no ring
        theta = f32(k)
        rad = f32(deg * theta)
        s, c = f32(math.sin(float(rad))), f32(math.cos(float(rad)))
        y = int(f32(sixty_four * c))
        phi = deg * (f32(ninety / theta) * np.arange(k, 0, -1, dtype=f32))        # each product rounded to float32
        sp = np.array([math.sin(v) for v in phi.tolist()], f32)
        cp = np.array([math.cos(v) for v in phi.tolist()], f32)
        block[n:n + k, 0] = np.trunc(sixty_four * (s * sp)).astype(np.int8)
        block[n:n + k, 1] = y
        block[n:n + k, 2] = np.trunc(sixty_four * (s * cp)).astype(np.int8)
        n += k
    assert n == 4096
    signs = np.array([(1, 1, 1), (-1, 1, 1), (-1, 1, -1), (1, 1, -1), (1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1)],
                     np.int8)
    axes = np.array([(0, 64, 0), (0, -64, 0), (64, 0, 0), (-64, 0, 0), (0, 0, 64), (0, 0, -64)], np.int8)
    table = np.zeros((NORMAL_ENTRIES, 3), np.int8)
    for i, sg in enumerate(signs):
        table[4096 * i:4096 * (i + 1)] = block * sg
    table[8 * 4096:8 * 4096 + 6] = axes
    return table


@functools.lru_cache(maxsize=1)
def normal_table() -> np.ndarray:
    """normal_table_s8() as unit-ish float32 vectors (divided by 64, the 6 fraction bits); cached for the process."""
    t = normal_table_s8().astype(np.float32) / 64.0
    t.setflags(write=False)
    return t


def _cstr(b: bytes, o: int) -> str:
    return b[o:b.index(b"\0", o)].decode("latin-1")


class Ape:
    def __init__(self, data: bytes):
        self.b = b = bytes(data)
        U = self.U
        self.name = _cstr(b, 0)
        self.n_bones, self.n_mats = b[0x3E], b[0x44]
        (self.p_segbones, self.p_bones, self.p_lights, self.p_skel, self.p_mats, self.p_coll, self.p_segs,
         self.p_gc) = U("8I", 0x68)
        self.bones = []
        for i in range(self.n_bones):
            o = self.p_bones + 0x138 * i
            m = [np.array(U("16f", o + 32 + 64 * k), float).reshape(4, 4) for k in range(4)]
            self.bones.append({"name": _cstr(b, o), "b2m": m[0], "m2b": m[1], "parent": b[o + 0x130],
                               "nchild": b[o + 0x131], "off": o})
        nvb, pvb = b[self.p_gc + 0x15], U("I", self.p_gc + 0x18)[0]
        self.vbs = []
        for i in range(nvb):
            o = pvb + 0x1C * i
            npos, ptype, pdesc, pstride, pfrac, ncol, cdesc, x, ppos, pcol, pst, p18 = U("I4BH2B4I", o)
            self.vbs.append({"off": o, "npos": npos, "ptype": ptype, "pdesc": pdesc, "pstride": pstride, "pfrac": pfrac,
                             "ncol": ncol, "cdesc": cdesc, "pos": ppos, "col": pcol, "st": pst})
        self.mats = []
        for m in range(self.n_mats):
            mo = self.p_mats + 0x48 * m
            sub = U("I", mo + 0x10)[0]
            pk, npk = U("IH", sub) if sub else (0, 0)
            packets = []
            for i in range(npk):
                r = pk + 0x18 * i
                size, dl = U("II", r + 0xC)
                packets.append({"off": r, "flags": b[r], "bone": b[r + 1], "vb": b[r + 0xB], "size": size, "dl": dl})
            self.mats.append({"off": mo, "shader": b[mo + 8], "ntex": b[mo + 0x16], "sub": sub, "packets": packets,
                              "textures": self._mat_textures(mo)})

    def U(self, f: str, o: int):
        return struct.unpack_from(">" + f, self.b, o)

    def _mat_textures(self, mo: int) -> list[str]:
        """Texture names of the material's layers (+4 -> layer pointer list; layer record +0x10 u32 3, +0x18 u16 = name offset)."""
        out, p = [], self.U("I", mo + 4)[0]
        for k in range(24):
            v = self.U("I", p + 4 * k)[0]
            if v == 0xFFFFFFFF:
                break
            if 0x88 < v < len(self.b) - 0x1C and self.U("I", v + 0x10)[0] == 3:
                no = self.U("H", v + 0x18)[0]
                if 0 < no < 0x400 and 32 <= self.b[no] < 127:
                    out.append(_cstr(self.b, no))
        return out

    def vertex_size(self, mat: dict) -> int:
        return 5 + 2 * mat["ntex"]

    def packet_tris(self, mat: dict, pk: dict) -> list[tuple]:
        """-> [(v0, v1, v2)] with v = (pos, nrm, col, st...) index tuples, in GX order."""
        b, stride, ntex = self.b, self.vertex_size(mat), mat["ntex"]
        p, end, tris = pk["dl"], pk["dl"] + pk["size"], []
        while p < end:
            op = b[p]
            if op == 0:
                p += 1
                continue
            if op & 0xF8 not in (0x90, 0x98):
                raise ValueError(f"{self.name}: display-list opcode {op:#x} at {p:#x}")
            n = self.U("H", p + 1)[0]
            vs = []
            for k in range(n):
                q = p + 3 + k * stride
                vs.append(struct.unpack_from(">HHB" + "H" * ntex, b, q))
            p += 3 + n * stride
            if op & 0xF8 == 0x90:
                tris += [tuple(vs[i:i + 3]) for i in range(0, n - 2, 3)]
            else:
                for i in range(n - 2):
                    t = (vs[i], vs[i + 1], vs[i + 2]) if i % 2 == 0 else (vs[i + 1], vs[i], vs[i + 2])
                    if len({t[0][0], t[1][0], t[2][0]}) == 3:
                        tris.append(t)
        return tris

    def vb_arrays(self, vb: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        b = self.b
        dt = {1: ">i1", 3: ">i2", 0: ">u1", 2: ">u2"}[vb["ptype"]]
        pos = np.frombuffer(b, dt, vb["npos"] * 3, vb["pos"]).reshape(-1, 3).astype(float) / (1 << vb["pfrac"])
        col = np.frombuffer(b, np.uint8, vb["ncol"] * 4, vb["col"]).reshape(-1, 4)
        nst = (len(b) - vb["st"]) // 4
        st = np.frombuffer(b, ">i2", nst * 2, vb["st"]).reshape(-1, 2).astype(float) / 256.0
        return pos, col, st

    def bone_world(self, i: int) -> np.ndarray:
        return self.bones[i]["b2m"]


# --------------------------------------------------------------------------------------------------------- texture
def tex_decode(data: bytes, mask: bool = False) -> np.ndarray:
    """Fang GC .tga -> RGBA (top mip). Format 7 = CMPR colour + a second CMPR chain the shaders use as a mask
    (Glitch: the reflection/specular mask, not transparency): alpha = that mask only with mask=True, else 255."""
    from .re4gc_models import tpl_decode_image
    fmt, mips = data[0x14], data[0x17]
    w, h = struct.unpack_from(">HH", data, 0x1C)
    body = data[0x20:]
    if fmt in (6, 7):
        img = tpl_decode_image(14, w, h, body)[:h, :w].copy()
        if fmt == 7 and mask:
            half = len(body) // 2
            a = tpl_decode_image(14, w, h, body[half:])[:h, :w]
            img[..., 3] = a[..., 1]
        else:
            img[..., 3] = 255
        return img
    raise ValueError(f"texture format {fmt} not supported yet")


def _mips(img: np.ndarray, n: int) -> list[np.ndarray]:
    from PIL import Image
    out, im = [], Image.fromarray(np.ascontiguousarray(img)).convert("RGBA")
    w, h = im.size
    for k in range(n):
        out.append(np.array(im.resize((max(8, w >> k), max(8, h >> k)), Image.LANCZOS)))
    return out


def tex_encode(orig: bytes, img: np.ndarray) -> bytes:
    """A new image in the original texture's header, size, format and mip count (so it fits the same slot)."""
    from .re4gc_models import cmpr_encode
    from PIL import Image
    fmt, mips = orig[0x14], orig[0x17]
    w, h = struct.unpack_from(">HH", orig, 0x1C)
    if fmt not in (6, 7):
        raise ValueError(f"texture format {fmt} not supported yet")
    img = np.array(Image.fromarray(np.ascontiguousarray(img)).convert("RGBA").resize((w, h), Image.LANCZOS))
    chain = _mips(img, mips)
    col = b"".join(cmpr_encode(np.concatenate([m[..., :3], np.full(m.shape[:2] + (1,), 255, np.uint8)], -1))
                   for m in chain)
    out = col
    if fmt == 7:
        out += b"".join(cmpr_encode(np.repeat(m[..., 3:4], 4, -1) | np.array([0, 0, 0, 255], np.uint8)) for m in chain)
    out = orig[:0x20] + out
    if len(out) != len(orig):
        raise ValueError(f"texture size {len(out)} != {len(orig)}")
    return out


# ------------------------------------------------------------------------------------------------------- to glTF
MIRROR = np.diag([-1.0, 1.0, 1.0])


def ape_prims(m: Ape, textures: dict[str, np.ndarray]) -> list[dict]:
    """Glitch-space (mirrored to glTF axes) rigid primitives: one per material, J = packet bone."""
    nt = normal_table()
    prims = []
    vbd = [m.vb_arrays(v) for v in m.vbs]
    for mi, mat in enumerate(m.mats):
        P, N, UV, J, C, T = [], [], [], [], [], []
        for pk in mat["packets"]:
            if pk["flags"] & 0x80:
                continue
            pos, col, st = vbd[pk["vb"]]
            M = m.bones[pk["bone"]]["b2m"]
            for tri in m.packet_tris(mat, pk):
                base = len(P)
                for v in tri:
                    p = np.append(pos[v[0]], 1.0) @ M
                    n = nt[v[1]] @ M[:3, :3]
                    P.append(p[:3] @ MIRROR)
                    N.append(n @ MIRROR)
                    UV.append(st[v[3]] if mat["ntex"] and v[3] < len(st) else (0.0, 0.0))
                    J.append(pk["bone"])
                    C.append(col[v[2]] if v[2] < len(col) else (255, 255, 255, 255))
                a, bb, c = np.array(P[base:base + 3])
                fn = np.cross(bb - a, c - a)
                if fn @ np.sum(N[base:base + 3], 0) < 0:        # wind each triangle to agree with its normals
                    T.append((base, base + 2, base + 1))
                else:
                    T.append((base, base + 1, base + 2))
        if not T:
            continue
        Jm = np.zeros((len(P), 4), np.int64)
        Jm[:, 0] = J
        Wm = np.zeros((len(P), 4))
        Wm[:, 0] = 1
        tn = mat["textures"][0] if mat["textures"] else None
        prims.append({"pos": np.array(P), "nrm": np.array(N), "uv": np.array(UV), "tris": np.array(T, np.int64),
                      "J": Jm, "W": Wm, "tex": textures.get((tn or "").lower()), "name": f"{m.name}_m{mi}_{tn}",
                      "color": (200, 200, 200, 255)})
    return prims


def ape_to_gltf(m: Ape, textures: dict[str, np.ndarray], out: Path) -> Path:
    from .melee_models import write_gltf
    joints = []
    for bn in m.bones:
        w = np.eye(4)
        w[:3, 3] = bn["b2m"][3, :3] @ MIRROR
        joints.append({"parent": bn["parent"] if bn["parent"] != 0xFF else -1, "world": w})
    prims = ape_prims(m, textures)
    return write_gltf(Path(out), joints, prims, SCALE, m.name, [bn["name"] for bn in m.bones])


def load_textures(mst: Master, m: Ape) -> dict[str, np.ndarray]:
    out = {}
    for mat in m.mats:
        for t in mat["textures"][:1]:
            if t.lower() in out or (t.lower() + ".tga") not in mst.entries:
                continue
            try:
                out[t.lower()] = tex_decode(mst.read(t + ".tga"))
            except ValueError:
                pass
    return out


def extract(iso: Path, ape_name: str, out: Path) -> dict:
    mst = Master(iso)
    m = Ape(mst.read(ape_name + ".ape"))
    texs = load_textures(mst, m)
    p = ape_to_gltf(m, texs, out)
    return {"path": str(p), "bones": m.n_bones, "materials": len(m.mats),
            "triangles": sum(len(pr["tris"]) for pr in ape_prims(m, texs)), "textures": sorted(texs)}


# ---------------------------------------------------------------------------------------------------------- writer
class _Template:
    """Duck-typed re4gc_models.Bin for re4gc_enemies.retarget(): bones (index, parent), positions in glTF axes x100."""

    def __init__(self, m: Ape):
        self.bones = [(k, b["parent"]) for k, b in enumerate(m.bones)]
        self._w = {k: (b["b2m"][3, :3] @ MIRROR) * 100.0 for k, b in enumerate(m.bones)}

    def bone_world(self):
        return self._w


def retarget_onto(m: Ape, src_model: Path, src_roles: dict, scale: dict | None = None) -> list[dict]:
    """A library character -> prims in the .ape's model space (Fang units, left-handed): pos, nrm, tris, bone per
    vertex (rigid), uv, tex, color."""
    from .characters import rig_from_gltf
    from .re4gc_enemies import retarget
    rig = rig_from_gltf(Path(src_model), src_roles)
    names = [b["name"] for b in m.bones]
    roles = {r: names.index(n) for r, n in roles_for(m, retarget=True).items()}
    prims = retarget(rig, _Template(m), roles=roles, height_range=(330.0, 520.0), scale=scale, fit_shoulders=True)
    for p in prims:
        p["pos"] = (np.asarray(p["pos"], float) / 100.0) @ MIRROR
        p["nrm"] = np.asarray(p["nrm"], float) @ MIRROR
        p["bone"] = np.asarray(p["J"])[:, 0].astype(int)
    return prims


def strips_cw(tris: list[tuple]) -> tuple[list[list[int]], list[tuple]]:
    """Greedy triangle strips that keep every triangle's winding (GX strip parity: triangle k of a strip is
    (v[k], v[k+1], v[k+2]) for even k, (v[k+1], v[k], v[k+2]) for odd k). Returns (strips, leftover triangles)."""
    left = set(range(len(tris)))
    edge = {}
    for i, (a, b, c) in enumerate(tris):
        for e, w in (((a, b), c), ((b, c), a), ((c, a), b)):
            edge.setdefault(e, []).append((i, w))
    strips, singles = [], []
    while left:
        i = min(left)
        left.discard(i)
        best = None
        for rot in range(3):                                   # each rotation of the seed: keep the longest strip
            t0 = tris[i]
            v, used = [t0[rot], t0[(rot + 1) % 3], t0[(rot + 2) % 3]], []
            k = 1
            while True:
                e = (v[-2], v[-1]) if k % 2 == 0 else (v[-1], v[-2])
                nxt = next(((j, w) for j, w in edge.get(e, ()) if j in left and j not in used), None)
                if nxt is None:
                    break
                used.append(nxt[0])
                v.append(nxt[1])
                k += 1
            if best is None or len(used) > len(best[1]):
                best = (v, used)
        v, used = best
        for j in used:
            left.discard(j)
        if used:
            strips.append(v)
        else:
            singles.append(tuple(v))
    return strips, singles


def _nearest_normals(n: np.ndarray, table: np.ndarray) -> np.ndarray:
    tn = table / np.maximum(np.linalg.norm(table, axis=1, keepdims=True), 1e-6)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    out = np.empty(len(n), np.int64)
    for k in range(0, len(n), 2048):
        out[k:k + 2048] = (n[k:k + 2048] @ tn.T).argmax(1)
    return out


def _al(n: int, a: int = 32) -> int:
    return (n + a - 1) // a * a


def _pointer_slots(m: Ape) -> list[int]:
    """Every pointer slot in the .ape (from the loader's fixup, 0x8029DB68), for relocating a moved region."""
    U, b, out = m.U, m.b, [0x68 + 4 * k for k in range(8)]
    for mat in m.mats:
        out += [mat["off"], mat["off"] + 4, mat["off"] + 0x10]
        if mat["sub"]:
            out.append(mat["sub"])
            for pk in mat["packets"]:
                if not pk["flags"] & 0x80:
                    out.append(pk["off"] + 0x10)
    if m.p_coll:
        for i in range(b[0x45]):
            e = m.p_coll + 0x44 * i
            out += [e + 8, e + 0x10, e + 0x40]
            arr, n = U("I", e + 8)[0], U("H", e + 6)[0]
            for k in range(n if arr else 0):
                out += [arr + 0x10 * k, arr + 0x10 * k + 4]
    g = m.p_gc
    out += [g + 0x18, g + 0x1C]
    for v in m.vbs:
        out += [v["off"] + 0xC, v["off"] + 0x10, v["off"] + 0x14, v["off"] + 0x18]
    x = U("I", g + 0x1C)[0]
    if x:
        out += [x + 8, x + 0x10, x + 0x14]
    return sorted(set(out))


def main_material(m: Ape) -> int:
    """The material the new character is drawn with: the first textured one (Glitch: 0, 2 texcoord sets)."""
    return next((i for i, mt in enumerate(m.mats) if mt["ntex"] >= 1 and mt["textures"] and mt["sub"]), 0)


def build_ape(m: Ape, prims: list[dict], atlas_uvs: list[np.ndarray], color: tuple = (0, 0, 0, 128)) -> tuple[bytes, dict]:
    """Rewrite the .ape's geometry: every triangle goes into the main material (main_material: its shader, texture
    and texcoord-set count decide the display-list vertex layout),
    one display-list packet per bone (rigid, positions in the bone's space, S16 in the VBs drawn with the engine's
    dynamic vertex format 7); the other materials draw nothing. Skeleton, materials, lights and collision trees are
    kept (the collision block moves behind the new geometry and its pointers are relocated).
    prims: Fang model space {pos, nrm, tris, bone (per vertex)}; atlas_uvs: per prim (t, 3, 2) corner uvs."""
    U = m.U
    table = normal_table()
    mm = main_material(m)
    ntex = m.mats[mm]["ntex"]
    vfmt = ">HHB" + "H" * ntex
    corners = {}                                               # bone -> [(pos, nrm, uv) x 3] per triangle
    for p, uv in zip(prims, atlas_uvs):
        P, N, T, B = p["pos"], p["nrm"], np.asarray(p["tris"], int).reshape(-1, 3), np.asarray(p["bone"], int)
        for t, tri in enumerate(T):
            bone = int(np.bincount(B[tri]).argmax())
            corners.setdefault(bone, []).append([(P[v], N[v], uv[t, k]) for k, v in enumerate(tri)])
    locs = {}
    for bone, tris in corners.items():
        M = m.bones[bone]["m2b"]
        allp = np.array([c[0] for t in tris for c in t])
        alln = np.array([c[1] for t in tris for c in t])
        lp = np.c_[allp, np.ones(len(allp))] @ M
        ln = alln @ M[:3, :3]
        # library models disagree on what's outside (FF7 ones are inside-out, Melee winds against its normals): the
        # normals must point away from the part (the engine lights with them) and the winding follows them below
        cen = lp[:, :3].mean(0)
        tc = lp[:, :3].reshape(-1, 3, 3).mean(1) - cen
        if ((ln.reshape(-1, 3, 3).sum(1) * tc).sum(1) > 0).mean() < 0.5:
            ln = -ln
        locs[bone] = (lp[:, :3], _nearest_normals(ln, table), np.array([c[2] for t in tris for c in t]))
    mx = max(float(np.abs(v[0]).max()) for v in locs.values()) if locs else 1.0
    frac = int(max(0, min(14, np.floor(np.log2(32767.0 / max(mx, 1e-3))))))
    q = float(1 << frac)
    pos_l, st_l, pos_ix, st_ix, dl_blobs = [], [], {}, {}, []
    for bone, (lp, ni, uvs) in sorted(locs.items()):
        idx = []
        for k in range(len(lp)):
            pk_ = tuple(int(round(x * q)) for x in lp[k])
            if pk_ not in pos_ix:
                pos_ix[pk_] = len(pos_l)
                pos_l.append(pk_)
            sk = (int(np.clip(round(uvs[k][0] * 256), -32768, 32767)), int(np.clip(round(uvs[k][1] * 256), -32768, 32767)))
            if sk not in st_ix:
                st_ix[sk] = len(st_l)
                st_l.append(sk)
            idx.append((pos_ix[pk_], int(ni[k]), 0) + (st_ix[sk],) * ntex)
        vid, verts, tri_v = {}, [], []
        for t in range(len(idx) // 3):
            tv = []
            for k in range(3):
                key = idx[3 * t + k]
                if key not in vid:
                    vid[key] = len(verts)
                    verts.append(key)
                tv.append(vid[key])
            if len({verts[x][0] for x in tv}) < 3:
                continue
            a, bb, c = (np.array(pos_l[verts[x][0]], float) for x in tv)
            n = sum(table[verts[x][1]] for x in tv)
            if np.cross(bb - a, c - a) @ n > 0:                # the engine's front face: cross . normal < 0
                tv = [tv[0], tv[2], tv[1]]
            tri_v.append(tuple(tv))
        strips, singles = strips_cw(tri_v)
        dl = bytearray()
        for sv in strips:
            dl += struct.pack(">BH", 0x9F, len(sv)) + b"".join(struct.pack(vfmt, *verts[x]) for x in sv)
        if singles:
            flat = [x for t in singles for x in t]
            dl += struct.pack(">BH", 0x97, len(flat)) + b"".join(struct.pack(vfmt, *verts[x]) for x in flat)
        dl += bytes(_al(len(dl)) - len(dl))
        dl_blobs.append((bone, bytes(dl), len(strips), len(singles)))
    if len(pos_l) > 0xFFFF or len(st_l) > 0xFFFF:
        raise ValueError(f"too many vertices for 16-bit indices ({len(pos_l)} positions, {len(st_l)} uvs)")
    # layout: [0, first VB array) kept | positions | colour | st | packet records | display lists | collision (moved)
    start = min(min(v["pos"], v["col"], v["st"]) for v in m.vbs)
    coll = m.p_coll if m.p_coll else len(m.b)
    out = bytearray(m.b[:start])
    p_pos = len(out)
    out += np.array(pos_l, ">i2").tobytes()
    out += bytes(_al(len(out)) - len(out))
    p_col = len(out)
    out += bytes(color) * 2
    out += bytes(_al(len(out)) - len(out))
    p_st = len(out)
    out += np.array(st_l, ">i2").tobytes()
    out += bytes(_al(len(out)) - len(out))
    # one packet record per (LOD, bone): packet +2 = the LOD it's drawn at (the renderer picks one by distance), +3 =
    # the part bit tested against the instance's part mask; all LODs share the one display list per bone
    lods = sorted({m.b[pk["off"] + 2] for mt in m.mats for pk in mt["packets"]}) or [0]
    p_pk = len(out)
    out += bytes(_al(0x18 * len(dl_blobs) * len(lods)))
    recs = []
    for bone, dl, ns, nl in dl_blobs:
        recs.append((bone, len(out), len(dl), ns, nl))
        out += dl
    delta = len(out) - coll
    out += m.b[coll:]
    for s_ in _pointer_slots(m):                           # relocate pointers that point into the moved block
        if start <= s_ < coll:
            continue                                       # slots inside the replaced region: rewritten below
        o = s_ if s_ < coll else s_ + delta
        v = struct.unpack_from(">I", out, o)[0]
        if v >= coll:
            struct.pack_into(">I", out, o, v + delta)
    k = 0
    for lod in lods:
        for bone, off, size, ns, nl in recs:
            struct.pack_into(">BBBBHHHBBII4B", out, p_pk + 0x18 * k, 0, bone, lod, 0, 7, nl, ns, 1, 0, size, off,
                             0, 0, 0, 0)
            k += 1
    for vb in m.vbs:                                       # every VB -> the new arrays: S16 positions, format 7
        o = vb["off"]
        struct.pack_into(">I4BH2B", out, o, len(pos_l), 3, 3, 6, frac, 2, 2, 7)
        struct.pack_into(">III", out, o + 0xC, p_pos, p_col, p_st)
    for i, mat in enumerate(m.mats):
        if mat["sub"]:
            if i == mm:
                struct.pack_into(">IH", out, mat["sub"], p_pk, len(recs) * len(lods))
            else:
                struct.pack_into(">H", out, mat["sub"] + 4, 0)
    stats = {"bones": len(recs), "lods": len(lods), "positions": len(pos_l), "uvs": len(st_l), "frac": frac,
             "triangles": sum(len(c) for c in corners.values()), "bytes": len(out), "slot": len(m.b),
             "dl_bytes": sum(len(d[1]) for d in dl_blobs)}
    return bytes(out), stats


# ------------------------------------------------------------------------------------------------- building a mod
# Glitch's files, grouped by the texture they share: story (00, 01 = a variant some levels load), cutscenes (gcd*)
PLAYER_GROUPS = [["grdggltch00", "grdggltch01"], ["gcdggltch00", "gcdggltch01"]]
MAX_TRIS = 3000


def _decimate_to(src: Path, work: Path, tris: int, budget: int) -> Path:
    from .re4gc_enemies import decimate
    return decimate(src, Path(work) / f"dec_{budget}.glb", float(budget))   # amount > 1 = target triangles


def swap_group(mst: Master, ape_names: list[str], model: Path, roles: dict, work: Path, scale: dict | None = None,
               mask: int = 40) -> dict:
    """Bot files that share one texture (Glitch: grdggltch00 + 01 -> trdggltch00): decimate the character once until
    every file fits its slot, retarget onto each file's skeleton, atlas once into the shared texture slot (same
    triangles in the same order, so the atlas uvs are shared). Returns {files: {name: bytes}, stats}."""
    from .characters import model_stats
    from .gta_stories_models import pack_atlases
    ms = [Ape(mst.read(a + ".ape")) for a in ape_names]
    tex_name = ms[0].mats[main_material(ms[0])]["textures"][0] if ms[0].mats[main_material(ms[0])]["textures"] else None
    if not tex_name or (tex_name.lower() + ".tga") not in mst.entries:
        raise ValueError(f"{ape_names[0]}: no texture slot to write")
    torig = mst.read(tex_name + ".tga")
    w, h = struct.unpack_from(">HH", torig, 0x1C)
    src, tried = Path(model), []
    tris = int(model_stats(src).get("triangles", 0) or 0)
    budget = min(tris or MAX_TRIS, MAX_TRIS)
    for attempt in range(10):
        cur = src if budget >= tris else _decimate_to(src, work, tris, budget)
        out, stats, atlas, uvs, worst = {}, {}, None, None, 0.0
        for a, m in zip(ape_names, ms):
            prims = retarget_onto(m, cur, roles, scale)
            if uvs is None:
                atlases, uvs = pack_atlases(prims, [(w, h)])
                atlas = atlases[0]
            data, st = build_ape(m, prims, [u for _, u in uvs])
            out[a + ".ape"], stats[a] = data, st
            worst = max(worst, st["bytes"] / st["slot"])
        tried.append({"budget": budget, "worst_fill": round(worst, 3)})
        if worst <= 1.0:
            img = atlas.copy()
            img[..., 3] = mask                              # the second CMPR chain: the reflection mask
            out[tex_name + ".tga"] = tex_encode(torig, img)
            return {"files": out, "stats": {"files": stats, "texture": tex_name, "tried": tried}}
        budget = int(min(budget, tris or budget) * min(0.9, 0.95 / worst))
    raise ValueError(f"{ape_names}: the model doesn't fit the slots: {tried}")


def build_mod(cfg, game: dict, iso: Path, model: Path, roles: dict, name: str, image_name: str,
              groups: list[list[str]] | None = None, scale: dict | None = None, progress=None) -> dict:
    """lcs/re4-style file mod: a copy of the disc image with the bot files rewritten in place inside the .mst."""
    import os
    import shutil
    from . import filemods
    progress = progress or (lambda p, m: None)
    mst = Master(iso)
    work = Path(cfg.cache) / "characters_build" / "metal_arms" / name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out, stats = {}, {}
    groups = groups or PLAYER_GROUPS
    for k, g in enumerate(groups):
        progress(30 + 30 * k / len(groups), f"Fitting the character onto {', '.join(g)}")
        r = swap_group(mst, g, model, roles, work, scale)
        out.update(r["files"])
        stats[g[0]] = r["stats"]
    patches = []
    for fname, data in out.items():
        e = mst.entries[fname.lower()]
        if len(data) > e["size"]:
            raise ValueError(f"{fname}: {len(data)} > {e['size']}")
        patches.append({"offset": mst.base + e["offset"], "hex": (data + bytes(e["size"] - len(data))).hex()})
        patches.append({"offset": mst.base + 0x6C + 36 * e["index"] + 24, "hex": struct.pack(">I", len(data)).hex()})
    link = work / image_name
    if link.exists():
        link.unlink()
    os.link(iso, link)
    stale = Path(cfg.cache) / game["game_id"] / image_name     # a staged older build with the same name + size
    if stale.exists():
        stale.unlink()
    progress(70, f"Writing the disc image {image_name}")
    try:
        b = filemods.build_image(types.SimpleNamespace(cache=Path(cfg.cache)), game["game_id"], link, name,
                                 {"@image": {"patch": patches}})
    finally:
        link.unlink()
    return b | {"files": sorted(out), "stats": stats}


# ------------------------------------------------------------------------------------------------ live identification
# GameCube RAM (Ghidra + live checks, USA): Player_aPlayer at 0x80481AF8 (0x24C8 bytes each; the player update
# 0x801C9B20 is called with it): +0x18D8 the player's own bot (Glitch), +0x18DC the entity he controls now (Glitch can
# possess other bots). Entity: +0x40 world position, +0x13C flags (bit 0 = a bot), +0x1B8 CFWorldMesh*.
# CFWorldMesh: +0 vtable 0x803D5354, +0x10 owner entity, +0x3C bound radius + centre, +0x60 mesh instance whose +0 is
# the FMesh* (the loaded .ape: its name at +0). Camera-to-world (3 axis rows + position, row vectors): 0x804A2DE0.
LIVE.update({"players": 0x80481AF8, "player_size": 0x24C8, "player_bot": 0x18D8, "player_entity": 0x18DC,
             "ent_pos": 0x40, "ent_flags": 0x13C, "ent_worldmesh": 0x1B8, "wm_vtable": 0x803D5354, "wm_owner": 0x10,
             "wm_sphere": 0x3C, "wm_inst": 0x60, "camera": 0x804A2DE0, "heap": (0x80600000, 0x81000000)})
NAMES = {a: n for a, _s, n, _al in ROSTER} | {"grdggltchmp": "Glitch (multiplayer)", "gcdggltch00": "Glitch (cutscene)"}


def _rd(ctx, sid: str, addr: int, n: int, tries: int = 3) -> bytes:
    """Read guest RAM through the session (Dolphin's GDB stub refuses a read now and then: retry)."""
    from .characters import _api
    for k in range(tries):
        try:
            return bytes.fromhex(_api(ctx, "POST", f"/api/sessions/{sid}/rpc",
                                      json={"op": "read_memory", "args": {"address": addr, "length": n}}))
        except Exception:                                   # noqa: BLE001
            if k == tries - 1:
                raise
            time.sleep(0.3)


def _u32(ctx, sid, a):
    return struct.unpack(">I", _rd(ctx, sid, a, 4))[0]


def _mesh_name(ctx, sid, wm: int) -> str | None:
    if not 0x80000000 <= wm < 0x81800000 or _u32(ctx, sid, wm) != LIVE["wm_vtable"]:
        return None
    inst = wm + LIVE["wm_inst"]
    mesh = _u32(ctx, sid, inst)
    if not 0x80000000 <= mesh < 0x81800000:
        return None
    return _rd(ctx, sid, mesh, 16).split(b"\0")[0].decode("latin-1")


def identify(ctx, sid: str) -> dict:
    """Who the player is in a running Metal Arms session: Player[0] -> the entity he controls -> its world mesh ->
    the .ape loaded for it (Glitch = grdggltch00/01; a possessed bot = that bot's .ape)."""
    p = LIVE["players"]
    own, cur = struct.unpack(">II", _rd(ctx, sid, p + LIVE["player_bot"], 8))
    if not (0x80000000 <= cur < 0x81800000):
        return {"status": "no_player", "message": "no player bot yet (title screen, menu or loading)"}
    ent = _rd(ctx, sid, cur, 0x1C0)
    wm = struct.unpack_from(">I", ent, LIVE["ent_worldmesh"])[0]
    ape = _mesh_name(ctx, sid, wm)
    if ape is None:
        return {"status": "no_player", "message": "the player bot has no mesh yet (loading)"}
    pos = [round(x, 2) for x in struct.unpack_from(">3f", ent, LIVE["ent_pos"])]
    who = NAMES.get(ape, ape)
    poss = cur != own
    return {"status": "ok", "entity": cur, "own_bot": own, "ape": ape + ".ape", "model": who, "position": pos,
            "possessing": poss, "message": (f"You are playing as Glitch, possessing a {who} ({ape}.ape)." if poss else
                                            f"You are playing as {who} ({ape}.ape).")}


def _camera(ctx, sid):
    m = np.array(struct.unpack(">16f", _rd(ctx, sid, LIVE["camera"], 64)), float).reshape(4, 4)
    R, t = m[:3, :3], m[3, :3]
    if not np.isfinite(m).all() or np.abs(R @ R.T - np.eye(3)).max() > 1e-2:
        raise ValueError("camera matrix not found (not in game?)")
    return R, t


def bots_on_screen(ctx, sid: str, tan_half_fov: float = 0.70) -> list[dict]:
    """Every bot world mesh in the heap (scan for the CFWorldMesh vtable), projected with the game camera:
    [{ape, name, entity, position, screen (x, y fractions), distance}] nearest first. Takes ~40 s over the GDB stub."""
    lo, hi = LIVE["heap"]
    vt = struct.pack(">I", LIVE["wm_vtable"])
    R, t = _camera(ctx, sid)
    me = struct.unpack(">I", _rd(ctx, sid, LIVE["players"] + LIVE["player_entity"], 4))[0]
    out, names = [], {}
    for a in range(lo, hi, 0x8000):
        try:
            blk = _rd(ctx, sid, a, 0x8000)
        except Exception:                                   # noqa: BLE001 - an unreadable block: skip it
            continue
        i = blk.find(vt)
        while i >= 0:
            if i % 4 == 0 and i + 0x64 <= len(blk):
                owner, = struct.unpack_from(">I", blk, i + LIVE["wm_owner"])
                rad, cx, cy, cz = struct.unpack_from(">4f", blk, i + LIVE["wm_sphere"])
                mesh, = struct.unpack_from(">I", blk, i + LIVE["wm_inst"])
                if 0x80000000 <= mesh < 0x81800000 and owner and owner != me and 0 < rad < 50:
                    if mesh not in names:
                        names[mesh] = _rd(ctx, sid, mesh, 16).split(b"\0")[0].decode("latin-1")
                    ape = names[mesh]
                    if ape.startswith("gr") and ape[2:3] in "dmz" and not ape.startswith("gr_"):
                        c = (np.array([cx, cy, cz]) - t) @ R.T          # camera space: x right, y up, z forward
                        scr = None
                        if c[2] > 0.5:
                            sx, sy = 0.5 + 0.5 * c[0] / (c[2] * tan_half_fov), 0.5 - 0.5 * c[1] / (c[2] * tan_half_fov * 0.75)
                            if -0.1 <= sx <= 1.1 and -0.1 <= sy <= 1.1:
                                scr = (round(float(sx), 3), round(float(sy), 3))
                        out.append({"ape": ape, "name": NAMES.get(ape, ape), "entity": owner, "screen": scr,
                                    "position": [round(cx, 1), round(cy, 1), round(cz, 1)],
                                    "distance": round(float(np.linalg.norm(c)), 1)})
            i = blk.find(vt, i + 1)
    return sorted(out, key=lambda b: b["distance"])


def bot_at(ctx, sid: str, x: float, y: float) -> dict | None:
    """The bot drawn nearest to screen point (x, y) (fractions of the picture)."""
    seen = [b for b in bots_on_screen(ctx, sid) if b["screen"]]
    if not seen:
        return None
    return min(seen, key=lambda b: (b["screen"][0] - x) ** 2 + (b["screen"][1] - y) ** 2 + (b["distance"] / 400.0) ** 2)


# --------------------------------------------------------------------------------------------- characters op=use
def _groups_for(mst: Master, ape: str) -> list[list[str]]:
    """The bot file and its numbered variants that share its texture (grmggrunt00 + grmggrunt01 ...)."""
    def tex(a):
        m = Ape(mst.read(a + ".ape"))
        return (m.mats[main_material(m)]["textures"] or [None])[0]
    t0, out = tex(ape), [ape]
    for k in range(10):
        v = f"{ape[:-2]}{k:02d}"
        if v != ape and v + ".ape" in mst.entries and tex(v) == t0:
            out.append(v)
    return [out]


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Metal Arms (GameCube): slot=player -> every Glitch model (story + cutscenes) replaced
    (mod ma_<slug>); slot=npc|enemy with session_id + x, y -> the bot drawn at that screen point (that bot type
    everywhere: mod ma_<slug>_<ape>). Builds on the control plane, launches on the session's node."""
    from . import characters as C
    from . import filemods
    gid = game["game_id"]
    who, target = None, None
    if inp.session_id:
        try:
            who = identify(ctx, inp.session_id)
        except Exception as e:                                       # noqa: BLE001 - informational
            who = {"status": "error", "message": f"couldn't read the session: {e}"}
    npc = inp.slot in ("npc", "enemy", "enemies", "bot")
    if npc:
        if not inp.session_id or inp.x is None or inp.y is None:
            raise ValueError("slot=npc needs session_id and x, y (the bot's point on the picture, 0..1)")
        target = bot_at(ctx, inp.session_id, inp.x, inp.y)
        if not target:
            return {"status": "not_found", "identified": who,
                    "message": "no bot is drawn near that point (bots_on_screen found none in view)"}
    name = f"ma_{meta['slug']}" + (f"_{target['ape']}" if target else "")
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = None
    if inp.rebuild or not have:
        if C.library_root(ctx.config).is_dir():
            roles = meta.get("rig", {}).get("roles")
            if not roles:
                raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't fit it to a Metal Arms skeleton")
            iso = C._gc_iso(ctx, game)
            groups = _groups_for(Master(iso), target["ape"]) if target else PLAYER_GROUPS
            built = build_mod(ctx.config, game, iso, C._local_or_fetch(ctx, meta, meta["model"]), roles, name,
                              f"Metal Arms {meta['slug']}{'_' + target['ape'] if target else ''}.iso", groups=groups,
                              progress=ctx.progress)
            C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                   json={"game_id": gid, "slot": "npc" if target else "player", "mod": name, "nodes": [C.HOST_OS],
                         "notes": (f"replaces every {target['name']} ({target['ape']}.ape)" if target else
                                   "replaces Glitch (grdggltch00/01 in play, gcdggltch00/01 in cutscenes); his "
                                   "skeleton and animations stay")})
        else:
            cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the Metal Arms mod on the control-plane node (the collection lives there)")
            j = C._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                           "launch": False, "slot": inp.slot, "session_id": inp.session_id,
                                           "x": inp.x, "y": inp.y}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "identified": who, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "build": built, "identified": who, "target": target,
           "replaces": f"every {target['name']} ({target['ape']}.ape)" if target else "Glitch (play + cutscenes)"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Metal Arms with {meta['name']} (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    t0 = time.time()
    while lj.get("state") in ("queued", "running") and time.time() - t0 < 1800:
        time.sleep(2)
        lj = C._api(ctx, "GET", f"/api/jobs/{lj['id']}")
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = ((who or {}).get("message", "") + " " if who and who.get("status") == "ok" else "") + (
        f"Metal Arms is running with {meta['name']} in {res['replaces']}'s place (mod {name})." if ok
        else f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else "launch " + str(lj.get("state")),
                  "launch": launch, "message": msg}


# ------------------------------------------------------------------------------- characters (DEDICATED route)
def roster() -> list[dict]:
    return [{"key": a, "slug": slug, "name": n, "aliases": al, "kind": "character"} for a, slug, n, al in ROSTER]


def roles_for(m: Ape, retarget: bool = False) -> dict[str, str]:
    """Body roles on a Metal Arms skeleton. retarget=True also maps the clavicles (no such bones) onto the chest so
    sources with clavicle roles fit."""
    names = {b["name"] for b in m.bones}
    if all(n in names for n in GLITCH_ROLES.values()):
        out = dict(GLITCH_ROLES)
    else:
        out = {r: next(n for n in c if n in names) for r, c in ROLE_CANDIDATES.items() if any(n in names for n in c)}
    extra = (("l_clav", "chest"), ("r_clav", "chest")) if retarget else ()
    for role, alt in (("neck", "head"), ("l_hand", "l_fore"), ("r_hand", "r_fore"), ("l_shin", "l_thigh"),
                      ("r_shin", "r_thigh"), ("l_foot", "l_shin"), ("r_foot", "r_shin")) + extra:
        if role not in out and alt in out:              # no such bone: ride the parent role's bone
            out[role] = out[alt]
    return out


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract: a Metal Arms character straight from the disc -> .gltf (skeleton, rigid weights, texture)."""
    from . import characters as C
    iso = C._gc_iso(ctx, game)
    mst = Master(iso)
    m = Ape(mst.read(e["key"] + ".ape"))
    texs = load_textures(mst, m)
    out = ape_to_gltf(m, texs, Path(work) / f"ma_{e['key']}.gltf")
    roles = roles_for(m)
    roles = roles if len(roles) >= 12 else {}               # bots with another skeleton: no body roles yet
    tris = sum(len(p["tris"]) for p in ape_prims(m, texs))
    return {"files": [out], "tool": "gbox.metal_arms", "roles": roles,
            "source_files": [f"{MST}: {e['key']}.ape ({len(mst.read(e['key'] + '.ape'))} bytes), "
                             + ", ".join(t + ".tga" for t in sorted(texs))],
            "notes": f"Metal Arms {e['key']}.ape: {m.n_bones} bones, {len(m.mats)} materials, {tris} triangles, rigid "
                     "(one bone per packet). " + ("Robot rig: short thighs (Leg_Upper -> Knee), long shins (Knee -> "
                     "Foot_Back), the right forearm is a gun arm (r_hand = Off_R_Hand_Dummy)." if roles else "")}


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "extract":
        print(json.dumps(extract(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])), indent=1))
