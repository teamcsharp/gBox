"""Bounded G4BE08 live controls over the existing verified RE4 dispatcher.

Generation is a host-observed context epoch, not an invented native allocation
field. It changes on observed process/player/room/phase changes or VI rewind.
An unsampled load restoring exactly the same context cannot be distinguished.
"""
from __future__ import annotations

import math
import os
import struct
import threading
from pathlib import Path

from ... import re_games as R, re_mods_tool as M
from .re6_switch_native import Unavailable, Uncertain

_CREATE_LOCK = threading.RLock()
_CONTEXT_LOCK = threading.RLock()
VI_COUNT = 0x802B2D2C  # RE4GC._Frame: verified __VIRetraceHandler counter
MAX_TIMER_FRAMES = 3600 * 30
UNSUPPORTED_WEAPONS = {0x03, 0x0D, 0x38, 0x52} | set(R.NOT_GIVABLE)


def process_identity(ad):
    proc = getattr(ad, "proc", None)
    if proc is None or proc.poll() is not None:
        raise Unavailable("the owned Dolphin process is not running")
    pid = int(proc.pid)
    if os.name == "posix":
        stat = Path(f"/proc/{pid}/stat").read_text()
        return pid, int(stat[stat.rfind(")") + 2:].split()[19])
    import psutil
    return pid, psutil.Process(pid).create_time()


def _ptr(p):
    return 0x80000000 <= p < 0x81800000


def context(ad, m):
    """Read the same bounded context for Controller and both bot loop variants."""
    with _CONTEXT_LOCK:
        identity = process_identity(ad)
        if m.rd(0x80000000, 6) != R.GAME_ID:
            raise Unavailable("live controls require Resident Evil 4 GameCube G4BE08")
        pg, player = (int.from_bytes(m.rd(a, 4), "big") for a in (R.P_GLOBAL, R.P_PLAYER))
        phase, room, hp, timer = 0, None, 0, 0
        if _ptr(pg) and _ptr(player):
            phase = m.rd(pg + 0x20, 1)[0]
            room = int.from_bytes(m.rd(pg + R.G_ROOM, 2), "big")
            hp = struct.unpack(">h", m.rd(pg + R.G_HP, 2))[0]
            timer = int.from_bytes(m.rd(R.MERC_TIMER, 4), "big")
        vi = int.from_bytes(m.rd(VI_COUNT, 4), "big")
        active = (phase == 3 and room in (0x400, 0x402, 0x403, 0x404)
                  and hp > 0 and 0 < timer <= MAX_TIMER_FRAMES)
        # Re-read indirections: a load during the reads cannot authorize a call.
        if (pg, player) != tuple(int.from_bytes(m.rd(a, 4), "big") for a in (R.P_GLOBAL, R.P_PLAYER)):
            active = False
        paused = bool(getattr(ad, "paused", False) or getattr(ad, "_paused_tids", ())
                      or getattr(ad, "_pso_timing_paused", False))
        key = (identity, pg, player, room, active, getattr(ad, "_pso_timing_epoch", 0))
        previous = getattr(ad, "_re4_native_context", None) or {}
        rewind = previous.get("vi") is not None and (vi - previous["vi"]) & 0xFFFFFFFF > 0x80000000
        generation = previous.get("generation", 0) + int(previous.get("key") != key or rewind)
        result = {"key": key, "identity": identity, "player": player, "generation": generation,
                  "generation_basis": "host_observed_context", "active": active and not paused,
                  "room": room, "hp": hp, "timer": timer, "vi": vi}
        ad._re4_native_context = result
        return result


def normalize_snapshot(ad, m, snap):
    """Add engine handover identity without replacing the title's native fields."""
    from .. import primary_weapon
    ctx = context(ad, m)
    player = snap.get("player")
    if player and player.get("ptr") == ctx["player"]:
        player.update(generation=ctx["generation"], generation_basis=ctx["generation_basis"], hp=ctx["hp"])
    snap["mercenaries_phase"] = 1 if ctx["active"] else 0
    snap["native_process_id"] = ctx["identity"][0]
    # The engine uses its fast owned shared-memory reader; do not replace each
    # decision with several synchronous GDB round trips.
    class ReadView:
        rd = staticmethod(m.rd)
        def u32(self, a):
            return int.from_bytes(self.rd(a, 4), "big")
    g = object.__new__(M.RE4)
    g.m, g.V = ReadView(), R.GC
    inventory = g.items()
    snap["inventory"] = [{"type": 1, "item": row["id"], "rounds": row["loaded"], "grid": row["slot"],
                          "hand": row["id"] == snap.get("weapon")}
                         for row in inventory if R.item_kind(row["id"]) == "weapon"]
    patch = g.patch_state("infinite_ammo")
    snap["infinite_ammo"] = True if patch == "on" else False if patch == "off" else None
    snap["primary_weapon"] = primary_weapon.snapshot(ad, snap, pid=ctx["identity"][0])
    return snap


