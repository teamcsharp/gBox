"""Optional desktop parent-pipe control; shutdown decisions run between claims only."""
import json
import hashlib
import os
import queue
import re
import sys
import threading
import time

PREFIX = 'GBOX_CLIENT_CONTROL:'
CURRENT = None   # the desktop app's control pipe when it owns this worker (gbox.node_rebuild asks it to relaunch the app)


class PipeLines:
    """Raw pipe reads avoid holding Python's buffered-stdin lock at shutdown."""
    def __init__(self, fd):
        self.fd, self.buffer = fd, b''

    def readline(self, limit):
        while b'\n' not in self.buffer and len(self.buffer) < limit:
            chunk = os.read(self.fd, min(4096, limit - len(self.buffer)))
            if not chunk:
                break
            self.buffer += chunk
        end = min(self.buffer.find(b'\n') + 1 or len(self.buffer), limit)
        line, self.buffer = self.buffer[:end], self.buffer[end:]
        return line.decode('utf-8', errors='replace')


class Control:
    def __init__(self, secret, stream, emit, *, clock=time.time, pid=os.getpid()):
        self.secret, self.stream, self.emit = secret, stream, emit
        self.clock, self.pid = clock, pid
        self.requests = queue.Queue(maxsize=4)

    def publish(self, **value):
        self.emit(PREFIX + json.dumps(dict(v=1, secret=self.secret, pid=self.pid, **value)))

    def start(self):
        self.publish(event='ready')
        threading.Thread(target=self.read, name='desktop-client-control', daemon=True).start()

    def read(self):
        # The reader NEVER sets stop: a claim can be in flight on the main loop.
        while True:
            line = self.stream.readline(4097)
            if not line:
                return
            if len(line) > 4096 or not line.endswith('\n'):
                continue
            try:
                value = json.loads(line)
                if (value.get('v') != 1 or value.get('secret') != self.secret
                        or value.get('op') != 'stop_if_idle'
                        or not re.fullmatch(r'[a-f0-9]{32}', str(value.get('id', '')))):
                    continue
                self.requests.put_nowait(value)
            except (ValueError, AttributeError, queue.Full):
                continue

    def check(self, idle_reason, stop):
        """Called only before another claim. Unknown/failed inspection is busy."""
        try:
            request = self.requests.get_nowait()
        except queue.Empty:
            return False
        expires = request.get('expires')
        if (not isinstance(expires, (float, int)) or isinstance(expires, bool)
                or not 0 < expires - self.clock() <= 15):
            reason = 'The desktop idle-stop request expired.'
        else:
            try:
                reason = idle_reason()
            except Exception:
                reason = 'Local worker activity could not be verified.'
        if not reason and not 0 < expires - self.clock() <= 15:
            reason = 'The desktop idle-stop request expired during inspection.'
        if reason:
            self.publish(event='refused', id=request['id'], reason=str(reason)[:240])
            return False
        # No claim or job creation can run between this decision and loop exit.
        stop.set()
        self.publish(event='stopping', id=request['id'])
        return True


def from_environment():
    global CURRENT
    secret = os.environ.get('GBOX_CLIENT_CONTROL', '')
    if not re.fullmatch(r'[a-f0-9]{64}', secret) or sys.stdin is None or sys.stdin.isatty():
        return None
    control = Control(secret, PipeLines(sys.stdin.fileno()), lambda line: print(line, flush=True))
    control.start()
    CURRENT = control
    return control


def idle_reason(active, outbox, sessions, running_file):
    if active:
        return 'This PC is still running worker jobs.'
    from .registry import inflight_executions
    if inflight_executions():
        return 'A local tool callable is still running or queued after its caller returned.'
    # Conservatively keep all registered adapters, even a stale one: restarting
    # the UI is optional, and must never invalidate a native game's owner.
    if sessions:
        return 'This PC still owns a native game session.'
    if outbox.pending_count():
        return 'Finished worker results still await delivery.'
    if outbox.protected_sessions(running_file):
        return 'A native game still has a live owned process.'
    return None


def inspect_disk(config_path):
    """Read-only companion for a desktop that has no running worker yet."""
    from pathlib import Path
    from .config import load
    source = Path(config_path)
    if not source.is_file():
        raise RuntimeError('The local worker configuration is unavailable.')
    runtime = load(source).runtime.resolve()
    manifest = runtime / 'gbox-running.json'
    def ownership_bytes():
        try:
            with manifest.open('rb') as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
        except FileNotFoundError:
            return None
        if len(raw) > 4 * 1024 * 1024:
            raise RuntimeError('The local ownership store could not be verified.')
        return raw

    before = ownership_bytes()
    digest = hashlib.sha256(before).digest() if before is not None else None
    stale = 0
    if before is not None:
        records = json.loads(before.decode('utf-8'))
        if not isinstance(records, dict) or len(records) > 10000:
            return dict(runtime=str(runtime), reason='Local native-game ownership still needs reconciliation.')
        from .worker_results import _pid_alive
        for sid, record in records.items():
            if not isinstance(sid, str) or not sid or not isinstance(record, dict):
                return dict(runtime=str(runtime), reason='Local native-game ownership still needs reconciliation.')
            # Query-only identity checks are shared with worker activation.
            # Only positive absence/reuse can release stale protection; denied
            # or legacy/unknown identities remain protected. Never delete the
            # record or invoke orphan cleanup (which can terminate processes).
            alive = _pid_alive(record.get('pid'), recorded_at=record.get('ts'),
                               recorded_identity=record.get('linux_identity'))
            if alive is not False:
                return dict(runtime=str(runtime), reason='Local native-game ownership still needs reconciliation.')
            stale += 1
    results = runtime / 'worker-results'
    if results.exists():
        # pathlib glob may silently skip unreadable directories. An unreadable
        # ownership/result store must block the optional desktop restart.
        inspected = 0
        with os.scandir(results) as namespaces:
            for namespace in namespaces:
                if namespace.is_symlink() or not namespace.is_dir():
                    raise RuntimeError('The local result store could not be verified.')
                with os.scandir(namespace.path) as entries:
                    for entry in entries:
                        inspected += 1
                        if inspected > 10000 or entry.is_symlink():
                            raise RuntimeError('The local result store could not be verified.')
                        if entry.name.endswith('.json'):
                            return dict(runtime=str(runtime), reason='Finished local worker results still need reconciliation.')
                        if entry.name == 'rejected':
                            with os.scandir(entry.path) as rejected:
                                if any(item.name.endswith('.json') for item in rejected):
                                    return dict(runtime=str(runtime), reason='Finished local worker results still need reconciliation.')
    after = ownership_bytes()
    after_digest = hashlib.sha256(after).digest() if after is not None else None
    if digest != after_digest:
        return dict(runtime=str(runtime), reason='Local native-game ownership changed during inspection.')
    return dict(runtime=str(runtime), reason=None, stale_ownership_records=stale)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--inspect':
        raise SystemExit('Only --inspect CONFIG is supported.')
    print(json.dumps(inspect_disk(sys.argv[2])))
