"""Scoped solo Mercenaries resuscitation through native progress.

The independently audited 864158..8645D0 path subtracts native timestep *
player scale from +1CEC, then requires progress strictly above parameter+3D0.
It clears progress and invokes the player's recovery notification itself.
Only the progress float is changed here. HP, callback pointers and completion
flags are never written. The legacy recovery candidate supplies read-only
field validation; its driver and its unproven 'generation' interpretation are
not used. External process writes are not atomic with the native game thread;
fresh fences and readback bound that race. Live acceptance remains outstanding.
"""
from __future__ import annotations

import math
import struct

from . import re5_recovery as F

TIMEOUT_S = 3.0
HP_CALLBACK_ENTRY, HP_CALLBACK_TOC = 0x0086017C, 0x0171C590
CALLBACK_SIGNATURES = {
    0x0086017C: bytes.fromhex('7c8707347c6a1b782f8700007c681b78396314a0409e0060'),
    0x008601F0: bytes.fromhex('396a14a0a00a14a47d4853787c060734b08b0004409cffa838000000b00b00044bffff9c'),
    0x0085F4B0: bytes.fromhex('83be815c380000007b760020981c1d0b813d0000'),
}


class Reject(ValueError):
    pass


def _u32(m, address):
    return struct.unpack('>I', m.rd(address, 4))[0]


def _f32(m, address):
    return struct.unpack('>f', m.rd(address, 4))[0]


def _heap(address, size=4):
    return type(address) is int and address % 4 == 0 and 0x30000000 <= address <= 0x40000000-size


def _descriptor(raw):
    # +68 is retained as opaque event data, not claimed as a generation.
    return raw[:8] + raw[0x10:0x5C] + raw[0x68:0x74]


def validate(m):
    for address, expected in (F.SIGNATURES | CALLBACK_SIGNATURES).items():
        if m.rd(address, len(expected)) != expected:
            raise Reject('Native solo recovery signatures do not match this build.')


def callback_identity(m, player):
    """The current player's native HP setter, including its PowerPC OPD context."""
    for address, expected in CALLBACK_SIGNATURES.items():
        if m.rd(address, len(expected)) != expected:
            raise Reject('Native recovery HP callback code is not verified.')
    vtable = _u32(m, player)
    if vtable % 4 or not 0x01000000 <= vtable <= 0x02000000-0x12C:
        raise Reject('Current player has no verified native callback table.')
    opd = _u32(m, vtable+0x128)
    if opd % 4 or not 0x01000000 <= opd <= 0x02000000-8:
        raise Reject('Recovery callback descriptor is outside the static data range.')
    entry, toc = struct.unpack('>2I', m.rd(opd, 8))
    if (entry, toc) != (HP_CALLBACK_ENTRY, HP_CALLBACK_TOC):
        raise Reject('Current player overrides the verified recovery HP callback.')
    return vtable, opd, entry, toc


