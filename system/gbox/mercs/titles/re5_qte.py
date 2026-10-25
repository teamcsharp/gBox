"""Scoped RE5 BLUS30491 01.01 native QTE accumulator assistance.

Modes 4 and 6 compare the selected display unit's +2C float with its +30
target. The evaluator's true return reaches 8CD694, which invokes the real
event callback. We change only that progress float; setting button success
bytes would bypass the callback and is deliberately not implemented.

Readback means progress was submitted, not that an event succeeded. Native
acceptance and a grabbed player's subsequent escape are separate observations.
External process writes cannot be made atomic with the game's update thread.
"""
from __future__ import annotations

import math
import struct
import time

MODES = {4: 'button accumulation', 6: 'stick wiggle'}
PROGRESS, TARGET = 0x2C, 0x30
OBSERVE_S = 3.0
SIGNATURES = {
    0x000AC414: bytes.fromhex('c19a0004c17a0008ff8c5800386000014fddf382419eff90386000005463063e'),
    0x000ACA88: bytes.fromhex('408200f03937002838600001c1a90008c0090004ff8068004fddf382409e011c'),
    0x000ACBA8: bytes.fromhex('c1a9000838600001c0090004ff8068004fddf382419efeec386000004bfffee4'),
    0x000B7EF4: bytes.fromhex('800b0028d3e700047c0007b4f8010080c9a10080fda06e9cfc006818ff9f0000d0070008419d0044'),
    0x000B7FD4: bytes.fromhex('80b8000879e400207fe3fb787ca507b44bff57d15463063e2f830000419efe0c83ff000c2f9f0000'),
    0x000B8048: bytes.fromhex('809800087fa3eb787c8407b44881564160000000'),
    0x008CD6E4: bytes.fromhex('813e8008380000017c9c07b49803000c9803000b7f84e37880690000'),
}


class Reject(ValueError):
    pass


def _u32(m, address):
    return struct.unpack('>I', m.rd(address, 4))[0]


def _heap(address, size=4):
    return type(address) is int and address % 4 == 0 and 0x30000000 <= address <= 0x40000000-size


def validate(m):
    from . import re5_ps3 as R
    for address, expected in (R.QTE_SIGNATURES | R.QTE_STICK_SIGNATURES | SIGNATURES).items():
        if m.rd(address, len(expected)) != expected:
            raise Reject('Native QTE code signatures do not match this build.')
    if m.rd(R.QTE_INPUT_TABLE, len(R.QTE_INPUT_SIGNATURE)) != R.QTE_INPUT_SIGNATURE:
        raise Reject('Native QTE input table does not match this build.')


def _descriptor(raw):
    # +68 is an opaque selection value, NOT a proven generation counter.
    # Keep callback/owner/target/argument identity without including native result bytes.
    return raw[:8] + raw[0x10:0x34] + raw[0x3C:0x5C] + raw[0x68:0x74]


