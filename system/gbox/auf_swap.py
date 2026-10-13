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
    weights kept), reduced to the 2-bone blends the format has, decimated to the slot's triangle budget, and its
    textures are packed into one 256x256 atlas;
  * the whole donor, head included, is encoded into the body model (auf_gcm.encode_gcm: the body's skeleton, hit
    boxes and animation bindings stay, so every native animation still drives it) and each head model only those
    bodies use becomes an invisible stub; a head that a body outside the build also wears is kept and the donor's
    own head is left out instead;
  * the atlas goes into the level's texture chunk by re-pointing a texture only the replaced models use (no new
    texture records: the game's texture table is fixed at 512 entries) and the donor's section uses that texture's
    shader name.
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
ATLAS = 256
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
    atlas: np.ndarray = None
    tiles: dict = None
    fits: dict = field(default_factory=dict)


def load_donor(slug: str, glb, roles: dict, name: str = "") -> Donor:
    from . import doa2_weighted_retarget as WR
    roles = dict(roles or {})
    if not {"hip", "head"} <= roles.keys():
        raise ValueError(f"{slug}: the collection entry has no hip/head rig roles (not retargetable)")
    d = Donor(slug, name or slug, Path(glb), roles)
    d.rig = WR.load_rig(Path(glb), roles)
    d.atlas, d.tiles = build_atlas(d.rig["prims"])
    return d


def _material_key(p):
    tex = p.get("tex")
    return (hashlib.sha1(np.ascontiguousarray(tex).tobytes()).hexdigest() if tex is not None else None,
            tuple(int(c) for c in p.get("color", (255, 255, 255, 255))[:3]))


