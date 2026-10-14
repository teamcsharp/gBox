"""Soul Calibur II (GameCube): collection characters in place of the fighters (docs/soulcalibur2_gc.md).

Slots: `fighter:<key>` (every costume of a fighter), `fighter:<key>:<n>` (costume n, 1-based), `all` / `cast`
(pairs [{target, donor}], the rest dealt in roster order), `random` (the operator's mixed build: every fighter's
costumes filled from two donor pools and the select patch below). cast_slots() feeds the cast menu; cast_swap uses
the pairs path (build_cast: one disc image for the whole plan).

Per costume:

1. **Retarget**: `sm64_swap.load_rig` + `sm64_swap.retarget` (the shared rigid retarget, Retarget editor profile
   included) onto the costume's own bind skeleton (the VMG bone table: T-pose, metres, +Y up), JMAP role -> bone by
   name (KOSHI hip, MUNE2 chest, ATAMA head, KATA / UDE / TE arms, MOMO / HIZA / ASHI legs). Fit events: scale /
   retarget / proportion (shared retarget), weights, decimate, encode, write.
2. **Atlas**: `auf_swap.donor_materials` + `build_pages` pack the donor's textures into one 256 x 256 CMPR image;
   the 2P colour (both players on the same costume) is the same image, slightly darkened.
3. **Encode** (`sc2_vmg.encode`): a new VMG on the costume's skeleton (bones, names, nodes, texture stages and tail
   kept): one CPU-skinned mesh, every vertex on one bone at weight 1, one material, one texture set. Budget: the
   costume's VMG bytes (package child 0); `auf_swap.decimate` until it fits.
4. **Weapon**: untouched. The weapon packages (the costume's child 13 and base + 16 + w) keep their model and motion;
   the weapon's roots are driven by the fighter's moves around TE_R / TE_L, which the donor's hands now ride.
5. **Disc**: every costume package the slot covers (normal and Extra-mode copies) is rewritten in place inside
   human.olk with the same size, so no OLK record, package offset or FST entry moves. Read back from the image.
6. **Random select** (`random_select=True`): main.dol's body load (0x800a213c) takes `mftb % costume count` instead of
   the selected costume, so each time a fighter is loaded into a match one of its costumes is drawn at random.

  python -m gbox.soulcalibur2_swap random <image> <library dir> <out dir> --pool sa2 --pool sm64ds [--seed S]
  python -m gbox.soulcalibur2_swap build <image> <library dir> <out dir> --pair fighter:taki=sonic ...
  python -m gbox.soulcalibur2_swap verify <image>
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import sc2_vmg as V
from . import soulcalibur2 as S

GAME_IDS = S.GAME_IDS
WRITER = "gbox.soulcalibur2_swap"
RANDOM_MOD = "sc2_sonic_vs_mario_random"
ATLAS = (256, 256)
MAX_TRIS = 9000
SHRINK = 0.85
REPLACEMENT_SPEC = {"skeleton": "Soul Calibur II fighter (VMG bone table: 21 body bones + fingers, face, swing bones; "
                                "CPU skinning)", "roles": "all", "influences": 1, "tex": 256, "decimate": True,
                    "budget": "the costume's VMG bytes (human.olk package child 0); the package keeps its size"}
# the body load in main.dol (case 7 of 0x800a1e4c): lha r27,0x64(r31) / mr r3,r26 / bl 0x800aa518 (costume count)
# / cmpw r27,r3 / bgt +8 / mr r3,r27  ->  mftb r27 / mr r3,r26 / bl / divwu r0,r27,r3 / mullw r0,r0,r3 / subf r3,r0,r27
RANDOM_STOCK = bytes.fromhex("ab7f0064" "7f43d378" "480083d5" "7c1b1800" "41810008" "7f63db78")
RANDOM_PATCH = bytes.fromhex("7f6c42e6" "7f43d378" "480083d5" "7c1b1b96" "7c0019d6" "7c60d850")
SIZE = {"astaroth": 1.25, "berserker": 1.2, "nightmare": 1.1, "necrid": 1.1, "lizardman": 1.05, "inferno": 1.1,
        "talim": 0.9, "seung_mina": 0.95, "taki": 0.95, "xianghua": 0.95, "cassandra": 0.95, "link": 0.95}
POOLS = {"sa2": "Sonic Adventure 2", "sm64ds": "Super Mario 64 DS"}


# ------------------------------------------------------------------------------------------------ slots

def slot_name(key: str, costume: int | None = None) -> str:
    return f"fighter:{key}" + (f":{costume + 1}" if costume is not None else "")


def parse_slot(slot: str) -> tuple[str, int | None]:
    """'fighter:taki' -> ('taki', None); 'fighter:taki:2' -> ('taki', 1); a bare fighter name works too."""
    s = (slot or "").strip().lower()
    if s == "player":                                     # the box-art lead; a fighting game has no single player
        s = "mitsurugi"
    s = s.removeprefix("fighter:")
    parts = s.split(":")
    key = S.fighter(parts[0])[1]
    costume = None
    if len(parts) > 1 and parts[1]:
        costume = int(parts[1]) - 1
        if costume < 0:
            raise ValueError(f"costume numbers start at 1 ({slot})")
    return key, costume


def is_slot(slot: str) -> bool:
    s = (slot or "").strip().lower()
    if s in ("all", "cast", "roster", "everyone", "random"):
        return True
    try:
        parse_slot(s)
        return True
    except (KeyError, ValueError):
        return False


def keys_for(slot: str, table: dict | None = None) -> list[tuple[str, int]]:
    """(fighter key, costume) pairs a slot covers; costume counts from main.dol when table is given (else EXPECTED)."""
    counts = {k: v["costumes"] for k, v in table.items()} if table else {k: v[1] for k, v in S.EXPECTED.items()}
    s = (slot or "").strip().lower()
    if s in ("all", "cast", "roster", "everyone", "random"):
        return [(k, c) for _f, k, _n, _a in S.FIGHTERS for c in range(counts.get(k, 0))]
    key, costume = parse_slot(s)
    if costume is not None:
        if costume >= counts.get(key, 0):
            raise ValueError(f"{key} has {counts.get(key, 0)} costumes")
        return [(key, costume)]
    return [(key, c) for c in range(counts.get(key, 0))]


def cast_slots() -> list[dict]:
    """The cast menu (characters op=collect "slots", char_coverage.cast_slots): one slot per fighter (every
    costume), then the groups."""
    out = []
    for fid, key, name, al in S.FIGHTERS:
        out.append({"slot": slot_name(key), "name": name, "kind": "fighter", "writer": WRITER,
                    "aliases": al, "size": SIZE.get(key, 1.0), "costumes": S.EXPECTED[key][1]})
    out.append({"slot": "all", "name": "every fighter (pairs [{target, donor}], the rest dealt in roster order)",
                "kind": "group", "aggregate": True, "writer": WRITER, "models": len(S.FIGHTERS)})
    return out


# ------------------------------------------------------------------------------------------------ the fit

@dataclass
class Donor:
    slug: str
    name: str
    glb: Path
    roles: dict
    scale: dict | None = None
    rig: dict = None
    source: str = ""
    fits: dict = field(default_factory=dict)


def load_donor(slug: str, glb, roles: dict, name: str = "", scale: dict | None = None, source: str = "") -> Donor:
    from .sm64_swap import load_rig
    roles = dict(roles or {})
    if not {"hip", "head"} <= roles.keys():
        raise ValueError(f"{slug}: the collection entry has no hip/head body roles (rig.roles); not retargetable")
    d = Donor(slug, name or slug, Path(glb), roles, scale, source=source)
    d.rig = load_rig(Path(glb), roles)
    return d


def donor_from_library(root: Path, slug: str) -> Donor:
    meta = json.loads((Path(root) / slug / "meta.json").read_text(encoding="utf-8"))
    rig = meta.get("rig") or {}
    return load_donor(slug, Path(root) / slug / meta["model"], rig.get("roles"), meta.get("name", slug),
                      rig.get("scale"), (meta.get("source") or {}).get("game_title", ""))


def jmap_of(v: V.Vmg) -> dict[str, int]:
    idx = {b.name: b.index for b in v.bones}
    return {r: idx[n] for r, n in S.ROLE_BONES.items() if n in idx and r in (
        "hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
        "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")}


def target_of(v: V.Vmg) -> dict:
    """The retarget target (sm64_swap frame: left +X, up +Y, front +Z, metres) of a costume's skeleton."""
    root = V.model_root(v)
    W = V.bind_world(v, root)
    jm = jmap_of(v)
    missing = {"hip", "head", "l_hand", "r_hand", "l_foot", "r_foot"} - jm.keys()
    if missing:
        raise ValueError(f"the skeleton has no {', '.join(sorted(missing))} bones")
    prims, _W, _n = V.decode(v)
    allp = np.concatenate([p["pos"] for p in prims if not p.get("weapon")])
    head = [p["pos"][p["J"][np.arange(len(p["J"])), p["W"].argmax(1)] == jm["head"]] for p in prims]
    head = np.concatenate([h for h in head if len(h)]) if any(len(h) for h in head) else allp[:1]
    return {"T": W[:, :3, 3].copy(), "parent": [b.parent for b in v.bones], "ground": float(allp[:, 1].min()),
            "head_h": float(np.ptp(head[:, 1])) if len(head) > 1 else 0.22, "joints": len(v.bones),
            "height": float(allp[:, 1].max() - allp[:, 1].min()), "root": root, "jmap": jm}


