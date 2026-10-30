"""Rebuild & relaunch this node from any gBox instance (operator 2026-10-26: "from my instance, i want to be able
rebuild and relaunch remote instances and be able to see a pip of the display being processed and the app updated and
rebuild with console text about the situation with npx animations and a loading bar").

The `rebuild_node` tool (gbox.tools) runs here, on the PC being rebuilt. Its console (every command line, each step's
outcome) streams through the job's progress reports in small batches, so the control plane's job doc
(POST /api/jobs/{jid}/progress -> job["console"], GET /api/jobs/{jid}/console) carries it to the desktop app's rebuild
panel; the same lines end in the rebuild.log artifact.

Steps, each a receipt {step, status: ok | skipped | warn | failed, detail}:
  code     A Windows checkout with .git: git pull --ff-only. A node running from the share has nothing to pull (the
           Spark's deploy keeps the share at merged main). The Spark itself (Linux) is deployed only by
           ~/bin/deploy_main.sh --deploy, which the operator runs: this step reports the deployed commit and never
           fetches or deploys (that gate is not bypassed).
  python   the bootstrap's pip step for this OS into this worker's own interpreter: scripts/bootstrap-windows.ps1's
           packages + pyproject dependencies on Windows; pip install -e .[test] on Linux (scripts/bootstrap-linux.sh).
  desktop  Windows: the desktop app's npm packages (the Electron runtime in %LOCALAPPDATA%\\gbox\\desktop) when
           clients/desktop/package.json changed since the last rebuild (a stamp under this node's runtime dir).
  check    python -P -m gbox --config <this node's config> setup, as the bootstraps run it, then a decisive import of
           the updated code; an import failure blocks the restart (the running worker keeps the code that works).
  restart  waits for this node's game sessions (the control plane queued their save/stop jobs first) and other jobs,
           then schedules the restart so the job's result reaches the control plane first:
             - Windows under the desktop app: a `relaunch` event on the authenticated parent pipe
               (worker_client_control): the app keeps the moments of its games, relaunches itself and restarts this
               worker. If the app does not act (older app code), the worker exits by itself and the app's watchdog
               restarts it.
             - the Spark (gbox.service): `sudo -n systemctl restart gbox.service` after the same idle check the deploy
               uses (gbox.hermes_activation --check-idle); busy = deferred, not forced (force=True skips the check).
             - no supervisor: skipped; the operator restarts by hand.
Secrets never reach the console: child processes get an environment without GBOX_TOKEN / GBOX_CLIENT_CONTROL and every
line is redacted (bearer tokens, token= / password= / secret= values, user:password@ in URLs).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .registry import HOST_OS

ROOT = Path(__file__).resolve().parent.parent                 # <checkout>/system: the code this worker runs
STEPS = (("code", "Code"), ("python", "Python packages"), ("desktop", "Desktop app packages"),
         ("check", "Self-check"), ("restart", "Restart"))
WINDOW = {"code": (2, 14), "python": (14, 46), "desktop": (46, 58), "check": (58, 90), "restart": (90, 100)}
SECRET_ENV = ("GBOX_TOKEN", "GBOX_CLIENT_CONTROL")
WINDOWS_PIP_FALLBACK = ["fastapi>=0.110", "uvicorn>=0.29", "pydantic>=2.6", "httpx>=0.27",
                        "opencv-contrib-python-headless>=4.8", "psutil>=5.9"]
SERVICE = "gbox.service"
_REDACT = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1***"),
    (re.compile(r"(?i)((?:token|secret|password|passwd|api[_-]?key|authorization)\s*[=:]\s*)(bearer\s+)?[^\s,;&\"']+"),
     r"\1\2***"),
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+(@)"), r"\1***\2"),
)
# seams for the tests (subprocesses, sleeping, the process exit)
_popen = subprocess.Popen
_sleep = time.sleep
_exit = os._exit


def _terminate_command(proc):
    """Close the command's own process tree, including inherited output pipes."""
    try:
        if HOST_OS == 'windows':
            from .adapters import _win_terminate_tree
            # Use our retained Popen handle even if the wrapper already exited;
            # its descendants may still own stdout and keep the reader blocked.
            _win_terminate_tree(proc)
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # Console.run gives it a new session
    except (OSError, AttributeError):
        proc.kill()


