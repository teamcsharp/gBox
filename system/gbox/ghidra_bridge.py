"""Ghidra Bridge: the operator's Ghidra held open on a worker, queried as JSON (follows gbox/rea.py's conventions).

Upstream: Dryxio/ghidra-bridge (MIT, https://github.com/Dryxio/ghidra-bridge) gives AI agents decompile / xrefs /
strings / function search over a Ghidra program, either from a headless PyGhidra export (JSON files) or offline from
that export. gBox integrates both halves without vendoring the package:

* live  - `Session` starts gbox/ghidra_bridge_server.py under a Python that has PyGhidra, with GHIDRA_INSTALL_DIR set
          to the operator's Ghidra (config.ghidra_home / rea_env) and JAVA_HOME to the pinned JDK 21. The program stays
          open in that process between jobs (worker-owned, like REA), so every query after `open` is fast.
* export - `ExportBackend` answers the same queries from an export directory written by upstream `ghidra-bridge export`
          or by this bridge's `export` op, with no Ghidra running.

PyGhidra comes from the operator's own Ghidra (Ghidra/Features/PyGhidra/pypkg/dist, offline wheels). `install()`
creates a private venv in the worker runtime from exactly those wheels; nothing is downloaded and Ghidra itself is
never modified.
"""
import atexit
from collections import deque
from functools import lru_cache
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

from .registry import ToolUnavailable

SERVER = Path(__file__).with_name("ghidra_bridge_server.py")
SCRIPT_DIRS = [str(Path(__file__).resolve().parent.parent / "adapters" / "ghidra")]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class BridgeError(RuntimeError):
    """The bridge rejected one request; the program stays open and later requests still work."""


def ghidra_install_dir(config) -> Path | None:
    if config.rea_env.get("GHIDRA_INSTALL_DIR"):
        return Path(config.rea_env["GHIDRA_INSTALL_DIR"])
    if os.environ.get("GHIDRA_INSTALL_DIR"):
        return Path(os.environ["GHIDRA_INSTALL_DIR"])
    from .provision import ghidra_home
    return ghidra_home(config)


def venv_dir(config) -> Path:
    return config.runtime.resolve() / "pyghidra-venv"


def python_for(config) -> str:
    """GBOX_PYGHIDRA_PYTHON, then gBox's PyGhidra venv, then this interpreter."""
    if os.environ.get("GBOX_PYGHIDRA_PYTHON"):
        return os.environ["GBOX_PYGHIDRA_PYTHON"]
    v = venv_dir(config)
    for exe in (v / "Scripts" / "python.exe", v / "bin" / "python"):
        if exe.is_file():
            return str(exe)
    return sys.executable


