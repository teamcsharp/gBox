"""Guarded 3OE2 co-op globals and native elapsed-time measurement."""
import math
import struct
import time

from .pso_gc_live import PHASE, FLOOR, GC, dispatcher_lock
from .registry import Unsupported

# PsoV3.dol SHA256 1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a.
# r13 is 0x805DA600. TLevelSelect update stores its selected index at r13-0x50B0;
# runtime enemy and quest routines read the same global (see docs/pso-coop-campaign).
DIFFICULTY = 0x805D5550
GUARDS = {
    0x801330C4: bytes.fromhex("906daf50"),  # selected difficulty -> global
    0x801F44D4: bytes.fromhex("80adaf502c0500004180000c2c050004"),  # quest difficulty range 0..3
    0x800ACA34: bytes.fromhex("800daf502c00000340820014"),  # enemy Ultimate branch
    0x8001E5C8: bytes.fromhex("806dba604e800020"),  # known episode/SDA identity
}


def context(ad):
    read = ad.read_memory
    if read(0x80000000, 8) != b"GPOE8P\0\x02":
        raise Unsupported("PSO co-op globals require Plus US revision 2")
    for address, expected in GUARDS.items():
        if read(address, len(expected)) != expected:
            raise Unsupported(f"PSO difficulty reader code fingerprint differs at {address:#x}")
    if struct.unpack(">I", read(PHASE, 4))[0] != 14:
        return {"difficulty_verified": False}
    before = read(DIFFICULTY, 4)
    difficulty = struct.unpack(">I", before)[0]
    if difficulty not in range(4):
        raise Unsupported("PSO native difficulty is outside 0..3")
    if read(DIFFICULTY, 4) != before or struct.unpack(">I", read(PHASE, 4))[0] != 14:
        return {"difficulty_verified": False}
    return {"difficulty": difficulty, "difficulty_verified": True,
            "difficulty_source": "3OE2 native global 0x805D5550"}


# Owned DOL: mftb r3,0x10c; blr. The function itself only reads the CPU clock.
# Dolphin SystemTimers: GC core clock 486 MHz / TIMER_RATIO 12 = 40.5 MHz TB.
READ_TICK = 0x80375F20
READ_TICK_CODE = bytes.fromhex("7c6c42e64e800020")
TICKS_PER_SECOND = 40_500_000
EPISODE, TRAVELLING = 0x805D6060, 0x805D49B8


class ClockContextChanged(Unsupported):
    """No clock is pending; a portal/menu/actor change needs a new baseline."""


