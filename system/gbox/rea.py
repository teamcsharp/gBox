"""REA as a gBox tool: the MCP server started locally and called over stdio.

REA (`http://github.com/morluto/rea`, package `rea-agents`) is one MCP server over binaries, applications and runtimes -
229 tools at 6.8.0. Registering it with an agent's config only helps that agent; this module lets gBox itself start it,
list what it can do, and call any of it, so a route, a bot, a scheduled task or another operator can all use it.

The transport is MCP over stdio: newline-delimited JSON-RPC 2.0, one object per line. That is why the client below is a
subprocess and a line reader rather than an HTTP client.
"""
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time

TOOL_ENV = "GBOX_REA"
DEFAULT_TIMEOUT = 300.0
PROTOCOL = "2025-11-25"


class ReaError(RuntimeError):
    """REA is missing, or the server refused/failed the call."""


def install_dir() -> pathlib.Path:
    """Where the project keeps REA: `~/gBox_alt/tools/rea` (installed with npm), overridable by `GBOX_REA`."""
    return pathlib.Path(os.environ.get(TOOL_ENV) or (pathlib.Path.home() / "gBox_alt" / "tools" / "rea"))


def command() -> list[str] | None:
    """The argv that starts the MCP server, or None when REA is not installed."""
    override = os.environ.get("GBOX_REA_COMMAND")
    if override:
        return override.split()
    folder = install_dir()
    for candidate in (folder / "node_modules" / ".bin" / "rea", folder / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"):
        if candidate.is_file():
            if candidate.suffix == ".mjs":
                node = shutil.which("node")
                return [node, str(candidate), "--mcp"] if node else None
            return [str(candidate), "--mcp"]
    found = shutil.which("rea")
    return [found, "--mcp"] if found else None


def available() -> dict:
    """Whether REA can be started here, and where it lives - for a page to show rather than guess at."""
    argv = command()
    return {"installed": argv is not None, "command": argv, "dir": str(install_dir()),
            "note": "install with `npm install rea-agents` in that directory; the MCP server starts as `rea --mcp`"}


class Rea:
    """One REA server process, used for many calls.

    The server is started on first use and kept open: REA holds target state across calls ("an opened target persists
    across turns"), so restarting it per call would throw away every analysis in progress.
    """

    def __init__(self, argv: list[str] | None = None, *, timeout: float = DEFAULT_TIMEOUT):
        self.argv = argv or command()
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self.server: dict = {}
        self.tools: list[dict] = []
        self._id = 0
        self._lock = threading.Lock()

    # ---- lifecycle
    def start(self) -> dict:
        if self.process and self.process.poll() is None:
            return self.server
        if not self.argv:
            raise ReaError("REA is not installed (looked for GBOX_REA, ~/gBox_alt/tools/rea and PATH)")
        try:
            self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as exc:
            raise ReaError(f"REA could not be started: {exc}") from exc
        reply = self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                            "clientInfo": {"name": "gbox", "version": "1"}})
        self.server = reply.get("serverInfo") or {}
        self._notify("notifications/initialized", {})
        return self.server

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
        self.process = None

    # ---- transport
    def _write(self, payload: dict) -> None:
        line = json.dumps(payload) + "\n"
        try:
            self.process.stdin.write(line)
            self.process.stdin.flush()
        except (BrokenPipeError, AttributeError, ValueError) as exc:
            raise ReaError(f"REA closed its input: {exc}") from exc

    def _readline(self, deadline: float) -> str:
        line = []
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ReaError(f"REA exited with code {self.process.returncode}")
            chunk = self.process.stdout.readline()
            if chunk:
                return chunk
            line = []
        raise ReaError(f"REA did not answer within {self.timeout:.0f}s")

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._id += 1
            ident = self._id
            self._write({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            deadline = time.monotonic() + self.timeout
            while True:
                raw = self._readline(deadline)
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue                     # a log line, not a protocol message
                if message.get("id") != ident:
                    continue                     # a notification or an earlier reply
                if "error" in message:
                    detail = message["error"]
                    raise ReaError(f"REA refused {method}: {detail.get('message') or detail}")
                return message.get("result") or {}

    def _notify(self, method: str, params: dict) -> None:
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- the useful surface
    def list_tools(self, *, refresh: bool = False) -> list[dict]:
        self.start()
        if self.tools and not refresh:
            return self.tools
        result = self._request("tools/list", {})
        self.tools = result.get("tools") or []
        return self.tools

    def find(self, needle: str) -> list[dict]:
        """Tools whose name or description mentions `needle` - how a caller discovers what exists without a catalog."""
        needle = (needle or "").lower()
        return [tool for tool in self.list_tools()
                if needle in str(tool.get("name", "")).lower()
                or needle in str(tool.get("description", "")).lower()]

    def call(self, name: str, arguments: dict | None = None, *, timeout: float | None = None) -> dict:
        """Call one tool. Returns REA's raw result: `content` items plus any structured fields."""
        self.start()
        if timeout:
            self.timeout = float(timeout)
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})

    def text(self, name: str, arguments: dict | None = None, **kwargs) -> str:
        """The text content of a call, joined - what most callers want to read."""
        result = self.call(name, arguments, **kwargs)
        parts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
