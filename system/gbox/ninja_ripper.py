"""NinjaRipper as gBox tools (#443): find it, run an agent-owned PC game/emulator with it inside, press its rip hotkey,
list what it wrote, and convert .rip files into one GLB that `characters op=add artifact=<sha>` stores in the collection.

RenderDoc ripping (gbox.frame_rip, gbox.scene_capture) and Ghidra stay the main routes; NinjaRipper is the fallback for
PC games and emulators whose draws RenderDoc can't replay, and it rips the input vertex buffers (pre-transform meshes).

Install: NinjaRipper is closed-source freeware and is never downloaded by gBox. Unpack it on the PC worker (default
search: C:/_tools, Program Files, the user's Desktop/Downloads/Documents/tools, <runtime>/tools) or set
[ninja_ripper] path in gbox.toml. Other [ninja_ripper] keys:
    dll            the intercept DLL to load into the target (64-bit). Default: the one DLL in the install whose name has
                   "ninja" / "ripper" / "intercept" and isn't a d3d*/dxgi*/opengl32 proxy.
    launcher_args  mode=launcher: argv for NinjaRipper's own launcher, placeholders {launcher} {exe} {args} {cwd} {out}
    hotkey         rip hotkey pressed by op=rip (default F10, NinjaRipper's "rip frame" key)
    output_dir     where NinjaRipper writes rips (default: searched under the install and the user's Documents)

Rules (gbox.background_testing): launch / attach / rip / stop run only as agent jobs (agent_use) on a PC that is ticked
for background testing; attach and session rips only touch sessions an agent started (tray label owner=agent or an
agent_use launch job, never owner=you); pid rips and stop only touch processes this tool launched itself.

.rip format (NinjaRipper 1.x, version 4; as documented by the community importers for Blender and Noesis), little endian:
    u32 magic 0xDEADC0DE, u32 version 4, u32 faces, u32 vertices, u32 vertex_size, u32 textures, u32 shaders, u32 attrs
    attrs x { cstr semantic, u32 semantic_index, u32 offset, u32 size, u32 n, u32 type[n] (0 float, 1 uint, 2 int) }
    textures x cstr (file names next to the .rip), shaders x cstr
    faces x 3 u32 indices, then vertices x vertex_size bytes (every element 4 bytes at offset + 4*k)
NinjaRipper 2.x writes .nr containers instead; those are listed but not converted.

CLI:  python -m gbox.ninja_ripper find
      python -m gbox.ninja_ripper list [--root DIR]
      python -m gbox.ninja_ripper glb <folder or .rip> --out model.glb [--select "*.rip"] [--keep-d3d]
"""
from __future__ import annotations

import fnmatch
import io
import json
import math
import os
import struct
import subprocess
import sys
import time
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Ctx, ToolUnavailable, Unsupported, tool

RIP_MAGIC = 0xDEADC0DE
RIP_VERSION = 4
RIP_EXT = {".rip", ".nr"}
TEX_EXT = {".dds", ".png", ".tga", ".bmp", ".jpg", ".jpeg"}
DEFAULT_HOTKEY = "F10"

# parser bounds: a corrupt or hostile header can't make gBox allocate or loop beyond these
MAX_VERTICES = 1 << 24
MAX_FACES = 1 << 24
MAX_STRIDE = 4096
MAX_ATTRS = 64
MAX_ELEMENTS = 16
MAX_NAMES = 256
MAX_STR = 1024
# import bounds (one GLB)
MAX_IMPORT_VERTICES = 16_000_000
MAX_TEXTURE_FILE = 64 << 20
MAX_TEXTURE_TOTAL = 512 << 20


class RipError(ValueError):
    """The bytes are not a valid NinjaRipper .rip (v4) file."""


@dataclass
class RipAttr:
    semantic: str
    index: int
    offset: int
    size: int
    types: list[int]


@dataclass
class Rip:
    version: int
    vertex_count: int
    stride: int
    attrs: list[RipAttr]
    textures: list[str]
    shaders: list[str]
    indices: array                       # u32, faces * 3
    vertices: bytes                      # vertex_count * stride
    notes: list[str] = field(default_factory=list)

    @property
    def face_count(self) -> int:
        return len(self.indices) // 3

    def attr(self, semantic: str, index: int = 0) -> RipAttr | None:
        s = semantic.upper()
        return next((a for a in self.attrs if a.semantic.upper() == s and a.index == index), None)


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.pos = memoryview(data), 0

    def need(self, n: int, what: str):
        if n < 0 or self.pos + n > len(self.d):
            raise RipError(f"truncated .rip: {what} needs {n} bytes at offset {self.pos}, file has {len(self.d)}")

    def u32s(self, n: int, what: str) -> tuple:
        self.need(4 * n, what)
        v = struct.unpack_from(f"<{n}I", self.d, self.pos)
        self.pos += 4 * n
        return v

    def cstr(self, what: str) -> str:
        end = min(len(self.d), self.pos + MAX_STR + 1)
        chunk = bytes(self.d[self.pos:end])
        z = chunk.find(b"\0")
        if z < 0:
            raise RipError(f"{what}: unterminated or longer than {MAX_STR} bytes at offset {self.pos}")
        self.pos += z + 1
        return chunk[:z].decode("utf-8", "replace")

    def take(self, n: int, what: str) -> bytes:
        self.need(n, what)
        b = bytes(self.d[self.pos:self.pos + n])
        self.pos += n
        return b


