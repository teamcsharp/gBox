"""RE6 travel drops, emergency rings and deadline-first native detonation."""
from __future__ import annotations

import math
from pathlib import Path
import threading
import time
import uuid

from .re6_bomb_deadlines import Deadlines, finite, record_placement
from .follow_report_delivery import _write

ROOT = Path(__file__).resolve().parents[2] / 'gbox-data' / 'mercs' / 'native-remote-receipts'
TRAVEL_CM, REQUEST_GAP_S = 609.6, 3.0
TRAVEL_ACTIONS = frozenset('cPlAction_pl_act_' + name for name in (
    'walk', 'run', 'dash', 'weapon_ready_move', 'weapon_fire'))


def position(value):
    return isinstance(value, (tuple, list)) and len(value) == 3 and all(finite(v) for v in value)


class Travel:
    """Credit observed locomotion, never stick input, wall pushing or warps."""
    def __init__(self):
        self.owner, self.previous = None, None
        self.distance, self.last_move, self.last_request = 0., -math.inf, -math.inf
        self.moving = False

    def observe(self, owner, snap, stats, now, enabled):
        p = snap.get('player') or {}
        if owner != self.owner:
            self.__init__()
            self.owner = owner
        valid = (enabled and bool(owner[0]) and all(type(v) is int for v in owner[1:])
                 and not stats.get('operator_control') and not stats.get('round_evidence_closed')
                 and stats.get('screen') in (None, 'playing') and (p.get('hp') or 0) > 0
                 and position(p.get('pos')) and p.get('state') in (0, 2)
                 and type(p.get('equipped')) is int and 0 <= p['equipped'] < 7
                 and p.get('action') in TRAVEL_ACTIONS)
        self.moving = False
        if valid:
            if self.previous is not None:
                then, old = self.previous
                dt = now - then
                distance = math.hypot(p['pos'][0] - old[0], p['pos'][2] - old[2])
                if 0 < dt <= 1. and distance <= 1200. * dt + 30.:
                    if distance >= 1.:
                        self.distance = min(TRAVEL_CM, self.distance + distance)
                        self.last_move = now
                    # The engine observes deadlines before and after its input
                    # decision using the same snapshot. Do not erase a real
                    # movement sample on that second observation.
                    self.moving = 0 <= now - self.last_move <= .25
                elif dt == 0 and distance == 0:
                    self.moving = 0 <= now - self.last_move <= .25
                else:
                    self.distance, self.last_move = 0., -math.inf
            self.previous = now, tuple(p['pos'])
        else:
            self.previous = None
        if not enabled or stats.get('operator_control'):
            self.distance = 0.
        stats.update(mine_travel_cm=round(self.distance, 1), mine_travel_interval_ft=20,
                     mine_travel_moving=self.moving)

    def due(self, now):
        return self.moving and self.distance >= TRAVEL_CM and now - self.last_request >= REQUEST_GAP_S

    def claimed(self, now):
        self.distance, self.last_request = 0., now


def single_drop_now(ad, owner, cancelled):
    """One body-position drop with an atomic all-bomb and held-gun preflight."""
    from .titles import re6_switch_native as native
    result = {'op': 'bomb_trail', 'state': 'unavailable', 'verified': False,
              'requested': 1, 'placed': 0, 'units': [], 'radius_cm': 0.}
    allocation_started = False
    try:
        with native._CREATE_LOCK:
            ctl = getattr(ad, '_re6_native_flash', None)
            if ctl is None:
                ctl = ad._re6_native_flash = native.Controller(ad)
        with ctl.lock:
            if not ctl.recover_completed_call() and ctl.failed:
                raise native.Unavailable('native controller awaits recovery after an uncertain operation')
            if cancelled() or ctl.ready() != tuple(owner[1:]):
                raise native.Unavailable('travel drop no longer belongs to a moving bot in this round')
            units = native.R.owned_throwables(ctl, ctl.base, owner[1])
            if not isinstance(units, list):
                raise native.Unavailable('live native bomb census is unavailable')
            if any(u.get('kind') == 'remote' for u in units):
                raise native.Unavailable('existing native remote bomb must resolve before a travel drop')
            before = ctl.current_weapon()
            if before is None:
                raise native.Unavailable('travel drop requires a gun already held')
            result['weapon_before'] = before
            if cancelled():
                raise native.Unavailable('travel ended before native allocation')
            allocation_started = True
            receipt = ctl.drop_bomb(expected_player=owner[1], expected_generation=owner[2], cancelled=cancelled)
            if not (receipt.get('verified') is True and receipt.get('armed') is True
                    and type(receipt.get('unit')) is int and type(receipt.get('generation')) is int
                    and finite(receipt.get('placed_at')) and position(receipt.get('pos'))):
                raise native.Uncertain('travel drop lacks native placed-and-armed evidence; not replayed')
            result.update(placed=1, units=[receipt], placed_at=receipt['placed_at'])
            after = ctl.current_weapon()
            result.update(weapon_after=after, weapon_unchanged=before == after)
            if before != after:
                raise native.Uncertain('gun changed during travel drop; placement retained for escape')
            result.update(state='confirmed', verified=True)
    except Exception as exc:
        result.update(state='uncertain' if allocation_started else 'unavailable', verified=False,
                      reason=f'{type(exc).__name__}: {exc}'[:250])
    return result


