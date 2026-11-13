"""Gated RE5 native single drops without taking ownership of the input pad.

The native controller owns allocation and activation. This worker owns only a
single request, its round identity, cancellation and an archived receipt. The
combat thread consumes the result and keeps moving while the request runs.
"""
from __future__ import annotations

import math
from pathlib import Path
import queue
import struct
import threading
import time
import uuid

from ..follow_report_delivery import _write

ROOT = Path(__file__).resolve().parents[3] / 'gbox-data' / 'mercs' / 'native-mine-receipts'
DEADLINE_S, OBSERVER_FRESH_S = 24., 2.
GUARD_ATTRIBUTE = '_re5_native_mine_guard'
DISTANCE_CM, REACTION_S, REQUEST_GAP_S = 609.6, 8., 3.
TRAVEL_MOTIONS = frozenset({1, 4, 7})  # walk, observed B+LUP sprint, backing


def position(value):
    return (isinstance(value, (tuple, list)) and len(value) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in value))


class Cadence:
    """Observed travel, with one bounded request per hit/grab event."""
    def __init__(self):
        self.owner, self.previous = None, None
        self.distance, self.last_request = 0., -math.inf
        self.event_id = None
        self.traversal_id = None

    def observe(self, snap, stats, now, enabled=True):
        from . import re5_switch as R
        owner, p = identity(snap, stats), snap.get('player') or {}
        if owner != self.owner:
            self.__init__()
            self.owner = owner
        valid = (enabled and _owner_ok(owner) and not stats.get('operator_control')
                 and not stats.get('round_evidence_closed') and stats.get('screen') in (None, 'playing')
                 and snap.get('mercenaries_phase') == R.PHASE_PLAYING
                 and (p.get('hp') or 0) > R.DYING_HP and position(p.get('pos')))
        moving = valid and p.get('motion') in TRAVEL_MOTIONS
        if moving and self.previous is not None:
            then, old = self.previous
            dt, step = now - then, math.dist(old, p['pos'])
            # Missing observations, warps and wall-clock jumps are not travel.
            if 0 < dt <= 1. and step <= 1200. * dt + 30.:
                self.distance = min(DISTANCE_CM, self.distance + step)
        self.previous = (now, tuple(p['pos'])) if moving else None
        if not enabled:
            self.distance = 0.
            event = stats.get('automine_event') or {}
            self.event_id = event.get('id')
            self.traversal_id = (stats.get('traversal_mine_event') or {}).get('id')
        stats.update(automine_enabled=bool(enabled), automine_distance_cm=round(self.distance, 1),
                     automine_interval_ft=20)

    def demand(self, snap, stats, now):
        if now - self.last_request < REQUEST_GAP_S:
            return None
        event = stats.get('automine_event') or {}
        if (tuple(event.get('owner') or ()) == self.owner and event.get('id') != self.event_id
                and event.get('kind') in ('hit', 'qte') and type(event.get('at')) in (int, float)
                and 0 <= now - event['at'] <= REACTION_S):
            return event['kind'], event['id']
        from .re5_traversal import EVENT_FRESH_S
        landing = stats.get('traversal_mine_event') or {}
        if (tuple(landing.get('owner') or ()) == self.owner and landing.get('id') != self.traversal_id
                and landing.get('kind') == 'traversal' and position(landing.get('pos'))
                and type(landing.get('at')) in (int, float) and 0 <= now-landing['at'] <= EVENT_FRESH_S):
            return 'traversal', landing['id']
        if self.distance >= DISTANCE_CM and (snap.get('player') or {}).get('motion') in TRAVEL_MOTIONS:
            return 'distance', None
        return None

    def claimed(self, demand, now):
        self.last_request = now
        self.distance = 0.                           # no burst of catch-up drops after a long request
        if demand[1] is not None:
            if demand[0] == 'traversal':
                self.traversal_id = demand[1]
            else:
                self.event_id = demand[1]


def enabled(memory):
    from . import re5_proximity_native as native
    adapter = getattr(memory, 'adapter', None)
    return (native.LIVE_VERIFIED is True and adapter is not None
            and getattr(adapter, 'address_mode', None) == 'direct'
            and not getattr(memory, 'mercs_no_modifications', False))


def identity(snap, stats):
    player = snap.get('player') or {}
    return stats.get('round_evidence_id'), player.get('ptr'), player.get('generation')


def _owner_ok(owner):
    return bool(owner[0]) and all(type(v) is int for v in owner[1:])


