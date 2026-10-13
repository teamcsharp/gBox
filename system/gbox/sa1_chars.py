"""Sonic Adventure (Dreamcast) character models -> UAP / glTF: rigged (one bone per Ninja node), textured (PVM).

SA1 predates SA2's chunk models: a character is a tree of classic 0x34-byte NJS_OBJECTs whose NJS_MODELs are "basic"
models (points, normals, meshsets of tris / quads / strips with per-corner UVs, 0x14-byte materials). The six playable
characters live inside 1ST_READ.BIN (load address 0x8C010000), found through the executable's own code by
gbox.sa1_analysis.character_map (texlist load -> draw routine -> tree). Super Sonic lives in the Perfect Chaos boss
overlay (SONICADV/B_CHAOS7.PRS) and Tikal in TIKAL_PROG.PRS; both overlays are PRS-compressed SH-4 modules whose
pointers are absolute addresses in the 0x0Cxxxxxx (cached) range: the load address is recovered from the module's own
PVM table (a "SUPERSONIC" name pointer) or from where its pointers cluster. Textures: SONICADV/<PVM>.PRS (PRS ->
PVM), texture id = PVM order (each character's NJS_TEXLIST has exactly the archive's entry count).

    python -m gbox.sa1_chars DISC.gdi OUT_DIR --char sonic
"""
from __future__ import annotations

import collections
import json
import struct
from pathlib import Path

import numpy as np

from . import ninja, uap
from .sa1_inventory import KEY, MAT_SIZE, MESHSET_SIZE, Exe, scan_trees

GAME_IDS = {"1a3f4cd416db9ffd": "Sonic Adventure (USA)"}
READER = "gbox.sa1_chars + gbox.ninja"
IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
# SA1 characters face -X with +Y up, like SA2's; this turns them to face +Z (glTF viewers, characters.tree_roles:
# left = +X): (x, y, z) -> (z, y, -x)
FACE_Z = [[0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 1]]

# key -> (name, aliases, texture archive SONICADV/<pvm>.PRS, where the tree is)
#   ("exe", slug)          1ST_READ.BIN, the tree character_map proves for that texlist
#   ("overlay", FILE)      SONICADV/<FILE>.PRS module: the largest player-sized tree whose texture ids fit the PVM
CHARACTERS = {
    "sonic": ("Sonic", ["Sonic the Hedgehog", "SA1 Sonic", "Sonic (Sonic Adventure)"], "SONIC", ("exe", "sonic")),
    "tails": ("Tails", ["Miles Prower", "Miles Tails Prower", "SA1 Tails"], "MILES", ("exe", "tails")),
    "knuckles": ("Knuckles", ["Knuckles the Echidna", "SA1 Knuckles"], "KNUCKLES", ("exe", "knuckles")),
    "amy": ("Amy Rose", ["Amy", "SA1 Amy"], "AMY", ("exe", "amy")),
    "big": ("Big the Cat", ["Big", "SA1 Big"], "BIG", ("exe", "big")),
    "e102": ("E-102 Gamma", ["Gamma", "E-102", "E102", "SA1 Gamma"], "E102", ("exe", "e102")),
    "super_sonic": ("Super Sonic", ["SA1 Super Sonic"], "SUPERSONIC", ("overlay", "B_CHAOS7")),
    "tikal": ("Tikal", ["Tikal the Echidna", "SA1 Tikal"], "TIKAL", ("overlay", "TIKAL_PROG")),
}
# the verified USA 1ST_READ.BIN (sha256 45bc5d3c...367a): roots as gbox.sa1_analysis proves them (tests pin these)
USA_ROOTS = {"sonic": 0x8C1CE76C, "tails": 0x8C25F968, "knuckles": 0x8C35B094, "amy": 0x8C4C7C3C, "big": 0x8C52F298,
             "e102": 0x8C42CC34}

USE_TEXTURE = 0x00200000            # NJS_MATERIAL attrflags: NJD_FLAG_USE_TEXTURE