def clock_scope(m):
    """Verified current Mercenaries owner and clocks; no campaign-round guess."""
    from ... import re5_mods_tool as M
    from . import re5_ps3 as R
    if R.player_index(m) != 0 or not R.modifications_allowed(m):
        raise Reject('Solo first-player scope is required.')
    sp, player, main = _u32(m, F.S_PLAYER), R.player_pointer(m), _u32(m, F.S_MAIN)
    if not _heap(sp, F.SPLAYER_FLAGS+4) or not _heap(player, F.P_MODE+4) \
            or not _heap(main, F.MAIN_FLAGS+4):
        raise Reject('Current player or game owner is unavailable.')
    gs, area = _u32(m, main+F.MAIN_GAMESYS), _u32(m, M.S_AREA)
    if not _heap(gs, M.GS_BONUS_TOTAL+4) or not _heap(area, M.AREA_GAME+4) \
            or _u32(m, area) != M.AREA_VT:
        raise Reject('Verified Mercenaries clock owner is unavailable.')
    game = _u32(m, area+M.AREA_GAME)
    if not _heap(game, M.GAME_CLOCK+4) or _u32(m, game) != M.GAME_VT \
            or _u32(m, game+M.GAME_CLOCK_STATE) != 0:
        raise Reject('The native round clock is not active.')
    mode, phase = _u32(m, gs+F.GAMESYS_MODE), _u32(m, gs+R.GS_PHASE)
    if mode not in (2, 5) or phase not in (0, 1, 2) or _u32(m, gs+0x340) == 2:
        raise Reject('Only a current solo Mercenaries/Reunion round is supported.')
    clock, hud, initial = _f32(m, game+M.GAME_CLOCK), _f32(m, gs+R.GS_TIMER), m.rd(gs+R.GS_START, 4)
    start = struct.unpack('>f', initial)[0]
    if not all(math.isfinite(value) and 0 < value < 86400 for value in (clock, hud, start)) \
            or abs(clock-hud) > 2.:
        raise Reject('Current owner/HUD/start clocks are invalid or inconsistent.')
    stage, character = _u32(m, gs+0x348), _u32(m, gs+0x364)
    kills, score = _u32(m, gs+R.GS_KILLS), _u32(m, gs+R.GS_SCORE)
    if stage >= 8 or character >= 64 or kills > 10000 or score > 100000000:
        raise Reject('Current round identity/counters are invalid.')
    callback = callback_identity(m, player)
    identity = (sp, player, main, gs, area, game, mode, phase, initial, stage, character, callback)
    if _u32(m, F.S_PLAYER) != sp or R.player_pointer(m) != player or _u32(m, F.S_MAIN) != main \
            or _u32(m, main+F.MAIN_GAMESYS) != gs or _u32(m, M.S_AREA) != area \
            or _u32(m, area+M.AREA_GAME) != game:
        raise Reject('Round owner changed during clock observation.')
    return {'identity': identity, 'player': player, 'clock': clock, 'kills': kills, 'score': score}


def _continuous(before, after):
    # Bonuses or a clock reset make attribution uncertain. Decline instead of
    # treating a new round or rewind as the old event's successful recovery.
    return before['identity'] == after['identity'] and 0 < after['clock'] <= before['clock']+.05 \
        and after['kills'] >= before['kills'] and after['score'] >= before['score']


def view(m, snapshot):
    from . import re5_ps3 as R
    current = clock_scope(m)
    if not isinstance(snapshot, dict) or (snapshot.get('player') or {}).get('ptr') != current['player']:
        raise Reject('Recovery player differs from the current bot snapshot.')
    try:
        native = F._snapshot(m)  # pure reads; every guard from the native threshold branch
    except F.Reject as error:
        raise Reject(str(error)) from error
    raw = m.rd(native['btn'], 0x74)
    if raw[:0x70] != native['raw'] or raw[F.BUTTON_ACTIVE] != 1 or raw[F.BUTTON_CONSUMED] \
            or raw[0x0D] or struct.unpack_from('>I', raw, 0x70)[0] & 1:
        raise Reject('The owned recovery request is changing, consumed, or resetting.')
    parameter, timestep, profile = (_u32(m, address) for address in (F.S_PARAMETER, F.S_TIMESTEP, F.S_PROFILE))
    scale = m.rd(native['pl']+F.P_SCALE, 4)
    controller = _u32(m, native['pl']+F.P_CONTROLLER)
    identity = (native['sp'], native['pl'], native['btn'], _descriptor(raw),
                parameter, timestep, profile, scale, controller, native['threshold'], native['increment'])
    later = clock_scope(m)
    if not _continuous(current, later) or native['pl'] != current['player'] \
            or R.player_pointer(m) != native['pl'] or _u32(m, native['pl']+F.P_BUTTON) != native['btn']:
        raise Reject('Recovery event/round scope changed during observation.')
    return {'identity': identity, 'clock_scope': later, 'player': native['pl'], 'button': native['btn'],
            'descriptor': _descriptor(raw), 'progress': native['progress'], 'threshold': native['threshold'],
            'decay': native['decay'], 'increment': native['increment']}


def target_for(state):
    """Strict native comparison after decay, plus the audited three-step margin."""
    target = struct.unpack('>f', struct.pack('>f', state['threshold']+state['decay']*(1+F.MARGIN_STEPS)))[0]
    if not math.isfinite(target) or target-state['threshold'] <= state['decay'] \
            or target-state['threshold'] > F.MAX_PROGRESS_SPAN:
        raise Reject('No bounded positive native recovery margin can be represented.')
    return struct.pack('>f', target)


