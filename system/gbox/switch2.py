"""Switch 2 runtimes: the Lichii/Fritchii emulator family and Hookshot's native Ocarina of Time build.

Switch 2 titles are not Switch 1 NSPs: the operator's library holds `.nup` archives, a Mario Kart World `.nsp`, and
extracted dump folders (`base/exefs`, `base/romfs`). gBox runs them with three engines, all configured per node:

* **fritchii** - the pinned Windows x64 Lichii fork tuned for Ocarina of Time (Frizti/Fritchii, v5.8.4). A portable
  `lichii.exe`; `-g <game>` starts a title, keys live in `user/keys/`. It is the default Switch 2 emulator.
* **lichii** - the operator's own Lichii install (zortos293/Lichii), same `-g` contract and portable `user/`. A custom
  preconfigured build for OoT ships on the `switch2` share (`Custom Version of Lichi for OoT.zip`).
* **hookshot** - NotRexed/Hookshot, a native recompilation of the Ocarina of Time Switch 2 remake. Its builder takes
  the `.nup` (or a folder with `romfs`/`exefs`) through `--cli --prepare --game <path>` and produces
  `<home>/Games/Hookshot`; `--play <game>` runs it. The game exposes a local control bridge (`HOS_CONTROL` named pipe
  on Windows, Unix socket on Linux) with guest-memory reads/writes - the hook surface live model swaps will use.

Everything here is a plan, not a process: `plan_launch` resolves the engine, the game argument (a NUP, NSP, or a
loose `exefs/main`), the portable keys, and the arguments/environment; `gbox.adapters.Switch2Adapter` starts it and
`gbox.tools` exposes the long Hookshot prepare as a job. Keys and firmware come from the operator's own share
(`prod.keys`, `title.keys`, firmware ZIP); nothing is bundled.

Host support: Fritchii and Lichii are Windows x64 only. Hookshot has Windows x64 and Linux x86_64 builds; the DGX Spark
(aarch64) cannot execute any of the three releases natively, so a Switch 2 session runs on a Windows/x86 worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

from . import nup, switch_nup

OCARINA = "0400486024DEC000"                     # The Legend of Zelda: Ocarina of Time (Switch 2)
FRITCHII = {
    "version": "5.8.4",
    "url": "https://github.com/Frizti/Fritchii/releases/download/fritchii-v5.8.4/Fritchii-v5.8.4-Windows-x64.zip",
    "sha256": "8fbe37d69665e8264bf9e92fe40846961923cff29dc165f8fdafe193605d10da",
    "zip_folder": "Fritchii-v5.8.4",
    "exe": "lichii.exe",
}
HOOKSHOT = {
    "version": "2.1.0",
    "url": "https://github.com/NotRexed/Hookshot/releases/download/v2.1.0/Hookshot-v2.1.0-Windows-x64.zip",
    "sha256": "fdfa49be0d7ead29398ef08c4f489ca79215dbf51f90d7b7c179f8cf02b12bcd",
    "exe": "HookshotBuilder.exe",
}
ENGINES = ("fritchii", "lichii", "hookshot")
EDEN_FORKS = ("fritchii", "lichii")
GAME_EXTS = (".nup", ".nsp", ".xci", ".xcz")     # what an Eden fork can take with -g
MARKER = ".gbox-nup.json"


# --- folders and engines ----------------------------------------------------------------------------------------------

def root(cfg) -> Path:
    """This node's Switch 2 runtime folder (`switch2_root`, else <runtime>/switch2)."""
    configured = getattr(cfg, "switch2_root", None)
    return Path(configured).expanduser() if configured else Path(cfg.runtime) / "switch2"


def engine_dir(cfg, name: str) -> Path:
    key = f"switch2_{name}"
    configured = getattr(cfg, key, None)
    p = Path(configured).expanduser() if configured else root(cfg) / name
    return p