def roster() -> list[dict]:
    """characters.DEDICATED roster rows (slug sa1_<key>: SA2's Sonic already owns the plain "sonic" slug)."""
    return [{"key": k, "slug": f"sa1_{k}", "name": n if k != "sonic" else "Sonic (Sonic Adventure)",
             "aliases": a, "kind": "character"} for k, (n, a, _p, _w) in CHARACTERS.items()]


# ---------------------------------------------------------------- basic NJS_MODEL -> corners

def basic_model(ex: Exe, model: int) -> dict:
    """One basic NJS_MODEL: {points, normals, faces [(material, ((i, uv), (i, uv), (i, uv)))], materials}. Strips
    alternate winding (bit 15 of a strip's count flips it); quads split (0,1,2) (1,3,2); n-gons are strips."""
    pts, nrm, n, msets, mats, nms, nmat = ex.u("IIiIIHH", model)
    P = [ex.u("3f", pts + 12 * i) for i in range(n)]
    N = [ex.u("3f", nrm + 12 * i) for i in range(n)] if nrm else None
    M = []
    for k in range(nmat):
        diffuse, _spec, _exp, tex, fl = ex.u("IIfII", mats + k * MAT_SIZE)
        M.append({"tex": tex & 0x3FFF if fl & USE_TEXTURE else None, "flags": fl,
                  "color": [((diffuse >> s) & 0xFF) / 255 for s in (16, 8, 0, 24)]})        # ARGB -> RGBA
    faces = []
    for m in range(nms):
        tm, nmesh, meshes, _attrs, _nrm, _col, uvs = ex.u("HHIIIII", msets + m * MESHSET_SIZE)
        kind, mat = tm >> 14, tm & 0x3FFF
        p, c = meshes, 0                               # c: corner counter into the meshset's vertuv array

        def uv(j):
            if not uvs or not ex.ok(uvs + 4 * j, 4, 2):
                return [0.0, 0.0]
            u, v = ex.u("hh", uvs + 4 * j)
            return [u / 255.0, v / 255.0]
        for _ in range(nmesh):
            if kind in (0, 1):
                k = 3 + kind
                idx = ex.u(f"{k}H", p)
                cs = [(idx[i], uv(c + i)) for i in range(k)]
                p, c = p + 2 * k, c + k
                faces.append((mat, (cs[0], cs[1], cs[2])))
                if k == 4:
                    faces.append((mat, (cs[1], cs[3], cs[2])))
                continue
            head = ex.u("H", p)[0]
            cnt, flip = head & 0x3FFF, bool(head & 0x8000)
            idx = ex.u(f"{cnt}H", p + 2)
            cs = [(idx[i], uv(c + i)) for i in range(cnt)]
            p, c = p + 2 + 2 * cnt, c + cnt
            for i in range(cnt - 2):
                a, b, d = cs[i:i + 3]
                faces.append((mat, (b, a, d) if (i % 2) ^ flip else (a, b, d)))
    faces = [f for f in faces if max(x[0] for x in f[1]) < n and len({x[0] for x in f[1]}) == 3]
    return {"points": P, "normals": N, "faces": faces, "materials": M}