def _spawn_command(cmd, **kwargs):
    if HOST_OS != 'windows':
        proc = _popen(cmd, **kwargs)
        return proc, lambda: _terminate_command(proc)
    # Assign before the wrapper can spawn children. Walking current parent PIDs
    # cannot recover grandchildren after an intermediate wrapper has exited.
    import ctypes
    from ctypes import wintypes
    from .refract import _JobObject
    job, proc = _JobObject(), None
    try:
        if not job.ok:
            raise OSError('Cannot create the rebuild command job')
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x4  # CREATE_SUSPENDED
        proc = _popen(cmd, **kwargs)
        if not job.add(proc):
            raise OSError('Cannot bind the rebuild command to its job')
        resume = ctypes.WinDLL('ntdll').NtResumeProcess
        resume.argtypes, resume.restype = [wintypes.HANDLE], ctypes.c_long
        if resume(wintypes.HANDLE(int(proc._handle))) != 0:
            raise OSError('Cannot resume the rebuild command')
    except BaseException:
        if proc is not None:
            proc.kill()
        job.close()
        raise
    lock = threading.Lock()
    def stop():
        with lock:
            job.close()
    return proc, stop


class RebuildIn(BaseModel):
    enable_remote_admin: bool = False  # explicit per-installation opt-in; ordinary rebuilds never enable recovery
    force: bool = False        # restart although game sessions are still up here / the self-check failed / the Spark is busy
    restart: bool = True       # False: update and check only
    drain_s: float = Field(default=90, ge=0, le=900)     # how long to wait for this node's game sessions to close first
    delay_s: float = Field(default=6, ge=1, le=60)       # seconds between this job's result and the restart
    stop_jobs: list[str] = []  # the stop_game jobs the control plane queued before this one (the panel names them)


class RebuildOut(BaseModel):
    node: str
    os: str
    steps: list[dict]
    failed: list[str]
    restart: str               # scheduled | deferred | skipped | blocked
    detail: str = ""


def redact(text: str) -> str:
    for rx, rep in _REDACT:
        text = rx.sub(rep, text)
    return text


def scrubbed_env(env: dict | None = None) -> dict:
    """A child's environment without this worker's credentials (nothing a child prints can leak them)."""
    out = {k: v for k, v in (os.environ if env is None else env).items() if k not in SECRET_ENV}
    out.setdefault("PYTHONUNBUFFERED", "1")
    return out


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


class Console:
    """The rebuild's console: every line goes to the job's progress stream (batched, newest last) and to the
    rebuild.log artifact. The pct never moves backwards (registry.Ctx.progress keeps the maximum)."""

    def __init__(self, ctx, *, flush_s: float = 0.7, batch: int = 40, now=time.monotonic):
        self.ctx, self.flush_s, self.batch, self.now = ctx, flush_s, batch, now
        self.lines: list[str] = []
        self._pending: list[str] = []
        self._pct = 0.0
        self._sent = now()

    def line(self, text: str, pct: float | None = None):
        text = redact(str(text).rstrip("\r\n"))
        if pct is not None:
            self._pct = max(self._pct, float(pct))
        if not text.strip():
            return
        self.lines.append(text)
        self._pending.append(text)
        if len(self._pending) >= self.batch or self.now() - self._sent >= self.flush_s:
            self.flush()

    def flush(self):
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        self._sent = self.now()
        self.ctx.progress(self._pct, "\n".join(batch))         # raises Cancelled once the operator cancelled

    def step(self, n: int, key: str, title: str):
        self.line(f"== {n}/{len(STEPS)} {title} ==", WINDOW[key][0])
        self.flush()

    def run(self, cmd: list[str], *, lo: float, hi: float, cwd=None, env: dict | None = None,
            timeout: float = 1800, expect_s: float = 120) -> int:
        """Run a command: each output line to the console, pct creeping from lo towards hi while it runs."""
        self.line("$ " + " ".join(_quote(a) for a in cmd), lo)
        self.flush()
        try:
            # The desktop control reader holds a synchronous read on stdin.
            # Windows children inheriting that pipe can block during CRT startup,
            # before git or Python executes. Rebuild commands are noninteractive.
            proc, stop = _spawn_command(cmd, cwd=str(cwd) if cwd else None, env=scrubbed_env(env),
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                          start_new_session=HOST_OS != 'windows')
        except OSError as exc:
            self.line(f"! could not start {cmd[0]}: {exc}", lo)
            return 127
        started, timed_out = self.now(), threading.Event()
        timer = threading.Timer(timeout, lambda: (timed_out.set(), stop()))
        timer.daemon = True
        timer.start()
        try:
            for raw in proc.stdout:
                frac = min(0.95, (self.now() - started) / max(expect_s, 1.0))
                self.line(raw, lo + (hi - lo) * frac)
            rc = proc.wait()
        except BaseException:
            stop()
            raise
        finally:
            timer.cancel()
            stop()
        if timed_out.is_set():
            self.line(f"! {cmd[0]} did not finish within {timeout:.0f} s and was stopped", hi)
            return -1
        self.line(f"[exit {rc}]" if rc else "[ok]", hi)
        return rc


