from types import SimpleNamespace
from gbox import game_unlocks as G, smb3_unlock as S

SMB3 = {'game_id': S.GAME_ID, 'platform': S.PLATFORM}


def test_gate_pending_and_inventory_unknown():
    p = G.profile_for(SMB3)
    assert p['verified'] is False and p['status'] == 'pending_research'
    assert set(p['inventory']) == set(S.CATEGORIES)
    assert all(v['state'] == 'unknown' for v in p['inventory'].values())


def test_pre_launch_and_plan_reach_no_writer():
    r = G.pre_launch(SMB3, SimpleNamespace())
    assert r['applied'] is False and r['state'] == 'research_pending'
    plan = G.launch_plan(SMB3, {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}, enable_unlock=True, allow_save_upgrade=True)
    assert plan['status'] == 'unsupported_unlock' and plan['jobs'] == []


def test_title_or_platform_mismatch_unsupported():
    assert G.profile_for({'title': S.TITLE})['status'] == 'unsupported'
    assert G.profile_for({'game_id': S.GAME_ID, 'platform': 'snes'})['status'] == 'unsupported'


def test_revision_guard_rejects_other_bytes():
    assert S.revision_guard(b'\x00' * S.OWNED_SIZE)['match'] is False
    assert S.revision_guard(S.OWNED_HEADER)['match'] is False
