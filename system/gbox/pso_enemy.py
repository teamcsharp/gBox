"""Phantasy Star Online Ver. 2 (Dreamcast, US 2OEF, gBox game daba7a3b195dcf6b): an enemy -> a collection character on
the enemy's own Ninja node tree, so the enemy's NJM motions drive the new model (#235: OoT characters as Boomas; the
enemy-slot half of the PSO writer, gbox.pso_player holds the player half and the shared BML / NJ helpers).

Where the enemies live (ISO9660 walk of the GDI, 1844 files): one PRS-packed BML per family in PSO/, named
BM_ENE_<family>_A.BML (17 packs on the disc; BM_ENE_COMMON_ALL.BML is a one-node common model). A pack holds the family's
body .nj entries, each NJTL (texture names) + POF0 + NJCM (node tree) + POF0 with its own PVM texture archive packed
behind it, followed by the family's .njm motions (NMDM, type 3 = position + rotation keys), which animate a body by node
index: one mdata slot per node, in tree order. The three Booma bodies share one 51-node layout, so one motion set
animates all three; a replacement must keep the node count, order, flags and transforms, and may only change what the
nodes draw.

Booma family = PSO/BM_ENE_BM1_SHARK_A.BML (163424 bytes at LBA 189894, exactly 80 sectors, the next file follows at
once: no slack on the disc):
  bm1_s_wala_body.nj    Booma      51 nodes, 203 vertices, 308 triangles; textures s128_bmwal_c / s256_bmwal_a, _b (brown)
  bm1f_s1_wala_body.nj  Gobooma    51 nodes, 203 vertices, 308 triangles, the same skeleton; textures _f_ (blue)
  bm1tl_s_wala_body.nj  Gigobooma  51 nodes, 172 vertices, 288 triangles, a taller skeleton (hip at y 15.8, not 12.7);
                                   textures _t_ / _tl_ (brown, pink)
  appear / atackl / atackr / damage / dead / deadb / leader / mihari / run / stund / wakeup / walk _bm1_s_wala_body.njm
Which body is which comes from the texture colours and the skeleton sizes (Booma brown, Gobooma blue, Gigobooma the
tallest and the odd one out); the game itself hasn't confirmed it yet (the live check in docs/pso_enemy_swap.md).

Skeleton (bind pose; the model faces +Z with its left at +X; ~1 unit = a tenth of a player height). Joint nodes
(flags 0x0c, hidden, translated) carry the motion keys; the mesh nodes (flags 0x05, zero translation) hang off them.
  0 root (caches the strips)      1 / 2 hip joint / pelvis + tail mesh     3 / 4 chest joint / torso + back spikes
  5 / 6 / 7 / 8 right shoulder / upper arm / forearm + claw / claw-tip marker (x -6.9: the right side)
  10 / 11 / 12 / 13 the left arm the same way (x +7.0)
  15 / 16 / 17 / 18 crest: Booma and Gobooma keep 4 vertices on 16, Gigobooma's whole head is 17 (31 vertices)
  19 / 20 / 23 head joint / skull + snout (28 vertices, to z +16) / jaw (14): empty nodes in Gigobooma
  27 / 28 / 30-31 / 32 / 34-35 / 36 left leg: thigh / shin / lower shin / foot / toe marker;  38-47 the right leg
  9, 14, 18, 21, 24, 25, 26, 29, 33, 37, 40, 44, 48 markers (flags 0x1e: hidden, not rotated); 49 / 50 draw nodes
A marker has no mesh and the motions don't rotate it, so donor geometry never lands on one: hand roles point at the
claw-tip markers for the limb fit and collapse onto the forearm node (ninja_swap.split_nodes, tgt["collapse"]). A role the
skeleton has no node for at all gets a virtual joint extrapolated from its parent segment, collapsed the same way.

Writer: the donor goes through the player path (gbox.ninja_swap.fit: sm64_swap.retarget onto the enemy's bind pose with
the role map, decimation to the PSO budgets, rigid per-node geometry, one atlas). Every node keeps its original vertex
chunks (the SA2 / PSO engine rule, gbox.pso_player) and the role nodes get the donor's rigid vertices from a free cache
slot plus new strips on texture 0; the original strips (cached on node 0, drawn by 49 / 50) go. The body's PVM gets the
atlas in texture 0's own size and format; the other textures keep their sizes when the pack still fits its sectors,
else they shrink to 8 x 8 (only texture 0 is referenced). The pack is rebuilt (gbox.pso_player.bml_build, PRS) and the
disc copied as a mod image with the pack rewritten in place (gbox.gdrom.patch_gdi): nothing is written in place.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np

from . import ninja, pso_player
from .pso_player import PSO_BUDGETS, bml_build, bml_files

GAME_IDS = pso_player.GAME_IDS
LIMBS = [("l_upper", "l_fore", "l_hand"), ("r_upper", "r_fore", "r_hand"),
         ("l_thigh", "l_shin", "l_foot"), ("r_thigh", "r_shin", "r_foot")]

BOOMA_PACK = "PSO/BM_ENE_BM1_SHARK_A.BML"
BOOMA_ROLES = {"hip": 2, "chest": 4, "head": 20, "l_upper": 11, "l_fore": 12, "l_hand": 13, "r_upper": 6, "r_fore": 7,
               "r_hand": 8, "l_thigh": 28, "l_shin": 31, "l_foot": 35, "r_thigh": 39, "r_shin": 42, "r_foot": 46}
GIGOBOOMA_ROLES = BOOMA_ROLES | {"head": 17}
BOOMA_COLLAPSE = {13: 12, 8: 7}                       # claw-tip markers -> the forearm that carries the claw
ENEMIES = {
    "booma": {"name": "Booma", "file": BOOMA_PACK, "entry": "bm1_s_wala_body.nj", "roles": BOOMA_ROLES,
              "collapse": BOOMA_COLLAPSE, "head_nodes": [16, 17, 20, 23], "family": "boomas", "area": "Forest"},
    "gobooma": {"name": "Gobooma", "file": BOOMA_PACK, "entry": "bm1f_s1_wala_body.nj", "roles": BOOMA_ROLES,
                "collapse": BOOMA_COLLAPSE, "head_nodes": [16, 17, 20, 23], "family": "boomas", "area": "Forest"},
    "gigobooma": {"name": "Gigobooma", "file": BOOMA_PACK, "entry": "bm1tl_s_wala_body.nj", "roles": GIGOBOOMA_ROLES,
                  "collapse": BOOMA_COLLAPSE, "head_nodes": [16, 17], "family": "boomas", "area": "Forest"},
}
FAMILIES = {"boomas": ["booma", "gobooma", "gigobooma"]}
# The other enemy packs on the disc: slot enemy:<key> replaces every body in the pack (bodies enumerated from the BML,
# roles inferred from the skeleton: infer_roles). Names are read off the pack names and are NOT verified in game.
PACKS = {
    "bm2_moja": ("PSO/BM_ENE_BM2_MOJA_A.BML", "Hildebear family (probable)"),
    "bm3_fly": ("PSO/BM_ENE_BM3_FLY_A.BML", "Monest / Mothmant (probable)"),
    "bm5_wolf": ("PSO/BM_ENE_BM5_WOLF_A.BML", "Savage Wolf / Barbarous Wolf (probable)"),
    "lappy": ("PSO/BM_ENE_LAPPY_AP.BML", "Rag Rappy / Al Rappy"),
    "grass": ("PSO/BM_ENE_GRASS_A.BML", "Grass Assassin (probable)"),
    "cgrass": ("PSO/BM_ENE_CGRASS_A.BML", "Crimson Assassin (probable)"),
    "dubchik": ("PSO/BM_ENE_DUBCHIK_A.BML", "Dubchic / Gilchic (probable)"),
    "gyaranzo": ("PSO/BM_ENE_GYARANZO_A.BML", "Garanz (probable)"),
    "me1_mb": ("PSO/BM_ENE_ME1_MB_A.BML", "Canadine / Canane (probable)"),
    "me3_shinowa": ("PSO/BM_ENE_ME3_SHINOWA_A.BML", "Sinow Beat / Sinow Gold (probable)"),
    "re2_flower": ("PSO/BM_ENE_RE2_FLOWER_A.BML", "Poison Lily / Nar Lily (probable)"),
    "re4_sorcerer": ("PSO/BM_ENE_RE4_SORCERER_A.BML", "Chaos Sorcerer (probable)"),
    "re7_berura": ("PSO/BM_ENE_RE7_BERURA_A.BML", "Dark Belra (probable)"),
    "re8_b_beast": ("PSO/BM_ENE_RE8_B_BEAST_A.BML", "Ruins beast (unidentified)"),
    "df2_bringer": ("PSO/BM_ENE_DF2_BRINGER_A.BML", "Chaos Bringer (probable)"),
    "df3_dimedian": ("PSO/BM_ENE_DF3_DIMEDIAN_A.BML", "Dimenian family (probable)"),
}

# Body size against a hunter (1.0), for the whole-cast swap's by_role mapping (gbox.cast_swap): big donors on the big
# enemies. Rough figures from the families' in-game look; the pack names themselves are still unverified.
SIZES = {"booma": 1.15, "gobooma": 1.15, "gigobooma": 1.4, "bm2_moja": 1.6, "bm3_fly": 0.6, "bm5_wolf": 0.8,
         "lappy": 0.7, "grass": 1.5, "cgrass": 1.5, "dubchik": 1.0, "gyaranzo": 1.6, "me1_mb": 0.7, "me3_shinowa": 1.1,
         "re2_flower": 0.9, "re4_sorcerer": 1.2, "re7_berura": 1.7, "re8_b_beast": 1.3, "df2_bringer": 1.6,
         "df3_dimedian": 1.1}


# ---------------------------------------------------------------- slots and rosters (no disc needed)

def slot_name(slot: str) -> str:
    """enemy:<name> -> the mod-name suffix (lower case, [a-z0-9_])."""
    s = (slot or "").strip().lower()
    s = s[6:] if s.startswith("enemy:") else s
    return "".join(c if c.isalnum() else "_" for c in s).strip("_") or "enemies"


def pack_bodies(bml: bytes) -> list[str]:
    """The body entries (.nj) of an enemy pack, in pack order."""
    return [e["name"].split(b"\0")[0].decode("latin-1").lower() for e in bml_files(bml)
            if e["name"].split(b"\0")[0].lower().endswith(b".nj")]


def resolve_slot(slot: str, disc=None) -> list[dict]:
    """slot=enemy:<name> | enemies -> the bodies to replace: [{key, name, file, entry, roles, collapse, head_nodes}].
    <name>: an ENEMIES key (booma, gobooma, gigobooma), a family (boomas), a PACKS key (bm2_moja: every body of that
    pack) or a body entry name (bm2f_s_moj_body); packs and entries need the disc (gbox.gdrom.GDRom) to list bodies,
    and their roles are inferred from the skeleton at build time."""
    s = (slot or "").strip().lower()
    if s in ("enemies", "enemy", "enemy:all", "enemy:*"):
        return [dict(ENEMIES[k], key=k) for k in ENEMIES]
    if not s.startswith("enemy:"):
        raise ValueError(f"not an enemy slot: {slot!r} (enemy:<name> or enemies)")
    name = s[6:].strip().replace(" ", "_").replace("-", "_")
    if name in ENEMIES:
        return [dict(ENEMIES[name], key=name)]
    if name in FAMILIES:
        return [dict(ENEMIES[k], key=k) for k in FAMILIES[name]]
    known = ", ".join(list(ENEMIES) + list(FAMILIES) + list(PACKS))
    for key, e in ENEMIES.items():                        # a mapped body by its entry name
        if name in (e["entry"], e["entry"].removesuffix(".nj")):
            return [dict(e, key=key)]
    pack = None
    for key, (path, label) in PACKS.items():
        stem = Path(path).stem.lower()
        if name in (key, stem, stem.removeprefix("bm_ene_"), stem.removeprefix("bm_ene_").removesuffix("_a").removesuffix("_ap")):
            pack = (key, path, label)
            break
    if disc is None:
        raise ValueError(f"unknown enemy {name!r} (known: {known}); other packs and body names need the disc to list their bodies")
    if pack is not None:
        key, path, label = pack
        if path not in disc.files:
            raise ValueError(f"{path} is not on this disc")
        bodies = pack_bodies(disc.read(path))
        return [{"key": b.removesuffix(".nj"), "name": f"{label}: {b}", "file": path, "entry": b, "roles": None,
                 "collapse": None, "head_nodes": None, "family": key, "inferred": True} for b in bodies]
    want = name if name.endswith(".nj") else name + ".nj"
    for key, (path, label) in PACKS.items():
        if path in disc.files and want in pack_bodies(disc.read(path)):
            return [{"key": want.removesuffix(".nj"), "name": f"{label}: {want}", "file": path, "entry": want, "roles": None,
                     "collapse": None, "head_nodes": None, "family": key, "inferred": True}]
    raise ValueError(f"unknown enemy {name!r}: not a known slot ({known}) and no pack on the disc has a body {want}")


def slots(disc=None) -> list[dict]:
    """The enemy slots this writer offers (characters op=collect "slots", the cast menu): the Booma family with
    verified skeleton maps, then the other packs (bodies listed when the disc is given, roles inferred)."""
    out = [{"slot": f"enemy:{k}", "name": e["name"], "kind": "enemy", "file": e["file"], "entry": e["entry"],
            "roles": "mapped", "family": e["family"], "area": e["area"], "size": SIZES.get(k, 1.0),
            "writer": "gbox.pso_player"} for k, e in ENEMIES.items()]
    out.append({"slot": "enemy:boomas", "name": "Booma, Gobooma and Gigobooma", "kind": "enemy", "file": BOOMA_PACK,
                "entries": [ENEMIES[k]["entry"] for k in FAMILIES["boomas"]], "roles": "mapped", "family": "boomas",
                "area": "Forest", "aggregate": True, "writer": "gbox.pso_player"})
    for key, (path, label) in PACKS.items():
        row = {"slot": f"enemy:{key}", "name": label, "kind": "enemy", "file": path, "roles": "inferred", "family": key,
               "size": SIZES.get(key, 1.0), "writer": "gbox.pso_player"}
        if disc is not None and path in disc.files:
            row["entries"] = pack_bodies(disc.read(path))
        out.append(row)
    return out


def roster_entries() -> list[dict]:
    """The enemies as gbox.characters DEDICATED roster entries (kind enemy: listed by /api/games/<gid>/roster for the
    cast menu, ripped by op=extract through export(); op=collect leaves them alone)."""
    return [{"key": f"enemy:{k}", "slug": f"pso_{k}", "name": e["name"], "kind": "enemy", "slot": f"enemy:{k}",
             "aliases": [f"PSO {e['name']}", e["name"], f"{e['name']} (PSO enemy)"], "file": e["file"], "entry": e["entry"]}
            for k, e in ENEMIES.items()]


# ---------------------------------------------------------------- the enemy skeleton as a retarget target

def _entry(bml: bytes, name: str) -> dict:
    for e in bml_files(bml):
        if e["name"].split(b"\0")[0].decode("latin-1").lower() == name.lower():
            return e
    raise KeyError(f"no entry {name} in the pack (has {pack_bodies(bml)})")


def _unpack(e: dict) -> tuple[bytes, bytes | None]:
    raw = ninja.prs_decompress(e["raw"]) if e["fields"][0] != e["fields"][2] else e["raw"]
    tex = None
    if e["tex"] is not None:
        tex = ninja.prs_decompress(e["tex"]) if e["fields"][3] != e["fields"][4] else e["tex"]
    return raw, tex


def _njcm(raw: bytes) -> tuple[bytes, bytes]:
    """(everything before the NJCM chunk: NJTL + its POF0, the NJCM data)."""
    o = raw.find(b"NJCM")
    if o < 0:
        raise ValueError("no NJCM chunk")
    size = struct.unpack_from("<I", raw, o + 4)[0]
    return raw[:o], raw[o + 8:o + 8 + size]


def drawn_vertices(nj: ninja.NJ) -> list[dict]:
    """The vertices the model draws, as snapshotted when their strips were drawn (cache slots get reused), de-duplicated
    per slot and drawing node; each {pos, nrm, joints}."""
    seen: dict = {}
    for tris in nj.tris.values():
        for tri in tris:
            for c in tri:
                v = c[2] if len(c) > 2 and c[2] else nj.vbuf.get(c[0])
                if v:
                    seen.setdefault((c[0], max(v["joints"], key=lambda jw: jw[1])[0]), v)
    return list(seen.values()) if seen else list(nj.vbuf.values())


def vertex_owners(nj: ninja.NJ) -> dict[int, int]:
    """{node: number of drawn vertices it owns (strongest weight)}."""
    counts: dict[int, int] = {}
    for v in drawn_vertices(nj):
        j = max(v["joints"], key=lambda jw: jw[1])[0]
        counts[j] = counts.get(j, 0) + 1
    return counts


def infer_roles(nj: ninja.NJ, nodes: list[dict]) -> tuple[dict, dict, list[int]]:
    """Body roles of an enemy node tree from its shape (model facing +Z, left at +X): hip = the first mesh node, chest
    = the first centred mesh node below it, arms = the mirrored pair of chains under the chest, legs = the mirrored pair
    under the hip, head = the centred chest chain with the most vertices (its biggest node). A limb with two mesh nodes
    uses a marker leaf (no mesh) as its hand / foot, collapsed onto the second node. -> (roles, collapse, head_nodes)."""
    counts = vertex_owners(nj)
    par = [nd["parent"] for nd in nodes]
    W = [np.array(b["m"], float)[:3, 3] for b in nj.bones]
    drawn = drawn_vertices(nj)
    pts = np.array([v["pos"] for v in drawn]) if drawn else np.zeros((1, 3))
    tol = 0.08 * max(float(np.ptp(pts[:, 1])), 1e-6)
    kids = lambda i: [k for k, p in enumerate(par) if p == i]

    def chain(i):                                          # the subtree in depth-first order
        out = [i]
        for k in kids(i):
            out += chain(k)
        return out
    mesh = [i for i in range(len(nodes)) if counts.get(i)]
    if not mesh:
        raise ValueError("the enemy model has no vertices")
    hip = mesh[0]
    chest = next((k for k in chain(hip)[1:] if counts.get(k) and abs(W[k][0]) < tol), None)
    roles, collapse = {"hip": hip}, {}
    if chest is not None:
        roles["chest"] = chest

    def limbs(root):                                       # [(first child, mesh nodes, x of the first mesh node)]
        out = []
        for k in kids(root):
            ms = [m for m in chain(k) if counts.get(m)]
            if ms:
                out.append((k, ms, float(W[ms[0]][0])))
        return out

    def pair(cands):
        best = None
        for i, a in enumerate(cands):
            for b in cands[i + 1:]:
                if abs(a[2]) > tol / 2 and abs(a[2] + b[2]) < tol and a[2] * b[2] < 0:
                    score = len(a[1]) + len(b[1])
                    if best is None or score > best[0]:
                        best = (score, a, b)
        return (best[1], best[2]) if best else None

    def assign(ms, names):
        a, b, c = names
        roles[a] = ms[0]
        if len(ms) >= 3:
            roles[b], roles[c] = ms[1], ms[-1]
        elif len(ms) == 2:
            roles[b] = ms[1]
            leaf = next((k for k in kids(ms[1]) if not counts.get(k) and not kids(k)), None)
            if leaf is not None:
                roles[c] = leaf
                collapse[leaf] = ms[1]
    arms = pair(limbs(chest)) if chest is not None else None
    if arms:
        for (_k, ms, x) in arms:
            assign(ms, tuple(("l_" if x > 0 else "r_") + r for r in ("upper", "fore", "hand")))
    legs = pair([l for l in limbs(hip) if chest is None or l[0] not in chain(chest)])
    if legs:
        for (_k, ms, x) in legs:
            assign(ms, tuple(("l_" if x > 0 else "r_") + r for r in ("thigh", "shin", "foot")))
    head_nodes: list[int] = []
    if chest is not None:
        used = {roles[r] for r in roles}
        centred = [(k, ms) for k, ms, x in limbs(chest) if abs(x) < tol and not any(m in used for m in ms)]
        if centred:
            k, ms = max(centred, key=lambda km: sum(counts[m] for m in km[1]))
            roles["head"] = max(ms, key=lambda m: counts[m])
            head_nodes = ms
    return roles, collapse, head_nodes


def enemy_target(nj: ninja.NJ, roles: dict, collapse: dict | None = None, head_nodes=None) -> dict:
    """The enemy's bind pose as a gbox.sm64_swap.retarget target (gbox.ninja_swap.target_from_nj) with: the ground at
    the feet (the Booma's claws dip under the floor), a virtual joint for every limb end the skeleton has no node for
    (hand / foot: extrapolated from the parent segment) and tgt["collapse"] {node: node} for the markers and virtual
    joints, so split_nodes puts their geometry on the animated mesh node."""
    from . import ninja_swap as NS
    roles = dict(roles)
    collapse = dict(collapse or {})
    tgt = NS.target_from_nj(nj, roles, set(head_nodes or ([roles["head"]] if "head" in roles else [])))
    feet = [roles[r] for r in ("l_foot", "r_foot") if r in roles]
    if feet:
        ys = [v["pos"][1] for v in drawn_vertices(nj) if max(v["joints"], key=lambda jw: jw[1])[0] in feet]
        if ys:
            tgt["ground"] = float(min(ys))
    T, W, parent = [np.asarray(t, float) for t in tgt["T"]], list(tgt["W"]), list(tgt["parent"])
    virtual = {}
    for a, b, c in LIMBS:
        if a in roles and b in roles and c not in roles:
            v = T[roles[b]] + (T[roles[b]] - T[roles[a]])
            j = len(T)
            Wj = np.array(W[roles[b]], float).copy()
            Wj[:3, 3] = v
            T.append(v)
            W.append(Wj)
            parent.append(roles[b])
            roles[c] = j
            collapse[j] = roles[b]
            virtual[c] = j
    tgt.update({"T": np.array(T), "W": W, "parent": parent, "joints": len(T), "roles": roles, "collapse": collapse,
                "virtual": virtual})
    return tgt


# ---------------------------------------------------------------- writing the body and its textures

def _render_state(data: bytes, nodes: list[dict]) -> tuple[bytes, int, int, int]:
    """The body's own render state: first material chunk, tiny-chunk flags, texture flags, strip flags."""
    mat, tiny_fl, tex_fl, strip_fl = b"", 0x34, 0x4000, 0x12
    for nd in nodes:
        if not nd["model"]:
            continue
        o = struct.unpack_from("<I", data, nd["model"] + 4)[0]
        if not o:
            continue
        for _ in range(64):
            h = struct.unpack_from("<H", data, o)[0]
            t = h & 0xFF
            if t == 0xFF:
                break
            if 0x10 <= t <= 0x3A:
                mat = mat or data[o:o + 4 + struct.unpack_from("<H", data, o + 2)[0] * 2]
                o += 4 + struct.unpack_from("<H", data, o + 2)[0] * 2
            elif t in (8, 9):
                tiny_fl, tex_fl = h >> 8, struct.unpack_from("<H", data, o + 2)[0] & 0xE000
                o += 4
            elif 0x40 <= t <= 0x4B:
                strip_fl = (h >> 8) | 0x10
                break
            else:
                o += 2
        if mat:
            break
    return mat, tiny_fl, tex_fl, strip_fl


def body_nj(raw: bytes, geo: dict) -> bytes:
    """The body entry (NJTL + POF0 + NJCM + POF0) with the donor geometry {node: (pos, nrm, tris)} drawn by its nodes.
    The tree keeps every node, flag and transform (the motions index nodes); each node keeps its original vertex chunks
    (the engine needs the weighted ones) and loses its strips; geometry nodes add rigid vertices from a free cache slot
    and strips on texture 0."""
    prefix, data = _njcm(raw)
    nodes = ninja.tree_nodes(data, 0)
    nj = ninja.NJ(raw)
    vbase = (max(nj.vbuf) + 1 + 15) & ~15 if nj.vbuf else 0
    mat, tiny_fl, tex_fl, strip_fl = _render_state(data, nodes)
    empty_pl = struct.pack("<HH", 0xFF, 0)
    models = {}
    for j, nd in enumerate(nodes):
        keep = b""
        if nd["model"]:
            vl = struct.unpack_from("<I", data, nd["model"])[0]
            keep = data[vl:vl + ninja.chunk_list_len(data, vl, "v") - 4] if vl else b""
        if j in geo:
            P, N, T = geo[j]
            models[j] = ninja.cnk_model_lists(P, N, T, 0, mat, tiny_fl, tex_fl, strip_fl, base=vbase, keep_vlist=keep)
        elif nd["model"]:
            c_r = struct.unpack_from("<4f", data, nd["model"] + 8)
            models[j] = (keep + struct.pack("<I", 0xFF) if keep else b"", empty_pl, list(c_r[:3]), c_r[3])
    nn = [dict(nd) for nd in nodes]
    for j in geo:
        if j >= len(nn):
            raise ValueError(f"geometry for node {j}, the tree has {len(nn)} nodes")
        nn[j]["flags"] &= ~0x8
    d2, _root, ptrs = ninja.write_tree(nn, models, 0)
    d2 += bytes((-len(d2)) % 4)
    return prefix + b"NJCM" + struct.pack("<I", len(d2)) + d2 + ninja.pof0(ptrs)


def pvm_pack(entries: list[tuple[str, bytes, int | None]], flags: int = 0x11F) -> bytes:
    """A PVM archive of [(name, PVR chunk (GBIX + PVRT or PVRT), global index or None)]: the header lists every
    texture's name, pixel / data format and size (read off its PVRT header) and global index, like PSO's packs."""
    head = bytearray(struct.pack("<HH", flags, len(entries)))
    body = bytearray()
    for k, (name, chunk, gbix) in enumerate(entries):
        q = chunk.find(b"PVRT")
        if q < 0:
            raise ValueError(f"texture {name}: no PVRT chunk")
        pix, fmt, w, h = chunk[q + 8], chunk[q + 9], *struct.unpack_from("<HH", chunk, q + 12)
        head += struct.pack("<H", k)
        if flags & 8:
            head += name.encode("latin-1")[:27].ljust(28, b"\0")
        if flags & 4:
            head += struct.pack("<H", pix | (fmt << 8))
        if flags & 2:
            head += struct.pack("<H", (int(math.log2(w)) - 2) | ((int(math.log2(h)) - 2) << 4))
        if flags & 1:
            head += struct.pack("<I", gbix or 0)
        body += chunk + bytes((-len(chunk)) % 4)
    head += bytes((-len(head)) % 8)
    return b"PVMH" + struct.pack("<I", len(head)) + bytes(head) + bytes(body)


def pvm_meta(data: bytes) -> tuple[int, list[tuple[str, int | None]]]:
    """(header flags, [(name, global index)]) of a PVM."""
    flags, count = struct.unpack_from("<HH", data, 8)
    out, o = [], 12
    for k in range(count):
        o += 2
        name = f"tex{k}"
        if flags & 8:
            name = data[o:o + 28].split(b"\0")[0].decode("latin-1")
            o += 28
        o += (2 if flags & 4 else 0) + (2 if flags & 2 else 0)
        gbix = None
        if flags & 1:
            gbix = struct.unpack_from("<I", data, o)[0]
            o += 4
        out.append((name, gbix))
    return flags, out


def body_pvm(pvm: bytes, atlas, small: bool = False) -> bytes:
    """The body's texture archive with the atlas in every texture (texture 0 in its own size and format; the others
    too, or 8 x 8 twiddled stand-ins when small, since only texture 0 is referenced). Names and global indices stay."""
    flags, meta = pvm_meta(pvm)
    ents = ninja.pvm(pvm)
    out = []
    for k, ((name, chunk), (_n, gbix)) in enumerate(zip(ents, meta)):
        q = chunk.find(b"PVRT")
        if k == 0 or not small:
            new = ninja.pvr_like(chunk, atlas)
        else:
            pix = chunk[q + 8] if chunk[q + 8] in (0, 1, 2) else 1
            img = np.asarray(atlas.convert("RGBA").resize((8, 8)))
            new = chunk[:q] + ninja.pvr_twiddled(img, pix)
        out.append((name, new, gbix))
    return pvm_pack(out, flags)


def room_bytes(disc, path: str) -> int:
    """Bytes a file may grow to in place: its sectors plus the free ones before the next file (gbox.gdrom.patch_gdi)."""
    lba, size = disc.files[path]
    nxt = min((l for l, _s in disc.files.values() if l > lba), default=None)
    return ((nxt - lba) if nxt else (size + 2047) // 2048) * 2048


def _noise(size: int = 128):
    from PIL import Image
    rng = np.random.default_rng(235)
    return Image.fromarray(rng.integers(0, 256, (size, size, 3), np.uint8), "RGB")


def build_swap(disc, model: Path | None, roles: dict | None, work: Path, name: str, enemies: list[dict],
               blender: str | None = None, progress=lambda p, m: None, scale: dict | None = None,
               on_error=None) -> dict:
    """disc: a gbox.gdrom.GDRom (or anything with .files {path: (lba, size)} and .read(path)); enemies: resolve_slot().
    Pairs: an enemy with "donor" {model, roles, name, scale} gets that character instead of model / roles (the
    whole-cast swap: every enemy its own donor, every pack rebuilt once). on_error(key, exc): report a failing enemy
    (or every enemy of a pack that no longer fits) and keep building the rest; without it the first failure raises.
    -> {files {disc path: new pack bytes}, report {enemy key: fit report}, rigged {key: gltf}, atlas {key: PIL}}."""
    from . import ninja_swap as NS
    work = Path(work)
    files, report, rigged, atlases = {}, {}, {}, {}
    by_file: dict[str, list[dict]] = {}
    for en in enemies:
        by_file.setdefault(en["file"], []).append(en)
    for path, group in by_file.items():
        if path not in disc.files:
            err = ValueError(f"{path} is not on this disc")
            if on_error is None:
                raise err
            for en in group:
                on_error(en["key"], err)
            continue
        bml = disc.read(path)
        room = room_bytes(disc, path)
        done_nj: dict[str, bytes] = {}
        done_tex: dict[str, bytes] = {}
        built: list[dict] = []
        for en in group:
            key, entry_name = en["key"], en["entry"].lower()
            donor = en.get("donor") or {}
            d_model = Path(donor["model"]) if donor.get("model") else model
            d_roles, d_name = donor.get("roles", roles), donor.get("name", name)
            d_scale = donor.get("scale", scale) if donor else scale
            try:
                raw, pvm = _unpack(_entry(bml, entry_name))
                if pvm is None:
                    raise ValueError(f"{path}:{entry_name} has no texture archive")
                if d_model is None or not d_roles:
                    raise ValueError(f"{key}: no donor model / body roles")
                nj = ninja.NJ(raw)
                _prefix, data = _njcm(raw)
                nodes = ninja.tree_nodes(data, 0)
                er, ec, eh = en.get("roles"), en.get("collapse"), en.get("head_nodes")
                inferred = er is None
                if inferred:
                    er, ec, eh = infer_roles(nj, nodes)
                    if "hip" not in er or "chest" not in er:
                        raise ValueError(f"{entry_name}: can't infer body roles from its skeleton ({len(nodes)} nodes)")
                tgt = enemy_target(nj, er, ec, eh)
                progress(15, f"Fitting {d_name} to {en['name']} ({len(nodes)} nodes, {len(nj.vbuf)} vertices)")
                noise = _noise()
                tex_try = [(False, body_pvm(pvm, noise, False)), (True, body_pvm(pvm, noise, True))]
                mode = {"small": None}

                def encode(geo, _raw=raw, _entry=entry_name, _tex_try=tex_try, _mode=mode):
                    body = body_nj(_raw, geo)
                    size = 0
                    for small, tex in _tex_try:
                        b2 = bml_build(bml, done_nj | {_entry: body}, done_tex | {_entry: tex})
                        size = len(b2)
                        if size <= room:
                            _mode["small"] = small
                            return body
                    raise ValueError(f"{path}: {size} bytes, {room} available")
                r = NS.fit(d_model, d_roles, tgt, work / key, d_name, PSO_BUDGETS, blender, encode, 128, d_scale, progress)
            except Exception as e:                         # noqa: BLE001 - re-raised unless the caller collects failures
                if on_error is None:
                    raise
                on_error(key, e)
                continue
            done_nj[entry_name] = r["data"]
            done_tex[entry_name] = body_pvm(pvm, r["atlas"], bool(mode["small"]))
            rigged[key], atlases[key] = r["rigged"], r["atlas"]
            built.append(en)
            report[key] = r["report"] | {"enemy": en["name"], "file": path, "entry": entry_name, "nodes_total": len(nodes),
                                         "roles": {k: int(v) for k, v in tgt["roles"].items()},
                                         "collapse": {int(k): int(v) for k, v in tgt["collapse"].items()},
                                         "virtual": {k: int(v) for k, v in tgt["virtual"].items()},
                                         "roles_inferred": inferred, "textures_small": bool(mode["small"]),
                                         "body_bytes": len(r["data"]), "pvm_bytes": len(done_tex[entry_name]),
                                         "donor": d_name}
        if not built:
            continue
        b2 = bml_build(bml, done_nj, done_tex)
        if len(b2) > room:
            err = ValueError(f"{path}: {len(b2)} bytes, {room} available (the atlas packed worse than its stand-in)")
            if on_error is None:
                raise err
            for en in built:
                report.pop(en["key"], None)
                rigged.pop(en["key"], None)
                atlases.pop(en["key"], None)
                on_error(en["key"], err)
            continue
        files[path] = b2
        for en in built:
            report[en["key"]]["pack_bytes"], report[en["key"]]["pack_room"] = len(b2), room
    return {"files": files, "report": report, "rigged": rigged, "atlas": atlases}


def build_mod(cfg, meta: dict, game: dict, gdi: Path, enemies: list[dict], progress=lambda p, m: None,
              root: Path | None = None, name: str | None = None, slot: str = "") -> dict:
    """The mod dir cache/mods/<game>/<name>: a copy of the disc with the enemy packs rewritten (never the original)."""
    import json
    import shutil
    import time
    from . import characters as C, filemods
    from .gdrom import GDRom, patch_gdi
    root = root or C.library_root(cfg)
    gid = game["game_id"]
    name = name or f"pso_{meta['slug']}_as_{slot_name(slot) if slot else '_'.join(e['key'] for e in enemies)}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json)")
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "pso_enemy"
    shutil.rmtree(work, ignore_errors=True)
    b = build_swap(GDRom(gdi), root / meta["slug"] / meta["model"], roles, work, meta["name"], enemies, C._blender(cfg),
                   progress, (meta.get("rig") or {}).get("scale"))
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    for key, path in b["rigged"].items():
        shutil.copy2(path, tdir / f"pso_{key}.gltf")
        b["atlas"][key].save(tdir / f"pso_{key}_atlas.png")
        try:
            C.render_preview(tdir / f"pso_{key}.gltf", tdir / f"pso_{key}_preview.png")
        except Exception as e:                                 # noqa: BLE001 - a preview never blocks the build
            progress(90, f"preview of {key} skipped: {e}")
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    img = patch_gdi(gdi, d, name, b["files"], progress)
    (d / ".gbox-mod.json").write_text(json.dumps({
        "name": name, "game_id": gid, "image": img.name, "built": time.time(), "files": sorted(b["files"]),
        "character": meta["slug"], "slot": slot or "enemy:" + ",".join(e["key"] for e in enemies),
        "enemies": [e["key"] for e in enemies], "verified": False,
        "report": json.loads(json.dumps(b["report"], default=str))}))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img.name, "report": b["report"]}


