import os
import pytest
from gbox.cvx_system_models import classify, mdl_runs

def test_classify():
    assert classify(b"\x00\x00\x04\xa8MDL\xbc\x00\x10\x00\x02") == "mdl"
    assert classify(b"TPVR\x00\x08\x00\x20") == "TPVR"
    assert classify(b"\x00\x00\xb4\x64\x00\x00\x0c\x38SKIN") == "skin"
    assert classify(b"dummy_data") == "other"

def test_runs_split_on_gap():
    e = [(1, "mdl", 10), (2, "TPVR", 5), (20, "mdl", 3), (21, "mdl", 4), (22, "skin", 1), (50, "mdl", 2)]
    assert mdl_runs(e) == [(1, 1, 1, 10), (20, 21, 2, 7), (50, 50, 1, 2)]

def test_owned_disc_runs():
    from gbox.cvx_inventory import SOURCE_PATH
    if not os.path.exists(SOURCE_PATH):
        pytest.skip("owned disc not mounted")
    from gbox.gcdisc import GCDisc
    from gbox.cvx_system_models import census
    runs = mdl_runs(census(GCDisc(SOURCE_PATH)))
    assert [(r[0], r[1]) for r in runs if r[2] > 3] == [(20, 40), (50, 70), (80, 99), (110, 130)]
