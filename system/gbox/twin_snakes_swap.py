"""Metal Gear Solid: The Twin Snakes (GameCube, GGSEA4): any collection character as Snake, the Genome soldiers or the
other cast members, written into a rebuilt disc image (a mod; the source image is never touched).

How a slot is replaced (formats: docs/twin_snakes.md, gbox.ts_stage / ts_kms / ts_tex):
  1. the slot's model (`snake_def`, `out_cold`, ...) and its low-detail twin (`55ab65` for Snake, `<name>_sh` for the
     soldiers) are read from the first gameplay stage that has them;
  2. the donor goes through the shared rigid retarget (gbox.sm64_swap.retarget, body roles onto the MGS2 21-bone
     skeleton; the operator's Retarget editor profile applies), fit events per slot (scale / retarget / proportion /
     weights / decimate / encode / write) for the Fitting pop-up;
  3. the donor's textures are packed into ONE atlas the size of the model's main colour texture, written over that
     image in its own format (the texture set keeps its size and layout); the bump and specular images of the same
     layer are flattened (constant) so the donor is not lit with the old character's relief;
  4. the model is re-encoded on the same skeleton (gbox.ts_kms.encode: header, bones and mesh records kept, one part
     per bone mesh, single-bone envelopes) within the stock model's byte size, decimating (quadric edge collapse) until
     it fits; gear meshes past the bones draw nothing;
  5. in every stage that holds the model, including in-engine cutscenes (`demo*`, `r_demo*`, `r_dmo*`),
     the model, its twin and the texture set are replaced; other models that draw with the overwritten
     images (Snake's bandana tails) are hidden; the stage is recompressed (zlib 9) and must fit its sector span;
  6. stage.dat is rewritten in place (same size) in a copy of the disc image (gbox.filemods.build_image).

Slots: player | model:<key> (any CAST key, e.g. model:out_cold, model:hev_grd, model:psy_def) | enemies (= soldiers:
every Genome soldier model) | bosses | npcs | all | cast (pairs [{target, donor}], the rest dealt in order).

Live: `use(..., launch=true, session_id=...)` launches the mod through the server's session swap (save state ->
mod on the same worker -> load state), so the moment is kept; the stage's models are in RAM, so the new body shows
from the next area load (go through a door, or Continue). `live_apply` (tool twin_snakes_live) writes the encoded
body straight into the running game's loaded model (paused, verified, rolled back on any mismatch).

  python -m gbox.twin_snakes_swap build <disc.iso> <character dir> <out dir> [--slot player] [--stage r_sna]
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import twin_snakes as TS
from . import ts_kms as K
from . import ts_stage as S
from . import ts_tex as T

GAME_IDS = TS.GAME_IDS
WRITER = "gbox.twin_snakes_swap"
LIVE_FILE = "tts-live.json"                               # the mod's live write (twin_snakes_live apply items)
BUDGET_TRIES = 6
SHRINK = 0.85

# slot targets: the model and the low-detail twins drawn for the same character in gameplay
TWINS = {"snake_def": ["#55ab65"], "out_cold": ["out_cold_sh"], "out_cold2": ["out_cold2_sh"],
         "in_door": ["in_door_sh"], "in_gus": ["in_gus_sh"], "hev_grd": ["hev_grd_sh"], "mrl_dis_def": ["mrl_dis_sh"]}
GROUPS = {"enemies": ("enemy",), "soldiers": ("enemy",), "bosses": ("boss",), "npcs": ("npc",),
          "all": ("player", "enemy", "boss", "npc")}
SLOT_HELP = ("player | model:<key> (" + ", ".join(c["key"] for c in TS.CAST) + ") | enemies | soldiers | bosses | "
             "npcs | all | cast")
CUTSCENE = re.compile(r"^(demo|r_demo|r_dmo|r_dmT|r_brif|r_open|ending|n_title|r_title|init|disk)")
# The pick whip / chat words for the soldiers and Snake
SOLDIER_WORDS = re.compile(r"soldier|guard|genome|enemy|grunt|trooper|parka|gas ?mask|hood", re.I)
SNAKE_WORDS = re.compile(r"\bsnake\b|player|\bme\b|myself|sneaking suit|bandana", re.I)


# --------------------------------------------------------------------------------------------- slots

def is_slot(slot: str) -> bool:
    s = (slot or "player").strip().lower()
    return s in ("player", "cast", "roster", "everyone") or s in GROUPS or s.startswith("model:") or \
        any(s == c["key"] for c in TS.CAST)


def keys_for(slot: str) -> list[str]:
    """The CAST keys a slot replaces."""
    s = (slot or "player").strip().lower()
    if s == "player":
        return ["snake_def"]
    if s in GROUPS:
        return [c["key"] for c in TS.CAST if c["role"] in GROUPS[s]]
    k = s.split(":", 1)[1] if s.startswith("model:") else s
    for c in TS.CAST:
        if c["key"].lower() == k or TS.slug_of(c["key"]) == k:
            return [c["key"]]
    raise ValueError(f"unknown Twin Snakes slot {slot!r} ({SLOT_HELP})")


def slot_for_model(model) -> str | None:
    """Pick-whip link: a model (strcode int, '0x26e012' / '#26e012', or a name, twins like 'out_cold_sh' too) ->
    the slot that replaces it."""
    if isinstance(model, str):
        m = model.strip().lower()
        h = int(m[1:], 16) if m.startswith("#") else int(m, 16) if m.startswith("0x") else S.strcode(m)
    else:
        h = int(model) & 0xFFFFFF
    for c in TS.CAST:
        keys = [c["key"]] + TWINS.get(c["key"], [])
        if any(TS.model_hash(k) == h for k in keys):
            return TS.slot_for_key(c["key"])
    return None


def cast_slots() -> list[dict]:
    """The cast menu (`characters op=collect` "slots", gbox.char_coverage.cast_slots): the groups, then every model."""
    out = [{"slot": "player", "name": "Solid Snake (gameplay body + low-detail twin)", "kind": "player",
            "writer": WRITER, "size": 1.0}]
    for g, text in (("enemies", "every Genome soldier model (arctic, hood, indoor, gas mask, heavy guard)"),
                    ("bosses", "the bosses (Ocelot, Mantis, Wolf, Raven, Liquid, Ninja)"),
                    ("npcs", "Meryl, Otacon, Johnny"), ("all", "everyone"),
                    ("cast", "pairs [{target, donor}], the rest dealt in order")):
        out.append({"slot": g, "name": text, "kind": "group", "aggregate": True, "writer": WRITER,
                    "models": len(keys_for(g)) if g != "cast" else len(TS.CAST)})
    for c in TS.CAST:
        if c["key"] == "snake_def":
            continue
        out.append({"slot": TS.slot_for_key(c["key"]), "name": c["name"], "kind": c["role"], "writer": WRITER,
                    "aliases": c["aliases"], "discs": sorted(c["stage"])})
    return out


def plan_cast(pairs, seed: str = "") -> dict[str, str]:
    """{cast key: donor slug} from pairs [(target, donor)]: named targets first (a model beats a group), then donors
    without a target are dealt over the remaining keys in CAST order (seeded rotation)."""
    plan: dict[str, str] = {}
    named = [(t, d) for t, d in pairs if t]
    free = [d for t, d in pairs if not t and d]
    for t, d in sorted(named, key=lambda p: 0 if p[0].lower() in GROUPS else 1):
        for k in keys_for(t):
            plan[k] = d
    rest = [c["key"] for c in TS.CAST if c["key"] not in plan]
    if free and rest:
        r = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(free) if seed else 0
        free = free[r:] + free[:r]
        for i, k in enumerate(rest):
            plan[k] = free[i % len(free)]
    return plan


# --------------------------------------------------------------------------------------------- the fit

@dataclass
class Donor:
    slug: str
    name: str
    glb: Path
    roles: dict
    scale: dict | None = None
    rig: dict = None
    fits: dict = field(default_factory=dict)


def load_donor(slug: str, glb, roles: dict, name: str = "", scale: dict | None = None) -> Donor:
    from .sm64_swap import load_rig
    roles = dict(roles or {})
    if not {"hip", "head"} <= roles.keys():
        raise ValueError(f"{slug}: the collection entry has no hip/head body roles (rig.roles); not retargetable")
    d = Donor(slug, name or slug, Path(glb), roles, scale)
    d.rig = load_rig(Path(glb), roles)
    return d


def target_of(m: K.Kms) -> dict:
    """The retarget target (sm64_swap frame: left +X, up +Y, front +Z, the game's mm) of a 21-bone model."""
    if [b["parent"] for b in m.bones] != K.PARENTS:
        raise ValueError("not on the MGS2 21-bone skeleton")
    T_ = np.array([b["world"] for b in m.bones], float)
    prims = K.decode(m)
    allp = np.concatenate([p["pos"] for p in prims]) if prims else T_
    head = [p["pos"][(p["J"][np.arange(len(p["J"])), p["W"].argmax(1)] == K.ROLE_BONE["head"])] for p in prims]
    head = np.concatenate([h for h in head if len(h)]) if any(len(h) for h in head) else allp[:1]
    return {"T": T_, "parent": list(K.PARENTS), "ground": float(allp[:, 1].min()),
            "head_h": float(np.ptp(head[:, 1])) if len(head) > 1 else 200.0, "joints": len(m.bones),
            "height": float(allp[:, 1].max() - allp[:, 1].min())}


JMAP = {r: K.ROLE_BONE[r] for r in ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
                                    "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")}


