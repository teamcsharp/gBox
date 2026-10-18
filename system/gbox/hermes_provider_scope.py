"""Operator-owned provider scope for gBox private backlog admission.

Not an inference tool or a public-research dispatcher. Request text/config cannot
supply the purpose or relax this separate policy. No credentials are persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from . import hermes_delivery

MAX_POLICY_BYTES = 65536
SCOPE = 'public_source_only'

# Provider spelling aliases observed in Hermes providers.py; identity normalization,
# not a restriction. Policies remain installation-specific and opt-in.
_ALIAS_GROUPS = {'openrouter': ('openai',),
 'zai': ('glm', 'z-ai', 'z.ai', 'zhipu'),
 'xai': ('x-ai', 'x.ai', 'grok'),
 'xai-oauth': ('grok-oauth', 'xai-oauth', 'x-ai-oauth', 'xai-grok-oauth'),
 'nvidia': ('nim', 'nvidia-nim', 'build-nvidia', 'nemotron'),
 'kimi-for-coding': ('kimi', 'kimi-coding', 'kimi-coding-cn', 'moonshot'),
 'stepfun': ('step', 'stepfun-coding-plan'),
 'minimax-cn': ('minimax-china', 'minimax_cn'),
 'anthropic': ('claude', 'claude-code'),
 'github-copilot': ('copilot', 'github'),
 'copilot-acp': ('github-copilot-acp',),
 'openai-codex': ('chatgpt', 'chatgpt-codex'),
 'vercel': ('ai-gateway', 'aigateway', 'vercel-ai-gateway'),
 'opencode': ('opencode-zen', 'zen'),
 'opencode-go': ('go', 'opencode-go-sub'),
 'kilo': ('kilocode', 'kilo-code', 'kilo-gateway'),
 'deepseek': ('deep-seek',),
 'alibaba': ('dashscope', 'aliyun', 'qwen', 'alibaba-cloud'),
 'alibaba-coding-plan': ('alibaba_coding', 'alibaba-coding', 'alibaba_coding_plan'),
 'huggingface': ('hf', 'hugging-face', 'huggingface-hub'),
 'novita': ('novita-ai', 'novitaai'),
 'xiaomi': ('mimo', 'xiaomi-mimo'),
 'tencent-tokenhub': ('tencent', 'tokenhub', 'tencent-cloud', 'tencentmaas'),
 'tencent-tokenplan': ('tokenplan', 'tencent-lkeap'),
 'bedrock': ('aws', 'aws-bedrock', 'amazon-bedrock', 'amazon'),
 'arcee': ('arcee-ai', 'arceeai'),
 'gmi': ('gmi-cloud', 'gmicloud'),
 'fireworks': ('fireworks-ai', 'fw'),
 'upstage': ('solar',),
 'actual': ('actual-computer', 'actualcomputer', 'aci'),
 'nebius-token-factory': ('nebius',
                          'nebius-tokenfactory',
                          'nebius-tf',
                          'token-factory',
                          'tokenfactory'),
 'lmstudio': ('lmstudio', 'lm-studio', 'lm_studio'),
 'custom': ('ollama', 'local', 'vllm', 'llamacpp', 'llama.cpp', 'llama-cpp')}
_ALIASES = {alias: canonical for canonical, names in _ALIAS_GROUPS.items() for alias in names}


def path():
    return hermes_delivery.state_dir() / 'provider-scopes.json'


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid provider scope identifier')
    return value.strip().casefold()


def _host(value):
    value = _name(value).rstrip('.')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '..' in value:
        raise ValueError('endpoint host must be a DNS host without URL, port or credentials')
    return value


def validate(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'rules'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('unsupported provider scope policy')
    rules = value['rules']
    if not isinstance(rules, list) or len(rules) > 128:
        raise ValueError('invalid provider scope rules')
    clean = []
    for row in rules:
        if not isinstance(row, dict) or set(row) != {'scope', 'providers', 'endpoint_hosts'} or row['scope'] != SCOPE:
            raise ValueError('invalid provider scope rule')
        lists = [row['providers'], row['endpoint_hosts']]
        if any(not isinstance(v, list) or len(v) > 64 for v in lists) or not any(lists):
            raise ValueError('invalid provider scope matches')
        clean.append({'scope': SCOPE, 'providers': sorted({_name(x) for x in lists[0]}),
                      'endpoint_hosts': sorted({_host(x) for x in lists[1]})})
    return {'schema': 1, 'rules': clean}


def read():
    try:
        with path().open('rb') as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
    except FileNotFoundError:
        return {'schema': 1, 'rules': []}
    except OSError:
        return {'error': 'Provider scope policy is unreadable; private backlog admission deferred'}
    try:
        if len(raw) > MAX_POLICY_BYTES:
            raise ValueError('policy size')
        return validate(json.loads(raw))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {'error': 'Provider scope policy is invalid; private backlog admission deferred'}


def _identities(value):
    name = str(value or '').strip().casefold().replace(' ', '-')
    named = name.removeprefix('custom:')
    identities = {name, named}
    if not name.startswith('custom:'):
        identities.add(_ALIASES.get(name, name))
    return identities - {''}


def _model(config):
    raw = config.get('model') or {}
    model = dict(raw) if isinstance(raw, dict) else {}
    default = model.get('default') or model.get('model') or model.get('name')
    if isinstance(default, dict):
        model['provider'] = model.get('provider') or default.get('provider')
    model['provider'] = model.get('provider') or config.get('provider')
    model['base_url'] = (model.get('base_url') or model.get('api_base') or
                         config.get('base_url') or config.get('api_base'))
    return model


def _endpoint(entry):
    """Installed config_providers.py URL order, without credentials or env expansion."""
    attempted = False
    for key in ('base_url', 'baseUrl', 'url', 'api'):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        attempted = True
        if '{' in value or '}' in value:
            raise ValueError('unresolved endpoint template')
        try:
            parsed = urlsplit(value)
            if parsed.scheme and parsed.hostname:
                return value
        except ValueError:
            pass
    if attempted:
        raise ValueError('unresolved endpoint')
    return None


def reason(item, config, *, policy=None):
    """A safe public reason, or None. This function always means PRIVATE backlog."""
    policy = read() if policy is None else policy
    if policy.get('error'):
        return policy['error']
    if not policy['rules']:
        return None
    if not isinstance(item, dict) or not isinstance(item.get('provider'), str) or not item['provider'].strip():
        return 'Provider identity is unavailable; private backlog admission deferred'
    identities = _identities(item['provider'])
    for rule in policy['rules']:
        if any(identities.intersection(_identities(name)) for name in rule['providers']):
            return 'Operator policy restricts this provider to public-source research; private backlog is not authorized'
    endpoints, matched = [], False
    try:
        endpoint = _endpoint(item)
        if endpoint:
            endpoints.append(endpoint)
        legacy = config.get('custom_providers') or []
        providers = config.get('providers') or {}
        if not isinstance(legacy, list) or not isinstance(providers, dict):
            raise ValueError('invalid endpoint registry')
        entries = [(None, e) for e in legacy] + list(providers.items())
        for key, entry in entries:
            if not isinstance(entry, dict):
                continue
            names = _identities(key) | _identities(entry.get('name')) | _identities(entry.get('provider_key'))
            if identities.intersection(names):
                matched = True
                endpoint = _endpoint(entry)
                if not endpoint:
                    raise ValueError('named endpoint unresolved')
                endpoints.append(endpoint)
        model = _model(config)
        # Bare custom uses the configured endpoint even with cron.model_provider.
        # Registered-provider overrides use it only for the same provider identity.
        if ('custom' in identities or identities.intersection(_identities(model.get('provider')))):
            endpoint = _endpoint(model)
            if endpoint:
                endpoints.append(endpoint)
        if item['provider'].strip().casefold().startswith('custom:') and not matched and not endpoints:
            raise ValueError('named endpoint unresolved')
        if 'custom' in identities and not endpoints:
            raise ValueError('bare custom endpoint unresolved')
        if 'auto' in identities:
            raise ValueError('automatic provider identity unresolved')
        hosts = {urlsplit(url).hostname.casefold().rstrip('.') for url in endpoints}
    except (ValueError, AttributeError, TypeError):
        return 'Provider endpoint identity is unresolved; private backlog admission deferred'
    for rule in policy['rules']:
        if hosts.intersection(rule['endpoint_hosts']):
            return 'Operator policy restricts this provider to public-source research; private backlog is not authorized'
    return None


def inherited_fallbacks(config):
    # Installed fallback_config merges both keys, each accepting a list or dict.
    # Preserve malformed entries for the private admission check to fail closed.
    rows = []
    for key in ('fallback_providers', 'fallback_model'):
        value = config.get(key)
        if value is None:
            continue
        rows.extend(value if isinstance(value, list) else [value])
    return rows


def admission(config, selected=None):
    """Check actual inherited routes, not just the supervisor's filtered view.

    Pinned jobs may inherit global fallbacks too. Conservatively hold admission
    until the normal between-run supervisor has removed any restricted fallback.
    """
    policy = read()
    cron = config.get('cron') or {}
    model = _model(config)
    primary = {'provider': cron.get('model_provider') or model.get('provider'),
               'model': cron.get('model') or model.get('default')}
    if not primary['provider'] and selected is not None:
        primary = selected
    routes = [('primary', primary)]
    if selected is not None:
        effective = dict(primary)
        effective.update({k: v for k, v in selected.items() if v is not None})
        routes.append(('selected', effective))
    routes += [('fallback', item) for item in inherited_fallbacks(config)]
    for kind, item in routes:
        why = reason(item, config, policy=policy)
        if why:
            return {'route': kind, 'reason': why}
    return None


def restrict(providers, endpoint_hosts, *, apply=False):
    """Trusted local maintenance only: additive restrictions, never relaxations."""
    rule = validate({'schema': 1, 'rules': [{'scope': SCOPE, 'providers': providers,
                                            'endpoint_hosts': endpoint_hosts}]})['rules'][0]
    with hermes_delivery.locked('provider-scopes'):
        old = read()
        if old.get('error'):
            raise ValueError(old['error'])
        new = {'schema': 1, 'rules': list(old['rules'])}
        if rule not in new['rules']:
            new['rules'].append(rule)
        raw = (json.dumps(validate(new), indent=2) + '\n').encode()
        if len(raw) > MAX_POLICY_BYTES:
            raise ValueError('provider scope policy exceeds size limit')
        changed = new != old
        if apply and changed:
            target = path()
            fd, temporary = tempfile.mkstemp(prefix='.provider-scopes-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return {'applied': bool(apply and changed), 'would_change': changed,
                'policy': new, 'serialized_sha256': hashlib.sha256(raw).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    change = sub.add_parser('restrict', help='add a restriction; dry run unless --apply')
    change.add_argument('--provider', action='append', default=[])
    change.add_argument('--endpoint-host', action='append', default=[])
    change.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    result = read() if args.command == 'status' else restrict(args.provider, args.endpoint_host, apply=args.apply)
    print(json.dumps(result, indent=2))
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