@lru_cache(maxsize=8)
def pyghidra_version(python: str) -> str | None:
    try:
        r = subprocess.run([python, "-I", "-c", "import pyghidra, importlib.metadata as m; print(m.version('pyghidra'))"],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def wheel_dir(home: Path) -> Path:
    return home / "Ghidra" / "Features" / "PyGhidra" / "pypkg" / "dist"


def unavailable(config) -> str | None:
    home = ghidra_install_dir(config)
    if not home or not (home / "Ghidra").is_dir():
        return "Ghidra Bridge needs the operator's Ghidra on this worker: set ghidra_home (or GHIDRA_INSTALL_DIR)."
    if not pyghidra_version(python_for(config)):
        hint = f"run `gbox ghidra-bridge-install` (offline venv from {wheel_dir(home)})" if wheel_dir(home).is_dir() \
            else "this Ghidra has no bundled PyGhidra (11.3+ ships it); set GBOX_PYGHIDRA_PYTHON to a Python with pyghidra"
        return f"PyGhidra is not available to the Ghidra Bridge on this worker: {hint}."
    return None


def install(config) -> dict:
    """Create the bridge's PyGhidra venv from the operator's Ghidra wheels only (--no-index; no network, no Ghidra edits)."""
    home = ghidra_install_dir(config)
    if not home or not wheel_dir(home).is_dir():
        raise ToolUnavailable("No PyGhidra wheels in this Ghidra (needs Ghidra 11.3+): set GBOX_PYGHIDRA_PYTHON instead.")
    v = venv_dir(config)
    if not (v / "pyvenv.cfg").is_file():
        subprocess.run([sys.executable, "-m", "venv", str(v)], check=True, timeout=300, creationflags=NO_WINDOW)
    py = python_for(config)
    r = subprocess.run([py, "-m", "pip", "install", "--no-index", "--find-links", str(wheel_dir(home)), "pyghidra"],
                       capture_output=True, text=True, timeout=900, creationflags=NO_WINDOW)
    if r.returncode:
        raise ToolUnavailable(f"PyGhidra venv install failed: {(r.stderr or r.stdout)[-1500:]}")
    pyghidra_version.cache_clear()
    return {"step": "ghidra_bridge", "status": "ok", "python": py, "pyghidra": pyghidra_version(py), "ghidra": str(home)}


class Session:
    """One bridge process per worker: requests are serialized, replies matched by id, stderr never blocks stdout."""

    def __init__(self, config, command=None):
        self.config = config
        self.command = command          # tests: a fake bridge server; default: the real one under PyGhidra
        self.lock = threading.RLock()
        self.process = None
        self.serial = 0
        self.responses = queue.Queue()
        self.stderr = deque(maxlen=60)
        self.opened: dict | None = None  # the open() arguments + program info of the program held open

    def env(self):
        env = os.environ.copy()
        env.update(self.config.rea_env)
        if home := ghidra_install_dir(self.config):
            env["GHIDRA_INSTALL_DIR"] = str(Path(home).resolve())
        if "JAVA_HOME" not in env:
            from .provision import jdk21
            if java := jdk21(self.config):
                env["JAVA_HOME"] = str(java.resolve())
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        with self.lock:
            if self.running():
                return
            if self.command is None and (reason := unavailable(self.config)):
                raise ToolUnavailable(reason)
            cmd = self.command or [python_for(self.config), "-I", str(SERVER)]
            self.responses = queue.Queue()
            responses = self.responses
            self.stderr.clear()
            self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True, encoding="utf-8", env=self.env(), creationflags=NO_WINDOW)
            process = self.process

            def stdout():
                try:
                    for line in process.stdout:
                        try:
                            responses.put(json.loads(line))
                        except ValueError:
                            self.stderr.append("non-protocol stdout: " + line.rstrip()[:300])
                except (OSError, ValueError) as exc:
                    responses.put(exc)
                finally:
                    responses.put(RuntimeError("Ghidra Bridge process exited; the open program is gone. Open it again."))

            def stderr():
                try:
                    for line in process.stderr:
                        self.stderr.append(line.rstrip())
                except (OSError, ValueError):
                    pass

            threading.Thread(target=stdout, daemon=True).start()
            threading.Thread(target=stderr, daemon=True).start()

    def stop(self):
        with self.lock:
            process, self.process, self.opened = self.process, None, None
            if process is None:
                return False
            try:
                process.stdin.close()            # EOF: the server closes (saves) the program and exits
                process.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            return True

    def _request(self, op, args, timeout, progress=None):
        self.serial += 1
        rid = self.serial
        self.process.stdin.write(json.dumps({"id": rid, "op": op, "args": args}) + "\n")
        self.process.stdin.flush()
        deadline, last = time.monotonic() + timeout, time.monotonic()
        while True:
            try:
                msg = self.responses.get(timeout=max(0, min(1, deadline - time.monotonic())))
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Ghidra Bridge {op} exceeded {timeout}s; bridge stopped.") from None
                if progress and time.monotonic() - last >= 10:
                    progress()
                    last = time.monotonic()
                continue
            if isinstance(msg, Exception):
                raise RuntimeError(f"{msg}\n" + "\n".join(list(self.stderr)[-15:])) from msg
            if msg.get("id") != rid:
                continue
            if "error" in msg:
                raise BridgeError(f"Ghidra Bridge {op}: {msg['error']}")
            return msg["result"]

    def request(self, op, args=None, timeout=600, progress=None):
        if not self.lock.acquire(timeout=30):
            raise ToolUnavailable("This worker's Ghidra Bridge is busy with another job; retry when it finishes.")
        try:
            if self.process is not None and self.process.poll() is not None:
                self.stop()
                raise RuntimeError("Ghidra Bridge process exited; the open program was lost. Run op=open again.")
            self.start()
            try:
                result = self._request(op, args or {}, timeout, progress)
            except BridgeError:
                raise
            except Exception:
                self.stop()
                raise
            if op == "open":
                self.opened = {"args": args, "program": result}
            elif op == "close":
                self.opened = None
            return result
        finally:
            self.lock.release()