def corners(prims: list[dict], layout: dict) -> dict:
    """Retargeted prims -> one welded mesh {P, N, UV (atlas), B, F}; every corner gets its atlas UV."""
    from .auf_swap import _material_key, atlas_uvs
    P, N, UV, B, F = [], [], [], [], []
    index: dict = {}
    for p in prims:
        k = _material_key(p)
        page, tile, size = layout.get(k, (0, (0, 0, 1, 1), (1, 1)))
        for tri in np.asarray(p["tris"], int).reshape(-1, 3):
            uv3 = atlas_uvs(p["uv"][tri], tile, size)
            face = []
            for c, vi in enumerate(tri):
                key = (tuple(np.round(p["pos"][vi], 5)), tuple(np.round(uv3[c], 4)), int(p["J"][vi, 0]))
                i = index.get(key)
                if i is None:
                    i = index[key] = len(P)
                    P.append(p["pos"][vi])
                    N.append(p["nrm"][vi])
                    UV.append(uv3[c])
                    B.append(int(p["J"][vi, 0]))
                face.append(i)
            if len(set(face)) == 3:
                F.append(face)
    return {"P": np.array(P, float).reshape(-1, 3), "N": np.array(N, float).reshape(-1, 3),
            "UV": np.array(UV, float).reshape(-1, 2), "B": np.array(B, int), "F": np.array(F, int).reshape(-1, 3)}


