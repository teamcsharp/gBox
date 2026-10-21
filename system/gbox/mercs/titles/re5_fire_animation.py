"""Opt-in, bounded playback rates for verified RE5 magnum firing layers.

This changes three data floats only. It does not request a shot or change game time, action/completion flags,
or executable code. New animation setup overwrites these rates. Observed action/frame resets invalidate ownership;
there is no verified generation counter, so an unobserved complete reuse between reads cannot be ruled out.
External memory reads and writes are not an atomic game-thread transaction; fences and readback bound this risk.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

S_PLAYER = 0x017FEB34
P_HP, P_ACTION, P_LAYER_COUNT = 0x14A4, 0x1238, 0x2F4
FIRE_VT = 0x0163DFC0
P_INVENTORY, INVENTORY_COUNT, INVENTORY_STRIDE = 0x22E0, 24, 0x30
MAGNUMS = frozenset((0x0B, 0x1A, 0x1B))
LAYERS = ((0x300, 0x051D), (0x3E0, 0x051E), (0x4C0, 0x051C))
BASE_RATE = struct.pack(">f", 1.0)
MAX_MULTIPLIER = 8.0
SIGNATURES = {
    0x00DFBA3C: bytes.fromhex("548028345489402e2f8400007d204850392903007d284a14"),
    0x00DFBA70: bytes.fromhex("d06a002438e00000d1aa00146000ffff3920000a7f850000"),
    0x00E0128C: bytes.fromhex("c1830010c0070010ff804800c1670024409d06a8ec006028"),
    0x00E012D0: bytes.fromhex("7f890000419e04c8a127000aed4b0332552006f62f800000"),
    0x00E012F4: bytes.fromhex("c1a70018edaa682a4fddf382d1a70018409e044c5520077a"),
    0x00A08E68: bytes.fromhex("c3de80087fe3fb7838800000fc20f89038a0051dfc60f090816901887fa9eb78"),
    0x00A3854C: bytes.fromhex("807f0018a0030308540007fe2f800000419efccc3c801000"),
    0x00E01208: bytes.fromhex("800302f4fbc1fff02f80000083c28f50fb41ffd0fb61ffd8"),
}


class _Reject(ValueError):
    pass


def _heap(address, size):
    return type(address) is int and address % 4 == 0 and 0x30000000 <= address <= 0x40000000 - size


def _u32(memory, address):
    return struct.unpack(">I", memory.rd(address, 4))[0]


def _in_hand(memory, player):
    inventory = memory.rd(player + P_INVENTORY, INVENTORY_COUNT * INVENTORY_STRIDE)
    hand = []
    for slot in range(INVENTORY_COUNT):
        row = inventory[slot * INVENTORY_STRIDE:(slot + 1) * INVENTORY_STRIDE]
        if row[0x2D] and struct.unpack_from(">I", row, 0x20)[0] == 1:
            hand.append((slot, struct.unpack_from(">I", row, 8)[0]))
    return tuple(hand)


@dataclass(frozen=True)
class _View:
    identity: tuple
    clocks: tuple
    rates: tuple
    player: int


def _view(memory, snapshot):
    if snapshot is not None and (not isinstance(snapshot, dict) or not isinstance(snapshot.get("player"), dict)):
        raise _Reject("waiting for a current player snapshot")
    if any(memory.rd(a, len(expected)) != expected for a, expected in SIGNATURES.items()):
        raise _Reject("firing-animation signatures did not match")
    sp = _u32(memory, S_PLAYER)
    pl = _u32(memory, sp + 0x28) if _heap(sp, 0x2C) else 0
    if not _heap(pl, P_INVENTORY + INVENTORY_COUNT * INVENTORY_STRIDE) \
            or snapshot is not None and snapshot["player"].get("ptr") != pl:
        raise _Reject("current player does not match snapshot")
    hp, maximum = struct.unpack(">hh", memory.rd(pl + P_HP, 4))
    if not 1 < hp <= maximum <= 32767 or snapshot is not None and (snapshot["player"].get("hp") or 0) <= 1:
        raise _Reject("waiting for a living player outside DYING")
    action = _u32(memory, pl + P_ACTION)
    if not _heap(action, 0x24) or _u32(memory, action) != FIRE_VT or _u32(memory, action + 0x18) != pl:
        raise _Reject("current player does not own a FIRE action")
    count = _u32(memory, pl + P_LAYER_COUNT)
    if not 3 <= count <= 32:  # 32 is a defensive bound, not a claimed engine capacity.
        raise _Reject("invalid animation layer count")
    hand = _in_hand(memory, pl)
    shown = [row for row in (snapshot or {}).get("inventory") or () if isinstance(row, dict) and row.get("hand")]
    if len(hand) != 1 or hand[0][1] not in {0x100 | wid for wid in MAGNUMS} \
            or snapshot is not None and (len(shown) != 1 or shown[0].get("slot") != hand[0][0]
                                        or shown[0].get("id") != hand[0][1]):
        raise _Reject("in-hand magnum does not match snapshot")
    clocks = list(struct.unpack(">2f", memory.rd(action + 0x1C, 8)))
    ends, rates = [], []
    for base, motion in LAYERS:
        raw = memory.rd(pl + base, 0x28)
        if struct.unpack_from(">H", raw, 4)[0] != motion:
            raise _Reject("firing motion IDs changed")
        frame, end = struct.unpack_from(">2f", raw, 0x18)
        rate = struct.unpack_from(">f", raw, 0x24)[0]
        if not math.isfinite(end) or end <= 0 or not math.isfinite(rate) or not 0 < rate <= MAX_MULTIPLIER:
            raise _Reject("invalid animation end or playback rate")
        clocks.append(frame)
        ends.append(raw[0x1C:0x20])
        rates.append(raw[0x24:0x28])
    if any(not math.isfinite(value) or value < 0 for value in clocks):
        raise _Reject("invalid action or animation clock")
    # FIRE's verified +0x18 owner must agree with the player's current-action pointer in both fences.
    if _u32(memory, S_PLAYER) != sp or _u32(memory, sp + 0x28) != pl \
            or _u32(memory, pl + P_ACTION) != action or _u32(memory, action) != FIRE_VT \
            or _u32(memory, action + 0x18) != pl:
        raise _Reject("player or action changed during observation")
    # HP, equipment and motions can change during the earlier reads even when the owning pointers stay stable.
    hp, latest_max = struct.unpack(">hh", memory.rd(pl + P_HP, 4))
    if not 1 < hp <= latest_max <= 32767 or latest_max != maximum or _in_hand(memory, pl) != hand \
            or _u32(memory, pl + P_LAYER_COUNT) != count:
        raise _Reject("health, equipped weapon or layer count changed during observation")
    latest_clocks = list(struct.unpack(">2f", memory.rd(action + 0x1C, 8)))
    for index, (base, motion) in enumerate(LAYERS):
        raw = memory.rd(pl + base, 0x28)
        if struct.unpack_from(">H", raw, 4)[0] != motion or raw[0x24:0x28] != rates[index] \
                or raw[0x1C:0x20] != ends[index]:
            raise _Reject("firing motion or playback rate changed during observation")
        latest_clocks.append(struct.unpack_from(">f", raw, 0x18)[0])
    if any(not math.isfinite(new) or new < old for old, new in zip(clocks, latest_clocks)):
        raise _Reject("action or animation clock reset during observation")
    return _View((sp, pl, action, hand[0], count, tuple(ends)), tuple(latest_clocks), tuple(rates), pl)


def _continuous(before, after):
    return before.identity == after.identity and all(new >= old for old, new in zip(before.clocks, after.clocks))


class FireAnimation:
    """Keep one helper per adapter. ``scope`` must identify its current session/PID, not just guest addresses.

    ``memory`` supplies rd(address,size)->bytes and wr(address,bytes)->bool. Applying needs a matching snapshot.
    Every write has a fresh full guard and exact expected-value check; at most three floats are owned at once.
    Disable with a snapshot or None to restore unchanged owned values using fresh RAM. Changed/reused animations
    are never restored. Scope must be checked again by the writer immediately before it touches process memory.
    """

    def __init__(self):
        self.scope = None
        self.last = None
        self.owned = {}

    def update(self, memory, snapshot, *, enabled, multiplier, scope):
        result = {"enabled": bool(enabled), "active": False, "verified": False, "writes": 0,
                  "write_attempts": 0, "restored": 0, "reason": ""}
        if scope is None:
            self.scope, self.last, self.owned = None, None, {}
            return {**result, "reason": "a session/PID scope is required"}
        if self.scope != scope:
            self.scope, self.last, self.owned = scope, None, {}
        if type(multiplier) not in (int, float) or not math.isfinite(multiplier) or not 1 <= multiplier <= MAX_MULTIPLIER:
            return {**result, "reason": "multiplier must be finite and between 1 and 8"}
        if (enabled is not True or multiplier == 1) and not self.owned:
            return {**result, "verified": True, "owned_layers": 0, "reason": "no owned rates to restore"}
        def observe():
            try:
                return _view(memory, snapshot)
            except (OSError, ValueError, TypeError, struct.error, IndexError):
                self.last, self.owned = None, {}        # a lost/invalid observation cannot prove instance continuity
                raise
        try:
            current = observe()
            if self.last is not None and not _continuous(self.last, current):
                self.owned.clear()                      # an observed reset is a new animation instance
            self.last = current
            for index, expected in list(self.owned.items()):
                if current.rates[index] != expected:
                    self.owned.pop(index)              # the game or another writer replaced our value
            snap = snapshot or {}
            timer = snap.get("timer")
            apply = enabled is True and multiplier > 1 and isinstance(timer, (int, float)) \
                and math.isfinite(timer) and timer > 0 and not snap.get("prompt") \
                and not snap.get("stage_prompt") and not snap.get("recovery_active")
            wanted = struct.pack(">f", float(multiplier)) if apply else BASE_RATE
            if apply and any(rate != BASE_RATE and self.owned.get(i) != rate for i, rate in enumerate(current.rates)):
                raise _Reject("playback rate is neither baseline nor an unchanged owned value")
            indices = range(len(LAYERS)) if apply else tuple(self.owned)
            for index in indices:
                expected = current.rates[index]
                if not apply and self.owned.get(index) != expected:
                    raise _Reject("owned playback rate changed before restore")
                if expected == wanted:
                    continue
                fresh = observe()                      # never issue a blind multi-layer write
                if not _continuous(current, fresh) or fresh.rates != current.rates:
                    self.last, self.owned = None, {}
                    raise _Reject("animation changed before rate write")
                current = self.last = fresh            # compare postwrite against the newest observed clocks
                address = current.player + LAYERS[index][0] + 0x24
                result["write_attempts"] += 1
                ok = memory.wr(address, wanted)
                if not ok or memory.rd(address, 4) != wanted:
                    self.owned.pop(index, None)
                    raise _Reject("playback rate write did not verify")
                result["writes"] += 1
                if not apply:
                    self.owned.pop(index, None)
                    result["restored"] += 1
                after = observe()
                expected_rates = list(current.rates)
                expected_rates[index] = wanted
                if not _continuous(current, after) or after.rates != tuple(expected_rates):
                    self.last, self.owned = None, {}
                    raise _Reject("animation changed during rate verification")
                if apply:
                    self.owned[index] = wanted
                current = self.last = after
            result.update(active=apply and all(rate == wanted for rate in current.rates), verified=True,
                          reason="scoped magnum playback verified" if apply else "unchanged owned rates restored")
        except (OSError, ValueError, TypeError, struct.error, IndexError) as error:
            result["reason"] = str(error) or type(error).__name__
        result["owned_layers"] = len(self.owned)
        return result
