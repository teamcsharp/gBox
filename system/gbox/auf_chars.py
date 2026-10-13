"""007: Agent Under Fire (GameCube, GW7E69) character-tool integration.

This module wires the existing :mod:`gbox.auf_ngc_writer` package swap into the
universal ``characters`` tool.  Two operations are supported:

* ``characters op=use character=<AUF actor slug> game=<AUF> slot=<target actor .gcm>``
  replaces one actor .gcm with another actor from the same level (same skeleton).

* ``characters op=match game=<AUF> pairs=[{character,donor},...]`` or
  ``slot=cast`` replaces many / all actors in a level.  With ``random=true``
  every compatible actor slot is assigned a random donor from the provided list.

Cross-game replacement (e.g. a Def Jam wrestler into AUF) is not implemented
yet: AUF .gcm geometry is NGC GX matrix-palette skinning and a glTF-to-.gcm
retargeting encoder is still required.  Same-game cast randomization is live.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import hashlib
import tempfile
from gbox import auf_ngc as ngc
from gbox import auf_ngc_writer as W
from gbox import filemods
from gbox.characters import slugify

GAME_ID = "65b7187589166b26"
GAME_IDS = {GAME_ID}
DEFAULT_LEVEL = "maps/dm1.ngc"


def _game_path(game: dict) -> Path:
    """Resolve a disc path via the catalog / rom_path helpers used by gbox.tools."""
    from gbox.tools import rom_path
    return Path(rom_path(game))


def _level_from_input(inp, default: str = DEFAULT_LEVEL) -> str:
    return getattr(inp, "level", None) or default


def _read_level(gcz: Path, level: str) -> "ngc.NgcPackage":
    from gbox import au_inventory
    with tempfile.TemporaryDirectory() as td:
        got = au_inventory.extract(str(gcz), [Path(level).name], td)
        src = Path(got[0]["out"]).read_bytes()
    return ngc.NgcPackage(src)


def _build_mod(cfg, game: dict, level: str, name: str, assignments: dict,
               progress=None) -> dict:
    gcz = _game_path(game)
    pkg = _read_level(gcz, level)
    data, report = W.cast_swap(pkg, assignments, progress=progress)
    chk = W.check_package(data, {t: hashlib.sha256(pkg.read(d)).hexdigest()
                                 for t, d in report["assignments"].items()})
    if chk["problems"]:
        raise ValueError("rebuilt %s failed its check: %s" % (level, chk["problems"][:5]))
    b = filemods.build_image(cfg, GAME_ID, gcz, name, {level: {"bytes": data}}, progress)
    mj = {"name": name, "game_id": GAME_ID, "image": Path(b["image"]).name,
          "title": name, "built": time.time(),
          "files": [f"{level}: actor .gcm swaps (gbox.auf_ngc_writer)"],
          "level": level, "assignments": report["assignments"],
          "verified_in_game": False}
    (Path(b["dir"]) / ".gbox-mod.json").write_text(json.dumps(mj))
    return b | {"level": level, "level_sha256": hashlib.sha256(data).hexdigest(),
                "assignments": report, "check": chk}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use: slot = an actor .gcm path in the level (e.g.
    ``models/actors/bond/bond_combat_l.gcm``); character must be an AUF actor
    that has a compatible skeleton.  Cross-game characters are reported as not
    yet supported."""
    from gbox import characters as C
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": needs(game)["have"]}
    if not C.library_root(ctx.config).is_dir():
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers")
                   if w.get("os") == "linux"), None)
        args = {"op": inp.op, "character": inp.character, "game_id": gid,
                "slot": inp.slot, "rebuild": inp.rebuild, "launch": False}
        j = C._job(ctx, "characters", args, cp, 1800)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        return r
    level = _level_from_input(inp)
    # same-game: the character slug must name an AUF actor .gcm in the level
    gcz = _game_path(game)
    pkg = _read_level(gcz, level)
    targets = W.actor_gcms(pkg)
    slot = inp.slot or targets[0] if targets else None
    if not slot:
        raise ValueError("no actor .gcm slots found in %s" % level)
    donor = next((n for n in targets if n.lower().endswith("/" + meta["slug"] + ".gcm")
                  or n.lower().endswith("/" + meta["slug"].split("_")[-1] + ".gcm")), None)
    if donor is None:
        # cross-game request
        return {"status": "not_yet_supported",
                "message": "Cross-game character replacement into AUF needs a glTF-to-.gcm retargeting encoder; "
                           "use op=match with AUF actor donors or slot=cast random=true for same-game cast swaps."}
    name = "auf_%s_as_%s" % (meta["slug"], Path(slot).stem)
    return _finish(ctx, game, meta, slot, name, {slot: donor}, level=level)


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]],
          title: str | None = None) -> dict:
    """characters op=match for AUF.  ``pairs`` are (target .gcm, donor .gcm).
    With ``inp.random=true`` the pairs are ignored and every actor slot is
    assigned a random compatible donor from ``inp.donors`` (or every actor in
    the level)."""
    from gbox import characters as C
    from gbox.characters import best_match
    gid = game["game_id"]
    level = _level_from_input(inp)
    gcz = _game_path(game)
    pkg = _read_level(gcz, level)
    targets = W.actor_gcms(pkg)
    if getattr(inp, "random", False) or inp.slot == "cast":
        donor_pool = getattr(inp, "donors", None) or targets
        seed = getattr(inp, "seed", None)
        assignments = W.random_cast_assignments(pkg, donor_pool, seed=seed)
    else:
        assignments = {}
        for tq, dq in pairs_in:
            donor = dq or tq
            if donor.lower() not in [n.lower() for n in targets]:
                raise LookupError(f"{donor!r} is not an actor .gcm in {level}")
            target = tq
            if target.lower() not in [n.lower() for n in targets]:
                raise LookupError(f"{target!r} is not an actor .gcm in {level}")
            assignments[target] = donor
    if not assignments:
        raise ValueError("no compatible actor swaps could be assigned in %s" % level)
    names = sorted(set(assignments.values()))
    name = "auf_cast_" + "_".join(Path(n).stem for n in names[:3])
    if title:
        name = "auf_" + C.slugify(title)
    return _finish(ctx, game, {"name": title or name, "slug": name}, "cast", name, assignments, level=level)


