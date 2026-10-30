"""Recovery must remain installation-scoped and at-most-once even across uncertain process effects."""
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest
import psutil

from gbox import desktop_supervisor as S

AUTH, CONTROLLER, WORKER, EPOCH = 'a' * 64, 'b' * 32, 'c' * 16, 'd' * 32


def command(**updates):
    return {'id': 'e' * 32, 'op': 'relaunch', 'authority': AUTH, 'controller_id': CONTROLLER,
            'worker_id': WORKER, 'epoch': EPOCH, 'force': True, 'expires_at': 1100., 'sessions': [], **updates}


def test_completed_command_survives_executor_restart_without_repeating_effects(tmp_path):
    effects = []
    closed = [{'session_id': WORKER + '-game', 'pid': 123, 'created': 10.}]
    def act(value):
        effects.append(value)
        return closed
    first = S.Executor(tmp_path, AUTH, CONTROLLER, act).execute(command(), server_time=1000.)
    second = S.Executor(tmp_path, AUTH, CONTROLLER, act).execute(command(), server_time=1001.)
    assert first['status'] == second['status'] == 'requested'
    assert second['closed_sessions'] == closed and len(effects) == 1
    assert second == first                         # central accepts only the original immutable receipt


def test_process_crash_after_reservation_never_replays_ambiguous_effect(tmp_path):
    effects = []
    def crash(value):
        effects.append(value)
        raise SystemExit('process died after side effect')
    with pytest.raises(SystemExit):
        S.Executor(tmp_path, AUTH, CONTROLLER, crash).execute(command(), server_time=1000.)
    replay = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value)).execute(command(), server_time=1001.)
    assert replay['status'] == 'unknown' and len(effects) == 1


def test_failed_final_receipt_write_preserves_reservation_and_prevents_replay(tmp_path, monkeypatch):
    write, effects = S.write_json, []
    def fail_final(path, value):
        if value['status'] == 'requested':
            raise OSError('disk full after effect')
        write(path, value)
    monkeypatch.setattr(S, 'write_json', fail_final)
    with pytest.raises(OSError):
        S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value)).execute(command(), server_time=1000.)
    monkeypatch.setattr(S, 'write_json', write)
    replay = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value)).execute(command(), server_time=1001.)
    assert replay['status'] == 'unknown' and len(effects) == 1


def test_same_id_with_changed_scope_cannot_reuse_or_replace_a_receipt(tmp_path):
    effects = []
    executor = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value))
    executor.execute(command(), server_time=1000.)
    with pytest.raises(ValueError, match='changed'):
        executor.execute(command(epoch='f' * 32), server_time=1001.)
    assert len(effects) == 1


@pytest.mark.parametrize('update', [{'force': 'true'}, {'worker_id': '../other'}, {'controller_id': 'f' * 32},
                                   {'authority': 'f' * 64}, {'op': 'shell'}, {'expires_at': float('nan')},
                                   {'expires_at': 1000.}, {'expires_at': 1200.}])
def test_invalid_or_expired_command_has_no_effect_or_reservation(tmp_path, update):
    effects = []
    with pytest.raises(ValueError):
        S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value)).execute(command(**update), server_time=1000.)
    assert not effects and not list(tmp_path.iterdir())


def test_epoch_change_between_reservation_and_effect_is_a_durable_refusal(tmp_path):
    states = iter([{'worker_id': WORKER, 'epoch': EPOCH}, {'worker_id': WORKER, 'epoch': 'f' * 32}])
    effects = []
    executor = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value),
                          preflight=lambda value: S.verify_observation(value, next(states)))
    result = executor.execute(command(), server_time=1000.)
    assert result['status'] == 'failed' and not effects
    assert executor.execute(command(), server_time=1001.)['status'] == 'failed'


@pytest.mark.parametrize('observed', [{'foreign': True}, {'worker_id': 'f' * 16}, {'epoch': 'f' * 32}])
def test_foreign_or_replaced_authority_has_a_durable_refusal_before_any_effect(tmp_path, observed):
    executor = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: pytest.fail('effect'),
                          preflight=lambda value: S.verify_observation(value, observed))
    receipt = executor.execute(command(), server_time=1000.)
    assert receipt['status'] == 'failed' and receipt['closed_sessions'] == []
    assert S.read_json(tmp_path / ('command-' + command()['id'] + '.json'))['receipt'] == receipt
    assert executor.execute(command(), server_time=1001.) == receipt


