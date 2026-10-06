"""Dependency resolution: `gbox setup` installs/verifies everything a node needs; launches call ensure_* on demand.

Every step is idempotent (check first, install only when missing) and returns a receipt dict.
Linux installs use `sudo -n` (passwordless sudo required, never prompts). Downloads come from the projects' own
distribution points (Ubuntu apt, buildbot.libretro.com, GitHub releases).
"""
import io
import json
import os
import platform
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import httpx

from . import systems
from .config import HOST_OS, Config

ARCH = {"aarch64": "aarch64", "arm64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}[platform.machine().lower()]
APT = ["retroarch", "xvfb", "xdotool", "x11-utils", "p7zip-full", "unzip", "cifs-utils", "ffmpeg", "openjdk-21-jdk-headless",
       "mesa-utils", "libgl1-mesa-dri"]
BUILDBOT = "https://buildbot.libretro.com/nightly"
BUILDBOT_ASSETS = "https://buildbot.libretro.com/assets/system"   # core support files (Dolphin Sys, PPSSPP assets...)
CORE_ASSETS = {"dolphin": ("dolphin-emu", "Dolphin.zip"), "ppsspp": ("PPSSPP", "PPSSPP.zip")}
PREFETCH_CORES = ["flycast", "dolphin"]


class ProvisionError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise ProvisionError(f"{' '.join(cmd[:4])}... exit {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
    return r


def _sudo(cmd: list[str], timeout: int = 1800):
    return _run(["sudo", "-n", *cmd], timeout)


def _receipt(step: str, status: str, detail="") -> dict:
    return {"step": step, "status": status, "detail": detail, "at": time.time()}


# --- linux system packages -------------------------------------------------------------------

def apt_packages(pkgs: list[str] = APT) -> dict:
    missing = [p for p in pkgs if subprocess.run(["dpkg", "-s", p], capture_output=True).returncode]
    if not missing:
        return _receipt("apt", "ok", f"{len(pkgs)} packages present")
    _sudo(["apt-get", "update", "-q"], 900)
    _sudo(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "-q", *missing])
    return _receipt("apt", "installed", " ".join(missing))


def _fstab_escape(s: str) -> str:
    return s.replace(" ", "\\040")


def mount_library(cfg: Config, lib) -> dict:
    target = Path(lib.mount_root or lib.paths["linux"])
    if not cfg.smb_credentials:
        raise ProvisionError("smb_credentials not configured")
    opts = f"ro,credentials={cfg.smb_credentials},uid={os.getuid()},gid={os.getgid()},iocharset=utf8,vers=3.0,_netdev,nofail"
    line = f"{_fstab_escape(lib.mount)} {_fstab_escape(str(target))} cifs {opts} 0 0"
    added = False
    if _fstab_escape(str(target)) + " " not in Path("/etc/fstab").read_text():     # persist across reboots
        _sudo(["cp", "/etc/fstab", f"/etc/fstab.gbox-{int(time.time())}.bak"])        # rollback copy
        _sudo(["sh", "-c", f"printf '%s\\n' '# gbox library {lib.id}' '{line}' >> /etc/fstab"])
        _sudo(["systemctl", "daemon-reload"])
        added = True
    if not os.path.ismount(target):
        _sudo(["mkdir", "-p", str(target)])
        _sudo(["mount", str(target)], 120)
        added = True
    return _receipt(f"mount:{lib.id}", "installed" if added else "ok", line)


# --- libretro cores / BIOS ------------------------------------------------------------------

def core_path(cfg: Config, core: str) -> Path:
    ext = "dll" if HOST_OS == "windows" else "so"
    return cfg.runtime / "cores" / f"{core}_libretro.{ext}"


# When a core has no build for this platform, try these instead (same system, different emulator).
CORE_FALLBACKS = {"mupen64plus_next": ["parallel_n64"], "parallel_n64": ["mupen64plus_next"],
                  "yabasanshiro": ["kronos", "mednafen_saturn", "yabause"], "mesen": ["nestopia", "fceumm"],
                  "pcsx2": ["play"], "citra": ["citra2018"], "melonds": ["melondsds", "desmume"],
                  "pcsx_rearmed": ["swanstation", "mednafen_psx_hw"], "mame": ["mame2016", "mame2010"]}


def ensure_core(cfg: Config, core: str) -> Path:
    """Return a local core library, downloading it from the libretro buildbot if missing (with fallbacks)."""
    if os.sep in core or "/" in core:
        return Path(core)
    tried = []
    for name in [core, *CORE_FALLBACKS.get(core, [])]:
        p = core_path(cfg, name)
        if p.exists():
            return p
        try:
            return _download_core(name, p)
        except ProvisionError as e:
            tried.append(str(e))
    raise ProvisionError("; ".join(tried))


def _download_core(core: str, p: Path) -> Path:
    plat = f"windows/x86_64" if HOST_OS == "windows" else f"linux/{ARCH}"
    url = f"{BUILDBOT}/{plat}/latest/{p.name}.zip"
    r = httpx.get(url, timeout=600, follow_redirects=True)
    if r.status_code != 200:
        raise ProvisionError(f"core {core} not available for {plat} ({r.status_code} {url})")
    p.parent.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(r.content)).extract(p.name, p.parent)
    (p.parent / f"{p.name}.receipt.json").write_text(json.dumps({"url": url, "bytes": len(r.content), "at": time.time()}))
    return p