def view(m, snapshot=None):
    """Fully validate one currently selected, reset-free accumulator request."""
    from . import re5_ps3 as R
    validate(m)
    if R.player_index(m) != 0 or not R.modifications_allowed(m):
        raise Reject('Native QTE assistance currently supports the solo first player.')
    request = R.selected_prompt(m)
    if not request or request['mode'] not in MODES:
        raise Reject('Waiting for a verified mode 4 or 6 QTE; other modes retain ordinary input.')
    sp, player, manager = _u32(m, R.S_PLAYER), R.player_pointer(m), _u32(m, R.S_ACTION)
    if not _heap(player, R.P_HP+4) or not _heap(manager, max(R.QTE_UNITS)+0x44):
        raise Reject('Current player or prompt manager is unavailable.')
    if snapshot is not None and (snapshot.get('player') or {}).get('ptr') != player:
        raise Reject('QTE player differs from the current bot snapshot.')
    hp = struct.unpack('>h', m.rd(player+R.P_HP, 2))[0]
    if hp <= 0:
        raise Reject('Terminal player cannot complete a live QTE.')
    button = request['button']
    if not _heap(button, 0x74):
        raise Reject('Invalid native button object.')
    raw = m.rd(button, 0x74)
    if raw[0x0B] or raw[0x0C] or raw[0x0D]:
        raise Reject('The request is accepted, consumed, or awaiting native reset.')
    target_int = struct.unpack_from('>i', raw, 0x28)[0]
    if not 0 < target_int <= 1_000_000:
        raise Reject('The event has no bounded positive accumulator target.')
    units = []
    for offset in R.QTE_UNITS:
        address = manager+offset
        unit = m.rd(address, 0x44)
        if unit[4] and unit[5] and struct.unpack_from('>I', unit, 0x0C)[0] == button:
            units.append((address, unit))
    if len(units) != 1:
        raise Reject('The selected QTE unit is missing or ambiguous.')
    address, unit = units[0]
    progress, target = struct.unpack_from('>2f', unit, PROGRESS)
    expected_target = struct.unpack('>f', struct.pack('>f', target_int))[0]
    if struct.unpack_from('>I', unit, 0x10)[0] != request['mode'] \
            or unit[0x34:0x38] != raw[0x68:0x6C] \
            or not math.isfinite(progress) or not 0 <= progress <= 1_000_000 \
            or not math.isfinite(target) or target != expected_target:
        raise Reject('Native mode/progress/target no longer matches the button definition.')
    identity = (sp, player, manager, address, button, request['mode'], _descriptor(raw),
                unit[0x0C:0x14], unit[0x18:0x1C], unit[TARGET:TARGET+4], unit[0x34:0x38])
    # Do not commit against a selection that changed during these reads.
    latest = m.rd(button, 0x74)
    if R.selected_prompt(m) != request or R.player_pointer(m) != player \
            or _u32(m, R.S_PLAYER) != sp or _u32(m, R.S_ACTION) != manager \
            or _descriptor(latest) != _descriptor(raw) or latest[0x0A:0x0E] != b'\1\0\0\0':
        raise Reject('The native QTE changed during observation.')
    return {'identity': identity, 'player': player, 'manager': manager, 'unit': address,
            'button': button, 'mode': request['mode'], 'descriptor': _descriptor(raw),
            'progress': progress, 'target': target, 'target_bytes': unit[TARGET:TARGET+4],
            'action': m.rd(player+R.P_ACTION, 1)[0]}


