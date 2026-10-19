"""Metal Gear Solid: The Twin Snakes (GameCube, GGSEA4, USA, 2 discs) - the cast as rigged, textured GLBs.

Disc inventory and formats: docs/twin_snakes.md. In short: Konami's MGS2 engine on the GameCube (code in
shared/mgso.rel, built from "C:\\MGS\\mgs2\\mgs2x\\MGS2GCN"); characters live in `stage.dat` (gbox.ts_stage) as
`.kms` models (gbox.ts_kms) on the shared 21-bone skeleton, skinned through 8-byte envelopes, with their textures
in `.tri` sets (gbox.ts_tex, an embedded TPL). Snake is `snake_def` in the resident stage `r_sna`; the Genome
soldiers are `out_cold` / `out_cold2` (outdoors), `in_door`, `in_gus` (gas masks), `hev_grd` (heavy guard) in the
area stages that place them; each has a `<name>_sh` low-detail twin on the same texture set.

`characters op=collect` on a Twin Snakes disc runs `extract_run` per `roster()` entry (characters.DEDICATED
"twin_snakes"): the model from its representative stage, every part's colour texture from the stage's texture sets,
the skeleton with bind-pose joints and up to three weights per vertex, the library frame (metres, up +Y, facing +Z,
left +X: the game's own axes) and the body roles of the shared skeleton. The writer is gbox.twin_snakes_swap.

  python -m gbox.twin_snakes <disc.iso> <out dir> [key ...]     GLBs + preview PNGs without the library
"""
from __future__ import annotations

import base64
import functools
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

from . import ts_kms as K
from . import ts_stage as S
from . import ts_tex as T

READER_VERSION = 1
DISC_ID = "GGSEA4"
GAME_TITLE = "Metal Gear Solid: The Twin Snakes"
# catalog entries (operator's library): two ISOs and the two HyperSpin GCZ discs. Which disc an image is comes from
# its header (byte 6), not from the id.
GAME_IDS = {"ba32927ecc104b9a": "Metal Gear Solid: The Twin Snakes (USA) (Disc 1) [iso]",
            "b87996662aa2a8f7": "Metal Gear Solid: The Twin Snakes (USA) (Disc 2) [iso]",
            "79965f951e479d2b": "Metal Gear Solid: The Twin Snakes (USA) (Disc 1)",
            "bf3675da8955e248": "Metal Gear Solid: The Twin Snakes (USA) (Disc 2)"}

