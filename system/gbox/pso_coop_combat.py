"""Bounded normal-attack envelopes from the owned 3OE2 PMT and native equipment.

The static PMT is targeting evidence, not a hit/line-of-sight guarantee. Dynamic
weapon virtual overrides and special attacks are not inferred from this table.
"""
import hashlib
import math
import struct
import time

from .pso_gc_live import GC, dispatcher_lock
from .pso_coop_native import EPISODE, FLOOR, TRAVELLING, DIFFICULTY
from .registry import Unsupported

PMT_SHA256 = '84d2f5291709f6f44dab59f50fdee0cb25a1ccc26e217e306b7155d03fbc987a'
# Owned PMT minimum positive horizontal range is 12; unarmed is 13. Stay inside
# that base envelope when the equipped weapon cannot be independently identified.
FALLBACK = dict(horizontal=10., vertical=10., horizontal_half_angle=8.,
                vertical_half_angle=20., verified=False, source='conservative_unknown_weapon')


def pmt_ranges(data):
    """Pinned RootV3V4T + WeaponRangeT schema; reject modified/unrecognized PMTs."""
    if hashlib.sha256(data).hexdigest() != PMT_SHA256:
        raise Unsupported('PSO attack ranges require the verified owned 3OE2 ItemPMT')
    root = struct.unpack_from('>I', data, len(data) - 16)[0]
    start, end = (struct.unpack_from('>I', data, root + n)[0] for n in (0x1c, 0x14))
    result = {}
    for index, at in enumerate(range(start, end, 0x14)):
        horizontal, vertical, angle, elevation, count = struct.unpack_from('>ffIII', data, at)
        if (not all(math.isfinite(v) and 0 < v <= 1000 for v in (horizontal, vertical)) or
                not 0 < angle <= 65536 or not 0 < elevation <= 65536 or not 1 <= count <= 100):
            continue
        result[index] = dict(horizontal=horizontal, vertical=vertical,
            horizontal_half_angle=angle * 360 / 65536, vertical_half_angle=elevation * 360 / 65536)
    return result


def load_ranges(ad):
    from .gcdisc import GCDisc
    from .ninja import prs_decompress
    path = getattr(ad, 'memory_card_rom', None)
    if not path:
        raise Unsupported('The current PSO disc path is unavailable')
    disc = GCDisc(path)
    try:
        if disc._r(0, 8) != b'GPOE8P\0\x02':
            raise Unsupported('PSO range disc is not Plus US revision 2')
        return pmt_ranges(prs_decompress(disc.read('ItemPMT.prs')))
    finally:
        disc.f.close()


