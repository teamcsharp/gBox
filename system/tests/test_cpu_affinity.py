"""Games and stream encoders on a heterogeneous node's fast cores; background (warm pool) games on the slow ones."""
import subprocess

import pytest

from gbox import cpu_affinity as C


def sysfs(tmp_path, freqs):
    for cpu, f in freqs.items():
        d = tmp_path / f"cpu{cpu}" / "cpufreq"
        d.mkdir(parents=True)
        (d / "cpuinfo_max_freq").write_text(str(f))
    return tmp_path


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("GBOX_FAST_CORES", raising=False)
    C.fast_cores.cache_clear()
    C.slow_cores.cache_clear()
    yield
    for f in (C.fast_cores, C.slow_cores):
        getattr(f, "cache_clear", lambda: None)()          # a test may have patched in a plain function


GB10 = {**{c: 2808000 for c in [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]},
        **{c: 3900000 for c in [5, 6, 7, 8, 9, 15, 16, 17, 18, 19]}}


def test_the_spark_split_is_detected(tmp_path):
    root = sysfs(tmp_path, GB10)
    assert C.fast_cores(root) == "5-9,15-19"
    assert C.slow_cores(root) == "0-4,10-14"


def test_a_uniform_node_has_no_split(tmp_path):
    root = sysfs(tmp_path, {c: 3000000 for c in range(8)})
    assert C.fast_cores(root) is None and C.slow_cores(root) is None


def test_the_env_overrides_or_disables(tmp_path, monkeypatch):
    root = sysfs(tmp_path, GB10)
    monkeypatch.setenv("GBOX_FAST_CORES", "off")
    assert C.fast_cores(root) is None
    C.fast_cores.cache_clear()
    monkeypatch.setenv("GBOX_FAST_CORES", "6-9")
    assert C.fast_cores(root) == "6-9"


def test_fast_argv_prefixes_taskset_only_with_a_split(monkeypatch):
    monkeypatch.setattr(C, "fast_cores", lambda: "5-9,15-19")
    monkeypatch.setattr(C.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(C.os, "name", "posix")
    assert C.fast_argv(["ffmpeg", "-i", ":90"]) == ["taskset", "-c", "5-9,15-19", "ffmpeg", "-i", ":90"]
    assert C.fast_argv(["taskset", "-c", "1", "x"]) == ["taskset", "-c", "1", "x"]
    monkeypatch.setattr(C, "fast_cores", lambda: None)
    assert C.fast_argv(["ffmpeg"]) == ["ffmpeg"]


def test_place_moves_a_tree_to_slow_or_fast_cores(monkeypatch):
    calls = []
    monkeypatch.setattr(C, "fast_cores", lambda: "5-9,15-19")
    monkeypatch.setattr(C, "slow_cores", lambda: "0-4,10-14")
    monkeypatch.setattr(C.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: calls.append(argv))
    C.place([11, 12], background=True)
    assert ["taskset", "-a", "-cp", "0-4,10-14", "11"] in calls and ["ionice", "-c", "3", "-p", "12"] in calls
    calls.clear()
    C.place([11], background=False)
    assert calls == [["taskset", "-a", "-cp", "5-9,15-19", "11"], ["ionice", "-c", "2", "-n", "4", "-p", "11"]]


def test_the_keeper_holds_by_niceness(monkeypatch):
    placed = []
    monkeypatch.setattr(C, "fast_cores", lambda: "5-9,15-19")
    monkeypatch.setattr(C.os, "name", "posix")
    monkeypatch.setattr(C, "tree", lambda pid: [pid])
    monkeypatch.setattr(C.os, "getpriority", lambda which, pid: 10 if pid == 2 else 0, raising=False)
    monkeypatch.setattr(C.os, "PRIO_PROCESS", 0, raising=False)
    C._keeper.clear()
    import threading
    done = threading.Event()

    def record(pids, background):
        placed.append((pids, background))
        if len(placed) >= 2:
            done.set()
        return 0
    monkeypatch.setattr(C, "hold", record)
    C.ensure_keeper(lambda: [1, 2], period=0.01)
    assert done.wait(2)
    assert ([1], False) in placed and ([2], True) in placed
    C._keeper["roots"] = lambda: []                       # the daemon idles for the rest of the run


def test_hold_puts_back_only_the_threads_the_emulator_re_pinned(monkeypatch):
    """Live 2026-11-10: Eden re-pinned all its threads to 10-19 within 12 s of a placement (new threads at a stage
    load). The hold rewrites just the threads whose mask is wrong, in process, every KEEP_S (2 s)."""
    monkeypatch.setattr(C, "fast_cores", lambda: "5-9,15-19")
    monkeypatch.setattr(C, "slow_cores", lambda: "0-4,10-14")
    monkeypatch.setattr(C.shutil, "which", lambda name: None)          # no ionice here
    masks = {101: set(range(10, 20)), 102: set(C._expand("5-9,15-19")), 103: set(range(10, 20))}
    monkeypatch.setattr(C, "_tids", lambda pid: list(masks))
    monkeypatch.setattr(C.os, "sched_getaffinity", lambda tid: masks[tid], raising=False)
    set_calls = []

    def setaff(tid, cpus):
        set_calls.append(tid)
        masks[tid] = set(cpus)
    monkeypatch.setattr(C.os, "sched_setaffinity", setaff, raising=False)
    assert C.hold([7], background=False) == 2 and sorted(set_calls) == [101, 103]
    assert all(m == set(C._expand("5-9,15-19")) for m in masks.values())
    assert C.hold([7], background=False) == 0, "nothing to put back"
    assert C.KEEP_S <= 2.0


def test_place_never_raises(monkeypatch):
    monkeypatch.setattr(C, "fast_cores", lambda: "5-9")
    monkeypatch.setattr(C, "slow_cores", lambda: "0-4")
    monkeypatch.setattr(C.shutil, "which", lambda name: "/usr/bin/" + name)

    def boom(*a, **k):
        raise OSError("no such process")
    monkeypatch.setattr(subprocess, "run", boom)
    C.place([99999], background=True)