# The cast: key = model name (strcode verified against the disc), the stage it is read from per disc, its texture
# set, its low-detail twin and its role. Models without a recovered name keep their strcode as the key.
CAST = [
    {"key": "snake_def", "name": "Solid Snake (Twin Snakes)", "aliases": ["Snake", "Solid Snake", "TTS Snake"],
     "stage": {1: "r_sna", 2: "r_sna"}, "role": "player", "player": True},
    {"key": "out_cold", "name": "Genome Soldier (arctic, Twin Snakes)", "aliases": ["arctic soldier", "Genome Soldier (arctic)"],
     "stage": {1: "area01a", 2: "area01a"}, "role": "enemy", "low": "out_cold_sh"},
    {"key": "out_cold2", "name": "Genome Soldier (arctic, hood, Twin Snakes)", "aliases": ["hooded soldier", "Genome Soldier (hood)"],
     "stage": {1: "area02a", 2: "area08a"}, "role": "enemy", "low": "out_cold2_sh"},
    {"key": "in_door", "name": "Genome Soldier (indoor, Twin Snakes)", "aliases": ["indoor soldier", "Genome Soldier (indoor)"],
     "stage": {1: "area04a", 2: "area17a"}, "role": "enemy", "low": "in_door_sh"},
    {"key": "in_gus", "name": "Genome Soldier (gas mask, Twin Snakes)", "aliases": ["gas mask soldier", "Genome Soldier (gas mask)"],
     "stage": {1: "area09a"}, "role": "enemy", "low": "in_gus_sh"},
    {"key": "in_gus_blue_def", "name": "Genome Soldier (gas mask, blue, Twin Snakes)", "aliases": [],
     "stage": {1: "demo09a", 2: "area17e"}, "role": "enemy"},
    {"key": "hev_grd", "name": "Genome Heavy Guard (Twin Snakes)", "aliases": ["heavy guard"],
     "stage": {1: "area04a", 2: "area21a"}, "role": "enemy", "low": "hev_grd_sh"},
    {"key": "mrl_def", "name": "Meryl Silverburgh (Twin Snakes)", "aliases": ["Meryl"],
     "stage": {1: "mrl_def", 2: "mrl_def"}, "role": "npc"},
    {"key": "mrl_dis_def", "name": "Meryl (soldier disguise, Twin Snakes)", "aliases": ["Meryl disguised"],
     "stage": {1: "mrl_dis", 2: "mrl_dis"}, "role": "npc", "low": "mrl_dis_sh"},
    {"key": "otc_def", "name": "Otacon (Twin Snakes)", "aliases": ["Hal Emmerich", "Otacon"],
     "stage": {1: "area11a", 2: "area27a"}, "role": "npc"},
    {"key": "rev_coat_def", "name": "Revolver Ocelot (Twin Snakes)", "aliases": ["Ocelot"],
     "stage": {1: "area06b", 2: "area06b"}, "role": "boss"},
    {"key": "psy_def", "name": "Psycho Mantis (Twin Snakes)", "aliases": ["Mantis"],
     "stage": {1: "area13a", 2: "area13a"}, "role": "boss"},
    {"key": "snp_def", "name": "Sniper Wolf (Twin Snakes)", "aliases": ["Wolf"],
     "stage": {1: "area15a", 2: "area15a"}, "role": "boss"},
    {"key": "snp_cold_def", "name": "Sniper Wolf (snowfield, Twin Snakes)", "aliases": [],
     "stage": {1: "area20a", 2: "area20a"}, "role": "boss"},
    {"key": "vul_def", "name": "Vulcan Raven (Twin Snakes)", "aliases": ["Raven"],
     "stage": {1: "area08a", 2: "area08a"}, "role": "boss"},
    {"key": "liq_coat_def", "name": "Liquid Snake (coat, Twin Snakes)", "aliases": ["Liquid"],
     "stage": {2: "area24a"}, "role": "boss"},
    {"key": "liq_def", "name": "Liquid Snake (Twin Snakes)", "aliases": [],
     "stage": {2: "area27b"}, "role": "boss"},
    {"key": "joh_def", "name": "Johnny Sasaki (Twin Snakes)", "aliases": ["Johnny"],
     "stage": {1: "jhJ_dmo", 2: "jhJ_dmo"}, "role": "npc"},
    {"key": "#65729f", "name": "Cyborg Ninja (Twin Snakes)", "aliases": ["Gray Fox", "Ninja"],
     "stage": {1: "nja_def", 2: "nja_def"}, "role": "boss"},
]

