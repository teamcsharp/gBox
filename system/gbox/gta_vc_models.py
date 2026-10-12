"""GTA Vice City (PS2) native character reader: extract the player ped clump from MODELS/GTA3.IMG to skinned glTF.

Uses gbox.gta_rw (RenderWare DFF/TXD/IMG parser, already round-tripped on the GTA III USA disc). Vice City shares the
same engine and archive layout; the frame names differ from Claude's and are mapped in gbox.gta_vc_swap.VC_ROLES.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import gta_rw as R
from . import gta_vc_swap as S
from . import gta3_swap as S3
from . import filemods

# Placeholder; replaced when the owned Vice City disc is catalogued.
GAME_IDS: dict[str, str] = {"0000000000000000": "Grand Theft Auto - Vice City (USA) (placeholder catalog ID)"}


def roster() -> list[dict]:
    """The Vice City player model in MODELS/GTA3.IMG (Tommy Vercetti)."""
    return [
        {"key": "player", "slug": "gtavc_tommy", "name": "Tommy Vercetti (GTA Vice City)",
         "aliases": ["Tommy", "Tommy Vercetti", "GTA Vice City player"], "kind": "character"},
    ]


def _rgba_from_txd(txd: bytes, name: str | None = None) -> np.ndarray | None:
    """First (or named) 8-bit PS2 raster from a TXD as RGBA."""
    root, _ = R.parse(txd)
    rasters = [R.texnative_read(t) for t in root.find(R.TEXNATIVE)]
    if not rasters:
        return None
    for r in rasters:
        if name is None or r.name.lower() == name.lower():
            return R.raster_rgba(r)
    return R.raster_rgba(rasters[0])


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract for GTA Vice City PS2: player.dff/.txd -> skinned .glb + body roles."""
    from . import characters as C
    rom = C._rom(ctx, game)
    iso = S.iso_from_rom(rom, filemods.base_dir(ctx.config, game["game_id"]) / (Path(rom).stem + ".iso"), ctx.progress)
    key = e["key"]
    disc = R.GtaDisc(iso)
    try:
        dff = disc.entry(f"{key}.dff")
        txd = disc.entry(f"{key}.txd")
    finally:
        disc.close()
    rgba = _rgba_from_txd(txd)
    out = Path(work) / f"gtavc_{key}.glb"
    R.clump_to_gltf(dff, out, rgba, key)
    root, _ = R.parse(dff)
    frames = R.frames_read(root.first(R.FRAMELIST))
    geoms = root.first(R.GEOMLIST).find(R.GEOMETRY)
    verts = sum(len(R.geometry_read(g).pos) for g in geoms)
    return {
        "files": [out],
        "tool": "gbox.gta_vc_models",
        "roles": dict(S.VC_ROLES),
        "source_files": [f"MODELS/GTA3.IMG: {key}.dff, {key}.txd"],
        "notes": f"GTA Vice City {key}.dff: {len(frames)} rigid frames, {verts} vertices, PS2 8-bit TXD",
    }
