"""Meta Quest games on a Windows worker through Refract Native: headset-free, in Refract's own PC viewer window.

    Based on Refract: https://github.com/MIXIDtheSilly/Refract (GPL-3.0-or-later, with a visible-credit term)

gBox runs Refract's official 1.0.2 Windows release as three separate processes, the way Refract's own
tools/run_native_game.ps1 -PcViewer does (research: docs/research/quest-refract-feasibility.md):
  pose_input_server.py   Xbox pad (XInput, read directly) and keyboard -> two Quest Touch controllers; TCP 38490 pose
                         stream (gBox's fork listens on 127.0.0.1 only), UDP 127.0.0.1:38495 scripted input
  refract_viewer.exe     the game's window on this PC (Win32 class RefractViewer, D3D11): the desktop app docks it,
                         and gBox captures (win_grab), records and stills it like any native emulator window
  refract_native.exe     runs the game's ARM64 code directly against Google's Android 14 system files: no emulator,
                         no headset, no SteamVR. Its /data (the game's saves) is <root>/data on this PC's D: drive.
Only the Refract scripts gBox had to change are in gbox/vendor/refract (GPL; LICENSE and NOTICE there): the installer
with the issue #38 loader fix, its private_libcxx.py, and the pose server (127.0.0.1 listener).

Ownership (the operator's rule, 2026-10-27): a Quest game starts only when it is the operator's own, shown either by
  * the operator's declaration in gbox.toml: [quest.owned."<package>"] with declared_by and declared_at (gBox never
    writes it; an entry without both is ignored), or
  * Refract's own Meta sign-in on that PC: its owned-library sync lists the game with owned=true, source="meta" in
    %APPDATA%\\Refract\\library.json. gBox never signs in for the operator and never reads or stores Meta tokens.
Then, and only for that package, gBox passes Refract's owner flag to the game (debug.refract.platform.owned.<pkg>=1,
what Refract's -Owned switch and scripts\\owned_games.txt do), and the session records which proof was used.
Otherwise the launch is refused before anything is downloaded, installed or started.

Setup is on demand, on the PCs listed in [quest] workers only (never a system drive): the pinned Refract release from
GitHub (sha256), Google's Android build-tools 36 and Android 14 ARM64 system image (sha1, as Refract's Settings > Setup
pins them; downloading them accepts the Android SDK License Agreement), ext4==1.2.4 for Refract's sysroot tool (Refract
issue #39: ext4 1.2.2 padded every extracted file; 1.2.3 fixed the over-read), a private copy of the game's APK and
OBBs taken read-only from the library share, then the game converted for Refract Native with the issue #38 fix.
Everything heavy runs on the worker itself in a background thread, so a launch whose job time runs out leaves the
setup going; the next launch continues where it is.
Layout under the root (default D:/gBox/refract):
  Refract-1.0.2-win64/   the official release, unmodified       sdk/      build-tools + Android 14 ARM64 image
  sysroot/               Android system files (make_sysroot.py) pylib/    ext4 and its two dependencies
  packages/<pkg>/<vc>/   the game's APK + obb/ copy             apps/     converted games (lib/arm64, classes.jar)
  data/                  the guest /data (saves)                logs/, shots/, tmp/, downloads/
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from .config import HOST_OS, Config, QuestConfig
from .registry import ToolUnavailable, Unsupported

CREDIT = "Based on Refract: https://github.com/MIXIDtheSilly/Refract"
VENDOR = Path(__file__).resolve().parent / "vendor" / "refract"
REFRACT = {"version": "1.0.2", "tag": "v1.0.2", "commit": "c0e83a847d74aef67379607d79413cd349503d97",
           "url": "https://github.com/MIXIDtheSilly/Refract/releases/download/v1.0.2/Refract-1.0.2-win64.zip",
           "sha256": "196229a244c1f3c3e5ab0b97ca8a176f348772fa97b4917d19cbe39481bcb380", "size": 111722943,
           "folder": "Refract-1.0.2-win64"}
# The parts of the release gBox runs or converts with (tools/package_release.ps1 puts them there).
RELEASE_FILES = ("build-native/refract_native.exe", "viewer/build/refract_viewer.exe",
                 "build-native/java/refract-android.jar", "native/tools/make_sysroot.py",
                 "native/java/tools/ShimBuilder.java", "tools/dex2jar/d2j-dex2jar.bat",
                 "jdk/bin/java.exe", "jdk/bin/javac.exe", "jdk/bin/server/jvm.dll",
                 "build-windows-gpu-layer/Release/refract_gpu_layer.json",
                 "build-android-runtime-windows-arm64-v8a/systemdriver/package/lib/arm64-v8a/libopenxr_runtime.so",
                 "build-android-runtime-windows-arm64-v8a/systemdriver/package/lib/arm64-v8a/librefract_driver.so",
                 "build-platform-sdk/package/lib/arm64-v8a/librefract_ovrplatform.so")
GOOGLE = "https://dl.google.com/android/repository/"
# Checksums and sizes as Google's repository lists them, the versions Refract 1.0.2 pins (launcher/core/android_sdk.mjs).
BUILD_TOOLS = {"label": "Android build tools 36", "file": "build-tools_r36_windows.zip",
               "sha1": "f16ccffd34de8790dede813a6c7d8e2c11a27b50", "size": 58699878, "dir": "build-tools/36.0.0"}
SYSTEM_IMAGE = {"label": "Android 14 ARM64 system files", "file": "sys-img/android/arm64-v8a-34_r04.zip",
                "sha1": "d9f2011131919abe952814e041f16f317242c3fa", "size": 705115396,
                "dir": "system-images/android-34/default/arm64-v8a"}
EXT4 = "ext4==1.2.4"
POSE_PORT, VIEWER_PORT, CONTROL_PORT = 38490, 38491, 38495
TITLES = {"com.Armature.VR4": "Resident Evil 4 VR"}
PACKAGE_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
OBB_RX = re.compile(r"^(main|patch)\.(\d+)\.([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\.obb$", re.I)
VIEWER_TITLE_RX = re.compile(r"\|\s*game\s+(\d+)\s+fps,\s*shown\s+(\d+)\s+fps\s*\(([^)]*)\)")
# Launch errors that are a setup state, not a fault (gbox/launch_failures.py files no ticket for them).
NOT_A_FAILURE_RX = re.compile(r"is not confirmed as the operator's own|Refract setup for .+ (?:is still running|finished)")
INSTALL_RECEIPT, PACKAGE_RECEIPT, RELEASE_RECEIPT = ".gbox-install.json", ".gbox-package.json", ".gbox-refract.json"


class OwnershipRequired(ToolUnavailable):
    """Neither an operator declaration nor Refract's Meta sign-in shows this game as the operator's own."""


class SetupStillRunning(ToolUnavailable):
    """The background setup (downloads, the game copy, conversion) outlived this launch job; it keeps going."""


# ------------------------------------------------------------------------------------------------ ownership

def quest_config(config: Config) -> QuestConfig:
    return getattr(config, "quest", None) or QuestConfig()


def declaration(config: Config, package: str) -> dict | None:
    """The operator's own declaration for this package, or None. gBox reads it; nothing in gBox writes it."""
    entry = quest_config(config).owned.get(package)
    if entry is None:
        return None
    row = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
    row = {k: str(row.get(k) or "").strip() for k in ("title", "declared_by", "declared_at", "statement")}
    return row if row["declared_by"] and row["declared_at"] else None


