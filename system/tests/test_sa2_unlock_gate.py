from types import SimpleNamespace

from gbox import game_unlocks as G, sa2_unlock as S

SA2 = {'game_id': S.GAME_ID, 'platform': S.PLATFORM}


def test_sa2_gate_pending_never_verified_and_covers_all_categories():
    p = G.profile_for(SA2)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert set(p['inventory']) == set(S.CATEGORIES)
    assert all(e['status'] in {'unlocked', 'not_present', 'unknown', 'mechanism_known'} and e['evidence']
               for v in p['inventory'].values() for e in v)
    assert p['executable']['sha1'] == '0817898aac799a8de5e8a9021d817bd7ef33a9e3'


def test_sa2_pre_launch_and_plan_reach_no_writer():
    r = G.pre_launch(SA2, SimpleNamespace())
    assert r['applied'] is False and r['state'] == 'research_pending'
    plan = G.launch_plan(SA2, {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}, enable_unlock=True, allow_save_upgrade=True)
    assert plan['status'] == 'unsupported_unlock' and plan['jobs'] == []


def test_sa2_gate_not_selected_by_title_or_other_platform():
    for g in ({'title': 'Sonic Adventure 2 (USA)'}, {'game_id': S.GAME_ID, 'platform': 'gamecube'},
              {'game_id': S.GAME_ID[:-1] + '0', 'platform': 'dreamcast'}):
        assert G.profile_for(g)['verified'] is False
        assert G.profile_for(g).get('status') != 'pending_research' or g.get('platform') == 'dreamcast' and g['game_id'] == S.GAME_ID
