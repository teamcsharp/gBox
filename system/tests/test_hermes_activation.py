import pytest

from gbox.hermes_activation import idle_reason, verify_activation


def test_activation_preserves_busy_work_and_spark_games():
    tasks = {'jobs': [], 'machines': [{'worker_id': 'spark', 'os': 'linux'}]}
    windows = {'session_id': 'windows-game', 'state': 'running', 'detail': {'pid': 123}}
    assert not idle_reason([], tasks, [windows])
    assert idle_reason([{'busy': True}], tasks, [windows])
    assert idle_reason([], tasks | {'jobs': [{'state': 'running'}]}, [windows])
    assert idle_reason([], tasks, [{'session_id': 'spark-game', 'state': 'running'}])


def test_activation_requires_loaded_bridge_and_original_emulator_process():
    policy = {'fallback_enabled': True, 'max_parallel_jobs': 2, 'image_input_mode': 'text'}
    before = [{'session_id': 'windows-game', 'state': 'running', 'detail': {'pid': 123}}]
    verify_activation(policy, before, before)
    with pytest.raises(RuntimeError, match='not loaded'):
        verify_activation({}, before, before)
    with pytest.raises(RuntimeError, match='original PID'):
        verify_activation(policy, before, [])
    with pytest.raises(RuntimeError, match='original PID'):
        verify_activation(policy, [{'session_id': 'windows-game', 'state': 'running'}], [])


def test_later_activation_can_require_its_own_loaded_policy_fields():
    with pytest.raises(RuntimeError, match='not loaded'):
        verify_activation({'fallback_enabled': True}, [], [], {'git_workspace_ready'})
    verify_activation({'git_workspace_ready': True}, [], [], {'git_workspace_ready'})
