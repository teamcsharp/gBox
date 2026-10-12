"""The model-swap readers must accept the archives used by catalog games."""
import shutil
import subprocess
import zipfile

import pytest

from gbox import n64_rom


@pytest.fixture(autouse=True)
def _private_cache(tmp_path, monkeypatch):
    monkeypatch.setenv(n64_rom.CACHE_ENV, str(tmp_path / "romcache"))


Z64 = b"\x80\x37\x12\x40" + b"test"
V64 = b"\x37\x80\x40\x12" + b"etts"
N64 = b"\x40\x12\x37\x80" + b"tset"


@pytest.mark.parametrize("source", [Z64, V64, N64])
def test_normalize_n64_byte_orders(source):
    assert n64_rom.normalize(source) == Z64


def test_reads_nested_zip_rom(tmp_path):
    path = tmp_path / "game.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "not a ROM")
        archive.writestr("nested/game.n64", V64)
    assert n64_rom.read(path) == Z64


def test_reads_7z_rom(tmp_path):
    exe = next((p for name in ("7z", "7zz", "7zr") if (p := shutil.which(name))), None)
    if not exe:
        pytest.skip("7-Zip is not installed on this test host")
    rom = tmp_path / "game.n64"
    rom.write_bytes(V64)
    archive = tmp_path / "game.7z"
    subprocess.run([exe, "a", str(archive), str(rom)], check=True, capture_output=True)
    assert n64_rom.read(archive) == Z64


def test_archive_rom_is_cached_and_reused(tmp_path, monkeypatch):
    path = tmp_path / "game.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("game.n64", N64)
    assert n64_rom.read(path) == Z64
    cached = list((tmp_path / "romcache").glob("*.z64"))
    assert [c.read_bytes() for c in cached] == [Z64]
    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: pytest.fail("cache hit must not reopen the archive"))
    assert n64_rom.read(path) == Z64


def test_changed_archive_misses_cache(tmp_path):
    path = tmp_path / "game.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("game.z64", Z64)
    assert n64_rom.read(path) == Z64
    other = b"\x80\x37\x12\x40" + b"two!"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("game.z64", other + b"more")
    import os
    os.utime(path, ns=(1, 1))
    assert n64_rom.read(path) == other + b"more"


def test_empty_cache_env_disables_cache(tmp_path, monkeypatch):
    monkeypatch.setenv(n64_rom.CACHE_ENV, "")
    path = tmp_path / "game.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("game.v64", V64)
    assert n64_rom.read(path) == Z64
    assert not (tmp_path / "romcache").exists()


def test_7z_timeout_scales_and_retries_once(tmp_path, monkeypatch):
    """#1053: a stalled share made the fixed 120 s 7-Zip limit fail an OoT swap."""
    archive = tmp_path / "big.7z"
    archive.write_bytes(b"x" * 1024)
    assert n64_rom._7z_timeout(archive) == n64_rom.MIN_7Z_SECONDS
    monkeypatch.setattr(n64_rom, "MIN_7Z_BYTES_PER_SECOND", 1)
    assert n64_rom._7z_timeout(archive) == max(n64_rom.MIN_7Z_SECONDS, 1024)
    monkeypatch.setattr(n64_rom.shutil, "which", lambda name: "/bin/7z" if name == "7z" else None)
    listing = "----------\nPath = big.7z\n\nPath = g.n64\nSize = 8\nFolder = -\n"
    calls = []

    def run(cmd, **kw):
        calls.append((cmd[1], kw.get("timeout")))
        if cmd[1] == "l":
            return subprocess.CompletedProcess(cmd, 0, listing, "")
        if sum(1 for c in calls if c[0] == "x") == 1:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        return subprocess.CompletedProcess(cmd, 0, N64, b"")

    monkeypatch.setattr(n64_rom.subprocess, "run", run)
    assert n64_rom.read(archive) == Z64
    assert [c for c in calls if c[0] == "x"] == [("x", 1024), ("x", 1024)]
