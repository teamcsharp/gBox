"""Round preferences use temporary files and fake catalogs; no emulator/service I/O."""
import json
import uuid
from types import SimpleNamespace

import pytest

from gbox.mercs import round_controls as R


@pytest.fixture
def controls(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'catalog', lambda title: (('Village', 'Castle', 'Base', 'Waterworld'), ('Leon', 'Ada', 'Wesker')))
    monkeypatch.setattr(R.Controls, 'quick_status', lambda self: {'available': False})
    return R.Controls('re4', 'worker-session', path=tmp_path / 'stages.json')


def command(control, op, **args):
    return control.command({'op': op, 'request_id': str(uuid.uuid4()), **args})


def stages(weights=(50, 25, 25, 0), enabled=(True, True, True, False)):
    return [{'id': i, 'enabled': on, 'weight': weight} for i, (on, weight) in enumerate(zip(enabled, weights))]


def test_status_contract_and_defaults_are_read_only(controls):
    status = controls.command({'op': 'status'})
    assert status['session_id'] == 'worker-session'
    assert status['title_id'] == 're4' and status['available']
    assert status['current_stage'] is None
    assert status['loop'] == {'enabled': False, 'stage_id': None}
    assert status['receipt'] is None and status['receipts'] == []
    assert [row['weight'] for row in status['stages']] == [25] * 4
    assert all(row['default_enabled'] for row in status['stages'])
    assert not controls.path.exists()


@pytest.mark.parametrize('rows', [
    [], stages()[:-1], stages() + [stages()[0]],
    [dict(row, id=0) for row in stages()],
    [dict(row, enabled=1) for row in stages()],
    [dict(row, weight=True) for row in stages()],
    [dict(row, weight=float('nan')) for row in stages()],
    [dict(row, weight=float('inf')) for row in stages()],
    [dict(row, weight=101) for row in stages()],
    [dict(row, enabled=False) for row in stages()],
    [dict(row, weight=0) for row in stages()],
])
def test_invalid_stage_sets_fail_closed_without_mutation(controls, rows):
    before = controls.rows.copy()
    with pytest.raises(ValueError):
        R.normalize(rows, controls.names)
    assert controls.rows == before and not controls.path.exists()


def test_normalization_zeroes_disabled_weights_and_preserves_relative_proportions(controls):
    rows = R.normalize(stages((5, 3, 2, 99)), controls.names)
    assert [row['weight'] for row in rows] == [50, 30, 20, 0]
    assert sum(row['weight'] for row in rows) == pytest.approx(100)


def test_stage_save_reset_and_reload_preserve_other_titles(controls):
    controls.path.write_text(json.dumps({'re5': [{'retain': True}]}), encoding='utf-8')
    reply = command(controls, 'stages', stages=stages((6, 2, 2, 0)))
    assert reply['receipt']['status'] == 'applied'
    assert [row['weight'] for row in reply['stages']] == [60, 20, 20, 0]
    saved = json.loads(controls.path.read_text(encoding='utf-8'))
    assert saved['re5'] == [{'retain': True}]
    reloaded = R.Controls('re4', 'next', path=controls.path)
    assert reloaded.rows == controls.rows and reloaded.configured
    reset = command(controls, 'stages', reset=True)
    assert [row['weight'] for row in reset['stages']] == [25] * 4
    assert all(row['enabled'] for row in reset['stages'])


def test_failed_stage_persistence_keeps_old_preferences(controls, monkeypatch):
    before = controls.rows.copy()
    monkeypatch.setattr(R.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('disk denied')))
    reply = command(controls, 'stages', stages=stages())
    assert reply['receipt']['status'] == 'rejected'
    assert 'disk denied' in reply['receipt']['error']
    assert controls.rows == before and not controls.path.exists()
    assert list(controls.path.parent.glob('*.tmp')) == []


def test_duplicate_request_returns_same_receipt_without_rewriting(controls, monkeypatch):
    body = {'op': 'stages', 'request_id': str(uuid.uuid4()), 'stages': stages()}
    first = controls.command(body)
    monkeypatch.setattr(R.os, 'replace', lambda *_: pytest.fail('duplicate request wrote again'))
    second = controls.command(dict(body))
    assert second['receipt'] == first['receipt']
    with pytest.raises(ValueError, match='different action'):
        controls.command(dict(body, reset=True))


def test_replay_requires_verified_round_and_is_consumed_only_by_matching_new_character(controls):
    assert command(controls, 'replay', mode='once')['receipt']['status'] == 'rejected'
    controls.observed(2, 1)
    body = {'op': 'replay', 'request_id': str(uuid.uuid4()), 'mode': 'once'}
    result = controls.command(body)
    assert result['receipt']['status'] == 'queued' and controls.holds_title()
    assert controls.choose_stage([0, 1]) is None
    assert 'not currently unlocked' in controls.reason
    assert controls.choose_stage([0, 2]) == 2
    assert controls.choose_character([1]) is None
    assert controls.choose_character([1, 2]) == 2
    controls.observed(2, 1)
    assert controls.once is not None
    controls.observed(3, 2)
    assert controls.once is not None
    controls.observed(2, 2)
    assert controls.once is None and not controls.holds_title()
    confirmed = controls.command(body)
    assert confirmed['receipt']['status'] == 'applied'
    assert confirmed['receipt']['character_id'] == 2
    assert controls.once is None, 'polling/repeating a completed request must not queue another replay'


