"""Five-second RE6 bomb deadlines, measured from native placed/armed evidence.

A flag write is not an observed explosion. Keep those timestamps separate, and
report overdue bombs without bypassing the live all-bomb clearance check.
"""
from __future__ import annotations

import math
import threading

DEADLINE_S = 5.0
SETTING = 'cWpAction_wp_act_setting'
BLAST = 'cWpAction_wp_act_bomb'
_PLACED = {}
_LOCK = threading.Lock()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def record_placement(player, player_generation, receipt):
    """Share exact native confirmations with manual, bot and ring observers."""
    key = (player, player_generation, receipt.get('unit'), receipt.get('generation'))
    if not all(type(v) is int for v in key) or not finite(receipt.get('placed_at')):
        return
    with _LOCK:
        _PLACED[key] = receipt['placed_at']
        if len(_PLACED) > 1024:
            for old in list(_PLACED)[:256]:
                _PLACED.pop(old, None)


class Deadlines:
    def __init__(self):
        self.owner = None
        self.units = {}

    def observe(self, snap, stats, now):
        player = snap.get('player') or {}
        owner = (stats.get('round_evidence_id'), player.get('ptr'), player.get('generation'))
        if owner != self.owner:
            self.owner, self.units = owner, {}
        observed = snap.get('throwables')
        if isinstance(observed, list):
            live = {}
            positions = []
            for unit in observed:
                if not isinstance(unit, dict) or unit.get('kind') != 'remote':
                    continue
                key = (unit.get('unit'), unit.get('generation'))
                if not all(type(v) is int for v in key):
                    continue
                pos = unit.get('pos')
                if isinstance(pos, (tuple, list)) and len(pos) == 3 and all(finite(v) for v in pos):
                    positions.append(list(pos))
                row = self.units.get(key)
                if row is None and unit.get('action') == SETTING:
                    with _LOCK:
                        native_at = _PLACED.get((*owner[1:], *key))
                    # A stale allocation receipt cannot predate this observer by
                    # minutes. Untracked hand throws use their first native
                    # placed observation, explicitly a lower bound on age.
                    native = finite(native_at) and 0 <= now - native_at <= 60
                    row = {'unit': key[0], 'generation': key[1],
                           'placed_at': native_at if native else now,
                           'timing_source': 'native_placed_armed' if native else 'first_observed_placed',
                           'missed': False, 'triggered_at': None, 'blast_at': None}
                if row is not None:
                    row['pos'] = list(pos) if pos is not None else None
                    row['action'] = unit.get('action')
                    if row['blast_at'] is None and unit.get('action') == BLAST:
                        row['blast_at'] = now
                        if now - row['placed_at'] > DEADLINE_S and not row['missed']:
                            row['missed'] = True
                            stats['mine_deadline_misses'] = int(stats.get('mine_deadline_misses', 0)) + 1
                        stats['mine_blasts_observed'] = int(stats.get('mine_blasts_observed', 0)) + 1
                        self._result(stats, row, now, 'native_blast_observed')
                    live[key] = row
            for key, row in self.units.items():
                if key not in live and row.get('triggered_at') is not None and row.get('blast_at') is None:
                    self._result(stats, row, now, 'unit_disappeared_after_flag')
            self.units = live
            stats['mine_avoid_positions'] = positions
        pending = [r for r in self.units.values() if r.get('blast_at') is None]
        active = [r for r in pending if r.get('triggered_at') is None]
        stats['mine_deadline_pending'] = len(pending)
        stats['mine_escape_required'] = bool(pending)
        if pending:
            oldest = min(pending, key=lambda r: r['placed_at'])
            stats.update(mine_oldest_placed_at=oldest['placed_at'],
                         mine_deadline_at=oldest['placed_at'] + DEADLINE_S,
                         mine_elapsed_s=round(max(0, now - oldest['placed_at']), 3),
                         mine_remaining_s=round(oldest['placed_at'] + DEADLINE_S - now, 3),
                         mine_timing_source=oldest['timing_source'])
            for row in pending:
                if now - row['placed_at'] > DEADLINE_S and not row['missed']:
                    row['missed'] = True
                    stats['mine_deadline_misses'] = int(stats.get('mine_deadline_misses', 0)) + 1
                    event = dict(row, deadline_at=row['placed_at'] + DEADLINE_S, observed_at=now,
                                 player_pos=player.get('pos'),
                                 reason=stats.get('mine_detonate_reason') or 'no blast observed before deadline')
                    log = stats.setdefault('mine_deadline_incidents', [])
                    log.append(event)
                    del log[:-16]
        else:
            for field in ('mine_oldest_placed_at', 'mine_deadline_at', 'mine_elapsed_s',
                          'mine_remaining_s', 'mine_timing_source'):
                stats.pop(field, None)
        return active

    def triggered(self, receipt, stats, now):
        if not receipt.get('verified'):
            return
        for row in self.units.values():
            if row['unit'] in (receipt.get('detonated') or []) and row.get('triggered_at') is None:
                row['triggered_at'] = receipt.get('triggered_at', now)
                self._result(stats, row, now, 'native_flag_readback')

    @staticmethod
    def _result(stats, row, now, outcome):
        elapsed = max(0, now - row['placed_at'])
        stats['mine_deadline_last'] = {k: row.get(k) for k in
            ('unit', 'generation', 'placed_at', 'triggered_at', 'blast_at', 'timing_source')}
        stats['mine_deadline_last'].update(outcome=outcome, elapsed_s=round(elapsed, 3),
            observed_within_five_seconds=elapsed <= DEADLINE_S,
            blast_confirmed=outcome == 'native_blast_observed')
