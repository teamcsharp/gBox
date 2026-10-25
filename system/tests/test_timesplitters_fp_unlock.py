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
    assert op['address'] == 0x02503488
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


def test_tsfp_all_codes_present_and_valid():
    """All five code features from G3FE69.txt are present and valid."""
    assert 'Game 100% Complete' in TSFP.ALL_CODES
    assert 'Infinite Health' in TSFP.ALL_CODES
    assert 'Infinite Ammo' in TSFP.ALL_CODES
    assert 'Some Timers Frozen' in TSFP.ALL_CODES
    assert 'Player 1 1st/3rd Person Mode' in TSFP.ALL_CODES
    for name, lines in TSFP.ALL_CODES.items():
        assert len(lines) > 0, f'{name} has no lines'
        for line in lines:
            parts = line.split()
            assert len(parts) == 2, f'{name}: {line} not 2-part'
            assert len(parts[0]) == 8, f'{name}: {line} cmd not 8 hex'
            assert len(parts[1]) == 8, f'{name}: {line} val not 8 hex'
            int(parts[0], 16)
            int(parts[1], 16)


def test_tsfp_profile_includes_all_codes_and_save_file_status():
    """Profile exposes the full code evidence and save file job tracking."""
    p = TSFP.profile()
    assert 'all_codes' in p
    assert len(p['all_codes']) == 5
    assert p['save_file_status'] == TSFP.SAVE_FILE_STATUS
    assert p['save_file_job_id'] == TSFP.SAVE_FILE_JOB_ID


def test_tsfp_gate_includes_code_features():
    """Gate evidence lists all code features and the source file."""
    gate = TSFP.profile_gate()
    assert 'code_features' in gate['evidence']
    assert len(gate['evidence']['code_features']) == 5
    assert 'code_file' in gate['evidence']
    assert 'G3FE69' in gate['evidence']['code_file']


def test_tsfp_infinite_health_code_addresses():
    """Infinite Health code patches the health check at 0x040755D0."""
    lines = TSFP.INFINITE_HEALTH_LINES
    assert lines[0] == '040755D0 C02301D8'
    assert lines[1] == '040755D4 D02301CC'
    assert lines[2] == '040755DC 4800000C'


def test_tsfp_infinite_ammo_code_addresses():
    """Infinite Ammo code nulls the ammo decrement at two sites."""
    lines = TSFP.INFINITE_AMMO_LINES
    assert lines[0] == '041A9BA0 60000000'
    assert lines[1] == '041A9BCC 60000000'


def test_tsfp_primary_unlock_is_first_code_line():
    """The primary unlock write is the first line of CODE_LINES."""
    assert TSFP.CODE_LINES[0] == '02503488 0011FFFF'
    assert TSFP.UNLOCK_ADDRESS == 0x02503488
    assert TSFP.UNLOCK_VALUE == 0x0011FFFF