def meta_library_path(env=None) -> Path | None:
    appdata = (os.environ if env is None else env).get("APPDATA")
    return Path(appdata) / "Refract" / "library.json" if appdata else None


def meta_record(package: str, path: Path | None = None) -> dict | None:
    """Refract's own record of a Meta-verified owned game: its launcher's owned-library sync sets owned=true on games
    from the signed-in account (source "meta") and clears it on every sync; imported APKs never get it."""
    path = path or meta_library_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    for game in (data.get("games") or []) if isinstance(data, dict) else []:
        if isinstance(game, dict) and game.get("package") == package and game.get("owned") is True \
                and game.get("source") == "meta":
            return game
    return None


def ownership(config: Config, package: str, *, library: Path | None = None) -> dict:
    if found := declaration(config, package):
        return {"owned": True, "via": "declaration", **found}
    if game := meta_record(package, library):
        return {"owned": True, "via": "meta", "library": str(library or meta_library_path()),
                "name": str(game.get("name") or ""), "meta_id": str(game.get("id") or "")}
    return {"owned": False}


def require_owned(config: Config, package: str, title: str, node: str, *, library: Path | None = None) -> dict:
    found = ownership(config, package, library=library)
    if found["owned"]:
        return found
    raise OwnershipRequired(
        f"{title} ({package}) is not confirmed as the operator's own on this gBox, so it was not started and "
        f"Refract's owner flag stays off. Either declare ownership yourself in gbox.toml:\n"
        f"[quest.owned.\"{package}\"]\ndeclared_by = \"<your name>\"\ndeclared_at = \"<date>\"\n"
        f"statement = \"I own this game.\"\n"
        f"or sign into Meta in Refract on {node}: Refract's owned-library sync then lists the game as yours in "
        f"%APPDATA%\\Refract\\library.json.")


# ------------------------------------------------------------------------------------------------ packages

def _package_of(names: list[str], hint: str | None = None) -> str | None:
    found = {m.group(3) for n in names if (m := OBB_RX.match(PurePosixPath(n).name))}
    if hint and PACKAGE_RX.match(hint):
        return hint
    if len(found) == 1:
        return found.pop()
    stems = {PurePosixPath(n).stem for n in names if n.lower().endswith(".apk")}
    stems = {s for s in stems if PACKAGE_RX.match(s)}
    return stems.pop() if len(stems) == 1 else None


def select_members(members: list[tuple[str, int, int]], hint: str | None = None) -> dict | None:
    """members = [(name, size, crc)] of a zip or folder -> {package, version_code, apk, obb, size}; None when it holds
    no Quest package (no APK). The APK may be stored twice (Meta's name and <package>.apk): identical copies are one."""
    names = [m[0] for m in members]
    apks = [m for m in members if m[0].lower().endswith(".apk")]
    if not apks:
        return None
    package = _package_of(names, hint)
    if not package:
        raise ValueError("no package name: expected main.<version>.<package>.obb or <package>.apk")
    if len({(m[1], m[2]) for m in apks}) > 1:
        raise ValueError("several different APKs (" + ", ".join(m[0] for m in apks) + "): one game per zip or folder")
    named = [m for m in apks if PurePosixPath(m[0]).name == f"{package}.apk"]
    apk = named[0] if named else sorted(apks, key=lambda m: (m[0].count("/"), m[0]))[0]
    obb = sorted(m for m in members if (o := OBB_RX.match(PurePosixPath(m[0]).name)) and o.group(3) == package)
    codes = {OBB_RX.match(PurePosixPath(m[0]).name).group(2) for m in obb}
    if len(codes) > 1:
        raise ValueError(f"OBB files of several versions: {', '.join(sorted(codes))}")
    return {"package": package, "version_code": int(codes.pop()) if codes else None, "apk": apk[0],
            "apk_size": apk[1], "apk_crc": apk[2], "obb": [m[0] for m in obb],
            "size": apk[1] + sum(m[1] for m in obb)}


def zip_members(path: Path) -> list[tuple[str, int, int]]:
    with zipfile.ZipFile(path) as z:
        return [(i.filename, i.file_size, i.CRC) for i in z.infolist() if not i.is_dir()]


def folder_members(path: Path) -> list[tuple[str, int, int]]:
    out = []
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path)
        if p.is_file() and len(rel.parts) <= 3 and p.suffix.lower() in (".apk", ".obb"):
            out.append((rel.as_posix(), p.stat().st_size, 0))
    return out


def scan_refract(root: Path, lib_id: str) -> tuple[list, list[str]]:
    """A `quest` library (gbox.toml kind = "quest"): each zip or folder directly under root that holds one Quest
    package (an APK, and OBBs main/patch.<version>.<package>.obb) becomes one platform "quest" catalog entry, played
    through Refract on a [quest] worker. Only zip directories / file names are read: nothing is unpacked here."""
    from .catalog import _gid
    from .models import CatalogEntry
    entries, problems = [], []
    for item in sorted(Path(root).iterdir(), key=lambda p: p.name.lower()):
        try:
            if item.is_file() and item.suffix.lower() == ".zip":
                info, container = select_members(zip_members(item)), "zip"
            elif item.is_dir():
                info, container = select_members(folder_members(item), item.name), "folder"
            else:
                continue
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            problems.append(f"{item.name}: {e}")
            continue
        if not info:
            continue
        rel = item.name
        gid = _gid(lib_id, rel)
        title = TITLES.get(info["package"]) or re.sub(r"[\s_]+", " ", Path(rel).stem).strip()
        entries.append(CatalogEntry(
            game_id=gid, title=title, platform="quest", platform_confidence="manifest", source_paths=[rel],
            library=lib_id, rel_path=rel, system="Meta Quest", collections=["Meta Quest"], size=info["size"],
            format=f"quest_{container}", runtimes={"refract": "windows-node"}, profile_id=gid,
            launch={"kind": "refract", "package": info["package"], "version_code": info["version_code"],
                    "container": container, "apk": info["apk"], "obb": info["obb"]}))
    return entries, problems


