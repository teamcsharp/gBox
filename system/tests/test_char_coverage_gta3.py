"""char_coverage registration for the GTA III PS2 writer (gbox/gta3_swap.py, PR #49): the writer module must be
listed in WRITERS and GTA III must not appear in DISCUSSED once a writer exists. The module itself lands with the
writer PR; these checks guard the coverage side so the matrix reports the writer the moment gta3_swap imports."""
from gbox import char_coverage as CC


def test_gta3_swap_registered_as_player_writer():
    row = next((r for r in CC.WRITERS if r[0] == "gta3_swap"), None)
    assert row is not None, "gta3_swap missing from char_coverage.WRITERS"
    assert row[1] == ["player"]


def test_gta3_not_listed_as_no_writer_game():
    assert ("Grand Theft Auto III", "ps2") not in CC.DISCUSSED