def _finish(ctx, game: dict, meta: dict, slot: str, name: str, assignments: dict, level: str = DEFAULT_LEVEL) -> dict:
    from gbox import characters as C
    import hashlib
    have = (filemods.mod_dir(ctx.config, GAME_ID, name) / ".gbox-mod.json").exists()
    built = None
    rebuild = getattr(getattr(ctx, "inp", None), "rebuild", False) if hasattr(getattr(ctx, "inp", None), "rebuild") else False
    if rebuild or not have:
        built = _build_mod(ctx.config, game, level, name, assignments, ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": GAME_ID, "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                     "notes": "AUF same-game actor .gcm swap (gbox.auf_ngc_writer); cross-game retargeting not yet built"})
    return {"status": "built" if built else "ready", "mod": name, "slot": slot,
            "character": meta.get("name", meta.get("slug")), "slug": meta["slug"],
            "game": game["title"], "game_id": GAME_ID,
            "assignments": assignments,
            "message": "AUF cast swap mod is built.  It replaces in-level actor .gcm files whose skeletons are "
                       "compatible.  Cross-game (WWE wrestlers etc.) needs a retargeting encoder and is not done yet."}


def needs(game: dict) -> dict:
    return {"target": "an actor .gcm in maps/dm*.ngc",
            "format": "NGCObject3D / GX matrix-palette skinning (gbox/auf_ngc.py)",
            "steps": ["glTF-to-.gcm retargeting encoder for cross-game donors"],
            "have": "same-game actor .gcm swaps and cast randomization (gbox/auf_chars.py)"}


def roster() -> list[dict]:
    """Roster placeholder: AUF actors are discovered per-level from the restable."""
    return []


def extract_run(ctx, game: dict, what: str, work: Path) -> dict:
    """Extract one AUF actor .gcm as a glTF into the collection."""
    from gbox import characters as C
    gcz = _game_path(game)
    level = _level_from_input(ctx, DEFAULT_LEVEL)
    pkg = _read_level(gcz, level)
    targets = W.actor_gcms(pkg)
    name = next((n for n in targets if what.lower() in n.lower().replace(".gcm", "").split("/")[-1]), None)
    if name is None:
        return {"status": "not_in_roster", "roster": [Path(n).name for n in targets]}
    gcm = pkg.read(name)
    m = ngc.mesh(gcm)
    slug = "auf_" + slugify(Path(name).stem)
    glb = work / f"{slug}.glb"
    ngc.to_glb(m, glb, slug)
    st = C.model_stats(glb)
    roles = {}  # roles not yet mapped for AUF skeletons
    return C.add(C.library_root(ctx.config), slug, Path(name).name, [glb],
                 {"game_id": GAME_ID, "game_title": game["title"], "file": name},
                 "gbox.auf_chars", rig={**st.pop("rig"), "roles": roles},
                 aliases=[f"AUF {Path(name).stem}"],
                 notes="AUF actor extracted from level package; skeleton hashes are available for same-game swaps")
