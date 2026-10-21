"""Native PC ports of console games: built on the worker from their source and launched like an emulator session.

The first one is the GoldenEye 007 PC port (github.com/jkdansereau/goldeneye-pc-port: the n64decomp/007
decompilation compiled for the PC, SDL2 + OpenGL, MIT-licensed port layer; the decomp files carry no licence and are
the upstream's), played in gBox with gBox's own bots (docs/goldeneye_bots.md).

Nothing of the port is vendored in gBox:
  * `native_port op=build` clones the pinned upstream commit into <runtime>/ports/<id>/src on the worker, copies in
    gBox's bridge (system/adapters/ge007_port/gbox_bridge.c, gBox's own code) with two one-line hooks, applies the
    platform fixes the port needs on this CPU (Port.fixes) and compiles it there: nice 19, idle I/O, -j4 by default.
  * `native_port op=prepare` puts the operator's own ROM into the port's data folder (byte order normalised, SHA-1
    checked) and runs the port's converters. The ROM and every file made from it stay in that runtime folder.
  * A launch of the port's catalog entry does both on first use.

Catalog: scan_library adds one entry per owned ROM a port accepts ("GoldenEye 007 (PC port + bots)",
launch.kind "native_port"). Its library/rel_path are the N64 ROM's, so a launch resolves and unpacks the ROM exactly
like the emulator entry does; adapters.for_game hands the entry to PortAdapter.

Sessions run on the Linux worker: a private Xvfb display, the GPU through VirtualGL when it is installed, the usual
MJPEG stream, and every input through the bridge (player 1 = the streamed pad, players 2-4 = gBox bots,
gbox/ge007_bots.py). A plain Play boots to the title screen: in Multiplayer pick 2-4 players and the bots take the
other seats. An autoplay or screensaver launch (jump) starts a 4-player match on a random arena at once (the port's
GE_STARTMP harness, which starts the next match when one ends). Windows can run a build that is already there (a
local window, input through the bridge); building on Windows (MSYS2 MinGW64) is not automated yet.
"""
from __future__ import annotations

import hashlib
import os
import platform as _platform
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from .adapters import HOST_OS, VGLRUN, Adapter, Display, MjpegStream, _kill_tree, grab_png
from .models import CatalogEntry
from .models import Permission as P
from .registry import ToolUnavailable, tool

GBOX_ROOT = Path(__file__).resolve().parents[1]                    # system/


@dataclass(frozen=True)
class Port:
    id: str
    title: str
    repo: str
    commit: str
    tag: str
    platform: str                         # catalog platform of the ROM it is built for
    titles: tuple                         # regexes over catalog titles of that ROM
    regions: tuple                        # catalog regions accepted (None = unknown also accepted)
    rom_sha1: tuple                       # ROM images the port accepts (big-endian .z64)
    rom_name: str                         # data/<rom_name> inside the source tree
    romid: str                            # the port's CMake ROMID
    exe: str                              # build-pc/<exe>.<arch>
    converters: tuple                     # argv tails run with the worker's Python, cwd = source tree
    sidecars: tuple                       # files the converters write (relative to the source tree)
    bridge: str                           # gBox's bridge source, relative to system/
    hooks: tuple                          # (file, old, new): exact one-time insertions into the upstream tree
    fixes: dict = field(default_factory=dict)       # machine -> ((file, old, new), ...)
    ini: dict = field(default_factory=dict)         # section -> {key: value} gBox pins in the port's ini (Linux)
    arenas: tuple = ()                    # GE_STARTMP stage indexes a quick match picks from
    seats: tuple = (1, 2, 3)              # seats the bots take


