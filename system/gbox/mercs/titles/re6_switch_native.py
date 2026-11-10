"""RE6 061D2A06 native flash, executed on the player's game thread.

No pad events, inventory writes, fuse wait, or weapon changes. The checked-in
ARM64 sources and standalone ABI tests reproduce the live-tested code. See
docs/research/re6-native-flash.md for evidence and the resource-loading limit.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import signal
import struct
import threading
import time

from . import re6_switch as R
from ..native.re6_061d2a06.code import IMAGES

ASSETS = Path(__file__).resolve().parents[1] / "native" / "re6_061d2a06"
CODE = (
    (0x18F2640, "call", 536, "eda15b096eebca87ac32027c4c2d4f0b76175a73bde3375c24da22264459fba0"),
    (0x18F2880, "spawn", 256, "5c5f9f0dca7ddbb01f1b7b1200ed99ffd49fa45db09e43c2bd6588b1ad97ae91"),
    (0x18F29C0, "detonate", 232, "c7d90bc2a61aeaa6d617864b993278fabbd08230c02e6a4aa0c668d45c4fb941"),
)
VT, TEMP, UPDATE, DISPATCH = 0x2858318, 0x25A3100, 0xF8CE10, 0x18F2780
VT_ENTRIES = (0xF8C640, 0xF8C6D0, 0xF8C790, 0x1C1270, 0xF8C7A0, 0xF8C7B0,
              0xF8C7C0, 0xF8CB50, 0xF8CD60, UPDATE, 0xF8D070)
_CREATE_LOCK = threading.Lock()

# Grenade ring (operator 2026-10-31): ten grenades spawned in a ring around the player that bloom outward and
# detonate. Only "flash" reuses the live-verified flash spawn + explosion transition (docs/research/
# re6-native-flash.md); a hand or incendiary grenade is a different native item class, so those kinds are refused
# with a reason and never substituted. The classes are known statically (branch re6-bomb-mind, 2026-11-10: uWpBomb's
# set-up main+0xF84FF4 stores (DTI id >> 8) & 0xFFFF into +0x3864, the ids from 0x07011100 + 0x201 / 0x301 / 0x401 /
# 0x501): uWp1091 the hand grenade (0x113, DTI main+0x2951490, vtable main+0x284B788), uWp1093 the incendiary (0x114,
# DTI main+0x29514C8, vtable main+0x284B328), uWp1095 the flash (0x115, DTI main+0x2951500), uWp1097 the placed remote
# bomb (0x116) - all on uWpBomb's own throw / explosion code. What is missing for them is a spawn image not pinned to
# the flash DTI (spawn.c links FLASH_DTI) and a live receipt.
RING_VERIFIED_KINDS = ("flash",)
RING_KIND_REFUSED = {
    "hand": "a hand-grenade ring is not yet verified on this build (uWp1091 is known; the compiled spawn image pins "
            "the flash's class)",
    "incendiary": "an incendiary-grenade ring is not yet verified on this build (uWp1093 is known; the compiled spawn "
                  "image pins the flash's class)",
}
RING_KINDS = RING_VERIFIED_KINDS + tuple(RING_KIND_REFUSED)
RING_COUNT_DEFAULT, RING_COUNT_MAX = 10, 16
# Radii in RE6 world units (centimetres, as everywhere in the bot). A flash takes no health, and the ring is still
# placed outward so the same geometry is safe for an explosive kind once one is verified.
RING_RADIUS_DEFAULT_CM, RING_RADIUS_MIN_CM, RING_RADIUS_MAX_CM = 600.0, 250.0, 2500.0
RING_INNER_DEFAULT_CM, RING_SELF_CLEAR_CM = 150.0, 250.0
RING_RIPPLE_MS_DEFAULT, RING_RIPPLE_MS_MAX = 40.0, 400.0
# The spawned flash's live world transform: spawn.c copies the player's +0x60 x/y and +0x68 z there. Relocating it
# before the explosion places the blast on the ring - the one step the live-verified single flash does not exercise.
RING_UNIT_POS = 0x60


def ring_defaults():
    return {"count": RING_COUNT_DEFAULT, "radius_cm": RING_RADIUS_DEFAULT_CM, "inner_cm": RING_INNER_DEFAULT_CM,
            "ripple_ms": RING_RIPPLE_MS_DEFAULT, "expand": True}


class Unavailable(RuntimeError):
    pass


class Uncertain(Unavailable):
    pass


class AllocationLost(Unavailable):
    """The game reclaimed a spawned projectile before we could detonate it."""


def process_identity(pid):
    # comm may contain spaces/parentheses. starttime (field 22) is immutable for
    # the life of this PID and available without optional psutil on Linux.
    stat = Path(f"/proc/{pid}/stat").read_text()
    return pid, int(stat[stat.rfind(")") + 2:].split()[19])


def backing_region(lines, address, length):
    matches = []
    for line in lines:
        parts = line.split(None, 5)
        if len(parts) != 6 or parts[5].strip() != "/memfd:HostMemory (deleted)":
            continue
        lo, hi = (int(x, 16) for x in parts[0].split("-"))
        if lo <= address and address + length <= hi:
            matches.append((int(parts[2], 16) + address - lo, int(parts[4])))
    if length <= 0 or len(matches) != 1:
        raise Unavailable("native code is not in one verified HostMemory mapping")
    return matches[0]


class Controller:
    def __init__(self, ad):
        if os.name != "posix" or os.uname().machine.lower() not in ("aarch64", "arm64") or getattr(ad, "address_mode", None) != "direct":
            raise Unavailable("native flash currently requires Linux Switch NCE")
        self.ad = ad
        self.pid, _ = ad._guest()
        self.identity = process_identity(self.pid)
        self.lock = threading.RLock()
        self.base = R.module_base(self)
        if not self.base:
            raise Unavailable("unsupported RE6 executable")
        self.heap = None
        self.failed = False

    @property
    def adapter(self):
        return self.ad

    def rd(self, at, n):
        return self.ad.read_memory(at, n)

    def q(self, at):
        return struct.unpack("<Q", self.rd(at, 8))[0]

    def w(self, at):
        return struct.unpack("<I", self.rd(at, 4))[0]

    def check_build(self):
        if process_identity(self.pid) != self.identity or self.ad._guest()[0] != self.pid:
            raise Unavailable("emulator process changed")
        if self.rd(self.base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
            raise Unavailable("RE6 executable changed")

    def check(self):
        self.check_build()
        if hasattr(self, "player"):
            if self.q(self.sp + R.P_FIRST) != self.player or self.w(self.player + 0x1308) != self.generation:
                raise Unavailable("player allocation changed")

    def write(self, at, data):
        self.check()
        self.ad.write_memory(at, data)

    def publish_call(self, state_at):
        try:
            self.write(state_at, struct.pack("<I", 1))
        except RuntimeError as exc:
            # The game can consume 1 -> 2 -> 3 before the adapter's immediate
            # equality readback. Those are valid acknowledgments, not a failed
            # write. Never publish again, and never relax ordinary RAM writes.
            if str(exc) != "memory write not confirmed by read-back":
                raise
            self.check()
            self.validate_heap()
            if self.w(state_at) not in (2, 3):
                raise

    def install(self, at, data):
        """Install only into zero padding, through its exact verified backing FD.

        /proc/pid/mem cannot write the shared RX NCE mapping. Never overwrite
        executed code: identical existing bytes are reusable; any other nonzero
        bytes refuse. Caller has stopped and revalidated this emulator.
        """
        self.check()
        before = self.rd(at, len(data))
        if before == data:
            return
        if any(before):
            raise Unavailable("native code padding is occupied")
        offset, inode = backing_region(Path(f"/proc/{self.pid}/maps").read_text().splitlines(), at, len(data))
        paths = []
        for p in Path(f"/proc/{self.pid}/fd").iterdir():
            try:
                if os.readlink(p) == "/memfd:HostMemory (deleted)" and p.stat().st_ino == inode:
                    paths.append(p)
            except FileNotFoundError:
                continue
        if len(paths) != 1:
            raise Unavailable("ambiguous guest backing file")
        fd = os.open(paths[0], os.O_RDWR)
        try:
            st = os.fstat(fd)
            if st.st_ino != inode or offset + len(data) > st.st_size or os.pread(fd, len(data), offset) != before:
                raise Unavailable("guest backing identity changed")
            self.check()
            if os.pwrite(fd, data, offset) != len(data) or self.rd(at, len(data)) != data:
                raise Unavailable("native code installation unconfirmed")
        finally:
            os.close(fd)

    def stopped(self, fn):
        self.check()
        state = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        if getattr(self.ad, "paused", False) or state in ("T", "t"):
            raise Unavailable("session is paused")
        # Signal this identity only. Do not resume a PID reused after a crash.
        os.kill(self.pid, signal.SIGSTOP)
        try:
            self.wait(lambda: all(p.read_text().rsplit(")", 1)[1].split()[0] in ("T", "t")
                                 for p in Path(f"/proc/{self.pid}/task").glob("*/stat")), .3)
            self.check()
            return fn()
        finally:
            if process_identity(self.pid) == self.identity:
                os.kill(self.pid, signal.SIGCONT)

    def wait(self, predicate, timeout=1.0):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            self.check()
            value = predicate()
            if value:
                return value
            time.sleep(.002)
        raise Uncertain("native completion uncertain; request will not be replayed")

    def attach(self):
        entries = struct.pack("<11Q", *(self.base + x for x in VT_ENTRIES))
        if self.rd(self.base + VT, len(entries)) != entries or self.q(self.manager) != self.base + VT:
            raise Unavailable("action manager is modified or unsupported")
        if self.q(self.manager + 8) != self.player:
            raise Unavailable("action manager owner mismatch")
        assets = []
        for off, name, size, digest in CODE:
            data = IMAGES[name]
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise Unavailable("native hook asset checksum mismatch")
            assets.append((self.base + off, data))
        clone = bytearray(entries)
        struct.pack_into("<Q", clone, 0x48, self.base + CODE[0][0])

        def install():
            for at, data in assets:
                self.install(at, data)
            self.install(self.base + TEMP, clone)
        if any(self.rd(at, len(data)) != data for at, data in assets + [(self.base + TEMP, clone)]):
            self.stopped(install)
        # All subsequent clicks use only the private mailbox and one aligned
        # vtable publication. No stop/resume or code rewriting during combat.
        if self.heap is None:
            self.write(self.manager, struct.pack("<Q", self.base + TEMP))
        else:
            self.validate_heap()
            if self.w(self.heap + 0xA8) not in (0, 3):
                raise Unavailable("previous native call is incomplete")
            self.write(self.heap + 0x90, struct.pack("<QI", self.player, self.generation))
            self.write(self.manager, struct.pack("<Q", self.heap))
        if self.heap is None:
            self.heap = self.wait(lambda: (v if R.ptr_ok(v := self.q(self.manager)) and v not in
                                          (self.base + VT, self.base + TEMP) else None))
        self.validate_heap()

    def validate_heap(self):
        if (self.rd(self.heap + 0xA0, 8) != b"GBXNC001" or self.q(self.heap + 0x80) != self.base + VT or
                self.q(self.heap + 0x48) != self.base + DISPATCH):
            raise Unavailable("private native mailbox identity changed")

    def call(self, off, *args):
        self.validate_heap()
        if self.w(self.heap + 0xA8) not in (0, 3):
            raise Unavailable("native call already pending")
        self.write(self.heap + 0xC0, struct.pack("<9Q", self.base + off, *args, *([0] * (8 - len(args)))))
        self.publish_call(self.heap + 0xA8)
        self.wait(lambda: self.w(self.heap + 0xA8) == 3)
        return self.q(self.heap + 0xB8)

    def recover_completed_call(self):
        """Permit a new click only after the old native call is fully quiescent.

        Never replay the failed click or clear a pending/executing mailbox.
        The native allocation can disappear during combat; that alone must not
        disable every later viewer intervention for the emulator's lifetime.
        """
        with self.lock:
            if not self.failed or not getattr(self, "recoverable", False):
                return not self.failed
            self.check_build()
            if self.heap is None:
                return False
            self.validate_heap()
            if self.w(self.heap + 0xA8) != 3:
                return False
            # The completed mailbox still belongs to the original operation.
            # A new round may have a different player; do not bind it until the
            # old dispatcher has returned and its table has been restored.
            if self.q(self.heap + 0x90) != self.player or self.w(self.heap + 0x98) != self.generation:
                return False
            self.detach_completed()
            if self.q(self.manager) != self.base + VT:
                return False
            self.failed = self.recoverable = False
            return True

    def detach_completed(self):
        # Do not strand a published call by removing its game-thread callback
        # when the Python wait expires. It may still complete on the next frame.
        # No subsequent call can publish while this mailbox is pending/running.
        if self.heap is not None:
            self.validate_heap()
            if self.w(self.heap + 0xA8) in (1, 2):
                return
        current = self.q(self.manager)
        if current in (self.heap, self.base + TEMP):
            self.write(self.manager, struct.pack("<Q", self.base + VT))

    def ready(self):
        """Current intervention epoch without changing the bound call owner."""
        self.check_build()
        if getattr(self.ad, "paused", False):
            raise Unavailable("session is paused")
        if self.failed and not self.recover_completed_call():
            raise Unavailable("native controller awaits recovery after an uncertain operation")
        sp = self.q(self.base + R.S_PLAYER)
        if not R.ptr_ok(sp):
            raise Unavailable("player manager unavailable")
        player = self.q(sp + R.P_FIRST)
        gm = R.game_man(self, self.base)
        if not R.ptr_ok(player) or not gm or self.w(gm + R.GM_PHASE) != R.PHASE_PLAYING:
            raise Unavailable("no living player in an active Mercenaries round")
        if struct.unpack("<h", self.rd(player + R.P_HP, 2))[0] <= 0:
            raise Unavailable("player is not alive")
        return player, self.w(player + 0x1308)

    def _ammo_backend(self):
        from . import re6_switch_mods as mods
        return mods, mods.RE6Switch

    def ammo_status(self):
        """Read this title's supported ammo mechanism without installing a hook."""
        mods, game_type = self._ammo_backend()
        try:
            with self.lock, mods._LOCK:
                epoch = self.ready()
                result = mods.ammo_readback(game_type(self.ad), epoch[0])
                if self.ready() != epoch:
                    raise Unavailable('player allocation changed during ammo readback')
                return {'available': True, **result}
        except (RuntimeError, OSError, ValueError, struct.error) as exc:
            return {'available': False, 'enabled': None, 'reason': str(exc)[:200]}

    def set_infinite_ammo(self, enabled, *, expected=None, allowed=None):
        """Use the existing mod, with the same life/input guard before every write."""
        if type(enabled) is not bool:
            raise Unavailable('enabled must be a boolean')
        mods, game_type = self._ammo_backend()
        with self.lock, mods._LOCK:
            epoch = self.ready() if expected is None else expected
            permit = allowed or (lambda: True)

            def guard():
                if not permit() or self.ready() != epoch:
                    raise Unavailable('player, round, input owner, or request deadline changed')

            guard()
            game = game_type(self.ad)
            adapter = self.ad

            class GuardedAdapter:
                def __getattr__(self, name):
                    return getattr(adapter, name)

                def write_memory(self, address, data):
                    guard()
                    return adapter.write_memory(address, data)

            # Keep ORIG keyed by the real session adapter; the wrapper only
            # protects this operation's writes, never creates another mod state.
            game.ad = GuardedAdapter()
            game.m.adapter = game.ad
            result = mods.infinite_ammo(game, enabled)
            guard()
            readback = mods.ammo_readback(game, epoch[0])
            guard()
            if not result.get('verified') or readback.get('enabled') is not enabled:
                raise Uncertain('infinite ammo change was not confirmed by readback')
            return {'state': 'confirmed', 'verified': True, 'op': 'set_infinite_ammo',
                    'player': epoch[0], 'player_generation': epoch[1], **readback}

    def weapon_choices(self):
        from .re6_switch_weapon_native import choices
        return choices(self)

    def equip_primary(self, item, *, expected=None, allowed=None):
        from .re6_switch_weapon_native import replace
        return replace(self, item, expected=expected, allowed=allowed)

    def current_weapon(self):
        player, _ = self.ready()
        index, item, _ = R.inventory_state(self, player)
        if not item or not 1 <= item <= 255:                 # Hand-To-Hand (0): no weapon the claim can carry
            return None
        return item if any(slot == index and 0 <= slot < R.WEAPON_INDEXES and (kind & 255) == item
                           for kind, slot in R.inventory_guns(self, player).items()) else None

    def flash(self):
        with self.lock:
            self.ready()
            # Establish the current player afresh. Check process/build before
            # discarding the previous allocation identity between rounds.
            if process_identity(self.pid) != self.identity:
                raise Unavailable("emulator process changed")
            self.sp = self.q(self.base + R.S_PLAYER)
            if not R.ptr_ok(self.sp):
                raise Unavailable("player manager unavailable")
            player = self.q(self.sp + R.P_FIRST)
            gm = R.game_man(self, self.base)
            if not R.ptr_ok(player) or not gm or self.w(gm + R.GM_PHASE) != R.PHASE_PLAYING:
                raise Unavailable("no living player in an active Mercenaries round")
            if struct.unpack("<h", self.rd(player + R.P_HP, 2))[0] <= 0:
                raise Unavailable("player is not alive")
            self.player = player
            self.generation = self.w(self.player + 0x1308)
            self.manager = self.player + 0x13A8
            self.check()
            if 0x115 not in R.inventory_items(self, self.player):
                raise Unavailable("flash resources are not loaded for this character")
            started = time.monotonic()
            attached = False
            try:
                # finally also detaches a partially completed bootstrap.
                attached = True
                self.attach()
                unit = self.call(0x18F2880, self.player)
                if not R.ptr_ok(unit):
                    raise Unavailable("native flash allocation refused")
                born = self.w(unit + 0x1308)
                def initialized():
                    current_born, owner = self.w(unit + 0x1308), self.q(unit + 0x1300)
                    if current_born != born or owner != self.player:
                        raise AllocationLost(f"flash allocation changed before detonation: unit={unit:#x}, "
                            f"generation={born}->{current_born}, owner={owner:#x}, player={self.player:#x}")
                    return R.unit_action(self, unit) == "cWpAction_wp_act_throw"
                self.wait(initialized)
                if self.call(0x18F29C0, unit, self.player, born, self.generation) != 1:
                    raise Unavailable("native explosion transition not confirmed")
                return {"state": "confirmed", "verified": True, "op": "flash_now",
                        "effect": "native_flash_explosion", "player_generation": self.generation,
                        "projectile_generation": born, "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
            except Exception:
                self.failed = True
                # A failed effect receipt is not an unfinished native call.
                # Initialization/resource timeouts and negative native returns
                # can also leave a completed mailbox. Accept a *new* click only
                # after verifying completion; never repeat this request.
                self.recoverable = True
                raise
            finally:
                if attached:
                    self.detach_completed()

    def grenade_kinds(self):
        """The ring's kinds as this build can honestly fire them (gbox.mercs.grenade_status reads this)."""
        return [{"kind": kind, "available": kind in RING_VERIFIED_KINDS,
                 "reason": "" if kind in RING_VERIFIED_KINDS else RING_KIND_REFUSED.get(kind, "not verified")}
                for kind in RING_KINDS]

    def _ring_one(self, x, y, z, index):
        """One flash projectile spawned, relocated to (x, y, z) and detonated - the verified flash with a position write.

        Raises AllocationLost/Unavailable on any allocation change, refusal or missing explosion transition so the
        ring aborts with a partial receipt instead of replaying a request.
        """
        unit = self.call(0x18F2880, self.player)
        if not R.ptr_ok(unit):
            raise Unavailable("native flash allocation refused")
        born = self.w(unit + 0x1308)

        def initialized():
            current_born, owner = self.w(unit + 0x1308), self.q(unit + 0x1300)
            if current_born != born or owner != self.player:
                raise AllocationLost(f"flash allocation changed before detonation: unit={unit:#x}, "
                    f"generation={born}->{current_born}, owner={owner:#x}, player={self.player:#x}")
            return R.unit_action(self, unit) == "cWpAction_wp_act_throw"
        self.wait(initialized)
        # Relocate the live transform onto the ring before the blast. Keep y (the floor height the spawn copied).
        self.write(unit + RING_UNIT_POS, struct.pack("<3f", x, y, z))
        if self.call(0x18F29C0, unit, self.player, born, self.generation) != 1:
            raise Unavailable("native explosion transition not confirmed")
        return {"index": index, "projectile_generation": born, "pos": [round(x, 1), round(y, 1), round(z, 1)]}

    def grenade_ring(self, kind="flash", *, count=None, radius_cm=None, inner_cm=None, ripple_ms=None, expand=None):
        """Spawn `count` grenades in a ring around the player and detonate them in a quick ripple.

        Only kind="flash" reuses a live-verified native path (the flash spawn + explosion transition). The ring grows
        outward from the player (expand) to a final radius_cm (default 10 grenades, ~6 m). The ring is kept at least
        RING_SELF_CLEAR_CM out whatever the caller asks; health is read back and reported (a flash takes none). The
        receipt is confirmed only if every requested grenade detonated; a partial ring is reported uncertain and is
        never replayed.
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
        with self.lock:
            self.ready()
            self.sp = self.q(self.base + R.S_PLAYER)
            player = self.q(self.sp + R.P_FIRST) if R.ptr_ok(self.sp) else 0
            gm = R.game_man(self, self.base)
            if not R.ptr_ok(player) or not gm or self.w(gm + R.GM_PHASE) != R.PHASE_PLAYING:
                raise Unavailable("no living player in an active Mercenaries round")
            if struct.unpack("<h", self.rd(player + R.P_HP, 2))[0] <= 0:
                raise Unavailable("player is not alive")
            self.player = player
            self.generation = self.w(self.player + 0x1308)
            self.manager = self.player + 0x13A8
            self.check()
            if 0x115 not in R.inventory_items(self, self.player):
                raise Unavailable("flash resources are not loaded for this character")
            hp_before = struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
            started = time.monotonic()
            grenades, abort, attached = [], None, False
            try:
                attached = True
                self.attach()
                for i in range(count):
                    self.check()
                    # Re-read his position each grenade: he keeps playing while the ring blooms.
                    px, py, pz = struct.unpack("<3f", self.rd(self.player + R.P_POS, 12))
                    angle = 2.0 * math.pi * i / count
                    r = radius_cm if not expand or count == 1 else inner_cm + (radius_cm - inner_cm) * i / (count - 1)
                    try:
                        grenades.append(self._ring_one(px + r * math.cos(angle), py, pz + r * math.sin(angle), i))
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
                if attached:
                    self.detach_completed()
            try:
                hp_after = struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
            except (OSError, struct.error):
                hp_after = None
            detonated = len(grenades)
            self_damage = (hp_before - hp_after) if isinstance(hp_after, int) else None
            receipt = {"op": "grenade_ring", "kind": kind, "requested": count, "detonated": detonated,
                       "radius_cm": round(radius_cm, 1), "inner_cm": round(inner_cm, 1), "expand": expand,
                       "player_generation": self.generation, "hp_before": hp_before, "hp_after": hp_after,
                       "self_damage": self_damage, "grenades": grenades,
                       "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
            if detonated == count and abort is None:
                return {"state": "confirmed", "verified": True, "effect": "native_flash_ring", **receipt}
            if abort is not None:
                self.failed, self.recoverable = True, True
            receipt["reason"] = abort or "the ring did not complete"
            return {"state": "failed" if detonated == 0 else "uncertain", "verified": False, **receipt}


def flash_now(ad):
    """One call = one native effect. Callers own durable request deduplication."""
    with _CREATE_LOCK:
        ctl = getattr(ad, "_re6_native_flash", None)
        if ctl is None:
            ctl = Controller(ad)
            ad._re6_native_flash = ctl
    return ctl.flash()


def grenade_ring_now(ad, kind="flash", **kw):
    with _CREATE_LOCK:
        ctl = getattr(ad, "_re6_native_flash", None)
        if ctl is None:
            ctl = Controller(ad)
            ad._re6_native_flash = ctl
    return ctl.grenade_ring(kind, **kw)
