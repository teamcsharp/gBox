"""007: Agent Under Fire (GameCube, GW7E69; gBox game 65b7187589166b26): the cast as collection characters.

``characters op=collect`` reads every body model of the cast (gbox.auf_swap.NAMES: Bond's outfits, the henchmen, the
bosses, the other people and the 16 multiplayer characters) straight off the owned disc and adds each one to the
character library as a rigged, textured GLB with body roles, so AUF characters can be donors in other games' writers.

Per body (one roster entry each, deduplicated over the 38 levels):
  * one representative level (``level_of``: the first mission level that has the body, else the first multiplayer
    map), read through the disc's FST (auf_swap._disc_reader) and parsed as a ``maps/*.ngc`` package (gbox.auf_ngc);
  * the level's entity scripts (``models/*.men``, auf_swap.level_cast) name the body's LOD models and head; the entity
    that wears the body is picked by LOD (``_h`` first), then mission class (Player, actor) before DeathmatchPlayer,
    then script name; the highest LOD of its body and of its head are used;
  * body: auf_ngc.mesh (skeleton, matrix palette, two-bone skin, UVs) and the level's textures per geom section;
  * head: the separate head model shares the body's skeleton by bone name hash (its extra face bones fold onto their
    nearest ancestor the body has); its vertices are moved from the head model's rest pose onto the body's and its
    sections appended, so the character is one skinned mesh on one skeleton;
  * body roles from the topology (auf_gcm.auto_roles, all 18 roles on all 127 shipped actor models);
  * exported in the library frame (left +X, up +Y, facing +Z: auf_swap.A2R), native units (about 85 = Bond's height),
    textures opaque (AUF draws characters opaque; auf_swap.donor_materials does the same for donors).

Names come from the entity scripts: the display name from auf_swap.NAMES, aliases from the ``.men`` scripts that wear
the body (MEN snapshot), their ``classname`` (Player / actor / DeathmatchPlayer) and the multiplayer pick names
(``mp_player_<name>``). The writer's slots stay in gbox.auf_swap (roster() / cast_slots()); each entry records its
slot (``model:<body>``) so a collected character can be put back into its own slot.

    python -m gbox.auf_chars <disc .gcz/.iso> <out dir> [body ...]
"""
from __future__ import annotations

import functools
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

from . import auf_gcm as G
from . import auf_ngc as N
from . import auf_swap as S

# 1: the roster listed only the writer's slots and extracted nothing; 2: every body extracted as a rigged GLB.
READER_VERSION = 2
GAME_ID = S.GAME_ID
GAME_IDS = S.GAME_IDS
GAME_TITLE = "007 Agent Under Fire"
LOD_RANK = {"h": 0, "m": 1, "l": 2}
CLASS_RANK = {"player": 0, "actor": 1, "deathmatchplayer": 2}
CLASSNAMES = {"player": "Player", "actor": "actor", "deathmatchplayer": "DeathmatchPlayer"}


# --------------------------------------------------------------------------------------------- roster

def classname_of(script: str) -> str:
    """The entity class a .men script of the MEN snapshot spawns (read from its init block on the disc)."""
    s = script.lower()
    if s.startswith("mp_player_"):
        return "DeathmatchPlayer"
    return "Player" if s == "bond" else "actor"


def level_of(key: str, levels: dict | None = None) -> str:
    """The representative level of a body: the first mission level (sorted) that has it, else the first map."""
    levels = levels or S.level_keys()
    have = sorted(lv for lv, ks in levels.items() if key in ks)
    if not have:
        raise ValueError(f"no level has the AUF body {key!r}")
    missions = [lv for lv in have if lv in S.MISSION_CAST]
    return (missions or have)[0]