def retarget(donor: Donor, m: K.Kms) -> tuple[list[dict], dict]:
    """The donor on the model's skeleton: prims in model space (mm), rigid per bone (J[:, 0])."""
    from .sm64_swap import retarget as rt
    tgt = target_of(m)
    prims, rep = rt(donor.rig, tgt, donor.scale, JMAP)
    return prims, rep | {"target_height_mm": round(tgt["height"], 1)}


def corners(prims: list[dict], layout: dict) -> dict:
    """Retargeted prims -> one welded corner mesh {P, N, UV (atlas), B, F}: every triangle corner gets its atlas UV
    (gbox.auf_swap.atlas_uvs), identical corners are shared."""
    from .auf_swap import _material_key, atlas_uvs
    P, N, UV, B, F = [], [], [], [], []
    index: dict = {}
    for p in prims:
        k = _material_key(p)
        page, tile, size = layout.get(k, (0, (0, 0, 1, 1), (1, 1)))
        for tri in np.asarray(p["tris"], int).reshape(-1, 3):
            uv3 = atlas_uvs(p["uv"][tri], tile, size)
            face = []
            for c, v in enumerate(tri):
                key = (tuple(np.round(p["pos"][v], 2)), tuple(np.round(uv3[c], 4)), int(p["J"][v, 0]))
                i = index.get(key)
                if i is None:
                    i = index[key] = len(P)
                    P.append(p["pos"][v])
                    N.append(p["nrm"][v])
                    UV.append(uv3[c])
                    B.append(int(p["J"][v, 0]))
                face.append(i)
            if len(set(face)) == 3:
                F.append(face)
    return {"P": np.array(P, float).reshape(-1, 3), "N": np.array(N, float).reshape(-1, 3),
            "UV": np.array(UV, float).reshape(-1, 2), "B": np.array(B, int), "F": np.array(F, int).reshape(-1, 3)}


def fit_to_budget(m: K.Kms, mesh: dict, budget: int, max_tris: int | None = None, progress=None) -> tuple[bytes, dict]:
    """Encode the corner mesh on the model within `budget` bytes, decimating (auf_swap.decimate) until it fits."""
    from .auf_swap import decimate
    F0 = mesh["F"]
    target = min(len(F0), max_tris or len(F0))
    last = None
    for attempt in range(12):
        P, F = decimate(mesh["P"], F0, target) if target < len(F0) else (mesh["P"], F0)
        data = K.encode(m, P, mesh["N"], mesh["UV"], mesh["B"], F)
        last = (data, {"triangles": int(len(F)), "bytes": len(data), "budget": budget, "attempts": attempt + 1,
                       "from_triangles": int(len(F0))})
        if len(data) <= budget:
            return last
        target = max(64, int(target * min(SHRINK, budget / len(data))))
        if progress:
            progress(None, f"{len(data)} bytes over the {budget}-byte budget: {target} triangles")
    raise ValueError(f"the donor does not fit the model's {budget} bytes even at {last[1]['triangles']} triangles")


def main_colour(m: K.Kms) -> tuple[int, ...] | None:
    """The texture layer (bump, colour, specular strcodes) of the bone meshes' first parts (the body atlas)."""
    from collections import Counter
    c = Counter(me.parts[0].tex for i, me in enumerate(m.meshes) if i < len(m.bones) and me.parts)
    return c.most_common(1)[0][0] if c else None


@dataclass
class Fit:
    key: str
    template: K.Kms
    data: bytes
    report: dict


