"""Blender round trip: any collection character out to Blender with its rig roles, and back in as a library character.

OUT  export_glb(root, slug): the character's model as ONE self-contained GLB (textures embedded) carrying gBox metadata
     as glTF extras, which Blender's importer turns into custom properties and its exporter writes back:
       scene / asset extras  {"gbox": {slug, name, base, variant_of, roles, props, source_game, kind, revision}}
       joint nodes           {"gbox_role": "<role>"}                      (bones keep their role names)
       mesh nodes            {"gbox_part": "body"} | {"gbox_prop": true, "gbox_bone": "<bone>"}  (attachments)
     Routes (register()):  GET  /api/characters/{slug}/blender          the GLB (add-on Pull, blender_copy, picker)
                           POST /api/characters/{slug}/blender/copy     -> the gBox clipboard (Ctrl+Shift+V in Blender);
                                {native: true} also queues blender_copy (Blender's own Ctrl+V clipboard on that PC)
                           POST /api/characters/blender/import          -> a `characters op=add` job (the import below)

IN   characters op=add (the add-on's "Send to gBox", the picker's import) runs classify() then:
     variant   the GLB names a collection character (base=, or the extras the export wrote: an armature node with
               gbox_slug / gbox_base, the scene's gbox) and its skeleton is unchanged -> gbox.variants.store: meta
               variant_of = the original, the base's rig roles, attachments as props (rigid, bound to their bone, own
               textures), revision + 1 on a re-send (replace=<variant slug>)
     derived   it names one but the bones changed and derived_ok -> a NEW character with derived_from = the original,
               roles from the bones that kept their names (gbox_role extras) + detection
     new       nothing gBox about it (modelled in Blender): roles from rig_roles, gbox_role extras, or
               gbox.rig_detect.detect (Mixamo, Rigify, VRoid/VRM, UE mannequin, 3ds Max biped, Blender metarig, joint
               tree); no skeleton -> gbox.rig_detect.auto_rig (auto_rig=true, the default) or stored unrigged with
               the reason. Either way rig.roles with a hip = a donor every writer (and cast_swap's gate) accepts.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from pydantic import BaseModel

from . import attachments


# ---------------------------------------------------------------- out: library -> Blender

def gbox_info(meta: dict) -> dict:
    roles = (meta.get("rig") or {}).get("roles") or {}
    # A photo donor is a new visual source; don't flatten a Blender edit back to unmodified Leon.
    base = meta['slug'] if meta.get('photo_skin_approval') else meta.get('variant_of') or meta['slug']
    return {"slug": meta["slug"], "name": meta.get("name"), "base": base,
            "variant_of": meta.get("variant_of") or "", "roles": roles,
            "props": [{"node": p.get("node"), "bone": p.get("bone"), "role": p.get("role")} for p in meta.get("props") or []],
            "source_game": (meta.get("source") or {}).get("game_title") or "", "kind": meta.get("kind") or "character",
            "revision": (meta.get("variant") or {}).get("revision", 0), "exported": time.time()}


def tag(gl: dict, meta: dict) -> dict:
    """Write the gBox extras into a glTF json (in place) -> the gbox info block."""
    info = gbox_info(meta)
    role_of = {n: r for r, n in info["roles"].items()}
    props = {p["node"]: p for p in info["props"] if p.get("node")}
    joints = {j for s in gl.get("skins") or [] for j in s.get("joints") or []}
    for i, nd in enumerate(gl.get("nodes") or []):
        e = dict(attachments.extras(nd))
        nm = nd.get("name")
        if i in joints and nm in role_of:
            e["gbox_role"] = role_of[nm]
        if "mesh" in nd:
            p = props.get(nm)
            if p is not None and "skin" not in nd:
                e.update({"gbox_prop": True, **({"gbox_bone": p["bone"]} if p.get("bone") else {})})
                e.pop("gbox_part", None)
            else:
                e["gbox_part"] = "body"
        if e:
            nd["extras"] = e
    scenes = gl.setdefault("scenes", [{"nodes": list(range(len(gl.get("nodes") or [])))}])
    sc = scenes[gl.get("scene", 0) if gl.get("scene", 0) < len(scenes) else 0]
    sc["extras"] = {**(sc.get("extras") if isinstance(sc.get("extras"), dict) else {}), "gbox": info}
    gl.setdefault("asset", {"version": "2.0"})["extras"] = {"gbox": info}
    return info


def export_glb(root: Path, slug: str) -> bytes:
    from . import characters as C
    meta = C.get(root, slug)
    gl, blob = attachments.pack(Path(root) / slug / meta["model"])
    tag(gl, meta)
    return attachments.glb_bytes(gl, blob)


# ---------------------------------------------------------------- in: Blender -> library

def read_info(gl: dict) -> dict:
    """What a GLB says about its gBox origin: {base, slug, roles (from gbox_role joint extras), info}."""
    out: dict = {"roles": {}}
    nodes = gl.get("nodes") or []
    joints = [j for s in gl.get("skins") or [] for j in s.get("joints") or []]
    for j in joints:
        r = attachments.extras(nodes[j]).get("gbox_role")
        if isinstance(r, str) and r and r not in out["roles"]:
            out["roles"][r] = nodes[j].get("name", f"node{j}")
    par = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    anc = set()                                            # the main skeleton's ancestors (the armature object's node)
    if gl.get("skins"):
        main = max(gl["skins"], key=lambda s: len(s.get("joints") or []))
        for j in main.get("joints") or []:
            p = par.get(j)
            while p is not None:
                anc.add(p)
                p = par.get(p)
    cands = sorted(range(len(nodes)), key=lambda i: (i not in anc, i))
    for i in cands:                                        # Blender: armature object custom props -> its node's extras
        e = attachments.extras(nodes[i])
        if e.get("gbox_base") or e.get("gbox_slug"):
            out["base"] = e.get("gbox_base") or e.get("gbox_slug")
            out["slug"] = e.get("gbox_slug") or out["base"]
            out["from"] = "armature extras"
            break
    if "base" not in out:
        for holder in [*(gl.get("scenes") or []), gl.get("asset") or {}]:
            g = (holder.get("extras") or {}).get("gbox") if isinstance(holder.get("extras"), dict) else None
            if isinstance(g, dict) and (g.get("base") or g.get("slug")):
                out.update(base=g.get("base") or g.get("slug"), slug=g.get("slug"), info=g, **{"from": "scene extras"})
                if not out["roles"] and isinstance(g.get("roles"), dict):
                    names = {nodes[j].get("name") for j in joints}
                    out["roles"] = {r: n for r, n in g["roles"].items() if n in names}
                break
    return out


def classify(model: Path, root: Path, base: str = "") -> dict:
    """variant | derived | new (module doc), with the evidence."""
    from . import characters as C, variants
    gl, _ = attachments.read_gltf(model)
    info = read_info(gl)
    want = base or info.get("base") or ""
    out = {"info": info, "skinned": bool(gl.get("skins"))}
    if want and not (Path(root) / want / "meta.json").is_file():
        hit = C.best_match(C.list_all(root), want) if base else None
        if base and not hit:
            raise ValueError(f"no collection character {base!r} to make a variant of")
        want = (hit or {}).get("slug", "") if hit else ""     # extras naming a character this library hasn't: new
    if not want:
        return out | {"mode": "new"}
    bm = C.get(root, want)
    chk = variants.check_skeleton(model, Path(root) / want / bm["model"])
    return out | {"mode": "variant" if chk["ok"] else "derived", "base": want, "skeleton": chk, "base_name": bm.get("name")}


def new_props(model: Path, roles: dict, hints: list | None = None) -> list[dict]:
    """Attachments of a character that has no base: marked nodes, and - when the body is skinned - every unskinned mesh
    hanging under a joint (a sword parented to the hand bone) that isn't marked as body."""
    from . import variants
    gl, _ = attachments.read_gltf(model)
    marked = attachments.prop_nodes(gl)
    skinned_body = any("skin" in n and "mesh" in n for n in gl.get("nodes") or [])
    rows = variants.find_props(model, roles, hints)
    by = {n.get("name"): n for n in gl.get("nodes") or []}
    keep = []
    for r in rows:
        nd = by.get(r["node"]) or {}
        if attachments.extras(nd).get("gbox_part") == "body":
            continue
        if r["node"] in marked or (skinned_body and r.get("bound")):
            keep.append(r)
    return keep


