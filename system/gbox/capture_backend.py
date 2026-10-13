"""Examine 3D capture sessions (#971 stage 2): which graphics backend an agent-owned capture session runs, and how
RenderDoc gets inside it.

A capture session is a second copy of the operator's game, started by gBox only to capture one frame (see
gbox/scene_relay.py). It never reuses the operator's own config files: every override below is written into the
capture session's own config dir, or passed on its command line (Dolphin's -C layer), and nothing is saved back.

Vulkan first. For a Vulkan backend RenderDoc enters through its Vulkan layer, loaded by the Vulkan loader from the
RenderDoc folder's renderdoc.json manifest (environment only: no process injection, no registry change). The
injection path (scene_capture.popen_hooked) stays for Direct3D, and for core-profile GL (glcore) when a core has no
Vulkan renderer: RenderDoc's injection breaks RetroArch's compatibility-profile `gl` window, not glcore.

plan(adapter, core) -> {"driver", "attach": "layer" | "inject", "core_options", "ra_cfg", "verified", "note"} or None
layer_env(renderdoc_dir, capture_template) -> the environment that loads RenderDoc's Vulkan layer into one process

Pure data + path logic: safe to import anywhere (server, tests).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LAYER_NAME = "VK_LAYER_RENDERDOC_Capture"

# libretro core -> core options that select its Vulkan renderer (most cores follow RetroArch's video_driver by
# themselves; these pin the ones with their own renderer switch). Keys were read from the core DLLs on the test PC.
VULKAN_CORE_OPTIONS = {
    "flycast": {},                                                       # follows the frontend's HW context
    "mednafen_psx_hw": {"beetle_psx_hw_renderer": "hardware_vk"},
    "beetle_psx_hw": {"beetle_psx_hw_renderer": "hardware_vk"},
    "pcsx2": {"pcsx2_renderer": "Vulkan"},
    "lrps2": {},                                                         # LRPS2 follows the frontend's HW context
    "dolphin": {"dolphin_renderer": "Hardware"},                         # the frontend's context = Vulkan
    "citra": {"citra_graphics_api": "Vulkan"},
    "swanstation": {"swanstation_GPU_Renderer": "Vulkan"},
    "duckstation": {"duckstation_GPU.Renderer": "Vulkan"},
    "ppsspp": {"ppsspp_backend": "vulkan"},
    "panda3ds": {},
}
# N64: ParaLLEl-RDP (the Vulkan path) rasterizes in compute shaders, so a capture has no vertex draw calls to rebuild.
# N64 capture sessions use an HLE renderer that draws real triangles, on core-profile GL with RenderDoc injected.
HLE_GL_CORE_OPTIONS = {
    "parallel_n64": {"parallel-n64-gfxplugin": "glide64", "parallel-n64-rspplugin": "hle"},
    "mupen64plus_next": {"mupen64plus-rdp-plugin": "gliden64", "mupen64plus-rsp-plugin": "hle"},
}
# cores whose Vulkan capture was run end to end on the test PC (docs/examine_emulators.md, live checks)
LIVE_CHECKED: set[str] = set()

# RetroArch settings for every capture session: no sound, no pad, no shader presets (GL .glslp), no rewind ring,
# a normal (not minimized) window that gBox parks off-screen, and nothing written back on exit.
RA_CAPTURE_CFG = {
    "audio_enable": "false", "audio_driver": "null", "input_joypad_driver": "null", "input_autodetect_enable": "false",
    "network_remote_enable": "false", "video_shader_enable": "false", "rewind_enable": "false",
    "video_fullscreen": "false", "video_windowed_fullscreen": "false", "pause_nonactive": "false",
    "config_save_on_exit": "false", "savestate_auto_load": "false", "savestate_auto_save": "false",
    "video_vsync": "true", "sort_savestates_enable": "false", "sort_savestates_by_content_enable": "false",
    "savestates_in_content_dir": "false", "savefiles_in_content_dir": "false", "sort_savefiles_enable": "false",
}

# standalone emulators: adapter -> (driver, how the backend is chosen for the capture session only)
STANDALONE = {
    "dolphin": ("vulkan", "-C Dolphin.Core.GFXBackend=Vulkan (command-line layer, not saved)"),
    "rpcs3": ("vulkan", "Video: Renderer: Vulkan in the capture session's own RPCS3 home (custom config)"),
    "yuzu": ("vulkan", "Yuzu's default renderer is Vulkan; RenderDoc's Vulkan layer is added by environment"),
}


def plan(adapter: str, core: str | None = None) -> dict | None:
    """The capture-session backend for an emulator (None: no 3D capture path at all)."""
    from .scene_support import GL_ONLY_CORES, SOFTWARE_CORES, VULKAN_CORES, core_name
    adapter = (adapter or "").lower()
    if adapter == "retroarch":
        c = core_name(core)
        if c in SOFTWARE_CORES:
            return None
        if c in GL_ONLY_CORES or c in HLE_GL_CORE_OPTIONS:
            return {"driver": "glcore", "attach": "inject", "core_options": dict(HLE_GL_CORE_OPTIONS.get(c, {})),
                    "ra_cfg": {"video_driver": "glcore"}, "verified": False,
                    "note": "core-profile GL with RenderDoc injected" + (" (HLE renderer: ParaLLEl-RDP's Vulkan "
                            "compute rasterizer has no draw calls)" if c in HLE_GL_CORE_OPTIONS else
                            " (no Vulkan renderer)")}
        known = c in VULKAN_CORES or c in VULKAN_CORE_OPTIONS
        return {"driver": "vulkan", "attach": "layer", "core_options": dict(VULKAN_CORE_OPTIONS.get(c, {})),
                "ra_cfg": {"video_driver": "vulkan"}, "verified": c in LIVE_CHECKED,
                "note": "RetroArch video_driver=vulkan + RenderDoc's Vulkan layer" + ("" if known else
                        f" (the {c or 'unknown'} core is not in the matrix: Vulkan is tried first)")}
    if adapter in STANDALONE:
        driver, note = STANDALONE[adapter]
        return {"driver": driver, "attach": "layer", "core_options": {}, "ra_cfg": {}, "verified": False, "note": note}
    return None


def manifest(rd_dir: Path) -> dict:
    """RenderDoc's Vulkan layer manifest (renderdoc.json next to renderdoc.dll in the portable zip)."""
    p = Path(rd_dir) / "renderdoc.json"
    if not p.is_file():
        raise FileNotFoundError(f"RenderDoc's Vulkan layer manifest is missing: {p}")
    layer = json.loads(p.read_text(encoding="utf-8")).get("layer") or {}
    if layer.get("name") != LAYER_NAME:
        raise ValueError(f"{p} is not RenderDoc's capture layer ({layer.get('name')!r})")
    return {"path": str(p), "name": layer["name"], "enable": dict(layer.get("enable_environment") or {}),
            "disable": dict(layer.get("disable_environment") or {}), "version": layer.get("implementation_version")}