def test_unavailable_local_service_does_not_prevent_explicit_scoped_force_recovery():
    S.verify_observation(command(), {'worker_id': None, 'epoch': None, 'worker_state': 'unavailable'})


class Process:
    def __init__(self, pid, exe, args, *, created=10., running=True, children=()):
        self.pid, self.info = pid, {'exe': str(exe), 'cmdline': list(map(str, args))}
        self.created, self.running, self.descendants, self.effects = created, running, list(children), []

    def create_time(self):
        return self.created

    def is_running(self):
        return self.running

    def children(self, recursive=False):
        assert recursive
        return self.descendants

    def as_dict(self, attrs):
        return {key: self.info[key] for key in attrs}

    def terminate(self):
        self.effects.append('terminate')

    def kill(self):
        self.effects.append('kill')


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root, local = tmp_path / 'system', tmp_path / 'Local'
    app, executable = root / 'clients/desktop', local / 'gbox/app/gBox.exe'
    for path in (app / 'main.js', root / 'scripts/register-desktop-supervisor.ps1', root / 'gbox.toml', executable):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    cfg = SimpleNamespace(data_dir=tmp_path / 'data')
    manifest = {'authority': AUTH, 'root': str(root), 'app': str(app), 'executable': str(executable), 'config': str(root / 'gbox.toml')}
    launches = []
    monkeypatch.setattr(S, 'windows_exited', lambda pid: False)
    monkeypatch.setattr(S, 'wait_processes', lambda processes, timeout: (list(processes), []))
    return cfg, manifest, launches


def parent(manifest, *children, pid=100):
    return Process(pid, manifest['executable'], [manifest['executable'], manifest['app']], children=children)


def test_relaunch_closes_only_owned_children_and_uses_fixed_launch_without_control_secrets(installation, monkeypatch):
    _, manifest, launches = installation
    owned = Process(101, manifest['executable'], [manifest['executable'], '--type=renderer'])
    unrelated = Process(102, 'browser.exe', ['browser.exe', 'https://example.test'])
    p = parent(manifest, owned, unrelated)
    for name in ('GBOX_TOKEN', 'GBOX_CLIENT_CONTROL', 'ELECTRON_RUN_AS_NODE'):
        monkeypatch.setenv(name, 'must-not-inherit')
    result = S.relaunch(manifest, command(executable='attacker.exe', args=['--evil']), processes=[p],
                        popen=lambda args, **kw: launches.append((args, kw)))
    assert p.effects == owned.effects == ['terminate'] and not unrelated.effects and result == []
    args, kwargs = launches[0]
    assert args == [manifest['executable'], manifest['app']] and kwargs['cwd'] == manifest['app']
    assert not {'GBOX_TOKEN', 'GBOX_CLIENT_CONTROL', 'ELECTRON_RUN_AS_NODE'} & kwargs['env'].keys()
    assert not kwargs.get('shell') and kwargs['stdin'] == subprocess.DEVNULL


def test_cached_create_time_alone_cannot_validate_a_reused_pid():
    p = Process(100, 'app.exe', ['app.exe'], created=10., running=False)
    assert S.same_process(p, (100, 10.)) is False


def test_reused_parent_pid_is_rejected_before_any_process_effect(installation):
    _, manifest, launches = installation
    p = parent(manifest)
    p.running = False
    with pytest.raises(ValueError):
        S.relaunch(manifest, command(), processes=[p], popen=lambda *a, **kw: launches.append(a))
    assert not p.effects and not launches


def test_multiple_matching_roots_or_self_descendant_refuse_before_effects(installation):
    _, manifest, launches = installation
    first, second = parent(manifest), parent(manifest, pid=110)
    with pytest.raises(ValueError, match='Ambiguous'):
        S.relaunch(manifest, command(), processes=[first, second], popen=lambda *a, **kw: launches.append(a))
    self_child = Process(os.getpid(), sys.executable, [sys.executable, '-m', 'gbox.desktop_supervisor'])
    first.descendants = [self_child]
    with pytest.raises(ValueError, match='supervisor'):
        S.relaunch(manifest, command(), processes=[first], popen=lambda *a, **kw: launches.append(a))
    assert not first.effects and not second.effects and not self_child.effects and not launches


