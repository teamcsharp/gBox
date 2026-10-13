"""Crazy Taxi (GameCube, GCTE51; gBox game id bc02bb68790ce2e7): a collection character as any of the four drivers, or
as any of the people in the shape bank, written into a rebuilt disc image in a mod dir (never in place).

Not Dreamcast, not Ninja: catalog entry bc02bb68790ce2e7 is the hyperspin GameCube `.gcz` (Dolphin; the unpacked ISO
sits in cache/modbase/bc02bb68790ce2e7), and its people are rigid GX `.shp` parts in `ct/polDC0.all`, which
gbox.crazy_taxi reads (`read_bank`, `read_shape`) and encodes (`encode_shape`). The PSO / SA2 Ninja encoders
(gbox.ninja, gbox.ninja_swap, gbox.pso_player) do not apply to this title.

The cast in the bank (owned disc; `people()` reads it, PEOPLE is the measured snapshot):
* drivers `MP_YH_plyrA..D_*` (Axel, B.D. Joe, Gena, Gus; 54/54/50/50 blobs): the 15 PARTS each, plus the hand poses
  `_gu/_ch/_ok` (rock / scissors / "ok" hands the gesture animations switch to), `sl_` low-detail twins and the
  accessory sub-parts below;
* pedestrians `MP_YH_ppl{M,W,X,Y}?_*` (18 groups) and `MP_YH_Man_*`: some have no hips / hand / foot parts;
* passengers (the fares) `MP_YH_psg??_*` (31 groups; `MP_YH_psgAO.shp` is a whole-body extra, left alone).

Accessory sub-parts: a `B`/`C`/`D` (or `1`) suffix on a part name is NOT an alternate mesh but an extra shape drawn
together with its part by its own rig entry (main.dol's rig list has atamaD/C/B before atama, muneB before mune):
B.D. Joe's hat (plyrB_atamaB: 32 verts around the top of the head), Gena's ponytails (plyrC_atamaB/C, mirrored at
z = +-0.54), sleeve cuffs at the far end of the upper arms (plyrA_kata_rB x 1.0..2.55 against kata_r x -0.63..2.15),
Axel's vest over his chest (muneB), Gus's wristband (plyrD_ude_lB x 2.04..2.5). Fitting the whole donor segment into
each of them (what gbox.crazy_taxi.swap_driver did for Axel) draws squashed extra copies of the donor's head, chest and
arms over the real ones, so this writer hides them (one zero-area triangle per material) and fits the donor into the
main part, its `sl_` twin and the hand poses only.

Frame: a part's s16 vertices are relative to its header centre and the game adds the centre back when drawing (the
decoded, centre-included parts are bone-local and start at their joint: thigh x -0.88..4.23, chest x 0.15..4.99; the
cabs' TAXI sign only lands on the roof with its centre added, gbox.crazy_taxi). The donor is therefore fitted onto the
centre-included cloud and stored centre-subtracted. The s16 range at the part's own scale/frac covers exactly its
bounding radius, so a fit that pokes out is shrunk about the cloud's mean to fit (`fit_blob`).

Materials: the material records carry no colour, only display-list pointers and indices into game-side tables (e.g.
plyrA_atama's records index 0xc/0xd/0xe, 0x15/0x16/0x17 ...), every part shares the solid white.tex and UV (0, 0), so
the donor's colours and textures cannot be written. The donor's triangles are dealt to the part's materials by region:
each material keeps the centroid of the triangles it drew in the stock part (hair on top of the head, face in front)
and takes the donor triangles nearest it, so the stock colours land roughly where they did before.

Budget: a blob keeps its size and the bank keeps every name and order (main.dol's shape enum addresses bank positions).
Vertices must fit the array region and the display lists the DL region of the template; `encode_shape` strips each
material's chunk separately, so the fit searches the largest vertex count whose actual encoding fits (the earlier
`_fit_segment` estimated one strip set for all materials and overflowed on B.D. Joe's 3-material head: 896 > 704).

Slots (`characters op=use slot=...`): `player` (the driver this character was last built for in this game, else
Axel), `driver:<axel|bd_joe|gena|gus>` (names and aliases), `drivers` (all four, so the driver-select choice does
not matter), `pedestrian:<group>` / `pedestrians`, `passenger:<group>` / `passengers`. `roster()` lists them and
`characters op=collect` reports them as slots (`cast_slots()`) without extracting anything (the parts are bone-local,
#1369).

Quantisation: the header (radius, centre, scale, format words) is kept byte for byte, so the game decodes the new
s16 arrays exactly as it decoded the stock ones. gbox.crazy_taxi's `Shape.frac()` guesses the POS shift from the
bounding radius; on a written blob that guess can differ (a donor that does not reach the stock radius reads as
frac 6), so checks decode written parts with the stock part's frac.

Checked on the owned bank (a5171e43...) with HUcast: every driver (54/54/50/50 blobs, 1087-1241 triangles), every
pedestrian and every fare group encode at their stock sizes, names and order.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import crazy_taxi as ct

GAME_IDS = ct.GAME_IDS
BANK = ct.BANK
PARTS = ct.PARTS
# slug: (bank letter, name, aliases); select order A..D
DRIVERS = {
    "axel": ("A", "Axel", ("axel", "a", "plyra")),
    "bd_joe": ("B", "B.D. Joe", ("bd_joe", "bdjoe", "bd joe", "b.d. joe", "b.d.joe", "joe", "b", "plyrb")),
    "gena": ("C", "Gena", ("gena", "c", "plyrc")),
    "gus": ("D", "Gus", ("gus", "d", "plyrd")),
}
# The people groups of the owned disc's ct/polDC0.all (sha256 a5171e43...): group -> (kind, blob count, PARTS missing).
# Measured with people(); the writer reads the live bank and uses this only to list slots without the disc.
PEOPLE = {
    "Man": ("pedestrian", 15, ()),
    "plyrA": ("driver", 54, ()),
    "plyrB": ("driver", 54, ()),
    "plyrC": ("driver", 50, ()),
    "plyrD": ("driver", 50, ()),
    "pplMC": ("pedestrian", 13, ("koshi", "te_l", "te_r")),
    "pplMD": ("pedestrian", 12, ("koshi", "te_l", "te_r")),
    "pplME": ("pedestrian", 12, ("koshi", "te_l", "te_r")),
    "pplMF": ("pedestrian", 12, ("koshi", "te_l", "te_r")),
    "pplMG": ("pedestrian", 12, ("koshi", "te_l", "te_r")),
    "pplMH": ("pedestrian", 12, ("koshi", "te_l", "te_r")),
    "pplMI": ("pedestrian", 13, ("koshi", "te_l", "te_r")),
    "pplWA": ("pedestrian", 11, ("koshi", "te_l", "te_r", "kakato_l", "kakato_r")),
    "pplWB": ("pedestrian", 11, ("koshi", "te_l", "te_r", "kakato_l", "kakato_r")),
    "pplXA": ("pedestrian", 18, ()),
    "pplXB": ("pedestrian", 18, ()),
    "pplXD": ("pedestrian", 14, ("koshi", "te_l")),
    "pplYA": ("pedestrian", 13, ("te_l", "te_r", "kakato_l", "kakato_r")),
    "pplYB": ("pedestrian", 12, ("te_l", "te_r", "kakato_l", "kakato_r")),
    "pplYC": ("pedestrian", 13, ("te_l", "te_r", "kakato_l", "kakato_r")),
    "pplYD": ("pedestrian", 13, ("te_l", "te_r", "kakato_l", "kakato_r")),
    "pplYE": ("pedestrian", 13, ("te_l", "te_r", "kakato_l", "kakato_r")),
    "pplYF": ("pedestrian", 16, ()),
    "psgAA": ("passenger", 23, ()),
    "psgAB": ("passenger", 22, ()),
    "psgAC": ("passenger", 25, ()),
    "psgAD": ("passenger", 21, ()),
    "psgAE": ("passenger", 24, ()),
    "psgAH": ("passenger", 21, ()),
    "psgAI": ("passenger", 23, ()),
    "psgAJ": ("passenger", 23, ()),
    "psgAK": ("passenger", 22, ()),
    "psgAL": ("passenger", 23, ()),
    "psgAM": ("passenger", 19, ()),
    "psgAN": ("passenger", 23, ()),
    "psgAO": ("passenger", 24, ()),
    "psgAP": ("passenger", 19, ()),
    "psgAQ": ("passenger", 23, ()),
    "psgAS": ("passenger", 21, ()),
    "psgAT": ("passenger", 23, ()),
    "psgAU": ("passenger", 23, ()),
    "psgAW": ("passenger", 22, ()),
    "psgAZ": ("passenger", 25, ()),
    "psgBA": ("passenger", 22, ()),
    "psgBB": ("passenger", 25, ()),
    "psgBC": ("passenger", 22, ()),
    "psgBD": ("passenger", 23, ()),
    "psgBE": ("passenger", 22, ()),
    "psgBF": ("passenger", 22, ()),
    "psgBG": ("passenger", 21, ()),
    "psgBH": ("passenger", 22, ()),
    "psgBI": ("passenger", 23, ()),
    "psgBJ": ("passenger", 23, ()),
    "psgCA": ("passenger", 22, ()),
}
_PART_RX = re.compile(r"^MP_YH_(?P<group>plyr[A-D]|ppl[A-Z]{2}|psg[A-Z]{2}|Man)_(?P<lod>sl_)?(?P<part>"
                      + "|".join(sorted(PARTS, key=len, reverse=True)) + r")(?P<acc>[BCD1])?(?P<pose>_gu|_ch|_ok)?\.shp$")
_GROUP_RX = re.compile(r"^MP_YH_(plyr[A-D]|ppl[A-Z]{2}|psg[A-Z]{2}|Man)(_|\.shp$)")
SLOT_HELP = ("player | driver:<axel|bd_joe|gena|gus> | drivers | pedestrian:<group> | pedestrians | "
             "passenger:<group> | passengers (characters op=collect lists the groups)")


# ----------------------------------------------------------------------------------------------- bank names

def classify(name: str) -> dict | None:
    """'MP_YH_plyrB_sl_atamaB.shp' -> {group: 'plyrB', part: 'atama', lod: True, accessory: True, pose: ''}; None for
    anything that is not a people part (cars, props, the whole-body MP_YH_psgAO.shp)."""
    m = _PART_RX.match(name)
    if not m:
        return None
    return {"group": m["group"], "part": m["part"], "lod": bool(m["lod"]), "accessory": bool(m["acc"]),
            "pose": (m["pose"] or "").lstrip("_")}


def group_kind(group: str) -> str:
    return "driver" if group.startswith("plyr") else "passenger" if group.startswith("psg") else "pedestrian"


def people(entries) -> dict[str, dict]:
    """The people groups of a bank: {group: {kind, blobs, parts: {part: [names]}, missing: (PARTS absent,)}}."""
    out: dict[str, dict] = {}
    for n, _o, _s in entries:
        m = _GROUP_RX.match(n)
        if not m:
            continue
        d = out.setdefault(m.group(1), {"kind": group_kind(m.group(1)), "blobs": 0, "parts": {}})
        d["blobs"] += 1
        c = classify(n)
        if c:
            d["parts"].setdefault(c["part"], []).append(n)
    for d in out.values():
        d["missing"] = tuple(p for p in PARTS if p not in d["parts"])
    return out


def _static_people() -> dict[str, dict]:
    return {g: {"kind": k, "blobs": b, "missing": m, "parts": {p: [] for p in PARTS if p not in m}}
            for g, (k, b, m) in PEOPLE.items()}


# ----------------------------------------------------------------------------------------------- slots

@dataclass(frozen=True)
class Slot:
    kind: str                 # driver | drivers | pedestrian | pedestrians | passenger | passengers
    groups: tuple             # bank groups replaced, e.g. ("plyrB",)
    label: str                # "B.D. Joe"
    suffix: str               # mod name suffix after ct_<slug>: "" (Axel), "_bd_joe", "_drivers", "_ped_pplMC" ...
    slot: str                 # canonical slot string, e.g. "driver:bd_joe"

    def describe(self) -> str:
        return {"driver": f"{self.label} the driver (MP_YH_{self.groups[0]}_*: every part, hand pose and sl_ LOD; "
                          "accessory sub-parts hidden; skeleton and animations stay)",
                "drivers": "all four drivers (Axel, B.D. Joe, Gena, Gus), whichever is selected",
                "pedestrian": f"the {self.groups[0]} pedestrians (MP_YH_{self.groups[0]}_*)",
                "pedestrians": f"every pedestrian group ({len(self.groups)})",
                "passenger": f"the {self.groups[0]} fares (MP_YH_{self.groups[0]}_*)",
                "passengers": f"every fare group ({len(self.groups)})"}[self.kind]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def driver_slug(text: str) -> str:
    """'B.D. Joe' / 'joe' / 'b' / 'plyrB' -> 'bd_joe'; raises for an unknown driver."""
    t = _norm(text)
    for slug, (_letter, name, aliases) in DRIVERS.items():
        if t and t in {_norm(slug), _norm(name), *(_norm(a) for a in aliases)}:
            return slug
    raise ValueError(f"unknown Crazy Taxi driver {text!r}: axel, bd_joe, gena or gus")


def _driver_slot(slug: str) -> Slot:
    letter, name, _ = DRIVERS[slug]
    return Slot("driver", (f"plyr{letter}",), name, "" if slug == "axel" else f"_{slug}", f"driver:{slug}")


def _group_key(text: str, kind: str, groups: dict) -> str:
    t = _norm(text)
    pre = {"pedestrian": "ppl", "passenger": "psg"}[kind]
    for g, d in groups.items():
        if d["kind"] == kind and t in {_norm(g), _norm(g[3:]) if g.startswith(pre) else _norm(g)}:
            return g
    have = ", ".join(sorted(g for g, d in groups.items() if d["kind"] == kind))
    raise ValueError(f"unknown Crazy Taxi {kind} group {text!r}; groups: {have}")


def is_slot(slot: str) -> bool:
    """Does this slot string belong to this writer (without validating the names)?"""
    s = (slot or "player").strip().lower()
    return s in ("player", "driver", "drivers", "pedestrians", "peds", "passengers", "fares") or \
        s.startswith(("driver:", "pedestrian:", "ped:", "passenger:", "fare:"))


def parse_slot(slot: str, default_driver: str = "axel", groups: dict | None = None) -> Slot:
    """The slot string -> Slot (bank groups to replace, mod suffix). groups: people() of the live bank, else PEOPLE."""
    s = (slot or "player").strip().lower()
    groups = groups or _static_people()
    if s in ("player", "driver", ""):
        return _driver_slot(default_driver if default_driver in DRIVERS else "axel")
    if s in ("drivers", "driver:all", "driver:*"):
        return Slot("drivers", tuple(f"plyr{v[0]}" for v in DRIVERS.values()), "all four drivers", "_drivers", "drivers")
    if s.startswith("driver:"):
        return _driver_slot(driver_slug(s[7:]))
    for kind, names, pre in (("pedestrian", ("pedestrians", "peds", "pedestrian:all", "ped:all"), ("pedestrian:", "ped:")),
                             ("passenger", ("passengers", "fares", "passenger:all", "fare:all"), ("passenger:", "fare:"))):
        if s in names:
            keys = tuple(sorted(g for g, d in groups.items() if d["kind"] == kind))
            return Slot(kind + "s", keys, f"all {len(keys)} {kind} groups", f"_{kind}s", kind + "s")
        for p in pre:
            if s.startswith(p):
                g = _group_key(s[len(p):], kind, groups)
                return Slot(kind, (g,), f"{kind} {g}", f"_{'ped' if kind == 'pedestrian' else 'psg'}_{g}", f"{kind}:{g}")
    raise ValueError(f"unknown Crazy Taxi slot {slot!r}: {SLOT_HELP}")


def default_driver(meta: dict, gid: str) -> str:
    """slot=player: the driver this character was last built for in this game (its driver:<x> target), else Axel."""
    for t in reversed(list((meta.get("targets") or {}).get(gid) or [])):
        s = str(t.get("slot") or "")
        if s.startswith("driver:") and s[7:] in DRIVERS:
            return s[7:]
    return "axel"


def mod_name(slug: str, slot: Slot) -> str:
    return f"ct_{slug}{slot.suffix}"


def roster(bank: bytes | None = None) -> list[dict]:
    """The writer's slots as roster entries (kind "slot", never extracted: `collect` False). With the bank, the groups
    come from it; without, from the PEOPLE snapshot."""
    grp = people(ct.read_bank(bank)) if bank is not None else _static_people()
    out = []
    for slug, (letter, name, aliases) in DRIVERS.items():
        g = grp.get(f"plyr{letter}", {})
        out.append({"key": f"driver:{slug}", "slug": f"crazy_taxi_{slug}", "name": f"{name} (Crazy Taxi driver)",
                    "aliases": [name, *aliases], "kind": "slot", "slot": f"driver:{slug}", "slot_kind": "driver",
                    "collect": False, "writer": "gbox.crazy_taxi_swap", "blobs": g.get("blobs", 0),
                    "missing": list(g.get("missing", ()))})
    out.append({"key": "drivers", "slug": "crazy_taxi_drivers", "name": "all four drivers (Crazy Taxi)",
                "aliases": ["drivers"], "kind": "slot", "slot": "drivers", "slot_kind": "drivers", "collect": False,
                "writer": "gbox.crazy_taxi_swap"})
    for g in sorted(grp):
        d = grp[g]
        if d["kind"] == "driver":
            continue
        out.append({"key": f"{d['kind']}:{g}", "slug": f"crazy_taxi_{g.lower()}", "name": f"{d['kind']} {g} (Crazy Taxi)",
                    "aliases": [g, g[3:] if g.startswith(("ppl", "psg")) else g], "kind": "slot",
                    "slot": f"{d['kind']}:{g}", "slot_kind": d["kind"], "collect": False,
                    "writer": "gbox.crazy_taxi_swap", "blobs": d["blobs"], "missing": list(d["missing"])})
    for kind in ("pedestrians", "passengers"):
        n = sum(1 for d in grp.values() if d["kind"] + "s" == kind)
        out.append({"key": kind, "slug": f"crazy_taxi_{kind}", "name": f"all {n} {kind[:-1]} groups (Crazy Taxi)",
                    "aliases": [kind], "kind": "slot", "slot": kind, "slot_kind": kind, "collect": False,
                    "writer": "gbox.crazy_taxi_swap"})
    return out


def cast_slots() -> list[dict]:
    """The slots this writer offers the cast menu (`characters op=collect` "slots", via
    gbox.char_coverage.cast_slots): `player` first, then every roster() slot. Nothing is extracted or read."""
    out = [{"slot": "player", "name": "the driver (the one this character was last built for, else Axel)",
            "kind": "player", "writer": "gbox.crazy_taxi_swap", "alias_of": "driver:axel"}]
    for r in roster():
        out.append({"slot": r["slot"], "name": r["name"], "kind": r["slot_kind"], "writer": r["writer"],
                    **({"aggregate": True} if r["slot"] in ("drivers", "pedestrians", "passengers") else {}),
                    "aliases": r["aliases"], **({"blobs": r["blobs"]} if "blobs" in r else {})})
    return out


# ----------------------------------------------------------------------------------------------- fitting

def representable(template: bytes, frac: int) -> np.ndarray:
    """Largest |centre-relative coordinate| per axis the part's s16 arrays hold: scale * 32767 / 2**frac (the part's
    bounding radius on the disc's own parts)."""
    return np.asarray(struct.unpack_from(">3f", template, 0x2C), float) * 32767.0 / (1 << frac)


