import os
import pytest
from gbox import puyotetris_inventory as pi
from gbox.formats import nitro

ROOT = "/mnt/gbox/quickswap2/Emulation/PS3/Puyo Puyo Tetris (Japan)/PS3_GAME/USRDIR/data"


def test_synthetic_narc_census(tmp_path):
    p = tmp_path / "a.narc"
    p.write_bytes(nitro.build_narc({"x": b"NCIF" + b"\0" * 20, "y": b"SWIF" + b"\0" * 8, "z": b"????abcd"}))
    c = pi.narc_census(p)
    assert c["members"] == 3 and c["classes"] == {"ncif": 1, "swif": 1, "other": 1}


@pytest.mark.skipif(not os.path.isdir(ROOT), reason="owned build not mounted")
def test_owned_character_narcs():
    c = pi.narc_census(ROOT + "/character_demo/character_demo.narc")
    assert c["members"] == 37 and c["classes"] == {"ncif": 29, "raw02": 8}
    a = pi.narc_census(ROOT + "/adventure/adv_character/surfboard/adv_character.narc")
    assert a["members"] == 2 and a["classes"] == {"swif": 1, "raw02": 1}


@pytest.mark.skipif(not os.path.isdir(ROOT), reason="owned build not mounted")
def test_owned_tree_parse():
    t = pi.tree_census(ROOT)
    assert t["parsed"] == 557 and len(t["failed"]) == 1 and t["members"] == 6579