@pytest.mark.parametrize('created', ['missing', None, 9., float('nan'), True, 0.])
def test_session_pid_without_exact_native_creation_witness_cannot_authorize_kill(installation, created):
    _, manifest, launches = installation
    game = Process(200, 'emulator.exe', ['emulator.exe'], created=10.)
    session = {'session_id': WORKER + '-game', 'pid': 200}
    if created != 'missing':
        session['created'] = created
    result = S.relaunch(manifest, command(sessions=[session]), processes=[parent(manifest, game)],
                        popen=lambda *a, **kw: launches.append(a))
    assert not game.effects and result == [] and len(launches) == 1


def test_exact_session_scope_and_creation_witness_are_required_in_closed_receipt(installation):
    _, manifest, launches = installation
    game, other = Process(200, 'emulator.exe', ['emulator.exe']), Process(201, 'other.exe', ['other.exe'])
    valid = {'session_id': WORKER + '-game', 'pid': 200, 'created': 10.}
    foreign = {'session_id': 'f' * 16 + '-other', 'pid': 201, 'created': 10.}
    result = S.relaunch(manifest, command(sessions=[valid, foreign]), processes=[parent(manifest, game, other)],
                        popen=lambda *a, **kw: launches.append(a))
    assert game.effects == ['terminate'] and not other.effects and result == [valid]


def test_reused_child_pid_is_not_terminated_or_killed_during_shutdown(installation, monkeypatch):
    _, manifest, launches = installation
    child = Process(201, manifest['executable'], [manifest['executable'], '--type=renderer'], running=False)
    waits = iter([( [], [child]), ([], [])])
    monkeypatch.setattr(S, 'wait_processes', lambda processes, timeout: next(waits))
    p = parent(manifest, child)
    with pytest.raises(ValueError):
        S.relaunch(manifest, command(), processes=[p], popen=lambda *a, **kw: launches.append(a))
    assert not p.effects and not child.effects and not launches


def test_helper_identity_checks_actual_python_invocation_not_arbitrary_arguments(installation):
    _, manifest, _ = installation
    helper = str(Path(manifest['app']) / 'winembed.py')
    good = {'exe': sys.executable, 'cmdline': [sys.executable, '-u', helper]}
    assert S.owned_helper(good, manifest, sys.executable)
    for args in ([sys.executable, 'unrelated.py', helper],
                 [sys.executable, 'unrelated.py', '-m', 'gbox.desktop_local', '--config', manifest['config']],
                 [sys.executable, '-c', 'pass', '-m', 'gbox', 'worker', '--config', manifest['config']]):
        assert not S.owned_helper({'exe': sys.executable, 'cmdline': args}, manifest, sys.executable)


def test_install_without_opt_in_or_existing_marker_is_noop(tmp_path):
    cfg, calls = SimpleNamespace(data_dir=tmp_path / 'data'), []
    assert S.install(cfg, tmp_path / 'missing.toml', tmp_path / 'missing-root', run=lambda *a, **kw: calls.append(a))['status'] == 'skipped'
    assert calls == [] and not S.directory(cfg).exists()


@pytest.mark.parametrize('field', ['root', 'app', 'executable', 'config'])
def test_supervisor_refuses_a_manifest_redirect_before_pairing_or_process_access(installation, monkeypatch, field):
    from gbox import desktop_local as L
    cfg, manifest, _ = installation
    fixed_root = Path(S.__file__).resolve().parent.parent
    config = manifest['config']
    manifest.update(enabled=True, root=str(fixed_root), app=str(fixed_root / 'clients/desktop'))
    manifest[field] = str(Path(cfg.data_dir) / 'foreign-installation')
    S.write_json(S.directory(cfg) / 'enabled.json', manifest)
    monkeypatch.setattr(L, 'local_config', lambda path: cfg)
    monkeypatch.setattr(L, 'installation_key', lambda path, config: AUTH)
    monkeypatch.setattr(S, 'load_pairing', lambda *args: pytest.fail('pairing accessed before manifest validation'))
    monkeypatch.setattr(S, 'enabled', lambda cfg: False)
    with pytest.raises(ValueError):
        S.run(config)


@pytest.mark.skipif(os.name != 'nt', reason='Windows task registration contract')
@pytest.mark.parametrize('existing', [False, True])
def test_registration_failure_restores_opt_in_state_exactly(installation, existing):
    cfg, manifest, _ = installation
    marker = S.directory(cfg) / 'enabled.json'
    original = b'{"enabled": true, "prior": "preserve-exact-bytes"}'
    if existing:
        S.atomic(marker, original)
    with pytest.raises(RuntimeError, match='register'):
        S.install(cfg, manifest['config'], manifest['root'], opt_in=True,
                  run=lambda *a, **kw: SimpleNamespace(returncode=1))
    assert marker.read_bytes() == original if existing else not marker.exists()


