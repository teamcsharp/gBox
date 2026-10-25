"""Mid-round bow supply through RE5's native pickup and ordinary equip.

Only an ownerless ammo pickup's serialized source is changed. The game's
1AEE90 -> 9D417C/9D693C -> 9D6520 -> 151540 path constructs the item and
uWp0f; an existing carried item, weapon pointer, model or owner is never edited.
"""
import math
import struct
import time
import uuid

from . import re5_eggs as E

ITEM, VTABLE = 0x10F, 0x016289F8
DTI, NAME = 0x018704A4, 0x01423AD0
REQUEST_S = 120.


def adapter_identity(ad, *, resolve_guest=False):
    proc = getattr(ad, 'proc', None)
    pid = getattr(proc, 'pid', None)
    if type(pid) is not int or pid <= 0:
        return None
    try:
        if callable(getattr(proc, 'poll', None)) and proc.poll() is not None:
            return None
        # Linux may resolve a descendant process independently of launch proc.
        # A validated read populates _mem; refresh it again at mutation fences.
        if hasattr(ad, '_mem'):
            guest = ad._guest() if resolve_guest and callable(getattr(ad, '_guest', None)) else ad._mem
            if not isinstance(guest, tuple) or len(guest) != 2 \
                    or any(type(value) is not int or value <= 0 for value in guest):
                return None
            mapping = ('linux', *guest)
        elif hasattr(ad, 'base'):
            base = ad._base() if resolve_guest and callable(getattr(ad, '_base', None)) else ad.base
            if type(base) is not int or base <= 0:
                return None
            mapping = ('windows', base, getattr(ad, '_handle', None))
        else:
            mapping = ('adapter',)
    except (OSError, RuntimeError, ValueError):
        return None
    return (id(ad), id(proc), pid, getattr(ad, 'generation', 0), mapping)


def current_request(state, cfg, ad, *, fresh=True, resolve_guest=False):
    process = adapter_identity(ad, resolve_guest=resolve_guest)
    if state.get('live_weapon') is not cfg or not cfg.get('active') \
            or process is None or process != cfg.get('process_identity') \
            or state.get('preferred_weapon') != cfg.get('installed_preference', cfg.get('initial_preference')):
        return False
    ctl = state.get('controller') or {}
    return ctl.get('owner') == cfg.get('controller_owner') and ctl.get('player') == cfg.get('player') \
        and (not fresh or controller_ready(state)) \
        and (cfg.get('phase') == 'equipped' or time.monotonic() < cfg.get('expires', 0.))


def controller_ready(state, now=None):
    from . import re5_controls as C
    from . import re5_ps3 as R
    ctl = state.get('controller') or {}
    now = time.monotonic() if now is None else now
    return bool(ctl.get('active') and R.ptr_ok(ctl.get('player') or 0)
                and 0 <= now - ctl.get('seen', -1e9) <= C.FRESH_S)


def status(state):
    cfg = state.get('live_weapon')
    if not cfg:
        return None
    keys = ('id', 'item', 'weapon', 'phase', 'reason', 'active', 'player',
            'native_created', 'equipped', 'restored', 'restoration_pending')
    out = {key: cfg[key] for key in keys if key in cfg}
    age = time.monotonic() - cfg.get('verified_at', -1e9)
    ref = state.get('_weapon_adapter_ref')
    ad = ref() if callable(ref) else None
    out['verified'] = cfg.get('phase') == 'equipped' and bool(cfg.get('equipped')) \
        and 0 <= age <= 5. and current_request(state, cfg, ad)
    if cfg.get('phase') == 'equipped' and not out['verified']:
        out['reason'] = 'Waiting for a fresh native equipped-bow observation.'
    out['completed'] = out['verified']
    return out


def validate(g):
    """Exact-build native constructor, bow registry and class identity."""
    if any(g.rd(a, len(raw)) != raw for a, raw in E.NATIVE_SIGNATURES.items()):
        raise ValueError('native item construction signature differs')
    expected = {0x01714EE0: 0x016A4AB0, 0x0169CB3C: 0x009D67AC,
                0x009D67B8: 0xFFFFFFB4, 0x009D6854: 0xFFFFFFB4,
                DTI + 4: NAME, DTI + 0x20: 0x07010F00,
                VTABLE + 0x14: 0x016EFCC8, 0x016EFCC8: 0x010F1FD4,
                0x016EFCCC: 0x0171C590}
    if any(g.u32(address) != value for address, value in expected.items()) \
            or g.rd(NAME, 6) != b'uWp0f\0':
        raise ValueError('native longbow factory or class identity differs')


