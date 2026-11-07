"""MCP over stdio, generically: start a server, list what it offers, call any of it.

REA, the Ghidra bridge and Playwright are all MCP servers that speak newline-delimited JSON-RPC on stdin/stdout. This is
the one client for them, so a new integration is a registry entry (a command and its arguments) rather than a module.

A server is kept open while it is used: these tools hold state between calls - REA keeps an opened target, the Ghidra
bridge keeps a program - and restarting per call would throw that away.
"""
import json
import os
import subprocess
import threading
import time

PROTOCOL = "2025-11-25"
DEFAULT_TIMEOUT = 300.0


class McpError(RuntimeError):
    """The server is missing, exited, or refused the call."""


def split_command(text: str) -> list[str]:
    """A registry `command` may be one line: `npx -y @playwright/mcp --browser chromium`.

    Split without POSIX unescaping: a Windows command line is full of backslashes (`C:\\Python311\\python.exe`), and
    `shlex.split` in its default mode eats them, so the process cannot be found (measured: WinError 2 from a command that
    is plainly on disk).
    """
    import shlex
    tokens = shlex.split(text, posix=False)
    out = []
    for token in tokens:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            token = token[1:-1]
        out.append(token)
    return out


class McpServer:
    """One MCP server process.

    `argv` is the command line that starts it. Nothing here is specific to a particular server, which is the point:
    adding an integration is adding argv.
    """

    def __init__(self, argv, *, name: str = "mcp", timeout: float = DEFAULT_TIMEOUT, env: dict | None = None):
        self.argv = split_command(argv) if isinstance(argv, str) else list(argv or [])
        self.name = name
        self.timeout = timeout
        self.env = env or None
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
            raise McpError(f"{self.name}: no command configured")
        environment = None
        if self.env:
            environment = {**os.environ, **{str(k): str(v) for k, v in self.env.items()}}
        try:
            self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=environment)
        except OSError as exc:
            raise McpError(f"{self.name} could not be started: {exc}") from exc
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

    def alive(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    # ---- transport
    def _write(self, payload: dict) -> None:
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, AttributeError, ValueError) as exc:
            raise McpError(f"{self.name} closed its input: {exc}") from exc

    def _readline(self, deadline: float) -> str:
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise McpError(f"{self.name} exited with code {self.process.returncode}")
            chunk = self.process.stdout.readline()
            if chunk:
                return chunk
        raise McpError(f"{self.name} did not answer within {self.timeout:.0f}s")

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
                    raise McpError(f"{self.name} refused {method}: {detail.get('message') or detail}")
                return message.get("result") or {}

    def _notify(self, method: str, params: dict) -> None:
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- the useful surface
    def list_tools(self, *, refresh: bool = False) -> list[dict]:
        self.start()
        if self.tools and not refresh:
            return self.tools
        self.tools = (self._request("tools/list", {}) or {}).get("tools") or []
        return self.tools

    def find(self, needle: str) -> list[dict]:
        needle = (needle or "").lower()
        return [tool for tool in self.list_tools()
                if needle in str(tool.get("name", "")).lower()
                or needle in str(tool.get("description", "")).lower()]

    def call(self, name: str, arguments: dict | None = None, *, timeout: float | None = None) -> dict:
        self.start()
        if timeout:
            self.timeout = float(timeout)
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})

    def text(self, name: str, arguments: dict | None = None, **kwargs) -> str:
        result = self.call(name, arguments, **kwargs)
        return "\n".join(str(item.get("text") or "") for item in (result.get("content") or [])
                         if isinstance(item, dict) and item.get("type") == "text")