def roster() -> list[dict]:
    """Every body model of the cast as a collectable character (one per body; slug auf_<body>)."""
    levels = S.level_keys()
    out = []
    for key, (name, kind) in sorted(S.NAMES.items(), key=lambda kv: (kv[1][1], kv[0])):
        scripts = S.MEN.get(key, "").split()
        mp = [s[len("mp_player_"):] for s in scripts if s.startswith("mp_player_")]
        classes = sorted({classname_of(s) for s in scripts})
        aliases = [name, key, f"{name} ({GAME_TITLE})", *scripts, *mp]
        out.append({"key": key, "slug": f"auf_{key}", "name": name, "kind": "character",
                    "aliases": list(dict.fromkeys(aliases)), "role": kind, "slot": f"model:{key}",
                    "men": scripts, "classnames": classes, "multiplayer": bool(mp), "mp_names": mp,
                    "level": level_of(key, levels), "levels": sorted(lv for lv, ks in levels.items() if key in ks)})
    return out


# --------------------------------------------------------------------------------------------- one character

def lod_of(name: str) -> str:
    stem = Path(name).stem.lower()
    return stem[-1] if len(stem) > 2 and stem[-2] == "_" and stem[-1] in LOD_RANK else ""


def _best_lod(names: list[str]) -> str | None:
    return min(names, key=lambda n: (LOD_RANK.get(lod_of(n), 3), n)) if names else None


def pick(cast: list, key: str):
    """The entity of a level that shows a body best: highest body LOD, mission class first, then script name."""
    mine = [c for c in cast if c.key == key]
    if not mine:
        return None
    return min(mine, key=lambda c: (LOD_RANK.get(lod_of(_best_lod(c.bodies)), 3), CLASS_RANK.get(c.cls, 3),
                                    not c.heads, c.men))


def entity_facts(pkg: "N.NgcPackage", men: str) -> dict:
    """classname / animations / sounds of a .men script as written (not lower-cased)."""
    r = next((x for x in pkg.resources() if x.name == men), None)
    if r is None:
        return {}
    toks = S.men_tokens(pkg.table[r.offset:r.offset + r.size], S.script_strings(pkg))
    out = {}
    for k in ("classname", "animations", "sounds"):
        if k in toks and toks.index(k) + 1 < len(toks):
            out[k] = toks[toks.index(k) + 1]
    return out


def _bone_mat(b) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(b["rot"], float), np.asarray(b["world_pos"], float)


def merge_head(body: dict, head: dict, fallback: int | None = None) -> dict:
    """Body mesh + head mesh (auf_ngc.mesh dicts) on the body's skeleton: head joints map by bone name hash (extra
    face bones onto their nearest mapped ancestor; the head models' own extra root chain, which no vertex uses on the
    disc, onto ``fallback``, the body's head bone), head vertices move from the head model's rest pose onto the
    body's rest pose through their first joint, head sections follow the body's."""
    bones, hb = body["bones"], head["bones"]
    by_hash = {b["hash"]: b["index"] for b in bones}
    head_by_hash = {b["hash"]: b["index"] for b in hb}
    remap, anchor = [], []                                  # body bone, and the head bone whose rest pose maps onto it
    for b in hb:
        j, seen = b["index"], set()
        while j >= 0 and j not in seen and hb[j]["hash"] not in by_hash:
            seen.add(j)
            j = hb[j]["parent"]
        ok = j >= 0 and j not in seen
        remap.append(by_hash[hb[j]["hash"]] if ok else -1)
        anchor.append(j if ok else -1)
    P = np.asarray(head["positions"], float)
    Nn = np.asarray(head["normals"], float)
    J = np.asarray(head["joints"], int).reshape(-1, 2)
    W = np.asarray(head["weights"], float).reshape(-1, 2)
    if len(P) and any(remap[j] < 0 for j in np.unique(J)):
        if fallback is None:
            raise ValueError("head vertices hang on bones the body does not have")
        fb_head = head_by_hash.get(bones[fallback]["hash"])
        anchor = [a if r >= 0 else (i if fb_head is None else fb_head) for i, (a, r) in enumerate(zip(anchor, remap))]
        remap = [fallback if r < 0 else r for r in remap]
    if len(P):
        first = J[:, 0]
        for hj in np.unique(first):
            Rh, th = _bone_mat(hb[anchor[hj]])
            Rb, tb = _bone_mat(bones[remap[hj]])
            M = Rb @ Rh.T
            sel = first == hj
            P[sel] = (P[sel] - th) @ M.T + tb
            Nn[sel] = Nn[sel] @ M.T
        J = np.asarray(remap)[J]
        same = J[:, 0] == J[:, 1]                           # both influences folded onto one body bone
        W[same] = [1.0, 0.0]
    n0, s0 = len(body["positions"]), len(body["shaders"])
    return {"positions": list(body["positions"]) + P.tolist(), "normals": list(body["normals"]) + Nn.tolist(),
            "uvs": list(body["uvs"]) + list(head["uvs"]), "joints": list(body["joints"]) + J.tolist(),
            "weights": list(body["weights"]) + W.tolist(),
            "faces": list(body["faces"]) + [(a + n0, b + n0, c + n0, s + s0) for a, b, c, s in head["faces"]],
            "shaders": list(body["shaders"]) + list(head["shaders"]), "bones": bones}