def rows(memory, donor=None):
    return E.world_items(memory, donor, item_id=ITEM, item_vtable=VTABLE)


def _same_ownerless(memory, row):
    return E._u(memory, row['ptr']) == row['vtable'] \
        and E._u(memory, row['ptr'] + 0x1110) == row['handle'] \
        and E._u(memory, row['ptr'] + 0x111C) == 0 \
        and E._u(memory, row['ptr'] + 0x1BC0) == E.SOURCE_VT


def native_item(memory, player, inventory, *, held=False):
    """Require a real live cItem and its correct game-created weapon owner.

    The parser record begins four bytes before cItem. The native cItem weapon
    member is +0x2C, hence record+0x30 even though record stride is also 0x30.
    """
    from . import re5_ps3 as R
    if not R.ptr_ok(player):
        return None
    for item in inventory or ():
        slot = item.get('slot')
        if item.get('id') != ITEM or type(slot) is not int or not 0 <= slot < R.INV_ALL \
                or item.get('rounds', 0) <= 0 or held and not item.get('hand'):
            continue
        try:
            address = player + R.P_INV + slot * R.INV_SLOT
            raw = memory.rd(address, 0x34)
            if not raw[0x2D] or struct.unpack_from('>I', raw, 8)[0] != ITEM \
                    or struct.unpack_from('>I', raw, 12)[0] <= 0 \
                    or held and struct.unpack_from('>I', raw, 0x20)[0] != 1:
                continue
            weapon = struct.unpack_from('>I', raw, 0x30)[0]
            if not R.ptr_ok(weapon) or E._u(memory, weapon) != VTABLE \
                    or E._u(memory, weapon + 0x111C) != player:
                continue
            root = E._u(memory, R.S_PLAYER)
            if R.ptr_ok(root) and E._u(memory, root + 0x28) == player \
                    and memory.rd(address, 0x34) == raw \
                    and E._u(memory, weapon) == VTABLE and E._u(memory, weapon + 0x111C) == player:
                return item
        except (OSError, ValueError, struct.error, IndexError, TypeError):
            pass
    return None


def inventory_item(memory, player, inventory):
    """A game-created cItem may be equipped before the weapon actor is attached."""
    from . import re5_ps3 as R
    if not R.ptr_ok(player):
        return None
    for item in inventory or ():
        slot = item.get('slot')
        if item.get('id') != ITEM or type(slot) is not int or not 0 <= slot < R.INV_ALL:
            continue
        try:
            address = player + R.P_INV + slot * R.INV_SLOT
            raw = memory.rd(address, 0x30)
            root = E._u(memory, R.S_PLAYER)
            if raw[0x2D] and struct.unpack_from('>I', raw, 8)[0] == ITEM \
                    and struct.unpack_from('>I', raw, 12)[0] > 0 and R.ptr_ok(root) \
                    and E._u(memory, root + 0x28) == player and memory.rd(address, 0x30) == raw:
                return item
        except (OSError, ValueError, struct.error, IndexError, TypeError):
            pass
    return None


def restore(g, cfg):
    """Restore only our still-ownerless source, never a reused/consumed actor."""
    donor = cfg.get('donor')
    if not donor:
        cfg['restoration_pending'] = False
        return True
    cfg['restoration_pending'] = True
    if adapter_identity(g.ad) != cfg.get('process_identity'):
        cfg['reason'] = 'Emulator process or generation changed; old source restoration is withheld.'
        return False
    try:
        from . import re5_ps3 as R
        validate(g)
        actor = donor['actor']
        identity = (E._u(g, actor), E._u(g, actor + 0x1110), E._u(g, actor + 0x111C))
        if identity != (E._u(g, actor), E._u(g, actor + 0x1110), E._u(g, actor + 0x111C)):
            cfg['reason'] = 'Pickup identity is changing; restoration remains pending.'
            return False
        if adapter_identity(g.ad) != cfg.get('process_identity'):
            cfg['reason'] = 'Resolved guest memory changed; old source restoration is withheld.'
            return False
        if identity[:2] != (donor['vtable'], donor['handle']) or R.ptr_ok(identity[2]):
            cfg.pop('donor', None)  # positively observed reuse or native ownership transfer
            cfg['restoration_pending'] = False
            return True
        if identity[2] != 0:
            cfg['reason'] = 'Pickup owner is invalid; restoration remains pending.'
            return False
        address = actor + 0x1C36
        before, after = donor['before'], struct.pack('>HI', ITEM, 1)
        current = g.rd(address, 6)
        if adapter_identity(g.ad) != cfg.get('process_identity'):
            cfg['reason'] = 'Resolved guest memory changed; old source restoration is withheld.'
            return False
        if current == before:
            cfg.pop('donor', None)
            cfg['restoration_pending'] = False
            return True
        row = next((v for v in rows(g, donor) if v['ptr'] == actor
                    and v['handle'] == donor['handle'] and v['vtable'] == donor['vtable']), None)
        if row is None or current != after or not _same_ownerless(g, row):
            cfg['reason'] = 'Pickup source or list is unverified; restoration remains pending.'
            return False
        if not _same_ownerless(g, row) or g.rd(address, 6) != after \
                or adapter_identity(g.ad, resolve_guest=True) != cfg.get('process_identity') \
                or not g.wr(address, before):
            return False
    except (OSError, ValueError, struct.error, IndexError, AttributeError):
        cfg['reason'] = 'Pickup read failed; restoration remains pending.'
        return False
    cfg.pop('donor', None)
    cfg['restoration_pending'] = False
    return True


