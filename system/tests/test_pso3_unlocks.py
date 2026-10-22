"""Guards for the PSO Episode III C.A.R.D. Revolution unlock research profile (#2210)."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox import game_unlocks, pso3_unlocks

GAME = {'game_id': pso3_unlocks.GAME_ID, 'platform': pso3_unlocks.PLATFORM}
OWNED_DOL = Path('/home/ehm_eckx/.hermes/cache/scratch/pso_card_2210/PsoV3.dol')


def test_profile_never_claims_a_verified_unlock():
    prof = pso3_unlocks.profile()
    assert prof['verified'] is False
    assert prof['status'] == 'pending_runtime_verification'
    assert prof['game_id'] == pso3_unlocks.GAME_ID
    assert prof['save_effect'].startswith('None')


def test_profile_for_registers_the_game_without_unlocking_it():
    prof = game_unlocks.profile_for(GAME)
    assert prof['verified'] is False
    assert prof['status'] != 'verified_profile'
    assert prof['profile'] == 'pso3-ep3-card-revolution-research-v1'
    assert prof['reason']


def test_pre_launch_writes_nothing():
    result = game_unlocks.pre_launch(GAME, None)
    assert result['applied'] is False
    assert result['state'] == 'research_pending'
    assert result['items']


def test_inventory_covers_every_required_category():
    seen = {entry['category'] for entry in pso3_unlocks.inventory()}
    assert set(pso3_unlocks.CATEGORIES) == seen
    for entry in pso3_unlocks.inventory():
        assert entry['state'] in pso3_unlocks.STATES
        assert entry['evidence']
        assert entry['name']


def test_no_entry_is_marked_verified_before_runtime_acceptance():
    assert all(entry['state'] != 'verified' for entry in pso3_unlocks.inventory())


def test_artifact_digest_is_pinned():
    data = json.loads(pso3_unlocks._artifact_path().read_text(encoding='utf-8'))
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == pso3_unlocks.ARTIFACT_SHA256
    assert pso3_unlocks.load_artifact()['game_id'] == pso3_unlocks.GAME_ID


def test_save_layout_and_lock_targets_are_evidence_backed():
    for row in pso3_unlocks.save_layout():
        assert row['addr'] and row['value']
    for row in pso3_unlocks.lock_trace_targets():
        assert row['addr'] and row['symbol']


def test_revision_guard_rejects_any_other_executable():
    assert pso3_unlocks.revision_matches(b'not the owned dol') is False
    assert pso3_unlocks.dol_revision(b'x') != pso3_unlocks.DOL_SHA256


def test_revision_guard_accepts_the_owned_executable():
    if not OWNED_DOL.is_file():
        import pytest
        pytest.skip('owned disc image not present in this environment')
    assert pso3_unlocks.revision_matches(OWNED_DOL.read_bytes()) is True
