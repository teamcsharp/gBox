"""#1506 "why does it take so long to load a game": the cache staging of a launch.

Measured on the operator's PC (JAYBUILTFINALE, Wi-Fi to the library NAS, cache on an 8 TB HDD): every launch of a
cached game re-read the whole file for its SHA-1 (147 MiB/s: ~51 s for Metroid: Other M's 7.4 GB), a first copy ran
at ~9.5 MB/s (read 8 MiB, write it, read the next) and then re-read the copy for the hash; the Metroid launch was
still copying after 9 minutes when the app gave up."""
import hashlib
import json
import os
import sys
import threading
import time

import pytest

from gbox import catalog, tools
from gbox.config import Config, EmulatorConfig, Library
from gbox.models import CatalogEntry
from gbox.registry import Ctx

BLOCK = 64 << 10


@pytest.fixture(autouse=True)
def small_blocks(monkeypatch):
    monkeypatch.setattr(catalog, "STAGE_BLOCK", BLOCK)
    monkeypatch.setattr(catalog, "_COPIES", {})


def cfg_for(tmp_path, **kw):
    return Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c", **kw)


def disc(tmp_path, name="game.iso", size=BLOCK * 10 + 123):
    p = tmp_path / "share" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(os.urandom(size))
    return p


def count_hashes(monkeypatch):
    calls = []
    real = catalog.file_hashes
    monkeypatch.setattr(catalog, "file_hashes", lambda path, cache: calls.append(str(path)) or real(path, cache))
    return calls


def test_relaunch_never_rereads_the_cached_file(tmp_path, monkeypatch):
    cfg, src = cfg_for(tmp_path), disc(tmp_path)
    calls = count_hashes(monkeypatch)
    first = catalog.stage(src, "g", cfg)
    assert first["copied"] and first["sha1"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert calls == []                                       # hashed while copying, not by a second full read
    for _ in range(3):
        again = catalog.stage(src, "g", cfg)
        assert again["copied"] is False and again["hashed"] is False and again["sha1"] == first["sha1"]
    assert calls == []


def test_cached_file_from_before_the_db_is_hashed_once(tmp_path, monkeypatch):
    cfg, src = cfg_for(tmp_path), disc(tmp_path)
    dst = cfg.cache / "g" / src.name
    dst.parent.mkdir(parents=True)
    dst.write_bytes(src.read_bytes())                        # staged by the old code: no db record
    calls = count_hashes(monkeypatch)
    assert catalog.stage(src, "g", cfg)["hashed"] is True
    assert catalog.stage(src, "g", cfg)["hashed"] is False and len(calls) == 1


def test_changed_source_or_changed_copy_is_not_trusted(tmp_path, monkeypatch):
    cfg, src = cfg_for(tmp_path), disc(tmp_path)
    catalog.stage(src, "g", cfg)
    data = bytearray(src.read_bytes())
    data[5] ^= 0xFF
    src.write_bytes(bytes(data))                             # same size, new content
    os.utime(src, ns=(time.time_ns(), time.time_ns() + 10**9))
    r = catalog.stage(src, "g", cfg)
    assert r["copied"] is True and r["sha1"] == hashlib.sha1(bytes(data)).hexdigest()
    dst = cfg.cache / "g" / src.name
    with open(dst, "r+b") as f:                              # something wrote into the cached copy
        f.write(b"x")
    os.utime(dst, ns=(time.time_ns(), time.time_ns() + 2 * 10**9))
    assert catalog.stage(src, "g", cfg)["hashed"] is True    # its mtime moved: hashed again, not trusted


def test_interrupted_copy_resumes(tmp_path):
    cfg, src = cfg_for(tmp_path), disc(tmp_path)
    dst = cfg.cache / "g" / src.name
    dst.parent.mkdir(parents=True)
    part = dst.with_name(dst.name + ".part")
    part.write_bytes(src.read_bytes()[:BLOCK * 3 + 77])      # the worker restarted mid-copy
    catalog._db_set(cfg.cache, str(part), {"src": catalog._ident(src.stat())})
    r = catalog.stage(src, "g", cfg)
    assert r["resumed_from"] == BLOCK * 3
    assert dst.read_bytes() == src.read_bytes() and r["sha1"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert not part.exists()


def test_reads_run_ahead_in_parallel(tmp_path, monkeypatch):
    src = disc(tmp_path, size=BLOCK * 12)
    live, peak, lock = [0], [0], threading.Lock()
    real_open = open

    class Slow:
        def __init__(self, f):
            self.f = f
        def seek(self, off):
            self.f.seek(off)
        def read(self, n):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)                                 # a share round trip
            with lock:
                live[0] -= 1
            return self.f.read(n)
        def close(self):
            self.f.close()
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: Slow(real_open(p, *a, **k)) if str(p) == str(src) else real_open(p, *a, **k))
    t = time.monotonic()
    data = b"".join(catalog._read_ahead(src, 0, src.stat().st_size, streams=4, block=BLOCK))
    took = time.monotonic() - t
    monkeypatch.undo()
    assert data == src.read_bytes() and peak[0] >= 3 and took < 12 * 0.05 * 0.6


