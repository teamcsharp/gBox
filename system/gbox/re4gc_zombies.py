"""Resident Evil 4 (GameCube) enemies as a model from the collection - the whole swap in one call.

The player swap (`gbox.char_swap`) rebuilds the four player packs from a glTF rigged to the PLAYER skeleton. Enemies are a
different problem: there are 31 ganado packs, each with its own skeleton, and each sits in a fixed-size hole on the disc. This
module does that swap:

* **roles from geometry** - a model from the collection usually has no anatomical joint names, so `gbox.rig_roles` reads the
  roles off the rest pose (limb pairs first, then the spine)
* **retarget per pack** - `gbox.re4gc_enemies.retarget` fits the source rig onto that pack's own skeleton
* **container** - `write_rigged_gltf` writes a JSON glTF; `attachments.glb_bytes` turns it into the GLB `swap_body` wants
* **fit to the disc slot** - a rebuilt pack must not be bigger than the original, so each pack is tried with its spare bodies
  collapsed, then with only the model's biggest primitive, then with smaller textures
* **pad to the original size** - the rule that makes any of this visible: a shorter file written in place leaves the original's
  tail readable, and the game then draws the original mesh out of it

Everything is reported per pack, so a pack that cannot be fitted says so with its best size instead of failing silently.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# module level, so a test can patch these three names on this module
from . import attachments, re4gc_enemies, re4gc_models, rig_roles

PACKS = ("em10", "em11", "em12", "em13", "em14", "em15", "em16", "em17", "em19", "em1a", "em1b", "em1c",
         "em1d", "em1e", "em1f", "em20", "em46", "em4c", "em4d", "em4f", "em50", "em56",
         "em5c", "em5d", "em5f", "em60", "em66", "em6c", "em6d", "em6f", "em70")


def enemy_packs(iso) -> list[str]:
    """Every ENEMY pack on the disc, read from its file system rather than a hand-kept list.

    The disc keeps 128 files under em/: the 31 ganados in PACKS, ~30 more enemy files (em18, em21..em3e - soldiers, novistadors,
    the "It", villagers of other kinds), and the pl*/wep* families that live in the same folder. A list written by hand missed
    the middle group, which is why a stage could still spawn stock enemies after "all" the ganados were swapped. Anything that
    starts with em/em is an enemy model.
    """
    try:
        from .gcdisc import GCDisc
        disc = GCDisc(iso)
    except Exception:
        return []
    try:
        return sorted(Path(name).stem for name in disc.files
                      if name.startswith("em/em") and name.endswith(".drs"))
    finally:
        disc.f.close()


def thin_prims(prims, keep: float):
    """Drop triangles from every primitive until `keep` of them remain, and keep only the vertices still referenced.

    The fitting ladder can run out of room when a pack has little slack - the soldier and novistador packs are like that - and
    the alternative to thinning is Blender, which may not be on the node. A stride over each primitive's triangle list costs
    no dependencies and keeps the model recognisable; vertices no triangle uses are dropped so the buffer actually shrinks.
    """
    import numpy as np
    out = []
    for prim in prims:
        if prim.get("tris") is None or keep >= 1:
            out.append(prim)
            continue
        tris = np.asarray(prim["tris"])
        if len(tris) < 2:
            out.append(prim)
            continue
        stride = max(1, int(round(1 / max(keep, 1e-6))))
        thinned = tris[::stride]
        used = np.unique(thinned.reshape(-1))
        if len(used) < 3:
            out.append(prim)
            continue
        remap = {int(old): new for new, old in enumerate(used)}
        new_prim = dict(prim)
        for field in ("pos", "nrm", "uv", "owner"):
            value = prim.get(field)
            if value is not None:
                new_prim[field] = np.asarray(value)[used]
        if prim.get("J") is not None:
            new_prim["J"] = np.asarray(prim["J"])[used]
        if prim.get("W") is not None:
            new_prim["W"] = np.asarray(prim["W"])[used]
        new_prim["tris"] = np.array([[remap[int(a)], remap[int(b)], remap[int(c)]] for a, b, c in thinned])
        out.append(new_prim)
    return out


def body_candidates(pack, enemies=None) -> list[int]:
    """The BIN items that can serve as a body, in preference order.

    `re4gc_enemies.body_slots` knows the layout of the ganado packs. Other enemy files hold the same kind of skinned BIN but at
    different indices - em21's body is item 0 (32 bones), em2b carries fourteen skinned BINs (64-74 bones) - so when the known
    slots are absent the candidates are found by asking each BIN whether it parses with a skeleton, biggest skeleton first. That
    is what turns "no body slot" from a dead end into another pack the same writer can rebuild.
    """
    if enemies is None:
        enemies = re4gc_enemies
    slots = enemies.body_slots(pack)
    if slots:
        return list(slots)
    scored = []
    for index, (kind, payload) in enumerate(pack.items):
        if kind != "BIN":
            continue
        try:
            parsed = re4gc_models.bin_read(payload)
        except Exception:
            continue
        bones = getattr(parsed, "bones", None)
        if bones:
            scored.append((len(bones), index))
    scored.sort(reverse=True)
    return [index for _bones, index in scored]


def target_roles(template) -> dict:
    """A `roles` map for THIS skeleton, keyed by its own bone ids.

    `re4gc_enemies.GANADO_ROLES` is written against the ganado bone numbering ("pelvis": 17, ...). Some enemy files carry a
    different numbering or fewer bones, and the retarget then raises KeyError on the first role that does not exist. The roles
    can be read off the skeleton itself the same way `gbox.rig_roles` reads a source rig: limb pairs first, then the spine.
    Returns {} when the skeleton has no recognisable humanoid shape, so the caller can report that instead of crashing.
    """
    bones = getattr(template, "bones", None) or []
    if not bones:
        return {}
    try:
        world = template.bone_world()
    except Exception:
        return {}
    joints, ids, parent = [], [], []
    index_by_id = {}
    for index, bone in enumerate(bones):
        bone_id = bone[0]
        ids.append(bone_id)
        index_by_id[bone_id] = index
        joints.append(tuple(float(v) for v in world[bone_id]))
    for bone in bones:
        par = bone[1]
        parent.append(index_by_id.get(par, -1) if par != 0xFF else -1)
    derived = rig_roles.derive(joints, parent)
    mapping = {role: ids[index] for role, index in derived.items() if 0 <= index < len(ids)}
    # the retargeter's own map names the root BOTH "pelvis" and "hip"; rig_roles calls it "hip", so alias it
    if "hip" in mapping and "pelvis" not in mapping:
        mapping["pelvis"] = mapping["hip"]
    return mapping


def degenerate(template) -> str:
    """Why this skeleton cannot be retargeted onto, or '' when it is usable."""
    bones = getattr(template, "bones", None) or []
    if len(bones) < 4:
        return f"skeleton has {len(bones)} bones"
    try:
        world = template.bone_world()
    except Exception as exc:
        return f"bone world failed: {type(exc).__name__}"
    heights = [float(world[bone[0]][1]) for bone in bones]
    span = max(heights) - min(heights)
    if not (span > 1e-3):
        return "skeleton has no height (all bones at one level)"
    # a bone at NaN/inf poisons the retarget's own scale (it divides by the model's height), and the failure surfaces much
    # later as "cannot convert float NaN to integer" during vertex packing, so it is caught here instead
    for bone in bones:
        x, y, z = (float(v) for v in world[bone[0]])
        if not all(map(math.isfinite, (x, y, z))):
            return f"bone {bone[0]} has a non-finite position"
    return ""


def attempts(primitive_counts):
    """The fitting strategies, in the order they are tried: (label, how many primitives to keep, texture limit).

    Collapsing the pack's spare bodies costs nothing visually, so it is always on; the primitive count and the texture size are
    what give way next. Measured on the 31 ganado packs: 8 fit with every primitive, 22 need only the biggest one, 1 needs
    small textures as well.
    """
    counts = []
    for count in primitive_counts:
        if count not in counts:
            counts.append(count)
    plan = [(f"keep={count} tex=64", count, 64, 1.0) for count in counts]
    plan += [(f"keep={counts[0]} tex=16", counts[0], 16, 1.0)]
    # last resort: thin the triangles (no Blender needed) at the biggest primitive count that leaves a mesh
    for fraction in (0.6, 0.35, 0.2):
        plan.append((f"keep={counts[0]} tex=64 thin={fraction:.0%}", counts[0], 64, fraction))
    return plan


def derive_rig(model, characters=None, rig_roles=None):
    """A model from the collection -> the rig dict `re4gc_enemies.retarget` takes, roles found by geometry.

    Returns (rig, roles_by_name). Raises ValueError when the rest pose does not look like a humanoid (fewer than ten roles),
    because retargeting on a partial map produces a mangled enemy rather than an error.
    """
    import numpy as np
    if characters is None:
        from . import characters as characters_mod
        characters = characters_mod
    if rig_roles is None:
        from . import rig_roles as rig_roles_mod
        rig_roles = rig_roles_mod
    model = Path(model)
    gl, acc, image, world = characters._load(model)
    nodes = gl.get("nodes") or []
    names = [node.get("name") or f"n{index}" for index, node in enumerate(nodes)]
    joints = [tuple(float(v) for v in np.asarray(world[i])[:3, 3]) for i in range(len(nodes))]
    parent = [-1] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            parent[child] = index
    roles = rig_roles.named(joints, parent, names)
    if len(roles) < 10:
        raise ValueError(f"{model.name}: only {len(roles)} joint roles found ({sorted(roles)}); "
                         f"a humanoid rest pose needs hip, chest, head and both limb chains")
    return characters.rig_from_gltf(model, roles), roles


def swap_ganados(iso, model, out_dir, packs=None, *, rig=None, log=print, swap=None, read=None):
    """Every ganado pack rebuilt around `model`, each padded to its own disc size.

    swap(original_bytes, glb_path, body, hide, max_tex) -> rebuilt_bytes   (injectable for tests)
    read(name) -> bytes                                                    (injectable for tests)
    Returns {pack: report}, each report carrying `fitted` and either the sizes or the reason it could not fit.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if rig is None:
        rig, _roles = derive_rig(model)
    enemies, R = re4gc_enemies, re4gc_models

    if read is None:
        from .gcdisc import GCDisc
        iso_path = Path(iso)

        def read(name):
            disc = GCDisc(iso_path)
            try:
                return disc.read(name)
            finally:
                disc.f.close()

    if swap is None:
        def swap(original, glb, body, hide, max_tex):
            pack = R.ModelPack(original)
            R.swap_body(pack, glb, body, hide=hide, max_tex=max_tex, shrink_hidden=True)
            return pack.to_bytes()

    report = {}
    chosen = list(packs) if packs else (enemy_packs(iso) or list(PACKS))
    for stem in chosen:
        name = f"em/{stem}.drs"
        try:
            original = read(name)
        except Exception as exc:                                    # absent from this disc
            report[stem] = {"fitted": False, "reason": f"absent ({type(exc).__name__})"}
            log(f"{stem}: absent")
            continue
        try:
            pack = R.ModelPack(original)
            slots = body_candidates(pack, enemies)
            if not slots:
                report[stem] = {"fitted": False, "reason": "no body slot"}
                log(f"{stem}: no body slot")
                continue
            body = slots[0]
            template = R.bin_read(pack.items[body][1])
            why = degenerate(template)
            if why:
                report[stem] = {"fitted": False, "reason": f"unusable skeleton: {why}"}
                log(f"{stem}: unusable skeleton ({why})")
                continue
            try:
                prims = enemies.retarget(rig, template)
            except (KeyError, ValueError, IndexError):
                # this skeleton does not carry the ganado bone numbering: derive the roles from the skeleton itself
                roles = target_roles(template)
                if len(roles) < 10:
                    report[stem] = {"fitted": False, "reason": f"skeleton roles: only {len(roles)} found"}
                    log(f"{stem}: only {len(roles)} roles on its own skeleton")
                    continue
                prims = enemies.retarget(rig, template, roles=roles)
        except Exception as exc:
            report[stem] = {"fitted": False, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
            log(f"{stem}: {type(exc).__name__}")
            continue
        # biggest primitive first: numpy arrays must not be tested for truth, so this measures the length directly
        prims = sorted(prims, key=lambda p: -len(p["pos"]) if p.get("pos") is not None else 0)
        glb_paths = {}
        best = None
        for label, keep, max_tex, fraction in attempts([len(prims), 1]):
            key = (keep, round(fraction, 3))
            if key not in glb_paths:
                subset = thin_prims(prims[:keep], 1.0) if fraction >= 1 else thin_prims(prims[:keep], fraction)
                gltf = enemies.write_rigged_gltf(subset, template, out_dir / f"{stem}_{keep}_{key[1]}.gltf")
                doc, blob = attachments.pack(gltf)
                glb = out_dir / f"{stem}_{keep}_{key[1]}.glb"
                glb.write_bytes(attachments.glb_bytes(doc, blob))
                glb_paths[key] = glb
            try:
                rebuilt = swap(original, glb_paths[key], body, tuple(slots[1:]), max_tex)
            except Exception as exc:
                report[stem] = {"fitted": False, "reason": f"swap {type(exc).__name__}: {str(exc)[:100]}"}
                break
            if best is None or len(rebuilt) < best[0]:
                best = (len(rebuilt), label, rebuilt)
            if len(rebuilt) <= len(original):
                (out_dir / f"{stem}.drs").write_bytes(rebuilt + b"\0" * (len(original) - len(rebuilt)))
                report[stem] = {"fitted": True, "how": label, "bytes": len(rebuilt), "disc": len(original)}
                log(f"{stem}: fits with {label} ({len(rebuilt)} <= {len(original)})")
                break
        else:
            report[stem] = {"fitted": False, "reason": f"grows: best {best[0]} vs {len(original)}"}
            log(f"{stem}: grows (best {best[0]} vs {len(original)})")
    return report


def summary(report) -> str:
    """One line per pack plus a count, for a log or a job's output."""
    fitted = [p for p, row in report.items() if row.get("fitted")]
    lines = [f"{pack}: {row.get('how') or row.get('reason')}" for pack, row in sorted(report.items())]
    lines.append(f"{len(fitted)}/{len(report)} packs fitted")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="RE4 GameCube: enemies as a model from the collection")
    parser.add_argument("--iso", required=True, help="the disc image")
    parser.add_argument("--model", required=True, help="a rigged .glb/.gltf from the collection")
    parser.add_argument("--out", required=True, help="where the rebuilt em/*.drs packs are written")
    parser.add_argument("--packs", default="", help="comma separated pack stems (default: all)")
    args = parser.parse_args(argv)
    packs = [p.strip() for p in args.packs.split(",") if p.strip()] or None
    report = swap_ganados(args.iso, args.model, args.out, packs)
    print(summary(report))
    print(json.dumps(report, indent=2)[:4000])
    return 0 if any(row.get("fitted") for row in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
