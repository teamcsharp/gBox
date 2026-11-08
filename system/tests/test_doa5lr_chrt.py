"""Focused acceptance test for the DOA5LR CHRT block-table reader (request #2450).

    python3 -m pytest tests/test_doa5lr_chrt.py -q

Pinned against the chara_rtm.lnk sample extracted from the owned
Dead or Alive 5 - Last Round (Japan) PS3 image (gbox-cache research
sample, not part of the repo). Skips when the sample is absent.
"""
import hashlib
import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "gbox", "doa5lr_chrt.py")
SAMPLE = os.environ.get(
    "DOA5LR_CHRT_SAMPLE",
    os.path.join(
        os.path.expanduser("~"),
        "gbox-cache", "research", "doa5lr_samples_2450", "extract",
        "Dead or Alive 5 - Last Round (Japan)", "PS3_GAME", "USRDIR",
        "chara_rtm.lnk",
    ),
)
EXPECTED_FILE_SHA = "b3b2a2c80af74b923c367957714a6de9a747425f40ff6c0620dd2a5d70f7ef0c"
EXPECTED_COUNT = 368
EXPECTED_TOTAL = 0x4BC5000
EXPECTED_BASE = 0x800
EXPECTED_TABLE_END = 0x2E20
BLOCK0 = (0x56F0, 0x3000, "306b764fd78543af7c781a412909e726ce2dfc8fe6a620e88df04879aa58b5a6")
BLOCK1 = (0x194C0, 0x8800, "df44ed75066eac6a99c550e612919f52cf53e4f719555dc974805a21c17247d4")


def _load_module():
    spec = importlib.util.spec_from_file_location("doa5lr_chrt", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chrt = _load_module()


@pytest.fixture(scope="module")
def buf():
    if not os.path.isfile(SAMPLE):
        pytest.skip("chara_rtm.lnk sample not present on this host")
    with open(SAMPLE, "rb") as f:
        data = f.read()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_FILE_SHA
    return data


def test_header_fields(buf):
    count, total, base = chrt.parse_header(buf)
    assert buf[:4] == b"CHRT"
    assert count == EXPECTED_COUNT
    assert total == EXPECTED_TOTAL
    assert base == EXPECTED_BASE
    # NOTE: @0x14 (0x4bc5000) != N - base (0x4bc4800)


def test_table_geometry(buf):
    assert chrt.table_end(buf) == EXPECTED_TABLE_END == 0x20 + EXPECTED_COUNT * 32
    assert chrt.table_end(buf) < len(buf)


def test_all_records_field_consistent(buf):
    rep = chrt.verify(buf)
    assert rep["bad"] == []
    assert rep["records"] == EXPECTED_COUNT
    # overlap pattern: field_a is not a plain byte size
    assert rep["sum_field_a"] > rep["n"]


def test_known_block_hashes(buf):
    for addr, size, sha in (BLOCK0, BLOCK1):
        assert hashlib.sha256(buf[addr:addr + size]).hexdigest() == sha
