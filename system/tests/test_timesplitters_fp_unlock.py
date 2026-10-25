"""Tests for the TimeSplitters: Future Perfect (GameCube, USA) unlock profile."""
from gbox import game_unlocks
from gbox import timesplitters_fp_unlock as TSFP


GAME = {'game_id': TSFP.GAME_ID, 'platform': TSFP.PLATFORM}


def test_tsfp_profile_gate_is_honest_and_has_no_writer():
    gate = TSFP.profile_gate()
    assert 'runtime' in gate['reason'].lower() or 'not' in gate['reason'].lower()
    assert gate['evidence']['source'].startswith('https://gamehacking.org/')
    assert gate['evidence']['desc'] == 'Game 100% Complete'
    assert len(gate['evidence']['codes']) == 5
    assert gate['blockers']
    assert 'live' in gate['next'].lower()


def test_tsfp_profile_for_is_pending_research_and_not_verified():
    p = game_unlocks.profile_for(GAME)
    assert p['status'] == 'pending_research'
    assert p['verified'] is False
    assert p['profile'] is None
    assert p['scope'] == list(TSFP.CATEGORIES)
    assert 'reason' in p
    assert 'evidence' in p
    assert 'blockers' in p
    assert 'next' in p


def test_tsfp_pre_launch_reports_research_pending_and_applies_nothing():
    result = game_unlocks.pre_launch(GAME, ctx=None)
    assert result['state'] == 'research_pending'
    assert result['applied'] is False
    assert result['reason']
    assert result['evidence']
    assert result['blockers']
    assert result['next']


def test_tsfp_unlock_address_and_value_match_gecko_code():
    p = TSFP.profile()
    op = p['unlock_ops'][0]
    assert op['address'] == 0x503488
    assert op['hex_bytes'] == format(0x0011FFFF, '08x')
    assert op['width'] == 4
    assert op['gameplay_verified'] is False


def test_tsfp_code_lines_are_valid_gecko_format():
    for line in TSFP.CODE_LINES:
        parts = line.split()
        assert len(parts) == 2
        cmd, value = parts
        assert len(cmd) == 8
        assert len(value) == 8
        int(cmd, 16)
        int(value, 16)


def test_tsfp_wrong_platform_is_unsupported():
    wrong = {'game_id': TSFP.GAME_ID, 'platform': 'ps2'}
    p = game_unlocks.profile_for(wrong)
    assert p['status'] == 'unsupported'
    assert p['verified'] is False
