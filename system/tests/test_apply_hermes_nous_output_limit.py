import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_hermes_nous_output_limit.py'
spec = importlib.util.spec_from_file_location('nous_output_limit_maintenance', SCRIPT)
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


def fixture_source():
    return 'from __future__ import annotations\n\nUNCHANGED = 19\n\n' + maintenance.ORIGINAL_CONSTRUCTOR + '\nAFTER = 23\n'


def construct(provider, cfg):
    source, _ = maintenance.patch_source(fixture_source())
    namespace = {
        '_resolve_cron_enabled_toolsets': lambda job, config: ['terminal', 'mcp'],
        '_resolve_cron_disabled_toolsets': lambda config: [],
    }
    exec(compile(source, '<supported-scheduler-fixture>', 'exec'), namespace)
    setup = SimpleNamespace(runtime={'provider': provider, 'requested_provider': 'nous'},
                            model='anthropic/claude-opus-5.5', max_iterations=45,
                            reasoning_config={'effort': 'high'}, prefill_messages=None,
                            fallback_model=None, credential_pool=None)
    return namespace['_construct_cron_agent'](lambda **kwargs: kwargs, {}, cfg, setup,
                                              workdir='/private/work', session_id='fixture', session_db=None)


def test_exact_constructor_delivers_cap_and_preserves_tools_reasoning_and_pinning():
    actual = construct('nous', {'cron': {'output_token_limits': {'nous': 8192}}})
    assert actual['max_tokens'] == 8192
    assert actual['provider'] == 'nous'
    assert actual['model'] == 'anthropic/claude-opus-5.5'
    assert actual['fallback_model'] is None
    assert actual['max_iterations'] == 45
    assert actual['reasoning_config'] == {'effort': 'high'}
    assert actual['enabled_toolsets'] == ['terminal', 'mcp']
    assert actual['skip_background_review'] is True


@pytest.mark.parametrize('provider', ['openrouter', 'deepseek', 'ollama-cloud', 'zai', None])
def test_requested_nous_does_not_cap_an_actual_other_provider(provider):
    assert construct(provider, {'cron': {'output_token_limits': {'nous': 8192}}})['max_tokens'] is None


@pytest.mark.parametrize('value', [None, 0, -1, True, False, 8192.0, '8192', [], {}])
def test_invalid_limits_leave_native_default(value):
    assert construct('nous', {'cron': {'output_token_limits': {'nous': value}}})['max_tokens'] is None


@pytest.mark.parametrize('cfg', [{}, {'cron': None}, {'cron': []}, {'cron': {'output_token_limits': None}},
                                 {'cron': {'output_token_limits': []}}])
def test_absent_or_malformed_config_preserves_default(cfg):
    assert construct('nous', cfg)['max_tokens'] is None


def test_idempotent_structural_patch_preserves_surrounding_code_and_comments():
    original = fixture_source().replace('    return AIAgent(', '    # Native existing constructor comment\n    return AIAgent(')
    once, changed = maintenance.patch_source(original)
    twice, changed_again = maintenance.patch_source(once)
    assert changed and not changed_again and twice == once
    assert 'Native existing constructor comment' in once
    assert once.startswith('from __future__ import annotations\n\nUNCHANGED = 19')
    assert once.endswith('AFTER = 23\n')


@pytest.mark.parametrize('source', [
    fixture_source().replace('max_iterations=setup.max_iterations', 'max_iterations=12'),
    fixture_source().replace('request_overrides=runtime.get("request_overrides"),', 'request_overrides=None,'),
    fixture_source() + '\n_gbox_nous_cron_output_tokens = None\n',
    fixture_source() + '\n' + maintenance.ORIGINAL_CONSTRUCTOR,
])
def test_unknown_or_ambiguous_runtime_fails_closed(source):
    with pytest.raises(maintenance.UnsupportedScheduler):
        maintenance.patch_source(source)


def test_tampered_or_missing_existing_helper_fails_closed():
    patched, _ = maintenance.patch_source(fixture_source())
    with pytest.raises(maintenance.UnsupportedScheduler):
        maintenance.patch_source(patched.replace('value > 0', 'value >= 0'))
    with pytest.raises(maintenance.UnsupportedScheduler):
        maintenance.patch_source(patched.replace(maintenance.HELPER + '\n\n', ''))


def test_check_only_backup_and_idempotent_apply(tmp_path):
    parent = tmp_path / 'cron'
    parent.mkdir()
    path = parent / 'scheduler.py'
    before = fixture_source().replace('\n', '\r\n').encode()
    path.write_bytes(before)
    checked = maintenance.apply_file(path)
    assert checked['status'] == 'compatible' and not checked['applied']
    assert path.read_bytes() == before and list(parent.iterdir()) == [path]
    applied = maintenance.apply_file(path, apply=True)
    assert applied['applied'] and Path(applied['backup']).read_bytes() == before
    after = path.read_bytes()
    assert b'\r\n' in after and b'\n' not in after.replace(b'\r\n', b'')
    repeated = maintenance.apply_file(path, apply=True)
    assert repeated['status'] == 'already_applied' and not repeated['applied']
    assert len(list(parent.glob('*.bak'))) == 1 and path.read_bytes() == after


def test_unknown_version_never_creates_backup_or_changes_file(tmp_path):
    parent = tmp_path / 'cron'
    parent.mkdir()
    path = parent / 'scheduler.py'
    before = b'def different_scheduler():\n    pass\n'
    path.write_bytes(before)
    with pytest.raises(maintenance.UnsupportedScheduler):
        maintenance.apply_file(path, apply=True)
    assert path.read_bytes() == before and list(parent.iterdir()) == [path]
