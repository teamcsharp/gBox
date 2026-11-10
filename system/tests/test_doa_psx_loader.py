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


BIN = os.environ.get("DOA_PSX_BIN", "/home/ehm_eckx/gBox_alt/gbox-cache/5b699968cf37a8ac/PS_DOA.BIN")


def test_msf_decode():
    assert L.msf_ref_to_sector(0x730200) == 223
    assert L.msf_ref_to_sector(0x000001) == 4500 and L.msf_ref_to_sector(0x655800) == 4415


def test_table_contiguous_on_disc():
    if not os.path.exists(BIN):
        pytest.skip("owned PS_DOA.BIN not present")
    with open(BIN, "rb") as f:
        head = f.read(4096)
        f.seek(0, 2)
        total = f.tell() // 2048
    t = L.parse_asset_table(head)
    assert len(t) == 338
    exp = 0
    for i, size, sec, _ in t:
        assert sec == exp, i
        exp = sec + (size + 0x7FF) // 2048
    assert exp == 22661 and total - exp == 2
    assert t[1][1:3] == (10608, 223) and t[85][1:3] == (173412, 4500)
