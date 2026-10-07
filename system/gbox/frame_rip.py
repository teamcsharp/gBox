"""Rip what's on screen: capture one frame of a running GPU-rendered emulator with RenderDoc, then export the posed
3D triangles of anything visible (positions, UVs, textures) to glTF.

Pipeline (Windows node; RenderDoc portable in <runtime>/tools/RenderDoc_*):
  1. launch()   RetroArch (or any emulator) under `renderdoccmd capture`. Vulkan needs no admin layer registration:
                the layer json is added per process with VK_LAYER_PATH/VK_ADD_LAYER_PATH + VK_INSTANCE_LAYERS.
  2. capture()  trigger N frames through RenderDoc's target control (qrenderdoc --python; RenderDoc's Python API only
                ships embedded in qrenderdoc.exe, there is no standalone renderdoc.pyd in the release zip).
  3. extract()  replay the .rdc in qrenderdoc and dump every draw: raw vertex buffers, post-VS clip positions, index
                buffers, fragment-shader specialization constants, and every bound texture's pixels at that draw.
  4. load()     decode the dump into screen-space triangles (x, y in pixels + w = view depth) with UVs/texture keys.
                Decoders: "beetle_psx_vk" (Beetle PSX HW, Vulkan renderer = parallel-psx: 76-byte vertices, PGXP w in
                Position.w, VRAM as a 1024x512 R32_UINT atlas, texture depth in the PS spec constant SHIFT) and a
                generic one (post-VS gl_Position for any core; no texture decode).
  5. pick()/select_box() choose the object (seed point + same-depth, touching components), rip() writes glTF:
                X = (x - cx) * w / f, Y = (y - cy) * w / f, Z = w   (f = projection plane distance; PS1 = GTE H)
                then Y-up, feet at the origin, scaled to `height` metres. Each connected component becomes its own
                node "part_NN" (PS1 models are built from rigid per-bone pieces), with textures decoded from VRAM.

PS1 notes: 3D (GTE) primitives carry PGXP w; 2D sprites/backgrounds have w == 1 and are skipped. H is game state
(Parasite Eve: *(u32*)*(u32*)0x800BCFA8 = 323), read it with RetroArch READ_CORE_MEMORY or pass `focal`.

CLI:  python -m gbox.frame_rip launch <content> [--core mednafen_psx_hw]
      python -m gbox.frame_rip capture [--pid N] [--frames 3]
      python -m gbox.frame_rip extract <file.rdc> [--out dir]
      python -m gbox.frame_rip show <dumpdir> [--out debug.png]           (screen view of 3D triangles + components)
      python -m gbox.frame_rip rip <dumpdir> --pick X,Y [--focal 323] [--height 1.7] --out model.gltf
"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ------------------------------------------------------------------------------------------------ RenderDoc side

CAPTURE_PY = r'''
import os, time
import renderdoc as rd
out = open(os.environ["RD_OUT"], "w")
try:
    pid = int(os.environ.get("RD_PID", "0") or 0)
    old = set(os.environ.get("RD_OLD", "").split("|"))
    ident, tc = rd.EnumerateRemoteTargets("", 0), None
    while ident:
        t = rd.CreateTargetControl("", ident, "gbox-frame-rip", True)
        if t and (not pid or t.GetPID() == pid):
            tc = t
            break
        if t:
            t.Shutdown()
        ident = rd.EnumerateRemoteTargets("", ident)
    if not tc:
        raise RuntimeError("no RenderDoc target (is the emulator running under renderdoccmd?)")
    n = int(os.environ.get("RD_N", "1"))
    tc.TriggerCapture(n)
    t0, paths = time.time(), []
    while time.time() - t0 < float(os.environ.get("RD_WAIT", "60")) and len(paths) < n:
        m = tc.ReceiveMessage(None)
        if m.type == rd.TargetControlMessageType.NewCapture:
            p = m.newCapture.path
            if p not in old and os.path.basename(p) not in old:
                paths.append(p)
        elif m.type == rd.TargetControlMessageType.Disconnected:
            break
    for p in paths:
        out.write("CAPTURE %s\n" % p)
    tc.Shutdown()
except BaseException:
    import traceback
    out.write(traceback.format_exc())
out.close()
os._exit(0)
'''

EXTRACT_PY = r'''
import json, os, re, struct
import renderdoc as rd
outd = os.environ["RD_OUT"]
os.makedirs(outd, exist_ok=True)
log = open(os.path.join(outd, "extract.log"), "w")
try:
    cap = rd.OpenCaptureFile()
    st = cap.OpenFile(os.environ["RD_CAP"], "", None)
    assert st == rd.ResultCode.Succeeded, str(st)
    st, ctl = cap.OpenCapture(rd.ReplayOptions(), None)
    assert st == rd.ResultCode.Succeeded, str(st)
    sf = ctl.GetStructuredFile()
    texinfo = {str(t.resourceId): t for t in ctl.GetTextures()}
    acts = []
    def walk(a):
        for x in a:
            if x.flags & rd.ActionFlags.Drawcall:
                acts.append(x)
            walk(x.children)
    walk(ctl.GetRootActions())
    spec_cache, draws, texdump = {}, [], {}
    maxtex = int(os.environ.get("RD_MAXTEX", str(8 << 20)))
    for a in acts:
        ctl.SetFrameEvent(a.eventId, False)
        ps = ctl.GetPipelineState()
        pipe = str(ps.GetGraphicsPipelineObject())
        d = {"eid": a.eventId, "name": a.GetName(sf), "n": a.numIndices, "inst": a.numInstances,
             "vertexOffset": a.vertexOffset, "indexOffset": a.indexOffset, "baseVertex": a.baseVertex,
             "indexed": bool(a.flags & rd.ActionFlags.Indexed), "pipe": pipe}
        d["inputs"] = [{"name": at.name, "fmt": at.format.Name(), "buf": at.vertexBuffer, "off": at.byteOffset}
                       for at in ps.GetVertexInputs()]
        vbs = ps.GetVBuffers()
        d["vbs"] = [{"off": vb.byteOffset, "stride": vb.byteStride} for vb in vbs]
        if d["indexed"]:
            ib = ps.GetIBuffer()
            w = ib.byteStride or 2
            raw = ctl.GetBufferData(ib.resourceId, ib.byteOffset + a.indexOffset * w, a.numIndices * w)
            idx = [i + a.baseVertex for i in struct.unpack("<%d%s" % (a.numIndices, "H" if w == 2 else "I"), raw)]
            lo, hi = min(idx), max(idx) + 1
            open(os.path.join(outd, "d%d_idx.bin" % a.eventId), "wb").write(struct.pack("<%dI" % len(idx), *idx))
        else:
            lo, hi = a.vertexOffset, a.vertexOffset + a.numIndices
        d["vlo"], d["vhi"] = lo, hi
        for bi, vb in enumerate(vbs[:4]):
            if vb.byteStride:
                data = ctl.GetBufferData(vb.resourceId, vb.byteOffset + lo * vb.byteStride, (hi - lo) * vb.byteStride)
                open(os.path.join(outd, "d%d_vb%d.bin" % (a.eventId, bi)), "wb").write(data)
        try:
            m = ctl.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
            if m.vertexResourceId != rd.ResourceId.Null() and m.numIndices:
                cnt = m.numIndices
                if m.indexResourceId != rd.ResourceId.Null():
                    w = m.indexByteStride or 4
                    raw = ctl.GetBufferData(m.indexResourceId, m.indexByteOffset, cnt * w)
                    open(os.path.join(outd, "d%d_postvs_idx.bin" % a.eventId), "wb").write(raw)
                    d["postvs_index_stride"] = w
                    cnt = max(struct.unpack("<%d%s" % (cnt, "H" if w == 2 else "I"), raw)) + 1
                data = ctl.GetBufferData(m.vertexResourceId, m.vertexByteOffset, cnt * m.vertexByteStride)
                open(os.path.join(outd, "d%d_postvs.bin" % a.eventId), "wb").write(data)
                d["postvs"] = {"stride": m.vertexByteStride, "count": cnt}
        except Exception as e:
            d["postvs_error"] = str(e)
        if pipe not in spec_cache:
            sh = ps.GetShaderReflection(rd.ShaderStage.Pixel)
            txt = ctl.DisassembleShader(ps.GetGraphicsPipelineObject(), sh, "") if sh else ""
            spec_cache[pipe] = {k: int(v) for _, k, v in
                                re.findall(r"const (int|uint|bool) (\w+) = (-?\d+) : \[\[SpecId", txt)}
        d["spec"] = spec_cache[pipe]
        d["viewport"] = [ps.GetViewport(0).x, ps.GetViewport(0).y, ps.GetViewport(0).width, ps.GetViewport(0).height]
        tex = []
        for ro in ps.GetReadOnlyResources(rd.ShaderStage.Pixel):
            rid = str(ro.descriptor.resource)
            t = texinfo.get(rid)
            if t is None:
                continue
            tex.append(rid)
            if t.width * t.height * max(1, t.format.compByteWidth * t.format.compCount) <= maxtex:
                key = "t%s_e%d" % (re.sub(r"\D", "", rid), a.eventId)
                open(os.path.join(outd, key + ".bin"), "wb").write(ctl.GetTextureData(t.resourceId, rd.Subresource(0, 0, 0)))
                texdump.setdefault(rid, []).append(a.eventId)
        d["tex"] = tex
        draws.append(d)
    textures = {rid: {"w": t.width, "h": t.height, "fmt": t.format.Name()} for rid, t in texinfo.items()}
    json.dump({"capture": os.environ["RD_CAP"], "draws": draws, "textures": textures, "texdump": texdump},
              open(os.path.join(outd, "manifest.json"), "w"), indent=1)
    log.write("OK %d draws\n" % len(draws))
    ctl.Shutdown()
    cap.Shutdown()
except BaseException:
    import traceback
    log.write(traceback.format_exc())
log.close()
os._exit(0)
'''


def _cfg():
    """gBox config: $GBOX_CONFIG, else the gbox.toml next to the package (never a cwd-relative default, which would
    provision a fresh runtime in the current directory)."""
    from . import config
    p = os.environ.get("GBOX_CONFIG") or Path(__file__).resolve().parents[1] / "gbox.toml"
    return config.load(p)


def renderdoc_dir(runtime: Path | str | None = None) -> Path:
    """The portable RenderDoc under <runtime>/tools (newest RenderDoc_* folder)."""
    roots = [Path(runtime)] if runtime else []
    if not roots:
        try:
            roots.append(_cfg().runtime)
        except Exception:
            pass
        roots.append(Path("D:/gBox/runtime"))
    for r in roots:
        found = sorted((r / "tools").glob("RenderDoc_*/qrenderdoc.exe"))
        if found:
            return found[-1].parent
    raise FileNotFoundError("RenderDoc not found under <runtime>/tools/RenderDoc_*")


def _qrd(script: str, env: dict, timeout: float = 600) -> None:
    """Run a script inside qrenderdoc.exe (it hosts the renderdoc Python module). The script exits the process."""
    rd = renderdoc_dir()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
    try:
        p = subprocess.Popen([str(rd / "qrenderdoc.exe"), "--python", f.name], env={**os.environ, **env})
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise
    finally:
        os.unlink(f.name)


def renderdoc_env(rd: Path | None = None) -> dict:
    """Environment that loads RenderDoc's Vulkan layer without registering it system-wide."""
    rd = rd or renderdoc_dir()
    return {"VK_LAYER_PATH": str(rd), "VK_ADD_LAYER_PATH": str(rd), "VK_INSTANCE_LAYERS": "VK_LAYER_RENDERDOC_Capture",
            "ENABLE_VULKAN_RENDERDOC_CAPTURE": "1"}