class WeaponRanges:
    """No guessed active-item layout: reuse guarded inventory/object functions.

    The shared dispatcher lock covers the whole scratch-buffer transaction. A
    native-call failure latches this reader, so it never repeats an uncertain
    publication. Actor/area/equipment changes invalidate cached identities.
    """
    def __init__(self, ad, *, table=None, factory=GC, clock=time.monotonic, recovery=None):
        self.ad, self.factory, self.clock = ad, factory, clock
        self.recovery = recovery
        self.cache, self.attempted, self.failure, self.table = {}, {}, None, table
        if table is None:
            try:
                self.table = load_ranges(ad)
            except (OSError, ValueError, KeyError, Unsupported, struct.error) as exc:
                self.failure = str(exc)

    def for_player(self, state, slot):
        fallback = dict(FALLBACK, reason=self.failure or 'Native weapon is not uniquely verified')
        ad = self.ad
        if (self.failure or not self.table or ad is None or not state.get('verified') or
                state.get('phase') != 14 or state.get('travelling') or
                getattr(ad, '_pso_timing_paused', False) or getattr(ad, 'paused', False) or
                set(getattr(ad, '_pso_verified_player_slots', ())) != {0, 1}):
            return fallback
        lock = dispatcher_lock(ad)
        if not lock.acquire(blocking=False):
            return dict(fallback, reason='Native equipment dispatcher is busy')
        uncertain = False
        try:
            gc = self.factory(ad, player_index=slot - 1, pin_player=True)
            player = state['players'][slot]
            epoch = getattr(ad, '_pso_timing_epoch', 0)
            def context_matches():
                return (gc.u32(EPISODE) + 1 == state.get('episode') and gc.u32(FLOOR) == state.get('floor') and
                        gc.u32(DIFFICULTY) == state.get('difficulty') and not gc.u32(TRAVELLING) and
                        getattr(ad, '_pso_timing_epoch', 0) == epoch and not getattr(ad, '_pso_timing_paused', False))
            if not context_matches():
                self.cache.pop(slot, None)
                return fallback
            pointer = gc.check()
            if pointer != int(player['ptr'], 16):
                self.cache.pop(slot, None)
                return fallback
            active = gc.read(pointer + 0xD04, 13 * 4)
            identity = (pointer, state.get('episode'), state.get('floor'), state.get('difficulty'),
                        getattr(ad, '_pso_timing_epoch', 0), active)
            now = self.clock()
            cached = self.cache.get(slot)
            if cached and cached[0] == identity and 0 <= now - cached[1] <= 1.:
                return dict(cached[2])
            self.cache.pop(slot, None)
            attempted = self.attempted.get(slot)
            if attempted and attempted[0] == identity and 0 <= now - attempted[1] <= 1.:
                return fallback
            self.attempted[slot] = (identity, now)
            uncertain = True
            inventory = gc.inventory()
            uncertain = False
            rows = [r for r in inventory if r.get('equipped') and str(r.get('code', '')).startswith('00')]
            # Effects stacking can leave several equipped flags. Do not choose
            # one arbitrarily even though only one animation is drawn.
            if len(rows) != 1:
                return dict(fallback, reason='No weapon equipped' if not rows else 'Multiple equipped weapon effects are ambiguous')
            row = rows[0]
            uncertain = True
            obj = gc.item_object(row['id'])
            uncertain = False
            if (obj not in struct.unpack('>13I', active) or gc.check() != pointer or not context_matches() or
                    gc.read(pointer + 0xD04, 13 * 4) != active):
                return fallback
            base = self.table.get(bytes.fromhex(row['code'])[1])
            if base is None:
                return fallback
            envelope = dict(base, horizontal=base['horizontal'] * .85,
                vertical=base['vertical'] * .85,
                horizontal_half_angle=min(35., base['horizontal_half_angle'] * .8),
                vertical_half_angle=min(60., base['vertical_half_angle'] * .8),
                verified=True, source='owned_pmt_native_equipped_normal_attack',
                code=row['code'], item_id=row['id'], base=dict(base), player_ptr=player['ptr'],
                hit_verified=False, dynamic_override_verified=False)
            self.cache[slot] = (identity, now, envelope)
            if self.recovery is not None:
                self.recovery.remember(state, slot, row)
            return dict(envelope)
        except (OSError, RuntimeError, ValueError, KeyError, Unsupported, struct.error) as exc:
            self.cache.pop(slot, None)
            if uncertain:
                self.failure = 'Native weapon observation failed; no automatic retry: ' + str(exc)
                if self.recovery is not None:
                    self.recovery.block(self.failure)
            return dict(fallback, reason=str(exc))
        finally:
            lock.release()


