import os
import pytest

from gbox import tetris_psp_inventory as m

SRC = os.environ.get(
    "TETRIS_PSP_CSO",
    "/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Minis/roms/Tetris (USA).cso",
)
SHA = "b0afb70a682c11c56f7660d39ea1224950b0b3eb33f2686970da5870bfa61bf2"
pytestmark = pytest.mark.skipif(not os.path.exists(SRC), reason="owned Tetris CSO not present")


@pytest.fixture(scope="module")
def inv():
    return m.inventory(SRC)


def test_source_hash():
    assert m.sha256_file(SRC) == SHA


def test_container(inv):
    assert inv["container"] == "CISO"
    assert inv["block_size"] == 2048
    assert inv["uncompressed_bytes"] == 0x0A238000
    assert inv["index_entries"] == 83057


def test_sfo(inv):
    assert inv["param_sfo"]["DISC_ID"] == "NPUZ00003"
    assert inv["param_sfo"]["TITLE"] == "Tetris"
    assert inv["param_sfo"]["CATEGORY"] == "UG"


def test_eboot_encrypted(inv):
    assert inv["eboot"]["path"] == "/PSP_GAME/SYSDIR/EBOOT.BIN"
    assert inv["eboot"]["magic"] == "7e505350"  # ~PSP: encrypted, not directly loadable by Ghidra
    assert inv["eboot"]["size"] == 3032768


def test_file_counts(inv):
    assert inv["file_count"] == 199
    exts = {}
    for p, _, _ in inv["files"]:
        exts[p.rsplit(".", 1)[-1]] = exts.get(p.rsplit(".", 1)[-1], 0) + 1
    assert exts["PSP"] == 186 and exts["SBK"] == 1 and exts["STR"] == 1


def test_target_asset():
    t = m.identify_target(SRC)
    assert t["path"] == m.TARGET_ASSET
    assert t["size"] == 7312512
    assert t["lu_magic_ok"]
    assert t["names"][:2] == ["global", "tetris"]
    assert len(t["sha256"]) == 64


def test_reader_bad_magic(tmp_path):
    p = tmp_path / "x.cso"
    p.write_bytes(b"XXXX" + b"\0" * 64)
    with pytest.raises(ValueError):
        m.CisoReader(str(p))