class Tree:
    """A basic-model NJS_OBJECT tree in the shape gbox.ninja.to_manifest reads (bones, tris per texture id with
    per-corner vertex snapshots): bind-pose model-space vertices, each rigidly bound to its node's bone."""

    def __init__(self, ex: Exe, root: int, root_matrix=IDENTITY):
        self.bones: list[dict] = []
        self.tris: dict[int, list] = {}
        self.vbuf: dict = {}
        self.colors: dict[int, list[float]] = {}        # untextured material keys (>= 0x10000) -> RGBA
        stack = [(root, None, root_matrix)]
        while stack:
            off, parent, pm = stack.pop()
            flags, model = ex.u("II", off)
            pos, ang, scl = ex.u("3f", off + 8), ex.u("3i", off + 0x14), ex.u("3f", off + 0x20)
            child, sib = ex.u("II", off + 0x2C)
            local = ninja._node_matrix([0, 0, 0] if flags & 1 else pos, [0, 0, 0] if flags & 2 else ang,
                                       [1, 1, 1] if flags & 4 else scl, bool(flags & 0x20))
            m = ninja._mat_mul(pm, local)
            if parent is None:
                local = m                                   # the root bone carries root_matrix (FACE_Z)
            bi = len(self.bones)
            self.bones.append({"name": f"node{bi:03d}", "parent": parent, "t": [local[0][3], local[1][3], local[2][3]],
                               "r": ninja._quat(local), "m": m, "addr": off})
            if model and not flags & 8:
                self._model(ex, model, m, bi)
            if sib:                                         # siblings after this node's subtree (depth-first order)
                stack.append((sib, parent, pm))
            if child and not flags & 0x10:
                stack.append((child, bi, m))

    def _model(self, ex: Exe, model: int, m, bone: int):
        bm = basic_model(ex, model)
        W = [ninja._xf(m, v) for v in bm["points"]]
        WN = [ninja._xf(m, v, 0.0) for v in bm["normals"]] if bm["normals"] else None
        for mat, corners in bm["faces"]:
            mm = bm["materials"][mat] if mat < len(bm["materials"]) else {"tex": None, "color": [1, 1, 1, 1]}
            key = mm["tex"]
            if key is None:
                col = [round(x, 3) for x in mm["color"]]
                key = 0x10000 + int(col[0] * 255) * 65536 + int(col[1] * 255) * 256 + int(col[2] * 255)
                self.colors[key] = col
            self.tris.setdefault(key, []).append(tuple(
                (i, uv, {"pos": W[i], "nrm": WN[i] if WN else None, "joints": [(bone, 1.0)]}) for i, uv in corners))

    # ------------------------------------------------------------ body roles

    def world(self) -> list[np.ndarray]:
        """Each bone's world matrix from the exported TRS chain (what the glTF skeleton shows)."""
        W: list = [None] * len(self.bones)

        def get(i):
            if W[i] is None:
                b = self.bones[i]
                m = np.eye(4)
                m[:3, :3], m[:3, 3] = _qmat(b["r"]), b["t"]
                W[i] = m if b["parent"] is None else get(b["parent"]) @ m
            return W[i]
        for i in range(len(self.bones)):
            get(i)
        return W

    def corners(self) -> dict[int, list]:
        """bone -> the vertex snapshots bound to it (shared dicts: rebinding one moves the corner)."""
        out: dict[int, list] = {}
        for tris in self.tris.values():
            for tri in tris:
                for c in tri:
                    out.setdefault(c[2]["joints"][0][0], []).append(c[2])
        return out

    def body_roles(self) -> dict[str, str]:
        """Body roles for SA1's character trees, which tree_roles (a hip -> chest -> shoulders hierarchy) can't read:
        a centre-line body node hangs every part off itself (head, arms, legs, the rigid torso mesh, tails...), each
        limb a joint chain with its meshes on side nodes (Big and Gamma add a second centre hub for the upper body,
        Tikal a pelvis hub for the legs). Facing +Z with left = +X, H = model height:
          * limb candidates = the first off-centre joint (|x| > 2% H) under a centre-line joint, with geometry and 3+
            joint position groups along the path to its lowest vertex (eyes, ears and quills are single leaves);
          * per side the leg is the lowest-anchored candidate reaching the floor, the arm the candidate anchored above
            it whose geometry spans the most height; the groups give upper / fore / hand, thigh / shin / foot;
          * hip = the common ancestor of the four limbs; head = the highest ancestor of the topmost vertex that holds no
            limb, moved down to its first branching joint;
          * chest: SA1 has no chest joint (one rigid torso mesh), so a `chest` bone is added under the hip halfway
            between the leg and shoulder anchors; the arms and head re-parent to it and every other vertex above it
            (the upper torso) is bound to it.
        Adds the chest bone (mutates the tree) and returns {role: bone name}."""
        W = self.world()
        pos = np.array([w[:3, 3] for w in W])
        cor = self.corners()
        kids: dict[int, list[int]] = {}
        for i, b in enumerate(self.bones):
            if b["parent"] is not None:
                kids.setdefault(b["parent"], []).append(i)
        allv = np.array([c["pos"] for cs in cor.values() for c in cs]).reshape(-1, 3)
        if not len(allv):
            raise ValueError("no geometry")
        y0, H = float(allv[:, 1].min()), float(np.ptp(allv[:, 1]))
        eps = 0.02 * H

        def sub(i):
            out, st = [], [i]
            while st:
                j = st.pop()
                out.append(j)
                st.extend(kids.get(j, []))
            return out

        def anc(i):
            out = [i]
            while self.bones[out[-1]]["parent"] is not None:
                out.append(self.bones[out[-1]]["parent"])
            return out

        def chain(root):
            """Joint position groups along the path from root to the bone of its lowest vertex (None: no geometry)."""
            low = min(((c["pos"][1], j) for j in sub(root) for c in cor.get(j, [])), default=None)
            if low is None:
                return None
            path = anc(low[1])
            path = path[:path.index(root) + 1][::-1]
            G: list[list[int]] = []
            for j in path:
                if G and np.linalg.norm(pos[j] - pos[G[-1][-1]]) < eps:
                    G[-1].append(j)
                else:
                    G.append([j])
            return G, low[0]
        cands = []
        for i, b in enumerate(self.bones):
            p = b["parent"]
            if p is None or abs(pos[i][0]) <= eps or abs(pos[p][0]) > eps:
                continue
            ch = chain(i)
            if ch is None or len(ch[0]) < 3:
                continue
            ys = [c["pos"][1] for j in sub(i) for c in cor.get(j, [])]
            cands.append({"root": i, "side": "l" if pos[i][0] > 0 else "r", "y": float(pos[i][1]), "G": ch[0],
                          "low": ch[1], "span": max(ys) - min(ys)})
        roles, limbs = {}, {}
        for s, label in (("l", "left"), ("r", "right")):
            ps = [c for c in cands if c["side"] == s]
            legs = [c for c in ps if c["low"] < y0 + 0.2 * H]
            if not legs:
                raise ValueError(f"no {label} leg (a side joint chain reaching the floor)")
            leg = min(legs, key=lambda c: c["y"])
            arms = [c for c in ps if c is not leg and c["y"] > leg["y"] + eps]
            if not arms:
                raise ValueError(f"no {label} arm above the leg")
            arm = max(arms, key=lambda c: c["span"])
            limbs[s] = (arm, leg)
            for c, names in ((arm, ("upper", "fore", "hand")), (leg, ("thigh", "shin", "foot"))):
                roles[f"{s}_{names[0]}"] = c["G"][0][-1]
                for k, g in zip(names[1:], c["G"][1:3]):
                    roles[f"{s}_{k}"] = g[0]
        roots = [c["root"] for a in limbs.values() for c in a]
        common = set(anc(roots[0]))
        for r in roots[1:]:
            common &= set(anc(r))
        hip = max(common, key=lambda j: len(anc(j)))            # the deepest common ancestor
        in_limb = {j for r in roots for j in sub(r)}
        holders = {j for r in roots for j in anc(r)}            # ancestors of a limb
        top = max(((c["pos"][1], j) for j, cs in cor.items() if j not in in_limb for c in cs), default=None)
        if top is None:
            raise ValueError("no head geometry")
        head = top[1]
        while self.bones[head]["parent"] is not None and self.bones[head]["parent"] not in holders:
            head = self.bones[head]["parent"]
        if head in holders:
            raise ValueError("the topmost vertex belongs to the body node: no separate head")
        hd = head
        while len(kids.get(hd, [])) == 1:
            hd = kids[hd][0]
        roles["hip"], roles["head"] = hip, hd
        sy = np.mean([limbs[s][0]["y"] for s in "lr"])
        ly = np.mean([limbs[s][1]["y"] for s in "lr"])
        hang = [limbs[s][0]["root"] for s in "lr"] + [head]
        roles["chest"] = self._add_chest(hip, (sy + ly) / 2, hang, W, cor, in_limb | set(sub(head)))
        return {r: self.bones[j]["name"] for r, j in roles.items()}

    def _add_chest(self, hip: int, y: float, hang: list[int], W, cor, skip: set[int]) -> int:
        """A `chest` bone under the hip at height y (the hip's own orientation): the `hang` subtrees re-parent to it,
        and every vertex above y on a bone outside `skip` (limbs, head) is bound to it."""
        wh = W[hip]
        p = wh[:3, 3].copy()
        p[1] = y
        target = np.eye(4)
        target[:3, :3], target[:3, 3] = wh[:3, :3], p
        local = np.linalg.inv(wh) @ target
        ci = len(self.bones)
        self.bones.append({"name": "chest", "parent": hip, "t": [float(x) for x in local[:3, 3]],
                           "r": [0.0, 0.0, 0.0, 1.0], "m": None, "addr": 0})
        for h in hang:
            loc = np.linalg.inv(target) @ W[h]
            self.bones[h].update(parent=ci, t=[float(x) for x in loc[:3, 3]], r=ninja._quat(loc.tolist()))
        for j, cs in cor.items():
            if j in skip:
                continue
            for c in cs:
                if c["pos"][1] > y:
                    c["joints"] = [(ci, 1.0)]
        return ci


