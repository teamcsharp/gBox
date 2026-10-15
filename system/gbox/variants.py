"""Variant characters: an edited copy of a collection character (Blender Live Link, or a head-size change in the session
sidebar) that every swap writer can build like any other character.

A variant is a normal collection entry (<cache>/characters/<slug>/meta.json + model + preview) with:
  variant_of   the base slug (the entry it was made from)
  variant      {base_name, made_with, revision, updated, props, scale, skeleton check}
  rig.roles    the base's body roles (Blender keeps the joint names), rig.scale {"head": k} (head-bone scale)
  props        extra meshes bound to a bone: [{node, bone, role, triangles}] (a hat on the head joint -> role "head")
  targets      the base's targets, copied as {"slot", "needs_rebuild": true, "base_mod"} (no mod yet: the first
               characters op=use builds it); a re-sent variant (Live Link push) marks its own built mods needs_rebuild.
Bones must stay as they were in the base (names, count, hierarchy): the writers map joints by name and the games' skeletons
never change; a variant whose skeleton differs is refused with the list of differences.
"""
from __future__ import annotations

import json
import shutil
import struct
import time
from pathlib import Path


def _gl(path: Path) -> dict:
    d = Path(path).read_bytes()
    if d[:4] == b"glTF":
        jl = struct.unpack_from("<I", d, 12)[0]
        return json.loads(d[20:20 + jl])
    return json.loads(d)


def skeleton(path: Path) -> dict:
    """{joint name: parent joint name | None} of the model's biggest skin (the body)."""
    gl = _gl(path)
    skins = gl.get("skins") or []
    if not skins:
        return {}
    main = max(skins, key=lambda s: len(s["joints"]))
    js = set(main["joints"])
    par = {c: i for i, n in enumerate(gl["nodes"]) for c in n.get("children", [])}
    out = {}
    for j in main["joints"]:
        p = par.get(j)
        while p is not None and p not in js:
            p = par.get(p)
        out[gl["nodes"][j].get("name", f"node{j}")] = gl["nodes"][p].get("name", f"node{p}") if p is not None else None
    return out


def check_skeleton(new: Path, base: Path) -> dict:
    """Bone count, names and hierarchy unchanged (the 'order' a writer depends on is the parent chain + names)."""
    a, b = skeleton(base), skeleton(new)
    problems = []
    if len(a) != len(b):
        problems.append(f"bone count {len(b)} (base has {len(a)})")
    if missing := sorted(set(a) - set(b)):
        problems.append("bones missing or renamed: " + ", ".join(missing[:12]))
    if extra := sorted(set(b) - set(a)):
        problems.append("new bones: " + ", ".join(extra[:12]) + " (add props as objects bound to a bone, not as bones)")
    moved = [n for n in set(a) & set(b) if a[n] != b[n]]
    if moved:
        problems.append("bones re-parented: " + ", ".join(f"{n} ({a[n]} -> {b[n]})" for n in sorted(moved)[:8]))
    return {"ok": not problems, "bones": len(b), "base_bones": len(a), "problems": problems}


def find_props(path: Path, roles: dict, hints: list | None = None, base_model: Path | None = None) -> list[dict]:
    """Meshes that aren't skinned = props: each one's bone (nearest joint ancestor in the node tree) and the body role
    that bone belongs to (its nearest ancestor with a role: a hat on 'Head_end' still rides the head).
    base_model: the variant's original - its own unskinned meshes (a rigid-part body: N64 / PS1 limbs) are body, not
    props, unless the original listed them as props; a node the export marked gbox_part=body is never a prop."""
    from . import attachments
    gl = _gl(path)
    base_body = set()
    if base_model is not None:
        bgl = _gl(base_model)
        base_body = {n.get("name") for n in bgl.get("nodes") or [] if "mesh" in n} - attachments.prop_nodes(bgl)
    skins = gl.get("skins") or []
    joints = {j for s in skins for j in s["joints"]}
    par = {c: i for i, n in enumerate(gl["nodes"]) for c in n.get("children", [])}
    name = lambda i: gl["nodes"][i].get("name", f"node{i}")            # noqa: E731
    role_of = {n: r for r, n in roles.items()}
    hint = {h.get("object") or h.get("node"): h for h in hints or [] if isinstance(h, dict)}
    out = []
    for i, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd or "skin" in nd or attachments.extras(nd).get("gbox_part") == "body":
            continue
        if name(i) in base_body and not attachments.is_marked(nd):
            continue
        p = par.get(i)
        while p is not None and p not in joints:
            p = par.get(p)
        bone = name(p) if p is not None else None
        role, q = None, p
        while q is not None and role is None:
            role = role_of.get(name(q)) if q in joints else None
            q = par.get(q)
        tris = 0
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            a = gl["accessors"][pr["indices"]] if "indices" in pr else gl["accessors"][pr["attributes"]["POSITION"]]
            tris += a["count"] // 3
        h = hint.get(name(i), {})
        out.append({"node": name(i), "bone": bone, "role": role or ("hip" if bone else None), "triangles": tris,
                    "bound": bone is not None, **({"requested_bone": h["bone"]} if h.get("bone") else {})})
    return out