# --- the steps ---------------------------------------------------------------------------------------------------

def _receipt(step: str, status: str, detail: str = "") -> dict:
    return {"step": step, "status": status, "detail": str(detail)[:400]}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _req_name(req: str) -> str:
    return re.split(r"[<>=!~\[; ]", req, maxsplit=1)[0].strip().lower().replace("_", "-")


def config_path() -> Path:
    """This worker's config file: the --config it was started with, else GBOX_CONFIG, else the checkout's gbox.toml."""
    argv = sys.argv
    if "--config" in argv and argv.index("--config") + 1 < len(argv):
        return Path(argv[argv.index("--config") + 1])
    if env := os.environ.get("GBOX_CONFIG"):
        return Path(env)
    return ROOT / "gbox.toml"


def bootstrap_packages(script: Path | None = None) -> list[str]:
    """The pip packages scripts/bootstrap-windows.ps1 installs: the quoted requirements of its pip install line."""
    try:
        text = (script or ROOT / "scripts" / "bootstrap-windows.ps1").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(WINDOWS_PIP_FALLBACK)
    pkgs: list[str] = []
    for line in text.splitlines():
        if "pip install" in line and "--upgrade pip" not in line:
            pkgs += re.findall(r'"([^"]+)"', line.split("pip install", 1)[1].split("#", 1)[0])
    return pkgs or list(WINDOWS_PIP_FALLBACK)


def deploy_state(cfg) -> tuple[str, bool]:
    """The Spark's deployed main commit and whether runtime code waits for a restart (deploy_main.sh's files)."""
    for folder in (cfg.data_dir, ROOT / "gbox-data"):
        commit = _read(Path(folder) / "deployed-main.txt")
        if commit:
            return commit[:12], (Path(folder) / "deploy-restart-pending").exists()
    return "", (Path(cfg.data_dir) / "deploy-restart-pending").exists()


def step_code(con: Console, cfg) -> dict:
    lo, hi = WINDOW["code"]
    if HOST_OS == "linux":
        deployed, pending = deploy_state(cfg)
        con.line(f"Code: {ROOT} is the deployed copy of main" + (f" ({deployed})" if deployed else "") +
                 ". Merged main reaches it only through deploy_main.sh --deploy, which the operator runs; this rebuild "
                 "neither fetches nor deploys code.", hi)
        if pending:
            con.line("Runtime code was deployed since the last service restart (deploy-restart-pending): this restart "
                     "activates it.", hi)
        return _receipt("code", "skipped", f"deployed main {deployed or 'unknown'}; deploy_main.sh --deploy is the "
                                           "operator's step")
    git_root = next((p for p in (ROOT, ROOT.parent) if (p / ".git").exists()), None)
    if git_root is None:
        con.line(f"Code: {ROOT} runs from the share, which the Spark's deploy keeps at merged main; nothing to pull "
                 "on this PC.", hi)
        return _receipt("code", "skipped", "runs from the share")
    rc = con.run(["git", "-C", str(git_root), "pull", "--ff-only"], lo=lo, hi=hi, timeout=180, expect_s=20)
    return _receipt("code", "ok" if rc == 0 else "failed",
                    f"git pull --ff-only in {git_root}" + ("" if rc == 0 else f" exited {rc}"))