GE007 = Port(
    id="ge007",
    title="GoldenEye 007 (PC port + bots)",
    repo="https://github.com/jkdansereau/goldeneye-pc-port.git",
    commit="5b86a9bbeba89508a0c7d6b797361b7454ceda20",
    tag="v0.6.0",
    platform="n64",
    titles=(r"golden\s*eye\s*007", r"007\W+golden\s*eye"),
    regions=("US", None),
    rom_sha1=("abe01e4aeb033b6c0836819f549c791b26cfde83",),        # 007 - GoldenEye (USA), the only ROM it builds for
    rom_name="ge007.ntsc-final.z64",
    romid="ntsc-final",
    exe="ge007",
    converters=(("tools_pc/d43_emit.py", "ntsc-final"), ("tools_pc/d69_emit.py", "ntsc-final"),
                ("tools_pc/d88_emit.py", "ntsc-final", "--regen")),
    sidecars=("data/pcmodels-ntsc-final/pcmodels.bin", "data/pccg-ntsc-final/pccg.bin"),
    bridge="adapters/ge007_port/gbox_bridge.c",
    hooks=(
        ("src/boss.c",
         "                            joyConsumeSamplesWrapper();\n                            permit_stderr(0);\n",
         "                            joyConsumeSamplesWrapper();\n"
         "                            { extern void gboxBridgeTick(void); gboxBridgeTick(); }   /* gBox bridge */\n"
         "                            permit_stderr(0);\n"),
        ("port/src/input.c",
         "    if (sx > STICK_MAX)  sx = STICK_MAX;\n",
         "    {   /* gBox bridge (gbox_bridge.c): a seat gBox drives takes its buttons and stick */\n"
         "        extern int gboxBridgeSeat(int idx, unsigned *button, int *sx, int *sy);\n"
         "        gboxBridgeSeat(idx, &button, &sx, &sy);\n"
         "    }\n"
         "    if (sx > STICK_MAX)  sx = STICK_MAX;\n"),
    ),
    fixes={
        # ARM Linux is "not yet" upstream (v0.6.0 ships arm64 macOS only). Two things stand in the way on aarch64:
        "aarch64": (
            # the D34 ANIM_DATA lvalues are only widened for arm64 macOS; Linux needs the same (address-only)
            ("assets/animationtable_data.h",
             "#if defined(__x86_64__) || (defined(__aarch64__) && defined(__APPLE__))\n",
             "#if defined(__x86_64__) || defined(__aarch64__)   /* gBox: aarch64 Linux too */\n"),
            # sub_GAME_7F0B37EC walks specialportalarray up to &g_BgCurrentRoom (N64 linker adjacency); aarch64 GCC
            # puts levelentry_index between the two, the walk reads it as a record and loops forever loading Temple
            ("src/game/bg.c",
             "    end = (u8 *)&g_BgCurrentRoom;\n",
             "    end = specialportalarray + sizeof(specialportalarray);   /* gBox: not linker adjacency */\n"),
        ),
    },
    ini={"Input": {"NaturalPitch": "0", "MouseEnabled": "0"},            # 1.1 Honey for streamed pads and bots
         "Window": {"Width": "960", "Height": "720"},
         "Video": {"VSync": "0"}},
    arenas=(1, 2, 3, 4, 5, 6, 7),                                       # Temple .. Facility: 4-player arenas
)

PORTS = {GE007.id: GE007}


def machine() -> str:
    m = _platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(m, m)


def port_root(config, port: Port) -> Path:
    return Path(config.runtime) / "ports" / port.id


def source_dir(config, port: Port) -> Path:
    return port_root(config, port) / "src"


def exe_path(config, port: Port) -> Path:
    name = f"{port.exe}.{machine()}" + (".exe" if HOST_OS == "windows" else "")
    return source_dir(config, port) / "build-pc" / name


def bridge_name(port: Port, tag: str) -> str:
    """GE_GBOX_BRIDGE for one session: a file under /dev/shm on Linux, a named mapping on Windows."""
    safe = re.sub(r"[^\w.-]", "_", tag)
    if HOST_OS == "windows":
        return f"Local\\gbox-{port.id}-{safe}"
    shm = Path("/dev/shm")
    return str((shm if shm.is_dir() else Path(os.environ.get("TMPDIR", "/tmp"))) / f"gbox-{port.id}-{safe}")


