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
import json
import math
import os
import struct
import threading
import time

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
#: Serializes controller creation across the UI / MCP callers: ``interventions.native_controller`` holds each native
#: module's ``_CREATE_LOCK`` while it builds the one Controller per adapter, the lock every other native title module
#: already exposed. The harness was missing it, so the builder skipped this module with an AttributeError and the PiP
#: greyed every grenade on an RE4 Switch round (live 2026-11-11: "re4_switch_native: module ... has no attribute
#: '_CREATE_LOCK'").
_CREATE_LOCK = threading.Lock()

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
#: The hand grenade's own blast (checkpoint G2): same fake-object route, class 0x13, radius 6000 mm, floor 7000 mm.
HAND_BLAST = 0x2E48B0
#: G3's incendiary: the item table gives the grenades their classes (hand 0x13, incendiary 0x16, flash 0x17) and the
#: class behaviour table in `.data` lists them in item order - `0xB05B00` (spawn `0x2E48B0`, the hand), `0xB05B58`
#: (spawn `0x2E4BA0`, the incendiary, secondary `0x2E4DF0`) and `0xB05BB0` (spawn `0x2E4E50`, the flash), stride 0x58,
#: spawn at +0x28. The incendiary's spawn is the persistent fire: it calls EFFECT 0x26 and no AREA_ATTACK (no 0x16 area
#: class exists in the image), so its damage is the burning field, not an instant blast.
INCENDIARY_CANDIDATE = 0x2E4BA0
HAND_MIN_MM = 7000.0
#: A MINE ring is NOT a fourth entry in that table, checked 2026-11-12 for the operator's "360 blast around them using
#: the mine thrower ... I don't want them equipping the mine thrower": the Mine Thrower (item 0x36, and 0xAB with its
#: scope) is class 0x0E and the Mine-Darts (0x46) are class 0x00, while that table holds only the grenade classes
#: 0x13/0x16/0x17 in item order. 0x0E is a WEAPON class (beside the shotgun 0x07 and the rifle 0x09), so the thrower
#: fires its darts through the ordinary weapon path and has no spawn/detonate helper to point at a coordinate the way
#: FLASH_BLAST and HAND_BLAST can. A mine ring therefore needs the mine-dart's own projectile spawn found in the image
#: (the FLASH_BLAST-style research), and cannot be derived by the table's 0x58 stride.
#: The ring (checkpoint G1/G2): N blasts round him, the inner ring at the kind's floor.
RING_COUNT_DEFAULT, RING_COUNT_MAX = 10, 16
RING_RADIUS_MM_DEFAULT, RING_INNER_MM_DEFAULT = 9000.0, 4000.0
RING_RIPPLE_MS_DEFAULT = 40.0
#: The barrage (checkpoint G4): the ring's step at random points in a cone toward the threats. Its kinds are the two
#: blasts identified on this build; the shared rule speaks cm, so `safe_cm` is converted at this boundary while the
#: `toward` points are the title's own raw (mm) positions.
SCATTER_KINDS = ("flash", "hand")
SCATTER_COUNT_DEFAULT, SCATTER_COUNT_MAX = 8, 16
SCATTER_SPREAD_DEG = 30.0
SCATTER_MIN_MM, SCATTER_MAX_MM = 4000.0, 15000.0
SCATTER_GAP_MS = (100.0, 200.0)
SCATTER_SAFE_MM = 10.0                  # one cm past the learned reach, in mm
#: The proven private page (set after E3's three-load watch passes; None means the harness cannot attach).
#: `choose_mailbox` returns the page OFFSET; the guest address is main's known base (0x3ca7c04000, `KNOWN_BASES`) plus
#: it. Chosen 2026-11-11 11:26 from the live three-load watch of session 0569c82d21614288-c655ae564d744afc (RE4
#: Village, three round starts): 0x1700000 read all zero in every load while the other four candidates carried data in
#: every one (0x1cb9000/0x1cba000/0x1cbb000 non-zero, 0x1cbc000 floats). 0x1700000 + 0x3ca7c04000 = 0x3ca9304000.
MAILBOX_AT: int | None = 0x3CA9304000


