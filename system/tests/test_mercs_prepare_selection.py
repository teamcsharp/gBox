"""The prepare playbook dispatches the queued pick to the matching native menus."""
import sys
from types import SimpleNamespace

import pytest

from gbox import mercs_bot as MB
from gbox.mercs.titles import re5_switch as SW


@pytest.fixture
def prepare(monkeypatch, tmp_path):
    monkeypatch.setattr(SW, 'SELECTION', {})
    reads, behavior = [], {}
    adapter = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))

    def screen(memory):
        control = getattr(memory.adapter, '_merc_round_controls', None)
        pending = control.selection if control is not None else None
        reads.append({key: pending[key] for key in ('stage', 'character')} if pending else {})
        if behavior.get('fail'):
            raise RuntimeError('menu read failed')
        if pending and behavior['confirmed']:
            control.menu_pressed({'where': 'select_stage', 'cursor': pending['stage'], 'target': pending['stage']}, 'a')
            control.menu_pressed({'where': 'select_player', 'cursor': pending['character'], 'target': pending['character']}, 'a')
        return {'where': 'playing'}

    menus = SimpleNamespace(screen=screen, step=lambda _: None, snapshot=lambda _: {},
                            STAGE_NAMES=SW.STAGE_NAMES)
    monkeypatch.setitem(sys.modules, '_selection_test_menus', menus)
    profile = {'map_id': SW.MAP_ID, 'menus': '_selection_test_menus', 'platform': 'switch'}
    monkeypatch.setattr(MB, 'profile_for', lambda *_: profile)
    monkeypatch.setattr(MB, 'title_engine', lambda _: SimpleNamespace(play_round=lambda *_a, **_k: 'stopped'))
    monkeypatch.setattr(MB, 'lessons_writer', lambda *_: None)

    def run(pick, *, confirmed=True, stopped=False, fail=False, preparing=True):
        behavior.update(confirmed=confirmed, fail=fail)
        return MB.play(adapter, lambda _: pytest.fail('prepare must not press a pad once playing'), lambda: stopped,
                       m=SimpleNamespace(), prepare=preparing,
                       game={'launch': {'mercmode': {'selection': pick}}})

    run.adapter = adapter
    return run, reads, profile