def _find_exe(folder: Path, name: str) -> Path | None:
    """An executable in `folder` or one packaged level below it (the release zips wrap a version folder)."""
    for candidate in (folder / name, *sorted(folder.glob(f"*/{name}"))):
        if candidate.is_file():
            return candidate
    return None


def engine_exe(cfg, name: str) -> Path | None:
    """The engine's launcher, or None when it is not installed on this node."""
    if name == "hookshot":
        return hookshot_builder(cfg)
    return _find_exe(engine_dir(cfg, name), "lichii.exe")


def _local_hookshot_home() -> Path | None:
    """The installed Builder's data home (`%LOCALAPPDATA%\\HookshotBuilder`): versions/, settings, per-game output."""
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "HookshotBuilder").is_dir():
        return Path(local) / "HookshotBuilder"
    return None


def hookshot_builder(cfg) -> Path | None:
    """The installed `HookshotBuilder.exe`, else the pinned setup/launcher, else the configured path.

    The release zip is the setup; its first run installs the real Builder under
    `%LOCALAPPDATA%\\HookshotBuilder\\versions\\<version>\\HookshotBuilder\\`. That installed copy carries `tools/nx2`
    (the `--cli` prepare path), so it is preferred over the setup exe beside `switch2_root`.
    """
    configured = getattr(cfg, "switch2_hookshot", None)
    if configured:
        p = Path(configured).expanduser()
        if p.is_file():
            return p
        found = _find_exe(p, HOOKSHOT["exe"])
        if found:
            return found
    home = _local_hookshot_home()
    if home:
        try:
            version = (home / "versions" / "current.txt").read_text(encoding="utf-8").strip()
        except OSError:
            version = ""
        candidates = [home / "versions" / version / "HookshotBuilder" / HOOKSHOT["exe"]] if version else []
        candidates += sorted(home.glob("versions/*/HookshotBuilder/HookshotBuilder.exe"), reverse=True)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return _find_exe(engine_dir(cfg, "hookshot"), HOOKSHOT["exe"])


def installed(cfg, name: str) -> bool:
    return engine_exe(cfg, name) is not None


def engine_home(cfg, name: str) -> Path:
    """The folder whose portable `user/` belongs to the engine (the exe's folder when a path names the exe)."""
    exe = engine_exe(cfg, name)
    return exe.parent if exe else engine_dir(cfg, name)


def host_support(name: str) -> str | None:
    """None when this host can run the engine, else why not."""
    if name in EDEN_FORKS and os.name != "nt":
        return (f"{name} is a Windows x64 emulator; run this title on a Windows worker (e.g. i9-NUC), or use Hookshot "
                "on a Linux x86_64 host")
    return None


def engine_for(cfg, game: dict) -> str:
    """Which engine plays this title: Hookshot for OoT once built, else the configured/default Eden fork.

    `switch2_engine` = auto | fritchii | lichii | hookshot. `auto` picks Hookshot only when its OoT build already
    exists (a prepare takes 10-45 minutes, never inside a launch); otherwise it prefers Fritchii, then the operator's
    own Lichii.
    """
    requested = str(getattr(cfg, "switch2_engine", "auto") or "auto").lower()
    tid = str(game.get("serial") or (game.get("launch") or {}).get("title_id") or "").upper()
    if requested == "hookshot" or (requested == "auto" and tid == OCARINA and hookshot_game(cfg).is_dir()):
        return "hookshot"
    if requested in EDEN_FORKS:
        return requested
    return "fritchii" if installed(cfg, "fritchii") else "lichii"