BEETLE_VK_OPTIONS = {
    "beetle_psx_hw_renderer": "hardware_vk", "beetle_psx_hw_pgxp_mode": "memory + CPU",
    "beetle_psx_hw_pgxp_vertex": "enabled", "beetle_psx_hw_pgxp_texture": "enabled",
    "beetle_psx_hw_internal_resolution": "1x(native)", "beetle_psx_hw_skip_bios": "enabled",
}


def launch(content: str, work: Path, core: str = "mednafen_psx_hw", retroarch: str | None = None,
           cmd_port: int = 55433, pad_port: int = 55440, core_options: dict | None = None,
           extra_cfg: dict | None = None) -> subprocess.Popen:
    """Start RetroArch (Vulkan) under renderdoccmd with its own config dir `work` (never the worker's session config).
    Captures land in work/cap. PS1 CHD v4 images are not readable by Beetle's libchdr: convert to bin/cue first
    (psx_chd_to_bin)."""
    from . import provision
    cfg = _cfg()
    core_path = provision.ensure_platform(cfg, "psx", core)[0] if core == "mednafen_psx_hw" else provision.ensure_core(cfg, core)
    ra = retroarch or provision._retroarch_windows_raw(cfg)
    work = Path(work)
    for d in ("saves", "states", "shots", "cap"):
        (work / d).mkdir(parents=True, exist_ok=True)
    opts = {**(BEETLE_VK_OPTIONS if "psx_hw" in core else {}), **(core_options or {})}
    (work / "core-options.cfg").write_text("".join(f'{k} = "{v}"\n' for k, v in opts.items()))
    c = {"system_directory": str(cfg.runtime / "system"), "savefile_directory": str(work / "saves"),
         "savestate_directory": str(work / "states"), "screenshot_directory": str(work / "shots"),
         "network_cmd_enable": "true", "network_cmd_port": str(cmd_port), "config_save_on_exit": "false",
         "pause_nonactive": "false", "network_remote_enable": "true", "network_remote_enable_user_p1": "true",
         "network_remote_base_port": str(pad_port), "video_fullscreen": "false", "video_driver": "vulkan",
         "audio_driver": "null", "audio_enable": "false", "menu_driver": "rgui", "video_vsync": "true",
         "core_options_path": str(work / "core-options.cfg"), "global_core_options": "true",
         "video_font_enable": "false", "rewind_enable": "false", "input_autodetect_enable": "false",
         "video_scale": "3", "savestate_thumbnail_enable": "false", "ui_menubar_enable": "false",
         "ui_companion_enable": "false", "video_smooth": "false", "video_shader_enable": "false", **(extra_cfg or {})}
    (work / "ra.cfg").write_text("".join(f'{k} = "{v}"\n' for k, v in c.items()))
    rd = renderdoc_dir()
    args = [str(rd / "renderdoccmd.exe"), "capture", "-c", str(work / "cap" / "frame"), "-d", str(Path(ra).parent),
            ra, "--config", str(work / "ra.cfg"), "-L", str(core_path), content]
    return subprocess.Popen(args, env={**os.environ, **renderdoc_env(rd)}, cwd=str(Path(ra).parent),
                            stdout=open(work / "launch.log", "w"), stderr=subprocess.STDOUT)