def _run(memory, expected, allowed, *, count=1, center=None, on_deployed=None):
    from . import re5_switch_native as native
    adapter = memory.adapter
    with native._CREATE_LOCK:
        ctl = getattr(adapter, '_re5_native_flash', None)
        if ctl is None:
            ctl = adapter._re5_native_flash = native.Controller(adapter)
    return ctl.proximity_mines(count=count, expected=expected, allowed=allowed, wait_for_lock=False,
                               center=center, on_deployed=on_deployed)


class Flight:
    def __init__(self, memory, *, run=None):
        self.memory, self.run = memory, run or _run
        self.job, self.owner, self.blocked_owner = None, None, None
        self.closed, self.live = False, False
        self.seen = -math.inf
        self.guard = None
        self.clearance_cm = 500.
        self.emergency = False
        self.deployments = queue.Queue(maxsize=40)

    def cancel(self):
        if self.job is not None:
            self.job['cancel'].set()

    def close(self):
        self.closed = True
        self.cancel()

    def observe(self, snap, stats):
        from . import re5_switch as R
        owner, p = identity(snap, stats), snap.get('player') or {}
        self.seen = time.monotonic()
        self.live = bool(not self.closed and enabled(self.memory) and _owner_ok(owner)
                         and not stats.get('operator_control') and not stats.get('round_evidence_closed')
                         and stats.get('screen') in (None, 'playing')
                         and snap.get('mercenaries_phase') == R.PHASE_PLAYING
                         and stats.get('automine_enabled', True) and position(p.get('pos'))
                         and (p.get('hp') or 0) > R.DYING_HP
                         and (self.emergency or p.get('motion') not in R.MOTION_HELD))
        self.owner = owner
        if self.job is not None and (not self.live or owner != self.job['owner']):
            self.cancel()
        if _owner_ok(owner):
            guard = getattr(self.memory, GUARD_ATTRIBUTE, None)
            if not isinstance(guard, dict) or guard.get('owner') != owner:
                guard = {'owner': owner, 'actors': {}, 'pending': False, 'needs_scan': True}
            guard.update(seen=self.seen, pending=bool(self.job and self.job['owner'] == owner
                                                     and not self.job['done'].is_set()))
            self.guard = guard
            setattr(self.memory, GUARD_ATTRIBUTE, guard)

    def poll(self, snap, stats):
        self.observe(snap, stats)
        job = self.job
        stats['native_mine_pending'] = bool(job and not job['done'].is_set())
        if job is None or not job['done'].is_set():
            return None
        self.job = None
        result = job['result']
        if self.owner != job['owner']:
            stats['native_mine_retired'] = {'id': job['id'], 'owner': list(job['owner']),
                                           'state': result.get('state'), 'archive': str(job['path'])}
            return None
        # An uncertain allocation is not a cue to allocate another actor. Its
        # hazards remain observable; another round must begin before auto retry.
        if result.get('state') == 'uncertain' or result.get('prepared') and result.get('state') != 'confirmed':
            self.blocked_owner = job['owner']
        if self.guard is not None:
            for row in [*(result.get('prepared') or ()), *(result.get('mines') or ())]:
                if isinstance(row, dict) and type(row.get('unit')) is int and type(row.get('generation')) is int:
                    self.guard['actors'][row['unit']] = row['generation']
            self.guard['pending'] = False
        return {'id': job['id'], 'owner': job['owner'], 'receipt': result,
                'requested': job['requested'], 'center': job['center'],
                'reason': job['reason'],
                'cancelled': job['cancel'].is_set(), 'archive': str(job['path'])}

    def take_deployments(self):
        """Combat-thread drain; the worker only queues detached owned facts."""
        rows = []
        for _ in range(40):
            try:
                row = self.deployments.get_nowait()
            except queue.Empty:
                break
            if row['owner'] == self.owner:
                rows.append(row)
        return rows

    def submit(self, snap, stats, now, *, reason='distance', count=1, center=None):
        from ..primary_weapon import quiescing
        if type(count) is not int or count not in (1, 5) or center is not None and not position(center):
            return False
        if quiescing(stats, snap):
            stats['native_mine_admission_pause'] = 'native weapon handover prevents immediate escape'
            return False
        stats.pop('native_mine_admission_pause', None)
        center = tuple(center) if center is not None else None
        self.emergency = reason in ('hit', 'qte')
        self.observe(snap, stats)
        if not self.live or self.job is not None or self.owner == self.blocked_owner:
            return False
        owner = self.owner
        landing = None
        remaining = DEADLINE_S
        if reason == 'traversal':
            from .re5_traversal import EVENT_FRESH_S
            event = stats.get('traversal_mine_event') or {}
            if (event.get('kind') != 'traversal' or tuple(event.get('owner') or ()) != owner
                    or event.get('id') is None or not position(event.get('pos'))
                    or tuple(event['pos']) != center or type(event.get('at')) not in (int, float)
                    or not 0 <= now-event['at'] < EVENT_FRESH_S):
                return False
            landing = {k: event.get(k) for k in ('id', 'at', 'kind')}
            landing.update(owner=list(event['owner']), pos=list(event['pos']))
            remaining = EVENT_FRESH_S-(now-event['at'])
        rid = uuid.uuid4().hex
        job = {'id': rid, 'owner': owner, 'cancel': threading.Event(), 'done': threading.Event(),
               'path': ROOT / (rid + '.json'), 'requested': count, 'center': center, 'reason': reason}
        record = {'schema': 'gbox.mercs.native-mine/1', 'id': rid, 'owner': list(owner),
                  'session': stats.get('source_session_id'), 'requested_at': now,
                  'requested': count, 'center': center, 'state': 'requested', 'reason': reason}
        if reason == 'traversal':
            event = stats.get('traversal_mine_event') or {}
            record['traversal'] = {k: event.get(k) for k in ('id','at','pos','traversal',
                'entered_at','native_action','completed_action','completion_flag_seen','evidence')}
        started = time.monotonic()
        deadline, landing_deadline = started + DEADLINE_S, started + remaining
        landing_deployed = threading.Event()

        def allowed():
            stamp = time.monotonic()
            return (not self.closed and not job['cancel'].is_set() and enabled(self.memory)
                    and self.live and self.owner == owner and stamp < deadline
                    and (landing is None or landing_deployed.is_set()
                         or stamp < landing_deadline
                         and all((stats.get('traversal_mine_event') or {}).get(k) == v
                                 for k, v in landing.items()))
                    and 0 <= stamp - self.seen <= OBSERVER_FRESH_S
                    and stats.get('round_evidence_id') == owner[0]
                    and not stats.get('round_evidence_closed') and not stats.get('operator_control')
                    and stats.get('automine_enabled', True)
                    and not quiescing(stats, {'player': {'ptr': owner[1], 'generation': owner[2]}})
                    and stats.get('screen') in (None, 'playing'))

        def deployed(row):
            if (not isinstance(row, dict) or type(row.get('unit')) is not int
                    or type(row.get('generation')) is not int or not position(row.get('pos'))):
                return
            mine = {'unit': row['unit'], 'generation': row['generation'], 'pos': tuple(row['pos']),
                    'active': row.get('active') is True, 'armed_observed': False}
            if row.get('active') is True:
                # A committed physical mine remains a hazard even after its
                # landing token expires. Finish observing native arming; this
                # does not permit another allocation (traversal count is one).
                landing_deployed.set()
            deployed_center = center if center is not None else tuple(row['center']) if position(row.get('center')) else None
            try:
                self.deployments.put_nowait({'id': rid, 'owner': owner, 'center': deployed_center,
                                            'requested': count, 'mine': mine})
            except queue.Full:
                job['deployment_queue_overflow'] = True

        def work():
            entered_native = False
            try:
                _write(job['path'], record)
                if not allowed():
                    job['result'] = {'state': 'unavailable', 'reason': 'native mine request no longer belongs to live play'}
                else:
                    entered_native = True
                    job['result'] = self.run(self.memory, owner[1:], allowed,
                                            count=count, center=center, on_deployed=deployed)
                    if not isinstance(job['result'], dict):
                        job['result'] = {'state': 'uncertain', 'reason': 'native mine returned no receipt'}
            except Exception as exc:
                from .re5_switch_native import Unavailable, ControllerBusy
                state = 'unavailable' if type(exc) in (Unavailable, ControllerBusy) else 'uncertain' if entered_native else 'failed'
                job['result'] = {'state': state, 'reason': f'{type(exc).__name__}: {exc}'[:240]}
            finally:
                record.update(state='finished', receipt=job['result'], finished_at=time.time(),
                              cancelled=job['cancel'].is_set(),
                              deployment_queue_overflow=job.get('deployment_queue_overflow', False))
                try:
                    _write(job['path'], record)
                except Exception as exc:
                    job['result']['receipt_archive_error'] = str(exc)[:200]
                job['done'].set()

        self.job = job
        if self.guard is not None:
            self.guard['pending'] = True
        try:
            threading.Thread(target=work, name='re5-native-mine-drop', daemon=True).start()
        except Exception:
            self.job = None
            if self.guard is not None:
                self.guard['pending'] = False
            raise
        stats.update(native_mine_pending=True, native_mine_request_id=rid, native_mine_requested_at=now)
        return True