def _download(url: str, dst: Path, sha256: str, progress=None) -> Path:
    """Stream a pinned release to `dst`, verify its SHA-256, and return it (a stale partial file is replaced)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=300) as src, open(tmp, "wb") as out:
        total = int(src.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = src.read(1 << 20)
            if not block:
                break
            out.write(block)
            digest.update(block)
            done += len(block)
            if progress and total:
                progress(min(99.0, 100 * done / total), f"{dst.name}: {done >> 20}/{total >> 20} MB")
    if digest.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{dst.name}: SHA-256 mismatch (expected {sha256}, got {digest.hexdigest()})")
    tmp.replace(dst)
    return dst


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract a release zip into `dest` without letting a member escape it."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise RuntimeError(f"release zip member escapes {dest}: {member.filename!r}")
        z.extractall(dest)


def provision(cfg, name: str, *, progress=None) -> dict:
    """Install a pinned engine release (Fritchii/Hookshot) or report the operator's Lichii path.

    Fritchii is downloaded once into <switch2_root>/fritchii and its portable `user/` receives the operator's keys.
    Hookshot is only the builder/setup (`HookshotBuilder.exe` + `recomplauncher.json`); its game build is op=prepare.
    Lichii is never downloaded here: it is the operator's own install (`switch2_lichii`), such as the share's custom
    OoT build extracted beside the library.
    """
    name = (name or "auto").lower()
    if name == "auto":
        name = "fritchii"
    if name not in ENGINES:
        raise ValueError(f"unknown Switch 2 engine {name!r} (fritchii, lichii, hookshot)")
    if name == "lichii":
        exe = engine_exe(cfg, "lichii")
        if not exe:
            raise FileNotFoundError("Lichii is not installed: set switch2_lichii to the folder holding lichii.exe")
        return {"engine": "lichii", "exe": str(exe), "installed": True, "keys": install_keys(cfg, "lichii")}
    spec = FRITCHII if name == "fritchii" else HOOKSHOT
    folder = engine_dir(cfg, name)
    exe = engine_exe(cfg, name)
    downloaded = False
    if not exe:
        holder = folder.parent / "downloads"
        zip_path = holder / spec["url"].rsplit("/", 1)[-1]
        if not zip_path.is_file() or _sha256(zip_path) != spec["sha256"]:
            _download(spec["url"], zip_path, spec["sha256"], progress=progress)
            downloaded = True
        _extract_zip(zip_path, folder)
        exe = engine_exe(cfg, name)
        if not exe:
            raise RuntimeError(f"{spec['exe']} is not in the extracted release at {folder}")
    out = {"engine": name, "exe": str(exe), "folder": str(exe.parent), "installed": True, "downloaded": downloaded}
    if name == "hookshot":
        out["needs_setup"] = not hookshot_tools(cfg)
        if out["needs_setup"]:
            out["setup"] = (f"Run {exe.name} --portable once (interactive): it installs the Builder, its tools and "
                            "Python beside the setup; then set switch2_hookshot to the installed HookshotBuilder.exe")
    if name in EDEN_FORKS:
        out["keys"] = install_keys(cfg, name)
        out["firmware"] = install_firmware(cfg, name)
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --- keys and firmware ------------------------------------------------------------------------------------------------

def keys(cfg) -> Path | None:
    """The operator's prod.keys for Switch 2: `switch2_keys`, else the share's prod.keys at a Switch library root."""
    configured = getattr(cfg, "switch2_keys", None)
    if configured and Path(configured).expanduser().is_file():
        return Path(configured).expanduser()
    for lib in getattr(cfg, "libraries", []) or []:
        try:
            lib_root = lib.root()
        except Exception:                                  # noqa: BLE001 - unconfigured path for this OS
            continue
        if lib_root and lib.platform == "switch" and (lib_root / "prod.keys").is_file():
            return lib_root / "prod.keys"
    return None


def install_keys(cfg, name: str) -> list[str]:
    """Copy prod.keys/title.keys into the portable engine's user/keys (missing or changed only)."""
    from . import provision
    source = keys(cfg)
    if source is None:
        return []
    return provision.switch_install_keys(source, engine_home(cfg, name) / "user" / "keys")


