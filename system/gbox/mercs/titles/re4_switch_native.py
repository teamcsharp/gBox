"""RE4 Switch (82C2A04A21D3E0B850F273D4149C9003) native call harness.

The harness never rewrites an executed instruction and never changes a branch: it clones the player unit's vtable
into the vetted zero padding at `main+0x655880`, points that clone's slot `+0x20` (the unit base-class transform
virtual, `main+0x2B6420`, shared by every measured unit class) at the dispatcher, and stores the clone's address into
the player object's vtable pointer (`+0`). That single aligned 8-byte store is the whole trigger; the restore puts
the original pointer back. The dispatcher (`native/re4_82c2a04a/dispatch.S`) tail-calls the original transform every
entry, so the game runs normally while the harness is attached.

Private storage (the mailbox) is a proven-unused `.bss` page (`E3`): the cave is executable code in the RX segment,
an install target only, never guest-writable. `Controller(ad, mailbox=...)` refuses to attach without one.

The call surface: `call(off, *args)` publishes one request (target + up to seven arguments) into the mailbox and waits
for the dispatcher to complete it on the game thread; a timeout is `Uncertain` and the request is never replayed.
Any write into `main`'s `.text`/`.rodata` is refused - only `install()` into the verified cave can change bytes there.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import threading

from . import re4_switch as R, re6_switch_native as N
from ..native.re4_82c2a04a import code as CODE

Unavailable, Uncertain, AllocationLost = N.Unavailable, N.Uncertain, N.AllocationLost
process_identity = N.process_identity

CAVE_AT, CAVE_SIZE = CODE.CAVE_AT, CODE.CAVE_SIZE
CAVE_END = CODE.CAVE_END
CLONE_AT, CLONE_SIZE = CODE.CLONE_AT, CODE.CLONE_SIZE
ORIGINAL_TRANSFORM, SLOT_TRANSFORM = CODE.ORIGINAL_TRANSFORM, CODE.SLOT_TRANSFORM
MAILBOX, MAILBOX_SIZE = CODE.MAILBOX, CODE.MAILBOX_SIZE
STATE = CODE.STATE
DISPATCH = CODE.DISPATCH
#: End of the read-only image (`main` .text + .rodata; the header's own rodata end). Writes below this are refused.
CODE_END = 0xAE1BCC
CALL_TIMEOUT_S = 1.0

#: The flash blast (checkpoint F2 route (i)): `fn(obj)` reads the object's position at +0xA4 and starts the flash's
#: effects/sound/area attack. A zeroed fake object with that position is enough; +0x3CC must not read 0xD6 (the
#: ground/type check skips the effects then).
FLASH_BLAST = 0x2E4E50
FLASH_OBJECT_POS = 0xA4
FLASH_OBJECT_TYPE_BYTE = 0x3CC
OBJECT_SIZE = 0x400
SCRATCH_OFF = 0x100                    # the fake object, in the same proven page as the mailbox (E3)
#: The operator's placement rule for a flash (checkpoint F3), in RE4's millimetres.
FLASH_MIN_MM, FLASH_MAX_MM, FLASH_FROM_MM = 4000.0, 9000.0, 12000.0
#: The proven private page (set after E3's three-load watch passes; None means the harness cannot attach).
MAILBOX_AT: int | None = None


def verify_dispatch() -> bytes:
    """The pinned dispatcher image, checked against its digest (the bytes the controller installs)."""
    data = CODE.IMAGES["dispatch"]
    if len(data) != DISPATCH[2] or hashlib.sha256(data).hexdigest() != DISPATCH[3]:
        raise Unavailable("native dispatcher image checksum mismatch")
    return data


def is_code_address(base: int, at: int) -> bool:
    """True when `at` lies in `main`'s code/read-only image (where a guest write must never go)."""
    return base <= at < base + CODE_END