def _qmat(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


# ---------------------------------------------------------------- locating the trees

def overlay_key(blob: bytes, pvm_name: str | None = None) -> int:
    """Load address of a PRS overlay module: from its PVM table ({char *name, NJS_TEXLIST *} with `pvm_name`) when it
    has one, else the 4 KB-aligned base under which most of its 0x0C / 0x8C words point inside the module."""
    w = np.frombuffer(blob, "<u4", len(blob) // 4)
    hi = (w >> 24 == 0x0C) | (w >> 24 == 0x8C)
    srt = np.sort(w[hi])

    def inside(key):                                       # how many of its pointers land inside the module
        return int(np.searchsorted(srt, key + len(blob)) - np.searchsorted(srt, key))
    if pvm_name:
        s, pat = -1, pvm_name.encode() + b"\0"
        while True:
            s = blob.find(pat, s + 1)
            if s <= 0 or blob[s - 1] == 0:
                break
        if s > 0:                                          # a word w[i] = key + s followed by a valid NJS_TEXLIST *
            keys = set()
            for i in np.nonzero(hi[:-1] & ((w[:-1] - s) % 0x1000 == 0))[0]:
                key, tl = int(w[i]) - s, int(w[i + 1])
                if key <= tl < key + len(blob) - 8:
                    tp, cnt = struct.unpack_from("<II", blob, tl - key)
                    if 0 < cnt < 512 and key <= tp < key + len(blob):
                        keys.add(key)
            if keys:
                return max(sorted(keys), key=inside)
    pages = collections.Counter((int(x) & 0xFFFFF000) for x in srt)
    best = (0, -1)
    for page, _n in pages.most_common(8):
        for key in range(max(0, page - 0x40000), page + 0x1000, 0x1000):
            n = inside(key)
            if n > best[1]:
                best = (key, n)
    return best[0]


def pick_tree(ex: Exe, tex_count: int, min_nodes: int = 40) -> int:
    """The player-sized tree of a module: the most nodes (then points) among trees whose texture ids all fit."""
    trees = [t for t in scan_trees(ex.d, ex.key, min_nodes) if max(t["textures"], default=-1) < tex_count]
    if not trees:
        raise ValueError(f"no tree of {min_nodes}+ nodes fits a {tex_count}-texture archive")
    return int(max(trees, key=lambda t: (t["nodes"], t["points"]))["addr"], 16)


def locate(disc, key: str, exe: bytes | None = None, pvm_count: int | None = None) -> tuple[Exe, int, str]:
    """(module, tree root address, source file) of a roster character."""
    _n, _a, pvm, (where, what) = CHARACTERS[key]
    if where == "exe":
        exe = exe if exe is not None else disc.read("1ST_READ.BIN")
        ex = Exe(exe, KEY)
        import hashlib
        if hashlib.sha256(exe).hexdigest().startswith("45bc5d3c25dcfe2c") and key in USA_ROOTS:
            return ex, USA_ROOTS[key], "1ST_READ.BIN"
        from .sa1_analysis import character_map
        root = (character_map(ex).get(what) or {}).get("root")
        if not root:
            raise ValueError(f"1ST_READ.BIN: no {what} tree reachable from its texlist code")
        return ex, root, "1ST_READ.BIN"
    path = f"SONICADV/{what}.PRS"
    blob = ninja.prs_decompress(disc.read(path))
    ex = Exe(blob, overlay_key(blob, pvm))
    if pvm_count is None:
        pvm_count = len(ninja.pvm(ninja.prs_decompress(disc.read(f"SONICADV/{pvm}.PRS"))))
    return ex, pick_tree(ex, pvm_count), path


# ---------------------------------------------------------------- export

def to_manifest(tree: Tree, name: str, source: dict, textures: list[str | None]) -> uap.Manifest:
    m = ninja.to_manifest(tree, name, source, textures)
    for mat in m.materials:
        k = int(mat.name[3:])
        if k in tree.colors:
            mat.base_color, mat.texture = tree.colors[k], None
            mat.name = f"color{k - 0x10000:06x}"
    m.confidence.update(skin_weights="verified", source_identity="verified")
    return m


def export(gdi: str, out_dir: str, char: str = "sonic") -> Path:
    from .gdrom import GDRom
    disc = GDRom(gdi)
    _n, _a, pvm, _w = CHARACTERS[char]
    tpath = f"SONICADV/{pvm}.PRS"
    tex = ninja.pvm(ninja.prs_decompress(disc.read(tpath)))
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    files: list[str | None] = []
    for tname, chunk in tex:
        try:
            w, h, rgba, _ = ninja.pvr_decode(chunk)
            (out / "textures" / f"{tname}.png").write_bytes(ninja.png(w, h, rgba))
            files.append(f"textures/{tname}.png")
        except ValueError:
            files.append(None)
    ex, root, src = locate(disc, char, pvm_count=len(tex))
    tree = Tree(ex, root, FACE_Z)
    roles = tree.body_roles()                              # adds the chest bone before the skeleton is written
    name = f"sa1_{char}"
    m = to_manifest(tree, name, {"game": "Sonic Adventure (DC)", "files": [src, tpath], "root": f"0x{root:08X}",
                                 "load_address": f"0x{ex.key:08X}", "extraction_method": "gbox.sa1_chars",
                                 "body_roles": roles}, files)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED run(): the GLB + its manifest / textures, the source files and the body roles."""
    from . import characters as C
    gdi = str(C._dc_gdi(ctx, game))
    glb = export(gdi, str(work), e["key"])
    man = json.loads((work / "manifest.json").read_text())
    out = {"files": [glb, work / "textures", work / "manifest.json"], "tool": READER,
           "source_files": man["source"]["files"], "roles": man["source"]["body_roles"],
           "notes": f"Sonic Adventure basic-model tree at {man['source']['root']} "
                    f"({len(man['skeleton'])} nodes, one bone each; rigid per-node skinning)"}
    if e["key"] == "sonic":
        out["extra"] = {"native_player": True}             # the game's lead: the cast planner's lead donor
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("out")
    ap.add_argument("--char", default="sonic", choices=sorted(CHARACTERS))
    a = ap.parse_args(argv)
    print(export(a.gdi, a.out, a.char))


if __name__ == "__main__":
    main()
