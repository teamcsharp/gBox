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
import stat
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import httpx

from . import systems
from .config import HOST_OS, Config
from .registry import ToolUnavailable

ARCH = {"aarch64": "aarch64", "arm64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}[platform.machine().lower()]
APT = ["retroarch", "xvfb", "xdotool", "x11-utils", "p7zip-full", "unzip", "cifs-utils", "ffmpeg", "openjdk-21-jdk-headless",
       "mesa-utils", "libgl1-mesa-dri", "flatpak", "mame", "mgba-qt"]
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
    for n in names:                                        # "drive/path->core/path" when the drive layout differs
        sname, dname = n.split("->") if "->" in n else (n, n)
        s, d = src / sname, dest / dname
        if not s.exists():
            continue
        if s.is_dir():                                     # fill in missing files (an empty dir is not "installed")
            for f in s.rglob("*"):
                t = d / f.relative_to(s)
                if f.is_file() and not t.exists():
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, t)
                    copied.append(f"{dname}/{f.relative_to(s).as_posix()}")
        elif not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            copied.append(dname)
    return copied


def ensure_platform(cfg: Config, platform_: str, core: str | None = None) -> tuple[Path, list[str]]:
    core0, bios = systems.core_for(platform_)
    core = core or core0
    if not core:
        raise ProvisionError(f"no libretro core for platform {platform_} on {HOST_OS}/{ARCH}; use a Windows node")
    path = ensure_core(cfg, core)
    ensure_core_assets(cfg, core)
    return path, ensure_bios(cfg, bios)


# --- the runtime check of a launch, remembered per emulator version ------------------------------------------------
# A RetroArch launch checked the core, its assets and the BIOS every time. The BIOS check walks the drive's BIOS folder
# over SMB (Dreamcast "dc": 68 files): 1.4 s warm, 18.7 s cold on JAYBUILTFINALE (2026-10-13). The result is kept in
# <runtime>/runtime-check.json keyed by platform + core, valid while the core file and the RetroArch executable are the
# same files (size + mtime) and the BIOS files it found are still in the local system folder; past RUNTIME_RECHECK_S
# the drive is re-scanned in the background (it only ever adds missing files), never on the launch's path.

RUNTIME_CHECK = "runtime-check.json"
RUNTIME_RECHECK_S = 6 * 3600.0
_RC_LOCK = threading.Lock()
_RC_REFRESHING: set[str] = set()


def _file_ident(p) -> list[int] | None:
    try:
        st = Path(p).stat()
        return [st.st_size, st.st_mtime_ns]
    except (OSError, TypeError):
        return None


def _rc_load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _rc_set(path: Path, key: str, value: dict) -> None:
    with _RC_LOCK:
        db = _rc_load(path)
        db[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(db, indent=1))
        tmp.replace(path)


def _bios_local_names(names: list[str]) -> list[str]:
    return [n.split("->")[-1] for n in names]


def _refresh_bios_later(cfg: Config, path: Path, key: str, rec: dict) -> None:
    if key in _RC_REFRESHING:
        return
    _RC_REFRESHING.add(key)

    def run():
        try:
            copied = ensure_bios(cfg, rec.get("bios") or [])
            dest = cfg.runtime / "system"
            _rc_set(path, key, rec | {"at": time.time(), "bios_local": [n for n in _bios_local_names(rec.get("bios") or [])
                                                                        if (dest / n).exists()],
                                      "bios_copied_later": copied})
        except Exception as e:                       # noqa: BLE001 - the next stale launch tries again
            print(f"gBox: background BIOS check for {key} failed: {e}", flush=True)
        finally:
            _RC_REFRESHING.discard(key)
    threading.Thread(target=run, daemon=True, name=f"bios-{key}").start()