def test_pairing_is_never_saved_without_opt_in_and_is_only_stored_encrypted(tmp_path, monkeypatch):
    cfg, calls = SimpleNamespace(data_dir=tmp_path), []
    def crypt(data, *, decrypt=False):
        calls.append(decrypt)
        return data[7:][::-1] if decrypt else b'CIPHER:' + data[::-1]
    monkeypatch.setattr(S, 'crypt', crypt)
    assert S.save_pairing(cfg, AUTH, 'https://gbox.example', 'f' * 64, 'sensitive-token') is False
    assert not calls and not S.directory(cfg).exists()
    S.write_json(S.directory(cfg) / 'enabled.json', {'enabled': True})
    assert S.save_pairing(cfg, AUTH, 'https://gbox.example', 'f' * 64, 'sensitive-token') is True
    payload = (S.directory(cfg) / 'pairing.bin').read_bytes()
    assert payload.startswith(b'CIPHER:') and b'sensitive-token' not in payload
    assert S.load_pairing(cfg, AUTH)['token'] == 'sensitive-token'
    with pytest.raises(ValueError, match='installation'):
        S.load_pairing(cfg, 'f' * 64)


@pytest.mark.skipif(os.name != 'nt', reason='Windows user DPAPI')
def test_real_windows_dpapi_round_trip_protects_pairing_bytes():
    plain = b'gbox-supervisor-test-credential-no-real-token'
    encrypted = S.crypt(plain)
    assert encrypted != plain and plain not in encrypted
    assert S.crypt(encrypted, decrypt=True) == plain


def test_foreign_local_service_is_rejected_without_sending_it_the_token():
    requests = []
    class Client:
        def get(self, url, **kwargs):
            requests.append((url, kwargs))
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'kind': 'gbox.desktop-local/1', 'installation': 'f' * 64})
    result = S.local_state(SimpleNamespace(token=lambda: 'sensitive-token'), AUTH, Client())
    assert result['foreign'] is True and len(requests) == 1 and not requests[0][1].get('headers')


@pytest.mark.parametrize('change', ['none', 'pid_before', 'exit_before', 'pid_after', 'exit_after', 'handle_after', 'nan', 'negative', 'denied'])
def test_native_process_birth_witness_requires_the_same_live_adapter_handle(monkeypatch, change):
    from gbox import tools
    state = {'exited': change == 'exit_before'}
    proc = SimpleNamespace(pid=201 if change == 'pid_before' else 200,
                           poll=lambda: 0 if state['exited'] else None)
    ad, calls = SimpleNamespace(proc=proc), []
    def query(pid):
        calls.append(pid)
        if change == 'denied':
            raise psutil.AccessDenied(pid)
        def created():
            if change == 'pid_after':
                proc.pid = 201
            if change == 'exit_after':
                state['exited'] = True
            if change == 'handle_after':
                ad.proc = SimpleNamespace(pid=200, poll=lambda: None)
            return float('nan') if change == 'nan' else -1. if change == 'negative' else 12345.5
        return SimpleNamespace(create_time=created)
    monkeypatch.setattr(psutil, 'Process', query)
    actual = tools._native_process_created(ad, 200)
    assert actual == 12345.5 if change == 'none' else actual is None
    if change in ('pid_before', 'exit_before'):
        assert not calls


def test_dead_desktop_recovers_only_config_bound_or_birth_witnessed_orphans(installation):
    _, manifest, launches = installation
    worker = Process(301, sys.executable, [sys.executable, '-P', '-m', 'gbox.desktop_local', '--config', manifest['config']])
    foreign_worker = Process(302, sys.executable, [sys.executable, '-m', 'gbox.desktop_local', '--config', 'other.toml'])
    renderer = Process(303, manifest['executable'], [manifest['executable'], '--type=renderer'])
    game = Process(304, 'emulator.exe', ['emulator.exe'])
    unrelated_game = Process(305, 'emulator.exe', ['emulator.exe'])
    original = {'session_id': WORKER + '-game', 'pid': game.pid, 'created': 10.}
    closed = S.relaunch(manifest, command(sessions=[original]),
                        processes=[worker, foreign_worker, renderer, game, unrelated_game],
                        popen=lambda *a, **kw: launches.append(a))
    assert worker.effects == game.effects == ['terminate']
    assert not foreign_worker.effects and not renderer.effects and not unrelated_game.effects
    assert closed == [original] and len(launches) == 1


