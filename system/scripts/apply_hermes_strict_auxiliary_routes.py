"""Install context-local strict vision routes for explicitly opted-in Hermes cron jobs.

Check: python apply_hermes_strict_auxiliary_routes.py /path/to/hermes-agent
Apply: add --apply with the runtime stopped, then restart it; alternatively keep
the target job disabled until its next execution is confirmed to use a fresh
external worker. Cached in-process modules are not activated by editing files.
Job field: auxiliary_routes.vision={provider: nous, model: <id>, strict: true}.
The command never changes configuration/job records, calls a model, or starts jobs.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

HELPER_START = '# GBOX STRICT JOB AUXILIARY ROUTES BEGIN\n'
HELPER_END = '# GBOX STRICT JOB AUXILIARY ROUTES END\n'
HELPERS = '''_GBOX_JOB_AUXILIARY_ROUTES = contextvars.ContextVar("gbox_job_auxiliary_routes", default=None)


def set_gbox_job_auxiliary_routes(routes):
    """Validate and snapshot explicit policy; no environment or global-config mutation."""
    if routes is None:
        return _GBOX_JOB_AUXILIARY_ROUTES.set(None)
    if not isinstance(routes, dict) or any(key != "vision" for key in routes):
        raise ValueError("auxiliary_routes must contain only the supported vision task")
    validated = {}
    for task, policy in routes.items():
        if not isinstance(policy, dict) or set(policy) != {"provider", "model", "strict"}:
            raise ValueError("Strict auxiliary vision policy requires provider, model and strict")
        provider, model = policy.get("provider"), policy.get("model")
        if policy.get("strict") is not True:
            raise ValueError("Explicit auxiliary routes require strict=true")
        if (not isinstance(provider, str) or not provider.strip()
                or provider.strip().lower() == "auto"
                or any(c.isspace() or c in ":/\\\\" for c in provider.strip())):
            raise ValueError("Strict auxiliary provider must be a concrete provider name")
        if (not isinstance(model, str) or not model.strip() or model.strip().lower() == "auto"
                or any(ord(c) < 32 for c in model) or len(model) > 512):
            raise ValueError("Strict auxiliary model must be an explicit model identifier")
        validated[task] = {"provider": provider.strip().lower(), "model": model.strip(), "strict": True}
    return _GBOX_JOB_AUXILIARY_ROUTES.set(validated)


def reset_gbox_job_auxiliary_routes(token):
    """Restore the caller's context, including nested scopes."""
    _GBOX_JOB_AUXILIARY_ROUTES.reset(token)


def _gbox_job_auxiliary_route(task):
    routes = _GBOX_JOB_AUXILIARY_ROUTES.get()
    policy = routes.get(task) if isinstance(routes, dict) else None
    return dict(policy) if policy is not None else None
'''

EARLY_POLICY = '''    policy = _gbox_job_auxiliary_route(task)
    if policy is not None:
        return policy["provider"], policy["model"], None, None, None
'''
EARLY_CONFIG = '''    policy = _gbox_job_auxiliary_route(task)
    if policy is not None:
        return dict(policy, fallback_chain=[])
'''
EARLY_PREPARE = '''    policy = _gbox_job_auxiliary_route(task)
    if policy is not None:
        provider, model = policy["provider"], policy["model"]
        base_url, api_key, api_mode = None, None, None
'''
EARLY_FALLBACK = '''    if _gbox_job_auxiliary_route(route.task) is not None:
        logger.warning("Auxiliary %s: provider fallback disabled by strict job route", route.task)
        return None
'''
ACCOUNTING_POLICY = '''    policy = _gbox_job_auxiliary_route(task)
    if policy is not None:
        if provider and provider.strip().lower() != policy["provider"]:
            raise RuntimeError("Auxiliary response route violates strict job provider")
        provider = policy["provider"]
'''
RESOLVED_POLICY = '''    policy = _gbox_job_auxiliary_route(task)
    if policy is not None and client is not None:
        if (effective_provider or resolved_provider or "").strip().lower() != policy["provider"]:
            raise RuntimeError("Auxiliary client resolution violates strict job provider")
        if final_model != policy["model"]:
            raise RuntimeError("Auxiliary client resolution violates strict job model")
