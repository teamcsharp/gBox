"""The model-swap readers must accept the archives used by catalog games."""
import shutil
import subprocess
import zipfile

import pytest

from gbox import n64_rom


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
