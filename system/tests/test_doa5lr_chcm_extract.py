"""Focused acceptance test for the DOA5LR CHCM character-asset extractor.

    python3 -m pytest tests/test_doa5lr_chcm_extract.py -q

Skipped (not failed) when the owned PS3 source is not mounted.
"""
import hashlib
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "gbox", "doa5lr_chcm_extract.py")
USRDIR = os.environ.get(
    "DOA5LR_USRDIR",
    "/home/ehm_eckx/.hermes/cache/scratch/doa5lr_extracted/"
    "Dead or Alive 5 - Last Round (Japan)/PS3_GAME/USRDIR",
)
LINK = os.path.join(USRDIR, "chara_common.lnk")
INDEX = os.path.join(USRDIR, "chara_common.bin")
EXPECTED_COUNT = 2355
TARGET = 18
EXPECTED_SHA256 = "d0b7226709bdd4c8a266fdc7d4ac140efa1ce6df519ed8967acc47a4235972e6"
EXPECTED_SIZE = 58484
EXPECTED_MAGIC = b"char_dat"


def _module():
    spec = importlib.util.spec_from_file_location("doa5lr_chcm_extract", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pytestmark = pytest.mark.skipif(not os.path.exists(LINK), reason="owned PS3 source not mounted")


def test_header_is_chcm():
    mod = _module()
    header = mod.read_header(LINK)
    assert header["magic"] == b"CHCM"
    assert header["count"] == EXPECTED_COUNT
    assert header["align"] == 2048
    assert header["file_size"] == os.path.getsize(LINK)


def test_reader_matches_direct_struct_parse():
    mod = _module()
    entries = mod.parse_entries(LINK)
    direct = mod._direct_entries(LINK)
    assert len(entries) == len(direct) == EXPECTED_COUNT
    for got, want in zip(entries, direct):
        assert got[0] == want[0] and got[3] == want[3]


def test_lfmo_name_index_agrees_with_chcm_entries():
    mod = _module()
    assert len(mod.parse_names(INDEX)) == EXPECTED_COUNT
    assert len(mod.parse_entries(LINK)) == EXPECTED_COUNT


def test_extract_target_entry_is_byte_exact():
    mod = _module()
    info, payload = mod.extract_entry(TARGET, LINK, INDEX)
    assert info["size"] == EXPECTED_SIZE == len(payload)
    assert info["sha256"] == EXPECTED_SHA256 == hashlib.sha256(payload).hexdigest()
    assert info["magic"] == EXPECTED_MAGIC
    assert info["offset"] % 2048 == 0
    assert info["offset"] + info["size"] <= os.path.getsize(LINK)
    assert info["name"]


def test_entry_lookup_by_name_round_trip():
    mod = _module()
    info, _ = mod.extract_entry(TARGET, LINK, INDEX)
    base = info["name"].split("@")[0].lstrip("/")
    assert mod.entry_by_name(base, LINK, INDEX) == TARGET
