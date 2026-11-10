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

# Grenade ring (operator 2026-11-10: "spam throwing grenades" at the enemies a ring of grenades deals with best).
# Two more pinned images in the same zero padding after `detonate` (main+0x18F2AA8..0x18F3000, the executable
# page's end): spawn_at.c = spawn.c for a chosen grenade class and world point, detonate_at.c = detonate.c for that
# class with the ring point's x/z re-set on the game thread just before the explosion request. Installed only when a
# ring is first requested (attach(CODE + RING_CODE)); the flash button keeps its own three images.
SPAWN_AT, DETONATE_AT = 0x18F2AC0, 0x18F2C00
RING_CODE = (
    (SPAWN_AT, "spawn_at", 304, "aa3708c69bbceb6ebaa4e3f93b38096c38844a9c7bfcf4c1caaefde221e88ab8"),
    (DETONATE_AT, "detonate_at", 320, "854ec6d6b61d502203eee3777dfcdbce6467ca5e7ace8cac3695d0b750c7a739"),
)
THROW_VT, BOMB_VT = 0x288C9A0, 0x288C868     # cWpAction_wp_act_throw / cWpAction_wp_act_bomb (action 7 / 10)
# kind -> (the item it is on his wheel, the thrown class's DTI, its vtable, the class). uWpBomb's setup
# (main+0xF84FF4: slot 6) stores (DTI id >> 8) & 0xFFFF into +0x3864 as the kind, and the static initialiser gives the
# ids 0x07011100 (main+0x13DB84) + 0x201 uWp1091 / 0x301 uWp1093 / 0x401 uWp1095 / 0x501 uWp1097: 0x113 hand,
# 0x114 incendiary, 0x115 flash, 0x116 the remote bomb (never spawned here). Statically confirmed, 2026-11-10.
GRENADES = {
    "flash": (0x115, 0x2951500, 0x284AEB8, "uWp1095"),
    "hand": (0x113, 0x2951490, 0x284B788, "uWp1091"),
    "incendiary": (0x114, 0x29514C8, 0x284B328, "uWp1093"),
}
RING_KINDS = tuple(GRENADES)
# The flash's class, spawn and explosion transition are live-verified (re6-native-flash.md); the hand and incendiary
# classes share the same uWpBomb code (their vtables differ only in getDTI) but their explosions have not been seen
# live yet. Add a kind here only after a live receipt + frames; allow_unverified=True runs one for that proof.
RING_VERIFIED_KINDS = ("flash",)
RING_COUNT_DEFAULT, RING_COUNT_MAX = 10, 16
# Radii in world centimetres, the RE5 ring's: ten grenades blooming from 1.5 m out to 6 m. An explosive kind is never
# placed nearer him than its clearance (his own hand grenade / fire can hurt him); hp_before/after are read back.
RING_RADIUS_DEFAULT_CM, RING_RADIUS_MAX_CM, RING_INNER_DEFAULT_CM = 600.0, 2500.0, 150.0
RING_SELF_CLEAR_CM = {"flash": 250.0, "hand": 400.0, "incendiary": 400.0}
RING_RIPPLE_MS_MAX = 200.0
# One ring is bounded in time: no native call is published with less than RING_CALL_MIN_S left, and every wait
# (bootstrap, call completion, initialization) stops at the deadline. Unfinished calls are reported, never replayed.
RING_DEADLINE_S, RING_DEADLINE_MAX_S, RING_CALL_MIN_S, RING_INIT_WAIT_S = 2.5, 2.9, 0.12, 0.5


def f32_bits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def ring_geometry(kind, count=None, radius_cm=None, inner_cm=None, expand=None):
    """The ring's (count, radius, inner radius, expand), clamped: 1..16 grenades, never nearer him than the kind's
    clearance, at most 25 m out. Non-numeric or non-finite values refuse."""
    def number(v, default):
        if v is None:
            return float(default)
        if type(v) not in (int, float) or not math.isfinite(v):
            raise Unavailable("ring radii must be finite numbers")
        return float(v)
    if count is not None and (type(count) is not int or count < 1):
        raise Unavailable("ring count must be a positive integer")
    count = min(RING_COUNT_DEFAULT if count is None else count, RING_COUNT_MAX)
    clear = RING_SELF_CLEAR_CM[kind]
    radius = max(clear, min(number(radius_cm, RING_RADIUS_DEFAULT_CM), RING_RADIUS_MAX_CM))
    inner = number(inner_cm, RING_INNER_DEFAULT_CM)
    inner = max(clear if kind != "flash" else 0.0, min(inner, radius))
    return count, radius, inner, True if expand is None else bool(expand)