def second_colour(atlas: np.ndarray) -> np.ndarray:
    """The 2P image: the same atlas, 15 % darker and a little cooler (both players on one costume stay apart)."""
    a = atlas.astype(float)
    a[..., :3] *= np.array([0.80, 0.85, 0.95])
    return np.clip(a, 0, 255).astype(np.uint8)


def ground_feet(prims: list[dict], tgt: dict) -> dict:
    """Shrink each foot about its ankle bone until its sole stands on the fighter's ground (chibi donors' shoes are
    taller than an SC2 ankle: Sonic's would sink 0.3 m into the floor and overlap). -> {role: factor applied}."""
    out = {}
    T, jm, ground = tgt["T"], tgt["jmap"], tgt["ground"]
    for role in ("l_foot", "r_foot"):
        j = jm.get(role)
        if j is None:
            continue
        ankle = T[j]
        lows = [p["pos"][p["J"][:, 0] == j][:, 1].min() for p in prims if (p["J"][:, 0] == j).any()]
        if not lows:
            continue
        low = float(min(lows))
        if low >= ground - 0.01 or ankle[1] - low < 1e-6:
            continue
        k = float(np.clip((ankle[1] - ground) / (ankle[1] - low), 0.5, 1.0))
        for p in prims:
            m = p["J"][:, 0] == j
            if m.any():
                p["pos"] = p["pos"].copy()
                p["pos"][m] = (p["pos"][m] - ankle) * k + ankle
        out[role] = round(k, 3)
    return out


@dataclass
class Fit:
    key: str
    costume: int
    data: bytes
    report: dict
    mesh: dict
    atlas: np.ndarray


