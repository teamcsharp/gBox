"""Examine 3D capability matrix (#971): can THIS session's frame be rebuilt as a 3D scene, and if not, why.

support(adapter, core, driver) -> {"status": "supported" | "relaunch_under_capture" | "unsupported", "reason", "driver",
"fallback", "adapter", "core"}

* supported: RenderDoc can capture this renderer as it runs (a Direct3D/Vulkan RetroArch core, Dolphin on D3D12).
* relaunch_under_capture: capturable after a relaunch. `driver` names the backend the capture session must use
  ("vulkan" first, "glcore" for GL-only cores); `driver` is None when the same renderer just needs RenderDoc inside
  (the session started without Examine 3D). A backend override belongs to an agent-owned capture session only,
  never the operator's own config.
* unsupported: no 3D capture path today; `fallback` = "frame_2d" (the still frame / frame dump, labelled 2D-only).

Pure data + string logic: no RenderDoc, no Windows APIs, safe to import anywhere (server, UI payloads, tests).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SUPPORTED, RELAUNCH, UNSUPPORTED = "supported", "relaunch_under_capture", "unsupported"
CAPTURE_DRIVERS = ("d3d11", "d3d12", "vulkan")          # RenderDoc injection keeps the RetroArch window working

# libretro cores with a hardware Vulkan renderer: run the capture session with video_driver=vulkan (no GL window).
VULKAN_CORES = {"flycast", "parallel_n64", "mupen64plus_next", "mednafen_psx_hw", "beetle_psx_hw", "pcsx2", "lrps2",
                "dolphin", "citra", "swanstation", "ppsspp", "duckstation", "panda3ds"}
# hardware 3D cores with only an OpenGL renderer: core-profile GL (glcore) is the second choice, not live-checked yet.
GL_ONLY_CORES = {"kronos", "yabasanshiro", "melonds", "play", "mame2016_gl", "reicast_gl", "citra_canary_gl"}
# software renderers: the frame is one 2D blit, a draw-call capture has no scene in it.
SOFTWARE_CORES = {"snes9x", "snes9x2010", "bsnes", "bsnes_hd_beta", "mesen", "mesen-s", "fceumm", "nestopia",
                  "genesis_plus_gx", "picodrive", "mgba", "gambatte", "sameboy", "gearboy", "vba_next", "vbam",
                  "fbneo", "fbalpha2012", "mame", "mame2003_plus", "mame2010", "stella", "stella2014", "prosystem",
                  "handy", "mednafen_pce", "mednafen_pce_fast", "mednafen_supergrafx", "mednafen_ngp", "mednafen_wswan",
                  "mednafen_vb", "mednafen_lynx", "mednafen_saturn", "beetle_saturn", "yabause", "mednafen_psx",
                  "pcsx_rearmed", "neocd", "opera", "4do", "virtualjaguar", "desmume", "desmume2015", "bluemsx",
                  "fmsx", "puae", "vice_x64", "dosbox_pure", "quasi88", "np2kai", "pokemini", "o2em", "freechaf",
                  "gearsystem", "smsplus", "potator", "atari800", "cap32", "tgbdual", "gpsp", "meteor"}

_WIN_ONLY = "3D draw-call capture runs on a Windows node (RenderDoc)."
_STANDALONE = {
    # adapter name -> (status, driver, reason) on a Windows node
    "dolphin": (SUPPORTED, None, "Dolphin renders with Direct3D 12; RenderDoc captures it."),
    "yuzu": (UNSUPPORTED, "vulkan", "3D draw-call capture is not integrated with the Yuzu window yet "
             "(planned: Yuzu's Vulkan backend under RenderDoc's Vulkan layer in an agent-owned capture session)."),
    "rpcs3": (UNSUPPORTED, "vulkan", "3D draw-call capture is not integrated with RPCS3 yet "
              "(planned: RPCS3's Vulkan renderer under RenderDoc's Vulkan layer in an agent-owned capture session)."),
    "xenia": (UNSUPPORTED, None, "Xenia has no RenderDoc capture path in gBox; only the 2D frame is available."),
    "steam": (UNSUPPORTED, None, "PC games are not launched under RenderDoc by gBox; only the 2D frame is available."),
    "rocketlauncher": (UNSUPPORTED, None, "RocketLauncher starts its own emulators outside gBox, so RenderDoc "
                       "can't be placed inside them; only the 2D frame is available."),
    "mgba": (UNSUPPORTED, None, "mGBA renders in software (2D frame only)."),
    "duckstation": (UNSUPPORTED, None, "The DuckStation debug session runs on Linux without RenderDoc capture."),
    "mame": (UNSUPPORTED, None, "MAME renders in software (2D frame only)."),
    "command": (UNSUPPORTED, None, "Custom command emulators have no RenderDoc integration; only the 2D frame is available."),
}


def core_name(core: str | None) -> str:
    """'C:/.../flycast_libretro.dll' | 'flycast_libretro' | 'flycast' -> 'flycast'."""
    if not core:
        return ""
    n = Path(str(core).replace("\\", "/")).name.lower()
    n = re.sub(r"\.(dll|so|dylib)$", "", n)
    return re.sub(r"_libretro(_android)?$", "", n)


def _out(status, reason, driver=None, adapter="", core=""):
    return {"status": status, "reason": reason, "driver": driver,
            "fallback": "frame_2d" if status != SUPPORTED else None, "adapter": adapter, "core": core}


def support(adapter: str, core: str | None = None, driver: str | None = None, *, hooked: bool | None = None,
            host_os: str | None = None) -> dict:
    """The matrix row for one session. `driver` = the renderer the session runs now (RetroArch video_driver);
    `hooked` = RenderDoc is inside the process (None: unknown, e.g. before launch)."""
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
        if drv in CAPTURE_DRIVERS:
            if hooked is False:
                return _out(RELAUNCH, "this session was started without Examine 3D (RenderDoc isn't inside the "
                            "emulator): relaunch the game with Examine 3D on (save state first)", None, adapter, c)
            return _out(SUPPORTED, f"RetroArch {drv} renderer: RenderDoc captures it.", None, adapter, c)
        if c in GL_ONLY_CORES:
            return _out(RELAUNCH, f"The {c} core only renders with OpenGL and RenderDoc injection prevents RetroArch's "
                        "GL window from opening; capture needs a separate capture session on the core-profile "
                        "driver (glcore, not live-checked yet). The game remains playable.", "glcore", adapter, c)
        if c in VULKAN_CORES or not c:
            return _out(RELAUNCH, f"This RetroArch session renders with {drv or 'OpenGL'}, which RenderDoc injection "
                        f"can't open a window for; the {c or 'core'} core has a Vulkan renderer, so the frame can be "
                        "captured in a separate capture session under video_driver=vulkan (your game keeps its own "
                        "settings).", "vulkan", adapter, c)
        return _out(RELAUNCH, f"This RetroArch session renders with {drv or 'OpenGL'}, which RenderDoc injection can't "
                    f"open a window for; the {c} core is not in the capture matrix yet, so a Vulkan capture session "
                    "is the first thing to try.", "vulkan", adapter, c)
    status, d, reason = _STANDALONE.get(adapter, (UNSUPPORTED, None, f"{adapter or 'This emulator'} has no 3D "
                                                  "capture path in gBox yet; only the 2D frame is available."))
    if status == SUPPORTED and hooked is False:
        return _out(RELAUNCH, "this session was started without Examine 3D (RenderDoc isn't inside the emulator): "
                    "relaunch the game with Examine 3D on (save state first)", None, adapter, c)
    return _out(status, reason, d, adapter, c)


def session_support(ad, host_os: str | None = None) -> dict:
    """The matrix row for a live adapter instance (tools.SESSIONS)."""
    proc = getattr(ad, "proc", None)
    info = getattr(proc, "renderdoc", None) if proc is not None else None
    hooked = (bool(info) and "error" not in info) if proc is not None else None
    cfg = getattr(ad, "cfg", None)
    core = getattr(cfg, "core", None) if cfg is not None else None
    return support(getattr(ad, "name", "") or "", getattr(ad, "core_path", None) or core,
                   getattr(ad, "video_driver", None), hooked=hooked, host_os=host_os)


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
| Emulator / core | Status | Capture driver | Notes |
|---|---|---|---|
| RetroArch, D3D11/D3D12/Vulkan core | supported | (current) | needs Examine 3D on at launch |
| RetroArch, GL session of a Vulkan-capable core (Flycast, ParaLLEl N64, Beetle PSX HW, PCSX2, Dolphin, Citra, SwanStation, PPSSPP) | relaunch_under_capture | vulkan | agent-owned capture session only |
| RetroArch, GL-only 3D core (Kronos, YabaSanshiro, melonDS, Play!) | relaunch_under_capture | glcore | not live-checked |
| RetroArch, software core (Snes9x, Genesis Plus GX, mGBA, FBNeo, ...) | unsupported | - | 2D frame only |
| Dolphin (Windows, D3D12) | supported | (current) | |
| Yuzu | unsupported | vulkan (planned) | still frame only today |
| RPCS3 | unsupported | vulkan (planned) | still frame only today |
| Xenia, Steam, RocketLauncher, Linux sessions | unsupported | - | 2D frame only |
"""
