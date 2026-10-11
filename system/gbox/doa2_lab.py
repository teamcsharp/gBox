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
    op: Literal["inspect", "decompose", "build", "motions", "native_cache", "environments"] = "inspect"
    game_id: str = "1de2e7634f3161ff"
    fighter: str = "Kasumi"               # fighter name/family; decompose also supports all
    costume: str = "00"                  # decompose also supports all
    character: str = ""                  # build: donor library slug/name
    profile: str = ""                    # optional override relative to analysis/doa2/<game_id>/rigs
    allow_downscale: bool = False
    complete_source: bool = True          # decompose: include verified accessories/chains/cloth
    native_cache: str = "native-cloth-cache"  # relative to this game's analysis directory
    cache_action: Literal["prepare", "run", "verify"] = "verify"
    include_details: bool = False        # full provenance is always attached as doa2-details.json
    environment: str = "all"            # environments: STAGE03 (archive, not inferred arena name)
    environment_action: Literal["inspect", "decompose"] = "inspect"


class Doa2Out(BaseModel):
    result: dict


def selected_costumes(files: dict, fighter: str, costume: str, executable: bytes | None = None) -> list[tuple[str, str]]:
    """Resolve only actual costume pairs; never silently fall back to another."""
    from .doa2_chars import roster
    from .doa2_swap import fighter_slot
    families = roster(files)
    if fighter.casefold() != "all":
        try:
            family, specified = fighter_slot(fighter)
        except ValueError:
            from .doa2_chars import VARIANTS
            family = fighter.upper()
            if family not in VARIANTS:
                raise
            specified = None
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
    if executable is not None:
        from .doa2_bindings import parse_render_scripts
        bound = {row['files']['geometry'].upper().rsplit('/', 1)[-1].split('.')[0]
                 for slot in parse_render_scripts(executable) if slot['slot'] not in (19,20,21,22)
                 for row in slot['costumes'] if row['sections']['primary']}
        result = [(family, costume) for family, costume in result if family + costume in bound]
        if not result:
            raise ValueError('Requested archive has no native fighter render binding')
    return result


def profile_file(root: Path, relative: str) -> Path:
    if not relative:
        raise ValueError("Build requires a verified runtime rig profile")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != ".json" or not path.is_file():
        raise ValueError("Rig profile must be a JSON file inside this game's rig directory")
    return path


def cache_directory(analysis: Path, relative: str) -> Path:
    path = (analysis / relative).resolve()
    if not relative or not path.is_relative_to(analysis.resolve()):
        raise ValueError('Native cache must remain inside this game\'s analysis directory')
    return path


def run_cache(ctx, disc, analysis, cache, action):
    from .doa2_native_export import generate_cache as N
    if action == 'prepare':
        return N.prepare(disc, cache)
    if action == 'verify':
        result = N.verify(cache)
        if result.get('errors'):
            raise ValueError('Native cache verification failed: ' + str(result['errors'][:3]))
        return result
    import subprocess
    from .tools import _ghidra_exe, _ghidra_env
    executable = _ghidra_exe(ctx.config)
    if executable is None or not executable.is_file():
        raise ValueError('Native cache execution requires Ghidra on the selected worker')
    seed = cache / '1ST_READ.BIN'
    if not seed.is_file():
        raise ValueError('Run native_cache prepare before executing the owned cloth generators')
    if hashlib.sha256(seed.read_bytes()).hexdigest() != hashlib.sha256(disc.read('1ST_READ.BIN')).hexdigest():
        raise ValueError('Native cache executable does not match this owned disc')
    project = analysis / 'native-ghidra'
    if any(part.startswith('.') for part in project.absolute().parts):
        raise ValueError('Use a data directory without hidden path elements for the native Ghidra project')
    project.mkdir(parents=True, exist_ok=True)
    name = 'doa2-native'
    if not (project / (name + '.gpr')).is_file():
        arguments = [str(executable), str(project), name, '-import', str(seed),
                     '-loader', 'BinaryLoader', '-loader-baseAddr', '0x8c010000',
                     '-processor', 'SuperH4:LE:32:default', '-noanalysis']
        with (cache / 'native_import.log').open('w', encoding='utf-8') as log:
            imported = subprocess.run(arguments, stdout=log, stderr=subprocess.STDOUT,
                                      env=_ghidra_env(ctx.config), timeout=1800, check=False)
        if imported.returncode:
            raise RuntimeError('Native Ghidra import failed; inspect native_import.log in the cache')
    ctx.progress(35, 'Executing original SH4 cloth generators in the verified read-only program')
    result = N.run_native(cache, executable, project, name, '1ST_READ.BIN', env=_ghidra_env(ctx.config))
    if result.get('errors'):
        raise ValueError('Native cloth execution failed verification: ' + str(result['errors'][:3]))
    return result


