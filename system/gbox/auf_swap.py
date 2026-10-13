"""007: Agent Under Fire (GameCube, GW7E69; gBox game 65b7187589166b26): collection characters in place of Bond, the
enemies, the bosses, the other people and the multiplayer bots, written into a rebuilt disc image in a mod dir.

Where the characters live (read from the owned disc, docs/auf_writer.md): every level is one ``maps/*.ngc`` package
(gbox.auf_ngc).  Its ``restable`` file system holds the models (``models/actors/**.gcm``) and the entity definitions
(``models/*.men``, compiled scripts whose u16 tokens index the level's ``script_dictionary``):

    mp_player_bondcombat.men: setup { path models/actors  lod_model { Bond/Bond_Combat_l.o3d }
                                      lod_head { ActorHeads/bond_head_l.o3d } }  init { server { classname
                                      DeathmatchPlayer } }  animations mp_player_male

so each character is a body model (one per LOD, ``_h``/``_m``/``_l`` with switch distances) plus a head model, and the
``classname`` says who it is: ``Player`` (Bond in the missions), ``actor`` (enemies, bosses, allies, hostages, Bond in
cut scenes), ``DeathmatchPlayer`` (the 16 multiplayer characters the bots and players pick).  ``level_cast`` reads
that for any level; CAST below is the snapshot of all 38 levels (45 body models).

How a donor goes in (per level, per body model):
  * target skeleton = the body model's own bones and rest pose; body roles from its topology (auf_gcm.auto_roles,
    127/127 shipped actor models give all 18 roles);
  * the donor (a rigged collection character, meta rig.roles) is fitted with gbox.doa2_weighted_retarget (skin
    weights kept) and reduced to the 2-bone blends the format has; a static T-pose donor without a skeleton (the
    Def Jam Vendetta GC wrestlers) is rigged to the slot by ``fit_static``; quadric decimation to the slot's budget;
  * the whole donor, head included, is encoded into the body model (auf_gcm.encode_gcm: the body's skeleton, hit
    boxes and animation bindings stay, so every native animation still drives it) and each head model only those
    bodies use becomes an invisible stub; a head that a body outside the build also wears is kept and the donor's
    own head is left out instead;
  * the donor's textures are packed into the textures only the replaced models used (one group / one pass CMPR
    shaders nobody else draws with), written over their own bytes at their own size and mip count: no texture record
    is added (the game's table is fixed at 512 entries) and the level's texture memory does not change; the donor's
    sections use those textures' shader names.
The rebuilt levels go into a copy of the disc image (gbox.filemods.build_image: in its FST slot when it fits, else
moved after the last file), so the owned image is never written.

Slots (``characters op=use slot=...``): ``player`` (every Bond body: missions, cut scenes, multiplayer), ``enemies``
(the mission henchmen), ``bosses``, ``npcs`` (allies, hostages, leaders), ``bots`` (every multiplayer character),
``all``, ``model:<body>`` (one body model everywhere, e.g. model:thug_orchid) and ``cast`` with ``pairs`` =
[{target, donor}] (target = a body, a group name or empty; donors without a target are dealt over the remaining
bodies in a seeded shuffle, so "the whole cast as WWF wrestlers" is one deterministic build).

    python -m gbox.auf_swap plan --slot cast --donor sd2_the_rock --donor nm_kane
    python -m gbox.auf_swap build <disc .gcz/.iso> <library dir> <out dir> --slot player --donor sd2_the_rock
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import auf_gcm as G
from . import auf_ngc as ngc
from . import auf_ngc_writer as NW

GAME_ID = "65b7187589166b26"
GAME_IDS = {GAME_ID: "007 - Agent Under Fire (USA)"}
DISC_ID = "GW7E"
BUDGET_FACTOR = 1.2           # donor triangles <= 1.2 x (body + stubbed heads) of the slot's own LOD
MIN_BUDGET = 300
A2R = np.array([[0.0, 1, 0], [0, 0, 1], [1, 0, 0]])   # AUF (x front, y left, z up) -> retarget frame (left, up, front)

# --------------------------------------------------------------------------------------------- the cast (snapshot)
# body key -> (display name, kind).  kind: player | enemy | boss | npc | bot (multiplayer only).
NAMES = {
    "bond_tux": ("Bond (tuxedo)", "player"), "bond_combat": ("Bond (combat)", "player"),
    "bond_graysuit": ("Bond (grey suit)", "player"), "bond_jetpack": ("Bond (jetpack)", "player"),
    "henchmen_vest": ("Henchman (vest)", "enemy"), "thug_alpine_inside": ("Alpine guard (inside)", "enemy"),
    "thug_alpine_outside": ("Alpine guard (outside)", "enemy"), "thug_carrier": ("Carrier thug", "enemy"),
    "thug_oilrig": ("Oil rig thug", "enemy"), "thug_orchid": ("Orchid thug", "enemy"),
    "thug_uwb": ("Underwater base thug", "enemy"), "superthug_body": ("Super thug", "enemy"),
    "biosuit": ("Biosuit guard", "enemy"),
    "malprave_suit": ("Malprave (suit)", "boss"), "malprave_gown": ("Malprave (gown)", "boss"),
    "zero": ("Nigel Bloch", "boss"), "zero_jetpack": ("Nigel Bloch (jetpack)", "boss"),
    "griffin_body": ("Griffin", "boss"), "jackal_body": ("Jackal", "boss"), "twins": ("The twins", "boss"),
    "zoe_body": ("Zoe Nightshade", "npc"), "natalya_body": ("Natalya", "npc"), "showergirl_body": ("Shower girl", "npc"),
    "host1": ("Hostage 1", "npc"), "hostage2": ("Hostage 2", "npc"), "m_suit": ("Hostage 3", "npc"),
    "cigar_skirt": ("Hostage 4", "npc"), "bond_shirt": ("Male hostage", "npc"),
    "g8canada_body": ("G8 Canada", "npc"), "g8france_body": ("G8 France", "npc"), "g8germany_body": ("G8 Germany", "npc"),
    "g8italy_body": ("G8 Italy", "npc"), "g8japan_body": ("G8 Japan", "npc"), "g8russia_body": ("G8 Russia", "npc"),
    "g8uk_body": ("G8 UK", "npc"), "g8us_body": ("G8 USA", "npc"), "scientist_male": ("Scientist", "npc"),
    "missileofficer_body": ("Missile officer", "npc"), "embassy_guard_body": ("Embassy guard", "npc"),
    "rigdiver_wetsuit": ("Rig diver (wetsuit)", "npc"), "vip_body": ("VIP (escort)", "npc"),
    "rigdiver_body": ("Rig diver (multiplayer)", "bot"), "thug_oilrig_mp": ("Oil rig thug (multiplayer)", "bot"),
    "twins_mp": ("The twins (multiplayer)", "bot"), "zero_body": ("Bloch (multiplayer)", "bot"),
}
MP_MAPS = ("dm1", "dm10", "dm11", "dm11_4p", "dm2", "dm2_4p", "dm3", "dm4", "dm4_4p", "dm5", "dm6", "dm7", "dm8", "dm9",
           "dm9_4p", "dmescort", "escort4p")
MP_KEYS = ("bond_combat", "bond_tux", "griffin_body", "henchmen_vest", "jackal_body", "malprave_suit", "rigdiver_body",
           "superthug_body", "thug_alpine_inside", "thug_carrier", "thug_oilrig_mp", "thug_orchid", "thug_uwb", "twins_mp",
           "zero_body", "zoe_body")
# mission levels -> body keys used by 'actor' / 'Player' entities there (from every level's .men files)
MISSION_CAST = {
    "alp1_1": "bond_graysuit bond_tux thug_alpine_inside twins",
    "alp1_2": "bond_tux superthug_body thug_alpine_inside",
    "alp2_1": "bond_combat bond_tux thug_alpine_outside zoe_body",
    "alp2_2": "bond_tux g8canada_body g8france_body g8germany_body g8italy_body g8japan_body g8russia_body g8uk_body "
              "g8us_body thug_alpine_inside thug_alpine_outside",
    "alp2_3": "bond_combat bond_tux malprave_suit zero zero_jetpack zoe_body",
    "carrier1": "biosuit bond_combat bond_tux superthug_body thug_carrier zoe_body",
    "carrier2": "bond_tux missileofficer_body superthug_body thug_carrier zoe_body",
    "emstel_1": "bond_combat bond_tux embassy_guard_body griffin_body malprave_gown",
    "m6_1": "bond_graysuit bond_tux henchmen_vest scientist_male showergirl_body",
    "m6_2": "bond_shirt bond_tux cigar_skirt henchmen_vest host1 hostage2 jackal_body m_suit natalya_body",
    "m6_3": "bond_tux henchmen_vest jackal_body",
    "orc_1": "bond_combat bond_tux g8russia_body thug_orchid",
    "orc_2": "bond_combat bond_tux thug_orchid",
    "orc_3": "bond_tux thug_orchid",
    "orc_4": "bond_combat bond_tux thug_orchid zero zoe_body",
    "rig_1": "bond_jetpack bond_tux thug_oilrig zero",
    "rig_2": "bond_combat bond_tux rigdiver_wetsuit superthug_body thug_oilrig zero",
    "uwb_2a": "biosuit bond_combat bond_tux superthug_body thug_uwb",
    "uwb_2aa": "biosuit bond_tux superthug_body thug_uwb",
    "uwb_2b": "bond_combat bond_tux thug_uwb zoe_body",
}


def level_keys() -> dict[str, dict[str, str]]:
    """{level: {body key: 'actor' | 'deathmatchplayer'}} for all 37 levels with people (frontend has none)."""
    out = {lv: {k: "actor" for k in ks.split()} for lv, ks in MISSION_CAST.items()}
    for lv in MP_MAPS:
        out[lv] = {k: "deathmatchplayer" for k in MP_KEYS}
        if "escort" in lv:
            out[lv]["vip_body"] = "actor"
    return out


GROUPS = ("player", "enemies", "bosses", "npcs", "bots", "all")
GROUP_KINDS = {"player": ("player",), "enemies": ("enemy",), "bosses": ("boss",), "npcs": ("npc",)}
SLOT_HELP = ("player | enemies | bosses | npcs | bots | all | model:<body> (" + ", ".join(sorted(NAMES)) +
             ") | cast (pairs [{target, donor}])")


def body_key(o3d: str) -> str:
    """'Bond/Bond_Combat_l.o3d' -> 'bond_combat' (the LOD suffix dropped)."""
    base = Path(o3d.replace("\\", "/")).name.lower()
    base = base[:-4] if base.endswith((".o3d", ".gcm")) else base
    return re.sub(r"_(h|m|l)$", "", base)


def select(slot: str, levels: dict | None = None) -> set[tuple[str, str]]:
    """A slot -> the (level, body key) pairs it replaces."""
    levels = levels or level_keys()
    s = (slot or "player").strip().lower()
    out = set()
    if s.startswith("model:"):
        key = body_key(s[6:])
        if key not in NAMES:
            raise ValueError(f"unknown AUF body {s[6:]!r}; bodies: {', '.join(sorted(NAMES))}")
        return {(lv, k) for lv, ks in levels.items() for k in ks if k == key}
    if s in ("all", "cast", "everyone", "roster"):
        return {(lv, k) for lv, ks in levels.items() for k in ks}
    if s == "bots":
        return {(lv, k) for lv, ks in levels.items() for k, c in ks.items() if c == "deathmatchplayer"}
    if s == "player":
        return {(lv, k) for lv, ks in levels.items() for k in ks if NAMES.get(k, ("", ""))[1] == "player"}
    if s in GROUP_KINDS:
        kinds = GROUP_KINDS[s]
        return {(lv, k) for lv, ks in levels.items() for k, c in ks.items()
                if c == "actor" and NAMES.get(k, ("", ""))[1] in kinds}
    if s in NAMES:
        return select("model:" + s, levels)
    raise ValueError(f"unknown 007 Agent Under Fire slot {slot!r}: {SLOT_HELP}")


def is_slot(slot: str) -> bool:
    s = (slot or "player").strip().lower()
    return s in GROUPS or s in ("cast", "roster", "everyone") or s.startswith("model:") or s in NAMES


def plan_cast(pairs, seed: str = "", levels: dict | None = None) -> dict[tuple[str, str], str]:
    """[(target, donor)] -> {(level, body key): donor}.  A target is a body key, model:<body>, a group (player, enemies,
    bosses, npcs, bots, all) or '' (dealt).  Fixed targets win over groups (a later, narrower pair overrides an earlier
    group); donors without a target are dealt over every body nobody named, in a shuffle that depends only on ``seed``
    and the donors (repeating when there are fewer donors than bodies)."""
    levels = levels or level_keys()
    plan: dict = {}
    free: list = []
    ranked = []
    for target, donor in pairs:
        if not donor:
            raise ValueError("every cast entry needs a donor character")
        t = (target or "").strip().lower()
        if not t:
            free.append(donor)
            continue
        sel = select(t, levels)
        if not sel:
            raise ValueError(f"{target!r} selects no character")
        ranked.append((0 if t in GROUPS else 1, sel, donor))
    for _rank, sel, donor in sorted(ranked, key=lambda r: r[0]):
        for lk in sel:
            plan[lk] = donor
    if free:
        keys = sorted({k for lv, ks in levels.items() for k in ks} - {k for _lv, k in plan})
        rng = random.Random(f"auf-cast:{seed}:{','.join(free)}")
        rng.shuffle(keys)
        pool = list(free)
        rng.shuffle(pool)
        deal = {k: pool[i % len(pool)] for i, k in enumerate(keys)}
        for lv, ks in levels.items():
            for k in ks:
                if (lv, k) not in plan and k in deal:
                    plan[(lv, k)] = deal[k]
    if not plan:
        raise ValueError("the cast plan replaces nobody")
    return plan


def roster() -> list[dict]:
    """The writer's slots as roster entries (kind "slot": listed by characters op=collect, never extracted)."""
    lv = level_keys()
    out = []
    for key, (name, kind) in sorted(NAMES.items(), key=lambda kv: (kv[1][1], kv[0])):
        maps = sorted(l for l, ks in lv.items() if key in ks)
        out.append({"key": f"model:{key}", "slug": f"auf_{key}", "name": f"{name} (007 Agent Under Fire)",
                    "aliases": [name, key], "kind": "slot", "slot": f"model:{key}", "slot_kind": kind, "collect": False,
                    "writer": "gbox.auf_swap", "levels": maps})
    return out