# Who a model is, by its texture set (header +0x0c): every gameplay, cut-scene and close-up model of a character
# draws from that character's sets. Identified on both discs by strcode names (sna_def, mrl_dmo, liq_coat_dmo ...)
# and, for unnamed sets, by rendering every humanoid model (148 on disc 1, 26 more on disc 2; docs/twin_snakes.md).
# Sets of items drawn on the skeleton (guns 0x49e8c3, armour / gas mask 0xcba219, snow decals 0xcc73a9) and models
# whose set is not in their own stage are not characters here.
IDENTITIES = {
    "snake": ("Solid Snake", ["413aa8", "69b995", "d34a29", "35a87a", "083577", "a5346d", "a53576", "413bb1",
                              "b13aa8", "23eb63"]),
    "meryl": ("Meryl Silverburgh", ["f13930", "f139bd", "f13a39", "27476f", "302832", "603414", "f1627a", "6f4c92",
                                    "f4985c", "c675db"]),
    "otacon": ("Otacon", ["683fc2", "721b33", "730bad"]),
    "liquid": ("Liquid Snake", ["4139e8", "f38a4a", "26c3bc", "4138df", "323452"]),
    "ocelot": ("Revolver Ocelot", ["26f2c6", "f86750", "aa06fb"]),
    "wolf": ("Sniper Wolf", ["313aa9", "313bb2", "4f5aec"]),
    "mantis": ("Psycho Mantis", ["65abf6", "c13afc", "c139f3", "f38b6a"]),
    "raven": ("Vulcan Raven", ["f13b76", "f13c7f", "0ad1d2", "c85014", "f882e5", "cb3cb3", "2f60d0", "f17b04"]),
    "ninja": ("Cyborg Ninja", ["413960", "c3c1bd", "274d59", "b5ab6b"]),
    "decoy": ("Decoy Octopus", ["288a7a"]),
    "anderson": ("Donald Anderson (DARPA chief)", ["4136ec", "725667"]),
    "baker": ("Kenneth Baker", ["313635", "31373e"]),
    "naomi": ("Naomi Hunter", ["213a58"]),
    "campbell": ("Roy Campbell", ["013798", "270b21"]),
    "johnny": ("Johnny Sasaki", ["737a80"]),
    "soldier_arctic": ("Genome Soldier (arctic)", ["26e012", "dc0276"]),
    "soldier_indoor": ("Genome Soldier (indoor)", ["23e574"]),
    "soldier_gas": ("Genome Soldier (gas mask)", ["112bec", "4516e3", "f7935d"]),
    "soldier_heavy": ("Genome heavy guard", ["914575"]),
}
TEXSET_IDENTITY = {int(t, 16): k for k, (_n, ts) in IDENTITIES.items() for t in ts}
# Codec portraits (shared/face.dat: one stage per call setup f00a .. f20a, one .tri set per speaker)
CODEC = {0xB7F564: "snake", 0x045793: "meryl", 0x721B33: "otacon", 0x35D30D: "campbell", 0x124A10: "naomi",
         0x2B343F: "mei_ling", 0x75E28E: "nastasha", 0xB7680D: "miller", 0x3D49E6: "wolf", 0x01D464: "houseman"}
CODEC_NAMES = {"mei_ling": "Mei Ling", "nastasha": "Nastasha Romanenko", "miller": "Master Miller",
               "houseman": "Jim Houseman (old man in a suit; name not in the data)"}
PORTRAIT = (104, 178)


def identity_of(model: bytes) -> str | None:
    """A model's character (IDENTITIES key) from its texture set, else None."""
    return TEXSET_IDENTITY.get(struct.unpack_from(">I", model, 0x0C)[0] & 0xFFFFFF) if len(model) >= 0x10 else None


def model_hash(key: str) -> int:
    return int(key[1:], 16) if key.startswith("#") else S.strcode(key)


def slug_of(key: str) -> str:
    return "tts_" + re.sub(r"[^a-z0-9]+", "_", key.lower().lstrip("#")).strip("_")


def disc_of(game: dict | None = None, header: bytes | None = None) -> int:
    """1 or 2: from the disc header (byte 6) when given, else from the catalog title / id."""
    if header is not None and len(header) > 6:
        return header[6] + 1
    t = f"{(game or {}).get('title', '')} {GAME_IDS.get((game or {}).get('game_id', ''), '')}"
    return 2 if re.search(r"disc\s*2", t, re.I) else 1


def roster(disc: int | None = None) -> list[dict]:
    """Library entries for the cast (disc: only the characters that disc carries)."""
    out = []
    for c in CAST:
        if disc is not None and disc not in c["stage"]:
            continue
        out.append({"key": c["key"], "slug": slug_of(c["key"]), "name": c["name"],
                    "aliases": list(c["aliases"]) + [c["key"]], "kind": "character", "role": c["role"],
                    "stage": c["stage"], "native_player": bool(c.get("player"))})
    return out


def cast_entry(key: str) -> dict:
    return next(c for c in CAST if c["key"] == key)


# ----------------------------------------------------------------------------------------------- reading

def texture_sets(stage: S.Stage) -> list[T.TextureSet]:
    out = []
    for f in stage.files():
        if f.type == S.TEXTURES:
            try:
                out.append(T.TextureSet(f.data))
            except (ValueError, struct.error, KeyError):
                pass
    return out


def find_image(sets: list[T.TextureSet], h: int, first: int | None = None):
    """(set, image) for a texture strcode: the model's own set first (the engine's search order), then any."""
    order = sorted(sets, key=lambda s: 0 if first is not None and any(t.hash == h for t in s.textures) else 1)
    for s in order:
        img = s.by_hash(h)
        if img is not None:
            return s, img
    return None, None