class Controller:
    def __init__(self, ad):
        self.ad = ad
        self.identity = process_identity(ad)
        self.pid = self.identity[0]
        self.g = M.RE4(ad)
        if self.g.V is not R.GC:
            raise Unavailable("RE4 live interventions require verified GameCube G4BE08")
        self.lock = M.native_lock(ad)
        self.failed = False

    def ready(self):
        if self.failed or self.g.state.get("native_call_uncertain"):
            raise Unavailable("RE4 native operation was uncertain; relaunch before another intervention")
        c = context(self.ad, self.g.m)
        if c["identity"] != self.identity:
            raise Unavailable("owned Dolphin process changed")
        if not c["active"]:
            raise Unavailable("no living player in an active unpaused RE4 Mercenaries round")
        return c["player"], c["generation"]

    def _guard(self, expected=None, allowed=None):
        if allowed is not None and not allowed():
            raise Unavailable("operator took control or request expired")
        current = self.ready()
        if expected is not None and current != expected:
            raise Unavailable("RE4 player or observed round context changed")
        return current

    def prepare(self):
        # The worker polls this: never install hooks just to show controls.
        self.ready()

    def current_weapon(self):
        expected = self.ready()
        held = self.g.m.u16(R.ITEM_MGR + 0x10)
        classes = M.weapon_classes(self.g)
        self._guard(expected)
        return held if held in classes else None

    def weapon_choices(self):
        expected = self.ready()
        held, inventory = self.current_weapon(), self.g.items()
        rows = []
        for item, (cls, _) in M.weapon_classes(self.g).items():
            if item not in R.ITEMS or item in UNSUPPORTED_WEAPONS or R.item_kind(item) != "weapon":
                continue
            if not 0 <= cls < R.N_CLASSES:
                continue
            damage = struct.unpack(">f", self.g.m.rd(R.FIREPOWER_TBL + cls * 28, 4))[0]
            damage = round(damage, 2) if math.isfinite(damage) and 0 <= damage <= 1e9 else None
            slots = [row for row in inventory if row["id"] == item]
            family = ("rifle" if item in M.SNIPERS else "shotgun" if item in M.SHOTGUNS else
                      "magnum" if item in (*M.MAGNUMS, M.HANDCANNON) else "rocket" if item in M.ROCKETS else "gun")
            rows.append({"item": item, "weapon": R.item_name(item), "family": family, "damage": damage,
                         "damage_basis": "live_level0_firepower" if damage is not None else "unmeasured",
                         "in_inventory": bool(slots), "equipped": held == item,
                         "inventory_slots": [row["slot"] for row in slots]})
        self._guard(expected)
        return sorted(rows, key=lambda r: (r["damage"] is None, -(r["damage"] or 0), r["weapon"]))

    def _result(self, expected, **kwargs):
        return {"state": "confirmed", "verified": True, "player": expected[0],
                "player_generation": expected[1], "generation_basis": "host_observed_context", **kwargs}

    def equip_primary(self, item, *, expected=None, allowed=None):
        with self.lock:
            expected = self._guard(expected, allowed)
            if type(item) is not int or item not in {r["item"] for r in self.weapon_choices()}:
                raise ValueError("not a supported RE4 GameCube weapon")
            self._guard(expected, allowed)
            # Pin the guarded context for each native call inside give/equip.
            previous = getattr(self.g, "before_call", None)
            self.g.before_call = lambda: self._guard(expected, allowed)
            try:
                result = M.equip_item(self.g, item)
                self._guard(expected, allowed)
                if result.get("verified") is not True:
                    raise Uncertain("native equipment readback did not confirm the selected RE4 weapon")
                # Snipers explicitly selected by the user stay selected, with 30x
                # native class intervals; animation/frame pacing remain game-owned.
                if item in M.SNIPERS or item in (*M.MAGNUMS, M.HANDCANNON):
                    cls = M.weapon_classes(self.g)[item][0]
                    original = struct.unpack_from(">f", R.FIRE_RATE_ORIG, cls * 20)[0]
                    rate = max(1.0, original / M.FIRE_X.get(item, 40))
                    self._guard(expected, allowed)
                    if not M.weapon_mod(self.g, item, fire_rate=rate).get("verified"):
                        raise Uncertain("RE4 fire-rate readback was not confirmed")
                # A round-start deferred equip must not undo this explicit pick.
                self._guard(expected, allowed)
                if not self.g.wr(R.PEND, bytes(4)):
                    raise Uncertain("pending automatic equipment could not be cleared")
                self._guard(expected, allowed)
                if self.current_weapon() != item:
                    raise Uncertain("RE4 selected weapon changed before receipt")
                return self._result(expected, item=item, weapon=R.item_name(item),
                                    weapon_generation=expected[1], given=result.get("given", False))
            except Exception as exc:
                self.failed = True
                raise Uncertain(f"RE4 equipment outcome requires inspection: {exc}") from exc
            finally:
                self.g.before_call = previous

    def ammo_status(self):
        self.ready()
        value = self.g.patch_state("infinite_ammo")
        return {"available": value in ("on", "off"), "enabled": value == "on" if value in ("on", "off") else None,
                **({} if value in ("on", "off") else {"reason": "RE4 ammo instruction does not match verified bytes"})}

    def set_infinite_ammo(self, enabled, *, expected=None, allowed=None):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        with self.lock:
            expected = self._guard(expected, allowed)
            result = self.g.patch("infinite_ammo", enabled)
            try:
                self._guard(expected, allowed)
                if result.get("verified") is not True or self.ammo_status().get("enabled") is not enabled:
                    raise Uncertain("RE4 ammo patch readback was not confirmed")
            except Exception as exc:
                raise Uncertain(f"RE4 ammo patch outcome needs inspection: {exc}") from exc
            with M._OPERATOR_LOCK:
                M.operator_overrides(self.ad)["infinite_ammo"] = {"on": enabled}
            return self._result(expected, enabled=enabled)

    def timer_status(self):
        expected = self.ready()
        seconds = self.g.m.u32(R.MERC_TIMER) / 30.0
        self._guard(expected)
        return {"available": True, "seconds": seconds, "min": 1, "max": 3600}

    def set_timer(self, seconds, *, expected=None, allowed=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 3600:
            raise ValueError("RE4 timer must be 1..3600 seconds")
        with self.lock:
            expected = self._guard(expected, allowed)
            result = M.merc_time(self.g, seconds)
            self._guard(expected, allowed)
            if not result.get("verified"):
                raise Uncertain("RE4 timer readback was not confirmed")
            return self._result(expected, seconds=result["seconds"])

    def grenade_kinds(self):
        safe = self.g.patch_state("unlimited_health") == "on"
        return [{"kind": "flash", "available": True, "reason": ""},
                {"kind": "hand", "available": safe,
                 "reason": "" if safe else "Injected hand grenades require verified unlimited health; native owner=0 can damage the player"}]

    def _blasts(self, kind, count, radius):
        with self.lock:
            expected = self.ready()
            if kind not in ("flash", "hand"):
                raise ValueError("RE4 supports flash and hand-grenade native blasts only")
            if kind == "hand" and self.g.patch_state("unlimited_health") != "on":
                raise Unavailable("injected RE4 grenades require verified unlimited health")
            M.install_blasts(self.g)
            self._guard(expected)
            pos = struct.unpack(">3f", self.g.m.rd(expected[0] + 0x94, 12))
            if not all(math.isfinite(v) and abs(v) < 1e7 for v in pos):
                raise Unavailable("RE4 player position is invalid")
            done = 0
            previous = getattr(self.g, "before_call", None)
            self.g.before_call = lambda: self._guard(expected)
            try:
                for i in range(count):
                    self._guard(expected)
                    if kind == "hand" and self.g.patch_state("unlimited_health") != "on":
                        raise Unavailable("RE4 grenade protection changed")
                    angle = i * math.tau / count
                    point = (pos[0] + radius * math.sin(angle), pos[1], pos[2] + radius * math.cos(angle))
                    self.g.m.wr(R.BLAST_POS, struct.pack(">3f", *point))
                    self._guard(expected)
                    if self.g.call(R.FLASH_AT if kind == "flash" else R.GRENADE_AT, R.BLAST_POS) != 1:
                        raise Uncertain("RE4 detonation did not return its completion marker")
                    done += 1
                    self._guard(expected)
            except Exception as exc:
                self.failed = True
                raise Uncertain(f"RE4 blast outcome uncertain ({done}/{count} completed): {exc}") from exc
            finally:
                self.g.before_call = previous
            return self._result(expected, effect="native_flash_explosion" if kind == "flash" else "native_grenade_explosion",
                                kind=kind, requested=count, detonated=done, radius_game_units=radius)

    def flash(self):
        return self._blasts("flash", 1, 0.0)

    def grenade_ring(self, kind="flash"):
        return self._blasts(kind, 6, 1800.0)