def material_regions(template: bytes, name: str = "") -> list[np.ndarray]:
    """Per material record (display-list order): the centroid of the triangles it draws in the stock part, decoded
    with the centre included."""
    s = ct.read_shape(template, name)
    attrs = [a for a, o in ct.ATTR_OFFS if ct._u32(template, o)]
    pts = np.asarray(s.positions(), float)
    out = []
    for off, size in s.lists:
        idx = [c["pos"] for t in ct.decode_dl(template[off:off + size], attrs) for c in t]
        out.append(pts[idx].mean(0) if idx else pts.mean(0))
    return out


def deal_materials(pos, tris, centroids) -> list[list[tuple]]:
    """Each triangle to the material whose stock region centroid is nearest the triangle's centroid. Every material
    keeps at least one triangle while there are enough, so no zero-length display list is written."""
    tris = [tuple(map(int, t)) for t in tris]
    if not tris:
        return [[] for _ in centroids]
    if len(centroids) <= 1:
        return [list(tris)]
    C = np.asarray(centroids, float)
    pos = np.asarray(pos, float)
    tc = np.asarray([pos[list(t)].mean(0) for t in tris])
    d = ((tc[:, None, :] - C[None, :, :]) ** 2).sum(-1)
    order: list[list[int]] = [[] for _ in centroids]
    for i, k in enumerate(d.argmin(1)):
        order[int(k)].append(i)
    for k in range(len(order)):
        if not order[k]:
            giver = max(range(len(order)), key=lambda j: len(order[j]))
            if len(order[giver]) < 2:
                break
            i = min(order[giver], key=lambda i: d[i, k])
            order[giver].remove(i)
            order[k].append(i)
    return [[tris[i] for i in o] for o in order]


