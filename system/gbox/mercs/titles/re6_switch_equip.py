"""Guarded RE6 native weapon-change requests for the Mercenaries driver.

Build 061D2A06: BBFDE8..BBFEF8 selects pending item/gun, then player vfunc188
(B1D7B0) requests action26 from inline cActionManager. F8C7C0 publishes +30/+3C;
F8CE10 consumes it and performs old-action end/new-action init. Table26 init
1094980 calls B230B0, which tears down the old hand, selects +5050, and enables
the new weapon. These functions/table/context were read back on an owned RE6
session on 2026-10-28. On 2026-10-29, an owned live session accepted a magnum
request and attached/enabled its native hand object in about 37 ms.

Only the native pending selection and request state are written. Active slot,
active weapon, inventory, code, and action-object metadata are never assigned.
External memory writes are not an atomic game-thread transaction: callers must
retain emergency-action priority. A consumed request is never rolled back or
repeated after an uncertain outcome in the same player life.
"""
from __future__ import annotations

import struct
import time

from . import re6_switch as R

class _Stop(Exception):
    pass


class _Reads:
    """Bounded native reads; the caller's memory adapter owns process identity."""
    def __init__(self, memory, max_reads=128, max_seconds=0.03):
        self.memory, self.limit, self.seconds = memory, max_reads, max_seconds
        self.started, self.reads, self.bytes = time.monotonic(), 0, 0

    def rd(self, address, length):
        if not R.ptr_ok(address) or not 0 < length <= 1024:
            raise _Stop("invalid_read")
        if self.reads >= self.limit or self.bytes + length > 32768:
            raise _Stop("read_budget")
        if time.monotonic() - self.started >= self.seconds:
            raise _Stop("time_budget")
        self.reads += 1
        self.bytes += length
        data = bytes(self.memory.rd(address, length))
        if len(data) != length:
            raise _Stop("short_read")
        if time.monotonic() - self.started >= self.seconds:
            raise _Stop("time_budget")
        return data

    def u32(self, address):
        return struct.unpack("<I", self.rd(address, 4))[0]

    def u64(self, address):
        return struct.unpack("<Q", self.rd(address, 8))[0]

MANAGER, REQUEST_ID = 0x13A8, 0x26
MANAGER_VTABLE, REQUEST_FUNCTION, UPDATE_FUNCTION = 0x2858318, 0xF8C7C0, 0xF8CE10
EQUIP_INIT, DIRECT_HAND_GETTER, HAND_ENABLE = 0x1094980, 0xF41E80, 0xF41BF0
GENERATION, OWNER, HIDDEN = 0x1308, 0x1300, 0x12F4
ACTIVE_OBJECT, ACTIVE_INDEX = 0x5050, 0x5064
PENDING_GUN, PENDING_ALT, PENDING_ITEM_SELECT, PENDING_ITEM = 0x505C, 0x5060, 0x5438, 0x5440
SLOTS, STRIDE, SLOT_COUNT = 0x5070, 0x28, 24
ITEMS = frozenset((0x113, 0x114, 0x115, 0x116))
GUNS = frozenset(range(0x101, 0x113)) | {0x117, 0x11B, 0x128}
FREE_ACTIONS = frozenset("cPlAction_pl_act_" + name for name in (
    "wait", "walk", "walk_to_wait", "run", "weapon_ready_begin", "weapon_ready_loop", "weapon_ready_end"))
TIMEOUT_S = 1.5


