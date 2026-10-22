from gbox import game_unlocks, tetris4d_unlock

G = {'game_id': tetris4d_unlock.GAME_ID, 'platform': 'dc'}


def test_profile_is_unverified_pending():
    p = game_unlocks.profile_for(G)
    assert p['status'] == 'pending_research' and p['verified'] is False
    assert p['evidence']['1ST_READ.BIN_sha256'] == tetris4d_unlock.FIRST_READ_SHA256


def test_pre_launch_never_applies():
    r = game_unlocks.pre_launch(G, None)
    assert r['state'] == 'research_pending' and r['applied'] is False
    assert r['blockers']


def test_launch_plan_rejects_unlock():
    w = {'id': 'w1', 'name': 'JAYBUILTFINALE'}
    r = game_unlocks.launch_plan(G, w, enable_unlock=True)
    assert r['status'] == 'unsupported_unlock' and r['jobs'] == []