class SpeedSampler:
    """At most one clock call/second; no clock result is inferred from a hotkey.

    Only a dedicated, verified offline buddy session can publish measurements.
    A timed-out queue operation is never retried by this sampler instance.
    """
    def __init__(self, ad, session_id, stopped=lambda: False, clock=None):
        self.ad, self.session_id, self.stopped = ad, session_id, stopped
        self.clock = clock or time.monotonic
        self.previous, self.identity, self.next_at = None, None, 0.
        self.failure = None
        self.invalidate()

    def invalidate(self):
        self.previous = None
        self.ad._autoplay_speed_observed = None

    def _identity(self, state):
        ad = self.ad
        card = getattr(ad, "_pso_coop_new_card", {}) or {}
        speed = getattr(ad, "autoplay_speed", 1)
        if (card.get("isolated") is not True or card.get("session_id") != self.session_id or not card.get("path") or
                type(speed) not in (int, float) or speed not in (2, 4, 8, 10) or
                getattr(ad, "_autoplay_speed_known", False) is not True or
                getattr(ad, "_autoplay_speed_changing", False) or getattr(ad, "paused", False) or
                getattr(ad, "_pso_timing_paused", False) or getattr(ad, "paused_tids", None) or self.stopped() or
                set(getattr(ad, "_pso_verified_player_slots", ())) != {0, 1} or
                not state.get("verified") or state.get("phase") != 14 or state.get("travelling") or
                not state.get("difficulty_verified") or set(state.get("players", {})) != {1, 2}):
            return None
        return (speed, getattr(ad, "_pso_timing_epoch", 0), state.get("episode"), state.get("floor"),
                state.get("difficulty"), tuple(state["players"][slot]["ptr"] for slot in (1, 2)))

    def _native(self, state):
        primary, secondary = GC(self.ad, pin_player=True), GC(self.ad, player_index=1, pin_player=True)
        def static_guard():
            if primary.u32(PHASE) != 14:
                raise ClockContextChanged("PSO left offline play during clock measurement")
            if self.ad.read_memory(READ_TICK, len(READ_TICK_CODE)) != READ_TICK_CODE:
                raise Unsupported("PSO native clock instruction fingerprint differs")
            try:
                primary.check(player=False)
            except Unsupported:
                if primary.u32(PHASE) != 14:
                    raise ClockContextChanged("PSO left offline play during clock verification")
                raise
        def area_guard():
            from .pso_gc_live import PLAYER
            expected = tuple(int(state["players"][slot]["ptr"], 16) for slot in (1, 2))
            if (primary.u32(TRAVELLING) or primary.u32(EPISODE) + 1 != state["episode"] or
                    primary.u32(FLOOR) != state["floor"] or primary.u32(DIFFICULTY) != state["difficulty"] or
                    struct.unpack('>2I', self.ad.read_memory(PLAYER, 8)) != expected):
                raise ClockContextChanged("PSO area or players changed during clock measurement")
        def guard():
            static_guard()
            area_guard()
            try:
                primary.check()
                secondary.check()
            except (Unsupported, RuntimeError):
                # Recheck immutable code separately; a recreated actor or entity
                # table can be transient even before its loading flag changes.
                static_guard()
                raise ClockContextChanged("PSO player validation changed during clock measurement")
            area_guard()
        guard()
        start = self.clock()
        try:
            tick = primary.call([(READ_TICK,)], timeout=.15)[0]
        except Unsupported:
            # Hook validation can notice a portal after our own preflight but
            # before publication. A queue timeout remains a latched RuntimeError.
            guard()
            raise
        end = self.clock()
        guard()
        return tick, start, end

    def observe(self, state):
        identity, now = self._identity(state), self.clock()
        receipt = getattr(self.ad, "_autoplay_speed_observed", None)
        if receipt and not 0 <= now - receipt["monotonic"] <= 2:
            self.invalidate()
        if identity is None or self.failure:
            self.invalidate()
            self.identity = None
            return None
        if identity != self.identity:
            self.invalidate()
            self.identity = identity
        if now < self.next_at:
            return getattr(self.ad, "_autoplay_speed_observed", None)
        self.next_at = now + 1.
        # UI/stat commands and the timer own this same session lock. The lower
        # dispatcher lock also protects callers outside those command paths.
        from .pso_controls import session_lock
        speed_lock = getattr(self.ad, "_autoplay_speed_lock", None)
        if speed_lock is None:
            self.invalidate()
            return None
        acquired = []
        try:
            for lock in (session_lock(self.session_id), speed_lock, dispatcher_lock(self.ad)):
                if not lock.acquire(blocking=False):
                    self.invalidate()
                    return None
                acquired.append(lock)
            if self._identity(state) != identity:
                self.invalidate()
                return None
            tick, start, end = self._native(state)
            if type(tick) is not int or not 0 <= tick <= 0xFFFFFFFF:
                raise Unsupported("PSO native clock returned an invalid tick")
            if self._identity(state) != identity or not (0 <= end - start <= .15):
                self.invalidate()
                return None
            previous, self.previous = self.previous, (tick, start, end)
            self.ad._autoplay_speed_observed = None
            if previous is None:
                return None
            old_tick, old_start, old_end = previous
            minimum, maximum = start - old_end, end - old_start
            if not (.5 <= minimum <= maximum <= 2.):
                self.previous = None
                return None
            elapsed = ((tick - old_tick) & 0xFFFFFFFF) / TICKS_PER_SECOND
            lower, upper = elapsed / maximum, elapsed / minimum
            actual = elapsed / ((minimum + maximum) / 2)
            if (not math.isfinite(actual) or not 0 < lower <= upper <= 12 or
                    (upper - lower) / actual > .05):
                # Includes backwards clocks/resets masquerading as modulo wrap.
                self.previous = None
                return None
            receipt = {"requested": identity[0], "actual": actual, "lower": lower, "upper": upper,
                       "verified": True, "monotonic": end, "timing_epoch": identity[1],
                       "tick_delta": (tick - old_tick) & 0xFFFFFFFF,
                       "sample_seconds": (minimum + maximum) / 2,
                       "source": "3OE2 native timebase 0x80375F20"}
            self.ad._autoplay_speed_observed = receipt
            return receipt
        except ClockContextChanged:
            self.invalidate()
            self.identity = None
            return None
        except (Unsupported, OSError, RuntimeError, ValueError, KeyError, struct.error) as exc:
            self.failure = str(exc)
            self.invalidate()
            return None
        finally:
            for lock in reversed(acquired):
                lock.release()