def _axes(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centroid and principal axes (rows, by falling variance) of a point set."""
    mu = X.mean(0)
    _u, _s, vt = np.linalg.svd(X - mu, full_matrices=False)
    if len(vt) < 3:                                          # fewer than 3 points: complete the frame
        vt = np.linalg.qr(np.vstack([vt, np.eye(3)]).T)[0].T[:3]
    return mu, vt


def _chamfer(a: np.ndarray, b: np.ndarray) -> float:
    d = ((a[:, None, :] - b[None, :, :]) ** 2).sum(-1)
    return float(np.sqrt(d.min(1)).mean() + np.sqrt(d.min(0)).mean())


def fit_points(P, N, cloud, max_stretch: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Donor points P (normals N) onto a stock part's decoded cloud: the donor's principal axes onto the part's (of the
    four proper sign choices, the one with the smallest chamfer distance), each axis scaled to the part's extent along
    it (stretch held within `max_stretch` of the mean scale, so a flat donor plate is not blown up into a box), and the
    bounding-box centres matched. Returns (points, unit normals).

    A rigid + uniform-scale Umeyama on farthest-point samples (gbox.crazy_taxi._fit_rigid) pairs points by sample
    order, not by position; on unrelated shapes that pairing shrinks the donor (a 4 x 2 x 2 part took a sphere 1.3
    across), so the parts came out as small blobs at the joints."""
    P, cloud = np.asarray(P, float), np.asarray(cloud, float)
    N = np.asarray(N, float) if len(N) == len(P) else np.zeros_like(P)
    mp, ap = _axes(P)
    mc, ac = _axes(cloud)
    cq = (cloud - mc) @ ac.T
    lo_c, hi_c = cq.min(0), cq.max(0)
    sub = P[ct._farthest(P, min(len(P), 400))]
    best = None
    for signs in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)):
        S = np.asarray(signs, float)
        if np.linalg.det(ac.T @ np.diag(S) @ ap) < 0:
            S = -S                                           # keep a proper rotation (ap/ac may be left-handed)
        q = (P - mp) @ ap.T * S
        lo_p, hi_p = q.min(0), q.max(0)
        ext_p, ext_c = np.maximum(hi_p - lo_p, 1e-6), np.maximum(hi_c - lo_c, 1e-6)
        k = ext_c / ext_p
        g = float(np.exp(np.log(k).mean()))
        k = np.clip(k, g / max_stretch, g * max_stretch)
        shift = (lo_c + hi_c) / 2 - k * (lo_p + hi_p) / 2

        def place(X, S=S, k=k, shift=shift):
            return mc + (((X - mp) @ ap.T * S) * k + shift) @ ac

        err = _chamfer(place(sub), cloud)
        if best is None or err < best[0]:
            best = (err, S, k, place)
    _err, S, k, place = best
    L = ac.T @ np.diag(k) @ np.diag(S) @ ap                  # x' = L x (+ offset): normals go by L^-T
    nrm = N @ np.linalg.inv(L)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    return place(P), nrm


