"""One periodic crowd tactic, independently due from routine defensive rings.

This scheduler never owns movement, changes animation rates or allocates mines.
It chooses verified native effects and hands confirmed flash follow-ups to the
title's existing owned placement/escape controller.
"""
from __future__ import annotations

import importlib
import math
import random

INTERVAL_S, RETRY_S, FOLLOWUP_S = 120., 10., 8.
SEPARATION_S = 6.  # extra volleys remain separated; reactive rings may be accounted for in place
RE5, RE6 = '010018100CD46000', '01002A000CD48000'


def owner(snap, stats):
    p = snap.get('player') or {}
    return (stats.get('round_evidence_id') or stats.get('rounds') or stats.get('round'),
            p.get('ptr'), p.get('generation', p.get('id')))


def pending_reason(snap, stats):
    for key in ('native_mine_pending', 'ring_async_pending', 'mine_ring_pending', 'mine_deadline_pending',
                'mine_escape_required', 'native_mine_escape_required'):
        if stats.get(key):
            return key
    if stats.get('bot_grenade_state') == 'requested':
        return 'native grenade request pending'
    if any(u.get('kind') == 'remote' for u in snap.get('throwables') or () if isinstance(u, dict)):
        return 'existing native remote bomb'
    return None


def capabilities(target, *, background=False):
    """Separate verified scatter repertoire from ring capability reporting."""
    from .grenade_ring import KINDS
    rows = target.grenade_kinds()
    kinds = {r.get('kind') for r in rows or () if isinstance(r, dict)
             and r.get('available') is True and r.get('kind') in KINDS}
    if background:
        kinds &= {'flash'}
    out = [('ring', k) for k in sorted(kinds)] if callable(getattr(target, 'grenade_ring', None)) else []
    if callable(getattr(target, 'grenade_scatter', None)):
        module = importlib.import_module(type(target).__module__)
        scatter = getattr(target, 'SCATTER_KINDS', getattr(module, 'SCATTER_KINDS', ()))
        out.extend(('scatter', k) for k in sorted(kinds.intersection(scatter)))
    return out