def step_python(con: Console) -> dict:
    lo, hi = WINDOW["python"]
    py, mid = sys.executable, lo + (hi - lo) * 0.25
    pip = [py, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
    if con.run([*pip, "--upgrade", "pip"], lo=lo, hi=mid, cwd=ROOT, timeout=240, expect_s=30):
        con.line("! pip could not upgrade itself; continuing with the installed pip", mid)
    if HOST_OS == "linux":
        cmd = [*pip, "-e", f"{ROOT}[test]"]                      # scripts/bootstrap-linux.sh
    else:
        from . import deps
        pkgs = bootstrap_packages()                              # scripts/bootstrap-windows.ps1
        names = {_req_name(p) for p in pkgs}
        pkgs += [req for req in deps.declared() if _req_name(req) not in names]
        cmd = [*pip, *pkgs]
    rc = con.run(cmd, lo=mid, hi=hi, cwd=ROOT, timeout=1200, expect_s=120)
    return _receipt("python", "ok" if rc == 0 else "failed",
                    f"pip into {sys.prefix}" + ("" if rc == 0 else f" exited {rc}"))


def _stamp_path(cfg) -> Path:
    return Path(cfg.runtime) / "rebuild" / "desktop-package.sha256"


def step_desktop(con: Console, cfg) -> dict:
    lo, hi = WINDOW["desktop"]
    if HOST_OS != "windows":
        con.line("Desktop app: none on this node (the Spark runs the control plane and worker only).", hi)
        return _receipt("desktop", "skipped", "no desktop app on this node")
    pkg = ROOT / "clients" / "desktop" / "package.json"
    try:
        raw = pkg.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        spec = str((json.loads(raw.decode("utf-8")).get("devDependencies") or {}).get("electron") or "")
    except (OSError, ValueError) as exc:
        con.line(f"! clients/desktop/package.json is unreadable: {exc}", hi)
        return _receipt("desktop", "failed", f"package.json unreadable: {exc}")
    stamp, previous = _stamp_path(cfg), _read(_stamp_path(cfg))
    if previous == digest:
        con.line("Desktop app packages: clients/desktop/package.json is unchanged since the last rebuild; nothing to "
                 "install.", hi)
        return _receipt("desktop", "skipped", "package.json unchanged")
    if not previous:
        _write(stamp, digest)
        con.line("Desktop app packages: first rebuild on this PC, package.json recorded; its npm packages are "
                 "reinstalled when it changes.", hi)
        return _receipt("desktop", "skipped", "package.json recorded")
    local = os.environ.get("LOCALAPPDATA")
    runtime = Path(local) / "gbox" / "desktop" if local else None
    if not runtime or not runtime.is_dir():
        con.line("! the desktop runtime folder (%LOCALAPPDATA%\\gbox\\desktop) is missing: run "
                 "clients/desktop/install.ps1 on this PC", hi)
        return _receipt("desktop", "warn", "desktop runtime folder missing")
    npm = shutil.which("npm")
    if not npm:
        con.line("! npm is not on this PC's PATH; the desktop app's packages were not reinstalled", hi)
        return _receipt("desktop", "warn", "npm missing")
    con.line(f"Desktop app packages: clients/desktop/package.json changed; installing electron@{spec or 'latest'} "
             f"into {runtime}", lo)
    rc = con.run([npm, "install", "--no-audit", "--no-fund", f"electron@{spec}" if spec else "electron"],
                 lo=lo, hi=hi, cwd=runtime, timeout=600, expect_s=90)
    if rc == 0:
        _write(stamp, digest)
        con.line("The branded runtime copy (%LOCALAPPDATA%\\gbox\\app) is refreshed by clients/desktop/install.ps1; "
                 "run it when Electron's major version changed.", hi)
    return _receipt("desktop", "ok" if rc == 0 else "failed",
                    f"npm install in {runtime}" + ("" if rc == 0 else f" exited {rc}"))


def step_check(con: Console, cfg_path: Path) -> tuple[dict, bool]:
    """gbox setup (as the bootstraps run it) and a decisive import of the updated code. Returns (receipt, may restart)."""
    lo, hi = WINDOW["check"]
    env, mid = {**os.environ, "PYTHONPATH": str(ROOT)}, lo + (hi - lo) * 0.85
    rc = con.run([sys.executable, "-P", "-m", "gbox", "--config", str(cfg_path), "setup"],
                 lo=lo, hi=mid, cwd=ROOT, env=env, timeout=1200, expect_s=180)
    probe = con.run([sys.executable, "-P", "-c", "import gbox.server, gbox.worker, gbox.tools; print('gbox imports ok')"],
                    lo=mid, hi=hi, cwd=ROOT, env=env, timeout=180, expect_s=20)
    if probe != 0:
        con.line("! the updated code does not import: the restart is blocked (the running worker keeps the code that "
                 "works)", hi)
        return _receipt("check", "failed", "gbox does not import"), False
    if rc != 0:
        con.line("! gbox setup reported failed or missing steps (above); the code imports, so the restart goes ahead", hi)
        return _receipt("check", "warn", f"gbox setup exited {rc}"), True
    return _receipt("check", "ok", "gbox setup + import"), True


def _drain(con: Console, inp: RebuildIn, lo: float, hi: float) -> int:
    """Wait (bounded) for this node's game sessions and other jobs; returns how many sessions are still up."""
    from . import tools as T
    from .registry import inflight_executions
    deadline, last, said = time.monotonic() + inp.drain_s, None, 0.0
    while True:
        sessions, others = len(T.SESSIONS), max(0, inflight_executions() - 1)
        if not sessions and not others:
            con.line("No game session or other job is running on this node.", hi)
            return 0
        if (sessions, others) != last or time.monotonic() - said >= 10:
            con.line(f"Waiting for {sessions} game session(s) to be saved and closed and {others} other job(s) to "
                     f"finish ({max(0.0, deadline - time.monotonic()):.0f} s left)...", lo)
            last, said = (sessions, others), time.monotonic()
        if time.monotonic() >= deadline:
            return sessions
        _sleep(2)


def _service_active() -> bool:
    """This process runs the Spark's gbox.service (systemd restarts it)."""
    if os.environ.get("INVOCATION_ID"):
        return True
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _spawn_detached(cmd: list[str]) -> None:
    _popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           start_new_session=True, env=scrubbed_env())