PART_ROLE = {"koshi": "hip", "mune": "chest", "atama": "head", "kata_l": "l_upper", "ude_l": "l_fore", "te_l": "l_hand",
             "kata_r": "r_upper", "ude_r": "r_fore", "te_r": "r_hand", "momo_l": "l_thigh", "sune_l": "l_shin",
             "kakato_l": "l_foot", "momo_r": "r_thigh", "sune_r": "r_shin", "kakato_r": "r_foot"}


def profile_matrix(part: str | None, cloud, profile: dict | None) -> np.ndarray:
    """The operator's retarget profile (gbox.retarget_profile) for one rigid Crazy Taxi part: parts are stored in
    their own joint frame, so only the size adjustments apply - head size, a role's scale, its length along the part's
    long axis and girth across it, torso width on the hips / chest, arm / leg length. Offsets, rotations, height and
    ground need a shared skeleton frame and are left to the game's own pose. Identity without a profile."""
    from . import retarget_profile as RP
    prof = RP.profile_of({"profile": profile}) if profile else None
    role = PART_ROLE.get(part or "")
    if prof is None or role is None:
        return np.eye(3)
    a = prof["adjust"].get(role, RP.ADJUST_DEFAULT)
    length = a["length"] * (prof["arm_length"] if role in RP.ARMS else prof["leg_length"] if role in RP.LEGS else 1.0)
    _mu, axes = _axes(np.asarray(cloud, float))
    d = axes[0] / max(float(np.linalg.norm(axes[0])), 1e-9)
    M = a["girth"] * np.eye(3) + (length - a["girth"]) * np.outer(d, d)
    M = M @ np.diag(a["scale"])
    if role == "head":
        M = M * prof["head"]
    if role in ("hip", "chest"):
        M = np.diag([prof["torso_width"], 1.0, 1.0]) @ M
    return M