def configure(g, weapon=None, on=True):
    if on and (type(weapon) is not int or weapon not in (0x0F, ITEM)):
        return {'queued': False, 'verified': False, 'live_weapon': {
            'phase': 'unsupported', 'reason': 'Live native creation currently supports the longbow only.',
            'active': False, 'equipped': False, 'completed': False}}
    old = g.orig.get('live_weapon')
    if old and on and adapter_identity(g.ad) is not None \
            and adapter_identity(g.ad) != old.get('process_identity'):
        old.update(active=False, phase='rejected', equipped=False,
                   reason='Old process request retired; no old source rollback was attempted.')
        g.orig['retired_live_weapon'] = old
        old = None
    if old:
        old['active'] = False
        if old.get('installed_preference') == g.orig.get('preferred_weapon') and 'installed_preference' in old:
            if old.get('previous_preference'):
                g.orig['preferred_weapon'] = old['previous_preference']
            else:
                g.orig.pop('preferred_weapon', None)
        restored = restore(g, old)
        old.update(phase='cancelled', equipped=False, restored=restored, restoration_pending=not restored)
        if restored:
            old['reason'] = 'Live request cancelled; any already-created native inventory is retained.'
        if not restored:
            return {'queued': False, 'verified': False, 'live_weapon': status(g.orig)}
    if not on:
        return {'queued': False, 'verified': bool(not old or old.get('restored')),
                'live_weapon': status(g.orig), 'cancelled': True}
    process_before = adapter_identity(g.ad, resolve_guest=True)
    validate(g)
    process = adapter_identity(g.ad, resolve_guest=True)
    if not controller_ready(g.orig) or process is None or process != process_before:
        return {'queued': False, 'verified': False, 'reason': 'A fresh active solo RE5 bot is required.'}
    player = (g.orig.get('controller') or {}).get('player')
    cfg = {'id': uuid.uuid4().hex, 'item': 15, 'weapon': 'longbow', 'phase': 'pending',
           'active': True, 'player': player, 'native_created': False, 'equipped': False,
           'process_identity': process, 'controller_owner': g.orig['controller']['owner'],
           # Retain the process object so its Python identity cannot be recycled.
           '_process': g.ad.proc,
           'initial_preference': g.orig.get('preferred_weapon'),
           'expires': time.monotonic() + REQUEST_S,
           'reason': 'Waiting for an existing native bow or a safe spare-ammo pickup; current round continues.'}
    g.orig['live_weapon'] = cfg
    return {'queued': True, 'verified': False, 'live_weapon': status(g.orig)}