def event_fence(m, state):
    """Short final current-event guard after the longer native/round validation."""
    from . import re5_ps3 as R
    player, button = state['player'], state['button']
    if callback_identity(m, player) != state['clock_scope']['identity'][-1]:
        raise Reject('Current player recovery callback changed at the write boundary.')
    if R.player_pointer(m) != player or _u32(m, player+F.P_BUTTON) != button:
        raise Reject('Current player/recovery request changed at the write boundary.')
    raw = m.rd(button, 0x74)
    if _descriptor(raw) != state['descriptor'] or raw[F.BUTTON_ACTIVE] != 1 \
            or raw[F.BUTTON_CONSUMED] or raw[0x0D]:
        raise Reject('Recovery request reset or ended at the write boundary.')
    progress = _f32(m, player+F.P_PROGRESS)
    if struct.unpack('>h', m.rd(player+F.P_HP, 2))[0] != 1 \
            or m.rd(player+F.P_RECOVER_FLAG, 1) != b'\0' or not math.isfinite(progress) or progress <= 0:
        raise Reject('Native DYING state ended at the write boundary.')
    return progress


def write_fence(m, state):
    """Repeat every native authorization gate at the adapter write boundary."""
    latest = view(m, {'player': {'ptr': state['player']}})
    if latest['identity'] != state['identity'] or not _continuous(state['clock_scope'], latest['clock_scope']):
        raise Reject('Native recovery parameters, controller, profile, or round changed before the write.')
    proposed = struct.unpack('>f', state['target'])[0]
    required = struct.unpack('>f', target_for(latest))[0]
    if not math.isfinite(proposed) or proposed < required:
        raise Reject('The prepared recovery value no longer covers the native decay margin.')
    return event_fence(m, latest)


class SoloRecovery:
    """One attempt per instance, including uncertain writes and timeouts.

    scope identifies the current process/guest/controller. scope_valid must
    freshly verify it before mutation and again before publishing an outcome;
    an adapter writer must repeat that same check at its actual write boundary.
    The caller may create another instance only after observing a new recovery
    event following healthy gameplay, or a new verified round/controller.
    """

    def __init__(self, scope):
        self.scope, self.pending, self.result = scope, None, None

    @staticmethod
    def _result(phase, reason, **values):
        return {'phase': phase, 'reason': reason, 'verified': False, 'completed': False,
                'native_recovered': False, 'writes': 0, **values}

    def _observe(self, m, now):
        pending = self.pending
        # No late HP value, reset, or replacement player can turn timeout into success.
        if not 0 <= now-pending['at'] < TIMEOUT_S:
            return self._result('timeout', 'Recovery outcome was not confirmed within the bounded window.')
        current = clock_scope(m)
        if not _continuous(pending['clock_scope'], current):
            return self._result('rejected', 'Round identity, native clock, or counters changed; no recovery inferred.')
        player = pending['player']
        health = m.rd(player+F.P_HP, 4)
        hp, maximum = struct.unpack('>hh', health)
        progress, flag = _f32(m, player+F.P_PROGRESS), m.rd(player+F.P_RECOVER_FLAG, 1)[0]
        button = _u32(m, player+F.P_BUTTON)
        ended = button == 0
        if button == pending['button']:
            raw = m.rd(button, 0x74)
            if _descriptor(raw) != pending['descriptor']:
                return self._result('rejected', 'Recovery button identity changed; no success inferred.')
            ended = not raw[F.BUTTON_ACTIVE] or bool(raw[F.BUTTON_CONSUMED])
        elif button:
            return self._result('rejected', 'A different recovery request replaced the owned event.')
        later = clock_scope(m)
        if not _continuous(current, later):
            return self._result('rejected', 'Round scope changed during recovery outcome reads.')
        if _u32(m, player+F.P_BUTTON) != button or m.rd(player+F.P_HP, 4) != health \
                or _f32(m, player+F.P_PROGRESS) != progress or m.rd(player+F.P_RECOVER_FLAG, 1)[0] != flag:
            return self._result('pending', 'Native recovery state changed during readback; waiting for a stable witness.')
        if button and m.rd(button, 0x74) != raw:
            return self._result('pending', 'Native request changed during readback; no completed outcome inferred.')
        # 8643B4..BC stores zero to +1D0B. It is a consistency guard,
        # not a positive recovery flag or an independently observed transition.
        if 1 < hp <= maximum <= 32767 and progress == 0. and flag == 0 and ended:
            return self._result('completed', 'Cleared recovery progress, HP increase, and owned request end observed.',
                                verified=True, completed=True, native_recovered=True)
        if hp <= 0:
            return self._result('failed', 'Player reached terminal HP before native recovery was confirmed.')
        return self._result('pending', 'Waiting for the native recovery transition; HP alone is not sufficient.')

    def step(self, m, snapshot, now, *, scope, scope_valid, enabled=True):
        if not enabled:
            return self._result('disabled', 'Solo recovery assistance is disabled; no countdown is restored.')
        try:
            if scope is None or scope != self.scope or not math.isfinite(now) \
                    or not callable(scope_valid) or not scope_valid():
                raise Reject('Process/guest/controller scope is unavailable or changed.')
            if self.result is not None:
                if self.result.get('completed'):
                    return self._result('historical', 'This one-shot event already ended; caller must observe a new event to rearm.',
                                        last_outcome=dict(self.result, writes=0))
                return dict(self.result, writes=0)
            if self.pending is not None:
                result = self._observe(m, now)
            else:
                first = view(m, snapshot)
                latest = view(m, snapshot)
                if first['identity'] != latest['identity'] \
                        or not _continuous(first['clock_scope'], latest['clock_scope']):
                    raise Reject('Recovery event changed before the progress write.')
                if latest['progress'] > latest['threshold']:
                    return self._result('native_ready', 'Progress is already above threshold; waiting for the native update.')
                target = target_for(latest)
                if event_fence(m, latest) > latest['threshold']:
                    return self._result('native_ready', 'Native progress crossed the threshold before the write.')
                if not scope_valid():
                    raise Reject('Owner scope changed at the progress write boundary.')
                self.pending = dict(latest, at=now, target=target)
                written = m.wr(latest['player']+F.P_PROGRESS, target)
                result = self._observe(m, now)
                if result['phase'] == 'pending':
                    readback = m.rd(latest['player']+F.P_PROGRESS, 4)
                    result = self._result('submitted' if written and readback == target else 'write_unconfirmed',
                        'Native progress submitted; recovery has not yet been observed.' if written and readback == target
                        else 'Recovery progress write was not confirmed; native outcome remains unknown.',
                        progress_verified=bool(written and readback == target), writes=int(bool(written)))
                else:
                    result = dict(result, writes=int(bool(written)))
            if not scope_valid():
                raise Reject('Owner scope changed during recovery readback; no verified result published.')
            if result['phase'] in ('completed', 'failed', 'timeout', 'rejected'):
                self.result = dict(result, writes=0)
            return result
        except (Reject, F.Reject, OSError, ValueError, struct.error, IndexError) as error:
            result = self._result('rejected', str(error))
            if self.pending is not None:
                self.result = result  # never retry a write whose ownership/outcome became uncertain
            return result