@pytest.mark.parametrize('opt_in,checked', [(False, True), (True, True), (True, False)])
def test_rebuild_hook_preserves_explicit_opt_in_and_requires_successful_self_check(installation, monkeypatch, opt_in, checked):
    from gbox import node_rebuild as N
    cfg, manifest, _ = installation
    calls = []
    class Console:
        lines = []
        def __init__(self, ctx):
            pass
        def line(self, *args):
            pass
        def step(self, *args):
            pass
        def flush(self):
            pass
    monkeypatch.setattr(N, 'Console', Console)
    monkeypatch.setattr(N, 'HOST_OS', 'windows')
    monkeypatch.setattr(N, 'ROOT', Path(manifest['root']))
    monkeypatch.setattr(N, 'config_path', lambda: Path(manifest['config']))
    for name in ('code', 'python', 'desktop'):
        monkeypatch.setattr(N, 'step_' + name, lambda *args, label=name: N._receipt(label, 'ok', 'fixture'))
    monkeypatch.setattr(N, 'step_check', lambda *args: (N._receipt('check', 'ok' if checked else 'failed', 'fixture'), checked))
    monkeypatch.setattr(N, 'step_restart', lambda *args: (N._receipt('restart', 'skipped', 'fixture'), 'skipped', 'fixture'))
    monkeypatch.setattr(S, 'install', lambda *args, **kwargs: calls.append(kwargs['opt_in']) or {'status': 'skipped', 'detail': 'fixture'})
    assert N.RebuildIn().enable_remote_admin is False
    N.run(N.RebuildIn(enable_remote_admin=opt_in), SimpleNamespace(config=cfg, artifact=lambda *a, **kw: None))
    assert calls == ([opt_in] if checked else [])


def test_outbox_retries_an_identical_receipt_after_lost_network_ack_without_reexecution(tmp_path, monkeypatch):
    effects, sent = [], []
    receipt = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value)).execute(command(), server_time=1000.)
    def lost_ack(rid, value):
        sent.append((rid, value.copy()))
        raise OSError('server accepted but response was lost')
    try:
        S.flush_receipts(tmp_path, AUTH, lost_ack)
    except OSError:
        pass
    assert sent == [(command()['id'], receipt)]
    record = S.read_json(tmp_path / ('command-' + command()['id'] + '.json'))
    assert record.get('acknowledged') is not True
    monkeypatch.setattr(S.time, 'time', lambda: 2000.)   # command expired; its result still must be deliverable
    assert S.flush_receipts(tmp_path, AUTH, lambda rid, value: sent.append((rid, value.copy()))) == 1
    assert sent[0] == sent[1] and len(effects) == 1
    assert S.flush_receipts(tmp_path, AUTH, lambda *args: pytest.fail('acknowledged receipt redelivered')) == 0


def test_old_controller_crash_reservation_becomes_persisted_unknown_outbox_receipt(tmp_path):
    old, effects, sent = 'f' * 32, [], []
    def crash(value):
        effects.append(value)
        raise SystemExit()
    with pytest.raises(SystemExit):
        S.Executor(tmp_path, AUTH, old, crash).execute(command(controller_id=old), server_time=1000.)
    assert S.flush_receipts(tmp_path, AUTH, lambda rid, value: sent.append((rid, value.copy()))) == 1
    rid, receipt = sent[0]
    assert rid == command()['id'] and receipt['controller_id'] == old and receipt['status'] == 'unknown'
    assert receipt.get('closed_sessions', []) == [] and len(effects) == 1
    record = S.read_json(tmp_path / ('command-' + rid + '.json'))
    assert record['receipt'] == receipt and record['acknowledged'] is True


def test_outbox_never_delivers_another_installations_receipt(tmp_path):
    other = 'f' * 64
    S.Executor(tmp_path, other, CONTROLLER, lambda value: []).execute(command(authority=other), server_time=1000.)
    assert S.flush_receipts(tmp_path, AUTH, lambda *args: pytest.fail('foreign installation receipt')) == 0


