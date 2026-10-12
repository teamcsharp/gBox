"""char_coverage registration for the GTA Vice City PS2 writer (gbox/gta_vc_swap.py): the writer module must be
listed in WRITERS and Vice City must not appear in DISCUSSED once a writer exists."""
from gbox import char_coverage as CC


def test_gta_vc_swap_registered_as_player_writer():
    row = next((r for r in CC.WRITERS if r[0] == "gta_vc_swap"), None)
    assert row is not None, "gta_vc_swap missing from char_coverage.WRITERS"
    assert row[1] == ["player"]


def test_gta_vc_not_listed_as_no_writer_game():
    assert ("Grand Theft Auto Vice City", "ps2") not in CC.DISCUSSED


def test_gta_vc_writer_routed_by_title_without_catalog_id():
    # Until the owned disc is scanned, the catalog ID is unknown; coverage should still route by title.
    game = {"game_id": "unknown", "title": "Grand Theft Auto - Vice City", "platform": "ps2"}
    w = CC.writer_for(game)
    assert w is not None, "Vice City should have a writer routed by title"
    assert w["writer"] == "gbox.gta_vc_swap"
    assert w["routed"] is True
    assert w["slots"] == ["player"]
