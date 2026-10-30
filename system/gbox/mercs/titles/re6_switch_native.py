"""RE6 061D2A06 native flash, executed on the player's game thread.

No pad events, inventory writes, fuse wait, or weapon changes. The checked-in
ARM64 sources and standalone ABI tests reproduce the live-tested code. See
docs/research/re6-native-flash.md for evidence and the resource-loading limit.
"""
from __future__ import annotations

import hashlib
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
        self.lock = threading.Lock()
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

    def check(self):
        if process_identity(self.pid) != self.identity or self.ad._guest()[0] != self.pid:
            raise Unavailable("emulator process changed")
        if self.rd(self.base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
            raise Unavailable("RE6 executable changed")
        if hasattr(self, "player"):
            if self.q(self.sp + R.P_FIRST) != self.player or self.w(self.player + 0x1308) != self.generation:
                raise Unavailable("player allocation changed")

    def write(self, at, data):
        self.check()
        self.ad.write_memory(at, data)

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
        self.write(self.heap + 0xA8, struct.pack("<I", 1))
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
            self.check()
            self.validate_heap()
            if self.w(self.heap + 0xA8) != 3 or self.q(self.manager) != self.base + VT:
                return False
            self.failed = self.recoverable = False
            return True

    def flash(self):
        with self.lock:
            if getattr(self.ad, "paused", False):
                raise Unavailable("session is paused")
            if self.failed:
                raise Unavailable("native controller awaits recovery after an uncertain operation")
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
            except Exception as exc:
                self.failed = True
                self.recoverable = isinstance(exc, AllocationLost)
                raise
            finally:
                if attached:
                    def detach():
                        current = self.q(self.manager)
                        if current in (self.heap, self.base + TEMP):
                            self.write(self.manager, struct.pack("<Q", self.base + VT))
                    detach()


def flash_now(ad):
    """One call = one native effect. Callers own durable request deduplication."""
    with _CREATE_LOCK:
        ctl = getattr(ad, "_re6_native_flash", None)
        if ctl is None:
            ctl = Controller(ad)
            ad._re6_native_flash = ctl
    return ctl.flash()