def fit_costume(donor: Donor, v: V.Vmg, key: str, costume: int, budget: int, progress=None) -> Fit:
    """One donor on one costume: retarget, atlas, decimate + encode within `budget` bytes."""
    from . import fit_events as FE
    from .auf_swap import build_pages, decimate, donor_materials
    from .sm64_swap import retarget
    tgt = target_of(v)
    prims, rep = retarget(donor.rig, tgt, donor.scale, tgt["jmap"])
    rep["feet_scaled"] = ground_feet(prims, tgt)
    names = {b.index: b.name for b in v.bones}
    FE.weights(prims, tgt["jmap"], "rigid per bone (one VMG bone per vertex, CPU skin record weight 1)",
               len(v.bones), names=names)
    side = ATLAS[0]
    while side > 32 and 2 * side * side // 2 > 0.4 * budget:   # 1P + 2P CMPR images take at most 40 % of the room
        side //= 2
    pages, layout = build_pages(donor_materials(prims), [(side, side)])
    atlas = pages[0]
    mesh = corners(prims, layout)
    F0 = mesh["F"]
    target = min(len(F0), MAX_TRIS)
    last = None
    for attempt in range(12):
        Pd, F = decimate(mesh["P"], F0, target) if target < len(F0) else (mesh["P"], F0)
        used = np.unique(F.reshape(-1))
        remap = np.full(len(Pd), -1)
        remap[used] = np.arange(len(used))
        if len(used) > 0xFFFF:
            target = int(target * SHRINK)
            continue
        data = V.encode(v, Pd[used], mesh["N"][used], mesh["UV"][used], mesh["B"][used], remap[F], atlas,
                        second_colour(atlas), tgt["root"])
        last = (data, {"triangles": int(len(F)), "vertices": int(len(used)), "bytes": len(data), "budget": budget,
                       "attempts": attempt + 1, "from_triangles": int(len(F0))})
        if len(data) <= budget:
            break
        target = max(64, int(target * min(SHRINK, budget / len(data))))
        if progress:
            progress(None, f"{len(data)} bytes over the {budget}-byte budget: {target} triangles")
    if last is None or len(last[0]) > budget:
        raise ValueError(f"{donor.name} does not fit {key} costume {costume + 1}'s {budget} bytes")
    data, r = last
    FE.stage("decimate", data={"from": r["from_triangles"], "to": r["triangles"], "budget": f"{budget} bytes "
                               "(the costume's VMG)", "attempts": r["attempts"]},
             prims=[{"pos": mesh["P"], "tris": F0}])
    FE.stage("encode", data={"bytes": r["bytes"], "budget": budget, "vertices": r["vertices"], "bones": len(v.bones),
                             "atlas": f"{side}x{side} CMPR (1P + 2P)", "where": "package child 0"})
    rep = {k: v_ for k, v_ in rep.items() if k in ("scale", "torso_up", "torso_down", "shoulder_widen", "head_scale",
                                                  "limb_stretch", "normals_flipped", "profile", "feet_scaled")}
    return Fit(key, costume, data, rep | r | {"target_height_m": round(tgt["height"], 3)}, mesh, atlas)


def replace_child0(pkg: bytes, vmg: bytes) -> bytes:
    """A costume package with its VMG replaced in place (same child offsets, same package size; zero padding)."""
    kids = S.package(pkg)
    if not kids or not kids[0][1]:
        raise ValueError("not a costume package")
    o, s = kids[0]
    if len(vmg) > s:
        raise ValueError(f"the new model ({len(vmg)} bytes) is larger than the costume's {s}")
    out = bytearray(pkg)
    out[o:o + s] = vmg + bytes(s - len(vmg))
    return bytes(out)


# ------------------------------------------------------------------------------------------------ plans

def plan_pairs(pairs: list[tuple[str, str]], table: dict | None = None, seed: str = "") -> dict[tuple[str, int], str]:
    """{(fighter, costume): donor slug} from [(slot, donor)]: named slots first (a costume beats a fighter), donors
    without a slot are dealt over the remaining fighters in roster order (seeded rotation)."""
    plan: dict[tuple[str, int], str] = {}
    named = [(t, d) for t, d in pairs if t and t.lower() not in ("all", "cast", "roster", "everyone")]
    free = [d for t, d in pairs if (not t or t.lower() in ("all", "cast", "roster", "everyone")) and d]
    for t, d in sorted(named, key=lambda p: p[0].count(":")):
        for kc in keys_for(t, table):
            plan[kc] = d
    rest = [f[1] for f in S.FIGHTERS if not any(k == f[1] for k, _c in plan)]
    if free and rest:
        r = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(free) if seed else 0
        free = free[r:] + free[:r]
        for i, k in enumerate(rest):
            for kc in keys_for(slot_name(k), table):
                plan[kc] = free[i % len(free)]
    return plan


def plan_random(pools: list[list[str]], table: dict | None = None, seed: str = "sc2") -> dict[tuple[str, int], str]:
    """The mixed build: every fighter's costumes alternate between the pools (fighter i starts with pool i % len),
    so the random select patch shows each fighter from either franchise; donors are dealt round robin per pool
    (shuffled by `seed`), no donor repeating in a pool before every one of its donors is used."""
    pools = [list(p) for p in pools if p]
    if not pools:
        raise ValueError("no donor pool")
    rng = random.Random(seed)
    queues = []
    for p in pools:
        q = list(p)
        rng.shuffle(q)
        queues.append([q, 0])
    counts = {k: v["costumes"] for k, v in table.items()} if table else {k: v[1] for k, v in S.EXPECTED.items()}
    plan = {}
    for i, (_fid, key, _n, _a) in enumerate(S.FIGHTERS):
        used = set()
        for c in range(counts.get(key, 0)):
            q = queues[(i + c) % len(queues)]
            for _try in range(len(q[0])):
                slug = q[0][q[1] % len(q[0])]
                q[1] += 1
                if slug not in used or len(q[0]) == 1:
                    break
            used.add(slug)
            plan[(key, c)] = slug
    return plan