def _exit_later(seconds: float) -> None:
    """The fallback when the desktop app does not act on the relaunch event: this worker process exits, the app's
    watchdog (or the desktop-local supervisor) starts a new one on the updated code."""
    t = threading.Timer(seconds, lambda: _exit(0))
    t.daemon = True
    t.start()


def schedule_restart(con: Console, ctx, inp: RebuildIn, lo: float, hi: float) -> tuple[str, str]:
    from . import worker_client_control as WCC
    delay = inp.delay_s
    if HOST_OS == "linux" and _service_active():
        if not inp.force:
            rc = con.run([sys.executable, "-m", "gbox.hermes_activation", "--check-idle", str(ROOT)], lo=lo, hi=hi,
                         cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=120, expect_s=10)
            if rc != 0:
                con.line("Restart deferred: the Spark has running Hermes/agent work (the same idle check the deploy "
                         "uses). deploy_main.sh --deploy restarts the service in its next idle window; rerun with force "
                         "to restart now.", hi)
                return "deferred", "the Spark is busy (idle check)"
        # --no-block: the restart job is queued in systemd and goes on after it stops this service's cgroup (us included)
        _spawn_detached(["bash", "-c", f"sleep {delay:.0f}; sudo -n systemctl --no-block restart {SERVICE}"])
        con.line(f"{SERVICE} restarts in ~{delay:.0f} s (sudo -n systemctl --no-block restart {SERVICE}); the control "
                 "plane and this worker come back together.", hi)
        return "scheduled", f"systemctl restart {SERVICE}"
    control = WCC.CURRENT
    if control is not None:
        control.publish(event="relaunch", job=ctx.job_id, delay_s=delay, reason="rebuilt")
        _exit_later(delay + 20)
        con.line(f"The gBox desktop app on this PC relaunches in ~{delay:.0f} s (its games keep their moments; this "
                 f"worker restarts with it). If the app does not act within {delay + 20:.0f} s, the worker exits by "
                 "itself and the app's watchdog restarts it.", hi)
        return "scheduled", "desktop app relaunch"
    con.line("Restart skipped: no supervisor owns this worker (it was started by hand). Restart it yourself to load "
             "the update.", hi)
    return "skipped", "no supervisor"


