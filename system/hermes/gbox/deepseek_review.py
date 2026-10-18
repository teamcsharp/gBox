"""Credential-isolated DeepSeek transport for the result-review controller.

Run as a file so Hermes bootstrap can re-exec into its managed environment.
Only sanitized status, balance, usage and model output leave this process.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / '.hermes/hermes-agent'))


def main():
    import hermes_bootstrap  # noqa: F401 - may re-exec this file
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from decimal import Decimal
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
    import socket

    runtime = resolve_runtime_provider(requested='deepseek', target_model='deepseek-v4-pro')
    key = runtime.get('api_key')
    if runtime.get('provider') != 'deepseek' or not key:
        return {'error': 'credential_unavailable'}

    def call(path, body=None):
        req = Request('https://api.deepseek.com/' + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=300 if body is not None else 20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Response exceeded limit')
        return json.loads(raw)

    try:
        balance = call('user/balance')
        available = balance.get('is_available') is True and any(
            Decimal(str(row.get('total_balance', '0'))) > 0 for row in balance.get('balance_infos', []))
        if not available:
            return {'error': 'out_of_credit', 'balance': balance}
        packet = json.load(sys.stdin)
        if packet.get('balance_only'):
            return {'balance': balance}
        result = call('chat/completions', {
            'model': 'deepseek-v4-pro', 'messages': packet['messages'],
            'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low',
            'response_format': {'type': 'json_object'}, 'max_tokens': 16000 if packet.get('review_kind') == 'pr' else 8000,
        })
        return {'balance': balance, 'usage': result.get('usage'),
                'finish_reason': result['choices'][0].get('finish_reason'),
                'content': result['choices'][0]['message']['content']}
    except HTTPError as exc:
        return {'error': 'http_' + str(exc.code)}
    except URLError as exc:
        return {'error': 'dns_unavailable' if isinstance(exc.reason, socket.gaierror) else
                'provider_timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'network_unavailable'}
    except (TimeoutError, socket.timeout):
        return {'error': 'provider_timeout'}
    except OSError:
        return {'error': 'network_unavailable'}
    except (ValueError, KeyError, TypeError):
        return {'error': 'invalid_provider_response'}


if __name__ == '__main__':
    try:
        print(json.dumps(main()))
    except Exception:
        # Never propagate resolver errors containing authentication material.
        print(json.dumps({'error': 'transport_setup_failed'}))