def fit_model(donor: Donor, m: K.Kms, key: str, budget_scale: float = 1.0, atlas_size=None, progress=None) -> tuple[Fit, np.ndarray]:
    """One donor on one model: retarget, atlas, decimate + encode. -> (Fit, atlas RGBA (h, w, 4))."""
    from . import fit_events as FE
    from .auf_swap import build_pages, donor_materials
    prims, rep = retarget(donor, m)
    FE.weights(prims, JMAP, "rigid per bone (one MGS2 bone / envelope per vertex)", len(m.bones),
               names=K.BONE_NAMES)
    w, h = atlas_size or (256, 256)
    pages, layout = build_pages(donor_materials(prims), [(w, h)])
    mesh = corners(prims, layout)
    budget = int(len(m.data) * budget_scale)
    stock_tris = K.stats(m)["triangles"]
    data, r = fit_to_budget(m, mesh, budget, max_tris=int(stock_tris * 1.25), progress=progress)
    FE.stage("decimate", data={"from": r["from_triangles"], "to": r["triangles"], "stock": stock_tris,
                               "budget": f"{budget} bytes (the stock model's size)", "attempts": r["attempts"]},
             prims=[{"pos": mesh["P"] * K.MM, "tris": mesh["F"]}])
    FE.stage("encode", data={"bytes": r["bytes"], "budget": budget, "stock_bytes": len(m.data), "bones": len(m.bones),
                             "meshes": len(m.meshes), "atlas": f"{w}x{h}", "where": "in place of the stock model"})
    return Fit(key, m, data, rep | r), pages[0]


# --------------------------------------------------------------------------------------------- textures

def flatten(ts: T.TextureSet, img: T.Image, value: str = "mid") -> None:
    """An image made constant in place: C4 / C8 keep their palette and point every texel at one entry (mid grey for a
    bump map, the darkest for a specular mask); other formats are re-encoded flat."""
    n = T.image_size(img.fmt, img.w, img.h)
    o = ts.tpl + img.data_off
    if img.fmt in (8, 9) and img.pal_off:
        pal = T.palette(bytes(ts.data[ts.tpl + img.pal_off: ts.tpl + img.pal_off + 2 * img.pal_count]), img.pal_fmt)
        lum = (pal[:, :3].astype(float).mean(1) * (pal[:, 3] / 255.0))[:16 if img.fmt == 8 else 256]
        idx = int(np.argmin(lum)) if value == "dark" else int(np.argmin(np.abs(lum - 128)))
        b = (idx << 4 | idx) if img.fmt == 8 else idx
        ts.data[o:o + n] = bytes([b]) * n
        return
    rgba = np.zeros((img.h, img.w, 4), np.uint8)
    rgba[..., :3] = 0 if value == "dark" else 128
    rgba[..., 3] = 255
    ts.data[o:o + n] = T.encode(img.fmt, img.w, img.h, rgba)


SHARED_MAX = 8                                            # images this small are the engine's shared stand-ins


def paint_layer(sets: dict, layer: tuple, atlas: np.ndarray, own: int | None = None) -> tuple[dict, set]:
    """The donor atlas over the layer's colour image; bump and specular flattened. Only images of the model's own
    texture set (`own`) are touched, and never the tiny shared stand-ins (the 2x2 null texture 0x9576ef ...).
    sets: {set file hash: TextureSet}. -> ({set hash: True} changed, {texture strcodes changed})."""
    bump, colour, spec = (list(layer) + [0, 0, 0])[:3]
    if not colour or colour in (0, 1):
        colour, bump = bump, 0
    changed, touched = {}, set()
    for h, mode in ((colour, "atlas"), (bump, "mid"), (spec, "dark")):
        if not h or h in (0, 1) or (h == colour and mode != "atlas"):
            continue
        for sh, ts in sets.items():
            if own is not None and sh != own:
                continue
            img = ts.by_hash(h)
            if img is None or (img.w <= SHARED_MAX and img.h <= SHARED_MAX):
                continue
            if mode == "atlas":
                ts.replace_image(img, atlas)
            else:
                flatten(ts, img, mode)
            changed[sh] = True
            touched.add(h)
            break
    return changed, touched


def colour_size(sets: dict, layer: tuple) -> tuple[int, int] | None:
    c = layer[1] if layer[1] and layer[1] not in (0, 1) else layer[0]
    for ts in sets.values():
        img = ts.by_hash(c)
        if img is not None:
            return img.w, img.h
    return None


def part_textures(data: bytes) -> set[int]:
    """Every texture strcode a model's parts name (light walk: works for character and prop models)."""
    out = set()
    try:
        g = struct.unpack_from(">I", data, 0x5C)[0]
        nmesh, _np, _sub, recs = struct.unpack_from(">HHII", data, g + 8)
        for i in range(nmesh):
            mo = g + recs + 0x48 * i
            npart = struct.unpack_from(">H", data, mo + 0x38)[0]
            poff = struct.unpack_from(">I", data, mo + 0x44)[0]
            if not npart or g + poff + 0x24 * npart > len(data):
                continue
            for k in range(npart):
                out.update(x & 0xFFFFFF for x in struct.unpack_from(">3I", data, g + poff + 0x24 * k + 4))
    except struct.error:
        pass
    return out - {0, 1}


# --------------------------------------------------------------------------------------------- stages

def gameplay_stages(sd: S.StageDat, hashes: set[int], cutscenes: bool = True) -> list[int]:
    out = set()
    for h in hashes:
        out.update(sd.stages_with(h, S.MODEL))
    return sorted(i for i in out if cutscenes or not CUTSCENE.match(sd.entries[i][0]))


