"""Focused tests for the DOA5 Ultimate Arcade unlock profile (request #2099)."""
from gbox import game_unlocks
from gbox import doa5_arcade_unlock


def test_profile_for_doa5_is_gated_and_honest():
    game = {'game_id': '75957a5c46d70c90', 'platform': 'sega_arcade_pc'}
    prof = game_unlocks.profile_for(game)
    assert prof['verified'] is False
    assert prof['status'] == 'research_pending'
    assert set(prof['scope']) == {'characters', 'hidden_characters', 'modes', 'levels',
                                  'stages', 'costumes', 'items', 'extras'}
    assert 'online competitive advantage' in ' '.join(prof['exclusions']).lower()


def test_pre_launch_never_applies_unverified_unlock():
    game = {'game_id': '75957a5c46d70c90', 'platform': 'sega_arcade_pc'}
    result = game_unlocks.pre_launch(game, ctx=None, mod='')
    assert result['state'] == 'research_pending'
    assert result['applied'] is False


def test_other_games_still_unsupported():
    prof = game_unlocks.profile_for({'game_id': 'ffffffffffffffff', 'platform': 'pc'})
    assert prof['status'] == 'unsupported'
    assert prof['verified'] is False


def test_template_file_exists_and_is_json():
    import json
    data = json.loads(doa5_arcade_unlock.template_path().read_text(encoding='utf-8'))
    assert data['game_id'] == doa5_arcade_unlock.DOA5_ID
    assert data['platform'] == doa5_arcade_unlock.DOA5_PLATFORM
    assert data['status'] == 'research_pending'
