"""GTA Vice City (PS2) native player swap: a library character replaces Tommy Vercetti (player.dff + player.txd
in MODELS/GTA3.IMG on the Vice City DVD), keeping his rigid-frame rig so every ped animation, the controls and the
car entry/exit still drive the new body.

This reuses the RenderWare DFF/TXD/IMG parser from gbox.gta3_swap; only the frame-name -> body-role map differs.
The player model layout is identical to GTA III: one clump with named frames and one geometry per frame.

Game IDs: filled from the catalog once the owned Vice City disc is scanned. The placeholder below is overwritten by
char_coverage when the real catalog ID is known.
"""
from __future__ import annotations

from pathlib import Path

from . import filemods
from . import gta3_swap as S3
from . import gta_rw as R

# TODO: replace with the catalog ID from a scanned "Grand Theft Auto - Vice City (USA)" disc.
# char_coverage.coverage() will match the title/platform if this placeholder is never updated.
GAME_IDS: dict[str, str] = {"0000000000000000": "Grand Theft Auto - Vice City (USA) (placeholder catalog ID)"}
SECTOR = R.SECTOR
ENTRIES = ("player.dff", "player.txd")
# Tommy Vercetti's frame names are not yet verified against an owned disc; this is the best-guess mapping
# based on GTA III / RenderWare ped conventions and will be tightened once the real frame list is read.
VC_ROLES = {
    "pelvis": "player", "hip": "waist", "chest": "torso", "neck": "neck", "head": "head",
    "l_upper": "upperarml", "l_fore": "lowerarml", "l_hand": "handl",
    "r_upper": "upperarmr", "r_fore": "lowerarmr", "r_hand": "handr",
    "l_thigh": "upperlegl", "l_shin": "lowerlegl", "l_foot": "footl",
    "r_thigh": "upperlegr", "r_shin": "lowerlegr", "r_foot": "footr",
}
SKINS = ("player",)


def _title_matches_vc(game: dict) -> bool:
    t = (game.get("title") or "").lower()
    return "grand theft auto" in t and "vice city" in t and "stories" not in t and game.get("platform") == "ps2"


def build_mod(cfg, game: dict, rom: Path, src_model: Path, roles: dict, name: str, progress=None) -> dict:
    """Vice City disc-image mod: player.dff/.txd replaced in every MODELS/GTA3.IMG copy."""
    return S3.build_mod(cfg, game, rom, src_model, roles, name, progress=progress, mod_roles=VC_ROLES)


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for GTA Vice City PS2 slot=player: build gtavc_<slug>."""
    from . import characters as C
    gid, name = game["game_id"], f"gtavc_{meta['slug']}"
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = None
    if inp.rebuild or not have:
        roles = meta.get("rig", {}).get("roles")
        if not roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't fit it to Tommy's frames")
        built = build_mod(ctx.config, game, C._rom(ctx, game), C._local_or_fetch(ctx, meta, meta["model"]),
                          roles, name, progress=ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": "replaces Tommy Vercetti (player.dff/.txd in every MODELS/GTA3.IMG copy; his rigid-frame animations stay)"})
    res = {"mod": name, "build": built, "replaces": "Tommy Vercetti, the Vice City player (special model 'player')"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    return res | {"status": "launching", "launch_job": lj.get("id"), "node": node,
                  "message": f"GTA Vice City mod {name} is launching; start a new game (a save state restores Tommy from RAM)."}