def swap_stage(st: S.Stage, models: dict[int, bytes], layers: list[tuple], atlases: list[np.ndarray],
               keep: set[int] = frozenset(), owners: list | None = None) -> tuple[dict, dict]:
    """New file contents for one stage: {(type, hash): bytes} for the swapped models, the texture sets with the
    donor atlas, and the hidden models (others drawing with the overwritten images). -> (new, report)."""
    new: dict = {}
    for h, data in models.items():
        if st.find(h, S.MODEL) is not None:
            new[(S.MODEL, h)] = data
    sets = {f.hash: T.TextureSet(f.data) for f in st.files() if f.type == S.TEXTURES}
    painted, used = {}, set()
    for i, (layer, atlas) in enumerate(zip(layers, atlases)):
        if layer is None:
            continue
        ch, touched = paint_layer(sets, layer, atlas, (owners or [None] * len(layers))[i])
        painted.update(ch)
        used.update(touched)
    for sh in painted:
        new[(S.TEXTURES, sh)] = bytes(sets[sh].data)
    hidden = []
    for f in st.files():
        if f.type != S.MODEL or f.hash in models or f.hash in keep:
            continue
        own_set = struct.unpack_from(">I", f.data, 0x0C)[0] & 0xFFFFFF if len(f.data) >= 0x10 else 0
        # drawn with an image the donor replaced, or an accessory of the replaced character (its own texture set:
        # Snake's bandana tails and items in sna_def)
        if part_textures(f.data) & used or (own_set and own_set in set(owners or ()) and own_set in painted):
            new[(S.MODEL, f.hash)] = K.hide(f.data)
            hidden.append(f"{f.hash:06x}")
    return new, {"stage": st.name, "models": sorted(f"{h:06x}" for (t, h) in new if t == S.MODEL and h in models),
                 "texture_sets": sorted(f"{h:06x}" for h in painted), "hidden": hidden}


# --------------------------------------------------------------------------------------------- the build

def _first_model(sd: S.StageDat, stages: list[int], h: int) -> K.Kms | None:
    for i in stages:
        st = sd.stage(i)
        f = st.find(h, S.MODEL)
        if f is not None:
            return K.parse(f.data)
    return None


def build_stage_dat(stage_dat: bytes, plan: dict[str, Donor], progress=None, cutscenes: bool = True) -> tuple[bytes, dict]:
    """stage.dat bytes + {cast key: Donor} -> (new stage.dat, report). Every gameplay or in-engine cutscene stage holding a planned model
    is rebuilt in its own sector span; the whole build shrinks the donors' byte budgets and retries when a stage
    would not fit."""
    from . import fit_events as FE
    progress = progress or (lambda p, m: None)
    sd = S.StageDat.from_bytes(stage_dat)
    slots: dict[str, dict] = {}
    for key, donor in plan.items():
        hs = {TS.model_hash(key)} | {TS.model_hash(t) for t in TWINS.get(key, [])}
        stages = gameplay_stages(sd, hs, cutscenes)
        if not stages:
            slots[key] = {"status": "failed", "reason": f"{key} has no model stage on this disc"}
            continue
        slots[key] = {"donor": donor, "stages": stages, "hashes": hs}
    scale, last_err = 1.0, None
    for attempt in range(BUDGET_TRIES):
        out = bytearray(stage_dat)
        reports, fits = [], {}
        for key, s in slots.items():
            if "donor" not in s:
                continue
            FE.model(TS.slot_for_key(key), f"{s['donor'].name} -> {TS.cast_entry(key)['name']}", s["donor"].slug)
            models, layers, atlases, rep, owners = {}, [], [], {}, []
            try:
                for i, mk in enumerate([key] + TWINS.get(key, [])):
                    h = TS.model_hash(mk)
                    m = _first_model(sd, s["stages"], h)
                    if m is None:
                        continue
                    layer = main_colour(m)
                    st0 = next(sd.stage(si) for si in s["stages"] if sd.stage(si).find(h, S.MODEL) is not None)
                    sets = {f.hash: T.TextureSet(f.data) for f in st0.files()
                            if f.type == S.TEXTURES and f.hash == m.tex_set}
                    size = colour_size(sets, layer) if layer else None
                    progress(None, f"Fitting {s['donor'].name} on {mk} (budget x{scale:.2f})")
                    fit, atlas = fit_model(s["donor"], m, mk, scale, size)
                    models[h] = fit.data
                    layers.append(layer)
                    atlases.append(atlas)
                    owners.append(m.tex_set)
                    rep[mk] = fit.report
                fits[key] = (models, layers, atlases, rep, owners)
            except Exception as e:                        # noqa: BLE001 - one slot's failure never stops the others
                s["error"] = str(e)[:400]
                FE.stage("encode", "failed", {"reason": str(e)[:150]})
        keep = set().union(*[set(f[0]) for f in fits.values()]) if fits else set()
        too_big = []
        for i in sorted({i for s in slots.values() for i in s.get("stages", [])}):
            models, layers, atlases, owners = {}, [], [], []
            for key, (ms, ls, as_, _r, ow) in fits.items():
                if i in slots[key]["stages"]:
                    models.update(ms)
                    layers += ls
                    atlases += as_
                    owners += ow
            if not models:
                continue
            st = sd.stage(i)
            new, rep = swap_stage(st, models, layers, atlases, keep, owners)
            try:
                blob = S.rebuild_stage(st, new)
            except S.StageTooBig as e:
                too_big.append(str(e))
                continue
            off, span = sd.span(i)
            out[off:off + span] = blob + bytes(span - len(blob))
            rep["bytes"] = len(blob)
            rep["span"] = span
            reports.append(rep)
            progress(None, f"Stage {st.name}: {', '.join(rep['models'])} replaced, {len(rep['hidden'])} hidden")
        if not too_big:
            for key, s in slots.items():
                if "donor" not in s:
                    continue
                if key in fits:
                    st_names = [sd.entries[i][0] for i in s["stages"]]
                    s.update(status="built", stages_written=st_names, fit=fits[key][3])
                    FE.model(TS.slot_for_key(key))
                    FE.stage("write", data={"stages": len(st_names), "first": st_names[0],
                                            "bytes": sum(len(b) for b in fits[key][0].values())})
                else:
                    s.update(status="failed", reason=s.get("error") or "fit failed")
            return bytes(out), {"stages": reports, "budget_scale": round(scale, 3), "attempts": attempt + 1,
                                "slots": {k: {x: y for x, y in v.items() if x in ("status", "reason", "stages_written",
                                                                                    "fit")} for k, v in slots.items()}}
        last_err = too_big
        scale *= SHRINK
        progress(None, f"{len(too_big)} stage(s) over their sector span; shrinking the budgets to x{scale:.2f}")
    raise S.StageTooBig("; ".join(last_err or ["stages do not fit"]))


