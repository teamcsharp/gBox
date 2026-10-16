"""A managed favorite tool call is attributed by Hermes core, not model input."""
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from gbox import hermes_unlock_guard as G

RID, OTHER = '1' * 16, '2' * 16
JOB, RUN = 'abc123abc123', '3' * 32
LIMITS = {'custom_build_unlocks': 'f' * 16, 'idle_only': True,
          'no_rom_copy': True, 'no_automatic_launch': True,
          'unlock_dispatch': {'versions': {'@original': 'a' * 64}, 'profile_revision': None}}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    home, db_path, queue = tmp_path / 'hermes', tmp_path / 'gbox.sqlite3', tmp_path / 'queue.json'
    (home / 'cron').mkdir(parents=True)
    jobs = [{'id': JOB, 'name': 'gBox queue inbox ' + RID}]
    (home / 'cron/jobs.json').write_text(json.dumps({'jobs': jobs}))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions(id TEXT,job_id TEXT,status TEXT,started_at TEXT,claimed_at TEXT)')
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?)',
                   (RUN, JOB, 'running', '1970-01-01T00:16:41+00:00', '1970-01-01T00:16:40+00:00'))
    request = {'id': RID, 'status': 'in_progress', 'context': LIMITS}
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE docs(kind TEXT,id TEXT,body TEXT)')
        db.execute('INSERT INTO docs VALUES(?,?,?)', ('request', RID, json.dumps(request)))
    item = {'request_id': RID, 'job_id': JOB, 'dispatch_state': 'queued', 'unlock_work': True,
            'unlock_scope': G.dispatch_scope(request, 1000)}
    queue.write_text(json.dumps({'items': {'inbox:' + RID: item}}))
    monkeypatch.setattr(G, '_control_db', lambda: db_path)
    monkeypatch.setattr(G, '_queue', lambda: queue)
    return SimpleNamespace(home=home, db=db_path, queue=queue, item=item, request=request, jobs=jobs,
                           task=f'cron:{JOB}:{RUN}')


def call(rig, tool, args=None, **kw):
    return G.pre_tool_call(tool_name='mcp_gbox_' + tool, args=args or {},
                           task_id=rig.task, home=rig.home, **kw)


@pytest.mark.parametrize('parent', [None, OTHER, RID])
def test_jobs_receive_core_derived_parent_even_when_model_omits_or_changes_it(rig, parent):
    args = {'game_id': LIMITS['custom_build_unlocks'], 'source': 'ram', 'session_id': 'w-session'}
    if parent is not None:
        args['parent_request_id'] = parent
    result = call(rig, 'job_re_executable', args)
    assert result == {'action': 'modify', 'args': {'parent_request_id': RID}}
    assert args.get('parent_request_id') == parent  # Never mutate model input in place.
    # Hermes's real modify contract shallow-merges the directive before dispatch.
    dispatched = args | result['args']
    assert dispatched['parent_request_id'] == RID and dispatched['source'] == 'ram'


def test_generic_and_rea_job_shapes_are_attributed(rig):
    for name, args in [('start_job', {'tool': 'analyze_binary', 'input': {'binary_path': '/saved/exact.elf'}}),
                       ('job_rea_open_binary', {'input': {'path': '/saved/exact.elf'}}),
                       ('job_ghidra_bridge', {'op': 'decompile', 'target': '0x1234'})]:
        assert call(rig, name, args)['args']['parent_request_id'] == RID


@pytest.mark.parametrize('tool,args', [
    ('job_re_executable', {'source': 'auto'}), ('job_re_study', {'source': 'disc'}),
    ('job_ghidra_bridge', {'op': 'run_script', 'script': 'arbitrary.py'}),
    ('job_file_mod', {'op': 'build'}), ('job_launch_game', {}), ('launch_game', {}),
    ('ask_gbox', {'text': 'launch a game'}), ('capture_request_screenshot', {}),
    ('start_job', {'tool': 'evidence_capture', 'input': {}}),
])
def test_job_convenience_or_wrapper_cannot_escape_restricted_scope(rig, tool, args):
    assert call(rig, tool, args)['action'] == 'block'


@pytest.mark.parametrize('tool', ['terminal', 'execute_code', 'delegate_task', 'browser_navigate', 'file_write'])
def test_non_mcp_tools_cannot_escape_via_shell_code_browser_or_subagents(rig, tool):
    result = G.pre_tool_call(tool_name=tool, args={'command': 'curl localhost'}, task_id=rig.task, home=rig.home)
    assert result['action'] == 'block'


