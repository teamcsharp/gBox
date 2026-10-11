"""Typed DOA2 RE operations available to gBox and Hermes through MCP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool


class Doa2In(BaseModel):
    op: Literal["inspect", "decompose", "build", "motions"] = "inspect"
    game_id: str = "1de2e7634f3161ff"
    fighter: str = "Kasumi"               # fighter name/family; decompose also supports all
    costume: str = "00"                  # decompose also supports all
    character: str = ""                  # build: donor library slug/name
    profile: str = ""                    # optional override relative to analysis/doa2/<game_id>/rigs
    allow_downscale: bool = False


class Doa2Out(BaseModel):
    result: dict


def selected_costumes(files: dict, fighter: str, costume: str) -> list[tuple[str, str]]:
    """Resolve only actual costume pairs; never silently fall back to another."""
    from .doa2_chars import roster
    from .doa2_swap import fighter_slot
    families = roster(files)
    if fighter.casefold() != "all":
        family, specified = fighter_slot(fighter)
        families = [f for f in families if f["key"] == family]
        costume = specified or costume
    result = []
    for family in families:
        choices = family["costumes"]
        if costume.casefold() != "all":
            if not costume.isdigit() or len(costume) > 2:
                raise ValueError("Costume must be a decimal number or all")
            choices = [c for c in choices if int(c) == int(costume)]
        for c in choices:
            if all(f"DOA2/{family['key']}{c.zfill(2)}.{ext}" in files for ext in ("CHR", "BIN", "SUP")):
                result.append((family["key"], c.zfill(2)))
    if not result:
        raise ValueError("Requested fighter costume is absent from the owned disc")
    return result


def profile_file(root: Path, relative: str) -> Path:
    if not relative:
        raise ValueError("Build requires a verified runtime rig profile")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != ".json" or not path.is_file():
        raise ValueError("Rig profile must be a JSON file inside this game's rig directory")
    return path


def _validate(out: Doa2Out, artifacts: dict) -> list[str]:
    report = artifacts.get("doa2-report.json")
    if not report or json.loads(report) != out.result:
        return ["DOA2 report does not match the operation result"]
    return []


@tool("doa2_assets", "1.0", Doa2In, Doa2Out, capabilities=["analysis", "asset", "modding"],
      permissions=[P.READ, P.STAGE, P.EXECUTE], timeout_s=3600,
      side_effects=["writes decomposed assets and modified disc copies into the cache/analysis folders"],
      artifacts=["doa2-report.json"], validation="native archive validation and operation report match",
      validate=_validate)
def doa2_assets(inp: Doa2In, ctx):
    """Inspect/decompose DOA2 native fighter geometry, textures and motion files, or build a copied ROM
    with a donor character retargeted to the native executable rest rig. Does not substitute an overlay or certify gameplay.
    Inspect/decompose supports fighter=all costume=all. Build derives transforms from owned native tables and SUP axes, then neutralizes stale APV/SUP/cloth offsets.
    """
    from . import characters as C, doa2_chars, doa2_geometry as G, doa2_textures as T, doa2_swap as S
    from .gdrom import GDRom
    from .filemods import mod_dir
    if inp.game_id not in S.GAME_IDS:
        raise ValueError("This native format implementation only supports DOA2 Limited Edition Japan")
    game = C._api(ctx, "GET", f"/api/catalog/{inp.game_id}")
    gdi = C._dc_gdi(ctx, game)
    disc = GDRom(gdi)
    executable_sha = hashlib.sha256(disc.read("1ST_READ.BIN")).hexdigest()
    if executable_sha != S.EXECUTABLE_SHA256:
        raise ValueError("Unsupported executable identity")
    selected = [] if inp.op == "motions" else selected_costumes(disc.files, inp.fighter, inp.costume)
    analysis = Path(ctx.config.data_dir) / "analysis" / "doa2" / inp.game_id
    if inp.op == "motions":
        from . import doa2_motion
        names=sorted(name for name in disc.files if name.endswith('.MOT'))
        motions=[]
        for index,name in enumerate(names):
            ctx.progress(5+90*index/len(names),f'Motion records: {name}')
            data=disc.read(name)
            try:
                motion=doa2_motion.inspect_mot(data,include_clips=True)
                motions.append({'file':name,'status':'records_verified','motion':motion})
            except doa2_motion.MotionFormatError as error:
                motions.append({'file':name,'status':'unsupported_encoding','bytes':len(data),
                                'sha256':hashlib.sha256(data).hexdigest(),'reason':str(error)})
        result={'op':'motions','game_id':inp.game_id,'motions':motions,
                'interpolation_decoded':False,'native_animation_policy':'preserve original MOT bytes'}
    elif inp.op == "build":
        if inp.fighter.casefold() == "all":
            raise ValueError("Build requires an explicit fighter")
        if inp.profile and len(selected) != 1:
            raise ValueError("A profile override requires one explicit costume")
        root = C.library_root(ctx.config)
        meta = C.find(C.list_all(root), inp.character)
        if not meta:
            raise ValueError("Donor character is absent from the library")
        family = selected[0][0]
        costume = selected[0][1] if len(selected) == 1 else "all"
        suffix = '' if costume == 'all' else costume
        output = mod_dir(ctx.config, inp.game_id, f"doa2_{family.lower()}{suffix}_{meta['slug']}")
        if inp.profile:
            profile = json.loads(profile_file(analysis / "rigs", inp.profile).read_text(encoding="utf-8"))
            result = S.build(gdi, root / meta["slug"], output, family, costume, profile,
                             allow_downscale=inp.allow_downscale, progress=ctx.progress)
        else:
            result = S.build_fighter(gdi, root / meta["slug"], output, family, costume,
                                     allow_downscale=inp.allow_downscale, progress=ctx.progress)
    else:
        entries = []
        for index, (family, costume) in enumerate(selected):
            ctx.progress(10 + 85 * index / len(selected), f"{inp.op}: {family}{costume} ({index+1}/{len(selected)})")
            stem = f"DOA2/{family}{costume}"
            chr_data, bin_data = disc.read(stem + ".CHR"), disc.read(stem + ".BIN")
            archive = G.decode_chr(chr_data)
            if G.roundtrip_chr(archive) != chr_data:
                raise AssertionError(f"Native reconstruction mismatch: {stem}")
            textures = T.descriptors(chr_data, bin_data)
            entry = {"fighter": family, "costume": costume, "models": len(archive["models"]),
                     "textures": len(textures), "triangles": sum(len(mesh["triangles"]) for model in archive["models"]
                                                                     for mesh in model["meshes"]),
                     "chr_sha256": hashlib.sha256(chr_data).hexdigest(),
                     "bin_sha256": hashlib.sha256(bin_data).hexdigest(), "reconstruction": "byte_exact"}
            if inp.op == "decompose":
                output = analysis / "assets" / (family + costume)
                exported = doa2_chars.export(str(gdi), str(output), family, costume)
                entry.update(path=str(output), files=exported["files"], confidence=exported["manifest"]["confidence"])
            entries.append(entry)
        result = {"op": inp.op, "game_id": inp.game_id, "executable_sha256": executable_sha,
                  "costumes": entries, "gameplay_verified": False,
                  "animation_rig": "native rest vectors and SUP axis graph; MOT channels retain their native IK semantics"}
    result = json.loads(json.dumps(result, default=str))
    ctx.artifact("doa2-report.json", json.dumps(result, indent=2).encode(), "application/json", game_id=inp.game_id)
    ctx.progress(100, f"DOA2 {inp.op} completed; gameplay acceptance is separate")
    return {"result": result}
