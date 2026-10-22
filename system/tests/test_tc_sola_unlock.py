"""Focused checks for the True Crime: Streets of LA unlock research module."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbox import game_unlocks, tc_sola_unlock as tc

# The 404-byte progress table of the owned Shell/mc.dat template, recorded from
# the owned disc (GTLE52) so the module can be checked without the 1.4 GB image.
FLAG_FRAGMENT_HEX = (
    '100010000000000000000111011101110111011101110111011112221222122212221222133313331322110011001100220022002200220022002200320033003300330043004400440044004400440055015501550155015501650165016501650166016601660166016601b822bc23bc23c043c443c443c443c844c844c844c843c443c443c443c023c023c023c023c023c023bc23bc23bc22bc22bc22bc22bc22bc22b822b822b822b822b422b4228421842188428c638c63908494a598c698c69ce7a108a108a529a94aad6bb18cb18c244425552555255535663666366636663666366636663666377737773777377747774888488848884888499949994999499959995aaa5aaa5aaa59996999c631c631ca52ce73d294d294d6b5dad66bbb6bbbdef76bbb6bbb6bbbe318e318e318e318e739e739e739e739e739eb5aeb5aeb5aeb5aef7bef7bef7bef7bef7bef7bf39cf39cf39cf39cf39cf39cf7bdf7bdf7bdf7bdf7bdf7bdf7bdf7bdf7bdf7bdf7bdfbdefbdefbdefbdefbdefbdefbdefbdeffffffffffffffffffffffffffffffff'
)


def _fragment():
    return bytes.fromhex(FLAG_FRAGMENT_HEX)


def _template():
    """A full-size save template whose progress table is the recorded fragment."""
    buf = bytearray(tc.MC_SIZE)
    buf[tc.MC_FLAG_REGION[0]:tc.MC_FLAG_REGION[1]] = _fragment()
    return bytes(buf)


def test_owns_exact_disc_identity():
    assert tc.DISC_ID == 'GTLE52'
    assert tc.GAME_ID == 'b5f07832ba61272a'
    assert tc.PLATFORM == 'gamecube'
    assert tc.DOL_SIZE == 4624192
    assert len(tc.DOL_SHA256) == 64
    assert len(tc.MC_SHA256) == 64


def test_recorded_progress_table_matches_the_module_digest():
    assert len(_fragment()) == tc.MC_FLAG_REGION[1] - tc.MC_FLAG_REGION[0]
    assert hashlib.sha256(_fragment()).hexdigest() == tc.MC_FLAG_REGION_SHA256
    assert _fragment().endswith(b'\xff' * 12)
    assert tc.MC_COMPLETE_VALUE == 0xFF


def test_profile_artifact_agrees_with_module_constants():
    prof = tc.load_profile()
    assert prof['revision']['dol_sha256'] == tc.DOL_SHA256
    assert prof['disc_id'] == tc.DISC_ID
    assert prof['save']['sha256'] == tc.MC_SHA256
    assert prof['save']['mc_flag_region_sha256'] == tc.MC_FLAG_REGION_SHA256
    assert prof['categories'] == list(tc.CATEGORIES)
    assert tc.check_profile_consistency() == []


def test_inventory_covers_every_category_and_states_honest_status():
    inv = tc.profile()['inventory']
    assert set(inv) == set(tc.CATEGORIES)
    for name, entry in inv.items():
        assert entry['status'] in ('present', 'unknown', 'not_present'), name
        assert entry['evidence'].strip(), name
    # No category may claim a lock table that was never located.
    assert inv['characters']['status'] == 'unknown'
    assert inv['hidden_characters']['status'] == 'unknown'
    assert inv['costumes']['status'] == 'unknown'


def test_verify_dol_and_mc_reject_anything_but_the_owned_bytes():
    ok, _ = tc.verify_dol(b'\x00' * tc.DOL_SIZE)
    assert ok is False
    ok, _ = tc.verify_mc(b'\x00' * tc.MC_SIZE)
    assert ok is False
    ok, reason = tc.verify_mc(bytes(tc.MC_SIZE))
    assert ok is False and 'mc.dat' in reason


def test_progress_table_reads_the_pinned_region():
    tmpl = _template()
    assert tc.progress_table(tmpl) == _fragment()
    with pytest.raises(ValueError):
        tc.progress_table(b'\x00' * 10)


def test_unlock_ops_skip_already_complete_bytes():
    ops = tc.unlock_ops(_template())
    assert ops, 'expected pending progress bytes'
    for op in ops:
        assert op['offset'] >= tc.MC_FLAG_REGION[0]
        assert op['offset'] < tc.MC_FLAG_REGION[1]
        assert op['target'] == tc.MC_COMPLETE_VALUE
        assert op['current'] != tc.MC_COMPLETE_VALUE
        assert op['content'] is None


def test_apply_ops_refuses_without_a_proven_content_map():
    ops = tc.unlock_ops(_template())
    with pytest.raises(tc.UnlockNotProven):
        tc.apply_ops(_template(), ops)
    with pytest.raises(tc.UnlockNotProven):
        tc.apply_ops(_template(), ops, {'never on disc': True})


def test_apply_ops_refuses_offsets_outside_the_progress_table():
    op = {'offset': 0x0100, 'current': 0, 'target': 0xFF, 'content': 'modes'}
    with pytest.raises(ValueError):
        tc.apply_ops(_template(), [op], {'modes': True})


def test_apply_ops_refuses_to_move_a_byte_backwards():
    op = {'offset': tc.MC_FLAG_REGION[0], 'current': 0xFF, 'target': 0x01, 'content': 'modes'}
    with pytest.raises(ValueError):
        tc.apply_ops(_template(), [op], {'modes': True})


def test_apply_ops_writes_only_inside_the_region_and_keeps_a_backup():
    ops = tc.unlock_ops(_template())
    for op in ops:
        op['content'] = 'modes'
    result = tc.apply_ops(_template(), ops, {'modes': True})
    assert result['backup'] == _template()
    data = result['data']
    assert len(data) == tc.MC_SIZE
    assert data[:tc.MC_FLAG_REGION[0]] == _template()[:tc.MC_FLAG_REGION[0]]
    assert data[tc.MC_FLAG_REGION[1]:] == _template()[tc.MC_FLAG_REGION[1]:]
    assert data[tc.MC_FLAG_REGION[0]:tc.MC_FLAG_REGION[1]] == b'\xff' * (tc.MC_FLAG_REGION[1] - tc.MC_FLAG_REGION[0])


def test_profile_gate_reports_blockers_and_no_writable_profile():
    gate = tc.profile_gate()
    assert gate['blockers'], 'unproven mapping must stay a blocker'
    assert gate['next']
    assert tc.profile()['verified'] is False


def test_game_unlocks_registers_the_profile_for_the_exact_game():
    prof = game_unlocks.profile_for({'game_id': tc.GAME_ID, 'platform': tc.PLATFORM})
    assert prof['status'] == 'pending_research'
    assert prof['verified'] is False
    assert prof['scope'] == list(tc.CATEGORIES)


def test_game_unlocks_ignores_other_games():
    prof = game_unlocks.profile_for({'game_id': 'ffffffffffffffff', 'platform': 'gamecube'})
    assert prof['verified'] is False
    assert prof['status'] == 'unsupported'


def test_pre_launch_reports_research_pending_and_writes_nothing():
    result = game_unlocks.pre_launch({'game_id': tc.GAME_ID, 'platform': tc.PLATFORM}, None)
    assert result['state'] == 'research_pending'
    assert result['applied'] is False
    assert result['scope'] == list(tc.CATEGORIES)
    assert result['blockers']
