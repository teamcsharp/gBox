"""Resident Evil 6 (Xbox 360) character models: MT Framework .mod (version 0xD3, big-endian) read/write, .mrl
materials, glTF export of the game's characters and the collection -> RE6 character swap writer.

.mod layout (offsets from the header, all big-endian):
  0x00 "\\0DOM" u16 0xD3 u16 bones u16 primitives u16 materials u32 vertices u32 indices u32 triangles
       u32 vertex-buffer size u32 textures(0) u32 groups, then offsets: bones, groups, material hashes, primitives,
       vertex buffer, index buffer, data end
  0x40 bounding sphere, bbox min, bbox max (vec4 each), u32 mid/low LOD distance, light group, 0
  bones: 24 B {u8 id, parent, mirror, 0, f32 furthest vertex, parent distance, x, y, z} + local 4x4 + inverse-bind
       4x4 (row vectors) per bone + a 256-byte id -> index map. The inverse binds work on the quantised vertex
       positions: real = q / 32767 * S + bbox_min, with one scale S folded into every inverse bind.
  groups 32 B, material name hashes (CRC of the .mrl material names), primitives 48 B, u32 count + 144-byte bone
  envelopes (per primitive: one per bone it uses, bone-local bounds), vertex buffer, u16 triangle-list indices.
Vertex formats used for player bodies (hash -> stride): 0xA8FAB018 20 rigid (q pos, u16 bone, normal, tangent, uv),
0xC31F201C 24 two bones, 0x14D40020 28 four bones, 0x64593023 40 four bones + uv2; 0x0CB68015 / 0xB0983013 /
0xDB7DA014 are edge (shadow-volume) meshes.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np

from . import re6

EDGE_FORMATS = {0x0CB68015, 0xB0983013, 0xDB7DA014, 0x0CB68014, 0x0CB6800E, 0xB0983014, 0xB0983012, 0xB098300C,
                0xDB7DA013, 0xDB7DA00D, 0xA320C015, 0xA320C016, 0xA320C00F}
RIGID = 0xA8FAB018
HEADER = ">4sHHHHIIIIIIIIIIIII"            # 0x40 bytes

# Player characters: arc stem per costume; parts = body, head, hands (+ accessory head: hair / cutscene face)
CHARACTERS = {
    "leon": {"pl": "pl0000", "arc": "uPl00{part}Leon{costume}", "costumes": ["Usa", "Asia", "Omake00", "Omake01", "Omake02"],
             "name": "Leon S. Kennedy (RE6)"},
    "helena": {"pl": "pl0100", "arc": "uPl01{part}Helena{costume}", "costumes": ["Usa", "Asia", "Debola", "Omake00", "Omake01", "Omake02"],
               "name": "Helena Harper"},
    "chris": {"pl": "pl0200", "arc": "uPl02{part}Chris{costume}", "costumes": ["Europe", "Asia", "Bad", "Omake00", "Omake01", "Omake02"],
              "name": "Chris Redfield (RE6)"},
    "piers": {"pl": "pl0300", "arc": "uPl03{part}Piers{costume}", "costumes": ["Europe", "Asia", "Canon", "Personal", "Omake00", "Omake01", "Omake02"],
              "name": "Piers Nivans"},
    "jake": {"pl": "pl0400", "arc": "uPl04{part}Jake{costume}", "costumes": ["Europe", "Asia", "Monitor", "Snow", "Omake00", "Omake01", "Omake02"],
             "name": "Jake Muller"},
    "sherry": {"pl": "pl0500", "arc": "uPl05{part}Sherry{costume}", "costumes": ["Europe", "Asia", "Monitor", "Snow", "Omake00", "Omake01", "Omake02"],
               "name": "Sherry Birkin (RE6)"},
    "ada": {"pl": "pl0600", "arc": "uPl06{part}Ada{costume}", "costumes": ["A", "B", "Carla", "Omake00", "Omake01", "Omake02"],
            "name": "Ada Wong (RE6)"},
}
PARTS = ("", "Head", "HandLeft", "HandRight")          # body arc has no part word

# RE6 player skeletons: body role -> bone id (the first byte of each bone record; indices differ between costumes,
# ids don't: Leon Usa has 54 bones, Asia / Omake02 fewer). Resolved to indices per model with role_indices().
RE6_ROLE_IDS = {"pelvis": 15, "hip": 1, "chest": 2, "neck": 3, "head": 4,
                "r_clav": 5, "r_upper": 6, "r_fore": 7, "r_hand": 8,
                "l_clav": 10, "l_upper": 11, "l_fore": 12, "l_hand": 13,
                "r_thigh": 16, "r_shin": 17, "r_foot": 18, "r_toe": 19,
                "l_thigh": 20, "l_shin": 21, "l_foot": 22, "l_toe": 23}


def role_indices(m: "Mod") -> dict:
    ids = {b[0]: i for i, b in enumerate(m.bones)}
    return {r: ids[i] for r, i in RE6_ROLE_IDS.items() if i in ids}


def arc_dir(base: Path) -> Path:
    return Path(base) / "nativeXenon" / "arc" / "X360"


# ------------------------------------------------------------------ .mod

class Mod:
    def __init__(self, data: bytes):
        d = data
        h = struct.unpack_from(HEADER, d)
        (magic, self.version, nb, nm, nmat, self.nv, self.ni, self.ntri, vbs, self.ntex, ng,
         ob, og, omat, omesh, ovb, oib, oend) = h
        if magic != b"\0DOM" or self.version != 0xD3:
            raise ValueError(f"not an RE6 Xbox 360 model ({magic!r} v{self.version:#x})")
        self.info = bytearray(d[0x40:0x80])               # sphere, bbox, LOD distances, light group
        self.bones = [list(struct.unpack_from(">BBBBfffff", d, ob + 24 * i)) for i in range(nb)]
        o = ob + 24 * nb
        self.local = np.array(struct.unpack_from(f">{16 * nb}f", d, o), float).reshape(nb, 4, 4)
        self.inv = np.array(struct.unpack_from(f">{16 * nb}f", d, o + 64 * nb), float).reshape(nb, 4, 4)
        self.remap = bytes(d[o + 128 * nb:o + 128 * nb + 256]) if nb else b""
        self.groups = bytes(d[og:og + 32 * ng])
        self.ng = ng
        self.mat_hashes = list(struct.unpack_from(f">{nmat}I", d, omat))
        self.prims = []
        for i in range(nm):
            f = struct.unpack_from(">HHIIIIIIIIBBHHHI", d, omesh + 48 * i)
            self.prims.append(dict(zip(("draw", "nverts", "data0", "data1", "vstart", "vbo", "fmt", "istart", "icount",
                                        "ivo", "skin_begin", "nenv", "mesh_id", "vmin", "vmax", "rt"), f)))
        o = omesh + 48 * nm
        nenv = struct.unpack_from(">I", d, o)[0]
        envs = [bytes(d[o + 4 + 144 * k:o + 4 + 144 * (k + 1)]) for k in range(nenv)]
        k = 0
        for p in self.prims:                              # envelopes belong to primitives in order
            p["envelopes"] = envs[k:k + p["nenv"]]
            k += p["nenv"]
        self.vb = bytes(d[ovb:ovb + vbs])
        self.ib = np.frombuffer(d, ">u2", self.ni, oib).copy()
        self.tail = bytes(d[oend:]) if oend else b""

    # --- derived
    @property
    def material(self):
        return lambda p: (p["data0"] >> 8) & 0xFFF

    def world(self) -> np.ndarray:
        """Bone world matrices (row-vector convention: v @ M)."""
        W = np.zeros_like(self.local)
        for i, b in enumerate(self.bones):
            W[i] = self.local[i] if b[1] == 255 else self.local[i] @ W[b[1]]
        return W

    def dequant(self) -> np.ndarray:
        """4x4 mapping quantised (0..1) positions to model space: inverse bind @ world of any bone."""
        return self.inv[0] @ self.world()[0]

    @staticmethod
    def pflags(p) -> dict:
        d0, d1 = p["data0"], p["data1"]
        return {"group": d0 >> 20, "material": (d0 >> 8) & 0xFFF, "lod": d0 & 0xFF, "visible": d1 >> 31,
                "weights": (d1 >> 24) & 0x1F, "alpha": (d1 >> 16) & 0xFF, "stride": (d1 >> 8) & 0xFF,
                "prim": (d1 >> 2) & 0x3F, "flip": (d1 >> 1) & 1, "bridge": d1 & 1}

    def decode(self, p) -> dict | None:
        """One primitive -> {pos (model space), nrm, uv, J (n,4 bone indices), W (n,4), tris} or None (edge mesh)."""
        fl = self.pflags(p)
        st, fmt, n = fl["stride"], p["fmt"], p["nverts"]
        if fmt in EDGE_FORMATS:
            return None
        base = p["vbo"] + (p["vstart"] + p["ivo"]) * st
        raw = self.vb[base:base + n * st]
        if fmt == RIGID:
            dt = np.dtype([("p", ">i2", 3), ("b", ">u2"), ("n", "u1", 4), ("t", "u1", 4), ("uv", ">f2", 2)])
        elif fmt == 0xC31F201C:
            dt = np.dtype([("p", ">i2", 3), ("w0", ">i2"), ("n", "u1", 4), ("t", "u1", 4), ("uv", ">f2", 2), ("b2", ">f2", 2)])
        elif fmt in (0x14D40020, 0x14D40022, 0x14D40019, 0x14D4001F, 0x14D40021):
            dt = np.dtype([("p", ">i2", 3), ("w0", ">i2"), ("n", "u1", 4), ("t", "u1", 4), ("b", "u1", 4), ("uv", ">f2", 2),
                           ("w12", ">f2", 2)])
        elif fmt in (0x64593022, 0x64593023, 0x64593025):
            dt = np.dtype([("p", ">i2", 3), ("w0", ">i2"), ("n", "u1", 4), ("t", "u1", 4), ("b", "u1", 4), ("uv", ">f2", 2),
                           ("w12", ">f2", 2), ("x", ">u4"), ("uv2", ">f2", 2), ("y", ">u4")])
        else:
            return None
        if dt.itemsize != st:
            return None
        v = np.frombuffer(raw, dt)
        q = np.c_[v["p"].astype(float) / 32767, np.ones(n)]
        pos = (q @ self.dequant())[:, :3]
        nrm = v["n"][:, :3].astype(float) / 127.5 - 1
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        uv = v["uv"].astype(float)
        J, W = np.zeros((n, 4), int), np.zeros((n, 4))
        sb = p["skin_begin"] if p["skin_begin"] < len(self.bones) else 0
        if fmt == RIGID:
            J[:, 0], W[:, 0] = v["b"].astype(int) + sb, 1
        elif fmt == 0xC31F201C:
            w0 = v["w0"].astype(float) / 32767
            J[:, :2] = v["b2"].astype(float).astype(int) + sb
            W[:, 0], W[:, 1] = w0, 1 - w0
        else:
            w0 = v["w0"].astype(float) / 32767
            w12 = v["w12"].astype(float)
            J[:] = v["b"].astype(int) + sb
            W[:, 0], W[:, 1:3] = w0, w12
            W[:, 3] = np.clip(1 - W[:, :3].sum(1), 0, 1)
        idx = self.ib[p["istart"]:p["istart"] + p["icount"]].astype(int) - p["vstart"]
        tris = idx.reshape(-1, 3)
        tris = tris[(tris >= 0).all(1) & (tris < n).all(1)]
        return {"pos": pos, "nrm": nrm, "uv": uv, "J": J, "W": W, "tris": tris, "material": fl["material"],
                "lod": fl["lod"], "fmt": fmt}

    # --- writing
    def serialize(self) -> bytes:
        nb, nm = len(self.bones), len(self.prims)
        body = bytearray(0x80)
        ob = len(body)
        for b in self.bones:
            body += struct.pack(">BBBBfffff", *b)
        body += self.local.astype(">f4").tobytes() + self.inv.astype(">f4").tobytes() + (self.remap if nb else b"")
        og = len(body)
        body += self.groups
        omat = len(body)
        body += struct.pack(f">{len(self.mat_hashes)}I", *self.mat_hashes)
        omesh = len(body)
        envs = []
        for p in self.prims:
            p["nenv"] = len(p["envelopes"])
            body += struct.pack(">HHIIIIIIIIBBHHHI", p["draw"], p["nverts"], p["data0"], p["data1"], p["vstart"], p["vbo"],
                                p["fmt"], p["istart"], p["icount"], p["ivo"], p["skin_begin"], p["nenv"], p["mesh_id"],
                                p["vmin"], p["vmax"], p.get("rt", 0))
            envs += p["envelopes"]
        body += struct.pack(">I", len(envs)) + b"".join(envs)
        ovb = len(body)
        body += self.vb
        oib = len(body)
        body += self.ib.astype(">u2").tobytes()
        body += bytes((-len(body)) % 4)
        oend = len(body)
        body += self.tail or bytes(4)
        nv = sum(p["nverts"] for p in self.prims)
        struct.pack_into(HEADER, body, 0, b"\0DOM", 0xD3, nb, nm, len(self.mat_hashes), nv, len(self.ib), len(self.ib) // 3,
                         len(self.vb), 0, self.ng, ob, og, omat, omesh, ovb, oib, oend)
        body[0x40:0x80] = self.info
        return bytes(body)


# ------------------------------------------------------------------ .mrl (materials)

class Mrl:
    """Texture table (type hash, path[64]) + 60-byte materials whose command lists name textures by 1-based index."""

    def __init__(self, data: bytes):
        self.d = bytearray(data)
        magic, self.version, self.nmat, self.ntex, self.shader, otex, omat = struct.unpack_from(">4sIIIIII", data)
        if magic != b"\0LRM":
            raise ValueError("not an Xbox 360 .mrl")
        self.otex, self.omat = otex, omat
        self.textures = [data[otex + 0x4C * i + 12:otex + 0x4C * (i + 1)].split(b"\0")[0].decode("latin-1")
                         for i in range(self.ntex)]
        self.materials = []
        for i in range(self.nmat):
            o = omat + 60 * i
            typ, name, size, bs, ds, rs, cnt, flags = struct.unpack_from(">IIIIIIII", data, o)
            anim_size, cmd_off, anim_off = struct.unpack_from(">III", data, o + 48)
            ncmd = cnt >> 20                                # top 12 bits: command count
            texs = []
            for k in range(ncmd):
                c0, val, h = struct.unpack_from(">III", data, cmd_off + 12 * k)
                if c0 >> 28 == 3 and 0 < val <= self.ntex:
                    texs.append(val - 1)
            self.materials.append({"name_hash": name, "textures": texs, "offset": o})

    def by_hash(self, h: int) -> dict | None:
        return next((m for m in self.materials if m["name_hash"] == h), None)

    def set_texture_path(self, i: int, path: str):
        b = path.encode("latin-1")[:63]
        o = self.otex + 0x4C * i + 12
        self.d[o:o + 64] = b + b"\0" + b"\xcd" * (63 - len(b))
        self.textures[i] = path

    def bytes(self) -> bytes:
        return bytes(self.d)


# ------------------------------------------------------------------ reading a character from the extracted disc

def _arc(base: Path, stem: str) -> re6.Arc | None:
    p = arc_dir(base) / f"{stem}.arc"
    return re6.Arc(path=p) if p.is_file() else None


def find_resource(base: Path, name: str, ext: str, prefer: list[str] = ()) -> bytes | None:
    """A resource by full name from the given arcs first, else any arc that has it (index cached per base)."""
    for stem in prefer:
        a = _arc(base, stem)
        if a:
            try:
                return a.get(a.find(name, ext))
            except KeyError:
                pass
    idx = _index(base)
    for stem in idx.get((name.lower(), ext), []):
        a = _arc(base, stem)
        try:
            return a.get(a.find(name, ext))
        except KeyError:
            continue
    return None


_IDX: dict = {}


def _index(base: Path) -> dict:
    """(name lower, ext) -> [arc stems], from the arc headers only (fast; cached in runtime/re6/arc_index.json)."""
    key = str(base)
    if key in _IDX:
        return _IDX[key]
    cache = Path(base).parent / "arc_index.json"
    if cache.is_file():
        raw = json.loads(cache.read_text())
    else:
        raw = {}
        for p in sorted(arc_dir(base).glob("*.arc")):
            with open(p, "rb") as f:
                h = f.read(8)
                if h[:4] != b"\0CRA":
                    continue
                n = struct.unpack(">H", h[6:8])[0]
                t = f.read(80 * n)
            for i in range(n):
                e = t[80 * i:80 * (i + 1)]
                nm = e[:64].split(b"\0")[0].decode("latin-1").lower()
                ext = re6.EXT.get(struct.unpack(">I", e[64:68])[0], f"{struct.unpack('>I', e[64:68])[0]:08x}")
                raw.setdefault(f"{nm}|{ext}", []).append(p.stem)
        cache.write_text(json.dumps(raw))
    _IDX[key] = {tuple(k.split("|")): v for k, v in raw.items()}
    return _IDX[key]


def tex_stems(base: Path, model: str) -> list[str]:
    """uPlTex arcs with this model's textures: a costume's body/head/hands (pl0010..pl0013) share uPlTex0010_*
    (one per damage state). Costumes without them (Omake) keep their textures in the part arcs."""
    return sorted(p.stem for p in arc_dir(base).glob(f"uPlTex{model[2:5]}0_*.arc"))


def character_parts(base: Path, char: str, costume: str | None = None) -> dict:
    c = CHARACTERS[char]
    costume = costume or c["costumes"][0]
    out = {}
    for part in PARTS:
        stem = c["arc"].format(part=part, costume=costume)
        a = _arc(base, stem)
        if not a:
            continue
        for e in a.entries:
            if e["ext"] == "mod" and "\\model\\" in e["name"]:
                out[stem] = {"arc": stem, "mod": e["name"]}
    return out


def _texture_image(base: Path, path: str, prefer: list[str]):
    d = find_resource(base, path, "tex", prefer)
    if not d:
        return None
    try:
        return np.asarray(re6.tex_to_image(d).convert("RGBA"))
    except Exception:
        return None


def export_character(base: Path, char: str, out: Path, costume: str | None = None, lod_mask: int = 1) -> dict:
    """An RE6 player character (body + head + hands, LOD0) -> skinned glTF with its colour textures."""
    from .melee_models import write_gltf
    c = CHARACTERS[char]
    costume = costume or c["costumes"][0]
    first = next(iter(character_parts(base, char, costume).values()), None)
    texarcs = tex_stems(base, first["mod"].rsplit("\\", 1)[1]) if first else []
    body = None
    prims, stats = [], {"parts": [], "triangles": 0}
    for stem, info in character_parts(base, char, costume).items():
        a = _arc(base, stem)
        m = Mod(a.get(a.find(info["mod"], "mod")))
        if body is None or len(m.bones) > len(body.bones):
            body = m if body is None or len(m.bones) > len(body.bones) else body
        mrl_name = info["mod"] + "_0"
        mrl = None
        for nm_ in (info["mod"].rsplit("\\", 1)[0] + "\\" + info["mod"].rsplit("\\", 1)[1] + "_0", info["mod"]):
            d = find_resource(base, nm_, "mrl", texarcs + [stem])
            if d and len(d) > 64:
                mrl = Mrl(d)
                break
        texcache = {}
        for p in m.prims:
            g = m.decode(p)
            if not g or not (g["lod"] & lod_mask) or not len(g["tris"]):
                continue
            if Mod.pflags(p)["group"] >= 29 or p["draw"] == 59080:      # damage caps (shown when a limb is hit), shadows
                continue
            tex = None
            if mrl and g["material"] < len(m.mat_hashes):
                mt = mrl.by_hash(m.mat_hashes[g["material"]])
                if mt:
                    bms = [mrl.textures[t] for t in mt["textures"] if mrl.textures[t].upper().endswith("_BM")]
                    # the character's own colour map, not shared overlays (data/chara/textures/pl_Blood_BM ...)
                    bm = next((x for x in bms if "\\textures\\" not in x.lower() and "blood" not in x.lower()),
                              bms[0] if bms else None)
                    if bm:
                        if bm not in texcache:
                            texcache[bm] = _texture_image(base, bm, texarcs + [stem])
                        tex = texcache[bm]
            # part skeletons share bone ids with the body: map this part's bone indices to body bone indices by id
            prims.append({**g, "tex": tex, "name": f"{stem}_{len(prims)}", "_ids": [b[0] for b in m.bones],
                          "_root": (m.bones[0][0], m.world()[0])})
            stats["triangles"] += len(g["tris"])
        stats["parts"].append(stem)
    if body is None:
        raise FileNotFoundError(f"no model arcs for {char} {costume}")
    id2body = {b[0]: i for i, b in enumerate(body.bones)}
    W = body.world()
    for p in prims:
        ids = p.pop("_ids")
        rid, rw = p.pop("_root")
        root_b = id2body.get(rid, 0)
        if rid != body.bones[0][0] and rid in id2body:    # a part model (head, hands) lives in its root bone's space:
            T = np.linalg.inv(rw) @ W[root_b]             # move it onto the body's bone with the same id
            p["pos"] = (np.c_[p["pos"], np.ones(len(p["pos"]))] @ T)[:, :3]
            p["nrm"] = p["nrm"] @ T[:3, :3]
        # bones the body doesn't have (fingers, face) ride the part's root bone
        p["J"] = np.vectorize(lambda j: id2body.get(ids[j] if j < len(ids) else rid, root_b))(p["J"])
        p["uv"] = p["uv"].astype(np.float32)
    joints = [{"parent": b[1] if b[1] != 255 else -1, "world": W[i].T} for i, b in enumerate(body.bones)]
    names = [f"b{b[0]:03d}" for b in body.bones]
    write_gltf(out, joints, prims, 0.01, f"re6_{char}", names)
    stats["costume"] = costume
    return stats


# ------------------------------------------------------------------ collection character -> RE6 player

class _Tmpl:
    """Duck-typed skeleton for gbox.re4gc_enemies.retarget: bones [(index, parent)], bone_world() {index: xyz}."""

    def __init__(self, m: Mod):
        self.W = m.world()
        self.bones = [(i, b[1]) for i, b in enumerate(m.bones)]

    def bone_world(self) -> dict:
        return {i: self.W[i][3, :3] for i in range(len(self.W))}


def _pack(prims: list[dict], size: int = 1024):
    """Texture pages -> one square atlas. Long strips (PS1 texture pages stacked: 256 x 6400) are cut into square
    pages; each triangle samples the page its centroid falls in; only used pages are packed. Prims are un-indexed
    (3 vertices per triangle) and their uv rewritten in place. Returns the atlas (PIL RGB)."""
    from PIL import Image
    cells, tri_cell = {}, []
    for p in prims:
        t = p.get("tex")
        uv = np.asarray(p["uv"], float)
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        if t is None:                                  # flat material colour: a solid cell of its own
            col = tuple(int(c) for c in (p.get("color") or (200, 200, 200, 255))[:3])
            cells.setdefault(("color", col), (None, col, 1, True))
            tri_cell.append(("color", col))
            continue
        h, w = t.shape[:2]
        n = max(1, round(max(h, w) / min(h, w)))
        cu = uv[T].mean(1)
        page = np.clip(np.floor((cu[:, 1] if h >= w else cu[:, 0]) * n), 0, n - 1).astype(int)
        for pg in set(page.tolist()):
            cells.setdefault((id(t), pg), (t, pg, n, h >= w))
        tri_cell.append(page)
    keys = list(cells)
    g = max(1, int(np.ceil(np.sqrt(len(keys)))))
    cell = size // g
    img = Image.new("RGB", (cell * g, cell * g), (128, 128, 128))
    where = {}
    for k, key in enumerate(keys):
        t, pg, n, tall = cells[key]
        x, y = (k % g) * cell, (k // g) * cell
        if t is None:                                  # solid colour cell
            img.paste(Image.new("RGB", (cell, cell), pg), (x, y))
            where[key] = (x / img.width, y / img.height, cell / img.width)
            continue
        h, w = t.shape[:2]
        crop = t[pg * h // n:(pg + 1) * h // n] if tall else t[:, pg * w // n:(pg + 1) * w // n]
        x, y = (k % g) * cell, (k // g) * cell
        img.paste(Image.fromarray(np.ascontiguousarray(crop[..., :3]).astype(np.uint8)).resize((cell, cell), Image.LANCZOS), (x, y))
        where[key] = (x / img.width, y / img.height, cell / img.width)
    for p, page in zip(prims, tri_cell):
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        flat = T.reshape(-1)
        uv = np.asarray(p["uv"], float)[flat]
        for k in ("pos", "nrm", "J", "W"):
            if k in p:
                p[k] = np.asarray(p[k])[flat]
        if isinstance(page, tuple):                     # solid colour: the middle of its cell
            u0, v0, sz = where[page]
            uv = np.tile([u0 + sz / 2, v0 + sz / 2], (len(flat), 1))
        else:
            t = p["tex"]
            h, w = t.shape[:2]
            n = max(1, round(max(h, w) / min(h, w)))
            pv = np.repeat(page, 3)
            local = uv.copy()
            if h >= w:
                local[:, 1] = uv[:, 1] * n - pv
            else:
                local[:, 0] = uv[:, 0] * n - pv
            local = np.clip(local, 0.002, 0.998)
            o = np.array([where[(id(t), int(q))] for q in pv])
            uv = np.c_[o[:, 0] + local[:, 0] * o[:, 2], o[:, 1] + local[:, 1] * o[:, 2]]
        p["uv"] = uv
        p["tris"] = np.arange(len(flat)).reshape(-1, 3)
    return img


def _envelope(bone: int, P: np.ndarray, Wb: np.ndarray) -> bytes:
    """144-byte bone envelope: bounds of the bone's vertices in bone-local space (sphere, AABB, axis-aligned OBB)."""
    L = (np.c_[P, np.ones(len(P))] @ np.linalg.inv(Wb))[:, :3]
    lo, hi = L.min(0), L.max(0)
    c, ext = (lo + hi) / 2, (hi - lo) / 2
    r = float(np.linalg.norm(L - c, axis=1).max()) if len(L) else 0.0
    obb = np.eye(4)
    obb[3, :3] = c
    return (struct.pack(">IIII", bone, 0, 0, 0) + struct.pack(">4f", *c, r) + struct.pack(">4f", *lo, 0) +
            struct.pack(">4f", *hi, 0) + obb.astype(">f4").tobytes() + struct.pack(">4f", *ext, 0))


