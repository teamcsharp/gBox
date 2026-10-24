"""#2203: Nintendogs candidate codes decode for nds but are not applied until runtime-verified."""
from gbox import cheats as C, game_unlocks as U
from gbox.nds_nintendogs_candidate import CANDIDATE

GAME = {"game_id": "53a70492655203c9", "title": "Nintendogs - Dalmatian & Friends (USA)", "platform": "nds"}


def test_candidate_codes_decode_for_nds():
    assert CANDIDATE["platform"] == "nds" and CANDIDATE["game_id"] == GAME["game_id"]
    for entry in CANDIDATE["codes"]:
        ops, bad = C.decode("nds", "\n".join(entry["lines"]))
        assert ops and not bad


def test_candidate_is_unverified_and_not_applied():
    assert CANDIDATE["verified"] is False
    assert U.code_profile(GAME) is None
