"""Owned, bounded browser leases shared by the Node tests and Python UI evidence.

One small supervisor per browser holds a Windows kill-on-close Job Object. Its
stdin is a lifetime lease: losing the client closes the entire browser tree.
No existing browser or user profile is adopted. See docs/browser-lifecycle.md.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import logging
import math
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import psutil


def alive(pid, created):
    try:
        return abs(psutil.Process(int(pid)).create_time() - float(created)) < .000001
    except (psutil.Error, TypeError, ValueError):
        return False


def settings():
    def number(name, default, low=1):
        value = float(os.environ.get(name, default))
        if not math.isfinite(value) or value < low:
            raise ValueError(f'{name} must be >= {low}')
        return value
    sessions = int(number('GBOX_BROWSER_MAX_SESSIONS', 2))
    return dict(max_sessions=sessions, max_queue=int(number('GBOX_BROWSER_MAX_QUEUE', sessions * 4)),
                queue_s=number('GBOX_BROWSER_QUEUE_TIMEOUT_S', 120),
                startup_s=number('GBOX_BROWSER_STARTUP_TIMEOUT_S', 30),
                lifetime_s=number('GBOX_BROWSER_TIMEOUT_S', 600),
                budget_mb=number('GBOX_BROWSER_BUDGET_MB', min(2048, psutil.virtual_memory().total / 2**20 * .1)),
                session_mb=number('GBOX_BROWSER_SESSION_MB', 0, 0))


class Registry:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('GBOX_BROWSER_STATE') or Path(tempfile.gettempdir()) / 'gbox-browser-managed').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'profiles').mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'leases.sqlite3', timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, doc TEXT NOT NULL)')
        self.db.commit()

    def rows(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT doc FROM leases')]

    def put(self, row):
        self.db.execute('INSERT OR REPLACE INTO leases VALUES (?,?)', (row['id'], json.dumps(row)))

    def update(self, row, **values):
        row.update(values)
        with self.db:
            self.put(row)

    def acquire(self, limits, stopped):
        # A supervisor hard-crash closes its Windows job but cannot run finally.
        # Recover only its marked disposable profile after all recorded PIDs died.
        for stale in self.rows():
            if (stale.get('profile') and stale['state'] != 'closed'
                    and not alive(stale['broker_pid'], stale['broker_created'])
                    and not alive(stale.get('browser_pid'), stale.get('browser_created'))
                    and not any(alive(p['pid'], p['created']) for p in stale.get('members', []))):
                try:
                    if Path(stale['profile']).exists(): clean_profile(self, stale)
                    self.update(stale, state='closed', recovered=True, rss=0)
                except (OSError, ValueError, RuntimeError):
                    pass  # retain the evidence and retry on a later invocation
        me = psutil.Process()
        owner = psutil.Process(os.getppid())
        row = dict(id=uuid.uuid4().hex, broker_pid=me.pid, broker_created=me.create_time(),
                   owner_pid=owner.pid, owner_created=owner.create_time(), queued_at=time.time(), state='queued', rss=0)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            waiting = [r for r in self.rows() if r['state'] == 'queued' and alive(r['broker_pid'], r['broker_created'])]
            if len(waiting) >= limits['max_queue']:
                raise RuntimeError('Browser queue is full; retry after an active task finishes')
            self.put(row)
        try:
            while not stopped.is_set():
                if not alive(row['owner_pid'], row['owner_created']):
                    raise RuntimeError('Browser client exited while queued')
                with self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    live = []
                    for r in self.rows():
                        if r['state'] not in ('queued', 'starting', 'running', 'orphaned'):
                            continue
                        if not alive(r['broker_pid'], r['broker_created']):
                            # A crashed Windows supervisor closes its job automatically.
                            # On other platforms retain a still-live owned browser as an
                            # orphan occupying a slot, rather than start unlimited replacements.
                            r['state'] = 'orphaned' if alive(r.get('browser_pid'), r.get('browser_created')) else 'abandoned'
                            self.put(r)
                        if r['state'] in ('queued', 'starting', 'running', 'orphaned'):
                            live.append(r)
                    active = [r for r in live if r['state'] != 'queued']
                    waiters = sorted((r for r in live if r['state'] == 'queued'), key=lambda r: (r['queued_at'], r['id']))
                    if waiters and waiters[0]['id'] == row['id'] and len(active) < limits['max_sessions'] and sum(r.get('rss', 0) for r in active) < limits['budget_mb'] * 2**20:
                        row['state'] = 'starting'; self.put(row)
                        return row
                if time.time() - row['queued_at'] >= limits['queue_s']:
                    raise TimeoutError('Timed out waiting for a browser slot or memory budget')
                stopped.wait(.1)
            raise RuntimeError('Browser request cancelled before startup')
        except BaseException:
            self.update(row, state='cancelled')
            raise


class WindowsTree:
    """Assign the suspended browser before it can create any children."""
    def __init__(self, args):
        from ctypes import wintypes as W
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.k
        class SI(ctypes.Structure):
            _fields_ = [('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR), ('lpTitle', W.LPWSTR),
                        ('dwX', W.DWORD), ('dwY', W.DWORD), ('dwXSize', W.DWORD), ('dwYSize', W.DWORD),
                        ('dwXCountChars', W.DWORD), ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD),
                        ('dwFlags', W.DWORD), ('wShowWindow', W.WORD), ('cbReserved2', W.WORD),
                        ('lpReserved2', ctypes.c_void_p), ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)]
        class PI(ctypes.Structure):
            _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', W.DWORD),
                        ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active_limit', W.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]; k.CreateJobObjectW.restype = W.HANDLE
        k.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
        k.CreateProcessW.argtypes = [W.LPCWSTR,W.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,W.BOOL,W.DWORD,ctypes.c_void_p,W.LPCWSTR,ctypes.POINTER(SI),ctypes.POINTER(PI)]
        k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        k.ResumeThread.argtypes = [W.HANDLE]; k.ResumeThread.restype = W.DWORD
        k.CloseHandle.argtypes = [W.HANDLE]
        k.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        k.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
        k.QueryInformationJobObject.argtypes = [W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.c_void_p]
        self.job = k.CreateJobObjectW(None, None); self.process = None
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close(); raise ctypes.WinError(ctypes.get_last_error())
        si, pi = SI(), PI(); si.cb = ctypes.sizeof(si)
        if not k.CreateProcessW(args[0], ctypes.create_unicode_buffer(subprocess.list2cmdline(args)), None,None,False,
                                0x08000000 | 0x4, None,None,ctypes.byref(si),ctypes.byref(pi)):
            error = ctypes.get_last_error(); self.close(); raise ctypes.WinError(error)
        self.process = pi.process; self.pid = pi.pid
        try:
            if not k.AssignProcessToJobObject(self.job, pi.process):
                error = ctypes.get_last_error(); k.TerminateProcess(pi.process, 1); raise ctypes.WinError(error)
            if k.ResumeThread(pi.thread) == 0xffffffff:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close(); raise
        finally:
            k.CloseHandle(pi.thread)

    def pids(self):
        from ctypes import wintypes as W
        class Pids(ctypes.Structure):
            _fields_ = [('assigned',W.DWORD),('count',W.DWORD),('pids',ctypes.c_size_t*4096)]
        result = Pids()
        if not self.k.QueryInformationJobObject(self.job,3,ctypes.byref(result),ctypes.sizeof(result),None):
            raise ctypes.WinError(ctypes.get_last_error())
        return list(result.pids[:result.count])

    def close(self):
        if self.job:
            self.k.TerminateJobObject(self.job, 0)
            self.k.CloseHandle(self.job); self.job = None
        if self.process:
            self.k.CloseHandle(self.process); self.process = None


class PosixTree:
    def __init__(self, args):
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.pid = self.proc.pid

    def pids(self):
        try:
            p = psutil.Process(self.pid)
            return [p.pid] + [c.pid for c in p.children(recursive=True)]
        except psutil.NoSuchProcess:
            return []

    def close(self):
        with contextlib.suppress(ProcessLookupError): os.killpg(self.pid, signal.SIGTERM)
        try: self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError): os.killpg(self.pid, signal.SIGKILL)
            self.proc.wait(timeout=3)
        # The root can exit ahead of its renderers.
        with contextlib.suppress(ProcessLookupError): os.killpg(self.pid, signal.SIGKILL)


def browser_args(browser, profile, software_gl=False):
    args = [str(Path(browser).resolve()), '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
            '--user-data-dir='+str(profile)]
    if os.environ.get('GBOX_BROWSER_NO_SANDBOX') == '1':
        if os.name == 'nt' or not os.environ.get('GBOX_BROWSER_NO_SANDBOX_REASON', '').strip():
            raise ValueError('Unsandboxed mode requires a documented Linux/container reason; Windows remains sandboxed')
        args.append('--no-sandbox')
    if software_gl:
        args += ['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']
    return args + ['about:blank']


def clean_profile(registry, row):
    profile = Path(row['profile'])
    parent = (registry.root/'profiles').resolve()
    if profile.is_symlink() or profile.resolve().parent != parent or profile.name != row['id']:
        raise ValueError('Refusing profile cleanup outside the owned profile directory')
    mark = json.loads((profile/'gbox-owner.json').read_text())
    if mark['id'] != row['id']:
        raise ValueError('Profile ownership marker does not match')
    # Never delete a profile still held by any recorded process, even if root exited.
    if any(alive(p['pid'],p['created']) for p in row.get('members',[])):
        raise RuntimeError('Owned browser processes have not exited; preserving profile')
    for attempt in range(40):
        try: shutil.rmtree(profile); return
        except FileNotFoundError: return
        except OSError:
            if attempt == 39: raise
            time.sleep(.1)


def emit(value):
    print(json.dumps(value), flush=True)


def host(browser, software_gl=False):
    stop = threading.Event()
    def input_reader():
        try:
            for line in sys.stdin:
                if line.strip() == 'close': break
        finally: stop.set()
    threading.Thread(target=input_reader, daemon=True).start()
    for sig in (signal.SIGTERM,signal.SIGINT): signal.signal(sig,lambda *_:stop.set())
    registry=Registry(); limits=settings(); row=None; tree=None; error=None
    log=logging.getLogger('browser-lifecycle');log.setLevel(logging.INFO)
    handler=RotatingFileHandler(registry.root/'events.jsonl',maxBytes=1<<20,backupCount=3)
    log.addHandler(handler)
    def event(kind, **values):log.info(json.dumps({'event':kind,'time':time.time(),'lease':row['id'] if row else None,**values}))
    try:
        row=registry.acquire(limits,stop)
        profile=registry.root/'profiles'/row['id'];profile.mkdir()
        (profile/'gbox-owner.json').write_text(json.dumps({'id':row['id'],'broker_pid':os.getpid()}))
        registry.update(row,profile=str(profile))
        args=browser_args(browser,profile,software_gl)
        registry.update(row,sandboxed='--no-sandbox' not in args,
                        sandbox_reason=os.environ.get('GBOX_BROWSER_NO_SANDBOX_REASON','')[:500] if '--no-sandbox' in args else '')
        tree=(WindowsTree if os.name=='nt' else PosixTree)(args)
        created=psutil.Process(tree.pid).create_time()
        registry.update(row,browser_pid=tree.pid,browser_created=created)
        start=time.monotonic(); ready=False; peak=0; peak_handles=0
        while not stop.wait(.25):
            if not alive(row['owner_pid'],row['owner_created']):
                event('client_exited');break
            elapsed=time.monotonic()-start
            if elapsed>limits['lifetime_s']:raise TimeoutError('Browser session lifetime exceeded')
            members=[];rss=0;handles=0;cpu=0
            for pid in tree.pids():
                try:
                    p=psutil.Process(pid);members.append({'pid':pid,'created':p.create_time()});rss+=p.memory_info().rss
                    cpu+=sum(p.cpu_times()[:2]);handles+=p.num_handles() if os.name=='nt' else p.num_fds()
                except psutil.Error:pass
            peak=max(peak,rss)
            peak_handles=max(peak_handles,handles)
            registry.update(row,members=members,rss=rss,peak_rss=peak,handles=handles,peak_handles=peak_handles,cpu_seconds=cpu)
            if not members:
                if ready:event('browser_exited');break
                raise RuntimeError('Browser process tree exited during startup')
            if limits['session_mb'] and rss>limits['session_mb']*2**20:raise RuntimeError('Owned browser exceeded its configured session memory limit')
            if not ready:
                try:
                    lines=(profile/'DevToolsActivePort').read_text().splitlines()
                    port=int(lines[0]);endpoint=lines[1]
                    if not 0<port<65536 or not endpoint.startswith('/devtools/browser/'):raise ValueError('Invalid local debugging endpoint')
                except (OSError,ValueError,IndexError):
                    if elapsed>limits['startup_s']:raise TimeoutError('Browser startup timed out')
                    continue
                registry.update(row,state='running',port=port)
                emit({'ready':True,'lease':row['id'],'pid':tree.pid,'profile':str(profile),'port':port,
                      'browser_ws':f'ws://127.0.0.1:{port}{endpoint}','sandboxed':'--no-sandbox' not in browser_args(browser,profile,software_gl)})
                event('started',pid=tree.pid,port=port);ready=True
    except BaseException as exc:
        error=f'{type(exc).__name__}: {exc}';emit({'error':error});event('failed',error=error)
    finally:
        if tree:
            tree.close()
            deadline=time.monotonic()+5
            while row and any(alive(p['pid'],p['created']) for p in row.get('members',[])) and time.monotonic()<deadline:time.sleep(.05)
        if row:
            cleanup_error=None
            if row.get('profile'):
                try:clean_profile(registry,row)
                except Exception as exc:cleanup_error=str(exc)
            registry.update(row,state='cleanup_pending' if cleanup_error else 'closed',ended=time.time(),error=error,cleanup_error=cleanup_error,rss=0)
            event('closed',cleanup_error=cleanup_error,peak_rss=row.get('peak_rss',0))
            emit({'closed':True,'cleanup_error':cleanup_error})
        registry.db.close();handler.close();log.removeHandler(handler)


class BrowserLease:
    """Python caller for the same crash-safe supervisor the Node clients use."""
    def __init__(self,browser,software_gl=False):self.browser=browser;self.software_gl=software_gl;self.proc=None
    def __enter__(self):
        args=[sys.executable,str(Path(__file__).resolve()),'host','--browser',self.browser]
        if self.software_gl:args.append('--software-gl')
        self.proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            messages=queue.Queue()
            threading.Thread(target=lambda:[messages.put(line) for line in self.proc.stdout],daemon=True).start()
            reply=json.loads(messages.get(timeout=settings()['queue_s']+settings()['startup_s']+10))
            if not reply.get('ready'):raise RuntimeError(reply.get('error') or 'Browser did not start')
            return reply
        except BaseException:self.__exit__(None,None,None);raise
    def __exit__(self,*_):
        if not self.proc:return
        if self.proc.stdin:
            with contextlib.suppress(OSError):self.proc.stdin.write('close\n');self.proc.stdin.flush();self.proc.stdin.close()
        try:self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill();self.proc.wait(timeout=5)
        for stream in (self.proc.stdout,self.proc.stderr):
            if stream:
                with contextlib.suppress(OSError):stream.close()


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['host','status'])
    ap.add_argument('--browser');ap.add_argument('--software-gl',action='store_true')
    a=ap.parse_args()
    if a.command=='status':
        r=Registry()
        rows=[row|{'broker_alive':alive(row['broker_pid'],row['broker_created']),
                   'browser_alive':alive(row.get('browser_pid'),row.get('browser_created')),
                   'live_members':[p for p in row.get('members',[]) if alive(p['pid'],p['created'])]} for row in r.rows()]
        emit({'limits':settings(),'leases':rows});r.db.close()
    elif not a.browser:ap.error('--browser is required')
    else:host(a.browser,a.software_gl)