def _roles(model: Path, inp, info: dict, base_meta: dict | None) -> tuple[dict, dict]:
    """(roles, how) for a non-variant import: explicit > gbox_role extras (+ the base's still-present names) > detect."""
    from . import characters as C, rig_detect
    if inp.rig_roles:
        return C.validate_rig_roles(model, inp.rig_roles), {"rig": "given", "evidence": "rig_roles"}
    gl, _ = attachments.read_gltf(model)
    names = set(rig_detect.skin_joint_names(gl))
    roles = {r: n for r, n in (info.get("roles") or {}).items() if n in names}
    if base_meta:
        for r, n in ((base_meta.get("rig") or {}).get("roles") or {}).items():
            if n in names:
                roles.setdefault(r, n)
    if rig_detect.usable(roles) or ({"hip", "head"} <= roles.keys() and len(roles) >= 6):
        return roles, {"rig": "gbox", "evidence": "gbox_role bone names" + (" + the original's roles" if base_meta else ""),
                       "matched": len(roles)}
    det = rig_detect.detect(model)
    merged = {**det.get("roles", {}), **roles}
    return merged, {k: v for k, v in det.items() if k != "roles"}


# asset extras gbox_source keys copied into the entry's meta (a converted / downloaded model says where it came from:
# gbox.sm64_decomp writes them for the SM64 ROM and Render96 HD donors); `licence` replaces characters.LICENCE
SOURCE_META = ("licence", "attribution", "character", "donor_group", "donor_quality", "pose", "reader",
               "reader_version")


