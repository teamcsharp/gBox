"""Enforced tool limits for bounded favorite unlock research.

These limits apply only to the persisted request context. Operator actions and
ordinary offline build requests keep their existing permission checks.
"""
from functools import lru_cache
from copy import deepcopy
import gzip
import json
from pathlib import Path, PurePosixPath


FLAGS = ('idle_only', 'no_rom_copy', 'no_automatic_launch')
ANALYSIS = {'analyze_binary', 'ghidra_bridge', 'read_rea_result', 'rea_tools', 'rea_resources',
            'get_frame', 'read_memory', 'session_info', 're_executable', 're_study'}
AGENT_READS = {'web_search', 'web_fetch', 'wiki', 'recall', 'remember', 'search_games',
               're_dossier', 're_playbook', 'ghidra_scripts', 'list_sessions', 'session_info',
               'look_at_screen', 'live_research', 'memory_snapshot', 'memory_filter'}
GHIDRA_OPS = {'status', 'start', 'open', 'info', 'functions', 'decompile', 'xrefs_to',
              'xrefs_from', 'containing', 'strings', 'export'}


@lru_cache(maxsize=1)
def _rea_reads():
    contracts = json.loads(gzip.decompress(Path(__file__).with_name('rea_catalog.json.gz').read_bytes()))
    return frozenset('rea_' + t['name'] for t in contracts['tools']
                     if not any(t['effects'].get(k, True) for k in
                                ('mutatesTarget', 'writesFilesystem', 'launchesProcess',
                                 'accessesNetwork', 'changesUiState', 'mayDiscardData')))


def _elf(path):
    return isinstance(path, str) and PurePosixPath(path.replace('\\', '/')).suffix.lower() == '.elf'


def reason(context, name, args, *, agent=False):
    """Return a refusal before any dispatch, including wrapped/learned calls."""
    context = context or {}
    if not any(context.get(k) for k in FLAGS):
        return ''
    if name == 'run_tool':
        name, args = args.get('name'), args.get('input') or {}
    if not isinstance(args, dict):
        return 'Unlock research requires typed tool arguments'
    gid = context.get('custom_build_unlocks')
    if gid and args.get('game_id') and args['game_id'] != gid:
        return 'Unlock research is bound to its requested game'
    if not (context.get('no_rom_copy') or context.get('no_automatic_launch')):
        return ''  # idle admission is checked separately, including legacy build work
    if name in {'re_executable', 're_study'} and args.get('source', 'auto') != 'ram':
        return 'Favorite unlock research cannot copy or unpack a ROM; reuse an existing ELF or use source=ram'
    if name == 'ghidra_bridge':
        if args.get('op', 'status') not in GHIDRA_OPS:
            return 'Favorite unlock research permits bounded Ghidra analysis, not arbitrary scripts or process control'
        if args.get('op') in {'open', 'start'} and not _elf(args.get('binary_path')):
            return 'Favorite unlock research opens an existing ELF, never a ROM or unbound project'
    if name == 'analyze_binary' and not _elf(args.get('binary_path')):
        return 'Favorite unlock research analyzes an existing ELF, never a ROM'
    if name == 'rea_open_binary':
        return '' if _elf(args.get('path')) else 'Favorite unlock research opens an existing ELF in REA'
    if name in ANALYSIS or name in _rea_reads() or agent and name in AGENT_READS:
        return ''
    return 'Favorite unlock research cannot launch a game, copy a ROM, or run build/mutation tools; this work remains pending'


def snapshot(context):
    if not any((context or {}).get(k) for k in FLAGS):
        return None
    return deepcopy({k: context.get(k) for k in (*FLAGS, 'custom_build_unlocks', 'unlock_dispatch')})


def admit(store, app, parent_request_id, name, args, *, expected=None):
    """Authenticate limits from the stored parent, then sample idle state afresh."""
    request = store.get('request', parent_request_id) if parent_request_id else None
    context = (request or {}).get('context') or {}
    if expected is not None and snapshot(context) != expected:
        return 'Unlock research scope changed or disappeared; a new admitted job is required'
    if why := reason(context, name, args):
        return why
    if context.get('idle_only'):
        check = getattr(app.state, 'custom_build_unlock_job_admission', None)
        if not callable(check):
            return 'Idle unlock admission is unavailable; research remains pending'
        try:
            return check(parent_request_id) or ''
        except Exception:
            return 'Idle unlock admission could not be verified; research remains pending'
    return ''