def test_one_failed_outbox_delivery_does_not_starve_later_receipts(tmp_path):
    effects, sent, errors = [], [], []
    executor = S.Executor(tmp_path, AUTH, CONTROLLER, lambda value: effects.append(value))
    executor.execute(command(), server_time=1000.)
    executor.execute(command(id='f' * 32), server_time=1000.)
    def send(rid, value):
        if rid == command()['id']:
            raise OSError('one immutable receipt was refused')
        sent.append(rid)
    assert S.flush_receipts(tmp_path, AUTH, send, on_error=lambda *args: errors.append(args)) == 1
    assert sent == ['f' * 32] and len(errors) == 1 and len(effects) == 2
    assert S.read_json(tmp_path / ('command-' + command()['id'] + '.json')).get('acknowledged') is not True
    assert S.read_json(tmp_path / ('command-' + 'f' * 32 + '.json'))['acknowledged'] is True
    assert S.flush_receipts(tmp_path, AUTH, lambda rid, value: sent.append(rid)) == 1
    assert sent == ['f' * 32, command()['id']] and len(effects) == 2


def test_failed_new_desktop_launch_preserves_verified_old_session_closures(installation, tmp_path):
    _, manifest, _ = installation
    game = Process(200, 'emulator.exe', ['emulator.exe'])
    p = parent(manifest, game)
    original = {'session_id': WORKER + '-' + '1' * 16, 'pid': 200, 'created': 10.}
    def cannot_launch(*args, **kwargs):
        raise OSError('fixed executable could not start')
    action = lambda value: S.relaunch(manifest, value, processes=[p], popen=cannot_launch)
    executor = S.Executor(tmp_path / 'receipts', AUTH, CONTROLLER, action)
    requested = command(sessions=[original])
    receipt = executor.execute(requested, server_time=1000.)
    assert receipt['status'] == 'unknown' and receipt['closed_sessions'] == [original]
    assert p.effects == game.effects == ['terminate']
    assert executor.execute(requested, server_time=1001.) == receipt
    assert p.effects == game.effects == ['terminate']


@pytest.mark.skipif(os.name != 'nt', reason='Windows Scheduled Task launch syntax')
@pytest.mark.parametrize('initial_state', ['Ready', 'Running'])
def test_registered_launch_can_find_gbox_and_refresh_only_its_own_task(tmp_path, initial_state):
    root = Path(S.__file__).resolve().parent.parent
    config = tmp_path / 'gbox.toml'
    config.write_text('unused: --help exits before reading configuration')
    harness = tmp_path / 'capture-task.ps1'
    harness.write_text('''param($Python, $Config, $Root, $InitialState)
$global:TaskState = $InitialState
$global:TaskEffects = @()
$global:TaskNames = @()
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory); [pscustomobject]@{Execute=$Execute; Arguments=$Argument; WorkingDirectory=$WorkingDirectory} }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User); @{} }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel); @{} }
function New-ScheduledTaskSettingsSet { param($MultipleInstances, $ExecutionTimeLimit, $RestartCount, $RestartInterval, [switch]$StartWhenAvailable, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries); @{} }
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, $Description, [switch]$Force); $global:CapturedAction=$Action; $global:TaskEffects += 'register'; $global:TaskNames += $TaskName }
function Get-ScheduledTask { param($TaskName); $global:TaskNames += $TaskName; [pscustomobject]@{State=$global:TaskState} }
function Stop-ScheduledTask { param($TaskName); $global:TaskEffects += 'stop'; $global:TaskNames += $TaskName; $global:TaskState='Ready' }
function Start-ScheduledTask { param($TaskName); $global:TaskEffects += 'start'; $global:TaskNames += $TaskName; $global:TaskState='Running' }
& (Join-Path $Root 'scripts/register-desktop-supervisor.ps1') -Python $Python -Config $Config -Root $Root -Installation ('a' * 64) | Out-Null
[pscustomobject]@{Action=$global:CapturedAction; Effects=$global:TaskEffects; Names=$global:TaskNames} | ConvertTo-Json -Compress
''', encoding='utf8')
    captured = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                               str(harness), '-Python', sys.executable, '-Config', str(config), '-Root', str(root),
                               '-InitialState', initial_state],
                              capture_output=True, text=True, timeout=15, check=True)
    assert captured.stdout.strip(), captured.stderr
    result = json.loads(captured.stdout.strip())
    assert result['Effects'] == (['register', 'stop', 'start'] if initial_state == 'Running' else ['register', 'start'])
    assert set(result['Names']) == {'GBox Recovery ' + 'a' * 16}
    action = result['Action']
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'GBOX_TOKEN', 'GBOX_CLIENT_CONTROL')}
    result = subprocess.run([action['Execute'], *shlex.split(action['Arguments']), '--help'],
                            cwd=action['WorkingDirectory'], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert '--config' in result.stdout