def _native_type(rd, unit):
    vt = rd.u64(unit)
    fn = rd.u64(vt + 0x28)
    w0, w1, w2 = struct.unpack("<III", rd.rd(fn, 12))
    if w0 & 0x9F00001F != 0x90000000 or w1 & 0xFFC003FF != 0x91000000 or w2 != 0xD65F03C0:
        raise _Stop("invalid_native_type")
    imm = ((w0 >> 29) & 3) | (((w0 >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    dti = (fn & ~0xFFF) + (imm << 12) + ((w1 >> 10) & 0xFFF)
    return vt, (rd.u32(dti + 0x34) >> 8) & 0xFFFF


def _view(rd, base, player, kind):
    if kind not in GUNS | ITEMS or not R.ptr_ok(base) or not R.ptr_ok(player):
        raise _Stop("unsupported_request")
    if rd.rd(base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
        raise _Stop("build_signature")
    sp, gm = rd.u64(base + R.S_PLAYER), rd.u64(base + R.S_GAMEMAN)
    if not R.ptr_ok(sp) or not R.ptr_ok(gm) or rd.u64(sp + R.P_FIRST) != player:
        raise _Stop("player_identity")
    if rd.u32(gm + R.GM_PHASE) != R.PHASE_PLAYING:
        raise _Stop("not_playing")
    gen = rd.u32(player + GENERATION)
    if not gen or struct.unpack("<h", rd.rd(player + R.P_HP, 2))[0] <= 0:
        raise _Stop("player_not_alive")
    manager = rd.rd(player + MANAGER, 0x70)
    vt, owner = struct.unpack_from("<QQ", manager)
    count = struct.unpack_from("<I", manager, 0x18)[0]
    table = struct.unpack_from("<Q", manager, 0x28)[0]
    current, previous, priority = struct.unpack_from("<iii", manager, 0x30)
    active_action = struct.unpack_from("<Q", manager, 0x48)[0]
    if (vt != base + MANAGER_VTABLE or owner != player or not REQUEST_ID < count <= 1024
            or not R.ptr_ok(table) or not 0 <= current < count or not R.ptr_ok(active_action)):
        raise _Stop("action_manager_identity")
    if rd.u64(vt + 0x30) != base + REQUEST_FUNCTION or rd.u64(vt + 0x48) != base + UPDATE_FUNCTION:
        raise _Stop("request_function")
    equip = rd.u64(table + 8 * REQUEST_ID)
    if not R.ptr_ok(equip):
        raise _Stop("equip_action_identity")
    action = rd.rd(equip, 0x30)
    act_vt = struct.unpack_from("<Q", action)[0]
    if (struct.unpack_from("<QQQ", action, 0x10) != (player, player, 0)
            or rd.u64(act_vt + 0x38) != base + EQUIP_INIT
            or R.class_name(rd, equip) != "cPlAction_pl_act_weapon_change"):
        raise _Stop("equip_action_identity")
    raw = rd.rd(player + SLOTS, SLOT_COUNT * STRIDE)
    candidates = []
    for off in range(0, len(raw), STRIDE):
        row = raw[off:off + STRIDE]
        index = row[9]
        valid_index = 7 <= index < 15 if kind in ITEMS else index < 7
        if row[8] and valid_index and struct.unpack_from("<H", row, 0xA)[0] == kind:
            candidates.append((off, row))
    if len(candidates) != 1:
        raise _Stop("item_unavailable_or_ambiguous")
    off, row = candidates[0]
    if struct.unpack_from("<h", row, 0xE)[0] <= 0:
        raise _Stop("item_empty")
    obj = struct.unpack_from("<Q", row, 0x20)[0]
    if not R.ptr_ok(obj):
        raise _Stop("item_object_missing")
    object_vt, object_kind = _native_type(rd, obj)
    if (object_kind != kind or rd.u64(object_vt + 0x3A0) != base + DIRECT_HAND_GETTER
            or rd.u64(object_vt + 0x390) != base + HAND_ENABLE):
        raise _Stop("unsupported_hand_lifecycle")
    object_owner = rd.u64(obj + OWNER)
    object_gen = rd.u32(obj + GENERATION)
    if object_owner != player or not object_gen:
        raise _Stop("item_owner_identity")
    hand = rd.u64(player + ACTIVE_OBJECT)
    index = rd.u32(player + ACTIVE_INDEX)
    enabled = not (struct.unpack("<H", rd.rd(obj + HIDDEN, 2))[0] & 1)
    return {"base": base, "player": player, "generation": gen, "kind": kind, "sp": sp,
            "slot": player + SLOTS + off, "slot_bytes": row, "index": row[9],
            "object": obj, "object_generation": object_gen, "manager": manager,
            "active_action": active_action, "current": current, "priority": priority,
            "pending": manager[0x3C], "equipped": hand == obj and index == row[9] and enabled}


def _same_player(rd, ticket):
    return (rd.u64(ticket["sp"] + R.P_FIRST) == ticket["player"]
            and rd.u32(ticket["player"] + GENERATION) == ticket["generation"])


def _same_request_context(rd, view):
    player = view["player"]
    return (_same_player(rd, view)
            and rd.rd(player + MANAGER + 0x30, 13) == view["manager"][0x30:0x3D]
            and rd.u64(player + MANAGER + 0x48) == view["active_action"]
            and rd.rd(view["slot"], STRIDE) == view["slot_bytes"]
            and rd.u32(view["object"] + GENERATION) == view["object_generation"]
            and rd.u64(view["object"] + OWNER) == player)


def _writer(memory):
    writer = getattr(memory, "wr", None)
    if not callable(writer):
        writer = getattr(getattr(memory, "adapter", None), "write_memory", None)
    if not callable(writer):
        raise _Stop("no_native_writer")
    return writer


def poll(memory, *, now=None):
    """Confirm the native hand lifecycle; never reissue or revert a published request."""
    ticket = getattr(memory, "_re6_native_equip", None)
    if not ticket:
        return {"state": "idle"}
    now = time.monotonic() if now is None else now
    rd = _Reads(memory, 256, 0.03)
    try:
        view = _view(rd, ticket["base"], ticket["player"], ticket["kind"])
        if (view["generation"], view["object"], view["object_generation"]) != (
                ticket["generation"], ticket["object"], ticket["object_generation"]):
            raise _Stop("request_identity_changed")
        if view["equipped"]:
            memory._re6_native_equip = None
            return {"state": "equipped", "kind": ticket["kind"], "index": view["index"],
                    "object": view["object"], "player_generation": view["generation"]}
        if now >= ticket["deadline"]:
            raise _Stop("request_timeout")
        if view["current"] != REQUEST_ID:
            raise _Stop("request_interrupted")
        return {"state": "pending", "kind": ticket["kind"], "accepted": not view["pending"]}
    except (_Stop, OSError, ValueError, RuntimeError, OverflowError, struct.error) as exc:
        memory._re6_native_equip = None
        return {"state": "unconfirmed", "kind": ticket["kind"],
                "reason": str(exc) if isinstance(exc, _Stop) else "read_error"}


def request(memory, base, player, kind, *, now=None, expected_index=None):
    """Publish one verified native action26 request, or defer with zero writes.

    Pre-publication failure restores only our unchanged preparation cells while
    the original player/action identity is still present. After publication,
    even a write/readback exception is treated as uncertain until native poll.
    """
    now = time.monotonic() if now is None else now
    if getattr(memory, "_re6_native_equip", None):
        return poll(memory, now=now)
    rd = _Reads(memory, 128, 0.03)
    prepared, view, write = [], None, None
    published = False
    try:
        view = _view(rd, base, player, kind)
        if expected_index is not None and view['index'] != expected_index:
            raise _Stop('target_slot_changed')
        if view["equipped"]:
            return {"state": "equipped", "kind": kind, "index": view["index"],
                    "object": view["object"], "player_generation": view["generation"]}
        if view["pending"] or view["priority"] != -1:
            raise _Stop("native_request_busy")
        if R.class_name(rd, view["active_action"]) not in FREE_ACTIONS:
            raise _Stop("native_action_busy")
        write = _writer(memory)
        selection = ((PENDING_ITEM_SELECT, view["index"]), (PENDING_ITEM, view["index"])) if kind in ITEMS else (
            (PENDING_ITEM, -1), (PENDING_GUN, view["index"]), (PENDING_ALT, -1))
        writes = [(player + offset, struct.pack("<i", value)) for offset, value in selection]
        writes += [(player + MANAGER + 0x40, bytes(4)), (player + MANAGER + 0x6C, b"\1\0"),
                   (player + 0xC, struct.pack("<I", 3))]
        for address, data in writes:
            if not _same_request_context(rd, view):
                raise _Stop("identity_changed_before_preparation")
            original = rd.rd(address, len(data))
            if original != data:
                prepared.append((address, original, data))
                write(address, data)
                if rd.rd(address, len(data)) != data:
                    raise _Stop("preparation_unconfirmed")
        if not _same_request_context(rd, view):
            raise _Stop("identity_changed_before_publication")
        ticket = {k: view[k] for k in ("base", "player", "generation", "kind", "sp", "object", "object_generation")}
        ticket["deadline"] = now + TIMEOUT_S
        memory._re6_native_equip = ticket
        # Current/previous/priority and the pending byte form one bounded write;
        # the pending byte is last in the publication buffer, as in the producer.
        publication = struct.pack("<iiiB", REQUEST_ID, view["current"], -1, 1)
        published = True
        try:
            write(player + MANAGER + 0x30, publication)
        except (OSError, ValueError, RuntimeError):
            pass  # write_memory may race a successful native consumption/readback
        result = poll(memory, now=now)
        if result["state"] == "pending":
            result["state"] = "requested"
        return result
    except (_Stop, OSError, ValueError, RuntimeError, OverflowError, struct.error) as exc:
        restored = 0
        if not published and view is not None and write is not None:
            rollback = _Reads(memory, 64, 0.03)
            try:
                if (_same_player(rollback, view)
                        and rollback.rd(player + MANAGER + 0x30, 13) == view["manager"][0x30:0x3D]
                        and rollback.u64(player + MANAGER + 0x48) == view["active_action"]):
                    for address, original, data in reversed(prepared):
                        if rollback.rd(address, len(data)) == data:
                            write(address, original)
                            restored += 1
            except (_Stop, OSError, ValueError, RuntimeError, OverflowError, struct.error):
                pass
        return {"state": "deferred", "kind": kind, "restored_cells": restored,
                "reason": str(exc) if isinstance(exc, _Stop) else "memory_error"}


class Controller:
    """Session-bound driver bridge. Refusal never falls back to wheel inputs."""
    def __init__(self, memory, stats):
        self.memory, self.stats = memory, stats
        self.failed = None

    def record(self, result):
        self.stats['native_equip'] = result
        return result

    def tick(self):
        ticket = getattr(self.memory, '_re6_native_equip', None)
        if ticket:
            result = poll(self.memory)
            if result.get('state') == 'unconfirmed':
                self.failed = (ticket['player'], ticket['generation'], ticket['kind'])
            return self.record(result)
        return None

    def select(self, player, index):
        if self.stats.get('operator_control') or getattr(self.memory, 'mercs_no_modifications', False):
            return self.record({'state': 'disabled'})
        kinds = [kind for kind, slot in (player.get('guns') or {}).items() if slot == index]
        kinds += [kind for kind, row in (player.get('nades') or {}).items() if row[0] == index]
        if index == R.BOMB_INDEX and (player.get('bomb') or {}).get('count', 0) > 0:
            kinds.append(0x116)
        kinds = set(kinds)
        if len(kinds) != 1:
            return self.record({'state': 'deferred', 'reason': 'target_unavailable'})
        kind = kinds.pop()
        try:
            base = R.module_base(self.memory)
            generation = _Reads(self.memory).u32(player.get('ptr', 0) + GENERATION)
            identity = (player.get('ptr'), generation, kind)
            if self.failed == identity:
                return self.record({'state': 'unconfirmed', 'kind': kind, 'reason': 'previous_request_unconfirmed'})
            result = request(self.memory, base, player.get('ptr'), kind, expected_index=index)
            if result.get('state') == 'unconfirmed':
                self.failed = identity
        except (OSError, ValueError, RuntimeError, struct.error):
            result = {'state': 'deferred', 'reason': 'memory_error'}
        return self.record(result)
