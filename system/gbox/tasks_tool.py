"""`tasks`: what gBox is running on this machine and what it costs, with a hard stop.

ops: list | kill
- list: every gBox-related process on this worker (game sessions, emulators, gBox's worker/embedder, Blender/Ghidra/RenderDoc
  runs, and test scripts started by Claude's agents), with RAM, CPU %, GPU % and GPU memory per process, plus machine totals.
- kill pid=...: end that process and everything it started; a session's emulator also ends its session.
Only processes this tool lists can be killed (never arbitrary PIDs).
"""
import os
import re
import subprocess
import sys
import time

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool

# what counts as gBox's (matched against the command line, case-insensitive)
GBOX = re.compile(r"\\gbox\\runtime\\|/gbox/runtime/|gbox game\.exe|gbox dolphin\.exe|-m gbox|winembed\.py|"
                  r"\\temp\\claude\\|/tmp/claude|agent-work|gbox-cache|renderdoc|analyzeheadless|ghidra|blender.*gbox", re.I)
KEEP = re.compile(r"-m gbox .*\b(worker|serve)\b|winembed\.py", re.I)       # gBox itself: shown, never killed from here


def _gpu_windows() -> dict[int, dict]:
    """Per-process GPU from Windows' performance counters: 3D engine % and dedicated VRAM."""
    ps = ("$u=@{}; (Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples | "
          "% { if ($_.InstanceName -match 'pid_(\\d+)_') { $u[$matches[1]] += $_.CookedValue } }; "
          "$m=@{}; (Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | "
          "% { if ($_.InstanceName -match 'pid_(\\d+)_') { $m[$matches[1]] += $_.CookedValue } }; "
          "foreach ($k in ($u.Keys + $m.Keys | Sort-Object -Unique)) { \"$k $([math]::Round($u[$k],1)) $([math]::Round($m[$k]/1MB))\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20,
                             creationflags=0x08000000).stdout
    except Exception:
        return {}
    res = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3:
            res[int(p[0])] = {"gpu_pct": float(p[1] or 0), "vram_mb": int(float(p[2] or 0))}
    return res


