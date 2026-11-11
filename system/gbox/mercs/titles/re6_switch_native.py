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
from ..native.re6_061d2a06 import classes as CLASSES
from ..native.re6_061d2a06.code import IMAGES

ASSETS = Path(__file__).resolve().parents[1] / "native" / "re6_061d2a06"
CODE = (
    (0x18F2640, "call", 536, "eda15b096eebca87ac32027c4c2d4f0b76175a73bde3375c24da22264459fba0"),
    (0x18F2880, "spawn", 256, "5c5f9f0dca7ddbb01f1b7b1200ed99ffd49fa45db09e43c2bd6588b1ad97ae91"),
    (0x18F29C0, "detonate", 232, "c7d90bc2a61aeaa6d617864b993278fabbd08230c02e6a4aa0c668d45c4fb941"),
)
# The remote bomb dropped already placed (operator 2026-11-10 ~07:05: "I want the bot able to just instant drop them
# without even doing the animation ... The remote mines should just fall onto the ground and be armed and ready for
# detonation by the bot flipping the ram byte flag at will"): spawn_bomb.c - the native allocation of the placed bomb
# (uWp1097), its owner, the point, the detonator's flag (player u32 +0x5A18 bit 0x2000) set on the game thread, then its
# own placed action (24, cWpAction_wp_act_setting). Installed into the zero padding after `detonate` on the first drop.
SPAWN_BOMB = (0x18F2AC0, "spawn_bomb", 232, "1de55b539fc610c1b5fe4ed3caac0d4c4500978f70767eabbde6e15a287506fd")
BOMB_VTABLE, BOMB_SETTING = 0x284AA58, "cWpAction_wp_act_setting"
P_FLAGS_ARMED_BYTE, ARMED_BIT = 0x5A19, 0x20
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
#: The parameterised class spawn/detonate (classes.py) runs the item factory and loads the class's resources on its
#: first call; the flash's 1 s wait is too tight for it (the first live hand ring timed out after 1295 ms, 2026-11-11
#: 13:51, and left the controller uncertain), so the derived pair gets its own, wider budget.
CLASS_SPAWN_TIMEOUT_S = 3.0
CLASS_WAIT_S = 2.0
# Implemented but not yet verified live (the handoff's "get a live receipt per kind, then advertise"): the
# parameterised spawn/detonate pair in native/re6_061d2a06/classes.py takes the class, so the ring *can* fire them
# (`allow_unverified` on the controller, never on the queue); grenade_kinds() keeps advertising only the verified
# ones until each has a receipt.
RING_IMPLEMENTED_KINDS = ("flash",) + tuple(CLASSES.CLASSES)
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
# The smallest radius an *explosive* kind (hand, incendiary) may be ringed at: the flash's 250 cm floor is inside a
# grenade's blast. The scatter's learned reach default is 500-600 cm; the ring stays conservative and reports the clamp.
RING_EXPLOSIVE_CLEAR_CM = 600.0
RING_RIPPLE_MS_DEFAULT, RING_RIPPLE_MS_MAX = 40.0, 400.0
# The spawned flash's live world transform: spawn.c copies the player's +0x60 x/y and +0x68 z there. Relocating it
# before the explosion places the blast on the ring - the one step the live-verified single flash does not exercise.
RING_UNIT_POS = 0x60
# The scatter barrage (grenade_scatter): the ring's verified step along a cone toward the threats. Its kinds are the
# verified ones only - the flash; the grenade launcher's rounds (and the hand / incendiary classes' spawn) are not
# identified / verified on this build, so "random" draws from this tuple.
SCATTER_KINDS = RING_VERIFIED_KINDS
SCATTER_COUNT_DEFAULT, SCATTER_COUNT_MAX = 8, 16
SCATTER_SPREAD_DEG, SCATTER_MIN_CM, SCATTER_MAX_CM = 30.0, 300.0, 1500.0
SCATTER_GAP_MS = (100.0, 200.0)
SCATTER_CHEST_CM = 120.0
# One centimetre past the learned reach: the placement is computed with sin/cos, and float rounding must never put an
# explosive round a hair inside it (checkpoint 0.2).
SCATTER_SAFE_CM = 1.0


