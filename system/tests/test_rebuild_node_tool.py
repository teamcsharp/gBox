"""gbox/node_rebuild.py: the rebuild_node tool's steps on the worker, with its subprocesses scripted.

Windows: git pull (a checkout with .git) or "runs from the share", the bootstrap's pip packages, the desktop app's npm
packages only when package.json changed, gbox setup + an import probe, then the relaunch event to the desktop app.
The Spark: the deploy gate is reported and never bypassed, pip -e, gbox.service restarts only after the deploy's idle
check. Secrets stay out of the console and of every child's environment.
"""
import json
import os
import sys
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import node_rebuild as NR
from gbox import worker_client_control as WCC
from gbox.config import Config
from gbox.registry import Cancelled, Ctx


@pytest.mark.skipif(os.name != 'nt', reason='Windows synchronous control pipe')
def test_rebuild_child_starts_while_desktop_control_pipe_has_a_pending_read(tmp_path):
    """Reproduce the actual i9 startup deadlock in an isolated parent process."""
    script = tmp_path / 'control_pipe_parent.py'
    script.write_text('''
import os,sys,threading,ctypes,msvcrt,subprocess,time
from ctypes import wintypes
from types import SimpleNamespace
sys.path.insert(0, ROOT)
from gbox.node_rebuild import Console
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.GetStdHandle.argtypes=[wintypes.DWORD];k.GetStdHandle.restype=wintypes.HANDLE
k.SetStdHandle.argtypes=[wintypes.DWORD,wintypes.HANDLE];k.SetStdHandle.restype=wintypes.BOOL
old=k.GetStdHandle(0xfffffff6)
r,w=os.pipe();assert k.SetStdHandle(0xfffffff6,msvcrt.get_osfhandle(r))
entered=threading.Event()
def read():
    entered.set();os.read(r,1)
reader=threading.Thread(target=read,daemon=True);reader.start();entered.wait();time.sleep(.1)
try:
    con=Console(SimpleNamespace(progress=lambda pct,msg: None))
    result=con.run([sys.executable,'-I','-c','import sys; print("child ready",sys.stdin.read())'],lo=0,hi=100,timeout=2)
    assert result==0,con.lines
    assert any('child ready' in line for line in con.lines),con.lines
finally:
    k.SetStdHandle(0xfffffff6,old);os.write(w,b'x');reader.join(2);os.close(r);os.close(w)
'''.replace('ROOT', repr(str(Path(NR.__file__).resolve().parent.parent))), encoding='utf8')
    result = subprocess.run([sys.executable, '-I', str(script)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('wrapper_waits', [False, True])
def test_timeout_releases_stdout_inherited_by_a_descendant(tmp_path, monkeypatch, wrapper_waits):
    """A real wrapper/child pair reproduces the Git timeout's inherited pipe."""
    import psutil
    monkeypatch.setattr(NR, '_popen', subprocess.Popen)
    child_record = tmp_path / 'owned-child.json'
    script = tmp_path / 'wrapper.py'
    script.write_text(
        'import subprocess, sys, time, json, pathlib, psutil\n'
        'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        f'pathlib.Path({str(child_record)!r}).write_text(json.dumps([p.pid, psutil.Process(p.pid).create_time()]))\n'
        'print("child started", flush=True)\n'
        + ('time.sleep(60)\n' if wrapper_waits else ''), encoding='utf8')
    reports, result, errors = [], [], []
    con = NR.Console(SimpleNamespace(progress=lambda pct, msg: reports.append(msg)), flush_s=0)
    def run():
        try:
            result.append(con.run([sys.executable, str(script)], lo=0, hi=100, timeout=2))
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        worker.join(10)
        assert not worker.is_alive(), 'timed-out descendant still holds the console pipe'
        assert errors == [] and result == [-1]
        assert any('did not finish' in line for line in reports)
    finally:
        if child_record.exists():
            pid, born = json.loads(child_record.read_text())
            try:
                child = psutil.Process(pid)
                if child.create_time() == born and child.is_running():
                    child.kill()
            except psutil.NoSuchProcess:
                pass
        worker.join(3)

PS1 = ('& "$Venv\\Scripts\\python.exe" -m pip install -q --upgrade pip\n'
       '& "$Venv\\Scripts\\python.exe" -m pip install -q "fastapi>=0.110" "pycaw==20260927"   # Windows per-app volume\n')


class FakePopen:
    """A scripted child process: answer(cmd) -> (output lines, exit code)."""
    calls: list = []
    answer = staticmethod(lambda cmd: ([], 0))

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((list(cmd), kw))
        lines, rc = FakePopen.answer(cmd)
        self.stdout, self.rc, self.killed = iter([ln + "\n" for ln in lines]), rc, False

    def wait(self, timeout=None):
        return self.rc

    def kill(self):
        self.killed = True


def _has(cmd, *words):
    text = " ".join(cmd)
    return all(w in text for w in words)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    root = tmp_path / "system"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "bootstrap-windows.ps1").write_text(PS1, encoding="utf-8")
    (root / "clients" / "desktop").mkdir(parents=True)
    (root / "clients" / "desktop" / "package.json").write_text(json.dumps({"devDependencies": {"electron": "^38.0.0"}}))
    (root / "gbox.toml").write_text("")
    cfg = Config(data_dir=tmp_path / "data", runtime_dirs={NR.HOST_OS: str(tmp_path / "runtime")})
    ctx = Ctx(cfg, job_id="job1", worker="w1")
    reports = []
    monkeypatch.setattr(ctx, "progress", lambda pct, msg: reports.append((pct, msg)))
    FakePopen.calls, FakePopen.answer = [], staticmethod(lambda cmd: (["fine"], 0))
    monkeypatch.setattr(NR, "_popen", FakePopen)
    def fake_spawn(cmd, **kwargs):
        proc = NR._popen(cmd, **kwargs)
        return proc, proc.kill
    monkeypatch.setattr(NR, '_spawn_command', fake_spawn)
    monkeypatch.setattr(NR, "_sleep", lambda s: None)
    monkeypatch.setattr(NR, "ROOT", root)
    monkeypatch.setattr(NR, "HOST_OS", "windows")
    monkeypatch.setattr(NR, "_service_active", lambda: False)
    exits = []
    monkeypatch.setattr(NR, "_exit_later", lambda s: exits.append(s))
    published = []
    monkeypatch.setattr(WCC, "CURRENT", SimpleNamespace(publish=lambda **v: published.append(v)))
    monkeypatch.setattr(sys, "argv", ["python", "-m", "gbox", "--config", str(root / "gbox.toml"), "worker"])
    monkeypatch.setenv("GBOX_TOKEN", "top-secret-token")
    monkeypatch.setenv("GBOX_CLIENT_CONTROL", "a" * 64)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    from gbox import tools as T
    T.SESSIONS.clear()
    return SimpleNamespace(root=root, cfg=cfg, ctx=ctx, reports=reports, exits=exits, published=published, sessions=T.SESSIONS)


def _cmds(words_list):
    return [c for c, _ in FakePopen.calls if _has(c, *words_list)]


def test_windows_checkout_runs_every_step_in_order_and_asks_the_app_to_relaunch(rig):
    (rig.root / ".git").mkdir()
    out = NR.run(NR.RebuildIn(), rig.ctx)
    cmds = [c for c, _ in FakePopen.calls]
    assert cmds[0] == ["git", "-C", str(rig.root), "pull", "--ff-only"]
    assert cmds[1][-2:] == ["--upgrade", "pip"] and cmds[1][0] == sys.executable
    pip = cmds[2]
    assert pip[:4] == [sys.executable, "-m", "pip", "install"] and "pycaw==20260927" in pip
    assert pip.count("fastapi>=0.110") == 1 and any(p.startswith("numpy") for p in pip)      # bootstrap + pyproject, once each
    assert cmds[3] == [sys.executable, "-P", "-m", "gbox", "--config", str(rig.root / "gbox.toml"), "setup"]
    assert cmds[4][:3] == [sys.executable, "-P", "-c"] and "import gbox.server" in cmds[4][3]
    assert len(cmds) == 5
    setup_env = FakePopen.calls[3][1]["env"]
    assert setup_env["PYTHONPATH"] == str(rig.root) and "GBOX_TOKEN" not in setup_env and "GBOX_CLIENT_CONTROL" not in setup_env
    assert [(s["step"], s["status"]) for s in out["steps"]] == [("code", "ok"), ("python", "ok"), ("desktop", "skipped"),
                                                                ("check", "ok"), ("restart", "ok")]
    assert out["failed"] == [] and out["restart"] == "scheduled" and out["os"] == "windows"
    assert rig.published == [{"event": "relaunch", "job": "job1", "delay_s": 6.0, "reason": "rebuilt"}]
    assert rig.exits == [26.0]
    # the desktop package stamp was recorded for the next rebuild
    assert (Path(rig.cfg.runtime) / "rebuild" / "desktop-package.sha256").read_text()
    # every console line reached the progress stream (batched, newest last) with a pct that never moves backwards
    joined = "\n".join(msg for _, msg in rig.reports).split("\n")
    log = [name for name, *_ in rig.ctx.artifacts]
    assert log == ["rebuild.log"]
    text = rig.ctx.artifacts[0][1].decode()
    for line in ("== 1/5 Code ==", "== 2/5 Python packages ==", "== 5/5 Restart ==", "$ git -C", "[ok]"):
        assert line in text and any(line in ln for ln in joined)
    pcts = [p for p, _ in rig.reports]
    assert pcts == sorted(pcts) and pcts[-1] == 100
    assert "top-secret-token" not in text and "relaunches in ~6 s" in text


def test_a_share_checkout_has_nothing_to_pull(rig):
    out = NR.run(NR.RebuildIn(restart=False), rig.ctx)
    assert not _cmds(["git"])
    assert out["steps"][0] == {"step": "code", "status": "skipped", "detail": "runs from the share"}
    assert out["restart"] == "skipped" and out["steps"][-1]["detail"] == "not requested"
    assert rig.published == [] and rig.exits == []


def test_console_redacts_secrets_and_children_get_a_scrubbed_environment(rig):
    FakePopen.answer = staticmethod(lambda cmd: (["Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
                                                  "token=hunter2hunter2 password: sw0rdfish",
                                                  "fetching https://user:pa55@example.org/x"], 0))
    NR.run(NR.RebuildIn(restart=False), rig.ctx)
    text = rig.ctx.artifacts[0][1].decode()
    for secret in ("abcdefghijklmnopqrstuvwxyz", "hunter2", "sw0rdfish", "pa55"):
        assert secret not in text
    assert "Bearer ***" in text and "token=***" in text and "user:***@example.org" in text
    for _, kw in FakePopen.calls:
        assert "GBOX_TOKEN" not in kw["env"] and "GBOX_CLIENT_CONTROL" not in kw["env"]
        assert kw["env"]["PYTHONUNBUFFERED"] == "1"


def test_a_failed_import_blocks_the_restart_unless_forced(rig):
    FakePopen.answer = staticmethod(lambda cmd: (["ModuleNotFoundError: No module named 'gbox.server'"], 1)
                                    if _has(cmd, "import gbox") else (["ok"], 0))
    out = NR.run(NR.RebuildIn(), rig.ctx)
    assert out["failed"] == ["check"] and out["restart"] == "blocked" and rig.published == []
    assert out["steps"][-1] == {"step": "restart", "status": "skipped", "detail": "blocked by the self-check"}
    FakePopen.calls.clear()
    out = NR.run(NR.RebuildIn(force=True), rig.ctx)
    assert out["failed"] == ["check"] and out["restart"] == "scheduled" and len(rig.published) == 1


def test_a_failing_gbox_setup_is_a_warning_when_the_code_imports(rig):
    FakePopen.answer = staticmethod(lambda cmd: (["FAILED: ['ghidra']"], 1) if _has(cmd, "setup") else (["ok"], 0))
    out = NR.run(NR.RebuildIn(), rig.ctx)
    assert out["failed"] == [] and out["restart"] == "scheduled"
    assert out["steps"][3] == {"step": "check", "status": "warn", "detail": "gbox setup exited 1"}


def test_running_game_sessions_block_the_restart_without_force(rig):
    rig.sessions["w1-game"] = (None, {})
    out = NR.run(NR.RebuildIn(drain_s=0), rig.ctx)
    assert out["restart"] == "blocked" and out["failed"] == ["restart"] and rig.published == []
    assert "1 session(s) still running" in out["detail"]
    assert "Waiting for 1 game session(s)" in rig.ctx.artifacts[0][1].decode()
    out = NR.run(NR.RebuildIn(drain_s=0, force=True), rig.ctx)
    assert out["restart"] == "scheduled" and len(rig.published) == 1
    assert "force: 1 game session(s) close with the restart" in rig.ctx.artifacts[-1][1].decode()


def test_without_a_supervisor_the_restart_is_skipped(rig, monkeypatch):
    monkeypatch.setattr(WCC, "CURRENT", None)
    out = NR.run(NR.RebuildIn(), rig.ctx)
    assert out["restart"] == "skipped" and out["steps"][-1]["detail"] == "no supervisor" and rig.exits == []


def test_desktop_packages_reinstall_only_when_package_json_changed(rig, monkeypatch, tmp_path):
    stamp = Path(rig.cfg.runtime) / "rebuild" / "desktop-package.sha256"
    stamp.parent.mkdir(parents=True)
    stamp.write_text("0" * 64)                                   # a previous rebuild saw another package.json
    local = tmp_path / "local"
    (local / "gbox" / "desktop").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(NR.shutil, "which", lambda name: "C:/nodejs/npm.cmd" if name == "npm" else None)
    out = NR.run(NR.RebuildIn(restart=False), rig.ctx)
    npm = _cmds(["npm.cmd", "install"])
    assert npm == [["C:/nodejs/npm.cmd", "install", "--no-audit", "--no-fund", "electron@^38.0.0"]]
    assert FakePopen.calls[[c for c, _ in FakePopen.calls].index(npm[0])][1]["cwd"] == str(local / "gbox" / "desktop")
    assert out["steps"][2]["status"] == "ok" and stamp.read_text() != "0" * 64
    FakePopen.calls.clear()
    out = NR.run(NR.RebuildIn(restart=False), rig.ctx)
    assert not _cmds(["npm.cmd"]) and out["steps"][2] == {"step": "desktop", "status": "skipped",
                                                          "detail": "package.json unchanged"}


def test_the_spark_reports_the_deploy_gate_and_restarts_the_service_only_when_idle(rig, monkeypatch):
    monkeypatch.setattr(NR, "HOST_OS", "linux")
    monkeypatch.setattr(NR, "_service_active", lambda: True)
    rig.cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (rig.cfg.data_dir / "deployed-main.txt").write_text("4eb0c7b4deadbeef0123\n")
    (rig.cfg.data_dir / "deploy-restart-pending").write_text("")
    (rig.root / ".git").mkdir()                                  # even a checkout is never pulled on the Spark
    out = NR.run(NR.RebuildIn(), rig.ctx)
    assert not _cmds(["git"])
    assert out["steps"][0]["status"] == "skipped" and "deploy_main.sh --deploy" in out["steps"][0]["detail"]
    assert "4eb0c7b4dead" in out["steps"][0]["detail"]
    text = rig.ctx.artifacts[0][1].decode()
    assert "neither fetches nor deploys code" in text and "deploy-restart-pending" in text
    assert _cmds(["pip", "install", "-e", f"{rig.root}[test]"])
    assert out["steps"][2] == {"step": "desktop", "status": "skipped", "detail": "no desktop app on this node"}
    assert _cmds(["gbox.hermes_activation", "--check-idle", str(rig.root)])
    restart = _cmds(["systemctl", "restart", "gbox.service"])
    assert restart == [["bash", "-c", "sleep 6; sudo -n systemctl --no-block restart gbox.service"]]
    kw = FakePopen.calls[[c for c, _ in FakePopen.calls].index(restart[0])][1]
    assert kw["start_new_session"] is True and "GBOX_TOKEN" not in kw["env"]
    assert out["restart"] == "scheduled" and rig.published == [] and rig.exits == []


def test_a_busy_spark_defers_the_restart_and_force_skips_the_idle_check(rig, monkeypatch):
    monkeypatch.setattr(NR, "HOST_OS", "linux")
    monkeypatch.setattr(NR, "_service_active", lambda: True)
    FakePopen.answer = staticmethod(lambda cmd: (["gBox update deferred: Hermes work is running."], 75)
                                    if _has(cmd, "--check-idle") else (["ok"], 0))
    out = NR.run(NR.RebuildIn(), rig.ctx)
    assert out["restart"] == "deferred" and not _cmds(["systemctl"])
    assert out["steps"][-1]["status"] == "warn" and out["failed"] == []
    FakePopen.calls.clear()
    out = NR.run(NR.RebuildIn(force=True), rig.ctx)
    assert out["restart"] == "scheduled" and not _cmds(["--check-idle"]) and _cmds(["systemctl", "restart"])


def test_cancel_kills_the_running_child(rig, monkeypatch):
    calls = {"n": 0}

    def progress(pct, msg):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise Cancelled("cancelled by the operator")
    monkeypatch.setattr(rig.ctx, "progress", progress)
    FakePopen.answer = staticmethod(lambda cmd: ([f"line {n}" for n in range(10)], 0))
    con = NR.Console(rig.ctx, flush_s=0)
    with pytest.raises(Cancelled):
        con.run(["slow", "thing"], lo=0, hi=10)
    child = FakePopen.calls[-1]
    assert child[0] == ["slow", "thing"]


def test_console_batches_lines_and_a_missing_command_is_reported(rig, monkeypatch):
    clock = {"t": 0.0}
    con = NR.Console(rig.ctx, flush_s=5, batch=3, now=lambda: clock["t"])
    con.line("one", 1)
    con.line("two", 2)
    assert rig.reports == []                                     # under the batch size, inside the flush window
    con.line("three", 3)
    assert rig.reports == [(3.0, "one\ntwo\nthree")]
    clock["t"] = 10
    con.line("four", 2)                                          # a lower pct never moves the bar backwards
    assert rig.reports[-1] == (3.0, "four")

    def boom(cmd, **kw):
        raise OSError("not found")
    monkeypatch.setattr(NR, "_popen", boom)
    assert con.run(["nope"], lo=0, hi=5) == 127
    assert con.lines[-1].startswith("! could not start nope")


def test_helpers_read_the_bootstrap_the_worker_argv_and_the_deploy_state(rig, monkeypatch):
    assert NR.bootstrap_packages() == ["fastapi>=0.110", "pycaw==20260927"]
    real = Path(NR.__file__).resolve().parent.parent / "scripts" / "bootstrap-windows.ps1"
    pkgs = NR.bootstrap_packages(real)
    assert "fastapi>=0.110" in pkgs and "pycaw==20260927" in pkgs and "pip" not in pkgs
    assert NR.bootstrap_packages(rig.root / "missing.ps1") == NR.WINDOWS_PIP_FALLBACK
    assert NR.config_path() == rig.root / "gbox.toml"
    monkeypatch.setattr(sys, "argv", ["python"])
    monkeypatch.setenv("GBOX_CONFIG", "/etc/gbox.toml")
    assert NR.config_path() == Path("/etc/gbox.toml")
    monkeypatch.delenv("GBOX_CONFIG")
    assert NR.config_path() == rig.root / "gbox.toml"
    assert NR.deploy_state(rig.cfg) == ("", False)
    assert NR.redact("x-gbox-actor: operator, api_key=abc123") == "x-gbox-actor: operator, api_key=***"


def test_the_tool_is_registered_with_install_permission_and_the_log_artifact():
    from gbox import tools  # noqa: F401
    from gbox.models import Permission
    from gbox.registry import REGISTRY
    t = REGISTRY["rebuild_node"]
    assert t.permissions == [Permission.INSTALL] and t.artifacts == ["rebuild.log"] and t.timeout_s == 3600
    out = t.Out(node="x", os="windows", steps=[], failed=["python"], restart="blocked")
    assert t.validate(out, {}) == ["step failed: python"]
    assert t.validate(t.Out(node="x", os="windows", steps=[], failed=[], restart="scheduled"), {}) == []