class EquipmentRecovery:
    """One normal equip of the exact prior weapon after an observed death.

    Evidence is private to this bot run. No item selection, creation, stat patch,
    revive, hook implementation, background thread or retry of uncertain calls.
    The caller must observe every native state and admit tick only after its
    current menu guard permits native control; a tick that reads/equips returns
    True so the caller reobserves before using any old combat plan.
    """
    def __init__(self, ad, sid, driver, stopped, *, factory=None, clock=time.monotonic):
        self.ad, self.sid, self.driver, self.stopped = ad, sid, driver, stopped
        self.process = getattr(ad, 'proc', None)
        self.clock, self.factory = clock, factory
        self.known, self.pending, self.due = {}, {}, {}
        self.failure = None
        self.status = {'state': 'observing', 'players': {}}

    def authorized(self):
        from .tools import SESSIONS, AUTOPLAY
        from .models import Permission
        from . import pad_takeover
        ad = self.ad
        session, run = SESSIONS.get(self.sid), AUTOPLAY.get(self.sid) or {}
        auth = getattr(ad, '_pso_coop_new_card', {}) or {}
        return bool(not self.stopped() and self.process is not None and
            getattr(ad, 'proc', None) is self.process and self.process.poll() is None and
            session and session[0] is ad and run.get('driver') is self.driver and
            not getattr(self.driver, 'stopped', False) and not run.get('took_over') and
            not pad_takeover.active(self.sid) and auth.get('isolated') is True and
            auth.get('session_id') == self.sid and getattr(ad, 'coop_players', None) == 2 and
            set(getattr(ad, '_pso_verified_player_slots', ())) == {0, 1} and
            Permission.MEMORY_WRITE in getattr(getattr(ad, 'config', None), 'granted_permissions', ()) and
            not any(getattr(ad, flag, False) for flag in
                ('paused', 'paused_tids', '_pso_timing_paused', '_autoplay_speed_changing')))

    def _identity(self, state, slot):
        p = state.get('players', {}).get(slot) or {}
        if (state.get('verified') is not True or state.get('phase') != 14 or state.get('travelling') or
                set(state.get('players', {})) != {1, 2} or not isinstance(p.get('ptr'), str) or
                type(p.get('hp')) is not int or p['hp'] < 0):
            return None
        return (getattr(self.ad, '_pso_mapping_epoch', 0), p['ptr'], state.get('episode'),
                state.get('floor'), state.get('difficulty'))

    def clear(self, reason):
        self.known.clear(); self.pending.clear(); self.due.clear()
        self.status.update(state=reason)

    def block(self, reason):
        self.failure = str(reason)
        self.clear('blocked_uncertain_native_outcome')
        self.status['reason'] = self.failure

    def remember(self, state, slot, row):
        """Only WeaponRanges' completed unique active-object proof calls this."""
        if not self.authorized() or self.failure:
            return
        identity = self._identity(state, slot)
        if identity is None or state['players'][slot]['hp'] <= 0:
            return
        try:
            raw = bytes.fromhex(row['data'])
            valid = (len(raw) == 20 and raw[0] == 0 and row['equipped'] is True and
                     type(row['id']) is int and struct.unpack_from('>I', raw, 12)[0] == row['id'] and
                     raw[:3].hex() == row['code'])
        except (ValueError, TypeError, KeyError, struct.error):
            return
        if valid:
            self.known[slot] = (identity, {k: row[k] for k in ('id', 'code', 'data')})
            self.pending.pop(slot, None)
            self.status['players'][str(slot)] = dict(state='weapon_attested', item_id=row['id'], code=row['code'])

    def observe(self, state):
        if not self.authorized():
            self.clear('ownership_unavailable')
            return
        for slot in (1, 2):
            identity = self._identity(state, slot)
            known = self.known.get(slot)
            if not known or identity is None or identity != known[0]:
                self.known.pop(slot, None); self.pending.pop(slot, None)
                continue
            if state['players'][slot]['hp'] == 0:
                self.pending[slot] = known
                self.status['players'][str(slot)] = dict(state='waiting_for_native_revival', item_id=known[1]['id'])

    def tick(self, state, *, menu_allowed=False):
        self.observe(state)
        if self.failure or not menu_allowed or not self.pending:
            return False
        from .pso_controls import session_lock
        from .pso_gc_extras import Extras
        class Deferred(Exception):
            pass
        for slot, known in list(self.pending.items()):
            if state['players'][slot]['hp'] <= 0 or self.clock() < self.due.get(slot, 0):
                continue
            self.due[slot] = self.clock() + 2.
            session = session_lock(self.sid)
            if not session.acquire(blocking=False):
                self.status.update(state='session_command_busy'); return False
            lock = dispatcher_lock(self.ad)
            if not lock.acquire(blocking=False):
                session.release(); self.status.update(state='native_dispatcher_busy'); return False
            uncertain, worked = False, False
            try:
                native = (self.factory or Extras)(self.ad, player_index=slot-1, pin_player=True)
                expected = int(state['players'][slot]['ptr'], 16)
                epoch = getattr(self.ad, '_pso_timing_epoch', 0)
                def context():
                    if (not self.authorized() or self._identity(state, slot) != known[0] or
                            getattr(self.ad, '_pso_timing_epoch', 0) != epoch):
                        raise Deferred('Ownership or timing changed before native equipment work')
                    if (native.check() != expected or native.u32(EPISODE)+1 != state['episode'] or
                            native.u32(FLOOR) != state['floor'] or native.u32(DIFFICULTY) != state['difficulty'] or
                            native.u32(TRAVELLING) or native.u16(expected+0x32c) <= 0):
                        raise Deferred('Native player/area/life changed before equipment work')
                original = native.call
                def checked_call(*args, **kwargs):
                    nonlocal uncertain, worked
                    context()
                    uncertain = worked = True
                    result = original(*args, **kwargs)
                    uncertain = False
                    return result
                native.call = checked_call
                context()
                rows = native.inventory()
                context()
                equipped = [r for r in rows if r.get('equipped') and str(r.get('code', '')).startswith('00')]
                if equipped:
                    self.pending.pop(slot, None)
                    self.status['players'][str(slot)] = dict(state='existing_weapon_preserved')
                    return True
                matches = [r for r in rows if all(r.get(k) == v for k, v in known[1].items())]
                if len(matches) != 1:
                    self.pending.pop(slot, None); self.known.pop(slot, None)
                    self.status['players'][str(slot)] = dict(state='prior_item_missing_or_changed')
                    return True
                context()
                accepted = native.equip_id(known[1]['id'])
                context()
                after = native.inventory()
                context()
                active = [r for r in after if r.get('equipped') and str(r.get('code', '')).startswith('00')]
                verified = accepted is True and len(active) == 1 and all(active[0].get(k) == v for k,v in known[1].items())
                if verified:
                    obj = native.item_object(known[1]['id'])
                    context()
                    verified = obj in struct.unpack('>13I', native.read(expected+0xD04, 13*4))
                    context()
                self.pending.pop(slot, None)
                self.status['players'][str(slot)] = dict(state='restored' if verified else 'equip_not_verified',
                    item_id=known[1]['id'], code=known[1]['code'], verified=verified,
                    source='existing_native_equip_and_inventory_active_object_readback')
                if not verified:
                    self.known.pop(slot, None)
                return True
            except Deferred as exc:
                self.clear(str(exc))
                # A rejected fresh native context invalidates the caller's old
                # movement snapshot even when no native call was published.
                return True
            except (OSError, RuntimeError, ValueError, KeyError, Unsupported, struct.error) as exc:
                if uncertain:
                    self.failure = 'Native equipment outcome uncertain; no automatic retry: ' + str(exc)
                    self.status.update(state='blocked_uncertain_native_outcome', reason=self.failure)
                else:
                    self.status.update(state='equipment_recovery_refused', reason=str(exc))
                self.pending.pop(slot, None); self.known.pop(slot, None)
                # Guard/read failures also require a fresh native/menu snapshot.
                return True
            finally:
                lock.release(); session.release()
        return False