def model_prims(m: K.Kms, sets: list[T.TextureSet]) -> list[dict]:
    """Decoded prims with RGBA colour textures (cached per strcode), positions in metres."""
    cache: dict[int, np.ndarray | None] = {}
    prims = K.decode(m)
    for p in prims:
        h = p["tex"]
        if h not in cache:
            s, img = find_image(sets, h, m.tex_set)
            try:
                cache[h] = s.rgba(img) if s is not None else None
            except (ValueError, IndexError, KeyError):
                cache[h] = None
        p["image"] = cache[h]
        p["pos"] = p["pos"] * K.MM
    return prims


def joints_of(m: K.Kms) -> list[dict]:
    """One joint per mesh matrix: the bones, then the extra meshes (hair, gear) on their parent mesh."""
    out = []
    for i in range(max(len(m.bones), len(m.meshes))):
        w = np.eye(4)
        if i < len(m.bones):
            w[:3, 3] = np.asarray(m.bones[i]["world"]) * K.MM
            par = m.bones[i]["parent"]
        else:
            me = m.meshes[i]
            w[:3, 3] = np.asarray(me.world) * K.MM
            par = me.parent if 0 <= me.parent < i else (0 if i else -1)     # props: no bone table, meshes only
        out.append({"parent": par, "world": w})
    return out


def joint_names(m: K.Kms) -> list[str]:
    n = max(len(m.bones), len(m.meshes))
    base = list(K.BONE_NAMES) if [b["parent"] for b in m.bones] == K.PARENTS else         [f"bone{i:02d}" for i in range(len(m.bones))]
    return base + [f"mesh{i:02d}" for i in range(len(m.bones), n)]


def roles_of(m: K.Kms) -> dict[str, str]:
    """Body roles of the shared 21-bone skeleton (rig.roles: {role: joint name})."""
    if [b["parent"] for b in m.bones] != K.PARENTS:
        return {}
    return dict(K.ROLES)


