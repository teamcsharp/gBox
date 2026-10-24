"""Team requests remain intent until exact session/adapter native proof is fresh."""
from types import SimpleNamespace

import pytest

from gbox.mercs import teamplay as T
from gbox import mercs_team_tool as TOOL


@pytest.fixture(autouse=True)
def fresh_evidence():
    T._EVIDENCE.clear()
    yield
    T._EVIDENCE.clear()


def test_defaults_preserve_assisted_settings_and_explicit_reduction_optin(tmp_path):
    store = T.TeamStore(tmp_path)
    ad = SimpleNamespace(name='rpcs3')
    out = store.status('worker-session', game_id=T.RE5, adapter=ad)
    assert out['config'] == T.DEFAULT
    assert out['control_player'] == 1
    assert out['effective_training_profile'] == 'assisted'
    assert out['modifiers_changed'] is False
    assert not out['adaptive_reduction_ready']
    assert not list(tmp_path.rglob('*.json'))  # status never creates files


def test_saved_p2_request_survives_store_reload_without_any_p1_fallback(tmp_path):
    store = T.TeamStore(tmp_path)
    store.configure('worker-session', {'role': 'teammate_p2'}, game_id=T.RE5)
    ad = SimpleNamespace(name='rpcs3')
    out = T.TeamStore(tmp_path).status('worker-session', game_id=T.RE5, adapter=ad)
    assert out['config']['role'] == 'teammate_p2'
    assert out['control_player'] is None and out['phase'] == 'waiting_p2'
    assert out['config']['auto_reduce_mods'] is False
    assert T.TeamStore(tmp_path).get('worker-other') == T.DEFAULT


def test_p2_needs_actor_separate_controller_exact_adapter_session_and_fresh_proof(tmp_path):
    store = T.TeamStore(tmp_path)
    ad = SimpleNamespace(name='rpcs3')
    store.configure('worker-session', {'role': 'teammate_p2'}, game_id=T.RE5)
    proof = {'p2_verified': True, 'p2_actor_verified': True, 'controller2_verified': True,
             'camera2_verified': True, 'prompt2_verified': True,
             'active_players': [{'id': f'p{slot}', 'slot': slot, 'actor': 100+slot,
                                'provenance': {'native_actor_verified': True}} for slot in (1, 2)]}
    for change in ({'controller2_verified': False}, {'p2_verified': False}, {'active_players': [{'slot': 1}]},
                   {'active_players': [{'slot': 2}]}, {'camera2_verified': False}, {'prompt2_verified': False},
                   {'p2_actor_verified': False}, {'active_players': [proof['active_players'][0]]*2},
                   {'active_players': [dict(p, actor=123) for p in proof['active_players']]},
                   {'active_players': [dict(p, provenance={}) for p in proof['active_players']]}):
        T.publish_runtime('worker-session', ad, {**proof, **change}, now=10)
        assert store.status('worker-session', game_id=T.RE5, adapter=ad, now=11)['control_player'] is None
    T.publish_runtime('worker-session', ad, proof, now=10)
    assert store.status('worker-session', game_id=T.RE5, adapter=ad, now=11)['control_player'] == 2
    assert store.status('worker-session', game_id=T.RE5, adapter=ad, now=16)['control_player'] is None
    assert store.status('worker-session', game_id=T.RE5, adapter=SimpleNamespace(name='rpcs3'), now=11)['control_player'] is None
    store.configure('worker-other', {'role': 'teammate_p2'}, game_id=T.RE5)
    assert store.status('worker-other', game_id=T.RE5, adapter=ad, now=11)['control_player'] is None


def test_observation_never_sends_input_or_claims_verified_human_without_proof(tmp_path):
    store = T.TeamStore(tmp_path)
    ad = SimpleNamespace(name='rpcs3')
    store.configure('w-s', {'role': 'observe_human'}, game_id=T.RE5)
    out = store.status('w-s', game_id=T.RE5, adapter=ad)
    assert out['control_player'] is None and out['phase'] == 'observing_unverified'
    T.publish_runtime('w-s', ad, {'human_observer_verified': True}, now=1)
    out = store.status('w-s', game_id=T.RE5, adapter=ad, now=2)
    assert out['control_player'] is None and out['phase'] == 'observing'


def test_partial_p2_evidence_is_reported_without_authorizing_teammate_input(tmp_path):
    store = T.TeamStore(tmp_path)
    ad = SimpleNamespace(name='rpcs3')
    store.configure('w-s', {'role': 'teammate_p2'}, game_id=T.RE5)
    T.publish_runtime('w-s', ad, {'p2_actor_verified': True, 'controller2_prepared': True,
                                'camera2_verified': False, 'prompt2_verified': False}, now=1)
    out = store.status('w-s', game_id=T.RE5, adapter=ad, now=2)
    assert out['runtime']['p2_actor_verified'] and out['runtime']['controller2_prepared']
    assert out['runtime']['camera2_verified'] is False and out['runtime']['prompt2_verified'] is False
    assert out['control_player'] is None and out['phase'] == 'waiting_p2'