class Controller(N.Controller):
    def __init__(self, ad, *, mailbox: int | None = None):
        if os.name != "posix" or os.uname().machine.lower() not in ("aarch64", "arm64") or \
                getattr(ad, "address_mode", None) != "direct":
            raise Unavailable("the RE4 native harness requires Linux Switch NCE")
        self.ad = ad
        self.pid, _ = ad._guest()
        self.identity = process_identity(self.pid)
        self.lock = threading.RLock()
        self.base = R.module_base(self)
        if not self.base:
            raise Unavailable("unsupported RE4 executable")
        self.mailbox = MAILBOX_AT if mailbox is None else mailbox
        self.player = None
        self.original = None
        self.player_id = None
        self.request_generation = 0
        self.failed = False

    # ---- primitive guards ----------------------------------------------------------------------------------------------

    def check_build(self):
        if process_identity(self.pid) != self.identity or self.ad._guest()[0] != self.pid:
            raise Unavailable("emulator process changed")
        if self.rd(self.base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
            raise Unavailable("RE4 executable changed")

    def write(self, at, data):
        """A guest write. Refuses `main`'s `.text`/`.rodata`: only `install()` may touch the cave (and only there).

        The vtable-pointer store, the mailbox and every other write go to the heap or `.bss`; nothing this controller
        does can rewrite an instruction.
        """
        self.check()
        if is_code_address(self.base, at) or is_code_address(self.base, at + len(data) - 1):
            raise Unavailable("refusing a write into main's code or read-only data")
        return super().write(at, data)

    def install(self, at, data):
        """Install bytes only inside the vetted zero cave (the base class's memfd path still refuses nonzero bytes)."""
        if not (self.base + CAVE_AT <= at and at + len(data) <= self.base + CAVE_END):
            raise Unavailable("refusing to install outside the vetted cave")
        return super().install(at, data)

    # ---- the player and the trigger ------------------------------------------------------------------------------------

    def prepare(self):
        """The status path: no capability is advertised before the private page is proven (E3)."""
        if self.mailbox is None:
            raise Unavailable("no proven private storage for the RE4 harness (E3's three-load watch is pending)")

    def ready(self):
        self.check_build()
        if getattr(self.ad, "paused", False):
            raise Unavailable("session is paused")
        if self.attached():
            # While attached the unit carries the clone; identify it by its own id instead of its class vtable.
            unit = R.read_unit(self, self.player)
            if unit is None or unit.get("id") != self.player_id:
                raise Unavailable("the player unit changed while the harness is attached")
            return self.player
        unit = R.player_unit(self, self.base)
        if unit is None or not R.ptr_ok(unit.get("ptr")):
            raise Unavailable("no player unit in a live Mercenaries round")
        cls = unit["vtable"] - self.base
        if not (R.PLAYER_VTABLE_RANGE[0] <= cls < R.PLAYER_VTABLE_RANGE[1]) or cls % 8:
            raise Unavailable(f"the player's class {cls:#x} is not a unit class this harness supports")
        self.player, self.player_class, self.player_id = unit["ptr"], cls, unit.get("id")
        return self.player

    def attached(self) -> bool:
        return self.player is not None and self.original is not None and \
            self.q(self.player) == self.base + CLONE_AT

    def attach(self):
        """Build the clone, install dispatcher + clone into the cave, and publish the clone - one vtable store."""
        if self.attached():
            return
        self.ready()
        vt = self.q(self.player)
        if vt != self.base + self.player_class:
            raise Unavailable("the player's vtable changed while binding")
        entries = self.rd(vt, CODE.CLONE_ENTRIES * 8)
        if len(entries) != CODE.CLONE_ENTRIES * 8 or self.q(vt + SLOT_TRANSFORM) != self.base + ORIGINAL_TRANSFORM:
            raise Unavailable("the player's transform slot is not the pinned original")
        if self.mailbox is None:
            raise Unavailable("no proven private storage for the harness mailbox (E3's three-load watch is pending)")
        if not R.ptr_ok(self.mailbox) or self.mailbox % 8:
            raise Unavailable("the harness mailbox address is not an aligned guest address")
        clone = bytearray(entries)
        struct.pack_into("<Q", clone, SLOT_TRANSFORM, self.base + CAVE_AT)
        clone.extend(struct.pack("<Q", self.mailbox))
        assets = ((self.base + CAVE_AT, verify_dispatch()), (self.base + CLONE_AT, bytes(clone)))
        if any(self.rd(at, len(data)) != data for at, data in assets):
            self.stopped(lambda: [self.install(at, data) for at, data in assets])
        self.original = vt
        self.write(self.player, struct.pack("<Q", self.base + CLONE_AT))
        if not self.attached():
            raise Uncertain("the player's vtable did not take the clone")

    def detach(self):
        """Put the original vtable pointer back (the clone in the cave is only ever read)."""
        if self.player is None or self.original is None:
            return
        if self.q(self.player) == self.base + CLONE_AT:
            self.write(self.player, struct.pack("<Q", self.original))
        if self.q(self.player) != self.original:
            raise Uncertain("the player's vtable was not restored")

    # ---- the call surface ----------------------------------------------------------------------------------------------

    def call(self, off, *args, timeout=CALL_TIMEOUT_S):
        """One native call on the game thread: publish the request, wait for done, return x0. Never replays."""
        if not self.attached():
            raise Unavailable("the harness is not attached to the player")
        if self.mailbox is None:
            raise Unavailable("no harness mailbox")
        pending = self.w(self.mailbox + MAILBOX["state"])
        if pending not in (STATE["idle"], STATE["done"]):
            raise Unavailable("previous native call is incomplete; not replayed")
        if len(args) > 7:
            raise Unavailable("the harness passes at most seven arguments")
        self.request_generation = (self.request_generation + 1) & 0xFFFFFFFF
        generation = self.request_generation
        self.write(self.mailbox + MAILBOX["target"], struct.pack("<Q", self.base + off))
        self.write(self.mailbox + MAILBOX["args"], struct.pack("<7Q", *args, *([0] * (7 - len(args)))))
        self.write(self.mailbox + MAILBOX["generation"], struct.pack("<Q", generation))
        self.write(self.mailbox + MAILBOX["state"], struct.pack("<I", STATE["requested"]))
        self.wait(lambda: self.w(self.mailbox + MAILBOX["state"]) == STATE["done"], timeout)
        if self.q(self.mailbox + MAILBOX["generation"]) != generation:
            raise Uncertain("the mailbox generation changed under the call; the result is not trusted")
        if self.q(self.player + 0) != self.base + CLONE_AT:
            raise Uncertain("the player's vtable changed during the call")
        return self.q(self.mailbox + MAILBOX["result"])

    def ticks(self) -> int:
        """The dispatcher's entry counter (E6's live proof that the cloned slot fires every frame)."""
        return self.q(self.mailbox + MAILBOX["ticks"]) if self.mailbox is not None else 0

    # ---- the flash (checkpoint F) --------------------------------------------------------------------------------------

    @property
    def scratch(self) -> int:
        """The fake blast object, in the same proven page as the mailbox (the mailbox uses only its first 0x80)."""
        if self.mailbox is None:
            raise Unavailable("no harness mailbox")
        return self.mailbox + SCRATCH_OFF

    def player_position(self) -> tuple:
        return struct.unpack("<3f", self.rd(self.player + R.U_POS, 12))

    def flash_at(self, x, y, z):
        """Start the game's flash blast on the point (x, y, z - RE4's millimetres) through the harness.

        Route (i) of checkpoint F2: the game's own flash blast `main+0x2E4E50` with a zeroed fake object whose
        position is the point; `+0x3CC` stays zero (not 0xD6, which would skip the effects). `state: confirmed` means
        the native call returned on the game thread; `verified` stays False until a live effect receipt (the stun
        state of the Ganados in range, his own hp unchanged) is seen - that is F4's row in `grenade_status`.
        """
        if not self.attached():
            raise Unavailable("the harness is not attached to the player")
        px, py, pz = self.player_position()
        from_mm = math.hypot(x - px, z - pz)
        if from_mm < FLASH_MIN_MM:
            raise Unavailable(f"a flash {from_mm / R.MM_PER_CM:.0f} cm from him is refused (never at his feet; "
                              f"the minimum is {FLASH_MIN_MM / R.MM_PER_CM:.0f} cm)")
        obj = bytearray(OBJECT_SIZE)
        struct.pack_into("<3f", obj, FLASH_OBJECT_POS, x, y, z)
        # +0x3CC is zero already: the blast's ground/type check must not skip the effects
        self.write(self.scratch, bytes(obj))
        result = self.call(FLASH_BLAST, self.scratch)
        return {"state": "confirmed", "verified": False, "op": "flash_at", "effect": "native_flash_blast",
                "pos": [round(v, 1) for v in (x, y, z)],
                "from_player_cm": round(from_mm / R.MM_PER_CM, 1), "player_generation": self.player_id,
                "call_result": result}

    def flash(self):
        """The intervention's `flash_now` op: the crowd point through this controller's own adapter."""
        return flash_now(self.ad, mailbox=self.mailbox)


def place_flash(player, enemies, level_mm: float | None = None):
    """The flash point on the crowd (checkpoint F3): `core.flash_window.place` in RE4's millimetres, or None.

    The nearer ones weigh more, the point is pushed out to at least FLASH_MIN_MM from him and never past
    FLASH_MAX_MM, on his floor; nobody within FLASH_FROM_MM: None (no flash is wanted).
    """
    from ..core import flash_window
    if player is None:
        return None
    foes = [tuple(q) for q in enemies or () if q is not None]
    return flash_window.place(tuple(player), foes, FLASH_MIN_MM, FLASH_MAX_MM, FLASH_FROM_MM,
                              R.LEVEL_MM if level_mm is None else level_mm)


class _Reader:
    """The adapter as `re4_switch.snapshot` wants it (`m.rd` and attribute caching), for a worker that has no driver."""

    def __init__(self, ad):
        self._ad = ad

    def rd(self, at, n):
        return self._ad.read_memory(at, n)

    def __getattr__(self, name):
        return getattr(self._ad, name)


def flash_now(ad, *, point=None, mailbox=None):
    """The module op of checkpoint F2: flash at `point` (mm) or on the nearest crowd.

    Needs the proven mailbox (E3) - `MAILBOX_AT` or the `mailbox` argument. Without a point it reads a snapshot
    through the adapter, places the flash with `place_flash`, and refuses (state unavailable) when nobody is near.
    """
    ctl = harness(ad, mailbox=MAILBOX_AT if mailbox is None else mailbox)
    if point is None:
        try:
            snap = R.snapshot(_Reader(ad), search=True)
        except Exception as exc:                          # noqa: BLE001 - a worker without a snapshot cannot place
            raise Unavailable(f"no crowd point for the flash: {type(exc).__name__}: {exc}") from None
        foes = [e.get("pos") for e in snap.get("enemies") or () if e.get("pos")]
        point = place_flash((snap.get("player") or {}).get("pos"), foes)
        if point is None:
            return {"state": "unavailable", "verified": False, "op": "flash_at",
                    "reason": "nobody within 12 m on his level to flash"}
    return ctl.flash_at(*point)


def harness(ad, *, mailbox: int | None = None) -> Controller:
    """The session's one controller (the same one `interventions.native_controller` caches), mailbox bound once."""
    ctl = getattr(ad, "_re4_switch_harness", None)
    if ctl is None:
        ctl = ad._re4_switch_harness = Controller(ad, mailbox=mailbox)
    elif mailbox is not None and ctl.mailbox is None:
        ctl.mailbox = mailbox
    return ctl