def install_firmware(cfg, name: str) -> dict:
    """Restore the configured firmware ZIP into the portable engine's nand when one is named; never guesses a version.

    Switch 2 builds on the share ship 23.0.x firmware and the operator's keys; Fritchii/Lichii initialise without a
    registered firmware for the titles measured so far. A configured `switch2_firmware` is installed through gBox's
    existing marker-gated restorer, with the NCA count taken from the ZIP (not the pinned 17.0.0 count).
    """
    configured = getattr(cfg, "switch2_firmware", None)
    if not configured or not Path(configured).expanduser().is_file():
        return {"installed": 0, "source": None}
    from . import provision
    src = Path(configured).expanduser()
    registered = engine_home(cfg, name) / "user" / "nand" / "system" / "Contents" / "registered"
    with zipfile.ZipFile(src) as z:
        expected = sum(1 for n in z.namelist() if n.lower().endswith(".nca"))
    written = provision.switch_install_firmware(src, registered, expected=expected)
    return {"installed": len(written), "source": str(src)}


# --- game resolution --------------------------------------------------------------------------------------------------

def is_game(game: dict) -> bool:
    """Whether a catalog row is Switch 2 (generation 2, or an 04... title / Switch 2 dump shape).

    A `.nup` can hold a Switch 1 game too: the catalog's `switch_generation` decides first, and an explicit generation 1
    row is never handed to Fritchii/Hookshot. Rows without a generation fall back to the title id (04... = Switch 2) and
    then to the dump shapes gBox itself creates for Switch 2.
    """
    if str(game.get("platform") or "") != "switch":
        return False
    launch = game.get("launch") or {}
    generation = launch.get("switch_generation")
    if generation == 2:
        return True
    if generation == 1:
        return False
    tid = str(game.get("serial") or launch.get("title_id") or "").upper()
    if tid:
        return tid.startswith("04")
    return str(game.get("format") or "").lower() in ("switch_dump", "nup_folder")


def exefs_main(folder: str | Path) -> Path | None:
    """The `main` of an extracted title: `base/exefs/main` (NUP canonical), `exefs/main`, or one level below."""
    p = Path(folder)
    for candidate in (p / "base" / "exefs" / "main", p / "exefs" / "main"):
        if candidate.is_file():
            return candidate
    return next((m for m in sorted(p.glob("*/exefs/main")) if m.is_file()), None)


def game_arg(cfg, game: dict, rom: str | Path) -> str:
    """The argument to start: a NUP/NSP path, or the loose `exefs/main` of an extracted title.

    Fritchii/Lichii take a container with `-g` and a loose ExeFS main for an extracted dump (the nx2 fork's loader is
    the same in both). `switch2_materialize_nup = true` extracts a NUP into <root>/games/<title> first, for an engine
    build that cannot read the container.
    """
    p = Path(rom)
    if p.is_dir():
        main = exefs_main(p)
        if main is None:
            raise FileNotFoundError(f"{p} is not an extracted Switch title (no base/exefs/main or exefs/main)")
        return str(main)
    if p.suffix.lower() == ".nup" and bool(getattr(cfg, "switch2_materialize_nup", False)):
        tid = switch_nup.title_id(p) or hashlib.sha1(str(p).encode()).hexdigest()[:16].upper()
        dest = root(cfg) / "games" / str(tid)
        marker = switch_nup.materialized(dest)
        if marker is None:
            with nup.NupReader(p) as reader:
                reader.materialize(dest)
        main = exefs_main(dest)
        if main is None:
            raise FileNotFoundError(f"{dest}: the extracted title has no exefs/main")
        return str(main)
    if p.suffix.lower() in GAME_EXTS or p.is_file():
        return str(p)
    raise FileNotFoundError(f"{p} is not a Switch game (NUP/NSP/XCI or an extracted folder)")


def hookshot_home(cfg) -> Path:
    """Hookshot's data home: the installed Builder's home, else `switch2_hookshot`, else <switch2_root>/hookshot."""
    local = _local_hookshot_home()
    if local:
        return local
    configured = getattr(cfg, "switch2_hookshot", None)
    if configured:
        p = Path(configured).expanduser()
        return p.parent if p.is_file() else p
    return engine_dir(cfg, "hookshot")


