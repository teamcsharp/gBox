"""Guarded RE5 native weapon-change requests.

See docs/research/re5-switch-native-equip.md for the Switch-only static chain.
The live driver uses Controller. No inventory/hand/model writes,
UI fallback, allocation, pause, or code execution. A pending-byte publication
is irreversible here: an adapter readback error can mean native consumption.
Separate memory operations are not an atomic transaction with the emulator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
import time

from . import re5_switch as R, re5_weapons

ACTION_ID, ACTION_VTABLE, ACTION_DTI_GETTER = 0x20, 0x1C7F598, 0x96AFF0
GENERATION, REQUEST_GRID = 0x1A00, 0x3F70
COUNT, TABLE, REQUESTED, PREVIOUS = 0x1B28, 0x1B38, 0x1B40, 0x1B44
PRIORITY, PENDING, RESET, CURRENT = 0x1B48, 0x1B4C, 0x1B50, 0x1B60
# Attachment uses the same native action for every catalogued weapon. A matching
# live object/class and unchanged allocation are still mandatory; this never
# constructs a weapon or substitutes a different item.
SUPPORTED_IDS = frozenset(0x100 | item for item in re5_weapons.WEAPONS)
IDLE_MOTIONS = frozenset((0, 1, 7, 9, 10, 26))
MAX_READS, MAX_BYTES, MAX_SECONDS = 512, 64 * 1024, 0.05


class Refused(RuntimeError):
    """A missing, changed or unsupported native witness; no guessed fallback."""


class _Reads:
    def __init__(self, memory, clock):
        self.memory, self.clock = memory, clock
        self.started, self.reads, self.bytes = clock(), 0, 0

    def rd(self, address, size):
        if not R.ptr_ok(address) or not 0 < size <= 24 * R.INV_SLOT:
            raise Refused("invalid_read")
        if self.reads >= MAX_READS or self.bytes + size > MAX_BYTES or self.clock() - self.started > MAX_SECONDS:
            raise Refused("read_budget")
        self.reads += 1
        self.bytes += size
        data = self.memory.rd(address, size)
        if len(data) != size:
            raise Refused("short_read")
        if self.clock() - self.started > MAX_SECONDS:
            raise Refused("read_budget")
        return bytes(data)


@dataclass(frozen=True)
class Witness:
    base: int
    player: int
    generation: int
    grid: int
    item: int
    slot: int
    object: int
    object_generation: int
    object_class: str
    action: int
    current: int
    requested: int
    held: bool
    pending: int
    checks: tuple = field(repr=False)


def _inspect(rd, base, grid, item, *, idle):
    if type(grid) is not int or not 0 <= grid <= 8 or item not in SUPPORTED_IDS:
        raise Refused("unsupported_target")
    checks = []

    def raw(address, size):
        value = rd.rd(address, size)
        checks.append((address, value))
        return value

    def value(address, fmt):
        return struct.unpack(fmt, raw(address, struct.calcsize(fmt)))[0]

    if raw(base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
        raise Refused("build_signature")
    sp = value(base + R.S_PLAYER, "<Q")
    sm = value(base + R.S_MAIN, "<Q")
    player = value(sp + R.P_FIRST, "<Q")
    gs = value(sm + R.MAIN_GAMESYS, "<Q")
    if value(gs + R.GS_PHASE, "<i") != R.PHASE_PLAYING:
        raise Refused("not_playing")
    if value(gs + 0x82C, "<B") != 0:
        raise Refused("unsupported_request_context")
    generation = value(player + GENERATION, "<Q")
    if not 0 < generation <= 0xFFFFFFFF or value(player + 0x3F2C, "<B") != 0:
        raise Refused("player_identity")
    if value(player + R.P_HP, "<h") <= R.DYING_HP:
        raise Refused("not_alive")
    motion = value(player + R.P_MOTION, "<B")
    if idle and motion not in IDLE_MOTIONS:
        raise Refused("busy_motion")
    if any((value(player + 0x3BD8, "<Q"), value(player + 0x3BE8, "<Q"),
            value(player + 0x3EF4, "<B"))):
        raise Refused("unsupported_player_override")
    count = value(player + COUNT, "<I")
    table = value(player + TABLE, "<Q")
    requested = value(player + REQUESTED, "<i")
    value(player + PREVIOUS, "<i")
    priority = value(player + PRIORITY, "<i")
    pending = value(player + PENDING, "<B")
    value(player + RESET, "<I")
    current = value(player + CURRENT, "<Q")
    value(player + REQUEST_GRID, "<i")
    if not ACTION_ID < count <= 512 or not 0 <= requested < count:
        raise Refused("action_table")
    action = value(table + 8 * ACTION_ID, "<Q")
    if value(action, "<Q") != base + ACTION_VTABLE \
            or value(base + ACTION_VTABLE + 0x28, "<Q") != base + ACTION_DTI_GETTER \
            or value(action + 0x10, "<Q") != player or value(action + 0x18, "<Q") != player:
        raise Refused("action_identity")
    if idle and (priority != -1 or pending != 0 or requested == ACTION_ID or current == action):
        raise Refused("busy_action")
    if not R.ptr_ok(current) or value(current + 0x10, "<Q") != player:
        raise Refused("current_action_identity")
    slots = raw(player + R.P_INV, 24 * R.INV_SLOT)
    found, held = [], []
    for index in range(24):
        offset = index * R.INV_SLOT
        ident = struct.unpack_from("<I", slots, offset + R.INV_ID)[0]
        cell = struct.unpack_from("<i", slots, offset + R.INV_GRID)[0]
        hand = struct.unpack_from("<i", slots, offset + R.INV_HAND)[0]
        if ident in R.EMPTY_IDS:
            continue
        if hand == 1:
            held.append(index)
        if cell == grid:
            found.append((index, ident, struct.unpack_from("<i", slots, offset + R.INV_ROUNDS)[0],
                          struct.unpack_from("<Q", slots, offset + R.INV_OBJ)[0]))
    if len(found) != 1 or len(held) != 1 or found[0][1] != item or found[0][2] <= 0:
        raise Refused("slot_identity")
    index, _, _, obj = found[0]
    obj_generation = value(obj + GENERATION, "<Q")
    if not 0 < obj_generation <= 0xFFFFFFFF:
        raise Refused("object_generation")
    vtable = value(obj, "<Q")
    name = R.class_name(rd, obj)
    if name is None or name.lower() != f"uWp{item & 0xFF:02x}".lower():
        raise Refused("object_class")
    if value(obj, "<Q") != vtable:
        raise Refused("object_changed")
    witness = Witness(base, player, generation, grid, item, player + R.P_INV + index * R.INV_SLOT,
                      obj, obj_generation, name, action, current, requested, held == [index], pending, tuple(checks))
    _unchanged(rd, witness.checks)
    return witness


def _unchanged(rd, checks):
    for address, expected in checks:
        if rd.rd(address, len(expected)) != expected:
            raise Refused("changed_witness")


class Request:
    """One-use request bound to an exact memory object, session and player life.

    Constructing is read-only. `publish` defaults disabled and is intentionally
    absent from the live bot. Caller supplies the adapter's verified write API.
    `observe` proves native hand/object ownership, not firing or damage.
    """

    def __init__(self, memory, session_id, base, grid, item, *, clock=time.monotonic):
        if not isinstance(session_id, str) or not session_id:
            raise Refused("session_required")
        self.memory, self.session_id, self.clock = memory, session_id, clock
        self.witness = _inspect(_Reads(memory, clock), base, grid, item, idle=True)
        self.used, self.receipt = False, None

    def observe(self, session_id):
        if session_id != self.session_id:
            return {"state": "unknown", "reason": "session_changed"}
        old = self.witness
        try:
            new = _inspect(_Reads(self.memory, self.clock), old.base, old.grid, old.item, idle=False)
            if (new.player, new.generation, new.slot, new.object, new.object_generation, new.object_class) != \
                    (old.player, old.generation, old.slot, old.object, old.object_generation, old.object_class):
                raise Refused("target_changed")
            if new.held and not new.pending and new.current != new.action:
                return {"state": "equipped", "item": new.item, "grid": new.grid,
                        "object_class": new.object_class, "player_generation": new.generation}
            return {"state": "waiting", "reason": "native_hand_not_confirmed"}
        except (Refused, OSError, ValueError, OverflowError, struct.error):
            return {"state": "unknown", "reason": "readback_unavailable"}

    def publish(self, session_id, write, *, enabled=False):
        if not enabled:
            return {"state": "disabled"}
        if self.used:
            return dict(self.receipt)
        if session_id != self.session_id:
            return {"state": "refused", "reason": "session_changed"}
        self.used = True
        old = self.witness
        rd = _Reads(self.memory, self.clock)
        expected = dict(old.checks)
        prepared = []
        publishing = False
        try:
            _unchanged(rd, old.checks)
            if old.held:
                self.receipt = {"state": "already_equipped", "item": old.item, "grid": old.grid}
                return dict(self.receipt)
            # Context already equals player. Never rewrite inventory, native
            # objects, current-action pointer, priority, or cooperative metadata.
            updates = ((old.player + REQUEST_GRID, struct.pack("<i", old.grid)),
                       (old.player + PREVIOUS, struct.pack("<i", old.requested)),
                       (old.player + RESET, struct.pack("<I", 0)),
                       (old.player + REQUESTED, struct.pack("<i", ACTION_ID)))
            for address, data in updates:
                _unchanged(rd, expected.items())
                before = expected[address]
                if data == before:
                    continue
                # A verifying writer can raise after changing memory. Record
                # the candidate before the call, and inspect it on failure.
                prepared.append((address, before, data))
                write(address, data)
                expected[address] = data
                if rd.rd(address, len(data)) != data:
                    raise Refused("write_not_confirmed")
            _unchanged(rd, expected.items())
            publishing = True
            write(old.player + PENDING, b"\x01")
            self.receipt = {"state": "requested", "item": old.item, "grid": old.grid}
        except (Refused, OSError, ValueError, RuntimeError, OverflowError, struct.error):
            # Never undo or retry an attempted publication. The native consumer
            # may already have cleared the flag before adapter verification.
            restored = False
            if not publishing:
                try:
                    for address, before, data in prepared:
                        actual = rd.rd(address, len(data))
                        if actual not in (before, data):
                            raise Refused("foreign_preparation")
                        expected[address] = actual
                    _unchanged(rd, expected.items())
                    for address, before, data in reversed(prepared):
                        _unchanged(rd, expected.items())
                        write(address, before)
                        expected[address] = before
                    restored = True
                except (Refused, OSError, ValueError, RuntimeError, OverflowError, struct.error):
                    pass
            self.receipt = {"state": "unknown" if publishing or not restored else "refused",
                            "reason": "publication_ambiguous" if publishing else "preparation_changed"}
        return dict(self.receipt)


class Controller:
    """One native request at a time, bound to the adapter and source session."""
    def __init__(self, memory, stats, clock=time.monotonic):
        self.memory, self.stats, self.clock = memory, stats, clock
        self.pending, self.deadline, self.failed = None, 0, None

    def record(self, result):
        self.stats['native_equip'] = result
        return result

    def tick(self):
        if self.pending is None:
            return None
        request = self.pending
        result = request.observe(self.stats.get('source_session_id'))
        if result['state'] == 'waiting' and self.clock() >= self.deadline:
            result = {'state': 'unknown', 'reason': 'request_timeout'}
        if result['state'] != 'waiting':
            self.pending = None
            if result['state'] == 'unknown':
                w = request.witness
                self.failed = (w.player, w.generation, w.item)
        return self.record(result)

    def select(self, grid, item):
        if self.stats.get('operator_control') or getattr(self.memory, 'mercs_no_modifications', False):
            return self.record({'state': 'disabled'})
        if self.pending is not None:
            return self.tick()
        sid = self.stats.get('source_session_id')
        if not sid:
            return self.record({'state': 'refused', 'reason': 'session_required'})
        try:
            base = R.module_base(self.memory)
            request = Request(self.memory, sid, base, grid, item, clock=self.clock)
            w = request.witness
            if self.failed == (w.player, w.generation, item):
                return self.record({'state': 'unknown', 'reason': 'previous_request_unconfirmed'})
            writer = getattr(self.memory, 'wr', None) or getattr(getattr(self.memory, 'adapter', None), 'write_memory', None)
            if not callable(writer):
                return self.record({'state': 'refused', 'reason': 'no_native_writer'})
            result = request.publish(sid, writer, enabled=True)
            if result['state'] in ('requested', 'unknown'):
                self.pending, self.deadline = request, self.clock() + 1.5
            return self.record(result)
        except (Refused, OSError, ValueError, RuntimeError, TypeError, struct.error) as exc:
            return self.record({'state': 'deferred', 'reason': str(exc) if isinstance(exc, Refused) else 'memory_error'})