def runtime_check(cfg: Config, platform_: str, core: str | None = None, exe: str | None = None) -> dict:
    """ensure_platform for a launch, remembered per emulator version (core file + RetroArch executable).
    {"core": Path, "bios_copied": [...], "cached": bool}."""
    core0, bios = systems.core_for(platform_)
    key = f"{platform_}|{core or core0}"
    path = cfg.runtime / RUNTIME_CHECK
    rec = _rc_load(path).get(key) or {}
    exe_ident = _file_ident(exe) if exe else None
    dest = cfg.runtime / "system"
    if (rec.get("core") and _file_ident(rec["core"]) == rec.get("core_ident") and rec.get("exe_ident") == exe_ident
            and rec.get("bios") == list(bios) and all((dest / n).exists() for n in rec.get("bios_local") or [])):
        if time.time() - rec.get("at", 0) > RUNTIME_RECHECK_S:
            _refresh_bios_later(cfg, path, key, rec)
        return {"core": Path(rec["core"]), "bios_copied": [], "cached": True, "checked_at": rec.get("at")}
    core_path_, copied = ensure_platform(cfg, platform_, core)
    _rc_set(path, key, {"core": str(core_path_), "core_ident": _file_ident(core_path_), "exe": exe, "exe_ident": exe_ident,
                        "bios": list(bios), "bios_local": [n for n in _bios_local_names(list(bios)) if (dest / n).exists()],
                        "at": time.time()})
    return {"core": core_path_, "bios_copied": copied, "cached": False}


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
    for c in (shutil.which("7zz"), shutil.which("7z"), "C:/Program Files/7-Zip/7z.exe", "C:/Program Files (x86)/7-Zip/7z.exe"):
        if c and Path(c).exists():
            return c
    if HOST_OS == 'linux':
        try:
            apt_packages(['7zip'])
        except ProvisionError:
            apt_packages(['p7zip-full'])
        found = shutil.which('7zz') or shutil.which('7z')
        if not found:
            apt_packages(['p7zip-full'])
            found = shutil.which('7z')
        if not found:
            raise ProvisionError('7-Zip install failed')
        return found
    _run(["winget", "install", "-e", "--id", "7zip.7zip", "--silent", "--accept-source-agreements", "--accept-package-agreements"], 900)
    c = "C:/Program Files/7-Zip/7z.exe"
    if not Path(c).exists():
        raise ProvisionError("7-Zip install failed")
    return c


def flatpak_ok(app: str) -> bool:
    return shutil.which("flatpak") is not None and subprocess.run(["flatpak", "info", app], capture_output=True).returncode == 0


def ensure_flatpak(app: str):
    """Standalone emulators (Dolphin, PPSSPP, DuckStation) come from Flathub as prebuilt, sandboxed apps."""
    if flatpak_ok(app):
        return
    if not shutil.which("flatpak"):
        apt_packages(["flatpak"])
    subprocess.run(["sudo", "-n", "flatpak", "remote-add", "--if-not-exists", "flathub",
                    "https://dl.flathub.org/repo/flathub.flatpakrepo"], capture_output=True)
    r = subprocess.run(["sudo", "-n", "flatpak", "install", "-y", "--noninteractive", "flathub", app], capture_output=True, text=True)
    if r.returncode != 0 or not flatpak_ok(app):
        raise ToolUnavailable(f"could not install {app}: {r.stderr[-400:]}")


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
          "--set-version-string", "ProductName", "gBox", "--set-version-string", "CompanyName", "gBox",
          "--set-version-string", "InternalName", exe.stem, "--set-version-string", "OriginalFilename", exe.name], 120)


def _retroarch_windows(cfg: Config) -> str:
    """Branded copy of RetroArch for local play: shows as "gBox Game" in Task Manager and the volume mixer."""
    raw = _retroarch_windows_raw(cfg)
    branded = Path(raw).with_name("gBox Game.exe")
    if not branded.exists() or branded.stat().st_mtime < Path(raw).stat().st_mtime:
        shutil.copy2(raw, branded)
        try:
            brand_exe(cfg, branded, "gBox Game")
        except Exception:
            return raw                                       # unbranded still works
    return str(branded)