def gltf_to_glb(gltf: dict) -> bytes:
    """A self-contained glTF dict (data: URIs) -> GLB bytes (one BIN chunk; images moved into buffer views)."""
    gl = json.loads(json.dumps(gltf))
    blob = bytearray()
    old = [base64.b64decode(b["uri"].split(",", 1)[1]) for b in gl["buffers"]]
    for v in gl["bufferViews"]:
        src = old[v["buffer"]][v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
        blob += bytes((-len(blob)) % 4)
        v["buffer"], v["byteOffset"] = 0, len(blob)
        blob += src
    for im in gl.get("images", []):
        if im.get("uri", "").startswith("data:"):
            mime = im["uri"][5:].split(";", 1)[0]
            data = base64.b64decode(im.pop("uri").split(",", 1)[1])
            blob += bytes((-len(blob)) % 4)
            gl["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
            blob += data
            im["bufferView"], im["mimeType"] = len(gl["bufferViews"]) - 1, mime
    blob += bytes((-len(blob)) % 4)
    gl["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js +
            struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def export(m: K.Kms, sets: list[T.TextureSet], out: Path, name: str = "model", extras: dict | None = None) -> dict:
    """Model -> skinned GLB at `out` (bind pose, metres). -> {path, triangles, textures, roles}."""
    from .melee_models import write_gltf
    prims = model_prims(m, sets)
    gp = []
    for p in prims:
        gp.append({"pos": p["pos"], "nrm": p["nrm"], "uv": p["uv"], "tris": p["tris"], "J": p["J"], "W": p["W"],
                   "tex": p["image"], "color": (255, 255, 255, 255), "wrap": (10497, 10497),
                   "name": f"m{p['mesh']:02d}p{p['part']}_{p['tex']:06x}"})
    tmp = Path(out).with_suffix(".gltf")
    write_gltf(tmp, joints_of(m), gp, 1.0, name, joint_names(m), extras=extras or {})
    gl = json.loads(tmp.read_text())
    tmp.unlink()
    gl["asset"]["generator"] = "gbox twin_snakes"
    Path(out).write_bytes(gltf_to_glb(gl))
    return {"path": Path(out), "triangles": int(sum(len(p["tris"]) for p in prims)),
            "textures": len({p["tex"] for p in prims if p["image"] is not None}),
            "missing_textures": sorted({f"{p['tex']:06x}" for p in prims if p["image"] is None}),
            "roles": roles_of(m), "stats": K.stats(m)}


# --------------------------------------------------------------------------------------------- the disc

@functools.lru_cache(maxsize=4)
def _stage(image: str, stamp: float, name: str) -> S.Stage:
    from .gcdisc import GCDisc
    d = GCDisc(image)
    try:
        if d.game_id != DISC_ID:
            raise ValueError(f"{Path(image).name}: expected {DISC_ID}, got {d.game_id}")
        return S.StageDat.from_disc(d).stage(name)
    finally:
        d.f.close()


def stage_of(image: Path, name: str) -> S.Stage:
    p = Path(image)
    return _stage(str(p), p.stat().st_mtime, name)


def disc_number(image: Path) -> int:
    with open(image, "rb") as f:
        return disc_of(header=f.read(8))


def read_model(stage: S.Stage, key: str) -> K.Kms:
    f = stage.find(model_hash(key), S.MODEL)
    if f is None:
        raise ValueError(f"stage {stage.name} has no model {key}")
    return K.parse(f.data)


def extract(image: Path, key: str, out: Path, name: str = "") -> dict:
    c = cast_entry(key)
    disc = disc_number(image)
    stage = c["stage"].get(disc)
    if stage is None:
        raise ValueError(f"{c['name']} is not on disc {disc} (discs {sorted(c['stage'])})")
    st = stage_of(image, stage)
    m = read_model(st, key)
    r = export(m, texture_sets(st), out, name or c["name"], {"tts_model": key, "tts_stage": stage})
    return r | {"stage": stage, "disc": disc, "model_bytes": len(m.data)}


def _image(ctx, game) -> Path:
    from . import characters as C
    return C._gc_iso(ctx, game)


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run for one roster entry (characters.extract_dedicated)."""
    key = e.get("key") or next(c["key"] for c in CAST if slug_of(c["key"]) == e["slug"])
    image = _image(ctx, game)
    ctx.progress(30, f"Reading stage.dat for {e['name']}")
    r = extract(image, key, Path(work) / f"{e['slug']}.glb", e["name"])
    ctx.progress(70, f"{e['name']}: {r['triangles']} triangles, {r['textures']} textures")
    extra = {"tts_reader": READER_VERSION, "tts_model": key, "tts_stage": r["stage"], "tts_disc": r["disc"],
             "tts_slot": slot_for_key(key), "native_player": key == "snake_def"}
    return {"files": [r["path"]], "tool": "gbox.twin_snakes (stage.dat / kms reader)",
            "source_files": [f"stage.dat:{r['stage']}:{key}.kms"], "roles": r["roles"], "extra": extra,
            "notes": f"{r['triangles']} triangles, {r['textures']} colour textures, 21-bone MGS2 skeleton with "
                     f"envelope weights, from stage {r['stage']} (disc {r['disc']}). Writer slot: characters op=use "
                     f"slot={slot_for_key(key)}."}


def slot_for_key(key: str) -> str:
    return "player" if key == "snake_def" else f"model:{key}"


def main(argv=None) -> int:
    import argparse
    from . import characters as C
    ap = argparse.ArgumentParser(description="Twin Snakes cast -> rigged GLBs")
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("keys", nargs="*")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    disc = disc_number(Path(a.image))
    ok = True
    for c in CAST:
        if (a.keys and c["key"] not in a.keys) or disc not in c["stage"]:
            continue
        try:
            r = extract(Path(a.image), c["key"], out / f"{slug_of(c['key'])}.glb", c["name"])
            C.render_preview(r["path"], out / f"{slug_of(c['key'])}.png")
            print(json.dumps({"key": c["key"], "stage": r["stage"], "triangles": r["triangles"],
                              "textures": r["textures"], "missing": r["missing_textures"]}), flush=True)
        except Exception as err:                         # noqa: BLE001 - report every character
            ok = False
            print(json.dumps({"key": c["key"], "error": f"{type(err).__name__}: {err}"}), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