# ----------------------------------------------------------------------------------------------- source tree edits

def patch_text(text: str, old: str, new: str, where: str) -> tuple[str, bool]:
    """Insert `new` in place of `old` exactly once; already patched -> unchanged. Raises when the anchor moved."""
    if new in text:
        return text, False
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{where}: expected one anchor for the gBox patch, found {n} (upstream changed?)")
    return text.replace(old, new), True


def patch_tree(src: Path, port: Port, arch: str | None = None) -> list[str]:
    """Copy gBox's bridge into the checkout and apply the hooks and this CPU's fixes. Returns what changed."""
    changed = []
    bridge = GBOX_ROOT / port.bridge
    dst = src / "port" / "src" / Path(port.bridge).name
    if not dst.is_file() or dst.read_bytes() != bridge.read_bytes():
        dst.write_bytes(bridge.read_bytes())
        changed.append(dst.relative_to(src).as_posix())
    for rel, old, new in port.hooks + tuple(port.fixes.get(arch or machine(), ())):
        p = src / rel
        text = p.read_text(encoding="utf-8", errors="surrogateescape")
        text, did = patch_text(text, old, new, rel)
        if did:
            p.write_text(text, encoding="utf-8", errors="surrogateescape")
            changed.append(rel)
    return changed


def pin_ini(path: Path, values: dict) -> bool:
    """Set section/key values in the port's ini (created when missing), keeping every other line. True if written."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    todo = {s: dict(kv) for s, kv in values.items()}
    out, section = [], None

    def flush(sec):
        for k, v in todo.pop(sec, {}).items():
            out.append(f"{k} = {v}")
    for line in lines:
        m = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if m:
            flush(section)
            section = m.group(1)
            out.append(line)
            continue
        kv = re.match(r"\s*([^=;#]+?)\s*=", line)
        if kv and section in todo and kv.group(1) in todo[section]:
            out.append(f"{kv.group(1)} = {todo[section].pop(kv.group(1))}")
            continue
        out.append(line)
    flush(section)
    for sec in list(todo):
        if todo[sec]:
            out.append(f"[{sec}]")
            flush(sec)
    text = "\n".join(out) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


# ----------------------------------------------------------------------------------------------- build / prepare

def _light(argv: list[str]) -> list[str]:
    """Run a build step without hurting the sessions on this machine (the Spark streams games)."""
    if HOST_OS != "linux":
        return argv
    pre = ["nice", "-n", "19"]
    if shutil.which("ionice"):
        pre += ["ionice", "-c3"]
    return pre + argv


def _run(argv, cwd=None, timeout=3600, run=subprocess.run):
    r = run(argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, argv[:6]))} failed ({r.returncode}): {(r.stdout + r.stderr)[-1500:]}")
    return r


def build_check(config) -> str | None:
    missing = [t for t in ("git", "cmake") if not shutil.which(t)]
    if HOST_OS == "windows":
        return "building the native ports on Windows (MSYS2 MinGW64) is not automated yet; build on the Linux worker"
    return f"missing {', '.join(missing)}" if missing else None


def status(config, port: Port) -> dict:
    src, exe = source_dir(config, port), exe_path(config, port)
    rom = src / "data" / port.rom_name
    return {"port": port.id, "title": port.title, "upstream": f"{port.repo} {port.tag} ({port.commit[:12]})",
            "machine": machine(), "source": str(src), "exe": str(exe), "built": exe.is_file(),
            "rom": rom.is_file(), "sidecars": all((src / s).is_file() for s in port.sidecars),
            "bridge": (src / "port" / "src" / Path(port.bridge).name).is_file()}


def build(config, port: Port, jobs: int = 4, progress=None, run=subprocess.run) -> dict:
    """Clone or update the pinned upstream commit, add gBox's bridge, compile. Returns status()."""
    reason = build_check(config)
    if reason:
        raise ToolUnavailable(reason)
    say = progress or (lambda pct, msg: None)
    src = source_dir(config, port)
    src.parent.mkdir(parents=True, exist_ok=True)
    if not (src / ".git").is_dir():
        say(5, f"Cloning {port.repo} ({port.tag})")
        _run(["git", "clone", "--filter=blob:none", port.repo, str(src)], timeout=1800, run=run)
    have = run(["git", "-C", str(src), "cat-file", "-e", port.commit + "^{commit}"], capture_output=True, text=True)
    if have.returncode != 0:
        say(10, "Fetching the pinned commit")
        _run(["git", "-C", str(src), "fetch", "--tags", "origin"], timeout=1800, run=run)
    _run(["git", "-C", str(src), "checkout", "--force", "--detach", port.commit], run=run)  # tracked files back to upstream
    changed = patch_tree(src, port)
    say(20, "gBox bridge in place" + (f" ({', '.join(changed)})" if changed else ""))
    _run(_light(["cmake", "-S", ".", "-B", "build-pc", f"-DROMID={port.romid}", "-DCMAKE_BUILD_TYPE=RelWithDebInfo"]),
         cwd=src, run=run)
    say(30, f"Compiling ({jobs} jobs, low priority)")
    _run(_light(["cmake", "--build", "build-pc", "-j", str(max(1, int(jobs)))]), cwd=src, timeout=7200, run=run)
    st = status(config, port)
    if not st["built"]:
        raise RuntimeError(f"the build finished without {exe_path(config, port).name}")
    say(100, f"Built {exe_path(config, port)}")
    return st | {"patched": changed}