def test_slow_copy_plays_from_the_share_and_finishes_in_the_background(tmp_path, monkeypatch):
    cfg, src = cfg_for(tmp_path, stage_wait_s=1.0, stage_background_mb_s=0), disc(tmp_path, size=BLOCK * 40)
    real = catalog._read_ahead

    def slow(*a, **k):
        for chunk in real(*a, **k):
            time.sleep(0.06)                                 # ~1 MB/s: 2.6 MB would take ~2.4 s > the 1 s budget
            yield chunk
    monkeypatch.setattr(catalog, "_read_ahead", slow)
    game = CatalogEntry(game_id="g", title="Big", platform="wii", source_paths=[], hashes={}, size=0, format="iso", runtimes={}, profile_id="g")
    progress = []
    ctx = Ctx(cfg, job_id="j", worker="w")
    ctx.progress = lambda pct, msg: progress.append(msg)
    t = time.monotonic()
    r = tools._stage_for_launch(src, game, ctx)
    assert r["background"] is True and r["dst"] is None and time.monotonic() - t < 2.0
    assert any("s left" in m for m in progress)
    copy = catalog._COPIES[str(cfg.cache / "g" / src.name)]
    assert catalog.stage_begin(src, "g", cfg) is copy        # a relaunch meanwhile joins the same copy
    done = copy.result()
    assert done["copied"] and (cfg.cache / "g" / src.name).read_bytes() == src.read_bytes()
    assert catalog.stage(src, "g", cfg)["copied"] is False   # the next launch is local
    must = tools._stage_for_launch(src, game, ctx, must_wait=True)
    assert must["dst"] == str(cfg.cache / "g" / src.name)


def test_background_copy_slows_down_while_a_game_plays(tmp_path, monkeypatch):
    cfg, src = cfg_for(tmp_path), disc(tmp_path, size=BLOCK * 8)
    copy = catalog.StageCopy(src, cfg.cache / "g" / src.name, cfg)
    copy.limit = lambda: BLOCK * 4                           # bytes/s while a session runs
    t = time.monotonic()
    copy.thread.start()
    copy.result()
    assert time.monotonic() - t >= 1.4                       # 8 blocks at 4 blocks/s


def test_launch_reports_where_its_time_went(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, stage_min_mb=0)
    cfg.libraries.append(Library(id="lib", kind="files", paths={"windows": str(tmp_path / "share"), "linux": str(tmp_path / "share")}))
    cfg.emulators["wii"] = EmulatorConfig(adapter="command", executable=sys.executable,
                                          args=["-c", "import time; time.sleep(30)", "{rom}"])
    src = disc(tmp_path)
    game = CatalogEntry(game_id="g", title="Big", platform="wii", source_paths=[src.name], library="lib", rel_path=src.name,
                        hashes={}, size=src.stat().st_size, format="iso", runtimes={}, profile_id="g")
    monkeypatch.setattr(tools, "SESSIONS", {})
    monkeypatch.setattr(tools, "track_emulator", lambda *a, **k: None)
    out = tools._launch_game(tools.LaunchIn(game=game), Ctx(cfg, job_id="j1", worker="w1"))
    try:
        t = out["detail"]["timings"]
        assert {"runtime_s", "rom_s", "mod_s", "stage_s", "close_previous_s", "emulator_start_s", "total_s"} <= set(t)
        assert out["detail"]["staging"]["copied"] is True
        assert t["total_s"] >= t["stage_s"]
        stopped = tools.session_op(tools.SessionIn(session_id=out["session_id"], op="stop_game"), Ctx(cfg, job_id="s", worker="w1"))
        assert stopped["ended"] and stopped["result"]["timings"]["kill_s"] < 2
        again = tools._launch_game(tools.LaunchIn(game=game), Ctx(cfg, job_id="j2", worker="w1"))
        staging = again["detail"]["staging"]
        assert staging["copied"] is False and staging["hashed"] is False and staging["size"] == src.stat().st_size
    finally:
        for sid in list(tools.SESSIONS):
            tools.session_op(tools.SessionIn(session_id=sid, op="stop_game"), Ctx(cfg, job_id="s2", worker="w1"))


def test_complete_local_build_launch_never_probes_the_base_share(tmp_path, monkeypatch):
    """Local build works with its original library offline; no network stat or download."""
    from gbox import filemods
    cfg = cfg_for(tmp_path)
    cfg.libraries.append(Library(id="lib", paths={"windows": str(tmp_path / "offline"), "linux": str(tmp_path / "offline")}))
    cfg.emulators["dreamcast"] = EmulatorConfig(adapter="command", executable=sys.executable,
                                                args=["-c", "import time; time.sleep(30)", "{rom}"])
    game = CatalogEntry(game_id="g", title="Local game", platform="dreamcast", library="lib", rel_path="base.chd",
                        source_paths=[], hashes={}, size=0, format="chd", runtimes={}, profile_id="g")
    folder = filemods.mod_dir(cfg, "g", "custom")
    folder.mkdir(parents=True)
    image = folder / "custom.gdi"
    image.write_text("fixture")
    (folder / ".gbox-mod.json").write_text(json.dumps({"image": image.name}))
    real_stat = type(image).stat

    def stat(path, *args, **kw):
        if "offline" in path.parts:
            pytest.fail("complete local build probed the network library")
        return real_stat(path, *args, **kw)

    monkeypatch.setattr(type(image), "stat", stat)
    monkeypatch.setattr(tools, "SESSIONS", {})
    monkeypatch.setattr(tools, "track_emulator", lambda *a, **kw: None)
    monkeypatch.setattr(filemods, "stage", lambda *a, **kw: pytest.fail("downloaded a complete local build"))
    try:
        out = tools._launch_game(tools.LaunchIn(game=game, mod="custom"), Ctx(cfg, job_id="local", worker="test"))
        assert tools.SESSIONS[out["session_id"]][1]["_rom_path"] == str(image)
        assert out["detail"]["mod"] == "custom"
    finally:
        for sid in list(tools.SESSIONS):
            tools.session_op(tools.SessionIn(session_id=sid, op="stop_game"), Ctx(cfg, job_id="stop", worker="test"))