def emergency_ring_now(ad, owner, cancelled, count, radius):
    """Serialize the live all-bomb preflight with the existing ring operation."""
    from .titles import re6_switch_native as native
    try:
        with native._CREATE_LOCK:
            ctl = getattr(ad, '_re6_native_flash', None)
            if ctl is None:
                ctl = ad._re6_native_flash = native.Controller(ad)
        with ctl.lock:
            if cancelled() or ctl.ready() != tuple(owner[1:]):
                raise native.Unavailable('emergency ring belongs to an ended player life')
            units = native.R.owned_throwables(ctl, ctl.base, owner[1])
            if not isinstance(units, list) or any(u.get('kind') == 'remote' for u in units):
                raise native.Unavailable('existing native bomb must resolve before an emergency ring')
            return native.bomb_ring_now(ad, count=count, radius_cm=radius, expected_player=owner[1],
                                       expected_generation=owner[2], cancelled=cancelled)
    except Exception as exc:
        return {'op': 'bomb_ring', 'state': 'unavailable', 'verified': False, 'placed': 0,
                'reason': f'{type(exc).__name__}: {exc}'[:250]}


class RingFlight:
    """One allocation batch per player life; no replay after an uncertain call."""
    def __init__(self):
        self.thread = None
        self.owner = None
        self.cancel = threading.Event()
        self.result = None

    @property
    def busy(self):
        return self.thread is not None

    def submit(self, owner, operation, metadata=None):
        if self.busy:
            return False
        self.owner, self.result = owner, None
        self.cancel = threading.Event()
        cancel = self.cancel
        record = {'schema': 'gbox.mercs.native-remote/1', 'id': uuid.uuid4().hex,
                  'identity': list(owner), 'requested_at': time.time(), 'state': 'requested',
                  'request': metadata or {}}

        def run():
            path = ROOT / (record['id'] + '.json')
            try:
                _write(path, record)
                self.result = operation(cancel.is_set)
            except Exception as exc:
                self.result = {'state': 'uncertain', 'placed': 0, 'reason': f'{type(exc).__name__}: {exc}'[:200]}
            finally:
                record.update(state='finished', receipt=self.result, finished_at=time.time(), cancelled=cancel.is_set())
                try:
                    _write(path, record)
                except Exception as exc:
                    self.result['receipt_archive_error'] = f'{type(exc).__name__}: {exc}'[:200]
        self.thread = threading.Thread(target=run, daemon=True, name='re6-remote-ring')
        self.thread.start()
        return True

    def poll(self, owner):
        if self.owner != owner:
            self.cancel.set()
        if self.thread is None or self.thread.is_alive():
            return None
        result = self.result if owner == self.owner else None
        self.thread, self.result = None, None
        return result

    def close(self):
        self.cancel.set()


