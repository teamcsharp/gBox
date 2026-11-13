"""Nonblocking RE6 remote rings and deadline-first native detonation."""
from __future__ import annotations

import math
from pathlib import Path
import random
import threading
import time
import uuid

from .re6_bomb_deadlines import Deadlines, finite
from .follow_report_delivery import _write

ROOT = Path(__file__).resolve().parents[2] / 'gbox-data' / 'mercs' / 'native-remote-receipts'


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
    book, flight = Deadlines(), RingFlight()
    last_attempt = -math.inf

    def owner_of(snap, stats):
        p = snap.get('player') or {}
        return stats.get('round_evidence_id'), p.get('ptr'), p.get('generation')

    def observe(snap, stats, now):
        nonlocal last_attempt
        owner = owner_of(snap, stats)
        if stats.get('operator_control'):
            flight.close()
        receipt = flight.poll(owner)
        stats['mine_ring_pending'] = flight.busy
        if receipt is not None:
            placed = int(receipt.get('placed') or 0)
            stats['mine_ring_last'] = receipt
            stats['mine_ring_bombs'] = int(stats.get('mine_ring_bombs', 0)) + placed
            stats['mine_rings_dropped'] = int(stats.get('mine_rings_dropped', 0)) + bool(placed)
            if receipt.get('state') != 'confirmed':
                field = 'mine_partial_rings' if placed else 'mine_ring_failures'
                stats[field] = int(stats.get(field, 0)) + 1
        active = book.observe(snap, stats, now)
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
        if not policy['enabled'] or stats.get('operator_control'):
            return dict(result, reason='automatic remote rings are switched off')
        if flight.busy or stats.get('mine_deadline_pending'):
            return dict(result, reason=result.get('reason') or 'existing bombs: escape and detonate before another ring')
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
        next_at = stats.get('mine_next_drop_at')
        if not flash and not surrounded and finite(next_at) and now < next_at:
            return dict(result, reason=f'{next_at-now:.1f} s to next ring')
        count = rules.FLASH_COMBO_MINES if flash or surrounded else policy['count']
        owner = owner_of(snap, stats)
        if not owner[0] or any(type(v) is not int for v in owner[1:]):
            return dict(result, reason='native ring needs a verified round and player identity')
        flight.submit(owner, lambda cancelled: native.bomb_ring_now(ad, count=count,
            radius_cm=policy['radius_cm'], expected_player=p.get('ptr'),
            expected_generation=p.get('generation'), cancelled=cancelled),
            {'count': count, 'radius_cm': policy['radius_cm'], 'session': stats.get('source_session_id')})
        stats['mine_ring_pending'] = True
        stats['mine_ring_requests'] = int(stats.get('mine_ring_requests', 0)) + 1
        stats['mine_next_drop_at'] = now + policy['drop_every_s'] + random.uniform(
            -policy['drop_jitter_s'], policy['drop_jitter_s'])
        if surrounded:
            stats['mine_surround_at'] = now
            stats['mine_surround_rings'] = int(stats.get('mine_surround_rings', 0)) + 1
        if flash:
            stats['mine_flash_combo_at'] = flash_at
            stats['mine_flash_combos'] = int(stats.get('mine_flash_combos', 0)) + 1
            stats.pop('qte_escape_mines_due', None)
        return dict(result, op='bomb_ring', pending=True,
                    reason=f'native ring of up to {count} requested; movement remains active')

    step.observe, step.close = observe, flight.close
    return step
