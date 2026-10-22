from types import SimpleNamespace
from gbox import game_unlocks as G, raidou1_unlock as R


def test_gate_pending_and_hash_bound():
    for gid in R.GAME_IDS:
        p = G.profile_for({'game_id': gid, 'platform': 'ps2'})
        assert p['verified'] is False and p['status'] == 'pending_research'
        assert len(p['executable_sha256']) == 64 and 'native_unlock_routine' in p['requires']


def test_no_writer_and_no_title_bypass():
    g = {'game_id': R.GAME_IDS[0], 'platform': 'ps2'}
    assert G.pre_launch(g, SimpleNamespace())['applied'] is False
    assert G.profile_for({'title': R.TITLE, 'platform': 'ps2'})['status'] == 'unsupported'
    assert G.profile_for({'game_id': R.GAME_IDS[0], 'platform': 'xbox'})['status'] == 'unsupported'
