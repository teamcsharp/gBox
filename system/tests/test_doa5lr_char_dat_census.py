"""Census acceptance (request #2450). Skipped when owned chara_common.lnk is absent."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gbox.doa5lr_char_dat_census import census  # noqa: E402

LNK = os.environ.get(
    "DOA5LR_CHARA_COMMON",
    "/home/ehm_eckx/gbox-cache/research/doa5lr_samples_2450/extract/"
    "Dead or Alive 5 - Last Round (Japan)/PS3_GAME/USRDIR/chara_common.lnk",
)


@pytest.mark.skipif(not os.path.exists(LNK), reason="owned chara_common.lnk not present")
def test_census_owned_source():
    r = census(LNK)
    assert r["entries"] == 2355
    assert r["char_dat_tagged"] == r["parsed"] + r["parse_failed"]
    assert r["parsed"] == 91 and r["parse_failed"] == 118
    s = r["sections"]
    # constant sections: nothing character-specific to swap
    assert s[3] == {"distinct_content": 1, "distinct_size": 1}
    assert s[4] == {"distinct_content": 1, "distinct_size": 1}
    # fixed-size but per-character sections: size-invariant swap candidates
    assert s[1]["distinct_size"] == 1 and s[1]["distinct_content"] > 50
    assert s[2]["distinct_size"] == 1 and s[2]["distinct_content"] > 50
    # variable-size sections: need a size-changing writer
    assert s[0]["distinct_size"] > 50 and s[5]["distinct_size"] > 50