def parse_rip(data: bytes) -> Rip:
    """Parse one NinjaRipper .rip (v4). Every count, offset and length is checked against the file and the bounds above."""
    r = _Reader(data)
    magic, version = r.u32s(2, "header")
    if magic != RIP_MAGIC:
        raise RipError(f"not a NinjaRipper .rip file (magic 0x{magic:08X}, expected 0x{RIP_MAGIC:08X})")
    if version != RIP_VERSION:
        raise RipError(f"unsupported .rip version {version} (this reader handles version {RIP_VERSION}, NinjaRipper 1.x)")
    faces, verts, stride, ntex, nshader, nattr = r.u32s(6, "header counts")
    if faces > MAX_FACES or verts > MAX_VERTICES:
        raise RipError(f"{faces} faces / {verts} vertices exceed the reader's bounds")
    if stride == 0 and verts:
        raise RipError("vertex size is 0")
    if stride > MAX_STRIDE or nattr > MAX_ATTRS or ntex > MAX_NAMES or nshader > MAX_NAMES:
        raise RipError(f"header out of bounds (vertex size {stride}, {nattr} attributes, {ntex} textures, {nshader} shaders)")
    attrs = []
    for i in range(nattr):
        sem = r.cstr(f"attribute {i} semantic")
        idx, off, size, n = r.u32s(4, f"attribute {i}")
        if n > MAX_ELEMENTS:
            raise RipError(f"attribute {sem}{idx}: {n} elements")
        types = list(r.u32s(n, f"attribute {sem}{idx} types"))
        if any(t not in (0, 1, 2) for t in types):
            raise RipError(f"attribute {sem}{idx}: unknown element type in {types}")
        if size < 4 * n or off + 4 * n > stride or off + size > stride:
            raise RipError(f"attribute {sem}{idx}: offset {off} size {size} ({n} elements) outside the {stride}-byte vertex")
        attrs.append(RipAttr(sem, idx, off, size, types))
    textures = [r.cstr(f"texture name {i}") for i in range(ntex)]
    shaders = [r.cstr(f"shader name {i}") for i in range(nshader)]
    indices = array("I")
    indices.frombytes(r.take(12 * faces, "index buffer"))
    if sys.byteorder == "big":
        indices.byteswap()
    vertices = r.take(verts * stride, "vertex buffer")
    rip = Rip(version, verts, stride, attrs, textures, shaders, indices, vertices)
    if r.pos != len(data):
        rip.notes.append(f"{len(data) - r.pos} trailing bytes ignored")
    return rip


def _values(rip: Rip, a: RipAttr, n: int) -> list[tuple]:
    """The first n elements of attribute a for every vertex (floats stay floats, ints stay ints)."""
    fmt = "<" + "".join("fIi"[t] for t in a.types[:n])
    s, v, off = struct.Struct(fmt), rip.vertices, a.offset
    return [s.unpack_from(v, i * rip.stride + off) for i in range(rip.vertex_count)]


def _float_attr(rip: Rip, names: tuple[str, ...], n: int) -> RipAttr | None:
    for name in names:
        a = rip.attr(name, 0)
        if a and len(a.types) >= n and all(t == 0 for t in a.types[:n]):
            return a
    return None


def _finite(x: float) -> float:
    return x if math.isfinite(x) else 0.0


def mesh_from_rip(rip: Rip, d3d_to_gltf: bool = True) -> dict:
    """Rip -> positions / normals / uvs / colours / triangles for glTF. D3D is left-handed: by default Z is negated and the
    winding reversed so the mesh faces the same way in glTF (right-handed, Y up)."""
    pa = _float_attr(rip, ("POSITION", "SV_POSITION"), 3) or next(
        (a for a in rip.attrs if len(a.types) >= 3 and all(t == 0 for t in a.types[:3])), None)
    if pa is None:
        raise RipError("no float POSITION attribute")
    zs = -1.0 if d3d_to_gltf else 1.0
    nonfinite = 0
    pos = array("f")
    for x, y, z in _values(rip, pa, 3):
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            nonfinite += 1
        pos.extend((_finite(x), _finite(y), _finite(z) * zs))
    nrm = None
    if na := _float_attr(rip, ("NORMAL",), 3):
        nrm = array("f")
        for x, y, z in _values(rip, na, 3):
            x, y, z = _finite(x), _finite(y), _finite(z) * zs
            ln = math.sqrt(x * x + y * y + z * z)
            nrm.extend((x / ln, y / ln, z / ln) if ln > 1e-12 else (0.0, 0.0, 1.0))
    uv = None
    if ta := _float_attr(rip, ("TEXCOORD",), 2):
        uv = array("f")
        for u, v in _values(rip, ta, 2):
            uv.extend((_finite(u), _finite(v)))
    col = None
    if ca := _float_attr(rip, ("COLOR",), 3):
        col = array("f")
        n = 4 if len(ca.types) >= 4 and ca.types[3] == 0 else 3
        for c in _values(rip, ca, n):
            c = [min(1.0, max(0.0, _finite(x))) for x in c] + [1.0] * (4 - n)
            col.extend(c)
    tris, dropped, nv = array("I"), 0, rip.vertex_count
    ix = rip.indices
    for i in range(0, len(ix) - 2, 3):
        a, b, c = ix[i], ix[i + 1], ix[i + 2]
        if a >= nv or b >= nv or c >= nv:
            dropped += 1
            continue
        tris.extend((a, c, b) if d3d_to_gltf else (a, b, c))
    return {"pos": pos, "nrm": nrm, "uv": uv, "col": col, "tris": tris, "dropped_faces": dropped,
            "nonfinite_positions": nonfinite, "texture": next((_basename(t) for t in rip.textures if _basename(t)), None)}