_RA_WIN: dict[str, str] = {}             # runtime root -> retroarch.exe (globbing the whole tree took ~0.5 s a launch)


def _retroarch_windows_raw(cfg: Config) -> str:
    """Native RetroArch for local play on a Windows node (full FPS, real audio, XInput pads, no stream)."""
    root = cfg.runtime / "retroarch-win"
    known = _RA_WIN.get(str(root))
    if known and Path(known).is_file():
        return known
    found = sorted(root.glob("**/retroarch.exe"))
    if found:
        _RA_WIN[str(root)] = str(found[0])
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
    """The operator's own Ghidra when it exists on this node (the Spark), else the one gBox installed into runtime."""
    if cfg.ghidra_home and Path(cfg.ghidra_home).exists():
        return Path(cfg.ghidra_home)
    found = sorted((cfg.runtime).glob("ghidra_*_PUBLIC"))
    return found[-1] if found else None


def jdk21(cfg: Config) -> Path | None:
    """A JDK 21 for Ghidra: apt's on Linux; on Windows a Temurin 21 zip unpacked into runtime (no admin, no PATH change)."""
    for p in ("/usr/lib/jvm/java-21-openjdk-arm64", "/usr/lib/jvm/java-21-openjdk-amd64"):
        if Path(p).exists():
            return Path(p)
    found = sorted(cfg.runtime.glob("jdk-21*"))
    return found[-1] if found else None


def ensure_jdk21(cfg: Config) -> dict:
    if jdk21(cfg):
        return _receipt("jdk21", "ok", str(jdk21(cfg)))
    if HOST_OS != "windows":
        apt_packages(["openjdk-21-jdk-headless"])
        return _receipt("jdk21", "installed", str(jdk21(cfg)))
    r = httpx.get("https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse",
                  timeout=1800, follow_redirects=True)
    r.raise_for_status()
    cfg.runtime.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(cfg.runtime)
    return _receipt("jdk21", "installed", str(jdk21(cfg)))


def rpcs3_home(cfg: Config) -> Path:
    return cfg.runtime / "rpcs3"


