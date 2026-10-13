"""GTA: Vice City (classic RenderWare PC port) native character reader: Tommy (player.dff + player.txd) and any ped
DFF out of models/gta3.img into a rigged (smooth-skinned) GLB with gBox body roles.

What the classic PC port holds (the 2002/2003 RenderWare 3.4.0.3 build; see docs/gta_vc_pc_swap.md for what was
verified on which file and what was not):
  * models/gta3.dir + models/gta3.img: IMG archive version 1. The DIR is 32-byte entries {u32 offset in 2048-byte
    sectors, u32 size in sectors, char name[24]}; the IMG is the entries' sector-aligned data (gbox.gta_rw.dir_read
    already parses this layout for GTA III PS2, which uses the same version 1).
  * <ped>.dff: RW clump (library id 0x1003FFFF = 3.4.0.3). Unlike GTA III's rigid-part peds, VC peds are one
    smooth-skinned atomic: the frame list carries the bone hierarchy (one frame per bone, a HAnim plugin 0x11E on
    every bone frame with its bone tag, the node table on the hierarchy root) and the geometry carries a Skin plugin
    0x116 (4 bone indices + 4 weights per vertex, one inverse bind matrix per bone). Geometry is PLAIN RW geometry
    (positions / normals / UVs in the Geometry struct, Bin Mesh in the extension), which the game's D3D8 driver
    instances at load; a D3D8-native geometry (0x510, platform 8) decoder is kept for files that carry one.
  * <ped>.txd: Texture Native platform 8 (D3D8): one Struct {platform, filter, name[32], mask[32], raster format,
    hasAlpha, w, h, depth, mip levels, raster type, DXT type, [palette], per level {u32 size, pixels}}.
    Formats seen in the wild for peds: DXT1/DXT3, 8-bit palette, 32-bit 8888. All are decoded here.

The owned install in the catalog (1fd42f50b10252e6, HyperSpin "PC Games") turned out to be the Definitive Edition
(Unreal Engine 4: Gameface/Content/Paks/gta.pak, peds are SK_player / SK_<ped> skeletal-mesh uassets) and holds no
gta3.img, so nothing below could be checked against an owned classic file yet; locate_install() tells the two apart.
Everything here is checked by synthetic round trips (tests/test_gta_vc_models.py) and by the format references named
in the docstrings (RW spec as documented on gtamods.com, re3/reVC, librw).
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import gta_rw as R

SECTOR = R.SECTOR
SKIN, HANIM = 0x116, 0x11E                    # RW plugin ids: rwID_SKINPLUGIN, rwID_HANIMPLUGIN
D3D8, D3D9 = 8, 9                             # Texture Native / native data platform ids (VC PC = 8, SA PC = 9)
GEOM_NATIVE, GEOM_TRISTRIP, GEOM_POS, GEOM_TEX, GEOM_PRELIT, GEOM_NRM, GEOM_LIGHT = 0x01000000, 1, 2, 4, 8, 0x10, 0x20
VC_VERSION = 0x1003FFFF                       # library id of every VC PC DFF/TXD: RW 3.4.0.3

# The two catalog entries that are this port (both windows_native; a2961272cbfaf3a8 is a PS4 stub and not a target).
GAME_IDS = {"5eacc9f11d9a5956": "Grand Theft Auto: Vice City (USA)", "1fd42f50b10252e6": "Grand Theft Auto Vice City"}

# HAnim bone tags of the VC ped skeleton -> gBox body role. The game binds peds by these TAGS, not by frame name
# (reVC src/modelinfo/PedModelInfo.cpp CPedModelInfo::ConvertPedNode2BoneTag; the enum in PedModelInfo.h:
# BONE_root 0, pelvis 1, spine 2, spine1 3, neck 4, head 5, l_clavicle 21, l_upperarm 22, l_forearm 23, l_hand 24,
# l_finger 25, r_clavicle 31, r_upperarm 32, r_forearm 33, r_hand 34, r_finger 35, l_thigh 41, l_calf 42, l_foot 43,
# l_toe 44, r_thigh 51, r_calf 52, r_foot 53, r_toe 54). "hip" is gBox's torso root above the pelvis (the GTA III map
# puts it on Smid), so spine -> hip and spine1 -> chest.
BONE_ROLES = {1: "pelvis", 2: "hip", 3: "chest", 4: "neck", 5: "head",
              21: "l_clav", 22: "l_upper", 23: "l_fore", 24: "l_hand", 25: "l_hand_end",
              31: "r_clav", 32: "r_upper", 33: "r_fore", 34: "r_hand", 35: "r_hand_end",
              41: "l_thigh", 42: "l_shin", 43: "l_foot", 44: "l_toe",
              51: "r_thigh", 52: "r_shin", 53: "r_foot", 54: "r_toe"}
# Frame names those bones carry in Rockstar's VC ped exports (the Character Studio Biped names re3/reVC's
# animation code and the DragonFF exporter use; "Bip01 " prefixes and case are ignored when matching). Fallback for
# a clump whose bone frames have no HAnim plugin; NOT yet read from an owned classic player.dff (none is installed:
# docs/gta_vc_pc_swap.md "Facts").
NAME_ROLES = {"pelvis": "pelvis", "spine": "hip", "spine1": "chest", "neck": "neck", "head": "head",
              "lclavicle": "l_clav", "lupperarm": "l_upper", "lforearm": "l_fore", "lhand": "l_hand", "lfinger": "l_hand_end",
              "rclavicle": "r_clav", "rupperarm": "r_upper", "rforearm": "r_fore", "rhand": "r_hand", "rfinger": "r_hand_end",
              "lthigh": "l_thigh", "lcalf": "l_shin", "lfoot": "l_foot", "ltoe0": "l_toe",
              "rthigh": "r_thigh", "rcalf": "r_shin", "rfoot": "r_foot", "rtoe0": "r_toe"}
REQUIRED_ROLES = ("pelvis", "hip", "chest", "neck", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                  "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")


# ------------------------------------------------------------------------------------------------- IMG v1 archive
class ImgArchive:
    """models/gta3.img + models/gta3.dir (IMG version 1) on disk: read entries, rebuild a modified copy."""

    def __init__(self, img: Path, dir_: Path | None = None):
        self.img = Path(img)
        self.dir = Path(dir_) if dir_ else self.img.with_suffix(".dir")
        self.dir_raw = self.dir.read_bytes()
        if len(self.dir_raw) % 32:
            raise ValueError(f"{self.dir}: not an IMG v1 directory (size {len(self.dir_raw)} is not 32-byte entries)")
        self.ents = R.dir_read(self.dir_raw)
        self.index = {e[2].lower(): i for i, e in enumerate(self.ents)}

    def names(self, suffix: str | None = None) -> list[str]:
        return [e[2] for e in self.ents if suffix is None or e[2].lower().endswith(suffix)]

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.index

    def entry(self, name: str) -> bytes:
        o, s, _ = self.ents[self.index[name.lower()]]
        with open(self.img, "rb") as f:
            f.seek(o * SECTOR)
            return f.read(s * SECTOR)

    def rebuild(self, dst_img: Path, replacements: dict[str, bytes]) -> bytes:
        """Write a new IMG with the given entries replaced (every other entry copied byte for byte, original order,
        sector offsets recomputed) and return the matching DIR bytes (names and padding kept, offsets/sizes updated)."""
        rep = {k.lower(): v for k, v in replacements.items()}
        unknown = [k for k in rep if k not in self.index]
        if unknown:
            raise KeyError(f"not in {self.dir.name}: {unknown}")
        ents, sector = [], 0
        with open(self.img, "rb") as src, open(dst_img, "wb") as dst:
            for o, s, n in self.ents:
                if n.lower() in rep:
                    data = rep[n.lower()]
                else:
                    src.seek(o * SECTOR)
                    data = src.read(s * SECTOR)
                need = (len(data) + SECTOR - 1) // SECTOR
                dst.write(data + b"\0" * (need * SECTOR - len(data)))
                ents.append([sector, need, n])
                sector += need
        return R.dir_write(ents, self.dir_raw)


def ide_peds(text: str) -> list[tuple[str, str]]:
    """The (model, txd) pairs of every `peds` section of an .ide file (data/default.ide: id, model, txd, type, ...)."""
    out, inside = [], False
    for line in text.splitlines():
        s = line.split("#")[0].strip()
        if not s:
            continue
        if s.lower() == "peds":
            inside = True
            continue
        if s.lower() == "end":
            inside = False
            continue
        if inside:
            parts = [p.strip() for p in s.split(",")]
            if len(parts) >= 3:
                out.append((parts[1], parts[2]))
    return out


# ------------------------------------------------------------------------------------------------- frames / HAnim
def hanim_read(framelist: R.Chunk) -> dict:
    """HAnim PLG per frame: {"ids": [bone tag | None per frame], "root": frame index holding the node table,
    "nodes": [(tag, index, flags)] in bone (skin) order, "flags": hierarchy flags}.
    Layout (gtamods wiki HAnim PLG, librw hanim.cpp): u32 version 0x100, u32 nodeId, u32 numNodes; when numNodes > 0
    (the hierarchy root only): u32 flags, u32 keyFrameSize (36), numNodes x {u32 nodeId, u32 nodeIndex, u32 flags}."""
    ids, nodes, root, flags = [], [], None, 0
    for i, ext in enumerate(framelist.find(R.EXTENSION)):
        h = [k for k in ext.kids if k.type == HANIM]
        if not h:
            ids.append(None)
            continue
        d = h[0].data
        _ver, bid, n = struct.unpack_from("<III", d)
        ids.append(bid)
        if n:
            flags = struct.unpack_from("<I", d, 12)[0]
            nodes = [struct.unpack_from("<III", d, 20 + 12 * k) for k in range(n)]
            root = i
    return {"ids": ids, "nodes": nodes, "root": root, "flags": flags}


def hanim_chunk(bone_id: int, nodes: list[tuple[int, int, int]] | None, version: int, flags: int = 0) -> R.Chunk:
    d = struct.pack("<III", 0x100, bone_id, len(nodes or []))
    if nodes:
        d += struct.pack("<II", flags, 36) + b"".join(struct.pack("<III", *n) for n in nodes)
    return R.Chunk(HANIM, version, d)


def normalize_frame_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("bip01", ""))


def role_map(frames: list[dict], hanim: dict) -> dict:
    """{role: frame index} for a VC ped clump, from the HAnim bone tags (the game's own binding) and, for frames
    without a tag, their names. Raises when a required role is missing (lists what the file has)."""
    roles, source = {}, {}
    for i, f in enumerate(frames):
        tag = hanim["ids"][i] if i < len(hanim["ids"]) else None
        r = BONE_ROLES.get(tag) if tag is not None else None
        how = "hanim"
        if r is None:
            r = NAME_ROLES.get(normalize_frame_name(f["name"]))
            how = "name"
        if r is not None and r not in roles:
            roles[r] = i
            source[r] = how
    missing = [r for r in REQUIRED_ROLES if r not in roles]
    if missing:
        have = [(f["name"], hanim["ids"][i] if i < len(hanim["ids"]) else None) for i, f in enumerate(frames)]
        raise ValueError(f"not a GTA VC ped clump: roles {missing} not found; frames (name, bone tag): {have}")
    return {"roles": roles, "source": source}


# -------------------------------------------------------------------------------------------------------- skin
@dataclass
class Skin:
    num_bones: int
    used: list[int]
    max_weights: int
    idx: np.ndarray                      # (nv, 4) uint8 bone indices (skin bone order = HAnim node table order)
    w: np.ndarray                        # (nv, 4) float32
    inv_bind: np.ndarray                 # (num_bones, 4, 4) column-vector convention
    split: bytes = b""                   # bone-limit / mesh split data (RW >= 3.4), kept verbatim
    old: bool = False


def skin_read(geom: R.Chunk, nv: int) -> Skin | None:
    """Skin PLG 0x116 in a Geometry's extension (gtamods wiki Skin PLG, librw skin.cpp readSkin):
    u8 numBones, u8 numUsedBones, u8 maxWeightsPerVertex, u8 pad, u8 usedBones[numUsedBones], u8 boneIndex[nv][4],
    f32 weight[nv][4], numBones x (RW < 3.4.0.3: u32 0xDEADDEAD then) f32 inverseBindMatrix[16] (RW row layout:
    right, up, at, pos); RW >= 3.4.0.3: u32 boneLimit, u32 numMeshes, u32 numRLE (+ split tables when numMeshes)."""
    sk = [k for k in geom.first(R.EXTENSION).kids if k.type == SKIN]
    if not sk:
        return None
    d = sk[0].data
    old = R.rw_version(geom.version) < 0x34003
    nb, nused, maxw, _pad = struct.unpack_from("<4B", d)
    o = 4
    used = list(d[o:o + nused])
    o += nused
    idx = np.frombuffer(d, np.uint8, nv * 4, o).reshape(nv, 4).copy()
    o += nv * 4
    w = np.frombuffer(d, "<f4", nv * 4, o).reshape(nv, 4).astype(np.float32)
    o += nv * 16
    mats = []
    for _ in range(nb):
        if old:
            o += 4
        mats.append(np.frombuffer(d, "<f4", 16, o).reshape(4, 4).T.astype(float))
        o += 64
    return Skin(nb, used, maxw, idx, w, np.array(mats) if mats else np.zeros((0, 4, 4)), bytes(d[o:]), old)


def skin_chunk(tmpl: Skin, idx: np.ndarray, w: np.ndarray, version: int) -> R.Chunk:
    """A Skin PLG for new vertices on the template's bones (inverse bind matrices kept; no mesh split tables)."""
    idx, w = np.asarray(idx, np.uint8).reshape(-1, 4), np.asarray(w, np.float32).reshape(-1, 4)
    if idx.max(initial=0) >= tmpl.num_bones:
        raise ValueError(f"bone index {idx.max()} >= {tmpl.num_bones} bones")
    old = R.rw_version(version) < 0x34003
    used = sorted({int(b) for b in idx[w > 0]})
    maxw = int((w > 0).sum(1).max(initial=1))
    d = struct.pack("<4B", tmpl.num_bones, 0 if old else len(used), 0 if old else maxw, 0)
    d += b"" if old else bytes(used)
    d += idx.tobytes() + w.astype("<f4").tobytes()
    for m in tmpl.inv_bind:
        d += (b"\xad\xde\xad\xde" if old else b"") + np.asarray(m, float).T.astype("<f4").tobytes()
    if not old:
        d += struct.pack("<III", 0, 0, 0)
    return R.Chunk(SKIN, version, d)


# ---------------------------------------------------------------------------------------------------- geometry
@dataclass
class SkinnedGeom:
    geom: R.Geom
    skin: Skin | None
    native: bool = False


def _d3d8_native_read(geom: R.Chunk, nv: int, fmt: int) -> R.Geom:
    """Native Data PLG 0x510 with platform 8: the D3D8 driver's instanced geometry as librw's d3d8.cpp readNativeData
    reads it: u32 platform, u32 numMeshes, per mesh {u32 minVert, i32 stride, i32 numVertices, i32 numIndices,
    u32 material, u32 vertexShader (D3D FVF), u32 primType, u32 indexBuffer, u32 vertexBuffer, u32 baseIndex,
    u8 vertexAlpha, u8 managed, u8 remapped, u8 pad}, then per mesh u16 indices[numIndices] + the vertex buffer
    (stride x numVertices, laid out by the FVF: XYZ, [normal], [diffuse ARGB], [uv x n]). UNVERIFIED against an
    owned file (VC PC ships plain geometry); the FVF-derived stride is checked against the declared one."""
    nd = [k for k in geom.first(R.EXTENSION).kids if k.type == R.NATIVEDATA]
    if not nd:
        raise ValueError("native geometry without a Native Data PLG")
    d = nd[0].data
    if d[:4] == struct.pack("<I", R.STRUCT):                   # wrapped in a Struct chunk
        d = d[12:]
    plat, nm = struct.unpack_from("<II", d)
    if plat != D3D8:
        raise NotImplementedError(f"native geometry platform {plat} (only D3D8 = 8)")
    meshes, o = [], 8
    for _ in range(nm):
        f = struct.unpack_from("<IiiiIIIIII4B", d, o)
        o += 44
        meshes.append({"min": f[0], "stride": f[1], "nv": f[2], "ni": f[3], "mat": f[4], "fvf": f[5], "prim": f[6]})
    P, N, U, T, M = [], [], [], [], []
    base = 0
    for m in meshes:
        idx = np.frombuffer(d, "<u2", m["ni"], o).astype(np.int64)
        o += m["ni"] * 2
        fvf = m["fvf"]
        off, has_n, has_c = 12, bool(fvf & 0x10), bool(fvf & 0x40)
        ntex = (fvf >> 8) & 0xF
        stride = 12 + (12 if has_n else 0) + (4 if has_c else 0) + 8 * ntex
        if stride != m["stride"]:
            raise ValueError(f"D3D8 native mesh: FVF {fvf:#x} implies stride {stride}, file says {m['stride']}")
        buf = np.frombuffer(d, np.uint8, m["stride"] * m["nv"], o).reshape(m["nv"], m["stride"])
        o += m["stride"] * m["nv"]
        P.append(buf[:, 0:12].copy().view("<f4").reshape(-1, 3))
        if has_n:
            N.append(buf[:, off:off + 12].copy().view("<f4").reshape(-1, 3))
            off += 12
        else:
            N.append(np.zeros((m["nv"], 3), np.float32))
        off += 4 if has_c else 0
        U.append(buf[:, off:off + 8].copy().view("<f4").reshape(-1, 2) if ntex else np.zeros((m["nv"], 2), np.float32))
        if m["prim"] == 5:                                       # D3DPT_TRIANGLESTRIP
            tri = np.stack([idx[:-2], idx[1:-1], idx[2:]], 1)
            tri[1::2] = tri[1::2, [1, 0, 2]]
            tri = tri[(tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
        else:                                                    # D3DPT_TRIANGLELIST (4)
            tri = idx[:len(idx) - len(idx) % 3].reshape(-1, 3)
        T.append(tri + base)
        M.append(np.full(len(tri), m["mat"], np.int64))
        base += m["nv"]
    return R.Geom(np.concatenate(P), np.concatenate(N), np.concatenate(U), np.concatenate(T), np.concatenate(M))


def geometry_read(geom: R.Chunk) -> SkinnedGeom:
    """Plain or D3D8-native geometry + its skin."""
    st = geom.first(R.STRUCT).data
    fmt, _nt, nv, _nm = struct.unpack_from("<IIII", st)
    if fmt & GEOM_NATIVE:
        g = _d3d8_native_read(geom, nv, fmt)
        return SkinnedGeom(g, skin_read(geom, len(g.pos)), True)
    g = R.geometry_read(geom)
    return SkinnedGeom(g, skin_read(geom, nv), False)


def geometry_chunk(g: R.Geom, template: R.Chunk, skin: Skin | None, idx=None, w=None) -> R.Chunk:
    """A plain Geometry chunk (template's material list + plugins, Bin Mesh rebuilt as a triangle list) with a new
    Skin PLG for the vertices when `skin` is given (idx/w per vertex; default: every vertex rigid on bone 0)."""
    out = R.geometry_build(g, template)
    ext = out.first(R.EXTENSION)
    if skin is not None:
        nv = len(g.pos)
        idx = np.zeros((nv, 4), np.uint8) if idx is None else idx
        w = np.c_[np.ones(nv), np.zeros((nv, 3))] if w is None else w
        sc = skin_chunk(skin, idx, w, template.version)
        kids = [sc if k.type == SKIN else k for k in ext.kids]
        if not any(k.type == SKIN for k in kids):
            kids.insert(0, sc)
        ext.kids = kids
    else:
        ext.kids = [k for k in ext.kids if k.type != SKIN]
    return out


# ---------------------------------------------------------------------------------------------- the ped clump
class Clump:
    """A VC ped DFF: frames (+ HAnim), geometries (+ skins), atomics, the bone <-> frame maps and the role map."""

    def __init__(self, dff: bytes):
        self.raw = dff
        self.root, self.tail = R.parse(dff)
        fl = self.root.first(R.FRAMELIST)
        self.frames = R.frames_read(fl)
        self.hanim = hanim_read(fl)
        self.geoms = self.root.first(R.GEOMLIST).find(R.GEOMETRY)
        self.atomics = [tuple(struct.unpack_from("<II", a.first(R.STRUCT).data)) for a in self.root.find(R.ATOMIC)]
        self.version = self.root.version
        rm = role_map(self.frames, self.hanim)
        self.roles, self.role_source = rm["roles"], rm["source"]
        tag_frame = {t: i for i, t in enumerate(self.hanim["ids"]) if t is not None}
        self.bone_frames = [tag_frame.get(tag, -1) for tag, _idx, _fl in self.hanim["nodes"]]   # skin bone k -> frame
        self.frame_bone = {f: k for k, f in enumerate(self.bone_frames) if f >= 0}
        self.skinned = [(fi, gi) for fi, gi in self.atomics if skin_read(self.geoms[gi], 0) is not None]

    # duck-typed re4gc_enemies.retarget template: bones (index, parent | 0xFF), joint positions in mm, glTF axes
    @property
    def bones(self):
        return [(i, f["parent"] if f["parent"] >= 0 else 0xFF) for i, f in enumerate(self.frames)]

    def bone_world(self):
        return {i: (R.GTA_TO_GLTF @ f["world"])[:3, 3] * 1000.0 for i, f in enumerate(self.frames)}

    def geometry(self, gi: int) -> SkinnedGeom:
        return geometry_read(self.geoms[gi])

    def stats(self) -> dict:
        tris = verts = 0
        for _fi, gi in self.atomics:
            g = self.geometry(gi).geom
            tris += len(g.tris)
            verts += len(g.pos)
        return {"frames": len(self.frames), "bones": len(self.hanim["nodes"]), "atomics": len(self.atomics),
                "skinned_atomics": len(self.skinned), "vertices": verts, "triangles": tris, "version": R.rw_version(self.version),
                "roles": {r: self.frames[i]["name"] for r, i in self.roles.items()}, "role_source": self.role_source}


def clump_build(frames: list[dict], geoms: list[R.Chunk], atomics: list[tuple[int, int]], version: int = VC_VERSION,
                hanim_nodes: list[tuple[int, int, int]] | None = None, hanim_root: int | None = None) -> bytes:
    """Encode a clump from scratch. frames: [{name, local (4x4), parent, bone (HAnim tag | None)}]; geoms: Geometry
    chunks; atomics: [(frame, geometry)]. Used by the tests' synthetic peds and by the writer's previews."""
    n = len(frames)
    st = struct.pack("<I", n)
    for f in frames:
        m = np.asarray(f["local"], float)
        st += struct.pack("<9f", *m[:3, :3].T.reshape(-1)) + struct.pack("<3f", *m[:3, 3]) + struct.pack("<iI", f["parent"], 0)
    fl = R.Chunk(R.FRAMELIST, version, container=True, kids=[R.Chunk(R.STRUCT, version, st)])
    for i, f in enumerate(frames):
        ext = R.Chunk(R.EXTENSION, version, container=True)
        if f.get("bone") is not None:
            ext.kids.append(hanim_chunk(f["bone"], hanim_nodes if i == hanim_root else None, version))
        if f.get("name"):
            ext.kids.append(R.Chunk(R.FRAMENAME, version, f["name"].encode()))
        fl.kids.append(ext)
    gl = R.Chunk(R.GEOMLIST, version, container=True, kids=[R.Chunk(R.STRUCT, version, struct.pack("<I", len(geoms)))] + list(geoms))
    clump = R.Chunk(R.CLUMP, version, container=True)
    clump.kids.append(R.Chunk(R.STRUCT, version, struct.pack("<III", len(atomics), 0, 0)))
    clump.kids += [fl, gl]
    for fi, gi in atomics:
        a = R.Chunk(R.ATOMIC, version, container=True)
        a.kids.append(R.Chunk(R.STRUCT, version, struct.pack("<IIII", fi, gi, 5, 0)))
        a.kids.append(R.Chunk(R.EXTENSION, version, container=True))
        clump.kids.append(a)
    clump.kids.append(R.Chunk(R.EXTENSION, version, container=True))
    return clump.to_bytes()


def material_list(textures: list[str | None], version: int = VC_VERSION) -> R.Chunk:
    """A Material List with one white material per entry (textured when a name is given; mask empty)."""
    ml = R.Chunk(R.MATLIST, version, container=True)
    ml.kids.append(R.Chunk(R.STRUCT, version, struct.pack("<I", len(textures)) + struct.pack(f"<{len(textures)}i", *([-1] * len(textures)))))
    for t in textures:
        m = R.Chunk(R.MATERIAL, version, container=True)
        m.kids.append(R.Chunk(R.STRUCT, version, struct.pack("<I4BIIfff", 0, 255, 255, 255, 255, 0, 1 if t else 0, 1.0, 1.0, 1.0)))
        if t:
            tx = R.Chunk(R.TEXTURE, version, container=True)
            tx.kids.append(R.Chunk(R.STRUCT, version, struct.pack("<BBH", 2, 0x11, 0)))
            tx.kids += [R.string_chunk(t, version), R.string_chunk("", version), R.Chunk(R.EXTENSION, version, container=True)]
            m.kids.append(tx)
        m.kids.append(R.Chunk(R.EXTENSION, version, container=True))
        ml.kids.append(m)
    return ml


def geometry_template(textures: list[str | None], version: int = VC_VERSION) -> R.Chunk:
    """An empty plain Geometry chunk (one degenerate triangle, the material list for `textures`, Bin Mesh) to build
    new geometries from where no original exists."""
    z = np.zeros((3, 3), np.float32)
    g = R.Geom(z, np.tile(np.array([0, 0, 1], np.float32), (3, 1)), np.zeros((3, 2), np.float32), np.array([[0, 1, 2]]))
    t = R.Chunk(R.GEOMETRY, version, container=True)
    t.kids.append(R.Chunk(R.STRUCT, version, b""))
    t.kids.append(material_list(textures, version))
    t.kids.append(R.Chunk(R.EXTENSION, version, container=True, kids=[R.Chunk(R.BINMESH, version, struct.pack("<III", 0, 0, 0))]))
    return R.geometry_build(g, t)


def material_textures(geom: R.Chunk) -> list[str | None]:
    """Texture name per material of a Geometry (None for untextured)."""
    out = []
    for m in geom.first(R.MATLIST).find(R.MATERIAL):
        tx = m.find(R.TEXTURE)
        out.append(tx[0].find(R.STRING)[0].data.split(b"\0")[0].decode("ascii", "replace") if tx else None)
    return out


# ---------------------------------------------------------------------------------------------- D3D8 rasters
RASTER_FORMATS = {0x100: "1555", 0x200: "565", 0x300: "4444", 0x400: "LUM8", 0x500: "8888", 0x600: "888", 0xA00: "555"}
PAL8, PAL4, MIPMAP, AUTOMIP = 0x2000, 0x4000, 0x8000, 0x1000


@dataclass
class D3dRaster:
    platform: int
    filter: int
    name: str
    mask: str
    fmt: int
    alpha: int                            # D3D8: hasAlpha; D3D9: the D3DFORMAT
    width: int
    height: int
    depth: int
    levels: int
    rtype: int
    comp: int                             # D3D8: DXT type (0/1/3/5); D3D9: flags (bit 0 alpha, bit 3 compressed)
    palette: bytes | None
    mips: list[bytes]
    extension: R.Chunk | None = None

    @property
    def dxt(self) -> int:
        if self.platform == D3D9:
            return {0x31545844: 1, 0x33545844: 3, 0x35545844: 5}.get(self.alpha, 0) if self.comp & 8 else 0
        return self.comp

    @property
    def has_alpha(self) -> bool:
        return bool(self.comp & 1) if self.platform == D3D9 else bool(self.alpha)

    def describe(self) -> str:
        f = RASTER_FORMATS.get(self.fmt & 0xF00, hex(self.fmt & 0xF00))
        pal = "PAL8 " if self.fmt & PAL8 else "PAL4 " if self.fmt & PAL4 else ""
        return f"{self.name}: {self.width}x{self.height} {pal}{f}{' DXT%d' % self.dxt if self.dxt else ''} {self.levels} level(s)"


def texnative_read(tn: R.Chunk) -> D3dRaster:
    """Texture Native (platform 8 / 9) Struct as documented on the gtamods wiki (Texture Native Struct) and in librw
    d3d.cpp readNativeTexture."""
    st = tn.first(R.STRUCT).data
    plat = struct.unpack_from("<I", st)[0]
    if plat not in (D3D8, D3D9):
        raise ValueError(f"not a PC (D3D8/D3D9) texture: platform {plat}")
    filt = struct.unpack_from("<I", st, 4)[0]
    name = st[8:40].split(b"\0")[0].decode("ascii", "replace")
    mask = st[40:72].split(b"\0")[0].decode("ascii", "replace")
    fmt, alpha = struct.unpack_from("<II", st, 72)
    w, h, depth, levels, rtype, comp = struct.unpack_from("<HHBBBB", st, 80)
    o, pal = 88, None
    if fmt & PAL8:
        pal, o = st[o:o + 1024], o + 1024
    elif fmt & PAL4:
        pal, o = st[o:o + 128], o + 128               # librw: 32 entries for PAL4 on D3D
    mips = []
    for _ in range(max(levels, 1)):
        n = struct.unpack_from("<I", st, o)[0]
        mips.append(st[o + 4:o + 4 + n])
        o += 4 + n
    ext = tn.find(R.EXTENSION)
    return D3dRaster(plat, filt, name, mask, fmt, alpha, w, h, depth, levels, rtype, comp, pal, mips, ext[0] if ext else None)


def texnative_chunk(r: D3dRaster, version: int = VC_VERSION) -> R.Chunk:
    st = struct.pack("<II", r.platform, r.filter) + r.name.encode()[:31].ljust(32, b"\0") + r.mask.encode()[:31].ljust(32, b"\0")
    st += struct.pack("<II", r.fmt, r.alpha) + struct.pack("<HHBBBB", r.width, r.height, r.depth, len(r.mips), r.rtype, r.comp)
    if r.palette is not None:
        st += r.palette
    for m in r.mips:
        st += struct.pack("<I", len(m)) + m
    tn = R.Chunk(R.TEXNATIVE, version, container=True)
    tn.kids.append(R.Chunk(R.STRUCT, version, st))
    tn.kids.append(r.extension or R.Chunk(R.EXTENSION, version, container=True))
    return tn


def txd_rasters(txd: bytes) -> list[D3dRaster]:
    root, _ = R.parse(txd)
    return [texnative_read(t) for t in root.find(R.TEXNATIVE)]


def _dxt_colors(block: bytes) -> tuple[np.ndarray, np.ndarray]:
    c0, c1 = struct.unpack_from("<HH", block)
    pal = np.zeros((4, 4), np.float64)
    for k, c in enumerate((c0, c1)):
        pal[k] = [((c >> 11) & 31) * 255 / 31, ((c >> 5) & 63) * 255 / 63, (c & 31) * 255 / 31, 255]
    if c0 > c1:
        pal[2] = (2 * pal[0] + pal[1]) / 3
        pal[3] = (pal[0] + 2 * pal[1]) / 3
    else:
        pal[2] = (pal[0] + pal[1]) / 2
        pal[3] = [0, 0, 0, 0]
    bits = np.frombuffer(block, np.uint8, 4, 4)
    idx = (bits[:, None] >> (np.arange(4) * 2)) & 3                 # (row, col) LSB first
    return pal, idx


def dxt_decode(data: bytes, w: int, h: int, kind: int) -> np.ndarray:
    """DXT1 / DXT3 / DXT5 blocks -> (h, w, 4) RGBA (block rows of 4x4, LSB-first indices, as D3D defines them)."""
    bw, bh = max(w // 4, 1), max(h // 4, 1)
    bs = 8 if kind == 1 else 16
    out = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    for by in range(bh):
        for bx in range(bw):
            b = data[(by * bw + bx) * bs:(by * bw + bx + 1) * bs]
            if len(b) < bs:
                break
            pal, idx = _dxt_colors(b[bs - 8:])
            px = pal[idx]
            if kind == 3:
                a = np.frombuffer(b, "<u2", 4, 0)
                px[..., 3] = ((a[:, None] >> (np.arange(4) * 4)) & 15) * 17
            elif kind == 5:
                a0, a1 = b[0], b[1]
                al = np.array([a0, a1] + ([((6 - i) * a0 + (i + 1) * a1) / 7 for i in range(6)] if a0 > a1 else
                                          [((4 - i) * a0 + (i + 1) * a1) / 5 for i in range(4)] + [0, 255]))
                bits = int.from_bytes(b[2:8], "little")
                ai = np.array([(bits >> (3 * k)) & 7 for k in range(16)]).reshape(4, 4)
                px[..., 3] = al[ai]
            out[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4] = np.clip(px + 0.5, 0, 255).astype(np.uint8)
    return out[:h, :w]


def raster_rgba(r: D3dRaster, level: int = 0) -> np.ndarray:
    """One mip level as (h, w, 4) RGBA."""
    w, h = max(r.width >> level, 1), max(r.height >> level, 1)
    d = r.mips[level]
    if r.dxt:
        return dxt_decode(d, w, h, r.dxt)
    if r.fmt & PAL8 or r.fmt & PAL4:
        pal = np.frombuffer(r.palette, np.uint8).reshape(-1, 4)          # RGBA entries
        if r.depth == 4 and r.fmt & PAL4:
            raw = np.frombuffer(d, np.uint8, (w * h + 1) // 2)
            idx = np.stack([raw & 15, raw >> 4], 1).reshape(-1)[:w * h]
        else:
            idx = np.frombuffer(d, np.uint8, w * h)
        return pal[idx].reshape(h, w, 4)
    kind = r.fmt & 0xF00
    if kind in (0x500, 0x600):                                             # D3DFMT_A8R8G8B8 / X8R8G8B8: B, G, R, A bytes
        px = np.frombuffer(d, np.uint8, w * h * 4).reshape(h, w, 4)[..., [2, 1, 0, 3]].copy()
        if kind == 0x600:
            px[..., 3] = 255
        return px
    if kind == 0x400:
        l = np.frombuffer(d, np.uint8, w * h).reshape(h, w)
        return np.stack([l, l, l, np.full_like(l, 255)], -1)
    v = np.frombuffer(d, "<u2", w * h).reshape(h, w).astype(np.uint32)
    if kind == 0x200:
        out = np.stack([(v >> 11) & 31, (v >> 5) & 63, v & 31, np.full_like(v, 255)], -1).astype(np.float64)
        out[..., :3] *= np.array([255 / 31, 255 / 63, 255 / 31])
    elif kind in (0x100, 0xA00):
        out = np.stack([(v >> 10) & 31, (v >> 5) & 31, v & 31, (v >> 15) & 1 if kind == 0x100 else np.ones_like(v)], -1).astype(np.float64)
        out[..., :3] *= 255 / 31
        out[..., 3] *= 255
    elif kind == 0x300:
        out = np.stack([(v >> 8) & 15, (v >> 4) & 15, v & 15, (v >> 12) & 15], -1).astype(np.float64) * 17
    else:
        raise NotImplementedError(f"raster format {r.fmt:#x}")
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def raster_8888(tmpl: D3dRaster, rgba: np.ndarray, mips: bool | None = None) -> D3dRaster:
    """A 32-bit 8888 raster (D3DFMT_A8R8G8B8, the format every VC PC TXD may carry uncompressed) with the template's
    name, mask, filter and platform; a full mip chain when the template had one (or `mips`)."""
    from PIL import Image
    rgba = np.ascontiguousarray(rgba[..., :4], np.uint8)
    h, w = rgba.shape[:2]
    if w & (w - 1) or h & (h - 1):
        raise ValueError(f"texture {w}x{h}: D3D8 needs power-of-two sizes")
    chain = [rgba]
    if mips if mips is not None else tmpl.levels > 1:
        img = Image.fromarray(rgba)
        cw, ch = w, h
        while cw > 1 or ch > 1:
            cw, ch = max(cw // 2, 1), max(ch // 2, 1)
            chain.append(np.array(img.resize((cw, ch), Image.LANCZOS), np.uint8))
    data = [np.ascontiguousarray(c[..., [2, 1, 0, 3]]).tobytes() for c in chain]
    alpha = bool((rgba[..., 3] < 255).any())
    fmt = 0x500 | (MIPMAP if len(chain) > 1 else 0)
    if tmpl.platform == D3D9:
        return D3dRaster(D3D9, tmpl.filter, tmpl.name, tmpl.mask, fmt, 21, w, h, 32, len(chain), 4, 1 if alpha else 0, None, data, tmpl.extension)
    return D3dRaster(D3D8, tmpl.filter, tmpl.name, tmpl.mask, fmt, 1 if alpha else 0, w, h, 32, len(chain), 4, 0, None, data, tmpl.extension)


def txd_replace(txd: bytes, rasters: dict[str, D3dRaster]) -> bytes:
    """The TXD with the named rasters replaced (others verbatim; count and device id kept)."""
    root, tail = R.parse(txd)
    rep = {k.lower(): v for k, v in rasters.items()}
    kids = []
    for k in root.kids:
        if k.type == R.TEXNATIVE:
            nm = texnative_read(k).name.lower()
            k = texnative_chunk(rep[nm], k.version) if nm in rep else k
        kids.append(k)
    root.kids = kids
    root.size_override = None
    return root.to_bytes() + tail


def txd_build(rasters: list[D3dRaster], version: int = VC_VERSION, device: int = 1) -> bytes:
    """A TXD from scratch (device id 1 = D3D8, 2 = D3D9)."""
    root = R.Chunk(R.TEXDICT, version, container=True)
    root.kids.append(R.Chunk(R.STRUCT, version, struct.pack("<HH", len(rasters), device)))
    root.kids += [texnative_chunk(r, version) for r in rasters]
    root.kids.append(R.Chunk(R.EXTENSION, version, container=True))
    return root.to_bytes()


# ---------------------------------------------------------------------------------------------------- glTF export
def clump_to_gltf(dff: bytes, out: Path, rgba: np.ndarray | None = None, name: str = "ped") -> Path:
    """A VC ped clump -> skinned .glb: every frame is a joint; skinned atomics keep their 4 weights (bone -> frame
    through the HAnim node table), rigid atomics ride their frame. GTA Z-up -> glTF (x, y, z) -> (-x, z, y)."""
    c = Clump(dff)
    C = R.GTA_TO_GLTF
    P, N, UV, J, W, T = [], [], [], [], [], []
    for fi, gi in c.atomics:
        sg = c.geometry(gi)
        g = sg.geom
        m = C @ c.frames[fi]["world"]
        base = sum(len(p) for p in P)
        P.append((np.c_[g.pos, np.ones(len(g.pos))] @ m.T)[:, :3])
        N.append(g.nrm @ m[:3, :3].T if g.nrm is not None else np.zeros_like(g.pos))
        UV.append(g.uv if g.uv is not None else np.zeros((len(g.pos), 2)))
        if sg.skin is not None:
            bf = np.array([max(f, 0) for f in c.bone_frames] + [fi], np.int64)
            idx = np.minimum(sg.skin.idx.astype(np.int64), len(bf) - 1)
            J.append(bf[idx])
            W.append(sg.skin.w)
        else:
            J.append(np.c_[np.full(len(g.pos), fi), np.zeros((len(g.pos), 3))].astype(np.int64))
            W.append(np.c_[np.ones(len(g.pos)), np.zeros((len(g.pos), 3))].astype(np.float32))
        T.append(g.tris + base)
    world = [C @ f["world"] for f in c.frames]
    return R.write_skinned_glb(out, np.concatenate(P), np.concatenate(N), np.concatenate(UV), np.concatenate(J),
                               np.concatenate(T), [f["name"] for f in c.frames], [f["parent"] for f in c.frames], world,
                               rgba, name, weights=np.concatenate(W))


def main_raster(txd: bytes, prefer: str | None = None) -> D3dRaster | None:
    """The raster a ped's geometry draws with: the named one, else the largest."""
    rs = txd_rasters(txd)
    if not rs:
        return None
    if prefer:
        for r in rs:
            if r.name.lower() == prefer.lower():
                return r
    return max(rs, key=lambda r: r.width * r.height)


# ---------------------------------------------------------------------------------------------- the owned install
def exe_from_launcher(rom: Path) -> Path | None:
    """The game exe behind a HyperSpin "PC Games" .bat (set "GAMENAME=..." / set "GAMEPATH=..." relative to the .bat)."""
    rom = Path(rom)
    if rom.suffix.lower() == ".exe":
        return rom
    if rom.suffix.lower() != ".bat":
        return None
    try:
        text = rom.read_text("utf-8", "replace")
    except OSError:
        return None
    name = re.search(r'set\s+"?GAMENAME=([^"\r\n]+)', text, re.I)
    path = re.search(r'set\s+"?GAMEPATH=([^"\r\n]+)', text, re.I)
    if not name:
        return None
    rel = (path.group(1) if path else "").replace("\\\\", "\\").strip("\\/").replace("\\", "/")
    return (rom.parent / rel / name.group(1).strip()) if rel else rom.parent / name.group(1).strip()


def locate_install(rom: Path) -> dict:
    """What the catalog's launch target really is: {"kind": "classic" | "definitive" | "unknown", "exe", "root",
    "img", "dir", "ide", "pak"}. classic = a RenderWare install (models/gta3.img beside the exe or up to two folders
    up); definitive = the Unreal Engine 4 Definitive Edition (Gameface/Content/Paks/gta.pak)."""
    rom = Path(rom)
    exe = exe_from_launcher(rom)
    base = exe.parent if exe else (rom if rom.is_dir() else rom.parent)
    out = {"kind": "unknown", "exe": str(exe) if exe else None, "root": str(base), "launcher": str(rom)}
    for up in [base, *base.parents[:3]]:
        img, dr = up / "models" / "gta3.img", up / "models" / "gta3.dir"
        if img.is_file() and dr.is_file():
            ide = up / "data" / "default.ide"
            return out | {"kind": "classic", "root": str(up), "img": str(img), "dir": str(dr), "ide": str(ide) if ide.is_file() else None}
        pak = up / "Gameface" / "Content" / "Paks" / "gta.pak"
        if pak.is_file():
            return out | {"kind": "definitive", "root": str(up), "pak": str(pak), "mods": str(pak.parent / "~mods"),
                          "engine": "Unreal Engine 4 (Gameface project): peds are SK_player / SK_<ped> skeletal-mesh "
                                    "uassets in gta.pak (pak v11, Oodle); not RenderWare"}
    return out


# ---------------------------------------------------------------------------------------- characters DEDICATED
def roster() -> list[dict]:
    """Tommy (player.dff) and the stock peds (every entry the game's data/default.ide lists is extractable by key;
    the roster names the ones a collection usually wants)."""
    return [
        {"key": "player", "slug": "gtavc_tommy", "name": "Tommy Vercetti (Vice City)",
         "aliases": ["Tommy", "Tommy Vercetti", "Vice City Tommy", "Vice City player"], "kind": "character"},
        {"key": "cop", "slug": "gtavc_cop", "name": "VCPD officer (Vice City)", "aliases": ["Vice City cop"], "kind": "character"},
        {"key": "male01", "slug": "gtavc_male01", "name": "male01 pedestrian (Vice City)", "aliases": ["Vice City ped"], "kind": "character"},
    ]


def extract(inst: dict, key: str, out: Path) -> dict:
    """One ped out of a classic install: <key>.dff + its TXD -> rigged .glb + body roles (joint names)."""
    img = ImgArchive(inst["img"], inst["dir"])
    txd_name = key
    if inst.get("ide"):
        for model, txd in ide_peds(Path(inst["ide"]).read_text("utf-8", "replace")):
            if model.lower() == key.lower():
                txd_name = txd
    dff = img.entry(f"{key}.dff")
    txd = img.entry(f"{txd_name}.txd") if f"{txd_name}.txd" in img else None
    c = Clump(dff)
    tex = None
    for _fi, gi in c.skinned or c.atomics:
        names = [t for t in material_textures(c.geoms[gi]) if t]
        tex = names[0] if names else tex
        break
    r = main_raster(txd, tex) if txd else None
    rgba = raster_rgba(r) if r else None
    clump_to_gltf(dff, out, rgba, key)
    st = c.stats()
    return {"glb": out, "roles": st["roles"], "stats": st, "raster": r.describe() if r else None,
            "source_files": [f"models/gta3.img: {key}.dff" + (f", {txd_name}.txd" if txd else "")]}


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract for Vice City PC: Tommy or a ped by DFF key -> skinned .glb + body roles."""
    from . import characters as C
    inst = locate_install(C._rom(ctx, game))
    if inst["kind"] != "classic":
        raise ValueError(f"{game['title']}: the owned install is not the classic RenderWare port ({inst['kind']}: "
                         f"{inst.get('engine') or inst['root']}); only models/gta3.img ped DFFs can be read")
    r = extract(inst, e["key"], Path(work) / f"gtavc_{e['key']}.glb")
    st = r["stats"]
    return {"files": [r["glb"]], "tool": "gbox.gta_vc_models", "roles": r["roles"], "source_files": r["source_files"],
            "notes": f"GTA VC PC {e['key']}.dff: {st['frames']} frames / {st['bones']} bones, {st['vertices']} vertices, "
                     f"{st['triangles']} triangles; {r['raster'] or 'no TXD'}; roles from {sorted(set(st['role_source'].values()))}"}
