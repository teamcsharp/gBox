"""Resident Evil 6 (Switch, No Mercy edition) native model reader for `characters op=collect`.

The Switch edition keeps each player body in an MTF `.arc` under `nativeNXx64/arc/NX`
(`uPl00LeonUsa.arc`, ...) - the same archives the `re6_switch_models` writer edits. This module is the
read side: it turns a native body archive into a rigged GLB for the character library, with the real
per-vertex skin weights (not the preview's bind-to-joint-0 shortcut) and the RE6 global bone-id role
table (`re6_switch_models.roles_for`), so a collected body is a swap-ready donor.

The RomFS comes from Eden's own Dump RomFS (`switch_mods.base_romfs`) or `GBOX_RE6_SWITCH_ROMFS`; the
reader never extracts a title itself. On a node without the dump, `roster()` falls back to the
canonical default-costume slots so the roster is still answerable; extraction raises with the exact
requirement.

`characters.DEDICATED` registers this as `re6_switch`, gated to game id 115f9cdbba115432 (the PS3 and
Xbox 360 editions have their own formats and are not matched).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from . import mt_arc, mt_model, re6_switch_models
from .re6_switch_models import ARCHIVE_DIR, TITLE_ID, SwitchModelError

READER_VERSION = 1


def title_test(title: str, platform: str) -> bool:
    return platform == "switch" and "resident evil 6" in (title or "")


def locate_romfs(config=None) -> Path | None:
    """An extracted RE6 Switch RomFS on this node, or None."""
    override = os.environ.get("GBOX_RE6_SWITCH_ROMFS")
    if override and (Path(override) / ARCHIVE_DIR).is_dir():
        return Path(override)
    from . import switch_mods
    try:
        base = switch_mods.base_romfs(config, TITLE_ID)
    except Exception:                                         # noqa: BLE001 - a stub config just means "no dump here"
        return None
    return base if base and (base / ARCHIVE_DIR).is_dir() else None


def _arc_slots(romfs: Path) -> dict[tuple[str, str], Path]:
    return re6_switch_models.body_arcs(romfs)


def roster() -> list[dict]:
    """Every native body arc when the RomFS dump is present; the canonical default costumes otherwise."""
    from . import skin_swap
    from .re6_models import CHARACTERS

    romfs = locate_romfs()
    out = []
    if romfs is not None:
        for (character, costume), _path in sorted(_arc_slots(romfs).items()):
            info = CHARACTERS.get(character) or {"name": character.title()}
            label = "default" if costume == "DebugId" else costume
            out.append({"key": f"{character}:{costume}", "slug": f"re6sw_{character}_{label.lower()}",
                        "name": f"{info['name']} - {label} (RE6 Switch)",
                        "aliases": [f"RE6 Switch {info['name']} {label}"], "kind": "character"})
        if out:
            return out
    for character, rel in skin_swap.CHARACTER_ARCS[TITLE_ID].items():
        info = CHARACTERS.get(character) or {"name": character.title()}
        out.append({"key": f"{character}:default", "slug": f"re6sw_{character}_default",
                    "name": f"{info['name']} - default (RE6 Switch)",
                    "aliases": [f"RE6 Switch {info['name']}"], "kind": "character"})
    return out


def _id_to_index(anim_map: list[int]) -> dict[int, int]:
    """Vertex bone ids reference the same anim ids as the bone headers: id -> skeleton index."""
    out: dict[int, int] = {}
    for index, anim in enumerate(anim_map):
        out.setdefault(int(anim), index)
    return out


def _bind(bones, weights, id_to_index: dict[int, int], fallback: int, count: int):
    """Per-vertex (joint indices, weights) as 4-wide arrays; unmapped ids fall back to `fallback`."""
    J = np.full((count, 4), fallback, np.int64)
    W = np.zeros((count, 4), np.float32)
    W[:, 0] = 1.0
    if not bones:
        return J, W
    for v, ids in enumerate(bones[:count]):
        if weights and v < len(weights):
            row = [(id_to_index.get(int(b), fallback), float(w)) for b, w in zip(ids, weights[v]) if w > 0]
        else:
            row = [(id_to_index.get(int(ids[0]), fallback), 1.0)] if ids else []
        for s, (joint, weight) in enumerate(row[:4]):
            J[v, s], W[v, s] = joint, weight
    total = W.sum(axis=1, keepdims=True)
    total[total == 0] = 1.0
    return J, W / total


def extract(arc_path: Path, glb_path: Path, name: str = "") -> dict:
    """Read a native body arc and write a rigged GLB (real skin weights + RE6 role table)."""
    from . import melee_models

    arc = mt_arc.parse(Path(arc_path).read_bytes())
    _mod_index, _mrl_index, mod_raw = re6_switch_models._find_model(arc)
    model = mt_model.parse_mod(mod_raw)
    roles = re6_switch_models.roles_for(model)                # {role: bone index} from the anim ids
    table = model.bone_table()
    world = model.bone_world()
    if not world:
        raise SwitchModelError("the body MOD has no readable bind skeleton")
    id_to_index = _id_to_index(table["anim_map"])
    joint_names, joints = [], []
    role_names = {"hip": "hip", "chest": "chest", "neck": "neck", "head": "head",
                  "r_hand": "right_hand", "l_hand": "left_hand",
                  "r_foot": "right_foot", "l_foot": "left_foot"}
    for index, x, y, z in world:
        parent = int(table["parents"][index])
        matrix = np.eye(4)
        matrix[:3, 3] = (x, y, z)
        joints.append({"parent": parent if 0 <= parent < len(world) else -1, "world": matrix})
        role = next((r for r, i in roles.items() if i == index and r in role_names), None)
        joint_names.append(role or f"j{index:03d}")
    # the index buffer addresses the whole model's vertex space (all_positions), so the body is one
    # primitive whose per-vertex weights come from each mesh's own slice of that space
    points = model.all_positions()
    tris = model.triangles()
    prims = []
    if points and tris:
        count = len(points)
        J = np.full((count, 4), roles["hip"], np.int64)
        W = np.zeros((count, 4), np.float32)
        W[:, 0] = 1.0
        normals_all: list[tuple[float, float, float]] = [(0.0, 1.0, 0.0)] * count
        uvs_all: list[tuple[float, float]] = [(0.0, 0.0)] * count
        base = 0
        for part, record in enumerate(model.meshes()):
            n = record["vertex_count"]
            slice_ = slice(base, base + n)
            data, _vb = model.mesh_bytes(part)
            weights = mt_model.decode_weights(data, record["vertex_format"], n, record["vertex_stride"])
            bones = model.bone_ids(part)
            if bones:
                Jm, Wm = _bind(bones, weights, id_to_index, roles["hip"], n)
                J[slice_], W[slice_] = Jm, Wm
            nrm = model.normals(part)
            if len(nrm) == n:
                normals_all[slice_] = nrm
            uv = model.uvs(part)
            if len(uv) == n:
                uvs_all[slice_] = uv
            base += n
        prims.append({"pos": np.asarray(points, np.float32), "nrm": np.asarray(normals_all, np.float32),
                      "uv": np.asarray(uvs_all, np.float32), "tris": np.asarray(tris, np.int64),
                      "J": J, "W": W, "color": (200, 200, 200, 255)})
    if not prims:
        raise SwitchModelError("the body MOD has no skinned geometry")
    Path(glb_path).parent.mkdir(parents=True, exist_ok=True)
    melee_models.write_gltf(Path(glb_path), joints, prims, 1.0, "re6_switch", joint_names)
    return {"gltf": str(glb_path), "vertices": sum(len(p["pos"]) for p in prims),
            "triangles": sum(len(p["tris"]) for p in prims), "joints": len(joints),
            "roles": {r: joint_names[i] for r, i in roles.items() if r in role_names}}


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run for one roster entry (characters.extract_dedicated)."""
    romfs = locate_romfs(getattr(ctx, "config", None))
    if romfs is None:
        raise SwitchModelError(
            "no extracted RE6 Switch RomFS on this node - dump it with Eden (Dump RomFS for "
            f"{TITLE_ID}) or set GBOX_RE6_SWITCH_ROMFS; the reader never extracts the title itself")
    slots = _arc_slots(romfs)
    character, _, costume = (e.get("key") or "").partition(":")
    path = slots.get((character, costume))
    if path is None and costume == "default":                 # roster fallback naming: the native default body
        candidates = sorted(p for (c, _cost), p in slots.items() if c == character)
        path = (next((p for p in candidates if "Usa" in p.stem), None)
                or next((p for p in candidates if p.stem.endswith("A")), None)
                or candidates[0])
    if path is None:
        raise SwitchModelError(f"{e['key']} has no body arc in this RomFS")
    ctx.progress(40, f"Reading {path.name} (MTF body arc)")
    r = extract(path, Path(work) / f"{e['slug']}.gltf", e["name"])
    ctx.progress(70, f"{e['name']}: {r['triangles']} triangles, {r['joints']} joints")
    rel = f"{TITLE_ID}:{path.name}"
    return {"files": [r["gltf"]], "tool": "gbox.re6_switch_chars (MTF arc/MOD reader)",
            "source_files": [rel], "roles": r["roles"],
            "extra": {"re6sw_reader": READER_VERSION, "re6sw_slot": e["key"], "re6sw_arc": rel,
                      "native_player": e["key"].split(":", 1)[0] in
                      ("leon", "helena", "chris", "piers", "jake", "sherry", "ada")},
            "notes": f"{r['vertices']} vertices, {r['triangles']} triangles, {r['joints']} bones with "
                     f"per-vertex skin weights and the RE6 bone-id role table, from {path.name}. "
                     "Writer slot: characters op=use (re6_switch_models)."}


def main(argv=None) -> int:
    import argparse, json, sys
    ap = argparse.ArgumentParser(description="RE6 Switch body arcs -> rigged GLBs")
    ap.add_argument("romfs")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = True
    for (character, costume), path in sorted(_arc_slots(Path(a.romfs)).items()):
        try:
            r = extract(path, out / f"re6sw_{character}_{costume.lower()}.gltf")
            print(json.dumps({"key": f"{character}:{costume}", "vertices": r["vertices"],
                              "triangles": r["triangles"], "joints": r["joints"]}), flush=True)
        except Exception as err:                              # noqa: BLE001 - report every slot
            ok = False
            print(json.dumps({"key": f"{character}:{costume}", "error": f"{type(err).__name__}: {err}"}), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
