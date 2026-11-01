"""RE5 EBFFDB22 flash detonation on the player's native game thread.

Uses the game's constructor, resource loader and flash hit-volume/effect callback.
No inventory, controller input, weapon animation or borrowed heap allocation.
Memory installation primitives are shared with the verified RE6 controller.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
import time

from . import re5_switch as R, re6_switch_native as N
from ..native.re5_ebffdb22.code import IMAGES
from ..native.re5_ebffdb22.vtables import BASE_ENTRIES, PLAYER_TABLES

Unavailable, Uncertain, AllocationLost = N.Unavailable, N.Uncertain, N.AllocationLost
process_identity = N.process_identity
TEMP, UPDATE, DISPATCH = 0x1A91900, 0x799210, 0x118E740
CODE = (
    (0x118E600, "call", 540, "a29a07b303da4b53b108e63626e7eda4e95b549dbd2d817b4693e2f036d62443"),
    (0x118E820, "spawn", 432, "3829ed6d9998c556747b70d773ab7ac56c4b28c23a486d37d77da4e5931a0a21"),
    (0x118E9D0, "explode", 248, "f034000c3b1f9b97571f4d850854463b49c2132fd46a566a5a5ad2ac31a9b890"),
    (0x118EAC8, "weapons", 1316, "a432bf2ef38b0091cc6431cff91be8300fc501383c72b330cb65b8ce6e639d9f"),
)
_CREATE_LOCK = threading.Lock()

# Grenade ring (operator 2026-10-31): a ring of grenades that bloom out from the player and detonate.
# Only "flash" reuses the live-verified flash spawn/explode path (PRs ~#1597-#1600); it is the sole
# shippable kind. The others are refused with a clear reason and never silently substituted - their
# projectile classes and explosions have not been verified on this build.
RING_VERIFIED_KINDS = ("flash",)
RING_KIND_REFUSED = {
    "hand": "a hand-grenade ring is not yet verified on this build (its projectile class and explosion are unconfirmed)",
    "incendiary": "an incendiary-grenade ring is not yet verified on this build (its projectile class and explosion are unconfirmed)",
}
RING_KINDS = RING_VERIFIED_KINDS + tuple(RING_KIND_REFUSED)
RING_COUNT_DEFAULT, RING_COUNT_MAX = 10, 16
# Radii in RE5 world units (centimetres, as everywhere in the bot). A flash does not take the player's
# health, but the ring is still placed outward so the same geometry is safe for the explosive kinds once
# they are verified. SELF_CLEAR_CM is the smallest final radius the op will accept.
RING_RADIUS_DEFAULT_CM, RING_RADIUS_MIN_CM, RING_RADIUS_MAX_CM = 600.0, 250.0, 2500.0
RING_INNER_DEFAULT_CM, RING_SELF_CLEAR_CM = 150.0, 250.0
RING_RIPPLE_MS_DEFAULT, RING_RIPPLE_MS_MAX = 40.0, 400.0
# The spawned flash unit's world transform: spawn.c copies the player's +0x60 position to the unit's live
# transform (+0x60, x/y/z floats) and its home copy (+0x2680). Relocating both before the explode places
# the blast on the ring. This RAM relocation is the one step NOT exercised by the live-verified flash.
RING_UNIT_POS, RING_UNIT_HOME = R.P_POS, 0x2680


def ring_defaults():
    return {"count": RING_COUNT_DEFAULT, "radius_cm": RING_RADIUS_DEFAULT_CM, "inner_cm": RING_INNER_DEFAULT_CM,
            "ripple_ms": RING_RIPPLE_MS_DEFAULT, "expand": True}


def ring_kind_options():
    """The UI chooser's rows: flash preselected and enabled; the others disabled with their reason."""
    return [{"kind": k, "available": k in RING_VERIFIED_KINDS,
             "reason": RING_KIND_REFUSED.get(k, "")} for k in RING_KINDS]


def table_bytes(base, vt):
    row = PLAYER_TABLES.get(vt - base)
    if row is None:
        raise Unavailable("unsupported RE5 player class")
    changes = row[1]
    return struct.pack("<149Q", *(base + changes.get(i, x) for i, x in enumerate(BASE_ENTRIES)))