def rom_bytes(rom: Path, port: Port) -> bytes:
    """The ROM as big-endian bytes, refused unless it is one the port builds for."""
    from . import n64_rom
    data = n64_rom.read(rom)
    sha = hashlib.sha1(data).hexdigest()
    if sha not in port.rom_sha1:
        raise ValueError(f"{Path(rom).name} (SHA-1 {sha}) is not a ROM the {port.title} accepts "
                         f"(it needs {', '.join(port.rom_sha1)})")
    return data


def prepare(config, port: Port, rom: Path, progress=None, run=subprocess.run) -> dict:
    """The operator's ROM into the port's data folder, the converters run once, gBox's ini settings pinned."""
    say = progress or (lambda pct, msg: None)
    src = source_dir(config, port)
    data = rom_bytes(Path(rom), port)
    target = src / "data" / port.rom_name
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = not target.is_file() or hashlib.sha1(target.read_bytes()).hexdigest() != hashlib.sha1(data).hexdigest()
    if fresh:
        target.write_bytes(data)
    converted = False
    if fresh or not all((src / s).is_file() for s in port.sidecars):
        for i, tail in enumerate(port.converters):
            say(40 + 15 * i, f"Converting the ROM's models and stages ({Path(tail[0]).name})")
            _run(_light([sys.executable, *tail]), cwd=src, timeout=1800, run=run)
        converted = True
    pinned = pin_ini(src / "data" / "ge007.ini", port.ini) if HOST_OS == "linux" and port.ini else False
    return {"rom": str(target), "converted": converted, "ini_pinned": pinned}


# ----------------------------------------------------------------------------------------------- catalog

def _matches(port: Port, e: dict) -> bool:
    """A catalog ROM the port could take (title and region; the ROM's SHA-1 is checked when the port prepares it:
    the catalog's hashes are the stored file's, usually a .zip)."""
    if e.get("platform") != port.platform or (e.get("launch") or {}).get("kind") == "native_port":
        return False
    title = str(e.get("title") or "")
    return e.get("region") in port.regions and any(re.search(t, title, re.I) for t in port.titles)


def entry_id(port: Port) -> str:
    """One id per port, whichever library's copy of the ROM it points at (partial scans upsert the same entry)."""
    return hashlib.sha1(f"native_port:{port.id}".encode()).hexdigest()[:16]


