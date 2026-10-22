from types import SimpleNamespace
from gbox import game_unlocks as G, nba2k2_unlock as N

NBA = {'game_id': N.GAME_ID, 'platform': N.PLATFORM}


def test_gate_pending_and_pinned():
    p = G.profile_for(NBA)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert p['executable']['elf_sha256'].startswith('54c99587')
    assert len(p['executable']['source_sha256']) == 64
    assert set(p['inventory']) == set(N.CATEGORIES)
    assert all(v['status'] == 'unknown' for v in p['inventory'].values())


def test_no_writer_reachable():
    r = G.pre_launch(NBA, SimpleNamespace())
    assert r['applied'] is False
    worker = {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}
    plan = G.launch_plan(NBA, worker, enable_unlock=True, allow_save_upgrade=True)
    assert plan['jobs'] == [] and plan['executed'] is False


def test_title_or_platform_cannot_bypass():
    for g in ({'title': N.TITLE}, {'game_id': N.GAME_ID, 'platform': 'ps2'}):
        assert G.profile_for(g)['verified'] is False