def build_atlas(prims, size: int = ATLAS) -> tuple[np.ndarray, dict]:
    """Every donor material (texture x colour factor, or a plain colour) in one grid of square tiles.
    -> (RGBA image, {material key: (x0, y0, tile)})."""
    from PIL import Image
    mats = []
    for p in prims:
        k = _material_key(p)
        if k not in [m[0] for m in mats]:
            mats.append((k, p.get("tex"), p.get("color", (255, 255, 255, 255))))
    cols = max(1, int(np.ceil(np.sqrt(len(mats)))))
    tile = size // cols
    img = np.zeros((size, size, 4), np.uint8)
    img[..., 3] = 255
    tiles = {}
    for i, (k, tex, color) in enumerate(mats):
        x0, y0 = (i % cols) * tile, (i // cols) * tile
        col = np.asarray(color[:3], float) / 255
        if tex is None:
            img[y0:y0 + tile, x0:x0 + tile, :3] = (col * 255).astype(np.uint8)
        else:
            t = np.asarray(tex, np.uint8)
            if t.ndim == 2:
                t = np.stack([t] * 3 + [np.full_like(t, 255)], -1)
            if t.shape[2] == 3:
                t = np.concatenate([t, np.full(t.shape[:2] + (1,), 255, np.uint8)], -1)
            a = t[..., 3] >= 128                          # AUF draws characters opaque: fill cut-out texels
            if a.any() and not a.all():
                t = t.copy()
                t[~a, :3] = t[a, :3].mean(0).astype(np.uint8)
            r = np.asarray(Image.fromarray(t[..., :3]).resize((tile, tile), Image.BILINEAR), float)
            img[y0:y0 + tile, x0:x0 + tile, :3] = np.clip(r * col, 0, 255).astype(np.uint8)
        tiles[k] = (x0, y0, tile)
    return img, tiles


def atlas_uvs(uv_tri: np.ndarray, tile: tuple, size: int = ATLAS) -> np.ndarray:
    """(3, 2) material UVs of one triangle -> atlas UVs: shifted by whole repeats into [0, 1] (clamped when the
    triangle itself spans more than one repeat) and mapped half a texel inside the material's tile."""
    x0, y0, t = tile
    u = np.asarray(uv_tri, float)
    u = u - np.floor(u.min(0))
    u = np.clip(u, 0.0, 1.0)
    return np.stack([(x0 + 0.5 + u[:, 0] * (t - 1)) / size, (y0 + 0.5 + u[:, 1] * (t - 1)) / size], 1)


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
    UVs and the atlas tile of every triangle."""
    from . import doa2_weighted_retarget as WR
    sig = skeleton_signature(body)
    if sig in donor.fits:
        return donor.fits[sig]
    tgt = target_of(body, head)
    prims, rep = WR.retarget(donor.rig, tgt, jmap=tgt["jmap"])
    Ps, Ns, UVs, Js, Ws, Fs, tiles = [], [], [], [], [], [], []
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
        tiles += [donor.tiles[_material_key(src)]] * len(tris)
        base += n
    fit = {"P": np.concatenate(Ps), "N": np.concatenate(Ns), "UV": np.concatenate(UVs), "J": np.concatenate(Js),
           "W": np.concatenate(Ws), "F": np.concatenate(Fs), "tiles": tiles, "roles": tgt["jmap"],
           "report": {k: rep[k] for k in ("scale", "torso_up", "torso_down", "shoulder_widen", "head_scale",
                                          "normals_flipped") if k in rep}}
    donor.fits[sig] = fit
    return fit


def decimate(P: np.ndarray, F: np.ndarray, target: int) -> tuple[np.ndarray, np.ndarray]:
    """Shortest-edge collapse on the welded surface until ``target`` triangles remain (collapses that flip a
    neighbouring face are skipped).  Split vertices (UV seams) move together; every corner keeps its own UV, normal
    and skin.  -> (moved vertex positions, surviving faces)."""
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
    parent = list(range(len(Q)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    FP = [list(map(int, pid[f])) for f in F]
    alive = [len(set(f)) == 3 for f in FP]
    adj: dict = {}
    for fi, f in enumerate(FP):
        if alive[fi]:
            for v in f:
                adj.setdefault(v, set()).add(fi)
    heap = []
    for fi, f in enumerate(FP):
        if alive[fi]:
            for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                heapq.heappush(heap, (float(np.linalg.norm(Q[a] - Q[b])), min(a, b), max(a, b)))
    count = sum(alive)

    def normal(f, moved=None, pos=None):
        p = [pos if moved is not None and find(v) in moved else Q[find(v)] for v in f]
        return np.cross(p[1] - p[0], p[2] - p[0])
    while count > target and heap:
        _l, a, b = heapq.heappop(heap)
        a, b = find(a), find(b)
        if a == b:
            continue
        fa, fb = adj.get(a, set()), adj.get(b, set())
        shared = {fi for fi in fa & fb if alive[fi]}
        if not shared:
            continue
        mid = (Q[a] + Q[b]) / 2
        ok = True
        for fi in (fa | fb) - shared:
            if not alive[fi]:
                continue
            n0 = normal(FP[fi])
            n1 = normal(FP[fi], {a, b}, mid)
            if np.dot(n0, n1) <= 0.2 * np.linalg.norm(n0) * np.linalg.norm(n1):
                ok = False
                break
        if not ok:
            continue
        parent[a] = b
        Q[b] = mid
        for fi in shared:
            alive[fi] = False
            count -= 1
        adj[b] = {fi for fi in fa | fb if alive[fi]}
        for fi in list(adj[b]):
            f = [find(v) for v in FP[fi]]
            if len(set(f)) < 3:
                alive[fi] = False
                count -= 1
                adj[b].discard(fi)
                continue
            for v in f:
                if v != b:
                    heapq.heappush(heap, (float(np.linalg.norm(Q[v] - Q[b])), min(v, b), max(v, b)))
    out = np.array([Q[find(int(v))] for v in pid])
    return out, F[np.array(alive, bool)]


def slot_mesh(fit: dict, budget: int, drop_head: bool, bones: list) -> dict:
    """Corner mesh for one body LOD: optional head removal (the slot keeps its own head), decimation to the budget,
    atlas UVs per triangle.  -> {P, N, UV, J, W, F}."""
    F = fit["F"]
    tiles = list(fit["tiles"])
    if drop_head:
        hb = fit["roles"]["head"]
        k = G._kids(bones)
        heads = set(G._subtree(k, hb))
        keep = ~np.all(np.isin(fit["J"][F, 0], list(heads)), axis=1)
        F = F[keep]
        tiles = [t for t, kp in zip(tiles, keep) if kp]
    tmap = {tuple(f): t for f, t in zip(F.tolist(), tiles)}
    P, F2 = decimate(fit["P"], F, budget)
    idx = F2.reshape(-1)
    uv = np.concatenate([atlas_uvs(fit["UV"][f], tmap[tuple(f)]) for f in F2.tolist()]) if len(F2) else np.zeros((0, 2))
    return {"P": P[idx], "N": fit["N"][idx], "UV": uv, "J": fit["J"][idx], "W": fit["W"][idx],
            "F": np.arange(len(idx)).reshape(-1, 3)}


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
    free = [f for f in free if f["id"] in names]
    donors = sorted({d.slug: d for d in assign.values()}.values(), key=lambda d: d.slug)
    if len(free) < len(donors):
        raise ValueError(f"{level}: {len(donors)} donor(s) need a texture each, but only {len(free)} textures are used "
                         f"by the replaced models alone ({sorted(replaced)[:6]})")
    # a donor prefers a texture of its own bodies
    pick, taken = {}, set()
    for d in donors:
        mine = {b for k, dd in assign.items() if dd is d for b in bodies[k]}
        cand = [f for f in free if f["id"] not in taken and users.get(f["id"], set()) & mine] or \
               [f for f in free if f["id"] not in taken]
        pick[d.slug] = cand[0]
        taken.add(cand[0]["id"])
    repl, report = {}, {"level": level, "replaced": [], "stub_heads": stub_heads, "textures": {}}
    for i, (k, d) in enumerate(sorted(assign.items())):
        progress(100 * i / max(1, len(assign)), f"{level}: {d.name} as {NAMES.get(k, (k,))[0]}")
        shader = names[pick[d.slug]["id"]]
        head0 = next((pkg.read(h) for c in cast if c.key == k for h in c.heads), None)
        own_head_stubbed = not kept_heads[k]
        for b in bodies[k]:
            body = pkg.read(b)
            stub_tris = sum(_tris(pkg.read(h)) for h in {h for c in cast if c.key == k for h in c.heads} & set(stub_heads))
            stub_pal = sum(struct.unpack_from(">H", pkg.read(h), G.HDR + 0x54)[0] - 1
                           for h in {h for c in cast if c.key == k for h in c.heads} & set(stub_heads))
            budget = max(MIN_BUDGET, int((_tris(body) + (stub_tris if own_head_stubbed else 0)) * BUDGET_FACTOR))
            fit = fit_donor(d, body, head0)
            m = slot_mesh(fit, budget, drop_head=not own_head_stubbed, bones=ngc.skeleton(body))
            pal = struct.unpack_from(">H", body, G.HDR + 0x54)[0] + (max(0, stub_pal) if own_head_stubbed else 0)
            gcm, rep = G.encode_gcm(body, m["P"], m["N"], m["UV"], m["J"], m["W"], m["F"], np.zeros(len(m["F"]), int),
                                    [shader], max_palette=min(255, pal))
            chk = G.decode_check(gcm)
            if chk["problems"] or chk["triangles"] < 0.95 * rep["triangles"]:
                raise ValueError(f"{level}/{b}: re-read check failed {chk['problems'][:3]}")
            repl[b] = gcm
            report["replaced"].append({"body": b, "key": k, "donor": d.slug, "triangles": rep["triangles"],
                                       "budget": budget, "palette": rep["palette"], "palette_limit": rep["palette_limit"],
                                       "weight_step": rep["weight_step"], "bytes": len(gcm), "source_bytes": len(body),
                                       "shader": shader, "head": "stubbed" if own_head_stubbed else "kept",
                                       "fit": fit["report"]})
    for h in stub_heads:
        repl[h] = G.empty_gcm(pkg.read(h))
    images = {}
    for d in donors:
        f = pick[d.slug]
        images[f["texture"]] = d.atlas
        report["textures"][d.slug] = {"texture": "%08x" % f["texture"], "shader": names[f["id"]],
                                      "was": f["size"], "now": [ATLAS, ATLAS]}
    progress(90, f"{level}: re-encoding the texture and file-system chunks")
    new_tx = G.repoint_textures(pkg.payload("restxtrs"), images)
    entries = NW.restable_entries(pkg.table)
    low = {k.lower(): v for k, v in repl.items()}
    entries = [(n, low.get(n.lower(), b)) for n, b in entries]
    out = NW.write_package(pkg, {"restable": NW.build_restable(entries), "restxtrs": new_tx})
    chk = NW.check_package(out, {n: hashlib.sha256(b).hexdigest() for n, b in repl.items()})
    q = ngc.NgcPackage(out)
    tq = ngc.textures(q)
    for d in donors:
        t = tq[pick[d.slug]["texture"]]
        if (t.width, t.height) != (ATLAS, ATLAS):
            chk["problems"].append(f"texture {t.id:08x} not re-pointed")
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
