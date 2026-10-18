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
    except (ValueError, TypeError, UnicodeError):
        return {'error': 'Provider scope policy is invalid; private backlog admission deferred'}


def reason(item, config, *, policy=None):
    """A safe public reason, or None. This function always means PRIVATE backlog."""
    policy = read() if policy is None else policy
    if policy.get('error'):
        return policy['error']
    if not policy['rules']:
        return None
    if not isinstance(item, dict) or not isinstance(item.get('provider'), str) or not item['provider'].strip():
        return 'Provider identity is unavailable; private backlog admission deferred'
    provider = item['provider'].strip().casefold()
    endpoints = [item.get('base_url')]
    for entry in config.get('custom_providers') or []:
        if isinstance(entry, dict) and str(entry.get('name') or '').strip().casefold() == provider:
            endpoints.append(entry.get('base_url'))
    hosts = set()
    for endpoint in endpoints:
        if endpoint:
            try:
                host = urlsplit(str(endpoint)).hostname
                if not host:
                    return 'Provider endpoint identity is invalid; private backlog admission deferred'
                hosts.add(host.casefold().rstrip('.'))
            except ValueError:
                return 'Provider endpoint identity is invalid; private backlog admission deferred'
    for rule in policy['rules']:
        if provider in rule['providers'] or hosts.intersection(rule['endpoint_hosts']):
            return 'Operator policy restricts this provider to public-source research; private backlog is not authorized'
    return None


def admission(config, selected=None):
    """Check actual inherited routes, not just the supervisor's filtered view.

    Pinned jobs may inherit global fallbacks too. Conservatively hold admission
    until the normal between-run supervisor has removed any restricted fallback.
    """
    policy = read()
    cron = config.get('cron') or {}
    model = config.get('model') or {}
    model = model if isinstance(model, dict) else {}
    primary = {'provider': cron.get('model_provider') or model.get('provider'),
               'model': cron.get('model') or model.get('default')}
    if not cron.get('model_provider') and model.get('base_url'):
        primary['base_url'] = model['base_url']
    if not primary['provider'] and selected is not None:
        primary = selected
    routes = [('primary', primary)]
    if selected is not None:
        effective = dict(primary)
        effective.update({k: v for k, v in selected.items() if v is not None})
        routes.append(('selected', effective))
    fallbacks = config.get('fallback_providers') or []
    if policy.get('rules') and not isinstance(fallbacks, list):
        return {'route': 'fallback', 'reason': 'Inherited provider fallback identity is invalid; private backlog admission deferred'}
    routes += [('fallback', item) for item in fallbacks]
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
