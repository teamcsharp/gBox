"""char_dat header-variant classification (request #2450). Skipped when owned chara_common.lnk absent."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gbox.doa5lr_char_dat_variants import classify, entry_span, variant_census, variant_census_span  # noqa: E402

LNK = os.environ.get(
    "DOA5LR_CHARA_COMMON",
    "/home/ehm_eckx/gbox-cache/research/doa5lr_samples_2450/extract/"
    "Dead or Alive 5 - Last Round (Japan)/PS3_GAME/USRDIR/chara_common.lnk",
)


def test_classify_synthetic():
    with pytest.raises(ValueError):
        classify(b"notchar_" + bytes(0x100))
    assert classify(b"char_dat" + bytes(0x20)) == "stub"


@pytest.mark.skipif(not os.path.exists(LNK), reason="owned chara_common.lnk not present")
def test_variant_census_owned_source():
    r = variant_census(LNK)
    assert r["counts"] == {"ok_v7": 91, "truncated": 60, "stub": 43, "v6": 41,
                           "ptable2": 15, "reserved_00": 1, "other": 1}
    assert r["members"]["ok_v7"][0] == 18  # target entry 0018 stays in the parsed class
    assert r["members"]["ptable2"][0] == 211
    assert r["members"]["other"] == [642]


@pytest.mark.skipif(not os.path.exists(LNK), reason="owned chara_common.lnk not present")
def test_span_resolves_truncated_entries():
    from gbox.doa5lr_chcm_extract import parse_entries
    es = parse_entries(LNK)
    assert entry_span(es, 26) == (13107200, 0x274800)  # stored size 720, real slot 2,574,336
    r = variant_census_span(LNK)
    # no stub/truncated remain once the slot span is used: all are real v7/v6/ptable2 bodies
    assert r["counts"] == {"ok_v7": 146, "v6": 56, "ptable2": 48, "reserved_00": 1, "other": 1}
