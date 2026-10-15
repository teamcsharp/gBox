"""Bounded, audited PSO commands over the session channel, independent of the build queue."""
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict

from .registry import Unsupported

OPS = frozenset(('capabilities', 'status', 'list', 'floor_spawn', 'floor_rares', 'floor_clear',
                 'floor_list', 'give', 'equip_any', 'multi_equip', 'stat',
                 'survival','revive','mag','mag_set','mag_feed','randomized','modes','legendary'))
READS = frozenset(('capabilities', 'status', 'list', 'floor_list','mag','modes'))
_receipts = {}
_guard = threading.Lock()


def authorize(store, config, sid, body):
    from pathlib import Path
    from .pso_controls import is_pso
    inp = validate(sid, body)
    session = store.get('session', sid)
    if not session or session.get('state') != 'running':
        raise ValueError('This PSO session has ended')
    game = store.catalog_get(session.get('game_id')) or session
    if not is_pso(game):
        raise ValueError('Choose a running PSO session')
    worker = store.get('worker', session.get('worker_id') or sid.split('-')[0]) or {}
    if time.time() - worker.get('last_seen', 0) > 60:
        raise ValueError('The emulator worker is offline')
    root = Path(__file__).parent
    for name in ('pso_live.py', 'pso_gc_live.py', 'pso_gc_extras.py','pso_modes.py', 'tools.py', 'pso_mods_tool.py', 'pso_controls.py'):
        expected = hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if worker.get('build_sources', {}).get('gbox/'+name) != expected:
            raise ValueError('This worker needs a safe refresh to load the verified PSO live controls')
    if inp.op not in READS and 'memory_write' not in config.granted_permissions:
        raise PermissionError('memory_write permission is required')
    return inp


def validate(sid, body):
    from .pso_mods_tool import ModsIn
    if not isinstance(body, dict) or set(body) != {'command_id', 'expires', 'input'}:
        raise ValueError('A PSO command needs command_id, expires and input')
    if not isinstance(body['command_id'], str):
        raise ValueError('command_id must be a UUID string')
    uuid.UUID(body['command_id'])
    expiry = body['expires']
    if type(expiry) not in (int, float) or not time.time() < expiry <= time.time() + 15:
        raise ValueError('PSO command expired; no action was executed')
    fields = body['input']
    if not isinstance(fields, dict) or set(fields) - set(ModsIn.model_fields):
        raise ValueError('Unknown PSO command fields')
    inp = ModsIn.model_validate(fields | {'session_id': sid})
    if fields.get('session_id', sid) != sid or inp.op not in OPS:
        raise ValueError('PSO command is not allowed for this session')
    return inp


def execute(sid, body, ctx):
    from .models import Permission
    from .pso_controls import is_pso, session_lock
    from .pso_mods_tool import pso_mods
    from .tools import SESSIONS
    inp = validate(sid, body)
    if ctx is None:
        raise Unsupported('Refresh this worker safely to enable PSO live commands')
    if inp.op not in READS and Permission.MEMORY_WRITE not in ctx.config.granted_permissions:
        raise PermissionError('memory_write permission is required')
    if sid not in SESSIONS or not is_pso(SESSIONS[sid][1]):
        raise Unsupported('This is not a running PSO session')
    lock = session_lock(sid)
    if not lock.acquire(blocking=False):
        raise RuntimeError('Another PSO command is applying; no new action was queued')
    try:
        signature = hashlib.sha256(json.dumps(body['input'], sort_keys=True).encode()).hexdigest()
        with _guard:
            # Session-scoped receipts are bounded and discarded for ended sessions.
            for ended in set(_receipts) - set(SESSIONS):
                _receipts.pop(ended, None)
            receipts = _receipts.setdefault(sid, OrderedDict())
            previous = receipts.get(body['command_id'])
            if previous:
                if previous['signature'] != signature:
                    raise ValueError('Command ID was already used with different parameters')
                if 'error' in previous:
                    raise RuntimeError(previous['error'])
                return previous['result']
            receipt = {'signature': signature}
            receipts[body['command_id']] = receipt
            while len(receipts) > 256:
                receipts.popitem(last=False)
        # Native commands recheck this after catalog access and before any mutation.
        from .registry import Ctx
        command_ctx = Ctx(ctx.config, 'pso-live-' + body['command_id'], ctx.worker)
        command_ctx.server, command_ctx.headers = ctx.server, ctx.headers
        command_ctx.pso_expires = body['expires']
        started = time.monotonic()
        try:
            result = pso_mods(inp, command_ctx)['result']
            result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
            result['command_id'] = body['command_id']
            receipt['result'] = result
            return result
        except Exception as error:
            receipt['error'] = str(error)
            raise
    finally:
        lock.release()


