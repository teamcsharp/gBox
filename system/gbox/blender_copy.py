"""`blender_copy`: put a ripped game asset on Blender's own clipboard, so Ctrl+V in any Blender 3D viewport pastes it,
fully textured (meshes, materials, packed textures, armature).

Blender's copy/paste between instances goes through a file: Ctrl+C writes <temp base>/copybuffer.blend and Ctrl+V reads
it (view3d_copybuffer_filepath: BLI_path_join(BKE_tempdir_base(), "copybuffer.blend"), unchanged through 4.2+). The
temp base is Blender's Preferences > File Paths > Temporary Files directory when that is set and exists, else on Windows
the TEMP of Blender's own environment, else /tmp. This tool imports the asset with headless Blender (the running one
first, so the file is written by the same version: copybuffer files are version-sensitive), packs its textures and
writes that file to every place the operator's Blender may read it from (#1393: the gBox worker often runs under
another session or user than Blender, so its %TEMP% is not Blender's).

A character comes as the round-trip GLB (/api/characters/<slug>/blender, gbox.blender_roundtrip): the pasted armature
carries gbox_slug / gbox_base / gbox_roles, its bones gbox_role, attachments gbox_prop / gbox_bone, so the add-on's
"Send to gBox" after a Ctrl+V paste stores the edit back as a variant of that character.

Sources: character=<collection slug> | environment=<slug> | artifact=<sha of a .glb/.gltf, e.g. a scene_capture> |
         path=<local .glb/.gltf>. nodes=[names]: only those objects (an Examine 3D selection: one node per draw call).
"""
import glob
import base64
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel

from .models import Permission as P
from .registry import Unsupported, tool

COPYBUFFER = "copybuffer.blend"

SCRIPT = r'''
import sys, json, bpy
a = sys.argv[sys.argv.index("--") + 1:]
src, out, keep = a[0], a[1], set(json.loads(a[2]))
tags = json.loads(a[3]) if len(a) > 3 else {}
mode = a[4] if len(a) > 4 else "model"
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
if mode == "model":
    bpy.ops.import_scene.gltf(filepath=src)
else:
    im = bpy.data.images.load(src, check_existing=False)
    if mode == "movie_plane" and im.source != "MOVIE":
        raise ValueError("MP4 image plane requires a movie")
    width, height = im.size
    if not width or not height:
        raise ValueError("Blender could not decode the image")
    if mode == "image_empty":
        obj = bpy.data.objects.new("gBox image empty", None)
        bpy.context.scene.collection.objects.link(obj)
        obj.empty_display_type = "IMAGE"
        obj.data = im
        obj.empty_display_size = 2
        obj.empty_image_depth = "DEFAULT"
    else:
        bpy.ops.mesh.primitive_plane_add(size=2)
        obj = bpy.context.object
        obj.name = "gBox MP4 image plane" if mode == "movie_plane" else "gBox image plane"
        obj.scale.x = width / height
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        mat = bpy.data.materials.new(obj.name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes; nodes.clear()
        tex = nodes.new("ShaderNodeTexImage"); tex.image = im; tex.interpolation = "Closest"
        emission = nodes.new("ShaderNodeEmission")
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        output = nodes.new("ShaderNodeOutputMaterial")
        links = mat.node_tree.links
        links.new(tex.outputs["Color"], emission.inputs["Color"])
        links.new(tex.outputs["Alpha"], mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1]); links.new(emission.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs["Surface"])
        if hasattr(mat, "surface_render_method"): mat.surface_render_method = "DITHERED"
        elif hasattr(mat, "blend_method"): mat.blend_method = "BLEND"
        obj.data.materials.append(mat)
        if mode == "movie_plane":
            tex.image_user.frame_duration = im.frame_duration
            tex.image_user.frame_start = 1
            tex.image_user.use_auto_refresh = True
            tex.image_user.use_cyclic = True
    obj["gbox_paste_as"] = mode
objs = list(bpy.data.objects)
for o in objs:                                        # gBox round trip: role names on bones, the character on the armature
    if o.type == "ARMATURE" and tags.get("armature"):
        for k, v in tags["armature"].items():
            o[k] = v
        for b in o.data.bones:
            if tags.get("bones", {}).get(b.name):
                b["gbox_role"] = tags["bones"][b.name]
    for k, v in (tags.get("objects", {}).get(o.name) or {}).items():
        o[k] = v
if keep:                                              # an Examine 3D selection: just those draw calls (+ their parents)
    want = {o for o in objs if o.name in keep or any(o.name.startswith(k + ".") for k in keep)}
    for o in list(want):
        p = o.parent
        while p:
            want.add(p); p = p.parent
    for o in objs:
        if o not in want:
            bpy.data.objects.remove(o, do_unlink=True)
    objs = list(want)
packed = 0
for im in bpy.data.images:
    if not im.packed_file and im.source in ("FILE", "GENERATED") and im.has_data:
        try:
            im.pack(); packed += 1
        except Exception:
            pass
tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs if o.type == "MESH")
bpy.data.libraries.write(out, set(objs), fake_user=False, compress=False)
print("GBOX_RESULT " + json.dumps({"objects": len(objs), "meshes": sum(o.type == "MESH" for o in objs),
      "triangles": tris, "materials": len(bpy.data.materials), "images": len(bpy.data.images),
      "packed": sum(1 for i in bpy.data.images if i.packed_file), "version": bpy.app.version_string}))
'''

