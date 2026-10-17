"""Isolated projects, provenance and bounded processes for native decompilation tools."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

from .registry import ToolUnavailable


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        text = stream.read((2 << 20) + 1)
    if len(text) > 2 << 20:
        raise ValueError('JSON exceeds 2 MiB')
    return json.loads(text)


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temp, path)


def inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Path must remain inside the project')
    return path


def projects(cfg, engine):
    return Path(cfg.runtime).resolve() / 'native-decomp' / engine


def project(cfg, engine, work_id):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', work_id):
        raise ValueError('work_id must be 1..64 letters, digits, underscores or hyphens')
    return inside(projects(cfg, engine), projects(cfg, engine) / work_id)


@contextmanager
def locked(work):
    # Kernel locks release after crashes. Never remove a lock file: another process may hold its inode.
    with (work / '.gbox.lock').open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if stream.read(1) == b'':
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('Project already has an active operation') from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Project already has an active operation') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def stop_process(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                       timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def execute(argv, work, ctx, timeout, env=None):
    """No shell; log to disk, bounded runtime/log size, cancel only this process tree."""
    log = work / ('run-' + uuid.uuid4().hex + '.log')
    start = time.monotonic()
    with log.open('wb') as out:
        proc = subprocess.Popen([str(x) for x in argv], cwd=work, env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=os.name != 'nt',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while proc.poll() is None:
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f'Operation exceeded {timeout}s; log: {log}')
                if log.stat().st_size > 32 << 20:
                    raise RuntimeError(f'Operation log exceeded 32 MiB: {log}')
                ctx.progress(20, 'Native decompilation running; project=' + work.name)
                time.sleep(.5)
        finally:
            stop_process(proc)
    with log.open('rb') as stream:
        stream.seek(max(0, log.stat().st_size - 32000))
        tail = stream.read().decode('utf-8', 'replace')
    ctx.artifact(log.name, tail.encode(), 'text/plain', full_log_sha256=sha(log))
    return {'argv': [str(x) for x in argv], 'returncode': proc.returncode, 'log': str(log),
            'log_sha256': sha(log), 'tail': tail, 'elapsed_s': round(time.monotonic() - start, 3)}


def settings(cfg, engine):
    local = Path(cfg.runtime).resolve() / 'decomp-tools' / 'gbox-local.json'
    installed = read_json(local).get(engine, {}) if local.is_file() else {}
    return {**installed, **(getattr(cfg, 'native_decomp', {}) or {}).get(engine, {})}


def home(cfg, engine):
    names = {'decomp_pipeline': 'DecompPipeline', 'xenonrecomp': 'XenonRecomp', 'rexglue': 'rexglue-sdk'}
    explicit = (getattr(cfg, 'native_decomp', {}) or {}).get(engine, {}).get('home')
    value = explicit or os.environ.get('GBOX_' + engine.upper() + '_HOME') or settings(cfg, engine).get('home')
    return Path(value).expanduser().resolve() if value else Path(cfg.runtime).resolve() / 'decomp-tools' / names[engine]


def executable(cfg, engine, name):
    opts, root = settings(cfg, engine), home(cfg, engine)
    explicit = opts.get(name)
    suffix = '.exe' if os.name == 'nt' else ''
    candidates = [Path(explicit).expanduser()] if explicit else [root / (name + suffix), root / 'bin' / (name + suffix),
        root / 'build' / name / (name + suffix), root / 'build' / name / 'Release' / (name + suffix)]
    return next((p.resolve() for p in candidates if p.is_file()), None)


def require(path, label):
    if path is None or not Path(path).is_file():
        raise ToolUnavailable(label + ' is unavailable; run op=status for setup details')
    return path


def inventory(work):
    rows = []
    for parent, dirs, files in os.walk(work, followlinks=False):
        dirs[:] = [d for d in dirs if d not in ('.git', 'ghidra', 'ghidra_slots', 'harness', 'build')]
        for name in files:
            p = Path(parent) / name
            if p.is_symlink() or name.startswith('.') or p.suffix == '.log' or name.startswith('receipt-') or name == 'gbox-project.json':
                continue
            inside(work, p)
            rows.append({'path': p.relative_to(work).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)})
            if len(rows) > 100000:
                raise ValueError('Artifact inventory exceeds 100000 files')
    return rows