def _validate(out: Doa2Out, artifacts: dict) -> list[str]:
    report = artifacts.get("doa2-report.json")
    if not report or json.loads(report) != out.result:
        return ["DOA2 report does not match the operation result"]
    return []


def compact_report(value, key=''):
    """Keep named costumes/results while bounding per-vertex and motion payloads."""
    if isinstance(value, dict):
        if key == 'native_report':
            fields = ('format', 'stem', 'triangles', 'vertices', 'joints',
                      'complete_source_components', 'projected_uv_unreplayed', 'gameplay_verified')
            return {k: compact_report(value[k], k) for k in fields if k in value} | {
                'report_file': 'core-report.json', 'details_artifact': 'doa2-details.json',
                'limits_in': 'source_export_limits'}
        return {k: compact_report(v, k) for k, v in value.items()}
    if isinstance(value, list):
        if key in ('provenance', 'clips', 'tracks', 'records', 'vertices', 'aliases',
                   'cells', 'uv_sequence_proofs', 'files', 'textures', 'parts') and len(value) > 16:
            return {'count': len(value), 'details_artifact': 'doa2-details.json',
                    'preview': [compact_report(v) for v in value[:2]]}
        return [compact_report(v) for v in value]
    return value


@tool("doa2_assets", "1.2", Doa2In, Doa2Out, capabilities=["analysis", "asset", "modding"],
      permissions=[P.READ, P.STAGE, P.EXECUTE], timeout_s=3600,
      side_effects=["writes decomposed assets and modified disc copies into the cache/analysis folders"],
      artifacts=["doa2-report.json", "doa2-details.json"], validation="native archive validation and operation report match",
      validate=_validate)