def fit_blob(template: bytes, seg, name: str = "", profile: dict | None = None) -> tuple[bytes, dict]:
    """One donor segment (pos, nrm, tris in donor space) -> the part's blob (same size): principal-axis fit onto the
    part's decoded cloud (`fit_points`), the retarget profile's size adjustments about the cloud's centroid
    (`profile_matrix`), centre subtracted, shrunk into the s16 range if needed, vertex-clustered down to the largest
    count whose actual encoding fits, triangles dealt to the materials by region."""
    shape = ct.read_shape(template, name)
    cloud = np.asarray(shape.positions(), float)
    P = np.asarray(seg[0], float)
    N = np.asarray(seg[1], float) if len(seg[1]) == len(seg[0]) else np.zeros_like(P)
    T = [tuple(map(int, t)) for t in seg[2]]
    if len(cloud) < 3 or len(P) < 3 or not T:
        raise ValueError(f"{name}: empty donor segment or target cloud")
    centre = np.asarray(shape.centre, float)
    fitted, nrm = fit_points(P, N, cloud)
    c = classify(name) if name else None
    M = profile_matrix(c["part"] if c else None, cloud, profile)
    if not np.allclose(M, np.eye(3)):
        mu = cloud.mean(0)
        fitted = (fitted - mu) @ M.T + mu
        nrm = nrm @ np.linalg.inv(M)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    local = fitted - centre
    over =float((np.abs(local).max(0) / (representable(template, shape.frac()) * 0.999)).max())
    if over > 1:
        mu = cloud.mean(0) - centre
        local = mu + (local - mu) / over
    regions = [c - centre for c in material_regions(template, name)]
    attrs = [a for a, o in ct.ATTR_WORDS if ct._u32(template, o)]
    vmax, _dl = ct.part_budgets(template, attrs)
    tried: dict[int, tuple | None] = {}

    def attempt(k: int):
        if k not in tried:
            mp, mn, mt = ct._cluster(local, nrm, T, k)
            res = None
            if mt:
                try:
                    blob = ct.encode_shape(template, mp, mn, mt, name, chunks=deal_materials(mp, mt, regions))
                    res = (blob, len(mp), len(mt))
                except ValueError:
                    res = None
            tried[k] = res
        return tried[k]

    hi = max(3, min(vmax, len(local)))
    best = attempt(hi)
    if best is None:
        # the smallest k that keeps a triangle (very few clusters can collapse every donor triangle), then the
        # largest k that still encodes (sizes grow with k)
        lo = next((k for k in range(3, min(hi, 48)) if attempt(k) is not None), None)
        if lo is None:
            raise ValueError(f"{name}: no vertex count up to {min(hi, 48) - 1} keeps a donor triangle that fits the "
                             f"part blob ({len(template)} bytes)")
        best = tried[lo]
        while hi - lo > 1:                                   # largest k that encodes (sizes grow with k)
            mid = (lo + hi) // 2
            r = attempt(mid)
            if r is None:
                hi = mid
            else:
                lo, best = mid, r
    blob, nv, nt = best
    return blob, {"verts": nv, "tris": nt, "size": len(template), "donor_tris": len(T), "shrunk": round(1 / max(over, 1.0), 3)}