def _gpu_linux() -> dict[int, dict]:
    try:
        out = subprocess.run(["nvidia-smi", "pmon", "-c", "1", "-s", "um"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return {}
    res = {}
    for line in out.splitlines():
        if line.startswith("#"):
            continue
        p = line.split()
        if len(p) >= 10 and p[1].isdigit():
            sm = float(p[3]) if p[3].replace(".", "").isdigit() else 0.0
            fb = int(p[9]) if p[9].isdigit() else 0
            res[int(p[1])] = {"gpu_pct": sm, "vram_mb": fb}
    return res


def _gpu_totals() -> dict:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000 if sys.platform == "win32" else 0).stdout.strip().splitlines()[0]
        n, u, mu, mt = [x.strip() for x in out.split(",")]
        return {"gpu": n, "gpu_pct": float(u), "vram_used_mb": int(mu), "vram_total_mb": int(mt)}
    except Exception:
        return {}


def _sessions_by_pid() -> dict[int, tuple[str, str]]:
    from .tools import SESSIONS
    out = {}
    for sid, (ad, g) in list(SESSIONS.items()):
        pid = getattr(getattr(ad, "proc", None), "pid", None)
        if pid:
            title = g.get("title") if isinstance(g, dict) else getattr(g, "title", "")
            out[int(pid)] = (sid, title or "")
    return out


def _kind(cmd: str, name: str, in_session: bool) -> str:
    c = cmd.lower()
    if in_session:
        return "game"
    if KEEP.search(cmd):
        return "gbox"
    if "\\temp\\claude\\" in c or "/tmp/claude" in c or "agent-work" in c:
        return "agent test"
    if "blender" in c:
        return "blender"
    if "ghidra" in c or "analyzeheadless" in c:
        return "ghidra"
    if "renderdoc" in c:
        return "renderdoc"
    if "runtime" in c:
        return "emulator"
    return "tool"


def list_tasks() -> dict:
    import psutil
    by_pid = _sessions_by_pid()
    # Every subprocess started by a gBox worker belongs to an app task, even when
    # its command line does not contain "gbox" (ffmpeg, 7z, emulator helpers, etc.).
    try:
        children = {p.pid for p in psutil.Process().children(recursive=True)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = set()
    procs = []
    # Windows can block for minutes while psutil reads *any* attribute of an
    # unrelated process. Worker descendants and live session PIDs are the
    # authoritative app-owned processes, so inspect only those by PID.
    fields = None if sys.platform == "win32" else ["pid", "ppid", "name", "cmdline", "create_time"]
    for p in psutil.process_iter(fields):
        try:
            pid = p.pid if sys.platform == "win32" else p.info["pid"]
            known = pid in by_pid or pid in children
            if sys.platform == "win32" and not known:
                continue
            if sys.platform == "win32":
                p.info = {"pid": pid, "ppid": p.ppid(), "name": p.name(), "cmdline": p.cmdline(), "create_time": p.create_time()}
            cmd = " ".join(p.info["cmdline"] or [])
            if not (known or GBOX.search(cmd) or GBOX.search(p.info["name"] or "")):
                continue
            if pid == os.getpid():
                continue
            p.cpu_percent(None)
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(0.5)                                   # cpu_percent needs an interval
    gpu = _gpu_windows() if sys.platform == "win32" else _gpu_linux()
    pids = {p.pid for p in procs}
    rows = []
    for p in procs:
        try:
            cmd0 = " ".join(p.cmdline() or [])
            parent = next((q for q in procs if q.pid == p.ppid()), None)
            if parent is not None and p.pid not in by_pid and not KEEP.search(" ".join(parent.cmdline() or []))                     and not KEEP.search(cmd0):
                continue                              # shown inside its parent's tree
            # gBox's own worker/embedder: just itself (its games are separate rows, each with its own stop)
            tree = [p] if KEEP.search(cmd0) else [p] + [c for c in p.children(recursive=True)]
            rss = sum(x.memory_info().rss for x in tree if x.is_running())
            cpu = sum(x.cpu_percent(None) for x in tree if x.is_running())
            g = [gpu.get(x.pid, {}) for x in tree]
            cmd = " ".join(p.cmdline() or [])
            sid, title = by_pid.get(p.pid, (None, ""))
            if not sid:
                for c in tree:
                    if c.pid in by_pid:
                        sid, title = by_pid[c.pid]
            k = _kind(cmd, p.name(), bool(sid))
            rows.append({"pid": p.pid, "name": title or p.name(), "kind": k, "session_id": sid,
                         "cmd": cmd[:240], "started": p.create_time(), "procs": len(tree),
                         "ram_mb": round(rss / 2**20), "cpu_pct": round(cpu / (psutil.cpu_count() or 1), 1),
                         "gpu_pct": round(sum(x.get("gpu_pct", 0) for x in g), 1), "vram_mb": sum(x.get("vram_mb", 0) for x in g),
                         "killable": k != "gbox"})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    vm = psutil.virtual_memory()
    totals = {"ram_used_mb": round((vm.total - vm.available) / 2**20), "ram_total_mb": round(vm.total / 2**20),
              "cpu_pct": psutil.cpu_percent(0.2)} | _gpu_totals()
    return {"totals": totals, "tasks": sorted(rows, key=lambda r: -r["ram_mb"])}


def kill_task(pid: int, config=None) -> dict:
    import psutil
    listed = {r["pid"]: r for r in list_tasks()["tasks"]}
    r = listed.get(int(pid))
    if not r:
        raise ValueError(f"pid {pid} isn't one of gBox's tasks on this machine")
    if not r["killable"]:
        raise ValueError(f"{r['name']} is gBox itself (worker/embedder): restart it from Control instead")
    p = psutil.Process(int(pid))
    tree = p.children(recursive=True) + [p]
    for x in tree:
        try:
            x.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(tree, timeout=5)
    if r.get("session_id"):                            # a game: its session is over too
        from .tools import SESSIONS, track_emulator
        SESSIONS.pop(r["session_id"], None)
        if config is not None:
            track_emulator(config, r["session_id"], None, add=False)
    return {"killed": r["name"], "pid": pid, "processes": len(tree), "session_id": r.get("session_id")}


class TasksIn(BaseModel):
    op: str = "list"            # list | kill
    pid: int | None = None


class TasksOut(BaseModel):
    result: dict


@tool("tasks", "1.0", TasksIn, TasksOut, capabilities=["runtime"], permissions=[P.EXECUTE], timeout_s=60)
def tasks(inp: TasksIn, ctx):
    """What gBox is running on this machine (games, emulators, agent test runs, Blender/Ghidra/RenderDoc) with RAM, CPU,
    GPU % and VRAM per task and machine totals; op=kill pid=N ends a task and everything it started."""
    if inp.op == "kill":
        return {"result": kill_task(int(inp.pid or 0), ctx.config)}
    return {"result": list_tasks()}
