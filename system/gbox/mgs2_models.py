"""Metal Gear Solid 2: Substance (PS2 SLUS-20554) character models: stage ``kms`` models (type 0x0a) and their
texture packs (type 0x13) -> rigged, textured GLB.

Layouts recovered from the owned disc (``gbox.mgs2_inventory`` reads the archives); all little endian.

**kms** (type 0x0a, e.g. ``sna_def`` = Snake, ``rai_def`` = Raiden, ``gbs_def`` = a Tanker soldier)::

    0x00 u32 flags / id   0x04 u32 bones   0x08 u32 meshes   0x0c u32 texture pack name hash (``<model>_mt``)
    0x10 u32 x3           0x1c f32 bound min[3], max[3]       (0x34..0x3f 0)
    0x40 mesh records x meshes, 0x40 bytes each:
         u32 flags, u32 parts, f32 min[3], f32 max[3], f32 offset[3] (from the parent, rest pose, millimetres),
         i32 parent, u32 part table offset, u32 x3 (runtime)
    part records (0x30): u32 flags, u32 vertices (<= 32: one VU batch), u32 texture hash, u32 second texture,
         u32 third texture, u32 position offset, u32 normal offset, u32 uv offset, u32 uv2 offset (flags & 0x200),
         u32 x3 0
    positions: s16 x, y, z, w   (model space of the mesh's bone, mm; w = the bone's weight in 1/4096, the rest goes
               to the parent bone: parts with flags & 1 blend two bones)
    normals:   s16 x, y, z (1/4096), u16 flags (0x8000 = strip restart: no triangle ends on this vertex)
    uvs:       s16 u, v (1/4096 of the texture's sub-rectangle)
    every part is one triangle strip.

The rest pose has no rotations (every bone's frame is the model frame): +Y up, the character faces +Z and its right
side is at -X (Snake's holster sits on the -X thigh), i.e. already glTF's frame (left = +X); the GLB is scaled to
metres and moved so the feet stand on y = 0.

**texture pack** (type 0x13, ``<model>_mt``)::

    0x00 u32 0, u32 pixel blocks, u32 pixel blocks, u32 CLUT blocks, u32 textures, u32 0, u32 pixel data offset,
         u32 CLUT data offset
    0x20 textures x 0xa0: f32 u0, v0, du, dv (the sub-rectangle in its page), u32 name hash, 12 bytes 0, a GIF A+D
         packet (CLAMP_1 region clamp, TEX2_1, TEX0_1 (TBP / TBW / PSM 0x13 PSMT8 or 0x14 PSMT4 / TW / TH / CBP /
         CSA, relative to the pack's VRAM), ALPHA_1, NOP) and six floats (-du/2, -dv/2, 1, 1, centre u, centre v)
    pixel data: the pack's VRAM uploaded page-linearly as PSMCT32 (64 pixels wide); CLUT data likewise (CSM1,
    32-bit colours, GS alpha 0x80 = opaque). ``gbox.ps2_gs`` swizzles both.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

from . import mgs2_inventory as inv
from .ps2_gs import GSMemory, alpha_to_8bit, csm1

HDR, MESH, PART, TEXREC = 0x40, 0x40, 0x30, 0xA0
FIXED = 4096.0
GLTF_SCALE = 0.001                     # millimetres -> metres
RESTART = 0x8000
F_BLEND, F_UV2 = 0x1, 0x200


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------- kms
def _u32(b, o):
    if o < 0 or o + 4 > len(b):
        raise FormatError(f"read past the end at 0x{o:x}")
    return struct.unpack_from("<I", b, o)[0]


def parse_kms(b: bytes) -> dict:
    if len(b) < HDR:
        raise FormatError("shorter than the kms header")
    flags, nb, nm, tex = struct.unpack_from("<4I", b, 0)
    extra = struct.unpack_from("<3I", b, 0x10)
    bmin, bmax = struct.unpack_from("<3f", b, 0x1C), struct.unpack_from("<3f", b, 0x28)
    if not 0 < nm <= 2048 or HDR + MESH * nm > len(b):
        raise FormatError(f"{nm} meshes do not fit the file")
    meshes = []
    for i in range(nm):
        o = HDR + MESH * i
        mf, nparts = struct.unpack_from("<2I", b, o)
        mn, mx, off = (struct.unpack_from("<3f", b, o + k) for k in (8, 20, 32))
        parent = struct.unpack_from("<i", b, o + 44)[0]
        ptab = _u32(b, o + 48)
        if not -1 <= parent < i:
            raise FormatError(f"mesh {i}: parent {parent} is not an earlier mesh")
        if nparts > 512 or ptab + PART * nparts > len(b):
            raise FormatError(f"mesh {i}: {nparts} parts at 0x{ptab:x} outside the file")
        parts = []
        for k in range(nparts):
            q = ptab + PART * k
            pf, nv, t1, t2, t3, op, on, ou, o2 = struct.unpack_from("<9I", b, q)
            if nv > 256:
                raise FormatError(f"mesh {i} part {k}: {nv} vertices")
            for what, oo, sz in (("positions", op, 8), ("normals", on, 8), ("uvs", ou, 4)):
                if oo + sz * nv > len(b):
                    raise FormatError(f"mesh {i} part {k}: {what} at 0x{oo:x} outside the file")
            P = np.frombuffer(b, "<i2", nv * 4, op).reshape(nv, 4)
            N = np.frombuffer(b, "<i2", nv * 4, on).reshape(nv, 4)
            UV = np.frombuffer(b, "<i2", nv * 2, ou).reshape(nv, 2)
            UV2 = None
            if pf & F_UV2 and o2:
                if o2 + 4 * nv > len(b):
                    raise FormatError(f"mesh {i} part {k}: uv2 outside the file")
                UV2 = np.frombuffer(b, "<i2", nv * 2, o2).reshape(nv, 2)
            parts.append({"flags": pf, "tex": (t1, t2, t3), "pos": P[:, :3].astype(np.float64),
                          "w": P[:, 3].astype(np.float64) / FIXED, "nrm": N[:, :3].astype(np.float64) / FIXED,
                          "restart": (N[:, 3].astype(np.int32) & RESTART) != 0, "uv": UV.astype(np.float64) / FIXED,
                          "uv2": None if UV2 is None else UV2.astype(np.float64) / FIXED,
                          "offsets": (op, on, ou, o2)})
        meshes.append({"flags": mf, "min": mn, "max": mx, "offset": np.array(off, float), "parent": parent,
                       "parts": parts, "table": ptab})
    world = []
    for m in meshes:
        world.append(m["offset"] + (world[m["parent"]] if m["parent"] >= 0 else 0))
    return {"flags": flags, "bones": nb, "tex": tex, "extra": extra, "min": bmin, "max": bmax, "meshes": meshes,
            "world": np.array(world), "parents": [m["parent"] for m in meshes]}


def strip_triangles(restart: np.ndarray) -> list[tuple[int, int, int]]:
    """Triangle strip -> triangles: every vertex without the restart (ADC) flag, from the third on, draws the triangle
    of the last three vertices. Winding is settled later from the normals (_oriented)."""
    return [(i - 2, i - 1, i) for i in range(2, len(restart)) if not restart[i]]


def _oriented(P, Nv, tris):
    """Faces whose winding disagrees with their vertex normals are flipped (glTF: counter-clockwise = front)."""
    if not tris:
        return np.zeros((0, 3), int)
    T = np.array(tris, int)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    fn = np.cross(b - a, c - a)
    vn = Nv[T[:, 0]] + Nv[T[:, 1]] + Nv[T[:, 2]]
    flip = (fn * vn).sum(1) < 0
    T[flip] = T[flip][:, [0, 2, 1]]
    return T


def assemble(k: dict) -> dict:
    """kms -> per texture hash: world positions (mm, model frame), normals, uvs, joints [bone, parent], weights."""
    groups: dict[int, dict] = {}
    W = k["world"]
    for bi, m in enumerate(k["meshes"]):
        for p in m["parts"]:
            if len(p["pos"]) < 3:
                continue
            g = groups.setdefault(p["tex"][0], {"P": [], "N": [], "UV": [], "J": [], "Wt": [], "T": [], "n": 0})
            P = p["pos"] + W[bi]
            tris = _oriented(P, p["nrm"], strip_triangles(p["restart"]))
            if not len(tris):
                continue
            nv = len(P)
            par = m["parent"]
            w = np.clip(p["w"], 0, 1) if (p["flags"] & F_BLEND and par >= 0) else np.ones(nv)
            J = np.zeros((nv, 4), np.uint16)
            Wt = np.zeros((nv, 4), np.float32)
            J[:, 0], Wt[:, 0] = bi, w
            if par >= 0:
                J[:, 1], Wt[:, 1] = par, 1 - w
            g["P"].append(P)
            g["N"].append(p["nrm"])
            g["UV"].append(p["uv"])
            g["J"].append(J)
            g["Wt"].append(Wt)
            g["T"].append(tris + g["n"])
            g["n"] += nv
    out = {}
    for t, g in groups.items():
        if not g["T"]:
            continue
        N = np.concatenate(g["N"])
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        out[t] = {"pos": np.concatenate(g["P"]), "nrm": N, "uv": np.concatenate(g["UV"]),
                  "joints": np.concatenate(g["J"]), "weights": np.concatenate(g["Wt"]),
                  "tris": np.concatenate(g["T"])}
    return out


def triangles(k: dict) -> int:
    return sum(len(strip_triangles(p["restart"])) for m in k["meshes"] for p in m["parts"])


# ---------------------------------------------------------------- body roles
def roles_of(parents: list[int], world: np.ndarray) -> dict[str, int]:
    """Body roles {role: bone} from the tree: the root is the hip; its two downward chains are the legs (-X = right);
    the upward chain leads to the chest (the bone with three children: two arms, the neck)."""
    n = len(parents)
    kids = {i: [c for c in range(n) if parents[c] == i] for i in range(n)}
    roots = [i for i in range(n) if parents[i] < 0]
    if len(roots) != 1:
        return {}
    hip = roots[0]

    def chain(b, depth=4):
        out = [b]
        while len(out) < depth and kids[out[-1]]:
            nxt = max(kids[out[-1]], key=lambda c: len(_desc(kids, c)))
            out.append(nxt)
        return out
    legs = [c for c in kids[hip] if world[c][1] < world[hip][1] and len(chain(c)) >= 3]
    ups = [c for c in kids[hip] if c not in legs and world[c][1] >= world[hip][1]]
    if len(legs) != 2 or not ups:
        return {}
    chest = max(ups, key=lambda c: len(_desc(kids, c)))
    while len(kids[chest]) == 1:
        chest = kids[chest][0]
    if len(kids[chest]) < 3:
        return {}
    sides = sorted(kids[chest], key=lambda c: world[c][0])
    r_arm, neck, l_arm = sides[0], None, sides[-1]
    mid = [c for c in kids[chest] if c not in (r_arm, l_arm)]
    neck = max(mid, key=lambda c: world[c][1]) if mid else None
    if neck is None or not world[r_arm][0] < world[chest][0] < world[l_arm][0]:
        return {}
    roles = {"hip": hip, "chest": chest, "neck": neck}
    head = chain(neck, 2)
    roles["head"] = head[1] if len(head) > 1 else neck
    for side, root in (("r", r_arm), ("l", l_arm)):
        c = chain(root, 4)
        if len(c) < 4:
            return {}
        roles.update({f"{side}_clav": c[0], f"{side}_upper": c[1], f"{side}_fore": c[2], f"{side}_hand": c[3]})
    lr = sorted(legs, key=lambda c: world[c][0])
    for side, root in (("r", lr[0]), ("l", lr[1])):
        c = chain(root, 3)
        roles.update({f"{side}_thigh": c[0], f"{side}_shin": c[1], f"{side}_foot": c[2]})
    return roles


def _desc(kids, b):
    out, st = [], [b]
    while st:
        x = st.pop()
        out.append(x)
        st += kids[x]
    return out


def bone_name(i: int, roles: dict[str, int]) -> str:
    inv_ = {v: k for k, v in roles.items()}
    return f"b{i:02d}_{inv_[i]}" if i in inv_ else f"b{i:02d}"


# ---------------------------------------------------------------- texture packs
class TexturePack:
    def __init__(self, b: bytes):
        if len(b) < 0x20:
            raise FormatError("texture pack shorter than its header")
        h = struct.unpack_from("<8I", b, 0)
        self.raw = b
        self.pix_blocks, self.clut_blocks, self.count = h[1], h[3], h[4]
        self.pix_off, self.clut_off = h[6], h[7]
        if 0x20 + TEXREC * self.count > self.pix_off or self.pix_off + 256 * self.pix_blocks > len(b) or \
                self.clut_off + 256 * self.clut_blocks > len(b):
            raise FormatError("texture pack regions outside the file")
        self.entries = {}
        for i in range(self.count):
            o = 0x20 + TEXREC * i
            u0, v0, du, dv = struct.unpack_from("<4f", b, o)
            hh = _u32(b, o + 16)
            regs = {}
            for k in range(5):
                d, a = struct.unpack_from("<2Q", b, o + 0x30 + 16 * k)
                regs[a & 0xFF] = d
            t0 = regs.get(0x06)
            if t0 is None:
                continue
            self.entries[hh] = {"index": i, "rect": (u0, v0, du, dv), "offset": o, "tex0": t0,
                                "tbp": t0 & 0x3FFF, "tbw": (t0 >> 14) & 0x3F, "psm": (t0 >> 20) & 0x3F,
                                "tw": 1 << ((t0 >> 26) & 0xF), "th": 1 << ((t0 >> 30) & 0xF),
                                "cbp": (t0 >> 37) & 0x3FFF, "csa": (t0 >> 56) & 0x1F}
        self._pix = self._clut = None

    def _mem(self):
        if self._pix is None:
            self._pix = GSMemory(max(self.pix_blocks * 256, 1 << 16) * 2)
            self._pix.load_linear(self.raw[self.pix_off:self.pix_off + 256 * self.pix_blocks])
            self._clut = GSMemory(max(self.clut_blocks * 256, 1 << 14) * 2)
            self._clut.load_linear(self.raw[self.clut_off:self.clut_off + 256 * self.clut_blocks])
        return self._pix, self._clut

    def image(self, h: int) -> np.ndarray | None:
        """The sub-texture as RGBA (alpha 0..255), or None when the pack has no such texture / format."""
        e = self.entries.get(h)
        if e is None:
            return None
        pix, clut = self._mem()
        W, H = max(e["tbw"], 1) * 64, e["th"]
        if e["psm"] == 0x13:
            idx = pix.read8(e["tbp"], e["tbw"], W, H)
            pal = csm1(clut.read32(e["cbp"], 1, 16, 16).reshape(256, 4))
        elif e["psm"] == 0x14:
            idx = pix.read4(e["tbp"], e["tbw"], W, H)
            pal = clut.read32(e["cbp"], 1, 8, 2).reshape(16, 4)
        else:
            return None
        img = alpha_to_8bit(pal)[idx]
        u0, v0, du, dv = e["rect"]
        x0, y0 = int(round(u0 * e["tw"])), int(round(v0 * e["th"]))
        x1, y1 = int(round((u0 + du) * e["tw"])), int(round((v0 + dv) * e["th"]))
        return img[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)].copy()


# ---------------------------------------------------------------- GLB
def write_glb(path: Path, k: dict, packs: list[TexturePack], name: str, roles: dict[str, int] | None = None,
              extras: dict | None = None) -> dict:
    from .defjam_models import png_bytes
    roles = roles if roles is not None else roles_of(k["parents"], k["world"])
    groups = assemble(k)
    if not groups:
        raise FormatError("the model has no triangles")
    allp = np.concatenate([g["pos"] for g in groups.values()])
    ground = float(allp[:, 1].min())
    Wj = (k["world"] - np.array([0, ground, 0])) * GLTF_SCALE
    bin_, views, accs = bytearray(), [], []

    def view(data: bytes, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_.extend(data)
        return len(views) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False):
        arr = np.ascontiguousarray(arr)
        x = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            x["min"], x["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(x)
        return len(accs) - 1
    nodes = []
    for i, par in enumerate(k["parents"]):
        t = Wj[i] - (Wj[par] if par >= 0 else 0)
        nodes.append({"name": bone_name(i, roles), "translation": [float(v) for v in t]})
    for i, par in enumerate(k["parents"]):
        if par >= 0:
            nodes[par].setdefault("children", []).append(i)
    roots = [i for i, p in enumerate(k["parents"]) if p < 0]
    ibm = []
    for w in Wj:
        M = np.eye(4, dtype=np.float32)
        M[3, :3] = -w
        ibm.append(M.reshape(16))
    images, textures, materials, prims = [], [], [], []
    missing = []
    for t, g in groups.items():
        img = next((im for im in (p.image(t) for p in packs) if im is not None), None)
        mat = {"name": f"tex_{t:06x}", "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9}}
        if img is not None and img.size:
            images.append({"bufferView": view(png_bytes(img)), "mimeType": "image/png", "name": f"{t:06x}"})
            textures.append({"source": len(images) - 1, "sampler": 0})
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(textures) - 1}
            if float((img[..., 3] < 128).mean()) > 0.02:
                mat.update(alphaMode="MASK", alphaCutoff=0.5, doubleSided=True)
        else:
            missing.append(f"{t:06x}")
            mat["pbrMetallicRoughness"]["baseColorFactor"] = [0.55, 0.55, 0.55, 1.0]
        materials.append(mat)
        P = (g["pos"] - np.array([0, ground, 0])) * GLTF_SCALE
        attrs = {"POSITION": acc(P.astype(np.float32), "VEC3", minmax=True),
                 "NORMAL": acc(g["nrm"].astype(np.float32), "VEC3"),
                 "TEXCOORD_0": acc(g["uv"].astype(np.float32), "VEC2"),
                 "JOINTS_0": acc(g["joints"].astype(np.uint16), "VEC4", 5123),
                 "WEIGHTS_0": acc(g["weights"].astype(np.float32), "VEC4")}
        prims.append({"attributes": attrs, "material": len(materials) - 1,
                      "indices": acc(g["tris"].reshape(-1).astype(np.uint32), "SCALAR", 5125, 34963)})
    skin = {"name": f"{name}_rig", "joints": list(range(len(Wj))), "skeleton": roots[0],
            "inverseBindMatrices": acc(np.array(ibm, np.float32), "MAT4", target=None)}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox.mgs2_models", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}], "skins": [skin], "materials": materials,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    if images:
        gl.update(images=images, textures=textures,
                  samplers=[{"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071}])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    height = float(np.ptp(allp[:, 1])) * GLTF_SCALE
    return {"glb": str(path), "triangles": int(sum(len(g["tris"]) for g in groups.values())),
            "vertices": int(sum(len(g["pos"]) for g in groups.values())), "bones": len(Wj), "materials": len(materials),
            "textures": len(images), "missing_textures": missing, "height_m": round(height, 3),
            "roles": {r: bone_name(i, roles) for r, i in roles.items()}}


def extract_bytes(kms: bytes, packs: list[bytes], out: Path, name: str, extras: dict | None = None) -> dict:
    k = parse_kms(kms)
    tp = []
    for b in packs:
        try:
            tp.append(TexturePack(b))
        except FormatError:
            pass
    roles = roles_of(k["parents"], k["world"])
    r = write_glb(out, k, tp, name, roles, extras)
    ok = bool(r["triangles"]) and len(roles) == 18 and 0.5 < r["height_m"] < 3.5
    return r | {"verified": ok, "sha256": hashlib.sha256(kms).hexdigest(), "meshes": len(k["meshes"]),
                "texture_pack": f"{k['tex']:06x}"}


# ---------------------------------------------------------------- roster (identified on the owned disc by render)
# (model hash, slug, display name, aliases, writer slot). The hash is name_hash(<model name>) of the stage file
# (type 0x0a); names gBox could not spell are identified from the previews. Where a character has a low and a high
# detail model, the collection takes the high one; the writer replaces both (mgs2_swap.SLOTS).
CAST = [
    (0x55AB65, "mgs2_snake", "Solid Snake (MGS2)", ["Snake", "Solid Snake", "MGS2 Snake", "Snake (Tanker)"], "snake"),
    (0xBFA829, "mgs2_snake_bigshell", "Solid Snake (Big Shell, MGS2)", ["Snake (Plant)", "Big Shell Snake"], "snake"),
    (0x1A1AB0, "mgs2_pliskin", "Iroquois Pliskin (MGS2)", ["Pliskin", "Iroquois Pliskin"], "pliskin"),
    (0xB41E89, "mgs2_raiden", "Raiden (MGS2)", ["Raiden", "MGS2 Raiden", "Jack"], "raiden"),
    (0x064E76, "mgs2_raiden_naked", "Raiden (naked, MGS2)", ["Naked Raiden"], "raiden_naked"),
    (0xB709C9, "mgs2_raiden_disguise", "Raiden (soldier disguise, MGS2)", ["Raiden disguise"], "raiden_disguise"),
    (0x613791, "mgs2_gurlukovich_soldier", "Gurlukovich soldier (Tanker, MGS2)", ["Tanker soldier", "Russian soldier"],
     "soldier_tanker"),
    (0xC9AAAF, "mgs2_gurlukovich_heavy", "Gurlukovich soldier, heavy (Tanker, MGS2)", ["Tanker heavy soldier"],
     "soldier_tanker_heavy"),
    (0xD83AAF, "mgs2_plant_soldier", "Gurlukovich soldier (Big Shell, MGS2)", ["Big Shell soldier", "Plant soldier"],
     "soldier_plant"),
    (0xD7AAAF, "mgs2_plant_soldier_heavy", "Gurlukovich soldier, heavy (Big Shell, MGS2)", ["Plant heavy soldier"],
     "soldier_plant_heavy"),
    (0xFBBAAF, "mgs2_hightech_soldier", "High-tech soldier (MGS2)", ["Hi-tech soldier", "High tech soldier"],
     "soldier_hightech"),
    (0xF13A96, "mgs2_navy_seal", "Navy SEAL (MGS2)", ["SEAL", "Navy SEAL"], "seal"),
    (0x77E995, "mgs2_marine", "US Marine (MGS2)", ["Marine", "US Marine"], "marine"),
    (0x296D9C, "mgs2_tengu", "Tengu soldier (MGS2)", ["Tengu"], "tengu"),
    (0xB3F701, "mgs2_olga", "Olga Gurlukovich (MGS2)", ["Olga", "Olga Gurlukovich"], "olga"),
    (0xC43F41, "mgs2_ninja", "Cyborg Ninja (MGS2)", ["Mr. X", "Ninja", "Cyborg Ninja"], "ninja"),
    (0x9BA944, "mgs2_ocelot", "Revolver Ocelot (MGS2)", ["Ocelot", "Revolver Ocelot"], "ocelot"),
    (0xF4B943, "mgs2_solidus", "Solidus Snake (MGS2)", ["Solidus", "Solidus Snake"], "solidus"),
    (0xB3F7F1, "mgs2_otacon", "Otacon (MGS2)", ["Otacon", "Hal Emmerich"], "otacon"),
]


def roster() -> list[dict]:
    return [{"key": f"{h:06x}", "slug": slug, "name": name, "model_hash": h, "slot": slot,
             "aliases": [*aliases, f"MGS2 {name.split(' (')[0]}"], "kind": "character"}
            for h, slug, name, aliases, slot in CAST]


def source_disc(ctx, game: dict) -> Path:
    from . import characters as C
    p = C._rom(ctx, game)
    if p.suffix.lower() not in (".chd", ".iso"):
        raise FormatError(f"{p.name}: the MGS2 reader reads the PS2 disc (CHD or ISO)")
    return p


def open_disc(path) -> tuple:
    disc = inv.Disc(path)
    ident = inv.identify(disc)
    if not ident["exact_build"]:
        disc.close()
        raise FormatError(f"{ident['boot']} ({ident['elf_sha256']}): the reader is verified on {inv.SERIAL} "
                          f"(ELF sha256 {inv.ELF_SHA256[:16]}) only")
    return disc, ident


class Index:
    """Where each kms / texture pack lives: (archive, stage) per (type, hash), from the stage headers only."""

    def __init__(self, disc):
        self.archives = {fn: inv.StageArchive(disc, fn) for fn in inv.STAGE_FILES}
        self.where: dict[tuple[int, int], list[tuple[str, str]]] = {}
        self._stages: dict[tuple[str, str], inv.Stage] = {}
        for fn, a in self.archives.items():
            for name, _sec in a.stages:
                st = a.stage(name)
                self._stages[(fn, name)] = st
                for p in st.pages:
                    for f in p.files:
                        self.where.setdefault((f[0], f[1]), []).append((fn, name))

    def stage(self, fn: str, name: str) -> inv.Stage:
        return self._stages[(fn, name)]

    def stages_with(self, typ: int, h: int) -> list[tuple[str, str]]:
        return list(dict.fromkeys(self.where.get((typ, h), [])))

    def page(self, fn: str, name: str, k: int, cache: dict | None = None) -> bytes:
        key = (fn, name, k)
        if cache is not None and key in cache:
            return cache[key]
        page = self.archives[fn].page(self.stage(fn, name), k)
        if cache is not None:
            cache[key] = page
        return page

    def read(self, fn: str, name: str, typ: int, h: int, cache: dict | None = None) -> bytes | None:
        hit = self.stage(fn, name).find(typ, h)
        if hit is None:
            return None
        k, f = hit
        return self.page(fn, name, k, cache)[f[2]:f[2] + f[3]]


def best_stage(index: Index, h: int) -> tuple[str, str]:
    """The stage to read a model from: resident stages (r_*) of the story disc file first."""
    places = index.stages_with(inv.T_KMS, h)
    if not places:
        raise FormatError(f"model {h:06x} is not on this disc")
    places.sort(key=lambda p: (not p[1].startswith("r_"), p[0] != "MGS2/STAGE.DAT", p[1]))
    return places[0]


def stage_packs(index: Index, fn: str, stage: str, cache: dict) -> list[tuple[int, bytes]]:
    st = index.stage(fn, stage)
    return [(f[1], index.read(fn, stage, inv.T_TEX, f[1], cache)) for p in st.pages for f in p.files
            if f[0] == inv.T_TEX]


def extract_model(index: Index, h: int, out: Path, name: str) -> dict:
    fn, stage = best_stage(index, h)
    cache: dict = {}
    kms = index.read(fn, stage, inv.T_KMS, h, cache)
    k = parse_kms(kms)
    packs = stage_packs(index, fn, stage, cache)
    packs.sort(key=lambda x: x[0] != k["tex"])                # the model's own pack first
    r = extract_bytes(kms, [b for _h, b in packs], out, name,
                      {"source": f"Metal Gear Solid 2 Substance PS2 {inv.SERIAL}", "model": f"{h:06x}",
                       "stage": f"{fn}:{stage}", "units": "metres (game millimetres x 0.001, feet on y = 0)"})
    return r | {"stage": f"{fn}:{stage}"}


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: one MGS2 character -> rigged, textured GLB with body roles."""
    disc, _ident = open_disc(source_disc(ctx, game))
    h = int(e.get("model_hash") or int(e["key"], 16))
    try:
        r = extract_model(Index(disc), h, Path(work) / f"{e['slug']}.glb", e["slug"])
    finally:
        disc.close()
    if not r["verified"]:
        raise FormatError(f"model {h:06x}: failed verification ({r['triangles']} triangles, "
                          f"{len(r['roles'])} body roles, {r['height_m']} m)")
    return {"files": [Path(r["glb"])], "roles": r["roles"], "tool": "gbox.mgs2_models",
            "source_files": [f"{r['stage']} kms {h:06x} (sha256 {r['sha256'][:16]})",
                             f"texture pack {r['texture_pack']}"],
            "notes": (f"Native {inv.SERIAL} kms model: {r['meshes']} bones, {r['triangles']} triangles from triangle "
                      f"strips, two-bone skin weights (bone + parent), {r['textures']} PS2 CLUT textures from its "
                      f"texture pack, {r['height_m']} m tall. Writer slot: {e.get('slot')} (gbox.mgs2_swap)."),
            "extra": {"mgs2_model": f"{h:06x}", "mgs2_slot": e.get("slot")}}


def extract_all(path, out_dir: Path, slugs=None) -> dict:
    disc, ident = open_disc(path)
    idx = Index(disc)
    out_dir = Path(out_dir)
    rows = []
    for e in roster():
        if slugs and e["slug"] not in slugs:
            continue
        try:
            rows.append({"slug": e["slug"], **extract_model(idx, e["model_hash"], out_dir / f"{e['slug']}.glb", e["slug"])})
        except (FormatError, inv.FormatError, KeyError) as x:
            rows.append({"slug": e["slug"], "verified": False, "error": str(x)})
    disc.close()
    man = {"identity": ident, "verified": sum(bool(r.get("verified")) for r in rows), "total": len(rows), "models": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return man


if __name__ == "__main__":
    man = extract_all(sys.argv[1], Path(sys.argv[2]), sys.argv[3:] or None)
    print(json.dumps({k: man[k] for k in ("verified", "total")}))
    for r in man["models"]:
        print(r["slug"], r.get("verified"), r.get("error") or (r["triangles"], r["height_m"], r["stage"],
                                                                r["missing_textures"]))
