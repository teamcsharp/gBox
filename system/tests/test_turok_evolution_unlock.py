"""Tests for the Turok - Evolution (USA) GameCube unlock inventory and guard."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import game_unlocks
from gbox import turok_evolution_unlock as turok

GAME = {'game_id': turok.GAME_ID, 'platform': turok.PLATFORM}


def test_pinned_identity_is_self_consistent():
    for digest in (turok.ISO_SHA256, turok.DOL_SHA256):
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
    assert turok.ISO_SIZE > turok.DOL_SIZE > 0
    assert turok.TRE_OFFSET + turok.TRE_SIZE <= turok.ISO_SIZE
    assert turok.DOL_TEXT_ADDR >= 0x80000000
    ident = turok.disc_identity()
    assert ident['serial'] == 'GTKE51' and ident['platform'] == 'gamecube'


def test_inventory_covers_every_required_category():
    inv = turok.inventory()
    assert tuple(inv) == turok.CATEGORIES
    for name, data in inv.items():
        assert 'entries' in data and 'note' in data
        for entry in data['entries']:
            assert entry['state'] in turok.STATES
            assert entry['name'] and entry['evidence']


def test_no_entry_claims_unlocked_before_runtime_acceptance():
    gate = turok.profile_gate()
    for data in turok.inventory().values():
        for entry in data['entries']:
            if not gate['verified']:
                assert entry['state'] in ('unknown', 'not_present')


def test_profile_gate_reports_blockers_and_next_step():
    gate = turok.profile_gate()
    assert gate['verified'] is False
    assert gate['status'] == 'pending_research'
    assert gate['reason'] and gate['blockers'] and gate['next']
    assert gate['scope'] == list(turok.CATEGORIES)
    assert gate['evidence']['identity']['dol_sha256'] == turok.DOL_SHA256


def test_revision_guard_rejects_other_builds():
    assert turok.verify_build(turok.ISO_SHA256, turok.DOL_SHA256) is True
    assert turok.verify_build('0' * 64, turok.DOL_SHA256) is False
    assert turok.verify_build(turok.ISO_SHA256, '0' * 64) is False
    result = turok.apply_unlock(None, iso_sha256='0' * 64)
    assert result['applied'] is False and result['state'] == 'revision_mismatch'


def test_apply_unlock_never_writes_before_proof(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / 'save.dat'
        result = turok.apply_unlock(str(target))
        assert result['applied'] is False
        assert result['state'] == 'research_pending'
        assert not target.exists()


def test_unlock_ops_are_declarations_only():
    ops = turok.unlock_ops()
    assert ops and all('op' in o for o in ops)
    assert any(o['op'] == 'map_save_layout' for o in ops)
    guard = [o for o in ops if o['op'] == 'unlock_progress'][0]['revision_guard']
    assert guard['iso_sha256'] == turok.ISO_SHA256


def test_profile_for_registers_this_game_as_pending_only():
    profile = game_unlocks.profile_for(GAME)
    assert profile['verified'] is False
    assert profile['profile'] is None
    assert profile['status'] == 'pending_research'
    assert profile['scope'] == list(turok.CATEGORIES)


def test_pre_launch_reports_research_pending_and_never_applies():
    result = game_unlocks.pre_launch(GAME, None)
    assert result['applied'] is False
    assert result['state'] == 'research_pending'
    assert result['scope'] == list(turok.CATEGORIES)
    assert result['blockers'] and result['next']


def test_other_games_are_unaffected():
    other = {'game_id': 'f' * 16, 'platform': 'gamecube'}
    profile = game_unlocks.profile_for(other)
    assert profile['status'] == 'unsupported'
    assert game_unlocks.pre_launch(other, None)['applied'] is False


if __name__ == '__main__':
    import tempfile
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS', name)
            except Exception as exc:            # noqa: BLE001 - report and continue
                failures += 1
                print('FAIL', name, type(exc).__name__, exc)
    print('failures:', failures)
    raise SystemExit(1 if failures else 0)