def hidden_blob(template: bytes, name: str = "") -> bytes:
    """The part drawn as nothing: three coincident vertices at the part's own centre and one zero-area triangle per
    material record (every display list stays non-empty)."""
    pairs = ct._material_list_slots(template, ct._u32(template, 0x110), ct._u32(template, 0x118),
                                    ct._u32(template, 0x11C) or len(template))
    tri = (0, 1, 2)
    return ct.encode_shape(template, np.zeros((3, 3)), np.tile([0.0, 1.0, 0.0], (3, 1)), [tri], name,
                           chunks=[[tri] for _ in pairs])


def swap_people(bank: bytes, segs: dict, groups, progress=None, hide_accessories: bool = True,
                profile: dict | None = None) -> tuple[bytes, dict]:
    """Every part blob of the bank groups `groups` -> the donor (main parts, sl_ twins and hand poses) or hidden
    (accessory sub-parts). The bank keeps every name, order and blob size. segs: gbox.crazy_taxi.donor_segments
    ({part: (pos, nrm, tris)}). Returns (new bank, {blob name: stats})."""
    groups = set(groups)
    todo = [(n, o, s, c) for n, o, s in ct.read_bank(bank) for c in [classify(n)] if c and c["group"] in groups]
    if not todo:
        raise ValueError(f"no {', '.join(sorted(groups))} parts in the bank")
    out = bytearray(bank)
    stats: dict[str, dict] = {}
    cache: dict[tuple, tuple[bytes, dict]] = {}
    for i, (n, o, s, c) in enumerate(todo):
        template = bytes(bank[o:o + s])
        key = (hashlib.sha1(template).digest(), c["part"], c["accessory"] and hide_accessories)
        if key not in cache:
            if c["accessory"] and hide_accessories:
                cache[key] = (hidden_blob(template, n), {"hidden": True, "size": s})
            else:
                seg = segs.get(c["part"])
                if seg is None:
                    raise ValueError(f"{n}: the donor has no segment for the {c['part']} part")
                cache[key] = fit_blob(template, seg, n, profile)
        blob, st = cache[key]
        if len(blob) != s:
            raise ValueError(f"{n}: encoded {len(blob)} bytes for a {s}-byte blob")
        out[o:o + s] = blob
        stats[n] = dict(st, part=c["part"], group=c["group"], pose=c["pose"], lod=c["lod"])
        if progress:
            progress(10 + 75 * (i + 1) / len(todo), f"Fitting {n}")
    return bytes(out), stats