# Where this Blender reads its clipboard from. Run WITHOUT --factory-startup so the operator's saved preferences
# (Temporary Files directory) count; bpy.app.tempdir is the per-session folder inside the base, so its parent is the base.
PROBE = ('import bpy, json, os; t = bpy.app.tempdir; print("GBOX_TEMP " + json.dumps({"base": os.path.dirname(t.rstrip("/\\\\")), '
         '"pref": bpy.context.preferences.filepaths.temporary_directory, "version": bpy.app.version_string}))')

_NOWINDOW = 0x08000000 if sys.platform == "win32" else 0


def running_blenders() -> list[dict]:
    """Every blender.exe running on this PC: exe, pid, user and the TEMP of its own environment (same-user processes only;
    psutil cannot read another user's environment, so those come back without temp)."""
    out = []
    try:
        import psutil
    except Exception:
        return out
    try:
        procs = list(psutil.process_iter(["name", "exe", "pid"]))
    except Exception:
        return out
    for p in procs:
        try:
            info = p.info
            if (info.get("name") or "").lower() != "blender.exe" or not info.get("exe"):
                continue
            rec = {"exe": info["exe"], "pid": info.get("pid"), "user": "", "temp": "", "localappdata": "", "userprofile": ""}
            try:
                rec["user"] = p.username() or ""
            except Exception:
                pass
            try:
                env = p.environ()
                rec["temp"] = env.get("TEMP") or env.get("TMP") or ""
                rec["localappdata"] = env.get("LOCALAPPDATA") or ""
                rec["userprofile"] = env.get("USERPROFILE") or ""
            except Exception:
                pass
            out.append(rec)
        except Exception:
            continue
    return out


def find_blender() -> str:
    """Newest Blender on this machine: a running one first (what the operator has open), then common install places."""
    cands = [r["exe"] for r in running_blenders()]
    if cands:                                          # the Blender the operator has open: the paste target, same version
        return max(dict.fromkeys(cands), key=os.path.getmtime)
    home = Path.home()                                 # fixed depths: a recursive scan of build folders takes minutes
    for pat in [str(home / "Desktop" / "Blender Builds" / "Builds" / "*" / "*" / "blender.exe"),
                r"C:\Program Files\Blender Foundation\*\blender.exe",
                str(home / "AppData" / "Roaming" / "Blender Launcher" / "*" / "*" / "*" / "blender.exe")]:
        cands += glob.glob(pat)
    cands = [c for c in dict.fromkeys(cands) if c and os.path.isfile(c)]
    if not cands:
        raise Unsupported("no Blender found on this machine (install Blender, or open it once so gBox can find it)")
    return max(cands, key=os.path.getmtime)


def probe_tempdir(exe: str, timeout: int = 90) -> dict:
    """Ask a headless instance of this Blender (with the user's preferences) for its temp base and version. {} on failure."""
    try:
        r = subprocess.run([exe, "-b", "--python-expr", PROBE], capture_output=True, text=True, timeout=timeout,
                           creationflags=_NOWINDOW)
    except Exception:
        return {}
    line = next((l for l in (r.stdout or "").splitlines() if l.startswith("GBOX_TEMP ")), None)
    if not line:
        return {}
    try:
        return json.loads(line[10:])
    except Exception:
        return {}


def copybuffer_path() -> Path:
    """This worker's own default: <its TEMP>/copybuffer.blend (one of the candidates; the operator's Blender may differ)."""
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()) / COPYBUFFER