@pytest.mark.parametrize('change', ['execution', 'job', 'state', 'queue_owner', 'queue_job', 'request_status'])
def test_stale_or_other_claim_fails_closed_without_global_inference(rig, change):
    if change in {'execution', 'job', 'state'}:
        with sqlite3.connect(rig.home / 'cron/executions.db') as db:
            field, value = {'execution': ('id', 'other'), 'job': ('job_id', 'other'), 'state': ('status', 'completed')}[change]
            db.execute(f'UPDATE executions SET {field}=?', (value,))
    elif change.startswith('queue_'):
        rig.item['request_id' if change == 'queue_owner' else 'job_id'] = OTHER
        rig.queue.write_text(json.dumps({'items': {'inbox:' + RID: rig.item}}))
    else:
        rig.request['status'] = 'done'
        with sqlite3.connect(rig.db) as db:
            db.execute('UPDATE docs SET body=?', (json.dumps(rig.request),))
    assert call(rig, 'start_job', {'tool': 'analyze_binary', 'input': {'binary_path': 'exact.elf'}})['action'] == 'block'


def test_parallel_execution_ids_do_not_borrow_another_active_owner(rig):
    with sqlite3.connect(rig.home / 'cron/executions.db') as db:
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?)',
                   ('other-run', 'other-job', 'running', '1970-01-01T00:16:41+00:00', None))
    result = G.pre_tool_call(tool_name='terminal', args={}, task_id=f'cron:{JOB}:other-run', home=rig.home)
    assert result['action'] == 'block'


def test_ordinary_cron_and_operator_runs_are_unaffected(rig):
    assert G.pre_tool_call(tool_name='terminal', args={}, task_id='interactive', home=rig.home) is None
    rig.jobs[0]['name'] = 'Ordinary housekeeping'
    (rig.home / 'cron/jobs.json').write_text(json.dumps({'jobs': rig.jobs}))
    assert G.pre_tool_call(tool_name='terminal', args={}, task_id=rig.task, home=rig.home) is None
    rig.jobs[0]['name'] = 'gBox queue inbox ' + RID
    (rig.home / 'cron/jobs.json').write_text(json.dumps({'jobs': rig.jobs}))
    rig.request['context'] = {'ordinary_build': True}
    rig.item.pop('unlock_scope'); rig.item['unlock_work'] = False
    rig.queue.write_text(json.dumps({'items': {'inbox:' + RID: rig.item}}))
    with sqlite3.connect(rig.db) as db:
        db.execute('UPDATE docs SET body=?', (json.dumps(rig.request),))
    assert call(rig, 'job_launch_game') is None


def test_request_reporting_stays_exact_and_analysis_has_no_false_success(rig):
    assert call(rig, 'get_request', {'request_id': RID}) is None
    assert call(rig, 'reply_request', {'request_id': OTHER, 'text': 'wrong report'})['action'] == 'block'
    assert not (rig.home / G.NAME).exists(), 'Pure policy checks do not write activation evidence'


def test_favorite_metadata_publication_stays_bound_to_request_and_game(rig):
    args = {'request_id': RID, 'game_id': LIMITS['custom_build_unlocks'], 'op': 'native_profile'}
    assert call(rig, 'favorite_unlocks', args) is None
    assert call(rig, 'favorite_unlocks', args | {'request_id': OTHER})['action'] == 'block'
    assert call(rig, 'favorite_unlocks', args | {'game_id': OTHER})['action'] == 'block'
    assert call(rig, 'favorite_unlocks', {'op': 'status'})['action'] == 'block'


def test_scope_snapshot_does_not_follow_later_request_edits(rig):
    scope = G.dispatch_scope(rig.request, 1000)
    changed = json.loads(json.dumps(rig.request))
    changed['context']['unlock_dispatch']['versions']['@original'] = 'later'
    changed['context']['no_rom_copy'] = False
    assert scope['release'] != changed['context']['unlock_dispatch']
    assert scope['context']['no_rom_copy'] is True


def test_readiness_requires_current_payload_actual_gateway_and_active_registration(rig, monkeypatch):
    monkeypatch.setattr(G, '_installed', lambda home: True)
    monkeypatch.setattr(G, '_gateway', lambda home: (os.getpid(), 100.25))
    assert G.readiness_reason(rig.home)
    G._mark_loaded(rig.home, G._payload(), 'registration')
    assert not G.readiness_reason(rig.home)
    monkeypatch.setattr(G, '_gateway', lambda home: (os.getpid(), 200.25))
    assert G.readiness_reason(rig.home), 'A reused/restarted gateway must register again'
    monkeypatch.setattr(G, '_gateway', lambda home: (os.getpid(), 100.25))
    payload = G._payload() | {'old': 'stale'}
    G._mark_loaded(rig.home, payload, 'older-source')
    assert G.readiness_reason(rig.home)
    G._mark_loaded(rig.home, G._payload(), 'new-source')
    G._mark_loaded(rig.home, payload, 'older-source', active=False)
    assert not G.readiness_reason(rig.home), 'An old unload cannot revoke a new registration'
    G._mark_loaded(rig.home, G._payload(), 'new-source', active=False)
    assert G.readiness_reason(rig.home)


def test_cli_cannot_claim_it_loaded_the_gateway_hook(rig, monkeypatch):
    monkeypatch.setattr(G, '_gateway', lambda home: (os.getpid() + 100, 100.25))
    G._mark_loaded(rig.home, G._payload(), 'cli')
    assert not (rig.home / G.NAME / 'loaded.json').exists()


