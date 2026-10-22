from gbox import game_unlocks, mk64_unlock, mk64_inventory

G = {'game_id': mk64_unlock.GAME_ID, 'platform': 'n64'}


def test_rom_hash_matches_inventory():
    assert mk64_unlock.ROM_SHA1_Z64 in mk64_inventory.KNOWN


def test_profile_pending_and_unverified():
    p = game_unlocks.profile_for(G)
    assert p['status'] == 'pending_research' and p['verified'] is False and p['profile'] is None
    assert set(p['scope']) == set(mk64_unlock.CATEGORIES)
    assert {i['category'] for i in p['evidence']['inventory']} == set(mk64_unlock.CATEGORIES)


def test_wrong_platform_unsupported():
    assert game_unlocks.profile_for({'game_id': mk64_unlock.GAME_ID, 'platform': 'xbox'})['status'] == 'unsupported'


def test_pre_launch_never_applies():
    r = game_unlocks.pre_launch(G, None)
    assert r['applied'] is False and r['state'] == 'research_pending'