_sessions: dict = {}
_lock = threading.Lock()


def session(config) -> Session:
    key = (str(ghidra_install_dir(config)), json.dumps(config.rea_env, sort_keys=True))
    with _lock:
        if key not in _sessions:
            _sessions[key] = Session(config)
        return _sessions[key]


def close_all():
    for s in list(_sessions.values()):
        s.stop()


atexit.register(close_all)


# --- offline: an existing export directory (upstream `ghidra-bridge export all` or op=export) ----------------------------

def _norm(addr) -> str:
    s = str(addr).strip().lower().removeprefix("0x").split(":")[-1].lstrip("0")
    return s or "0"


class ExportBackend:
    """The bridge's query ops over an export directory; same result shapes as the live bridge."""

    def __init__(self, export_dir):
        self.dir = Path(export_dir)
        idx = self.dir / "_index.json"
        if not idx.is_file():
            raise FileNotFoundError(f"{idx} missing: not a Ghidra Bridge export directory")
        self.index = json.loads(idx.read_text(encoding="utf-8"))
        self.by_addr = {_norm(a): (a, v) for a, v in self.index.items()}
        self._strings = None

    def _record(self, target):
        t = str(target).strip()
        hit = self.by_addr.get(_norm(t)) if re.fullmatch(r"(0x)?[0-9a-fA-F:]+", t) else None
        if hit is None:
            hit = next(((a, v) for a, v in self.index.items() if v.get("name") == t), None)
        if hit is None:
            raise LookupError(f"no function {t!r} in the export")
        path = self.dir / (hit[0].replace(":", "_") + ".json")
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"address": hit[0], **hit[1]}

    def info(self, **_):
        return {"export_dir": str(self.dir), "functions": len(self.index), "source": "export"}

    def functions(self, query="", limit=100, offset=0, **_):
        q = (query or "").lower()
        rows = [{"address": "0x" + _norm(a), "name": v.get("name"), "callers": v.get("num_callers"), "callees": v.get("num_callees")}
                for a, v in self.index.items() if not q or q in str(v.get("name", "")).lower()]
        return {"total": len(rows), "functions": rows[int(offset):int(offset) + int(limit)]}

    def decompile(self, target, **_):
        r = self._record(target)
        return {"address": "0x" + _norm(r["address"]), "name": r.get("name"), "signature": r.get("signature"),
                "calling_convention": r.get("calling_convention"), "decompiled": r.get("decompiled"), "error": None,
                "callers": [{"from": None, "type": c.get("ref_type"), "function": c.get("name"),
                             "function_address": "0x" + _norm(c.get("addr"))} for c in r.get("callers", [])],
                "callees": [{"address": "0x" + _norm(c.get("addr")), "name": c.get("name")} for c in r.get("callees", [])]}

    def xrefs_to(self, target, limit=200, **_):
        d = self.decompile(target)
        return {"target": d["address"], "xrefs": d["callers"][:int(limit)]}

    def xrefs_from(self, target, **_):
        d = self.decompile(target)
        return {"address": d["address"], "name": d["name"], "callees": d["callees"],
                "data_refs": self._record(target).get("data_refs", [])}

    def containing(self, address, **_):
        a = int(_norm(address), 16)
        starts = sorted((int(_norm(k), 16), k) for k in self.index)
        best = None
        for s, k in starts:
            if s > a:
                break
            best = k
        return {"address": str(address), "function": {"address": "0x" + _norm(best), "name": self.index[best].get("name"),
                                                      "note": "nearest function start at or below; exports carry no sizes"}
                if best else None}

    def strings(self, pattern="", limit=100, **_):
        if self._strings is None:
            p = self.dir / "_strings.json"
            self._strings = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        rx, rows = re.compile(pattern or ".", re.I), []
        for a, s in self._strings.items():
            if rx.search(str(s.get("value", ""))):
                rows.append({"address": "0x" + _norm(a), "value": s.get("value"), "type": s.get("type"),
                             "references": [{"from": "0x" + _norm(r.get("ref_addr")), "function": r.get("func_name"),
                                             "function_address": "0x" + _norm(r.get("func_addr"))} for r in s.get("references", [])]})
                if len(rows) >= int(limit):
                    break
        return {"strings": rows}
