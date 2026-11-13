"""Explicit, single-shell research operation. Not registered as a viewer/bot control.

Native emission and enemy ice reactions are separate evidence. Neither allocation,
the arm return value, nor a requested explosion action counts as an emission.
"""
from __future__ import annotations

import math
import struct
import time

from . import re6_switch as R
from .re6_switch_native import AllocationLost, Unavailable, Uncertain
from ..native.re6_061d2a06 import shell_probe as S

PACKET_OFFSET = 0x160  # Private 0x400-byte mailbox; dispatcher uses only through +0x108.
SAFE_DISTANCE_CM = 601.0
INITIALIZE_WAIT_S = 0.75


def _is_ice(action):
    return isinstance(action, str) and action.startswith("cEm") and action.endswith(("DmgIce", "DeadIce"))


def nearby_targets(ctl, point):
    """Bounded, read-only baseline for susceptible enemies near the proposed effect."""
    manager = ctl.q(ctl.base + R.S_ENEMY)
    if not R.ptr_ok(manager):
        return []
    count, array = ctl.w(manager + R.E_COUNT), ctl.q(manager + R.E_ARRAY)
    if count > R.MAX_ENEMIES or (count and not R.ptr_ok(array)):
        raise Unavailable("enemy manager is unavailable for the shell probe baseline")
    rows = []
    for unit in struct.unpack(f"<{count}Q", ctl.rd(array, count * 8)) if count else ():
        if not R.ptr_ok(unit):
            continue
        generation, vt = ctl.w(unit + 0x1308), ctl.q(unit)
        pos = struct.unpack("<3f", ctl.rd(unit + R.E_POS, 12))
        hp = struct.unpack("<h", ctl.rd(unit + R.E_HP, 2))[0]
        if hp <= 0 or not all(math.isfinite(v) for v in pos) or math.dist(point, pos) > 1000.:
            continue
        if (ctl.w(unit + 0x1308), ctl.q(unit)) != (generation, vt):
            continue
        rows.append({"unit": unit, "generation": generation, "vtable": vt, "hp": hp,
                     "pos": pos, "action": R.unit_action(ctl, unit)})
    return sorted(rows, key=lambda row: math.dist(point, row["pos"]))[:8]


def ice_changes(ctl, baseline):
    """New nearby ice reactions, never claimed as exclusive hit attribution."""
    changes = []
    for before in baseline:
        unit = before["unit"]
        identity = (before["generation"], before["vtable"])
        if _is_ice(before["action"]) or (ctl.w(unit + 0x1308), ctl.q(unit)) != identity:
            continue
        action = R.unit_action(ctl, unit)
        hp = struct.unpack("<h", ctl.rd(unit + R.E_HP, 2))[0]
        if _is_ice(action) and (ctl.w(unit + 0x1308), ctl.q(unit)) == identity:
            changes.append({"unit": unit, "generation": before["generation"],
                            "before": before["action"], "after": action,
                            "hp_before": before["hp"], "hp_after": hp})
    return changes


