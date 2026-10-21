import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location('compression_config',
    Path(__file__).resolve().parents[1] / 'scripts/configure_hermes_compression.py')
configurer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configurer)


@pytest.fixture
def files(tmp_path):
    config = {'auxiliary': {'compression': {'provider': 'custom', 'model': 'Qwen/Qwen3-Coder-Next-FP8',
        'base_url': 'http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1', 'timeout': 300,
        'api_key': 'private-test-key'}}, 'compression': {'threshold': 0.5, 'abort_on_summary_failure': False},
        'providers': {'other': {'api_key': 'other-private-key'}}, 'capacity': 24}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    runtime = tmp_path / 'hermes-agent'
    helper = runtime / 'agent/conversation_compression_deadline.py'
    helper.parent.mkdir(parents=True)
    helper.write_text('def resolve_context_compression_timeouts(cfg):\n'
                      '    return 300, cfg.get("context_total_ceiling_seconds", 600)\n')
    return path, runtime, config


def test_dry_run_then_apply_changes_only_total_ceiling_and_backs_up_exact_bytes(files):
    path, runtime, original = files
    before = path.read_bytes()
    dry = configurer.configure(path, runtime)
    assert dry['status'] == 'ready' and not dry['applied']
    assert path.read_bytes() == before and not (path.parent / 'config-backups').exists()
    result = configurer.configure(path, runtime, apply=True)
    assert result['applied'] and not result['restart_required']
    assert Path(result['backup']).read_bytes() == before
    expected = copy.deepcopy(original)
    expected['compression']['context_total_ceiling_seconds'] = 1200
    assert yaml.safe_load(path.read_bytes()) == expected
    assert 'private' not in json.dumps(result)
    saved = path.read_bytes()
    assert configurer.configure(path, runtime, apply=True)['status'] == 'already_applied'
    assert path.read_bytes() == saved and len(list((path.parent / 'config-backups').iterdir())) == 1


@pytest.mark.parametrize('section,key,value', [
    ('route', 'provider', 'paid'), ('route', 'model', 'other-model'),
    ('route', 'base_url', 'http://remote.example/v1'), ('route', 'timeout', 600),
    ('compression', 'context_timeout_seconds', 0), ('compression', 'context_timeout_seconds', 900),
    ('compression', 'context_total_ceiling_seconds', 1800),
    ('compression', 'context_total_ceiling_seconds', True),
])
def test_custom_routes_and_watchdog_overrides_are_preserved(files, section, key, value):
    path, runtime, config = files
    target = config['auxiliary']['compression'] if section == 'route' else config['compression']
    target[key] = value
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        configurer.configure(path, runtime, apply=True)
    assert path.read_bytes() == before
    assert not (path.parent / 'config-backups').exists()


def test_unsupported_runtime_and_parse_errors_do_not_expose_config(files, capsys):
    path, runtime, _ = files
    helper = runtime / 'agent/conversation_compression_deadline.py'
    before = path.read_bytes()
    helper.write_text('def resolve_context_compression_timeouts(cfg):\n    return 300, 600\n')
    assert configurer.main([str(path), str(runtime), '--apply']) == 2
    assert path.read_bytes() == before
    helper.write_text('def resolve_context_compression_timeouts(cfg):\n'
                      '    return 300, cfg.get("context_total_ceiling_seconds", 600)\n')
    path.write_text('api_key: [secret-value\n', encoding='utf-8')
    assert configurer.main([str(path), str(runtime)]) == 2
    assert 'secret' not in capsys.readouterr().out


def test_concurrent_config_edit_is_not_overwritten(files, monkeypatch):
    path, runtime, _ = files
    original = path.read_bytes()
    newer = original + b'operator_new_setting: true\n'
    chmod = configurer.os.chmod

    def edit_before_replace(temporary, mode):
        chmod(temporary, mode)
        path.write_bytes(newer)

    monkeypatch.setattr(configurer.os, 'chmod', edit_before_replace)
    with pytest.raises(ValueError, match='changed during preparation'):
        configurer.configure(path, runtime, apply=True)
    assert path.read_bytes() == newer
    assert next((path.parent / 'config-backups').iterdir()).read_bytes() == original
    assert not list(path.parent.glob('.gbox-compression-*'))
