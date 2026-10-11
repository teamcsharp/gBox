"""Add an initial Nous cron output budget to the supported Hermes constructor.

Usage: python apply_hermes_nous_output_limit.py /path/to/hermes-agent/cron/scheduler.py --apply
Without --apply this checks compatibility only. It never changes Hermes config or starts jobs.
The setting introduced is cron.output_token_limits.nous: 8192. This is an initial
request budget; Hermes's existing truncation retry ladder can increase it.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from datetime import datetime, timezone


ORIGINAL_CONSTRUCTOR = '''def _construct_cron_agent(AIAgent, job: dict, _cfg: dict, setup: _CronAgentSetup, *, workdir, session_id, session_db):
    runtime = setup.runtime
    pr = _cfg.get("provider_routing") or {}
    return AIAgent(
        model=setup.model,
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        requested_provider=runtime.get("requested_provider"),
        api_mode=runtime.get("api_mode"),
        request_overrides=runtime.get("request_overrides"),
        acp_command=runtime.get("command"),
        acp_args=runtime.get("args"),
        max_iterations=setup.max_iterations,
        reasoning_config=setup.reasoning_config,
        prefill_messages=setup.prefill_messages,
        fallback_model=setup.fallback_model,
        credential_pool=setup.credential_pool,
        providers_allowed=pr.get("only"),
        providers_ignored=pr.get("ignore"),
        providers_order=pr.get("order"),
        provider_sort=pr.get("sort"),
        openrouter_min_coding_score=(_cfg.get("openrouter") or {}).get("min_coding_score"),
        enabled_toolsets=_resolve_cron_enabled_toolsets(job, _cfg),
        disabled_toolsets=_resolve_cron_disabled_toolsets(_cfg),
        quiet_mode=True,
        skip_context_files=not bool(workdir),
        load_soul_identity=True,
        skip_memory=False,
        skip_background_review=True,
        platform="cron",
        session_id=session_id,
        session_db=session_db,
    )
'''

HELPER_NAME = '_gbox_nous_cron_output_tokens'
HELPER = '''def _gbox_nous_cron_output_tokens(cfg, runtime):
    """Validated initial output budget for actual Nous cron routes only."""
    if not isinstance(runtime, dict) or runtime.get("provider") != "nous":
        return None
    cron = cfg.get("cron") if isinstance(cfg, dict) else None
    limits = cron.get("output_token_limits") if isinstance(cron, dict) else None
    value = limits.get("nous") if isinstance(limits, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
'''

PATCHED_CONSTRUCTOR = ORIGINAL_CONSTRUCTOR.replace(
    '        request_overrides=runtime.get("request_overrides"),',
    '        max_tokens=_gbox_nous_cron_output_tokens(_cfg, runtime),\n'
    '        request_overrides=runtime.get("request_overrides"),',
)


class UnsupportedScheduler(ValueError):
    """The runtime changed or carries a conflicting patch; nothing was written."""


def _function(tree: ast.Module, name: str):
    matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == name]
    if len(matches) > 1:
        raise UnsupportedScheduler(f'Duplicate function: {name}')
    return matches[0] if matches else None


def _shape(node) -> str:
    return ast.dump(node, include_attributes=False)


def patch_source(source: str) -> tuple[str, bool]:
    """Fail closed unless the constructor exactly matches a known semantic AST."""
    tree = ast.parse(source)
    current = _function(tree, '_construct_cron_agent')
    helper = _function(tree, HELPER_NAME)
    original = ast.parse(ORIGINAL_CONSTRUCTOR).body[0]
    patched = ast.parse(PATCHED_CONSTRUCTOR).body[0]
    expected_helper = ast.parse(HELPER).body[0]
    if current is None:
        raise UnsupportedScheduler('Supported cron constructor not found')
    if _shape(current) == _shape(patched):
        if helper is None or _shape(helper) != _shape(expected_helper):
            raise UnsupportedScheduler('Patched constructor has a missing or conflicting helper')
        return source, False
    if _shape(current) != _shape(original):
        raise UnsupportedScheduler('Cron constructor does not match the supported runtime')
    # Any preexisting binding would make the helper unsafe to introduce.
    if HELPER_NAME in source:
        raise UnsupportedScheduler('Output-budget helper name already exists')
    lines = source.splitlines(keepends=True)
    before = ''.join(lines[:current.lineno - 1])
    existing = ''.join(lines[current.lineno - 1:current.end_lineno])
    anchor = '        request_overrides=runtime.get("request_overrides"),'
    if existing.count(anchor) != 1:
        raise UnsupportedScheduler('Supported request-overrides anchor not found exactly once')
    newline = '\r\n' if '\r\n' in source else '\n'
    added = '        max_tokens=_gbox_nous_cron_output_tokens(_cfg, runtime),' + newline
    updated = existing.replace(anchor, added + anchor)
    result = before + HELPER.replace('\n', newline) + newline + newline + updated + ''.join(lines[current.end_lineno:])
    new_tree = ast.parse(result)
    if (_shape(_function(new_tree, '_construct_cron_agent')) != _shape(patched)
            or _shape(_function(new_tree, HELPER_NAME)) != _shape(expected_helper)):
        raise UnsupportedScheduler('Patched constructor failed structural validation')
    compile(result, '<validated-hermes-cron-scheduler>', 'exec')
    return result, True


def apply_file(path: Path, *, apply: bool = False) -> dict:
    """Back up exact bytes and replace atomically; no write on check/idempotent runs."""
    path = Path(path).expanduser().resolve(strict=True)
    if path.name != 'scheduler.py' or path.parent.name != 'cron' or not path.is_file():
        raise UnsupportedScheduler('Expected an explicitly selected cron/scheduler.py file')
    before = path.read_bytes()
    text = before.decode('utf-8')
    patched, changed = patch_source(text)
    after = patched.encode('utf-8')
    before_hash = hashlib.sha256(before).hexdigest()
    result = {'status': 'compatible' if changed else 'already_applied',
              'scheduler': str(path), 'sha256_before': before_hash,
              'sha256_after': hashlib.sha256(after).hexdigest(), 'applied': False,
              'setting': 'cron.output_token_limits.nous', 'initial_budget_only': True}
    if not apply or not changed:
        return result
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = path.with_name(f'{path.name}.gbox-nous-output-limit-{stamp}-{before_hash[:12]}.bak')
    mode = stat.S_IMODE(path.stat().st_mode)
    with backup.open('xb') as stream:
        stream.write(before)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(backup, mode)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.gbox-nous-output-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if path.read_bytes() != before:
            raise UnsupportedScheduler('Scheduler changed during patch preparation; backup retained')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    result.update(status='applied', applied=True, backup=str(backup))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scheduler', type=Path, help='Explicit installed cron/scheduler.py path')
    parser.add_argument('--apply', action='store_true', help='Back up and atomically apply; default checks only')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(apply_file(args.scheduler, apply=args.apply), indent=2))
        return 0
    except (UnsupportedScheduler, SyntaxError, UnicodeError, OSError) as exc:
        print(json.dumps({'status': 'refused', 'error_type': type(exc).__name__, 'reason': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
