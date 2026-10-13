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
    "video_threaded": [False, True],
    "show_fps": [False, True],
    "rewind_mode": ["auto", "off"],
    "cpu_priority": ["normal", "above_normal"],
}
DEFAULT = {"res_scale": 100, "msaa": "auto", "aniso": 0, "upscaler": "bilinear", "sharpen": 50, "post_aa": "none", "vsync": True}
DEFAULT |= {"video_threaded": False, "show_fps": False, "rewind_mode": "auto", "cpu_priority": "normal"}
_SAVE_LOCK = threading.RLock()
_GPU_LOCK = threading.Lock()
_GPU_CACHE = None
_GPU_EXPIRES = 0.0

# These are the controls gBox actually writes into each emulator's launch config.
# A stored preference for one runtime must never be presented as an active
# setting in another runtime.
EMULATOR_FIELDS = {
    "rpcs3": ("res_scale", "msaa", "aniso", "upscaler", "sharpen"),
    "retroarch": ("upscaler", "post_aa", "vsync", "video_threaded", "show_fps", "rewind_mode", "cpu_priority"),
}


def choices_for(emulator: str) -> dict:
    return {key: FIELDS[key] for key in EMULATOR_FIELDS.get(emulator, ())}


def note_for(emulator: str) -> str:
    if emulator == "rpcs3":
        return "RPCS3 settings are written to this game's config and apply on the next launch."
    if emulator == "retroarch":
        return ("Saved per game on this worker; applies on the next launch. Performance disables shaders and rewind "
                "snapshots. Rewind off retains manual saves. Threaded video may help pacing but adds latency. "
                "Above-normal CPU priority is Windows-only; headless Linux keeps VSync off. "
                "FPS is emulator output, not necessarily game animation rate.")
    return f"gBox does not yet control {emulator or 'this emulator'} graphics settings. Configure them in the emulator."


def best_for_gpu(vram_mb: int) -> dict:
    """A strong preset for the installed GPU (8 GB class: ~4K internal from 720p, 4x MSAA, 16x AF, FSR)."""
    scale = 400 if vram_mb >= 12000 else 300 if vram_mb >= 7000 else 200 if vram_mb >= 4000 else 150
    return DEFAULT | {"res_scale": scale, "msaa": "auto", "aniso": 16, "upscaler": "fsr", "sharpen": 50, "post_aa": "fxaa", "vsync": True}


def performance_preset() -> dict:
    return DEFAULT | {"msaa": "off", "sharpen": 0, "upscaler": "nearest",
                      "vsync": False, "rewind_mode": "off", "cpu_priority": "above_normal", "show_fps": True}


def diagnose(adapter=None) -> dict:
    """Measure local resource pressure without starting expensive per-process GPU scans."""
    result = {"warnings": [], "fps": None,
              "fps_note": "Use the emulator FPS display to compare the same game scene before and after a change."}
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.25)
        mem = psutil.virtual_memory()
        result.update(cpu_pct=cpu, memory_pct=mem.percent, available_ram_mb=round(mem.available / 2**20))
        if cpu >= 90:
            result["warnings"].append("CPU is saturated. Pause background AI, extraction or other CPU-heavy work and compare the same scene again.")
        if mem.percent >= 90:
            result["warnings"].append("Memory pressure is high. Close unused applications to reduce paging.")
    except (ImportError, OSError) as exc:
        result["unavailable"] = str(exc)
    log = getattr(adapter, "log_path", None)
    if log:
        try:
            with Path(log).open("rb") as stream:
                head = stream.read(65536)
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 65536))
                lines = (head + b'\n' + stream.read()).decode("utf-8", "replace").splitlines()
            result["renderer"] = next((line for line in reversed(lines) if "Renderer:" in line), "Not present in the recent emulator log")
        except OSError:
            pass
    return result


def gpu() -> dict:
    # Settings reads should not repeatedly spawn nvidia-smi while the user plays.
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
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000 if sys.platform == 'win32' else 0).stdout.strip().splitlines()[0]
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


def get(cfg, game_id: str | None) -> dict:
    try:
        allp = json.loads(_file(cfg).read_text())
    except (OSError, ValueError):
        allp = {}
    return DEFAULT | allp.get(game_id or "", {})


def save(cfg, game_id: str, prefs: dict) -> dict:
    bad = {k: v for k, v in prefs.items() if k not in FIELDS or
           not any(type(v) is type(option) and v == option for option in FIELDS[k])}
    if bad:
        raise ValueError(f"unsupported values {bad}; choices: {FIELDS}")
    with _SAVE_LOCK:
        f = _file(cfg)
        try:
            allp = json.loads(f.read_text())
        except (OSError, ValueError):
            allp = {}
        allp[game_id] = get(cfg, game_id) | prefs
        f.parent.mkdir(parents=True, exist_ok=True)
        temporary = f.with_suffix(".tmp")
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


def retroarch_opts(p: dict, ra_dir: Path) -> dict:
    """RetroArch (GL driver) settings: one post-process shader preset + vsync."""
    sh = ra_dir / "shaders" / "shaders_glsl"
    preset = {"fxaa": sh / "anti-aliasing" / "fxaa.glslp", "advanced": sh / "anti-aliasing" / "advanced-aa.glslp"}.get(p["post_aa"])
    if not preset and p["upscaler"] == "fsr":
        preset = next(iter(sorted((sh / "fsr").glob("*.glslp"))), None)
    out = {"video_vsync": "true" if p["vsync"] else "false", "video_smooth": "false" if p["upscaler"] == "nearest" else "true"}
    out |= {"video_threaded": "true" if p.get("video_threaded") else "false",
            "fps_show": "true" if p.get("show_fps") else "false"}
    if p.get("show_fps"):
        out["video_font_enable"] = "true"
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
    print("graphics selftest ok")


if __name__ == "__main__":
    _selftest()
