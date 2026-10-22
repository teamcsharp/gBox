import re
from pathlib import Path

import pytest

from gbox import melee_inventory as mi

SRC = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Super Smash Bros. Melee (USA).gcz")


def test_costume_regex():
    assert mi.COSTUME_RE.match("PlPeNr.dat").groups() == ("Pe", "Nr")
    assert not mi.COSTUME_RE.match("PlPe.dat")


@pytest.mark.skipif(not SRC.exists(), reason="owned Melee GCZ not mounted")
def test_owned_build_inventory():
    inv = mi.inventory(SRC, hash_source=False)
    assert inv["game_id"] == "GALE01" and inv["fighters_found"] == inv["fighters_table"] == 33
    assert inv["target_slot"]["costume_file_present"]
    assert re.fullmatch(r"[0-9a-f]{64}", inv["main_dol"]["sha256"])
    from gbox.melee_models import load_fighter
    m, bones = load_fighter(SRC, "Peach")
    assert len(m.joints) > 50 and bones
