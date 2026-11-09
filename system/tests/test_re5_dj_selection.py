"""Same-title DJ jobs use a one-shot request on their own session only."""
from types import SimpleNamespace

import pytest

from gbox import mercmode, re5_mods_tool as T, tools
from gbox.mercs import round_controls
from gbox.mercs.titles import re5_switch as R, re5_switch_mods as SW


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    adapters = [SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path)) for _ in range(2)]
    monkeypatch.setattr(tools, 'SESSIONS', {
        f's{i}': (ad, {'game_id': '52d15709be0fda1a', 'platform': 'switch'}) for i, ad in enumerate(adapters)})
    monkeypatch.setattr(R, 'SELECTION', {'stage': 2, 'character': 8})
    return adapters


def test_scheduler_requests_have_unique_identity_and_do_not_mutate_queue_entry():
    entry = {'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0}
    first, second = [mercmode.selection_job('re5', 's0', entry) for _ in range(2)]
    assert first[0] == second[0] == 're5_mods'
    assert first[1]['one_round'] and second[1]['one_round']
    assert first[1]['request_id'] != second[1]['request_id']
    assert len(first[1]['request_id']) == 32 and set(entry) == {'mode', 'character', 'stage'}


def test_same_title_dj_pick_does_not_change_another_session_or_operator_selection(sessions, monkeypatch):
    controls = [round_controls.attach(ad, R.MAP_ID, f's{i}') for i, ad in enumerate(sessions)]
    monkeypatch.setattr(SW, 'tool_run', lambda *a, **kw: pytest.fail('DJ selection entered the persistent operator route'))
    tool, body = mercmode.selection_job('re5', 's0', {'mode': 'no_mercy', 'character': 'Chris (BSAA)', 'stage': 0})
    result = T.re5_mods(T.RE5ModsIn(**body), SimpleNamespace(job_id='job'))['result']
    assert result['queued'] and result['session_id'] == 's0' and result['one_round']
    assert controls[0].selection['stage'] == 0 and controls[0].selection['character'] == 0
    assert controls[1].selection is None and R.SELECTION == {'stage': 2, 'character': 8}
    assert not controls[0].path.exists()
    controls[0].observed(0, 0)
    assert controls[0].selection is None
    again = T.re5_mods(T.RE5ModsIn(**body), SimpleNamespace(job_id='job'))['result']
    assert not again['queued'] and again['already_played'] and again['native_start_verified']
    assert controls[0].selection is None


def test_operator_default_keeps_its_existing_queue_route(sessions, monkeypatch):
    calls = []
    monkeypatch.setattr(SW, 'tool_run', lambda *a, **kw: calls.append((a, kw)) or {'verified': True})
    T.re5_mods(T.RE5ModsIn(session_id='s0', op='mercs_select', mode='no_mercy', character='Chris (BSAA)'),
               SimpleNamespace(job_id='operator'))
    assert len(calls) == 1 and calls[0][1]['operator'] is True
    assert not hasattr(sessions[0], '_merc_round_controls')


def test_unavailable_dj_choice_does_not_attach_or_change_any_selection(sessions):
    result = T.re5_mods(T.RE5ModsIn(session_id='s0', op='mercs_select', mode='reunion', one_round=True),
                        SimpleNamespace(job_id='bad-pick'))['result']
    assert not result['verified'] and not result['queued']
    assert not hasattr(sessions[0], '_merc_round_controls') and R.SELECTION == {'stage': 2, 'character': 8}


def test_omitted_request_identity_uses_owning_job(sessions):
    result = T.re5_mods(T.RE5ModsIn(session_id='s0', op='mercs_select', mode='no_mercy',
                                   character='Chris (BSAA)', one_round=True), SimpleNamespace(job_id='owning-job'))['result']
    assert result['request_id'] == 'owning-job'
    assert sessions[0]._merc_round_controls.selection['key'] == 'request:owning-job'


def test_ps3_dj_route_retains_its_native_coverage_dispatch(sessions, monkeypatch):
    ad = sessions[0]
    tools.SESSIONS['s0'] = (ad, {'platform': 'ps3', 'game_id': 'e7ca89bbeb67360d'})
    calls = []
    monkeypatch.setattr(T, 'run', lambda *a, **kw: calls.append((a, kw)) or {'queued': True})
    result = T.re5_mods(T.RE5ModsIn(session_id='s0', op='mercs_select', one_round=True),
                        SimpleNamespace(job_id='ps3-job'))['result']
    assert result['queued'] and calls[0][0][:2] == (ad, 'mercs_select')
    assert not hasattr(ad, '_merc_round_controls')
