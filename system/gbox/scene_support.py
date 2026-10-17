"""Examine 3D capability matrix (#971): can THIS session's frame be rebuilt as a 3D scene, and if not, why.

support(adapter, core, driver) -> {"status": "supported" | "relaunch_under_capture" | "unsupported", "reason", "driver",
"attach", "relay", "verified", "fallback", "adapter", "core"}

* supported: RenderDoc captures this renderer as it runs (a Direct3D/Vulkan RetroArch core with RenderDoc inside,
  Dolphin on Vulkan, Yuzu / RPCS3 on Vulkan with RenderDoc's Vulkan layer).
* relaunch_under_capture: capturable in a capture session. `driver` names the backend it runs ("vulkan" first,
  "glcore" for GL-only cores), `attach` how RenderDoc gets in ("layer" = RenderDoc's Vulkan layer, no injection;
  "inject" = renderdoc.dll loaded at process start). `relay` = True: *Capture again* keeps the operator's game
  running and captures the same moment in an agent-owned capture session (save state -> capture session on the test
  PC or this PC -> load state -> capture -> GLB back to the panel; gbox/scene_relay.py). `relay` = False: the
  emulator's state can't be carried, so the game itself has to be relaunched with Examine 3D on.
  Backend overrides belong to the capture session only (gbox/capture_backend.py), never the operator's own config.
* unsupported: no 3D capture path; `fallback` = "frame_2d" (the live frame, labelled 2D-only).

`verified` = the capture path was run end to end on the test PC (docs/examine_emulators.md, live checks).

Pure data + string logic: no RenderDoc, no Windows APIs, safe to import anywhere (server, UI payloads, tests).
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

SUPPORTED, RELAUNCH, UNSUPPORTED = "supported", "relaunch_under_capture", "unsupported"
CAPTURE_DRIVERS = ("d3d11", "d3d12", "vulkan")          # RenderDoc injection keeps the RetroArch window working

# libretro cores with a hardware Vulkan renderer: run the capture session with video_driver=vulkan (no GL window).
VULKAN_CORES = {"flycast", "mednafen_psx_hw", "beetle_psx_hw", "dolphin", "citra", "swanstation", "ppsspp",
                "duckstation", "panda3ds"}
# PS2 (pcsx2_libretro = LRPS2): its Vulkan renderer aborts on the test PC; capture sessions use D3D11 + injection.
D3D_CORES = {"pcsx2", "lrps2"}
# hardware 3D cores with only an OpenGL renderer: core-profile GL (glcore) is the second choice, not live-checked yet.
GL_ONLY_CORES = {"kronos", "yabasanshiro", "melonds", "play", "mame2016_gl", "reicast_gl", "citra_canary_gl"}
# N64: the Vulkan RDP (ParaLLEl-RDP) has no vertex draw calls; captures need an HLE renderer on core-profile GL.
# Mupen64Plus-Next's GLideN64 asks for a core context (glcore); ParaLLEl N64's HLE plugins ask for a compatibility
# context, which stalls under glcore and which RenderDoc can't capture (test PC, 2026-10-13): 2D frame only.
N64_HLE_CORES = {"mupen64plus_next"}
N64_NO_SCENE = {"parallel_n64"}
# software renderers: the frame is one 2D blit, a draw-call capture has no scene in it.
SOFTWARE_CORES = {"snes9x", "snes9x2010", "bsnes", "bsnes_hd_beta", "mesen", "mesen-s", "fceumm", "nestopia",
                  "genesis_plus_gx", "picodrive", "mgba", "gambatte", "sameboy", "gearboy", "vba_next", "vbam",
                  "fbneo", "fbalpha2012", "mame", "mame2003_plus", "mame2010", "stella", "stella2014", "prosystem",
                  "handy", "mednafen_pce", "mednafen_pce_fast", "mednafen_supergrafx", "mednafen_ngp", "mednafen_wswan",
                  "mednafen_vb", "mednafen_lynx", "mednafen_saturn", "beetle_saturn", "yabause", "mednafen_psx",
                  "pcsx_rearmed", "neocd", "opera", "4do", "virtualjaguar", "desmume", "desmume2015", "bluemsx",
                  "fmsx", "puae", "vice_x64", "dosbox_pure", "quasi88", "np2kai", "pokemini", "o2em", "freechaf",
                  "gearsystem", "smsplus", "potator", "atari800", "cap32", "tgbdual", "gpsp", "meteor"}
LIVE_CHECKED = {("retroarch", "flycast"), ("retroarch", "ppsspp")}   # capture session run end to end on the test PC

_WIN_ONLY = "3D draw-call capture runs on a Windows node (RenderDoc)."
_RELAY = (" Capture again saves your moment, captures it in a separate agent-owned capture session (test PC first, "
          "else a hidden copy on this PC) and brings the 3D scene back here; your game keeps running.")
_UNSUPPORTED = {
    "xenia": "Xenia has no RenderDoc capture path in gBox; only the 2D frame is available.",
    "steam": "PC games are not launched under RenderDoc by gBox; only the 2D frame is available.",
    "rocketlauncher": "RocketLauncher starts its own emulators outside gBox, so RenderDoc can't be placed inside "
                      "them; only the 2D frame is available.",
    "mgba": "mGBA renders in software (2D frame only).",
    "duckstation": "The DuckStation debug session runs on Linux without RenderDoc capture.",
    "mame": "MAME renders in software (2D frame only).",
    "command": "Custom command emulators have no RenderDoc integration; only the 2D frame is available.",
}
_VULKAN_STANDALONE = {"yuzu": "Yuzu", "rpcs3": "RPCS3"}


def core_name(core: str | None) -> str:
    """'C:/.../flycast_libretro.dll' | 'flycast_libretro' | 'flycast' -> 'flycast'."""
    if not core:
        return ""
    n = Path(str(core).replace("\\", "/")).name.lower()
    n = re.sub(r"\.(dll|so|dylib)$", "", n)
    return re.sub(r"_libretro(_android)?$", "", n)


def _out(status, reason, driver=None, adapter="", core="", *, attach=None, relay=False):
    return {"status": status, "reason": reason, "driver": driver, "attach": attach, "relay": relay,
            "verified": (adapter, core) in LIVE_CHECKED or (adapter, "") in LIVE_CHECKED,
            "fallback": "frame_2d" if status != SUPPORTED else None, "adapter": adapter, "core": core}


def _matrix(adapter: str, core: str | None = None, driver: str | None = None, *, hooked: bool | None = None,
            host_os: str | None = None) -> dict:
    """The matrix row for one session. `driver` = the renderer the session runs now (RetroArch video_driver, or the
    standalone emulator's backend: "opengl" disables the Vulkan layer route); `hooked` = RenderDoc is inside the
    process (None: unknown, e.g. before launch)."""
    host_os = host_os or ("windows" if sys.platform == "win32" else "linux")
    adapter = (adapter or "").lower()
    c = core_name(core)
    drv = (driver or "").lower() or None
    if host_os != "windows":
        return _out(UNSUPPORTED, _WIN_ONLY, None, adapter, c)
    if adapter == "retroarch":
        if c in SOFTWARE_CORES:
            return _out(UNSUPPORTED, f"The {c} core renders in software: the frame is a 2D image with no 3D scene "
                        "to capture (2D frame only).", None, adapter, c)
        if c in N64_NO_SCENE:
            return _out(UNSUPPORTED, f"The {c} core has no capturable 3D path: its Vulkan renderer (ParaLLEl-RDP) "
                        "rasterizes in compute shaders with no draw calls, its angrylion renderer is software, and its "
                        "OpenGL plugins need a compatibility context RenderDoc can't capture (2D frame only; "
                        "Mupen64Plus-Next with GLideN64 is the N64 core with a capture path).", None, adapter, c)
        if drv in CAPTURE_DRIVERS:
            if hooked is False:
                cap = ("vulkan" if c in VULKAN_CORES else "glcore" if c in N64_HLE_CORES else
                       "d3d11" if c in D3D_CORES else drv)
                return _out(RELAUNCH, f"This session was started without RenderDoc inside (Examine 3D was off at "
                            f"launch).{_RELAY} The capture session renders with {cap}.", cap, adapter, c,
                            attach="layer" if cap == "vulkan" else "inject", relay=True)
            return _out(SUPPORTED, f"RetroArch {drv} renderer: RenderDoc captures it.", None, adapter, c)
        if c in D3D_CORES:
            return _out(RELAUNCH, f"This RetroArch session renders with {drv or 'OpenGL'}, which RenderDoc can't open "
                        f"a window for.{_RELAY} The capture session renders the {c} core with Direct3D 11 and "
                        "RenderDoc injected (its Vulkan renderer fails on the test PC).", "d3d11", adapter, c,
                        attach="inject", relay=True)
        if c in GL_ONLY_CORES or c in N64_HLE_CORES:
            why = (f"The {c} core only renders with OpenGL" if c in GL_ONLY_CORES else
                   f"The {c} core's Vulkan renderer (ParaLLEl-RDP) rasterizes in compute shaders with no draw calls")
            return _out(RELAUNCH, f"{why}, and RenderDoc can't open RetroArch's compatibility GL window.{_RELAY} "
                        "The capture session runs core-profile GL (glcore) with RenderDoc injected (not live-checked "
                        "yet).", "glcore", adapter, c, attach="inject", relay=True)
        known = c in VULKAN_CORES or not c
        return _out(RELAUNCH, f"This RetroArch session renders with {drv or 'OpenGL'}, which RenderDoc can't open a "
                    f"window for; the {c or 'core'} core " + ("has a Vulkan renderer" if known else
                    "is not in the capture matrix yet, so Vulkan is tried first") + f".{_RELAY} The capture session "
                    "runs video_driver=vulkan with RenderDoc's Vulkan layer (no injection; your settings are not "
                    "changed).", "vulkan", adapter, c, attach="layer", relay=True)
    if adapter == "dolphin":
        if hooked is False:
            return _out(RELAUNCH, "This Dolphin session was started without RenderDoc inside." + _RELAY +
                        " The capture session renders with Dolphin's Vulkan backend (a -C override for that session "
                        "only) under RenderDoc's Vulkan layer.", "vulkan", adapter, c, attach="layer", relay=True)
        return _out(SUPPORTED, "Dolphin renders with Vulkan; RenderDoc captures it.", None, adapter, c)
    if adapter in _VULKAN_STANDALONE:
        name = _VULKAN_STANDALONE[adapter]
        if drv and drv != "vulkan":
            return _out(UNSUPPORTED, f"{name} is set to render with {drv}; 3D capture needs its Vulkan renderer "
                        f"(set the graphics API to Vulkan in {name}, then relaunch with Examine 3D on). The 2D frame "
                        "is still available.", "vulkan", adapter, c, attach="layer")
        if hooked is False:
            return _out(RELAUNCH, f"This {name} session was started without RenderDoc's Vulkan layer (Examine 3D was "
                        f"off at launch). {name} save states can't be carried into a capture session, so relaunch "
                        "the game with Examine 3D on (save in-game first).", "vulkan", adapter, c, attach="layer")
        return _out(SUPPORTED, f"{name} renders with Vulkan and starts with RenderDoc's Vulkan layer (no injection); "
                    "RenderDoc captures it.", None, adapter, c, attach="layer")
    reason = _UNSUPPORTED.get(adapter, f"{adapter or 'This emulator'} has no 3D capture path in gBox yet; only the 2D "
                              "frame is available.")
    return _out(UNSUPPORTED, reason, None, adapter, c)


_NAMES = {**_VULKAN_STANDALONE, "dolphin": "Dolphin", "retroarch": "RetroArch"}
LAYER_PENDING_MAX_S = 300           # a layer-started emulator gets this long to create its Vulkan device (game boot)


def support(adapter: str, core: str | None = None, driver: str | None = None, *, hooked: bool | None = None,
            host_os: str | None = None, layer: str | None = None) -> dict:
    """The matrix row for one session (_matrix). `layer` (#971, Vulkan layer route): "pending" = started with
    RenderDoc's Vulkan layer, which the loader maps only once the emulator creates its Vulkan device (Yuzu / RPCS3 do
    that after the game boots, later than the launch check), so it may still load; "missed" = it never loaded within
    LAYER_PENDING_MAX_S. Neither case is "Examine 3D was off at launch"."""
    row = _matrix(adapter, core, driver, hooked=None if layer == "pending" else hooked, host_os=host_os)
    name = _NAMES.get((adapter or "").lower(), adapter or "The emulator")
    if layer == "pending" and row["status"] == SUPPORTED:
        row.update(layer="pending", attach="layer", reason=(
            f"{name} was started with Examine 3D on. RenderDoc's Vulkan layer loads when {name} creates its Vulkan "
            "device, once the game has booted; 3D capture works from then on (this row updates by itself)."))
    elif layer == "missed" and row["status"] == RELAUNCH:
        row.update(layer="missed", reason=(
            f"This {name} session was started with Examine 3D on, but RenderDoc's Vulkan layer never loaded: {name} "
            f"made no Vulkan device within {LAYER_PENDING_MAX_S // 60} minutes of launch. " + (
                "Capture again runs this moment in a separate capture session." if row.get("relay") else
                f"Check that {name} renders with Vulkan, then relaunch the game with Examine 3D on (save in-game "
                "first).")))
    return row


def layer_state(proc, info: dict) -> tuple:
    """(layer, hooked) for a process started with RenderDoc's Vulkan layer (#971). A live process is re-checked now
    (the launch check gives up after 10-15 s, before Yuzu has booted the game and made its Vulkan device); one still
    inside LAYER_PENDING_MAX_S of its start is "pending", past that "missed". A process that was never probed keeps the
    old answer (RenderDoc counted as inside)."""
    alive = callable(getattr(proc, "poll", None)) and getattr(proc, "pid", None) is not None and proc.poll() is None
    loaded = info.get("loaded")
    if not loaded and alive:
        try:
            from .scene_capture import layer_check
            loaded = layer_check(proc, 0)
        except Exception:                                  # noqa: BLE001 - a failed probe keeps the last answer
            loaded = info.get("loaded")
    if loaded or "loaded" not in info:
        return None, True
    started = info.get("started")
    if alive and started:
        return ("pending", None) if time.time() - float(started) < LAYER_PENDING_MAX_S else ("missed", False)
    return None, False


def session_support(ad, host_os: str | None = None) -> dict:
    """The matrix row for a live adapter instance (tools.SESSIONS)."""
    proc = getattr(ad, "proc", None)
    info = getattr(proc, "renderdoc", None) if proc is not None else None
    hooked = (bool(info) and "error" not in info) if proc is not None else None
    layer = None
    if hooked and isinstance(info, dict) and info.get("attach") == "layer":
        layer, hooked = layer_state(proc, info)           # the Vulkan loader only loads the layer for a Vulkan device
    cfg = getattr(ad, "cfg", None)
    core = getattr(cfg, "core", None) if cfg is not None else None
    return support(getattr(ad, "name", "") or "", getattr(ad, "core_path", None) or core,
                   getattr(ad, "video_driver", None), hooked=hooked, host_os=host_os, layer=layer)


def video_driver(argv) -> str | None:
    """RetroArch's video_driver from the --config file on its command line."""
    if "--config" not in argv:
        return None
    try:
        cfg = Path(argv[argv.index("--config") + 1]).read_text(errors="replace")
    except (OSError, IndexError):
        return None
    m = re.search(r'^video_driver\s*=\s*"([^"]*)"', cfg, re.M)
    return m.group(1) if m else None


MATRIX_DOC = """\
| Emulator / core | Status | Capture session | RenderDoc | Notes |
|---|---|---|---|---|
| RetroArch, D3D11/D3D12/Vulkan session with Examine 3D on | supported | (current) | injected at launch | |
| RetroArch, D3D/Vulkan session started without Examine 3D | relaunch_under_capture (relay) | vulkan for Vulkan-capable cores, else the same driver | layer / injected | game keeps running |
| RetroArch, GL session of a Vulkan-capable core (Flycast, Beetle PSX HW, Dolphin, Citra, SwanStation, DuckStation, PPSSPP) | relaunch_under_capture (relay) | vulkan | Vulkan layer | Flycast + PPSSPP live-checked |
| RetroArch PS2 (pcsx2 / LRPS2) | supported with Examine 3D on (D3D11); relay otherwise | d3d11 | injected | Vulkan aborts; D3D11 capture held no GS draws on the test PC |
| RetroArch, GL-only 3D core (Kronos, YabaSanshiro, melonDS, Play!) | relaunch_under_capture (relay) | glcore | injected | not live-checked |
| RetroArch N64, Mupen64Plus-Next | relaunch_under_capture (relay) | glcore + GLideN64 | injected | not live-checked |
| RetroArch N64, ParaLLEl N64 | unsupported | - | - | no draw calls (ParaLLEl-RDP) / compat GL; 2D frame only |
| RetroArch, software core (Snes9x, Genesis Plus GX, mGBA, FBNeo, ...) | unsupported | - | - | 2D frame only |
| Dolphin (Windows, Vulkan) with Examine 3D on | supported | (current) | injected at launch | |
| Dolphin started without Examine 3D | relaunch_under_capture (relay) | vulkan (-C Dolphin.Core.GFXBackend=Vulkan) | Vulkan layer | test PC only; capture held 1 draw (open) |
| Yuzu / RPCS3 on Vulkan with Examine 3D on | supported | (current) | Vulkan layer at launch | |
| Yuzu / RPCS3 started without Examine 3D | relaunch_under_capture | relaunch the game | Vulkan layer | states can't be carried |
| Yuzu / RPCS3 set to OpenGL | unsupported | - | - | switch the emulator to Vulkan |
| Xenia, Steam, RocketLauncher, Linux sessions | unsupported | - | - | 2D frame only |
"""