def build_mod(cfg, game: dict, image: Path, name: str, plan: dict[str, Donor], progress=None,
              cutscenes: bool = True) -> dict:
    """A disc-image mod (cache/mods/<game>/<name>): stage.dat rebuilt (same size, in place), the rest copied."""
    import types
    from . import filemods
    from .gcdisc import GCDisc
    progress = progress or (lambda p, m: None)
    disc = GCDisc(str(image))
    try:
        if disc.game_id != TS.DISC_ID:
            raise ValueError(f"{Path(image).name}: expected {TS.DISC_ID}, got {disc.game_id}")
        stage_dat = disc.read(S.STAGE_DAT)
        disc_no = TS.disc_of(header=disc._r(0, 8))
    finally:
        disc.f.close()
    new, report = build_stage_dat(stage_dat, plan, progress, cutscenes)
    if not any(v.get("status") == "built" for v in report["slots"].values()):
        raise ValueError("no slot was built: " + "; ".join(f"{k}: {v.get('reason')}" for k, v in report["slots"].items()))
    if len(new) != len(stage_dat):
        raise AssertionError("stage.dat changed size")
    work = Path(cfg.cache) / "characters_build" / "twin_snakes" / name
    work.mkdir(parents=True, exist_ok=True)
    (work / "stage.dat").write_bytes(new)
    progress(90, "Writing the disc image")
    cfg_ = cfg if hasattr(cfg, "cache") else types.SimpleNamespace(cache=Path(cfg))
    b = filemods.build_image(cfg_, game["game_id"], Path(image), name, {S.STAGE_DAT: {"from": str(work / "stage.dat")}},
                             progress)
    disc = GCDisc(b["image"])
    try:
        if hashlib.sha256(disc.read(S.STAGE_DAT)).digest() != hashlib.sha256(new).digest():
            raise ValueError("the image does not hold the rebuilt stage.dat")
    finally:
        disc.f.close()
    (Path(b["dir"]) / LIVE_FILE).write_text(json.dumps(live_items(stage_dat, new, list(plan))))
    marker = Path(b["dir"]) / ".gbox-mod.json"
    rec = json.loads(marker.read_text())
    rec |= {"writer": WRITER, "disc": disc_no, "cast": sorted([k, d.slug] for k, d in plan.items()),
            "report": {"stages": [{k: v for k, v in r.items()} for r in report["stages"]],
                       "budget_scale": report["budget_scale"],
                       "slots": {k: {x: y for x, y in v.items() if x != "fit"} for k, v in report["slots"].items()}},
            "replacement_scope": {"requested": "all_character_appearances", "in_engine_cutscenes": "written_unverified" if cutscenes else "excluded",
                                  "cutscene_stages": [x["stage"] for x in report["stages"] if CUTSCENE.match(x["stage"])],
                                  "prerecorded_movies": "unchanged", "complete": False},
            "verified_in_game": False}
    marker.write_text(json.dumps(rec, default=str))
    (work / "stage.dat").unlink(missing_ok=True)
    return b | {"report": report}


def mod_name(slot: str, plan: dict[str, Donor | str]) -> str:
    s = (slot or "player").strip().lower()
    tag = re.sub(r"[^a-z0-9]+", "_", s.split(":", 1)[-1]).strip("_") or "player"
    digest = hashlib.sha256(json.dumps(sorted([k, d if isinstance(d, str) else d.slug] for k, d in plan.items()))
                            .encode()).hexdigest()[:8]
    return f"tts_{tag}_{digest}_cs1"


def _donor_of(ctx, meta: dict) -> Donor:
    from . import characters as C
    rig = meta.get("rig") or {}
    return load_donor(meta["slug"], C._local_or_fetch(ctx, meta, meta["model"]), rig.get("roles"),
                      meta.get("name", meta["slug"]), rig.get("scale"))


def _pairs(meta: dict, inp) -> list[tuple[str, str]]:
    out = [(str(p.get("target") or p.get("slot") or ""), str(p.get("donor") or p.get("character") or ""))
           for p in getattr(inp, "pairs", None) or []]
    return out or [("", meta["slug"])]


def resolve_slot(ctx, game: dict, inp) -> str:
    """The slot an op=use names, or (pick whip / chat) the one at the picked point: the slot or the pick whip's
    `target` words first (Snake / a soldier / a cast name), then the cast models the running stage has loaded
    (twin_snakes_live op=loaded) and the point (pick_slot) when x, y and a session are given."""
    s = (inp.slot or "").strip()
    if s and is_slot(s):
        return s.lower()
    words = " ".join(w for w in (s, str(getattr(inp, "target", "") or "")) if w)
    loaded = []
    if not _named(words) and getattr(inp, "session_id", "") and getattr(inp, "x", None) is not None:
        try:
            from . import characters as C
            j = C._job(ctx, "twin_snakes_live", {"session_id": inp.session_id, "op": "loaded"},
                       inp.session_id.split("-")[0], 300)
            loaded = ((j.get("output") or {}).get("result") or {}).get("cast") or []
        except Exception:                                  # noqa: BLE001 - no live reading: decide from the words
            loaded = []
    return pick_slot(loaded, words, getattr(inp, "x", None), getattr(inp, "y", None))


def _named(label: str) -> str | None:
    if SNAKE_WORDS.search(label or ""):
        return "player"
    c = next((c for c in TS.CAST if any(a.lower() in (label or "").lower() for a in [c["name"]] + c["aliases"]
                                        if len(a) > 3)), None)
    return TS.slot_for_key(c["key"]) if c else None


def main_key(key: str) -> str | None:
    """A loaded model key (a twin like out_cold_sh / #55ab65 included) -> its CAST key."""
    for c in TS.CAST:
        if key == c["key"] or key in TWINS.get(c["key"], []):
            return c["key"]
    return None


CENTRE = (0.3, 0.7, 0.25, 0.85)          # the camera follows Snake: an unidentified pick near the middle is him