def flash_place_min_cm():
    """The nearest a flash round may be placed from him: the title's own floor (aim-book) or 400 cm (checkpoint 0.3).

    The operator (2026-11-10): "never let the bot get stunned by their own flash grenades". The scatter's old 300 cm
    near field is inside a flash's own effect; a title value below 400 is clamped, a wider one is honoured.
    """
    value = getattr(R, "FLASH_PLACE_MIN_CM", None)
    try:
        return max(400.0, float(value)) if value is not None else 400.0
    except (TypeError, ValueError):
        return 400.0


def ring_defaults():
    return {"count": RING_COUNT_DEFAULT, "radius_cm": RING_RADIUS_DEFAULT_CM, "inner_cm": RING_INNER_DEFAULT_CM,
            "ripple_ms": RING_RIPPLE_MS_DEFAULT, "expand": True}


def verify_build(image: bytes) -> dict:
    """Check a decompressed `main` image (hactool `--uncompressed`, its 0x100 header still in front) against the
    pinned build: the module signature and the three code caves this controller installs into.

    Every address in that output is 0x100 higher than its virtual address (gbox.nso_elf), so the image offset is
    ``vaddr + 0x100``. Returns the facts; raises nothing, so a wrong image is reported instead of trusted.
    """
    shift = 0x100
    out = {"image_bytes": len(image) if image else 0, "build_signature": False, "caves": {}, "ok": False}
    if not isinstance(image, (bytes, bytearray)) or len(image) < shift + R.SIG_OFF + len(R.SIGNATURE):
        return {**out, "reason": "image is shorter than the signature's address"}
    out["build_signature"] = bytes(image[shift + R.SIG_OFF:shift + R.SIG_OFF + len(R.SIGNATURE)]) == R.SIGNATURE
    ok = out["build_signature"]
    for off, name, size, digest in CODE + (SPAWN_BOMB,):     # (the instant bomb drop's cave too, 2026-11-10)
        data = IMAGES[name]
        at = shift + off
        before = bytes(image[at:at + size])
        usable = len(before) == size and (before == data or not any(before))
        out["caves"][name] = {"vaddr": hex(off), "size": size,
                              "image_bytes_match": before == data, "pristine_padding": not any(before),
                              "installable": usable,
                              "image_sha256": hashlib.sha256(data).hexdigest()}
        ok = ok and usable
    out["ok"] = ok
    out["reason"] = "" if ok else ("this image is not the pinned RE6 build" if not out["build_signature"]
                                   else "a code cave is neither pristine padding nor this controller's own image")
    return out


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

    def call(self, off, *args, timeout=1.0):
        self.validate_heap()
        if self.w(self.heap + 0xA8) not in (0, 3):
            raise Unavailable("native call already pending")
        self.write(self.heap + 0xC0, struct.pack("<9Q", self.base + off, *args, *([0] * (8 - len(args)))))
        self.publish_call(self.heap + 0xA8)
        self.wait(lambda: self.w(self.heap + 0xA8) == 3, timeout)
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

    def _ring_one(self, x, y, z, index, kind="flash"):
        """One grenade of `kind` spawned, relocated to (x, y, z) and detonated.

        The flash is the live-verified spawn/detonate pair exactly as shipped. A hand or incendiary grenade uses the
        parameterised pair (`native/re6_061d2a06/classes.py`): the same two verified images with the class's DTI and
        the unit's own vtable handed in, so the item factory builds that class and the wrapper checks "still the
        class this allocation carried". Raises AllocationLost/Unavailable on any allocation change, refusal or
        missing transition so the ring aborts with a partial receipt instead of replaying a request.
        """
        spec = CLASSES.class_for(kind)
        if kind == "flash":
            unit = self.call(0x18F2880, self.player)
        else:
            unit = self.call(CLASSES.SPAWN_CLASS[0], self.player, spec.dti, timeout=CLASS_SPAWN_TIMEOUT_S)
        if not R.ptr_ok(unit):
            raise Unavailable(f"native {kind} allocation refused")
        born = self.w(unit + 0x1308)

        def initialized():
            current_born, owner = self.w(unit + 0x1308), self.q(unit + 0x1300)
            if current_born != born or owner != self.player:
                raise AllocationLost(f"{kind} allocation changed before detonation: unit={unit:#x}, "
                    f"generation={born}->{current_born}, owner={owner:#x}, player={self.player:#x}")
            return R.unit_action(self, unit) == "cWpAction_wp_act_throw"
        self.wait(initialized, timeout=CLASS_WAIT_S)
        # Relocate the live transform onto the ring before the blast. Keep y (the floor height the spawn copied).
        self.write(unit + RING_UNIT_POS, struct.pack("<3f", x, y, z))
        if kind == "flash":
            if self.call(0x18F29C0, unit, self.player, born, self.generation) != 1:
                raise Unavailable("native explosion transition not confirmed")
            # The call's 1 is the confirmation the single flash (flash_now) is live-verified by. The +0x28A0 flag is
            # the RE5 effect's own and RE6 1.0.2 does not write it: live 2026-11-11 a ring aborted after its first
            # flash had visibly detonated (the screen was filled with the bloom) because this read was 0. Keep it as
            # evidence in the receipt, never as the blast's confirmation.
            flagged = self.rd(unit + 0x28A0, 1) == b"\x01"
            return {"index": index, "projectile_generation": born, "pos": [round(x, 1), round(y, 1), round(z, 1)],
                    "explosion_flag": flagged}
        carried = self.q(unit)                       # the class this allocation actually carries, not a table's
        if self.call(CLASSES.DETONATE_CLASS[0], unit, self.player, born, self.generation, carried, timeout=CLASS_SPAWN_TIMEOUT_S) != 1:
            raise Unavailable(f"native {kind} explosion transition not confirmed")
        return {"index": index, "kind": kind, "projectile_generation": born,
                "pos": [round(x, 1), round(y, 1), round(z, 1)], "class_vtable": hex(carried)}

    def grenade_ring(self, kind="flash", *, count=None, radius_cm=None, inner_cm=None, ripple_ms=None, expand=None,
                     allow_unverified=False):
        """Spawn `count` grenades in a ring around the player and detonate them in a quick ripple.

        kind="flash" reuses the live-verified native path; "hand" and "incendiary" use the parameterised class pair
        and are only reachable with `allow_unverified` (a research probe taking their first live receipt) until each
        has one - the queue and the PiP see only the verified kinds. The ring grows outward from the player (expand)
        to a final radius_cm (default 10 grenades, ~6 m). The ring is kept at least RING_SELF_CLEAR_CM out whatever
        the caller asks; health is read back and reported. The receipt is confirmed only if every requested grenade
        detonated; a partial ring is reported uncertain and is never replayed.
        """
        kind = (kind or "flash").lower()
        if kind not in RING_KINDS:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        if kind not in RING_VERIFIED_KINDS and not allow_unverified:
            raise Unavailable(RING_KIND_REFUSED.get(kind, "grenade kind not verified"))
        spec = CLASSES.class_for(kind)
        d = ring_defaults()
        count = d["count"] if count is None else int(count)
        count = max(1, min(count, RING_COUNT_MAX))
        # A flash is harmless up close; a hand or incendiary grenade is not. The ring's default inner radius (150 cm)
        # and self-clear (250 cm) were sized for the verified flash, so an explosive kind gets a floor of its own -
        # otherwise the first grenades of a default ring would detonate inside his own blast and the receipt would be
        # a self-damage one. The clamp is reported in the receipt so nobody has to guess what the ring actually did.
        floor_cm = RING_SELF_CLEAR_CM if kind == "flash" else RING_EXPLOSIVE_CLEAR_CM
        radius_cm = d["radius_cm"] if radius_cm is None else float(radius_cm)
        radius_cm = max(floor_cm, min(radius_cm, RING_RADIUS_MAX_CM))
        inner_cm = d["inner_cm"] if inner_cm is None else float(inner_cm)
        inner_cm = max(floor_cm if kind != "flash" else 0.0, min(inner_cm, radius_cm))
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
            if spec.item not in R.inventory_items(self, self.player):
                raise Unavailable(f"{kind} resources are not loaded for this character")
            hp_before = struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
            started = time.monotonic()
            grenades, abort, attached = [], None, False
            try:
                attached = True
                self.attach()
                if kind != "flash":
                    self._ensure_image(CLASSES.SPAWN_CLASS)
                    self._ensure_image(CLASSES.DETONATE_CLASS)
                for i in range(count):
                    self.check()
                    # Re-read his position each grenade: he keeps playing while the ring blooms.
                    px, py, pz = struct.unpack("<3f", self.rd(self.player + R.P_POS, 12))
                    angle = 2.0 * math.pi * i / count
                    r = radius_cm if not expand or count == 1 else inner_cm + (radius_cm - inner_cm) * i / (count - 1)
                    try:
                        grenades.append(self._ring_one(px + r * math.cos(angle), py, pz + r * math.sin(angle), i,
                                                       kind))
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
                effect = "native_flash_ring" if kind == "flash" else f"native_{kind}_ring"
                return {"state": "confirmed", "verified": True, "effect": effect, **receipt}
            if abort is not None:
                self.failed, self.recoverable = True, True
            receipt["reason"] = abort or "the ring did not complete"
            return {"state": "failed" if detonated == 0 else "uncertain", "verified": False, **receipt}

    def grenade_scatter(self, kind="random", *, count=None, toward=None, spread_deg=None, min_cm=None, max_cm=None,
                        gap_ms=None, safe_cm=None, rng=None, kinds=None):
        """A scatter barrage (operator 2026-11-10 ~07:00: "spray a scatter shot of grenades from his postion at threats
        at will ... a rapid barrage of random grenades ... without equipping it on his character ... sprayed like a
        scatterhsot whenever the going gets tough"): `count` rounds, each a native grenade set off at a random point
        of a cone from him toward the threats (`toward`: [(x, z)], else the living ones on his floor within max_cm,
        else his facing) - SCATTER_SPREAD_DEG either side, near to far, about chest height - SCATTER_GAP_MS apart.
        Each round is the ring's verified step (spawn, moved onto its point, the explosion transition): nothing is
        equipped and his gun stays in his hand. kind "random" draws each round from SCATTER_KINDS (only the verified
        ones: the flash today; the launcher's rounds are not identified); `kinds` narrows that draw for one barrage
        (the rule's flash cap leaves the flash out of a mixed draw inside the minute, checkpoint D) and every kind
        must be in SCATTER_KINDS; an explosive kind keeps every point past safe_cm (his learned reach) and the ring's
        600 cm floor, the flash keeps FLASH_PLACE_MIN_CM (400 cm) from him. A partial barrage is uncertain and never
        replayed."""
        import random as _random
        kind = (kind or "random").lower()
        if kind != "random" and kind not in RING_KINDS:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        if kind != "random" and kind not in RING_IMPLEMENTED_KINDS:
            raise Unavailable(RING_KIND_REFUSED.get(kind, "grenade kind not verified"))
        if kinds is not None:
            if kind != "random":
                raise Unavailable("a barrage of one explicit kind cannot also narrow its draw")
            kinds = tuple(str(k).lower() for k in kinds)
            if not kinds or any(k not in SCATTER_KINDS for k in kinds):
                raise Unavailable(f"this build's barrage cannot draw {kinds!r} (verified: {SCATTER_KINDS})")
        draw = (kinds or SCATTER_KINDS) if kind == "random" else (kind,)
        rng = rng or _random.Random()
        count = max(1, min(int(SCATTER_COUNT_DEFAULT if count is None else count), SCATTER_COUNT_MAX))
        spread = math.radians(float(SCATTER_SPREAD_DEG if spread_deg is None else spread_deg))
        lo = max(RING_SELF_CLEAR_CM, float(SCATTER_MIN_CM if min_cm is None else min_cm))
        hi = max(lo, min(float(SCATTER_MAX_CM if max_cm is None else max_cm), RING_RADIUS_MAX_CM))
        gap = gap_ms or SCATTER_GAP_MS
        # (checkpoint 0.2/0.3) No round may land inside its own blast: the flash keeps FLASH_PLACE_MIN_CM from him,
        # an explosive kind keeps the ring's 600 cm floor and, past it, his learned reach plus one centimetre.
        flash_floor = max(lo, flash_place_min_cm())
        explosive_floor = max(lo, RING_EXPLOSIVE_CLEAR_CM, float(safe_cm or 0.0) + SCATTER_SAFE_CM)
        floors = {"flash": round(flash_floor, 1), "explosive": round(explosive_floor, 1)}
        floor_cm = min(flash_floor if k == "flash" else explosive_floor for k in draw)
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
            if kind == "random" and kinds is None:
                # checkpoint A3: a random barrage draws only the verified kinds whose resources are loaded for this
                # character - a missing hand grenade must not refuse a flash barrage (and vice versa)
                loaded = tuple(k for k in SCATTER_KINDS
                               if CLASSES.class_for(k).item in R.inventory_items(self, self.player))
                if not loaded:
                    raise Unavailable(f"none of this build's barrage kinds ({', '.join(SCATTER_KINDS)}) has its "
                                      f"resources loaded for this character")
                draw = loaded
                floor_cm = min(flash_floor if k == "flash" else explosive_floor for k in draw)
            kinds_used = draw if kind == "random" else (kind,)
            for used in kinds_used:
                if CLASSES.class_for(used).item not in R.inventory_items(self, self.player):
                    raise Unavailable(f"{used} resources are not loaded for this character")
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
            rounds, abort, attached = [], None, False
            try:
                attached = True
                self.attach()
                if any(k != "flash" for k in (draw if kind == "random" else (kind,))):
                    self._ensure_image(CLASSES.SPAWN_CLASS)
                    self._ensure_image(CLASSES.DETONATE_CLASS)
                for i in range(count):
                    self.check()
                    this = rng.choice(draw) if kind == "random" else kind
                    # + SCATTER_SAFE_CM: the point is built with sin/cos, so the *measured* distance must stay past
                    # the floor the receipt reports, not exactly on it.
                    near = (flash_floor if this == "flash" else explosive_floor) + SCATTER_SAFE_CM
                    if hi < near:
                        hi = near                       # the far bound follows the floor: placement and receipt agree
                    d = near + (hi - near) * (i + rng.random()) / count   # near to far, each a step out
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
                if attached:
                    self.detach_completed()
            try:
                hp_after = struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
            except (OSError, struct.error):
                hp_after = None
            receipt = {"op": "grenade_scatter", "kind": kind, "requested": count, "detonated": len(rounds),
                       "kinds": sorted({r["kind"] for r in rounds}),
                       **({"probe": True} if kind not in RING_VERIFIED_KINDS and kind != "random" else {}),
                       "axis_deg": round(math.degrees(axis), 1), "spread_deg": round(math.degrees(spread), 1),
                       "near_cm": round(floor_cm, 1), "far_cm": round(hi, 1), "floor_cm": round(floor_cm, 1),
                       "floors_cm": floors, "rounds": rounds,
                       "hp_before": hp_before, "hp_after": hp_after,
                       "self_damage": (hp_before - hp_after) if isinstance(hp_after, int) else None,
                       "player_generation": self.generation,
                       "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
            if len(rounds) == count and abort is None:
                return {"state": "confirmed", "verified": True, "effect": "native_flash_scatter", **receipt}
            if abort is not None:
                self.failed, self.recoverable = True, True
            receipt["reason"] = abort or "the barrage did not complete"
            return {"state": "failed" if not rounds else "uncertain", "verified": False, **receipt}

    def _ensure_image(self, image):
        """One more pinned image into the zero padding (install() refuses anything else), the process stopped for it
        only the first time; its bytes checked against the pinned digest first."""
        at, name, size, digest = image
        data = CLASSES.image_bytes(name)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise Unavailable(f"native {name} asset checksum mismatch")
        if self.rd(self.base + at, size) != data:
            self.stopped(lambda: self.install(self.base + at, data))
        if self.rd(self.base + at, size) != data:
            raise Unavailable(f"native {name} installation unconfirmed")

    def drop_bomb(self, at=None, *, wait_s=0.5):
        """A remote bomb dropped at `at` (x, y, z; default his feet) already lying placed and armed - no throw, no
        animation, no remote in his hand (spawn_bomb.c). Verified: the unit is a uWp1097 owned by him, its action the
        placed one (cWpAction_wp_act_setting) within wait_s, and his detonator flag set. One call = one bomb, never
        replayed. -> {state, verified, op: bomb_drop, unit, generation, pos, armed, elapsed_ms}."""
        with self.lock:
            self.ready()
            if process_identity(self.pid) != self.identity:
                raise Unavailable("emulator process changed")
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
            _idx, _item, bomb = R.inventory_state(self, self.player)
            if bomb is None:
                raise Unavailable("remote bomb resources are not loaded for this character")
            x, y, z = at if at is not None else struct.unpack("<3f", self.rd(self.player + R.P_POS, 12))
            started, attached = time.monotonic(), False
            try:
                attached = True
                self.attach()
                self._ensure_image(SPAWN_BOMB)
                bits = [struct.unpack("<I", struct.pack("<f", float(v)))[0] for v in (x, y, z)]
                unit = self.call(SPAWN_BOMB[0], self.player, *bits)
                if not R.ptr_ok(unit):
                    raise Unavailable("native remote bomb allocation refused")
                born = self.w(unit + 0x1308)

                def placed():
                    if self.q(unit) != self.base + BOMB_VTABLE or self.q(unit + 0x1300) != self.player:
                        raise AllocationLost(f"remote bomb allocation changed: unit={unit:#x}")
                    return R.unit_action(self, unit) == BOMB_SETTING
                until = time.monotonic() + wait_s
                while not placed():
                    if time.monotonic() >= until:
                        raise Uncertain("the dropped bomb's placed action did not show; not replayed")
                    time.sleep(0.005)
                armed = bool(self.rd(self.player + P_FLAGS_ARMED_BYTE, 1)[0] & ARMED_BIT)
                if not armed:
                    raise Uncertain("the detonator flag did not read back set after the drop")
                return {"state": "confirmed", "verified": True, "op": "bomb_drop", "unit": unit, "generation": born,
                        "pos": [round(v, 1) for v in (x, y, z)], "armed": True, "player_generation": self.generation,
                        "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
            except Exception:
                self.failed, self.recoverable = True, True
                raise
            finally:
                if attached:
                    self.detach_completed()

    def drop_bomb_ring(self, count=4, radius_cm=200.0, *, wait_s=0.5):
        """`count` remote bombs ejected from his body in a ring around him, each already lying placed and armed -
        no throw, no remote in his hand, no animation (spawn_bomb.c through `drop_bomb`).

        The operator 2026-11-11: "eject them out of their body in sets of four in a ring around them ... drop massive
        quantities of them and then detonate them remotely". The ring is on his floor at `radius_cm` (the native
        spawn takes a point; nothing is thrown). A partial ring is `uncertain` (some units are placed; never replayed
        as a whole). -> {state, op: bomb_ring, requested, placed, radius_cm, units, failures, elapsed_ms}.
        """
        wanted = max(1, min(int(count or 4), 16))
        radius = max(0.0, min(float(radius_cm if radius_cm is not None else 200.0), 600.0))
        with self.lock:
            player, _generation = self.ready()
            x, y, z = struct.unpack("<3f", self.rd(player + R.P_POS, 12))
            started = time.monotonic()
            units, failures = [], []
            for i in range(wanted):
                angle = 2 * math.pi * (i / wanted) + (math.pi / 4 if wanted == 4 else 0.0)
                at = (x + radius * math.cos(angle), y, z + radius * math.sin(angle))
                try:
                    receipt = self.drop_bomb(at, wait_s=wait_s)
                except Exception as exc:                     # noqa: BLE001 - a refused bomb reports the ring partial
                    failures.append(f"{type(exc).__name__}: {exc}"[:200])
                    break
                units.append({"unit": receipt.get("unit"), "pos": receipt.get("pos")})
            state = "confirmed" if len(units) == wanted else ("uncertain" if units else "failed")
            return {"state": state, "op": "bomb_ring", "requested": wanted, "placed": len(units),
                    "radius_cm": radius, "units": units, "failures": failures,
                    "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}


def grenade_scatter_now(ad, kind="random", **kw) -> dict:
    """The scatter barrage on the session's one native controller (the bot's rule, the PiP's grenade_scatter). Never
    raises: a refusal is a receipt with its reason."""
    started = time.monotonic()
    try:
        with _CREATE_LOCK:
            ctl = getattr(ad, "_re6_native_flash", None)
            if ctl is None:
                ctl = Controller(ad)
                ad._re6_native_flash = ctl
        return ctl.grenade_scatter(kind, **kw)
    except Uncertain as exc:
        state, reason = "uncertain", exc
    except (Unavailable, ValueError, TypeError, OSError) as exc:
        state, reason = "unavailable", exc
    except Exception as exc:                                  # noqa: BLE001
        state, reason = "failed", exc
    return {"op": "grenade_scatter", "state": state, "verified": False, "kind": kind, "detonated": 0,
            "reason": (str(reason) or type(reason).__name__)[:300],
            "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}


def bomb_drop_now(ad, at=None) -> dict:
    """The bot's / the PiP's instant remote-bomb drop on the session's one native controller. Never raises: a refusal
    is a receipt with its reason (state unavailable / uncertain / failed)."""
    started = time.monotonic()
    try:
        with _CREATE_LOCK:
            ctl = getattr(ad, "_re6_native_flash", None)
            if ctl is None:
                ctl = Controller(ad)
                ad._re6_native_flash = ctl
        if not ctl.recover_completed_call() and ctl.failed:
            raise Unavailable("native controller awaits recovery after an uncertain operation")
        return ctl.drop_bomb(at)
    except Uncertain as exc:
        state, reason = "uncertain", exc
    except (Unavailable, ValueError, TypeError, OSError) as exc:
        state, reason = "unavailable", exc
    except Exception as exc:                                  # noqa: BLE001 - the bot never dies on a native receipt
        state, reason = "failed", exc
    return {"op": "bomb_drop", "state": state, "verified": False, "reason": (str(reason) or type(reason).__name__)[:300],
            "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}


def bomb_ring_now(ad, count=4, radius_cm=200.0, *, wait_s=0.5) -> dict:
    """The bot's / the PiP's ring of instant remote bombs on the session's one native controller (drop_bomb_ring).
    Never raises: a refusal is a receipt with its reason (state unavailable / uncertain / failed)."""
    started = time.monotonic()
    try:
        with _CREATE_LOCK:
            ctl = getattr(ad, "_re6_native_flash", None)
            if ctl is None:
                ctl = Controller(ad)
                ad._re6_native_flash = ctl
        if not ctl.recover_completed_call() and ctl.failed:
            raise Unavailable("native controller awaits recovery after an uncertain operation")
        return ctl.drop_bomb_ring(count, radius_cm, wait_s=wait_s)
    except Uncertain as exc:
        state, reason = "uncertain", exc
    except (Unavailable, ValueError, TypeError, OSError) as exc:
        state, reason = "unavailable", exc
    except Exception as exc:                                  # noqa: BLE001 - the bot never dies on a native receipt
        state, reason = "failed", exc
    return {"op": "bomb_ring", "state": state, "verified": False, "requested": count, "placed": 0,
            "reason": (str(reason) or type(reason).__name__)[:300],
            "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}


def bomb_detonate_now(ad, snap=None) -> dict:
    """Every remote bomb of his lying placed set off through the detonator's own flag (re6_switch_mods.detonate):
    no animation, no remote in his hand, no pad. Never raises: a refusal is a receipt with its reason."""
    from . import re6_switch_mods
    try:
        receipt = re6_switch_mods.detonate(ad, snap=snap)
    except Exception as exc:                                  # noqa: BLE001 - the bot never dies on a native receipt
        return {"op": "bomb_detonate", "verified": False, "count": 0,
                "reason": f"{type(exc).__name__}: {exc}"[:300]}
    return receipt if isinstance(receipt, dict) else {"op": "bomb_detonate", "verified": False, "count": 0}


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
