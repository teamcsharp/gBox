from gbox import game_unlocks as gu


def test_profile_is_pending_and_pinned():
    p = gu.profile_for({'game_id': gu.GAMES88_ID, 'platform': 'arcade'})
    assert p['status'] == 'research_pending' and p['verified'] is False
    assert p['zip_sha256'] == gu.GAMES88_ZIP_SHA256
    assert set(p['categories']) >= {'characters', 'hidden_characters', 'modes', 'levels',
                                    'stages', 'costumes', 'items', 'extras'}


def test_pre_launch_applies_nothing():
    r = gu.pre_launch({'game_id': gu.GAMES88_ID, 'platform': 'arcade'}, None)
    assert r['applied'] is False and r['state'] == 'research_pending'


def test_other_platform_unsupported():
    assert gu.profile_for({'game_id': gu.GAMES88_ID, 'platform': 'arcade_fbneo'})['status'] == 'unsupported'