def pick_slot(loaded: list[str], label: str = "", x: float | None = None, y: float | None = None) -> str:
    """A pick-whip target -> slot. loaded: the model keys the running stage has in RAM (twins allowed). Words win
    (Snake / a cast name; a soldier word picks the loaded soldier model, several -> enemies). Without words: the
    only loaded non-Snake cast member; a point in the middle of the picture is Snake (the camera follows him);
    elsewhere the loaded soldiers (enemies) or the only other cast member; else Snake."""
    label = label or ""
    hit = _named(label)
    if hit:
        return hit
    keys = []
    for k in loaded:
        mk = main_key(k)
        if mk and mk not in keys:
            keys.append(mk)
    others = [k for k in keys if k != "snake_def"]
    soldiers = [k for k in others if TS.cast_entry(k)["role"] == "enemy"]
    if SOLDIER_WORDS.search(label):
        return TS.slot_for_key(soldiers[0]) if len(soldiers) == 1 else "enemies"
    centre = x is not None and y is not None and CENTRE[0] <= x <= CENTRE[1] and CENTRE[2] <= y <= CENTRE[3]
    if not others or (centre and not label.strip()):
        return "player"
    if len(others) == 1:
        return TS.slot_for_key(others[0])
    if soldiers and len(soldiers) == len(others):
        return TS.slot_for_key(soldiers[0]) if len(soldiers) == 1 else "enemies"
    return "player"


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Twin Snakes (GC): slot player | model:<key> | enemies | bosses | npcs | all | cast
    (+pairs) | a pick-whip point (x, y + session_id) or words ("the soldier"). Built where the collection is (the
    control plane), launched through the session swap on the requesting session's node."""
    from . import characters as C, filemods
    picked = "slot" not in getattr(inp, "model_fields_set", set()) and getattr(inp, "x", None) is not None
    if picked and hasattr(inp, "model_copy"):
        inp = inp.model_copy(update={"slot": ""})        # a pick-whip point without a slot: what is there
    s = resolve_slot(ctx, game, inp)
    if s in ("cast", "roster", "everyone"):
        plan = plan_cast(_pairs(meta, inp), seed=getattr(inp, "title", "") or "")
    else:
        plan = {k: meta["slug"] for k in keys_for(s)}
    disc_no = TS.disc_of(game)
    plan = {k: v for k, v in plan.items() if disc_no in TS.cast_entry(k)["stage"]}
    if not plan:
        return {"status": "failed", "slot": s, "error": f"none of the slot's characters are on disc {disc_no}"}
    name = mod_name(s, plan)
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, game["game_id"])}
    built = None
    if inp.rebuild or not have:
        root = C.library_root(ctx.config)
        if not root.is_dir():
            cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux" and w.get("online")
                       and w.get("id") != getattr(ctx, "worker", None)), None)
            if not cp:
                raise RuntimeError("the Twin Snakes build needs the character collection on the control plane, which is offline")
            ctx.progress(5, "Building the Twin Snakes mod on the control-plane node (the collection lives there)")
            j = C._job(ctx, "characters", inp.model_dump() | {"launch": False, "session_id": "", "slot": s,
                                                               "game_id": game["game_id"]}, cp, 7200)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded":
                return {"status": "failed", "mod": name, "slot": s, "error": r.get("error") or j.get("error")}
            built = r.get("build")
        else:
            donors = {}
            for slug in sorted(set(plan.values())):
                m = C.get(root, slug) if slug != meta["slug"] else meta
                donors[slug] = _donor_of(ctx, m)
            iso = C._gc_iso(ctx, game)
            b = build_mod(ctx.config, game, iso, name, {k: donors[d] for k, d in plan.items()}, ctx.progress)
            built = {k: v for k, v in b.items() if k != "report"} | {"slots": b["report"]["slots"],
                                                                      "stages": len(b["report"]["stages"])}
            for slug in donors:
                C._api(ctx, "POST", f"/api/characters/{slug}/targets",
                       json={"game_id": game["game_id"], "slot": s, "mod": name, "nodes": [C.HOST_OS],
                             "notes": f"Twin Snakes {s}: {', '.join(k for k, d in plan.items() if d == slug)}; native "
                                      "skeleton and animations kept; gameplay verification required"})
    res = {"mod": name, "slot": s, "build": built, "status": "built_unverified" if built else "ready",
           "replaces": [TS.cast_entry(k)["name"] for k in plan], "gameplay_verified": False,
           "replacement_kind": "native_disc", "replacement_scope": {"requested": "all_character_appearances",
               "in_engine_cutscenes": "written_unverified", "prerecorded_movies": "unchanged", "complete": False}}
    if inp.launch:
        sess = C._session(ctx, inp.session_id) if inp.session_id else None
        node = sess["session_id"].split("-")[0] if sess else "idle"
        res["launch"] = C._launch(ctx, game["game_id"], name, node)
        res["message"] = (f"Twin Snakes is running with {meta['name']} as {', '.join(res['replaces'])} (mod {name}). "
                          "The session swap kept your moment; the new body appears from the next area load "
                          "(go through a door, or pick Continue). In-engine cutscene stages are included; prerecorded movies remain unchanged. "
                          "Full replacement still needs gameplay and cinematic verification.")
    return res


def live_items(old_sd: bytes, new_sd: bytes, keys: list[str]) -> list[dict]:
    """What a built mod changed, as twin_snakes_live apply items for a running game: for every stage the mod rebuilt,
    the swapped models (the same bytes in every stage), the texels of the texture images it changed (offsets in the
    set file, the set's TPL headers to check the loaded layout) and the models it hid. Deduplicated over stages."""
    import base64
    a, b = S.StageDat.from_bytes(old_sd), S.StageDat.from_bytes(new_sd)
    hs = {TS.model_hash(k) for k in keys} | {TS.model_hash(t) for k in keys for t in TWINS.get(k, [])}
    items, seen = [], set()
    for i, (name, _sec) in enumerate(a.entries):
        off, span = a.span(i)
        if old_sd[off:off + span] == new_sd[off:off + span]:
            continue
        sa, sb = a.stage(i), b.stage(i)
        old_files = {(f.type, f.hash): f.data for f in sa.files()}
        for f in sb.files():
            o = old_files.get((f.type, f.hash))
            if o is None or o[:len(f.data)] == f.data[:len(o)] and len(o) == len(f.data):
                continue
            if f.type == S.MODEL:
                kind = "model" if f.hash in hs else "hide"
                key = (kind, f.hash)
                if key in seen:
                    continue
                seen.add(key)
                it = {"kind": kind, "hash": f"{f.hash:06x}"}
                if kind == "model":
                    it |= {"data": base64.b64encode(f.data).decode(), "size": len(o),
                           "expect": base64.b64encode(o[:0x60]).decode(), "required": False}
                items.append(it)
            elif f.type == S.TEXTURES:
                ts = T.TextureSet(o)
                hdr = 12 + 8 * len(ts.images)
                tpl_hdr = o[ts.tpl:ts.tpl + hdr + 0x24 * len(ts.images)]
                for img in ts.images:
                    lo = ts.tpl + img.data_off
                    hi = lo + T.image_size(img.fmt, img.w, img.h)
                    ranges = [(lo, hi)]
                    if img.pal_off:
                        ranges.append((ts.tpl + img.pal_off, ts.tpl + img.pal_off + 2 * img.pal_count))
                    for lo2, hi2 in ranges:
                        if o[lo2:hi2] != f.data[lo2:hi2]:
                            key = ("tex", f.hash, lo2)
                            if key in seen:
                                continue
                            seen.add(key)
                            items.append({"kind": "texels", "textures": [t.hash for t in ts.textures], "offset": lo2,
                                          "data": base64.b64encode(f.data[lo2:hi2]).decode(),
                                          "expect": base64.b64encode(tpl_hdr).decode()})
    return items