def _basename(name: str) -> str:
    """A texture reference -> a file name inside the rip's own folder (never a path out of it)."""
    b = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return "" if b in (".", "..") else b


# ------------------------------------------------------------------------------------------------ GLB writer (stdlib)

class _Glb:
    def __init__(self, generator: str):
        self.bin = bytearray()
        self.gl = {"asset": {"version": "2.0", "generator": generator}, "scene": 0, "scenes": [{"nodes": []}],
                   "nodes": [], "meshes": [], "accessors": [], "bufferViews": [], "materials": [], "textures": [],
                   "images": [], "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]}
        self.tex_index: dict[str, int] = {}

    def view(self, data: bytes, target: int | None = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.gl["bufferViews"].append(v)
        return len(self.gl["bufferViews"]) - 1

    def accessor(self, arr: array, ctype: int, kind: str, count: int, target: int, minmax: bool = False) -> int:
        a = array(arr.typecode, arr)
        if sys.byteorder == "big":
            a.byteswap()
        acc = {"bufferView": self.view(a.tobytes(), target), "componentType": ctype, "count": count, "type": kind}
        if minmax:
            k = {"VEC3": 3, "VEC2": 2, "VEC4": 4, "SCALAR": 1}[kind]
            acc["min"] = [min(arr[j::k]) for j in range(k)]
            acc["max"] = [max(arr[j::k]) for j in range(k)]
        self.gl["accessors"].append(acc)
        return len(self.gl["accessors"]) - 1

    def material(self, name: str, image: tuple[bytes, str] | None, key: str | None) -> int:
        m = {"name": name, "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0}, "doubleSided": True}
        if image and key:
            if key not in self.tex_index:
                data, mime = image
                self.gl["images"].append({"name": key, "mimeType": mime, "bufferView": self.view(data)})
                self.gl["textures"].append({"sampler": 0, "source": len(self.gl["images"]) - 1})
                self.tex_index[key] = len(self.gl["textures"]) - 1
            m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": self.tex_index[key]}
        self.gl["materials"].append(m)
        return len(self.gl["materials"]) - 1

    def mesh(self, name: str, m: dict, material: int, extras: dict) -> None:
        nv = len(m["pos"]) // 3
        attrs = {"POSITION": self.accessor(m["pos"], 5126, "VEC3", nv, 34962, minmax=True)}
        if m["nrm"] is not None:
            attrs["NORMAL"] = self.accessor(m["nrm"], 5126, "VEC3", nv, 34962)
        if m["uv"] is not None:
            attrs["TEXCOORD_0"] = self.accessor(m["uv"], 5126, "VEC2", nv, 34962)
        if m["col"] is not None:
            attrs["COLOR_0"] = self.accessor(m["col"], 5126, "VEC4", nv, 34962)
        idx = self.accessor(m["tris"], 5125, "SCALAR", len(m["tris"]), 34963)
        self.gl["meshes"].append({"name": name, "primitives": [{"attributes": attrs, "indices": idx, "material": material}]})
        self.gl["nodes"].append({"name": name, "mesh": len(self.gl["meshes"]) - 1, "extras": extras})
        self.gl["scenes"][0]["nodes"].append(len(self.gl["nodes"]) - 1)

    def bytes(self) -> bytes:
        gl = {k: v for k, v in self.gl.items() if v != [] and not (k == "samplers" and not self.gl["textures"])}
        while len(self.bin) % 4:
            self.bin.append(0)
        gl["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(gl, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
                + struct.pack("<I4s", len(self.bin), b"BIN\0") + bytes(self.bin))


def texture_image(path: Path) -> tuple[tuple[bytes, str] | None, str | None]:
    """A texture next to the .rip -> (image bytes, mime) for the GLB, or (None, why). DDS/TGA/BMP go through Pillow."""
    try:
        if not path.is_file():
            return None, "missing"
        if path.stat().st_size > MAX_TEXTURE_FILE:
            return None, "larger than the per-texture bound"
        ext = path.suffix.lower()
        if ext == ".png":
            return (path.read_bytes(), "image/png"), None
        if ext in (".jpg", ".jpeg"):
            return (path.read_bytes(), "image/jpeg"), None
        try:
            from PIL import Image
        except ImportError:
            return None, "Pillow is not installed (needed for .dds/.tga/.bmp)"
        with Image.open(path) as im:
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, "PNG")
        return (buf.getvalue(), "image/png"), None
    except Exception as e:                                  # noqa: BLE001 - one bad texture never fails the import
        return None, f"{type(e).__name__}: {e}"


def rip_files(path: Path, select: str = "*.rip", max_files: int = 2000) -> list[Path]:
    path = Path(path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"no rip folder or file at {path}")
    files = sorted(p for p in path.iterdir() if p.is_file() and fnmatch.fnmatch(p.name.lower(), select.lower()))
    return files[:max(1, max_files)]


def rips_to_glb(files: list[Path], d3d_to_gltf: bool = True, textures: bool = True, name: str = "ninja_rip") -> tuple[bytes, dict]:
    """Convert .rip files (one mesh node each) into one GLB. Bad files are skipped and reported, never fatal."""
    g = _Glb("gbox ninja_ripper (.rip v4 -> glTF)")
    summary = {"files": len(files), "meshes": 0, "vertices": 0, "triangles": 0, "textures": 0, "skipped": [],
               "missing_textures": {}, "dropped_faces": 0, "notes": []}
    tex_bytes, images = 0, {}
    for f in files:
        try:
            if f.suffix.lower() == ".nr":
                raise RipError("NinjaRipper 2.x .nr container: not convertible by this reader")
            rip = parse_rip(f.read_bytes())
            m = mesh_from_rip(rip, d3d_to_gltf)
        except (RipError, OSError) as e:
            summary["skipped"].append({"file": f.name, "reason": str(e)})
            continue
        nv, nt = len(m["pos"]) // 3, len(m["tris"]) // 3
        if not nt:
            summary["skipped"].append({"file": f.name, "reason": "no triangles with valid indices"})
            continue
        if summary["vertices"] + nv > MAX_IMPORT_VERTICES:
            summary["skipped"].append({"file": f.name, "reason": "import vertex bound reached"})
            continue
        image, key = None, m["texture"]
        if textures and key:
            if key not in images:
                img, why = texture_image(f.parent / key)
                if img and tex_bytes + len(img[0]) > MAX_TEXTURE_TOTAL:
                    img, why = None, "import texture bound reached"
                images[key] = img
                if img:
                    tex_bytes += len(img[0])
                else:
                    summary["missing_textures"][key] = why
            image = images[key]
        mat = g.material(f.stem, image, key if image else None)
        g.mesh(f.stem, m, mat, {"rip": f.name, "textures": rip.textures, "shaders": rip.shaders,
                                "attributes": [f"{a.semantic}{a.index}" for a in rip.attrs]})
        summary["meshes"] += 1
        summary["vertices"] += nv
        summary["triangles"] += nt
        summary["dropped_faces"] += m["dropped_faces"]
        if m["nonfinite_positions"]:
            summary["notes"].append(f"{f.name}: {m['nonfinite_positions']} non-finite positions set to 0")
    summary["textures"] = len(g.gl["images"])
    if not summary["meshes"]:
        raise RipError("no convertible .rip mesh: " + "; ".join(f"{s['file']}: {s['reason']}" for s in summary["skipped"][:5]))
    g.gl["scenes"][0]["name"] = name
    return g.bytes(), summary


# ------------------------------------------------------------------------------------------------ install discovery

_FOUND: dict = {}


def _ncfg(cfg) -> dict:
    return dict(getattr(cfg, "ninja_ripper", None) or {})


def search_roots(cfg) -> list[Path]:
    home = Path.home()
    roots = [Path("C:/_tools"), Path("C:/Program Files"), Path("C:/Program Files (x86)"), home / "Desktop",
             home / "Downloads", home / "Documents", home / "tools"]
    try:
        roots.append(Path(cfg.runtime) / "tools")
    except Exception:                                       # noqa: BLE001
        pass
    return [r for r in roots if r.is_dir()]


def pe_machine(path: Path) -> str | None:
    """x64 / x86 / arm64 from a PE header (None if not a PE)."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        if head[:2] != b"MZ":
            return None
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        if pe + 6 > len(head) or head[pe:pe + 4] != b"PE\0\0":
            return None
        return {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(struct.unpack_from("<H", head, pe + 4)[0])
    except (OSError, struct.error):
        return None


def _launcher_in(d: Path, depth: int = 2) -> Path | None:
    for k in range(depth + 1):
        pat = "/".join(["*"] * k + ["NinjaRipper*.exe"])
        hits = sorted(p for p in d.glob(pat) if p.is_file() and "uninst" not in p.name.lower())
        if hits:
            return hits[0]
    return None


def _dlls(home: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for k in range(3):
        for p in home.glob("/".join(["*"] * k + ["*.dll"])):
            n = p.name.lower()
            if n.startswith(("d3d", "dxgi", "opengl32", "vulkan", "msvc", "vcruntime", "ucrt", "api-ms")):
                continue
            if any(w in n for w in ("ninja", "ripper", "intercept")):
                out.setdefault(pe_machine(p) or "unknown", []).append(str(p))
    return out


def find_install(cfg, refresh: bool = False) -> dict | None:
    """Where NinjaRipper is on this PC: config [ninja_ripper] path, env NINJA_RIPPER_HOME, then the search roots.
    Cached for a minute (the worker asks on every heartbeat)."""
    nc = _ncfg(cfg)
    key = (str(nc.get("path") or ""), os.environ.get("NINJA_RIPPER_HOME", ""))
    hit = _FOUND.get(key)
    if hit and not refresh and time.time() - hit[0] < 60:
        return hit[1]
    found = None
    for src, p in (("config", nc.get("path")), ("env", os.environ.get("NINJA_RIPPER_HOME"))):
        if not p:
            continue
        p = Path(os.path.expandvars(str(p)))
        exe = p if p.is_file() else _launcher_in(p) if p.is_dir() else None
        if exe or p.is_dir():
            found = {"home": str(exe.parent if exe else p), "launcher": str(exe) if exe else None, "source": src}
            break
    if not found:
        for root in search_roots(cfg):          # root/NinjaRipper.exe, root/*/NinjaRipper.exe, root/*ninja*/*/*/NinjaRipper.exe
            for d in [root] + sorted(x for x in root.glob("*") if x.is_dir() and "ninja" in x.name.lower()):
                exe = _launcher_in(d, depth=1 if d == root else 2)
                if exe:
                    found = {"home": str(exe.parent), "launcher": str(exe), "source": f"search {root}"}
                    break
            if found:
                break
    if found:
        found["dlls"] = _dlls(Path(found["home"]))
        if nc.get("dll"):
            found["dll"] = str(nc["dll"])
    _FOUND[key] = (time.time(), found)
    return found


def check(cfg) -> str | None:
    """Registry check hook: the reason ninja_ripper can't run on this PC, or None."""
    if sys.platform != "win32":
        return "NinjaRipper runs on a Windows PC worker"
    if find_install(cfg):
        return None
    return ("NinjaRipper is not installed on this PC. gBox never downloads it: unpack NinjaRipper into C:/_tools/NinjaRipper "
            "(or set [ninja_ripper] path = \"<folder>\" in gbox.toml) and restart the worker. RenderDoc ripping "
            "(characters op=extract, scene_capture) works without it.")


def output_roots(cfg, inst: dict | None) -> list[Path]:
    nc, home = _ncfg(cfg), Path.home()
    c = [Path(os.path.expandvars(str(nc["output_dir"])))] if nc.get("output_dir") else []
    if inst:
        h = Path(inst["home"])
        c += [h / "_NinjaRipper", h / "output", h / "Output", h / "rips"]
    c += [home / "Documents" / "NinjaRipper", home / "Documents" / "_NinjaRipper"]
    try:
        c.append(Path(cfg.runtime) / "ninja_ripper" / "out")
    except Exception:                                       # noqa: BLE001
        pass
    seen, out = set(), []
    for p in c:
        if p.is_dir() and str(p).lower() not in seen:
            seen.add(str(p).lower())
            out.append(p)
    return out


def _walk_rip_dirs(root: Path, max_depth: int = 3, max_dirs: int = 5000):
    stack, n = [(root, 0)], 0
    while stack and n < max_dirs:
        d, depth = stack.pop()
        n += 1
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        files = [e for e in entries if e.is_file() and Path(e.name).suffix.lower() in RIP_EXT | TEX_EXT]
        if any(Path(e.name).suffix.lower() in RIP_EXT for e in files):
            yield Path(d), files
        if depth < max_depth:
            stack += [(Path(e.path), depth + 1) for e in entries if e.is_dir()]


def list_rips(roots: list[Path], limit: int = 20) -> list[dict]:
    """Rip sets (folders holding .rip / .nr files) under the output roots, newest first."""
    sets = []
    for root in roots:
        for d, files in _walk_rip_dirs(root):
            st = [(e, e.stat()) for e in files]
            sets.append({"path": str(d), "rip": sum(Path(e.name).suffix.lower() == ".rip" for e, _ in st),
                         "nr": sum(Path(e.name).suffix.lower() == ".nr" for e, _ in st),
                         "textures": sum(Path(e.name).suffix.lower() in TEX_EXT for e, _ in st),
                         "bytes": sum(s.st_size for _, s in st), "modified": max(s.st_mtime for _, s in st)})
    sets.sort(key=lambda s: -s["modified"])
    return sets[:max(1, limit)]


def snapshot(roots: list[Path]) -> dict[str, float]:
    out = {}
    for root in roots:
        for d, files in _walk_rip_dirs(root):
            for e in files:
                if Path(e.name).suffix.lower() in RIP_EXT:
                    out[e.path] = e.stat().st_mtime
    return out


# ------------------------------------------------------------------------------------------------ Windows process side

def _ledger_path(cfg) -> Path:
    return Path(cfg.runtime) / "ninja_ripper" / "launched.json"


def load_ledger(cfg) -> dict:
    try:
        return json.loads(_ledger_path(cfg).read_text())
    except (OSError, ValueError):
        return {}


def save_ledger(cfg, d: dict) -> None:
    p = _ledger_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1))


def alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(0x1000, False, int(pid))            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def pick_dll(inst: dict, machine: str | None) -> Path:
    if inst.get("dll"):
        return Path(inst["dll"])
    cands = (inst.get("dlls") or {}).get(machine or "x64") or []
    if len(cands) == 1:
        return Path(cands[0])
    raise Unsupported(f"can't tell which NinjaRipper DLL to load into a {machine or 'x64'} process "
                      f"(found {cands or 'none'}); set [ninja_ripper] dll in gbox.toml or use mode=launcher")


def inject_dll(pid: int, dll: Path) -> dict:
    """LoadLibraryW(dll) inside pid through a remote thread (same mechanism gbox.scene_capture uses for RenderDoc).
    64-bit targets only: the LoadLibraryW address comes from this (64-bit) Python's kernel32."""
    import ctypes
    from .scene_capture import _k32, _modules, _remote_call
    k = _k32()
    h = k.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) failed ({ctypes.get_last_error()})")
    try:
        path = (str(dll) + "\0").encode("utf-16-le")
        mem = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04)     # MEM_COMMIT|RESERVE, PAGE_READWRITE
        if not mem:
            raise OSError("VirtualAllocEx failed")
        k.WriteProcessMemory(h, mem, path, len(path), None)
        ll = k.GetProcAddress(k.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        hmod = _remote_call(k, h, ll, mem)
        try:
            loaded = dll.name.lower() in _modules(pid)
        except Exception:                                   # noqa: BLE001 - a suspended process may not list modules yet
            loaded = None
        if not hmod and not loaded:
            raise RuntimeError(f"{dll.name} did not load into process {pid} (wrong bitness or missing dependency)")
        return {"dll": str(dll), "loaded": True if hmod else loaded}
    finally:
        k.CloseHandle(h)


def launch_injected(argv: list[str], dll: Path, cwd: str | None) -> tuple[subprocess.Popen, dict]:
    """Start the program suspended, load the NinjaRipper DLL before its first instruction, then let it run."""
    import ctypes
    from ctypes import wintypes
    p = subprocess.Popen(argv, cwd=cwd or None, creationflags=0x4)    # CREATE_SUSPENDED
    try:
        info = inject_dll(p.pid, dll)
    except Exception:
        p.kill()
        raise
    ctypes.WinDLL("ntdll").NtResumeProcess(wintypes.HANDLE(int(p._handle)))
    return p, info


VK = {**{f"F{i}": 0x6F + i for i in range(1, 25)}, "PRINTSCREEN": 0x2C, "SCROLLLOCK": 0x91, "PAUSE": 0x13,
      "INSERT": 0x2D, "HOME": 0x24, "END": 0x23}
MODS = {"CTRL": 0x11, "CONTROL": 0x11, "SHIFT": 0x10, "ALT": 0x12}


def parse_hotkey(s: str) -> list[int]:
    keys = [k.strip().upper() for k in (s or DEFAULT_HOTKEY).split("+") if k.strip()]
    out = []
    for k in keys:
        if k in MODS:
            out.append(MODS[k])
        elif k in VK:
            out.append(VK[k])
        elif len(k) == 1 and k.isalnum():
            out.append(ord(k))
        else:
            raise ValueError(f"unknown key {k!r} in hotkey {s!r}")
    if not out or all(v in MODS.values() for v in out):
        raise ValueError(f"hotkey {s!r} has no main key")
    return out


def _focus(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True
    u.EnumWindows(cb, 0)
    return bool(found and u.SetForegroundWindow(found[0]))


def press(hotkey: str, pid: int | None = None, hold: float = 0.12) -> dict:
    """Press the rip hotkey (keybd_event: NinjaRipper polls the async key state, so focus is best effort only)."""
    import ctypes
    keys = parse_hotkey(hotkey)
    focused = _focus(pid) if pid else False
    u = ctypes.WinDLL("user32")
    for k in keys:
        u.keybd_event(k, u.MapVirtualKeyW(k, 0), 0, 0)
    time.sleep(hold)
    for k in reversed(keys):
        u.keybd_event(k, u.MapVirtualKeyW(k, 0), 2, 0)          # KEYEVENTF_KEYUP
    return {"hotkey": hotkey or DEFAULT_HOTKEY, "focused": focused}


# ------------------------------------------------------------------------------------------------ worker tool

class NinjaIn(BaseModel):
    op: str = "status"          # status | launch | attach | rip | list | import | stop
    exe: str = ""               # launch: the game / emulator executable on this PC
    args: list[str] = []        # launch: its arguments
    cwd: str = ""               # launch: working directory (default: the exe's folder)
    mode: str = "auto"          # launch: inject (load the DLL into a suspended start) | launcher ([ninja_ripper] launcher_args) | auto
    session_id: str = ""        # attach / rip: an agent-owned gBox session on this PC
    pid: int = 0                # rip / stop: a process this tool launched
    hotkey: str = ""            # rip: default [ninja_ripper] hotkey or F10
    wait_s: float = 30.0        # rip: how long to wait for new files
    path: str = ""              # import: a rip folder or one .rip (default: the newest rip set)
    select: str = "*.rip"       # import: file pattern inside the folder
    max_files: int = 2000
    limit: int = 20             # list: rip sets returned
    d3d_to_gltf: bool = True    # import: negate Z + flip winding (D3D left-handed -> glTF)
    textures: bool = True       # import: embed the referenced textures (DDS via Pillow)
    name: str = ""              # import: model name kept in the artifact provenance


class NinjaOut(BaseModel):
    op: str
    result: dict


def _api(ctx: Ctx, method: str, path: str, **kw):
    import httpx
    if not ctx.server:
        raise Unsupported("ninja_ripper launch/attach/rip need the control plane (to check the background-testing rules)")
    r = httpx.request(method, ctx.server + path, headers=ctx.headers, timeout=kw.pop("timeout", 30), **kw)
    r.raise_for_status()
    return r.json()


def guard(ctx: Ctx, session_id: str = "") -> None:
    """gbox.background_testing rules for anything that starts, injects into or keys a process on this PC."""
    from . import background_testing as bt
    if not getattr(ctx, "agent_use", False):
        raise PermissionError("ninja_ripper launch/attach/rip/stop run only as agent test jobs (agent_use); the operator's "
                              "own games are never injected or keyed")
    if why := bt.worker_testing_reason(_api(ctx, "GET", "/api/testing/workers"), ctx.worker):
        raise PermissionError(why)
    if session_id:
        labels = _api(ctx, "GET", "/api/session_labels")
        try:
            job = _api(ctx, "GET", f"/api/jobs/{session_id.split('-', 1)[-1]}")
        except Exception:                                   # noqa: BLE001
            job = {}
        if not bt.agent_owned(labels.get(session_id), job):
            raise PermissionError(f"session {session_id} is not an agent-owned test session; ninja_ripper never attaches "
                                  "to or keys the operator's sessions")


def _session_pid(session_id: str) -> int:
    from .tools import SESSIONS
    s = SESSIONS.get(session_id)
    if s is None:
        raise Unsupported(f"session {session_id} is not running on this worker")
    proc = getattr(s[0], "proc", None)
    if proc is None or proc.poll() is not None:
        raise Unsupported(f"session {session_id} has no running local process to rip")
    return proc.pid


def _fmt(template: list[str], **kw) -> list[str]:
    out = []
    for t in template:
        if t == "{args}":
            out += kw["args"]
        else:
            out.append(t.format(**{k: v for k, v in kw.items() if k != "args"}))
    return out


def _launch(inp: NinjaIn, ctx: Ctx, inst: dict) -> dict:
    exe = Path(inp.exe)
    if not exe.is_file() or exe.suffix.lower() != ".exe":
        raise FileNotFoundError(f"launch needs exe = an .exe on this PC (got {inp.exe!r})")
    cwd = inp.cwd or str(exe.parent)
    nc, machine = _ncfg(ctx.config), pe_machine(exe)
    mode = inp.mode
    if mode == "auto":
        mode = "launcher" if nc.get("launcher_args") or machine != "x64" else "inject"
    if mode == "inject":
        if machine != "x64":
            raise Unsupported(f"{exe.name} is {machine or 'not a PE'}: DLL injection here is 64-bit only; use mode=launcher "
                              "with [ninja_ripper] launcher_args")
        dll = pick_dll(inst, machine)
        p, info = launch_injected([str(exe), *inp.args], dll, cwd)
    elif mode == "launcher":
        tmpl = nc.get("launcher_args")
        if not tmpl or not inst.get("launcher"):
            raise Unsupported("mode=launcher needs [ninja_ripper] launcher_args (e.g. [\"{launcher}\", \"{exe}\", \"{args}\"]) "
                              "and NinjaRipper's launcher exe")
        out = str((output_roots(ctx.config, inst) or [Path(ctx.config.runtime) / "ninja_ripper" / "out"])[0])
        argv = _fmt(list(tmpl), launcher=inst["launcher"], exe=str(exe), args=list(inp.args), cwd=cwd, out=out)
        p, info = subprocess.Popen(argv, cwd=cwd), {"argv": argv}
    else:
        raise ValueError("mode: inject | launcher | auto")
    led = load_ledger(ctx.config)
    led[str(p.pid)] = {"exe": str(exe), "args": list(inp.args), "mode": mode, "started": time.time(), "job": ctx.job_id,
                       "attached": False}
    save_ledger(ctx.config, led)
    return {"pid": p.pid, "mode": mode, "exe": str(exe), "machine": machine, **info,
            "next": "ninja_ripper op=rip pid=<pid> once the scene you want is on screen; op=stop pid=<pid> when done"}


def _rip(inp: NinjaIn, ctx: Ctx, inst: dict) -> dict:
    if inp.session_id:
        pid = _session_pid(inp.session_id)
    elif inp.pid:
        led = load_ledger(ctx.config)
        if str(inp.pid) not in led:
            raise PermissionError(f"pid {inp.pid} was not launched or attached by ninja_ripper on this PC")
        pid = inp.pid
    else:
        raise ValueError("rip needs session_id (agent-owned session) or pid (a process ninja_ripper launched)")
    if not alive(pid):
        raise Unsupported(f"process {pid} is not running")
    roots = output_roots(ctx.config, inst)
    before = snapshot(roots)
    hk = inp.hotkey or _ncfg(ctx.config).get("hotkey") or DEFAULT_HOTKEY
    pressed = press(hk, pid)
    ctx.progress(20, f"pressed {hk}; waiting for NinjaRipper's files")
    t0, last, stable = time.time(), None, 0.0
    new: dict = {}
    while time.time() - t0 < max(2.0, inp.wait_s):
        time.sleep(1.0)
        roots = output_roots(ctx.config, inst)
        now = snapshot(roots)
        new = {p: m for p, m in now.items() if before.get(p) != m}
        sig = (len(new), max(new.values(), default=0))
        if new and sig == last:
            stable += 1.0
            if stable >= 2.0:
                break
        else:
            stable = 0.0
        last = sig
    dirs = sorted({str(Path(p).parent) for p in new})
    sets = [s for s in list_rips(roots, 200) if s["path"] in dirs]
    return {"pid": pid, **pressed, "new_files": len(new), "sets": sets, "output_roots": [str(r) for r in roots],
            "note": None if new else "no new rip files appeared: check the hotkey ([ninja_ripper] hotkey) and output_dir, "
                                     "and that the game renders through D3D9/10/11 (NinjaRipper 1.x)",
            "next": "ninja_ripper op=import path=<set path> converts the rip to one GLB" if sets else None}


def _validate(out: NinjaOut, arts) -> list[str]:
    if out.op != "import":
        return []
    from .store import sha256
    d = arts.get("ninja_rip.glb", b"")
    if d[:4] != b"glTF":
        return ["ninja_rip.glb is not a binary glTF"]
    return [] if sha256(d) == out.result.get("glb") else ["ninja_rip.glb hash mismatch"]


@tool("ninja_ripper", "1.0", NinjaIn, NinjaOut, capabilities=["runtime", "asset", "rip"], platforms=["windows"],
      permissions=[P.READ, P.EXECUTE], timeout_s=900, artifacts=["ninja_rip.glb", "ninja_rip.json"],
      side_effects=["launch/attach: starts an agent-owned program with NinjaRipper's DLL inside (background-testing PCs only)",
                    "rip: presses the rip hotkey on that PC", "stop: closes a program ninja_ripper launched"],
      validate=_validate, validation="import: binary glTF magic + hash", check=check)
def ninja_ripper(inp: NinjaIn, ctx: Ctx):
    """NinjaRipper on a Windows PC: op=status (install, output folders, launched processes) | launch (exe, args: start an
    agent-owned game/emulator with NinjaRipper inside) | attach (session_id: load it into an agent-owned session's
    process) | rip (session_id or pid: press the rip hotkey, wait for the files) | list (rip sets, newest first) |
    import (path = rip folder or .rip, default newest: convert to one GLB artifact; store it in the collection with
    characters op=add artifact=<glb>) | stop (pid: close a process ninja_ripper launched)."""
    op = inp.op.lower()
    inst = find_install(ctx.config)
    if inst is None:
        raise ToolUnavailable(check(ctx.config) or "NinjaRipper not found")
    if op == "status":
        led = load_ledger(ctx.config)
        return {"op": op, "result": {"install": inst, "output_roots": [str(r) for r in output_roots(ctx.config, inst)],
                                     "hotkey": _ncfg(ctx.config).get("hotkey") or DEFAULT_HOTKEY,
                                     "launched": {pid: e | {"alive": alive(int(pid))} for pid, e in led.items()}}}
    if op == "list":
        roots = output_roots(ctx.config, inst)
        return {"op": op, "result": {"output_roots": [str(r) for r in roots], "sets": list_rips(roots, inp.limit)}}
    if op == "import":
        path = inp.path
        if not path:
            sets = list_rips(output_roots(ctx.config, inst), 1)
            if not sets:
                raise FileNotFoundError("no rip sets found; pass path=<rip folder> or rip first")
            path = sets[0]["path"]
        files = rip_files(Path(path), inp.select, inp.max_files)
        ctx.progress(10, f"converting {len(files)} rip files")
        glb, summary = rips_to_glb(files, inp.d3d_to_gltf, inp.textures, inp.name or Path(path).name)
        from .store import sha256
        meta = {"source": str(path), "model": inp.name or Path(path).name, "tool": "ninja_ripper"}
        ctx.artifact("ninja_rip.glb", glb, "model/gltf-binary", **meta)
        ctx.artifact("ninja_rip.json", json.dumps(summary, indent=1).encode(), "application/json", **meta)
        return {"op": op, "result": {"glb": sha256(glb), "glb_bytes": len(glb), "path": str(path), "summary": summary,
                                     "next": "characters op=add character=<name> artifact=<glb> kind=object|character "
                                             "stores it in the collection"}}
    if op in ("launch", "attach", "rip", "stop"):
        guard(ctx, inp.session_id if op in ("attach", "rip") else "")
    if op == "launch":
        return {"op": op, "result": _launch(inp, ctx, inst)}
    if op == "attach":
        if not inp.session_id:
            raise ValueError("attach needs session_id (an agent-owned session on this PC)")
        pid = _session_pid(inp.session_id)
        info = inject_dll(pid, pick_dll(inst, "x64"))
        led = load_ledger(ctx.config)
        led[str(pid)] = {"session_id": inp.session_id, "mode": "attach", "started": time.time(), "job": ctx.job_id,
                         "attached": True}
        save_ledger(ctx.config, led)
        return {"op": op, "result": {"pid": pid, **info, "note": "NinjaRipper hooks the graphics API when it loads; a "
                                     "device created before the attach may not be hooked. If op=rip writes nothing, "
                                     "relaunch the program with op=launch."}}
    if op == "rip":
        return {"op": op, "result": _rip(inp, ctx, inst)}
    if op == "stop":
        led = load_ledger(ctx.config)
        e = led.get(str(inp.pid))
        if not e:
            raise PermissionError(f"pid {inp.pid} was not launched by ninja_ripper on this PC")
        if e.get("attached"):
            raise PermissionError("that process is a gBox session (attached); end it with session_op, not ninja_ripper")
        r = subprocess.run(["taskkill", "/PID", str(inp.pid), "/T", "/F"], capture_output=True, text=True)
        led.pop(str(inp.pid), None)
        save_ledger(ctx.config, led)
        return {"op": op, "result": {"pid": inp.pid, "stopped": r.returncode == 0, "detail": (r.stdout + r.stderr)[-300:]}}
    raise ValueError("op: status | launch | attach | rip | list | import | stop")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.ninja_ripper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("find")
    ls = sub.add_parser("list")
    ls.add_argument("--root", action="append", default=[])
    gb = sub.add_parser("glb")
    gb.add_argument("path")
    gb.add_argument("--out", required=True)
    gb.add_argument("--select", default="*.rip")
    gb.add_argument("--keep-d3d", action="store_true")
    a = ap.parse_args(argv)
    from .scene_capture import _cfg
    if a.cmd == "find":
        print(json.dumps(find_install(_cfg(), refresh=True), indent=1))
    elif a.cmd == "list":
        cfg = _cfg()
        roots = [Path(r) for r in a.root] or output_roots(cfg, find_install(cfg))
        print(json.dumps(list_rips(roots, 50), indent=1))
    else:
        glb, summary = rips_to_glb(rip_files(Path(a.path), a.select), not a.keep_d3d)
        Path(a.out).write_bytes(glb)
        print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
