"""Pinned REA runtime and worker-owned, persistent JSON-RPC stdio sessions.

No agent registrations or upstream setup wizard are run. Binary databases,
evidence, unknowns and runtime sessions remain in the same REA process until
the worker exits. A failed call is never silently retried after losing state.
"""
import atexit
from collections import deque
from functools import lru_cache
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from .registry import ToolUnavailable

VERSION = "6.0.0"


class RpcError(RuntimeError):
    """The server rejected a request; its transport and analysis state remain valid."""


def package_root(config):
    return config.runtime.resolve() / "rea" / "node_modules" / "rea-agents"


@lru_cache(maxsize=8)
def node_problem(executable):
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        major, minor, *_ = map(int, result.stdout.strip().lstrip("v").split("."))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "Could not determine this worker's Node.js version."
    if not (major >= 26 or major == 24 and minor >= 11 or major == 22 and minor >= 19):
        return f"REA requires Node ^22.19, ^24.11 or >=26; found {result.stdout.strip()}."
    return None


def unavailable(config):
    if not shutil.which("node"):
        return "REA requires Node.js ^22.19, ^24.11 or >=26 on this worker; install Node, then run gbox rea-install."
    if reason := node_problem(shutil.which("node")):
        return reason
    root = package_root(config)
    try:
        version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return "REA runtime missing on this worker; run gbox rea-install."
    if version != VERSION:
        return f"REA {VERSION} catalog requires the matching runtime (found {version}); run gbox rea-install."
    if not (root / "dist/main.js").is_file():
        return "REA compiled MCP runtime missing; run gbox rea-install."
    return None


def install(config):
    """Install only pinned REA and its npm dependencies; never modify agent configs."""
    if not shutil.which("node") or not shutil.which("npm"):
        raise ToolUnavailable("Install supported Node.js/npm on this worker before gbox rea-install.")
    if reason := node_problem(shutil.which("node")):
        raise ToolUnavailable(reason)
    if unavailable(config) is None:
        return {"step": "rea", "status": "ok", "version": VERSION, "path": str(package_root(config))}
    prefix = config.runtime.resolve() / "rea"
    prefix.mkdir(parents=True, exist_ok=True)
    # On Windows invoke npm's JS entry point rather than a shell/.cmd command.
    npm = Path(shutil.which("npm"))
    npm_cli = npm.parent / "node_modules/npm/bin/npm-cli.js"
    command = [shutil.which("node"), str(npm_cli)] if npm_cli.is_file() else [str(npm)]
    result = subprocess.run([*command, "install", "--prefix", str(prefix), "--ignore-scripts",
                             "--no-audit", "--no-fund", f"rea-agents@{VERSION}"],
                            capture_output=True, text=True, timeout=900,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ToolUnavailable(f"REA npm installation failed: {(result.stderr or result.stdout)[-2000:]}")
    if reason := unavailable(config):
        raise ToolUnavailable(reason)
    return {"step": "rea", "status": "ok", "version": VERSION, "path": str(package_root(config))}


class Session:
    """Serialize operations and match replies by ID; stderr never blocks stdout."""
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.process = None
        self.serial = 0
        self.responses = queue.Queue()
        self.stderr = deque(maxlen=40)
        self.server_info = {}

    def close(self):
        with self.lock:
            process, self.process = self.process, None
            if process is None:
                return
            try:
                process.stdin.close()     # EOF asks REA to clean up its own providers
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in (process.stdout, process.stderr):
                stream.close()

    def _start(self):
        if reason := unavailable(self.config):
            raise ToolUnavailable(reason)
        env = os.environ.copy()
        env.pop("ELECTRON_RUN_AS_NODE", None)
        env.update(self.config.rea_env)
        if "GHIDRA_INSTALL_DIR" not in env:
            from .provision import ghidra_home
            home = ghidra_home(self.config)
            if home:
                env["GHIDRA_INSTALL_DIR"] = str(home.resolve())
        from .analysis_runtime import apply_java_home
        apply_java_home(self.config, env)
        self.responses = queue.Queue()
        responses = self.responses
        self.stderr.clear()
        self.process = subprocess.Popen([shutil.which("node"), str(package_root(self.config) / "scripts/rea.mjs"), "--mcp"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = self.process

        def stdout():
            try:
                for line in process.stdout:
                    try:
                        message = json.loads(line)
                    except ValueError:
                        responses.put(RuntimeError("REA emitted malformed JSON-RPC output."))
                        return
                    if "id" in message and ("result" in message or "error" in message):
                        responses.put(message)
                    elif "id" in message:  # no sampling/elicitation authority delegated by gBox
                        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                                            "error": {"code": -32601, "message": "Client method not supported"}}) + "\n")
                        process.stdin.flush()
            except (OSError, ValueError) as exc:
                responses.put(exc)
            finally:
                responses.put(RuntimeError("REA transport closed; its in-memory sessions are lost. Reopen the target."))

        def stderr():
            try:
                for line in process.stderr:
                    self.stderr.append(line.rstrip())
            except (OSError, ValueError):
                pass

        threading.Thread(target=stdout, daemon=True).start()
        threading.Thread(target=stderr, daemon=True).start()
        init = self._request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": "gbox", "version": "0.1.0"}}, 60)
        self.server_info = init.get("serverInfo", {})
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()

    def _request(self, method, params, timeout, progress=None):
        self.serial += 1
        request_id = self.serial
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        last_progress = time.monotonic()
        while True:
            try:
                response = self.responses.get(timeout=max(0, min(1, deadline - time.monotonic())))
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"REA {method} exceeded {timeout}s; session closed to prevent late mutations.") from None
                if progress and time.monotonic() - last_progress >= 10:
                    progress()
                    last_progress = time.monotonic()
                continue
            if isinstance(response, Exception):
                raise RuntimeError(f"{response}\n" + "\n".join(self.stderr)) from response
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RpcError(f"REA {method}: {json.dumps(response['error'])}")
            return response["result"]

    def request(self, method, params=None, timeout=900, progress=None):
        if not self.lock.acquire(timeout=30):
            raise ToolUnavailable("This worker's REA session is busy. Wait for its active job before issuing another operation.")
        try:
            if self.process is not None and self.process.poll() is not None:
                self.close()
                raise RuntimeError("REA process exited; session state was lost. Reopen the target on the same worker.")
            try:
                if self.process is None:
                    self._start()
                return self._request(method, params or {}, timeout, progress)
            except RpcError:
                raise
            except Exception:
                self.close()
                raise
        finally:
            self.lock.release()


_sessions = {}
_lock = threading.Lock()


def session(config):
    key = (str(package_root(config)), json.dumps(config.rea_env, sort_keys=True), config.ghidra_home)
    with _lock:
        if key not in _sessions:
            _sessions[key] = Session(config)
        return _sessions[key]


def close_all():
    for item in list(_sessions.values()):
        item.close()


atexit.register(close_all)