def section_images(pkg: "N.NgcPackage", m: dict, shd=None, tex=None) -> list:
    """(png, wrap_s, wrap_t, False) per geom section (opaque: AUF draws characters opaque), None without a texture."""
    out, cache = [], {}
    for t in N.section_textures(pkg, m, shd, tex):
        if t is None:
            out.append(None)
            continue
        if t.id not in cache:
            rgba = bytearray(N.texture_rgba(pkg, t))
            rgba[3::4] = b"\xff" * (len(rgba) // 4)
            cache[t.id] = (N.png_bytes(bytes(rgba), t.width, t.height), t.wrap_s, t.wrap_t, False)
        out.append(cache[t.id])
    return out


def joint_names(bones: list[dict]) -> list[str]:
    return ["bone%02d_%08x" % (i, b["hash"]) for i, b in enumerate(bones)]


def export(pkg: "N.NgcPackage", body: str, head: str | None, out: Path, name: str = "model") -> dict:
    """One character (body model + head model of a level package) -> rigged, textured GLB in the library frame.
    -> {path, roles {role: joint name}, vertices, triangles, sections, textures, body_sha1, head_sha1}"""
    gb = pkg.read(body)
    mb = N.mesh(gb)
    if not mb["bones"]:
        raise ValueError(f"{body}: no skeleton")
    roles_i = G.auto_roles(mb["bones"])
    m, gh, head_error = mb, None, None
    if head:
        gh = pkg.read(head)
        try:
            mh = N.mesh(gh)
        except (ValueError, struct.error) as e:             # a head model without geometry (none on the disc)
            mh, head_error = None, f"{Path(head).name}: {e}"
        if mh is not None and mh["faces"]:
            m = merge_head(mb, mh, roles_i["head"])
    if not m["faces"]:
        raise ValueError(f"{body}: no triangles")
    shd, tex = N.shaders(pkg), N.textures(pkg)
    images = section_images(pkg, m, shd, tex)
    names = joint_names(mb["bones"])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    N.to_glb(m, out, name, basis=S.A2R, names=names)
    N.glb_add_materials(out, m, images)
    return {"path": out, "roles": {r: names[i] for r, i in roles_i.items()}, "vertices": len(m["positions"]),
            "triangles": len(m["faces"]), "sections": len(m["shaders"]),
            "textures": len({im[0] for im in images if im is not None}),
            "body_sha1": hashlib.sha1(gb).hexdigest(), "head_sha1": hashlib.sha1(gh).hexdigest() if gh else None,
            "head_merged": m is not mb, "head_error": head_error}


def extract_body(pkg: "N.NgcPackage", key: str, out: Path, name: str = "") -> dict:
    """A body of a level package -> export() result + the entity facts it was read through."""
    c = pick(S.level_cast(pkg), key)
    if c is None:
        raise ValueError(f"the level has no entity wearing the AUF body {key!r}")
    body, head = _best_lod(c.bodies), _best_lod(c.heads)
    r = export(pkg, body, head, out, name or key)
    facts = entity_facts(pkg, c.men)
    return r | {"body": body, "head": head, "men": c.men, "lod": lod_of(body) or "single",
                "classname": facts.get("classname") or CLASSNAMES.get(c.cls, c.cls),
                "animations": facts.get("animations") or c.anim, "sounds": facts.get("sounds")}


# --------------------------------------------------------------------------------------------- the disc

@functools.lru_cache(maxsize=2)
def _level(image: str, stamp: float, level: str) -> bytes:
    read = S._disc_reader(Path(image))
    try:
        return read(S.level_path(level))
    finally:
        getattr(read, "close", lambda: None)()


def level_bytes(image: Path, level: str) -> bytes:
    """maps/<level>.ngc of an owned .gcz / .iso (the last two levels kept: collect() walks the roster in order)."""
    p = Path(image)
    return _level(str(p), p.stat().st_mtime, level)


def _image(ctx, game) -> Path:
    from . import characters as C
    rom = C._rom(ctx, game)
    return rom if rom.suffix.lower() in (".gcz", ".iso", ".gcm") else C._gc_iso(ctx, game)


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run for one roster entry (characters.extract_dedicated)."""
    key = e.get("key") or e["slug"][len("auf_"):]
    level = e.get("level") or level_of(key)
    image = _image(ctx, game)
    ctx.progress(30, f"Reading maps/{level}.ngc")
    pkg = N.NgcPackage(level_bytes(image, level))
    ctx.progress(50, f"Decoding {e['name']} (body, head, skeleton, textures)")
    r = extract_body(pkg, key, Path(work) / f"{e['slug']}.glb", e["name"])
    src = [f"maps/{level}.ngc:{r['body']}"] + ([f"maps/{level}.ngc:{r['head']}"] if r["head"] else []) + \
          [f"maps/{level}.ngc:{r['men']}"]
    extra = {"auf_reader": READER_VERSION, "auf_body": key, "auf_slot": f"model:{key}", "auf_role": e.get("role"),
             "auf_level": level, "auf_men": r["men"], "auf_classname": r["classname"],
             "auf_animations": r["animations"], "auf_lod": r["lod"], "auf_scripts": e.get("men") or [],
             "auf_multiplayer": bool(e.get("multiplayer")), "auf_mp_names": e.get("mp_names") or [],
             "auf_body_sha1": r["body_sha1"], "auf_head_sha1": r["head_sha1"], "auf_head_merged": r["head_merged"]}
    if r["head_error"]:
        extra["auf_head_error"] = r["head_error"]
    return {"files": [r["path"]], "tool": "gbox.auf_chars (auf_ngc reader)", "source_files": src, "roles": r["roles"],
            "extra": extra,
            "notes": f"{r['triangles']} triangles, {len(r['roles'])} body roles, {r['textures']} textures; body "
                     f"{Path(r['body']).name}" + (f" + head {Path(r['head']).name}" if r["head"] else "") +
                     f" from {level} ({r['men']}, classname {r['classname']}, animations {r['animations']}). "
                     f"Writer slot: characters op=use slot=model:{key}."}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="007 Agent Under Fire GC: the cast as rigged GLBs")
    ap.add_argument("image", help="owned .gcz or .iso")
    ap.add_argument("out")
    ap.add_argument("body", nargs="*", help="body keys (default: all)")
    a = ap.parse_args(argv)
    rows = []
    for e in roster():
        if a.body and e["key"] not in a.body:
            continue
        pkg = N.NgcPackage(level_bytes(Path(a.image), e["level"]))
        try:
            r = extract_body(pkg, e["key"], Path(a.out) / f"{e['slug']}.glb", e["name"])
            rows.append({"slug": e["slug"], "level": e["level"], "body": r["body"], "head": r["head"],
                         "triangles": r["triangles"], "roles": len(r["roles"]), "textures": r["textures"]})
        except (ValueError, KeyError, struct.error) as err:
            rows.append({"slug": e["slug"], "level": e["level"], "error": str(err)})
        print(json.dumps(rows[-1]), flush=True)
    return 0 if all("error" not in r for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