class Controller(N.Controller):
    def _ammo_backend(self):
        from . import re5_switch_mods as mods
        return mods, mods.RE5Switch

    def __init__(self, ad):
        if os.name != "posix" or os.uname().machine.lower() not in ("aarch64", "arm64") or getattr(ad, "address_mode", None) != "direct":
            raise Unavailable("native flash currently requires Linux Switch NCE")
        self.ad = ad
        self.pid, _ = ad._guest()
        self.identity = process_identity(self.pid)
        self.lock = threading.RLock()
        self.base = R.module_base(self)
        if not self.base:
            raise Unavailable("unsupported RE5 executable")
        self.heap = None
        self.failed = False

    def check_build(self):
        if process_identity(self.pid) != self.identity or self.ad._guest()[0] != self.pid:
            raise Unavailable("emulator process changed")
        if self.rd(self.base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
            raise Unavailable("RE5 executable changed")

    def check(self):
        self.check_build()
        if hasattr(self, "player"):
            if self.q(self.sp + R.P_FIRST) != self.player or self.q(self.player + 0x1A00) != self.generation:
                raise Unavailable("player allocation changed")

    def ready(self):
        self.check_build()
        if getattr(self.ad, "paused", False):
            raise Unavailable("session is paused")
        if self.failed and not self.recover_completed_call():
            raise Unavailable("native controller awaits recovery after an uncertain operation")
        sp = self.q(self.base + R.S_PLAYER)
        if not R.ptr_ok(sp):
            raise Unavailable("player manager unavailable")
        player = self.q(sp + R.P_FIRST)
        gs = R.game_sys(self, self.base)
        if not R.ptr_ok(player) or not gs or self.w(gs + R.GS_PHASE) != R.PHASE_PLAYING:
            raise Unavailable("no living player in an active Mercenaries round")
        if struct.unpack("<h", self.rd(player + R.P_HP, 2))[0] <= R.DYING_HP:
            raise Unavailable("player is dying or dead")
        vt = self.q(player)
        if vt != self.heap:
            table_bytes(self.base, vt)
        return player, self.q(player + 0x1A00)

    def validate_heap(self):
        if (self.heap is None or self.rd(self.heap + 0x6A0, 8) != b"GBXNC502" or
                self.q(self.heap + 0x60) != self.base + DISPATCH or
                self.q(self.heap + 0x688) != self.base + UPDATE or
                self.q(self.heap + 0x680) - self.base not in PLAYER_TABLES):
            raise Unavailable("private native mailbox identity changed")

    def attach(self):
        entries = table_bytes(self.base, self.original)
        if self.rd(self.original, len(entries)) != entries or self.q(self.player) != self.original:
            raise Unavailable("player vtable is modified or unsupported")
        assets = []
        for off, name, size, digest in CODE:
            data = IMAGES[name]
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise Unavailable("native hook asset checksum mismatch")
            assets.append((self.base + off, data))
        if self.heap is None:
            clone = bytearray(entries)
            struct.pack_into("<Q", clone, 0x60, self.base + CODE[0][0])
            clone.extend(struct.pack("<Q", self.original))
            assets.append((self.base + TEMP, clone))
        if any(self.rd(at, len(data)) != data for at, data in assets):
            self.stopped(lambda: [self.install(at, data) for at, data in assets])
        if self.heap is None:
            self.write(self.player, struct.pack("<Q", self.base + TEMP))
            self.heap = self.wait(lambda: (v if R.ptr_ok(v := self.q(self.player)) and v not in
                                          (self.original, self.base + TEMP) else None))
        else:
            self.validate_heap()
            if self.w(self.heap + 0x6A8) not in (0, 3):
                raise Unavailable("previous native call is incomplete")
            clone = bytearray(entries)
            struct.pack_into("<Q", clone, 0x60, self.base + DISPATCH)
            self.write(self.heap, clone)
            self.write(self.heap + 0x680, struct.pack("<4Q", self.original, self.base + UPDATE,
                                                    self.player, self.generation))
            self.write(self.player, struct.pack("<Q", self.heap))
        self.validate_heap()

    def call(self, off, *args):
        self.validate_heap()
        if self.w(self.heap + 0x6A8) not in (0, 3):
            raise Unavailable("native call already pending")
        self.write(self.heap + 0x6C0, struct.pack("<9Q", self.base + off, *args, *([0] * (8 - len(args)))))
        self.publish_call(self.heap + 0x6A8)
        self.wait(lambda: self.w(self.heap + 0x6A8) == 3)
        return self.q(self.heap + 0x6B8)

    def recover_completed_call(self):
        with self.lock:
            if not self.failed or not getattr(self, "recoverable", False):
                return not self.failed
            self.check_build()
            if self.heap is None:
                return False
            self.validate_heap()
            if self.w(self.heap + 0x6A8) != 3:
                return False
            if self.q(self.heap + 0x690) != self.player or self.q(self.heap + 0x698) != self.generation:
                return False
            self.detach_completed()
            if self.q(self.player) != self.original:
                return False
            self.failed = self.recoverable = False
            return True

    def detach_completed(self):
        if self.heap is not None:
            self.validate_heap()
            if self.w(self.heap + 0x6A8) in (1, 2):
                return
        if self.q(self.player) in (self.heap, self.base + TEMP):
            self.write(self.player, struct.pack("<Q", self.original))

    def projectile(self, unit, born):
        if (self.q(unit) != self.base + 0x1C5EF58 or self.q(unit + 0x1A00) != born or
                self.q(unit + 0x1A10) != self.player):
            raise AllocationLost("flash allocation changed; this click will not be replayed")

    def prepare(self):
        """Install/allocate dispatch before advertising the viewer capability.

        No projectile is created and no effect is invoked. This moves the
        one-time stopped-process/code-install cost out of the first click.
        """
        with self.lock:
            if self.heap is not None:
                self.validate_heap()
                return
            player, generation = self.ready()
            self.sp = self.q(self.base + R.S_PLAYER)
            self.player, self.generation = player, generation
            self.original = self.q(player)
            try:
                self.attach()
            except Exception:
                self.failed = True
                self.recoverable = False
                raise
            finally:
                self.detach_completed()

    def flash(self):
        # Recovery acquires the same lock; do it before entering the operation.
        self.ready()
        with self.lock:
            player, generation = self.ready()
            self.sp = self.q(self.base + R.S_PLAYER)
            self.player, self.generation = player, generation
            self.original = self.q(player)
            self.check()
            started = time.monotonic()
            try:
                self.attach()
                attached_at = time.monotonic()
                unit = self.call(0x118E820, self.player, self.generation)
                spawned_at = time.monotonic()
                if not R.ptr_ok(unit):
                    raise Unavailable("native flash allocation refused")
                born = self.q(unit + 0x1A00)
                def initialized():
                    self.projectile(unit, born)
                    return self.w(unit + 0x1B28) == 29 and self.rd(unit + 0x1B88, 1) == b"\x01"
                self.wait(initialized)
                initialized_at = time.monotonic()
                if self.call(0x118E9D0, unit, born, self.player, self.generation) != 1:
                    raise Unavailable("native flash resources or owner are unavailable")
                self.projectile(unit, born)
                if self.rd(unit + 0x28A0, 1) != b"\x01":
                    raise Uncertain("native flash effect did not publish its explosion flag")
                return {"state": "confirmed", "verified": True, "op": "flash_now",
                        "effect": "native_flash_explosion", "player_generation": self.generation,
                        "projectile_generation": born, "elapsed_ms": round(1000 * (time.monotonic() - started), 1),
                        "timings_ms": {"attach": round(1000 * (attached_at - started), 1),
                            "spawn": round(1000 * (spawned_at - attached_at), 1),
                            "initialize": round(1000 * (initialized_at - spawned_at), 1),
                            "explode": round(1000 * (time.monotonic() - initialized_at), 1)}}
            except Exception:
                self.failed = True
                self.recoverable = True
                raise
            finally:
                self.detach_completed()

    def ring_capable(self):
        return True

    def _ring_one(self, x, y, z, index):
        """One flash spawned, relocated to (x, y, z), and detonated - the verified flash with a position write.

        Returns the per-grenade record. Raises on any allocation loss, refusal or missing explosion flag so the
        ring aborts with a partial receipt rather than replaying a request.
        """
        unit = self.call(0x118E820, self.player, self.generation)
        if not R.ptr_ok(unit):
            raise Unavailable("native flash allocation refused")
        born = self.q(unit + 0x1A00)

        def initialized():
            self.projectile(unit, born)
            return self.w(unit + 0x1B28) == 29 and self.rd(unit + 0x1B88, 1) == b"\x01"
        self.wait(initialized)
        self.projectile(unit, born)
        # Relocate the live transform and its home copy onto the ring before the blast. Keep y (the floor).
        pos = struct.pack("<3f", x, y, z)
        self.write(unit + RING_UNIT_POS, pos)
        self.write(unit + RING_UNIT_HOME, pos)
        if self.call(0x118E9D0, unit, born, self.player, self.generation) != 1:
            raise Unavailable("native flash resources or owner are unavailable")
        self.projectile(unit, born)
        if self.rd(unit + 0x28A0, 1) != b"\x01":
            raise Uncertain("native flash effect did not publish its explosion flag")
        return {"index": index, "projectile_generation": born, "pos": [round(x, 1), round(y, 1), round(z, 1)]}

    def grenade_ring(self, kind="flash", *, count=None, radius_cm=None, inner_cm=None, ripple_ms=None, expand=None):
        """Spawn `count` grenades in a ring around the player and detonate them in a quick ripple.

        Only kind="flash" is verified and reuses the live flash spawn/explode. The ring grows outward from the
        player (expand) to a final radius_cm (default 10 grenades, ~6 m). Self-damage is read back and reported;
        flashes do not take the player's health, and the ring is kept at least RING_SELF_CLEAR_CM out regardless.
        The receipt is confirmed only if every requested grenade published its explosion; a partial result is
        reported as uncertain and never replayed.
        """
        kind = (kind or "flash").lower()
        if kind not in RING_KINDS:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        if kind not in RING_VERIFIED_KINDS:
            raise Unavailable(RING_KIND_REFUSED.get(kind, "grenade kind not verified"))
        d = ring_defaults()
        count = d["count"] if count is None else int(count)
        count = max(1, min(count, RING_COUNT_MAX))
        radius_cm = d["radius_cm"] if radius_cm is None else float(radius_cm)
        radius_cm = max(RING_SELF_CLEAR_CM, min(radius_cm, RING_RADIUS_MAX_CM))
        inner_cm = d["inner_cm"] if inner_cm is None else float(inner_cm)
        inner_cm = max(0.0, min(inner_cm, radius_cm))
        ripple_ms = d["ripple_ms"] if ripple_ms is None else float(ripple_ms)
        ripple_ms = max(0.0, min(ripple_ms, RING_RIPPLE_MS_MAX))
        expand = d["expand"] if expand is None else bool(expand)

        self.ready()
        with self.lock:
            player, generation = self.ready()
            self.sp = self.q(self.base + R.S_PLAYER)
            self.player, self.generation = player, generation
            self.original = self.q(player)
            self.check()
            hp_before = struct.unpack("<h", self.rd(player + R.P_HP, 2))[0]
            started = time.monotonic()
            grenades, abort = [], None
            try:
                self.attach()
                for i in range(count):
                    self.check()
                    # Re-read his position each grenade: he keeps playing while the ring blooms.
                    px, py, pz = struct.unpack("<3f", self.rd(self.player + R.P_POS, 12))
                    angle = 2.0 * math.pi * i / count
                    r = radius_cm if not expand or count == 1 else inner_cm + (radius_cm - inner_cm) * i / (count - 1)
                    gx, gz = px + r * math.cos(angle), pz + r * math.sin(angle)
                    try:
                        grenades.append(self._ring_one(gx, py, gz, i))
                    except (Unavailable, AllocationLost) as exc:
                        abort = str(exc)
                        break
                    if ripple_ms and i + 1 < count:
                        time.sleep(ripple_ms / 1000.0)
            except Exception:
                self.failed = True
                self.recoverable = True
                raise
            finally:
                self.detach_completed()
            try:
                hp_after = struct.unpack("<h", self.rd(player + R.P_HP, 2))[0]
            except (OSError, struct.error):
                hp_after = None
            detonated = len(grenades)
            self_damage = (hp_before - hp_after) if isinstance(hp_after, int) else None
            full = detonated == count and abort is None
            receipt = {"op": "grenade_ring", "kind": kind, "requested": count, "detonated": detonated,
                       "radius_cm": round(radius_cm, 1), "inner_cm": round(inner_cm, 1), "expand": expand,
                       "player_generation": self.generation, "hp_before": hp_before, "hp_after": hp_after,
                       "self_damage": self_damage, "grenades": grenades,
                       "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
            if full:
                return {"state": "confirmed", "verified": True, "effect": "native_flash_ring", **receipt}
            # Partial or empty: not replayed. A failure that detonated nothing is failed; anything partial is
            # uncertain so the operator can click again without a stuck controller.
            if abort is not None:
                self.failed, self.recoverable = True, True
            receipt["reason"] = abort or "the ring did not complete"
            return {"state": "failed" if detonated == 0 else "uncertain", "verified": False, **receipt}

    def current_weapon(self):
        player, _ = self.ready()
        held = [row['item'] for row in R.inventory(self, player) if row['type'] == 1 and row['hand']]
        return held[0] if len(held) == 1 else None

    def weapon_choices(self):
        from .re5_weapon_catalogue import choices
        return choices(self)

    def equip_primary(self, item, *, expected=None, allowed=None):
        from .re5_switch_weapon_native import replace
        return replace(self, item, expected=expected, allowed=allowed)


def flash_now(ad):
    with _CREATE_LOCK:
        ctl = getattr(ad, "_re5_native_flash", None)
        if ctl is None:
            ctl = ad._re5_native_flash = Controller(ad)
    return ctl.flash()


def grenade_ring_now(ad, kind="flash", **kw):
    with _CREATE_LOCK:
        ctl = getattr(ad, "_re5_native_flash", None)
        if ctl is None:
            ctl = ad._re5_native_flash = Controller(ad)
    return ctl.grenade_ring(kind, **kw)