def source_info(model: Path) -> dict:
    """The model's asset extras gbox_source ({pack, url, licence, attribution, game_title, character, donor_group,
    donor_quality ...}), else {}."""
    try:
        gl, _ = attachments.read_gltf(model)
    except (OSError, ValueError):
        return {}
    gs = ((gl.get("asset") or {}).get("extras") or {}).get("gbox_source")
    return dict(gs) if isinstance(gs, dict) else {}


def store_new(ctx, root: Path, f: Path, name: str, inp, game: dict | None, cls: dict) -> dict:
    """A character modelled (or re-boned) in Blender -> a collection entry: detected / auto-rigged roles, props."""
    from . import characters as C, rig_detect
    base_meta = C.get(root, cls["base"]) if cls.get("base") else None
    notes, rig_how, auto = [], {}, None
    if not cls.get("skinned"):
        if getattr(inp, "auto_rig", True):
            rigged = f.with_name(f.stem + "_rigged.glb")
            auto = rig_detect.auto_rig(f, rigged)
            final = f.with_suffix(".glb")
            f.unlink(missing_ok=True)
            rigged.replace(final)
            f = final
            roles, rig_how = auto["roles"], {"rig": "auto", "evidence": f"auto rig ({auto['pose']} pose, rigid weights)"}
            notes.append("no skeleton: auto-rigged (18 humanoid joints, rigid weights); rig it in Blender for real weights")
        else:
            roles, rig_how = {}, {"rig": None, "why": "no skeleton and auto_rig=false"}
            notes.append("no skeleton: stored as a static model (send with auto_rig=true, or rig it in Blender)")
    else:
        roles, rig_how = _roles(f, inp, cls.get("info") or {}, base_meta)
    props = new_props(f, roles, inp.props) if cls.get("skinned") else []
    if props:
        attachments.stamp(f, props)
    slug = C.free_slug(root, name)
    src = {"game_title": (game or {}).get("title") or (f"made from {base_meta['name']} in Blender" if base_meta else "made in Blender"),
           "game_id": (game or {}).get("game_id"), "from": "clipboard" if inp.from_clipboard else inp.artifact or inp.path}
    gs = source_info(f)
    if gs and not game:                                    # where a downloaded / converted model came from (module doc)
        src.update({k: gs[k] for k in ("game_title", "game_id", "platform", "pack", "url", "branch", "commit")
                    if gs.get(k)})
    if base_meta:
        src["derived_from"] = base_meta["slug"]
        notes.append(f"derived from {base_meta['name']} (skeleton changed: {'; '.join((cls.get('skeleton') or {}).get('problems') or [])})")
    if props:
        notes.append("props: " + ", ".join(f"{p['node']} on {p['bone']}" for p in props))
    extra = {"props": props, "blender": {"rig": rig_how, "auto_rig": auto, "imported": time.time(),
                                         "detected_roles": len(roles)}}
    if base_meta:
        extra["derived_from"] = base_meta["slug"]
        photo=(base_meta.get('photo_skin_approval') or {}).get('source_photo') or base_meta.get('selfie_photo')
        if photo:
            extra['selfie_photo']=photo
            extra['tags']=list(dict.fromkeys([*(base_meta.get('tags') or []),'selfie:'+photo]))
    if gs:
        extra.update({k: gs[k] for k in SOURCE_META if gs.get(k)})
        notes.append(f"source: {gs.get('pack') or gs.get('game_title')}" + (f" ({gs['url']})" if gs.get("url") else ""))
    shown = (gs or {}).get("name") or name                # the slug comes from `name`, the shown name from the source
    meta = C.add(root, slug, shown, [f], src, (gs or {}).get("reader") or "Blender (gBox add-on: Send to gBox)",
                 kind=inp.kind if inp.kind in C.KINDS else "character",
                 aliases=[name] + ([shown] if shown != name else []) + list((gs or {}).get("aliases") or []),
                 rig={"roles": roles, "detected": rig_how.get("rig")} if roles else None, notes="; ".join(notes), extra=extra)
    ready = bool(roles.get("hip"))
    return {"status": "added", "entry": meta, "env": False, "mode": cls["mode"], "roles": roles, "rig": rig_how,
            "props": props, "donor_ready": ready,
            **({"derived_from": base_meta["slug"]} if base_meta else {}),
            **({"note": "no body roles: writers can't fit it yet (" + (rig_how.get("why") or "rig not recognised") + ")"}
               if not ready else {})}


