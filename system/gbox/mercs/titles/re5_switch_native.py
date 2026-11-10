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
from ..native.re5_ebffdb22 import classes as CLASSES
from ..native.re5_ebffdb22.code import IMAGES
from ..native.re5_ebffdb22.vtables import BASE_ENTRIES, PLAYER_TABLES

Unavailable, Uncertain, AllocationLost = N.Unavailable, N.Uncertain, N.AllocationLost
process_identity = N.process_identity
TEMP, UPDATE, DISPATCH = 0x1A91900, 0x799210, 0x118E740
CODE = (
    (0x118E600, "call", 540, "a29a07b303da4b53b108e63626e7eda4e95b549dbd2d817b4693e2f036d62443"),
    # The spawn/explode pair is the parameterised class pair (native/re5_ebffdb22/classes.py): the flash DTI and
    # vtable/item/update are passed by the controller, so hand and incendiary grenades can use the same verified
    # wrappers. Same addresses and sizes; only the class constants changed (see the lane log for the receipt plan).
    (0x118E820, "spawn_class", CLASSES.SPAWN_CLASS[2], CLASSES.SPAWN_CLASS[3]),
    (0x118E9D0, "explode_class", CLASSES.EXPLODE_CLASS[2], CLASSES.EXPLODE_CLASS[3]),
    (0x118EAC8, "weapons", 1316, "a432bf2ef38b0091cc6431cff91be8300fc501383c72b330cb65b8ce6e639d9f"),
)
_CREATE_LOCK = threading.Lock()