def control(ad, prof, bot_getter=None):
    from . import remote_mines as rules
    from .titles import re6_switch_native as native
    if str((prof or {}).get('map_id') or '') not in rules.TITLES:
        return None
    book, flight, travel = Deadlines(), RingFlight(), Travel()
    last_attempt = -math.inf
    blocked_owner, receipt_owner, awaiting_census, last_census = None, None, {}, None
    live_view = {}

    def owner_of(snap, stats):
        p = snap.get('player') or {}
        return stats.get('round_evidence_id'), p.get('ptr'), p.get('generation')

    def observe(snap, stats, now):
        nonlocal last_attempt, blocked_owner, receipt_owner, last_census
        owner = owner_of(snap, stats)
        travel.observe(owner, snap, stats, now, rules.policy(stats)['enabled'])
        p = snap.get('player') or {}
        live_view.update(owner=owner, seen=time.monotonic(), moving=travel.moving,
                         allowed=rules.policy(stats)['enabled'] and not stats.get('operator_control')
                         and not stats.get('round_evidence_closed')
                         and (p.get('hp') or 0) > 0 and stats.get('screen') in (None, 'playing'))
        if receipt_owner != owner:
            awaiting_census.clear()
            receipt_owner, last_census = owner, None
            stats.pop('mine_allocation_blocked_reason', None)
        if stats.get('operator_control'):
            flight.close()
        receipt = flight.poll(owner)
        new_placements = []
        stats['mine_ring_pending'] = flight.busy
        if receipt is not None:
            placed = int(receipt.get('placed') or 0)
            stats['mine_ring_last'] = receipt
            stats['mine_ring_bombs'] = int(stats.get('mine_ring_bombs', 0)) + placed
            trail = receipt.get('op') == 'bomb_trail'
            field = 'mine_trail_drops' if trail else 'mine_rings_dropped'
            stats[field] = int(stats.get(field, 0)) + bool(placed)
            if trail:
                stats['mine_trail_last'] = receipt
            for unit in receipt.get('units') or ():
                key = unit.get('unit'), unit.get('generation')
                if (unit.get('armed') is True and all(type(v) is int for v in key)
                        and finite(unit.get('placed_at')) and position(unit.get('pos'))):
                    record_placement(owner[1], owner[2], unit)
                    awaiting_census[key] = {**unit, 'kind': 'remote',
                        'action': 'cWpAction_wp_act_setting', 'evidence': 'native_placed_receipt'}
                    new_placements.append(awaiting_census[key])
            if receipt.get('state') == 'uncertain':
                blocked_owner = owner
                stats['mine_allocation_blocked_reason'] = 'uncertain native allocation; no further automatic bombs in this life'
            if receipt.get('state') != 'confirmed':
                field = 'mine_partial_rings' if placed else 'mine_ring_failures'
                stats[field] = int(stats.get(field, 0)) + 1
        # A pre-allocation snapshot can still be in the input loop when the
        # native receipt arrives. Preserve its placed proof until the census
        # catches that allocation; an old empty list cannot erase its deadline.
        census = snap.get('throwables')
        if isinstance(census, list):
            last_census = census
            for unit in census:
                if unit.get('action') in ('cWpAction_wp_act_setting', 'cWpAction_wp_act_bomb'):
                    awaiting_census.pop((unit.get('unit'), unit.get('generation')), None)
        if new_placements:
            # Seed confirmed placement before processing the newest snapshot:
            # it may already show the blast, which still needs its original
            # five-second start time and an observed-explosion receipt.
            known = {(u.get('unit'), u.get('generation')): u for u in last_census or ()}
            known.update({(u['unit'], u['generation']): u for u in new_placements})
            book.observe(dict(snap, throwables=list(known.values())), stats, now)
        # An unreadable census also preserves older hazards, including moving
        # bombs which have not reached their placed action yet.
        observed = dict(snap, throwables=list(last_census or ()) + list(awaiting_census.values())) \
            if awaiting_census else snap
        active = book.observe(observed, stats, now)
        out = {'fire': False, 'fired': False, 'op': 'remote_mines', 'reason': ''}
        if not stats.get('mine_deadline_pending'):
            return out
        player = snap.get('player') or {}
        pos = player.get('pos')
        positions = stats.get('mine_avoid_positions') or []
        if not (isinstance(pos, (list, tuple)) and len(pos) == 3 and all(finite(v) for v in pos)
                and positions):
            stats['mine_detonate_reason'] = 'native bomb clearance is unknown'
            return dict(out, reason=stats['mine_detonate_reason'])
        clearance = min(math.hypot(pos[0] - at[0], pos[2] - at[2]) for at in positions)
        safe = rules.policy(stats)['detonate_safe_cm']
        stats['mine_clearance_cm'] = round(clearance, 1)
        stats['mine_required_clearance_cm'] = safe
        stats['mine_escape_required'] = clearance < safe
        if clearance < safe:
            stats['mine_detonate_reason'] = f'escape first: nearest actual bomb {clearance:.0f} cm; need {safe:.0f} cm'
            return dict(out, reason=stats['mine_detonate_reason'])
        if not active:
            return dict(out, reason='native flag confirmed; waiting for observed blast')
        if flight.busy:
            # Stop producing more bombs once clear. Never clear the shared
            # armed bit while another spawn is about to set it again.
            flight.close()
            stats['mine_detonate_reason'] = 'allocation completing; remaining spawns cancelled for detonation'
            return dict(out, reason=stats['mine_detonate_reason'])
        if stats.get('operator_control') or (player.get('hp') or 0) <= 0:
            return dict(out, reason='automatic detonation waits for a live bot-controlled player')
        if now - last_attempt < .15:
            return out
        last_attempt = now
        # This live reread checks every allocation, every bomb position, held
        # state and player life. No pad release or weapon change is needed.
        receipt = native.bomb_detonate_now(ad, snap=snap)
        stats['mine_detonate_reason'] = str(receipt.get('reason') or '')[:200]
        if not receipt.get('verified'):
            stats['mine_detonate_failures'] = int(stats.get('mine_detonate_failures', 0)) + 1
            return dict(out, receipt=receipt, reason=stats['mine_detonate_reason'])
        stamp = receipt.get('triggered_at')
        book.triggered(receipt, stats, max(now, stamp) if finite(stamp) else now)
        stats['mine_flag_detonations'] = int(stats.get('mine_flag_detonations', 0)) + 1
        stats['mine_last_detonate_at'] = stamp if finite(stamp) else now
        return dict(out, op='bomb_detonate', fired=True, receipt=receipt,
                    reason=f"native flag confirmed for {receipt.get('count', 0)} bombs; observing blast")

    def step(snap, stats, now, hold=None, **_):
        result = observe(snap, stats, now)
        if result.get('fired'):
            return result
        policy = rules.policy(stats)
        if (not policy['enabled'] or stats.get('operator_control') or stats.get('round_evidence_closed')
                or stats.get('screen') not in (None, 'playing')):
            return dict(result, reason='automatic remote rings are switched off')
        if flight.busy or stats.get('mine_deadline_pending'):
            return dict(result, reason=result.get('reason') or 'existing bombs: escape and detonate before another ring')
        if blocked_owner == owner_of(snap, stats):
            return dict(result, reason=stats.get('mine_allocation_blocked_reason'))
        p = snap.get('player') or {}
        if not p.get('pos') or (p.get('hp') or 0) <= 0:
            return dict(result, reason='no living player in a round')
        # A complete census is needed before allocating another set. Unknown
        # observations must not manufacture an empty field or reset a fuse.
        if not isinstance(snap.get('throwables'), list):
            return dict(result, reason='waiting for a complete native bomb census')
        if any(u.get('kind') == 'remote' for u in snap['throwables']):
            return dict(result, reason='native remote bomb still present; wait for placement or completed blast')
        bot = bot_getter() if callable(bot_getter) else None
        if bot is not None and (getattr(bot, 'bomb_phase', None) is not None or getattr(bot, 'nade', None) is not None):
            return dict(result, reason="the driver's own bomb or grenade action is in progress")
        pos = p['pos']
        near = sum(1 for e in snap.get('enemies') or [] if (e.get('hp') or 0) > 0 and e.get('pos')
                   and math.dist(pos, e['pos']) <= rules.SURROUND_R_CM)
        recovery = stats.get('qte_escape_mines_due')
        flash_at = stats.get('qte_escape_flash_at') if recovery else stats.get('ring_flash_at')
        flash = (finite(flash_at) and 0 <= now - flash_at <= (5 if recovery else rules.FLASH_COMBO_S)
                 and stats.get('mine_flash_combo_at') != flash_at)
        surrounded = near >= rules.SURROUND_N and now - float(stats.get('mine_surround_at') or 0) >= rules.SURROUND_S
        emergency = flash or surrounded
        if not emergency and not travel.due(now):
            return dict(result, reason=f'measured travel {travel.distance:.0f}/{TRAVEL_CM:.0f} cm; no stationary timer drops')
        count, radius = (rules.FLASH_COMBO_MINES, policy['radius_cm']) if emergency else (1, 0.)
        owner = owner_of(snap, stats)
        if not owner[0] or any(type(v) is not int for v in owner[1:]):
            return dict(result, reason='native ring needs a verified round and player identity')
        def operation(cancelled):
            def stopped():
                return (cancelled() or live_view.get('owner') != owner or not live_view.get('allowed')
                        or time.monotonic() - live_view.get('seen', -math.inf) > 1.
                        or not emergency and not live_view.get('moving'))
            if not emergency:
                return single_drop_now(ad, owner, stopped)
            return emergency_ring_now(ad, owner, stopped, count, radius)
        if not flight.submit(owner, operation,
                {'count': count, 'radius_cm': radius, 'reason': 'flash' if flash else 'surrounded' if surrounded else 'travel',
                 'travel_cm': round(travel.distance, 1), 'player_pos': list(pos),
                 'session': stats.get('source_session_id')}):
            return dict(result, reason='native bomb allocation already in progress')
        travel.claimed(now)
        stats['mine_ring_pending'] = True
        stats['mine_ring_requests'] = int(stats.get('mine_ring_requests', 0)) + 1
        if not emergency:
            stats['mine_trail_requests'] = int(stats.get('mine_trail_requests', 0)) + 1
        stats.pop('mine_next_drop_at', None)
        if surrounded:
            stats['mine_surround_at'] = now
            stats['mine_surround_rings'] = int(stats.get('mine_surround_rings', 0)) + 1
        if flash:
            stats['mine_flash_combo_at'] = flash_at
            stats['mine_flash_combos'] = int(stats.get('mine_flash_combos', 0)) + 1
            stats.pop('qte_escape_mines_due', None)
        return dict(result, op='bomb_ring' if emergency else 'bomb_trail', pending=True,
                    reason=f'native {"emergency ring of up to " + str(count) if emergency else "single travel bomb"} requested; movement remains active')

    step.observe, step.close = observe, flight.close
    return step