def psx_chd_to_bin(chd: Path, out_bin: Path) -> Path:
    """CHD v4 (HyperSpin set) -> single-track MODE2/2352 .bin + .cue via gbox.psxdisc (no chdman)."""
    from .psxdisc import CHD
    c = CHD(chd)
    c.f.seek(36)
    meta, frames = struct.unpack(">Q", c.f.read(8))[0], None
    while meta:                                        # CHT2 metadata: FRAMES:n
        c.f.seek(meta)
        _tag, ln, nxt = struct.unpack(">4sIQ", c.f.read(16))
        txt = c.f.read(ln & 0xFFFFFF).decode("ascii", "replace")
        if "FRAMES:" in txt:
            frames = (frames or 0) + int(txt.split("FRAMES:")[1].split()[0])
        meta = nxt
    n = frames or c.logical // c.frame
    with open(out_bin, "wb") as f:
        for i in range(n):
            f.write(c.sector(i))
    Path(out_bin).with_suffix(".cue").write_text(f'FILE "{Path(out_bin).name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    return Path(out_bin).with_suffix(".cue")


def ra_command(cmd: str, port: int = 55433, reply: bool = False) -> str | None:
    """RetroArch network command (SCREENSHOT, PAUSE_TOGGLE, READ_CORE_MEMORY addr n, ...)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        sk.settimeout(2)
        sk.sendto(cmd.encode(), ("127.0.0.1", port))
        if reply:
            try:
                return sk.recv(65536).decode()
            except socket.timeout:
                return None
    return None


def ra_read_u32(addr: int, port: int = 55433) -> int:
    r = ra_command(f"READ_CORE_MEMORY {addr & 0x1FFFFF:x} 4", port, True)
    return int.from_bytes(bytes(int(x, 16) for x in r.split()[2:6]), "little")


def psx_gte_h_from_pointer(ptr_addr: int, port: int = 55433) -> int:
    """Read the GTE H a game keeps behind a pointer (Parasite Eve: 0x800BCFA8)."""
    return ra_read_u32(ra_read_u32(ptr_addr, port), port) & 0xFFFF


def psx_boot_exe(disc: Path) -> tuple[str, bytes]:
    """(name, bytes) of the boot executable named in SYSTEM.CNF (CHD v4 or bin/cue via gbox.psxdisc)."""
    from .psxdisc import PSXDisc
    d = PSXDisc(disc)
    cnf = d.read("SYSTEM.CNF").decode("ascii", "replace")
    name = cnf.split("cdrom:", 1)[1].split(";")[0].strip().lstrip("\\").replace("\\", "/")
    return name, d.read(name)


def psx_cull_sites(exe: bytes) -> list[dict]:
    """Back-face culling branches in a PS1 EXE: a GTE NCLIP followed (within 12 instructions, before any jump) by a
    branch on the result register. Games skip a primitive when NCLIP <= 0, so a single frame only holds the camera-
    facing half of a model. Patch: 'blez/bltz r, skip' -> nop; 'bgtz/bgez r, draw' -> unconditional branch.
    Only sites whose branch tests a register (no library helper that returns the value) are listed."""
    base = struct.unpack_from("<I", exe, 0x18)[0]
    text = exe[0x800:]
    ws = struct.unpack("<%dI" % (len(text) // 4), text[:len(text) // 4 * 4])
    out = []
    for i, w in enumerate(ws):
        if w & 0xFE00003F != 0x4A000006 or not (w >> 25) & 1:     # cop2 NCLIP (0x4A400006 / 0x4B400006)
            continue
        for j in range(i + 1, min(len(ws), i + 13)):
            p = ws[j]
            op, rs, rt = p >> 26, (p >> 21) & 31, (p >> 16) & 31
            if op in (2, 3) or (op == 0 and (p & 0x3F) in (8, 9)):
                break
            kind = {6: "blez", 7: "bgtz"}.get(op) if rt == 0 else None
            if op == 1 and rt in (0, 1):
                kind = "bltz" if rt == 0 else "bgez"
            if kind:
                new = 0 if kind in ("blez", "bltz") else (0x10000000 | (p & 0xFFFF))   # nop | beq r0,r0,same target
                out.append({"nclip": base + 4 * i, "addr": base + 4 * j, "kind": kind, "reg": rs,
                            "orig": p, "patched": new})
                break
    return out


def psx_disable_cull(sites: list[dict], port: int = 55433, restore: bool = False) -> list[dict]:
    """Write the cull patches into a running RetroArch PS1 core (READ/WRITE_CORE_MEMORY). Each site is checked to hold
    the expected original word first (code loaded at its EXE address); restore=True writes the originals back."""
    done = []
    for s in sites:
        a = s["addr"] & 0x1FFFFF
        cur = ra_read_u32(a, port)
        want_from, want_to = (s["patched"], s["orig"]) if restore else (s["orig"], s["patched"])
        if cur != want_from:
            done.append({**s, "skipped": f"found {cur:#010x}"})
            continue
        ra_command(f"WRITE_CORE_MEMORY {a:x} " + " ".join(f"{b:02X}" for b in struct.pack("<I", want_to)), port)
        done.append({**s, "ok": ra_read_u32(a, port) == want_to})
    return done


RETROPAD = {"b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6, "right": 7, "a": 8, "x": 9,
            "l": 10, "r": 11, "l2": 12, "r2": 13, "l3": 14, "r3": 15}


def ra_pad(button: str, hold: float = 0.12, port: int = 55440) -> None:
    """Press a RetroPad button through RetroArch's network gamepad (focus independent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        for st in (1, 0):
            sk.sendto(struct.pack("<iiiiH2x", 0, 1, 0, RETROPAD[button], st), ("127.0.0.1", port))
            time.sleep(hold if st else 0.05)


def capture(pid: int = 0, frames: int = 3, cap_dir: Path | None = None, wait: float = 60) -> list[Path]:
    """Trigger `frames` consecutive captures in a running RenderDoc-injected process; returns the new .rdc paths.
    Games often render every other frame (30 fps): take several and use the largest."""
    fd, name = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    out = Path(name)
    old = "|".join(os.listdir(cap_dir)) if cap_dir and Path(cap_dir).is_dir() else ""
    _qrd(CAPTURE_PY, {"RD_OUT": str(out), "RD_PID": str(pid), "RD_N": str(frames), "RD_OLD": old,
                      "RD_WAIT": str(wait)}, wait + 60)
    txt = out.read_text()
    out.unlink()
    paths = [Path(l[8:].strip()) for l in txt.splitlines() if l.startswith("CAPTURE ")]
    if not paths:
        raise RuntimeError("capture failed: " + txt[-2000:])
    return paths


def extract(rdc: Path, out_dir: Path, timeout: float = 900) -> Path:
    out_dir = Path(out_dir)
    _qrd(EXTRACT_PY, {"RD_CAP": str(rdc), "RD_OUT": str(out_dir)}, timeout)
    log = (out_dir / "extract.log").read_text() if (out_dir / "extract.log").exists() else "no log"
    if not log.startswith("OK"):
        raise RuntimeError("extract failed: " + log[-3000:])
    return out_dir


# ------------------------------------------------------------------------------------------------ decode

BEETLE_VTX = np.dtype([("pos", "<f4", 4), ("col", "<f4", 4), ("win", "u1", 4), ("param", "<i2", 3), ("uv", "<i2", 4),
                       ("uvr", "<u2", 4), ("pad", "u1", 2), ("fog", "<f4", 4)])
BEETLE_INPUTS = ["Position", "Color", "Window", "Param", "UV", "UVRange", "Fog"]


@dataclass
class Frame:
    """Screen-space triangles of one captured frame. Arrays are per triangle (T) and per corner (T, 3)."""
    dir: Path
    xy: np.ndarray            # (T,3,2) pixels (PS1: VRAM coordinates incl. the drawing offset)
    w: np.ndarray             # (T,3) view depth (PGXP w; 1 = 2D primitive)
    uv: np.ndarray            # (T,3,2) texel coordinates inside the texture key's 256x256 page (or 0..1 generic)
    col: np.ndarray           # (T,3,4) vertex colour 0..1
    key: list                 # per triangle: texture key tuple or None (untextured)
    eid: np.ndarray           # (T,) draw event id
    vram: dict = field(default_factory=dict)   # eid -> (512,1024) uint16 VRAM at that draw
    decoder: str = "beetle_psx_vk"
    screen: tuple = (0, 0, 320, 240)            # display rect x, y, w, h

    @property
    def is3d(self) -> np.ndarray:
        return np.abs(self.w - 1.0).max(1) > 1e-3


def load(dump: Path) -> Frame:
    dump = Path(dump)
    man = json.loads((dump / "manifest.json").read_text())
    # textured pipelines bind all 7 inputs, untextured ones only Position/Color/Param/Fog (same 76-byte vertex)
    beetle = [d for d in man["draws"] if d["inputs"] and set(i["name"] for i in d["inputs"]) <= set(BEETLE_INPUTS)
              and {"Position", "Color", "Param"} <= set(i["name"] for i in d["inputs"]) and d["vbs"]
              and d["vbs"][0]["stride"] == BEETLE_VTX.itemsize]
    return _load_beetle(dump, man, beetle) if beetle else _load_generic(dump, man)


def _load_beetle(dump: Path, man: dict, draws: list) -> Frame:
    XY, W, UV, COL, KEY, EID = [], [], [], [], [], []
    vram = {}
    rects = []
    for d in draws:
        v = np.fromfile(dump / f"d{d['eid']}_vb0.bin", BEETLE_VTX)
        if d["indexed"]:
            idx = np.fromfile(dump / f"d{d['eid']}_idx.bin", "<u4") - d["vlo"]
            v = v[idx]
        v = v[:len(v) // 3 * 3].reshape(-1, 3)
        shift = d["spec"].get("SHIFT")
        textured = shift is not None
        if textured:
            atlas = next((t for t in d["tex"] if man["textures"][t]["w"] == 1024 and man["textures"][t]["h"] == 512
                          and man["textures"][t]["fmt"] == "R32_UINT"), None)
            f = dump / f"t{''.join(c for c in atlas if c.isdigit())}_e{d['eid']}.bin" if atlas else None
            if f and f.exists():
                vram[d["eid"]] = (np.fromfile(f, "<u4").reshape(512, 1024) & 0xFFFF).astype(np.uint16)
            else:
                textured = False
        p = v["pos"]
        XY.append(p[..., :2])
        W.append(p[..., 3])
        UV.append(v["uv"][..., :2].astype(np.float32))
        COL.append(v["col"])
        EID.append(np.full(len(v), d["eid"]))
        for t in v:
            c = t[0]
            KEY.append((d["eid"], int(shift), int(c["uv"][2]), int(c["uv"][3]), int(c["param"][0]), int(c["param"][1]),
                        tuple(int(x) for x in c["win"])) if textured else None)
        if not textured or True:
            if (np.abs(p[..., 3] - 1) < 1e-3).all():
                x0, y0 = p[..., 0].min(), p[..., 1].min()
                rects.append(((p[..., 0].max() - x0) * (p[..., 1].max() - y0), x0, y0, p[..., 0].max() - x0, p[..., 1].max() - y0))
    fr = Frame(dump, np.concatenate(XY), np.concatenate(W), np.concatenate(UV), np.concatenate(COL), KEY,
               np.concatenate(EID), vram, "beetle_psx_vk")
    # display rect: the largest full-screen 2D draw that holds the 3D geometry (clear / background)
    if fr.is3d.any():
        c3 = fr.xy[fr.is3d].reshape(-1, 2).mean(0)
        inside = [r for r in rects if r[1] <= c3[0] <= r[1] + r[3] and r[2] <= c3[1] <= r[2] + r[4] and r[3] >= 256]
        if inside:
            r = max(inside)
            fr.screen = (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
    return fr


def _load_generic(dump: Path, man: dict) -> Frame:
    """Any API/core: post-VS clip positions only (screen = NDC mapped to the viewport, w = clip w)."""
    XY, W, UV, COL, KEY, EID = [], [], [], [], [], []
    for d in man["draws"]:
        if "postvs" not in d:
            continue
        raw = np.fromfile(dump / f"d{d['eid']}_postvs.bin", np.uint8).reshape(-1, d["postvs"]["stride"])
        pos = raw[:, :16].copy().view("<f4").reshape(-1, 4)
        if (dump / f"d{d['eid']}_postvs_idx.bin").exists():
            pos = pos[np.fromfile(dump / f"d{d['eid']}_postvs_idx.bin", "<u2" if d.get("postvs_index_stride") == 2 else "<u4")]
        pos = pos[:len(pos) // 3 * 3].reshape(-1, 3, 4)
        vx, vy, vw, vh = d.get("viewport", [0, 0, 2, 2])
        wv = np.where(np.abs(pos[..., 3]) < 1e-9, 1e-9, pos[..., 3])
        xy = np.stack([vx + (pos[..., 0] / wv + 1) * vw / 2, vy + (pos[..., 1] / wv + 1) * vh / 2], -1)
        XY.append(xy)
        W.append(pos[..., 3])
        UV.append(np.zeros(xy.shape, np.float32))
        COL.append(np.ones(pos.shape, np.float32))
        KEY += [None] * len(pos)
        EID.append(np.full(len(pos), d["eid"]))
    fr = Frame(dump, np.concatenate(XY), np.concatenate(W), np.concatenate(UV), np.concatenate(COL), KEY,
               np.concatenate(EID), {}, "generic")
    vp = man["draws"][-1].get("viewport", [0, 0, 320, 240])
    fr.screen = tuple(float(x) for x in vp)
    return fr


def decode_page(vram: np.ndarray, shift: int, bu: int, bv: int, cx: int, cy: int, win=(255, 255, 0, 0)) -> np.ndarray:
    """A 256x256 RGBA texture page exactly as parallel-psx samples it (sample_vram_atlas): texture window, 4/8/16 bpp,
    CLUT at (cx, cy). PSX colour 0x0000 = transparent."""
    u = (np.arange(256) & win[0]) | win[2]
    v = (np.arange(256) & win[1]) | win[3]
    U, V = np.meshgrid(u, v)
    if shift:
        bpp = 16 >> shift
        word = vram[(bv + V) & 511, (bu + (U >> shift)) & 1023].astype(np.int64)
        idx = (word >> (bpp * (U & ((1 << shift) - 1)))) & ((1 << bpp) - 1)
        px = vram[cy & 511, (cx + idx) & 1023]
    else:
        px = vram[(bv + V) & 511, (bu + U) & 1023]
    px = px.astype(np.uint32)
    rgba = np.zeros((256, 256, 4), np.uint8)
    for c in range(3):
        x = (px >> (5 * c)) & 31
        rgba[..., c] = (x << 3) | (x >> 2)
    rgba[..., 3] = np.where(px == 0, 0, 255)
    return rgba


# ------------------------------------------------------------------------------------------------ selection

def components(fr: Frame, sel: np.ndarray | None = None, tol_px: float = 0.26, tol_w: float = 0.5) -> np.ndarray:
    """Connected components of 3D triangles (shared corners within tol). Returns a label per triangle (-1 = not 3D)."""
    sel = fr.is3d if sel is None else sel
    ids = np.nonzero(sel)[0]
    lab = np.full(len(fr.w), -1)
    if not len(ids):
        return lab
    q = np.concatenate([np.round(fr.xy[ids] / tol_px), np.round(fr.w[ids] / tol_w)[..., None]], -1).astype(np.int64)
    parent = list(range(len(ids)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    seen = {}
    for k in range(len(ids)):
        for c in range(3):
            key = tuple(q[k, c])
            if key in seen:
                ra, rb = find(k), find(seen[key])
                if ra != rb:
                    parent[ra] = rb
            else:
                seen[key] = k
    roots = {}
    for k in range(len(ids)):
        lab[ids[k]] = roots.setdefault(find(k), len(roots))
    return lab


def _dedupe(fr: Frame, tris: np.ndarray) -> np.ndarray:
    """Drop triangles drawn twice (semi-transparency passes draw the same primitive again)."""
    keep, seen = [], set()
    for t in tris:
        k = tuple(np.round(fr.xy[t], 2).ravel()) + tuple(np.round(fr.w[t], 1))
        if k not in seen:
            seen.add(k)
            keep.append(t)
    return np.array(keep, int)


def _point_in_tri(p, a, b, c):
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def pick(fr: Frame, x: float, y: float, depth_tol: float = 0.12, grow_px: float = 3.0, screen_coords: bool = True,
         lab: np.ndarray | None = None) -> np.ndarray:
    """Triangles of the object under screen point (x, y): the nearest 3D triangle there seeds it; connected components
    whose depth is within depth_tol (relative) of the seed's and whose screen bbox touches the grown object join.
    x, y are relative to the display rect when screen_coords (as in a screenshot), else absolute."""
    if screen_coords:
        x, y = x + fr.screen[0], y + fr.screen[1]
    lab = components(fr) if lab is None else lab
    hit = [t for t in np.nonzero(lab >= 0)[0] if _point_in_tri((x, y), *fr.xy[t])]
    if not hit:
        raise ValueError(f"no 3D triangle under ({x:.0f}, {y:.0f})")
    seed = min(hit, key=lambda t: fr.w[t].mean())
    wd = float(np.median(fr.w[lab == lab[seed]]))
    comps = {}
    for c in np.unique(lab[lab >= 0]):
        m = lab == c
        pts = fr.xy[m].reshape(-1, 2)
        comps[c] = (pts.min(0), pts.max(0), float(np.median(fr.w[m])))
    obj = {lab[seed]}
    lo, hi = comps[lab[seed]][0].copy(), comps[lab[seed]][1].copy()
    changed = True
    while changed:
        changed = False
        for c, (a, b, wc) in comps.items():
            if c in obj or abs(wc - wd) > depth_tol * wd:
                continue
            if (a <= hi + grow_px).all() and (b >= lo - grow_px).all() and _touches(fr, lab, obj, c, grow_px):
                obj.add(c)
                lo, hi = np.minimum(lo, a), np.maximum(hi, b)
                changed = True
    return _dedupe(fr, np.nonzero(np.isin(lab, list(obj)))[0])


def _touches(fr, lab, obj, c, px):
    """Some vertex of component c lies within px of some vertex of the object (screen space)."""
    a = fr.xy[lab == c].reshape(-1, 2)
    b = fr.xy[np.isin(lab, list(obj))].reshape(-1, 2)
    if len(a) * len(b) > 4e6:
        b = b[:: max(1, len(a) * len(b) // 4_000_000)]
    return (np.abs(a[:, None, :] - b[None, :, :]).max(-1) <= px).any()


def select_box(fr: Frame, x0, y0, x1, y1, wmin=0.0, wmax=1e9, screen_coords=True) -> np.ndarray:
    """3D triangles whose centroid lies in the box (display-relative coordinates by default) and w range."""
    if screen_coords:
        x0, x1, y0, y1 = x0 + fr.screen[0], x1 + fr.screen[0], y0 + fr.screen[1], y1 + fr.screen[1]
    c = fr.xy.mean(1)
    wm = fr.w.mean(1)
    m = fr.is3d & (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1) & (wm >= wmin) & (wm <= wmax)
    return _dedupe(fr, np.nonzero(m)[0])


# ------------------------------------------------------------------------------------------------ export

def unproject(fr: Frame, tris: np.ndarray, focal: float, center=None) -> np.ndarray:
    """(T,3,3) camera-space points, glTF convention (x right, y up, camera looks down -z)."""
    cx, cy = center if center is not None else (fr.screen[0] + fr.screen[2] / 2, fr.screen[1] + fr.screen[3] / 2)
    xy, w = fr.xy[tris], fr.w[tris]
    X = (xy[..., 0] - cx) * w / focal
    Y = (xy[..., 1] - cy) * w / focal
    return np.stack([X, -Y, -w], -1)


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(b, "PNG")
    return b.getvalue()


def rip(fr: Frame, tris: np.ndarray, out: Path, focal: float = 300.0, height: float | None = 1.7, center=None,
        name: str = "ripped", split_parts: bool = True, face_camera: bool = True) -> dict:
    """Write the selected triangles as a self-contained glTF: one node per connected component (part_NN), materials
    per PS1 texture page/CLUT (decoded from VRAM), untextured triangles coloured through a small palette texture.
    Model space: feet on y=0, centred on x/z, facing +z (toward the camera it was captured from) when face_camera,
    scaled so the bounding height is `height` metres (None keeps captured units)."""
    P = unproject(fr, tris, focal, center)
    flat = P.reshape(-1, 3)
    mid = (flat.min(0) + flat.max(0)) / 2
    P = P - np.array([mid[0], flat[:, 1].min(), mid[2]])
    if face_camera:                                    # camera looked down -z: the front faces +z already
        pass
    s = float(height / (flat[:, 1].max() - flat[:, 1].min())) if height else 1.0
    P = P * s
    # textures: one 256x256 page per key (texture page + CLUT + window), plus a palette for untextured triangles
    keys, pages = {}, []
    for t in tris:
        k = fr.key[t]
        if k is not None:
            kk = k[1:]
            if kk not in keys:
                keys[kk] = len(pages)
                eid, shift, bu, bv, cx, cy, win = k
                pages.append(decode_page(fr.vram[eid], shift, bu, bv, cx, cy, win))
    flat_cols = {}
    for t in tris:
        if fr.key[t] is None:
            c = tuple(np.clip(np.round(fr.col[t, :, :3].mean(0) * 255), 0, 255).astype(int))
            flat_cols.setdefault(c, len(flat_cols))
    pal = None
    if flat_cols:
        n = int(np.ceil(np.sqrt(len(flat_cols))))
        size = 1 << max(3, int(np.ceil(np.log2(max(1, n) * 4))))
        pal = np.zeros((size, size, 4), np.uint8)
        for c, i in flat_cols.items():
            r, q = divmod(i, size // 4)
            pal[r * 4:r * 4 + 4, q * 4:q * 4 + 4, :3] = c
            pal[r * 4:r * 4 + 4, q * 4:q * 4 + 4, 3] = 255
    lab = components(fr, np.isin(np.arange(len(fr.w)), tris)) if split_parts else np.zeros(len(fr.w), int)
    parts = sorted(set(lab[tris].tolist()))
    blob, views, accs = bytearray(), [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    images = [{"uri": "data:image/png;base64," + base64.b64encode(_png(p)).decode(), "name": f"page{i}"} for i, p in enumerate(pages)]
    if pal is not None:
        images.append({"uri": "data:image/png;base64," + base64.b64encode(_png(pal)).decode(), "name": "palette"})
    textures = [{"source": i, "sampler": 0} for i in range(len(images))]
    materials = [{"name": f"page{i}", "pbrMetallicRoughness": {"baseColorTexture": {"index": i}, "metallicFactor": 0.0,
                  "roughnessFactor": 0.9}, "alphaMode": "MASK", "doubleSided": True} for i in range(len(pages))]
    if pal is not None:
        materials.append({"name": "flat", "pbrMetallicRoughness": {"baseColorTexture": {"index": len(pages)},
                          "metallicFactor": 0.0, "roughnessFactor": 0.9}, "doubleSided": True})
    pos_of = {t: P[k] for k, t in enumerate(tris)}
    nodes, meshes, info = [], [], []
    for pi, part in enumerate(parts):
        pt = [t for t in tris if lab[t] == part]
        prims = []
        groups = {}
        for t in pt:
            k = fr.key[t]
            groups.setdefault(keys[k[1:]] if k is not None else -1, []).append(t)
        for mat, ts in groups.items():
            pos = np.concatenate([pos_of[t] for t in ts]).astype(np.float32)
            if mat >= 0:
                uv = np.concatenate([(fr.uv[t] + 0.5) / 256.0 for t in ts]).astype(np.float32)
            else:
                size = pal.shape[0]
                uv = []
                for t in ts:
                    c = tuple(np.clip(np.round(fr.col[t, :, :3].mean(0) * 255), 0, 255).astype(int))
                    r, q = divmod(flat_cols[c], size // 4)
                    uv += [((q * 4 + 2) / size, (r * 4 + 2) / size)] * 3
                uv = np.array(uv, np.float32)
            col = np.concatenate([fr.col[t] for t in ts]).astype(np.float32)
            # winding: PS1 has no consistent winding; emit as captured and mark materials double-sided
            nrm = np.cross(pos[1::3] - pos[0::3], pos[2::3] - pos[0::3])
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
            nrm = np.repeat(nrm, 3, 0).astype(np.float32)
            attrs = {"POSITION": add(pos, 5126, "VEC3", 34962, True), "NORMAL": add(nrm, 5126, "VEC3", 34962),
                     "TEXCOORD_0": add(uv, 5126, "VEC2", 34962), "COLOR_0": add(np.clip(col, 0, 1), 5126, "VEC4", 34962)}
            prims.append({"attributes": attrs, "material": mat if mat >= 0 else len(pages)})
        meshes.append({"name": f"part_{pi:02d}", "primitives": prims})
        pts = np.concatenate([pos_of[t] for t in pt])
        nodes.append({"name": f"part_{pi:02d}", "mesh": pi,
                      "extras": {"tris": len(pt), "centroid": pts.mean(0).tolist(), "min": pts.min(0).tolist(),
                                 "max": pts.max(0).tolist()}})
        info.append({"part": pi, "tris": len(pt), "centroid": [round(float(x), 4) for x in pts.mean(0)]})
    gl = {"asset": {"version": "2.0", "generator": "gbox frame_rip"}, "scene": 0,
          "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes, "materials": materials,
          "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()}],
          "extras": {"frame_rip": {"capture": str(fr.dir), "decoder": fr.decoder, "focal": focal, "screen": fr.screen,
                                    "scale": s, "triangles": int(len(tris))}}}
    if images:
        gl.update(images=images, textures=textures, samplers=[{"magFilter": 9728, "minFilter": 9728}])
    Path(out).write_text(json.dumps(gl))
    return {"out": str(out), "triangles": int(len(tris)), "parts": len(parts), "pages": len(pages),
            "flat_colours": len(flat_cols), "scale": s, "part_info": info}


def show(fr: Frame, out: Path, sel: np.ndarray | None = None, scale: int = 3) -> Path:
    """Debug view of the display rect: 2D primitives grey, 3D triangles coloured by component, selection outlined."""
    from PIL import Image, ImageDraw
    x0, y0, w, h = fr.screen
    im = Image.new("RGB", (int(w * scale), int(h * scale)), (16, 16, 16))
    dr = ImageDraw.Draw(im)
    lab = components(fr)
    rng = np.random.default_rng(1)
    pal = rng.integers(60, 255, (max(1, lab.max() + 1), 3))
    d3 = np.nonzero(fr.is3d)[0]
    for t in list(np.nonzero(~fr.is3d)[0]) + list(d3[np.argsort(-fr.w[d3].mean(1))]):
        pts = [((x - x0) * scale, (y - y0) * scale) for x, y in fr.xy[t]]
        dr.polygon(pts, fill=tuple(int(c) for c in pal[lab[t]]) if lab[t] >= 0 else (70, 70, 70))
    if sel is not None:
        for t in sel:
            pts = [((x - x0) * scale, (y - y0) * scale) for x, y in fr.xy[t]]
            dr.polygon(pts, outline=(255, 255, 255))
    im.save(out)
    return Path(out)


def render_gltf_preview(gltf: Path, out: Path, size: int = 512, yaw_deg=(0, 90, 180)) -> Path:
    """Quick software preview of a frame_rip glTF (textured, z-buffered) from several yaw angles, side by side."""
    from PIL import Image
    gl = json.loads(Path(gltf).read_text())
    buf = base64.b64decode(gl["buffers"][0]["uri"].split(",", 1)[1])

    def acc(i):
        a = gl["accessors"][i]
        v = gl["bufferViews"][a["bufferView"]]
        n = {"VEC2": 2, "VEC3": 3, "VEC4": 4, "SCALAR": 1}[a["type"]]
        return np.frombuffer(buf, "<f4", a["count"] * n, v["byteOffset"]).reshape(a["count"], n)
    texs = [np.array(Image.open(io.BytesIO(base64.b64decode(im["uri"].split(",", 1)[1]))).convert("RGBA"))
            for im in gl.get("images", [])]
    tris = []
    for m in gl["meshes"]:
        for p in m["primitives"]:
            tx = gl["materials"][p["material"]]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
            P, UV = acc(p["attributes"]["POSITION"]), acc(p["attributes"]["TEXCOORD_0"])
            tris.append((P.reshape(-1, 3, 3), UV.reshape(-1, 3, 2), gl["textures"][tx]["source"]))
    allp = np.concatenate([t[0].reshape(-1, 3) for t in tris])
    ctr = (allp.min(0) + allp.max(0)) / 2
    ext = (allp.max(0) - allp.min(0)).max()
    panels = []
    for yaw in yaw_deg:
        a = np.radians(yaw)
        R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
        img = np.full((size, size, 3), 40, np.uint8)
        zb = np.full((size, size), -1e9)
        for P, UV, ti in tris:
            Q = (P - ctr) @ R.T
            sx = (Q[..., 0] / ext * 0.9 + 0.5) * size
            sy = (0.5 - Q[..., 1] / ext * 0.9) * size
            tex = texs[ti]
            th, tw = tex.shape[:2]
            for k in range(len(Q)):
                xs, ys, zs = sx[k], sy[k], Q[k, :, 2]
                xa, xb = int(max(0, np.floor(xs.min()))), int(min(size - 1, np.ceil(xs.max())))
                ya, yb = int(max(0, np.floor(ys.min()))), int(min(size - 1, np.ceil(ys.max())))
                if xa > xb or ya > yb:
                    continue
                X, Y = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
                d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
                if abs(d) < 1e-9:
                    continue
                l0 = ((ys[1] - ys[2]) * (X - xs[2]) + (xs[2] - xs[1]) * (Y - ys[2])) / d
                l1 = ((ys[2] - ys[0]) * (X - xs[2]) + (xs[0] - xs[2]) * (Y - ys[2])) / d
                l2 = 1 - l0 - l1
                m = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
                if not m.any():
                    continue
                z = l0 * zs[0] + l1 * zs[1] + l2 * zs[2]
                u = l0 * UV[k, 0, 0] + l1 * UV[k, 1, 0] + l2 * UV[k, 2, 0]
                v = l0 * UV[k, 0, 1] + l1 * UV[k, 1, 1] + l2 * UV[k, 2, 1]
                c = tex[np.clip((v * th).astype(int), 0, th - 1), np.clip((u * tw).astype(int), 0, tw - 1)]
                m &= c[..., 3] > 0
                yy, xx = np.nonzero(m)
                zz = z[m]
                gy, gx = yy + ya, xx + xa
                closer = zz > zb[gy, gx]
                zb[gy[closer], gx[closer]] = zz[closer]
                img[gy[closer], gx[closer]] = c[m][closer][:, :3]
        panels.append(img)
    Image.fromarray(np.concatenate(panels, 1)).save(out)
    return Path(out)


# ------------------------------------------------------------------------------------------------ CLI

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="gbox.frame_rip", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("launch"); a.add_argument("content"); a.add_argument("--core", default="mednafen_psx_hw")
    a.add_argument("--work", default=str(Path(tempfile.gettempdir()) / "gbox-frame-rip"))
    a = sub.add_parser("capture"); a.add_argument("--pid", type=int, default=0); a.add_argument("--frames", type=int, default=3)
    a.add_argument("--cap-dir")
    a = sub.add_parser("extract"); a.add_argument("rdc"); a.add_argument("--out")
    a = sub.add_parser("show"); a.add_argument("dump"); a.add_argument("--out", default="frame_rip_show.png")
    a.add_argument("--pick")
    a = sub.add_parser("rip"); a.add_argument("dump"); a.add_argument("--pick", help="x,y in display pixels")
    a.add_argument("--box", help="x0,y0,x1,y1 in display pixels"); a.add_argument("--focal", type=float, default=300.0)
    a.add_argument("--height", type=float, default=1.7); a.add_argument("--depth-tol", type=float, default=0.12)
    a.add_argument("--out", default="ripped.gltf"); a.add_argument("--preview")
    a = sub.add_parser("chd2bin"); a.add_argument("chd"); a.add_argument("bin")
    a = sub.add_parser("nocull", help="list / apply PS1 back-face cull patches in a running RetroArch")
    a.add_argument("disc"); a.add_argument("--apply", action="store_true"); a.add_argument("--restore", action="store_true")
    a.add_argument("--all", action="store_true", help="also bgtz/bgez sites (made unconditional); default blez/bltz")
    a.add_argument("--port", type=int, default=55433)
    ns = ap.parse_args(argv)
    if ns.cmd == "launch":
        p = launch(ns.content, Path(ns.work), ns.core)
        print(json.dumps({"pid": p.pid, "work": ns.work}))
    elif ns.cmd == "capture":
        print("\n".join(map(str, capture(ns.pid, ns.frames, Path(ns.cap_dir) if ns.cap_dir else None))))
    elif ns.cmd == "extract":
        out = Path(ns.out or Path(ns.rdc).with_suffix(""))
        print(extract(Path(ns.rdc), out))
    elif ns.cmd == "show":
        fr = load(Path(ns.dump))
        sel = pick(fr, *map(float, ns.pick.split(","))) if ns.pick else None
        print(show(fr, Path(ns.out), sel), "screen", fr.screen, "3d tris", int(fr.is3d.sum()))
    elif ns.cmd == "rip":
        fr = load(Path(ns.dump))
        if ns.box:
            sel = select_box(fr, *map(float, ns.box.split(",")))
        else:
            sel = pick(fr, *map(float, ns.pick.split(",")), depth_tol=ns.depth_tol)
        r = rip(fr, sel, Path(ns.out), ns.focal, ns.height)
        if ns.preview:
            render_gltf_preview(Path(ns.out), Path(ns.preview))
        print(json.dumps({k: v for k, v in r.items() if k != "part_info"}))
    elif ns.cmd == "chd2bin":
        print(psx_chd_to_bin(Path(ns.chd), Path(ns.bin)))
    elif ns.cmd == "nocull":
        name, exe = psx_boot_exe(Path(ns.disc))
        sites = [s for s in psx_cull_sites(exe) if ns.all or s["kind"] in ("blez", "bltz")]
        if ns.apply or ns.restore:
            sites = psx_disable_cull(sites, ns.port, ns.restore)
        for s in sites:
            print(name, f"nclip {s['nclip']:08x} {s['kind']} r{s['reg']} @ {s['addr']:08x}",
                  s.get("skipped") or ("ok" if s.get("ok") else ""))


if __name__ == "__main__":
    main()