def plan_digest(plan: dict) -> str:
    return hashlib.sha256(json.dumps(sorted([f"{k}:{c}", d if isinstance(d, str) else d.slug]
                                            for (k, c), d in plan.items())).encode()).hexdigest()[:8]


def mod_name(slot: str, plan: dict) -> str:
    s = (slot or "all").strip().lower()
    tag = re.sub(r"[^a-z0-9]+", "_", s.removeprefix("fighter:")).strip("_") or "all"
    return f"sc2_{tag}_{plan_digest(plan)}"


# ------------------------------------------------------------------------------------------------ the disc

def random_patch_site(dol: bytes) -> int:
    """main.dol file offset of the body load's costume pick (0x800a213c); raises when the bytes are not stock / patched."""
    o = S.dol_offset(dol, S.COSTUME_LOAD)
    have = dol[o:o + len(RANDOM_STOCK)]
    if have not in (RANDOM_STOCK, RANDOM_PATCH):
        raise ValueError(f"main.dol at {S.COSTUME_LOAD:#x} is not the expected body load ({have.hex()})")
    return o


def random_patched(disc: S.Disc) -> bool:
    o = random_patch_site(disc.dol)
    return disc.dol[o:o + len(RANDOM_PATCH)] == RANDOM_PATCH


def _copy_image(src: Path, dst: Path, progress=None):
    from . import filemods
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")
    if src.suffix.lower() == ".gcz":
        filemods.gcz_to_iso(src, part, progress)
    else:
        shutil.copyfile(src, part)
    part.replace(dst)


def build_image(image: Path, out_dir: Path, plan: dict[tuple[str, int], Donor], random_select: bool = False,
                progress=None, image_name: str | None = None) -> dict:
    """The disc image with every planned costume (normal + Extra copies) rewritten in place, optionally the random
    costume select; read back. -> report {image, slots: {"key:costume": {...}}, entries, random_select}."""
    from . import fit_events as FE
    progress = progress or (lambda p, m: None)
    image, out_dir = Path(image), Path(out_dir)
    writes: dict[int, bytes] = {}
    slots: dict[str, dict] = {}
    with S.Disc(image) as d:
        table = S.fighter_table(d.dol)
        dol_off = random_patch_site(d.dol)
        FE.plan([(f"{k}:{c + 1}", dn.slug, f"{dn.name} -> {table[k]['name']} costume {c + 1}")
                 for (k, c), dn in plan.items()])
        for i, ((key, c), donor) in enumerate(sorted(plan.items())):
            sk = f"{key}:{c + 1}"
            progress(5 + 70 * i / max(1, len(plan)), f"Fitting {donor.name} as {table[key]['name']} costume {c + 1}")
            FE.model(sk, f"{donor.name} -> {table[key]['name']} costume {c + 1}", donor.slug)
            try:
                if c >= table[key]["costumes"]:
                    raise ValueError(f"{table[key]['name']} has {table[key]['costumes']} costumes")
                ents = table[key]["entries"][c]
                pkgs = {e: d.entry(e) for e in ents}
                first = pkgs[ents[0]]
                kids = S.package(first)
                tv = V.parse(first[kids[0][0]:kids[0][0] + kids[0][1]])
                budget = min(S.package(p)[0][1] for p in pkgs.values())
                f = fit_costume(donor, tv, key, c, budget, progress)
                for e, p in pkgs.items():
                    writes[e] = replace_child0(p, f.data)
                slots[sk] = {"status": "built", "donor": donor.slug, "donor_name": donor.name, "entries": ents,
                             "fit": f.report, "sha256": hashlib.sha256(f.data).hexdigest()}
                FE.stage("write", data={"entries": ents, "bytes": len(f.data), "budget": budget,
                                        "where": "human.olk, in place"})
            except Exception as e:                       # noqa: BLE001 - a slot that cannot be fitted fails alone
                if type(e).__name__ == "Cancelled":
                    raise
                slots[sk] = {"status": "failed", "donor": donor.slug, "reason": f"{type(e).__name__}: {e}"[:400]}
                FE.stage("encode", "failed", {"reason": str(e)[:150]})
        human = list(d.human)
        dol_disc = d.dol_offset + dol_off
    if not writes:
        raise ValueError("no costume was built: " + "; ".join(f"{k}: {v.get('reason')}" for k, v in slots.items()))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_img = out_dir / (image_name or (image.stem + ".iso"))
    progress(78, f"Writing {out_img.name}")
    _copy_image(image, out_img, lambda p, m: progress(78 + p * 0.1, m))
    with open(out_img, "r+b") as f:
        for e, data in writes.items():
            off, size = human[e]
            if len(data) != size:
                raise AssertionError(f"human.olk entry {e} changed size")
            f.seek(off)
            f.write(data)
        if random_select:
            f.seek(dol_disc)
            f.write(RANDOM_PATCH)
    progress(92, "Reading the image back")
    check = verify_image(out_img, {e: hashlib.sha256(b).hexdigest() for e, b in writes.items()}, random_select)
    return {"image": str(out_img), "slots": slots, "entries": sorted(writes), "random_select": random_select,
            "verify": check}