# ------------------------------------------------------------------------------------------------ setup

class Layout:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.release = self.root / REFRACT["folder"]
        for name in ("downloads", "sdk", "sysroot", "pylib", "packages", "apps", "data", "logs", "shots", "tmp"):
            setattr(self, name, self.root / name)

    @property
    def aapt2(self) -> Path:
        return self.sdk / BUILD_TOOLS["dir"] / "aapt2.exe"

    @property
    def system_img(self) -> Path:
        return self.sdk / SYSTEM_IMAGE["dir"] / "system.img"


def root(config: Config) -> Path:
    path = quest_config(config).root.get(HOST_OS)
    if not path:
        raise ToolUnavailable(f"[quest] root has no folder for {HOST_OS} in gbox.toml")
    return Path(os.path.expandvars(path))


def check_node(config: Config, node: str | None = None) -> Path:
    """The Refract root on this PC, or why Quest games can't be set up here."""
    node = node or platform.node()
    if HOST_OS != "windows":
        raise ToolUnavailable("Meta Quest games run in Refract Native on a Windows x64 worker")
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise ToolUnavailable("Refract Native needs 64-bit x86 Windows")
    workers = quest_config(config).workers
    if not any(node.casefold() == w.casefold() for w in workers):
        raise ToolUnavailable(f"Meta Quest games are set up only on {', '.join(workers) or 'no PC yet'} ([quest] "
                              f"workers in gbox.toml); Refract and each game's ~10 GB copy are not on {node}.")
    path = root(config)
    from . import storage_policy
    drive = storage_policy.system_drive()
    if storage_policy.on_system_drive(path, drive=drive or ""):
        raise storage_policy.SystemDriveRefused(
            f"gBox keeps game data off this PC's system drive ({drive}): the Refract root would be {path}. Set "
            "[quest] root = { windows = \"D:/gBox/refract\" } in gbox.toml.")
    return path


def python() -> str:
    """The interpreter for Refract's Python scripts (standard library only, plus ext4 on PYTHONPATH for make_sysroot):
    the base interpreter itself. A venv's python.exe on Windows is a launcher that starts the real interpreter as its
    child, so the pid gBox holds would not be the process that listens on the pose port."""
    base = getattr(sys, "_base_executable", None)
    return base if base and Path(base).is_file() else sys.executable


def _env(lay: Layout, **extra) -> dict:
    lay.tmp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TEMP=str(lay.tmp), TMP=str(lay.tmp), PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    env.pop("PYTHONPATH", None)
    return env | {k: str(v) for k, v in extra.items()}


def _digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _step(update, lo: float, hi: float):
    return lambda pct, msg: update(lo + (hi - lo) * max(0.0, min(100.0, pct)) / 100.0, msg)


def download(url: str, dest: Path, size: int, digest: str, algo: str, label: str, update=lambda *_: None) -> Path:
    """A pinned file, resumed from its .part, checked against its published size and hash before it is kept."""
    if dest.is_file() and dest.stat().st_size == size and _digest(dest, algo) == digest:
        return dest
    import httpx
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if have >= size:
        part.unlink()
        have = 0
    headers = {"User-Agent": "gBox-refract-setup"} | ({"Range": f"bytes={have}-"} if have else {})
    with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                      timeout=httpx.Timeout(60.0, read=120.0)) as r:
        if r.status_code not in (200, 206):
            raise ToolUnavailable(f"{label}: download failed (HTTP {r.status_code} from {url})")
        if have and r.status_code != 206:
            have = 0                                     # the server sent the whole file again
        done, shown = have, 0.0
        with open(part, "ab" if have else "wb") as out:
            for chunk in r.iter_bytes(1 << 20):
                done += len(chunk)
                if done > size:
                    raise ToolUnavailable(f"{label}: the download is larger than its published size")
                out.write(chunk)
                if time.monotonic() - shown > 1.0:
                    shown = time.monotonic()
                    update(100.0 * done / size, f"Downloading {label} ({done / 2**20:,.0f} of {size / 2**20:,.0f} MB)")
    if part.stat().st_size != size:
        raise ToolUnavailable(f"{label}: the download stopped at {part.stat().st_size:,} of {size:,} bytes; "
                              "the next launch resumes it")
    if _digest(part, algo) != digest:
        part.unlink()
        raise ToolUnavailable(f"{label}: the download failed its {algo} check and was deleted")
    os.replace(part, dest)
    return dest


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in name or not path.parts:
        raise ToolUnavailable(f"unsafe archive member: {name}")
    return path


def extract_single_folder(archive: Path, final: Path, top: str | None, label: str, update=lambda *_: None) -> Path:
    """Unpack an archive whose members share one top folder into `final` (staged beside it, then renamed)."""
    stage = final.with_name(final.name + ".gbox-stage")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        tops = set()
        for n, info in enumerate(infos):
            rel = _safe_name(info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ToolUnavailable(f"{label}: archive member is a symbolic link: {info.filename}")
            tops.add(rel.parts[0])
            target = stage.joinpath(*rel.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            if n % 50 == 0:
                update(100.0 * n / max(1, len(infos)), f"Unpacking {label}")
    if len(tops) != 1 or (top and tops != {top}):
        shutil.rmtree(stage, ignore_errors=True)
        raise ToolUnavailable(f"{label}: unexpected archive layout (top folders: {', '.join(sorted(tops))})")
    if final.exists():
        shutil.rmtree(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage / tops.pop(), final)
    shutil.rmtree(stage, ignore_errors=True)
    return final


def ensure_refract(lay: Layout, update=lambda *_: None) -> Path:
    """The official Refract 1.0.2 Windows release (GitHub, sha256-pinned), unpacked once and never modified."""
    receipt = lay.release / RELEASE_RECEIPT
    if receipt.is_file() and all((lay.release / f).is_file() for f in RELEASE_FILES):
        return lay.release
    if lay.release.exists() and not receipt.is_file():
        raise ToolUnavailable(f"{lay.release} exists but gBox did not install it (no {RELEASE_RECEIPT}); move it "
                              "aside so gBox can install the pinned official release there")
    archive = download(REFRACT["url"], lay.downloads / Path(REFRACT["url"]).name, REFRACT["size"], REFRACT["sha256"],
                       "sha256", f"Refract {REFRACT['version']}", _step(update, 0, 80))
    extract_single_folder(archive, lay.release, REFRACT["folder"], f"Refract {REFRACT['version']}", _step(update, 80, 100))
    missing = [f for f in RELEASE_FILES if not (lay.release / f).is_file()]
    if missing:
        raise ToolUnavailable(f"the Refract {REFRACT['version']} release lacks {', '.join(missing)}")
    receipt.write_text(json.dumps({k: REFRACT[k] for k in ("version", "tag", "commit", "url", "sha256", "size")}
                                  | {"credit": CREDIT, "at": time.time()}, indent=1), encoding="utf-8")
    archive.unlink(missing_ok=True)
    return lay.release


def ensure_ext4(lay: Layout, update=lambda *_: None) -> Path:
    """ext4 pinned (Refract issue #39) for make_sysroot.py, in gBox's own folder: the worker's packages stay as they are."""
    marker = lay.pylib / ".gbox-ext4.json"
    try:
        if json.loads(marker.read_text(encoding="utf-8")).get("pin") == EXT4 and (lay.pylib / "ext4").is_dir():
            return lay.pylib
    except (OSError, ValueError):
        pass
    update(0, f"Installing {EXT4} for Refract's Android system files tool")
    shutil.rmtree(lay.pylib, ignore_errors=True)
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--no-input", "--no-cache-dir", "--target",
                        str(lay.pylib), EXT4], capture_output=True, text=True, timeout=900, env=_env(lay))
    _log(lay, "setup-ext4.log", r)
    if r.returncode or not (lay.pylib / "ext4").is_dir():
        raise ToolUnavailable(f"installing {EXT4} failed: {(r.stderr or r.stdout)[-800:]}")
    marker.write_text(json.dumps({"pin": EXT4, "at": time.time()}), encoding="utf-8")
    return lay.pylib