# Grenade ring (operator 2026-10-31): a ring of grenades that bloom out from the player and detonate.
# Only "flash" reuses the live-verified flash spawn/explode path (PRs ~#1597-#1600); it is the sole
# shippable kind. The others are refused with a clear reason and never silently substituted - their
# projectile classes and explosions have not been verified on this build.
RING_VERIFIED_KINDS = ("flash",)
# Implemented but not yet verified live: the parameterised pair takes the class (its DTI and item from the game's own
# initialiser, its vtable from the allocation, its update function from the class family). They are reachable only
# with `allow_unverified` - a receipt probe - until each has one; the queue and the PiP see the verified kinds only.
RING_IMPLEMENTED_KINDS = ("flash",) + tuple(CLASSES.CLASSES)
RING_KIND_REFUSED = {
    "hand": "a hand-grenade ring is built on the parameterised spawn (uWp06, DTI main+0x1D714C8) but has no live "
            "receipt yet",
    "incendiary": "an incendiary-grenade ring is built on the parameterised spawn (uWp07, DTI main+0x1D71500) but has "
                  "no live receipt yet",
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

# The scatter barrage (operator 2026-11-10 ~07:00): the ring's verified step along a cone toward the threats. The
# verified kind is the flash; an explicit implemented class (hand/incendiary) is the receipt probe, never "random".
SCATTER_KINDS = RING_VERIFIED_KINDS
SCATTER_COUNT_DEFAULT, SCATTER_COUNT_MAX = 8, 16
SCATTER_SPREAD_DEG = 30.0
SCATTER_MIN_CM, SCATTER_MAX_CM = 300.0, 1500.0
SCATTER_GAP_MS = (100.0, 200.0)
SCATTER_CHEST_CM = 120.0
# One centimetre past the learned reach: the placement is computed with sin/cos, and float rounding must never put an
# explosive round a hair inside it.
SCATTER_SAFE_CM = 1.0


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
            data = CLASSES.image_bytes(name)
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
                unit = self.call(0x118E820, self.player, self.generation, CLASSES.CLASSES["flash"].dti)
                spawned_at = time.monotonic()
                if not R.ptr_ok(unit):
                    raise Unavailable("native flash allocation refused")
                born = self.q(unit + 0x1A00)
                def initialized():
                    self.projectile(unit, born)
                    return self.w(unit + 0x1B28) == 29 and self.rd(unit + 0x1B88, 1) == b"\x01"
                self.wait(initialized)
                initialized_at = time.monotonic()
                carried = self.q(unit)
                if carried != self.base + CLASSES.FLASH_VT:
                    raise Uncertain(f"native flash allocation is not the verified class: {carried:#x}")
                if self.call(0x118E9D0, unit, born, self.player, self.generation, carried,
                             CLASSES.CLASSES["flash"].item, self.base + CLASSES.FLASH_UPDATE_OFF) != 1:
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

    def grenade_kinds(self):
        """The ring's kinds as this build can honestly fire them (gbox.mercs.grenade_status reads this)."""
        return ring_kind_options()

    def _ring_one(self, x, y, z, index, kind="flash"):
        """One grenade of `kind` spawned, relocated to (x, y, z), and detonated.

        The spawn/explode pair is the parameterised class pair: the class DTI (from the game's own initialiser), the
        vtable the allocation carries, its item id and its update function (the flash's own for a flash, the bomb
        base for the other uWpBomb classes) are all passed in. Returns the per-grenade record. Raises on any
        allocation loss, refusal or missing explosion flag so the ring aborts with a partial receipt rather than
        replaying a request.
        """
        spec = CLASSES.CLASSES[kind]
        unit = self.call(0x118E820, self.player, self.generation, spec.dti)
        if not R.ptr_ok(unit):
            raise Unavailable(f"native {kind} allocation refused")
        born = self.q(unit + 0x1A00)

        def initialized():
            self.projectile(unit, born)
            return self.w(unit + 0x1B28) == 29 and self.rd(unit + 0x1B88, 1) == b"\x01"
        self.wait(initialized)
        self.projectile(unit, born)
        carried = self.q(unit)                      # the class this allocation actually carries
        if kind == "flash" and carried != self.base + CLASSES.FLASH_VT:
            raise Uncertain(f"native flash allocation is not the verified class: {carried:#x}")
        # Relocate the live transform and its home copy onto the ring before the blast. Keep y (the floor).
        pos = struct.pack("<3f", x, y, z)
        self.write(unit + RING_UNIT_POS, pos)
        self.write(unit + RING_UNIT_HOME, pos)
        update = self.base + (CLASSES.FLASH_UPDATE_OFF if kind == "flash" else CLASSES.BOMB_UPDATE_OFF)
        if self.call(0x118E9D0, unit, born, self.player, self.generation, carried, spec.item, update) != 1:
            raise Unavailable(f"native {kind} resources or owner are unavailable")
        self.projectile(unit, born)
        if self.rd(unit + 0x28A0, 1) != b"\x01":
            raise Uncertain(f"native {kind} effect did not publish its explosion flag")
        return {"index": index, "kind": kind, "projectile_generation": born,
                "pos": [round(x, 1), round(y, 1), round(z, 1)], "class_vtable": hex(carried)}

    def grenade_ring(self, kind="flash", *, count=None, radius_cm=None, inner_cm=None, ripple_ms=None, expand=None,
                     allow_unverified=False):
        """Spawn `count` grenades in a ring around the player and detonate them in a quick ripple.

        kind="flash" is the live-verified path; "hand" and "incendiary" are built on the parameterised class pair and
        are reachable only with `allow_unverified` (a research probe taking their first live receipt) until each has
        one - the queue and the PiP see the verified kinds only. The ring grows outward from the player (expand) to a
        final radius_cm (default 10 grenades, ~6 m). Self-damage is read back and reported; the ring is kept at least
        RING_SELF_CLEAR_CM out regardless. The receipt is confirmed only if every requested grenade published its
        explosion; a partial result is reported as uncertain and never replayed.
        """
        kind = (kind or "flash").lower()
        if kind not in RING_KINDS:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        if kind not in RING_VERIFIED_KINDS and not allow_unverified:
            raise Unavailable(RING_KIND_REFUSED.get(kind, "grenade kind not verified"))
        spec = CLASSES.CLASSES[kind]
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
                        grenades.append(self._ring_one(gx, py, gz, i, kind))
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
                effect = "native_flash_ring" if kind == "flash" else f"native_{kind}_ring"
                return {"state": "confirmed", "verified": True, "effect": effect, **receipt}
            # Partial or empty: not replayed. A failure that detonated nothing is failed; anything partial is
            # uncertain so the operator can click again without a stuck controller.
            if abort is not None:
                self.failed, self.recoverable = True, True
            receipt["reason"] = abort or "the ring did not complete"
            return {"state": "failed" if detonated == 0 else "uncertain", "verified": False, **receipt}

    def grenade_scatter(self, kind="random", *, count=None, toward=None, spread_deg=None, min_cm=None, max_cm=None,
                        gap_ms=None, safe_cm=None, rng=None):
        """A scatter barrage: `count` grenades set off at points of a cone from him toward the threats.

        The operator (2026-11-10 ~07:00): "i want the bot able to spray a scatter shot of grenades from his postion at
        threats at will ... a rapid barrage of random grenades ... without equipping it on his character ... sprayed
        like a scatterhsot whenever the going gets tough". Each round is the ring's verified step (spawn, moved onto
        its point, the explosion transition), so nothing is equipped and his gun stays in his hand. `toward` is
        [(x, z)] of the threats; without it the cone follows his facing. Rounds run near to far, SCATTER_SPREAD_DEG
        either side, about chest height, SCATTER_GAP_MS apart. kind "random" draws each round from SCATTER_KINDS
        (only the verified ones: the flash today); an explicit implemented class (hand/incendiary) is the receipt
        probe and marks the receipt `probe`. An explosive kind keeps every point past safe_cm (his learned reach).
        A partial barrage is uncertain and never replayed.
        """
        import random as _random
        kind = (kind or "random").lower()
        if kind != "random" and kind not in RING_KINDS:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        if kind != "random" and kind not in RING_IMPLEMENTED_KINDS:
            raise Unavailable(RING_KIND_REFUSED.get(kind, "grenade kind not verified"))
        rng = rng or _random.Random()
        count = max(1, min(int(SCATTER_COUNT_DEFAULT if count is None else count), SCATTER_COUNT_MAX))
        spread = math.radians(float(SCATTER_SPREAD_DEG if spread_deg is None else spread_deg))
        lo = max(RING_SELF_CLEAR_CM, float(SCATTER_MIN_CM if min_cm is None else min_cm))
        hi = max(lo, min(float(SCATTER_MAX_CM if max_cm is None else max_cm), RING_RADIUS_MAX_CM))
        gap = gap_ms or SCATTER_GAP_MS
        probe = kind != "random" and kind not in RING_VERIFIED_KINDS
        self.ready()
        with self.lock:
            player, generation = self.ready()
            self.sp = self.q(self.base + R.S_PLAYER)
            self.player, self.generation = player, generation
            self.original = self.q(player)
            self.check()
            px, py, pz = struct.unpack("<3f", self.rd(self.player + R.P_POS, 12))
            points = [(float(x), float(z)) for x, z in (toward or ())]
            if points:
                cx, cz = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
                axis = R.heading(cx - px, cz - pz)
                far = max(math.hypot(x - px, z - pz) for x, z in points)
                hi = max(lo, min(hi, far + 200.0))
            else:
                q = struct.unpack("<4f", self.rd(self.player + R.P_ROT, 16))
                axis = R.heading_of(q)
            hp_before = struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
            started = time.monotonic()
            rounds, abort = [], None
            try:
                self.attach()
                for i in range(count):
                    self.check()
                    this = rng.choice(SCATTER_KINDS) if kind == "random" else kind
                    near = lo if this == "flash" else max(lo, float(safe_cm or 0.0) + SCATTER_SAFE_CM)
                    d = near + (max(near, hi) - near) * (i + rng.random()) / count     # near to far, a step out
                    ang = axis + rng.uniform(-spread, spread)
                    x, z = px + d * math.sin(ang), pz + d * math.cos(ang)
                    try:
                        row = self._ring_one(x, py + SCATTER_CHEST_CM, z, i, this)
                    except (Unavailable, AllocationLost) as exc:
                        abort = str(exc)
                        break
                    rounds.append({**row, "kind": this, "dist_cm": round(d, 1)})
                    if i + 1 < count:
                        time.sleep(rng.uniform(*gap) / 1000.0)
            except Exception:
                self.failed = True
                self.recoverable = True
                raise
            finally:
                self.detach_completed()
            try:
                hp_after = struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
            except (OSError, struct.error):
                hp_after = None
            receipt = {"op": "grenade_scatter", "kind": kind, "requested": count, "detonated": len(rounds),
                       "kinds": sorted({r["kind"] for r in rounds}),
                       **({"probe": True} if probe else {}),
                       "axis_deg": round(math.degrees(axis), 1), "spread_deg": round(math.degrees(spread), 1),
                       "near_cm": round(lo, 1), "far_cm": round(hi, 1), "rounds": rounds,
                       "hp_before": hp_before, "hp_after": hp_after,
                       "self_damage": (hp_before - hp_after) if isinstance(hp_after, int) else None,
                       "player_generation": self.generation,
                       "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
            if len(rounds) == count and abort is None:
                effect = "native_flash_scatter" if kind == "random" else f"native_{kind}_scatter"
                return {"state": "confirmed", "verified": True, "effect": effect, **receipt}
            if abort is not None:
                self.failed, self.recoverable = True, True
            receipt["reason"] = abort or "the barrage did not complete"
            return {"state": "failed" if not rounds else "uncertain", "verified": False, **receipt}

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