def _inherit_targets(base: dict, prev: dict | None) -> dict:
    """Base targets -> 'needs rebuild' entries; a re-sent variant keeps its own built mods, marked needs_rebuild."""
    out = {}
    for gid, lst in (base.get("targets") or {}).items():
        for t in lst:
            out.setdefault(gid, []).append({"slot": t.get("slot", "player"), "needs_rebuild": True, "base_mod": t.get("mod"),
                                            "notes": f"inherited from {base['name']}: built on the first use"})
    for gid, lst in ((prev or {}).get("targets") or {}).items():
        mine = [dict(t, needs_rebuild=True) for t in lst if t.get("mod")]
        if mine:
            slots = {t.get("slot", "player") for t in mine}
            out[gid] = mine + [t for t in out.get(gid, []) if t["slot"] not in slots]
    return out


def store(ctx, root: Path, base_slug: str, name: str, model: Path, scale: dict | None = None, hints: list | None = None,
          replace: str = "", made_with: str = "gBox Live Link (Blender)", extra_files: list[Path] = (),
          keep_rigs: bool = False, slug: str = "") -> dict:
    """Write (or update in place: replace=<variant slug>) a variant entry. Raises ValueError when the skeleton changed."""
    from . import characters as C
    base = C.get(root, base_slug)
    base_model = Path(root) / base_slug / base["model"]
    chk = check_skeleton(model, base_model)
    if not chk["ok"]:
        raise ValueError("blocked: the skeleton changed - " + "; ".join(chk["problems"]) +
                         ". Game skeletons can't change: undo the bone edits (scale/pose bones instead, add props as objects).")
    prev = None
    if replace and (Path(root) / replace / "meta.json").is_file():
        prev = C.get(root, replace)
        if prev.get("variant_of") != base_slug:
            raise ValueError(f"{replace} isn't a variant of {base_slug}: can't update it")
        slug = replace
    elif not slug:
        slug = C.free_slug(root, name)
    names = set(skeleton(model))
    roles = {r: n for r, n in ((base.get("rig") or {}).get("roles") or {}).items() if n in names}
    sc = {k: round(float(v), 3) for k, v in (scale or {}).items() if v and abs(float(v) - 1) > 0.005}
    props = find_props(model, roles, hints, base_model)
    from . import attachments
    attachments.stamp(model, props)                        # marked in the file too: any writer finds them
    d = Path(root) / slug
    if prev:                                               # the old model file / Mario- or Leon-rigged copies are stale
        for f in [d / prev["model"], d / "targets"]:
            shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
    rev = ((prev or {}).get("variant") or {}).get("revision", 0) + 1
    var = {"base_name": base["name"], "made_with": made_with, "revision": rev, "updated": time.time(), "props": props,
           "scale": sc, "skeleton": chk}
    meta = C.add(root, slug, name, [model, *extra_files], dict(base.get("source") or {}, variant_of=base_slug),
                 made_with, rig={"roles": roles, **({"scale": sc} if sc else {})}, aliases=[name], kind=base.get("kind", "character"),
                 notes=f"variant of {base['name']}" + (f"; props: {', '.join(p['node'] + ' on ' + str(p['bone']) for p in props)}" if props else "")
                       + (f"; scale {sc}" if sc else ""),
                 extra={"variant_of": base_slug, "variant": var, "props": props,
                        **({"rigs": base["rigs"]} if keep_rigs and base.get("rigs") else {})})
    meta["targets"] = _inherit_targets(base, prev)
    photo=(base.get('photo_skin_approval') or {}).get('source_photo') or base.get('selfie_photo')
    if photo:
        meta['selfie_photo']=photo
        meta['tags']=list(dict.fromkeys([*(base.get('tags') or []),'selfie:'+photo]))
    return C.put_meta(root, meta)


def head_variant(ctx, root: Path, base_slug: str, k: float, rebuild: bool = False) -> dict:
    """The sidebar's 'Head size' slider: <name> - big head (x k) as a variant (same model, rig.scale.head = k)."""
    from . import characters as C
    base = C.get(root, base_slug)
    while base.get("variant_of") and not (base.get("variant") or {}).get("props") and (base.get("variant") or {}).get("made_with") == "head size":
        base = C.get(root, base["variant_of"])             # resizing a head-size variant: start from its base
    k = round(min(3.0, max(0.5, float(k))), 2)
    slug = f"{base['slug']}_head{int(round(k * 100))}"
    scale = dict(((base.get("rig") or {}).get("scale") or {}), head=k * ((base.get("rig") or {}).get("scale") or {}).get("head", 1.0))
    if (Path(root) / slug / "meta.json").is_file() and not rebuild:
        return C.get(root, slug)
    name = f"{base['name']} – {'big' if k > 1 else 'small'} head ×{k:g}"
    src = Path(root) / base["slug"]
    model = src / base["model"]
    extras = [f for f in src.iterdir() if f.name not in ("meta.json", "preview.png", "targets", base["model"]) and not f.name.startswith(".")]
    if (Path(root) / slug).exists():
        shutil.rmtree(Path(root) / slug)
    tmp = Path(ctx.config.cache) / "characters_build" / "head" / slug
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copy2(model, tmp / model.name)                  # add() copies into <slug>/ (never from inside the base folder)
    m = store(ctx, root, base["slug"], name, tmp / model.name, scale=scale, made_with="head size", extra_files=extras, slug=slug)
    shutil.rmtree(tmp, ignore_errors=True)
    return m
