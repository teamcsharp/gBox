"""A cached relaunch takes seconds (JAYBUILTFINALE, 2026-10-13, DOA2 relaunch: runtime_s 7.1, stage_s 7.8,
emulator_start_s 20.4).

- stage: the cached 840 MB CHD was not re-hashed (receipt "hashed": false, 0.42 s): size + mtime in the stage db
  (catalog._reuse, #1506). What remained was the LRU trim walking the cache, now off the launch's path.
- runtime: the BIOS check walked the drive's folder over SMB on every launch (1.4 s warm, 18.7 s cold): remembered per
  emulator version now (provision.runtime_check).
- progress: each progress POST waited 1-3.5 s on the control plane; runtime_s and stage_s were two lines each. A
  launch's Ctx sends them from a background thread (Ctx.nowait).
"""
import threading
import time

import httpx
import pytest

from gbox import catalog, provision
from gbox.config import Config
from gbox.registry import Cancelled, Ctx


# ------------------------------------------------------------------------------------------------ stage skip

def test_cached_file_with_same_size_and_mtime_is_not_rehashed_and_the_trim_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "_COPIES", {})
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    src = tmp_path / "share" / "doa2.chd"
    src.parent.mkdir()
    src.write_bytes(b"x" * 300_000)
    first = catalog.stage(src, "1de2e7634f3161ff", cfg)
    assert first["copied"] is True
    hashed = []
    monkeypatch.setattr(catalog, "file_hashes", lambda p, c: hashed.append(p) or {"sha1": "re-read", "crc32": "0"})
    trims = threading.Event()

    def slow_evict(cache, limit, keep=None):
        time.sleep(1.5)                                        # a cache walk on a slow disk
        trims.set()
        return []
    monkeypatch.setattr(catalog, "evict", slow_evict)
    t = time.monotonic()
    again = catalog.stage(src, "1de2e7634f3161ff", cfg)
    assert time.monotonic() - t < 1.0                          # the trim runs in the background
    assert again["copied"] is False and again["hashed"] is False and again["sha1"] == first["sha1"] and hashed == []
    assert trims.wait(5)


def test_a_changed_cached_file_is_hashed_again(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "_COPIES", {})
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    src = tmp_path / "share" / "g.iso"
    src.parent.mkdir()
    src.write_bytes(b"a" * 200_000)
    dst = catalog.stage(src, "g", cfg)["dst"]
    rec = catalog._db_load(cfg.cache)[dst]
    rec["ident"] = [rec["ident"][0], rec["ident"][1] - 10**9]     # the copy changed since it was hashed (mtime)
    catalog._db_set(cfg.cache, dst, rec)
    assert catalog.stage(src, "g", cfg)["hashed"] is True


# ------------------------------------------------------------------------------------------------ runtime check cache

@pytest.fixture
def rt(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path, runtime_dirs={"windows": str(tmp_path / "rt"), "linux": str(tmp_path / "rt")})
    core = cfg.runtime / "cores" / "flycast_libretro.dll"
    core.parent.mkdir(parents=True)
    core.write_bytes(b"core v1")
    exe = tmp_path / "gBox Game.exe"
    exe.write_bytes(b"MZ v1")
    (cfg.runtime / "system" / "dc").mkdir(parents=True)
    calls, bios = [], []
    monkeypatch.setattr(provision.systems, "core_for", lambda plat: ("flycast", ["dc"]))
    monkeypatch.setattr(provision, "ensure_platform", lambda c, plat, name=None: calls.append(plat) or (core, []))
    monkeypatch.setattr(provision, "ensure_bios", lambda c, names: bios.append(names) or [])
    monkeypatch.setattr(provision, "_RC_REFRESHING", set())
    return cfg, core, exe, calls, bios


def test_runtime_check_is_remembered_per_emulator_version(rt):
    cfg, core, exe, calls, _ = rt
    first = provision.runtime_check(cfg, "dreamcast", None, str(exe))
    assert first["cached"] is False and first["core"] == core and calls == ["dreamcast"]
    for _ in range(3):
        again = provision.runtime_check(cfg, "dreamcast", None, str(exe))
        assert again["cached"] is True and again["core"] == core
    assert calls == ["dreamcast"]                                       # the SMB BIOS walk ran once
    core.write_bytes(b"core v2 (a newer nightly)")                      # new core version: checked again
    assert provision.runtime_check(cfg, "dreamcast", None, str(exe))["cached"] is False
    exe.write_bytes(b"MZ v2, a new RetroArch")                          # new RetroArch: checked again
    assert provision.runtime_check(cfg, "dreamcast", None, str(exe))["cached"] is False
    assert len(calls) == 3
    assert provision.runtime_check(cfg, "dreamcast", None, str(exe))["cached"] is True


def test_runtime_check_redone_when_a_bios_it_found_is_gone(rt):
    cfg, _core, exe, calls, _ = rt
    provision.runtime_check(cfg, "dreamcast", None, str(exe))
    (cfg.runtime / "system" / "dc").rmdir()
    assert provision.runtime_check(cfg, "dreamcast", None, str(exe))["cached"] is False and len(calls) == 2


def test_stale_runtime_check_refreshes_bios_in_the_background(rt, monkeypatch):
    cfg, _core, exe, calls, bios = rt
    provision.runtime_check(cfg, "dreamcast", None, str(exe))
    monkeypatch.setattr(provision, "RUNTIME_RECHECK_S", 0.0)
    out = provision.runtime_check(cfg, "dreamcast", None, str(exe))
    assert out["cached"] is True and len(calls) == 1                   # the launch did not wait for it
    deadline = time.monotonic() + 5
    while not bios and time.monotonic() < deadline:
        time.sleep(0.02)
    assert bios == [["dc"]]


# ------------------------------------------------------------------------------------------------ progress never waits

def test_launch_progress_does_not_wait_on_the_control_plane(tmp_path, monkeypatch):
    sent, gate = [], threading.Event()

    class R:
        def __init__(self, cancel):
            self.cancel = cancel

        def json(self):
            return {"ok": True, "cancel": self.cancel}

    def slow_post(url, json=None, **kw):
        gate.wait(5)                                                    # the server holding its store lock
        sent.append(json["msg"])
        return R(json["msg"] == "cancel me")
    monkeypatch.setattr(httpx, "post", slow_post)
    ctx = Ctx(Config(data_dir=tmp_path), job_id="j1", worker="w")
    ctx.server, ctx.nowait = "http://cp", True
    t = time.monotonic()
    for i in range(5):
        ctx.progress(10 + i, f"line {i}")
    assert time.monotonic() - t < 0.5
    gate.set()
    deadline = time.monotonic() + 5
    while (not sent or sent[-1] != "line 4") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert sent[0] == "line 0" and sent[-1] == "line 4" and len(sent) <= 5   # newest line always arrives
    assert len(ctx.log) == 5                                            # the job's own log keeps every line
    ctx.progress(50, "cancel me")
    deadline = time.monotonic() + 5
    while not getattr(ctx, "_cancel", False) and time.monotonic() < deadline:
        time.sleep(0.02)
    with pytest.raises(Cancelled):
        ctx.progress(51, "next")


def test_other_jobs_keep_the_blocking_progress(tmp_path, monkeypatch):
    sent = []

    class R:
        def json(self):
            return {"ok": True, "cancel": False}
    monkeypatch.setattr(httpx, "post", lambda url, json=None, **kw: sent.append(json["msg"]) or R())
    ctx = Ctx(Config(data_dir=tmp_path), job_id="j2", worker="w")
    ctx.server = "http://cp"
    ctx.progress(1, "a")
    assert sent == ["a"]