def hookshot_game(cfg) -> Path:
    """The built OoT game folder: `switch2_hookshot_game`, else the Builder's own saved output (`builder-settings.json`
    `Out`), else `<home>/Games/Hookshot`.

    The operator's interactive build saved `Out = \\\\…\\switch2\\LOZ`, so reading the Builder's settings is what keeps
    gBox pointed at the game the Builder actually produced, not a guessed path.
    """
    explicit = getattr(cfg, "switch2_hookshot_game", None)
    if explicit:
        return Path(explicit).expanduser()
    settings = hookshot_home(cfg) / "builder-settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        if data.get("Out"):
            return Path(data["Out"])
    except (OSError, ValueError):
        pass
    return hookshot_home(cfg) / "Games" / "Hookshot"


def hookshot_ready(cfg) -> bool:
    game = hookshot_game(cfg)
    return any((game / name).is_file() for name in ("Hookshot.exe", "hookshot.exe", "hookshot"))


def hookshot_tools(cfg) -> bool:
    """Whether the Hookshot builder's own tools (nx2/make_game.py) are installed beside it.

    The release zip is the setup/launcher only; the first `HookshotBuilder.exe --portable` (or the standard setup)
    installs the Builder with `tools/` (Python, nx2/make_game.py, llvm-mingw). `--cli --prepare` needs those tools, so a
    prepare before that setup is refused with the one command that fixes it.
    """
    builder = hookshot_builder(cfg)
    bases = [builder.parent] if builder else []
    bases += [hookshot_home(cfg), engine_dir(cfg, "hookshot")]
    for base in bases:
        for candidate in (base / "tools" / "nx2" / "make_game.py", base / "nx2" / "make_game.py"):
            if candidate.is_file():
                return True
    return False


def hookshot_control(cfg, game_id: str = "") -> str:
    """The control bridge's address this launch will use: a Windows named pipe or a Linux Unix socket.

    The game reads `HOS_CONTROL` at start; `HOS_CONTROL_MEM=rw` allows guest-memory reads/writes, which is what a live
    model swap needs. Both are opt-in and local-only (gbox/switch2_control.py is the client).
    """
    key = (game_id or "switch2").replace(os.sep, "_")
    if os.name == "nt":
        return rf"\\.\pipe\gbox-hookshot-{key}"
    folder = root(cfg) / "control"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / f"{key}.sock")


def plan_launch(cfg, game: dict, rom: str | Path, *, debug: bool = False) -> dict:
    """Everything a launch needs: engine, executable, argv, cwd, env, log path and the resolved game argument."""
    name = engine_for(cfg, game)
    why = host_support(name)
    if why:
        raise RuntimeError(why)
    if name == "hookshot":
        builder = engine_exe(cfg, "hookshot")
        if builder is None:
            raise FileNotFoundError("Hookshot is not installed: set switch2_hookshot to HookshotBuilder.exe")
        game_dir = hookshot_game(cfg)
        if not hookshot_ready(cfg):
            raise FileNotFoundError(f"Hookshot has not built this title yet ({game_dir}); run switch2 op=prepare")
        control = hookshot_control(cfg, str(game.get("game_id") or OCARINA))
        env = {"HOS_CONTROL": control, "HOS_CONTROL_MEM": str(getattr(cfg, "switch2_hookshot_mem", "rw") or "rw")}
        if debug:
            env["HOS_CONTROL_MEM"] = "rw"
        return {"engine": "hookshot", "exe": str(builder), "argv": [str(builder), "--play", str(game_dir)],
                "cwd": str(builder.parent), "env": env, "game_arg": str(game_dir), "control": control,
                "log": str(game_dir / "log.txt"), "keys": [], "wait_s": 300}
    exe = engine_exe(cfg, name)
    if exe is None:
        raise FileNotFoundError(f"{name} is not installed: set switch2_{name} or run provision")
    arg = game_arg(cfg, game, rom)
    copied = install_keys(cfg, name)
    env = {}
    if debug:
        env["EDEN_NX2_IPC_TRACE"] = "1"
    return {"engine": name, "exe": str(exe), "argv": [str(exe), "-g", arg], "cwd": str(exe.parent), "env": env,
            "game_arg": arg, "control": None, "log": str(exe.parent / "user" / "log" / "eden_log.txt"),
            "keys": copied, "wait_s": 180}


