"""RE6 PS3 (BLUS30855) unlock research gate: honest pending_research contract.

The EBOOT hash is pinned and RPCS3 launch verified, but no native unlock
routine, save structure map, or live RAM measurement exists. This test pins
exactly what the gate promises: structured pending_research status, no
verified writer, required evidence chain, and safety invariants.
"""
from gbox import game_unlocks as G
from gbox import re6_ps3_unlock as R


def test_profile_gate_pins_exact_identity():
    gate = R.profile_gate()
    assert gate['game_id'] == '6fc93ff62e4eb868'
    assert gate['platform'] == 'ps3'
    assert gate['title_id'] == 'BLUS30855'
    assert gate['app_ver'] == '01.00'
    assert len(gate['eboot_sha256']) == 64
    assert gate['verified'] is False
    assert gate['status'] == 'pending_research'


def test_profile_gate_declares_categories():
    gate = R.profile_gate()
    for cat in ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
                'costumes', 'items', 'extras'):
        assert cat in gate['categories']


def test_profile_gate_lists_required_evidence():
    gate = R.profile_gate()
    for ev in ('owned_executable_sha256', 'native_unlock_routine',
               'save_structure_map', 'save_backup_receipt', 'rollback_receipt',
               'live_boot_and_selection_acceptance', 'second_launch_verification'):
        assert ev in gate['requires']


def test_profile_gate_carries_safety_invariants():
    gate = R.profile_gate()
    assert any('Never test on the operator PC' in s for s in gate['safety'])
    assert any('Preserve the original disc/EBOOT' in s for s in gate['safety'])
    assert any('code-only PR is not unlock completion' in s for s in gate['safety'])


def test_game_unlocks_profile_for_returns_pending_research():
    game = {'game_id': R.GAME_ID, 'platform': 'ps3'}
    profile = G.profile_for(game)
    assert profile['status'] == 'pending_research'
    assert profile['verified'] is False
    assert profile['profile'] is None
    assert 'characters' in profile['scope']
    assert 'extras' in profile['scope']
    assert 'reason' in profile


def test_game_unlocks_profile_for_wrong_platform_is_unsupported():
    game = {'game_id': R.GAME_ID, 'platform': 'xbox360'}
    profile = G.profile_for(game)
    assert profile['status'] == 'unsupported'


def test_game_unlocks_pre_launch_never_applies():
    game = {'game_id': R.GAME_ID, 'platform': 'ps3'}
    result = G.pre_launch(game, None)
    assert result['state'] == 'research_pending'
    assert result['applied'] is False
    assert 'reason' in result
    assert 'next_step' in result


def test_game_unlocks_pre_launch_wrong_platform_is_generic():
    game = {'game_id': R.GAME_ID, 'platform': 'xbox360'}
    result = G.pre_launch(game, None)
    assert result['applied'] is False
    assert result['state'] in ('research_pending', 'implementation_pending')