def choose_mailbox(loads) -> int | None:
    """The candidate page that read all zero at every recorded stage load (E3's acceptance), else None.

    `loads` is `stats["bss_watch_loads"]` from live telemetry (or any list of {stage, at, pages}). A page must be
    present and all-zero in each load; a missing page or a single nonzero byte rules it out for good. The earlier
    pages in `CODE`'s candidate order win (the tail of the free stretch first, as the E3 scanner vetted them).
    """
    if isinstance(loads, str):                            # the telemetry publishes the loads as a JSON string
        try:
            loads = json.loads(loads)
        except ValueError:
            return None
    if isinstance(loads, dict):
        loads = [loads]
    if not isinstance(loads, list) or not loads:
        return None
    clean = None
    for load in loads:
        pages = (load or {}).get("pages") or {}
        zero = {name for name, value in pages.items()
                if isinstance(value, str) and value and set(value) == {"0"}}
        clean = zero if clean is None else (clean & zero)
    order = ("0x1cb9000", "0x1cba000", "0x1cbb000", "0x1cbc000", "0x1700000")
    for name in order:
        if clean and name in clean:
            return int(name, 16)
    return None


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

    def check(self):
        """The identity guard every write passes (the base class's check reads RE6's `sp`/generation offsets, which
        this module does not have: the first real selftest died on "'Controller' object has no attribute 'sp'").

        The process and the executable must still be the recorded ones; once a player is bound, its unit id must not
        change and its vtable must be the class it had or, while attached, the clone.
        """
        self.check_build()
        if self.player is None:
            return
        unit = R.read_unit(self, self.player)
        if unit is None or unit.get("id") != self.player_id:
            raise Unavailable("the player unit changed")
        vt = unit.get("vtable")
        if self.attached():
            if vt != self.base + CLONE_AT:
                raise Unavailable("the harness clone is not on the player")
        elif self.player_class is not None and vt != self.base + self.player_class:
            raise Unavailable("the player's vtable changed while the harness is detached")

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

    def bss_watch_probe(self) -> str:
        """The five E3 candidate pages as `off=hex16` (read-only): the status reason carries them to the PiP/API."""
        parts = []
        for off in R.BSS_WATCH_PAGES:
            try:
                parts.append(f"{off:#x}=" + bytes(self.rd(self.base + off, R.BSS_WATCH_BYTES)).hex())
            except (OSError, ValueError, TypeError):
                parts.append(f"{off:#x}=?")
        return ";".join(parts)

    def prepare(self):
        """The status path: no capability is advertised before the private page is proven (E3)."""
        if self.mailbox is None:
            raise Unavailable("no proven private storage for the RE4 harness (E3's three-load watch is pending); "
                              f"pages now: {self.bss_watch_probe()}")

    def ready(self):
        """(player, generation) - the pair `interventions`'s worker and status epoch unpack.

        The RE6/RE5 controllers return that pair; this one returned the bare player, so the moment `prepare()` stopped
        refusing (the mailbox committed) every status read and click died on "cannot unpack non-iterable int object"
        (live 2026-11-11 11:44, session 0569c82d21614288-3c2b58fb55314015). The harness's generation is the player
        unit's own id, which changes when the unit does.
        """
        self.check_build()
        if getattr(self.ad, "paused", False):
            raise Unavailable("session is paused")
        if self.attached():
            # While attached the unit carries the clone; identify it by its own id instead of its class vtable.
            unit = R.read_unit(self, self.player)
            if unit is None or unit.get("id") != self.player_id:
                raise Unavailable("the player unit changed while the harness is attached")
            return self.player, self.player_id
        unit = R.player_unit(self, self.base)
        if unit is None or not R.ptr_ok(unit.get("ptr")):
            raise Unavailable("no player unit in a live Mercenaries round")
        cls = unit["vtable"] - self.base
        if not (R.PLAYER_VTABLE_RANGE[0] <= cls < R.PLAYER_VTABLE_RANGE[1]) or cls % 8:
            raise Unavailable(f"the player's class {cls:#x} is not a unit class this harness supports")
        self.player, self.player_class, self.player_id = unit["ptr"], cls, unit.get("id")
        return self.player, self.player_id

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
        self.failed = False

    def detach(self):
        """Put the original vtable pointer back (the clone in the cave is only ever read)."""
        if self.player is None or self.original is None:
            return
        if self.q(self.player) == self.base + CLONE_AT:
            self.write(self.player, struct.pack("<Q", self.original))
        if self.q(self.player) != self.original:
            raise Uncertain("the player's vtable was not restored")
        self.failed = False

    # ---- the call surface ----------------------------------------------------------------------------------------------

    def call(self, off, *args, timeout=CALL_TIMEOUT_S):
        """One native call on the game thread: publish the request, wait for done, return x0. Never replays."""
        if self.failed:
            raise Unavailable("the harness is in an uncertain state after a timed-out call; detach and re-attach first")
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
        try:
            self.wait(lambda: self.w(self.mailbox + MAILBOX["state"]) == STATE["done"], timeout)
        except Uncertain:
            # A request left in the mailbox could run later (a paused game resuming, a stage load): retire it and
            # refuse further calls until the harness is re-attached, so a timed-out call is never replayed.
            self.failed = True
            self._retire()
            raise
        if self.q(self.mailbox + MAILBOX["generation"]) != generation:
            self.failed = True
            self._retire()
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

    def _retire(self):
        """Put the mailbox back to idle so a request nobody is waiting for cannot run later (best effort)."""
        try:
            self.write(self.mailbox + MAILBOX["state"], struct.pack("<I", STATE["idle"]))
        except (OSError, ValueError, TypeError):
            pass

    def player_life(self):
        """The player's own life field (module+`PLAYER_LIFE`, u16), or None when it reads outside `LIFE_SANE`."""
        if not R.PLAYER_LIFE:
            return None
        try:
            value = self.w(self.base + R.PLAYER_LIFE)
        except (OSError, ValueError):
            return None
        return value if R.LIFE_SANE[0] <= value < R.LIFE_SANE[1] else None

    def _blast_at(self, blast, kind, x, y, z, floor_mm):
        """One blast through the mailbox: a zeroed object at the point, the game's own function, one call."""
        if not self.attached():
            raise Unavailable("the harness is not attached to the player")
        px, py, pz = self.player_position()
        from_mm = math.hypot(x - px, z - pz)
        if from_mm < floor_mm:
            raise Unavailable(f"a {kind} blast {from_mm / R.MM_PER_CM:.0f} cm from him is refused (the minimum is "
                              f"{floor_mm / R.MM_PER_CM:.0f} cm)")
        obj = bytearray(OBJECT_SIZE)
        struct.pack_into("<3f", obj, FLASH_OBJECT_POS, x, y, z)
        # +0x3CC is zero: the blast's ground/type check must not skip the effects
        self.write(self.scratch, bytes(obj))
        result = self.call(blast, self.scratch)
        return {"pos": [round(v, 1) for v in (x, y, z)], "from_player_cm": round(from_mm / R.MM_PER_CM, 1),
                "call_result": result}

    def flash_at(self, x, y, z):
        """Start the game's flash blast on the point (x, y, z - RE4's millimetres) through the harness.

        Route (i) of checkpoint F2: the game's own flash blast `main+0x2E4E50` with a zeroed fake object whose
        position is the point; `+0x3CC` stays zero (not 0xD6, which would skip the effects). `state: confirmed` means
        the native call returned on the game thread; `verified` stays False until a live effect receipt (the stun
        state of the Ganados in range, his own hp unchanged) is seen - that is F4's row in `grenade_status`.
        """
        row = self._blast_at(FLASH_BLAST, "flash", x, y, z, FLASH_MIN_MM)
        return {"state": "confirmed", "verified": False, "op": "flash_at", "effect": "native_flash_blast",
                "player_generation": self.player_id, **row}

    def grenade_kinds(self):
        """The ring's kinds as THIS build can honestly fire them (gbox.mercs.grenade_status reads this).

        RE4 had no such method at all, so every kind in the panel read "(unavailable)" and the ring could not be
        chosen on RE4 even though `grenade_ring` below fires it fine - the operator's own frame (2026-11-12) shows
        Flash with Hand (unavailable) / Incendiary (unavailable). flash and hand are both real spawn calls
        (FLASH_BLAST 0x2E4E50, HAND_BLAST 0x2E48B0); the incendiary is only the class-0x16 candidate that
        `grenade_ring` refuses without allow_unverified, so it stays advertised-but-unavailable rather than hidden.
        """
        if not self.attached():
            why = "the harness is not attached to the player"
            return [{"kind": k, "available": False, "reason": why} for k in ("flash", "hand", "incendiary")]
        return [
            {"kind": "flash", "available": True, "reason": ""},
            {"kind": "hand", "available": True, "reason": ""},
            {"kind": "incendiary", "available": False,
             "reason": "the incendiary blast is not identified on this build yet (checkpoint G3): probe only"},
        ]

    def grenade_ring(self, kind="flash", *, count=None, radius_cm=None, inner_cm=None, ripple_ms=None,
                     expand=None, allow_unverified=False):
        """N blasts in a ring round him (checkpoint G1/G2): flash 4000 mm or more, hand grenade 7000 mm or more.

        The points run outward from the inner ring to the outer radius on his floor; each is one native blast through
        the harness (the same route as `flash_at`). A failed blast aborts the ring with a partial receipt - it is
        never replayed. `state: confirmed` means every blast's call returned; a live receipt is still needed.
        `allow_unverified` is the probe path for the incendiary (G3): it calls the candidate fire spawn - the class-0x16
        persistent fire whose dispatch is not confirmed - and marks the receipt `probe: true`; the status and the rule
        never offer it.
        """
        if not self.attached():
            raise Unavailable("the harness is not attached to the player")
        kind = (kind or "flash").lower()
        if kind == "incendiary" and not allow_unverified:
            raise Unavailable("the incendiary blast is not identified on this build yet (checkpoint G3); pass "
                              "allow_unverified for the probe")
        blasts = {"flash": (FLASH_BLAST, FLASH_MIN_MM), "hand": (HAND_BLAST, HAND_MIN_MM),
                  "incendiary": (INCENDIARY_CANDIDATE, FLASH_MIN_MM)}
        if kind not in blasts:
            raise Unavailable(f"unknown grenade kind {kind!r}")
        blast, floor_mm = blasts[kind]
        count = max(1, min(int(RING_COUNT_DEFAULT if count is None else count), RING_COUNT_MAX))
        radius_mm = max(floor_mm, float(RING_RADIUS_MM_DEFAULT if radius_cm is None else radius_cm * R.MM_PER_CM))
        inner_mm = max(floor_mm, float(RING_INNER_MM_DEFAULT if inner_cm is None else inner_cm * R.MM_PER_CM))
        inner_mm = min(inner_mm, radius_mm)
        gap = max(0.0, float(RING_RIPPLE_MS_DEFAULT if ripple_ms is None else ripple_ms)) / 1000.0
        px, py, pz = self.player_position()
        life_before = self.player_life()
        started = time.monotonic()
        rounds, abort = [], None
        for index in range(count):
            angle = 2.0 * math.pi * index / count
            r = radius_mm if expand is False or count == 1 else inner_mm + (radius_mm - inner_mm) * index / (count - 1)
            x, z = px + r * math.sin(angle), pz + r * math.cos(angle)
            try:
                rounds.append({**self._blast_at(blast, kind, x, py, z, floor_mm), "index": index,
                               "radius_mm": round(r, 1)})
            except (Unavailable, Uncertain, AllocationLost) as exc:
                abort = str(exc)
                break
            if gap and index + 1 < count:
                time.sleep(gap)
        life_after = self.player_life()
        receipt = {"op": "grenade_ring", "kind": kind, "requested": count, "detonated": len(rounds),
                   "radius_cm": round(radius_mm / R.MM_PER_CM, 1), "radius_mm": round(radius_mm, 1),
                   "inner_cm": round(inner_mm / R.MM_PER_CM, 1), "inner_mm": round(inner_mm, 1),
                   "expand": expand is not False, "hp_before": life_before, "hp_after": life_after,
                   "self_damage": (life_before - life_after) if isinstance(life_before, int) and
                   isinstance(life_after, int) else None,
                   "grenades": rounds, "verified": False, "probe": kind == "incendiary",
                   "player_generation": self.player_id,
                   "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
        if len(rounds) == count and abort is None:
            return {"state": "confirmed", "effect": f"native_{kind}_ring", **receipt}
        receipt["reason"] = abort or "the ring did not complete"
        return {"state": "failed" if not rounds else "uncertain", **receipt}

    def grenade_scatter(self, kind="random", *, count=None, toward=None, spread_deg=None, min_cm=None, max_cm=None,
                        gap_ms=None, safe_cm=None, rng=None, kinds=None):
        """A barrage of native blasts in a cone toward the threats (checkpoint G4), same contract as RE5/RE6.

        `toward` are the title's own raw (x, z) positions (RE4 millimetres, straight from its snapshot); `safe_cm`
        is the shared rule's learned blast reach in cm and is converted here with `re4_switch.MM_PER_CM`. kind
        "random" draws each round from SCATTER_KINDS (flash, hand); `kinds` narrows that draw (the rule's flash cap
        leaves the flash out of a mixed barrage inside the minute). Every round keeps its own floor (flash 4000 mm,
        hand 7000 mm) and the learned reach plus one cm. A partial barrage is `uncertain` and is never replayed.
        """
        import random as _random
        if not self.attached():
            raise Unavailable("the harness is not attached to the player")
        kind = (kind or "random").lower()
        if kind == "incendiary":
            raise Unavailable("the incendiary blast is not identified on this build yet (checkpoint G3)")
        if kind != "random" and kind not in SCATTER_KINDS:
            raise Unavailable(f"unknown or unbuilt grenade kind {kind!r}")
        if kinds is not None:
            if kind != "random":
                raise Unavailable("a barrage of one explicit kind cannot also narrow its draw")
            kinds = tuple(str(k).lower() for k in kinds)
            if not kinds or any(k not in SCATTER_KINDS for k in kinds):
                raise Unavailable(f"this build's barrage cannot draw {kinds!r} (built: {SCATTER_KINDS})")
        draw = tuple(kinds) if kind == "random" and kinds else (SCATTER_KINDS if kind == "random" else (kind,))
        rng = rng or _random.Random()
        count = max(1, min(int(SCATTER_COUNT_DEFAULT if count is None else count), SCATTER_COUNT_MAX))
        spread = math.radians(float(SCATTER_SPREAD_DEG if spread_deg is None else spread_deg))
        safe_mm = max(0.0, float(safe_cm or 0.0) * R.MM_PER_CM)
        lo = max(SCATTER_MIN_MM, float(min_cm) * R.MM_PER_CM if min_cm is not None else 0.0)
        hi = max(lo, min(float(SCATTER_MAX_MM if max_cm is None else max_cm * R.MM_PER_CM), RING_RADIUS_MM_DEFAULT * 2))
        gap = gap_ms or SCATTER_GAP_MS
        floors = {"flash": max(FLASH_MIN_MM, safe_mm), "hand": max(HAND_MIN_MM, safe_mm)}
        px, py, pz = self.player_position()
        points = [(float(x), float(z)) for x, z in (toward or ())]
        if points:                                   # a cone toward the threats' weighted centre
            cx = sum(p[0] for p in points) / len(points)
            cz = sum(p[1] for p in points) / len(points)
            axis = math.atan2(cx - px, cz - pz)
            far = max(math.hypot(x - px, z - pz) for x, z in points)
            hi = max(lo, min(hi, far + 200.0 * R.MM_PER_CM))
        else:                                        # no threats: along his facing
            axis = struct.unpack("<f", self.rd(self.player + R.U_YAW, 4))[0]
        life_before = self.player_life()
        started = time.monotonic()
        rounds, abort = [], None
        for index in range(count):
            this = rng.choice(draw) if kind == "random" else kind
            floor_mm = floors[this]
            near = floor_mm + SCATTER_SAFE_MM
            if hi < near:
                hi = near
            d = near + (hi - near) * (index + rng.random()) / count
            ang = axis + rng.uniform(-spread, spread)
            x, z = px + d * math.sin(ang), pz + d * math.cos(ang)
            try:
                row = self._blast_at(FLASH_BLAST if this == "flash" else HAND_BLAST, this, x, py, z, floor_mm)
            except (Unavailable, Uncertain, AllocationLost) as exc:
                abort = str(exc)
                break
            rounds.append({**row, "kind": this, "dist_cm": round(d / R.MM_PER_CM, 1)})
            if index + 1 < count:
                time.sleep(rng.uniform(*gap) / 1000.0)
        life_after = self.player_life()
        planned = draw if kind == "random" else (kind,)
        floor_cm = min(floors[k] for k in planned) / R.MM_PER_CM
        receipt = {"op": "grenade_scatter", "kind": kind, "requested": count, "detonated": len(rounds),
                   "kinds": sorted({r["kind"] for r in rounds}),
                   "axis_deg": round(math.degrees(axis), 1), "spread_deg": round(math.degrees(spread), 1),
                   "near_cm": round(floor_cm, 1), "far_cm": round(hi / R.MM_PER_CM, 1),
                   "floor_cm": round(floor_cm, 1),
                   "floors_cm": {k: round(v / R.MM_PER_CM, 1) for k, v in floors.items()},
                   "rounds": rounds, "hp_before": life_before, "hp_after": life_after,
                   "self_damage": (life_before - life_after) if isinstance(life_before, int) and
                   isinstance(life_after, int) else None,
                   "verified": False, "player_generation": self.player_id,
                   "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
        if len(rounds) == count and abort is None:
            return {"state": "confirmed", "effect": f"native_{kind}_scatter", **receipt}
        receipt["reason"] = abort or "the barrage did not complete"
        return {"state": "failed" if not rounds else "uncertain", **receipt}

    def flash(self):
        """The intervention's `flash_now` op: the crowd point through this controller's own adapter."""
        return flash_now(self.ad, mailbox=self.mailbox)

    def selftest(self):
        """E6's no-op: attach, then one mailbox call to the dispatcher's own `ret` - no game code runs.

        The dispatcher ticks on every entry, so a rising `ticks` counter plus a zero result proves the clone fires
        and the mailbox round trip works; that is the live proof checkpoint E6 asks for before any real op.

        A call that never completes returns an uncertain receipt **carrying the mailbox counters** (ticks before/after
        and the state word): the difference between "the dispatcher is not invoked at all" (ticks unchanged - the
        clone's slot the game calls is not the one installed) and "it runs but the handshake is wrong" (ticks rose,
        state stuck) is the live diagnosis E6 needs, and a bare reason cannot make it.
        """
        if not self.attached():
            self.attach()
        before = self.ticks()
        try:
            result = self.call(CODE.SELFTEST_AT)
        except Uncertain as exc:
            return {"state": "uncertain", "reason": str(exc)[:300], "op": "re4_harness_selftest",
                    "ticks_before": before, "ticks": self.ticks(),
                    "mailbox_state": (self.w(self.mailbox + MAILBOX["state"]) if self.mailbox else None),
                    "attached_after": self.attached(), "player_generation": self.player_id}
        return {"state": "confirmed", "verified": result == 0, "op": "re4_harness_selftest", "result": result,
                "ticks_before": before, "ticks": self.ticks(), "player_generation": self.player_id}


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