def layer_env(rd_dir: Path, capture_template: Path | str | None = None, base: dict | None = None) -> dict:
    """Environment that makes the Vulkan loader load RenderDoc's layer into one process (and its children).

    * implicit layer: VK_ADD_IMPLICIT_LAYER_PATH + the manifest's enable_environment (ENABLE_VULKAN_RENDERDOC_CAPTURE=1)
    * explicit fallback for older loaders: VK_ADD_LAYER_PATH / VK_LAYER_PATH + VK_INSTANCE_LAYERS
    * the manifest's disable_environment is removed (a stale DISABLE_VULKAN_RENDERDOC_CAPTURE_x would veto it)
    * RENDERDOC_CAPFILE: RenderDoc's capture path template for this process (read when renderdoc.dll initialises)
    `base` (default os.environ) is copied, never modified."""
    m = manifest(rd_dir)
    env = dict(os.environ if base is None else base)
    for k in list(env):
        if k in m["disable"] or k.upper().startswith("DISABLE_VULKAN_RENDERDOC_CAPTURE"):
            env.pop(k)
    rd = str(Path(rd_dir))

    def add_path(key):
        cur = [x for x in (env.get(key) or "").split(os.pathsep) if x and x != rd]
        env[key] = os.pathsep.join([rd, *cur])
    add_path("VK_ADD_IMPLICIT_LAYER_PATH")
    add_path("VK_ADD_LAYER_PATH")
    add_path("VK_LAYER_PATH")
    layers = [x for x in (env.get("VK_INSTANCE_LAYERS") or "").split(os.pathsep) if x and x != LAYER_NAME]
    env["VK_INSTANCE_LAYERS"] = os.pathsep.join([LAYER_NAME, *layers])
    env.update(m["enable"] or {"ENABLE_VULKAN_RENDERDOC_CAPTURE": "1"})
    if capture_template:
        Path(capture_template).parent.mkdir(parents=True, exist_ok=True)
        env["RENDERDOC_CAPFILE"] = str(capture_template)
    return env