def ensure_sdk(lay: Layout, update=lambda *_: None) -> dict:
    """aapt2 (game manifests) and the stock Android 14 ARM64 image (system files), from Google's SDK repository."""
    for item, ready, lo, hi in ((BUILD_TOOLS, lay.aapt2, 0, 15), (SYSTEM_IMAGE, lay.system_img, 15, 100)):
        if ready.is_file():
            continue
        archive = download(GOOGLE + item["file"], lay.downloads / Path(item["file"]).name, item["size"], item["sha1"],
                           "sha1", item["label"], _step(update, lo, lo + (hi - lo) * 0.8))
        extract_single_folder(archive, lay.sdk / item["dir"], None, item["label"],
                              _step(update, lo + (hi - lo) * 0.8, hi))
        if not ready.is_file():
            raise ToolUnavailable(f"{item['label']}: {ready.name} is missing after unpacking")
        archive.unlink(missing_ok=True)
    return {"aapt2": lay.aapt2, "image": lay.system_img}


def sysroot_ok(path: Path) -> bool:
    """make_sysroot.py finished (it writes refract_symlinks.txt last) and the pieces issue #39 lost are there."""
    lib64 = path / "system" / "lib64"
    return ((path / "refract_symlinks.txt").is_file() and (path / "system" / "bin" / "linker64").is_file()
            and (path / "apex" / "com.android.runtime").is_dir() and (path / "apex" / "com.android.art").is_dir()
            and lib64.is_dir() and sum(1 for _ in lib64.glob("*.so")) >= 50)


def ensure_sysroot(lay: Layout, update=lambda *_: None) -> Path:
    if sysroot_ok(lay.sysroot):
        return lay.sysroot
    pylib = ensure_ext4(lay, _step(update, 0, 20))
    update(20, "Preparing Android's system files for Refract Native (make_sysroot.py)")
    stage = lay.root / "sysroot.gbox-stage"
    shutil.rmtree(stage, ignore_errors=True)
    r = subprocess.run([python(), "-s", str(lay.release / "native" / "tools" / "make_sysroot.py"), str(stage),
                        "--image", str(lay.system_img)], cwd=lay.release, capture_output=True, text=True,
                       timeout=3600, env=_env(lay, PYTHONPATH=pylib))
    _log(lay, "setup-sysroot.log", r)
    if r.returncode or not sysroot_ok(stage):
        raise ToolUnavailable("building Refract Native's Android system files failed (no complete sysroot: "
                              f"linker64/apex missing is Refract issue #39): {(r.stderr or r.stdout)[-800:]}")
    if lay.sysroot.exists():
        shutil.rmtree(lay.sysroot)
    os.replace(stage, lay.sysroot)
    return lay.sysroot


def stage_package(lay: Layout, launch: dict, source: Path, update=lambda *_: None) -> dict:
    """A private copy of the game's APK and OBBs under packages/<package>/<version>/, read-only from the library
    (a zip or folder there is never written). Each file is verified (the zip's CRC-32, or its size for a folder)."""
    package = launch.get("package") or ""
    if not PACKAGE_RX.match(package):
        raise ToolUnavailable(f"invalid Android package name: {package!r}")
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Quest package not reachable from this node: {source}")
    container = "zip" if source.is_file() else "folder"
    members = zip_members(source) if container == "zip" else folder_members(source)
    info = select_members(members, package)
    if not info or info["package"] != package:
        raise ToolUnavailable(f"{source.name} does not hold {package}")
    dest = lay.packages / package / str(info["version_code"] or 0)
    receipt_path = dest / PACKAGE_RECEIPT
    st = source.stat()
    identity = {"source": str(source), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "members": [list(m) for m in members]}                 # as it reads back from the JSON receipt
    files = [(info["apk"], dest / f"{package}.apk")] + [(m, dest / "obb" / PurePosixPath(m).name) for m in info["obb"]]
    sizes = {name: size for name, size, _ in members}
    try:
        done = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    if done.get("identity") == identity and done.get("package") \
            and all(t.is_file() and t.stat().st_size == sizes[m] for m, t in files):
        return done["package"]
    need = sum(sizes[m] for m, t in files if not (t.is_file() and t.stat().st_size == sizes[m]))
    lay.packages.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(lay.packages).free
    if free < need + (2 << 30):
        raise ToolUnavailable(f"not enough room for {package}: {need / 2**30:.1f} GB to copy, "
                              f"{free / 2**30:.1f} GB free on {lay.packages.anchor}")
    verified = {k: v for k, v in (done.get("verified") or {}).items() if done.get("identity") == identity}
    total, copied = max(1, need), 0
    reader = open(source, "rb", buffering=8 << 20) if container == "zip" else None
    try:
        z = zipfile.ZipFile(reader) if reader else None
        for member, target in files:
            if target.is_file() and target.stat().st_size == sizes[member] and verified.get(member):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            src = z.open(member) if z else open(source / member, "rb")
            with src, open(part, "wb") as out:          # a zip member's CRC-32 is checked when it is read to its end
                while block := src.read(8 << 20):
                    out.write(block)
                    copied += len(block)
                    update(100.0 * copied / total, f"Copying {PurePosixPath(member).name} for Refract "
                                                   f"({copied / 2**30:.1f} of {total / 2**30:.1f} GB)")
            if part.stat().st_size != sizes[member]:
                raise ToolUnavailable(f"{member}: copied {part.stat().st_size:,} of {sizes[member]:,} bytes")
            os.replace(part, target)
            verified[member] = "crc32" if z else "size"
            receipt_path.write_text(json.dumps({"identity": identity, "verified": verified}), encoding="utf-8")
    finally:
        if reader:
            reader.close()
    package_info = {"package": package, "version_code": info["version_code"], "dir": str(dest),
                    "apk": str(dest / f"{package}.apk"), "apk_size": info["apk_size"], "apk_crc": info["apk_crc"],
                    "obb_dir": str(dest / "obb") if info["obb"] else None, "source": str(source)}
    receipt_path.write_text(json.dumps({"identity": identity, "verified": verified, "package": package_info,
                                        "at": time.time()}, indent=1), encoding="utf-8")
    return package_info