def ensure_core_assets(cfg: Config, core: str) -> str | None:
    """Support data some cores need (Dolphin Sys/, PPSSPP assets). Must match the nightly core's version:
    an older Dolphin Sys (e.g. from the game drive) lacks shaders the new core expects and renders black."""
    if core not in CORE_ASSETS:
        return None
    dirname, zipname = CORE_ASSETS[core]
    dest = cfg.runtime / "system"
    marker = dest / dirname / ".gbox-source"
    if marker.exists() and marker.read_text().startswith("buildbot"):
        return "ok"
    try:
        r = httpx.get(f"{BUILDBOT_ASSETS}/{zipname}", timeout=900, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        src = _bios_root(cfg)
        if not (dest / dirname).exists() and src and (src / dirname).is_dir():
            shutil.copytree(src / dirname, dest / dirname)            # offline fallback: drive copy (may be older)
            (dest / dirname / ".gbox-source").write_text("drive")
        return "fallback"
    if (dest / dirname).exists():                                      # keep the stale copy for rollback
        (dest / dirname).rename(dest / f"{dirname}.replaced-{int(time.time())}")
    dest.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(dest)
    marker.write_text(f"buildbot {zipname} {time.time()}")
    return "installed"


def _bios_root(cfg: Config) -> Path | None:
    p = cfg.retroarch_bios.get(HOST_OS)
    return Path(p) if p and Path(p).is_dir() else None


def ensure_bios(cfg: Config, names: list[str]) -> list[str]:
    """Copy the BIOS files/dirs a core needs from the drive's RetroArch/system into the local system dir."""
    dest, src, copied = cfg.runtime / "system", _bios_root(cfg), []
    dest.mkdir(parents=True, exist_ok=True)
    if not src:
        return copied
    for n in names:
        s, d = src / n, dest / n
        if d.exists() or not s.exists():
            continue
        shutil.copytree(s, d) if s.is_dir() else shutil.copy2(s, d)
        copied.append(n)
    return copied


def ensure_platform(cfg: Config, platform_: str, core: str | None = None) -> tuple[Path, list[str]]:
    core0, bios = systems.core_for(platform_)
    core = core or core0
    if not core:
        raise ProvisionError(f"no libretro core for platform {platform_} on {HOST_OS}/{ARCH}; use a Windows node")
    path = ensure_core(cfg, core)
    ensure_core_assets(cfg, core)
    return path, ensure_bios(cfg, bios)


def retroarch_exe(cfg: Config) -> str:
    """libretro's own nightly RetroArch build. Ubuntu's arm64 package is OpenGL-ES only, which cannot host
    desktop-GL cores such as the buildbot Flycast ('Requesting OpenGL context, but RetroArch is compiled against
    OpenGLES'), so on linux the buildbot build (desktop GL + Vulkan) is downloaded into the runtime dir."""
    override = next((e.executable for e in cfg.emulators.values() if e.adapter == "retroarch" and e.executable), None)
    if override:
        return override
    if HOST_OS == "windows":
        return _retroarch_windows(cfg)
    exe = cfg.runtime / "retroarch-bin" / "retroarch"
    if exe.exists():
        return str(exe)
    url = f"{BUILDBOT}/linux/{ARCH}/RetroArch.7z"
    r = httpx.get(url, timeout=600, follow_redirects=True)
    if r.status_code != 200:
        raise ProvisionError(f"retroarch download failed ({r.status_code} {url})")
    exe.parent.mkdir(parents=True, exist_ok=True)
    archive = exe.parent / "RetroArch.7z"
    archive.write_bytes(r.content)
    if not shutil.which("7z"):
        apt_packages(["p7zip-full"])
    _run(["7z", "x", "-y", f"-o{exe.parent}", str(archive)])
    archive.unlink()
    exe.chmod(0o755)
    (exe.parent / "receipt.json").write_text(json.dumps({"url": url, "bytes": len(r.content), "at": time.time(),
                                                         "version": _run([str(exe), "--version"]).stdout.strip()[:200]}))
    return str(exe)


def ensure_virtualgl() -> dict:
    """GPU rendering for headless sessions: VirtualGL (EGL back end) puts each session's OpenGL on the NVIDIA GPU.
    Not in Ubuntu's apt; installed from the project's GitHub release .deb."""
    vgl = Path("/opt/VirtualGL/bin/vglrun")
    if not vgl.exists():
        rel = httpx.get("https://api.github.com/repos/VirtualGL/virtualgl/releases/latest", timeout=60).json()
        arch = {"aarch64": "arm64", "x86_64": "amd64"}[ARCH]
        asset = next(a for a in rel["assets"] if a["name"].endswith(f"_{arch}.deb"))
        deb = Path("/tmp") / asset["name"]
        deb.write_bytes(httpx.get(asset["browser_download_url"], timeout=600, follow_redirects=True).content)
        _sudo(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "-q", str(deb)])
        status = "installed"
    else:
        status = "ok"
    # prove it: which GL renderer does a VirtualGL'd client get on a throwaway Xvfb?
    x = subprocess.Popen(["Xvfb", ":139", "-screen", "0", "640x480x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        out = subprocess.run([str(vgl), "-d", "egl", "/opt/VirtualGL/bin/glxinfo", "-B"], capture_output=True, text=True,
                             timeout=60, env={**os.environ, "DISPLAY": ":139"}).stdout
    finally:
        x.terminate()
    renderer = next((ln.split(":", 1)[1].strip() for ln in out.splitlines() if "renderer string" in ln), "unknown")
    if "llvmpipe" in renderer or renderer == "unknown":
        return _receipt("gpu", "failed", f"VirtualGL renders on {renderer}, not the GPU")
    return _receipt("gpu", status, f"VirtualGL EGL -> {renderer}")


def _seven_zip() -> str:
    """7-Zip CLI (libretro's Windows archives use BCJ2, which pure-Python extractors can't decode)."""
    for c in (shutil.which("7z"), "C:/Program Files/7-Zip/7z.exe", "C:/Program Files (x86)/7-Zip/7z.exe"):
        if c and Path(c).exists():
            return c
    _run(["winget", "install", "-e", "--id", "7zip.7zip", "--silent", "--accept-source-agreements", "--accept-package-agreements"], 900)
    c = "C:/Program Files/7-Zip/7z.exe"
    if not Path(c).exists():
        raise ProvisionError("7-Zip install failed")
    return c


BRAND_ICO = Path(__file__).resolve().parent.parent / "assets" / "brand" / "gbox.ico"


def rcedit(cfg: Config) -> str:
    """electron/rcedit: sets icon + version strings inside Windows executables (what Task Manager/mixer display)."""
    exe = cfg.runtime / "tools" / "rcedit-x64.exe"
    if not exe.exists():
        exe.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get("https://github.com/electron/rcedit/releases/latest/download/rcedit-x64.exe", timeout=300, follow_redirects=True)
        r.raise_for_status()
        exe.write_bytes(r.content)
    return str(exe)


def brand_exe(cfg: Config, exe: Path, description: str):
    # executables without a version resource (RetroArch) need the version block created before strings can be set
    _run([rcedit(cfg), str(exe), "--set-file-version", "1.0.0.0", "--set-product-version", "1.0.0.0",
          "--set-icon", str(BRAND_ICO), "--set-version-string", "FileDescription", description,
          "--set-version-string", "ProductName", "G-Box", "--set-version-string", "CompanyName", "G-Box",
          "--set-version-string", "InternalName", exe.stem, "--set-version-string", "OriginalFilename", exe.name], 120)


def _retroarch_windows(cfg: Config) -> str:
    """Branded copy of RetroArch for local play: shows as "G-Box Game" in Task Manager and the volume mixer."""
    raw = _retroarch_windows_raw(cfg)
    branded = Path(raw).with_name("G-Box Game.exe")
    if not branded.exists() or branded.stat().st_mtime < Path(raw).stat().st_mtime:
        shutil.copy2(raw, branded)
        try:
            brand_exe(cfg, branded, "G-Box Game")
        except Exception:
            return raw                                       # unbranded still works
    return str(branded)


def _retroarch_windows_raw(cfg: Config) -> str:
    """Native RetroArch for local play on a Windows node (full FPS, real audio, XInput pads, no stream)."""
    root = cfg.runtime / "retroarch-win"
    found = sorted(root.glob("**/retroarch.exe"))
    if found:
        return str(found[0])
    seven = _seven_zip()
    url = f"{BUILDBOT}/windows/x86_64/RetroArch.7z"
    r = httpx.get(url, timeout=1800, follow_redirects=True)
    if r.status_code != 200:
        raise ProvisionError(f"retroarch download failed ({r.status_code} {url})")
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "RetroArch.7z"
    archive.write_bytes(r.content)
    _run([seven, "x", "-y", f"-o{root}", str(archive)], 900)              # BCJ2-filtered: needs real 7-Zip
    archive.unlink()
    found = sorted(root.glob("**/retroarch.exe"))
    if not found:
        raise ProvisionError("retroarch.exe missing after extraction")
    (root / "receipt.json").write_text(json.dumps({"url": url, "bytes": len(r.content), "at": time.time()}))
    return str(found[0])


# --- ghidra / blender -----------------------------------------------------------------------

def ghidra_home(cfg: Config) -> Path | None:
    if cfg.ghidra_home:
        return Path(cfg.ghidra_home)
    found = sorted((cfg.runtime).glob("ghidra_*_PUBLIC"))
    return found[-1] if found else None


def ensure_ghidra(cfg: Config) -> dict:
    if (h := ghidra_home(cfg)) and (h / "support").exists():
        return _receipt("ghidra", "ok", str(h))
    rel = httpx.get("https://api.github.com/repos/NationalSecurityAgency/ghidra/releases/latest", timeout=60).json()
    asset = next(a for a in rel["assets"] if a["name"].endswith(".zip"))
    r = httpx.get(asset["browser_download_url"], timeout=1800, follow_redirects=True)
    r.raise_for_status()
    cfg.runtime.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(cfg.runtime)
    h = ghidra_home(cfg)
    for f in (h / "support").glob("*"):                  # zip extraction drops exec bits
        if f.suffix in ("", ".sh"):
            f.chmod(0o755)
    for f in (h / "Ghidra").rglob("os/*/*"):
        f.chmod(0o755)
    return _receipt("ghidra", "installed", f"{rel['tag_name']} -> {h}")


_blender_cache: dict[tuple, tuple[float, str | None]] = {}


def find_blender(cfg: Config) -> str | None:
    """Newest Blender under blender_search. Builds sit 1-3 folders deep (Builds/daily/blender-x/blender.exe);
    a full rglob of a build library took ~100 s, so search shallow and cache for 10 min."""
    if cfg.blender_path and Path(cfg.blender_path).exists():
        return cfg.blender_path
    key = tuple(cfg.blender_search)
    hit = _blender_cache.get(key)
    if hit and time.time() - hit[0] < 600 and (hit[1] is None or Path(hit[1]).exists()):
        return hit[1]
    exe = "blender.exe" if HOST_OS == "windows" else "blender"
    found = [p for d in cfg.blender_search if Path(d).is_dir()
             for pat in (exe, f"*/{exe}", f"*/*/{exe}", f"*/*/*/{exe}") for p in Path(d).glob(pat)]
    best = str(max(found, key=lambda p: p.stat().st_mtime)) if found else shutil.which("blender")   # newest build
    _blender_cache[key] = (time.time(), best)
    return best


def check_blender(cfg: Config) -> dict:
    b = find_blender(cfg)
    if not b:
        return _receipt("blender", "missing", f"searched {cfg.blender_search}")
    v = _run([b, "--version"], 120).stdout.splitlines()[0]
    return _receipt("blender", "ok", f"{v} @ {b}")


def install_blender_addon(cfg: Config) -> dict:
    """Install + enable the G-Box Blender add-on (paste from G-Box) for the Blender this node uses."""
    b = find_blender(cfg)
    if not b:
        return _receipt("blender-addon", "missing", "no blender on this node")
    ver = re.search(r"Blender (\d+\.\d+)", _run([b, "--version"], 120).stdout)
    if not ver:
        return _receipt("blender-addon", "failed", "could not read blender version")
    base = (Path(os.environ["APPDATA"]) / "Blender Foundation" / "Blender" if HOST_OS == "windows"
            else Path.home() / ".config" / "blender")
    dest = base / ver.group(1) / "scripts" / "addons"
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parent.parent / "clients" / "blender" / "gbox_addon.py"
    shutil.copy2(src, dest / "gbox_addon.py")
    server = cfg.public_url or f"http://127.0.0.1:{cfg.api_port}"
    (dest / "gbox_addon.json").write_text(json.dumps({"server": server, "token": cfg.token()}))
    _run([b, "--background", "--factory-startup", "--python-expr",
          "import bpy; bpy.ops.preferences.addon_enable(module='gbox_addon'); bpy.ops.wm.save_userpref()"], 300)
    return _receipt("blender-addon", "ok", f"{dest / 'gbox_addon.py'} -> {server}")


def ensure_ffmpeg() -> dict:
    if shutil.which("ffmpeg"):
        return _receipt("ffmpeg", "ok", shutil.which("ffmpeg"))
    if HOST_OS == "windows":
        _run(["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements"])
        return _receipt("ffmpeg", "installed", "winget Gyan.FFmpeg (new shells pick up PATH)")
    apt_packages(["ffmpeg"])
    return _receipt("ffmpeg", "installed", "apt")


# --- orchestration --------------------------------------------------------------------------

def setup(cfg: Config, with_ghidra: bool = True, log=print) -> list[dict]:
    steps = []
    if HOST_OS == "linux":
        steps.append(("apt", apt_packages))
        for lib in cfg.libraries:
            if lib.mount and lib.paths.get("linux"):
                steps.append((f"mount:{lib.id}", lambda lib=lib: mount_library(cfg, lib)))
        steps.append(("gpu", ensure_virtualgl))
        steps.append(("retroarch", lambda: _receipt("retroarch", "ok", " ".join(
            (_run([retroarch_exe(cfg), "--version"]).stdout + " @ " + retroarch_exe(cfg)).split())[:110])))
        for c in PREFETCH_CORES:
            steps.append((f"core:{c}", lambda c=c: _receipt(f"core:{c}", "ok", str(ensure_core(cfg, c)))))
        steps.append(("bios", lambda: _receipt("bios", "ok", f"copied {ensure_bios(cfg, ['dc'])}")))
        if with_ghidra:
            steps.append(("ghidra", lambda: ensure_ghidra(cfg)))
    else:
        steps.append(("ffmpeg", ensure_ffmpeg))
        steps.append(("retroarch", lambda: _receipt("retroarch", "ok", retroarch_exe(cfg))))
        for c in PREFETCH_CORES:
            steps.append((f"core:{c}", lambda c=c: _receipt(f"core:{c}", "ok", str(ensure_core(cfg, c)))))
        steps.append(("blender", lambda: check_blender(cfg)))
        steps.append(("blender-addon", lambda: install_blender_addon(cfg)))
        for lib in cfg.libraries:
            p = lib.root("windows")
            steps.append((f"library:{lib.id}", lambda p=p, lib=lib: _receipt(
                f"library:{lib.id}", "ok" if p and p.exists() else "missing", str(p))))
    receipts = []
    for name, fn in steps:
        try:
            r = fn()
        except Exception as e:
            r = _receipt(name, "failed", f"{type(e).__name__}: {e}")
        log(f"  {r['status']:9} {r['step']:24} {str(r['detail'])[:110]}")
        receipts.append(r)
    out = cfg.data_dir / f"provision-{HOST_OS}-{platform.node()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipts, indent=1))
    return receipts


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)