def _rpcs3_busy(home: Path) -> bool:
    """RPCS3 allows one running copy per folder ("Another instance ... RPCS3.buf still exists"): busy = an rpcs3.exe
    is running from this folder (its RPCS3.buf can be deleted while in use, so the file alone proves nothing)."""
    import ctypes
    import ctypes.wintypes as w
    k = ctypes.windll.kernel32
    target = str((home / "rpcs3.exe").resolve()).lower()
    ids, got = (w.DWORD * 4096)(), w.DWORD()
    ctypes.windll.psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(got))
    for pid in ids[:got.value // 4]:
        h = k.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        buf, n = ctypes.create_unicode_buffer(1024), w.DWORD(1024)
        try:
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and buf.value.lower() == target:
                return True
        finally:
            k.CloseHandle(h)
    return False


def rpcs3_free_home(cfg: Config) -> Path:
    """A folder RPCS3 can start from right now. Extra instances (rpcs3-2, -3...) share the firmware, games, caches and
    save states with the main one through junctions + hard links; only the lock and the log are their own."""
    main = rpcs3_home(cfg)
    if not _rpcs3_busy(main):
        return main
    for n in range(2, 6):
        home = cfg.runtime / f"rpcs3-{n}"
        if not home.exists():
            home.mkdir(parents=True)
            for f in main.iterdir():
                t = home / f.name
                if f.name in ("log",) or f.name.startswith("RPCS3.buf") or f.name.startswith("RPCS3.log"):
                    continue
                if f.is_dir():
                    subprocess.run(["cmd", "/c", "mklink", "/J", str(t), str(f)], check=True, capture_output=True)
                else:
                    os.link(f, t)
        if not _rpcs3_busy(home):
            return home
    raise RuntimeError("five RPCS3 games are already running on this PC")


def ensure_rpcs3(cfg: Config, progress=None) -> dict:
    """PS3: RPCS3 (official Windows build, sha256-checked) + Sony's PS3 system software, installed into the runtime."""
    if HOST_OS != "windows":
        raise ToolUnavailable("PS3 (RPCS3) runs on Windows nodes")
    home = rpcs3_home(cfg)
    exe = home / "rpcs3.exe"
    if not exe.exists():
        rel = httpx.get("https://api.github.com/repos/RPCS3/rpcs3-binaries-win/releases/latest", timeout=60).json()
        a = next(x for x in rel["assets"] if x["name"].endswith(".7z"))
        want = httpx.get(a["browser_download_url"] + ".sha256", timeout=60, follow_redirects=True).text.split()[0].lower()
        progress and progress(10, f"Downloading RPCS3 {a['name']}")
        data = httpx.get(a["browser_download_url"], timeout=1800, follow_redirects=True).content
        import hashlib
        if hashlib.sha256(data).hexdigest() != want:
            raise RuntimeError("RPCS3 download failed its sha256 check")
        home.mkdir(parents=True, exist_ok=True)
        arc = home / a["name"]
        arc.write_bytes(data)
        z = shutil.which("7z") or r"C:\Program Files\7-Zip\7z.exe"
        subprocess.run([z, "x", "-y", f"-o{home}", str(arc)], check=True, capture_output=True)
        arc.unlink()
    if not (home / "dev_flash" / "vsh" / "module" / "vsh.self").exists():
        lst = httpx.get("http://fus01.ps3.update.playstation.net/update/ps3/list/us/ps3-updatelist.txt", timeout=60).text
        url = re.search(r"CDN=(\S+?PS3UPDAT\.PUP)", lst)[1]
        progress and progress(30, "Downloading PS3 system software from Sony")
        pup = home / "PS3UPDAT.PUP"
        with httpx.stream("GET", url, timeout=1800) as r, open(pup, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        progress and progress(50, "Installing PS3 system software into RPCS3")
        p = subprocess.Popen([str(exe), "--installfw", str(pup)], cwd=home)
        t = time.time()
        while time.time() - t < 900 and not (home / "dev_flash" / "vsh" / "module" / "vsh.self").exists():
            time.sleep(2)
        time.sleep(5)                                      # let the installer finish writing the last modules
        p.kill()
        if not (home / "dev_flash" / "vsh" / "module" / "vsh.self").exists():
            raise RuntimeError("PS3 firmware install did not complete")
        pup.unlink()
    return _receipt("rpcs3", "ok", str(exe))


# --- PS3 on a Linux node (the Spark, aarch64) ---------------------------------------------------------------------------
RPCS3_LINUX_REPO = {"aarch64": "RPCS3/rpcs3-binaries-linux-arm64", "x86_64": "RPCS3/rpcs3-binaries-linux"}
PS3_UPDATE_LIST = "http://fus01.ps3.update.playstation.net/update/ps3/list/us/ps3-updatelist.txt"


def rpcs3_linux_home(cfg: Config) -> Path:
    """gBox's own RPCS3 on Linux: the extracted AppImage (squashfs-root) and RPCS3's XDG folders."""
    return cfg.runtime / "rpcs3-linux"


def rpcs3_linux_env(cfg: Config) -> dict:
    """RPCS3 on Linux keeps config.yml, dev_flash, dev_hdd0 (game data, saves), input configs and save states under
    $XDG_CONFIG_HOME/rpcs3 and its PPU/SPU/shader caches and RPCS3.log under $XDG_CACHE_HOME/rpcs3: gBox's own here,
    never the user's ~/.config."""
    home = rpcs3_linux_home(cfg)
    return {"XDG_CONFIG_HOME": str(home / "config"), "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_DATA_HOME": str(home / "data"), **linux_audio_env(),
            # FAudio uses bundled SDL3. The exact driver is enumerated by that
            # binary; Pulse keeps playback individually addressable by PID.
            "SDL_AUDIO_DRIVER": os.environ.get("SDL_AUDIO_DRIVER") or "pulseaudio"}


def linux_audio_env(env=None, *, runtime_dir=None) -> dict:
    """Connect service-launched games to this user's existing Pulse/PipeWire socket.

    A system service does not inherit a desktop login's runtime directory. Cubeb
    otherwise falls back to ALSA, which may have no device on a headless node.
    Explicit operator settings win; never select another user's audio server.
    """
    env = os.environ if env is None else env
    out = {key: env[key] for key in ("XDG_RUNTIME_DIR", "PULSE_SERVER") if env.get(key)}
    if not hasattr(os, "getuid"):
        return out
    uid = os.getuid()
    runtime = Path(out.get("XDG_RUNTIME_DIR") or runtime_dir or f"/run/user/{uid}")
    pulse = runtime / "pulse" / "native"
    try:
        info = pulse.stat()
        if info.st_uid == uid and stat.S_ISSOCK(info.st_mode):
            out.setdefault("XDG_RUNTIME_DIR", str(runtime))
            out.setdefault("PULSE_SERVER", "unix:" + str(pulse))
    except OSError:
        pass
    return out


def rpcs3_linux_dir(cfg: Config) -> Path:
    """RPCS3's own folder (config.yml, dev_flash, dev_hdd0, input_configs, savestates)."""
    return rpcs3_linux_home(cfg) / "config" / "rpcs3"


def rpcs3_linux_exe(cfg: Config) -> Path:
    """What starts RPCS3: [rpcs3_appimage] when it names an AppRun or an rpcs3 binary (a folder: its AppRun), else the
    AppImage gBox extracted into its home (no FUSE needed)."""
    p = Path(cfg.rpcs3_appimage).expanduser() if cfg.rpcs3_appimage else None
    if p and p.is_dir():
        for c in (p / "AppRun", p / "squashfs-root" / "AppRun", p / "usr" / "bin" / "rpcs3"):
            if c.is_file():
                return c
    if p and p.is_file() and not p.name.lower().endswith(".appimage"):
        return p
    return rpcs3_linux_home(cfg) / "squashfs-root" / "AppRun"


def _rpcs3_appimage_extract(appimage: Path, home: Path) -> None:
    """--appimage-extract into home/squashfs-root (the AppImage runs without FUSE afterwards)."""
    appimage.chmod(0o755)
    shutil.rmtree(home / "squashfs-root", ignore_errors=True)
    subprocess.run([str(appimage), "--appimage-extract"], cwd=home, check=True, capture_output=True, timeout=600)
    if not (home / "squashfs-root" / "AppRun").is_file():
        raise RuntimeError(f"{appimage.name} did not extract an AppRun")


def rpcs3_installfw_linux(exe: Path, pup: Path, env: dict, done: Path, timeout_s: float = 900.0) -> bool:
    """`rpcs3 --installfw` asks "Install firmware: <path>?" (default No) before installing, and RPCS3 needs its GUI for
    it: run it on a private Xvfb display and answer Yes with the box's own mnemonic (Alt+Y) once it shows; done = the
    file the install writes last (dev_flash/vsh/module/vsh.self)."""
    from .adapters import Display, _kill_tree
    disp = Display(1024, 768)
    e = {**os.environ, **env, "DISPLAY": disp.name, "QT_QPA_PLATFORM": "xcb"}
    p = subprocess.Popen([str(exe), "--installfw", str(pup)], env=e, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while time.time() - t0 < timeout_s and not done.exists() and p.poll() is None:
            box = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "Firmware"], env=e,
                                 capture_output=True, text=True).stdout.split()
            if box:
                subprocess.run(["xdotool", "windowfocus", box[0], "key", "alt+y"], env=e, capture_output=True)
            time.sleep(2)
        if done.exists():
            time.sleep(5)                                  # let the installer finish writing the last modules
        return done.exists()
    finally:
        _kill_tree(p)
        disp.close()


def ensure_rpcs3_linux(cfg: Config, progress=None) -> dict:
    """PS3 on a Linux node: RPCS3's official AppImage for this CPU (GitHub release, checked against the sha256 digest
    GitHub publishes for it) or [rpcs3_appimage], extracted once, + Sony's PS3 system software installed into gBox's
    own RPCS3 folder (verified on the Spark, aarch64, 2026-10-20: RPCS3 0.0.43 runs RE5 Gold at ~60 fps)."""
    if HOST_OS != "linux":
        raise ToolUnavailable("rpcs3 (linux): Linux nodes only; Windows nodes use ensure_rpcs3")
    home = rpcs3_linux_home(cfg)
    home.mkdir(parents=True, exist_ok=True)
    exe = rpcs3_linux_exe(cfg)
    conf = Path(cfg.rpcs3_appimage).expanduser() if cfg.rpcs3_appimage else None
    if conf and conf.is_file() and conf.name.lower().endswith(".appimage"):
        mark, stat = home / "squashfs-root.from", f"{conf} {conf.stat().st_size} {int(conf.stat().st_mtime)}"
        if not exe.is_file() or not mark.is_file() or mark.read_text() != stat:
            progress and progress(12, f"Unpacking {conf.name}")
            _rpcs3_appimage_extract(conf, home)
            mark.write_text(stat)
    elif not exe.is_file():
        repo = RPCS3_LINUX_REPO.get(ARCH)
        if not repo:
            raise ToolUnavailable(f"no RPCS3 Linux build for {ARCH}")
        rel = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=60).json()
        a = next(x for x in rel["assets"] if x["name"].endswith(".AppImage"))
        want = str(a.get("digest") or "").removeprefix("sha256:").lower()
        if not want:
            raise RuntimeError(f"GitHub publishes no sha256 digest for {a['name']}: not running it unchecked")
        progress and progress(10, f"Downloading RPCS3 {a['name']}")
        img, h = home / a["name"], __import__("hashlib").sha256()
        with httpx.stream("GET", a["browser_download_url"], timeout=1800, follow_redirects=True) as r, open(img, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != want:
            img.unlink(missing_ok=True)
            raise RuntimeError("RPCS3 download failed its sha256 check")
        _rpcs3_appimage_extract(img, home)
        img.unlink()
    done = rpcs3_linux_dir(cfg) / "dev_flash" / "vsh" / "module" / "vsh.self"
    if not done.exists():
        lst = httpx.get(PS3_UPDATE_LIST, timeout=60).text
        url = re.search(r"CDN=(\S+?PS3UPDAT\.PUP)", lst)[1]
        progress and progress(30, "Downloading PS3 system software from Sony")
        pup = home / "PS3UPDAT.PUP"
        with httpx.stream("GET", url, timeout=1800) as r, open(pup, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        progress and progress(50, "Installing PS3 system software into RPCS3")
        if not rpcs3_installfw_linux(exe, pup, rpcs3_linux_env(cfg), done):
            raise RuntimeError("PS3 firmware install did not complete")
        pup.unlink()
    return _receipt("rpcs3", "ok", str(exe))


def ensure_ghidra(cfg: Config) -> dict:
    ensure_jdk21(cfg)
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

_EM_X86_64, _EM_AARCH64 = 62, 183


def _elf_machine(path: Path) -> int | None:
    """e_machine of an ELF executable (0x3e = x86-64, 0xb7 = aarch64); None when not an ELF or unreadable."""
    try:
        head = open(path, "rb").read(20)
    except OSError:
        return None
    if len(head) < 20 or head[:4] != b"\x7fELF":
        return None
    return int.from_bytes(head[18:20], "little")


def find_blender(cfg: Config) -> str | None:
    """Newest Blender under blender_search. Builds sit 1-3 folders deep (Builds/daily/blender-x/blender.exe);
    a full rglob of a build library took ~100 s, so search shallow and cache for 10 min.
    On Linux the chosen binary must match the host architecture: an x86-64 Blender on aarch64 dies with
    'ld-linux-x86-64.so.2', and PATH order alone hands back /usr/local/bin/blender before /usr/bin/blender."""
    if cfg.blender_path and Path(cfg.blender_path).exists():
        foreign = (HOST_OS == "linux" and ARCH == "aarch64"
                   and _elf_machine(Path(cfg.blender_path)) == _EM_X86_64)
        if not foreign:
            return cfg.blender_path
    key = tuple(cfg.blender_search)
    hit = _blender_cache.get(key)
    if hit and time.time() - hit[0] < 600 and (hit[1] is None or Path(hit[1]).exists()):
        return hit[1]
    exe = "blender.exe" if HOST_OS == "windows" else "blender"
    found = [p for d in cfg.blender_search if Path(d).is_dir()
             for pat in (exe, f"*/{exe}", f"*/*/{exe}", f"*/*/*/{exe}") for p in Path(d).glob(pat)]
    if not found and HOST_OS == "windows":
        # A shared config can name another PC's user directory. Discover local
        # installations before declaring conversion unavailable on this worker.
        roots = [Path.home() / "Desktop" / "Blender Builds"]
        roots += [Path(value) / "Blender Foundation" for key in ("ProgramFiles", "ProgramFiles(x86)")
                  if (value := os.environ.get(key))]
        found = [p for d in dict.fromkeys(roots) if d.is_dir()
                 for pat in (exe, f"*/{exe}", f"*/*/{exe}", f"*/*/*/{exe}")
                 for p in d.glob(pat) if p.is_file()]
    if not found:
        cands = [shutil.which("blender")] if HOST_OS == "windows" else \
                [shutil.which("blender"), "/usr/local/bin/blender", "/usr/bin/blender"]
        found = [Path(c) for c in dict.fromkeys(cands) if c and Path(c).exists()]
    if found and HOST_OS == "linux" and ARCH in ("aarch64", "x86_64"):
        native = _EM_AARCH64 if ARCH == "aarch64" else _EM_X86_64
        nat = [p for p in found if _elf_machine(p) == native]
        if nat:
            found = nat                                 # never run an emulated foreign-arch Blender
    best = str(max(found, key=lambda p: p.stat().st_mtime)) if found else None   # newest build
    _blender_cache[key] = (time.time(), best)
    return best


def check_blender(cfg: Config) -> dict:
    b = find_blender(cfg)
    if not b:
        return _receipt("blender", "missing", f"searched {cfg.blender_search}")
    v = _run([b, "--version"], 120).stdout.splitlines()[0]
    return _receipt("blender", "ok", f"{v} @ {b}")


def install_blender_addon(cfg: Config) -> dict:
    """Install + enable the gBox Blender add-on (paste from gBox) for the Blender this node uses."""
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
    steps.append(('archives', lambda: _receipt('archives', 'ok', _seven_zip())))
    from .rea import install as install_rea
    steps.append(("rea", lambda: install_rea(cfg)))
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
        if with_ghidra:                    # x86_64 Windows has Ghidra's native decompiler (the arm64 Spark build lacks it)
            steps.append(("ghidra", lambda: ensure_ghidra(cfg)))
    receipts = []
    for name, fn in steps:
        try:
            r = fn()
        except Exception as e:
            r = _receipt(name, "failed", f"{type(e).__name__}: {e}")
        log(f"  {r['status']:9} {r['step']:24} {str(r.get('detail', r.get('path', '')))[:110]}")
        receipts.append(r)
    out = cfg.data_dir / f"provision-{HOST_OS}-{platform.node()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipts, indent=1))
    return receipts


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)