class Roulette:
    def __init__(self, title, *, rng=None):
        self.title, self.rng = title, rng or random
        self.owner, self.next_at, self.at = None, math.inf, None
        self.pending, self.previous, self.sequence = None, None, 0
        self.retry_at = -math.inf

    def _event(self, stats, now, state, plan, **extra):
        row = {'at': now, 'state': state, **plan, **extra}
        rows = stats.setdefault('crowd_roulette_events', [])
        rows.append(row)
        del rows[:-24]
        stats['crowd_roulette_last'] = row

    def observe(self, snap, stats, now):
        current = owner(snap, stats)
        if current != self.owner or self.at is not None and now < self.at:
            if self.pending is not None:
                self._event(stats, now, 'retired', self.pending, reason='round or player lifetime changed')
            self.owner, self.next_at, self.pending = current, now+INTERVAL_S, None
            self.previous, self.sequence, self.retry_at = None, 0, -math.inf
        self.at = now
        stats['crowd_roulette_due_in_s'] = round(max(0., self.next_at-now), 1)
        stats['crowd_roulette_interval_s'] = INTERVAL_S
        follow = stats.get('crowd_roulette_mine_event') or {}
        if (follow.get('id') and follow.get('at', now) + FOLLOWUP_S < now
                and stats.get('crowd_roulette_mine_status') == 'requested'):
            stats['crowd_roulette_mine_status'] = 'expired before native placement admission'

    def decide(self, snap, stats, now, normal, policy, scatter, target, *, background=False):
        """None preserves normal rules; a wait reserves the due periodic slot."""
        from . import grenade_ring as G
        if now < self.next_at or self.pending is not None:
            return None
        p = snap.get('player') or {}
        if (not policy['enabled'] or stats.get('operator_control') or stats.get('round_evidence_closed')
                or stats.get('screen') not in (None, 'playing', 'unknown')
                or not self.owner[0] or any(type(v) is not int for v in self.owner[1:])
                or (p.get('hp') or 0) <= 0):
            return None
        # QTE/hit/traversal and boss responses retain their existing priority.
        # Only coalesce() can credit an existing reactive flash to this clock.
        if (normal.get('fire') and (normal.get('reactive') or normal.get('traversal')
                or normal.get('defend') or normal.get('dangerous'))
                or (snap.get('game') or {}).get('phase') == 'grabbed'):
            return None
        rows = G.enemies_near(snap, scatter['reach_cm'])
        pos = p.get('pos')
        rows = [(d, e) for d, e in rows if abs(e['pos'][1]-pos[1]) <= scatter['floor_dy_cm']]
        if len(rows) < 2:
            stats['crowd_roulette_wait'] = 'due; waiting for a crowd on the player floor'
            return None
        def wait(reason):
            stats['crowd_roulette_wait'] = reason
            return {'fire': False, 'roulette_wait': True, 'reason': reason}
        if reason := pending_reason(snap, stats):
            return wait('periodic crowd tactic waits: '+reason)
        if now < self.retry_at:
            return wait('periodic crowd capability retry cooldown')
        last = stats.get('ring_last_at')
        if isinstance(last, (int, float)) and now-last < SEPARATION_S:
            return wait('periodic crowd tactic waits for separation from the last ring')
        if normal['radius_cm'] > policy['max_radius_cm']:
            return wait('periodic crowd tactic lacks supported blast clearance')
        try:
            options = capabilities(target(), background=background)
        except Exception as exc:
            self.retry_at = now+RETRY_S
            return wait('native crowd capabilities unavailable: '+str(exc)[:140])
        if not scatter['enabled']:
            options = [o for o in options if o[0] != 'scatter']
        scatter_last = stats.get('scatter_last_at')
        if isinstance(scatter_last, (int, float)) and now-scatter_last < scatter['cooldown_s']:
            options = [o for o in options if o[0] != 'scatter']
        if G.flash_held(snap, stats, policy, self.title) is not None:
            options = [o for o in options if o[1] != 'flash']
        if not options:
            # A routine flash must not keep resetting the flash clock while the
            # only verified periodic effect waits for it to mature.
            return wait('periodic crowd tactic awaits an available verified effect and its cooldown')
        choices = [o for o in options if o != self.previous] or options
        operation, kind = self.rng.choice(choices)
        self.sequence += 1
        plan = {'id': f'{self.owner[0]}:{self.owner[1]}:{self.owner[2]}:crowd:{self.sequence}',
                'owner': list(self.owner), 'operation': operation, 'kind': kind, 'selected_at': now,
                'count': scatter['count'] if operation == 'scatter' else normal['count']}
        if kind == 'flash' and self.title in (RE5, RE6):
            plan['followup_mines'] = self.rng.choice((1, 5)) if self.title == RE5 else 5
        self.pending, self.previous = plan, (operation, kind)
        stats.pop('crowd_roulette_wait', None)
        stats['crowd_roulette_chosen'] = stats.get('crowd_roulette_chosen', 0)+1
        self._event(stats, now, 'chosen', plan)
        reason = f'periodic crowd roulette: {kind} {operation}; {len(rows)} enemies on this floor'
        if operation == 'scatter':
            return {'fire': True, 'roulette': plan, 'reason': reason, 'count': scatter['count'],
                    'kinds': [kind], 'narrowed': True, 'flash': kind == 'flash', 'flash_ok': True,
                    'toward': [(e['pos'][0], e['pos'][2]) for _, e in rows[:scatter['toward_n']]],
                    'safe_cm': max(0., float(stats.get('bomb_safe_cm') or 0.))}
        return {**normal, 'fire': True, 'roulette': plan, 'kind': kind, 'flash_ok': True, 'reason': reason}

    def coalesce(self, snap, stats, now, decision, policy, scatter, target, *, background=False):
        """Account for one already-required full reactive flash, never add a native call.

        Frequent hit/QTE flashes must not postpone the periodic clock forever.
        Their existing admission and clearance still own the effect. Its exact
        receipt can fulfill the due flash volley, explicitly as a coalesced
        emergency action, without duplicating its hit/QTE mine demand.
        """
        p = snap.get('player') or {}
        if (now < self.next_at or now < self.retry_at or self.pending is not None
                or owner(snap, stats) != self.owner or not self.owner[0]
                or any(type(v) is not int for v in self.owner[1:])
                or not policy['enabled'] or stats.get('operator_control')
                or stats.get('round_evidence_closed') or stats.get('screen') not in (None, 'playing', 'unknown')
                or (p.get('hp') or 0) <= 0 or not decision.get('fire') or not decision.get('reactive')
                or decision.get('kind') != 'flash' or type(decision.get('count')) is not int
                or decision['count'] < policy['count']
                or not isinstance(decision.get('radius_cm'), (int, float))
                or not policy['min_safe_cm'] <= decision['radius_cm'] <= policy['max_radius_cm']):
            return decision
        # Pending/existing explosive and escape gates remain intact, even
        # though this accounting method cannot start another constructor.
        if pending_reason(snap, stats):
            return decision
        source = decision.get('reactive_event')
        if isinstance(source, dict) and tuple(source.get('owner') or ()) != self.owner:
            return decision
        from . import grenade_ring as G
        rows = G.enemies_near(snap, scatter['reach_cm'])
        pos = p.get('pos')
        if not pos or sum(abs(e['pos'][1]-pos[1]) <= scatter['floor_dy_cm'] for _, e in rows) < 2:
            return decision
        try:
            if ('ring', 'flash') not in capabilities(target(), background=background):
                return decision
        except Exception:
            return decision  # capability bookkeeping must never delay the actual emergency
        self.sequence += 1
        plan = {'id': f'{self.owner[0]}:{self.owner[1]}:{self.owner[2]}:crowd:{self.sequence}',
                'owner': list(self.owner), 'operation': 'ring', 'kind': 'flash', 'selected_at': now,
                'count': decision['count'], 'coalesced': 'reactive_flash',
                'source_event': decision.get('reactive_event') or decision.get('trigger')}
        self.pending, self.previous = plan, ('ring', 'flash')
        stats.pop('crowd_roulette_wait', None)
        stats['crowd_roulette_chosen'] = stats.get('crowd_roulette_chosen', 0)+1
        self._event(stats, now, 'chosen', plan)
        return {**decision, 'roulette': plan}

    def submitted(self, stats, now, decision, result):
        plan = decision.get('roulette')
        if not plan or self.pending != plan:
            return
        if result.get('pending'):
            self._event(stats, now, 'submitted', plan)

    def retire(self, stats, now, reason):
        if self.pending is not None:
            self._event(stats, now, 'retired', self.pending, reason=reason)
            self.pending, self.next_at = None, now+INTERVAL_S

    def finish(self, snap, stats, now, decision, receipt):
        plan = decision.get('roulette')
        if not plan or self.pending != plan or tuple(plan['owner']) != owner(snap, stats):
            return
        actual = receipt.get('kinds') if plan['operation'] == 'scatter' else [receipt.get('kind')]
        count = receipt.get('detonated')
        complete = (receipt.get('state') == 'confirmed' and receipt.get('verified') is True
                    and type(count) is int and count == plan['count']
                    and receipt.get('requested', plan['count']) == plan['count']
                    and isinstance(actual, (tuple, list)) and bool(actual)
                    and all(k == plan['kind'] for k in actual))
        state = 'executed' if complete else 'refused' if receipt.get('state') in ('refused', 'unavailable', 'failed') else 'uncertain'
        self._event(stats, now, state, plan, receipt={k: receipt.get(k) for k in
            ('state', 'verified', 'kind', 'kinds', 'requested', 'detonated', 'reason', 'self_damage')})
        field = 'crowd_roulette_'+state
        stats[field] = stats.get(field, 0)+1
        if complete and plan.get('coalesced'):
            stats['crowd_roulette_coalesced'] = stats.get('crowd_roulette_coalesced', 0)+1
        # A proven unsubmitted busy/refused request may retry after a bounded
        # delay. Never apply this to an allocated/partial/uncertain operation.
        unsubmitted = (receipt.get('native_not_submitted') is True
                       and receipt.get('state') in ('refused', 'failed', 'unavailable')
                       and not receipt.get('prepared') and not receipt.get('mines')
                       and not receipt.get('detonated') and not receipt.get('placed'))
        self.pending, self.next_at = None, now+(RETRY_S if unsubmitted else INTERVAL_S)
        # Receipt completion schedules exactly one follow-up demand. It does
        # not claim a mine exists, bypass automine, or command an escape input.
        if complete and plan.get('followup_mines') and now-plan['selected_at'] <= 10.:
            if self.title == RE6:
                stats['ring_flash_at'] = now
                stats['crowd_roulette_followup'] = 'confirmed flash; remote controller owns placement and safe escape'
            elif self.title == RE5:
                stats['crowd_roulette_mine_event'] = {'id': plan['id'], 'owner': plan['owner'], 'at': now,
                    'kind': 'roulette_flash', 'count': plan['followup_mines'],
                    'pos': list((snap.get('player') or {})['pos'])}
                stats['crowd_roulette_mine_status'] = 'requested'
