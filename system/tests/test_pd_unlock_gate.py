from types import SimpleNamespace
from gbox import game_unlocks as G, pd_unlock as D, pd_inventory

PD = {'game_id': D.GAME_ID, 'platform': D.PLATFORM}


def test_pd_gate_pending_and_unverified():
    p = G.profile_for(PD)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert set(p['inventory']) == set(D.CATEGORIES)
    assert all(v['status'] == 'unknown' for v in p['inventory'].values())
    assert 'owned_rom_sha256' in p['requires']


def test_pd_pre_launch_and_plan_reach_no_writer():
    r = G.pre_launch(PD, SimpleNamespace())
    assert r['applied'] is False and r['state'] == 'research_pending'
    plan = G.launch_plan(PD, {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}, enable_unlock=True, allow_save_upgrade=True)
    assert plan['status'] == 'unsupported_unlock' and plan['jobs'] == []


def test_pd_gate_requires_exact_identity_and_has_no_addresses():
    for g in ({'title': D.TITLE}, {'game_id': D.GAME_ID, 'platform': 'xbox360'}, {'game_id': '4aef9956d37ab164', 'platform': 'n64'}):
        assert G.profile_for(g)['verified'] is False
    assert '0x' not in repr(D.profile_gate()).lower()
    assert D.CANDIDATE_BUILD['md5'] == pd_inventory.KNOWN_BUILDS['pal-final'][0]