def prepare(g, snap):
    """Background preparation; no pad input or writes to carried inventory."""
    from . import re5_ps3 as R
    cfg = g.orig.get('live_weapon') or {}
    p = snap.get('player') or {}
    if not cfg.get('active'):
        return None
    if not current_request(g.orig, cfg, g.ad):
        cfg.update(active=False, equipped=False, phase='rejected', reason='Request owner, process or deadline changed.')
        cfg['restored'] = restore(g, cfg)
        cfg['restoration_pending'] = not cfg['restored']
        return None
    if p.get('ptr') != cfg.get('player'):
        cfg.update(active=False, equipped=False, phase='rejected', reason='The player or round changed.')
        cfg['restored'] = restore(g, cfg)
        return None
    validate(g)
    if inventory_item(g, p['ptr'], snap.get('inventory')):
        made = native_item(g, p['ptr'], snap.get('inventory')) is not None
        cfg.update(phase='native_created' if made else 'inventory_present', native_created=made,
                   reason='Bow inventory exists; ordinary equip and native weapon ownership verification pending.')
        return None
    mesh = snap.get('nav')
    if (p.get('hp') or 0) <= 1 or mesh is None or snap.get('prompt') or snap.get('recovery_active'):
        return None
    occupied = {w.get('grid') for w in snap.get('inventory') or () if w.get('id') not in (0, 0x100)
                and w.get('grid') in range(9)}
    if len(occupied) >= 9:
        cfg['reason'] = 'Waiting for a free native inventory grid slot; existing items are retained.'
        return None
    world = rows(g, cfg.get('donor'))
    ready = next((row for row in world if row['id'] == ITEM), None)
    if ready:
        cfg.update(phase='donor', reason='Native bow pickup available; waiting for exact pickup and inventory acknowledgement.')
        return ready
    if cfg.get('donor'):
        cfg['reason'] = 'Prepared pickup is no longer observable; waiting for native inventory acknowledgement.'
        return None
    hazards = [(v['pos'], 600.) for v in (snap.get('ground_mines') or {}).values()]
    choices = []
    for row in world:
        if row['original_id'] not in E.AMMO_VTABLES.values() or math.dist(p['pos'], row['pos']) > 1500.:
            continue
        route = mesh.route_avoiding_hazards(p['pos'], row['pos'], hazards)
        if not route or any((e.get('hp') or 0) > 0 and any(math.dist(e['pos'], point) < 350.
                           for point in [p['pos']] + route) for e in snap.get('enemies') or ()):
            continue
        choices.append((sum(math.dist(a, b) for a, b in zip([p['pos']] + route, route)), row))
    if not choices:
        cfg['reason'] = 'Waiting for a safe ownerless spare-ammo pickup; no carried item is relabelled.'
        return None
    row = min(choices, key=lambda pair: pair[0])[1]
    root = E._u(g, R.S_PLAYER)
    if not R.ptr_ok(root) or E._u(g, root + 0x28) != p['ptr']:
        return None
    fresh = next((v for v in rows(g) if all(v.get(k) == row.get(k)
                 for k in ('ptr', 'handle', 'id', 'vtable', 'count', 'volume'))), None)
    if fresh is None:
        return None
    address = row['ptr'] + 0x1C36
    before = g.rd(address, 6)
    if before != struct.pack('>HI', row['id'], row['count']) or not _same_ownerless(g, row) \
            or E._u(g, R.S_PLAYER) != root or E._u(g, root + 0x28) != p['ptr']:
        return None
    donor = {'actor': row['ptr'], 'handle': row['handle'], 'vtable': row['vtable'],
             'original_id': row['id'], 'before': before}
    cfg['donor'] = donor
    # One six-byte source record write, followed by strict actor/readback validation.
    if not current_request(g.orig, cfg, g.ad, resolve_guest=True):
        cfg.pop('donor', None)
        return None
    if not g.wr(address, struct.pack('>HI', ITEM, 1)):
        cfg.update(active=False, phase='rejected', reason='Native pickup preparation was not confirmed.')
        cfg['restored'] = restore(g, cfg)
        return None
    ready = next((v for v in rows(g, donor) if v['ptr'] == row['ptr'] and v['handle'] == row['handle']
                  and v['id'] == ITEM), None)
    if ready is None:
        cfg.update(active=False, phase='rejected', reason='Pickup actor changed during preparation.')
        cfg['restored'] = restore(g, cfg)
        return None
    cfg.update(phase='donor', reason='Bow source prepared; waiting for native pickup and weapon construction.')
    return ready


def stop(state, ad, owner):
    """Retire only this input owner's request and schedule guarded source cleanup."""
    from ... import re5_mods_tool as M
    with M._HEALTH_LOCK:
        cfg = state.get('live_weapon') or {}
        if cfg.get('controller_owner') != owner:
            return
        cfg.update(active=False, phase='cancelled', equipped=False,
                   restoration_pending=bool(cfg.get('donor')),
                   reason='The input controller stopped; any unconsumed source cleanup is pending.')
        if 'installed_preference' in cfg and state.get('preferred_weapon') == cfg['installed_preference']:
            if cfg.get('previous_preference'):
                state['preferred_weapon'] = cfg['previous_preference']
            else:
                state.pop('preferred_weapon', None)
    if cfg.get('donor'):
        queue_supply(ad, force=True)