'''

# Filled from the installed source's semantic AST, not line numbers/whitespace.
EXPECTED_SHAPES = {'agent/auxiliary_client.py': {'_resolve_task_provider_model': {'original': 'a3269524250db081093a1178b86a878dc6616d8c6e25910448f654cedf937174', 'patched': '17b96760dce797e20f6f5ead13136872076543bccd63f960c8358b31b306b4d0'}, '_get_auxiliary_task_config': {'original': '4ad4f8bfeae436490641911d84ad5a7a9a65761b50c1896bdaae6c20c7d9e52a', 'patched': '2e64cd8262f471a40ec35473eb55b73110cc4de2135c9de07bf1c653ec80226f'}, '_prepare_aux_request': {'original': '18ccda267b855c0b90b56adb8308617ae0e8fc51eb9ff10784a1c0436482b513', 'patched': '10a49c9078d22041e4ab2feae41168b544d664fe7349f060ce94c8a859391122'}, '_resolve_call_client': {'original': '2607b20a5aa6dc15580b5c97285ab4c15c2c8077695237e901afc31662dc95a2', 'patched': 'ce95489e7486711d258af6fc9ce5e24e1f224cbcfb13b106685ffb17b69c5162'}, '_ladder_provider_fallback': {'original': '9cb5400ec583db8bd3afb755cc8045d7c20276f87126013813e571ccfd04caaa', 'patched': 'f4d1a610037591384a689bd97c5fb91623dac516c7dffdf00827282e051d6469'}, '_ladder_nous_rungs': {'original': '4edeaddfc4ad4969d60e2bef1d5fcc1c17d50f81da41917ba853318deb22cdce', 'patched': '4c20a4a954304dcfae0f25ec396874bc348bdfa4e7037f5d0ca4cab2bcf3a293'}, '_validate_llm_response': {'original': 'babca4b780895f8e08ffa882b07f181d6c893ec4c2a70b07eea7acfdf50d8c3e', 'patched': 'c8cd71d65ed5f0168eca1959ed163b774e108bf3c48c9d60225f6cd12037342a'}}, 'cron/scheduler.py': {'run_job': {'original': '59857c4d8f3708d71553aa94673488a1c1f2a3d28b13d87ea15ea1fed71339a6', 'patched': 'a15fb9b2563749ac55dbb8eed3f3fe10339f8929719cd1216ada3c905c7afb1f'}, '_run_agent_with_watchdog': {'original': 'd491fff5d5dfbbe89b33767eab46686db10613923a139c3059ac863838668aab'}}}


class UnsupportedRuntime(ValueError):
    """Unknown or conflicting runtime source: fail before writing."""


def _shape(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def _nodes(source):
    tree = ast.parse(source)
    result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in result:
                raise UnsupportedRuntime('Duplicate runtime function')
            result[node.name] = node
    return result


def _after_docstring(text, insertion):
    node = ast.parse(text).body[0]
    first = node.body[0]
    if not isinstance(first, ast.Expr) or not isinstance(first.value, ast.Constant) or not isinstance(first.value.value, str):
        raise UnsupportedRuntime('Expected a documented runtime function')
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:first.end_lineno]) + insertion + ''.join(lines[first.end_lineno:])


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise UnsupportedRuntime('Runtime patch anchor is missing or ambiguous')
    return text.replace(old, new)


def _transform(name, text):
    early = {'_resolve_task_provider_model': EARLY_POLICY,
             '_get_auxiliary_task_config': EARLY_CONFIG,
             '_prepare_aux_request': EARLY_PREPARE,
             '_ladder_provider_fallback': EARLY_FALLBACK}
    if name in early:
        return _after_docstring(text, early[name])
    if name == '_resolve_call_client':
        text = _replace_once(text,
            '        if client is None and resolved_provider != "auto" and not resolved_base_url:',
            '        if (client is None and resolved_provider != "auto" and not resolved_base_url\n'
            '                and _gbox_job_auxiliary_route(task) is None):')
        return _replace_once(text, '    if client is None:\n        raise AuxiliaryClientUnavailable(',
                             RESOLVED_POLICY + '    if client is None:\n        raise AuxiliaryClientUnavailable(')
    if name == '_ladder_nous_rungs':
        return _replace_once(text, '    if _is_model_not_found_error(first_err) and client_is_nous:',
            '    if (_is_model_not_found_error(first_err) and client_is_nous\n'
            '            and _gbox_job_auxiliary_route(task) is None):')
    if name == '_validate_llm_response':
        return _replace_once(text, '    from agent.aux_accounting import record_aux_usage',
                             ACCOUNTING_POLICY + '    from agent.aux_accounting import record_aux_usage')
    if name == 'run_job':
        text = _replace_once(text, '    scope = _CronRunScope(job, job_id, execution_id)',
            '    _gbox_auxiliary_routes_token = None\n    scope = _CronRunScope(job, job_id, execution_id)')
        text = _replace_once(text, '        scope.enter()',
            '        scope.enter()\n'
            '        from agent.auxiliary_client import set_gbox_job_auxiliary_routes, reset_gbox_job_auxiliary_routes\n'
            '        _gbox_auxiliary_routes_token = set_gbox_job_auxiliary_routes(job.get("auxiliary_routes"))')
        return _replace_once(text, '        scope.exit()',
            '        if _gbox_auxiliary_routes_token is not None:\n'
            '            reset_gbox_job_auxiliary_routes(_gbox_auxiliary_routes_token)\n        scope.exit()')
    raise UnsupportedRuntime('Unsupported transformation')


def patch_sources(sources):
    """Patch both files atomically at validation level; exact semantic compatibility only."""
    output, states = {}, []
    for relative, source in sources.items():
        source = source.replace('\r\n', '\n')
        expected = EXPECTED_SHAPES.get(relative)
        if expected is None:
            raise UnsupportedRuntime('Unexpected runtime source path')
        nodes = _nodes(source)
        file_states = []
        edits = []
        for name, shapes in expected.items():
            node = nodes.get(name)
            if node is None:
                raise UnsupportedRuntime('Required runtime function missing')
            digest = _shape(node)
            if name == '_run_agent_with_watchdog':
                if digest != shapes['original']:
                    raise UnsupportedRuntime('Cron worker context propagation changed')
                continue
            if digest == shapes['patched']:
                file_states.append('patched')
            elif digest == shapes['original']:
                file_states.append('original')
                lines = source.splitlines(keepends=True)
                text = ''.join(lines[node.lineno-1:node.end_lineno])
                changed = _transform(name, text)
                if _shape(ast.parse(changed).body[0]) != shapes['patched']:
                    raise UnsupportedRuntime('Transformed function failed semantic validation')
                edits.append((node.lineno-1, node.end_lineno, changed))
            else:
                raise UnsupportedRuntime('Runtime function does not match a supported semantic AST')
        if len(set(file_states)) != 1:
            raise UnsupportedRuntime('Mixed or incomplete runtime patch')
        state = file_states[0]
        states.append(state)
        if relative == 'agent/auxiliary_client.py':
            block = HELPER_START + HELPERS + HELPER_END
            if state == 'patched':
                if source.count(block) != 1:
                    raise UnsupportedRuntime('Strict route helpers missing or conflicting')
            elif '_GBOX_JOB_AUXILIARY_ROUTES' in source or 'set_gbox_job_auxiliary_routes' in source:
                raise UnsupportedRuntime('Strict route helper names already exist')
        if state == 'original':
            lines = source.splitlines(keepends=True)
            for start, end, changed in sorted(edits, reverse=True):
                lines[start:end] = [changed]
            changed_source = ''.join(lines)
            if relative == 'agent/auxiliary_client.py':
                changed_source = _replace_once(changed_source, 'def _resolve_task_provider_model(',
                    HELPER_START + HELPERS + HELPER_END + '\n\ndef _resolve_task_provider_model(')
            compile(changed_source, relative, 'exec')
            output[relative] = changed_source
        else:
            output[relative] = source
    if set(sources) != set(EXPECTED_SHAPES) or len(set(states)) != 1:
        raise UnsupportedRuntime('Both scheduler and auxiliary client must have the same patch state')
    return output, states[0] == 'original'


def apply_runtime(runtime, *, apply=False):
    root = Path(runtime).expanduser().resolve(strict=True)
    paths = {rel: root / rel for rel in EXPECTED_SHAPES}
    if any(not path.is_file() for path in paths.values()):
        raise UnsupportedRuntime('Expected the selected Hermes runtime source tree')
    before = {rel: path.read_bytes() for rel, path in paths.items()}
    patched, changed = patch_sources({rel: data.decode('utf-8') for rel, data in before.items()})
    after = {rel: src.encode('utf-8') for rel, src in patched.items()}
    receipt = {'status': 'compatible' if changed else 'already_applied', 'applied': False,
               'job_field': 'auxiliary_routes.vision', 'global_config_changed': False,
               'sha256_before': {k: hashlib.sha256(v).hexdigest() for k,v in before.items()},
               'sha256_after': {k: hashlib.sha256(v).hexdigest() for k,v in after.items()}}
    if not apply or not changed:
        return receipt
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backups, temporary, replaced = {}, {}, []
    try:
        for rel, path in paths.items():
            backup = path.with_name(path.name + '.gbox-strict-aux-' + stamp + '.bak')
            with backup.open('xb') as stream:
                stream.write(before[rel]); stream.flush(); os.fsync(stream.fileno())
            os.chmod(backup, stat.S_IMODE(path.stat().st_mode))
            backups[rel] = str(backup)
            with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.gbox-strict-aux-', delete=False) as stream:
                temporary[rel] = Path(stream.name)
                stream.write(after[rel]); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary[rel], stat.S_IMODE(path.stat().st_mode))
        for rel, path in paths.items():
            if path.read_bytes() != before[rel]:
                raise UnsupportedRuntime('Runtime changed during patch preparation')
        for rel, path in paths.items():
            os.replace(temporary.pop(rel), path)
            replaced.append(rel)
    except BaseException:
        for rel in reversed(replaced):
            paths[rel].write_bytes(before[rel])
        raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
    receipt.update(status='applied', applied=True, backups=backups, restart_required=True)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(apply_runtime(args.runtime, apply=args.apply), indent=2))
        return 0
    except (UnsupportedRuntime, SyntaxError, UnicodeError, OSError) as exc:
        print(json.dumps({'status':'refused','error_type':type(exc).__name__,'reason':str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
