"""Focused tests for tetris_psp_eboot against the owned Tetris (USA) CSO."""
import os
import pytest

from gbox.tetris_psp_eboot import BODY_OFFSET, extract_eboot, eboot_report

ROM = os.environ.get(
    "TETRIS_PSP_ROM",
    "/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Minis/roms/Tetris (USA).cso",
)
pytestmark = pytest.mark.skipif(
    not os.path.exists(ROM), reason="owned Tetris (USA) CSO not present"
)

EBOOT_SHA256 = "77f733ee047229ed40a5e5da90d51ce9e5fb5d9afff4487e3b7c7f9d58fcf701"


@pytest.fixture(scope="module")
def report():
    return eboot_report(ROM)


def test_eboot_identity(report):
    assert report["path"] == "/PSP_GAME/SYSDIR/EBOOT.BIN"
    assert report["lba"] == 224
    assert report["size"] == 3032768
    assert report["sha256"] == EBOOT_SHA256


def test_psp_v2_header_fields(report):
    assert report["magic"] == "~PSP"
    assert report["name"] == "simple"
    assert report["segments"] == 1
    assert report["elf_size"] == 3032424
    assert report["file_size"] == 3032768
    assert report["decrypt_mode"] == 9
    assert report["tag"] == 0xD9160AF0
    assert report["entry"] == 0x8AAC81C
    assert report["seg_addrs"][0] == 0x8900000
    assert report["seg_sizes"][0] == 0x27E100
    assert report["file_size"] == report["size"]
    assert report["size"] - BODY_OFFSET >= report["elf_size"]


def test_body_is_kirk_encrypted(report):
    data = extract_eboot(ROM)
    assert len(data) == report["size"]
    assert data[:4] == b"~PSP"
    assert b"\x7fELF" not in data[:0x1000]
    assert report["body_is_plaintext_elf"] is False
