"""Tetris Plus unlock anchor: pinned revision, honest pending state, no write path."""
import re

from gbox import game_unlocks
from gbox import tetris_plus_unlock as tp

HEX64 = re.compile(r'^[0-9a-f]{64}$')


def test_profile_gate_is_pending_and_unverified():
    gate = tp.profile_gate()
    assert gate['status'] == 'pending_research'
    assert gate['verified'] is False
    assert gate['reason']
    assert gate['blockers']
    assert gate['next']
    assert gate['scope'] == list(tp.CATEGORIES)


def test_save_block_table_matches_observed_literals():
    assert tp.SAVE_BLOCK_TABLE['SELECT.EXE']['primary'] == 'bu00:baslus-00338'
    assert tp.SAVE_BLOCK_TABLE['EDIT.EXE']['backup'] == 'bu10:baslus-00338'
    for name, spec in tp.SAVE_BLOCK_TABLE.items():
        assert spec['wildcards'] == ('bu00:*', 'bu10:*'), name
        assert len(spec['addresses']) == 4, name
        assert all(a.startswith('0x800') for a in spec['addresses']), name


def test_executable_digests_are_pinned_sha256():
    assert set(tp.EXECUTABLE_SHA256) == set(tp.SAVE_BLOCK_TABLE)
    for name, digest in tp.EXECUTABLE_SHA256.items():
        assert HEX64.match(digest), name


def test_profile_for_reports_pending_without_write_path():
    profile = game_unlocks.profile_for({'game_id': tp.GAME_ID, 'platform': tp.PLATFORM})
    assert profile['status'] == 'pending_research'
    assert profile['verified'] is False
    assert profile['scope'] == list(tp.CATEGORIES)
    assert profile['blockers'] and profile['next']


def test_pre_launch_never_writes():
    result = game_unlocks.pre_launch({'game_id': tp.GAME_ID, 'platform': tp.PLATFORM}, None)
    assert result['applied'] is False
    assert result['state'] == 'research_pending'


if __name__ == '__main__':
    for _name, _fn in sorted(globals().items()):
        if _name.startswith('test_'):
            _fn()
    print('tetris_plus_unlock tests OK')
