from types import SimpleNamespace

from gbox import game_unlocks as G, sshuffle_unlock as S

SS = {'game_id': S.GAME_ID, 'platform': S.PLATFORM}


def test_gate_pending_and_pinned():
    p = G.profile_for(SS)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert 'native_unlock_routine' in p['requires'] and len(p['known_roster_unverified_lock_state']) == 8
    assert '0x' not in repr(S.profile_gate()).lower()


def test_no_writer_reachable():
    r = G.pre_launch(SS, SimpleNamespace())
    assert r['applied'] is False and r['state'] == 'research_pending'
    plan = G.launch_plan(SS, {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}, enable_unlock=True, allow_save_upgrade=True)
    assert plan['jobs'] == [] and plan['executed'] is False


def test_identity_not_bypassed_by_title():
    for g in ({'title': 'Sonic Shuffle (USA)'}, {'game_id': S.GAME_ID, 'platform': 'xbox360'}):
        assert G.profile_for(g)['verified'] is False
        assert G.profile_for(g)['status'] != 'pending_research'