def installer_version() -> str:
    h = hashlib.sha256()
    for name in ("install_apk.py", "private_libcxx.py"):
        h.update((VENDOR / name).read_bytes())
    return h.hexdigest()[:16]


def install_app(lay: Layout, package: dict, update=lambda *_: None) -> dict:
    """Convert the game for Refract Native (gBox's fork of Refract's install_apk.py: the issue #38 fix included)."""
    app = lay.apps / package["package"]
    want = {"apk": [package["apk"], package["apk_size"], package["apk_crc"]], "installer": installer_version(),
            "refract": REFRACT["version"]}
    try:
        done = json.loads((app / INSTALL_RECEIPT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    if done.get("want") == want and (app / "app.properties").is_file() and (app / "classes.jar").is_file():
        return done
    update(0, f"Converting {package['package']} for Refract Native (dex2jar, Android shims, issue #38 fix)")
    r = subprocess.run([python(), "-s", "-E", str(VENDOR / "install_apk.py"), package["apk"],
                        "--refract-root", str(lay.release), "--sdk", str(lay.sdk), "--apps", str(lay.apps)],
                       capture_output=True, text=True, timeout=1800, env=_env(lay))
    _log(lay, f"install-{package['package']}.log", r)
    if r.returncode or not (app / "app.properties").is_file():
        raise ToolUnavailable(f"Refract could not convert {package['package']}: {(r.stderr or r.stdout)[-1200:]}")
    try:
        reports = json.loads((app / "gbox-private-libcxx.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reports = []
    rebind = {row["library"]: {"rebound": row.get("applied", 0), "skipped": len(row.get("skipped") or [])}
              for row in reports if row.get("eligible")}
    out = {"want": want, "app": str(app), "libcxx_rebind": rebind, "at": time.time()}
    (app / INSTALL_RECEIPT).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def _log(lay: Layout, name: str, result: subprocess.CompletedProcess) -> None:
    try:
        lay.logs.mkdir(parents=True, exist_ok=True)
        (lay.logs / name).write_text(f"$ {' '.join(map(str, result.args))}\nexit {result.returncode}\n"
                                     f"--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}\n", encoding="utf-8")
    except OSError:
        pass


def setup(config: Config, launch: dict, source: Path | None, update=lambda *_: None) -> dict:
    """Everything a Quest game needs on this PC, idempotent: each step checks its receipt and returns at once when done."""
    lay = Layout(check_node(config))
    for d in (lay.root, lay.data, lay.logs, lay.shots, lay.tmp):
        d.mkdir(parents=True, exist_ok=True)
    update(0, f"Refract {REFRACT['version']} on this PC ({CREDIT})")
    ensure_refract(lay, _step(update, 0, 10))
    ensure_sdk(lay, _step(update, 10, 35))
    ensure_sysroot(lay, _step(update, 35, 45))
    if source is not None:
        package = stage_package(lay, launch, source, _step(update, 45, 92))
    elif launch.get("apk") and Path(launch["apk"]).is_file():          # a game already on this PC (a local APK)
        apk = Path(launch["apk"])
        package = {"package": launch["package"], "version_code": launch.get("version_code"), "apk": str(apk),
                   "apk_size": apk.stat().st_size, "apk_crc": int(apk.stat().st_mtime_ns), "source": str(apk),
                   "obb_dir": launch.get("obb_dir") if launch.get("obb_dir") and Path(launch["obb_dir"]).is_dir() else None}
    else:
        raise ToolUnavailable(f"no APK for {launch.get('package')} on this PC")
    installed = install_app(lay, package, _step(update, 92, 100))
    update(100, "Refract Native is ready")
    return {"layout": lay, "package": package, "install": installed}


class _Setup:
    def __init__(self, fn):
        self.pct, self.message, self.result, self.error = 0.0, "starting", None, None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(fn,), daemon=True, name="refract-setup")

    def update(self, pct: float, msg: str):
        self.pct, self.message = max(self.pct, float(pct)), msg

    def _run(self, fn):
        try:
            self.result = fn(self.update)
        except BaseException as e:                              # noqa: BLE001 - reported to the waiting launch
            self.error = e
        finally:
            self.done.set()


_SETUPS: dict[str, _Setup] = {}
_SETUPS_LOCK = threading.Lock()


def run_setup(key: str, fn, progress, deadline: float | None, label: str, node: str) -> dict:
    """Run (or join) the background setup for `key`, mirroring its progress until it ends or the job's time runs out."""
    with _SETUPS_LOCK:
        job = _SETUPS.get(key)
        if job is None:
            job = _SETUPS[key] = _Setup(fn)
            job.thread.start()
    shown = None
    while not job.done.wait(1.0):
        if (round(job.pct), job.message) != shown:
            shown = (round(job.pct), job.message)
            progress(5 + job.pct * 0.65, job.message)
        if deadline is not None and time.monotonic() > deadline - 45:
            raise SetupStillRunning(f"Refract setup for {label} is still running on {node} ({job.message}, "
                                    f"{job.pct:.0f}%). It continues in the background; start the game again "
                                    "in a few minutes.")
    with _SETUPS_LOCK:
        if _SETUPS.get(key) is job:
            _SETUPS.pop(key)                                    # the next launch re-checks (fast once all is in place)
    if job.error is not None:
        raise job.error
    return job.result


# ------------------------------------------------------------------------------------------------ the session

class _JobObject:
    """A Windows job object holding this session's three processes: they end together with it, and with the worker
    (KILL_ON_JOB_CLOSE), so no Refract process outlives its session. Best effort: a failure leaves the watcher."""
    def __init__(self):
        self.handle, self.ok = None, False
        if HOST_OS != "windows":
            return
        from ctypes import wintypes as w
        k = self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = w.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.CloseHandle.argtypes = [w.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        handle = k.CreateJobObjectW(None, None)
        if not handle:
            return
        info = Extended()
        info.Basic.LimitFlags = 0x2000                          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k.CloseHandle(handle)
            return
        self.handle, self.ok = handle, True

    def add(self, proc) -> bool:
        if not self.handle or proc is None:
            return False
        from ctypes import wintypes as w
        added = bool(self.k.AssignProcessToJobObject(self.handle, w.HANDLE(int(proc._handle))))
        self.ok = self.ok and added
        return added

    def close(self, terminate: bool = True):
        if self.handle:
            if terminate:
                self.k.TerminateJobObject(self.handle, 1)
            self.k.CloseHandle(self.handle)
            self.handle = None


class _SessionProcess:
    """Process-like view of the session for gBox (liveness, pid): it runs while the viewer and the game both run.
    pid is the viewer's, the window gBox docks, captures and records."""
    def __init__(self, owner: "RefractAdapter"):
        self.owner = owner

    @property
    def pid(self):
        return self.owner.viewer.pid if self.owner.viewer else None

    @property
    def returncode(self):
        return self.poll()

    def poll(self):
        procs = [p for p in (self.owner.viewer, self.owner.native) if p is not None]
        if procs and all(p.poll() is None for p in procs):
            return None
        native = self.owner.native.poll() if self.owner.native else None
        return native if native is not None else next((p.poll() for p in procs if p.poll() is not None), 0)

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if end is not None and time.monotonic() > end:
                raise subprocess.TimeoutExpired("refract", timeout)
            time.sleep(0.1)
        return self.poll()


# gBox pad names -> Refract's scripted Touch input (pose_input_server.py UDP: hold <hand> <button> <s>, stick ...).
# The d-pad has no Quest equivalent and is ignored: the web client forwards the operator's left stick as d-pad
# presses, and those must not override the analog stick Refract reads from the pad itself.
BUTTONS = {"a": ("right", "a"), "b": ("right", "b"), "x": ("left", "x"), "y": ("left", "y"),
           "start": ("left", "menu"), "menu": ("left", "menu"), "l": ("left", "grip"), "l1": ("left", "grip"),
           "r": ("right", "grip"), "r1": ("right", "grip"), "l2": ("left", "trigger"), "r2": ("right", "trigger"),
           "l3": ("left", "stick"), "r3": ("right", "stick")}
STICKS = {"lup": ("left", 0, 1), "ldown": ("left", 0, -1), "lleft": ("left", -1, 0), "lright": ("left", 1, 0),
          "rup": ("right", 0, 1), "rdown": ("right", 0, -1), "rleft": ("right", -1, 0), "rright": ("right", 1, 0)}
HOLD_S, RESEND_S = 0.15, 0.05


def input_commands(held: set[str]) -> list[str]:
    """The UDP commands that keep these gBox pad names pressed for the next HOLD_S seconds."""
    out = [f"hold {BUTTONS[k][0]} {BUTTONS[k][1]} {HOLD_S}" for k in sorted(held) if k in BUTTONS]
    for hand in ("left", "right"):
        x = sum(STICKS[k][1] for k in held if k in STICKS and STICKS[k][0] == hand)
        y = sum(STICKS[k][2] for k in held if k in STICKS and STICKS[k][0] == hand)
        if x or y:
            out.append(f"stick {hand} {max(-1, min(1, x))} {max(-1, min(1, y))} {HOLD_S}")
    return out


class RefractAdapter:
    name = "refract"
    label = "Refract"
    display_name = "Refract Native"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "send_input"}
    checkpoint_state = False
    checkpoint_reason = "Refract Native has no save states; the game keeps its own saves in its /data folder"

    def __init__(self, config: Config, game: dict | None = None):
        self.config, self.game = config, dict(game or {})
        self.prepared = None
        self.pose = self.viewer = self.native = self.proc = None
        self.job = None
        self.log_dir = None
        self.deadline = None                                   # tools._launch_game: the job's monotonic deadline
        self.boot_timeout_s = float(quest_config(config).boot_timeout_s)
        self._held: set[str] = set()
        self._input_lock = threading.Lock()
        self._input_thread = None
        self._sock = None
        self._stopping = False

    def get_capabilities(self):
        from .adapters import OPS
        return {op: "supported" if op in self.supported else "unsupported" for op in OPS}

    def __getattr__(self, operation):
        from .adapters import OPS
        if operation in OPS:
            def unsupported(*args, **kwargs):
                raise Unsupported(f"{self.display_name} does not support {operation} in gBox")
            return unsupported
        raise AttributeError(operation)

    # -- setup ---------------------------------------------------------------------------------------------------

    def prepare(self, game: dict | None = None, source: Path | None = None) -> dict:
        """Ownership first (nothing happens for a game that isn't the operator's), then this PC's setup."""
        game = dict(game or self.game)
        launch = game.get("launch") or {}
        package = str(launch.get("package") or "")
        if not PACKAGE_RX.match(package):
            raise ToolUnavailable(f"this Quest catalog entry has no valid package name: {package!r}")
        title = game.get("title") or TITLES.get(package) or package
        node = platform.node()
        progress = getattr(self, "progress", lambda *_: None)
        check_node(self.config, node)
        owner = require_owned(self.config, package, title, node)
        progress(4, f"{title}: owned ({'declared by ' + owner['declared_by'] if owner['via'] == 'declaration' else 'Meta sign-in in Refract'})")
        key = f"{root(self.config)}|{package}|{source}"
        result = run_setup(key, lambda update: setup(self.config, launch, source, update), progress, self.deadline,
                           title, node)
        self.game, self.prepared = game, result | {"ownership": owner, "title": title}
        return self.prepared

    # -- launch --------------------------------------------------------------------------------------------------

    def _ports_busy(self) -> list[str]:
        """Another Refract on this PC (the operator's own Refract window, say) holds the ports a session needs. gBox
        never stops a Refract it did not start."""
        try:
            import psutil
            rows = psutil.net_connections(kind="inet")
        except Exception:                                      # noqa: BLE001 - unknown: the launch finds out itself
            return []
        busy = []
        for c in rows:
            port = c.laddr.port if c.laddr else None
            if (port in (POSE_PORT, VIEWER_PORT) and c.status == psutil.CONN_LISTEN) \
                    or (port == CONTROL_PORT and c.type == socket.SOCK_DGRAM):
                try:
                    name = psutil.Process(c.pid).name() if c.pid else "?"
                except Exception:                              # noqa: BLE001
                    name = "?"
                busy.append(f"{name} (pid {c.pid}) on port {port}")
        return busy

    @staticmethod
    def _listening(proc, port: int) -> bool:
        """proc (or a process it started) listens on port."""
        try:
            import psutil
            pids = {proc.pid} | {c.pid for c in psutil.Process(proc.pid).children(recursive=True)}
            return any(c.pid in pids and c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN
                       for c in psutil.net_connections(kind="tcp"))
        except Exception:                                      # noqa: BLE001 - the process may be gone
            return False

    def launch_game(self, rom: str = "") -> dict:
        from .adapters import capture_start, keep_offscreen
        from .graphics import prefer_gpu
        p = self.prepared or self.prepare(self.game, Path(rom) if rom else None)
        lay, package, q = p["layout"], p["package"], quest_config(self.config)
        if self.deadline is not None and time.monotonic() + float(self.boot_timeout_s or 240) + 60 > self.deadline:
            # a game booting past the job's end would run with no session on the control plane: start it fresh
            raise SetupStillRunning(f"Refract setup for {p['title']} finished on {platform.node()}, too late in this "
                                    "launch to boot it. Start the game again to play.")
        busy = self._ports_busy()
        if busy:
            raise RuntimeError(f"Refract is already running on {platform.node()}: {'; '.join(busy)}. Close that "
                               "Refract window or session first; gBox never stops a Refract it did not start.")
        self.log_dir = lay.logs / time.strftime("session-%Y%m%d-%H%M%S")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        app = Path(p["install"]["app"])
        env = _env(lay, REFRACT_CPU=q.cpu, REFRACT_JAVA_HOME=lay.release / "jdk")
        quiet = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.job, self._stopping = _JobObject(), False
        title = p["title"]
        try:
            with open(self.log_dir / "input.log", "wb") as log:
                self.pose = subprocess.Popen(pose_args(q), stdout=log, stderr=subprocess.STDOUT, creationflags=quiet,
                                             env=env, cwd=lay.root)
            self.job.add(self.pose)
            # The game reads its eye size from its first pose connection: the server must be listening first.
            deadline = time.monotonic() + 15
            while not self._listening(self.pose, POSE_PORT):
                if self.pose.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"Refract's input server did not start: {self._tail('input.log')}")
                time.sleep(0.2)
            viewer = lay.release / "viewer" / "build" / "refract_viewer.exe"
            native = lay.release / "build-native" / "refract_native.exe"
            for exe in (viewer, native):        # one GPU for both ends of the shared eye textures: the discrete one
                prefer_gpu(exe)
            with open(self.log_dir / "viewer.log", "wb") as log:
                self.viewer = subprocess.Popen(
                    [str(viewer), "--title", title, "--stats", "0", "--shots", str(lay.shots), "--native",
                     "refract_native.exe"], stdout=log, stderr=subprocess.STDOUT, cwd=viewer.parent, env=env,
                    startupinfo=capture_start())
            self.job.add(self.viewer)
            # parked off-screen until gBox docks it, which happens once the game's first frames end this launch
            wait = float(self.boot_timeout_s or 240)
            keep_offscreen(self.viewer.pid, limit_s=wait + 120, give_up_s=wait + 60)
            time.sleep(0.8)
            if self.viewer.poll() is not None:
                raise RuntimeError(f"Refract's viewer exited ({self.viewer.poll()}): {self._tail('viewer.log')}")
            args = native_args(lay, app, package, self.prepared["ownership"])
            with open(self.log_dir / "native.log", "wb") as log:
                self.native = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=native.parent, env=env,
                                               creationflags=quiet)
            self.job.add(self.native)
            self.proc = _SessionProcess(self)
            stats = self._wait_for_frames(title)
            threading.Thread(target=self._watch, daemon=True, name=f"refract-watch-{self.viewer.pid}").start()
            return {"pid": self.viewer.pid, "native_pid": self.native.pid, "pose_pid": self.pose.pid,
                    "local_window": True, "worker_name": platform.node(), "emulator": self.name,
                    "runtime": f"Refract {REFRACT['version']} (Refract Native, PC viewer)", "credit": CREDIT,
                    "package": package["package"], "version_code": package.get("version_code"),
                    "ownership": self.prepared["ownership"], "libcxx_rebind": p["install"].get("libcxx_rebind"),
                    "fps": stats.get("game_fps"), "viewer": stats, "log": str(self.log_dir),
                    "job_object": bool(self.job and self.job.ok), "window_ready": True, "rendering_verified": True,
                    "gameplay_verified": False,
                    "validation": f"the game sent frames to Refract's viewer ({stats.get('game_fps')} fps); "
                                  "gameplay not yet verified"}
        except Exception:
            self.stop_game()
            raise

    def _wait_for_frames(self, title: str) -> dict:
        """Up when the viewer counts frames from the game (its title shows "game N fps" once a second)."""
        deadline = time.monotonic() + float(self.boot_timeout_s or 240)
        stats, shown = {}, None
        progress = getattr(self, "progress", lambda *_: None)
        while time.monotonic() < deadline:
            if self.native.poll() is not None:
                raise RuntimeError(f"Refract Native exited with code {self.native.poll()} while {title} was "
                                   f"starting:\n{self._tail('native.log', 4000)}")
            if self.viewer.poll() is not None:
                raise RuntimeError(f"Refract's viewer closed while {title} was starting:\n{self._tail('viewer.log')}")
            stats = self.viewer_stats()
            if (stats.get("game_fps") or 0) > 0:
                return stats
            line = f"Refract Native is starting {title} ({stats.get('transport') or 'viewer opening'})"
            if line != shown:
                shown = line
                progress(80, line)
            time.sleep(0.5)
        raise RuntimeError(f"{title} sent no frames to Refract's viewer within {self.boot_timeout_s:.0f} s "
                           f"(viewer: {stats.get('title', 'no window')}):\n{self._tail('native.log', 4000)}")

    def _watch(self):
        """Refract's session ends when the viewer or the game ends (run_native_game.ps1 does the same)."""
        while not self._stopping:
            if self.proc is None or self.proc.poll() is not None:
                if not self._stopping:
                    self._terminate()
                return
            time.sleep(0.5)

    # -- runtime -------------------------------------------------------------------------------------------------

    def viewer_window(self):
        if HOST_OS != "windows" or not self.viewer or self.viewer.poll() is not None:
            return None
        from .adapters import _pid_window
        return _pid_window(self.viewer.pid)

    def viewer_stats(self) -> dict:
        hwnd = self.viewer_window()
        if not hwnd:
            return {}
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, len(buf))
        return parse_viewer_title(buf.value)

    def query_runtime(self) -> dict:
        running = bool(self.proc and self.proc.poll() is None)
        return {"running": running, "pid": self.viewer.pid if self.viewer else None,
                "native_pid": self.native.pid if self.native else None, "pose_pid": self.pose.pid if self.pose else None,
                **({"viewer": self.viewer_stats()} if running else {}),
                "ownership": (self.prepared or {}).get("ownership", {}).get("via"),
                "log": str(self.log_dir) if self.log_dir else None, "rendering_verified": running,
                "gameplay_verified": False}

    def log_tail(self, n: int = 60000) -> str:
        """The session's native/viewer/input logs; before a session exists, this PC's newest setup logs."""
        if self.log_dir:
            parts = [f"== {name}\n{self._tail(name, n // 3)}" for name in ("native.log", "viewer.log", "input.log")]
            return "\n".join(parts)[-n:]
        try:
            logs = sorted(Layout(root(self.config)).logs.glob("*.log"), key=lambda p: p.stat().st_mtime)[-3:]
        except (OSError, ToolUnavailable):
            return ""
        parts = []
        for path in logs:
            with open(path, "rb") as f:
                f.seek(max(0, path.stat().st_size - n // 3))
                parts.append(f"== {path.name}\n" + f.read().decode("utf-8", "replace"))
        return "\n".join(parts)[-n:]

    def _tail(self, name: str, n: int = 2000) -> str:
        path = self.log_dir / name if self.log_dir else None
        if not path or not path.is_file():
            return ""
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - n))
            return f.read().decode("utf-8", "replace")

    def get_frame(self) -> bytes:
        from .adapters import win_grab
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("the Refract session is not running")
        return win_grab(self.viewer.pid)

    def send_input(self, events: list[dict]) -> dict:
        """gBox pad events -> Refract's UDP control port (no window focus needed; never typed into another app)."""
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("the Refract session is not running")
        sent = 0
        with self._input_lock:
            for ev in events:
                key = str(ev.get("key", "")).lower()
                if int(ev.get("player", 1) or 1) != 1:
                    raise Unsupported("Refract has one Quest player: player 1 input only")
                if key not in BUTTONS and key not in STICKS:
                    continue
                if ev.get("down", True):
                    self._held.add(key)
                else:
                    self._held.discard(key)
                sent += 1
            commands = input_commands(self._held)
            if self._input_thread is None or not self._input_thread.is_alive():
                self._input_thread = threading.Thread(target=self._resend, daemon=True, name="refract-input")
                self._input_thread.start()
        self._send(commands)
        return {"sent": sent, "held": sorted(self._held), "via": f"Refract UDP 127.0.0.1:{CONTROL_PORT}"}

    def _send(self, commands: list[str]):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for command in commands:
            self._sock.sendto(command.encode("ascii"), ("127.0.0.1", CONTROL_PORT))

    def _resend(self):
        """Refract's hold/stick commands last HOLD_S: held keys are sent again until released (a release = silence)."""
        while not self._stopping and self.proc is not None and self.proc.poll() is None:
            with self._input_lock:
                commands = input_commands(self._held)
            if commands:
                try:
                    self._send(commands)
                except OSError:
                    pass
            time.sleep(RESEND_S)

    # -- stop ----------------------------------------------------------------------------------------------------

    def _terminate(self):
        from .adapters import _kill_tree
        for proc in (self.native, self.viewer, self.pose):
            try:
                _kill_tree(proc)
            except Exception:                                  # noqa: BLE001 - already gone
                pass
        if self.job:
            self.job.close()

    def stop_game(self) -> dict:
        """Close the viewer the way Refract does (its window's close), then end the game and the input server."""
        self._stopping = True
        with self._input_lock:
            self._held.clear()
        if self.viewer and self.viewer.poll() is None:
            hwnd = self.viewer_window()
            if hwnd and HOST_OS == "windows":
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE
                try:
                    self.viewer.wait(5)
                except subprocess.TimeoutExpired:
                    pass
        self._terminate()
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        alive = [p.pid for p in (self.native, self.viewer, self.pose) if p is not None and p.poll() is None]
        return {"stopped": not alive, "returncode": self.native.poll() if self.native else None, "alive": alive}


