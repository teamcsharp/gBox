"""Game emulators and stream encoders on a heterogeneous Linux node's fast cores (2026-10-27, the Spark's GB10: X925
at 3.9 GHz on CPUs 5-9/15-19, A725 at 2.8 GHz on 0-4/10-14). With Ollama, whisper and the agents' private emulators on
any core, the live game and its x11grab encoder shared cores with them and the operator's stream hitched (~270 ms
server stalls). Ollama is pinned to the little cores by its own systemd drop-in; this pins what gBox launches for play.

GBOX_FAST_CORES: "off" disables, a cpu list ("5-9,15-19") overrides the detection."""
from __future__ import annotations

import functools
import os
import shutil
from pathlib import Path

CPU_ROOT = Path("/sys/devices/system/cpu")


@functools.lru_cache(maxsize=1)
def fast_cores(root: Path = CPU_ROOT) -> str | None:
    """The cpu list of the fastest cores ("5-9,15-19") when the node mixes core speeds, else None."""
    env = os.environ.get("GBOX_FAST_CORES", "").strip()
    if env.lower() in ("off", "0", "none", "false"):
        return None
    if env:
        return env
    freqs = {}
    for cpu in root.glob("cpu[0-9]*"):
        try:
            freqs[int(cpu.name[3:])] = int((cpu / "cpufreq" / "cpuinfo_max_freq").read_text().strip())
        except (OSError, ValueError):
            continue
    if len(set(freqs.values())) < 2:
        return None
    top = max(freqs.values())
    return _ranges(sorted(c for c, f in freqs.items() if f == top))


def _ranges(cpus: list[int]) -> str:
    out, start = [], None
    for i, c in enumerate(cpus):
        if start is None:
            start = c
        if i + 1 == len(cpus) or cpus[i + 1] != c + 1:
            out.append(f"{start}-{c}" if c != start else str(c))
            start = None
    return ",".join(out)


@functools.lru_cache(maxsize=1)
def slow_cores(root: Path = CPU_ROOT) -> str | None:
    """The other cores ("0-4,10-14"): where a MercMode game boots or waits in the background."""
    fast = fast_cores(root)
    if not fast:
        return None
    fast_set = set(_expand(fast))
    rest = sorted(int(c.name[3:]) for c in root.glob("cpu[0-9]*") if int(c.name[3:]) not in fast_set)
    return _ranges(rest) if rest else None


def _expand(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def place(pids: list[int], *, background: bool) -> None:
    """A game's whole process tree: background (booting or parked in the warm pool) on the slow cores at idle disk
    priority; playing on the fast cores at normal disk priority. Best effort, never raises."""
    import subprocess
    cores = slow_cores() if background else fast_cores()
    if not pids or not cores or not shutil.which("taskset"):
        return
    for pid in pids:
        try:
            subprocess.run(["taskset", "-a", "-cp", cores, str(pid)], capture_output=True, timeout=5)
            if shutil.which("ionice"):
                subprocess.run(["ionice", *(("-c", "3") if background else ("-c", "2", "-n", "4")), "-p", str(pid)],
                               capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def tree(pid: int) -> list[int]:
    """A process and all its descendants (/proc children lists)."""
    pids, todo = [], [pid]
    while todo:
        p = todo.pop()
        pids.append(p)
        for task in Path(f"/proc/{p}/task").glob("*/children"):
            try:
                todo += [int(c) for c in task.read_text().split()]
            except (OSError, ValueError):
                pass
    return pids


# 2 s, not 30: Eden (like Citron) re-pins EVERY thread to 10-19 whenever it starts new ones - measured on lilspark
# 2026-11-10, RE6: 64 threads placed on 5-9,15-19, then 81 threads all back on 10-19 within 12 s (a stage load). With a
# 30 s keeper the game's GPU and CPU threads spent most of their time on the A725 cores 10-14, and Pine Box measured
# the game itself rendering ~50 fps unevenly (holds of 50-83 ms, ~1.6/s). The hold below only rewrites the threads whose
# mask is wrong, in process (no taskset spawn), so a check every 2 s costs a few hundred syscalls.
KEEP_S = 2.0
_keeper: dict = {}
_ioniced: dict = {}                                    # pid -> "bg" | "fg": ionice is spawned only on a change


def _tids(pid: int) -> list[int]:
    try:
        return [int(t.name) for t in Path(f"/proc/{pid}/task").iterdir() if t.name.isdigit()]
    except OSError:
        return []


def hold(pids: list[int], *, background: bool) -> int:
    """Every thread of these processes on the wanted cores (background: the slow ones; else the fast ones), in process:
    os.sched_setaffinity on each thread whose mask differs. ionice follows a process's placement when it changes.
    Returns the threads moved. Best effort, never raises."""
    cores = slow_cores() if background else fast_cores()
    if not pids or not cores or not hasattr(os, "sched_setaffinity"):
        return 0
    want = set(_expand(cores))
    moved = 0
    for pid in pids:
        for tid in _tids(pid):
            try:
                if set(os.sched_getaffinity(tid)) != want:
                    os.sched_setaffinity(tid, want)
                    moved += 1
            except OSError:
                pass
        kind = "bg" if background else "fg"
        if _ioniced.get(pid) != kind and shutil.which("ionice"):
            import subprocess
            try:
                subprocess.run(["ionice", *(("-c", "3") if background else ("-c", "2", "-n", "4")), "-p", str(pid)],
                               capture_output=True, timeout=5)
                _ioniced[pid] = kind
            except (OSError, subprocess.SubprocessError):
                pass
    return moved


def ensure_keeper(roots, period: float = KEEP_S) -> None:
    """Hold every live game's tree on its cores, checked each `period` s (roots() -> root pids): a tree at niceness 10+
    (a MercMode game booting or parked, tools._warm_priority) on the slow cores, the rest on the fast ones; threads the
    emulator re-pins or starts later are put back at the next check (KEEP_S). One daemon thread per process; a no-op
    without a fast/slow split. _keeper["moved"] counts the threads it had to put back."""
    import threading
    if _keeper.get("thread") or not fast_cores() or os.name != "posix":
        _keeper["roots"] = roots
        return
    _keeper["roots"] = roots
    _keeper.setdefault("moved", 0)

    def run():
        import time
        while True:
            time.sleep(period)
            try:
                live = list(_keeper["roots"]() or [])
                for pid in live:
                    try:
                        background = os.getpriority(os.PRIO_PROCESS, pid) >= 10
                    except OSError:
                        continue
                    _keeper["moved"] = _keeper.get("moved", 0) + hold(tree(pid), background=background)
                for gone in [p for p in _ioniced if p not in live]:
                    _ioniced.pop(gone, None)
            except Exception:                          # noqa: BLE001 - placement is best effort, never fatal
                pass
    t = threading.Thread(target=run, daemon=True, name="gbox-cpu-affinity")
    _keeper["thread"] = t
    t.start()


def fast_argv(argv: list[str]) -> list[str]:
    """argv run on the fast cores (taskset), unchanged where there is no such split or no taskset."""
    if os.name != "posix" or not argv or argv[0] == "taskset":
        return argv
    cores = fast_cores()
    if not cores or not shutil.which("taskset"):
        return argv
    return ["taskset", "-c", cores, *argv]