def test_loop_captures_current_stage_and_survives_rounds_until_explicit_off(controls):
    controls.observed(1, 0)
    assert command(controls, 'replay', mode='loop', enabled=True)['loop'] == {'enabled': True, 'stage_id': 1}
    controls.observed(2, 1)
    assert controls.choose_stage([0, 1, 2]) == 1
    assert controls.choose_character([0, 1]) == 0
    assert controls.holds_title()
    result = command(controls, 'replay', mode='loop', enabled=False)
    assert result['loop'] == {'enabled': False, 'stage_id': None}
    assert not controls.holds_title()


def test_queued_replay_receipt_survives_bounded_history(controls):
    controls.observed(0, 0)
    first = command(controls, 'replay', mode='once')['receipt']['request_id']
    for _ in range(150):
        command(controls, 'not-supported')
    assert len(controls.receipts) == 128 and first in controls.receipts
    assert controls.command({'op': 'status'})['replay_pending']


def test_evicted_completed_request_cannot_execute_again(controls):
    controls.observed(0, 0)
    body = {'op': 'replay', 'request_id': str(uuid.uuid4()), 'mode': 'once'}
    controls.command(body)
    controls.observed(0, 1)
    for _ in range(150):
        command(controls, 'not-supported')
    assert body['request_id'] not in controls.receipts
    reply = controls.command(body)
    assert reply['receipt']['status'] == 'rejected'
    assert 'already processed' in reply['receipt']['error']
    assert controls.once is None


def test_random_pool_is_latched_until_native_round_start_and_respects_unlocks(controls):
    calls = []
    controls.rng = SimpleNamespace(choices=lambda values, weights, k: calls.append((values, weights, k)) or [values[-1]])
    controls.rows = R.normalize(stages(), controls.names)
    assert controls.choose_stage([0, 2, 3]) == 2
    assert controls.choose_stage([0, 2, 3]) == 2
    assert calls == [([0, 2], [50, 25], 1)]
    controls.observed(2, 0)
    controls.choose_stage([0, 2, 3])
    assert len(calls) == 2
    assert controls.choose_stage([3]) is None


def test_quick_attack_routes_exact_validated_values_only(controls, monkeypatch):
    from gbox.mercs import bot_logic
    controls.title = 're6'
    monkeypatch.setattr(controls, 'quick_status', lambda: {'available': True, 'enabled': True, 'count': 4, 'interval_s': 24})
    calls = []
    monkeypatch.setattr(bot_logic, 'handle', lambda title, values: calls.append((title, values)))
    reply = command(controls, 'quick_attack', enabled=True, count=4, interval_s=24)
    assert reply['receipt']['status'] == 'applied'
    assert calls == [('re6', {'PERIODIC_QA': True, 'PERIODIC_QA_COUNT': 4, 'PERIODIC_QA_INTERVAL_S': 24})]
    for args in ({'enabled': 1, 'count': 4, 'interval_s': 24}, {'enabled': True, 'count': 9, 'interval_s': 24},
                 {'enabled': True, 'count': True, 'interval_s': 24}, {'enabled': True, 'count': 4, 'interval_s': 7}):
        assert command(controls, 'quick_attack', **args)['receipt']['status'] == 'rejected'
    assert len(calls) == 1


def test_unsupported_title_quick_attack_does_not_call_bot_logic(controls, monkeypatch):
    from gbox.mercs import bot_logic
    monkeypatch.setattr(bot_logic, 'handle', lambda *_a, **_k: pytest.fail('unsupported title changed knobs'))
    assert command(controls, 'quick_attack', enabled=True, count=4, interval_s=24)['receipt']['status'] == 'rejected'


def test_incomplete_re6_quick_attack_knobs_cannot_partially_toggle_existing_knob(controls, monkeypatch):
    from gbox.mercs import bot_logic
    controls.title = 're6'
    monkeypatch.setattr(controls, 'quick_status', lambda: {'available': False})
    monkeypatch.setattr(bot_logic, 'handle', lambda *_a, **_k: pytest.fail('partial knob mutation'))
    reply = command(controls, 'quick_attack', enabled=True, count=4, interval_s=24)
    assert reply['receipt']['status'] == 'rejected'
    assert 'all quick-attack controls' in reply['receipt']['error']


def test_status_receipts_are_detached_from_internal_state(controls):
    controls.observed(0, 0)
    command(controls, 'replay', mode='once')
    status = controls.status()
    status['receipt']['status'] = 'forged'
    status['receipts'][0]['status'] = 'forged'
    status['stages'][0]['enabled'] = False
    assert controls.status()['receipt']['status'] == 'queued'
    assert controls.rows[0]['enabled'] is True