def _live_file(cfg, gid: str, name: str) -> list | None:
    """The mod's live items on this node: its own folder, or the staged copy the session swap launched."""
    from . import filemods
    root = Path(cfg.cache) / "mods" / gid
    cands = [root / name] + sorted(root.glob(f"{name}{getattr(filemods, 'STAGED_SEP', '~')}*"), reverse=True)
    for d in cands:
        f = d / LIVE_FILE
        if f.is_file():
            return json.loads(f.read_text())
    return None


def _launch_wait(ctx, gid: str, mod: str, node: str, limit: float = 1800) -> dict:
    """@launch the mod on the session's node (the server turns it into a session swap: save state, launch the mod on
    the same worker, load the state, close the old copy) and wait for the new session."""
    from . import characters as C
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": mod, "node": node}})
    t0 = time.time()
    while lj.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(2)
        lj = C._api(ctx, "GET", f"/api/jobs/{lj['id']}")
    out = lj.get("output") or {}
    return {"job": lj.get("id"), "state": lj.get("state"), "node": node, "error": lj.get("error"),
            "session_id": out.get("session_id") or (out.get("result") or {}).get("session_id")}


def live_use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=live_use (the pick whip's "Try live replacement"): the slot at the picked point (or named) is
    built into a mod as op=use does, the running game moves onto the mod through the session swap (moment kept),
    then the new body and textures are written into the loaded stage (twin_snakes_live apply) so it shows now."""
    from . import characters as C
    if not inp.session_id:
        raise ValueError("live_use needs a running session_id")
    pick = inp
    if "slot" not in getattr(inp, "model_fields_set", set()) and getattr(inp, "x", None) is not None:
        pick = inp.model_copy(update={"slot": ""}) if hasattr(inp, "model_copy") else inp
    slot = resolve_slot(ctx, game, pick)
    built = use(ctx, meta, game, inp.model_copy(update={"slot": slot, "launch": False}) if hasattr(inp, "model_copy")
                else inp)
    if built.get("status") == "failed":
        return built | {"in_engine": False}
    name = built["mod"]
    res = dict(built, slot=slot)
    sess = C._session(ctx, inp.session_id)
    node = sess["session_id"].split("-")[0] if sess else "idle"
    launch = _launch_wait(ctx, game["game_id"], name, node)        # the server's session swap keeps the moment
    res["launch"] = launch
    new_sid = (launch or {}).get("session_id") or inp.session_id
    try:
        items = _live_file(ctx.config, game["game_id"], name)
        if items is None:
            raise FileNotFoundError(f"the mod's {LIVE_FILE} is not on this node")
        j = C._job(ctx, "twin_snakes_live", {"session_id": new_sid, "op": "apply", "items": items},
                   new_sid.split("-")[0], 600)
        res["live"] = (j.get("output") or {}).get("result") or {"state": j.get("state"), "error": j.get("error")}
        ok = j.get("state") == "succeeded"
    except Exception as e:                                # noqa: BLE001 - the mod is running either way
        res["live"] = {"error": str(e)[:400]}
        ok = False
    res["in_engine"] = ok
    res["status"] = "live_swapped" if ok else ("launched" if launch.get("state") == "succeeded" else
                                               f"launch {launch.get('state')}")
    res["message"] = (f"{meta['name']} replaces {', '.join(res['replaces'])} in the running game now (written into the "
                      f"loaded stage) and on the modded disc {name} from the next area load." if ok else
                      f"{meta['name']} is on the modded disc {name}; the session swap kept your moment, the new body "
                      "appears from the next area load (go through a door, or Continue). Live write: "
                      f"{(res.get('live') or {}).get('error') or 'not applied'}.")
    return res


def build_cast(cfg, game: dict, pairs, name: str, progress=None) -> dict:
    """cast_swap's pairs path: [(slot, meta)] -> one disc image. -> {mod, slots: {slot: {status, reason?}}}."""
    from . import characters as C
    plan, donors, per = {}, {}, {}
    root = C.library_root(cfg)
    for slot, meta in pairs:
        try:
            if meta["slug"] not in donors:
                rig = meta.get("rig") or {}
                donors[meta["slug"]] = load_donor(meta["slug"], root / meta["slug"] / meta["model"], rig.get("roles"),
                                                  meta.get("name", meta["slug"]), rig.get("scale"))
            for k in keys_for(slot):
                plan[k] = donors[meta["slug"]]
        except Exception as e:                            # noqa: BLE001
            per[slot] = {"status": "failed", "reason": str(e)[:400]}
    if not plan:
        return {"mod": None, "slots": per}
    from .models import CatalogEntry
    from .tools import rom_path
    image = rom_path(CatalogEntry.model_validate(game), cfg)
    if image.suffix.lower() == ".gcz":
        from . import filemods
        base = filemods.base_dir(cfg, game["game_id"]) / (image.stem + ".iso")
        if not base.exists():
            base.parent.mkdir(parents=True, exist_ok=True)
            filemods.gcz_to_iso(image, base.with_suffix(".part"), progress)
            base.with_suffix(".part").replace(base)
        image = base
    try:
        b = build_mod(cfg, game, image, name, plan, progress)
    except Exception as e:                                # noqa: BLE001
        return {"mod": None, "slots": per | {s: {"status": "failed", "reason": str(e)[:400]} for s, _m in pairs
                                             if s not in per}}
    rs = b["report"]["slots"]
    for slot, _m in pairs:
        if slot in per:
            continue
        st = [rs.get(k, {}) for k in keys_for(slot)]
        ok = [x for x in st if x.get("status") == "built"]
        per[slot] = {"status": "built"} if ok and len(ok) == len(st) else \
            {"status": "partial" if ok else "failed",
             "reason": "; ".join(f"{x.get('reason')}" for x in st if x.get("status") != "built")[:400]}
    return {"mod": name, "slots": per}


# --------------------------------------------------------------------------------------------- live (RAM)

MEM1 = (0x80000000, 0x81800000)


def find_loaded(ram: bytes, base: int = MEM1[0], hashes: set[int] | None = None) -> list[dict]:
    """Loaded character models in a MEM1 snapshot: a relocated .kms header (bones 21, the model strcode at +0x10,
    +0x5c = its own address + the mesh-group offset). -> [{address, hash, key, g}]."""
    want = hashes or {TS.model_hash(c["key"]) for c in TS.CAST} | {TS.model_hash(t) for v in TWINS.values() for t in v}
    out = []
    arr = np.frombuffer(ram[:len(ram) // 4 * 4], ">u4")
    cand = np.nonzero(np.isin(arr, np.array(sorted(want), np.uint32)))[0]     # the strcode at +0x10
    for i in cand:
        a = int(i) * 4 - 0x10
        if a < 0 or a + 0x60 > len(ram):
            continue
        name = struct.unpack_from(">I", ram, a + 0x10)[0]
        nb, nm = struct.unpack_from(">II", ram, a + 4)
        if not (0 < nb <= 256 and 0 < nm <= 512):
            continue
        g = struct.unpack_from(">I", ram, a + 0x5C)[0] - (base + a)
        if not 0x60 <= g <= 0x4000:
            continue
        key = next((c["key"] for c in TS.CAST if TS.model_hash(c["key"]) == name), None) or \
            next((t for v in TWINS.values() for t in v if TS.model_hash(t) == name), f"#{name:06x}")
        out.append({"address": base + a, "hash": name, "key": key, "g": g})
    return out


def relocate(new: bytes, address: int, ram_old: bytes) -> bytes:
    """An encoded model (file offsets) -> the bytes to write at `address` over a loaded copy (`ram_old`, its RAM
    bytes): every pointer the engine's loader makes absolute is made absolute here; texture fields keep the loaded
    copy's resolved texture-entry pointers of the same mesh's first part."""
    d = bytearray(new)
    G = struct.unpack_from(">I", d, 0x5C)[0]
    Ga = address + G
    for o in (0x4C, 0x50, 0x54, 0x58):
        v = struct.unpack_from(">I", d, o)[0]
        struct.pack_into(">I", d, o, Ga + v if v else 0)
    struct.pack_into(">I", d, 0x5C, Ga)
    nmesh, _np, sub, recs = struct.unpack_from(">HHII", d, G + 8)
    struct.pack_into(">II", d, G + 0x0C, 0, Ga + recs)
    old_parts = {}
    og = struct.unpack_from(">I", ram_old, 0x5C)[0] - address
    o_recs = struct.unpack_from(">I", ram_old, og + 0x10)[0] - address
    for i in range(nmesh):
        orec = o_recs + 0x48 * i
        if struct.unpack_from(">H", ram_old, orec + 0x38)[0]:
            pp = struct.unpack_from(">I", ram_old, orec + 0x44)[0] - address
            old_parts[i] = ram_old[pp + 4:pp + 0x10]
    for i in range(nmesh):
        mo = G + recs + 0x48 * i
        npart = struct.unpack_from(">H", d, mo + 0x38)[0]
        poff = struct.unpack_from(">I", d, mo + 0x44)[0]
        struct.pack_into(">I", d, mo + 0x44, Ga + poff if npart else 0)
        for k in range(npart):
            po = G + poff + 0x24 * k
            if i in old_parts:
                d[po + 4:po + 0x10] = old_parts[i]
            nstrip = struct.unpack_from(">H", d, po + 0x10)[0]
            ul, ul2, _x, so = struct.unpack_from(">4I", d, po + 0x14)
            struct.pack_into(">II", d, po + 0x14, Ga + ul, Ga + ul2 if ul2 else 0)
            struct.pack_into(">I", d, po + 0x20, Ga + so)
            for s in range(nstrip):
                q = G + so + 0x20 * s
                offs = struct.unpack_from(">7I", d, q)
                struct.pack_into(">7I", d, q, *[Ga + o if o else 0 for o in offs])
    return bytes(d)


def live_apply(ad, address: int, expected_head: bytes, new: bytes, old_size: int) -> dict:
    """Write a relocated model over a loaded copy: paused, the loaded header checked against `expected_head` first,
    the region read back, rolled back on any mismatch."""
    if len(new) > old_size:
        raise ValueError("the live model is larger than the loaded copy")
    state = (ad.query_runtime() or {}).get("state") if hasattr(ad, "query_runtime") else None
    paused = False
    if state != "PAUSED" and hasattr(ad, "pause"):
        ad.pause()
        paused = True
    try:
        old = bytes(ad.read_memory(address, old_size))
        if old[:len(expected_head)] != expected_head:
            raise ValueError("the loaded model changed (stage load?); nothing was written")
        data = relocate(new, address, old)
        try:
            ad.write_memory(address, data)
            back = bytes(ad.read_memory(address, len(data)))
            if back != data:
                raise ValueError("read-back mismatch")
        except Exception:
            ad.write_memory(address, old)
            raise
        return {"address": hex(address), "bytes": len(data), "verified": True}
    finally:
        if paused and hasattr(ad, "resume"):
            ad.resume()


# --------------------------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    import argparse
    import types
    ap = argparse.ArgumentParser(description="Twin Snakes: a library character as a cast model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="rebuild stage.dat (and, with --image, the disc) offline")
    b.add_argument("image")
    b.add_argument("character", help="library entry folder (meta.json + model)")
    b.add_argument("out")
    b.add_argument("--slot", default="player")
    b.add_argument("--disc-image", action="store_true", help="also write the modded disc image")
    a = ap.parse_args(argv)
    meta = json.loads((Path(a.character) / "meta.json").read_text(encoding="utf-8"))
    rig = meta.get("rig") or {}
    donor = load_donor(meta["slug"], Path(a.character) / meta["model"], rig.get("roles"), meta.get("name"), rig.get("scale"))
    plan = {k: donor for k in keys_for(a.slot)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    prog = lambda p, m: print(m, flush=True)               # noqa: E731
    if a.disc_image:
        game = {"game_id": "twin_snakes_cli", "title": "Twin Snakes"}
        r = build_mod(types.SimpleNamespace(cache=out), game, Path(a.image), mod_name(a.slot, plan), plan, prog)
        rep = r["report"]
    else:
        from .gcdisc import GCDisc
        d = GCDisc(a.image)
        sdat = d.read(S.STAGE_DAT)
        d.f.close()
        new, rep = build_stage_dat(sdat, plan, prog)
        (out / "stage.dat").write_bytes(new)
    print(json.dumps({"stages": rep["stages"], "budget_scale": rep["budget_scale"],
                      "slots": {k: {x: y for x, y in v.items() if x != "fit"} for k, v in rep["slots"].items()},
                      "seconds": round(time.time() - t0, 1)}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