def pose_args(q: QuestConfig) -> list[str]:
    """gBox's fork of Refract's pose server: pad + keyboard -> Touch controllers, listening on 127.0.0.1 only."""
    return [python(), "-s", "-E", "-u", str(VENDOR / "pose_input_server.py"), "--host", "127.0.0.1",
            "--port", str(POSE_PORT), "--control-port", str(CONTROL_PORT), "--eye-width", str(q.eye_size),
            "--eye-height", str(q.eye_size), "--refresh-rate", "250", "--focus", q.focus]


def native_args(lay: Layout, app: Path, package: dict, owner: dict) -> list[str]:
    """refract_native's command line, as run_native_game.ps1 builds it. The owner flag is set for this one package
    and only with a confirmed ownership (require_owned); the game's /data lives on the Refract root's drive."""
    if not owner.get("owned"):
        raise OwnershipRequired(f"{package['package']} is not confirmed as the operator's own")
    args = [str(lay.release / "build-native" / "refract_native.exe"), "--sysroot", str(lay.sysroot), "--app", str(app),
            "--data", str(lay.data), "--prop", f"debug.refract.platform.owned.{package['package']}=1"]
    if package.get("obb_dir"):
        args += ["--mount", f"/sdcard/Android/obb/{package['package']}={package['obb_dir']}"]
    return args


