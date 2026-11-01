"""Bounded, audited PSO commands over the session channel, independent of the build queue."""
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict

from .registry import Unsupported

OPS = frozenset(('capabilities', 'rehook', 'status', 'list', 'floor_spawn', 'floor_rares', 'floor_clear',
                 'floor_list', 'give', 'equip_any', 'always_hit', 'multi_equip', 'stat',
                 'survival','revive','mag','mag_set','mag_feed','randomized','modes','legendary',
                 'enemy_drops','walk_through','bosses','boss_warp','adventure_status','equip','autoplay_speed'))
READS = frozenset(('capabilities', 'status', 'list', 'floor_list','mag','modes','bosses','adventure_status'))
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
    for name in ('pso_live.py', 'pso_rehook.py', 'pso_accuracy.py', 'pso_gc_live.py', 'pso_gc_extras.py','pso_gc_adventure.py','pso_modes.py', 'psoitems.py','pso_loadouts.py','tools.py', 'pso_mods_tool.py', 'pso_controls.py'):
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
            try:
                # The legacy replay schema drops player_index and multiplier.
                # Keep these actions in command receipts/audit, never replay P2
                # gear against P1 or an unmeasured speed request as a native rate.
                if inp.player_index==0 and inp.op!='autoplay_speed':
                    from . import gameplay_actions
                    gameplay_actions.record(sid,body['input'],result,ctx,body['command_id'])
            except Exception:pass  # Applied mutations must never become retries because recording failed.
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
    from .psoitems import CATALOG_SCHEMA
    if not isinstance(rows, list) or not rows or any(i.get('schema') != CATALOG_SCHEMA for i in rows):
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
    m = GC(ad,player_index=inp.player_index,pin_player=True)
    m.check()
    if inp.op in ('enemy_drops','walk_through','bosses','boss_warp','adventure_status'):
        from .pso_gc_adventure import Adventure,validate_pool
        m=Adventure(ad);m.check()
        if inp.op=='bosses': return m.destinations()
        if inp.op=='adventure_status': return {'enemy_drops':m.loot_status(),'walk_through':m.walk_state(),'travel':m.travel_status(),'verified':True}
        if inp.op=='enemy_drops':
            rows=catalog(ctx,'gc') if inp.on else []
            codes,grinds=validate_pool(rows,inp.codes,inp.max_grind) if inp.on else ([],{})
            deadline(ctx);result=m.enemy_drops(inp.on,codes,grinds)
        else:
            deadline(ctx)
            result=m.walk_through(inp.on) if inp.op=='walk_through' else m.teleport_boss(inp.target)
        if inp.op!='boss_warp': ad._pso_preferences_dirty=True
        return result
    if inp.op in ('survival','revive','mag','mag_set','mag_feed','randomized','modes','legendary'):
        from .pso_gc_extras import Extras,legendary
        from . import pso_modes
        from .pso_gc_live import SURVIVAL,CAVE,VT_UPDATE
        m=Extras(ad,player_index=inp.player_index,pin_player=True);m.check();deadline(ctx)
        if inp.op in ('survival','legendary'):
            result=m.survival(inp.on) if inp.op=='survival' else legendary(ad,inp.on)
            ad._pso_preferences_dirty=True
            return result
        if inp.op=='revive':return m.revive()
        if inp.op=='mag':return m.mag()
        if inp.op in ('mag_set','mag_feed'):
            if inp.item_id is None:raise ValueError('Refresh your equipped MAG first')
            return m.mag_set(inp.item_id,inp.properties) if inp.op=='mag_set' else m.mag_feed(inp.item_id,inp.code)
        if inp.op=='modes':
            from .pso_gc_adventure import Adventure
            from .pso_controls import autoplay_speed_status
            return {'permanent_scape':not inp.player_index and m.u32(VT_UPDATE)==CAVE and m.u32(SURVIVAL)==1,'randomized':pso_modes.status(inp.session_id,inp.player_index),
                    'travel':Adventure(ad).travel_status(),
                    'autoplay_speed':autoplay_speed_status(ad, bool(getattr(ad,'_pso_coop_new_card',False) and
                        callable(getattr(ad,'set_autoplay_speed',None))))}
        rows=catalog(ctx,'gc') if inp.on else []
        deadline(ctx)
        return pso_modes.configure(inp.session_id,ad,ctx,inp.on,inp.interval,inp.categories,inp.character_class,rows,player_index=inp.player_index)
    if inp.op in ('floor_spawn', 'floor_rares', 'give', 'list','equip'):
        rows = catalog(ctx, 'gc')
        by_code = {i['code']: i for i in rows}
    deadline(ctx)
    if inp.op == 'status':
        return {'stats': m.shown_stats(), 'equip_any': m.read(EQUIP_PATCH, 4).hex() == '38000005'}
    if inp.op == 'list':
        return {'inventory': [r | {'name': by_code.get(r['code'][:4]+'00' if r['code'].startswith('02') else r['code'], {}).get('name', r['code'])} for r in m.inventory()]}
    if inp.op == 'equip':
        from .pso_gc_extras import Extras
        gear=Extras(ad,player_index=inp.player_index,pin_player=True);gear.check()
        item_id=inp.item_id
        if item_id is None:
            code=inp.code.strip().lower()
            if code not in by_code or not code.startswith(('00','02','0101','0102')):
                raise ValueError('Select one equippable item from this disc catalog')
            made=gear.give(code)
            if not made.get('verified') or len(made.get('ids',[]))!=1:
                raise RuntimeError('The selected equipment was not acknowledged; refresh inventory before retrying')
            item_id=made['ids'][0]
        verified=gear.equip_id(item_id)
        return {'verified':verified,'item_id':item_id,'player_index':inp.player_index,
                'message':'Equipment applied to player '+str(inp.player_index+1) if verified else 'The game refused this equipment; the item was retained'}
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
        result=m.give(code, max(1, min(20, inp.count)))
        if inp.equip and result.get('verified') and result.get('ids'):
            from .pso_gc_extras import Extras
            gear=Extras(ad,player_index=inp.player_index,pin_player=True)
            gear._player_binding=m._player_binding
            result['equipped']=gear.equip_id(result['ids'][0])
            result['verified']=bool(result['equipped'])
        return result
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