def doa2_assets(inp: Doa2In, ctx):
    """Inspect/decompose DOA2 native fighter geometry, textures and motion files, or build a copied ROM
    with a donor character retargeted to the native executable rest rig. Does not substitute an overlay or certify gameplay.
    Inspect/decompose supports fighter=all costume=all. Native_cache prepare/run/verify reproduces original
    SH4 cloth generation with Ghidra. Complete decomposition requires its verified cache. Build preserves
    mapped weights in native SUP, retains original motion/actor initialization and disables stale APV/ACS.
    Environments inspects/decomposes environment=all or an explicit STAGE## archive using
    environment_action=inspect/decompose. Exports editable, unassembled parts plus native CHR/BIN
    and full PVR mip chains. Stage placement, animation, collision and native reimport remain unverified.
    """
    from . import characters as C, doa2_chars, doa2_geometry as G, doa2_textures as T, doa2_swap as S
    from .gdrom import GDRom
    from .filemods import mod_dir
    if inp.game_id not in S.GAME_IDS:
        raise ValueError("This native format implementation only supports DOA2 Limited Edition Japan")
    game = C._api(ctx, "GET", f"/api/catalog/{inp.game_id}")
    gdi = C._dc_gdi(ctx, game)
    disc = GDRom(gdi)
    executable = disc.read("1ST_READ.BIN")
    executable_sha = hashlib.sha256(executable).hexdigest()
    if executable_sha != S.EXECUTABLE_SHA256:
        raise ValueError("Unsupported executable identity")
    selected = [] if inp.op in ("motions", "native_cache", "environments") else selected_costumes(disc.files, inp.fighter, inp.costume, executable)
    analysis = Path(ctx.config.data_dir) / "analysis" / "doa2" / inp.game_id
    cache = cache_directory(analysis, inp.native_cache)
    if inp.op == 'native_cache':
        result = {'op': inp.op, 'action': inp.cache_action, 'game_id': inp.game_id,
                  'cache': str(cache), 'verification': run_cache(ctx, disc, analysis, cache, inp.cache_action)}
    elif inp.op == 'environments':
        from . import doa2_environments as E
        import uuid
        entries = []
        stages = E.select(disc.files, inp.environment)
        for index, row in enumerate(stages):
            ctx.progress(5 + 90 * index / len(stages), f"Environment source: {row['name']}")
            try:
                if not row['available']:
                    raise ValueError('Corresponding native BIN is absent')
                chr_data, bin_data = disc.read(row['geometry']), disc.read(row['textures'])
                if inp.environment_action == 'decompose':
                    output = analysis / 'environments' / (row['name'] + '-' + uuid.uuid4().hex[:12])
                    entry = E.export_assets(chr_data, bin_data, output, row['name'],
                                            source={'game_id': inp.game_id, 'executable_sha256': executable_sha})
                else:
                    entry = E.inspect_archive(chr_data, bin_data, row['name'])
                entries.append(entry)
            except ValueError as error:
                entries.append({'name': row['name'], 'status': 'unsupported_source', 'reason': str(error)})
        result = {'op': inp.op, 'action': inp.environment_action, 'game_id': inp.game_id,
                  'executable_sha256': executable_sha, 'environments': entries,
                  'inventory_archives': len(E.inventory(disc.files)),
                  'available_archives': sum(row['available'] for row in E.inventory(disc.files)),
                  'selected_archives': len(stages),
                  'verified_archives': sum(e['status'] == 'source_records_verified' for e in entries),
                  'unsupported_archives': sum(e['status'] == 'unsupported_source' for e in entries),
                  'gameplay_verified': False, 'native_reimport_supported': False,
                  'assembly': 'unassembled native stage parts; arena selection and scene placement not inferred'}
    elif inp.op == "motions":
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
                'native_compact_polynomials_decoded': any((m.get('motion') or {}).get('native_compact_polynomials_decoded') for m in motions),
                'runtime_interpolation_verified': False, 'native_animation_policy':'preserve original MOT bytes'}
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
        if inp.op == 'decompose' and inp.complete_source and not (cache / 'verification.json').is_file():
            raise ValueError('Complete source requires native_cache prepare/run/verify first; complete_source=false explicitly exports the partial core')
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
                exported = doa2_chars.export(str(gdi), str(output), family, costume,
                                            native_cache=cache if inp.complete_source else None)
                entry.update(path=str(output), files=exported["files"], confidence=exported["assembled_confidence"],
                             assembly=exported['assembly'], native_report=exported.get('core_report'))
            entries.append(entry)
        from .doa2_native_export.source_binding import costumes
        inventory = costumes(disc, executable, include_unavailable=True)
        result = {"op": inp.op, "game_id": inp.game_id, "executable_sha256": executable_sha,
                  "costumes": entries, "gameplay_verified": False,
                  'unavailable_native_sources': [r for r in inventory if not r['available']],
                  "animation_rig": "native rest vectors and SUP axis graph; MOT channels retain their native IK semantics"}
        if inp.op == 'decompose':
            limits = {(json.dumps(e['native_report']['limits'], sort_keys=True))
                      for e in entries if (e.get('native_report') or {}).get('limits')}
            result['source_export_limits'] = [json.loads(row) for row in sorted(limits)]
    result = json.loads(json.dumps(result, default=str))
    ctx.artifact('doa2-details.json', json.dumps(result, indent=2).encode(), 'application/json', game_id=inp.game_id)
    if not inp.include_details:
        result = compact_report(result)
    ctx.artifact("doa2-report.json", json.dumps(result, indent=2).encode(), "application/json", game_id=inp.game_id)
    ctx.progress(100, f"DOA2 {inp.op} completed; gameplay acceptance is separate")
    return {"result": result}