class Controller:
    """Rearm only after verified healthy gameplay or a different native round.

    A controller handoff or toggling assistance is not a new event. An uncertain
    attempt stays blocked through those changes. Historical outcomes are kept
    separately and never promoted to the next event's current result.
    """

    def __init__(self, scope):
        self.scope, self.round_key, self.helper = scope, None, None
        self.attempted = False
        self.history, self.last = None, None

    def _result(self, phase, reason, *, current=False, **values):
        return {'phase': phase, 'reason': reason, 'current': current, 'kind': 'solo_recovery',
                'mode': 5, 'key_index': 25, 'verified': False, 'native_accepted': False,
                'native_recovered': False, 'completed': False, 'writes': 0, **values}

    def status(self):
        return {**(self.last or self._result('waiting', 'Waiting for a verified solo recovery event.')),
                'last_outcome': dict(self.history) if self.history else None}

    def invalidate(self, reason):
        if self.last and (self.last.get('completed') or self.last.get('verified')):
            self.history = dict(self.last, current=False, writes=0)
        self.last = self._result('rejected', reason)

    def rebind(self, scope):
        if scope != self.scope:
            if self.helper and self.helper.pending:
                self.attempted = True
                self.history = self._result('rejected', 'Controller changed after a recovery attempt; outcome unconfirmed.')
            self.scope, self.helper = scope, None
            self.last = self._result('waiting', 'New controller must observe healthy gameplay or a new native round.')

    @staticmethod
    def _round_key(clock):
        identity = clock['identity']
        # Only native game/area owners establish a new round here. A phase,
        # roster/callback change or player metadata update alone cannot rearm.
        return identity[2:6]

    @staticmethod
    def _healthy(m, clock):
        player = clock['player']
        health = m.rd(player+F.P_HP, 4)
        hp, maximum = struct.unpack('>hh', health)
        if not 1 < hp <= maximum <= 32767 or _f32(m, player+F.P_PROGRESS) != 0. \
                or m.rd(player+F.P_RECOVER_FLAG, 1) != b'\0':
            return False
        button = _u32(m, player+F.P_BUTTON)
        raw = None
        if button:
            if not _heap(button, 0x74): return False
            raw = m.rd(button, 0x74)
            if struct.unpack_from('>2I', raw) != (F.BUTTON_VT, player) \
                    or raw[F.BUTTON_ACTIVE] and not raw[F.BUTTON_CONSUMED]:
                return False
        later = clock_scope(m)
        return _continuous(clock, later) and m.rd(player+F.P_HP, 4) == health \
            and _f32(m, player+F.P_PROGRESS) == 0. and m.rd(player+F.P_RECOVER_FLAG, 1) == b'\0' \
            and _u32(m, player+F.P_BUTTON) == button and (not button or m.rd(button, 0x74) == raw)

    def step(self, m, snapshot, now, *, scope, scope_valid):
        from . import re5_ps3 as R
        current = False
        try:
            self.rebind(scope)
            if scope is None or not math.isfinite(now) or not scope_valid():
                raise Reject('Current process/controller scope is unavailable.')
            player = R.player_pointer(m)
            if not _heap(player, F.P_HP+4) or player != (snapshot.get('player') or {}).get('ptr'):
                raise Reject('Current recovery player differs from the bot snapshot.')
            hp = struct.unpack('>h', m.rd(player+F.P_HP, 2))[0]
            current = hp == 1 or self.helper is not None
            if not current and not self.attempted:
                self.last = self._result('ready', 'No current solo recovery event.')
                return None
            clock = clock_scope(m)
            key = self._round_key(clock)
            if self.round_key is not None and key != self.round_key:
                if self.helper:
                    self.history = self._result('ended_unconfirmed', 'Prior recovery event ended with a different native round.')
                self.helper, self.attempted = None, False
            self.round_key = key
            # Observe a submitted attempt before recognizing healthy gameplay,
            # so the final native transition is not silently discarded.
            result = self.helper.step(m, snapshot, now, scope=scope, scope_valid=scope_valid) if self.helper else None
            if self._healthy(m, clock):
                if result:
                    self.history = dict(result, current=False, writes=0)
                self.helper, self.attempted = None, False
                self.last = {**self._result('ready', 'Healthy gameplay observed; the next recovery event may rearm.'),
                             **(result if result and result.get('completed') else {})}
                if not scope_valid(): raise Reject('Controller changed during healthy-state readback.')
                return dict(self.last, current=True, kind='solo_recovery', mode=5, key_index=25) \
                    if result and result.get('completed') else None
            if hp != 1:
                if result and result.get('phase') in ('failed', 'timeout', 'rejected'):
                    self.last = {**self._result('waiting', 'Recovery event ended.', current=True), **result}
                    return self.last
                self.last = self._result('waiting', 'Waiting for healthy gameplay or a verified new recovery event.')
                return None
            if self.helper is None:
                if self.attempted:
                    self.last = self._result('blocked', 'This event already had an uncertain attempt; awaiting healthy gameplay or a new native round.', current=True)
                    return self.last
                self.helper = SoloRecovery(scope)
                result = self.helper.step(m, snapshot, now, scope=scope, scope_valid=scope_valid)
            self.attempted = self.attempted or self.helper.pending is not None
            self.last = {**self._result('waiting', 'Waiting for the native recovery transition.', current=True), **(result or {})}
            if not scope_valid(): raise Reject('Controller changed during recovery readback.')
            if self.helper.pending is None and not self.attempted and self.last.get('phase') == 'rejected':
                # HP1 alone does not own a recovery request. Preserve ordinary
                # accumulator QTE handling when no recovery write was attempted.
                self.last['current'] = False
                return None
            return self.last
        except (Reject, F.Reject, OSError, ValueError, struct.error, IndexError) as error:
            owns_attempt = self.attempted or self.helper is not None and self.helper.pending is not None
            self.last = self._result('rejected', str(error), current=bool(current and owns_attempt))
            return self.last if current and owns_attempt else None