def catalog_entries(entries) -> list[CatalogEntry]:
    """One entry per port whose ROM the library holds; a ROM file the emulator launches directly is preferred over
    a front-end (attract) listing of the same game."""
    out, seen = [], set()
    rows = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in entries]
    rows.sort(key=lambda d: (d.get("launch") or {}).get("kind") != "emulator")
    for d in rows:
        for port in PORTS.values():
            if port.id in seen or not _matches(port, d):
                continue
            seen.add(port.id)
            gid = entry_id(port)
            launch = {"kind": "native_port", "port": port.id, "base_game_id": d["game_id"], "platform": port.platform,
                      "path": (d.get("launch") or {}).get("path") or (d.get("source_paths") or [""])[0]}
            member = (d.get("launch") or {}).get("archive_member")
            if member:
                launch["archive_member"] = member
            out.append(CatalogEntry(
                game_id=gid, title=port.title, platform=port.platform, platform_confidence="native port",
                region=d.get("region"), source_paths=list(d.get("source_paths") or []), library=d.get("library"),
                rel_path=d.get("rel_path"), system="Native PC ports", collections=["native-ports"], core=None,
                year=d.get("year"), manufacturer=d.get("manufacturer"), category=d.get("category"), players="1-4",
                media=d.get("media") or {}, hashes=d.get("hashes") or {}, size=d.get("size") or 0, format=d.get("format") or "zip",
                runtimes={f"native_port/{port.id}": "built on the Linux worker"}, launch=launch, profile_id=gid))
    return out


# ----------------------------------------------------------------------------------------------- the session

N64_KEYS = {                                  # gBox pad names (RetroPad, padmap.py's N64 layout) -> N64 buttons
    "b": 0x8000, "a": 0x8000,                 # N64 A = Xbox A = RetroPad "b" ("a" accepted too)
    "y": 0x4000, "x": 0x4000,                 # N64 B = Xbox X = RetroPad "y"
    "l2": 0x2000, "z": 0x2000,                # Z = left trigger
    "start": 0x1000,
    "up": 0x0800, "down": 0x0400, "left": 0x0200, "right": 0x0100,
    "l": 0x0020, "r": 0x0010, "r2": 0x0010,
    "rup": 0x0008, "cup": 0x0008, "rdown": 0x0004, "cdown": 0x0004,
    "rleft": 0x0002, "cleft": 0x0002, "rright": 0x0001, "cright": 0x0001,
}
N64_STICK = {"lup": (0, 80), "ldown": (0, -80), "lleft": (-80, 0), "lright": (80, 0)}