def inspect_shell(ctl, unit, generation, kind):
    """Read the native shell's identity, action and enemy attack queue; write nothing.

11314E0 advances explode +28 to 2 after native effect dispatch and queueing the
explosion attack entries. Requiring the observed (4,4) entry rejects flight attacks
(1,1), a full queue, and action transitions that have not emitted enemy damage.
This is emission evidence, not attribution of a hit or proof of enemy freezing.
"""
    shell = S.SHELLS[kind]
    ctl.check()

    def identity():
        return (ctl.q(unit), ctl.q(unit + 0x1300), ctl.w(unit + 0x1308))

    expected = (ctl.base + shell.vtable, ctl.player, generation)
    if not R.ptr_ok(unit) or identity() != expected:
        raise AllocationLost("shell allocation identity changed")
    manager = unit + 0x13A8
    if ctl.q(manager) != ctl.base + S.MANAGER_VT or ctl.q(manager + 8) != unit:
        raise AllocationLost("shell action manager identity changed")
    result = {"unit": unit, "generation": generation, "kind": kind,
              "flight_phase": ctl.w(unit + 0xC), "collision_flags": ctl.w(unit + 0x2C18),
              "collision_requested": bool(ctl.w(unit + 0x3954) & 4),
              "action": None, "action_phase": None, "attack_pairs": [], "emitted": False,
              "arm_ready": False}
    count, table = ctl.w(manager + 0x18), ctl.q(manager + 0x28)
    if count > 64:
        raise Unavailable("shell action table exceeds its verified bound")
    if count > 19 and R.ptr_ok(table):
        explode = ctl.q(table + 19 * 8)
        if R.ptr_ok(explode):
            if ctl.q(explode) != ctl.base + S.SHELL_EXPLODE_VT or ctl.q(explode + 0x10) != unit:
                raise AllocationLost("shell native explosion action identity changed")
            result["arm_ready"] = ((result["flight_phase"] & 0xFFFFFF) == 0x201
                                   and not result["collision_flags"] & 1)
    action = ctl.q(manager + 0x48)
    if R.ptr_ok(action) and ctl.q(action) == ctl.base + S.SHELL_EXPLODE_VT:
        if ctl.q(action + 0x10) != unit or ctl.q(action + 0x30) != unit:
            raise AllocationLost("shell explosion action owner changed")
        action_id = ctl.q(action + 0x20)
        n, table = ctl.w(manager + 0x18), ctl.q(manager + 0x28)
        if action_id not in (17, 18, 19) or not 20 <= n <= 64 or not R.ptr_ok(table):
            raise Unavailable("shell explosion action table is unsupported")
        if ctl.q(table + action_id * 8) != action:
            raise AllocationLost("shell active action is not in its own action table")
        phase = ctl.rd(action + 0x28, 1)[0]
        count = ctl.w(unit + 0x2308)
        if count > 8:
            raise Unavailable("shell native attack queue exceeds its verified bound")
        pairs = [(ctl.w(unit + 0x2060 + i * 0x30), ctl.w(unit + 0x2070 + i * 0x30))
                 for i in range(count)]
        result.update(action=action_id, action_phase=phase, attack_pairs=pairs,
                      emitted=phase == 2 and (4, 4) in pairs)
        if (ctl.q(action), ctl.q(action + 0x10), ctl.q(action + 0x30)) != (
                ctl.base + S.SHELL_EXPLODE_VT, unit, unit):
            raise AllocationLost("shell action changed during receipt sampling")
    if identity() != expected:
        raise AllocationLost("shell allocation changed during receipt sampling")
    ctl.check()
    return result


def _safe_point(ctl, point):
    if len(point) != 3 or not all(math.isfinite(float(v)) for v in point):
        raise Unavailable("shell probe requires three finite world coordinates")
    point = tuple(float(v) for v in point)
    for i in range(8):
        player = ctl.q(ctl.sp + R.P_FIRST + i * 8)
        if not R.ptr_ok(player):
            continue
        pos = struct.unpack("<3f", ctl.rd(player + R.P_POS, 12))
        if not all(math.isfinite(v) for v in pos):
            raise Unavailable("player position is unavailable for shell probe clearance")
        if math.dist(point, pos) < SAFE_DISTANCE_CM:
            raise Unavailable("shell probe point is too close to a player")
    return point


def _install_images(ctl):
    for image in (S.SPAWN, S.ARM):
        data = S.image_bytes(image)
        at = ctl.base + image[0]
        if ctl.rd(at, len(data)) != data:
            ctl.stopped(lambda: ctl.install(at, data))
        if ctl.rd(at, len(data)) != data:
            raise Unavailable("shell research image installation unconfirmed")


def _no_owned_remotes(ctl, epoch):
    """Called under the shared native lock; stale/partial telemetry is no census."""
    units = R.owned_throwables(ctl, ctl.base, epoch[0])
    if ctl.ready() != epoch:
        raise AllocationLost("player changed during shell probe bomb census")
    if not isinstance(units, list) or any(not isinstance(u, dict) for u in units):
        raise Unavailable("shell probe requires a fresh complete native bomb census")
    if any(u.get('kind') == 'remote' for u in units):
        raise Unavailable("shell probe waits for every native remote bomb to resolve")