def step_restart(con: Console, ctx, inp: RebuildIn, may_restart: bool) -> tuple[dict, str, str]:
    lo, hi = WINDOW["restart"]
    if not inp.restart:
        con.line("Restart: not requested (update and check only).", hi)
        return _receipt("restart", "skipped", "not requested"), "skipped", "restart not requested"
    if not may_restart and not inp.force:
        con.line("Restart: blocked by the failed self-check. Fix it, or rerun with force to restart anyway.", hi)
        return _receipt("restart", "skipped", "blocked by the self-check"), "blocked", "self-check failed"
    mid = lo + (hi - lo) * 0.5
    left = _drain(con, inp, lo, mid)
    if left and not inp.force:
        con.line(f"! {left} game session(s) are still running on this PC after {inp.drain_s:.0f} s; not restarting "
                 "(rerun with force to close them with the restart)", hi)
        return _receipt("restart", "failed", f"{left} session(s) still running"), "blocked", f"{left} session(s) still running"
    if left:
        con.line(f"force: {left} game session(s) close with the restart (the stop jobs asked for their moments)", mid)
    mode, detail = schedule_restart(con, ctx, inp, mid, hi)
    return _receipt("restart", {"scheduled": "ok", "deferred": "warn"}.get(mode, "skipped"), detail), mode, detail


def run(inp: RebuildIn, ctx) -> dict:
    con, node = Console(ctx), platform.node()
    con.line(f"Rebuilding {node} ({HOST_OS}, Python {sys.version.split()[0]}) from {ROOT}" +
             (" with force" if inp.force else ""), 1)
    if inp.stop_jobs:
        con.line(f"{len(inp.stop_jobs)} game session(s) on this PC are being saved and closed first (stop jobs "
                 f"{', '.join(j[:8] for j in inp.stop_jobs)})", 1)
    steps: list[dict] = []
    mode, detail = "skipped", "not reached"
    try:
        con.step(1, "code", "Code")
        steps.append(step_code(con, ctx.config))
        con.step(2, "python", "Python packages")
        steps.append(step_python(con))
        con.step(3, "desktop", "Desktop app packages")
        steps.append(step_desktop(con, ctx.config))
        con.step(4, "check", "Self-check")
        receipt, may_restart = step_check(con, config_path())
        steps.append(receipt)
        if may_restart and HOST_OS == 'windows':
            from .desktop_supervisor import install as install_recovery
            try:
                recovery = install_recovery(ctx.config, config_path(), ROOT, opt_in=inp.enable_remote_admin)
                if recovery['status'] != 'skipped':
                    steps.append(_receipt('recovery', recovery['status'], recovery['detail']))
                    con.line(recovery['detail'], WINDOW['check'][1])
            except Exception as exc:
                steps.append(_receipt('recovery', 'failed', type(exc).__name__))
                con.line('Remote recovery task could not be registered; it is not confirmed installed.', WINDOW['check'][1])
        con.step(5, "restart", "Restart")
        receipt, mode, detail = step_restart(con, ctx, inp, may_restart)
        steps.append(receipt)
        failed = [s["step"] for s in steps if s["status"] == "failed"]
        con.line(("Done: " if not failed else "Done with failures: ") +
                 ", ".join(f"{s['step']} {s['status']}" for s in steps) + f"; restart {mode}", 100)
    finally:
        try:
            con.flush()
        finally:
            ctx.artifact("rebuild.log", ("\n".join(con.lines) + "\n").encode("utf-8"), "text/plain",
                         node=node, host_os=HOST_OS)
    return {"node": node, "os": HOST_OS, "steps": steps, "failed": failed, "restart": mode, "detail": detail}
