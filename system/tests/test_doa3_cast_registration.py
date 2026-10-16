"""char_coverage registration for the DOA3 cast writer (gbox.doa3_cast): the decode module is listed in WRITERS
so writer_for() reports its truthful state, but it stays "routed": false until characters.characters_tool
dispatches a use() that can reimport a donor body (donor retarget is not implemented yet). These checks guard
the coverage side so the build matrix reports the exact remaining gap instead of "no writer". """
from gbox import char_coverage as CC
from gbox.doa3_cast import GAME_ID, WRITER_GAME_IDS, cast_writer_status


DOA3 = {"game_id": GAME_ID, "title": "Dead or Alive 3 (USA)", "platform": "xbox"}


def test_doa3_cast_registered_with_writer_game_ids():
    row = next((r for r in CC.WRITERS if r[0] == "doa3_cast"), None)
    assert row is not None, "doa3_cast missing from char_coverage.WRITERS"
    assert WRITER_GAME_IDS == {GAME_ID}
    assert row[1] == ["fighter:<nick>[:<costume>]"]


def test_doa3_writer_recognized_but_not_routed_yet():
    w = CC.writer_for(DOA3)
    assert w is not None, "writer_for() should recognise the doa3_cast decode module"
    assert w["writer"] == "gbox.doa3_cast"
    assert w["routed"] is False, "no use() is dispatched yet, so the cast build must stay un-routed"
    assert CC.cast_slots(DOA3) == [], "decode-only: no routable cast slots yet"


def test_cast_writer_status_reports_the_remaining_gap():
    st = cast_writer_status()
    assert st["game_id"] == GAME_ID
    assert st["donor_retarget"] is False
    assert st["playable"] is False