class PortAdapter(Adapter):
    """A native port session. Linux: private Xvfb, VirtualGL, MJPEG stream; Windows: a local window."""
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "send_input", "stream_session"}
    screen = (960, 720)

    def __init__(self, config, game: dict | None = None, port: Port | None = None):
        launch = (game or {}).get("launch") or {}
        self.port = port or PORTS[launch.get("port", "ge007")]
        self.port_id, self.name = self.port.id, f"{self.port.id}_port"
        self.config, self.game = config, game or {}
        self.proc = self.display = self.stream = self.bridge = self.log_path = None
        self.bots, self._bots_stop, self.bridge_path = None, None, ""
        self.held: set[str] = set()
        self._pad_lock = threading.Lock()
        self._idle_since = None
        self.demo = False                       # set by _launch_game for autoplay / screensaver launches (jump)
        self.difficulty = os.environ.get("GBOX_GE007_BOTS", "00")
        if HOST_OS == "windows":                # a local window the desktop docks: no stream of its own
            self.supported = self.supported - {"stream_session"}

    def _p(self, pct, msg):
        cb = getattr(self, "progress", None)
        if cb:
            cb(pct, msg)

    def launch_game(self, rom: str) -> dict:
        port, cfg = self.port, self.config
        exe = exe_path(cfg, port)
        if not exe.is_file():
            if HOST_OS != "linux":
                raise ToolUnavailable(f"{port.title} is not built on this PC ({exe}); it builds on the Linux worker")
            self._p(8, f"First launch: building {port.title} on this PC (a few minutes, low priority)")
            build(cfg, port, progress=self._p)
        prep = prepare(cfg, port, Path(rom), progress=self._p)
        src = source_dir(cfg, port)
        logs = Path(cfg.runtime) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        tag = f"{os.getpid()}-{int(time.time() * 1000) % 10**8}"
        self.bridge_path = bridge_name(port, tag)
        env = {**os.environ, "GE_GBOX_BRIDGE": self.bridge_path, "GE_MPVIRT": str(len(port.seats))}
        if self.demo and port.arenas:
            env["GE_STARTMP"] = f"{len(port.seats) + 1},{random.choice(port.arenas)}"
        argv = [str(exe)]
        if HOST_OS == "linux":
            self.display = Display(*self.screen)
            env |= {"DISPLAY": self.display.name, "SDL_AUDIODRIVER": "dummy"}
            if Path(VGLRUN).exists():
                argv = [VGLRUN, "-d", "egl", *argv]
        self.log_path = logs / f"{self.name}-{tag}.log"
        self._p(70, f"Starting {port.title}" + (" in a 4-player match with bots" if "GE_STARTMP" in env else ""))
        with open(self.log_path, "wb") as log:
            if HOST_OS == "windows":
                from .adapters import _popen
                self.proc = _popen(self, argv, cwd=str(src), env=env, stdout=log, stderr=subprocess.STDOUT)
            else:
                self.proc = subprocess.Popen(argv, cwd=str(src), env=env, stdout=log, stderr=subprocess.STDOUT)
        from . import ge007_bridge, ge007_bots
        self.bridge = ge007_bridge.Bridge(self.bridge_path)
        if not self.bridge.open(timeout=90, stopped=lambda: self.proc.poll() is not None):
            rc = self.proc.poll()
            tail = self.log_tail()
            self.stop_game()
            raise RuntimeError(f"{port.title} did not start (exit {rc}): {tail}")
        self.bots, self._bots_stop = ge007_bots.start_thread(self.bridge, port.seats, self.difficulty)
        threading.Thread(target=self._pad_keepalive, daemon=True, name=f"{self.name}-pad").start()
        self._p(95, f"Bots on seats {', '.join(str(s + 1) for s in port.seats)} ({self.difficulty})")
        detail = {"pid": self.proc.pid, "worker_name": _platform.node(), "emulator": port.title, "log": str(self.log_path),
                  "native_port": {"id": port.id, "upstream": f"{port.tag} {port.commit[:12]}", "bridge": self.bridge_path,
                                  "bots": [s + 1 for s in port.seats], "difficulty": self.difficulty,
                                  "quick_match": "GE_STARTMP" in env, **prep}}
        if self.display:
            detail["display"] = self.display.name
        else:
            detail["local_window"] = True
        return detail

    def log_tail(self, n: int = 1500) -> str:
        try:
            return self.log_path.read_text(errors="replace")[-n:]
        except (OSError, AttributeError):
            return ""

    def stop_game(self) -> dict:
        if self._bots_stop:
            self._bots_stop.set()
        if self.stream:
            self.stream.close()
        if self.bridge:
            with self._pad_lock:
                self.bridge.close()
        _kill_tree(self.proc)
        if self.display:
            self.display.close()
        if self.bridge_path and HOST_OS != "windows":
            Path(self.bridge_path).unlink(missing_ok=True)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        d = {"running": bool(self.proc and self.proc.poll() is None), "emulator": self.port.title}
        if self.bots:
            d["bots"] = {k: v for k, v in self.bots.stats.items() if k != "seats"} | \
                {"seats": {str(s + 1): v for s, v in self.bots.stats.get("seats", {}).items()}}
        return d

    def get_frame(self) -> bytes:
        if self.display:
            return grab_png(self.display.name)
        from .adapters import win_grab
        return win_grab(self.proc.pid)

    def stream_session(self) -> MjpegStream:
        if not self.display:
            from .registry import Unsupported
            raise Unsupported("a local window: the gBox desktop shows it")
        if not self.stream:
            self.stream = MjpegStream(self.display.name, size=(self.display.w, self.display.h))
        return self.stream

    def send_input(self, events: list[dict]) -> dict:
        """Player 1's pad through the bridge (no window focus needed): gBox pad names -> N64 buttons and stick."""
        sent = 0
        for ev in events:
            if int(ev.get("player", 1)) != 1:
                continue                        # players 2-4 are the bots' seats
            key = str(ev.get("key", "")).lower()
            if key not in N64_KEYS and key not in N64_STICK:
                continue
            (self.held.add if ev.get("down", True) else self.held.discard)(key)
            sent += 1
        self._idle_since = None if self.held else time.monotonic()
        self._drive_pad()
        return {"sent": sent}

    def _drive_pad(self):
        with self._pad_lock:
            if not self.bridge or self.bridge.mm is None:
                return
            buttons = sx = sy = 0
            for k in self.held:
                buttons |= N64_KEYS.get(k, 0)
                dx, dy = N64_STICK.get(k, (0, 0))
                sx, sy = sx + dx, sy + dy
            self.bridge.drive(0, buttons, sx, sy)

    def _pad_keepalive(self):
        """The port drops a seat whose writer goes quiet for 2 s: re-send player 1's pad while it is in use, and
        hand the seat back to the port's own input 2 s after the last key came up."""
        while self.proc is not None and self.proc.poll() is None and self.bridge and self.bridge.mm is not None:
            time.sleep(0.25)
            if self.held:
                self._drive_pad()
            elif self._idle_since is not None and time.monotonic() - self._idle_since > 2.0:
                with self._pad_lock:
                    if self.bridge and self.bridge.mm is not None:
                        self.bridge.release(0)
                self._idle_since = None


