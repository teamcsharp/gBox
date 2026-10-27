"""Per-game graphics settings (internal resolution, MSAA, anisotropic filtering, upscaler/sharpening, post-process AA,
vsync), stored in data_dir/graphics.json and turned into each emulator's own settings at launch.

Not every emulator has every knob: RPCS3 = resolution scale, MSAA, AF, FSR + CAS sharpening; RetroArch (GL driver) =
post-process shader (FXAA / advanced AA / FSR) + vsync. Temporal AA does not exist in these emulators: it needs motion
vectors the original games never produce.
"""
import json
import threading
import time
from pathlib import Path

FIELDS = {
    "res_scale": [100, 150, 200, 250, 300, 400],          # % of native internal resolution
    "msaa": ["off", "auto"],
    "aniso": [0, 2, 4, 8, 16],
    "upscaler": ["bilinear", "nearest", "fsr"],
    "sharpen": list(range(0, 101, 10)),
    "post_aa": ["none", "fxaa", "advanced"],
    "vsync": [True, False],
}
DEFAULT = {"res_scale": 100, "msaa": "auto", "aniso": 0, "upscaler": "bilinear", "sharpen": 50, "post_aa": "none", "vsync": True}
_SAVE_LOCK = threading.RLock()
_GPU_LOCK = threading.Lock()
_GPU_CACHE = None
_GPU_EXPIRES = 0.0

# These are the controls gBox actually writes into each emulator's launch config.
# A stored preference for one runtime must never be presented as an active
# setting in another runtime.
EMULATOR_FIELDS = {
    "rpcs3": ("res_scale", "msaa", "aniso", "upscaler", "sharpen"),
    "retroarch": ("upscaler", "post_aa", "vsync"),
    "dolphin": ("res_scale", "msaa", "aniso"),
}

# Per-title starting points, keyed by emulator then the game's serial (GameCube: the six-byte disc id). A game with a
# preset launches with it even when nobody has opened its Graphics panel; a saved panel choice for the game (on this
# host's data_dir/graphics.json) still wins key by key. Games without a preset or a saved choice get no overrides, so
# they keep whatever the emulator's own config says.
PRESETS = {
    "dolphin": {
        # Resident Evil 4 (USA): the operator asked for it to come up looking good (2026-10-24): 3x native internal
        # resolution, 4x MSAA, 16x anisotropic filtering. Dolphin 2609a has no Sys/GameSettings/G4B*.ini hacks for it
        # and gBox writes no EFB/XFB keys, so nothing game-specific is overridden.
        "G4BE08": {"res_scale": 300, "msaa": "auto", "aniso": 16},
    },
}


def choices_for(emulator: str) -> dict:
    return {key: FIELDS[key] for key in EMULATOR_FIELDS.get(emulator, ())}


def preset_for(emulator: str, serial: str | None) -> dict:
    return dict(PRESETS.get(emulator, {}).get(serial or "", {}))


def note_for(emulator: str) -> str:
    if emulator == "rpcs3":
        return "RPCS3 settings are written to this game's config and apply on the next launch."
    if emulator == "retroarch":
        return "RetroArch shader, filtering and VSync settings apply on the next launch."
    if emulator == "dolphin":
        return ("Dolphin internal resolution, MSAA and anisotropic filtering apply on the next launch (Dolphin's "
                "command-line layer: never saved into its own settings).")
    return f"gBox does not yet control {emulator or 'this emulator'} graphics settings. Configure them in the emulator."


def best_for_gpu(vram_mb: int) -> dict:
    """A strong preset for the installed GPU (8 GB class: ~4K internal from 720p, 4x MSAA, 16x AF, FSR)."""
    scale = 400 if vram_mb >= 12000 else 300 if vram_mb >= 7000 else 200 if vram_mb >= 4000 else 150
    return {"res_scale": scale, "msaa": "auto", "aniso": 16, "upscaler": "fsr", "sharpen": 50, "post_aa": "fxaa", "vsync": True}


def gpu() -> dict:
    """The installed GPU, cached for a minute: every Graphics panel read used to start nvidia-smi (#712)."""
    global _GPU_CACHE, _GPU_EXPIRES
    with _GPU_LOCK:
        if _GPU_CACHE is None or time.monotonic() >= _GPU_EXPIRES:
            _GPU_CACHE = _read_gpu()
            _GPU_EXPIRES = time.monotonic() + 60
        return dict(_GPU_CACHE)


def _read_gpu() -> dict:
    import subprocess
    import sys
    try:
        # CREATE_NO_WINDOW: the windowless worker would otherwise flash a console window over the game (#1081)
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000 if sys.platform == "win32" else 0).stdout.strip().splitlines()[0]
        name, mb = [x.strip() for x in out.split(",")]
        return {"name": name, "vram_mb": int(float(mb))}
    except Exception:
        return {"name": "unknown", "vram_mb": 4000}


def prefer_gpu(exe) -> bool:
    """Windows: run this emulator on the high-performance GPU (Settings -> Display -> Graphics = "High performance").
    Without it Windows may hand D3D/Vulkan to another adapter (a virtual display, an iGPU) and games crawl. Per user,
    per exe path, no admin needed; takes effect for the next process start. Returns True when the setting is in place."""
    import sys
    if sys.platform != "win32" or not exe:
        return False
    import winreg
    path = str(Path(exe).resolve())
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences") as k:
            try:
                if winreg.QueryValueEx(k, path)[0] == "GpuPreference=2;":
                    return True
            except OSError:
                pass
            winreg.SetValueEx(k, path, 0, winreg.REG_SZ, "GpuPreference=2;")
        return True
    except OSError:
        return False


def _file(cfg) -> Path:
    return Path(cfg.data_dir) / "graphics.json"