def test_switch_re5_prepare_queues_public_assembly_before_native_menu_read(prepare):
    run, reads, _ = prepare
    result = run({'title': 're5', 'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0})
    assert reads == [{'stage': 0, 'character': 0}]
    assert result['prepared'] is True
    assert result['queued_selection'] == 'no_mercy / Chris (BSAA) / Public Assembly'
    assert result['queued_selection_request']['state'] == 'confirmed'
    assert result['stage_index'] == 0 and result['stage'] == 'Public Assembly'
    assert result['character'] == 'Chris (BSAA)'
    assert not SW.SELECTION and run.adapter._merc_round_controls.selection is None


@pytest.mark.parametrize('pick', [
    {'mode': 'reunion', 'character': 'Chris (BSAA)', 'stage': 0},
    {'mode': 'no_mercy', 'character': 'not-a-character', 'stage': 0},
    {'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 999},
    {'mode': 'no_mercy', 'character': 'Chris (BSAA)'},
    {'mode': 'no_mercy', 'stage': 0},
])
def test_unavailable_switch_pick_does_not_prepare_a_different_default_round(prepare, pick):
    run, reads, _ = prepare
    result = run({'title': 're5', **pick})
    assert result['queued_selection_error']
    assert result['queued_selection_error'] in result['wandered']
    assert not result.get('prepared')
    assert not SW.SELECTION and not reads


def test_other_title_pick_does_not_change_switch_re5_selection(prepare):
    run, reads, _ = prepare
    result = run({'title': 're4', 'character': 'HUNK', 'stage': 2})
    assert reads == [{}] and not SW.SELECTION
    assert 'queued_selection' not in result


def test_ps3_re5_pick_keeps_its_coverage_dispatch(prepare, monkeypatch):
    from gbox.mercs.titles import re5_ps3
    run, reads, profile = prepare
    profile['map_id'] = 'BLUS30491'
    calls = []
    monkeypatch.setattr(re5_ps3, 'coverage', lambda: SimpleNamespace(request=lambda *args: calls.append(args)))
    result = run({'title': 're5', 'mode': 'reunion', 'character': 'Chris (Heavy Metal)', 'stage': 2})
    assert calls == [('reunion', 'Chris (Heavy Metal)', 2)]
    assert reads == [{}] and not SW.SELECTION
    assert result['prepared'] is True


def test_prepare_does_not_claim_an_already_playing_round_matches_new_pick(prepare):
    run, _, _ = prepare
    result = run({'title': 're5', 'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0}, confirmed=False)
    assert not result.get('prepared')
    assert 'did not confirm' in result['wandered']
    assert result['queued_selection_request']['state'] == 'cancelled'
    assert run.adapter._merc_round_controls.selection is None


def test_stopped_prepare_cancels_only_its_ephemeral_choice(prepare):
    run, reads, _ = prepare
    result = run({'title': 're5', 'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0}, stopped=True)
    assert not reads and not result.get('prepared')
    assert result['queued_selection_request']['state'] == 'cancelled'
    assert run.adapter._merc_round_controls.selection is None and not SW.SELECTION


def test_failed_prepare_clears_its_choice_before_another_menu_walk(prepare):
    run, _, _ = prepare
    with pytest.raises(RuntimeError, match='menu read failed'):
        run({'title': 're5', 'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0}, fail=True)
    assert run.adapter._merc_round_controls.selection is None and not SW.SELECTION


def test_operator_selection_retains_its_explicit_queue_contract(monkeypatch):
    from gbox.mercs.titles import re5_switch_mods
    monkeypatch.setattr(SW, 'SELECTION', {})
    planned = re5_switch_mods.mercs_selection('no_mercy', 'Chris (BSAA)', 0)
    assert planned['verified'] and not SW.SELECTION
    result = re5_switch_mods.mercs_select(None, 'no_mercy', 'Chris (BSAA)', 0)
    assert result['verified'] and result['queued']
    assert SW.SELECTION == {'stage': 0, 'character': 0}


def test_confirmed_prepare_is_not_requeued_by_normal_start_or_bot_reload(prepare):
    run, reads, _ = prepare
    launch_pick = {'title': 're5', 'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0}
    prepared = run(dict(launch_pick, request_id='prepare-job-1'))
    assert prepared['prepared'] and prepared['queued_selection_request']['state'] == 'confirmed'
    # The launch may omit the prepare job id; a bot reload may retain it. Both
    # are the same already-played launch choice, not a second queued round.
    for pick in (launch_pick, dict(launch_pick, request_id='prepare-job-1')):
        restarted = run(pick, preparing=False)
        assert reads[-1] == {}
        assert restarted['queued_selection_request']['already_played'] is True
        assert run.adapter._merc_round_controls.selection is None
    # A new explicit prepare job can intentionally request that same pair.
    again = run(dict(launch_pick, request_id='prepare-job-2'))
    assert reads[-1] == {'stage': 0, 'character': 0}
    assert again['prepared'] and not again['queued_selection_request'].get('already_played')
    assert 'request_id' not in launch_pick and not SW.SELECTION


def test_invalid_request_id_still_runs_playbook_cleanup(prepare, monkeypatch):
    from gbox.mercs.read_retry import NativeReadRetry
    run, _, _ = prepare
    stopped = []
    monkeypatch.setattr(NativeReadRetry, 'stopped', lambda self: stopped.append(True))
    with pytest.raises(ValueError, match='request_id'):
        run({'title': 're5', 'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0, 'request_id': 'x' * 129})
    assert stopped == [True]
    assert run.adapter._merc_round_controls.selection is None