def verify_image(image: Path, expected: dict[int, str] | None = None, random_select: bool | None = None) -> dict:
    """Read an image back: every expected package hashes as written and its VMG parses and decodes (triangles,
    bones, the 18 roles); the random-select patch is present / absent as asked."""
    out = {"entries": {}, "ok": True}
    with S.Disc(image) as d:
        if random_select is not None:
            out["random_select"] = random_patched(d)
            out["ok"] &= out["random_select"] == random_select
        for e, sha in sorted((expected or {}).items()):
            pkg = d.entry(e)
            row = {"sha_ok": hashlib.sha256(pkg).hexdigest() == sha}
            try:
                kids = S.package(pkg)
                v = V.parse(pkg[kids[0][0]:kids[0][0] + kids[0][1]])
                prims, _W, _n = V.decode(v)
                row |= {"triangles": int(sum(len(p["tris"]) for p in prims)), "bones": len(v.bones),
                        "roles": len(S.roles_of(v)), "textures": V.stats(v)["textures"]}
                row["engine"] = V.engine_check(v)
                row["ok"] = row["sha_ok"] and row["triangles"] > 0 and row["roles"] == 18 and not row["engine"]
            except Exception as err:                     # noqa: BLE001
                row |= {"ok": False, "error": f"{type(err).__name__}: {err}"}
            out["entries"][e] = row
            out["ok"] &= row["ok"]
    return out


def random_desc(plan: dict) -> str:
    """The random build's description, naming the Mario side it was built from (SM64 DS, or the HD group)."""
    from .cast_swap import mario_side
    slugs = {d if isinstance(d, str) else d.slug for d in plan.values()}
    mario = mario_side(s for s in slugs if not s.startswith("sa2_") and s != "sonic")[1]
    return f"Soul Calibur II: Sonic Adventure 2 vs {mario}, a random costume per selection"


def write_marker(out_dir: Path, game_id: str, name: str, image: str, report: dict, plan: dict, desc: str,
                 pools: dict | None = None) -> dict:
    rec = {"name": name, "game_id": game_id, "image": image, "files": ["root.olk", "main.dol"] if
           report.get("random_select") else ["root.olk"], "built": time.time(), "writer": WRITER,
           "cast": sorted([f"{k}:{c + 1}", d if isinstance(d, str) else d.slug] for (k, c), d in plan.items()),
           "cast_names": {f[1]: f[2] for f in S.FIGHTERS},
           "random_select": bool(report.get("random_select")),
           "report": {"slots": {k: {x: y for x, y in v.items() if x != "fit"} | {"fit": {
               x: y for x, y in (v.get("fit") or {}).items() if x in ("triangles", "vertices", "bytes", "budget",
                                                                      "scale")}} for k, v in report["slots"].items()},
                      "entries": report["entries"], "verify_ok": report["verify"]["ok"]},
           "verified_in_game": False, "desc": desc}
    if pools:
        rec["pools"] = pools
    try:
        from . import build_record
        rec = build_record.stamp(rec, kind="romhack" if report.get("random_select") else "file",
                                 file_changes=[build_record.file_change("root.olk", "patched", None, None, None,
                                                                         f"{len(report['entries'])} costume packages "
                                                                         "rewritten in human.olk")])
    except Exception:                                     # noqa: BLE001 - the marker is still valid without it
        pass
    (Path(out_dir) / ".gbox-mod.json").write_text(json.dumps(rec, default=str))
    return rec


# ------------------------------------------------------------------------------------------------ tool entry points

def _image(ctx, game) -> Path:
    from . import characters as C
    return C._gc_iso(ctx, game)


