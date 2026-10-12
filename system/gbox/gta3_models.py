"""GTA III (PS2) native character reader: extract ped clumps from MODELS/GTA3.IMG to skinned glTF.

Uses gbox.gta_rw (RenderWare DFF/TXD/IMG parser, already round-tripped on the GTA III USA disc). GTA III
peds are rigid-part models animated by frame name; the exported glTF treats each frame as a joint with a
single weight per vertex, which is exactly what gbox.gta3_swap expects for retargeting.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import gta_rw as R
from .gta3_swap import GTA3_ROLES, iso_from_rom, SKINS
from . import filemods

GAME_IDS = {"265819390074bb4e": "Grand Theft Auto III (USA, Canada)"}


def roster() -> list[dict]:
    """The GTA III player skins in MODELS/GTA3.IMG (Claude + prison outfit + playerx).

    The full ped roster could be extended by scanning GTA3.DIR for every .dff/.txd pair; these three are the
    ones gta3_swap writes, so registering them also validates the writer's source rig.
    """
    return [
        {"key": "player", "slug": "gta3_claude", "name": "Claude (GTA III)",
         "aliases": ["Claude", "GTA III Claude", "GTA III player"], "kind": "character"},
        {"key": "playerp", "slug": "gta3_claude_prison", "name": "Claude (prison outfit, GTA III)",
         "aliases": ["Claude prison", "GTA III prison Claude"], "kind": "character"},
        {"key": "playerx", "slug": "gta3_claude_x", "name": "Claude (playerx, GTA III)",
         "aliases": ["Claude playerx"], "kind": "character"},
    ]


def _rgba_from_txd(txd: bytes, name: str | None = None) -> np.ndarray | None:
    """Pick a PS2 raster from a TXD and return it as RGBA.

    If a texture name is given, match it exactly. Otherwise prefer an 8-bit
    raster (GTA III player textures are 8-bit 256x256) and fall back to the
    largest available raster. This keeps 4-bit companion rasters (e.g.
    ``shot_all`` in ``playerx.txd``) from blocking extraction while still
    texturing the model with the main atlas.
    """
    root, _ = R.parse(txd)
    rasters = [R.texnative_read(t) for t in root.find(R.TEXNATIVE)]
    if not rasters:
        return None
    if name is not None:
        for r in rasters:
            if r.name.lower() == name.lower():
                return R.raster_rgba(r)
    # Prefer 8-bit, then the largest area (usually the main character atlas).
    candidates = sorted(rasters, key=lambda r: (r.depth != 8, -(r.width * r.height)))
    return R.raster_rgba(candidates[0])


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract for GTA III PS2: one .dff/.txd pair -> skinned .glb + body roles."""
    from . import characters as C
    rom = C._rom(ctx, game)
    iso = iso_from_rom(rom, filemods.base_dir(ctx.config, game["game_id"]) / (Path(rom).stem + ".iso"), ctx.progress)
    key = e["key"]
    disc = R.GtaDisc(iso)
    try:
        dff = disc.entry(f"{key}.dff")
        txd = disc.entry(f"{key}.txd")
    finally:
        disc.close()
    rgba = _rgba_from_txd(txd)
    out = Path(work) / f"gta3_{key}.glb"
    R.clump_to_gltf(dff, out, rgba, key)
    root, _ = R.parse(dff)
    frames = R.frames_read(root.first(R.FRAMELIST))
    geoms = root.first(R.GEOMLIST).find(R.GEOMETRY)
    verts = sum(len(R.geometry_read(g).pos) for g in geoms)
    return {
        "files": [out],
        "tool": "gbox.gta3_models",
        "roles": dict(GTA3_ROLES),
        "source_files": [f"MODELS/GTA3.IMG: {key}.dff, {key}.txd"],
        "notes": f"GTA III {key}.dff: {len(frames)} rigid frames, {verts} vertices, PS2 8-bit TXD",
    }