def retroarch_cfg(base: dict, p: dict, work: Path) -> dict:
    """The capture session's retroarch.cfg values: the session's normal settings, then the capture backend and
    RA_CAPTURE_CFG, with its own state/save folders and core options file under `work`."""
    work = Path(work)
    out = dict(base)
    out.update(RA_CAPTURE_CFG)
    out.update(p.get("ra_cfg") or {})
    out.update({"savestate_directory": str(work / "states"), "savefile_directory": str(work / "saves"),
                "screenshot_directory": str(work / "shots"), "core_options_path": str(work / "core-options.cfg"),
                "global_core_options": "true"})
    return out


def core_options_file(shared: Path, p: dict, work: Path) -> Path:
    """Copy the operator's core options (read only) into the capture session's dir and pin its Vulkan renderer."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    dst = work / "core-options.cfg"
    lines = Path(shared).read_text(errors="replace").splitlines() if Path(shared).is_file() else []
    over = p.get("core_options") or {}
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in over]
    dst.write_text("\n".join(lines + [f'{k} = "{v}"' for k, v in over.items()]) + "\n")
    return dst


def rpcs3_renderer_yaml(text: str, renderer: str = "Vulkan") -> str:
    """Set Video: Renderer in an RPCS3 (custom) config YAML text, keeping every other line."""
    lines = text.splitlines()
    out, in_video, done = [], False, False
    for ln in lines:
        if ln and not ln.startswith(" "):
            if in_video and not done:
                out.append(f"  Renderer: {renderer}")
                done = True
            in_video = ln.rstrip() == "Video:"
        if in_video and ln.strip().startswith("Renderer:"):
            if not done:
                out.append(f"  Renderer: {renderer}")
                done = True
            continue
        out.append(ln)
    if in_video and not done:
        out.append(f"  Renderer: {renderer}")
        done = True
    if not done:
        out += ["Video:", f"  Renderer: {renderer}"]
    return "\n".join(out) + "\n"


def yuzu_backend(qt_config: Path) -> str | None:
    """Yuzu's configured renderer from qt-config.ini ([Renderer] backend: 0 OpenGL, 1 Vulkan, 2 Null)."""
    try:
        text = Path(qt_config).read_text(errors="replace")
    except OSError:
        return None
    section = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("["):
            section = s
        elif section == "[Renderer]" and s.startswith("backend=") and "\\" not in s.split("=", 1)[0]:
            return {"0": "opengl", "1": "vulkan", "2": "null"}.get(s.split("=", 1)[1].strip(), s.split("=", 1)[1].strip())
    return "vulkan"                                                      # not set: Yuzu's default