def cast_slots() -> list[dict]:
    """The cast menu (characters op=collect "slots", gbox.char_coverage.cast_slots): the groups, then every body."""
    lv = level_keys()
    out = []
    for g, text in (("player", "Bond (every outfit, missions + multiplayer)"),
                    ("enemies", "every mission henchman"), ("bosses", "the bosses"),
                    ("npcs", "allies, hostages and the G8 leaders"), ("bots", "every multiplayer character (the bots)"),
                    ("all", "everyone"), ("cast", "the whole cast from pairs [{target, donor}], the rest dealt at random")):
        n = len({k for _l, k in select("all" if g == "cast" else g, lv)})
        out.append({"slot": g, "name": text, "kind": "player" if g == "player" else "group", "bodies": n,
                    "writer": "gbox.auf_swap"})
    for r in roster():
        out.append({"slot": r["slot"], "name": r["name"], "kind": r["slot_kind"], "aliases": r["aliases"],
                    "levels": len(r["levels"]), "writer": r["writer"]})
    return out


# --------------------------------------------------------------------------------------------- a level's cast

def script_strings(pkg: "ngc.NgcPackage") -> list[str]:
    d = next((r for r in pkg.resources() if r.name.endswith("script_dictionary")), None)
    if d is None:
        return []
    b = pkg.table[d.offset:d.offset + d.size]
    return [s.decode("latin-1") for s in b[0x20:].split(b"\0")]


