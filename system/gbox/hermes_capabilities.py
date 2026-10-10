"""Explicit operator opt-in to the full Hermes task tool profile."""
from __future__ import annotations

import argparse
import copy
import json

EXECUTION_MODES = ('cron_mode', 'single_query_mode', 'unattended_mode')
TASK_TOOLSETS = ('code_execution', 'terminal', 'file', 'computer_use', 'vision',
                 'browser', 'web', 'delegation', 'moa', 'video', 'cronjob')
INSTRUCTIONS = (
    'The operator has authorized unattended task execution: terminal commands, '
    'Python -c, execute_code and required gBox MCP operations are available. '
    'Use tool_search/tool_describe to discover current tools and their schemas; '
    'the full gBox registry is exposed, including job_<registered tool>. '
    'For long or remote operations use start_job/get_job with the same returned ID. '
    'If a tool reports a dependency or connection failure, record the exact error '
    'and correct that cause; do not treat historical approval denials as current policy. '
    'Keep changes in the isolated task workspace and install necessary project '
    'dependencies there or in its venv. Preserve the operator PC, existing games, '
    'owned ROMs and saves; agent Windows tests use JAYBUILTFINALE at 2% audio. '
    'Only send external messages when the operator explicitly requested them.'
)


def task_profile(config: dict) -> dict:
    """Return the requested profile; never opt in implicitly during scheduling."""
    result = copy.deepcopy(config)
    approvals = result.setdefault('approvals', {})
    approvals.update({key: 'approve' for key in EXECUTION_MODES})
    platforms = result.setdefault('platform_toolsets', {})
    # Hermes deliberately removes interactive messaging/clarification from cron.
    tools = list(dict.fromkeys([*(platforms.get('cron') or []),
                               *(platforms.get('cli') or []), *TASK_TOOLSETS]))
    platforms['cron'] = [name for name in tools if name not in ('messaging', 'clarify', 'no_mcp')]
    result.setdefault('cron', {})['allow_agent_scheduling'] = True
    result.setdefault('security', {})['allow_private_urls'] = True
    result.setdefault('browser', {})['allow_private_urls'] = True
    server = result.setdefault('mcp_servers', {}).setdefault('gbox', {})
    server['enabled'] = True
    filters = server.setdefault('tools', {})
    # include: [] means NO tools in Hermes, rather than all tools.
    filters.pop('include', None)
    filters.pop('exclude', None)
    return result


def audit(config: dict) -> dict:
    """Credential-free diagnostics, suitable for task status and inbox evidence."""
    approvals = config.get('approvals') or {}
    tools = (config.get('platform_toolsets') or {}).get('cron') or []
    server = (config.get('mcp_servers') or {}).get('gbox') or {}
    filters = server.get('tools') or {}
    missing = [f'approvals.{key}' for key in EXECUTION_MODES if approvals.get(key) != 'approve']
    missing += [f'cron toolset: {name}' for name in TASK_TOOLSETS if name not in tools]
    if not (config.get('cron') or {}).get('allow_agent_scheduling'):
        missing.append('cron.allow_agent_scheduling')
    if not (config.get('security') or {}).get('allow_private_urls'):
        missing.append('security.allow_private_urls')
    if not (config.get('browser') or {}).get('allow_private_urls'):
        missing.append('browser.allow_private_urls')
    if not server or server.get('enabled') is False:
        missing.append('mcp_servers.gbox.enabled')
    if filters.get('include') is not None or filters.get('exclude'):
        missing.append('gbox MCP tool filter')
    disabled = (config.get('agent') or {}).get('disabled_toolsets') or []
    missing += [f'disabled toolset: {name}' for name in TASK_TOOLSETS if name in disabled]
    env = server.get('env') or {}
    return {'ready': not missing, 'missing': missing,
            'execution_modes': {key: approvals.get(key, 'deny') for key in EXECUTION_MODES},
            'full_gbox_catalog': filters.get('include') is None and not filters.get('exclude'),
            'cron_toolsets': tools, 'operator_worker': env.get('GBOX_OPERATOR_WORKER'),
            'test_worker': env.get('GBOX_TEST_WORKER')}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply the explicitly authorized task profile')
    args = parser.parse_args()
    if args.apply:
        # Run with Hermes's interpreter/bootstrap so its atomic writer preserves
        # configuration templates and secures the file without copying credentials.
        from hermes_cli.config import load_config_readonly, save_config
        config = task_profile(load_config_readonly())
        if not config['mcp_servers']['gbox'].get('command'):
            raise RuntimeError('Provision the gBox MCP connection before applying its task profile')
        save_config(config, preserve_keys={('approvals', key) for key in EXECUTION_MODES})
        report = audit(load_config_readonly())
    else:
        from .hermes_task_mode import _config
        report = audit(_config())
    print(json.dumps(report, indent=2))
    if not report['ready']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
