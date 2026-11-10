"""Meta Quest titles through Refract (MIXIDtheSilly/Refract, GPL-3.0-or-later) - Stage 1 building blocks.

Refract stays a separate set of processes (arm's length): this module only reads its library.json and builds the argv
for the three processes that tools/run_native_game.ps1 starts. Nothing here reads or stores the Meta token
(meta-session.dpapi) and nothing is downloaded. See docs/research/quest-refract-feasibility.md.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .models import CatalogEntry

POSE_TCP_PORT = 38490
POSE_UDP_CONTROL = 38495
VIEWER_TITLE = "Refract Viewer"
_PKG = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


def default_data_dir() -> Path | None:
    """%APPDATA%\\Refract on Windows (library.json lives there); None elsewhere."""
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Refract" if appdata else None


def scan_refract(data_dir: Path | None = None) -> tuple[list[CatalogEntry], list[str]]:
    """Catalog entries for the owned Quest games in Refract's library.json (platform "quest")."""
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    if not data_dir:
        return [], ["no Refract data dir (APPDATA unset)"]
    lib = data_dir / "library.json"
    if not lib.exists():
        return [], [f"no library.json under {data_dir}"]
    try:
        games = json.loads(lib.read_text(encoding="utf-8", errors="replace")).get("games") or []
    except (OSError, ValueError, AttributeError) as e:
        return [], [f"{lib}: {e}"]
    entries, problems = [], []
    for g in games:
        pkg = g.get("package") if isinstance(g, dict) else None
        if not pkg or not _PKG.match(str(pkg)):
            problems.append(f"{lib}: game without a valid package: {g.get('name') if isinstance(g, dict) else g!r}")
            continue
        files = [f for f in g.get("files") or [] if isinstance(f, dict)]
        gid = f"quest-{pkg}"
        entries.append(CatalogEntry(
            game_id=gid, title=g.get("name") or pkg, platform="quest", platform_confidence="manifest",
            source_paths=[str(Path(f["path"]).parent) for f in files[:1] if f.get("path")],
            hashes={"refract_binary_id": str(g.get("binaryId") or "")}, size=sum(int(f.get("size") or 0) for f in files),
            format="quest_apk", runtimes={"quest": "refract"},
            launch={"kind": "refract", "package": pkg, "owned": bool(g.get("owned")),
                    "installed": bool(g.get("nativeInstalled")), "vr_sdk": g.get("vrSdk"),
                    "source": g.get("source"), "obb_dir": next((str(Path(f["path"]).parent) for f in files
                                                                if f.get("kind") == "obb" and f.get("path")), None)},
            profile_id=gid))
    return entries, problems


def native_commands(root: Path, package: str, name: str, *, owned: bool, obb_dir: str | None = None,
                    user_id: str | None = None, eye_size: int = 1600, pictures: str | None = None,
                    focus: str = f"gBox|{VIEWER_TITLE}") -> dict[str, list[str]]:
    """argv of the pose server, viewer and game as tools/run_native_game.ps1 -PcViewer starts them.

    Refuses an unowned title: the launcher only sets the entitlement property for Meta-library games.
    """
    if not _PKG.match(package):
        raise ValueError(f"bad package name {package!r}")
    if not owned:
        raise PermissionError(f"{package} is not marked owned in the signed-in Meta library; refusing to launch")
    root = Path(root)
    apps = Path(os.environ.get("LOCALAPPDATA", "")) / "Refract" / "native" / "apps" / package
    game = [str(root / "build-native" / "refract_native.exe"), "--sysroot", str(root / "build-native" / "sysroot"),
            "--app", str(apps), "--prop", f"debug.refract.platform.owned.{package}=1"]
    if user_id:
        game += ["--prop", f"debug.refract.platform.user_id={user_id}"]
    if obb_dir:
        game += ["--mount", f"/sdcard/Android/obb/{package}={obb_dir}"]
    viewer = [str(root / "viewer" / "build" / "refract_viewer.exe"), "--title", name, "--stats", "0",
              "--native", "refract_native.exe"]
    if pictures:
        viewer[5:5] = ["--shots", pictures]
    pose = ["python", str(root / "scripts" / "pose_input_server.py"), "--eye-width", str(eye_size),
            "--eye-height", str(eye_size), "--refresh-rate", "250", "--focus", focus]
    return {"pose": pose, "viewer": viewer, "game": game}


def control_message(kind: str, *args) -> bytes:
    """UDP text command for the pose server (127.0.0.1:38495): hold/stick/view/keys/tpose/center."""
    verbs = {"hold": 3, "stick": 4, "view": (4, 5), "keys": None, "tpose": 1, "center": 1}
    if kind not in verbs:
        raise ValueError(f"unknown Refract control {kind!r}")
    n = verbs[kind]
    if isinstance(n, int) and len(args) != n or isinstance(n, tuple) and len(args) not in n:
        raise ValueError(f"{kind}: wrong argument count {len(args)}")
    return (" ".join([kind, *map(str, args)]) + "\n").encode()