def store_variant(ctx, root: Path, f: Path, name: str, inp, base: str) -> dict:
    from . import variants
    meta = variants.store(ctx, root, base, name, f, scale=inp.scale, hints=inp.props, replace=inp.replace)
    return {"status": "added", "entry": meta, "env": False, "mode": "variant", "variant_of": meta["variant_of"],
            "props": meta.get("props"), "skeleton": meta["variant"]["skeleton"],
            "revision": meta["variant"].get("revision"), "donor_ready": True}


def import_model(ctx, inp, data: bytes, name: str, game: dict | None = None) -> dict:
    """characters op=add with a model from Blender (any route) -> variant / derived / new entry (module doc)."""
    from . import characters as C
    root = C.library_root(ctx.config)
    work = Path(ctx.config.cache) / "characters_build" / "add" / ("blender_" + (C.slugify(name) or "model"))
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    f = work / f"{C.slugify(name) or 'model'}.{'glb' if data[:4] == b'glTF' else 'gltf'}"
    if f.suffix == ".gltf" and not data.lstrip()[:1] == b"{":
        raise ValueError("that file isn't a glTF / GLB model")
    f.write_bytes(data)
    if f.suffix == ".gltf":                                # one self-contained GLB from here on
        gl, blob = attachments.pack(f)
        f = f.with_suffix(".glb")
        f.write_bytes(attachments.glb_bytes(gl, blob))
    try:
        cls = classify(f, root, inp.base)
        if cls["mode"] == "variant":
            return store_variant(ctx, root, f, name, inp, cls["base"]) | {"classified": _brief_cls(cls)}
        if cls["mode"] == "derived" and not getattr(inp, "derived_ok", False):
            raise ValueError("blocked: the skeleton changed - " + "; ".join(cls["skeleton"]["problems"]) +
                             f". Game skeletons can't change for a variant of {cls['base_name']}: undo the bone edits "
                             "(scale/pose bones instead, add props as objects), or send it as a new character "
                             "(derived_ok=true / the add-on's Send to gBox).")
        return store_new(ctx, root, f, name, inp, game, cls) | {"classified": _brief_cls(cls)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _brief_cls(cls: dict) -> dict:
    return {"mode": cls["mode"], "base": cls.get("base"), "from": (cls.get("info") or {}).get("from"),
            "skeleton": (cls.get("skeleton") or {}).get("problems") or []}


# ---------------------------------------------------------------- control-plane routes

class CopyIn(BaseModel):
    native: bool = False               # also write Blender's own clipboard (copybuffer.blend) on a worker
    worker: str = ""                   # with native: the PC whose Blender pastes (default: any that has blender_copy)


class ImportIn(BaseModel):
    name: str                          # the new entry's name
    artifact: str = ""                 # a .glb / .gltf artifact (uploaded with POST /api/artifacts)
    b64: str = ""                      # or the model itself
    from_clipboard: bool = False       # or the gBox clipboard's model
    base: str = ""                     # variant of this character ("" = what the file's gBox extras say)
    replace: str = ""                  # re-send: update this variant in place
    props: list[dict] = []             # [{object, bone}] the add-on bound
    rig_roles: dict[str, str] = {}     # {role: bone} (the add-on's gbox_role bones)
    scale: dict = {}                   # {"head": k}
    auto_rig: bool = True              # no skeleton: rig it with the humanoid heuristic
    derived_ok: bool = True            # bones changed: store as a new character derived from the original


def register(app, auth, store, chars, submit, JobRequest):
    """Routes on the control plane (server.create_app). chars() -> (characters module, library root);
    submit(JobRequest(...), actor) -> Job (the /api/jobs handler)."""
    import base64
    from fastapi import Depends, HTTPException
    from fastapi.responses import Response

    def glb(slug: str) -> bytes:
        K, root = chars()
        try:
            return export_glb(root, slug)
        except KeyError:
            raise HTTPException(404, f"no collection character {slug!r}")
        except (OSError, ValueError) as e:
            raise HTTPException(422, f"{slug}: the model can't be packed for Blender: {e}")

    @app.get("/api/characters/{slug}/blender")
    def chars_blender(slug: str, actor=Depends(auth)):
        """The character as one GLB for Blender: armature, weights, textures, rig role names (gbox_role), props."""
        return Response(glb(slug), media_type="model/gltf-binary",
                        headers={"content-disposition": f'attachment; filename="{slug}.glb"'})

    @app.post("/api/characters/{slug}/blender/copy")
    def chars_blender_copy(slug: str, inp: CopyIn = CopyIn(), actor=Depends(auth)):
        """Right-click > Copy to Blender: the character on the gBox clipboard (Ctrl+Shift+V in Blender, gBox add-on);
        native=true also queues blender_copy so a plain Ctrl+V pastes it."""
        data = glb(slug)
        K, root = chars()
        meta = K.get(root, slug)
        ref = store.put_artifact(data, f"{slug}.glb", "model/gltf-binary", {"clipboard": True, "by": actor, "character": slug})
        prev = store.get("clipboard", "current") or {"seq": 0}
        item = {"seq": prev["seq"] + 1, "kind": "gltf", "name": slug, "sha256": ref.sha256, "ts": time.time(), "by": actor,
                "meta": {"character": slug, "base": meta.get("variant_of") or slug, "roundtrip": 1,
                         "roles": (meta.get("rig") or {}).get("roles") or {}}}
        store.put("clipboard", "current", item)
        store.audit(actor, "clipboard.copy", ref.sha256, {"kind": "gltf", "name": slug, "character": slug})
        try:
            app.state.assets.invalidate()                  # the asset browser lists clipboard artifacts
        except AttributeError:
            pass
        out = {"clipboard": item, "character": slug, "name": meta.get("name"),
               "next": "In Blender: gBox sidebar > Paste (Ctrl+Shift+V); edit; gBox > Send to gBox"}
        if inp.native:
            j = submit(JobRequest(tool="blender_copy", input={"character": slug},
                                  require_worker=inp.worker or None), actor)
            out["native_job"] = j.model_dump() if hasattr(j, "model_dump") else j
        return out

    @app.post("/api/characters/blender/import")
    def chars_blender_import(inp: ImportIn, actor=Depends(auth)):
        """Import a model back from Blender (the picker / add-on): a `characters op=add` job on the control plane;
        poll /api/jobs/{id} (output.result: status, mode variant | derived | new, entry, roles, props)."""
        art = inp.artifact
        if inp.b64:
            art = store.put_artifact(base64.b64decode(inp.b64), f"{inp.name}.glb", "model/gltf-binary",
                                     {"by": actor, "from": "blender import"}).sha256
        if not (art or inp.from_clipboard):
            raise HTTPException(422, "give artifact, b64 or from_clipboard=true")
        j = submit(JobRequest(tool="characters", require_os="linux", input={
            "op": "add", "character": inp.name, "artifact": art, "from_clipboard": inp.from_clipboard and not art,
            "base": inp.base, "replace": inp.replace, "props": inp.props, "rig_roles": inp.rig_roles, "scale": inp.scale,
            "auto_rig": inp.auto_rig, "derived_ok": inp.derived_ok}), actor)
        return j
