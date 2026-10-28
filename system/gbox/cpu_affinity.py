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


KEEP_S = 30.0
_keeper: dict = {}


def ensure_keeper(roots, period: float = KEEP_S) -> None:
    """Re-place every live game's tree each `period` s (roots() -> root pids): Citron sets its own thread affinity
    after boot (2026-10-27: all 68 threads on 10-19, half of them A725) and new threads follow it. A tree at niceness
    10+ (a MercMode game booting or parked, tools._warm_priority) goes to the slow cores, the rest to the fast ones.
    One daemon thread per process; a no-op without a fast/slow split."""
    import threading
    if _keeper.get("thread") or not fast_cores() or os.name != "posix":
        _keeper["roots"] = roots
        return
    _keeper["roots"] = roots

    def run():
        import time
        while True:
            time.sleep(period)
            try:
                for pid in list(_keeper["roots"]() or []):
                    try:
                        background = os.getpriority(os.PRIO_PROCESS, pid) >= 10
                    except OSError:
                        continue
                    place(tree(pid), background=background)
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
