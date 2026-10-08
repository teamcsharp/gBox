"""Python packages gBox needs, installed into this node's own environment on demand.

ensure_declared(): at worker start, every dependency in pyproject.toml that can't be imported is pip-installed (a venv made
before a dependency was added never gets it otherwise). install_for(module): a job that hits ModuleNotFoundError installs
the package behind that import and is retried once (worker._run_job). Each package is tried once per process, so a package
that can't install never loops.
"""
from __future__ import annotations

import importlib
import importlib.util
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# import name -> pip package, where they differ (anything else installs under its own name)
PIP_NAME = {"PIL": "pillow", "cv2": "opencv-contrib-python-headless", "yt_dlp": "yt-dlp", "yaml": "pyyaml",
            "sklearn": "scikit-learn", "skimage": "scikit-image", "win32api": "pywin32", "win32con": "pywin32",
            "win32gui": "pywin32", "Crypto": "pycryptodome", "bs4": "beautifulsoup4", "dateutil": "python-dateutil",
            "OpenGL": "PyOpenGL", "serial": "pyserial", "usb": "pyusb", "magic": "python-magic"}
# pip package -> import name (to check whether a declared dependency is present)
IMPORT_NAME = {v: k for k, v in PIP_NAME.items()} | {"pillow": "PIL", "yt-dlp": "yt_dlp", "opencv-contrib-python-headless": "cv2"}
# never installed automatically: the gBox package itself and anything that isn't a plain top-level import name
NEVER = {"gbox", "__main__", "__mp_main__"}

_lock = threading.Lock()
_tried: dict[str, bool] = {}                                   # pip package -> installed ok


def _pip_cmd(pkgs: list[str]) -> list[list[str]]:
    """Ways to install into THIS interpreter's environment, best first (pip in the venv, then uv, then ensurepip+pip)."""
    cmds = [[sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", *pkgs]]
    if uv := shutil.which("uv"):
        cmds.append([uv, "pip", "install", "-q", "--python", sys.executable, *pkgs])
    return cmds


def _install(pkgs: list[str]) -> bool:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    for cmd in _pip_cmd(pkgs):
        try:
            if subprocess.run(cmd, capture_output=True, timeout=900, creationflags=flags).returncode == 0:
                importlib.invalidate_caches()
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    try:                                                       # a venv made without pip
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True, timeout=300, creationflags=flags)
        if subprocess.run(_pip_cmd(pkgs)[0], capture_output=True, timeout=900, creationflags=flags).returncode == 0:
            importlib.invalidate_caches()
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def install_for(module: str | None) -> bool:
    """Install the package that provides `import module` (top-level name). True = importable now."""
    top = (module or "").split(".")[0]
    if not top or top in NEVER or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", top):
        return False
    if importlib.util.find_spec(top):
        return True
    pkg = PIP_NAME.get(top, top.replace("_", "-"))
    with _lock:
        if pkg in _tried:
            return _tried[pkg] and bool(importlib.util.find_spec(top))
        print(f"gBox: installing {pkg} (needed for 'import {top}') into {sys.prefix}", flush=True)
        _tried[pkg] = _install([pkg])
        print(f"gBox: {pkg} {'installed' if _tried[pkg] else 'could NOT be installed'}", flush=True)
    return _tried[pkg] and bool(importlib.util.find_spec(top))


def missing_module(exc: BaseException | None) -> str | None:
    """The module a ModuleNotFoundError (anywhere in the exception chain) couldn't find."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ModuleNotFoundError) and exc.name:
            return exc.name
        exc = exc.__cause__ or exc.__context__
    return None


def declared() -> list[str]:
    """pyproject.toml [project] dependencies as pip requirement strings, plus the PC-side extras on Windows (the overlay
    swap tracker's OpenCV runs in the same environment as the worker there)."""
    try:
        import tomllib
        proj = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
        extra = proj.get("optional-dependencies", {}).get("overlay", []) if sys.platform == "win32" else []
        return list(proj["dependencies"]) + list(extra)
    except Exception:                                          # noqa: BLE001
        return []


def ensure_declared() -> list[str]:
    """Install every declared dependency this environment can't import. Returns what was installed."""
    need = []
    for req in declared():
        pkg = re.split(r"[<>=!~\[; ]", req, maxsplit=1)[0].strip()
        mod = IMPORT_NAME.get(pkg.lower(), pkg.replace("-", "_"))
        if pkg and not importlib.util.find_spec(mod):
            need.append(req)
    if need:
        print(f"gBox: this environment is missing declared packages {need}; installing", flush=True)
        ok = _install(need)
        with _lock:
            for req in need:
                _tried[re.split(r"[<>=!~\[; ]", req, maxsplit=1)[0].strip()] = ok
        print(f"gBox: {'installed' if ok else 'could NOT install'} {need}", flush=True)
    return need if need else []