def men_tokens(men: bytes, strs: list[str]) -> list[str]:
    """A compiled .men (``CS`` header, u16 dictionary tokens from +0x24, 0xFFFF = separator) -> its words."""
    if men[:2] != b"CS":
        raise ValueError("not a compiled entity script")
    words = struct.unpack_from(">%dH" % ((len(men) - 0x24) // 2), men, 0x24)
    return [strs[w] if w < len(strs) else "?%x" % w for w in words if w != 0xFFFF]


def _block_words(toks, key):
    out = []
    for i, x in enumerate(toks):
        if x == key and i + 1 < len(toks) and toks[i + 1] == "{":
            j = i + 2
            while j < len(toks) and toks[j] != "}":
                out.append(toks[j])
                j += 1
    return out


@dataclass
class Character:
    men: str
    cls: str
    key: str
    bodies: list = field(default_factory=list)     # restable names, one per LOD
    heads: list = field(default_factory=list)
    anim: str = ""


def level_cast(pkg: "ngc.NgcPackage") -> list[Character]:
    """Every character entity of a level (classes Player / actor / DeathmatchPlayer) with its body and head models."""
    strs = script_strings(pkg)
    have = {r.name.lower() for r in pkg.resources()}
    out = []
    for r in pkg.resources():
        if not r.name.endswith(".men"):
            continue
        try:
            toks = men_tokens(pkg.table[r.offset:r.offset + r.size], strs)
        except (ValueError, struct.error):
            continue
        if "classname" not in toks or "lod_model" not in toks:
            continue
        cls = toks[toks.index("classname") + 1].lower()
        if cls not in ("player", "actor", "deathmatchplayer"):
            continue
        path = toks[toks.index("path") + 1] if "path" in toks else "models/actors"

        def gcms(words):
            return [n for n in (f"{path}/{w}".lower().replace("\\", "/")[:-4] + ".gcm" for w in words
                                if w.lower().endswith(".o3d")) if n in have]
        bodies = gcms(_block_words(toks, "lod_model"))
        if not bodies:
            continue
        out.append(Character(r.name, cls, body_key(bodies[0]), bodies, gcms(_block_words(toks, "lod_head")),
                             toks[toks.index("animations") + 1] if "animations" in toks else ""))
    return out


# --------------------------------------------------------------------------------------------- donor fitting

@dataclass
class Donor:
    slug: str
    name: str
    glb: Path
    roles: dict
    rig: dict = None
    mats: list = None                              # [(material key, rgb image or None, colour, texel area)]
    fits: dict = field(default_factory=dict)


def load_donor(slug: str, glb, roles: dict, name: str = "", static_ok: bool = True) -> Donor:
    """A collection character ready to fit: a rigged one (meta rig.roles with hip and head) through
    gbox.doa2_weighted_retarget, or - when it has no skeleton (e.g. the Def Jam Vendetta GC wrestlers, static T-pose
    meshes) and ``static_ok`` - as a static T-pose mesh that ``fit_static`` rigs to the slot's skeleton."""
    from . import doa2_weighted_retarget as WR
    roles = dict(roles or {})
    d = Donor(slug, name or slug, Path(glb), roles)
    if {"hip", "head"} <= roles.keys():
        d.rig = WR.load_rig(Path(glb), roles)
    elif static_ok:
        d.rig = load_static(Path(glb))
    else:
        raise ValueError(f"{slug}: the collection entry has no hip/head rig roles (not retargetable)")
    d.mats = donor_materials(d.rig["prims"])
    return d


def load_static(path: Path) -> dict:
    """Every triangle primitive of a glTF in world space (glTF frame: Y up, the character facing +Z, its left +X)."""
    from .re4gc_models import _gltf_load, _node_world
    gl, acc, image = _gltf_load(path)
    wn = _node_world(gl)
    cache, prims = {}, []
    for ni, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd:
            continue
        M = wn[ni]
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            if pr.get("mode", 4) != 4:
                continue
            a = pr["attributes"]
            p = acc(a["POSITION"]).astype(float) @ M[:3, :3].T + M[:3, 3]
            n = (acc(a["NORMAL"]).astype(float) if "NORMAL" in a else np.tile([0, 1.0, 0], (len(p), 1))) @ \
                np.linalg.inv(M[:3, :3])
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
            uv = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(p), 2))
            tris = acc(pr["indices"]).reshape(-1, 3).astype(int) if "indices" in pr else \
                np.arange(len(p) // 3 * 3).reshape(-1, 3)
            tex, color = None, (255, 255, 255, 255)
            if (mi := pr.get("material")) is not None:
                pbr = gl["materials"][mi].get("pbrMetallicRoughness", {})
                color = tuple(int(round(c * 255)) for c in pbr.get("baseColorFactor", [1, 1, 1, 1]))
                if (bct := pbr.get("baseColorTexture")) is not None:
                    if bct["index"] not in cache:
                        try:
                            cache[bct["index"]] = image(bct["index"])
                        except Exception:                  # noqa: BLE001 - a missing image: plain colour
                            cache[bct["index"]] = None
                    tex = cache[bct["index"]]
            prims.append({"pos": p, "nrm": n, "uv": uv, "tris": tris, "tex": tex, "color": color})
    if not prims:
        raise ValueError(f"{Path(path).name}: no triangles")
    return {"static": True, "prims": prims}


def _material_key(p):
    tex = p.get("tex")
    return (hashlib.sha1(np.ascontiguousarray(tex).tobytes()).hexdigest() if tex is not None else None,
            tuple(int(c) for c in p.get("color", (255, 255, 255, 255))[:3]))


def donor_materials(prims) -> list:
    """The donor's distinct materials: (key, opaque RGB image or None, colour factor, texel area for packing).
    Cut-out texels take the opaque texels' mean colour (AUF draws characters opaque)."""
    out, seen = [], set()
    for p in prims:
        k = _material_key(p)
        if k in seen:
            continue
        seen.add(k)
        tex = p.get("tex")
        if tex is not None:
            t = np.asarray(tex, np.uint8)
            if t.ndim == 2:
                t = np.stack([t] * 3 + [np.full_like(t, 255)], -1)
            if t.shape[2] == 3:
                t = np.concatenate([t, np.full(t.shape[:2] + (1,), 255, np.uint8)], -1)
            a = t[..., 3] >= 128
            if a.any() and not a.all():
                t = t.copy()
                t[~a, :3] = t[a, :3].mean(0).astype(np.uint8)
            tex = t[..., :3]
        area = int(tex.shape[0] * tex.shape[1]) if tex is not None else 64
        out.append((k, tex, tuple(p.get("color", (255, 255, 255, 255))[:3]), area))
    return out


def build_pages(mats: list, sizes: list[tuple[int, int]]) -> tuple[list, dict]:
    """Pack the donor's materials into texture pages of the given (w, h) sizes (the slot textures they will be written
    over, largest first): materials are dealt by texel area so every page carries a similar share of its own area,
    then laid out on a grid of tiles in each page.  -> ([RGBA page], {material key: (page, (x0, y0, tw, th), (w, h))})."""
    from PIL import Image
    pages = [[] for _ in sizes]
    load = [0.0] * len(sizes)
    for m in sorted(mats, key=lambda m: -m[3]):
        i = min(range(len(sizes)), key=lambda j: (load[j] + m[3]) / (sizes[j][0] * sizes[j][1]))
        pages[i].append(m)
        load[i] += m[3]
    images, layout = [], {}
    for pi, ((w, h), ms) in enumerate(zip(sizes, pages)):
        img = np.zeros((h, w, 4), np.uint8)
        img[..., 3] = 255
        if ms:
            cols = max(1, int(np.ceil(np.sqrt(len(ms) * w / h))))
            rows = int(np.ceil(len(ms) / cols))
            tw, th = w // cols, h // rows
            for i, (k, tex, color, _a) in enumerate(ms):
                x0, y0 = (i % cols) * tw, (i // cols) * th
                col = np.asarray(color, float) / 255
                if tex is None:
                    img[y0:y0 + th, x0:x0 + tw, :3] = (col * 255).astype(np.uint8)
                else:
                    r = np.asarray(Image.fromarray(np.ascontiguousarray(tex)).resize((tw, th), Image.BILINEAR), float)
                    img[y0:y0 + th, x0:x0 + tw, :3] = np.clip(r * col, 0, 255).astype(np.uint8)
                layout[k] = (pi, (x0, y0, tw, th), (w, h))
        images.append(img)
    return images, layout


def atlas_uvs(uv_tri: np.ndarray, tile: tuple, page: tuple) -> np.ndarray:
    """(3, 2) material UVs of one triangle -> page UVs: shifted by whole repeats into [0, 1] (clamped when the
    triangle itself spans more than one repeat) and mapped half a texel inside the material's tile."""
    x0, y0, tw, th = tile
    w, h = page
    u = np.asarray(uv_tri, float)
    u = u - np.floor(u.min(0))
    u = np.clip(u, 0.0, 1.0)
    return np.stack([(x0 + 0.5 + u[:, 0] * (tw - 1)) / w, (y0 + 0.5 + u[:, 1] * (th - 1)) / h], 1)


def target_of(body: bytes, head: bytes | None = None) -> dict:
    """The retarget target (gbox.doa2_weighted_retarget / sm64_swap frame: left +X, up +Y, front +Z) of a body model."""
    bones = ngc.skeleton(body)
    roles = G.auto_roles(bones)
    T = np.array([b["world_pos"] for b in bones]) @ A2R.T
    m = ngc.mesh(body)
    P = np.asarray(m["positions"], float)
    ground = float(P[:, 2].min()) if len(P) else 0.0
    if head:
        hp = np.asarray(ngc.mesh(head)["positions"], float)
        head_h = float(np.ptp(hp[:, 2])) if len(hp) else 0.15 * float(P[:, 2].max() - ground)
    else:
        head_h = 0.15 * float(P[:, 2].max() - ground)
    return {"T": T, "ground": ground, "head_h": head_h, "jmap": roles, "bones": bones, "joints": len(bones),
            "parent": [b["parent"] for b in bones]}


def skeleton_signature(body: bytes) -> str:
    bones = ngc.skeleton(body)
    return hashlib.sha1(json.dumps([(b["parent"], b["hash"], [round(v, 3) for v in b["world_pos"]])
                                    for b in bones]).encode()).hexdigest()[:16]


def fit_donor(donor: Donor, body: bytes, head: bytes | None) -> dict:
    """The donor on a body model's skeleton (cached per skeleton): AUF-frame positions/normals, 2-bone skin, material
    UVs and the material of every triangle."""
    from . import doa2_weighted_retarget as WR
    sig = skeleton_signature(body)
    if sig in donor.fits:
        return donor.fits[sig]
    if donor.rig.get("static"):
        donor.fits[sig] = fit_static(donor, body, head)
        return donor.fits[sig]
    tgt = target_of(body, head)
    prims, rep = WR.retarget(donor.rig, tgt, jmap=tgt["jmap"])
    Ps, Ns, UVs, Js, Ws, Fs, mkeys = [], [], [], [], [], [], []
    base = 0
    for src, p in zip(donor.rig["prims"], prims):
        n = len(p["pos"])
        Ps.append(np.asarray(p["pos"], float) @ A2R)
        Ns.append(np.asarray(p["nrm"], float) @ A2R)
        UVs.append(np.asarray(p["uv"], float))
        Jp, Wp = np.asarray(p["J"], int), np.asarray(p["W"], float)
        order = np.argsort(-Wp, axis=1)
        j0 = np.take_along_axis(Jp, order[:, :1], 1)[:, 0]
        w0 = np.take_along_axis(Wp, order[:, :1], 1)[:, 0]
        if Jp.shape[1] > 1:
            j1 = np.take_along_axis(Jp, order[:, 1:2], 1)[:, 0]
            w1 = np.take_along_axis(Wp, order[:, 1:2], 1)[:, 0]
        else:
            j1, w1 = np.full(n, -1), np.zeros(n)
        j1 = np.where((w1 > 0.02) & (j1 != j0), j1, -1)
        Js.append(np.stack([j0, j1], 1))
        Ws.append(np.where(j1 >= 0, w0 / np.maximum(w0 + w1, 1e-9), 1.0))
        tris = np.asarray(p["tris"], int).reshape(-1, 3)
        Fs.append(tris + base)
        mkeys += [_material_key(src)] * len(tris)
        base += n
    fit = {"P": np.concatenate(Ps), "N": np.concatenate(Ns), "UV": np.concatenate(UVs), "J": np.concatenate(Js),
           "W": np.concatenate(Ws), "F": np.concatenate(Fs), "mkeys": mkeys, "roles": tgt["jmap"],
           "report": {k: round(float(rep[k]), 4) for k in ("scale", "torso_up", "torso_down", "shoulder_widen",
                                                           "head_scale", "normals_flipped") if k in rep}}
    donor.fits[sig] = fit
    return fit


def _chain(bones, top: int, bottom: int) -> list[int]:
    """Bones from ``top`` down to ``bottom`` (bottom's ancestors up to top)."""
    out = [bottom]
    while out[-1] != top:
        p = bones[out[-1]]["parent"]
        if p < 0:
            raise ValueError("bone %d is not below %d" % (bottom, top))
        out.append(p)
    return out[::-1]


def _segments(bones, chain: list[int]) -> list[tuple[int, np.ndarray, np.ndarray]]:
    """(bone, start, end) per chain bone; the last bone continues half its parent's length."""
    W = [np.asarray(bones[i]["world_pos"], float) for i in chain]
    out = []
    for k, b in enumerate(chain):
        if k + 1 < len(chain):
            out.append((b, W[k], W[k + 1]))
        else:
            d = W[k] - W[k - 1] if k else np.array([0, 0, 1.0])
            out.append((b, W[k], W[k] + 0.5 * d))
    return out


def _nearest_segment(X: np.ndarray, segs) -> tuple[np.ndarray, np.ndarray]:
    """For points X (n,3): index of the nearest segment and the projection parameter t in [0, 1] on it."""
    best_d = np.full(len(X), np.inf)
    best_i = np.zeros(len(X), int)
    best_t = np.zeros(len(X))
    for i, (_b, a, b) in enumerate(segs):
        d = b - a
        L = float(d @ d) or 1e-9
        t = np.clip((X - a) @ d / L, 0, 1)
        dist = np.linalg.norm(X - (a + t[:, None] * d), axis=1)
        better = dist < best_d
        best_d[better], best_i[better], best_t[better] = dist[better], i, t[better]
    return best_i, best_t


def fit_static(donor: Donor, body: bytes, head: bytes | None) -> dict:
    """A static T-pose donor on a body model's skeleton (no donor skeleton needed).

    The donor (glTF frame: Y up, facing +Z, arms along X) is mapped piecewise onto the slot's rest pose, which is a
    T-pose on the disc too: heights through (ground, hip, shoulder, top of head), widths through (shoulder, finger tips)
    so the arms reach the slot's hands, depth by the height ratio.  Each vertex is then skinned to the nearest bone
    segment of its region (an arm beyond the shoulders, a leg below the hip by side, else the spine/neck/head chain),
    blended 50/50 with the parent bone within the first 15% of a segment."""
    bones = ngc.skeleton(body)
    roles = G.auto_roles(bones)
    tm = np.asarray(ngc.mesh(body)["positions"], float)
    hm = np.asarray(ngc.mesh(head)["positions"], float) if head else np.zeros((0, 3))
    allt = np.concatenate([tm, hm]) if len(hm) else tm
    wp = lambda r: np.asarray(bones[roles[r]]["world_pos"], float)          # noqa: E731
    g_t, top_t = float(allt[:, 2].min()), float(allt[:, 2].max())
    hip_t = float(wp("hip")[2])
    sh_t = float((wp("l_upper")[2] + wp("r_upper")[2]) / 2)
    sw_t = float((abs(wp("l_upper")[1]) + abs(wp("r_upper")[1])) / 2)
    reach_t = float(np.abs(tm[:, 1]).max())
    cx_t = float(wp("hip")[0])
    P = np.concatenate([p["pos"] for p in donor.rig["prims"]]) @ A2R      # glTF (left, up, front) -> AUF
    Nn = np.concatenate([p["nrm"] for p in donor.rig["prims"]]) @ A2R
    if np.ptp(P[:, 0]) > np.ptp(P[:, 1]):                                   # arms along the depth axis: turn 90 deg
        P, Nn = P[:, [1, 0, 2]] * [1, -1, 1], Nn[:, [1, 0, 2]] * [1, -1, 1]
    g_d, top_d = float(P[:, 2].min()), float(P[:, 2].max())
    H_d, H_t = max(top_d - g_d, 1e-6), max(top_t - g_t, 1e-6)
    reach_d = float(np.abs(P[:, 1]).max())
    arm = np.abs(P[:, 1]) > 0.6 * reach_d
    sh_d = float(np.median(P[arm, 2])) if arm.any() else g_d + (sh_t - g_t) / H_t * H_d
    hip_d = g_d + (hip_t - g_t) / H_t * H_d
    sw_d = reach_d * sw_t / max(reach_t, 1e-6)
    cx_d = float(np.median(P[~arm, 0])) if (~arm).any() else 0.0
    z = np.interp(P[:, 2], [g_d, hip_d, sh_d, top_d], [g_t, hip_t, sh_t, top_t])
    ay = np.abs(P[:, 1])
    y = np.sign(P[:, 1]) * np.where(ay <= sw_d, ay * sw_t / max(sw_d, 1e-6),
                                    sw_t + (ay - sw_d) * (reach_t - sw_t) / max(reach_d - sw_d, 1e-6))
    x = cx_t + (P[:, 0] - cx_d) * H_t / H_d
    X = np.stack([x, y, z], 1)
    torso = _segments(bones, _chain(bones, roles["hip"], roles["head"]))
    chains = {side: {"arm": _segments(bones, [roles[f"{side}_{r}"] for r in ("clav", "upper", "fore", "hand")]),
                     "leg": _segments(bones, [roles[f"{side}_{r}"] for r in ("thigh", "shin", "foot")])}
              for side in ("l", "r")}
    J = np.zeros((len(X), 2), int)
    Wt = np.ones(len(X))
    is_arm = (np.abs(y) > sw_t * 1.05) & (z > sh_t - 0.25 * (sh_t - hip_t))
    is_leg = ~is_arm & (z < hip_t - 0.02 * H_t)
    groups = [(is_arm & (y > 0), chains["l"]["arm"]), (is_arm & (y <= 0), chains["r"]["arm"]),
              (is_leg & (y > 0), chains["l"]["leg"]), (is_leg & (y <= 0), chains["r"]["leg"]),
              (~is_arm & ~is_leg, torso)]
    for sel, segs in groups:
        if not sel.any():
            continue
        si, t = _nearest_segment(X[sel], segs)
        bone = np.array([segs[i][0] for i in si])
        par = np.array([segs[i - 1][0] if i > 0 else -1 for i in si])
        blend = (t < 0.15) & (par >= 0)
        J[sel, 0] = bone
        J[sel, 1] = np.where(blend, par, -1)
        Wt[sel] = np.where(blend, 0.5, 1.0)
    Ns = Nn / np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
    Fs, mkeys, base = [], [], 0
    for p in donor.rig["prims"]:
        tris = np.asarray(p["tris"], int).reshape(-1, 3)
        Fs.append(tris + base)
        mkeys += [_material_key(p)] * len(tris)
        base += len(p["pos"])
    return {"P": X, "N": Ns, "UV": np.concatenate([p["uv"] for p in donor.rig["prims"]]), "J": J, "W": Wt,
            "F": np.concatenate(Fs), "mkeys": mkeys, "roles": roles,
            "report": {"static": True, "height_scale": round(H_t / H_d, 4), "reach": [round(reach_d, 3), round(reach_t, 3)],
                       "landmarks_t": [round(v, 2) for v in (g_t, hip_t, sh_t, top_t)]}}


def decimate(P: np.ndarray, F: np.ndarray, target: int) -> tuple[np.ndarray, np.ndarray]:
    """Quadric-error edge collapse (Garland-Heckbert: area-weighted face planes, open borders held by perpendicular
    planes) on the welded surface until ``target`` triangles remain; a collapse that flips a neighbouring face is
    skipped.  Split vertices (UV seams) move together, every corner keeps its own UV, normal and skin.
    -> (moved vertex positions, surviving faces)."""
    import heapq
    P = np.asarray(P, float)
    F = np.asarray(F, int)
    if len(F) <= target:
        return P, F
    ext = float(np.ptp(P, 0).max()) or 1.0
    key = np.round(P / (ext * 1e-5)).astype(np.int64)
    _u, first, pid = np.unique(key, axis=0, return_index=True, return_inverse=True)
    pid = pid.reshape(-1)
    Q = P[first].copy()
    n_pts = len(Q)
    parent = list(range(n_pts))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    FP = [list(map(int, pid[f])) for f in F]
    alive = [len(set(f)) == 3 for f in FP]
    K = np.zeros((n_pts, 4, 4))
    edge_faces: dict = {}
    adj: dict = {}
    for fi, f in enumerate(FP):
        if not alive[fi]:
            continue
        p0, p1, p2 = Q[f[0]], Q[f[1]], Q[f[2]]
        n = np.cross(p1 - p0, p2 - p0)
        area = np.linalg.norm(n)
        if area < 1e-12:
            continue
        n = n / area
        pl = np.append(n, -n @ p0)
        for v in f:
            K[v] += 0.5 * area * np.outer(pl, pl)
            adj.setdefault(v, set()).add(fi)
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append((fi, n))
    for (a, b), fl in edge_faces.items():               # open border: keep it in place
        if len(fl) == 1:
            e = Q[b] - Q[a]
            m = np.cross(e, fl[0][1])
            ln = np.linalg.norm(m)
            if ln > 1e-12:
                m = m / ln
                pl = np.append(m, -m @ Q[a])
                w = 10.0 * float(e @ e)
                K[a] += w * np.outer(pl, pl)
                K[b] += w * np.outer(pl, pl)
    ver = [0] * n_pts

    def best(a, b):
        Ks = K[a] + K[b]
        cands = (Q[a], Q[b], (Q[a] + Q[b]) / 2)
        errs = [float(np.append(c, 1) @ Ks @ np.append(c, 1)) for c in cands]
        i = int(np.argmin(errs))
        return max(errs[i], 0.0), i
    heap = []
    for (a, b) in edge_faces:
        e, i = best(a, b)
        heap.append((e, a, b, 0, 0, i))
    heapq.heapify(heap)
    count = sum(alive)

    def normal(f, moved=None, pos=None):
        p = [pos if moved is not None and find(v) in moved else Q[find(v)] for v in f]
        return np.cross(p[1] - p[0], p[2] - p[0])
    while count > target and heap:
        _e, a, b, va, vb, ci = heapq.heappop(heap)
        if find(a) != a or find(b) != b or ver[a] != va or ver[b] != vb or a == b:
            continue
        fa, fb = adj.get(a, set()), adj.get(b, set())
        shared = {fi for fi in fa & fb if alive[fi]}
        if not shared:
            continue
        pos = (Q[a], Q[b], (Q[a] + Q[b]) / 2)[ci].copy()
        ok = True
        for fi in (fa | fb) - shared:
            if not alive[fi]:
                continue
            n0 = normal(FP[fi])
            n1 = normal(FP[fi], {a, b}, pos)
            if np.dot(n0, n1) <= 0.2 * np.linalg.norm(n0) * np.linalg.norm(n1):
                ok = False
                break
        if not ok:
            continue
        parent[a] = b
        Q[b] = pos
        K[b] = K[a] + K[b]
        ver[b] += 1
        for fi in shared:
            alive[fi] = False
            count -= 1
        adj[b] = {fi for fi in fa | fb if alive[fi]}
        nbrs = set()
        for fi in list(adj[b]):
            f = [find(v) for v in FP[fi]]
            if len(set(f)) < 3:
                alive[fi] = False
                count -= 1
                adj[b].discard(fi)
                continue
            nbrs |= {v for v in f if v != b}
        for v in nbrs:
            e, i = best(min(v, b), max(v, b))
            heapq.heappush(heap, (e, min(v, b), max(v, b), ver[min(v, b)], ver[max(v, b)], i))
    out = np.array([Q[find(int(v))] for v in pid])
    return out, F[np.array(alive, bool)]


def slot_mesh(fit: dict, budget: int, drop_head: bool, bones: list, layout: dict) -> dict:
    """Corner mesh for one body LOD: optional head removal (the slot keeps its own head), decimation to the budget,
    page UVs and section (= texture page) per triangle.  -> {P, N, UV, J, W, F, S}."""
    F = fit["F"]
    mk = list(fit["mkeys"])
    if drop_head:
        heads = set(G._subtree(G._kids(bones), fit["roles"]["head"]))
        keep = ~np.all(np.isin(fit["J"][F, 0], list(heads)), axis=1)
        F = F[keep]
        mk = [t for t, kp in zip(mk, keep) if kp]
    kmap = {tuple(f): t for f, t in zip(F.tolist(), mk)}
    P, F2 = decimate(fit["P"], F, budget)
    idx = F2.reshape(-1)
    uv, sec = [], []
    for f in F2.tolist():
        page, tile, size = layout[kmap[tuple(f)]]
        uv.append(atlas_uvs(fit["UV"][f], tile, size))
        sec.append(page)
    return {"P": P[idx], "N": fit["N"][idx], "UV": np.concatenate(uv) if uv else np.zeros((0, 2)),
            "J": fit["J"][idx], "W": fit["W"][idx], "F": np.arange(len(idx)).reshape(-1, 3),
            "S": np.asarray(sec, int)}


# --------------------------------------------------------------------------------------------- one level

def _tris(gcm: bytes) -> int:
    return struct.unpack_from(">I", gcm, G.HDR + 0x68)[0]


def swap_level(data: bytes, assign: dict[str, Donor], level: str = "", progress=None) -> tuple[bytes, dict]:
    """Rebuild one level package with ``assign`` {body key: Donor}.  Returns (package bytes, report)."""
    progress = progress or (lambda p, m: None)
    pkg = ngc.NgcPackage(data)
    cast = level_cast(pkg)
    present = {c.key for c in cast}
    assign = {k: d for k, d in assign.items() if k in present}
    if not assign:
        return data, {"level": level, "replaced": [], "note": "none of the assigned bodies is in this level"}
    bodies = {k: sorted({b for c in cast if c.key == k for b in c.bodies}) for k in assign}
    replaced_bodies = {b for bs in bodies.values() for b in bs}
    users_of_head: dict = {}
    for c in cast:
        for h in c.heads:
            users_of_head.setdefault(h, set()).add(c.key)
    stub_heads = sorted(h for h, ks in users_of_head.items() if ks <= set(assign))
    kept_heads = {k: sorted(h for c in cast if c.key == k for h in c.heads if h not in stub_heads) for k in assign}
    replaced = replaced_bodies | set(stub_heads)
    shd, tex = ngc.shaders(pkg), ngc.textures(pkg)
    users = G.shader_users(pkg)
    free = G.free_shaders(pkg, replaced, users, shd, tex)
    names = {}
    for n in sorted(replaced):
        for s in G.section_names(pkg.read(n)):
            names[NW.hash_string(s)] = s
    free = [f for f in free if f["id"] in names and f["fmt"] == ngc.GX_CMPR]
    donors = sorted({d.slug: d for d in assign.values()}.values(), key=lambda d: d.slug)
    if len(free) < len(donors):
        raise ValueError(f"{level}: {len(donors)} donor(s) need a texture each, but only {len(free)} textures are used "
                         f"by the replaced models alone ({sorted(replaced)[:6]})")
    # every donor first takes one texture of its own models, then the rest go to the donor whose models used them
    mine = {d.slug: {b for k, dd in assign.items() if dd is d for b in bodies[k]} |
            {h for c in cast if assign.get(c.key) is d for h in c.heads if h in stub_heads} for d in donors}
    alloc, taken = {d.slug: [] for d in donors}, set()

    def owners(f):
        return [d for d in donors if users.get(f["id"], set()) & mine[d.slug]]
    for d in donors:
        cand = [f for f in free if f["id"] not in taken and d in owners(f)] or [f for f in free if f["id"] not in taken]
        alloc[d.slug].append(cand[0])
        taken.add(cand[0]["id"])
    for f in free:
        if f["id"] in taken:
            continue
        d = min(owners(f) or donors, key=lambda d: sum(x["size"][0] * x["size"][1] for x in alloc[d.slug]))
        if len(alloc[d.slug]) < len(d.mats):
            alloc[d.slug].append(f)
            taken.add(f["id"])
    pages, images = {}, {}
    report = {"level": level, "replaced": [], "stub_heads": stub_heads, "textures": {}}
    for d in donors:
        fl = sorted(alloc[d.slug], key=lambda f: -f["size"][0] * f["size"][1])
        imgs, layout = build_pages(d.mats, [tuple(f["size"]) for f in fl])
        used = sorted({v[0] for v in layout.values()})
        layout = {k: (used.index(v[0]),) + v[1:] for k, v in layout.items()}
        pages[d.slug] = (layout, [names[fl[i]["id"]] for i in used])
        for i in used:
            images[fl[i]["texture"]] = imgs[i]
        report["textures"][d.slug] = [{"texture": "%08x" % fl[i]["texture"], "shader": names[fl[i]["id"]],
                                       "size": fl[i]["size"]} for i in used]
    repl = {}
    for i, (k, d) in enumerate(sorted(assign.items())):
        progress(100 * i / max(1, len(assign)), f"{level}: {d.name} as {NAMES.get(k, (k,))[0]}")
        layout, shader_names = pages[d.slug]
        heads_k = {h for c in cast if c.key == k for h in c.heads}
        head0 = next((pkg.read(h) for h in sorted(heads_k)), None)
        own_head_stubbed = not kept_heads[k]
        stub_tris = sum(_tris(pkg.read(h)) for h in heads_k & set(stub_heads))
        stub_pal = sum(struct.unpack_from(">H", pkg.read(h), G.HDR + 0x54)[0] - 1 for h in heads_k & set(stub_heads))
        for b in bodies[k]:
            body = pkg.read(b)
            budget = max(MIN_BUDGET, int((_tris(body) + (stub_tris if own_head_stubbed else 0)) * BUDGET_FACTOR))
            fit = fit_donor(d, body, head0)
            m = slot_mesh(fit, budget, not own_head_stubbed, ngc.skeleton(body), layout)
            pal = struct.unpack_from(">H", body, G.HDR + 0x54)[0] + (max(0, stub_pal) if own_head_stubbed else 0)
            gcm, rep = G.encode_gcm(body, m["P"], m["N"], m["UV"], m["J"], m["W"], m["F"], m["S"], shader_names,
                                    max_palette=min(255, pal))
            chk = G.decode_check(gcm)
            if chk["problems"] or chk["triangles"] < 0.95 * rep["triangles"]:
                raise ValueError(f"{level}/{b}: re-read check failed {chk['problems'][:3]}")
            repl[b] = gcm
            report["replaced"].append({"body": b, "key": k, "donor": d.slug, "triangles": rep["triangles"],
                                       "budget": budget, "palette": rep["palette"], "palette_limit": rep["palette_limit"],
                                       "weight_step": rep["weight_step"], "bytes": len(gcm), "source_bytes": len(body),
                                       "sections": shader_names, "head": "stubbed" if own_head_stubbed else "kept",
                                       "fit": fit["report"]})
    for h in stub_heads:
        repl[h] = G.empty_gcm(pkg.read(h))
    progress(90, f"{level}: re-encoding the texture and file-system chunks")
    new_tx = pkg.payload("restxtrs")
    for tid, img in images.items():
        new_tx = G.write_texture_in_place(new_tx, tid, img)
    entries = NW.restable_entries(pkg.table)
    low = {k.lower(): v for k, v in repl.items()}
    entries = [(n, low.get(n.lower(), b)) for n, b in entries]
    out = NW.write_package(pkg, {"restable": NW.build_restable(entries), "restxtrs": new_tx})
    chk = NW.check_package(out, {n: hashlib.sha256(b).hexdigest() for n, b in repl.items()})
    q = ngc.NgcPackage(out)
    tq, t0 = ngc.textures(q), tex
    if len(q.payload("restxtrs")) != len(pkg.payload("restxtrs")):
        chk["problems"].append("texture chunk changed size")
    for tid in tq:
        a_, b_ = t0[tid], tq[tid]
        if (a_.fmt, a_.width, a_.height, a_.offset, a_.size) != (b_.fmt, b_.width, b_.height, b_.offset, b_.size):
            chk["problems"].append(f"texture record {tid:08x} changed")
    chk["problems"] += [p for p in ngc.texture_check(q)]
    if chk["problems"]:
        raise ValueError(f"{level}: rebuilt package failed its check: {chk['problems'][:5]}")
    report |= {"source_sha256": hashlib.sha256(data).hexdigest(), "sha256": hashlib.sha256(out).hexdigest(),
               "source_size": len(data), "size": len(out), "textures_total": len(tq)}
    return out, report


# --------------------------------------------------------------------------------------------- the disc

def level_path(level: str) -> str:
    return f"maps/{level}.ngc"


def build_mod(cfg, image: Path, name: str, plan: dict, donors: dict[str, Donor], progress=None, workers: int = 1) -> dict:
    """A disc-image mod (cache/mods/<game>/<name>): every level the plan touches rebuilt, the rest copied."""
    import types
    from . import filemods
    from .gcdisc import GCDisc
    progress = progress or (lambda p, m: None)
    image = Path(image)
    by_level: dict = {}
    for (lv, k), slug in plan.items():
        by_level.setdefault(lv, {})[k] = donors[slug]
    changes, reports = {}, []
    src = _disc_reader(image)
    try:
        for i, lv in enumerate(sorted(by_level)):
            base = 5 + 80 * i / max(1, len(by_level))
            progress(base, f"Rebuilding {lv} ({i + 1}/{len(by_level)})")
            data = src(level_path(lv))
            out, rep = swap_level(data, by_level[lv], lv,
                                  lambda p, m, base=base: progress(base + 80 / max(1, len(by_level)) * p / 100, m))
            if rep.get("replaced"):
                changes[level_path(lv)] = {"bytes": out}
            reports.append(rep)
    finally:
        getattr(src, "close", lambda: None)()
    if not changes:
        raise ValueError("no level changed: the plan's characters are not on this disc")
    progress(88, "Writing the disc image")
    cfg = cfg if hasattr(cfg, "cache") else types.SimpleNamespace(cache=Path(cfg))
    b = filemods.build_image(cfg, GAME_ID, image, name, changes, progress)
    marker = Path(b["dir"]) / ".gbox-mod.json"
    rec = json.loads(marker.read_text())
    rec |= {"writer": "gbox.auf_swap", "cast": sorted([lv, k, s] for (lv, k), s in plan.items()),
            "levels": {r["level"]: {"sha256": r.get("sha256"), "replaced": len(r.get("replaced", []))} for r in reports}}
    marker.write_text(json.dumps(rec))
    disc = GCDisc(b["image"])
    try:
        moved = {k: disc.files[k] for k in changes}
        for k in changes:                                     # read every rebuilt level back from the new image
            if hashlib.sha256(disc.read(k)).hexdigest() != hashlib.sha256(changes[k]["bytes"]).hexdigest():
                raise ValueError(f"{k}: the image does not hold the rebuilt level")
    finally:
        disc.f.close()
    return b | {"levels": reports, "files": {k: {"offset": o, "size": s} for k, (o, s) in moved.items()}}


def _disc_reader(image: Path):
    """path in the FST -> bytes, for a .gcz (gbox.gcz random access) or a plain .iso/.gcm."""
    from .gcdisc import GCDisc
    if image.suffix.lower() == ".gcz":
        from . import au_inventory as AI
        from .gcz import GCZ
        g = GCZ(str(image))
        g.__enter__()
        _, fst_off, fst_size, _ = struct.unpack(">IIII", g.read(0x420, 16))
        files = {}
        for path, off, size in AI.FST(g.read(fst_off, fst_size)).walk():
            files[path.lower().split("/", 2)[-1] if path.startswith("/") else path.lower()] = (off, size)

        def read(key):
            k = key.lower()
            hit = files.get(k) or next((v for p, v in files.items() if p.endswith("/" + k) or p == k), None)
            if hit is None:
                raise KeyError(key)
            return g.read(*hit)
        read.close = lambda: g.__exit__(None, None, None)
        return read
    disc = GCDisc(image)

    def read(key):
        return disc.read(key)
    read.close = disc.f.close
    return read


# --------------------------------------------------------------------------------------------- characters op=use

def mod_name(slot: str, plan: dict) -> str:
    s = (slot or "player").strip().lower()
    tag = re.sub(r"[^a-z0-9]+", "_", s.split(":", 1)[-1]).strip("_") or "player"
    digest = hashlib.sha256(json.dumps(sorted([lv, k, d] for (lv, k), d in plan.items())).encode()).hexdigest()[:8]
    return f"auf_{tag}_{digest}"


def _pairs(meta: dict, inp) -> list[tuple[str, str]]:
    out = []
    for p in getattr(inp, "pairs", None) or []:
        out.append((str(p.get("target") or p.get("slot") or ""), str(p.get("donor") or p.get("character") or "")))
    if not out:
        out = [("", meta["slug"])]
    return out


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for 007 Agent Under Fire GC: slot player | enemies | bosses | npcs | bots | all |
    model:<body> | cast (+pairs).  Built where the collection is (the control plane), launched on request."""
    from . import characters as C, filemods
    s = (inp.slot or "player").strip().lower()
    if s in ("cast", "roster", "everyone"):
        plan = plan_cast(_pairs(meta, inp), seed=getattr(inp, "title", "") or "")
    else:
        plan = {lk: meta["slug"] for lk in select(s)}
    name = mod_name(s, plan)
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, game["game_id"])}
    built = None
    if inp.rebuild or not have:
        root = C.library_root(ctx.config)
        if not root.is_dir():
            cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux" and w.get("online")
                       and w.get("id") != getattr(ctx, "worker", None)), None)
            if not cp:
                raise RuntimeError("the AUF build needs the character collection on the control plane, which is offline")
            ctx.progress(5, "Building the Agent Under Fire mod on the control-plane node (the collection lives there)")
            j = C._job(ctx, "characters", inp.model_dump() | {"launch": False, "session_id": "", "game_id": game["game_id"]},
                       cp, 7200)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded":
                return {"status": "failed", "mod": name, "error": r.get("error") or j.get("error")}
            built = r.get("build")
        else:
            donors = {}
            for slug in sorted(set(plan.values())):
                m = C.get(root, slug) if slug != meta["slug"] else meta
                donors[slug] = load_donor(slug, C._local_or_fetch(ctx, m, m["model"]), (m.get("rig") or {}).get("roles"),
                                          m.get("name", slug))
            iso = C._gc_iso(ctx, game)
            built = build_mod(ctx.config, iso, name, plan, donors, ctx.progress)
            for slug in donors:
                C._api(ctx, "POST", f"/api/characters/{slug}/targets",
                       json={"game_id": game["game_id"], "slot": s, "mod": name, "nodes": [C.HOST_OS],
                             "notes": f"AUF {s}: {sum(1 for d in plan.values() if d == slug)} level bodies; "
                                      "native animations kept; gameplay verification required"})
    res = {"mod": name, "slot": s, "build": built, "status": "built_unverified" if built else "ready",
           "cast": sorted({(k, d) for (_lv, k), d in plan.items()}), "gameplay_verified": False,
           "replacement_kind": "native_disc"}
    if inp.launch:
        sess = C._session(ctx, inp.session_id) if inp.session_id else None
        node = sess["session_id"].split("-")[0] if sess else "idle"
        res["launch"] = C._launch(ctx, game["game_id"], name, node)
    return res


# --------------------------------------------------------------------------------------------- CLI

def _library_donor(root: Path, slug: str) -> Donor:
    meta = json.loads((Path(root) / slug / "meta.json").read_text(encoding="utf-8"))
    return load_donor(slug, Path(root) / slug / meta["model"], (meta.get("rig") or {}).get("roles"), meta.get("name"))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="007 Agent Under Fire GC character writer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="print the (level, body) -> donor plan")
    p.add_argument("--slot", default="player")
    p.add_argument("--donor", action="append", default=[], help="donor slug, or TARGET=SLUG for cast")
    p.add_argument("--seed", default="")
    b = sub.add_parser("level", help="rebuild one level package file")
    b.add_argument("ngc")
    b.add_argument("library")
    b.add_argument("out")
    b.add_argument("--slot", default="player")
    b.add_argument("--donor", action="append", default=[])
    d = sub.add_parser("build", help="build a disc-image mod")
    d.add_argument("image", help="owned .gcz or .iso")
    d.add_argument("library", help="character collection root (slug/meta.json)")
    d.add_argument("cache", help="cache dir (the mod goes to <cache>/mods/<game>/<name>)")
    d.add_argument("--slot", default="player")
    d.add_argument("--donor", action="append", default=[])
    d.add_argument("--seed", default="")
    d.add_argument("--name", default="")
    a = ap.parse_args(argv)

    def pairs():
        return [tuple(x.split("=", 1)) if "=" in x else ("", x) for x in a.donor]
    if a.cmd == "plan":
        plan = plan_cast(pairs(), a.seed) if a.slot == "cast" else {lk: a.donor[0] for lk in select(a.slot)}
        print(json.dumps(sorted([lv, k, s] for (lv, k), s in plan.items()), indent=0))
        return 0
    t0 = time.time()
    if a.cmd == "level":
        lv = Path(a.ngc).stem
        plan = plan_cast(pairs()) if a.slot == "cast" else {lk: a.donor[0] for lk in select(a.slot)}
        donors = {s: _library_donor(Path(a.library), s) for s in set(plan.values())}
        out, rep = swap_level(Path(a.ngc).read_bytes(), {k: donors[s] for (l, k), s in plan.items() if l == lv}, lv,
                              lambda p, m: print(f"{p:5.1f}% {m}"))
        Path(a.out).write_bytes(out)
        print(json.dumps(rep | {"seconds": round(time.time() - t0, 1)}, indent=1, default=str))
        return 0
    plan = plan_cast(pairs(), a.seed) if a.slot == "cast" else {lk: a.donor[0] for lk in select(a.slot)}
    donors = {s: _library_donor(Path(a.library), s) for s in set(plan.values())}
    name = a.name or mod_name(a.slot, plan)
    r = build_mod(Path(a.cache), Path(a.image), name, plan, donors, lambda p, m: print(f"{p:5.1f}% {m}"))
    print(json.dumps({k: v for k, v in r.items() if k != "levels"} | {"seconds": round(time.time() - t0, 1)}, indent=1,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
