"""Excluded local providers never become Hermes cron routes, wherever they are listed."""
from gbox import hermes_quota


CONFIG = {'cron': {'model_provider': 'nous', 'model': 'anthropic/claude-opus-5.5'},
          'fallback_providers': [{'provider': 'openrouter', 'model': 'anthropic/claude-opus-5.5'},
                                 {'provider': 'llamacpp', 'model': 'Qwen3.6-35B-A3B-UD-Q4_K_M'},
                                 {'provider': 'EhmBird', 'model': 'qwen3.8:27b-mtp-q4_K_M'}]}
SAVED = [{'provider': 'llamacpp', 'model': 'Qwen3.6-35B-A3B-UD-Q4_K_M'}, {'provider': 'zai', 'model': 'glm-5.3'}]


def test_default_excludes_cpu_and_ehmbird(monkeypatch):
    monkeypatch.delenv('GBOX_HERMES_EXCLUDED_PROVIDERS', raising=False)
    got = [r['provider'] for r in hermes_quota.routes(CONFIG, SAVED)]
    assert got == ['nous', 'openrouter', 'zai']


def test_env_override(monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_EXCLUDED_PROVIDERS', '')
    assert [r['provider'] for r in hermes_quota.routes(CONFIG, SAVED)] == ['nous', 'openrouter', 'llamacpp', 'EhmBird', 'zai']
    monkeypatch.setenv('GBOX_HERMES_EXCLUDED_PROVIDERS', 'OpenRouter')
    assert 'openrouter' not in [r['provider'] for r in hermes_quota.routes(CONFIG, SAVED)]