def parse_viewer_title(title: str) -> dict:
    """Refract's viewer puts its stats in its title once a second: "<game> – Refract Viewer  |  game 72 fps, shown
    72 fps (GPU shared)  |  ..."."""
    m = VIEWER_TITLE_RX.search(title or "")
    out = {"title": title}
    if m:
        out |= {"game_fps": int(m.group(1)), "shown_fps": int(m.group(2)), "transport": m.group(3)}
    return out


def main(argv=None) -> int:
    """python -m gbox.refract status | setup --source ZIP: the same checks and setup a launch runs, on this PC."""
    import argparse
    from .config import load
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("command", choices=["status", "setup", "scan"])
    ap.add_argument("--source", type=Path, help="a Quest package zip or folder (setup), or a library folder (scan)")
    ap.add_argument("--package", default="com.Armature.VR4")
    args = ap.parse_args(argv)
    config = load()
    if args.command == "scan":
        entries, problems = scan_refract(args.source, "quest")
        print(json.dumps({"entries": [e.model_dump() for e in entries], "problems": problems}, indent=1))
        return 0
    if args.command == "status":
        from .refract_status import status
        print(json.dumps(status(config, args.package), indent=1))
        return 0
    launch = {"package": args.package}
    result = setup(config, launch, args.source, lambda pct, msg: print(f"[{pct:5.1f}%] {msg}", flush=True))
    print(json.dumps({"package": result["package"], "install": result["install"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