def geometry(player, target, envelope):
    dx, dz = target['x'] - player['x'], target['z'] - player['z']
    distance = math.hypot(dx, dz)
    height = abs(target.get('y', 0.) - player.get('y', 0.))
    desired = math.degrees(math.atan2(dx, dz))
    angle = (desired - player['heading_deg'] + 180) % 360 - 180
    elevation = math.degrees(math.atan2(height, max(distance, .001)))
    vertical_ok = height <= envelope['vertical'] and elevation <= envelope['vertical_half_angle']
    return distance, angle, vertical_ok


class Engagements:
    """Target HP feedback is shared combat evidence, never per-player hit credit."""
    def __init__(self):
        self.rows, self.recoveries, self.deferred = {}, 0, 0

    def observe(self, state, slot, target, envelope, now):
        player = state['players'][slot]
        key = (player['ptr'], state.get('episode'), state.get('floor'), player.get('room'),
               target['ptr'], target.get('class'), envelope.get('item_id'), envelope.get('code'))
        row = self.rows.get(slot)
        if not row or row['key'] != key or target['hp'] != row['hp']:
            row = dict(key=key, hp=target['hp'], at=now, attempts=0, recoveries=0, until=0., destination=None,
                       aim_angle=None, aim_at=now)
            self.rows[slot] = row
        return row

    def recovery(self, row, player, target, envelope, now):
        if now < row['until']:
            return 'reposition', row['destination']
        if row['attempts'] < 3 or now - row['at'] < 2.:
            return None, None
        if row['recoveries'] >= 3:
            self.deferred += 1
            return 'defer', None
        dx, dz = player['x'] - target['x'], player['z'] - target['z']
        distance = max(math.hypot(dx, dz), .001)
        ux, uz = dx / distance, dz / distance
        if distance <= .001:
            ux, uz = 1., 0.
        # First close the distance, then try either side of the obstructed ray.
        side = (0., 8., -8.)[row['recoveries']]
        stand_off = min(envelope['horizontal'] * .55, 20.)
        dest = (target['x'] + ux * stand_off - uz * side,
                target['z'] + uz * stand_off + ux * side)
        row.update(at=now, attempts=0, recoveries=row['recoveries'] + 1, until=now + 1., destination=dest)
        self.recoveries += 1
        return 'reposition', dest

    def attacked(self, slot):
        self.rows[slot]['attempts'] += 1
