"""Durable finished-result delivery. Retrying a result never executes its tool.

The outbox contains owned result/artifact bytes, never credentials. A result is
released only after the control plane acknowledges its exact normalized digest.
"""
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def normalized_result(result: dict) -> dict:
    return {'job_id': result['job_id'], 'ok': result['ok'],
            'output': result.get('output'), 'error': result.get('error'),
            'log': result.get('log') or [],
            'artifacts': [{'name': a['name'], 'media_type': a['media_type'],
                           'provenance': a.get('provenance') or {}, 'b64': a['b64']}
                          for a in result.get('artifacts') or []]}


def result_digest(result: dict) -> str:
    data = json.dumps(normalized_result(result), sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def _pid_alive(pid):
    if type(pid) is not int or pid <= 0:
        raise RuntimeError('Invalid owned emulator PID; activation was stopped')
    if os.name == 'nt':
        # os.kill(pid, 0) is destructive on Windows; use a query-only handle.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # unknown/access denied also blocks activation
        try:
            code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _sync_dir(path: Path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _mkdir(path: Path):
    if path.is_dir():
        return
    _mkdir(path.parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not path.is_dir():
            raise
    _sync_dir(path.parent)


def _write(path: Path, value: dict):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class ResultOutbox:
    def __init__(self, runtime: Path, server: str, name: str, *, clock=time.time):
        self.server = server.rstrip('/')
        parsed = urlsplit(self.server)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Result delivery server must not contain credentials or query parameters')
        self.name = name
        self.clock = clock
        self.lock = threading.RLock()
        self.delivery_lock = threading.Lock()
        namespace = hashlib.sha256((self.server + '\0' + name).encode()).hexdigest()[:24]
        self.directory = Path(runtime) / 'worker-results' / namespace
        _mkdir(self.directory)
        self.archive = self.directory / 'acknowledged'
        _mkdir(self.archive)

    def _path(self, job_id):
        return self.directory / (hashlib.sha256(job_id.encode()).hexdigest() + '.json')

    def _read(self, path):
        record = json.loads(path.read_text(encoding='utf-8'))
        if (record.get('version') != 1 or record.get('server') != self.server
                or record.get('name') != self.name or not isinstance(record.get('worker_id'), str)
                or not record['worker_id'] or record.get('status') not in {'pending', 'rejected', 'acknowledged'}
                or record.get('result_sha256') != result_digest(record['result'])
                or path not in {self._path(record['result']['job_id']),
                                self.archive / self._path(record['result']['job_id']).name}):
            raise RuntimeError('Invalid durable worker result; delivery and activation were stopped')
        if path.parent == self.archive and record['status'] != 'acknowledged':
            raise RuntimeError('Unacknowledged result in the delivered archive; activation was stopped')
        if record['status'] == 'acknowledged':
            ack = record.get('acknowledgement') or {}
            if (ack.get('accepted') is not True or ack.get('result_sha256') != record['result_sha256']
                    or ack.get('job_id') != record['result']['job_id']
                    or ack.get('worker_id') != record['worker_id']
                    or ack.get('state') not in {'succeeded', 'failed', 'invalid'} or not ack.get('receipt')):
                raise RuntimeError('Invalid durable acknowledgement; activation was stopped')
        return record

    def records(self, *, include_acknowledged=False):
        with self.lock:
            paths = list(self.directory.glob('*.json'))
            if include_acknowledged:
                paths += list(self.archive.glob('*.json'))
            return [self._read(p) for p in sorted(paths)]

    def pending_count(self):
        return sum(r['status'] != 'acknowledged' for r in self.records())

    def save(self, worker_id: str, result: dict):
        payload = normalized_result(result)
        digest = result_digest(payload)
        path = self._path(payload['job_id'])
        with self.lock:
            archived = self.archive / path.name
            if archived.exists():
                path = archived
            if path.exists():
                old = self._read(path)
                if old['worker_id'] != worker_id or old['result_sha256'] != digest:
                    raise RuntimeError('A different finished result already occupies this job ID')
                return old
            record = {'version': 1, 'server': self.server, 'name': self.name,
                      'worker_id': worker_id, 'result': payload, 'result_sha256': digest,
                      'created': self.clock(), 'attempts': 0, 'next_attempt': 0,
                      'status': 'pending'}
            _write(path, record)
            return record

    def deliver(self, client, job_id: str, *, force=False):
        """One bounded attempt; uncertain responses retain exactly the same bytes."""
        # Serialize actual sends separately. Heartbeats and newly finished
        # results must not wait behind a network timeout.
        with self.delivery_lock:
            with self.lock:
                path = self._path(job_id)
                if not path.exists():
                    path = self.archive / path.name
                record = self._read(path)
                if record['status'] == 'acknowledged':
                    return True
                if record['status'] == 'rejected' or (not force and record['next_attempt'] > self.clock()):
                    return False
                record['attempts'] += 1
                record['next_attempt'] = self.clock() + min(60, 2 ** min(record['attempts'], 6))
                # Persist the attempt BEFORE transport. A lost response never clears this record.
                _write(path, record)
            try:
                response = client.post(f"/api/workers/{record['worker_id']}/result",
                                       json=record['result'], timeout=20)
                response.raise_for_status()
                ack = response.json()
                if (not isinstance(ack, dict) or ack.get('accepted') is not True
                        or ack.get('job_id') != job_id or ack.get('worker_id') != record['worker_id']
                        or ack.get('result_sha256') != record['result_sha256']
                        or ack.get('state') not in {'succeeded', 'failed', 'invalid'}
                        or not isinstance(ack.get('receipt'), str) or not ack['receipt']):
                    raise ValueError('The control plane did not verify this exact result')
                record.update(status='acknowledged', acknowledgement=ack, acknowledged_at=self.clock())
                record.pop('last_error', None)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if 400 <= status < 500 and status not in {408, 429}:
                    record['status'] = 'rejected'
                record['last_error'] = {'kind': 'http', 'status': status}
            except (httpx.HTTPError, ValueError) as exc:
                record['last_error'] = {'kind': type(exc).__name__}
            with self.lock:
                current = self._read(path)
                if (current['result_sha256'] != record['result_sha256']
                        or current['worker_id'] != record['worker_id']
                        or current['attempts'] != record['attempts'] or current['status'] != 'pending'):
                    raise RuntimeError('Durable result changed during transport; acknowledgement was not applied')
                _write(path, record)
                if record['status'] == 'acknowledged' and path.parent == self.directory:
                    destination = self.archive / path.name
                    if destination.exists():
                        raise RuntimeError('An acknowledged result already occupies this job ID')
                    os.replace(path, destination)
                    _sync_dir(self.archive)
                    _sync_dir(self.directory)
            return record['status'] == 'acknowledged'

    def send_ready(self, client, *, maximum=4, force=False):
        acknowledged = []
        candidates = [r for r in self.records() if r['status'] == 'pending'
                      and (force or r['next_attempt'] <= self.clock())][:maximum]
        for record in candidates:
            jid = record['result']['job_id']
            if self.deliver(client, jid, force=force):
                acknowledged.append(jid)
        return acknowledged

    def protected_sessions(self, running_file: Path, *, is_alive=_pid_alive):
        """An acknowledged native launch must not fall into startup orphan killing.

        A retained PID record cannot prove a process is dead or safely reattach its
        adapter. Refuse new activation until ownership is independently reconciled.
        """
        if not running_file.exists():
            return []
        running = json.loads(running_file.read_text(encoding='utf-8'))
        if not isinstance(running, dict):
            raise RuntimeError('Invalid native ownership manifest; worker activation was stopped')
        protected = []
        for sid, record in running.items():
            if not isinstance(sid, str) or not isinstance(record, dict):
                raise RuntimeError('Invalid native ownership manifest; activation was stopped')
            if is_alive(record.get('pid')):
                protected.append(sid)
        return sorted(protected)