def prepare_hookshot(cfg, game_path: str | Path, *, progress=None, cancel=None, timeout: float = 7200) -> dict:
    """Build Hookshot's native game from a NUP or extracted dump (`--cli --prepare --game <path>`), streamed.

    This is the 10-45 minute step; it runs as a job (`switch2 op=prepare`), never inside a launch. The builder prints
    its own progress lines; they are passed to `progress` and the whole output is returned.
    """
    builder = engine_exe(cfg, "hookshot")
    if builder is None:
        raise FileNotFoundError("Hookshot is not installed: set switch2_hookshot to HookshotBuilder.exe")
    if not hookshot_tools(cfg):
        raise RuntimeError(f"Hookshot's builder tools are not installed yet: run {builder.name} --portable once "
                           "(interactive); it installs the Builder, its tools and Python, then run prepare again")
    p = Path(game_path)
    if p.is_dir():
        if exefs_main(p) is None:
            raise FileNotFoundError(f"{p}: no romfs/exefs to build Hookshot from")
        source = str(p)
    elif p.suffix.lower() == ".nup":
        source = str(p)
    else:
        raise FileNotFoundError(f"Hookshot builds from a .nup or an extracted title folder, not {p.name}")
    argv = [str(builder), "--cli", "--prepare", "--game", source, "--out", str(hookshot_game(cfg))]
    env = {**os.environ}
    env.setdefault("HOOKSHOT_SETUP_BASE", str(hookshot_home(cfg)))
    proc = subprocess.Popen(argv, cwd=str(builder.parent), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    started = time.time()
    try:
        for line in proc.stdout or []:
            line = line.rstrip()
            if line:
                lines.append(line)
                if progress:
                    progress(min(97.0, 5.0 + (time.time() - started) / max(1.0, timeout) * 90.0), line[:300])
            if cancel and cancel():
                proc.terminate()
                raise TimeoutError("Hookshot prepare cancelled")
            if time.time() - started > timeout:
                proc.terminate()
                raise TimeoutError(f"Hookshot prepare exceeded {timeout / 3600:.1f} h")
        code = proc.wait(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    if code != 0:
        raise RuntimeError(f"Hookshot prepare failed (exit {code}): " + " | ".join(lines[-8:]))
    return {"engine": "hookshot", "source": source, "game": str(hookshot_game(cfg)), "exit": code,
            "seconds": round(time.time() - started, 1), "lines": lines[-120:]}


def status(cfg) -> dict:
    """What is installed on this node and how a Switch 2 launch would resolve, without starting anything."""
    machines = {}
    for name in ENGINES:
        exe = engine_exe(cfg, name)
        machines[name] = {"installed": exe is not None, "exe": str(exe) if exe else None,
                          "host": host_support(name) or "supported"}
    for name in EDEN_FORKS:
        machines[name]["keys"] = str(engine_home(cfg, name) / "user" / "keys")
    return {"root": str(root(cfg)), "engines": machines, "engine": str(getattr(cfg, "switch2_engine", "auto")),
            "keys": str(keys(cfg)) if keys(cfg) else None, "hookshot_game": str(hookshot_game(cfg)),
            "hookshot_ready": hookshot_ready(cfg), "hookshot_tools": hookshot_tools(cfg),
            "notes": ["Fritchii/Lichii are Windows x64; Hookshot has Windows x64 and Linux x86_64 builds",
                      "a NUP is passed to the Eden forks as-is; set switch2_materialize_nup=true for loose exefs"]}