def _rigid_vb(P, N, UV, B, dq_inv) -> bytes:
    q = np.clip(np.rint((np.c_[P, np.ones(len(P))] @ dq_inv)[:, :3] * 32767), 0, 32767).astype(">i2")
    n = np.clip(np.rint((np.asarray(N) + 1) * 127.5), 0, 255).astype(np.uint8)
    v = np.zeros(len(P), np.dtype([("p", ">i2", 3), ("b", ">u2"), ("n", "u1", 4), ("t", "u1", 4), ("uv", ">f2", 2)]))
    v["p"], v["b"] = q, B
    v["n"][:, :3], v["n"][:, 3] = n, 255
    v["t"] = (255, 128, 128, 255)                     # tangent +X
    v["uv"] = np.asarray(UV, np.float32)
    return v.tobytes()


def _quantiser(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Model-space bounds -> the 4x4 dequantisation (uniform scale S, offset lo) the inverse binds carry."""
    S = float((hi - lo).max()) * 1.02 + 1e-3
    D = np.eye(4) * S
    D[3] = [lo[0], lo[1], lo[2], 1]
    return D


SKIN4 = 0x14D40020


def _skin4_vb(P, N, UV, B, dq_inv) -> bytes:
    """0x14D40020 (28 B): q pos, s16 weight0, normal, tangent, 4 x u8 bones, half uv, 2 x half weights. Rigid
    vertices: all four bones = the vertex's bone, weights (1, 0, 0)."""
    q = np.clip(np.rint((np.c_[P, np.ones(len(P))] @ dq_inv)[:, :3] * 32767), 0, 32767).astype(">i2")
    n = np.clip(np.rint((np.asarray(N) + 1) * 127.5), 0, 255).astype(np.uint8)
    v = np.zeros(len(P), np.dtype([("p", ">i2", 3), ("w0", ">i2"), ("n", "u1", 4), ("t", "u1", 4), ("b", "u1", 4),
                                   ("uv", ">f2", 2), ("w12", ">f2", 2)]))
    v["p"], v["w0"] = q, 32767
    v["n"][:, :3], v["n"][:, 3] = n, 255
    v["t"] = (255, 128, 128, 255)
    v["b"] = np.repeat(np.asarray(B, np.uint8)[:, None], 4, 1)
    v["uv"] = np.asarray(UV, np.float32)
    return v.tobytes()


def write_body(m: Mod, prims: list[dict], material: int, mesh_id: int, draw: int, group: int = 0, data1: int | None = None) -> bytes:
    """Replace every primitive of `m` with `prims` (pos in model space, nrm, uv (already atlas-mapped), tris, bone
    per vertex in J[:, 0]) as rigid 0xA8FAB018 primitives in all LODs with one material; recompute inverse binds,
    bounds and envelopes."""
    W = m.world()
    allp = np.concatenate([p["pos"] for p in prims])
    allb = np.concatenate([np.asarray(p["J"])[:, 0] for p in prims]).astype(int)
    lo, hi = allp.min(0) - 1.0, allp.max(0) + 1.0
    D = _quantiser(lo, hi)
    m.inv = np.array([D @ np.linalg.inv(W[i]) for i in range(len(W))])
    Dinv = np.linalg.inv(D)
    vb, ib, new = bytearray(), [], []
    for p in prims:
        P, N, UV, T = p["pos"], p["nrm"], p["uv"], p["tris"]
        B = np.asarray(p["J"])[:, 0].astype(int)
        for s in range(0, len(P), 65000):                 # u16 indices: split very large meshes by vertex range
            sel_t = T[(T >= s).all(1) & (T < s + 65000).all(1)] - s
            if not len(sel_t):
                continue
            Ps, Ns, UVs, Bs = P[s:s + 65000], N[s:s + 65000], UV[s:s + 65000], B[s:s + 65000]
            vbo = len(vb)
            vb += _skin4_vb(Ps, Ns, UVs, Bs, Dinv)
            istart = sum(len(x) for x in ib)
            ib.append(sel_t.reshape(-1).astype(np.int64))
            envs = [_envelope(int(b), Ps[Bs == b], W[b]) for b in sorted(set(Bs.tolist()))]
            data0 = (group << 20) | (material << 8) | 0xFF
            d1 = data1 if data1 is not None else (1 << 31) | (4 << 24) | (28 << 8) | (3 << 2) | 2
            new.append({"draw": draw, "nverts": len(Ps), "data0": data0, "data1": d1, "vstart": 0, "vbo": vbo,
                        "fmt": SKIN4, "istart": istart, "icount": int(sel_t.size), "ivo": 0, "skin_begin": 0,
                        "nenv": len(envs), "mesh_id": mesh_id, "vmin": 0, "vmax": len(Ps) - 1, "rt": 0, "envelopes": envs})
    m.prims, m.vb = new, bytes(vb)
    m.ib = np.concatenate(ib).astype(np.uint16)
    c = (allp.min(0) + allp.max(0)) / 2
    r = float(np.linalg.norm(allp - c, axis=1).max())
    m.info[0:48] = struct.pack(">12f", *c, r, *allp.min(0), 0, *allp.max(0), 0)
    for i, b in enumerate(m.bones):                       # furthest vertex per bone (culling)
        sel = allb == i
        b[4] = float(np.linalg.norm(allp[sel] - W[i][3, :3], axis=1).max()) if sel.any() else 0.0
    return m.serialize()


def blank_part(m: Mod) -> bytes:
    """Hide a part model (head, hands): one degenerate triangle on bone 0, everything else removed."""
    W = m.world()
    p0 = W[0][3, :3]
    P = np.array([p0, p0, p0])
    D = _quantiser(p0 - 1, p0 + 1)
    m.inv = np.array([D @ np.linalg.inv(W[i]) for i in range(len(W))])
    vb = _rigid_vb(P, np.array([[0, 1.0, 0]] * 3), np.zeros((3, 2)), np.zeros(3, int), np.linalg.inv(D))
    first = next((p for p in m.prims if p["fmt"] not in EDGE_FORMATS), m.prims[0])
    m.prims = [{"draw": first["draw"], "nverts": 3, "data0": (first["data0"] & ~0xFF) | 0xFF,
                "data1": (1 << 31) | (1 << 24) | (20 << 8) | (3 << 2), "vstart": 0, "vbo": 0, "fmt": RIGID, "istart": 0,
                "icount": 3, "ivo": 0, "skin_begin": 0, "nenv": 1, "mesh_id": first["mesh_id"], "vmin": 0, "vmax": 2,
                "rt": 0, "envelopes": [_envelope(0, P, W[0])]}]
    m.vb, m.ib = vb, np.array([0, 1, 2], np.uint16)
    m.info[0:48] = struct.pack(">12f", *p0, 1.0, *(p0 - 1), 0, *(p0 + 1), 0)
    return m.serialize()


def solid_tex(rgb, size: int = 128) -> bytes:
    from PIL import Image
    return re6.image_to_tex(Image.new("RGB", (size, size), tuple(rgb)), size=size)


def build_swap(base: Path, model: Path, roles: dict, char: str = "leon", costume: str | None = None,
               slug: str = "swap", preview: Path | None = None) -> dict:
    """A collection character (glTF + body roles) as an RE6 player: returns {"files": {disc path: bytes}, ...}.
    Body .mod = the retargeted model (rigid, on the character's own skeleton, so every animation drives it);
    head / hands = hidden; the body material's colour / normal / mask textures -> new gbox textures (every damage
    state's .mrl). Nothing in the original arcs is written: the result is new arc files for a mod folder."""
    from . import characters as C
    from .re4gc_enemies import retarget
    c = CHARACTERS[char]
    costume = costume or c["costumes"][0]
    parts = character_parts(base, char, costume)
    body_stem = c["arc"].format(part="", costume=costume)
    if body_stem not in parts:
        raise FileNotFoundError(f"{body_stem}.arc not on the extracted disc")
    arcs = {s: _arc(base, s) for s in parts}
    body_arc = arcs[body_stem]
    body_name = parts[body_stem]["mod"]
    body = Mod(body_arc.get(body_arc.find(body_name, "mod")))
    rig = C.rig_from_gltf(Path(model), roles)
    roles_t = role_indices(body)
    missing = [r for r in ("pelvis", "hip", "chest", "neck", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
                           "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot") if r not in roles_t]
    if missing:
        raise ValueError(f"{char} {costume}: skeleton lacks {missing}")
    prims = retarget(rig, _Tmpl(body), roles_t, height_range=(150.0, 195.0))
    # big-headed characters (Mario, chibi models): the head is fitted on the head bone and rises far above a human
    # head (the camera then sits inside it). Shrink the head bone's vertices toward the bone until the top is at
    # ~1.85 m; joints stay where they are.
    Wb = body.world()
    hb = roles_t["head"]
    hp = Wb[hb][3, :3]
    top = max(float(np.asarray(p["pos"])[:, 1].max()) for p in prims)
    if top > 190.0:
        k = max(0.35, (185.0 - hp[1]) / max(top - hp[1], 1e-3))
        for p in prims:
            sel = np.asarray(p["J"])[:, 0] == hb
            if sel.any():
                P = np.asarray(p["pos"], float)
                P[sel] = hp + (P[sel] - hp) * k
                p["pos"] = P
    atlas = _pack(prims)
    vis = [p for p in body.prims if p["fmt"] == SKIN4 and Mod.pflags(p)["lod"] == 1 and Mod.pflags(p)["group"] == 0
           and p["draw"] == 65015] or [p for p in body.prims if p["fmt"] not in EDGE_FORMATS]
    main = max(vis, key=lambda p: p["nverts"])               # template: material, mesh id (visible part), flags
    mat = Mod.pflags(main)["material"]
    mat_hash = body.mat_hashes[mat]
    files, notes = {}, []
    # The body material's own colour / normal / mask maps are overwritten in place (same resource names, same size).
    # Pointing the .mrl at new texture names makes the material fail to resolve in game (body invisible: checked), so
    # the material file is never edited. Shared textures (data\\chara\\textures\\..., other characters' folders)
    # are left alone; only this character's own folder is written.
    own = f"data\\chara\\pl\\{c['pl']}\\model\\".lower()
    mrl_name = body_name.lower()
    texarcs = tex_stems(base, body_name.rsplit("\\", 1)[1]) + [body_stem]    # uPlTex<model>_*: e.g. pl0010 (Asia)
    patched = 0
    for stem in texarcs:
        a = body_arc if stem == body_stem else _arc(base, stem)
        changed = False
        for e in list(a.entries):
            if e["ext"] != "mrl" or not e["name"].lower().startswith(mrl_name) or e["size"] <= 64:
                continue
            mt = Mrl(a.get(e))
            mm = mt.by_hash(mat_hash)
            if not mm:
                continue
            for ti in mm["textures"]:
                path = mt.textures[ti]
                # colour map only: normal / mask maps keep their own formats (writing DXT1 into those slots made the
                # body vanish in game)
                suf = "_BM" if path.upper().endswith("_BM") else None
                if not suf or not path.lower().startswith(own):
                    continue
                try:
                    te = a.find(path, "tex")
                except KeyError:
                    continue                                  # lives in another arc of the set: written there
                old = a.get(te)
                inf = re6.tex_info(old)
                w1 = struct.unpack_from(">I", old, 4)[0]
                from PIL import Image
                img = atlas if suf == "_BM" else Image.new("RGB", (8, 8), (128, 128, 255) if suf == "_NM" else (24, 73, 90))
                a.put(path, "tex", re6.image_to_tex(img, size=max(128, inf["width"]), mips=inf["mips"], w1=w1))
                changed = True
            patched += 1
        if changed and stem != body_stem:
            files[f"nativeXenon/arc/X360/{stem}.arc"] = a.build()
    if not patched:
        notes.append(f"no .mrl with material {mat_hash:08x} found: the model draws with {c['name']}'s textures")
    body_bytes = write_body(body, prims, mat, main["mesh_id"], main["draw"], Mod.pflags(main)["group"],
                            main["data1"] if main["fmt"] == SKIN4 else None)
    body_arc.put(body_name, "mod", body_bytes)
    files[f"nativeXenon/arc/X360/{body_stem}.arc"] = body_arc.build()
    for stem, info in parts.items():
        if stem == body_stem:
            continue
        a = arcs[stem]
        a.put(info["mod"], "mod", blank_part(Mod(a.get(a.find(info["mod"], "mod")))))
        files[f"nativeXenon/arc/X360/{stem}.arc"] = a.build()
    out = {"files": files, "character": char, "costume": costume, "triangles": int(sum(len(p["tris"]) for p in prims)),
           "vertices": int(sum(len(p["pos"]) for p in prims)), "material": f"{mat_hash:08x}", "mrl_patched": patched,
           "hidden_parts": [s for s in parts if s != body_stem], "notes": notes}
    if preview is not None:                               # what was written, read back through the reader
        from .melee_models import write_gltf
        chk = Mod(body_bytes)
        W = chk.world()
        img = np.asarray(atlas.convert("RGBA"))
        gp = []
        for p in chk.prims:
            g = chk.decode(p)
            if g:
                gp.append({**g, "uv": g["uv"].astype(np.float32), "tex": img, "name": f"p{len(gp)}"})
        joints = [{"parent": b[1] if b[1] != 255 else -1, "world": W[i].T} for i, b in enumerate(chk.bones)]
        write_gltf(preview, joints, gp, 0.01, f"re6_{slug}", [f"b{b[0]:03d}" for b in chk.bones])
        out["preview_gltf"] = str(preview)
    return out


# ------------------------------------------------------------------ resource propagation
# MT Framework keeps one resident copy per resource path: whichever arc loads it first wins (Leon's body in
# MenuLeon.arc, zombie textures in ~28 arcs). A changed resource is therefore written into every arc on the disc that
# carries the same path, not only the arc it was built from.

def propagate(base: Path, files: dict[str, bytes], progress=None) -> dict[str, bytes]:
    changed: dict[tuple, bytes] = {}
    for rel, data in files.items():
        stem = Path(rel).stem
        orig = _arc(base, stem)
        new = re6.Arc(data)
        olds = {(e["name"].lower(), e["ext"]): e for e in orig.entries} if orig else {}
        for e in new.entries:
            k = (e["name"].lower(), e["ext"])
            o = olds.get(k)
            if o is None or o["csize"] != e["csize"] or o["_raw"] != e["_raw"]:
                changed[k] = new.get(e)
    idx = _index(base)
    targets: dict[str, list] = {}
    for k in changed:
        for stem in idx.get(k, []):
            targets.setdefault(stem, []).append(k)
    out = dict(files)
    for n, (stem, keys) in enumerate(sorted(targets.items())):
        rel = f"nativeXenon/arc/X360/{stem}.arc"
        a = re6.Arc(out[rel]) if rel in out else _arc(base, stem)
        touched = False
        for k in keys:
            e = next((x for x in a.entries if (x["name"].lower(), x["ext"]) == k), None)
            if e is None:
                continue
            if rel in out and e.get("_data") is not None and e["_data"] == changed[k]:
                continue
            cur = a.get(e) if rel in out else None
            if cur == changed[k]:
                continue
            a.put(e["name"], e["type"], changed[k])
            touched = True
        if touched:
            out[rel] = a.build()
        if progress and n % 8 == 0:
            progress(n / max(1, len(targets)), f"{stem}.arc")
    return out


# ------------------------------------------------------------------ enemies
# Zombie / J'avo models bundle every variant (heads, clothes, damage pieces) in one .mod; a variant shows a set of
# part groups. The replacement is written once per group (that group's mesh id + material), so every variant shows
# exactly one copy of it. Every colour map of the enemy family (its own model folders, not the shared
# data\\chara\\textures) gets the character's atlas, whichever material a copy draws with.

ENEMIES = {   # family -> (label, uEm arcs with the models, texture folders the family shares)
    "zombie_male": ("Zombies (men)", ["uEm5000", "uEm5100", "uEm5200", "uEm5300"], ["em5000", "em5100"]),
    "zombie_female": ("Zombies (women)", ["uEm5010", "uEm5110", "uEm5210", "uEm5310"], ["em5010", "em5110"]),
    "zombie_helmet": ("Zombies (helmet / gas mask)", ["uEm5180", "uEm5181", "uEm5190", "uEm5191"], ["em5180", "em5181", "em5190", "em5191"]),
    "zombie_armored": ("Armored zombies", ["uEm5050"], ["em5050"]),
    "javo": ("J'avo (soldiers)", ["uEm5800", "uEm5900"], ["em5800", "em5900"]),
}


def enemy_models(base: Path, family: str) -> list[tuple[str, str]]:
    """(arc stem, .mod name) of the family's full-body models (skeletons with the humanoid roles)."""
    out = []
    for stem in ENEMIES[family][1]:
        a = _arc(base, stem)
        if not a:
            continue
        for e in a.entries:
            if e["ext"] == "mod" and "\\em\\" in e["name"].lower() and e["size"] > 100000:
                try:
                    m = Mod(a.get(e))
                except ValueError:
                    continue
                if len(role_indices(m)) >= 17 and (stem, e["name"]) not in out:
                    out.append((stem, e["name"]))
    return out


def write_enemy(m: Mod, prims: list[dict]) -> bytes:
    """One copy of prims per LOD0 part group of m (representative primitive's material, mesh id, flags)."""
    reps = {}
    for p in m.prims:
        f = Mod.pflags(p)
        if p["fmt"] in EDGE_FORMATS or not (f["lod"] & 1) or p["draw"] == 59080:
            continue
        g = f["group"]
        if g not in reps or (p["fmt"] == SKIN4 and reps[g]["fmt"] != SKIN4) or p["nverts"] > reps[g]["nverts"]:
            reps[g] = p
    if not reps:
        raise ValueError("no drawable part groups in this enemy model")
    W = m.world()
    allp = np.concatenate([p["pos"] for p in prims])
    allb = np.concatenate([np.asarray(p["J"])[:, 0] for p in prims]).astype(int)
    D = _quantiser(allp.min(0) - 1.0, allp.max(0) + 1.0)
    m.inv = np.array([D @ np.linalg.inv(W[i]) for i in range(len(W))])
    Dinv = np.linalg.inv(D)
    # one vertex buffer (shared by every copy), one index range per copy
    P = np.concatenate([np.asarray(p["pos"], float) for p in prims])
    N = np.concatenate([np.asarray(p["nrm"], float) for p in prims])
    UV = np.concatenate([np.asarray(p["uv"], float) for p in prims])
    B = allb
    T, off = [], 0
    for p in prims:
        T.append(np.asarray(p["tris"], int).reshape(-1, 3) + off)
        off += len(p["pos"])
    T = np.concatenate(T)
    if len(P) > 65000:
        raise ValueError("replacement model too large for an enemy (65k vertices)")
    vb = _skin4_vb(P, N, UV, B, Dinv)
    envs = [_envelope(int(b), P[B == b], W[b]) for b in sorted(set(B.tolist()))]
    ib = T.reshape(-1).astype(np.uint16)
    new = []
    for k, (g, rp) in enumerate(sorted(reps.items())):
        f = Mod.pflags(rp)
        data0 = (g << 20) | (f["material"] << 8) | 0xFF
        d1 = rp["data1"] if rp["fmt"] == SKIN4 else (1 << 31) | (4 << 24) | (28 << 8) | (3 << 2) | 2
        d1 = (d1 & ~0xFF00 & ~(0x1F << 24)) | (28 << 8) | (4 << 24)
        new.append({"draw": rp["draw"], "nverts": len(P), "data0": data0, "data1": d1, "vstart": 0, "vbo": 0,
                    "fmt": SKIN4, "istart": 0, "icount": int(ib.size), "ivo": 0, "skin_begin": 0, "nenv": len(envs),
                    "mesh_id": rp["mesh_id"], "vmin": 0, "vmax": len(P) - 1, "rt": rp.get("rt", 0), "envelopes": envs})
    m.prims, m.vb, m.ib = new, vb, ib
    c = (allp.min(0) + allp.max(0)) / 2
    m.info[0:48] = struct.pack(">12f", *c, float(np.linalg.norm(allp - c, axis=1).max()), *allp.min(0), 0, *allp.max(0), 0)
    for i, b in enumerate(m.bones):
        sel = allb == i
        b[4] = float(np.linalg.norm(allp[sel] - W[i][3, :3], axis=1).max()) if sel.any() else 0.0
    return m.serialize()


def build_enemy_swap(base: Path, family: str, model: Path, roles: dict, slug: str = "swap") -> dict:
    """A collection character as every model of an enemy family: {"files": {disc path: arc bytes}, ...}."""
    from . import characters as C
    from .re4gc_enemies import retarget
    if family not in ENEMIES:
        raise ValueError(f"enemy family must be one of {sorted(ENEMIES)}")
    rig = C.rig_from_gltf(Path(model), roles)
    files, report = {}, []
    atlas = None
    for stem, name in enemy_models(base, family):
        rel = f"nativeXenon/arc/X360/{stem}.arc"
        a = re6.Arc(files[rel]) if rel in files else _arc(base, stem)
        m = Mod(a.get(a.find(name, "mod")))
        rt = role_indices(m)
        prims = retarget(rig, _Tmpl(m), rt, height_range=(150.0, 195.0))
        Wb, hb = m.world(), rt["head"]
        hp = Wb[hb][3, :3]
        top = max(float(np.asarray(p["pos"])[:, 1].max()) for p in prims)
        if top > 190.0:
            k = max(0.35, (185.0 - hp[1]) / max(top - hp[1], 1e-3))
            for p in prims:
                sel = np.asarray(p["J"])[:, 0] == hb
                if sel.any():
                    P = np.asarray(p["pos"], float)
                    P[sel] = hp + (P[sel] - hp) * k
                    p["pos"] = P
        img = _pack(prims)
        atlas = atlas or img
        a.put(name, "mod", write_enemy(m, prims))
        files[rel] = a.build()
        report.append({"arc": stem, "model": name.rsplit("\\", 1)[1], "triangles": int(sum(len(p["tris"]) for p in prims))})
    if not report:
        raise FileNotFoundError(f"no models for {family} on the extracted disc")
    # colour maps of the family's own folders -> the atlas (in place; same names, sizes kept)
    folders = [f"data\\chara\\em\\{f}\\model\\".lower() for f in ENEMIES[family][2]]
    idx = _index(base)
    from PIL import Image
    done = set()
    for (nm, ext), stems in idx.items():
        if ext != "tex" or not nm.endswith("_bm") or not any(nm.startswith(f) for f in folders) or nm in done:
            continue
        stem = stems[0]
        rel = f"nativeXenon/arc/X360/{stem}.arc"
        a = re6.Arc(files[rel]) if rel in files else _arc(base, stem)
        e = next(x for x in a.entries if x["name"].lower() == nm and x["ext"] == "tex")
        old = a.get(e)
        inf = re6.tex_info(old)
        if inf["format"] not in (0x14, 0x13):
            continue                                   # keep alpha-tested / special maps (NUKI, DXT5) as they are
        a.put(e["name"], "tex", re6.image_to_tex(atlas, size=max(128, inf["width"]), mips=inf["mips"],
                                                 w1=struct.unpack_from(">I", old, 4)[0]))
        files[rel] = a.build()
        done.add(nm)
    return {"files": files, "family": family, "label": ENEMIES[family][0], "models": report, "textures": len(done)}