def probe_one(ctl, point, *, kind="shell1304", timeout_s=1.0, expected=None, allowed=None):
    """Explicit research only: one shell per player generation, never replayed.

Returns an unverified receipt even after native emission. A live observer must
separately establish the ice reaction and player clearance before rollout. There
    is deliberately no ring loop, UI registration, automatic retry or verified grenade capability.
"""
    if kind not in S.SHELLS:
        raise Unavailable("unknown native shell probe kind")
    if not math.isfinite(float(timeout_s)) or not 0.05 <= float(timeout_s) <= 2.0:
        raise Unavailable("shell probe observation budget must be 0.05 to 2 seconds")
    with ctl.lock:
        epoch = ctl.ready()
        if expected is not None and epoch != expected or allowed is not None and not allowed():
            raise Unavailable("shell research ownership or claimed player changed")
        if epoch in getattr(ctl, "_shell_probe_epochs", set()):
            raise Unavailable("a shell probe was already submitted for this player generation; not replayed")
        ctl.player, ctl.generation = epoch
        ctl.sp = ctl.q(ctl.base + R.S_PLAYER)
        ctl.manager = ctl.player + 0x13A8
        ctl.check()
        _no_owned_remotes(ctl, epoch)
        if allowed is not None and not allowed():
            raise Unavailable("native bomb allocator became busy during shell probe admission")
        if 0x112 not in (R.inventory_guns(ctl, ctl.player) or {}):
            raise Unavailable("native grenade launcher resources are not present in this loadout")
        point = _safe_point(ctl, point)
        baseline = nearby_targets(ctl, point)
        result = {"op": "shell_probe", "kind": kind, "requested": 1, "spawned": 0,
                  "armed": 0, "detonated": 0, "verified": False, "state": "failed",
                  "player_generation": ctl.generation, "point": point, "samples": [],
                  "targets_before": baseline, "ice_observations": [],
                  "reason": "native shell effect has not been observed"}
        attached = False
        started = time.monotonic()
        deadline = started + 3.0 + float(timeout_s)

        def remaining():
            # Bound all initialization/arm/observation waits to this round and one
            # overall budget. Holding the shared controller must never cross a
            # round transition or wait indefinitely for resources.
            ctl.check()
            if ctl.ready() != epoch or allowed is not None and not allowed():
                raise Unavailable("active round or player changed during the shell probe")
            left = deadline - time.monotonic()
            if left <= 0:
                raise Uncertain("shell probe deadline elapsed; request will not be replayed")
            return left

        try:
            attached = True
            ctl.attach()
            _install_images(ctl)
            # Image preparation and resource/baseline reads can outlast the
            # admission snapshot. Recheck under the same lock immediately
            # before consuming this life's single allocation opportunity.
            _no_owned_remotes(ctl, epoch)
            remaining()
            _safe_point(ctl, point)
            packet = ctl.heap + PACKET_OFFSET
            ctl.write(packet, struct.pack("<4fQI4x", *point, 0.0, 0, 0))
            epochs = getattr(ctl, "_shell_probe_epochs", set())
            epochs.add(epoch)
            ctl._shell_probe_epochs = epochs
            shell = S.SHELLS[kind]
            returned = ctl.call(S.SPAWN[0], ctl.player, ctl.generation,
                                ctl.base + shell.dti, packet, timeout=min(3.0, remaining()))
            unit, stage = struct.unpack("<QI", ctl.rd(packet + 16, 12))
            result.update(unit=unit, spawn_stage=stage, spawned=int(bool(unit)))
            if stage != 2 or returned != unit or not R.ptr_ok(unit):
                raise Uncertain("shell initialization was not confirmed; allocation will not be replayed")
            born = ctl.w(unit + 0x1308)
            result["generation"] = born
            sample = inspect_shell(ctl, unit, born, kind)
            result["samples"].append(sample)
            result["detonated"] = int(sample["emitted"])
            initialize_until = min(deadline, time.monotonic() + INITIALIZE_WAIT_S)
            while not sample["emitted"] and not sample["arm_ready"]:
                remaining()
                if time.monotonic() >= initialize_until:
                    raise Uncertain("shell native flight/action initialization did not complete; not replayed")
                time.sleep(0.005)
                sample = inspect_shell(ctl, unit, born, kind)
                if sample != result["samples"][-1] and len(result["samples"]) < 32:
                    result["samples"].append(sample)
                result["detonated"] = int(sample["emitted"])
            if not sample["emitted"]:
                _safe_point(ctl, point)
                result["armed"] = int(ctl.call(S.ARM[0], unit, ctl.player, born,
                                               ctl.generation, ctl.base + shell.vtable,
                                               timeout=min(1.0, remaining())) == 1)
            until = min(deadline, time.monotonic() + float(timeout_s))
            emitted = sample["emitted"]
            while time.monotonic() < until:
                remaining()
                time.sleep(0.005)
                if not emitted:
                    sample = inspect_shell(ctl, unit, born, kind)
                    emitted = sample["emitted"]
                    result["detonated"] = int(emitted)
                    if sample != result["samples"][-1] and len(result["samples"]) < 32:
                        result["samples"].append(sample)
                ctl.check()
                result["ice_observations"] = ice_changes(ctl, baseline)
                if emitted and (result["ice_observations"] or not baseline):
                    break
            result.update(detonated=int(emitted), state="uncertain",
                          reason=("native enemy attack emission observed; ice reaction and live verification pending"
                                  if emitted else
                                  "native enemy attack emission was not observed; request will not be replayed"))
            if emitted and result["ice_observations"]:
                result["reason"] = "native emission and new nearby ice reactions observed; visual verification pending"
        except (Unavailable, OSError, ValueError, struct.error) as exc:
            result.update(state="uncertain" if result["spawned"] or isinstance(exc, Uncertain)
                          else "failed", reason=str(exc))
            if isinstance(exc, Uncertain):
                ctl.failed = ctl.recoverable = True
        finally:
            if attached:
                ctl.detach_completed()
        result["elapsed_ms"] = round(1000 * (time.monotonic() - started), 1)
        return result