class ProgressHook:
    """One bounded write per observed selection, scoped to one process/controller.

    memory.wr must recheck its process/controller identity immediately before
    writing. A scope change refuses the old helper; create a new helper only
    when explicitly configuring the new owner. No old progress is restored.
    """

    def __init__(self, scope):
        self.scope, self.pending, self.last_identity = scope, None, None

    def _result(self, phase, reason, **values):
        pending = self.pending or {}
        return {'phase': phase, 'reason': reason, 'verified': False, 'native_accepted': False,
                'completed': False, 'writes': 0, 'mode': pending.get('mode'),
                'button': pending.get('button'), **values}

    def _observe(self, m, now):
        from . import re5_ps3 as R
        pending = self.pending
        try:
            player = R.player_pointer(m)
            if player != pending['player'] or _u32(m, R.S_ACTION) != pending['manager']:
                return self._result('ended_unconfirmed', 'Player or prompt manager changed; no success inferred.')
            raw = m.rd(pending['button'], 0x74)
            if _descriptor(raw) != pending['descriptor']:
                return self._result('ended_unconfirmed', 'Button definition changed; no success inferred.')
            if now-pending['at'] >= OBSERVE_S:
                return self._result('native_accepted' if pending.get('accepted') else 'timeout',
                                    'Bounded outcome observation ended; no later action is attributed to this event.',
                                    verified=bool(pending.get('accepted')),
                                    native_accepted=bool(pending.get('accepted')))
            accepted = raw[0x0B] == 1 and raw[0x0C] == 1
            pending['accepted'] = pending.get('accepted', False) or accepted
            hp = struct.unpack('>h', m.rd(player+R.P_HP, 2))[0]
            action = m.rd(player+R.P_ACTION, 1)[0]
            if pending.get('accepted') and pending['action'] == R.P_GRABBED and hp > 0 \
                    and action != R.P_GRABBED:
                return self._result('completed', 'Native acceptance and release from the grabbed action observed.',
                                    verified=True, native_accepted=True, completed=True)
            if pending.get('accepted'):
                return self._result('native_accepted', 'Native completion flags observed; event outcome is not yet confirmed.',
                                    verified=True, native_accepted=True)
            return self._result('pending', 'Progress submitted; waiting for the native evaluator and callback.')
        except (OSError, ValueError, struct.error, IndexError):
            return self._result('pending' if now-pending['at'] < OBSERVE_S else 'timeout',
                                'Native completion readback is unavailable; no success inferred.')

    def step(self, m, snapshot, now, *, scope, enabled=True):
        if not enabled:
            return self._result('disabled', 'Native QTE assistance is disabled.')
        if scope is None or scope != self.scope or not math.isfinite(now):
            return self._result('rejected', 'Process/controller scope changed; old event writes are forbidden.')
        observed = self._observe(m, now) if self.pending else None
        try:
            current = view(m, snapshot)
            if current['identity'] == self.last_identity:
                # Only an observed native accepted->active/reset transition
                # re-arms an identical request. Time alone never proves reuse.
                if not (self.pending and self.pending.get('accepted')
                        and current['progress'] < current['target']):
                    return observed or self._result('pending', 'This selection has already been handled.')
            if current['progress'] >= current['target']:
                return self._result('native_ready', 'Native progress already meets the event target; no write needed.',
                                    mode=current['mode'], button=current['button'])
            # Full second guard immediately before the four-byte data write.
            latest = view(m, snapshot)
            if latest['identity'] != current['identity'] or latest['progress'] < current['progress']:
                raise Reject('The event or accumulator reset before the write.')
            if latest['progress'] >= latest['target']:
                return self._result('native_ready', 'Native progress reached its target before the write.')
            self.last_identity = current['identity']
            self.pending = dict(latest, at=now, accepted=False)
            if not m.wr(latest['unit']+PROGRESS, latest['target_bytes']):
                return self._result('write_unconfirmed', 'Progress write readback failed; native outcome remains unknown.')
            native = self._observe(m, now)
            if native.get('native_accepted'):
                return dict(native, writes=1)
            after = m.rd(latest['unit'], 0x44)
            button = m.rd(latest['button'], 0x74)
            if after[PROGRESS:PROGRESS+4] != latest['target_bytes'] \
                    or after[0x0C:0x14] != latest['identity'][7] \
                    or after[0x18:0x1C] != latest['identity'][8] \
                    or after[0x34:0x38] != latest['identity'][10] \
                    or after[TARGET:TARGET+4] != latest['target_bytes'] \
                    or _descriptor(button) != latest['descriptor'] or button[0x0D]:
                return self._result('write_unconfirmed', 'Progress changed before readback; no success inferred.', writes=1)
            return self._result('submitted', 'Event progress read back at its target; native callback is still pending.',
                                writes=1, progress_verified=True, target=latest['target'])
        except (Reject, OSError, ValueError, struct.error, IndexError) as error:
            return observed or self._result('waiting', str(error))


def status(state):
    cfg = state.get('qte_assist') or {}
    return {'enabled': bool(cfg.get('enabled')), 'native_modes': sorted(MODES),
            'other_modes': 'ordinary input automation; native completion is not implemented',
            'phase': 'waiting' if cfg.get('enabled') else 'disabled',
            'verified': False, 'native_accepted': False, 'completed': False,
            **(cfg.get('last') or {})}