def _user_temp(user: str) -> str:
    """C:\\Users\\<name>\\AppData\\Local\\Temp for a DOMAIN\\name or name (the per-user TEMP Windows sets by default)."""
    name = (user or "").split("\\")[-1].split("@")[0].strip()
    if not name:
        return ""
    drive = os.environ.get("SystemDrive") or "C:"
    return str(Path(drive + os.sep) / "Users" / name / "AppData" / "Local" / "Temp")


def candidate_dirs(running: list[dict] | None = None, probe: dict | None = None, env: dict | None = None) -> list[Path]:
    """Every directory the operator's Blender may read copybuffer.blend from, most likely first, existing ones only:
    its preferences' Temporary Files dir, the temp base a headless instance computed, the TEMP of each running Blender
    and of its user's profile, then this worker's TEMP / TMP / LOCALAPPDATA\\Temp, then <SystemDrive>\\tmp (Blender's
    fallback when TEMP is unusable)."""
    env = os.environ if env is None else env
    running = running_blenders() if running is None else running
    probe = probe or {}
    raw: list[str] = [probe.get("pref") or "", probe.get("base") or ""]
    for r in running:
        raw += [r.get("temp") or "", (str(Path(r["localappdata"]) / "Temp") if r.get("localappdata") else ""),
                (str(Path(r["userprofile"]) / "AppData" / "Local" / "Temp") if r.get("userprofile") else ""),
                _user_temp(r.get("user") or "")]
    raw += [env.get("TEMP") or "", env.get("TMP") or "", tempfile.gettempdir(),
            (str(Path(env["LOCALAPPDATA"]) / "Temp") if env.get("LOCALAPPDATA") else ""),
            (str(Path(env["USERPROFILE"]) / "AppData" / "Local" / "Temp") if env.get("USERPROFILE") else ""),
            str(Path((env.get("SystemDrive") or "C:") + os.sep) / "tmp")]
    out: list[Path] = []
    seen: set[str] = set()
    for d in raw:
        if not d:
            continue
        p = Path(d)
        key = os.path.normcase(os.path.normpath(str(p)))
        if key in seen or not p.is_dir():
            continue
        seen.add(key)
        out.append(p)
    return out


def write_everywhere(staged: Path, dirs: list[Path]) -> tuple[list[str], dict[str, str]]:
    """Copy the staged copybuffer into every candidate dir: (written paths, {dir: why not})."""
    written, skipped = [], {}
    for d in dirs:
        dest = d / COPYBUFFER
        try:
            shutil.copyfile(staged, dest)
            written.append(str(dest))
        except Exception as e:                         # another user's temp we cannot write, a read-only dir, ...
            skipped[str(d)] = f"{type(e).__name__}: {e}"
    return written, skipped


def gbox_tags(src: Path) -> dict:
    """The gBox metadata a round-trip GLB carries (gbox.blender_roundtrip.tag), as Blender custom properties to set
    after the import: {armature: {gbox_slug, gbox_base, gbox_name, gbox_roles}, bones: {bone: role},
    objects: {node: {gbox_prop, gbox_bone, gbox_part}}}. {} for a file without them."""
    from . import attachments
    try:
        gl, _ = attachments.read_gltf(Path(src))
    except Exception:                                  # noqa: BLE001 - not a glTF we can read: nothing to tag
        return {}
    g = next((sc.get("extras", {}).get("gbox") for sc in gl.get("scenes") or []
              if isinstance(sc.get("extras"), dict) and isinstance(sc["extras"].get("gbox"), dict)), None)
    nodes = gl.get("nodes") or []
    bones = {n.get("name"): attachments.extras(n)["gbox_role"] for n in nodes if attachments.extras(n).get("gbox_role")}
    objs = {n.get("name"): {k: v for k, v in attachments.extras(n).items() if k in ("gbox_prop", "gbox_bone", "gbox_part")}
            for n in nodes if "mesh" in n and any(k in attachments.extras(n) for k in ("gbox_prop", "gbox_bone", "gbox_part"))}
    if not (g or bones or objs):
        return {}
    arm = {}
    if g:
        arm = {"gbox_slug": g.get("slug") or "", "gbox_base": g.get("base") or g.get("slug") or "",
               "gbox_name": g.get("name") or "", "gbox_roles": json.dumps(g.get("roles") or {})}
    return {"armature": arm, "bones": bones, "objects": objs}


