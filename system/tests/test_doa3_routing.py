"""DOA3 cast writer routing: discoverable through writer_for, honest, never fabricates a build."""
from gbox import char_coverage as CC
from gbox import doa3_cast
from gbox.doa3_inventory import GAME_ID

GAME = {"game_id": GAME_ID, "title": "Dead or Alive 3 (USA)", "platform": "xbox"}


class _Inp:
    def __init__(self, slot):
        self.slot = slot


def test_writer_for_routes_doa3():
    w = CC.writer_for(GAME)
    assert w is not None, "DOA3 must resolve a writer now that doa3_cast is registered"
    assert w["writer"] == "gbox.doa3_cast"
    assert w["routed"] is True, "characters_tool must call doa3_cast.use for the writer to count as routed"


def test_writer_status_honest_not_playable():
    st = doa3_cast.cast_writer_status()
    assert st["afs_patch_path"] is True
    assert st["donor_retarget"] is False
    assert st["playable"] is False


def test_is_slot():
    assert doa3_cast.is_slot("cast") is True
    assert doa3_cast.is_slot("fighter:kasumi") is True
    assert doa3_cast.is_slot("fighter:kasumi:02") is True
    assert doa3_cast.is_slot("player") is False
    assert doa3_cast.is_slot("") is False
    assert doa3_cast.is_slot(None) is False


def test_use_reports_in_progress_without_a_build():
    r = doa3_cast.use(None, {"name": "x", "slug": "x"}, GAME, _Inp("cast"))
    assert r["status"] == "writer_in_progress"
    assert r["writer"] == "gbox.doa3_cast"
    assert r["playable"] is False
    assert r["donor_retarget"] is False
    assert r.get("mod") is None, "a non-playable writer must never fabricate a mod"


def test_cast_swap_whole_cast_is_honestly_unsupported():
    from gbox import cast_swap
    p = cast_swap.plan(GAME, [], "sonic,mario", mapping="alternate")
    # single-slot strategy: the whole-cast request is refused with a precise reason, not a blanket
    # "no routed character writer" and never a build.
    assert p["status"] == "unsupported_cast"
    assert p["writer"] == "gbox.doa3_cast"
    assert p.get("mod") is None