def capability(game):
    from .re5_live_weapon import adapter_identity
    try:
        validate(game)
        available = adapter_identity(game.ad, resolve_guest=True) is not None
        return {'available': available, 'native_modes': sorted(MODES),
                'reason': 'Native progress assistance for button accumulation and stick wiggle; '
                          'other decoded QTEs use ordinary input.' if available else 'No current emulator process.'}
    except (OSError, ValueError, struct.error):
        return {'available': False, 'native_modes': [], 'reason': 'Native QTE signatures are not verified.'}


def configure(game, on=True):
    from . import re5_controls as C
    from .re5_live_weapon import adapter_identity
    with C.LOCK:
        if on:
            validate(game)
            process = adapter_identity(game.ad, resolve_guest=True)
            if process is None:
                raise Reject('No verified current emulator process for native QTE assistance.')
            game.orig['qte_assist'] = {'enabled': True, 'process': process}
        else:
            cfg = game.orig.setdefault('qte_assist', {})
            cfg.update(enabled=False, last={'phase': 'disabled', 'reason': 'Native QTE assistance disabled.',
                                           'verified': False, 'native_accepted': False, 'completed': False})
            cfg.pop('helper', None)
        return {'verified': True, 'configured': bool(on), 'native_outcome_verified': False,
                'qte_assist': status(game.orig)}


def maintain(adapter, snapshot, *, owner, enabled=True):
    """Run from the bot's single existing owner, before its ordinary prompt input.

    The adapter owns all writes. Reads use that same adapter mapping instead of
    an old ProcMem handle, and the writer repeats process/guest/controller fences.
    """
    from ... import re5_mods_tool as mods
    from . import re5_controls as C
    from .re5_live_weapon import adapter_identity
    with mods._HEALTH_LOCK, C.LOCK:
        state = mods.ORIG.get(id(adapter), {})
        cfg = state.get('qte_assist') or {}
        if not cfg.get('enabled'):
            return status(state)
        if not enabled:
            cfg['last'] = {'phase': 'waiting', 'reason': 'No active gameplay owner.', 'verified': False,
                           'native_accepted': False, 'completed': False}
            return status(state)
        try:
            game = mods.RE5(adapter)
            process = adapter_identity(adapter, resolve_guest=True)
            controller = state.get('controller') or {}
            now = time.monotonic()
            if process is None or process != cfg.get('process'):
                raise Reject('Emulator process or guest mapping changed; reconfigure native QTE assistance.')
            if not controller.get('active') or controller.get('owner') != owner \
                    or not 0 <= now-controller.get('seen', -1e9) <= C.FRESH_S \
                    or controller.get('player') != (snapshot.get('player') or {}).get('ptr'):
                raise Reject('Waiting for the current solo bot owner and player.')
            scoped_player = controller['player']
            scope = (process, owner)
            helper = cfg.get('helper')
            if helper is None or helper.scope != scope:
                helper = cfg['helper'] = ProgressHook(scope)

            def owns_scope():
                current = state.get('controller') or {}
                return state.get('qte_assist') is cfg and cfg.get('enabled') \
                    and adapter_identity(adapter, resolve_guest=True) == process \
                    and current.get('active') and current.get('owner') == owner \
                    and current.get('player') == scoped_player \
                    and 0 <= time.monotonic()-current.get('seen', -1e9) <= C.FRESH_S

            class GuardedMemory:
                def rd(self, address, size):
                    return game.rd(address, size)

                def wr(self, address, data):
                    if not owns_scope():
                        return False
                    return game.wr(address, data)

            result = helper.step(GuardedMemory(), snapshot, now, scope=scope)
            if not owns_scope():
                result = {'phase': 'rejected', 'reason': 'Process/controller scope changed during QTE readback.',
                          'verified': False, 'native_accepted': False, 'completed': False,
                          'writes': result.get('writes', 0)}
        except (OSError, ValueError, struct.error, RuntimeError, mods.Unsupported) as error:
            result = {'phase': 'rejected', 'reason': str(error), 'verified': False,
                      'native_accepted': False, 'completed': False, 'writes': 0}
        cfg['last'] = result
        return status(state)
