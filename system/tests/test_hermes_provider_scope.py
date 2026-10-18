import json
from pathlib import Path

import pytest

from gbox import hermes_provider_scope as scope, hermes_quota, hermes_local
from gbox.config import HermesLocalConfig


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))


def policy():
    scope.restrict(['ZAI'], ['API.Z.AI.'], apply=True)


def route(provider='zai'):
    return {'provider': provider, 'model': 'glm'}


def config(provider='nous', **more):
    return {'cron': {'model_provider': provider, 'model': 'glm'}, **more}


def test_absent_policy_keeps_other_installations_unchanged_and_dry_run_does_not_install():
    assert hermes_quota.routes(config('zai')) == [route()]
    preview = scope.restrict(['ZAI'], ['API.Z.AI.'])
    assert preview['would_change'] and not preview['applied'] and not scope.path().exists()
    assert not scope.admission(config('zai'))
    applied = scope.restrict(['ZAI'], ['API.Z.AI.'], apply=True)
    assert applied['applied'] and applied['serialized_sha256'] == preview['serialized_sha256']
    assert not scope.restrict(['zai'], ['api.z.ai'], apply=True)['applied']


def test_restrictions_are_additive_and_do_not_modify_hermes_config(tmp_path):
    original = tmp_path / 'config.yaml'; original.write_text('api_key: secret\n')
    policy(); scope.restrict(['another'], [], apply=True)
    assert len(scope.read()['rules']) == 2 and original.read_text() == 'api_key: secret\n'
    assert scope.reason(route('another'), {}) and scope.reason(route(), {})


@pytest.mark.parametrize('provider', ['zai', 'ZAI', ' ZaI '])
def test_saved_current_preferred_and_environment_override_cannot_restore_restricted_provider(monkeypatch, provider):
    policy(); monkeypatch.setenv('GBOX_HERMES_EXCLUDED_PROVIDERS', '')
    cfg = config(provider, fallback_providers=[route('nous'), route(provider)])
    cfg['cron'].update(preferred_provider=provider, preferred_model='glm')
    assert hermes_quota.routes(cfg, [route(provider)]) == [route('nous')]
    selected = hermes_local.choose([route(provider), route('nous')], {}, 1, primary=route(provider),
        preferred=route(provider), s=HermesLocalConfig(enabled=False), only_local=False, config=cfg)
    assert selected['route'] == route('nous') and not selected['fallbacks']
    assert scope.admission(cfg)['route'] == 'primary'


@pytest.mark.parametrize('url', ['https://API.Z.AI/api/coding/paas/v4', 'https://api.z.ai.:443/v1',
                                  'https://ignored-user:ignored-secret@api.z.ai/v1'])
def test_alias_host_matches_actual_url_without_exposing_credentials(url):
    policy()
    cfg = config('safe-alias', custom_providers=[{'name': 'SAFE-ALIAS', 'base_url': url, 'api_key': 'secret'}])
    assert hermes_quota.routes(cfg) == []
    why = scope.admission(cfg)
    assert why and 'secret' not in json.dumps(why) and 'https' not in json.dumps(why)
    assert scope.reason(route('unregistered'), {}, policy=scope.read()) is None


def test_hosts_match_exactly_not_by_substring_and_raw_fallback_url_is_checked():
    policy()
    for host in ['notapi.z.ai', 'api.z.ai.evil.test', 'other.example']:
        assert not scope.reason(route('alias') | {'base_url': 'https://' + host}, {})
    cfg = config(fallback_providers=[route('alias') | {'base_url': 'https://api.z.ai/v1'}])
    assert scope.admission(cfg)['route'] == 'fallback'
    assert hermes_quota.routes(cfg) == [route('nous')]


def test_selected_node_and_raw_inherited_fallback_are_checked_even_when_local_only():
    policy()
    cfg = config('local', fallback_providers=[route()])
    assert scope.admission(cfg, route('local'))['route'] == 'fallback'
    assert scope.admission(config(), route())['route'] == 'selected'
    assert scope.admission(config(), route('local')) is None


@pytest.mark.parametrize('bad', [b'{', b'[]', b'{"schema":true,"rules":[]}',
    b'{"schema":1,"rules":[{"scope":"all","providers":["zai"],"endpoint_hosts":[]}]}',
    b'x' * (scope.MAX_POLICY_BYTES + 1)])
def test_invalid_present_policy_fails_closed_for_all_private_routes(bad):
    scope.path().write_bytes(bad)
    assert scope.admission(config()) and hermes_quota.routes(config()) == []
    assert scope.read().get('error')
    with pytest.raises(ValueError): scope.restrict(['zai'], [], apply=True)


def test_unreadable_policy_fails_closed(monkeypatch):
    actual = Path.open
    def denied(self, *a, **kw):
        if self == scope.path(): raise PermissionError('private filesystem detail')
        return actual(self, *a, **kw)
    monkeypatch.setattr(Path, 'open', denied)
    assert 'unreadable' in scope.admission(config())['reason']
    assert 'private filesystem detail' not in json.dumps(scope.read())


@pytest.mark.parametrize('fallback', [[None], [{'model': 'glm'}], 'zai'])
def test_unknown_raw_fallback_identity_is_not_assumed_safe(fallback):
    policy()
    assert scope.admission(config(fallback_providers=fallback))


def test_inbox_or_model_configuration_cannot_grant_public_scope():
    policy()
    cfg = config('zai', purpose='public_source_research', provider_scopes={'rules': []})
    assert scope.admission(cfg | {'request': {'context': {'purpose': 'public_source_research'}}})


def test_cli_has_no_relaxation_or_tool_mutation_interface(capsys):
    assert scope.main(['restrict', '--provider', 'zai']) == 0
    assert not scope.path().exists()
    assert scope.main(['restrict', '--provider', 'zai', '--apply']) == 0
    assert scope.main(['status']) == 0
    with pytest.raises(SystemExit): scope.main(['allow', '--provider', 'zai'])


def test_base_url_only_pin_uses_effective_provider_but_cannot_hide_restricted_endpoint():
    policy()
    assert scope.admission(config(), {'base_url': 'https://api.z.ai/v1'})['route'] == 'selected'
    assert not scope.admission(config(), {'base_url': 'https://safe.example/v1'})
    assert scope.admission({'model': {'provider': 'zai', 'default': 'glm'}})
    assert scope.admission(config(), {'provider': 'alias', 'base_url': 'invalid-relative-url'})
