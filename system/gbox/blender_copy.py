"""`blender_copy`: put a ripped game asset on Blender's own clipboard, so Ctrl+V in any Blender 3D viewport pastes it,
fully textured (meshes, materials, packed textures, armature).

Blender's copy/paste between instances goes through a file: Ctrl+C writes <temp>/copybuffer.blend and Ctrl+V reads it.
This tool imports the asset with headless Blender (the newest one installed), packs its textures and writes that file.

Sources: character=<collection slug> | environment=<slug> | artifact=<sha of a .glb/.gltf, e.g. a scene_capture> |
         path=<local .glb/.gltf>. nodes=[names]: only those objects (an Examine 3D selection: one node per draw call).
"""
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Unsupported, tool

SCRIPT = r'''
import sys, json, bpy
a = sys.argv[sys.argv.index("--") + 1:]
src, out, keep = a[0], a[1], set(json.loads(a[2]))
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = list(bpy.data.objects)
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
      "packed": sum(1 for i in bpy.data.images if i.packed_file)}))
'''


def find_blender() -> str:
    """Newest Blender on this machine: a running one first (what the operator has open), then common install places."""
    cands = []
    try:
        import psutil
        cands += [p.info["exe"] for p in psutil.process_iter(["name", "exe"]) if (p.info["name"] or "").lower() == "blender.exe"
                  and p.info["exe"]]
    except Exception:
        pass
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


def copybuffer_path() -> Path:
    """Where Blender's Ctrl+V reads from: <system temp>/copybuffer.blend (Blender's base temp dir)."""
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()) / "copybuffer.blend"


def to_blender(src: Path, nodes: list[str] | None = None) -> dict:
    exe = find_blender()
    out = copybuffer_path()
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "gbox_copybuffer.py"
        script.write_text(SCRIPT)
        r = subprocess.run([exe, "-b", "--factory-startup", "--python", str(script), "--", str(src), str(out),
                            __import__("json").dumps(nodes or [])], capture_output=True, text=True, timeout=300,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
    line = next((l for l in r.stdout.splitlines() if l.startswith("GBOX_RESULT ")), None)
    if not line:
        raise RuntimeError("Blender couldn't import the asset: " + (r.stdout + r.stderr)[-600:])
    res = __import__("json").loads(line[12:])
    if not res["objects"]:
        raise RuntimeError("nothing to copy (no matching objects)")
    return res | {"copybuffer": str(out), "blender": exe,
                  "next": "In Blender, hover the 3D viewport and press Ctrl+V: the asset pastes with its textures."}


def _fetch(ctx, url: str, suffix: str) -> Path:
    import httpx
    r = httpx.get(f"{ctx.server}{url}", headers=ctx.headers, timeout=300)
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
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


class CopyOut(BaseModel):
    result: dict


@tool("blender_copy", "1.0", CopyIn, CopyOut, capabilities=["assets"], permissions=[P.EXECUTE], timeout_s=400)
def blender_copy(inp: CopyIn, ctx):
    """Copy a ripped game asset to Blender's clipboard (copybuffer.blend): afterwards Ctrl+V in any Blender 3D viewport on
    this PC pastes it fully textured. Give character=<collection slug>, environment=<slug>, artifact=<scene_capture glb sha>
    or path=<.glb>; nodes=[...] keeps only those draw calls (an Examine 3D selection)."""
    if inp.mod:                                        # which collection character this mod was built from
        import httpx
        chars = httpx.get(f"{ctx.server}/api/characters", headers=ctx.headers, timeout=60).json()
        hit = next((c for c in chars for gid, ts in (c.get("targets") or {}).items()
                    for t in ts if t.get("mod") == inp.mod and (not inp.game_id or gid == inp.game_id)), None)
        if not hit:
            raise ValueError(f"mod {inp.mod!r} isn't a character swap gBox built from the collection")
        key = "sm64" if inp.mod.startswith("sm64_") else "re4gc" if inp.mod.startswith("re4_") else inp.mod.split("_")[0]
        fitted = next((f for f in (hit.get("target_files") or []) if f.startswith(f"targets/{key}") and f.endswith((".glb", ".gltf"))), None)
        src = _fetch(ctx, f"/api/characters/{hit['slug']}/file/{fitted}" if fitted else f"/api/characters/{hit['slug']}/model", ".glb")
    elif inp.path:
        src = Path(inp.path)
    elif inp.character:
        src = _fetch(ctx, f"/api/characters/{inp.character}/model", ".glb")
    elif inp.environment:
        import httpx
        meta = httpx.get(f"{ctx.server}/api/environments/{inp.environment}", headers=ctx.headers, timeout=60).json()
        src = _fetch(ctx, f"/api/environments/{inp.environment}/file/{meta['model']}", ".glb")
    elif inp.artifact:
        src = _fetch(ctx, f"/api/artifacts/{inp.artifact}", ".glb")
    else:
        raise ValueError("give character, environment, artifact or path")
    return {"result": to_blender(src, inp.nodes)}