def saved(cfg, game_id: str | None) -> dict:
    """The choices stored for this game on this host ({} when its Graphics panel was never saved)."""
    try:
        allp = json.loads(_file(cfg).read_text())
    except (OSError, ValueError):
        allp = {}
    mine = allp.get(game_id or "", {}) if isinstance(allp, dict) else {}
    return dict(mine) if isinstance(mine, dict) else {}


def get(cfg, game_id: str | None, preset: dict | None = None) -> dict:
    return DEFAULT | (preset or {}) | saved(cfg, game_id)


def save(cfg, game_id: str, prefs: dict, preset: dict | None = None) -> dict:
    # exact types: True == 1 and 1.0 == 1, so `in` alone accepted vsync=1 or res_scale=True
    bad = {k: v for k, v in prefs.items() if k not in FIELDS or
           not any(type(v) is type(option) and v == option for option in FIELDS[k])}
    if bad:
        raise ValueError(f"unsupported values {bad}; choices: {FIELDS}")
    with _SAVE_LOCK:                                   # concurrent saves for two games must not drop either one
        f = _file(cfg)
        try:
            allp = json.loads(f.read_text())
        except (OSError, ValueError):
            allp = {}
        allp[game_id] = get(cfg, game_id, preset) | prefs
        f.parent.mkdir(parents=True, exist_ok=True)
        temporary = f.with_suffix(".tmp")               # a crash mid-write leaves the previous file intact
        temporary.write_text(json.dumps(allp, indent=1))
        temporary.replace(f)
        return allp[game_id]


def rpcs3_yaml(p: dict) -> str:
    """Per-game RPCS3 override (config/custom_configs/config_<SERIAL>.yml; RPCS3 layers it over the global config)."""
    mode = {"bilinear": "Bilinear", "nearest": "Nearest", "fsr": "FidelityFX Super Resolution"}[p["upscaler"]]
    return ("Video:\n"
            f"  Resolution Scale: {p['res_scale']}\n"
            f"  MSAA: {'Auto' if p['msaa'] == 'auto' else 'Disabled'}\n"
            f"  Anisotropic Filter Override: {p['aniso']}\n"
            f"  Output Scaling Mode: {mode}\n"
            f"  FidelityFX CAS Sharpening Intensity: {p['sharpen']}\n")


DOLPHIN_MSAA_SAMPLES = 4           # every Vulkan driver gBox runs on (RTX, GB10) supports 4x; SSAA stays off (it is
                                   # the same sample count shaded per sample: far costlier for little gain at 3x IR)
_DOLPHIN_ANISO = {2: 1, 4: 2, 8: 3, 16: 4}   # GFX.ini [Enhancements] MaxAnisotropy stores log2: 4 = 16x


def dolphin_opts(p: dict, max_res_scale: int | None = None) -> dict:
    """Dolphin GFX settings as `-C System.Section.Key=Value` options (Dolphin's command-line layer).

    The command-line layer sits above Dolphin's own GFX.ini but below its game INIs (Sys/ and User/GameSettings), so a
    game's compatibility hacks and anything the operator set in Dolphin's Game Properties keep winning, and nothing is
    written to disk. Only these keys are owned: GFX.Settings.InternalResolution / MSAA / SSAA and
    GFX.Enhancements.MaxAnisotropy (only when an anisotropy level is chosen; 0 leaves Dolphin's own setting).
    max_res_scale caps the internal resolution where extra pixels cannot be seen (the Spark's streamed 1280x720
    display, where a GameCube frame is drawn at most about 1280x983)."""
    scale = int(p["res_scale"])
    if max_res_scale:
        scale = min(scale, int(max_res_scale))
    out = {"GFX.Settings.InternalResolution": str(max(1, int(scale / 100 + 0.5))),   # Dolphin's IR is a whole multiple
           "GFX.Settings.MSAA": str(DOLPHIN_MSAA_SAMPLES if p["msaa"] == "auto" else 1),
           "GFX.Settings.SSAA": "False"}
    if _DOLPHIN_ANISO.get(p["aniso"]):
        out["GFX.Enhancements.MaxAnisotropy"] = str(_DOLPHIN_ANISO[p["aniso"]])
    return out


def retroarch_opts(p: dict, ra_dir: Path) -> dict:
    """RetroArch (GL driver) settings: one post-process shader preset + vsync."""
    sh = ra_dir / "shaders" / "shaders_glsl"
    preset = {"fxaa": sh / "anti-aliasing" / "fxaa.glslp", "advanced": sh / "anti-aliasing" / "advanced-aa.glslp"}.get(p["post_aa"])
    if not preset and p["upscaler"] == "fsr":
        preset = next(iter(sorted((sh / "fsr").glob("*.glslp"))), None)
    out = {"video_vsync": "true" if p["vsync"] else "false", "video_smooth": "false" if p["upscaler"] == "nearest" else "true"}
    if preset and preset.exists():
        out |= {"video_shader_enable": "true", "video_shader": str(preset)}
    else:
        out |= {"video_shader_enable": "false"}
    return out


def _selftest():
    y = rpcs3_yaml(best_for_gpu(8192))
    assert "Resolution Scale: 300" in y and "MSAA: Auto" in y and "FidelityFX Super Resolution" in y
    o = retroarch_opts(DEFAULT | {"post_aa": "fxaa"}, Path("/nonexistent"))
    assert o["video_shader_enable"] == "false" and o["video_vsync"] == "true"
    d = dolphin_opts(DEFAULT | preset_for("dolphin", "G4BE08"))
    assert d["GFX.Settings.InternalResolution"] == "3" and d["GFX.Settings.MSAA"] == "4"
    assert d["GFX.Enhancements.MaxAnisotropy"] == "4"
    print("graphics selftest ok")


if __name__ == "__main__":
    _selftest()