def _pairs(meta: dict, inp) -> list[tuple[str, str]]:
    out = [(str(p.get("target") or p.get("slot") or ""), str(p.get("donor") or p.get("character") or ""))
           for p in getattr(inp, "pairs", None) or []]
    return out or [("", meta["slug"])]


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Soul Calibur II (GC): slot fighter:<key>[:<costume>] | all | cast (+pairs) | random
    (pairs give the donors; two sources alternate per costume, plus the random costume select). Built where the
    collection is (the control plane); launched only when `launch` is passed."""
    from . import characters as C, filemods
    s = (inp.slot or "").strip().lower()
    if not is_slot(s):
        s = slot_name(S.fighter(s or "mitsurugi")[1]) if s else "all"
    if s == "random":
        groups: dict[str, list[str]] = {}
        for _t, slug in _pairs(meta, inp):
            m = C.get(C.library_root(ctx.config), slug) if slug != meta["slug"] else meta
            groups.setdefault((m.get("source") or {}).get("game_title", "?"), []).append(slug)
        plan = plan_random(list(groups.values()), seed=getattr(inp, "title", "") or "sc2")
        name = RANDOM_MOD
    elif s in ("all", "cast", "roster", "everyone"):
        plan = plan_pairs(_pairs(meta, inp), seed=getattr(inp, "title", "") or "")
        name = mod_name(s, plan)
    else:
        plan = {kc: meta["slug"] for kc in keys_for(s)}
        name = mod_name(s, plan)
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, game["game_id"])}
    built = None
    if inp.rebuild or not have:
        root = C.library_root(ctx.config)
        donors = {slug: donor_from_library(root, slug) for slug in sorted(set(plan.values()))}
        iso = _image(ctx, game)
        out = filemods.mod_dir(ctx.config, game["game_id"], name)
        tmp = out.with_name(out.name + ".building")
        shutil.rmtree(tmp, ignore_errors=True)
        rep = build_image(iso, tmp, {k: donors[d] for k, d in plan.items()}, random_select=(s == "random"),
                          progress=ctx.progress)
        if not rep["verify"]["ok"]:
            raise ValueError(f"the rebuilt image did not read back: {rep['verify']}")
        write_marker(tmp, game["game_id"], name, Path(rep["image"]).name, rep, plan,
                     f"Soul Calibur II: {s} ({len(rep['entries'])} costume packages)")
        shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)
        built = {"slots": rep["slots"], "entries": len(rep["entries"]), "random_select": rep["random_select"]}
        for slug in donors:
            try:
                C._api(ctx, "POST", f"/api/characters/{slug}/targets",
                       json={"game_id": game["game_id"], "slot": s, "mod": name, "nodes": [C.HOST_OS],
                             "notes": "Soul Calibur II " + ", ".join(f"{k} {c + 1}" for (k, c), dd in plan.items()
                                                                    if dd == slug)[:300]
                                      + "; native skeleton, motions and weapon kept; gameplay verification required"})
            except Exception:                            # noqa: BLE001 - bookkeeping never fails a build
                pass
    res = {"mod": name, "slot": s, "build": built, "status": "built_unverified" if built else "ready",
           "replaces": sorted({S.fighter(k)[2] for k, _c in plan}), "gameplay_verified": False,
           "replacement_kind": "native_disc"}
    if getattr(inp, "launch", False):
        sess = C._session(ctx, inp.session_id) if inp.session_id else None
        node = sess["session_id"].split("-")[0] if sess else "idle"
        res["launch"] = C._launch(ctx, game["game_id"], name, node)
    return res


def build_cast(cfg, game: dict, pairs, name: str, progress=None) -> dict:
    """cast_swap's pairs path: [(slot, meta)] -> one disc image. -> {mod, slots: {slot: {status, reason?}}}."""
    from . import characters as C, filemods
    root = C.library_root(cfg)
    plan, donors, per = {}, {}, {}
    for slot, meta in pairs:
        try:
            if meta["slug"] not in donors:
                donors[meta["slug"]] = donor_from_library(root, meta["slug"])
            for kc in keys_for(slot):
                plan[kc] = donors[meta["slug"]]
        except Exception as e:                            # noqa: BLE001
            per[slot] = {"status": "failed", "reason": str(e)[:400]}
    if not plan:
        return {"mod": None, "slots": per}
    from .models import CatalogEntry
    from .tools import rom_path
    image = rom_path(CatalogEntry.model_validate(game), cfg)
    out = filemods.mod_dir(cfg, game["game_id"], name)
    tmp = out.with_name(out.name + ".building")
    try:
        rep = build_image(image, tmp, plan, progress=progress)
        write_marker(tmp, game["game_id"], name, Path(rep["image"]).name, rep, plan, f"Soul Calibur II cast {name}")
        shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)
    except Exception as e:                                # noqa: BLE001
        return {"mod": None, "slots": per | {s: {"status": "failed", "reason": str(e)[:400]} for s, _m in pairs
                                             if s not in per}}
    for slot, _m in pairs:
        if slot in per:
            continue
        st = [rep["slots"].get(f"{k}:{c + 1}", {}) for k, c in keys_for(slot)]
        ok = [x for x in st if x.get("status") == "built"]
        per[slot] = {"status": "built"} if ok and len(ok) == len(st) else \
            {"status": "partial" if ok else "failed",
             "reason": "; ".join(f"{x.get('reason')}" for x in st if x.get("status") != "built")[:400]}
    return {"mod": name, "slots": per}