def to_blender(src: Path, nodes: list[str] | None = None, paste_as: str = "model") -> dict:
    exe = find_blender()
    tags = gbox_tags(src) if paste_as == "model" else {}
    running = running_blenders()
    probe = probe_tempdir(exe)
    dirs = candidate_dirs(running, probe)
    with tempfile.TemporaryDirectory() as td:
        script, staged = Path(td) / "gbox_copybuffer.py", Path(td) / COPYBUFFER
        script.write_text(SCRIPT)
        r = subprocess.run([exe, "-b", "--factory-startup", "--python", str(script), "--", str(src), str(staged),
                            json.dumps(nodes or []), json.dumps(tags), paste_as], capture_output=True, text=True, timeout=300, creationflags=_NOWINDOW)
        line = next((l for l in r.stdout.splitlines() if l.startswith("GBOX_RESULT ")), None)
        if not line:
            raise RuntimeError("Blender couldn't import the asset: " + (r.stdout + r.stderr)[-600:])
        res = json.loads(line[12:])
        if not res["objects"]:
            raise RuntimeError("nothing to copy (no matching objects)")
        if not staged.is_file():
            raise RuntimeError("Blender imported the asset but wrote no copybuffer.blend")
        written, skipped = write_everywhere(staged, dirs)
    if not written:
        raise RuntimeError("the clipboard file could not be written anywhere: " +
                           ("; ".join(f"{d}: {why}" for d, why in skipped.items()) or "no temp directory exists on this PC"))
    version = res.pop("version", "") or probe.get("version", "")
    host = platform.node()
    return res | {"copybuffer": written[0], "copybuffers": written, "skipped": skipped, "blender": exe,
                  "gbox": {"character": (tags.get("armature") or {}).get("gbox_slug", ""), "roles": len(tags.get("bones") or {}),
                           "props": sorted(k for k, v in (tags.get("objects") or {}).items() if v.get("gbox_prop"))},
                  "blender_version": version, "blender_tempdir": probe.get("base", ""), "blender_pref_tempdir": probe.get("pref", ""),
                  "running": [x["exe"] for x in running], "host": host, "paste_as": paste_as,
                  "next": f"In Blender on {host}, hover the 3D viewport and press Ctrl+V: the asset pastes with its textures."}


def _fetch(ctx, url: str, suffix: str) -> Path:
    import httpx
    r = httpx.get(f"{ctx.server}{url}", headers=ctx.headers, timeout=300)
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if suffix in (".glb", ".gltf"):
        suffix = ".gltf" if (r.content[:1] == b"{" or "json" in ct) else ".glb"
    f = Path(tempfile.mkdtemp(prefix="gbox-bl-")) / ("asset" + suffix)
    f.write_bytes(r.content)
    return f


class CopyIn(BaseModel):
    character: str = ""         # collection slug
    environment: str = ""       # environments slug
    artifact: str = ""          # sha256 of a .glb/.gltf artifact (scene_capture output)
    path: str = ""              # a local .glb/.gltf on this machine
    nodes: list[str] = []       # only these objects (Examine 3D draw-call node names)
    mod: str = ""               # a built swap mod (e.g. sm64_cloud, re4_aya): copies the character fitted to that game
    game_id: str = ""           # with mod
    asset_url: str = ""         # same-control-plane asset file (never an arbitrary URL)
    image_b64: str = ""         # current sprite frame / image, PNG encoded by the client
    paste_as: Literal["model", "image_plane", "image_empty", "movie_plane"] = "model"


class CopyOut(BaseModel):
    result: dict


def asset_source(url: str) -> str:
    """Only authenticated file endpoints. Never forward the worker token to a supplied host or query."""
    import re
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in path or any(p in (".", "..") for p in path.split("/")):
        raise ValueError("asset_url must be a gBox asset API path without credentials or query parameters")
    if not re.fullmatch(r"/api/(?:assets/[^/]+/file|artifacts/[0-9a-f]{64}|characters/[^/]+/(?:model|preview|file/.+)|environments/[^/]+/file/.+)", path):
        raise ValueError("asset_url is not a supported asset file endpoint")
    return parsed.path


def prepare_image(src: Path, paste_as: str, media_dir: Path) -> Path:
    """Pack still PNGs into copybuffer; keep movies at a stable content-addressed path (Blender cannot pack them)."""
    from PIL import Image
    data = src.read_bytes()
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("clipboard media exceeds 64 MB")
    if paste_as == "movie_plane":
        if len(data) < 12 or data[4:8] != b"ftyp":
            raise ValueError("MP4 image plane requires an MP4 file; select an animation with an MP4 export")
        suffix = ".mp4"
    else:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 16000000:
                raise ValueError("image exceeds 16 megapixels")
            im.seek(0)
            out = io.BytesIO(); im.convert("RGBA").save(out, format="PNG"); data = out.getvalue()
        suffix = ".png"
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = media_dir.resolve() / (hashlib.sha256(data).hexdigest() + suffix)
    if not dest.exists():
        dest.write_bytes(data)
    return dest


