"""Measured assistance and participant provenance, separate from observed scores.

An enabled training aid is sticky for the entire round. Turning it off at the
results screen cannot turn an assisted score into an unmodified qualification.
Missing readback or old recordings never constitute proof of original rules.
"""
from __future__ import annotations

from copy import deepcopy
import math


class RoundAssistance:
    def __init__(self):
        self.effects = set()
        self.samples = 0
        self.unknown = False

    def observe(self, evidence):
        self.samples += 1
        if not isinstance(evidence, dict):
            self.unknown = True
            return self.summary()
        for effect in evidence.get('effects', ()):
            if isinstance(effect, str) and effect:
                self.effects.add(effect[:100])
        if evidence.get('verified') is not True or evidence.get('classification') not in ('unmodified', 'mod_assisted'):
            self.unknown = True
        if evidence.get('classification') == 'mod_assisted' and not self.effects:
            self.effects.add('unspecified_gameplay_assistance')
        return self.summary()

    def summary(self):
        classification = ('mod_assisted' if self.effects else
                          'unmodified' if self.samples and not self.unknown else 'unknown')
        return {'classification': classification, 'verified': bool(self.samples and not self.unknown),
                'effects': sorted(self.effects), 'samples': self.samples}


def re5_assistance(adapter):
    """Read current known aids without writes or a guessed pristine baseline.

    A full original-rules verifier is still required to certify clean play. This
    observer positively identifies active modifications; absence of these flags
    alone is insufficient, including after a worker restart or manual RAM edits.
    """
    from .. import re5_mods_tool as M
    from .titles import re5_mines
    effects = []
    try:
        game = M.RE5(adapter)
        original = game.orig
        if original.get('health', {}).get('on'):
            effects.append('health_protection')
        if original.get('kill_time', {}).get('on'):
            effects.append('extra_time_per_kill')
        if original.get('fire_animation_on'):
            effects.append('fire_animation_speed')
        if original.get('rotten_eggs', {}).get('on'):
            effects.append('infinite_rotten_eggs')
        if re5_mines.settings()['enabled']:
            effects.append('infinite_mine_training')
        fps = game.f32(M.FIRE_TIMER_FPS)
        if not math.isfinite(fps) or abs(fps-M.FIRE_TIMER_ORIG) > .01:
            effects.append('fire_rate')
        damage = game.f32(M.UPG_TABLE+0x02*M.UPG_STRIDE+M.UPG_GROUP0+M.G_DAMAGE*M.UPG_GROUP+4)
        if not math.isfinite(damage) or abs(damage-150.) > .01:
            effects.append('bullet_damage')
        # The Gatling's native infinite ammunition is part of its normal loadout.
        flags = [game.u32(M.DEF_TABLE+w*M.DEF_STRIDE+M.DEF_NOAMMO)
                 for w in (0x02, 0x03, 0x0A, 0x0B, 0x0F)]
        if any(flag == 1 for flag in flags[:4]):
            effects.append('infinite_ammunition')
        param = game.param()
        for offset, (_, value) in M.TURN.items():
            observed = game.f32(param+offset)
            if not math.isfinite(observed) or abs(observed-value) > max(.001, abs(value)*.001):
                effects.append('turn_speed')
                break
        # Original tables/presets can outlive an enabled switch. Do not certify
        # their restoration from a convenient sample of one weapon's fields.
        return {'classification': 'mod_assisted' if effects else 'unknown', 'verified': False,
                'effects': sorted(set(effects)), 'source': 'native_readback_and_worker_mod_state',
                'reason': 'Original rules, all loadouts and prior round writes have not been fully verified.'}
    except Exception as error:
        return {'classification': 'unknown', 'verified': False, 'effects': sorted(set(effects)),
                'source': 'native_readback_unavailable', 'reason': type(error).__name__}


def participant(player, slot, control, *, source):
    """A title-verified actor plus an explicit control assignment, never identity by proximity."""
    if not isinstance(player, dict) or type(slot) is not int or slot not in (1, 2):
        return None
    actor, pos = player.get('ptr'), player.get('pos')
    if type(actor) is not int or not 0x30000000 <= actor < 0x40000000 \
            or not isinstance(pos, (tuple, list)) or len(pos) != 3 \
            or not all(type(v) in (int, float) and math.isfinite(v) for v in pos):
        return None
    if control not in ('human', 'bot', 'unknown'):
        control = 'unknown'
    return {'id': f'p{slot}', 'slot': slot, 'control': control, 'actor': actor, 'pos': list(pos),
            'hp': player.get('hp'), 'hp_max': player.get('hp_max'),
            'provenance': {'source': source, 'native_actor_verified': True,
                           'control_source': 'operator_assignment_and_bot_input_fence',
                           'inputs_observed': False}}


class HumanObserver:
    """A neutral engine participant: no combat policy, prompt presses or memory maintenance."""
    def __init__(self, stats):
        self.stats = stats
        self.marker = None

    def observe_round(self, snap, where, now):
        mode, index = snap.get('mercenaries_mode'), snap.get('character_index')
        if mode:
            self.stats['mercenaries_mode'] = mode
        if mode and type(index) is int:
            from .titles.re5_ps3 import MODE_ROSTERS
            roster = MODE_ROSTERS.get(mode, ())
            if 0 <= index < len(roster):
                self.stats['character'] = roster[index]
        current = ((snap.get('player') or {}).get('ptr'), snap.get('kills'))
        if where == 'playing' and (self.marker is None or current[0] != self.marker[0]
                or type(current[1]) is int and type(self.marker[1]) is int and current[1] < self.marker[1]):
            self.stats['_round_started'] = now
            self._round_started = now
        if where == 'playing':
            self.marker = current

    def tick(self, snap):
        return {'hold': set()}

    def prompt_ok(self, *args):
        return False

    def plan(self):
        return {'phase': 'human_demonstration', 'note': 'Human controls Player 1; bot input disabled.'}

    def save(self):
        pass


def round_fields(stats, assistance):
    summary = assistance.summary()
    stats['assistance_classification'] = summary['classification']
    stats['assistance_verified'] = summary['verified']
    stats['assistance_effects'] = ','.join(summary['effects'])
    stats['assistance'] = deepcopy(summary)
    return summary