def donor_segments(glb, joint_roles: dict) -> dict:
    """A library model + its rig roles -> {part: (pos, nrm, tris)} (gbox.crazy_taxi.donor_segments)."""
    return ct.donor_segments(Path(glb), ct.resolve_roles(joint_roles), dict(joint_roles))


def swap_bank(bank: bytes, glb, joint_roles: dict, slot: Slot, progress=None,
              profile: dict | None = None) -> tuple[bytes, dict]:
    """The whole thing for one slot: donor segments, every group of the slot swapped. Returns (bank, report).
    profile: the operator's retarget profile (size adjustments per part, gbox.retarget_profile)."""
    from . import fit_events as FE
    progress = progress or (lambda p, m: None)
    progress(5, "Cutting the donor into body segments")
    FE.auto_model(glb)
    segs = donor_segments(glb, joint_roles)
    if FE.active():                                       # the donor as loaded, then cut into the game's body parts
        cut = [{"pos": np.asarray(v[0], float), "tris": np.asarray(v[2], int).reshape(-1, 3)} for v in segs.values()]
        whole = [{"pos": np.concatenate([c["pos"] for c in cut]),
                  "tris": np.concatenate([c["tris"] + sum(len(x["pos"]) for x in cut[:i]) for i, c in enumerate(cut)])}]
        FE.stage("scale", data={"donor_height": FE.height(cut), "donor_vertices": int(len(whole[0]["pos"])),
                                "donor_triangles": FE.triangles(cut), "donor_roles": len(joint_roles),
                                "fit": "each part to the stock part's extent (bone-local parts, no global scale)"},
                 prims=whole)
    FE.stage("retarget", data={"segments": len(segs), "triangles": int(sum(len(v[2]) for v in segs.values())),
                               "fit": "principal axes per part"}, prims=cut if FE.active() else None)
    grp = people(ct.read_bank(bank))
    missing = [g for g in slot.groups if g not in grp]
    if missing:
        raise ValueError(f"{BANK} has no {', '.join(missing)} parts")
    FE.stage("proportion", "done" if profile else "skipped",
             {"profile": "size adjustments per part" if profile else "none"})
    FE.stage("weights", data={"mode": "rigid per part (each part rides its own bone)", "limbs": len(segs),
                              "vertices": int(sum(len(v[0]) for v in segs.values())),
                              "per_limb": {p: int(len(v[0])) for p, v in sorted(segs.items(), key=lambda x: -len(x[1][0]))}})
    new_bank, stats = swap_people(bank, segs, slot.groups, progress, profile=profile)
    fitted = [v for v in stats.values() if not v.get("hidden")]
    per_part: dict[str, int] = {}                         # a part's twins / LODs share its donor segment: once each
    for v in fitted:
        per_part[v["part"]] = max(per_part.get(v["part"], 0), int(v["tris"]))
    FE.stage("decimate", data={"from": int(sum(len(segs[p][2]) for p in per_part if p in segs)),
                               "triangles": int(sum(per_part.values())), "parts": len(per_part), "blobs": len(fitted),
                               "budget": "each stock blob's own size (vertex clustering)",
                               "shrunk": min((v["shrunk"] for v in fitted), default=1.0)})
    FE.stage("encode", data={"blobs": len(stats), "fitted": len(fitted),
                             "bytes": int(sum(v["size"] for v in stats.values())), "relocated": False,
                             "where": "every blob rewritten in place at its own size",
                             "triangles": int(sum(v["tris"] for v in fitted)),
                             "vertices": int(sum(v["verts"] for v in fitted))})
    report = {"slot": slot.slot, "groups": list(slot.groups), "blobs": len(stats), "fitted": len(fitted),
              "hidden": len(stats) - len(fitted), "triangles": sum(v["tris"] for v in fitted),
              "vertices": sum(v["verts"] for v in fitted),
              "segments": {p: {"verts": len(v[0]), "tris": len(v[2])} for p, v in segs.items()},
              "source_bank": hashlib.sha256(bank).hexdigest()[:16]}
    return new_bank, report | {"parts": stats}


# ----------------------------------------------------------------------------------------------- mod + tool