def build_cast(cfg, game: dict, gdi: Path, pairs: list[tuple[str, dict]], name: str, progress=lambda p, m: None,
               root: Path | None = None) -> dict:
    """The whole-cast swap's PSO pairs path (gbox.cast_swap): [(slot, donor meta)] -> ONE mod with every enemy pack
    rebuilt with its own donors (build_swap pairs) and one GD-ROM written (patch_gdi; never the original).
    -> {mod, image, slots {slot: {status built|partial|failed, reason?, enemies}}, detail {enemy key: fit report}}."""
    import json
    import shutil
    import time
    from . import characters as C, filemods
    from .gdrom import GDRom, patch_gdi
    root = Path(root or C.library_root(cfg))
    disc = GDRom(gdi)
    slots: dict[str, dict] = {}
    todo: list[dict] = []
    owner: dict[str, str] = {}
    for slot, meta in pairs:
        if not pso_player.is_enemy_slot(slot):
            slots[slot] = {"status": "failed", "reason": "the PSO player-class writer builds files the game doesn't draw "
                                                         "yet (pso_player.use: not_working)"}
            continue
        try:
            try:
                enemies = resolve_slot(slot)
            except ValueError:
                enemies = resolve_slot(slot, disc)
        except ValueError as e:
            slots[slot] = {"status": "failed", "reason": str(e)}
            continue
        roles = (meta.get("rig") or {}).get("roles") or {}
        if "hip" not in roles:
            slots[slot] = {"status": "failed", "reason": f"{meta.get('name')} has no body roles (rig.roles)"}
            continue
        keys = []
        for en in enemies:
            if en["key"] in owner:
                continue                                   # an earlier slot already took this body
            owner[en["key"]] = slot
            keys.append(en["key"])
            todo.append(dict(en, donor={"model": root / meta["slug"] / meta["model"], "roles": roles,
                                        "name": meta.get("name") or meta["slug"], "scale": (meta.get("rig") or {}).get("scale"),
                                        "slug": meta["slug"]}))
        slots[slot] = {"status": "pending", "enemies": keys} if keys else \
            {"status": "failed", "reason": "every body of this slot is assigned by another slot"}
    errors: dict[str, str] = {}
    work = Path(cfg.cache) / "characters_build" / "cast" / name
    shutil.rmtree(work, ignore_errors=True)
    b = {"files": {}, "report": {}, "rigged": {}, "atlas": {}}
    if todo:
        progress(5, f"Fitting {len(todo)} enemy bodies ({len({e['file'] for e in todo})} packs)")
        b = build_swap(disc, None, None, work, name, todo, C._blender(cfg), progress,
                       on_error=lambda key, e: errors.__setitem__(key, str(e)[:400] or type(e).__name__))
    for slot, row in slots.items():
        if row["status"] != "pending":
            continue
        bad = {k: errors[k] for k in row["enemies"] if k in errors}
        good = [k for k in row["enemies"] if k in b["report"]]
        row["status"] = "built" if good and not bad else "partial" if good else "failed"
        if bad:
            row["reason"] = "; ".join(f"{k}: {v}" for k, v in bad.items())
    out = {"mod": None, "slots": slots, "detail": json.loads(json.dumps(b["report"], default=str))}
    if not b["files"]:
        return out
    for key, path in b["rigged"].items():                  # the fitted model next to each donor (Blender / previews)
        en = next(e for e in todo if e["key"] == key)
        tdir = root / en["donor"]["slug"] / "targets"
        try:
            tdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, tdir / f"pso_{key}.gltf")
            b["atlas"][key].save(tdir / f"pso_{key}_atlas.png")
        except OSError as e:
            progress(90, f"fitted copy of {key} skipped: {e}")
    d = filemods.mod_dir(cfg, game["game_id"], name)
    if d.exists():
        shutil.rmtree(d)
    img = patch_gdi(gdi, d, name, b["files"], progress)
    (d / ".gbox-mod.json").write_text(json.dumps({
        "name": name, "game_id": game["game_id"], "image": img.name, "built": time.time(), "files": sorted(b["files"]),
        "writer": "gbox.pso_enemy.build_cast", "verified": False,
        "enemies": {k: owner[k] for k in b["report"]}, "report": out["detail"]}))
    shutil.rmtree(work, ignore_errors=True)
    return out | {"mod": name, "image": img.name}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use slot=enemy:<name> | enemies for PSO Ver.2 (DC): the character replaces the enemy's body on the
    enemy's own node tree (its motions drive it); built on the control plane as pso_<slug>_as_<name>, launched on
    request. The build is unverified in game until the live check (docs/pso_enemy_swap.md)."""
    from . import characters as C, filemods
    from .gdrom import GDRom
    gid, slot = game["game_id"], inp.slot or ""
    try:
        enemies = resolve_slot(slot)
    except ValueError as unknown:                          # a pack or body name: the disc lists the bodies
        if not C.library_root(ctx.config).is_dir():
            raise
        try:
            disc = GDRom(C._dc_gdi(ctx, game))
        except (OSError, ValueError):
            raise unknown from None
        enemies = resolve_slot(slot, disc)
    name = f"pso_{meta['slug']}_as_{slot_name(slot)}"
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if inp.rebuild or not have:
        if not C.library_root(ctx.config).is_dir():
            raise ValueError("PSO swaps are built on the control-plane node (the Spark): run this there")
        built = build_mod(ctx.config, meta, game, C._dc_gdi(ctx, game), enemies, ctx.progress, name=name, slot=slot)
        tris = {k: r.get("triangles") for k, r in built["report"].items()}
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces {', '.join(e['name'] for e in enemies)} on the enemy's own motions ({tris} triangles); "
                              "offline play only; unverified in game (live check: Forest 1, first Booma); preview targets/pso_<enemy>_preview.png"})
    out = {"mod": name, "build": built, "slot": slot, "replaces": [e["name"] for e in enemies],
           "verification": "unverified: the enemy must be checked in Forest 1 (docs/pso_enemy_swap.md)"}
    if not inp.launch:
        return out | {"status": "built" if built else "ready"}
    l = C._launch(ctx, gid, name, C.HOST_OS)
    return out | {"status": "built+launched" if built else "launched", "launch": l}


# ---------------------------------------------------------------- the rip side: an enemy body out of the disc

def export(gdi: str, out_dir: str, key: str) -> Path:
    """The enemy body as a skinned GLB (node skeleton, its three textures as PNGs) under out_dir -> the .glb path."""
    from . import uap
    from .gdrom import GDRom
    disc = GDRom(gdi)
    en = resolve_slot(f"enemy:{key}", disc)[0]
    bml = disc.read(en["file"])
    raw, pvm = _unpack(_entry(bml, en["entry"]))
    nj = ninja.NJ(raw)
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    tex_files: list[str | None] = []
    for nm, chunk in (ninja.pvm(pvm) if pvm else []):
        w, h, rgba, _ = ninja.pvr_decode(chunk)
        rel = f"textures/{nm}.png"
        (out / rel).write_bytes(ninja.png(w, h, rgba))
        tex_files.append(rel)
    name = f"pso_{en['key']}"
    m = ninja.to_manifest(nj, name, {"game": "Phantasy Star Online Ver.2 (DC, US)", "enemy": en["name"],
                                     "files": [f"{en['file']}:{en['entry']}"], "extraction_method": "gbox.pso_enemy"}, tex_files)
    m.unit_scale_m = 0.1
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


def export_roles(key: str) -> dict[str, str]:
    """Body roles of a ripped enemy as joint names (ninja.to_manifest names nodes nodeNNN): mesh nodes only."""
    e = ENEMIES.get(key)
    if not e:
        return {}
    return {r: f"node{j:03d}" for r, j in e["roles"].items() if j not in e["collapse"]}


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--slot", default="enemy:booma")
    ap.add_argument("--export", help="write the enemy body as a GLB into this directory")
    a = ap.parse_args()
    from .gdrom import GDRom
    if a.export:
        print(export(a.gdi, a.export, slot_name(a.slot)))
    else:
        print(json.dumps(slots(GDRom(a.gdi)), indent=1))
