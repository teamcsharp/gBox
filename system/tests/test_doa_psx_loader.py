import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gbox import doa_psx_loader as L

EXE = os.environ.get("DOA_PSX_EXE", "/home/ehm_eckx/gBox_alt/gbox-cache/5b699968cf37a8ac/SLUS_006.06")


@pytest.fixture(scope="module")
def img():
    if not os.path.exists(EXE):
        pytest.skip("owned SLUS_006.06 not present")
    data = open(EXE, "rb").read()
    assert L.parse_psx_exe(data)["pc0"] == 0x80010E44
    return L.text_image(data)


def test_path(img):
    assert L.loader_path(img) == b"\\PS_DOA.BIN;1"
    assert img[0x8004C321 - L.TEXT_BASE:].startswith(b"PS_DOA.BIN;1")


def test_only_loader_refs_path(img):
    refs = L.data_refs(img, L.PATH_ADDR)
    assert any(L.LOADER_FUNC <= u < L.LOADER_FUNC + 0xD0 for _, u in refs)
    assert all(0x80010e44 <= u < 0x80010e90 or L.LOADER_FUNC <= u < L.LOADER_FUNC + 0xD0 for _, u in refs)


def test_sectors():
    assert L.sectors_for(46413824) == 22663


def test_state_table(img):
    o = 0x8004C32C - L.TEXT_BASE
    import struct
    vals = struct.unpack_from("<7I", img, o)
    assert vals[1:6] == (0x8004C608, 0x8004C618, 0x8004C670, 0x8004C6DC, 0x8004C728)