@tool("blender_copy", "1.0", CopyIn, CopyOut, capabilities=["assets"], permissions=[P.EXECUTE], timeout_s=400)
def blender_copy(inp: CopyIn, ctx):
    """Copy a ripped game asset to Blender's clipboard (copybuffer.blend, written to every temp dir the operator's Blender
    may read): afterwards Ctrl+V in any Blender 3D viewport on this PC pastes it fully textured. Give character=<collection
    slug>, environment=<slug>, artifact=<scene_capture glb sha> or path=<.glb>; nodes=[...] keeps only those draw calls
    (an Examine 3D selection). The result lists the files written (copybuffers) and the source (an API path the client can
    show as a preview)."""
    if inp.image_b64:
        if inp.paste_as not in ("image_plane", "image_empty"):
            raise ValueError("image_b64 requires image_plane or image_empty")
        if len(inp.image_b64) > 24 * 1024 * 1024:
            raise ValueError("clipboard image is too large")
        data = base64.b64decode(inp.image_b64, validate=True)
        src = Path(tempfile.mkdtemp(prefix="gbox-bl-")) / "image.png"
        src.write_bytes(data); source = ""
    elif inp.asset_url:
        source = asset_source(inp.asset_url)
        if inp.paste_as == "model" and source.startswith("/api/assets/"):
            # The library bundles a .gltf's companion buffers/images into the artifact.
            import httpx
            reply = httpx.post(f"{ctx.server}{source[:-5]}/copy", headers=ctx.headers, json={}, timeout=300)
            reply.raise_for_status()
            digest = reply.json().get("sha256", "")
            source = asset_source("/api/artifacts/" + digest)
        src = _fetch(ctx, source, ".mp4" if inp.paste_as == "movie_plane" else ".image" if inp.paste_as != "model" else ".glb")
    elif inp.mod:                                        # which collection character this mod was built from
        import httpx
        chars = httpx.get(f"{ctx.server}/api/characters", headers=ctx.headers, timeout=60).json()
        hit = next((c for c in chars for gid, ts in (c.get("targets") or {}).items()
                    for t in ts if t.get("mod") == inp.mod and (not inp.game_id or gid == inp.game_id)), None)
        if not hit:
            raise ValueError(f"mod {inp.mod!r} isn't a character swap gBox built from the collection")
        key = "sm64" if inp.mod.startswith("sm64_") else "re4gc" if inp.mod.startswith("re4_") else inp.mod.split("_")[0]
        fitted = next((f for f in (hit.get("target_files") or []) if f.startswith(f"targets/{key}") and f.endswith((".glb", ".gltf"))), None)
        source = f"/api/characters/{hit['slug']}/file/{fitted}" if fitted else f"/api/characters/{hit['slug']}/model"
        src = _fetch(ctx, source, ".glb")
    elif inp.path:
        source = inp.path
        src = Path(inp.path)
    elif inp.character:                                # the round-trip GLB: rig role names + props ride along
        source = f"/api/characters/{inp.character}/blender"
        try:
            src = _fetch(ctx, source, ".glb")
        except Exception:                              # noqa: BLE001 - an older control plane: the plain model
            source = f"/api/characters/{inp.character}/model"
            src = _fetch(ctx, source, ".glb")
    elif inp.environment:
        import httpx
        meta = httpx.get(f"{ctx.server}/api/environments/{inp.environment}", headers=ctx.headers, timeout=60).json()
        source = f"/api/environments/{inp.environment}/file/{meta['model']}"
        src = _fetch(ctx, source, ".glb")
    elif inp.artifact:
        source = f"/api/artifacts/{inp.artifact}"
        src = _fetch(ctx, source, ".glb")
    else:
        raise ValueError("give character, environment, artifact or path")
    if inp.paste_as != "model":
        downloaded = src
        try:
            src = prepare_image(src, inp.paste_as, Path(ctx.config.data_dir) / "blender-media")
        finally:
            if (inp.image_b64 or inp.asset_url) and downloaded.parent.name.startswith("gbox-bl-"):
                shutil.rmtree(downloaded.parent)
        return {"result": to_blender(src, inp.nodes, inp.paste_as) | {"source": source, "media_path": str(src)}}
    return {"result": to_blender(src, inp.nodes) | {"source": source}}