def test_evaluation_pauses_without_changing_modifiers_until_verified(tmp_path):
    store = T.TeamStore(tmp_path)
    ad = SimpleNamespace(name='rpcs3')
    store.configure('w-s', {'training_profile': 'unmodified_evaluation'}, game_id=T.RE5)
    out = store.status('w-s', game_id=T.RE5, adapter=ad)
    assert out['evaluation_pending'] and out['phase'] == 'waiting_evaluation'
    assert out['control_player'] is None and not out['modifiers_changed']
    T.publish_runtime('w-s', ad, {'unmodified_verified': True}, now=2)
    out = store.status('w-s', game_id=T.RE5, adapter=ad, now=3)
    assert not out['evaluation_pending'] and out['control_player'] == 1
    assert out['effective_training_profile'] == 'unmodified_evaluation'


def test_re6_remains_unsupported_even_if_unrelated_p2_flags_exist(tmp_path):
    store = T.TeamStore(tmp_path)
    ad = SimpleNamespace(name='xenia')
    store.configure('w-s', {'role': 'teammate_p2'}, game_id=T.RE6)
    T.publish_runtime('w-s', ad, {'p2_verified': True, 'controller2_verified': True,
                                'active_players': [{'slot': 2}]}, now=2)
    out = store.status('w-s', game_id=T.RE6, adapter=ad, now=3)
    assert out['control_player'] is None
    assert 'RE6' in out['capabilities']['teammate_p2']['reason']
    assert not out['capabilities']['teammate_p2']['available']


def test_selected_demonstration_requires_adoption_title_and_validated_geometry(tmp_path):
    store = T.TeamStore(tmp_path)
    rid = 'a'*32
    row = {'kind': 'recorded_demonstration', 'adopted': True, 'bot_eligible': True, 'title': 'BLUS30491',
           'mode': 'reunion', 'geometry': 'navmesh-full-id',
           'source': {'control': 'human', 'title': 'BLUS30491', 'mode': 'reunion', 'geometry': 'navmesh-full-id'}}
    for change in ({'adopted': False}, {'bot_eligible': False}, {'kind': 'drawn'}, {'title': 'BH6'},
                   {'source': {**row['source'], 'control': 'unknown'}}, {'mode': ''}, {'geometry': 'other-map'}):
        with pytest.raises(ValueError, match='adopted'):
            store.configure('w-s', {'selected_route_id': rid}, game_id=T.RE5, route_lookup=lambda _: {**row, **change})
    store.configure('w-s', {'selected_route_id': rid}, game_id=T.RE5, route_lookup=lambda _: row)
    assert store.get('w-s')['selected_route_id'] == rid
    # Revoking adoption must not block the operator from changing team ownership.
    # Guidance revalidates persisted routes before use; an old selection is no authority.
    store.configure('w-s', {'role': 'observe_human'}, game_id=T.RE5,
                    route_lookup=lambda _: {**row, 'adopted': False})
    assert store.get('w-s')['role'] == 'observe_human'
    store.configure('w-s', {'selected_route_id': None}, game_id=T.RE5)
    assert store.get('w-s')['selected_route_id'] is None


def test_invalid_or_unknown_config_does_not_replace_durable_choices(tmp_path):
    store = T.TeamStore(tmp_path)
    store.configure('w-s', {'role': 'observe_human'}, game_id=T.RE5)
    for patch in ({'role': 'p1_fallback'}, {'auto_reduce_mods': 'true'}, {'selected_route_id': '../x'}, {'godmode': True}):
        with pytest.raises(ValueError):
            store.configure('w-s', patch, game_id=T.RE5)
    assert store.get('w-s')['role'] == 'observe_human'
    with pytest.raises(ValueError):
        store.get('../other')
    assert not list(tmp_path.rglob('*.partial'))


def test_tool_uses_owned_exact_session_and_persists_intent_without_memory_or_pad_calls(tmp_path, monkeypatch):
    from gbox import tools
    class Adapter:
        name = 'rpcs3'
        proc = SimpleNamespace(poll=lambda: None)
        def send_input(self, *a):
            pytest.fail('Team configuration must not send pad input')
        def write_memory(self, *a):
            pytest.fail('Team configuration must not alter existing modifiers')
    monkeypatch.setattr(tools, 'SESSIONS', {'w-s': (Adapter(), {'game_id': T.RE5})})
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    result = TOOL.mercs_team(TOOL.TeamIn(session_id='w-s', op='configure', role='teammate_p2'), ctx)['result']
    assert result['configuration_verified'] is True and result['runtime_verified'] is False
    assert result['status']['control_player'] is None
    with pytest.raises(Exception, match='ended'):
        TOOL.mercs_team(TOOL.TeamIn(session_id='w-ended'), ctx)


def test_prepare_tool_is_explicit_future_launch_intent_not_active_p2_proof(tmp_path, monkeypatch):
    from gbox import tools
    calls = []
    row = {'player': 2, 'prepared': False, 'verified': False, 'requires_relaunch': True,
           'reason': 'Saved for next launch; Player 1 controls unchanged.'}
    class Adapter:
        name = 'rpcs3'
        proc = SimpleNamespace(poll=lambda: None)
        def prepare_teammate_pad(self, *, player):
            calls.append(player)
            return row
        def teammate_pad_status(self):
            return row
    ad = Adapter()
    monkeypatch.setattr(tools, 'SESSIONS', {'w-s': (ad, {'game_id': T.RE5})})
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    result = TOOL.mercs_team(TOOL.TeamIn(session_id='w-s', op='prepare_player2'), ctx)['result']
    assert calls == [2]
    assert result['status']['player2_preparation']['requires_relaunch'] is True
    assert result['status']['capabilities']['teammate_p2']['available'] is False
    assert result['status']['config']['role'] == 'solo_p1'
