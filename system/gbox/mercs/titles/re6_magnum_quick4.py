"""One bounded RE6 magnum quick-shot sequence, verified from native actions.

No arbitrary count, weapon creation, input loop, or retry. The caller owns the
persistent UUID and bot-input handover. Each new press requires the preceding
quick-shot action to have been observed and left; lost evidence stops the run.
"""
from __future__ import annotations

import struct
import time

from . import re6_switch as R, re6_switch_equip as E, re6_switch_native as N

OP = 'magnum_quick4'
MAGNUMS = {0x107: 'Lightning Hawk', 0x108: 'Elephant Killer'}
QUICK = 'cPlAction_pl_act_weapon_comn_quick_shot'
KEYS = ('zl', 'zr')


def loaded(ctl, player):
    raw = ctl.rd(player + R.P_SLOTS, R.SLOT_STRIDE * R.N_SLOTS)
    choices = []
    for off in range(0, len(raw), R.SLOT_STRIDE):
        kind = struct.unpack_from('<H', raw, off + 0xA)[0]
        if raw[off + 8] and raw[off + 9] < R.WEAPON_INDEXES and kind in MAGNUMS:
            rounds = struct.unpack_from('<h', raw, off + 0xE)[0]
            if rounds >= 4:
                choices.append((kind, raw[off + 9]))
    return choices


def available(ctl):
    # RE5 inherits the flash transport, not RE6's mechanics or memory layout.
    if type(ctl) is not N.Controller:
        return False
    ad = ctl.ad
    if (not callable(getattr(ad, 'send_input', None)) or
            getattr(ad, 'mercs_no_modifications', False) or getattr(ad, 'mercs_coop', False) or
            getattr(ad, 'mercs_player_index', 0) != 0 or getattr(ad, 'coop_players', 1) > 1):
        return False
    player, _ = ctl.ready()
    return bool(loaded(ctl, player))


def sequence(read, send, *, clock=time.monotonic, sleep=time.sleep):
    """At most four input edges; confirm game actions, never count key presses.

    read() must enforce the exact player/round and selected native hand before
    returning the action class. It may raise to cancel at any point.
    """
    started, completed, presses = clock(), 0, 0
    down = False
    result = {'op': OP, 'requested': 4, 'completed': 0, 'presses': 0, 'verified': False}

    def wait_for(predicate, seconds, reason):
        deadline = min(started + 7.0, clock() + seconds)
        while True:
            action = read()
            if predicate(action):
                return action
            if clock() >= deadline:
                raise N.Uncertain(reason)
            sleep(.002)

    def release():
        nonlocal down
        # Releasing is idempotent cleanup, never another attack. If the first
        # release fails, finally gets one more chance to leave no trigger held.
        send([{'key': key, 'down': False} for key in KEYS])
        down = False

    try:
        for _ in range(4):
            wait_for(lambda a: a in E.FREE_ACTIONS, 1.0, 'player did not become ready')
            # A fresh read immediately before each edge preserves the caller's
            # player/round fence even after the idle wait returned.
            if read() not in E.FREE_ACTIONS:
                raise N.Unavailable('player action changed before quick shot')
            presses += 1
            down = True
            send([{'key': key, 'down': True} for key in KEYS])
            # No repeated tap when a press is ignored or its acknowledgement is
            # lost. A short bounded hold prevents a stalled game holding fire.
            wait_for(lambda a: a == QUICK, .12, 'quick-shot start was not observed; not replayed')
            release()
            action = wait_for(lambda a: a != QUICK, 1.5, 'quick-shot completion was not observed')
            if action not in E.FREE_ACTIONS:
                raise N.Uncertain('quick shot was interrupted; remaining shots cancelled')
            completed += 1
            # Let at least two game frames see the released triggers. This is
            # outside the attack: it cannot auto-repeat a shot.
            sleep(.04)
        read()  # a late session/player change must not produce success
        result.update(state='confirmed', verified=True, effect='native_magnum_quick_shot_actions')
    except (OSError, ValueError, RuntimeError, struct.error) as exc:
        result.update(state='uncertain' if presses else 'failed', reason=str(exc)[:300])
    finally:
        if down:
            try:
                release()
            except (OSError, ValueError, RuntimeError) as exc:
                result.update(state='uncertain', verified=False, reason='trigger release unconfirmed: ' + str(exc)[:220])
        result.update(completed=completed, presses=presses,
                      elapsed_ms=round((clock() - started) * 1000, 1))
    return result


def execute(ctl, *, expected, allowed, clock=time.monotonic, sleep=time.sleep):
    """Equip one loaded magnum once, then run the acknowledged four-shot action."""
    if not available(ctl):
        raise N.Unavailable('four magnum quick shots require supported RE6 and a loaded magnum with four rounds')
    with ctl.lock:
        player, generation = expected

        def guard():
            if not allowed() or ctl.ready() != expected:
                raise N.Unavailable('player, round, input owner, or request deadline changed')
            if ctl.rd(ctl.base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
                raise N.Unavailable('RE6 executable changed')

        guard()
        choices = loaded(ctl, player)
        if not choices:
            raise N.Unavailable('loaded magnum changed before execution')
        equipped = R.equipped_id(ctl, player)
        kind, index = next((x for x in choices if (x[0] & 255) == equipped), choices[0])
        from .re6_switch_weapon_native import select
        equipment = select(ctl, kind & 255, expected=expected, allowed=allowed, clock=clock, sleep=sleep)
        hand, born = equipment['object'], equipment['weapon_generation']

        def read():
            guard()
            if (ctl.q(player + E.ACTIVE_OBJECT) != hand or ctl.w(player + E.ACTIVE_INDEX) != index or
                    ctl.w(hand + E.GENERATION) != born or ctl.q(hand + E.OWNER) != player or
                    struct.unpack('<H', ctl.rd(hand + E.HIDDEN, 2))[0] & 1):
                raise N.Unavailable('the selected native magnum hand changed')
            action = R.unit_action(ctl, player)
            if action is None:
                raise N.Uncertain('native quick-shot action is unreadable')
            return action

        def send(rows):
            # Releases are cleanup even after cancellation. New key-downs must
            # still belong to the exact claimed player/round/input owner.
            if any(row['down'] for row in rows):
                guard()
            answer = ctl.ad.send_input(rows)
            if isinstance(answer, dict) and answer.get('skipped'):
                raise N.Uncertain('Switch trigger input was not accepted')

        receipt = sequence(read, send, clock=clock, sleep=sleep)
        return receipt | {'item': kind & 255, 'weapon': MAGNUMS[kind],
                          'player': player, 'player_generation': generation}