def queue_supply(ad, *, force=False):
    import threading
    from ... import re5_mods_tool as M
    with M._HEALTH_LOCK:
        cfg = M.ORIG.get(id(ad), {}).get('live_weapon') or {}
        now = time.monotonic()
        if adapter_identity(ad) is None or adapter_identity(ad) != cfg.get('process_identity'):
            return
        if cfg.get('worker') is not None and cfg['worker'].is_alive():
            if force:
                cfg['cleanup_requested'] = True
            return
        if not cfg.get('active') and not cfg.get('donor') or not force and now < cfg.get('supply_after', 0.):
            return
        cfg['supply_after'] = now + 3.
        request_id = cfg['id']
        def work():
            try:
                with M._HEALTH_LOCK:
                    g = M.RE5(ad)
                    if (g.orig.get('live_weapon') or {}).get('id') != request_id:
                        return
                    if not cfg.get('active'):
                        cfg['restored'] = restore(g, cfg)
                        cfg['restoration_pending'] = not cfg['restored']
                        return
                    from . import re5_ps3 as R, re5_mines
                    snap = R.snapshot(g)
                    snap['ground_mines'] = re5_mines.ground_mines(g)
                    prepare(g, snap)
            except Exception as error:
                with M._HEALTH_LOCK:
                    if cfg.get('active'):
                        cfg.update(active=False, phase='rejected', equipped=False,
                                   restoration_pending=bool(cfg.get('donor')),
                                   reason='Native bow preparation failed: ' + type(error).__name__)
            finally:
                with M._HEALTH_LOCK:
                    cfg['worker'] = None
                    cleanup = cfg.pop('cleanup_requested', False)
                if cleanup and not cfg.get('active') and cfg.get('donor'):
                    queue_supply(ad, force=True)
        cfg['worker'] = threading.Thread(target=work, daemon=True, name='re5-live-bow-supply')
        cfg['worker'].start()


def pickup_request(memory, request, row, donor=None):
    return E.pickup_request(memory, request, row, donor, item_id=ITEM, item_vtable=VTABLE)


def observe(memory, state, snap, where):
    """Only native ownership readback makes the request complete."""
    from ... import re5_mods_tool as M
    with M._HEALTH_LOCK:
        _observe(memory, state, snap, where)


def _observe(memory, state, snap, where):
    cfg = state.get('live_weapon') or {}
    if not cfg.get('active'):
        return
    if state.get('preferred_weapon') != cfg.get('installed_preference', cfg.get('initial_preference')):
        cfg.update(active=False, phase='cancelled', equipped=False,
                   restoration_pending=bool(cfg.get('donor')),
                   reason='A newer operator weapon preference superseded this live request.')
        return
    p = snap.get('player') or {}
    ad = getattr(memory, 'adapter', None) or getattr(memory, 'ad', None)
    if where != 'playing' or p.get('ptr') != cfg.get('player') or not current_request(state, cfg, ad):
        cfg.update(active=False, phase='rejected', equipped=False,
                   restoration_pending=bool(cfg.get('donor')),
                   reason='The round or player changed; this live request ended.')
        return
    held = native_item(memory, p['ptr'], snap.get('inventory'), held=True)
    if not current_request(state, cfg, ad):
        cfg.update(active=False, phase='rejected', equipped=False,
                   restoration_pending=bool(cfg.get('donor')),
                   reason='The request or resolved guest memory changed during observation.')
        return
    if held is not None:
        cfg.update(phase='equipped', equipped=True, native_created=True,
                   verified_at=time.monotonic(),
                   reason='Native longbow weapon, player owner and equipped inventory verified.')
        from . import re5_weapons as W
        if 'installed_preference' not in cfg:
            cfg['previous_preference'] = state.get('preferred_weapon')
            cfg['installed_preference'] = {'item': 15, 'weapon': 'longbow', 'target': W.inventory_key(held)}
            state['preferred_weapon'] = cfg['installed_preference']
    else:
        cfg['equipped'] = False
        if inventory_item(memory, p['ptr'], snap.get('inventory')) is not None:
            made = native_item(memory, p['ptr'], snap.get('inventory')) is not None
            cfg.update(phase='native_created' if made else 'inventory_present', native_created=made,
                       reason='Bow inventory exists; equipped native weapon class and owner not yet confirmed.')