# ------------------------------------------------------------------------------------------------ CLI

def pool_slugs(root: Path, pool: str) -> list[str]:
    """Humanoid donors of a pool in a library folder: sa2 = the Sonic Adventure 2 entries, sm64ds = the Super Mario
    64 DS ones, mario = gbox.cast_swap's 'mario' group (the best model per character: HD > SM64 > SM64 DS), all only
    when replacement readiness (or the roles) allow a full-body fit."""
    if pool == "mario":
        from . import cast_swap
        metas = {m["slug"]: m for m in cast_swap.library_metas(Path(root)) if m.get("slug")}
        need = {"hip", "head", "l_hand", "r_hand", "l_foot", "r_foot"}
        return sorted(s for s in cast_swap.group_best(list(metas.values()), "mario").values()
                      if need <= ((metas[s].get("rig") or {}).get("roles") or {}).keys())
    title = POOLS.get(pool, pool)
    out = []
    for m in sorted(Path(root).glob("*/meta.json")):
        try:
            meta = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src = re.sub(r"\s*\([^)]*\)", "", (meta.get("source") or {}).get("game_title", "")).strip().lower()
        if src != title.lower():
            continue
        roles = (meta.get("rig") or {}).get("roles") or {}
        rd = (meta.get("readiness") or {}).get("status")
        if rd in ("blocked", "limited") or not {"hip", "head", "l_hand", "r_hand", "l_foot", "r_foot"} <= roles.keys():
            continue
        out.append(meta["slug"])
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Soul Calibur II (GC) fighter writer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("random")
    r.add_argument("image")
    r.add_argument("library")
    r.add_argument("out")
    r.add_argument("--pool", action="append", required=True,
                   help="sa2 | sm64ds | mario (best per character: HD > SM64 > DS) | a source game title")
    r.add_argument("--seed", default="sc2")
    r.add_argument("--name", default=RANDOM_MOD)
    r.add_argument("--game-id", default="201629ad498aba7b")
    r.add_argument("--image-name")
    b = sub.add_parser("build")
    b.add_argument("image")
    b.add_argument("library")
    b.add_argument("out")
    b.add_argument("--pair", action="append", required=True, help="slot=donor slug")
    b.add_argument("--random-select", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("image")
    a = ap.parse_args(argv)

    def prog(p, m):
        print(f"[{'--' if p is None else int(p):>3}] {m}", flush=True)
    if a.cmd == "verify":
        with S.Disc(a.image) as d:
            print(json.dumps({"random_select": random_patched(d)}))
        return 0
    if a.cmd == "random":
        pools = {p: pool_slugs(Path(a.library), p) for p in a.pool}
        plan = plan_random(list(pools.values()), seed=a.seed)
        rs = True
        name = a.name
    else:
        plan = plan_pairs([tuple(x.split("=", 1)) for x in a.pair])
        rs = a.random_select
        name = mod_name("all", plan)
        pools = None
    donors = {s: donor_from_library(Path(a.library), s) for s in sorted(set(plan.values()))}
    rep = build_image(Path(a.image), Path(a.out), {k: donors[s] for k, s in plan.items()}, rs, prog,
                      getattr(a, "image_name", None))
    rec = write_marker(Path(a.out), getattr(a, "game_id", "201629ad498aba7b"), name, Path(rep["image"]).name, rep,
                       plan, random_desc(plan) if a.cmd == "random" else f"Soul Calibur II {name}", pools)
    print(json.dumps({"image": rep["image"], "verify_ok": rep["verify"]["ok"], "random_select": rs,
                      "slots": {k: (v["status"], v.get("donor"), v.get("reason")) for k, v in rep["slots"].items()},
                      "marker": rec["name"]}, indent=1))
    return 0 if rep["verify"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