def deadline(ctx):
    if time.time() >= getattr(ctx, 'pso_expires', float('inf')):
        raise TimeoutError('PSO command expired before mutation; no new action was executed')


_catalogs = {}
_catalog_lock = threading.Lock()


def catalog(ctx, version):
    """Catalog metadata is already prepared by panel browsing; reuse it on the worker for subsequent clicks."""
    key = (ctx.server, version)
    with _catalog_lock:
        cached = _catalogs.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    import httpx
    response = httpx.get(f'{ctx.server}/api/pso/items', params={'version': version}, headers=ctx.headers, timeout=3)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows or any(i.get('schema') != 2 for i in rows):
        raise Unsupported('Prepare the updated owned-disc item database first')
    with _catalog_lock:
        if len(_catalogs) >= 8:
            _catalogs.clear()
        _catalogs[key] = (time.monotonic(), rows)
    return rows


def gamecube(inp, ctx, ad):
    import random
    from .pso_gc_live import GC, EQUIP_PATCH
    from .psoitems import CLASSES, rare_pool
    m = GC(ad)
    m.check()
    if inp.op in ('survival','revive','mag','mag_set','mag_feed','randomized','modes','legendary'):
        from .pso_gc_extras import Extras,legendary
        from . import pso_modes
        from .pso_gc_live import SURVIVAL,CAVE,VT_UPDATE
        m=Extras(ad);m.check();deadline(ctx)
        if inp.op in ('survival','legendary'):
            result=m.survival(inp.on) if inp.op=='survival' else legendary(ad,inp.on)
            ad._pso_preferences_dirty=True
            return result
        if inp.op=='revive':return m.revive()
        if inp.op=='mag':return m.mag()
        if inp.op in ('mag_set','mag_feed'):
            if inp.item_id is None:raise ValueError('Refresh your equipped MAG first')
            return m.mag_set(inp.item_id,inp.properties) if inp.op=='mag_set' else m.mag_feed(inp.item_id,inp.code)
        if inp.op=='modes':return {'permanent_scape':m.u32(VT_UPDATE)==CAVE and m.u32(SURVIVAL)==1,'randomized':pso_modes.status(inp.session_id)}
        rows=catalog(ctx,'gc') if inp.on else []
        deadline(ctx)
        return pso_modes.configure(inp.session_id,ad,ctx,inp.on,inp.interval,inp.categories,inp.character_class,rows)
    if inp.op in ('floor_spawn', 'floor_rares', 'give', 'list'):
        rows = catalog(ctx, 'gc')
        by_code = {i['code']: i for i in rows}
    deadline(ctx)
    if inp.op == 'status':
        return {'stats': m.shown_stats(), 'equip_any': m.read(EQUIP_PATCH, 4).hex() == '38000005'}
    if inp.op == 'list':
        return {'inventory': [r | {'name': by_code.get(r['code'][:4]+'00' if r['code'].startswith('02') else r['code'], {}).get('name', r['code'])} for r in m.inventory()]}
    if inp.op == 'equip_any':
        result=m.equip_any(inp.on);ad._pso_preferences_dirty=True
        return result
    if inp.op == 'multi_equip':
        return m.multi_equip(inp.target, inp.on)
    if inp.op == 'stat':
        return m.set_stat(inp.name, inp.value)
    if inp.op == 'floor_clear':
        return m.floor_clear()
    if inp.op == 'floor_list':
        return {'floor_items': [{'id': hex(i), 'code': c} for i, c in m.floor_items()]}
    if inp.op == 'give':
        code = inp.code.strip().lower()
        if code not in by_code:
            raise ValueError('Choose an item code from this GameCube disc database')
        return m.give(code, max(1, min(20, inp.count)))
    if inp.op in ('floor_spawn', 'floor_rares'):
        count = max(1, min(20, inp.count))
        if inp.op == 'floor_rares':
            if inp.character_class not in CLASSES:
                raise ValueError('Choose your GameCube character class')
            pool = rare_pool(rows, inp.character_class, inp.highest)
            if not pool:
                raise ValueError('No class-compatible rares found in this disc database')
            codes = [r['code'] for r in random.choices(pool, k=count)]
        else:
            codes = inp.codes[:20] if inp.codes else [inp.code.strip().lower()] * count
        if not codes or any(c not in by_code for c in codes):
            raise ValueError('Choose item codes from this GameCube disc database')
        return m.floor_spawn(codes, inp.radius, {c: by_code[c].get('max_grind', 0) for c in codes} if inp.max_grind else {})
    raise Unsupported(f'GameCube action {inp.op} has not been implemented and verified')