def adapter(game: dict, config) -> PortAdapter:
    return PortAdapter(config, game)


# ----------------------------------------------------------------------------------------------- the tool

class NativePortIn(BaseModel):
    op: str = "status"            # status | build | prepare
    port: str = "ge007"
    rom_path: str = ""            # prepare: the owned ROM (.z64/.v64/.n64 or in a .zip/.7z) this worker can read
    jobs: int = 4                 # build: parallel compile jobs (the build runs at nice 19)


class NativePortOut(BaseModel):
    op: str
    result: dict


@tool("native_port", "1.0", NativePortIn, NativePortOut, capabilities=["native-port", "build", "n64"],
      platforms=["linux", "windows"], permissions=[P.READ, P.EXECUTE], timeout_s=7200,
      side_effects=["clones and compiles the port under <runtime>/ports/<id> (nice 19, -j4)",
                    "copies the operator's ROM and the files made from it into that folder"])
def native_port(inp: NativePortIn, ctx):
    """Native PC ports (GoldenEye 007 PC port + gBox bots): op=status (built? ROM and converted files in place?) |
    build (clone the pinned upstream commit, add gBox's bridge, compile at low priority, jobs=4) | prepare
    (rom_path: the owned ROM, SHA-1 checked, into the port's data folder; the port's converters run once)."""
    port = PORTS.get(inp.port)
    if port is None:
        raise ValueError(f"unknown port {inp.port!r}: {', '.join(PORTS)}")
    op = inp.op.lower()
    if op == "status":
        return {"op": op, "result": status(ctx.config, port)}
    if op == "build":
        return {"op": op, "result": build(ctx.config, port, jobs=inp.jobs, progress=ctx.progress)}
    if op == "prepare":
        if not inp.rom_path:
            raise ValueError("prepare needs rom_path")
        return {"op": op, "result": prepare(ctx.config, port, Path(inp.rom_path), progress=ctx.progress)}
    raise ValueError("op: status | build | prepare")
