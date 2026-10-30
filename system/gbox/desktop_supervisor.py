"""Opt-in, per-user outbound GBox recovery, independent of Electron and its worker.

Only an authenticated, installation-bound relaunch command can change processes.
No listener, arbitrary executable, shell command, or automatic game launch exists.
An ambiguous process action is recorded before effect and is never replayed.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

HEX = re.compile(r'^[a-f0-9]{32}$')
AUTHORITY = re.compile(r'^[a-f0-9]{64}$')
WORKER = re.compile(r'^[a-f0-9]{16,64}$')


def directory(cfg):
    return Path(cfg.data_dir) / 'desktop-admin'


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    try:
        with tmp.open('xb') as out:
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path, value):
    atomic(path, json.dumps(value, sort_keys=True).encode('utf8'))


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 128_000:
        raise ValueError('Oversized recovery state')
    return json.loads(path.read_text(encoding='utf8'))


def enabled(cfg):
    try:
        return read_json(directory(cfg) / 'enabled.json').get('enabled') is True
    except (OSError, ValueError, AttributeError):
        return False


def crypt(data, *, decrypt=False):
    """Windows DPAPI, bound to the current interactive user; never machine-wide."""
    if os.name != 'nt':
        raise RuntimeError('Windows user protection is required')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buffer), Blob()
    lib = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = lib.CryptUnprotectData if decrypt else lib.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError('Windows credential protection failed')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(result.data)


def save_pairing(cfg, authority, remote, secret, token):
    # Pairing an ordinary PC never opts it into remote process administration.
    if not enabled(cfg):
        return False
    from gbox.desktop_bridge import origin
    if not AUTHORITY.fullmatch(authority) or not AUTHORITY.fullmatch(secret):
        raise ValueError('Invalid recovery pairing identity')
    if not isinstance(token, str) or not 1 <= len(token) <= 16384:
        raise ValueError('Invalid recovery credential')
    value = {'authority': authority, 'remote': origin(remote), 'secret': secret, 'token': token}
    atomic(directory(cfg) / 'pairing.bin', crypt(json.dumps(value).encode('utf8')))
    return True


def load_pairing(cfg, authority):
    path = directory(cfg) / 'pairing.bin'
    if path.stat().st_size > 64_000:
        raise ValueError('Oversized recovery pairing')
    value = json.loads(crypt(path.read_bytes(), decrypt=True))
    from gbox.desktop_bridge import origin
    if value.get('authority') != authority or origin(value['remote']) != value['remote'] \
            or not AUTHORITY.fullmatch(value.get('secret', '')) or not isinstance(value.get('token'), str):
        raise ValueError('Recovery pairing does not match this installation')
    return value


def install(cfg, config_path, root, *, opt_in=False, run=subprocess.run):
    """Install only on explicit opt-in, or refresh an already enabled installation."""
    if os.name != 'nt':
        return {'status': 'skipped', 'detail': 'Windows desktop recovery only'}
    if not opt_in and not enabled(cfg):
        return {'status': 'skipped', 'detail': 'Remote desktop recovery is not enabled'}
    from gbox.desktop_local import installation_key
    root, config_path = Path(root).resolve(), Path(config_path).resolve()
    app = root / 'clients/desktop'
    executable = Path(os.environ['LOCALAPPDATA']) / 'gbox/app/gBox.exe'
    script = root / 'scripts/register-desktop-supervisor.ps1'
    if not executable.is_file() or not (app / 'main.js').is_file() or not script.is_file():
        raise ValueError('The fixed installed GBox desktop or recovery script is missing')
    authority = installation_key(config_path, cfg)
    marker = directory(cfg) / 'enabled.json'
    previous = marker.read_bytes() if marker.exists() else None
    write_json(marker, {'enabled': True, 'authority': authority, 'root': str(root),
                        'config': str(config_path), 'executable': str(executable), 'app': str(app)})
    try:
        result = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                      '-File', str(script), '-Python', sys.executable, '-Config', str(config_path),
                      '-Root', str(root), '-Installation', authority],
                     capture_output=True, timeout=45, check=False,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError('Windows could not register the GBox recovery task')
    except Exception:
        if previous is None:
            marker.unlink(missing_ok=True)
        else:
            atomic(marker, previous)
        raise
    return {'status': 'ok', 'detail': 'Per-user outbound recovery task registered'}


def command_identity(command):
    return hashlib.sha256(json.dumps(command, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class RelaunchFailure(RuntimeError):
    def __init__(self, closed_sessions):
        super().__init__('Replacement GBox could not be launched')
        self.closed_sessions = closed_sessions


class Executor:
    def __init__(self, state_dir, authority, controller_id, action, preflight=lambda command: None):
        self.state_dir, self.authority, self.controller_id, self.action = Path(state_dir), authority, controller_id, action
        self.preflight = preflight

    def execute(self, command, *, server_time):
        if not isinstance(command, dict) or not HEX.fullmatch(str(command.get('id', ''))):
            raise ValueError('Invalid recovery command ID')
        if command.get('op') != 'relaunch' or command.get('authority') != self.authority \
                or command.get('controller_id') != self.controller_id or command.get('force') is not True \
                or not WORKER.fullmatch(str(command.get('worker_id', ''))):
            raise ValueError('Recovery command scope mismatch')
        expiry = command.get('expires_at')
        if type(expiry) not in (int, float) or not math.isfinite(expiry) \
                or type(server_time) not in (int, float) or not math.isfinite(server_time) \
                or not 0 < expiry - server_time <= 125:
            raise ValueError('Expired recovery command')
        path = self.state_dir / ('command-' + command['id'] + '.json')
        digest = command_identity(command)
        if path.exists():
            prior = read_json(path)
            if prior.get('digest') != digest:
                raise ValueError('Recovery command changed after reservation')
            if prior.get('receipt'):
                return prior['receipt']
            receipt = {'controller_id': self.controller_id, 'status': 'unknown',
                       'detail': 'prior effect not confirmed', 'closed_sessions': []}
            write_json(path, prior | {'status': 'unknown', 'receipt': receipt})
            return receipt
        record = {'id': command['id'], 'authority': self.authority, 'controller_id': self.controller_id,
                  'digest': digest, 'status': 'reserved', 'acknowledged': False}
        try:
            self.preflight(command)
        except Exception:
            receipt = {'controller_id': self.controller_id, 'status': 'failed', 'detail': 'local identity changed',
                       'closed_sessions': []}
            write_json(path, record | {'status': 'failed', 'receipt': receipt})
            return receipt
        write_json(path, record)
        try:
            self.preflight(command)
        except Exception:
            receipt = {'controller_id': self.controller_id, 'status': 'failed', 'detail': 'local identity changed',
                       'closed_sessions': []}
            write_json(path, record | {'status': 'failed', 'receipt': receipt})
            return receipt
        closed = []
        try:
            closed = self.action(command) or []
        except RelaunchFailure as exc:
            closed = exc.closed_sessions
            status, detail = 'unknown', 'replacement launch not confirmed'
        except Exception:
            # A process may already have exited or started: never repeat it blindly.
            status, detail = 'unknown', 'relaunch outcome uncertain'
        else:
            status, detail = 'requested', 'fixed gbox relaunch requested'
        receipt = {'controller_id': self.controller_id, 'status': status, 'detail': detail, 'closed_sessions': closed}
        write_json(path, record | {'status': status, 'receipt': receipt})
        return receipt


def flush_receipts(state_dir, authority, send, *, on_error=None):
    """Deliver durable outcomes even after expiry or a supervisor restart."""
    acknowledged = 0
    attempted = 0
    for path in sorted(Path(state_dir).glob('command-*.json')):
        row = read_json(path)
        if row.get('authority') != authority or row.get('acknowledged') is True:
            continue
        if attempted >= 256:
            break
        attempted += 1
        if not HEX.fullmatch(str(row.get('id', ''))) or not HEX.fullmatch(str(row.get('controller_id', ''))):
            raise ValueError('Invalid local recovery receipt identity')
        receipt = row.get('receipt')
        if receipt is None:
            if row.get('status') != 'reserved':
                raise ValueError('Missing local recovery receipt')
            receipt = {'controller_id': row['controller_id'], 'status': 'unknown',
                       'detail': 'prior effect not confirmed', 'closed_sessions': []}
            row = row | {'status': 'unknown', 'receipt': receipt}
            write_json(path, row)
        try:
            send(row['id'], receipt)
        except Exception as exc:
            if on_error is None:
                raise
            on_error(exc)
            continue
        write_json(path, row | {'acknowledged': True})
        acknowledged += 1
    return acknowledged


def same_process(process, witness):
    try:
        return (process.is_running() and process.pid == witness[0] and process.create_time() == witness[1]
                and not windows_exited(process.pid))
    except Exception:
        return False


def windows_exited(pid):
    """Windows may retain an exited PID while another process holds its handle.

    psutil.wait() waits for that PID to disappear even after Windows reports an
    exit code. Recovery must wait for execution to end, not handle owners.
    This read-only check never treats access denial or an unknown wait as exit.
    """
    if sys.platform != 'win32':
        return False
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: absent PID
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:  # WAIT_OBJECT_0, including exit code 259
            return True
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259)
    finally:
        kernel.CloseHandle(handle)


def wait_processes(processes, timeout):
    import psutil
    if sys.platform != 'win32':
        return psutil.wait_procs(processes, timeout=timeout)
    until = time.monotonic() + timeout
    alive, gone = list(processes), []
    while alive:
        for process in list(alive):
            if windows_exited(process.pid):
                alive.remove(process)
                gone.append(process)
        remaining = until - time.monotonic()
        if not alive or remaining <= 0:
            break
        time.sleep(min(.05, remaining))
    return gone, alive


def app_matches(info, executable, app):
    norm = lambda p: os.path.normcase(os.path.abspath(str(p)))
    args = info.get('cmdline') or []
    return norm(info.get('exe') or '') == norm(executable) and 2 <= len(args) <= 3 \
        and norm(args[1]) == norm(app) and (len(args) == 2
        or re.fullmatch(r'--gbox-client-handoff=[a-f0-9]{64}', args[2]) is not None)


def owned_helper(info, manifest, python):
    """Descendance alone does not authorize closing a browser launched by GBox."""
    norm = lambda p: os.path.normcase(os.path.abspath(str(p)))
    args = info.get('cmdline') or []
    if norm(info.get('exe') or '') == norm(manifest['executable']):
        return any(a.startswith('--type=') for a in args[1:])
    if norm(info.get('exe') or '') not in {norm(python), norm(getattr(sys, '_base_executable', python))}:
        return False
    invocation = args[1:]
    while invocation and invocation[0] in ('-P', '-u', '-B', '-s', '-E', '-I'):
        invocation = invocation[1:]
    if invocation[:1] == ['-m']:
        if len(invocation) < 2 or invocation[1] not in ('gbox.desktop_local', 'gbox'):
            return False
        if invocation[1] == 'gbox' and 'worker' not in invocation[2:]:
            return False
        return any(a == '--config' and i + 1 < len(invocation) and norm(invocation[i + 1]) == norm(manifest['config'])
                   for i, a in enumerate(invocation))
    helper = Path(manifest['app']) / 'winembed.py'
    return bool(invocation and not invocation[0].startswith('-') and norm(invocation[0]) == norm(helper))


def relaunch(manifest, command, *, processes=None, popen=subprocess.Popen):
    import psutil
    executable, app = Path(manifest['executable']), Path(manifest['app'])
    if not executable.is_file() or not (app / 'main.js').is_file():
        raise ValueError('Installed GBox executable is unavailable')
    candidates, inspected = [], []
    for process in (processes if processes is not None else psutil.process_iter(['exe', 'cmdline'])):
        try:
            inspected.append(process)
            if app_matches(process.info, executable, app) and not windows_exited(process.pid):
                candidates.append((process, (process.pid, process.create_time())))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if len(candidates) > 1:
        raise ValueError('Ambiguous GBox desktop ownership')
    closed = []
    sessions = command.get('sessions', [])
    if not isinstance(sessions, list) or len(sessions) > 16:
        raise ValueError('Invalid original session witnesses')
    sessions = [s for s in sessions if isinstance(s, dict) and type(s.get('pid')) is int and s['pid'] > 0
                and str(s.get('session_id', '')).startswith(command['worker_id'] + '-')]
    targets, native = {}, []
    def select_native(process, identity):
        matches = [s for s in sessions if s['pid'] == process.pid and type(s.get('created')) in (int, float)
                   and math.isfinite(s['created']) and s['created'] > 0 and s['created'] == identity[1]]
        native.extend((s, identity) for s in matches)
        return bool(matches)
    for process, witness in candidates:
        if not same_process(process, witness):
            raise ValueError('GBox process changed during inspection')
        descendants = process.children(recursive=True)
        if any(p.pid == os.getpid() for p in descendants):
            raise ValueError('Recovery supervisor was unexpectedly owned by the app')
        targets[process.pid] = (process, witness)
        for child in descendants:
            identity = (child.pid, child.create_time())
            matches = select_native(child, identity)
            info = child.as_dict(attrs=['exe', 'cmdline'])
            if (owned_helper(info, manifest, sys.executable) or matches) and not windows_exited(child.pid):
                targets[child.pid] = (child, identity)
    # After an Electron crash its exact config-bound worker or recorded native
    # session can remain orphaned. Never infer ownership from a process name.
    for process in inspected:
        try:
            identity = (process.pid, process.create_time())
            matches = select_native(process, identity)
            info = process.info
            is_python = os.path.normcase(str(info.get('exe') or '')) != os.path.normcase(str(executable))
            if matches or (is_python and owned_helper(info, manifest, sys.executable)):
                if not windows_exited(process.pid):
                    targets[process.pid] = (process, identity)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if os.getpid() in targets:
        raise ValueError('Recovery supervisor cannot restart itself')
    # Complete every identity check before the first effect. A reused PID ends
    # this request; retry requires a new explicit, freshly scoped command.
    if any(not same_process(p, identity) for p, identity in targets.values()):
        raise ValueError('A process changed during recovery inspection')
    for process, witness in candidates:
        if same_process(process, witness):
            process.terminate()
    for process, identity in targets.values():
        if not any(process.pid == p.pid for p, _ in candidates) and same_process(process, identity):
            process.terminate()
    _, alive = wait_processes([p for p, _ in targets.values()], timeout=5)
    for process in alive:
        if same_process(process, targets[process.pid][1]):
            process.kill()
    _, alive = wait_processes(alive, timeout=3)
    if alive:
        raise RuntimeError('The prior GBox process did not exit')
    unique = {(s['session_id'], identity[0], identity[1]) for s, identity in native}
    closed.extend({'session_id': sid, 'pid': pid, 'created': created} for sid, pid, created in sorted(unique))
    # The supervisor may use a different Python distribution from the desktop's
    # installed venv. Inheriting its PYTHONHOME mixes the latter's native modules
    # with the former's standard library and crashes local control on import.
    # Electron assigns the checkout's PYTHONPATH to its own Python helpers.
    excluded = {'GBOX_TOKEN', 'GBOX_CLIENT_CONTROL', 'ELECTRON_RUN_AS_NODE',
                'PYTHONHOME', 'PYTHONPATH', '__PYVENV_LAUNCHER__'}
    env = {k: v for k, v in os.environ.items() if k.upper() not in excluded}
    try:
        popen([str(executable), str(app)], cwd=str(app), env=env, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    except Exception:
        raise RelaunchFailure(closed) from None
    return closed


def verify_observation(command, observed):
    # A recovered/replaced local app must never be killed by an older command.
    if observed.get('foreign'):
        raise ValueError('Another local installation owns the service port')
    if observed.get('worker_id') and observed['worker_id'] != command['worker_id']:
        raise ValueError('The local worker has changed')
    if observed.get('epoch') and observed['epoch'] != command.get('epoch'):
        raise ValueError('The local desktop has changed')


def local_state(cfg, authority, client):
    try:
        response = client.get('http://127.0.0.1:18765/api/desktop-local')
        response.raise_for_status()
        local = response.json()
        if local.get('installation') != authority or local.get('kind') != 'gbox.desktop-local/1':
            return {'epoch': None, 'worker_id': None, 'worker_state': 'unavailable', 'foreign': True}
        response = client.get('http://127.0.0.1:18765/api/desktop-local/bridge',
                              headers={'authorization': 'Bearer ' + cfg.token()})
        response.raise_for_status()
        bridge = response.json()
        epoch, worker = bridge.get('epoch'), bridge.get('worker_id')
        return {'epoch': epoch if HEX.fullmatch(str(epoch)) else None,
                'worker_id': worker if WORKER.fullmatch(str(worker)) else None,
                'worker_state': 'running' if (local.get('worker') or {}).get('running') else 'unavailable'}
    except Exception:
        return {'epoch': None, 'worker_id': None, 'worker_state': 'unavailable'}


def run(config_path):
    import httpx
    from gbox.desktop_local import local_config, installation_key
    cfg = local_config(config_path)
    authority = installation_key(config_path, cfg)
    state_dir = directory(cfg)
    manifest = read_json(state_dir / 'enabled.json')
    if manifest.get('enabled') is not True or manifest.get('authority') != authority \
            or Path(manifest.get('config', '')).resolve() != Path(config_path).resolve():
        raise ValueError('Recovery is not enabled for this installation')
    root = Path(__file__).resolve().parent.parent
    if Path(manifest['root']).resolve() != root or Path(manifest['app']).resolve() != root / 'clients/desktop' \
            or Path(manifest['executable']).resolve() != (Path(os.environ['LOCALAPPDATA']) / 'gbox/app/gBox.exe').resolve():
        raise ValueError('Recovery launch paths differ from the fixed installed GBox')
    # Task Scheduler also enforces IgnoreNew. The file lock covers manual duplicates.
    import msvcrt
    with (state_dir / 'supervisor.lock').open('a+b') as lock:
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        controller = secrets.token_hex(16)
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            executor = Executor(state_dir, authority, controller, lambda command: relaunch(manifest, command),
                                lambda command: verify_observation(command, local_state(cfg, authority, client)))
            while enabled(cfg):
                try:
                    pairing = load_pairing(cfg, authority)
                    headers = {'authorization': 'Bearer ' + pairing['token'],
                               'x-gbox-federation-key': pairing['secret'], 'x-gbox-actor': 'desktop-federation'}
                    base = pairing['remote'] + '/api/federation/' + authority + '/admin'
                    def send_receipt(rid, receipt):
                        sent = client.post(base + '/' + rid + '/result', headers=headers, json=receipt)
                        sent.raise_for_status()
                    delivery_errors = []
                    delivery_error = lambda exc: delivery_errors.append(type(exc).__name__)
                    flush_receipts(state_dir, authority, send_receipt, on_error=delivery_error)
                    observation = local_state(cfg, authority, client)
                    response = client.post(base + '/poll', headers=headers,
                                           json={'controller_id': controller, **{k: v for k, v in observation.items() if k != 'foreign'}})
                    response.raise_for_status()
                    reply = response.json()
                    commands = reply.get('commands', [])
                    if not isinstance(commands, list) or len(commands) > 2:
                        raise ValueError('Invalid recovery batch')
                    for command in commands:
                        executor.execute(command, server_time=reply.get('server_time'))
                        flush_receipts(state_dir, authority, send_receipt, on_error=delivery_error)
                    write_json(state_dir / 'health.json', {'at': time.time(), 'state': 'connected',
                               'controller_id': controller, 'receipt_delivery_errors': delivery_errors[:8], **observation})
                except Exception as exc:
                    # Exception strings can contain credential URLs; record only the class.
                    write_json(state_dir / 'health.json', {'at': time.time(), 'state': 'retrying',
                               'reason': type(exc).__name__, 'controller_id': controller})
                time.sleep(5)


if __name__ == '__main__':
    # Task Scheduler does not inherit Electron's PYTHONPATH. The task executes
    # this fixed script directly; load only its own checkout, never the cwd.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    run(args.config)
