from gbox import ts2_unlock as t, game_unlocks as g

GAME = {'game_id': t.GAME_ID, 'platform': 'gamecube'}


def test_gate_honest():
    gate = t.profile_gate()
    assert gate['verified'] is False and gate['blockers'] and gate['next']


def test_inventory_all_unknown():
    inv = t.inventory()
    assert list(inv) == list(t.CATEGORIES) and len(inv) == 8
    assert all(v['status'] == 'unknown' for v in inv.values())


def test_guard_exact_build_only():
    assert t.revision_guard(t.DOL_SHA256, 'USA') is True
    assert t.revision_guard('0' * 64, 'USA') is False
    assert t.revision_guard(t.DOL_SHA256, 'PAL') is False


def test_pre_launch_never_applies():
    r = g.pre_launch(GAME, None)
    assert r['state'] == 'research_pending' and r['applied'] is False
    assert r['scope'] == list(t.CATEGORIES)
    assert g.profile_for(GAME)['verified'] is False