def watching(memory, player):
    guard = getattr(memory, GUARD_ATTRIBUTE, None)
    return (isinstance(guard, dict)
            and guard.get('owner', (None,))[1:] == (player.get('ptr'), player.get('generation'))
            and 0 <= time.monotonic() - guard.get('seen', -math.inf) <= OBSERVER_FRESH_S)


def ground(memory, base, player):
    """Read a current owner's native mines, including one still being activated.

    Only an admitted worker creates this guard. While it is pending, its line is
    walked with the existing 64-unit bound. Thereafter only remembered actors are
    read, each by native class/generation/owner. None means no valid observation,
    never an empty census inferred from a partial or failed read.
    """
    from . import re5_switch as R, re5_proximity_native as native
    guard = getattr(memory, GUARD_ATTRIBUTE, None)
    if isinstance(guard, dict):
        guard['observations'] = None
    if not watching(memory, player):
        return None
    p, generation = player['ptr'], player['generation']
    actors = dict(guard.get('actors') or {})
    try:
        q = lambda at: struct.unpack('<Q', memory.rd(at, 8))[0]
        flag = lambda at: struct.unpack('<B', memory.rd(at, 1))[0] == 1
        if q(p + 0x1A00) != generation:
            return None
        if guard.get('pending') or guard.get('needs_scan'):
            su = q(base + R.S_UNIT)
            u = q(su + R.UNIT_LINES + R.LINE_STRIDE * R.MINE_LINE) if R.ptr_ok(su) else 0
            seen = set()
            while R.ptr_ok(u) and len(seen) < R.GROUND_MAX:
                if u in seen:
                    return None
                seen.add(u)
                if q(u) == base + native.VTABLE and q(u + 0x1A10) == p and flag(u + 0x27B9):
                    actors[u] = q(u + 0x1A00)
                u = q(u + R.UNIT_NEXT)
            if R.ptr_ok(u):
                return None
        if len(actors) > 40:
            return None
        out, observations, retained = [], [], {}
        retirements = dict(guard.get('retirements') or {})
        for unit, born in actors.items():
            current = (q(unit), q(unit + 0x1A00), q(unit + 0x1A10))
            if current != (base + native.VTABLE, born, p):
                if current != (q(unit), q(unit + 0x1A00), q(unit + 0x1A10)):
                    return None  # changing allocation is not a stable retirement witness
                retirements[(unit, born)] = {'ptr': unit, 'generation': born, 'native_owner': p,
                    'retired_observed': True, 'retirement_reason': 'native allocation identity changed',
                    'observed_vtable': current[0], 'observed_generation': current[1], 'observed_owner': current[2]}
                continue
            trigger = flag(unit + 0x28C1)
            active = flag(unit + 0x27B9)
            primary, proximity = q(unit + 0x2710), q(unit + 0x28C8)
            primary_enabled = flag(primary + 0x14) if R.ptr_ok(primary) else None
            proximity_enabled = flag(proximity + 0x14) if R.ptr_ok(proximity) else None
            pos = struct.unpack('<3f', memory.rd(unit + R.E_POS, 12))
            if not all(math.isfinite(v) for v in pos):
                return None
            if q(unit) != base + native.VTABLE or q(unit + 0x1A00) != born or q(unit + 0x1A10) != p:
                return None  # allocation changed during the read, not a confirmed empty census
            row = {'ptr': unit, 'generation': born, 'pos': pos, 'native_owner': p,
                   'active': active, 'trigger_observed': trigger, 'primary_enabled': primary_enabled,
                   'proximity_enabled': proximity_enabled}
            observations.append(row)
            if trigger:
                continue  # observed latch is preserved below, but no longer a standing ground hazard
            retained[unit] = born
            if active:
                out.append(row)
        if q(p + 0x1A00) != generation:
            return None
        guard['actors'] = retained
        # Keep a bounded witness across prompt-only ticks. The combat thread
        # may not consume the very first snapshot in which an actor retired.
        guard['retirements'] = dict(list(retirements.items())[-80:])
        guard['observations'] = observations + list(guard['retirements'].values())
        guard['needs_scan'] = False
        return out
    except (ValueError, OSError, OverflowError, struct.error, TypeError):
        return None


def ground_observations(memory, player):
    """The last complete owned read, including an observed trigger/inactive transition."""
    guard = getattr(memory, GUARD_ATTRIBUTE, None)
    return guard.get('observations') if watching(memory, player) else None
