"""DOA2 native geometry reintegration, requiring a proved runtime rig profile.

CHR contains local model parts, not joint matrices. A profile must identify the
native part driven by each body joint and its bind transform before a donor can
be retargeted. Archive conversion alone is not a gameplay acceptance result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import doa2_chars, doa2_geometry as G

GAME_IDS = doa2_chars.GAME_IDS
EXECUTABLE_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"
REQUIRED_ROLES = {"hip", "chest", "head", "l_upper", "l_fore", "l_hand",
                  "r_upper", "r_fore", "r_hand", "l_thigh", "l_shin", "l_foot",
                  "r_thigh", "r_shin", "r_foot"}


def writer_fingerprint() -> str:
    """Invalidate copied-ROM builds when their conversion implementation changes."""
    digest = hashlib.sha256()
    names = ('doa2_swap', 'doa2_geometry', 'doa2_materials', 'doa2_textures',
             'doa2_pvr', 'doa2_atlas', 'doa2_rig', 'doa2_axes', 'doa2_rest',
             'doa2_bindings', 'doa2_morphs', 'doa2_acs', 'doa2_seams',
             'doa2_weighted_retarget', 'retarget_profile', 'doa2_sup_payload', 'doa2_sup_plan',
             'doa2_sup_writer', 'doa2_weighted_encode', 'doa2_strip_encode', 'gdrom', 'gdrom_slack', 'sm64_swap', 'melee_models')
    for name in names:
        digest.update(name.encode('ascii'))
        digest.update(Path(__file__).with_name(name + '.py').read_bytes())
    return digest.hexdigest()


class RigUnavailable(ValueError):
    """The requested native rig has not been established by runtime evidence."""


def fighter_slot(slot: str) -> tuple[str, str | None]:
    """Resolve a fighter name/family and optional costume, e.g. 'Kasumi:00'."""
    parts = slot.removeprefix("fighter:").split(":")
    if len(parts) > 2:
        raise ValueError("Use fighter name or fighter name:costume")
    query = parts[0].strip().casefold()
    if query in {"", "player", "default"}:
        raise ValueError("DOA2 requires an explicit fighter and optional costume; the marked point and current player "
                         "have not been resolved. Use slot='ein:01' for known Ein C1, or another verified fighter name.")
    variants = [(key, key, []) for key in ('LOR', 'MAM', 'PDG', 'WBA')]
    for key, name, aliases in [*doa2_chars.FIGHTERS, *variants]:
        if query in {s.casefold() for s in [key, name, *aliases]}:
            costume = parts[1] if len(parts) == 2 else None
            if costume is not None and (not costume.isdigit() or len(costume) > 2):
                raise ValueError("Costume must be one or two decimal digits")
            return key, costume.zfill(2) if costume is not None else None
    raise ValueError(f"Unknown DOA2 fighter {parts[0]!r}")


def validate_profile(profile: dict, archive: dict) -> dict:
    """Validate a rig without silently synthesizing a missing joint hierarchy."""
    if profile.get("format") != "doa2-native-rig-v1":
        raise RigUnavailable("A verified doa2-native-rig-v1 profile is required")
    if profile.get("executable_sha256") != EXECUTABLE_SHA256:
        raise RigUnavailable("Rig profile belongs to a different executable")
    evidence = profile.get("evidence") or {}
    if not evidence.get("bind_transforms") or not evidence.get("part_mapping"):
        raise RigUnavailable("Native bind-transform and part-mapping evidence is missing")
    world = np.asarray(profile.get("world"), dtype=float)
    if world.ndim != 3 or world.shape[1:] != (4, 4) or not len(world) or not np.isfinite(world).all():
        raise ValueError("Rig world transforms must be finite 4x4 matrices")
    if not np.allclose(world[:, 3, :], [0, 0, 0, 1], atol=1e-7):
        raise ValueError("Rig matrices must use affine column-vector convention")
    if np.any(np.abs(np.linalg.det(world[:, :3, :3])) < 1e-8):
        raise ValueError("Rig contains a singular transform")
    parent = profile.get("parent")
    if not isinstance(parent, list) or len(parent) != len(world):
        raise ValueError("Rig hierarchy length does not match joint transforms")
    for joint, p in enumerate(parent):
        if not isinstance(p, int) or not -1 <= p < len(world) or p == joint:
            raise ValueError("Invalid joint parent")
    for joint, p in enumerate(parent):
        seen = {joint}
        while p != -1:
            if p in seen:
                raise ValueError("Rig hierarchy contains a cycle")
            seen.add(p)
            p = parent[p]
    roles = profile.get("roles") or {}
    if REQUIRED_ROLES - roles.keys():
        raise RigUnavailable(f"Missing target roles: {sorted(REQUIRED_ROLES - roles.keys())}")
    if any(not isinstance(j, int) or not 0 <= j < len(world) for j in roles.values()):
        raise ValueError("Target role references an invalid joint")
    emit = {int(j): int(m) for j, m in (profile.get("emit_models") or {}).items()}
    body = profile.get("body_models") or []
    if not body or len(set(body)) != len(body) or any(not isinstance(m, int) or not 0 <= m < len(archive["models"]) for m in body):
        raise ValueError("Body model IDs must be unique native archive model IDs")
    if any(not 0 <= j < len(world) or m not in body for j, m in emit.items()):
        raise ValueError("Emitted geometry must use a body model and valid joint")
    if set(roles.values()) - emit.keys() or len(set(emit.values())) != len(emit):
        raise ValueError("Each target joint needs a distinct native emission model")
    model_world = {int(m): np.asarray(w, dtype=float) for m, w in (profile.get("model_world") or {}).items()}
    for j, m in emit.items():
        # A model may have an attachment offset relative to its body joint.
        w = model_world.setdefault(m, world[j])
        if w.shape != (4, 4) or not np.isfinite(w).all() or not np.allclose(w[3], [0, 0, 0, 1]) or abs(np.linalg.det(w[:3, :3])) < 1e-8:
            raise ValueError("Invalid emitted model bind transform")
    ground, head_h = float(profile["ground"]), float(profile["head_h"])
    if not np.isfinite([ground, head_h]).all() or head_h <= 0:
        raise ValueError("Native ground and head height must be finite and positive")
    return {"T": world[:, :3, 3], "W": world, "parent": parent, "joints": len(world),
            "jmap": roles, "emit_models": emit, "body_models": body, "model_world": model_world,
            "ground": ground, "head_h": head_h}


def encode_parts(chr_data: bytes, bin_data: bytes, prims: list[dict], profile: dict,
                 *, size_budget: int, allow_downscale: bool = False,
                 synthesize_headers: bool = False, retype_argb4444: bool = False) -> dict:
    """Convert already-retargeted world geometry to native joint-local parts.

    Triangles spanning joint boundaries use their majority joint, consistently
    converting all three vertices into that model's local frame. Native motion,
    unrelated volume parts, and their texture allocations remain separate.
    """
    from . import doa2_materials as M, doa2_pvr
    archive = G.decode_chr(chr_data)
    target = validate_profile(profile, archive)
    body = set(target["body_models"])
    retained_slots = {mesh["texture_id"] for model in archive["models"] if model["id"] not in body
                      for mesh in model["meshes"] if mesh["texture_id"] >= 0}
    materials = M.allocate(archive, bin_data, prims, allow_downscale=allow_downscale,
                           excluded_slots=retained_slots, synthesize_headers=synthesize_headers,
                           retype_argb4444=retype_argb4444)
    meshes_by_model = {m: [] for m in body}
    source_triangles = 0
    for primitive, material in zip(prims, materials["primitives"]):
        p, n, uv = (np.asarray(primitive[k], dtype=float) for k in ("pos", "nrm", "uv"))
        triangles = np.asarray(primitive["tris"], dtype=int)
        joints = np.asarray(primitive["J"], dtype=int)[:, 0]
        if p.ndim != 2 or p.shape[1] != 3 or n.shape != p.shape or uv.shape != (len(p), 2) or len(joints) != len(p):
            raise ValueError("Retargeted vertex attribute lengths do not match")
        if not all(np.isfinite(x).all() for x in (p, n, uv)) or triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("Retargeted geometry must contain finite triangle attributes")
        if np.any(triangles < 0) or np.any(triangles >= len(p)):
            raise ValueError("Triangle references a missing donor vertex")
        if any(int(j) not in target["emit_models"] for j in np.unique(joints)):
            raise ValueError("Retargeted vertex uses a joint without a native model")
        owners = joints[triangles]
        # Stable first-vertex tie-break when all three joints differ.
        winners = np.where(owners[:, 1] == owners[:, 2], owners[:, 1], owners[:, 0])
        source_triangles += len(triangles)
        for joint in np.unique(winners):
            m = target["emit_models"][int(joint)]
            inverse = np.linalg.inv(target["model_world"][m])
            local_p = p @ inverse[:3, :3].T + inverse[:3, 3]
            # Inverse transpose for normals under a world-to-model transform.
            local_n = n @ np.linalg.inv(inverse[:3, :3])
            local_n /= np.maximum(np.linalg.norm(local_n, axis=1, keepdims=True), 1e-9)
            used = triangles[winners == joint]
            indices, remap = np.unique(used, return_inverse=True)
            attrs = np.concatenate((local_p[indices], local_n[indices], uv[indices]), axis=1)
            meshes_by_model[m].append({"vertices": [tuple(v) for v in attrs],
                                      "triangles": [tuple(map(int, t)) for t in remap.reshape(-1, 3)],
                                      "header": doa2_pvr.sampler(material["header"], primitive.get("wrap",(10497,10497))), "texture_id": material["texture_id"]})
    placeholder_header = next((mesh['header'] for meshes in meshes_by_model.values()
                               for mesh in meshes), None)
    if placeholder_header is None:
        raise ValueError('Donor has no triangles for native reintegration')
    replacements = {m: G.encode_model(archive["models"][m], meshes) if meshes else
                    G.invisible_model(archive["models"][m], placeholder_header)
                    for m, meshes in meshes_by_model.items()}
    rebuilt = G.replace_models(chr_data, replacements, size_budget=size_budget)
    if materials["report"]["descriptor_retypes"]:
        updated = bytearray(rebuilt)
        offset = G.decode_chr(rebuilt)["texture_table_offset"]
        updated[offset:offset + len(materials["descriptor_bytes"])] = materials["descriptor_bytes"]
        rebuilt = bytes(updated)
    decoded = G.decode_chr(rebuilt)
    written = sum(len(mesh["triangles"]) for m in decoded["models"] if m["id"] in body for mesh in m["meshes"])
    if written != source_triangles:
        raise AssertionError("Native conversion lost donor triangles")
    for model in archive["models"]:
        if model["id"] in body:
            continue
        new = decoded["models"][model["id"]]
        if chr_data[model["offset"]:model["end_offset"]] != rebuilt[new["offset"]:new["end_offset"]]:
            raise AssertionError("Unrelated native model changed")
    return {"chr_data": rebuilt, "bin_data": materials["bin_data"],
            "report": {"triangles": written, "chr_bytes": len(rebuilt), "chr_budget": size_budget,
                       "bin_bytes": len(materials["bin_data"]), "body_models": sorted(body),
                       "materials": materials["report"], "gameplay_verified": False,
                       "profile_sha256": hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()}}


def encode_budgeted(chr_data, bin_data, prims, profile, target, size_budget, *,
                    coefficients=None, sup_budget=None, allow_downscale=False,
                    progress=lambda p,m:None):
    """Keep full geometry when it fits; use audited Blender LOD attempts otherwise."""
    import tempfile
    from . import sm64_swap as S
    from . import doa2_atlas as A, doa2_materials as M
    from .re4gc_enemies import decimate
    source_triangles=sum(len(p['tris']) for p in prims)
    original_prims=prims
    attempts=[]
    atlas_report=None
    def encode(geometry):
        if coefficients is not None:
            from .doa2_weighted_encode import encode_weighted
            return encode_weighted(chr_data, bin_data, geometry, profile, coefficients,
                                   chr_budget=size_budget, sup_budget=sup_budget,
                                   allow_downscale=allow_downscale,
                                   synthesize_headers=bool(profile.get('synthesize_material_headers')),
                                   retype_argb4444=bool(profile.get('retype_argb4444')))
        return encode_parts(chr_data,bin_data,geometry,profile,size_budget=size_budget,
                            allow_downscale=allow_downscale,
                            synthesize_headers=bool(profile.get('synthesize_material_headers')),
                            retype_argb4444=bool(profile.get('retype_argb4444')))
    from . import fit_events as FE
    def finish(result, reduced, geometry=None):
        result['report'].update(source_triangles=source_triangles, lod_attempts=attempts,
                                geometry_reduced=reduced, atlas=atlas_report)
        FE.stage('decimate', 'done' if reduced else 'skipped',
                 {'from': source_triangles, 'triangles': result['report'].get('triangles'), 'attempts': len(attempts)})
        FE.comparison(original_prims, geometry if geometry is not None else prims,
                      reason='Original mesh exceeds native CHR allocation' if reduced else 'Original geometry fits unchanged',
                      limits={'chr_budget_bytes':size_budget,'sup_budget_bytes':sup_budget,
                              'original_failure':attempts[0]['result'] if attempts else None})
        return result
    try:
        result=encode(prims)
        return finish(result, False)
    except M.MaterialCapacityError as error:
        archive=G.decode_chr(chr_data)
        body=set(target['body_models'])
        retained={mesh['texture_id'] for model in archive['models'] if model['id'] not in body
                  for mesh in model['meshes'] if mesh['texture_id'] >= 0}
        capacities=A.native_capacities(archive, bin_data, excluded_slots=retained,
                                      synthesize_headers=bool(profile.get('synthesize_material_headers')),
                                      retype_argb4444=bool(profile.get('retype_argb4444')))
        progress(32, 'Packing donor materials into native texture allocations')
        atlas=A.atlas_primitives(prims, capacities, allow_downscale=allow_downscale)
        prims=atlas['primitives']
        atlas_report={'initial_capacity_failure':str(error), **atlas['report']}
        # The atlas already reports any pixel loss; do not resize it again in allocation.
        allow_downscale=False
        try:
            return finish(encode(prims), False)
        except ValueError as error:
            if not str(error).startswith('CHR budget exceeded:'): raise
            attempts.append({'triangles':source_triangles,'result':str(error)})
    except ValueError as error:
        if not str(error).startswith('CHR budget exceeded:'): raise
        attempts.append({'triangles':source_triangles,'result':str(error)})
    with tempfile.TemporaryDirectory(prefix='gbox-doa2-lod-') as temporary:
        work=Path(temporary)
        rigged=S.write_rigged(prims,target,work/'retargeted.gltf','native-donor')
        failed_budget=source_triangles
        best=None
        best_geometry=None
        best_budget=None
        def reduced_geometry(budget):
            model=decimate(rigged,work/f'lod{budget}.glb',float(budget))
            if coefficients is not None:
                from .doa2_weighted_retarget import read_rigged
                geometry=read_rigged(model, target['jmap'])
            else:
                geometry=S.read_rigged(model)
                for primitive in geometry: primitive['J']=np.asarray(primitive['jid'])[:,None]
            count=sum(len(p['tris']) for p in geometry)
            FE.stage('decimate', 'running', {'from': source_triangles, 'to': budget, 'triangles': count}, prims=geometry)
            return geometry, count
        for budget in sorted({max(128,int(source_triangles*.8**k)) for k in range(1,11)},reverse=True):
            progress(35,f'Native allocation: reducing donor to {budget} triangles')
            geometry,count=reduced_geometry(budget)
            try:
                result=encode(geometry)
            except ValueError as error:
                if not str(error).startswith('CHR budget exceeded:'): raise
                attempts.append({'budget':budget,'triangles':count,'result':str(error)})
                failed_budget=budget
                continue
            attempts.append({'budget':budget,'triangles':count,'result':'allocation_verified'})
            best,best_budget=result,budget
            best_geometry=geometry
            break
        if best is not None:
            # Measure intermediate allocations; keep the most detailed actual fit.
            low,high=best_budget,failed_budget
            for _ in range(5):
                if high-low <= 8: break
                budget=(low+high)//2
                progress(38,f'Refining native geometry allocation at {budget} triangles')
                geometry,count=reduced_geometry(budget)
                try:
                    result=encode(geometry)
                except ValueError as error:
                    if not str(error).startswith('CHR budget exceeded:'): raise
                    attempts.append({'budget':budget,'triangles':count,'result':str(error)})
                    high=budget
                    continue
                attempts.append({'budget':budget,'triangles':count,'result':'allocation_verified'})
                low=budget
                if result['report']['triangles'] > best['report']['triangles']:
                    best=result
                    best_geometry=geometry
            best['report']['lod_skin_policy']=('Blender retains mapped skin weights; native SUP quantization is reported'
                if coefficients is not None else 'legacy rigid-part conversion; explicit native SUP coefficients were not supplied')
            return finish(best, True, best_geometry)
    raise ValueError('Native allocation cannot fit donor geometry after bounded LOD attempts: '+str(attempts))


def limit_influences(prims: list[dict], max_influences: int = 2) -> tuple[list[dict], dict]:
    """Keep each vertex's heaviest joints only (native SUP stores at most two) and renormalise their weights.

    The retarget keeps every mapped weight on purpose; this is the explicit reduction the SUP planner asks for.
    Duplicate joints in a row are merged first, so a vertex that only looks over-influenced is left exact. Returns
    (primitives, report) with how many vertices were reduced and the largest weight that was dropped."""
    import numpy as np
    out, reduced, dropped = [], 0, 0.0
    for primitive in prims:
        joints, weights = np.asarray(primitive['J'], dtype=int), np.asarray(primitive['W'], dtype=float)
        if joints.ndim != 2 or joints.shape != weights.shape:
            raise ValueError('skin arrays must be (vertices, influences) and share a shape')
        new_j = np.repeat(joints[:, :1], max_influences, axis=1)
        new_w = np.zeros((len(joints), max_influences), float)
        for vertex in range(len(joints)):
            merged: dict[int, float] = {}
            for j, w in zip(joints[vertex], weights[vertex]):
                if w > 0:
                    merged[int(j)] = merged.get(int(j), 0.0) + float(w)
            ranked = sorted(merged.items(), key=lambda item: (-item[1], item[0]))
            if len(ranked) > max_influences:
                reduced += 1
                dropped = max(dropped, ranked[max_influences][1] / max(sum(w for _, w in ranked), 1e-12))
                ranked = ranked[:max_influences]
            total = sum(w for _, w in ranked) or 1.0
            for column, (j, w) in enumerate(ranked):
                new_j[vertex, column], new_w[vertex, column] = j, w / total
            if not ranked:
                new_w[vertex, 0] = 1.0
        out.append({**primitive, 'J': new_j, 'W': new_w, 'owner': new_j[:, 0]})
    return out, {'max_influences': max_influences, 'vertices_reduced': reduced, 'largest_weight_dropped': round(dropped, 4)}


def weights_stage(prims: list[dict], fit: dict, jmap: dict) -> None:
    """The Fitting pop-up's weights stage: vertices per DOA2 body part (strongest influence), and the two-influence
    reduction native SUP needs (skipped when the donor already has at most two)."""
    from . import fit_events as FE
    if not FE.active():
        return
    names = {}
    for role, j in jmap.items():
        names.setdefault(int(j), f"{role} (bone {j})")
    counts = FE.per_limb(prims, names)
    data = {"mode": "weighted (native SUP: two influences)", "bones": len(counts), "vertices": int(sum(counts.values())),
            "per_limb": counts}
    if "influence_reduction" in fit:
        FE.stage("weights", data=data | {"max_influences_before": fit["max_influences"], **fit["influence_reduction"]})
    else:
        FE.stage("weights", data=data | {"max_influences": fit.get("max_influences"), "native_limit": 2})


def prepare(gdi: str | Path, character_dir: str | Path, out_dir: str | Path,
          fighter: str, costume: str, profile: dict, *, allow_downscale: bool = False,
          progress=lambda p, m: None) -> dict:
    """Prepare one costume without mutating or copying its source disc."""
    from .gdrom import GDRom, patch_gdi
    from .doa2_weighted_retarget import load_rig, retarget
    from . import doa2_morphs, doa2_bindings
    family, selected = fighter_slot(fighter)
    costume = selected or str(costume).zfill(2)
    if not costume.isdigit() or len(costume) != 2:
        raise ValueError("Invalid costume")
    if profile.get("fighter") != family or profile.get("costume") != costume:
        raise RigUnavailable("Rig profile does not match the requested fighter costume")
    disc = GDRom(gdi)
    executable = disc.read("1ST_READ.BIN")
    if hashlib.sha256(executable).hexdigest() != EXECUTABLE_SHA256:
        raise ValueError("Unsupported DOA2 executable; refusing fixed-layout reintegration")
    stem = f"DOA2/{family}{costume}"
    chr_data, bin_data = disc.read(stem + ".CHR"), disc.read(stem + ".BIN")
    target = validate_profile(profile, G.decode_chr(chr_data))
    binding = doa2_bindings.render_part_mapping(executable, int(profile["render_slot"]), int(profile["render_costume"]))
    if any(target["emit_models"].get(j) != m for j, m in enumerate(binding["emit_models"])):
        raise RigUnavailable("Rig model mapping does not match the executable's native draw script")
    directory = Path(character_dir)
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    from . import fit_events as FE, retarget_profile as RP
    meta = RP.apply_to_meta(meta, GAME_IDS, f"fighter:{family}")     # the operator's Retarget editor profile
    FE.model(f"fighter:{family}", f"{meta.get('name', directory.name)} -> {family} (costume {costume})",
             meta.get("slug") or directory.name)
    roles = (meta.get("rig") or {}).get("roles") or {}
    if not {"hip", "head"} <= roles.keys():
        raise ValueError("Donor needs hip and head body roles for retargeting")
    model = (directory / meta["model"]).resolve()
    if not model.is_relative_to(directory.resolve()):
        raise ValueError("Donor model must remain inside its character directory")
    progress(10, "Retargeting donor onto verified DOA2 body transforms")
    rig = load_rig(model, roles, [p["node"] for p in meta.get("props") or []])
    prims, fit = retarget(rig, target, (meta.get("rig") or {}).get("scale"), target["jmap"])
    if fit.get("max_influences", 0) > 2:                       # native SUP holds two influences per vertex
        prims, fit["influence_reduction"] = limit_influences(prims, 2)
        progress(20, f"Reduced {fit['influence_reduction']['vertices_reduced']} vertices to two bone influences")
    weights_stage(prims, fit, target["jmap"])
    lba, original_bytes = disc.files[stem + ".CHR"]
    next_lba = min((l for l, _ in disc.files.values() if l > lba), default=lba+(original_bytes+2047)//2048)
    sup_lba, sup_bytes = disc.files[stem + '.SUP']
    sup_next = min((l for l, _ in disc.files.values() if l > sup_lba),
                   default=sup_lba+(sup_bytes+2047)//2048)
    from .doa2_seams import native_coefficients
    progress(30, "Encoding native joint-local geometry and texture allocations")
    FE.stage("encode", "running", {"budget_bytes": (next_lba-lba)*2048})
    try:
        result = encode_budgeted(chr_data, bin_data, prims, profile, target, (next_lba-lba)*2048,
                                 coefficients=native_coefficients(executable),
                                 allow_downscale=allow_downscale, progress=progress)
    except Exception as e:
        FE.stage("encode", "failed", {"error": str(e)[:150]})
        raise
    FE.stage("encode", data={"chr_bytes": len(result["chr_data"]), "bin_bytes": len(result["bin_data"]),
                             "sup_bytes": len(result["sup_data"]), "budget_bytes": (next_lba-lba)*2048,
                             "reduced": bool((result.get("report") or {}).get("geometry_reduced"))})
    changes = {stem + ".CHR": result["chr_data"], stem + ".BIN": result["bin_data"],
               stem + '.SUP': result['sup_data']}
    supplements = []
    for suffix, disable in (("APV", doa2_morphs.disable_apv),):
        key = stem + "." + suffix
        if key not in disc.files:
            raise RigUnavailable(f"Missing native supplement: {key}")
        changes[key], report = disable(disc.read(key))
        supplements.append(report)
    from .doa2_acs import disable_acs
    accessory = doa2_bindings.accessory_filename(executable, int(profile["render_slot"]),
                                                int(profile["render_costume"]))
    key = 'DOA2/' + accessory['filename'].upper()
    if key not in disc.files:
        raise RigUnavailable(f'Missing native accessory resource: {key}')
    changes[key], cloth = disable_acs(disc.read(key))
    supplements.append(cloth | {'native_binding': accessory})
    from .gdrom_slack import plan_modified_slack
    start, sector_bytes, track = max(disc.tracks)
    allocation = plan_modified_slack(disc.files, changes, track_start=start,
                                    track_end=start + track.stat().st_size // sector_bytes,
                                    reserved_ranges=disc.metadata_ranges)
    report = result['report'] | {'fit': fit, 'fighter': family, 'costume': costume,
                               'retarget_profile_digest': meta.get('retarget_profile_digest', ''),
                               'native_sup_original_budget': (sup_next-sup_lba)*2048,
                               'disc_allocation': allocation,
                               'supplements': supplements,
                               'source_model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
                               'files': {key: {'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
                                         for key, data in changes.items()}}
    return changes, report


def write_mod(gdi, out_dir, name, slug, changes, reports, progress):
    from .gdrom import GDRom, patch_gdi
    image = patch_gdi(gdi, out_dir, name, changes, progress, reuse_modified_slack=True)
    rebuilt = GDRom(image)
    for key, data in changes.items():
        if rebuilt.read(key) != data:
            raise AssertionError(f'Native GDI reintegration mismatch: {key}')
    report = reports[0] if len(reports)==1 else {'costumes':reports, 'gameplay_verified':False}
    Path(out_dir, 'build-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    Path(out_dir, '.gbox-mod.json').write_text(json.dumps({'name':name, 'game_id':next(iter(GAME_IDS)),
                  'image':image.name, 'character':slug, 'files':list(changes), 'report':report,
                  'writer_sha256':writer_fingerprint(), 'profile_digest': profiles_digest(reports),
                  'gameplay_verified':False}),encoding='utf-8')
    from . import fit_events as FE
    FE.stage('write', data={'image': image.name, 'files': len(changes)})
    return {'mod':name, 'image':str(image), 'report':report, 'status':'built_unverified'}


def profiles_digest(reports=(), metas=()) -> str:
    """The retarget profiles a build used (from its costume reports) or will use ([(family, meta)]): a changed
    profile in the Retarget editor rebuilds the mod."""
    from . import retarget_profile as RP
    found = {r.get('retarget_profile_digest', '') for r in reports if isinstance(r, dict)}
    found |= {RP.digest(RP.resolve(meta, GAME_IDS, f'fighter:{family}')) for family, meta in metas}
    return ','.join(sorted(found - {''}))


def build(gdi, character_dir, out_dir, fighter, costume, profile, *, allow_downscale=False, progress=lambda p,m:None):
    changes, report = prepare(gdi, character_dir, out_dir, fighter, costume, profile,
                              allow_downscale=allow_downscale, progress=progress)
    meta=json.loads(Path(character_dir,'meta.json').read_text(encoding='utf-8'))
    name=f"doa2_{report['fighter'].lower()}{report['costume']}_{meta['slug']}"
    return write_mod(gdi,out_dir,name,meta['slug'],changes,[report],progress)


def merge_executable_patches(original, patches):
    """Merge disjoint costume script edits, rejecting conflicting byte changes."""
    result=bytearray(original); changed={}
    for patch in patches:
        if len(patch)!=len(original):
            raise ValueError('Native executable patch resized the source')
        for index,(a,b) in enumerate(zip(original,patch)):
            if a==b: continue
            if index in changed and changed[index]!=b:
                raise ValueError('Conflicting native costume script edits')
            changed[index]=b;result[index]=b
    return bytes(result)


def fighter_edits(disc, audit, gdi, character_dir, out_dir, family, costume='all', *, allow_downscale=False,
                  progress=lambda p, m: None):
    """Every costume of one fighter replaced by one donor: (file changes, reports, executable patches)."""
    from . import doa2_rig, doa2_lab
    selected = doa2_lab.selected_costumes(disc.files, family, costume)
    changes, reports, patches = {}, [], []
    for index, (key, number) in enumerate(selected):
        profile = doa2_rig.for_archive(disc, f'DOA2/{key}{number}.CHR', audit)

        def update(p, m, index=index):
            progress(100 * (index + p / 100) / len(selected), m)
        edits, report = prepare(gdi, character_dir, out_dir, key, number, profile, allow_downscale=allow_downscale, progress=update)
        if '1ST_READ.BIN' in edits:
            patches.append(edits.pop('1ST_READ.BIN'))
        changes.update(edits)
        reports.append(report)
    return changes, reports, patches


def build_fighter(gdi, character_dir, out_dir, fighter, costume='all', *, allow_downscale=False, progress=lambda p,m:None):
    from .gdrom import GDRom
    from . import doa2_rig
    family, specified=fighter_slot(fighter)
    costume=specified or costume
    disc=GDRom(gdi); audit=doa2_rig.collect_axes(disc)
    changes, reports, patches = fighter_edits(disc, audit, gdi, character_dir, out_dir, family, costume,
                                              allow_downscale=allow_downscale, progress=lambda p, m: progress(0.6 * p, m))
    if patches: changes['1ST_READ.BIN']=merge_executable_patches(disc.read('1ST_READ.BIN'),patches)
    meta=json.loads(Path(character_dir,'meta.json').read_text(encoding='utf-8'))
    suffix='' if costume=='all' else str(costume).zfill(2)
    name=f"doa2_{family.lower()}{suffix}_{meta['slug']}"
    return write_mod(gdi,out_dir,name,meta['slug'],changes,reports,progress)


ROSTER = [key for key, _name, _aliases in doa2_chars.FIGHTERS]      # the 14 selectable fighters, boss variants excluded
# body size relative to the cast (the cast swap's by_role mapping): the Armstrongs' heavyweight and Tengu are large
FIGHTER_SIZE = {"BAS": 1.3, "TNG": 1.25, "BAY": 1.1, "ZAC": 1.05, "KAS": 0.9, "AYA": 0.88, "LEI": 0.9, "HIK": 0.92,
                "TIN": 0.95, "KTE": 1.0, "GEN": 0.9, "RYU": 1.0, "JAN": 1.0, "SAM": 1.0}


def cast_slots() -> list[dict]:
    """The cast menu / whole-cast swap: every selectable fighter (all costumes), the slots use_roster fills at once."""
    return [{"slot": f"fighter:{key}", "name": name, "kind": "fighter", "size": FIGHTER_SIZE.get(key, 1.0),
             "writer": "gbox.doa2_swap"} for key, name, _aliases in doa2_chars.FIGHTERS]


def plan_roster(pairs: list[tuple[str, str]], seed: str = "") -> list[tuple[str, str]]:
    """[(fighter or '', donor slug)] -> [(family, donor slug)] covering every selectable fighter once (#1385).

    Pairs that name a fighter are fixed. The donors of pairs without a fighter are dealt over the remaining fighters
    in a shuffled order that depends only on `seed` (and repeat when there are fewer donors than fighters), so the same
    request always builds the same disc and 'the whole cast as Sonic Adventure 2 characters' is one deterministic plan."""
    import random
    fixed, free = {}, []
    for fighter, donor in pairs:
        if not donor:
            raise ValueError("Every roster entry needs a character")
        if fighter:
            family, costume = fighter_slot(fighter)
            if costume is not None:
                raise ValueError("A roster replaces every costume of a fighter; drop the :costume suffix")
            if family not in ROSTER:
                raise ValueError(f"{family} is a story/boss variant, not a selectable fighter")
            if family in fixed and fixed[family] != donor:
                raise ValueError(f"{family} was assigned twice")
            fixed[family] = donor
        else:
            free.append(donor)
    remaining = [f for f in ROSTER if f not in fixed]
    if remaining and not free:
        raise ValueError(f"No donors left for {', '.join(remaining)}; add characters without a fighter to fill the rest")
    rng = random.Random(f"doa2-roster:{seed}:{','.join(free)}")
    order = list(remaining)
    rng.shuffle(order)
    pool = list(free)
    rng.shuffle(pool)
    plan = dict(fixed)
    for index, family in enumerate(order):
        plan[family] = pool[index % len(pool)]
    return [(family, plan[family]) for family in ROSTER]


def build_roster(gdi, donors: dict[str, Path], out_dir, plan: list[tuple[str, str]], *, allow_downscale=False,
                 progress=lambda p, m: None):
    """One disc with every selectable fighter replaced per `plan` ([(family, donor slug)]; donors: slug -> character dir)."""
    from .gdrom import GDRom
    from . import doa2_rig, fit_events as FE
    disc = GDRom(gdi)
    audit = doa2_rig.collect_axes(disc)
    names = {key: name for key, name, _aliases in doa2_chars.FIGHTERS}
    FE.plan([(f"fighter:{family}", slug, f"{slug} -> {names.get(family, family)}") for family, slug in plan])
    changes, reports, patches = {}, [], []
    for index, (family, slug) in enumerate(plan):
        if slug not in donors:
            raise ValueError(f"Unknown donor {slug!r}")

        def update(p, m, index=index):
            progress(60 * (index + p / 100) / len(plan), f"{family}: {m}")     # percent, like write_mod's
        edits, fighter_reports, fighter_patches = fighter_edits(disc, audit, gdi, donors[slug], out_dir, family, 'all',
                                                                allow_downscale=allow_downscale, progress=update)
        overlap = set(edits) & set(changes)
        if overlap:
            raise ValueError(f"{family} and an earlier fighter share disc files: {sorted(overlap)[:3]}")
        changes.update(edits)
        for report in fighter_reports:
            report['donor'] = slug
        reports.extend(fighter_reports)
        patches.extend(fighter_patches)
    if patches:
        changes['1ST_READ.BIN'] = merge_executable_patches(disc.read('1ST_READ.BIN'), patches)
    digest = hashlib.sha256(json.dumps(plan).encode()).hexdigest()[:8]
    name = f"doa2_roster_{digest}"
    result = write_mod(gdi, out_dir, name, ','.join(sorted({slug for _f, slug in plan})), changes, reports, progress)
    marker = Path(out_dir, '.gbox-mod.json')
    record = json.loads(marker.read_text(encoding='utf-8'))
    record['roster'] = [{'fighter': family, 'character': slug} for family, slug in plan]
    marker.write_text(json.dumps(record), encoding='utf-8')
    for family, slug in plan:                            # every fighter's files, written into the one disc
        FE.model(f"fighter:{family}")
        mine = {k: v for k, v in changes.items() if Path(k).name.upper().startswith(family)}
        FE.stage('write', data={'mod': name, 'image': Path(str(result.get('image') or '')).name, 'files': len(mine),
                                'bytes': sum(len(v) for v in mine.values()),
                                'costumes': sum(1 for r in reports if r.get('fighter') == family)})
    return result | {'roster': record['roster']}


def _donor_dirs(root: Path, slugs: set[str]) -> dict[str, Path]:
    """slug -> character directory for every donor the plan names; exact slugs only, missing ones listed."""
    found, missing = {}, []
    for slug in sorted(slugs):
        d = Path(root) / slug
        if (d / 'meta.json').is_file():
            found[slug] = d
        else:
            missing.append(slug)
    if missing:
        raise ValueError(f"Not in the collection (use exact slugs from characters op=list): {', '.join(missing)}")
    return found


def _roster_on_control_plane(ctx, game, inp, plan):
    """A Windows worker has no character collection (#1361: 'Not in the collection' for every SA2 donor), so the roster
    disc is built on the online Linux control plane that holds it; the launch, if asked, then happens here."""
    from . import characters as C
    me = getattr(ctx, 'worker', None)      # never this worker: a plane whose collection is missing would queue itself forever
    plane = next((w['id'] for w in C._api(ctx, 'GET', '/api/workers')
                  if w.get('os') == 'linux' and w.get('online') and 'characters' in (w.get('tools') or [])
                  and w.get('id') != me), None)
    if not plane:
        raise RuntimeError("The roster build needs the character collection on the Linux control plane, which is "
                           f"{'missing it here' if C.HOST_OS == 'linux' else 'offline'} ({C.library_root(ctx.config)})")
    job = C._job(ctx, 'characters', inp.model_dump() | {'session_id': '', 'game_id': game['game_id'], 'launch': False},
                 plane, 3600)
    if job.get('state') != 'succeeded':
        raise RuntimeError(f"roster build on the control plane {job.get('state')}: {job.get('error')}")
    result = dict(job['output']['result'])
    result['built_by'] = job.get('id')
    result['launch'] = C._launch(ctx, game['game_id'], result['mod'], C.HOST_OS) if inp.launch else None
    return result


def use_roster(ctx, meta, game, inp):
    """slot='roster': every selectable fighter replaced in one disc (#1385). `pairs` = [{character, slot?}]: entries
    with a fighter are fixed, the rest are dealt at random (deterministically) over the remaining fighters."""
    from . import characters as C, filemods
    pairs = [(str(p.get('slot') or ''), str(p.get('character') or '')) for p in (inp.pairs or [])]
    if not pairs:
        pairs = [('', meta['slug'])]
    plan = plan_roster(pairs, seed=inp.title or '')
    if not C.library_root(ctx.config).is_dir():
        return _roster_on_control_plane(ctx, game, inp, plan)
    donors = _donor_dirs(C.library_root(ctx.config), {slug for _f, slug in plan})
    digest = hashlib.sha256(json.dumps(plan).encode()).hexdigest()[:8]
    name = f"doa2_roster_{digest}"
    output = filemods.mod_dir(ctx.config, game['game_id'], name)
    marker = output / '.gbox-mod.json'
    try:
        cached = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cached = {}
    result = None
    want = profiles_digest(metas=[(family, json.loads((donors[slug] / 'meta.json').read_text(encoding='utf-8')))
                                  for family, slug in plan])
    if (inp.rebuild or cached.get('writer_sha256') != writer_fingerprint()
            or cached.get('profile_digest', '') != want):
        gdi = C._dc_gdi(ctx, game)
        result = build_roster(gdi, donors, output, plan, progress=ctx.progress)
        for family, slug in plan:
            C._api(ctx, 'POST', f"/api/characters/{slug}/targets",
                   json={'game_id': game['game_id'], 'slot': f'fighter:{family}:all', 'mod': name, 'nodes': [C.HOST_OS],
                         'notes': 'Roster build: every selectable fighter replaced in one disc. Gameplay verification required per fighter.'})
    launch = C._launch(ctx, game['game_id'], name, C.HOST_OS) if inp.launch else None
    return {'status': 'built_unverified', 'mod': name, 'build': result,
            'roster': [{'fighter': family, 'character': slug} for family, slug in plan], 'launch': launch,
            'gameplay_verified': False, 'replacement_kind': 'native_rom'}


def use(ctx, meta, game, inp):
    """Build one named fighter/costume into a copied native ROM, then optionally launch; slot='roster' builds the cast."""
    from . import characters as C, filemods
    if (inp.slot or '').strip().casefold() in ('roster', 'cast', 'everyone', 'all fighters'):
        return use_roster(ctx, meta, game, inp)
    family, costume = fighter_slot(inp.slot)
    costume = costume or "all"
    name = f"doa2_{family.lower()}{costume if costume != 'all' else ''}_{meta['slug']}"
    output = filemods.mod_dir(ctx.config, game['game_id'], name)
    result = None
    marker = output / '.gbox-mod.json'
    try:
        cached = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cached = {}
    if (inp.rebuild or cached.get('writer_sha256') != writer_fingerprint()
            or cached.get('profile_digest', '') != profiles_digest(metas=[(family, meta)])):
        gdi = C._dc_gdi(ctx, game)
        result = build_fighter(gdi, C.library_root(ctx.config) / meta['slug'], output, family, costume, progress=ctx.progress)
        C._api(ctx, 'POST', f"/api/characters/{meta['slug']}/targets",
               json={'game_id': game['game_id'], 'slot': f'fighter:{family}:{costume}',
                     'mod': name, 'nodes': [C.HOST_OS],
                     'notes': 'Native CHR/BIN retarget; original fighter motions retained. Gameplay verification required per donor.'})
    launch = C._launch(ctx, game['game_id'], name, C.HOST_OS) if inp.launch else None
    return {'status': 'built_unverified', 'mod': name, 'build': result,
            'fighter': family, 'costume': costume, 'launch': launch,
            'gameplay_verified': False, 'replacement_kind': 'native_rom'}
