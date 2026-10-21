"""Typed tool registry. Tools run on workers; validation and acceptance run on the control plane."""
import concurrent.futures
from contextvars import ContextVar
import platform
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from .config import Config
from .models import Permission, ToolInfo

_execution_deadline = ContextVar('gbox_execution_deadline', default=None)

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

    @property
    def execution_deadline_monotonic(self):
        """Absolute deadline captured before executor submission, scoped to this run.

        Context-local storage prevents a reused Ctx or overlapping timed-out
        executions from replacing another execution's deadline.
        """
        active = _execution_deadline.get()
        return active[1] if active is not None and active[0] is self else None

    # A launch must not wait on the control plane: each progress POST took 1-3.5 s there (the server serializes them
    # behind its store lock; a 404 for an unknown job took 0.9-1.6 s on 2026-10-13), which made runtime_s 7.1 s and
    # stage_s 7.8 s of a cached relaunch out of two lines each. nowait = True sends from a background thread instead,
    # newest line only; a cancel in a reply raises Cancelled on the next progress() call.
    nowait = False

    def progress(self, pct: float, msg: str):
        """Live progress for the UI (loading screen). Best effort: never fails the job. Never moves backwards."""
        pct = self._pct = max(pct, getattr(self, "_pct", 0.0))
        fit = " #fit{" in msg
        if self.server and fit:
            msg = self._fit_files(msg)
        self.log.append(f"[{pct:5.1f}%] {msg}")
        if not self.server:
            return
        if self.nowait and not fit:
            self._post_later(round(pct, 1), msg)
            if getattr(self, "_cancel", False):
                raise Cancelled("cancelled by the operator")
            return
        try:
            import httpx
            r = httpx.post(f"{self.server}/api/jobs/{self.job_id}/progress", json={"pct": round(pct, 1), "msg": msg},
                           headers=self.headers, timeout=3).json()
        except Exception:
            return
        if r.get("cancel"):
            raise Cancelled("cancelled by the operator")

    def _post_later(self, pct: float, msg: str):
        """Queue the newest progress line for the sender thread (started on demand, exits when nothing is queued)."""
        import threading
        lock = self.__dict__.setdefault("_send_lock", threading.Lock())
        with lock:
            self._pending = {"pct": pct, "msg": msg}
            if getattr(self, "_sender", None) and self._sender.is_alive():
                return
            self._sender = threading.Thread(target=self._send_loop, daemon=True, name=f"progress-{self.job_id}")
            self._sender.start()

    def _send_loop(self):
        import httpx
        while True:
            with self._send_lock:
                body, self._pending = getattr(self, "_pending", None), None
                if body is None:
                    self._sender = None
                    return
            try:
                r = httpx.post(f"{self.server}/api/jobs/{self.job_id}/progress", json=body, headers=self.headers,
                               timeout=10).json()
                if r.get("cancel"):
                    self._cancel = True
            except Exception:                                # noqa: BLE001 - best effort, like the blocking path
                pass

    def _fit_files(self, msg: str) -> str:
        """A fitting event's snapshot GLB / preview image (worker-local paths) -> uploaded to the job, URL in the event
        (gbox.fit_events). A failed upload drops the file from the event, never the progress line."""
        from pathlib import Path
        from . import fit_events
        text, ev = fit_events.split(msg)
        if ev is None:
            return msg
        fields = [(ev, key) for key in ("snapshot", "preview")]
        if isinstance(ev.get("comparison"), dict):
            fields += [(ev["comparison"], key) for key in ("before", "after")]
        for owner, key in fields:
            p = owner.get(key)
            if not p or str(p).startswith("/api/"):
                continue
            owner.pop(key)
            f = Path(p)
            try:
                if f.is_file() and f.stat().st_size <= 8 << 20:
                    import httpx
                    r = httpx.post(f"{self.server}/api/jobs/{self.job_id}/fitting/files/{f.name}", content=f.read_bytes(),
                                   headers=self.headers, timeout=10)
                    if r.status_code == 200:
                        owner[key] = r.json()["url"]
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
_execution_lock = threading.Lock()
_execution_futures: set[concurrent.futures.Future] = set()


def inflight_executions() -> int:
    """Queued/running callables, including work whose caller already timed out."""
    with _execution_lock:
        return len(_execution_futures)


def _execution_finished(future):
    with _execution_lock:
        _execution_futures.discard(future)


def _submit_execution(fn, inp, ctx, deadline):
    future = _pool.submit(_run_with_fitting, fn, inp, ctx, deadline)
    with _execution_lock:
        _execution_futures.add(future)
    # A completed future invokes this callback immediately, so register it
    # outside the lock. Only completion/cancellation releases the live work.
    future.add_done_callback(_execution_finished)
    return future


def _run_with_fitting(fn, inp, ctx: "Ctx", execution_deadline=None):
    """A tool run with a fitting-event sink (gbox.fit_events): the writers' per-model stages reach this job's progress
    stream, and their snapshot files are removed once the job has uploaded them."""
    import shutil
    from pathlib import Path
    from . import fit_events
    work = Path(getattr(ctx.config, "cache", None) or ".") / "fitting" / str(ctx.job_id)
    deadline_token = _execution_deadline.set((ctx, execution_deadline))
    try:
        with fit_events.job(ctx.progress, work):
            return fn(inp, ctx)
    finally:
        _execution_deadline.reset(deadline_token)
        if ctx.server:
            shutil.rmtree(work, ignore_errors=True)


def execute(name: str, raw_input: dict, ctx: Ctx) -> dict:
    """Run a tool on this host with input validation, timeout and retries. Raises on failure."""
    t = REGISTRY[name]
    if reason := t.unavailable_reason(ctx.config):
        raise ToolUnavailable(reason)
    inp = t.In.model_validate(raw_input)
    from . import cache_tiers                    # two-tier cache: busy while it runs; named units come up first
    with cache_tiers.job_scope(name, raw_input, ctx):
        return _execute(t, inp, ctx)


def _execute(t, inp, ctx: Ctx) -> dict:
    last = None
    for attempt in range(t.retries + 1):
        ctx.artifacts.clear()
        try:
            # ponytail: a timed-out thread keeps running in the background; move tools to subprocesses if that bites.
            deadline = time.monotonic() + t.timeout_s
            out = _submit_execution(t.fn, inp, ctx, deadline).result(timeout=t.timeout_s)
            return t.Out.model_validate(out).model_dump(mode="json")
        except (ToolUnavailable, Unsupported, Cancelled):
            raise
        except Exception as e:
            last = e
            ctx.log.append(f"attempt {attempt + 1} failed: {traceback.format_exc(limit=3)}")
            time.sleep(0.2 * (attempt + 1))
    raise last