def build_mod(cfg, game: dict, iso: Path, bank: bytes, name: str, slot: Slot, report: dict, slug: str = "",
              progress=None) -> dict:
    """A Crazy Taxi file mod (cache/mods/<game>/<name>): a copy of the disc image with ct/polDC0.all replaced in its
    own slot (same size); the marker keeps the slot and the fit report. The source image is never written."""
    b = ct.build_mod(cfg, game, iso, bank, name, f"Crazy Taxi {name}.iso", progress=progress)
    marker = Path(b["dir"]) / ".gbox-mod.json"
    try:
        m = json.loads(marker.read_text())
    except (OSError, ValueError):
        m = {"name": name, "game_id": game["game_id"], "image": Path(b["image"]).name, "files": [BANK]}
    m |= {"character": slug, "slot": slot.slot, "replaces": slot.describe(),
          "report": {k: v for k, v in report.items() if k != "parts"}}
    marker.write_text(json.dumps(m))
    return b | {"report": report}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Crazy Taxi (GC): the library character as the slot's driver / people (mod ct_<slug>...),
    built on the control plane (where the collection is) and launched on the requesting session's node."""
    from . import characters as C, filemods
    gid = game["game_id"]
    slot = parse_slot(inp.slot, default_driver(meta, gid))
    name = mod_name(meta["slug"], slot)
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = None
    if inp.rebuild or not have:
        joint_roles = dict((meta.get("rig") or {}).get("roles") or {})
        ct.resolve_roles(joint_roles)                       # a missing body role fails before any disc work
        if C.library_root(ctx.config).is_dir():
            from .gcdisc import GCDisc
            glb = C._local_or_fetch(ctx, meta, meta["model"])
            iso = C._gc_iso(ctx, game)
            disc = GCDisc(iso)
            if disc.game_id != ct.DISC_ID:
                raise ValueError(f"expected {ct.DISC_ID}, got {disc.game_id}")
            bank = disc.read(BANK)
            disc.f.close()
            from .retarget_profile import profile_of
            new_bank, report = swap_bank(bank, glb, joint_roles, slot, ctx.progress,
                                         profile=profile_of((meta.get("rig") or {}).get("scale")))
            built = build_mod(ctx.config, game, iso, new_bank, name, slot, report, meta["slug"], ctx.progress)
            C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                   json={"game_id": gid, "slot": slot.slot, "mod": name, "nodes": [C.HOST_OS],
                         "notes": f"replaces {slot.describe()}; {report['fitted']} parts fitted, {report['hidden']} "
                                  f"accessory sub-parts hidden, {report['triangles']} triangles; source bank "
                                  f"{report['source_bank']}..."})
        else:
            cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"
                       and w.get("online")), None)
            ctx.progress(10, "Building the Crazy Taxi mod on the control-plane node (the collection lives there)")
            j = C._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid,
                                           "rebuild": inp.rebuild, "launch": False, "slot": slot.slot}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "slot": slot.slot,
                        "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "slot": slot.slot, "build": built, "replaces": slot.describe()}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else "idle"
    ctx.progress(90, f"Launching Crazy Taxi with {meta['name']} as {slot.label} (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    t0 = time.time()
    while lj.get("state") in ("queued", "running") and time.time() - t0 < 1800:
        time.sleep(2)
        lj = C._api(ctx, "GET", f"/api/jobs/{lj['id']}")
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"Crazy Taxi is running with {meta['name']} as {slot.label} (mod {name}). Pick {slot.label} on the driver "
           f"select screen to see it." if slot.kind == "driver" else
           f"Crazy Taxi is running with {meta['name']} as {slot.describe()} (mod {name}).") if ok else \
        f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}"
    return res | {"status": ("built+launched" if built else "launched") if ok else "launch " + str(lj.get("state")),
                  "launch": launch, "message": msg}


def main(argv=None):
    """python -m gbox.crazy_taxi_swap <iso|polDC0.all> <character dir (meta.json + model)> <slot> <out dir>: writes the
    swapped polDC0.all and report.json (no disc image); for checking a fit without the control plane."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", help="the GameCube ISO, or a loose ct/polDC0.all")
    ap.add_argument("character", help="library entry folder (meta.json + model)")
    ap.add_argument("slot")
    ap.add_argument("out", type=Path)
    a = ap.parse_args(argv)
    src = Path(a.source)
    if src.suffix.lower() in (".iso", ".gcm"):
        from .gcdisc import GCDisc
        bank = GCDisc(src).read(BANK)
    else:
        bank = src.read_bytes()
    meta = json.loads((Path(a.character) / "meta.json").read_text())
    slot = parse_slot(a.slot, groups=people(ct.read_bank(bank)))
    t0 = time.time()
    new_bank, report = swap_bank(bank, Path(a.character) / meta["model"], meta["rig"]["roles"], slot,
                                 lambda p, m: print(f"{p:3.0f}% {m}"))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "polDC0.all").write_bytes(new_bank)
    (a.out / "report.json").write_text(json.dumps(report | {"seconds": round(time.time() - t0, 1)}, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k not in ("parts", "segments")}, indent=1),
          f"\n{round(time.time() - t0, 1)} s")


if __name__ == "__main__":
    main()
