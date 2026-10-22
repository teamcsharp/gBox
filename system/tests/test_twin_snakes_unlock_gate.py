from types import SimpleNamespace
from gbox import game_unlocks as G, twin_snakes_unlock as T

TS = {'game_id': T.GAME_ID, 'platform': T.PLATFORM}


def test_gate_pending_and_unverified():
    p = G.profile_for(TS)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert 'owned_executable_sha256' in p['requires']
    assert set(p['inventory']) == set(T.CATEGORIES)
    assert all(v['state'] == 'unknown' for v in p['inventory'].values())


def test_pre_launch_and_plan_reach_no_writer():
    r = G.pre_launch(TS, SimpleNamespace())
    assert r['applied'] is False and r['state'] == 'research_pending'
    plan = G.launch_plan(TS, {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}, enable_unlock=True, allow_save_upgrade=True)
    assert plan['status'] == 'unsupported_unlock' and plan['jobs'] == []


def test_other_discs_and_titles_not_matched():
    for g in ({'title': T.TITLE}, {'game_id': T.GAME_ID, 'platform': 'wii'},
              {'game_id': '79965f951e479d2b', 'platform': 'gamecube'}):
        assert G.profile_for(g)['verified'] is False
        assert G.profile_for(g).get('game_id') != T.GAME_ID


def test_no_addresses_staged():
    assert '0x' not in repr(T.profile_gate()).lower()
