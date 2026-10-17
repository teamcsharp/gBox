"""Durable PSO action/checkpoint capture without delaying a successful live command.

Input observations remain approximate. Native states are copied from the existing
rewind ring; this recorder never takes an extra state or borrows a human save slot.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

import httpx

MAX_LOCAL = 20 * 2**30
MAX_STATE = 128 * 2**20
_recorders = {}
_guard = threading.Lock()
READS = {'capabilities', 'rehook', 'status', 'list', 'floor_list', 'mag', 'modes', 'bosses', 'adventure_status'}
FIELDS = {'op', 'on', 'code', 'codes', 'count', 'equip', 'target', 'rare', 'highest', 'max_grind', 'radius',
          'name', 'value', 'factor', 'character_class', 'item_id', 'properties', 'interval', 'categories'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def action(inp, result):
    """Resolve randomness now, never roll again when reproducing a human action."""
    value = {k: v for k, v in inp.items() if k in FIELDS}
    op = value.get('op')
    if op in READS or not op:
        return None
    if op in ('pso_face_apply','pso_face_restore'):
        return {'schema':1,'tool':'pso_faces',
                'input':{k:v for k,v in inp.items() if k in ('op','candidate','key','address')},
                'replay_input':{},'result':{'verified':result.get('verified')},'replayable':False,
                'reason':'Live face texture RAM is retained in subsequent native checkpoints; a standalone paint action is not yet replayed'}
    replay = dict(value)
    reason = ''
    if op in ('floor_rares', 'floor_spawn'):
        codes = result.get('codes')
        if not isinstance(codes, list) or not codes:
            reason = 'The applied drop did not report its resolved item codes'
        else:
            replay.update(op='floor_spawn', codes=list(codes), count=len(codes), code='')
    elif op == 'randomized':
        # Each actual cycle is captured separately. Re-starting a random timer
        # would equip different items at a different point in the demo.
        reason = 'Mode configuration; recorded resolved equipment cycles drive playback'
    elif op == 'item_set' and result.get('after', {}).get('code'):
        replay.update(code=result['after']['code'], rare=False)
    from .pso_live import OPS
    if op not in OPS:
        reason='This queued PSO action has no verified live replay handler; its effects remain in native checkpoints'
    return {'schema': 1, 'tool': 'pso_mods', 'input': value, 'replay_input': replay,
            'result': {k: v for k, v in result.items() if k in
                       ('verified', 'codes', 'max_grinds', 'created', 'requested', 'spawned', 'shown_now',
                        'stat', 'permanent_scape', 'hp', 'tp', 'equipped', 'mag', 'food', 'before', 'after')},
            'replayable': not reason and result.get('verified') is not False,
            'reason': reason or ('The game did not verify this action' if result.get('verified') is False else ''),
            'evidence': 'native action receipt; observed-input reproduction is not a frame-exact TAS'}


class Recorder:
    def __init__(self, sid, ad, game, ctx):
        self.sid, self.ad, self.game, self.ctx = sid, ad, game, ctx
        self.root = Path(ctx.config.runtime)/'gameplay-actions'/sid
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.seq = max((int(p.stem.split('-')[0]) for p in self.root.glob('*-event.json')), default=0)
        self.branch = 0
        self.last_snapshot = 0
        self.closed = False
        self.error = None
        self.identity = None
        self.cards = None
        self.manifest = self.root/'manifest.json'
        if self.manifest.is_file():
            kept=json.loads(self.manifest.read_text())
            self.identity,self.cards=kept.get('identity'),kept.get('cards')
        self.wakeup = threading.Event()
        self.sender = threading.Thread(target=self.upload, daemon=True, name='gameplay-actions-'+sid)
        self.sender.start()

    def status(self):
        return {'state': 'recording' if not self.error else 'retained_locally',
                'mode': 'observed PSO input and native action/checkpoint journal; not frame-exact TAS',
                'pending': len(list(self.root.glob('*-event.json'))), 'error': self.error}

    def save(self, kind, payload, token=None, at=None):
        raw = {'kind': kind, 'payload': payload, 'token': token or 'action:'+uuid.uuid4().hex,
               'at': time.time() if at is None else at}
        data = json.dumps(raw, allow_nan=False).encode()
        if len(data) > 16384:
            raise ValueError('Gameplay action exceeds 16 KiB')
        with self.lock:
            if self.used() + len(data) > MAX_LOCAL:
                raise ValueError('Local gameplay-action budget reached; previous runs were retained')
            self.seq += 1
            path = self.root/f'{self.seq:010d}-event.json'
            temp = path.with_suffix('.tmp')
            temp.write_bytes(data)
            os.replace(temp, path)
        self.wakeup.set()

    def used(self):
        return sum(p.stat().st_size for p in self.root.parent.glob('*/*') if p.is_file())

    def blob(self, path):
        path = Path(path)
        before = path.stat()
        if not 0 < before.st_size <= MAX_STATE:
            raise ValueError('Gameplay checkpoint exceeds 128 MiB')
        target = self.root/(uuid.uuid4().hex+'.blob')
        shutil.copyfile(path, target)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            target.unlink(missing_ok=True)
            raise ValueError('Gameplay checkpoint changed during capture')
        sha = digest(target)
        kept = self.root/(sha+'.blob')
        if kept.exists():
            target.unlink()
        else:
            target.replace(kept)
        return {'sha256': sha, 'bytes': before.st_size}

    def fingerprint(self):
        proc = getattr(self.ad, 'proc', None)
        argv = getattr(proc, 'args', [])
        exe = str(argv[0]) if isinstance(argv, (list, tuple)) and argv else ''
        # Linux flatpak's command is not the emulator executable. This identity
        # is intentionally unsupported for cross-worker states until resolved.
        exe_sha = digest(exe) if exe and Path(exe).is_file() else None
        core = None
        if isinstance(argv, (list, tuple)) and '-L' in argv:
            core = str(argv[argv.index('-L')+1])
        source = self.game.get('_rom_path')
        return {'adapter': self.ad.name, 'platform': self.game.get('platform'),
                'emulator_sha256': exe_sha, 'core_sha256': digest(core) if core else None,
                'rom_sha256': digest(source) if source and Path(source).is_file() else None,
                'state_suffix': '.s08' if self.ad.name == 'dolphin' else '.state'}

    def capture_cards(self):
        from .memory_card_emulators import discover, describe
        result = []
        for row in discover(self.ad, self.game):
            path = Path(row['path'])
            try:
                before = path.stat()
                raw = path.read_bytes()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Memory card changed during read')
                if not describe(raw, self.game['platform'])['formatted']:
                    continue
                info = self.blob(path)
                result.append(info | {'slot': row['slot'], 'name': path.name})
            except (OSError, ValueError):
                continue
        if not result:
            raise ValueError('No stable memory card available for an isolated PSO demonstration')
        return result

    def checkpoint(self, path, kind='checkpoint'):
        if kind not in ('checkpoint', 'restore'):
            raise ValueError('Unknown gameplay checkpoint kind')
        now = time.time()
        # Keep every actual state restore. Periodic checkpoints need not create
        # another 40 MiB archive entry every 20 seconds.
        if kind == 'checkpoint' and now-self.last_snapshot < 120:
            return
        with self.lock:
            used = self.used()
            if used + Path(path).stat().st_size > MAX_LOCAL or shutil.disk_usage(self.root).free < 4*2**30:
                raise ValueError('Gameplay snapshot budget reached; existing captures retained')
            info = self.blob(path)
            # Hashing a disc image belongs in the uploader, never in the state
            # callback while a person's game is resuming.
            if kind == 'restore':
                self.branch += 1
            payload = info | {'schema': 1, 'operation': kind, 'branch': self.branch,
                              'captured_at': now, 'source': 'existing verified rewind checkpoint',
                              'adapter': self.ad.name, 'platform': self.game.get('platform')}
            self.save('checkpoint', payload, at=now)
            self.last_snapshot = now

    def upload_blob(self, sha):
        path = self.root/(sha+'.blob')
        with path.open('rb') as stream:
            response = httpx.post(self.ctx.server+'/api/gameplay-memory/blobs/'+sha,
                headers=self.ctx.headers, content=iter(lambda: stream.read(2**20), b''), timeout=120)
        response.raise_for_status()
        if response.json().get('sha256') != sha:
            raise ValueError('Archived gameplay snapshot hash differs')

    def upload_once(self):
        if not self.ctx.server:
            return
        if self.identity is None:
            self.identity=self.fingerprint()
        if self.cards is None:
            self.cards=self.capture_cards()
        if not self.manifest.is_file():
            proc=getattr(self.ad,'proc',None)
            row={'session_id':self.sid,'game':self.game,'identity':self.identity,'cards':self.cards,
                 'pid':getattr(proc,'pid',None),'started':time.time()}
            try:row['process_created']=__import__('psutil').Process(proc.pid).create_time()
            except Exception:pass
            temp=self.manifest.with_suffix('.tmp');temp.write_text(json.dumps(row));temp.replace(self.manifest)
        for path in sorted(self.root.glob('*-event.json'))[:100]:
            body = json.loads(path.read_text())
            if body['kind'] == 'checkpoint':
                body['payload'].update(identity=self.identity, cards=self.cards)
                for ref in [body['payload'], *self.cards]:
                    self.upload_blob(ref['sha256'])
            response = httpx.post(self.ctx.server+f'/api/gameplay-memory/runs/{self.sid}/observe',
                                  headers=self.ctx.headers, json=body, timeout=10)
            response.raise_for_status()
            if not response.json().get('saved'):
                raise ValueError('Spark did not accept the gameplay event')
            path.unlink()
        self.error = None

    def upload(self):
        # A session can end while its pending immutable events still need to be
        # uploaded. Bounded retry continues for this worker's lifetime.
        while not self.closed or list(self.root.glob('*-event.json')):
            self.wakeup.wait(10)
            self.wakeup.clear()
            try:
                self.upload_once()
            except Exception as error:
                self.error = str(error)[:240]
                time.sleep(1)


def start(sid, ad, game, ctx):
    from .pso_controls import is_pso
    if not ctx or not getattr(ctx.config, 'gameplay_memory_enabled', True) or getattr(ctx, 'agent_use', False) or not is_pso(game):
        return {'state': 'off'}
    recover_pending(ctx)
    with _guard:
        recorder = _recorders.get(sid)
        if recorder is None:
            recorder = _recorders[sid] = Recorder(sid, ad, game, ctx)
    def checkpoint(path, kind='checkpoint'):
        try:
            recorder.checkpoint(path, kind)
        except Exception as error:
            recorder.error = str(error)[:240]
    ad.gameplay_checkpoint = checkpoint
    return recorder.status()


def record(sid, inp, result, ctx, command_id):
    """Best effort and non-networked; never turn a successful mutation into failure."""
    try:
        from .tools import SESSIONS
        current = SESSIONS.get(sid)
        if not current:
            return
        if sid not in _recorders:
            start(sid, current[0], current[1], ctx)
        recorder = _recorders.get(sid)
        payload = action(inp, result)
        if recorder and payload:
            recorder.save('mod_action', payload, token='pso-live:'+sid+':'+str(command_id))
    except Exception as error:
        if sid in _recorders:
            _recorders[sid].error = str(error)[:240]


def randomized(sid, gear, ctx, cycle):
    """Persist each resolved item, not just the request to start a random timer."""
    try:
        recorder = _recorders.get(sid)
        if recorder:
            recorder.save('mod_action', {'schema': 1, 'tool': 'pso_mods',
                'input': {'op': 'equipment_cycle'}, 'replay_input': {'op': 'equipment_cycle', 'gear': gear},
                'result': {'verified': True}, 'replayable': True,
                'evidence': 'resolved native randomizer cycle; equipped items were read back'},
                token='pso-cycle:'+sid+':'+str(cycle)+':'+uuid.uuid4().hex)
    except Exception as error:
        if sid in _recorders:
            _recorders[sid].error = str(error)[:240]


def stop(sid):
    recorder = _recorders.get(sid)
    if recorder:
        recorder.closed = True
        recorder.wakeup.set()


def recover_pending(ctx):
    """Resume previously captured immutable events after a worker restart."""
    if not getattr(ctx,'server',None):return
    root=Path(ctx.config.runtime)/'gameplay-actions'
    for manifest in list(root.glob('*/manifest.json'))[:200]:
        sid=manifest.parent.name
        if sid in _recorders or not list(manifest.parent.glob('*-event.json')):continue
        try:
            saved=json.loads(manifest.read_text())
            pid=saved.get('pid')
            if pid:
                try:
                    process=__import__('psutil').Process(pid)
                    if abs(process.create_time()-saved.get('process_created',0))<.1:continue
                except __import__('psutil').Error:pass
            with _guard:
                if sid not in _recorders:
                    recorder=Recorder(sid,None,saved['game'],ctx)
                    recorder.closed=True
                    _recorders[sid]=recorder
                    recorder.wakeup.set()
        except (OSError,ValueError,KeyError):
            continue # no state/input bytes are discarded if a manifest needs repair
