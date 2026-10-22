from types import SimpleNamespace
from gbox import game_unlocks as G, pstone2_unlock as P

PS2 = {'game_id': P.GAME_ID, 'platform': P.PLATFORM}


def test_gate_pending_and_unverified():
    p = G.profile_for(PS2)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert p['evidence']['first_read_sha256'] == P.FIRST_READ_SHA256
    assert set(p['categories']) == set(P.CATEGORIES)


def test_no_writer_reachable():
    r = G.pre_launch(PS2, SimpleNamespace())
    assert r['applied'] is False
    plan = G.launch_plan(PS2, {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}, enable_unlock=True, allow_save_upgrade=True)
    assert plan['jobs'] == [] and plan['executed'] is False


def test_other_platform_not_matched():
    assert G.profile_for({'game_id': P.GAME_ID, 'platform': 'psx'})['status'] == 'unsupported'