def test_plugin_registers_supported_hook_and_unload_revokes_readiness(rig, monkeypatch):
    plugin = SimpleNamespace(_get_pre_tool_call_directive_details=lambda: None,
                             _dispatch_pre_tool_call_hooks=lambda: None)
    monkeypatch.setitem(sys.modules, 'hermes_cli', SimpleNamespace(plugins=plugin))
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: rig.home))
    monkeypatch.setattr(G.inspect, 'getsource', lambda fn: 'action == "modify"; details.modified_args')
    monkeypatch.setattr(G, '_gateway', lambda home: (os.getpid(), 100.25))
    monkeypatch.setattr(G, '_installed', lambda home: True)
    hooks, unload = {}, []
    bootstrap = {name: G._payload()[f'hermes/{G.NAME}/{name}'] for name in ('__init__.py', 'plugin.yaml')}
    G.register(SimpleNamespace(register_hook=lambda name, cb: hooks.update({name: cb}), on_unload=unload.append),
               bootstrap=bootstrap)
    assert not G.readiness_reason(rig.home)
    assert hooks['pre_tool_call'](tool_name='terminal', args={}, task_id=rig.task)['action'] == 'block'
    unload[0]()
    assert G.readiness_reason(rig.home)
    assert hooks['pre_tool_call'](tool_name='terminal', args={}, task_id='ordinary')['action'] == 'block'
    assert G.readiness_reason(rig.home), 'An in-flight old callback cannot reactivate an unloaded registration'


@pytest.mark.parametrize('change', ['missing_request', 'flags', 'release', 'later_occurrence', 'missing_scope'])
def test_running_occurrence_never_loses_its_restrictions_or_borrows_a_later_lease(rig, change):
    if change == 'later_occurrence':
        rig.item['unlock_scope']['dispatched_at'] = 1002
    elif change == 'missing_scope':
        rig.item.pop('unlock_scope')
    else:
        with sqlite3.connect(rig.db) as db:
            if change == 'missing_request':
                db.execute('DELETE FROM docs')
            else:
                context = json.loads(json.dumps(rig.request['context']))
                if change == 'flags':
                    context.pop('no_rom_copy'); context.pop('no_automatic_launch')
                else:
                    context['unlock_dispatch']['versions']['@original'] = 'changed'
                db.execute('UPDATE docs SET body=?', (json.dumps(rig.request | {'context': context}),))
    rig.queue.write_text(json.dumps({'items': {'inbox:' + RID: rig.item}}))
    result = G.pre_tool_call(tool_name='terminal', args={}, task_id=rig.task, home=rig.home)
    assert result['action'] == 'block'


@pytest.mark.parametrize('which', ['guard', 'policy', 'bootstrap'])
def test_cached_old_python_modules_cannot_certify_new_source_on_disk(rig, monkeypatch, which):
    from gbox import unlock_job_policy
    plugin = SimpleNamespace(_get_pre_tool_call_directive_details=lambda: None,
                             _dispatch_pre_tool_call_hooks=lambda: None)
    monkeypatch.setitem(sys.modules, 'hermes_cli', SimpleNamespace(plugins=plugin))
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: rig.home))
    monkeypatch.setattr(G.inspect, 'getsource', lambda fn: 'action == "modify"; details.modified_args')
    monkeypatch.setattr(G, '_gateway', lambda home: (os.getpid(), 100.25))
    monkeypatch.setattr(G, '_installed', lambda home: True)
    bootstrap = {name: G._payload()[f'hermes/{G.NAME}/{name}'] for name in ('__init__.py', 'plugin.yaml')}
    if which == 'guard': monkeypatch.setattr(G, 'LOADED_SOURCE_SHA256', '0' * 64)
    elif which == 'policy': monkeypatch.setattr(unlock_job_policy, 'LOADED_SOURCE_SHA256', '0' * 64)
    else: bootstrap['__init__.py'] = '0' * 64
    G.register(SimpleNamespace(register_hook=lambda *a: None, on_unload=lambda *a: None), bootstrap=bootstrap)
    assert G.readiness_reason(rig.home)


def test_installer_is_dry_run_and_never_replaces_existing_data(tmp_path):
    home = tmp_path / 'home'
    plan = G.install(home)
    assert plan['action'] == 'create_symlink' and plan['applied'] is False
    assert not home.exists()
    target = home / 'plugins' / G.NAME
    target.mkdir(parents=True)
    saved = target / 'personal.txt'
    saved.write_text('preserved')
    with pytest.raises(ValueError, match='will not be replaced'):
        G.install(home, apply=True)
    assert saved.read_text() == 'preserved'


def test_favorite_idle_admission_fails_closed_before_other_inventory(rig, monkeypatch):
    from gbox import custom_build_unlocks as U
    monkeypatch.setattr(G, 'readiness_reason', lambda: 'Current hook not loaded')
    assert U.idle_reason(None, [], U.FAVORITE_DEFAULTS, require_guard=True) == 'Current hook not loaded'
