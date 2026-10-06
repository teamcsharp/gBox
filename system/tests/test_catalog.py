import os
import struct

from conftest import run_job
from gbox import catalog
from gbox.config import Config


def ip_bin(title=b"PHANTASY STAR ONLINE VER.2", serial=b"MK-51166"):
    ip = bytearray(b" " * 0x100)
    ip[0:16] = b"SEGA SEGAKATANA "
    ip[0x30:0x38] = b"JUE     "
    ip[0x40:0x40 + len(serial)] = serial
    ip[0x80:0x80 + len(title)] = title
    return bytes(ip)


def make_library(root):
    (root / "nes").mkdir(parents=True)
    (root / "nes" / "Test Game (USA).nes").write_bytes(b"NES\x1a" + bytes(40000))
    dc = root / "dc" / "pso2"
    dc.mkdir(parents=True)
    (dc / "track01.bin").write_bytes(bytes(0x10) + ip_bin() + bytes(0x20000))
    (dc / "track02.raw").write_bytes(bytes(1000))
    (dc / "track03.bin").write_bytes(b"\x01" * 0x30000)
    (dc / "disc.gdi").write_text("3\n1 0 4 2352 track01.bin 0\n2 600 0 2352 track02.raw 0\n3 45000 4 2352 track03.bin 0\n")
    gc = bytearray(0x50000)
    gc[0:6], gc[0x1C:0x20], gc[0x20:0x28] = b"GPOE8P", b"\xc2\x33\x9f\x3d", b"PSO EP12"
    (root / "Some GC Game (Europe).iso").write_bytes(gc)
    ps = bytearray(0x50000)
    ps[0x8001:0x8006], ps[0x8008:0x8013] = b"CD001", b"PLAYSTATION"
    (root / "ps1game.iso").write_bytes(ps)
    (root / "copy").mkdir()
    (root / "copy" / "Test Game (USA) [dup].nes").write_bytes(b"NES\x1a" + bytes(40000))
    (root / "mystery.bin").write_bytes(bytes(0x50000))
    (root / "readme.txt").write_text("ignored")


def test_scan_detects_dedupes_readonly(tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    before = {p: p.stat().st_mtime_ns for p in lib.rglob("*")}
    entries, problems = catalog.scan([lib, tmp_path / "missing"], {"dreamcast": "configured"})
    by = {e.platform: e for e in entries}
    assert set(by) == {"nes", "dreamcast", "gamecube", "ps1", "unknown"}
    dc = by["dreamcast"]
    assert dc.platform_confidence == "header" and dc.serial == "MK-51166" and "PHANTASY" in dc.alt_title
    assert dc.runtimes == {"dreamcast": "configured"} and dc.format == "gdi"
    assert by["gamecube"].serial == "GPOE8P" and by["gamecube"].region == "EU"
    assert len(by["nes"].source_paths) == 2 and by["nes"].title == "Test Game" and by["nes"].region == "US"
    assert any("not reachable" in p for p in problems) and any("mystery.bin" in p for p in problems)
    assert before == {p: p.stat().st_mtime_ns for p in lib.rglob("*")}   # originals untouched


def test_hash_cache_reused(tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    cache = {}
    catalog.scan([lib], {}, cache)
    n = len(cache)
    catalog.scan([lib], {}, cache)
    assert len(cache) == n > 0


def test_steam(tmp_path):
    root = tmp_path / "steam"
    (root / "steamapps").mkdir(parents=True)
    lib2 = tmp_path / "lib2" / "steamapps"
    lib2.mkdir(parents=True)
    path2 = str(tmp_path / "lib2").replace("\\", "\\\\")
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "0"\n {{\n  "path" "{path2}"\n  "apps" {{ "70" "123" }}\n }}\n}}\n')
    (lib2 / "appmanifest_70.acf").write_text('"AppState"\n{\n "appid" "70"\n "name" "Half-Life"\n "installdir" "Half-Life"\n "buildid" "42"\n}\n')
    entries, problems = catalog.scan_steam(root)
    assert not problems and len(entries) == 1
    e = entries[0]
    assert e.game_id == "steam-70" and e.title == "Half-Life" and e.launch == {"kind": "steam", "appid": "70"}


def test_stage_lru(tmp_path):
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c", cache_limit_gb=250_000 / 1024**3)
    srcs = []
    for i in range(3):
        p = tmp_path / f"g{i}.bin"
        p.write_bytes(bytes([i]) * 100_000)
        srcs.append(p)
    r0 = catalog.stage(srcs[0], "g0", cfg)
    os.utime(r0["dst"], (1, 1))                       # make g0 the least recently used
    catalog.stage(srcs[1], "g1", cfg)
    r2 = catalog.stage(srcs[2], "g2", cfg)
    assert r2["evicted"] == [r0["dst"]] and srcs[0].exists()
    assert r2["sha1"] == catalog.file_hashes(srcs[2], {})["sha1"]


def test_scan_job_ingests_catalog_and_profiles(plane, tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    job = run_job(plane, "scan_library", {"roots": [str(lib)], "include_steam": False})
    assert job["state"] == "succeeded", job
    games = plane.get("/api/catalog", params={"platform": "dreamcast"}).json()["items"]
    assert len(games) == 1
    prof = plane.get(f"/api/profiles/{games[0]['game_id']}").json()
    assert prof["platform"] == "dreamcast" and prof["catalog"]["serial"] == "MK-51166"
    assert plane.get("/api/catalog", params={"q": "test game"}).json()["total"] == 1
