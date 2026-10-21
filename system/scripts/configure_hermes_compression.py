"""Give the measured Spark2 compression route a bounded 1200-second total budget.

Dry run by default. Only the host total ceiling changes; route, idle watchdog,
auxiliary timeout, concurrency and spending limits are preserved.
"""
from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile

import yaml

KEY = 'context_total_ceiling_seconds'
CEILING = 1200


def planned_config(config):
    """Refuse other routes or operator overrides; return an isolated proposal."""
    if not isinstance(config, dict):
        raise ValueError('Hermes config must be a mapping')
    auxiliary = config.get('auxiliary') or {}
    route = auxiliary.get('compression') if isinstance(auxiliary, dict) else None
    if (not isinstance(route, dict) or route.get('provider') != 'custom'
            or route.get('model') != 'Qwen/Qwen3-Coder-Next-FP8'
            or route.get('base_url') != 'http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1'
            or type(route.get('timeout')) not in (int, float) or route['timeout'] != 300):
        raise ValueError('Expected the measured Spark2 compression route with a 300-second auxiliary timeout')
    compression = config.get('compression', {})
    if not isinstance(compression, dict):
        raise ValueError('Hermes compression settings must be a mapping')
    idle = compression.get('context_timeout_seconds', 120)
    before = compression.get(KEY, 600)
    if type(idle) not in (int, float) or idle not in (120, 300):
        raise ValueError('Custom compression idle timeout is preserved; automatic tuning refused')
    if type(before) not in (int, float) or before not in (600, CEILING):
        raise ValueError('Custom compression total ceiling is preserved; automatic tuning refused')
    proposal = copy.deepcopy(config)
    proposal.setdefault('compression', {})[KEY] = CEILING
    return proposal, before


def configure(config_path, runtime, *, apply=False):
    path = Path(config_path).expanduser().resolve(strict=True)
    helper = Path(runtime).expanduser() / 'agent/conversation_compression_deadline.py'
    tree = ast.parse(helper.read_text(encoding='utf-8'))
    resolver = next((node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'resolve_context_compression_timeouts'), None)
    if resolver is None or not any(isinstance(node, ast.Constant) and node.value == KEY
                                   for node in ast.walk(resolver)):
        raise ValueError('Installed Hermes does not expose the supported compression total ceiling')
    original = path.read_bytes()
    config = yaml.safe_load(original)
    proposal, before = planned_config(config)
    receipt = {'status': 'already_applied' if before == CEILING else 'ready', 'applied': False,
               'setting': 'compression.' + KEY, 'before': before, 'after': CEILING,
               'effective_idle_seconds': 300, 'restart_required': False}
    if not apply or before == CEILING:
        return receipt
    output = yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True).encode('utf-8')
    if yaml.safe_load(output) != proposal:
        raise ValueError('Hermes config round trip failed')
    mode = stat.S_IMODE(path.stat().st_mode)
    backups = path.parent / 'config-backups'
    backups.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backups / (path.name + '.before-compression-ceiling-' + stamp)
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.gbox-compression-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if path.read_bytes() != original:
            raise ValueError('Hermes config changed during preparation; update refused')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if yaml.safe_load(path.read_bytes()) != proposal:
        raise ValueError('Hermes config readback differs; private backup is available')
    receipt.update(status='applied', applied=True, backup=str(backup))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('runtime', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(configure(args.config, args.runtime, apply=args.apply), indent=2))
        return 0
    except (ValueError, OSError, SyntaxError, yaml.YAMLError) as error:
        # YAML parse errors can contain credential-bearing lines: only the type is public.
        print(json.dumps({'status': 'refused', 'error_type': type(error).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
