"""Typed tool registry. Tools run on workers; validation and acceptance run on the control plane."""
import concurrent.futures
import platform
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from .config import Config
from .models import Permission, ToolInfo

HOST_OS = platform.system().lower()          # "windows" | "linux" | "darwin"


class Cancelled(Exception):
    """The operator cancelled this job (e.g. Esc on the loading screen)."""


class ToolUnavailable(Exception):
    """Raised when a tool's backing program/config is missing. Always surfaced, never swallowed."""


class Unsupported(Exception):
    """Raised when a backend lacks a capability."""


class Ctx:
    """Handed to tool functions on the worker. Collects artifacts with provenance."""
    def __init__(self, config: Config, job_id: str = "local", worker: str = "local"):
        self.config, self.job_id, self.worker = config, job_id, worker
        self.server: str | None = None       # control plane URL + auth headers (set by the worker; used by live sessions)
        self.headers: dict = {}
        self.artifacts: list[tuple[str, bytes, str, dict]] = []
        self.log: list[str] = []

    def progress(self, pct: float, msg: str):
        """Live progress for the UI (loading screen). Best effort: never fails the job. Never moves backwards."""
        pct = self._pct = max(pct, getattr(self, "_pct", 0.0))
        if self.server and " #fit{" in msg:
            msg = self._fit_files(msg)
        self.log.append(f"[{pct:5.1f}%] {msg}")
        if not self.server:
            return
        try:
            import httpx
            r = httpx.post(f"{self.server}/api/jobs/{self.job_id}/progress", json={"pct": round(pct, 1), "msg": msg},
                           headers=self.headers, timeout=3).json()
        except Exception:
            return
        if r.get("cancel"):
            raise Cancelled("cancelled by the operator")

    def _fit_files(self, msg: str) -> str:
        """A fitting event's snapshot GLB / preview image (worker-local paths) -> uploaded to the job, URL in the event
        (gbox.fit_events). A failed upload drops the file from the event, never the progress line."""
        from pathlib import Path
        from . import fit_events
        text, ev = fit_events.split(msg)
        if ev is None:
            return msg
        for key in ("snapshot", "preview"):
            p = ev.get(key)
            if not p or str(p).startswith("/api/"):
                continue
            ev.pop(key)
            f = Path(p)
            try:
                if f.is_file() and f.stat().st_size <= 8 << 20:
                    import httpx
                    r = httpx.post(f"{self.server}/api/jobs/{self.job_id}/fitting/files/{f.name}", content=f.read_bytes(),
                                   headers=self.headers, timeout=10)
                    if r.status_code == 200:
                        ev[key] = r.json()["url"]
            except Exception:                                # noqa: BLE001 - best effort, like progress itself
                pass
        return text + fit_events.encode(ev)

    def artifact(self, name: str, data: bytes, media_type: str = "application/octet-stream", **provenance):
        self.artifacts.append((name, data, media_type, {"job": self.job_id, "worker": self.worker, **provenance}))


@dataclass
class Tool:
    name: str
    version: str
    fn: Callable
    In: type[BaseModel]
    Out: type[BaseModel]
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: ["windows", "linux"])
    engines: list[str] = field(default_factory=lambda: ["*"])
    permissions: list[Permission] = field(default_factory=lambda: [Permission.READ])
    side_effects: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    timeout_s: float = 60
    retries: int = 0
    validation: str = "output schema"
    # (output, {artifact name: bytes}) -> problems. Runs on the control plane, not the worker.
    validate: Callable[[BaseModel, dict[str, bytes]], list[str]] | None = None
    # (store, output) -> None. Server-side ingestion after validation passes.
    on_accept: Callable | None = None
    # (store, job dict, actor) -> None. Server-side bookkeeping when a job fails/is invalid.
    on_fail: Callable | None = None
    # (config) -> reason string if unavailable on this host, else None.
    check: Callable[[Config], str | None] | None = None

    def info(self) -> ToolInfo:
        return ToolInfo(name=self.name, version=self.version, description=self.description,
                        capabilities=self.capabilities, input_schema=self.In.model_json_schema(),
                        output_schema=self.Out.model_json_schema(), platforms=self.platforms, engines=self.engines,
                        permissions=self.permissions, side_effects=self.side_effects, artifacts=self.artifacts,
                        timeout_s=self.timeout_s, retries=self.retries, validation=self.validation)

    def unavailable_reason(self, config: Config) -> str | None:
        if HOST_OS not in self.platforms:
            return f"host os {HOST_OS} not in {self.platforms}"
        return self.check(config) if self.check else None


REGISTRY: dict[str, Tool] = {}


def tool(name: str, version: str, In: type[BaseModel], Out: type[BaseModel], **kw):
    def deco(fn):
        REGISTRY[name] = Tool(name=name, version=version, fn=fn, In=In, Out=Out,
                              description=(fn.__doc__ or "").strip(), **kw)
        return fn
    return deco


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)


def _run_with_fitting(fn, inp, ctx: "Ctx"):
    """A tool run with a fitting-event sink (gbox.fit_events): the writers' per-model stages reach this job's progress
    stream, and their snapshot files are removed once the job has uploaded them."""
    import shutil
    from pathlib import Path
    from . import fit_events
    work = Path(getattr(ctx.config, "cache", None) or ".") / "fitting" / str(ctx.job_id)
    try:
        with fit_events.job(ctx.progress, work):
            return fn(inp, ctx)
    finally:
        if ctx.server:
            shutil.rmtree(work, ignore_errors=True)


def execute(name: str, raw_input: dict, ctx: Ctx) -> dict:
    """Run a tool on this host with input validation, timeout and retries. Raises on failure."""
    t = REGISTRY[name]
    if reason := t.unavailable_reason(ctx.config):
        raise ToolUnavailable(reason)
    inp = t.In.model_validate(raw_input)
    last = None
    for attempt in range(t.retries + 1):
        ctx.artifacts.clear()
        try:
            # ponytail: a timed-out thread keeps running in the background; move tools to subprocesses if that bites.
            out = _pool.submit(_run_with_fitting, t.fn, inp, ctx).result(timeout=t.timeout_s)
            return t.Out.model_validate(out).model_dump(mode="json")
        except (ToolUnavailable, Unsupported, Cancelled):
            raise
        except Exception as e:
            last = e
            ctx.log.append(f"attempt {attempt + 1} failed: {traceback.format_exc(limit=3)}")
            time.sleep(0.2 * (attempt + 1))
    raise last