def ring_points(centre, count, radius, inner, expand):
    """Grenade i at angle 2*pi*i/count, its radius growing from inner to radius (expand: the bloom), on his floor y."""
    cx, cy, cz = centre
    out = []
    for i in range(count):
        angle = 2.0 * math.pi * i / count
        r = radius if not expand or count == 1 else inner + (radius - inner) * i / (count - 1)
        out.append((cx + r * math.cos(angle), cy, cz + r * math.sin(angle)))
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

    _deadline = None    # a bounded operation's (the grenade ring's) monotonic deadline: no wait outlives it

    def wait(self, predicate, timeout=1.0):
        until = time.monotonic() + timeout
        if self._deadline is not None:
            until = min(until, self._deadline)
        while time.monotonic() < until:
            self.check()
            value = predicate()
            if value:
                return value
            time.sleep(.002)
        raise Uncertain("native completion uncertain; request will not be replayed")

    def attach(self, images=CODE):
        entries = struct.pack("<11Q", *(self.base + x for x in VT_ENTRIES))
        if self.rd(self.base + VT, len(entries)) != entries or self.q(self.manager) != self.base + VT:
            raise Unavailable("action manager is modified or unsupported")
        if self.q(self.manager + 8) != self.player:
            raise Unavailable("action manager owner mismatch")
        assets = []
        for off, name, size, digest in images:
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

    # --- the grenade ring ---------------------------------------------------------------------------------------

    def ring_capable(self):
        return True

    def _kind_status(self, kind, carried, error="", allow_unverified=False):
        item, _dti, _vt, cls = GRENADES[kind]
        if error:
            return {"available": False, "reason": error}
        if kind not in RING_VERIFIED_KINDS and not allow_unverified:
            return {"available": False, "reason": f"a {kind}-grenade ring ({cls}, identified statically) is not yet "
                                                  f"live-verified on this build"}
        if item not in carried:
            return {"available": False, "reason": f"{kind}-grenade resources are not loaded this round: the "
                                                  f"character does not carry item {item:#x}"}
        return {"available": True, "reason": ""}

    def grenade_kinds(self):
        """The ring chooser's rows (flash, hand, incendiary), read-only and never raising: a kind is available only
        when it is verified and this round's character carries it (its resources are loaded)."""
        try:
            player, _ = self.ready()
            carried, error = R.inventory_items(self, player), ""
        except (RuntimeError, OSError, ValueError, struct.error) as exc:
            carried, error = {}, str(exc)[:200] or type(exc).__name__
        return [{"kind": kind, **self._kind_status(kind, carried, error)} for kind in RING_KINDS]

    def _bind_player(self):
        """flash()'s player binding: the current living player, his generation and action manager (the fence)."""
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

    def _grenade_state(self, g, vt):
        unit = g["unit"]
        if (self.q(unit) != self.base + vt or self.w(unit + 0x1308) != g["born"] or
                self.q(unit + 0x1300) != self.player):
            return "lost"
        act = self.q(unit + 0x13F0)
        avt = self.q(act) if R.ptr_ok(act) else 0
        return "thrown" if avt == self.base + THROW_VT else "exploding" if avt == self.base + BOMB_VT else "init"

    def _await_thrown(self, g, vt, until):
        """Its native throw action initialized (the state detonate_at accepts), it already exploding, or lost."""
        stop = min(until - RING_CALL_MIN_S, time.monotonic() + RING_INIT_WAIT_S)
        while True:
            self.check()
            state = self._grenade_state(g, vt)
            if state != "init":
                return state
            if time.monotonic() >= stop:
                return "uninitialized"
            time.sleep(.002)

    def _hp(self):
        try:
            return struct.unpack("<h", self.rd(self.player + R.P_HP, 2))[0]
        except (OSError, ValueError, struct.error):
            return None

    def grenade_ring(self, kind="flash", *, count=None, radius_cm=None, inner_cm=None, ripple_ms=None, expand=None,
                     deadline_s=None, allow_unverified=False):
        """Ten grenades of `kind` in a ring around the player that blooms out (1.5 m -> 6 m), then set off in order.

        Phase 1 spawns each at its ring point (spawn_at: the verified flash spawn for that class and point, one per
        game frame). Phase 2 sets each off once its native throw action is initialized (detonate_at, x/z re-set to
        the ring point). A grenade whose own fuse/contact check already exploded counts as detonated ("exploding").
        Preconditions (kind, verification, resources, a living player) raise Unavailable before any game write.
        Once native work starts, a receipt is always returned: confirmed only when every requested grenade's
        explosion was read natively; otherwise uncertain (some spawned) or failed (none) - never replayed.
        The whole ring, including a first install / bootstrap, ends by deadline_s (default 2.5 s, at most 2.9 s).
        """
        started = time.monotonic()
        kind = kind.lower() if isinstance(kind, str) else kind
        if kind not in GRENADES:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        count, radius, inner, expand = ring_geometry(kind, count, radius_cm, inner_cm, expand)
        if ripple_ms is not None and (type(ripple_ms) not in (int, float) or not math.isfinite(ripple_ms)):
            raise Unavailable("ripple_ms must be a finite number")
        ripple = max(0.0, min(float(ripple_ms or 0.0), RING_RIPPLE_MS_MAX)) / 1000.0
        if deadline_s is not None and (type(deadline_s) not in (int, float) or not math.isfinite(deadline_s)):
            raise Unavailable("deadline_s must be a finite number")
        budget = RING_DEADLINE_S if deadline_s is None else max(0.0, min(float(deadline_s), RING_DEADLINE_MAX_S))
        until = started + budget
        if budget < RING_CALL_MIN_S:
            raise Unavailable("no time left for a native grenade ring")
        if not self.lock.acquire(timeout=max(0.0, until - RING_CALL_MIN_S - time.monotonic())):
            raise Unavailable("native controller is busy with another operation")
        try:
            return self._grenade_ring(kind, count, radius, inner, expand, ripple, started, until, budget,
                                      allow_unverified)
        finally:
            self.lock.release()

    def _grenade_ring(self, kind, count, radius, inner, expand, ripple, started, until, budget, allow_unverified):
        item, dti, vt, cls = GRENADES[kind]
        self.ready()                     # recovers a completed earlier call; refuses paused / dead / no round
        self._bind_player()
        status = self._kind_status(kind, R.inventory_items(self, self.player), "", allow_unverified)
        if not status["available"]:
            raise Unavailable(status["reason"])
        centre = struct.unpack("<3f", self.rd(self.player + R.P_POS, 12))
        if not all(math.isfinite(v) and abs(v) < 1e7 for v in centre):
            raise Unavailable("player position is invalid")
        points = ring_points(centre, count, radius, inner, expand)
        hp_before = self._hp()
        grenades, abort, uncertain, timings = [], None, False, {}
        mark = started
        attached = False
        self._deadline = until
        try:
            attached = True
            self.attach(CODE + RING_CODE)
            timings["attach"], mark = round(1000 * (time.monotonic() - mark), 1), time.monotonic()
            for i, (x, y, z) in enumerate(points):
                if until - time.monotonic() < RING_CALL_MIN_S:
                    abort = "deadline reached before every grenade was spawned"
                    break
                unit = self.call(SPAWN_AT, self.player, self.base + dti, f32_bits(x), f32_bits(y), f32_bits(z))
                if not R.ptr_ok(unit):
                    abort = "native grenade allocation refused"
                    break
                grenades.append({"index": i, "unit": unit, "born": self.w(unit + 0x1308), "pos": (x, y, z),
                                 "state": "spawned"})
                if ripple and i + 1 < count:
                    time.sleep(min(ripple, max(0.0, until - RING_CALL_MIN_S - time.monotonic())))
            timings["spawn"], mark = round(1000 * (time.monotonic() - mark), 1), time.monotonic()
            for g in grenades:
                if until - time.monotonic() < RING_CALL_MIN_S:
                    abort = abort or "deadline reached before every grenade was set off"
                    break
                state = self._await_thrown(g, vt, until)
                if state != "thrown":
                    g["state"] = state           # exploding on its own, lost, or uninitialized: no request made
                    continue
                x, _y, z = g["pos"]
                result = self.call(DETONATE_AT, g["unit"], self.player, g["born"], self.generation,
                                   self.base + vt, f32_bits(x), f32_bits(z))
                g["state"] = {1: "detonated", 2: "exploding"}.get(result, "refused")
            timings["detonate"] = round(1000 * (time.monotonic() - mark), 1)
        except Exception as exc:          # noqa: BLE001 - every native outcome becomes a receipt, never a replay
            # Same rule as flash(): once anything may have been published, a new request is accepted only after the
            # mailbox is verified complete. A refusal before the first bootstrap (no private mailbox yet, nothing
            # spawned, not a timeout) published nothing and must not leave the controller awaiting recovery.
            uncertain = self.heap is not None or bool(grenades) or isinstance(exc, Uncertain)
            if uncertain:
                self.failed = self.recoverable = True
            abort = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            self._deadline = None
            if attached:
                try:
                    self.detach_completed()
                except Exception as exc:  # noqa: BLE001 - the player changed: recovery restores it later
                    self.failed = self.recoverable = True
                    abort = abort or f"detach: {exc}"[:200]
        hp_after = self._hp()
        exploded = [g for g in grenades if g["state"] in ("detonated", "exploding")]
        receipt = {
            "op": "grenade_ring", "kind": kind, "class": cls, "requested": count, "spawned": len(grenades),
            "detonated": len(exploded), "natural": sum(g["state"] == "exploding" for g in grenades),
            "centre": [round(v, 1) for v in centre], "radius_cm": round(radius, 1), "inner_cm": round(inner, 1),
            "expand": expand, "player_generation": self.generation, "hp_before": hp_before, "hp_after": hp_after,
            "self_damage": hp_before - hp_after if isinstance(hp_before, int) and isinstance(hp_after, int) else None,
            "grenades": [{"index": g["index"], "state": g["state"], "generation": g["born"],
                          "pos": [round(g["pos"][0], 1), round(g["pos"][2], 1)]} for g in grenades],
            "deadline_s": round(budget, 2), "timings_ms": timings,
            "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
        if abort is None and len(exploded) == count:
            return {"state": "confirmed", "verified": True, "effect": f"native_{kind}_ring", **receipt}
        receipt["reason"] = abort or "not every grenade's explosion was read"
        return {"state": "uncertain" if grenades or uncertain else "failed", "verified": False, **receipt}


def flash_now(ad):
    """One call = one native effect. Callers own durable request deduplication."""
    with _CREATE_LOCK:
        ctl = getattr(ad, "_re6_native_flash", None)
        if ctl is None:
            ctl = Controller(ad)
            ad._re6_native_flash = ctl
    return ctl.flash()


def grenade_ring_now(ad, kind="hand", radius_cm=None, *, count=None, deadline_s=None, allow_unverified=False) -> dict:
    """The bot's grenade ring, safe from a background thread: one call = one ring, never replayed.

    Uses the session's one serialized native controller (ad._re6_native_flash under _CREATE_LOCK, the object
    interventions.native_controller shares with the UI), so the bot and a viewer never race the mailbox. Never raises
    and never blocks past the deadline (default 2.5 s, at most 2.9 s): a busy controller, an unverified or unloaded
    kind, or no living player returns state "unavailable". The receipt always carries kind, state, spawned, detonated,
    elapsed_ms, centre and radius_cm (see Controller.grenade_ring for the rest).
    """
    started = time.monotonic()
    budget = RING_DEADLINE_S if deadline_s is None else deadline_s
    out = {"op": "grenade_ring", "kind": kind, "verified": False, "spawned": 0, "detonated": 0, "centre": None,
           "radius_cm": radius_cm}

    def done(state, exc):
        return {**out, "state": state, "reason": (str(exc) or type(exc).__name__)[:300],
                "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
    try:
        if type(budget) not in (int, float) or not math.isfinite(budget):
            raise Unavailable("deadline_s must be a finite number")
        budget = max(0.0, min(float(budget), RING_DEADLINE_MAX_S))
        if not _CREATE_LOCK.acquire(timeout=max(0.0, budget - RING_CALL_MIN_S)):
            raise Unavailable("native controller is being created by another thread")
        try:
            ctl = getattr(ad, "_re6_native_flash", None)
            if ctl is None:
                ctl = Controller(ad)
                ad._re6_native_flash = ctl
        finally:
            _CREATE_LOCK.release()
        if not callable(getattr(ctl, "grenade_ring", None)):
            raise Unavailable("this session's native controller has no grenade ring")
        return ctl.grenade_ring(kind, count=count, radius_cm=radius_cm, allow_unverified=allow_unverified,
                                deadline_s=budget - (time.monotonic() - started))
    except Uncertain as exc:
        return done("uncertain", exc)
    except (Unavailable, ValueError, TypeError, OSError) as exc:
        return done("unavailable", exc)
    except Exception as exc:              # noqa: BLE001 - the bot thread must never die on a native receipt
        return done("failed", exc)
