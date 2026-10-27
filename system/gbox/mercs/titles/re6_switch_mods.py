"""Resident Evil 6 (Nintendo Switch, title 01002A000CD48000 v1.0.2, main build 061D2A06CD700785E987C42CE2D72231) live
Mercenaries mods on Citron: data writes into the running game through the Switch adapter (write_memory reads every
write back). Everything is RAM only: a relaunch is the full revert. A bot module (gbox.hot_reload reloads it in place;
ORIG survives).

The Mercenaries playbook applies the profile's playing_ops through run() when a round starts (gbox/mercs_bot.py
apply_ops), and the driver (gbox.mercs.titles.re6_switch.RE6Switch.screen) calls maintain() on every snapshot.

ops:
  status                    what is on, and the in-hand weapon's rounds / capacity
  infinite_ammo on=true     every gun in the inventory keeps a full magazine: a weapon slot whose rounds fell below its
                            capacity is topped up on the next snapshot, so the gun never empties and never reloads (the
                            item slots - the tablets, the sprays, the grenades - are left alone)
  infinite_tablets on=true  the tablet case is kept at TABLET_KEEP tablets while its slot is alive (count-keeping, as RE5
                            Switch keeps its spray): only the count's s16 is written, only into a live cItem slot holding
                            the tablets (id 0x1D, in use, its item object set), re-read just before the write and read
                            back after it; never the id, the object pointer or a slot that is not the tablets'
  infinite_stamina on=true  the combat gauge (melee, quick shots, dodges) kept full: player +0x42A0 set to its maximum
                            +0x42A4 whenever it fell below (f32, re-read just before the write, read back after; only a
                            maximum in 1..STAMINA_SANE). Where (Ghidra, this build): the HUD's gauge (uIdLife's update
                            main+0x9FEA90) asks the player's vfunc 0x3F8 (main+0xBD9CD0) for its segments, int((gauge -
                            300) / 100); the vfunc 0x400 beside it gives the maximum's; the player's init sets both from
                            the character's level (main+0xB18BF4) and every spend / refill goes through the vfunc 0x3E0
                            (main+0xB209D0), which waits for the refill delay +0x42A8
  infinite_grenades on=true every hand / incendiary / flash grenade and remote bomb stack (the start list's slots, +0x9
                            15-23, type 0x113-0x116) kept at THROWN_MAX - it never reaches 0, where the ammo consumer
                            main+0xB25DC0 frees the stack and its object - and the item wheel's count (+0x9 7-14) at the
                            stacks' total; counts only (merc_loadout gives every loadout the stacks)
  unlock_characters on=true every Mercenaries character and costume on the save: the character select's mask (cSystemInfo
                            +0x974 and its copy +0x5E84, which the select's constructor main+0xAA9158 ORs with 0x20010101)
                            set to 0x3FFFFFFF, both copies read back; nothing else in cSystemInfo is ever written, and the
                            game's own next save keeps it (live 2026-10-27: 0x10711 -> 0x3FFFFFFF, the select listed 9)
  fire_rate multiplier=N    every gun fires N times as fast: the game's own seconds between two shots, one f32 per
                            weapon record in the weapon parameter table (main+0x2962170, 48 records of 0x1A0, the
                            record's +0x1C), set to this build's value / N (never below FIRE_FLOOR: the countdown has to
                            pass zero), each read back; N=1 (or on=false) writes the build's values back. Grenades, the
                            remote bomb, the knife and the melee weapons keep theirs. A data write, live and reversible
                            (a relaunch reloads the table too); nothing else in the table, no code, no pointer.
                            Where (Ghidra, this build): every shot's fire action asks main+0xB26F90 for the interval -
                            ldr s8, [x0, #0x1c] at main+0xB2701C reads it from the in-hand weapon's record (the lookup
                            main+0x10ECE20: the weapon type's low byte, a few alternate-mode records) - and stores it in
                            player +0x5AEC (main+0x109A8C8); the player's update counts +0x5AEC down by the frame time
                            (main+0xBD3A90), and the automatic loop of the fire action (main+0x10982D0) fires again once
                            it is <= 0 with the trigger held (main+0x1098508..+0x1098528: re-arm main+0x109A8A0, the
                            state back to 0); a semi-automatic's next press is taken once it is below the record's
                            +0x20 (player +0x5590)

Where (measured live 2026-10-27 in a private Citron NEO session on the Spark; docs/research/re6-switch-ram.md):
  player +0x5070  the inventory: 12 cItem slots of 0x28 (vtable main+0x2875848), +0x8 1 = in use, +0x9 the slot's
                  index, +0xA the item id, +0xE s16 the rounds in the magazine, +0x14 s16 its capacity (the Wing Shooter
                  18 / 18; three shots took it to 15, the HUD's magazine row), +0x16 the carry limit. Slots 0-6 hold the
                  weapons, 7-11 the items: Chris's slot 0 is his assault rifle (id 0x0F, 30 / 30; a held ZR spent 24 rounds
                  in 2.5 s, an automatic), slot 1 id 0x07 (7 / 7), slot 7 id 0x1D (0 / 12: the tablets, Leon's 8 at the
                  start), 8 id 0x20 (0 / 3), 9-11 ids 0x13-0x15 (3 / 5, 0 / 5, 0 / 5)
  player +0x507E  the first slot's rounds = the gun in hand at the round start (gbox.mercs.titles.re6_switch.P_AMMO)
  player +0x5196  s16 the health tablets (8 at the start; R takes one)
"""
from __future__ import annotations

import struct
import threading
import time

from . import re6_switch as R

GAME = "Resident Evil 6 (Nintendo Switch 01002A000CD48000 v1.0.2, main 061D2A06CD700785E987C42CE2D72231)"
MAP_ID = R.MAP_ID
SLOTS, SLOT_STRIDE, SLOT_ROUNDS, SLOT_CAP, N_SLOTS = 0x5070, 0x28, 0xE, 0x14, 12
WEAPON_SLOTS = 7                                         # slots 0-6 the weapons; 7-11 the items (tablets, sprays, grenades)
SLOT_VTABLE = 0x2875848                                  # cItem
SLOT_USED, SLOT_ID, SLOT_OBJ = 0x8, 0xA, 0x20            # u8 1 = in use, u8 the item id, the item's object (never written)
TABLET_ID, TABLET_KEEP = 0x1D, 6                         # the tablet case (Leon 8 / 12 at the start, Chris 0 / 12)
P_STAMINA, P_STAMINA_MAX = 0x42A0, 0x42A4                # f32 the combat gauge and its maximum (100 a segment past 300)
ALL_SLOTS, SLOT_INDEX, SLOT_TYPE = 24, 0x9, 0xA          # the 24 cItem slots (the getter main+0xB22BB0 finds one by its
                                                         # +0x9 index); u16 +0xA the type (0x100 + the item id)
STACK_INDEXES = range(15, 24)                            # the start list's items, one slot each (grenades, the remote bomb)
WHEEL_INDEXES = range(7, 15)                             # the item wheel: a grenade's count there is its stacks' total
                                                         # (the ammo consumer main+0xB25DC0 recounts it after each throw)
STAMINA_SANE = 10000.0                                   # a maximum above this is not the gauge's
CHARACTER_MASK = (0x974, 0x974 + 0x5510)                 # cSystemInfo: the select's unlock mask, copy A and copy B
ALL_CHARACTERS = 0x3FFFFFFF                              # 4 costume bits for each of 7 characters, then bits 28 and 29
CAP_MAX = 200                                            # a capacity above this is not a gun's magazine
CHECK_S = 0.25                                           # maintain tops up at most this often
FIRE_MAX = 80.0
FIRE_TABLE, FIRE_STRIDE, FIRE_RECORDS = 0x2962170, 0x1A0, 48   # the weapon parameter table (lookup main+0x10ECE20)
FIRE_INTERVAL, FIRE_TAG, FIRE_TAG_VALUE = 0x1C, 0x4, 60        # f32 the seconds between two shots; i32 60 in every record
FIRE_SITE, FIRE_SITE_WORD = 0xB2701C, 0xBD401C08               # main+0xB26F90: ldr s8, [x0, #0x1c] (this build's check)
FIRE_ORIGINAL = (10.0, 0.5, 0.6, 0.5, 1.2, 0.8, 0.6, 0.8, 1.2, 10.0, 0.7, 2.25, 0.1, 0.5, 0.5, 0.1, 0.1, 0.12, 1.0,
                 2.0, 2.0, 2.0, 2.0, 1.0, 10.0, 10.0, 10.0, 10.0, 0.1, 1.0, 0.1, 10.0, 1.0, 10.0, 10.0, 10.0, 10.0, 10.0,
                 10.0, 1.0, 0.5, 0.25, 2.25, 0.5, 0.1, 1.0, 1.0, 2.0)   # this build's intervals, records 0-47 (live dump)
FIRE_SKIP = frozenset({0x13, 0x14, 0x15, 0x16, 0x2F})   # the grenades and the remote bomb: thrown, never sped up
FIRE_GUN_MAX = 5.0                                       # a longer interval is the knife's or a melee weapon's
FIRE_FLOOR = 0.004                                       # never 0: a semi-automatic's next press waits for the countdown
                                                         # to fall below its record's +0x20 (0 for most), so it must pass 0
# The Mercenaries' starting loadouts (Ghidra, this build): main+0x38C740 copies one 0x74-byte entry into the game's
# per-player buffer when a round is set up - the entry of the pointer array main+0x2890008 at the costume's loadout index
# (the costume code table main+0x222B352, 5 bytes a code: character, variant, select id, costume, loadout index; costume
# 0 has its own entry, costumes 1-3 share the second). Modes 4-7 read the other arrays (+0x7C8, +0x1008, +0x17C8,
# +0x1F88); No Mercy and The Mercenaries read this one (live 2026-10-27: Chris's round matched it). An entry: u16 id,
# health / maximum (900 / 900), 0, 0xFF, 0, 0, 0; then 7 (type, rounds) weapon pairs at +0x10 (type 0x100 + the item id,
# rounds 0xFFFF for a melee weapon), 8 (type, count) item-wheel pairs at +0x2C, 9 (type, count) pairs at +0x4C given at
# the start (grenades, the remote bomb 0x116, the spray, ammo boxes 0x2xx); an empty pair is (0, 0xFFFF); +0x70 u32 0.
LOADOUT_BLOCK, LOADOUT_SIZE = 0x2890088, 0x74
L_ID, L_HP, L_TAG, L_TAG_VALUE = 0x0, 0x2, 0x8, 0xFF
L_WEAPONS, L_EXTRAS, N_WEAPONS, N_EXTRAS = 0x10, 0x4C, 7, 9
EMPTY = (0, 0xFFFF)
ROCKET = 0x117                                           # the rocket launcher (1 round; Ada's first costume)
SWAPS = ((0x107, 7), (0x108, 5), (0x104, 8), (0x105, 7), (0x106, 3))   # magnums and shotguns: (type, magazine)
REMOTE_BOMB, HAND_GRENADE, INCENDIARY, FLASH = 0x116, 0x113, 0x114, 0x115
THROWN = (REMOTE_BOMB, HAND_GRENADE, INCENDIARY, FLASH)  # given in this order while the start list has room
THROWN_MAX = 5                                           # the grenades' and the remote bomb's carry limit (their records)
LOADOUTS = (                                             # this build's entries: id, weapons, start list (live dump)
    (0x0000, ((0x103, 18), (0x104, 8)), ((0x116, 4), (0x201, 50), (0x202, 8))),
    (0x1000, ((0x111, 30), (0x109, 6), (0x2112, 5120)), ((0x204, 60), (0x203, 30))),
    (0x0001, ((0x102, 16), (0x106, 3), (0x1112, 192)), ((0x201, 50), (0x20E, 30))),
    (0x1001, ((0x10C, 50), (0x109, 6)), ((0x304, 1), (0x120, 1), (0x114, 3), (0x201, 50), (0x203, 20))),
    (0x0002, ((0x10F, 30), (0x107, 7), (0x119, 0xFFFF)), ((0x113, 3), (0x204, 60), (0x206, 7))),
    (0x1002, ((0x101, 15), (0x104, 8), (0x11B, 1)), ((0x201, 50), (0x202, 20))),
    (0x0003, ((0x10E, 30), (0x10B, 10)), ((0x120, 1), (0x116, 3), (0x201, 50), (0x205, 20))),
    (0x1003, ((0x10C, 50), (0x10A, 5), (0x105, 7)), ((0x201, 30), (0x203, 15), (0x202, 10))),
    (0x0004, ((0x101, 15), (0x108, 5), (0x100, 0xFFFF)), ((0x115, 2), (0x201, 50), (0x207, 10))),
    (0x1004, ((0x118, 0xFFFF), (0x10A, 5), (0x112, 6)), ((0x120, 1), (0x203, 20), (0x208, 12))),
    (0x0005, ((0x10D, 20), (0x107, 7), (0x11A, 0xFFFF)), ((0x304, 1), (0x304, 1), (0x120, 1), (0x201, 30), (0x206, 10))),
    (0x1005, ((0x110, 286), (0x105, 7)), ((0x304, 1), (0x304, 1), (0x120, 1), (0x115, 2), (0x204, 60), (0x202, 20),
                                          (0x208, 3))),
    (0x0006, ((0x10C, 50), (0x117, 1)), ((0x114, 3), (0x201, 30), (0x20C, 60), (0x20D, 30))),
    (0x1006, ((0x10E, 30), (0x109, 6)), ((0x304, 1), (0x304, 1), (0x113, 3), (0x115, 2), (0x201, 30), (0x203, 6))),
    (0x0206, ((0x102, 16), (0x112, 6)), ((0x201, 50), (0x209, 12), (0x20A, 6))),
    (0x0007, ((0x101, 15), (0x10A, 5), (0x118, 0xFFFF)), ((0x116, 5), (0x120, 2), (0x201, 50), (0x203, 20))),
)
ORIG: dict = {}                                          # id(adapter) -> this boot's settings
_LOCK = threading.RLock()
RELOAD_KEEP = ("ORIG", "_LOCK")


class Mem:
    """The session's guest memory for re6_switch's readers: rd() and the adapter (its guest rows find main)."""

    def __init__(self, ad):
        self.adapter = ad

    def rd(self, a: int, n: int) -> bytes:
        return self.adapter.read_memory(a, n)


class RE6Switch:
    """RE6 Switch in one session: main's base this boot, checked against this build's title gate."""

    def __init__(self, ad):
        self.ad = ad
        self.m = Mem(ad)
        self.state = ORIG.setdefault(id(ad), {})
        if isinstance(self.state.get("base"), int):
            self.m.module_base = self.state["base"]
        base = R.module_base(self.m)
        if base is None:
            raise RuntimeError("RE6 Switch's main is not in this session's memory (another title or build?)")
        self.base = base
        if self.state.get("base") != base:                   # a new boot: the old settings start over
            self.state.clear()
            self.state["base"] = base

    def slots(self, player: int) -> list[tuple[int, int, int]]:
        """The gun slots [(slot, rounds, capacity)]: the weapon slots' cItem records with a magazine (0 < capacity <=
        CAP_MAX; a knife has none). The item slots after them are not guns."""
        out = []
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * WEAPON_SLOTS)
        except (ValueError, OSError):
            return out
        for i in range(WEAPON_SLOTS):
            o = SLOT_STRIDE * i
            vt = struct.unpack_from("<Q", raw, o)[0]
            if vt != self.base + SLOT_VTABLE:
                break
            rounds, cap = struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0], struct.unpack_from("<h", raw, o + SLOT_CAP)[0]
            if 0 < cap <= CAP_MAX:
                out.append((player + SLOTS + o, rounds, cap))
        return out

    def tablet_slot(self, player: int) -> tuple[int, int, int] | None:
        """The tablet case's live slot (slot, count, capacity): an item slot (7-11) with the cItem vtable, in use, the
        tablets' id and its item object set; None when there is none (a character without the case, a slot the game
        cleared)."""
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * N_SLOTS)
        except (ValueError, OSError):
            return None
        for i in range(WEAPON_SLOTS, N_SLOTS):
            o = SLOT_STRIDE * i
            if (struct.unpack_from("<Q", raw, o)[0] == self.base + SLOT_VTABLE and raw[o + SLOT_USED] == 1
                    and raw[o + SLOT_ID] == TABLET_ID and struct.unpack_from("<Q", raw, o + SLOT_OBJ)[0]):
                return (player + SLOTS + o, struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0],
                        struct.unpack_from("<h", raw, o + SLOT_CAP)[0])
        return None

    def thrown_slots(self, player: int) -> tuple[list, list]:
        """The live grenade and remote bomb slots: (stacks, wheel), each [(slot, type, count, capacity)] - a cItem slot in
        use whose type is a grenade's or the remote bomb's, at a start-list index (15-23) or an item-wheel one (7-14)."""
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * ALL_SLOTS)
        except (ValueError, OSError):
            return [], []
        stacks, wheel = [], []
        for i in range(ALL_SLOTS):
            o = SLOT_STRIDE * i
            if struct.unpack_from("<Q", raw, o)[0] != self.base + SLOT_VTABLE or raw[o + SLOT_USED] != 1:
                continue
            kind = struct.unpack_from("<H", raw, o + SLOT_TYPE)[0]
            if kind not in THROWN:
                continue
            row = (player + SLOTS + o, kind, struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0],
                   struct.unpack_from("<h", raw, o + SLOT_CAP)[0])
            if raw[o + SLOT_INDEX] in STACK_INDEXES:
                stacks.append(row)
            elif raw[o + SLOT_INDEX] in WHEEL_INDEXES:
                wheel.append(row)
        return stacks, wheel

    def status(self) -> dict:
        st = {"game": GAME, "module_base": hex(self.base), "infinite_ammo": bool(self.state.get("infinite_ammo")),
              "infinite_tablets": bool(self.state.get("infinite_tablets")),
              "infinite_stamina": bool(self.state.get("infinite_stamina")), "fire_rate_x": self.state.get("fire_rate", 1.0)}
        snap = R.snapshot(self.m)
        p = snap.get("player")
        if p:
            st["guns"] = [{"rounds": r, "capacity": c} for _, r, c in self.slots(p["ptr"])]
            st["in_hand_rounds"] = p.get("ammo")
            t = self.tablet_slot(p["ptr"])
            st["tablets"] = {"count": t[1], "capacity": t[2]} if t else None
        return st


def infinite_ammo(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_ammo"] = bool(on)
    filled = 0
    snap = R.snapshot(g.m)
    p = snap.get("player")
    if on and p:
        filled = _top_up(g.ad, g, p["ptr"])
    return {"infinite_ammo": bool(on), "verified": True, "topped_up": filled,
            "note": "every gun's magazine kept at its capacity (each driver snapshot tops up a slot that fired): the "
                    "gun never empties and never reloads"}


def infinite_tablets(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_tablets"] = bool(on)
    kept = 0
    p = R.snapshot(g.m).get("player")
    if on and p:
        kept = _keep_tablets(g.ad, g, p["ptr"])
    return {"infinite_tablets": bool(on), "verified": True, "kept": kept,
            "note": "the tablet case kept at %d while its slot is alive (its count's s16 only, re-read before and read "
                    "back after every write): a tablet taken is back on the next snapshot" % TABLET_KEEP}


RACE_SPENT = 3                                           # a count the game spent this much of right after the write
STAMINA_RACE = 400.0                                     # (a shot, a throw, a melee between the write and its read-back)


def _put_count(ad, addr: int, value: int) -> None:
    """A count (s16) written and read back; a read-back the game's own spending explains (the value lower by at most
    RACE_SPENT: a shot or a throw landed between the write and the read) counts as done - the next check tops it up -
    any other mismatch raises as the adapter does."""
    try:
        ad.write_memory(addr, struct.pack("<h", value))
    except RuntimeError:
        now = struct.unpack("<h", ad.read_memory(addr, 2))[0]
        if not 0 <= value - now <= RACE_SPENT:
            raise


def _keep_tablets(ad, g: RE6Switch, player: int) -> int:
    t = g.tablet_slot(player)
    if t is None:
        return 0
    slot, count, cap = t
    if not 0 <= count < TABLET_KEEP or cap < TABLET_KEEP:
        return 0
    again = g.tablet_slot(player)                            # the same live slot, unchanged, right before the write
    if again != t:
        return 0
    _put_count(ad, slot + SLOT_ROUNDS, TABLET_KEEP)
    return 1


def _keep_thrown(ad, g: RE6Switch, player: int) -> int:
    """Each live grenade / remote bomb stack back at THROWN_MAX (it never reaches 0, where the game frees it), then each
    item-wheel count at its stacks' total (what the game itself writes after a throw); counts only, each slot re-read
    just before its write."""
    stacks, _wheel = g.thrown_slots(player)
    writes = 0
    for slot, kind, count, _cap in stacks:
        if 0 < count < THROWN_MAX:
            again = struct.unpack("<h", ad.read_memory(slot + SLOT_ROUNDS, 2))[0]
            if again == count:
                _put_count(ad, slot + SLOT_ROUNDS, THROWN_MAX)
                writes += 1
    stacks, wheel = g.thrown_slots(player)
    totals: dict = {}
    for _slot, kind, count, _cap in stacks:
        totals[kind] = totals.get(kind, 0) + max(0, count)
    for slot, kind, count, _cap in wheel:
        want = totals.get(kind)
        if want is not None and count != want and 0 < want <= 99:
            _put_count(ad, slot + SLOT_ROUNDS, want)
            writes += 1
    return writes


def infinite_grenades(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_grenades"] = bool(on)
    kept = 0
    p = R.snapshot(g.m).get("player")
    if on and p:
        kept = _keep_thrown(g.ad, g, p["ptr"])
    stacks = g.thrown_slots(p["ptr"])[0] if p else []
    return {"infinite_grenades": bool(on), "verified": True, "kept": kept,
            "stacks": [{"type": hex(k), "count": c} for _s, k, c, _cap in stacks],
            "note": "every grenade and remote bomb stack kept at %d (its count only, never 0: the game frees an empty "
                    "one), the item wheel's counts at their totals" % THROWN_MAX}


def stamina(ad, player: int) -> tuple[float, float] | None:
    """(gauge, maximum) of the player, None when the maximum is not a gauge's (1..STAMINA_SANE) or a value is not a
    number."""
    try:
        cur, top = struct.unpack("<2f", ad.read_memory(player + P_STAMINA, 8))
    except (ValueError, OSError):
        return None
    if not (1.0 <= top <= STAMINA_SANE) or cur != cur:
        return None
    return cur, top


def _keep_stamina(ad, player: int) -> int:
    s = stamina(ad, player)
    if s is None or s[0] >= s[1]:
        return 0
    if stamina(ad, player) != s:                             # moved between the reads: the next check takes it
        return 0
    try:
        ad.write_memory(player + P_STAMINA, struct.pack("<f", s[1]))
    except RuntimeError:                                     # a melee spent some right after the write: done
        now = struct.unpack("<f", ad.read_memory(player + P_STAMINA, 4))[0]
        if not 0.0 <= s[1] - now <= STAMINA_RACE:
            raise
    return 1


def infinite_stamina(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_stamina"] = bool(on)
    kept = 0
    p = R.snapshot(g.m).get("player")
    if on and p:
        kept = _keep_stamina(g.ad, p["ptr"])
    s = stamina(g.ad, p["ptr"]) if p else None
    return {"infinite_stamina": bool(on), "verified": True, "kept": kept,
            "gauge": None if s is None else {"value": round(s[0], 1), "max": round(s[1], 1)},
            "note": "the combat gauge (player +0x42A0) kept at its maximum (+0x42A4): melee, quick shots and dodges "
                    "never run it dry (its f32 only, re-read before and read back after every write)"}


def _pairs(raw: bytes, off: int, n: int) -> list[tuple[int, int]]:
    return [struct.unpack_from("<2H", raw, off + 4 * i) for i in range(n)]


def _padded(pairs, n: int) -> list[tuple[int, int]]:
    return list(pairs) + [EMPTY] * (n - len(pairs))


def loadout_plan(entry: int, rocket: bool, thrown: int, rng) -> tuple[list, list]:
    """The entry's (weapons, start list) as merc_loadout leaves them: the rocket launcher swapped for a random magnum or
    shotgun at its magazine, the remote bomb and the grenades each at `thrown` (an existing pair raised, a missing one
    put in the start list's next empty pair while there is one)."""
    _id, weapons, extras = LOADOUTS[entry]
    w = _padded(weapons, N_WEAPONS)
    if rocket:
        w = [rng.choice(SWAPS) if t == ROCKET else (t, c) for t, c in w]
    x = _padded(extras, N_EXTRAS)
    if thrown > 0:
        for kind in THROWN:
            at = next((i for i, (t, _c) in enumerate(x) if t == kind), None)
            if at is None:
                at = next((i for i, p in enumerate(x) if p == EMPTY), None)
                if at is None:                               # no room for this one: a later one present is raised
                    continue
            if x[at][0] != kind or x[at][1] < thrown:
                x[at] = (kind, thrown)
    return w, x


def _loadout_ok(entry: int, raw: bytes) -> bool:
    """This build's entry, untouched or as merc_loadout leaves it: its id and header, every weapon pair the build's (or a
    swap where the rocket launcher was), every start pair the build's, or a thrown item where the build's was empty or
    the same item."""
    eid, weapons, extras = LOADOUTS[entry]
    hd = struct.unpack_from("<5H", raw, 0)
    if hd[0] != eid or hd[1] != 900 or hd[2] != 900 or hd[3] != 0 or hd[4] != L_TAG_VALUE:
        return False
    for cur, orig in zip(_pairs(raw, L_WEAPONS, N_WEAPONS), _padded(weapons, N_WEAPONS)):
        if cur != orig and not (orig[0] == ROCKET and cur in SWAPS):
            return False
    for cur, orig in zip(_pairs(raw, L_EXTRAS, N_EXTRAS), _padded(extras, N_EXTRAS)):
        if cur != orig and not (cur[0] in THROWN and 0 < cur[1] <= THROWN_MAX and (orig == EMPTY or orig[0] == cur[0])):
            return False
    return True


def merc_loadout(g: RE6Switch, on: bool = True, rocket: bool = True, thrown: int = THROWN_MAX, seed=None) -> dict:
    """Every Mercenaries starting loadout (the table the game copies at a round's set-up, so the game itself creates the
    weapons and items): no rocket launcher - a random magnum or shotgun in its place - and the remote bomb, the hand,
    incendiary and flash grenades at `thrown` each where the start list has room. Only the changed (type, count) pairs
    are written, each read back; off writes the build's pairs back. A round already set up keeps its inventory: the
    profile runs it from round_ops, at every character select."""
    import random
    try:
        thrown = int(thrown)
    except (TypeError, ValueError):
        raise ValueError("merc_loadout thrown: 0..5 of each grenade and the remote bomb") from None
    if not 0 <= thrown <= THROWN_MAX:
        raise ValueError("merc_loadout thrown: 0..5 of each grenade and the remote bomb")
    base = g.base + LOADOUT_BLOCK
    try:
        raw = g.ad.read_memory(base, LOADOUT_SIZE * len(LOADOUTS))
    except (ValueError, OSError):
        raw = b""
    entries = [raw[i * LOADOUT_SIZE:(i + 1) * LOADOUT_SIZE] for i in range(len(LOADOUTS))]
    if len(raw) != LOADOUT_SIZE * len(LOADOUTS) or not all(_loadout_ok(i, e) for i, e in enumerate(entries)):
        return {"merc_loadout": False, "verified": False, "writes": 0,
                "reason": "the loadout table is not this build's (main+%#x): nothing written" % LOADOUT_BLOCK}
    rng = random.Random(seed)
    writes, swapped, given = 0, [], 0
    for i, cur in enumerate(entries):
        if on:
            w, x = loadout_plan(i, rocket, thrown, rng)
        else:
            w, x = _padded(LOADOUTS[i][1], N_WEAPONS), _padded(LOADOUTS[i][2], N_EXTRAS)
        at = base + i * LOADOUT_SIZE
        for off, want, have in ((L_WEAPONS, w, _pairs(cur, L_WEAPONS, N_WEAPONS)),
                                (L_EXTRAS, x, _pairs(cur, L_EXTRAS, N_EXTRAS))):
            for k, (pw, ph) in enumerate(zip(want, have)):
                if pw != ph:
                    g.ad.write_memory(at + off + 4 * k, struct.pack("<2H", *pw))   # read back by the adapter
                    writes += 1
        if on:
            swapped += [(hex(LOADOUTS[i][0]), hex(t)) for (t, _c), (o, _d) in zip(w, _padded(LOADOUTS[i][1], N_WEAPONS))
                        if o == ROCKET and t != ROCKET]
            given += sum(1 for t, _c in x if t in THROWN)
    g.state["merc_loadout"] = bool(on)
    return {"merc_loadout": bool(on), "verified": True, "writes": writes, "rocket_swaps": swapped,
            "thrown_pairs": given, "thrown_each": thrown if on else None,
            "note": "the Mercenaries' starting loadouts (main+%#x, read by the round set-up main+0x38C740): no rocket "
                    "launcher, the remote bomb and the grenades given; the next round set up starts with them"
                    % LOADOUT_BLOCK}


def unlock_characters(g: RE6Switch, on: bool = True) -> dict:
    """Every character and costume in the Mercenaries select: only the mask's two u32 in cSystemInfo (copy A, copy B)
    are written, each read first and read back after; nothing to do once both hold every bit. Off changes nothing
    (an unlock is the save's: the game's own next save keeps it)."""
    from ... import re6_switch_unlock as U
    info = U.system_info(g.m, g.base)
    if info is None:
        return {"unlock_characters": bool(on), "verified": False, "reason": "no cSystemInfo yet (still booting)"}
    before = [struct.unpack("<I", g.ad.read_memory(info + off, 4))[0] for off in CHARACTER_MASK]
    writes = 0
    if on:
        for off, value in zip(CHARACTER_MASK, before):
            if value & ALL_CHARACTERS != ALL_CHARACTERS:
                g.ad.write_memory(info + off, struct.pack("<I", value | ALL_CHARACTERS))
                writes += 1
    after = [struct.unpack("<I", g.ad.read_memory(info + off, 4))[0] for off in CHARACTER_MASK]
    g.state["unlock_characters"] = bool(on)
    return {"unlock_characters": bool(on), "verified": not on or all(v & ALL_CHARACTERS == ALL_CHARACTERS for v in after),
            "before": [hex(v) for v in before], "after": [hex(v) for v in after], "writes": writes,
            "note": "the character select's mask in both cSystemInfo copies; the select lists every character and "
                    "costume from its next opening, and the game's own next save keeps it"}


def fire_interval(index: int, k: float) -> float:
    """Record index's seconds between shots at multiplier k: this build's value / k for a gun (never below FIRE_FLOOR),
    the build's own for the grenades, the remote bomb, the knife and the melee weapons (and at k=1)."""
    orig = FIRE_ORIGINAL[index]
    if k == 1.0 or index in FIRE_SKIP or not 0.0 < orig < FIRE_GUN_MAX:
        return orig
    return max(FIRE_FLOOR, orig / k)


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def fire_records(g: RE6Switch) -> list[tuple[int, int, float]] | None:
    """The weapon table's interval cells [(index, address, seconds)], or None when this is not the build's table: the
    interval's reader at FIRE_SITE must be its ldr, every record must carry the table's tag and the same first word,
    and every interval must be the build's own or one fire_rate writes (at most the build's)."""
    try:
        if struct.unpack("<I", g.ad.read_memory(g.base + FIRE_SITE, 4))[0] != FIRE_SITE_WORD:
            return None
        raw = g.ad.read_memory(g.base + FIRE_TABLE, FIRE_STRIDE * FIRE_RECORDS)
    except (ValueError, OSError):
        return None
    first = raw[:4]
    out = []
    for i in range(FIRE_RECORDS):
        o = FIRE_STRIDE * i
        if raw[o:o + 4] != first or struct.unpack_from("<i", raw, o + FIRE_TAG)[0] != FIRE_TAG_VALUE:
            return None
        cur = struct.unpack_from("<f", raw, o + FIRE_INTERVAL)[0]
        if not (cur == _f32(FIRE_ORIGINAL[i]) or FIRE_FLOOR * 0.999 <= cur <= FIRE_ORIGINAL[i] * 1.0001):
            return None
        out.append((i, g.base + FIRE_TABLE + o + FIRE_INTERVAL, cur))
    return out


def fire_rate(g: RE6Switch, mult) -> dict:
    try:
        k = float(mult if mult is not None else FIRE_MAX)
    except (TypeError, ValueError):
        raise ValueError("fire_rate multiplier: a number 1..80 (1 = the game's)") from None
    if not 1.0 <= k <= FIRE_MAX:
        raise ValueError("fire_rate multiplier: 1..80 (1 = the game's)")
    recs = fire_records(g)
    if recs is None:
        return {"fire_rate_x": g.state.get("fire_rate", 1.0), "verified": False, "writes": 0,
                "reason": "the weapon table is not this build's (its reader at main+%#x or a record differs): nothing "
                          "written" % FIRE_SITE}
    writes = 0
    for i, addr, cur in recs:
        want = _f32(fire_interval(i, k))
        if cur != want:
            g.ad.write_memory(addr, struct.pack("<f", want))      # read back by the adapter
            writes += 1
    g.state["fire_rate"] = k
    rifle = _f32(fire_interval(0x0F, k))
    return {"fire_rate_x": k, "verified": True, "writes": writes,
            "assault_rifle_interval_s": round(rifle, 4),
            "note": "the game's own seconds between shots (weapon table +0x1C) at the build's / %g for every gun; the "
                    "grenades, the remote bomb, the knife and the melee weapons keep theirs" % k}


def _top_up(ad, g: RE6Switch, player: int) -> int:
    n = 0
    for slot, rounds, cap in g.slots(player):
        if 0 <= rounds < cap:
            _put_count(ad, slot + SLOT_ROUNDS, cap)
            n += 1
    return n


def maintain(ad, snap=None, *, enabled: bool = True, clock=time.monotonic) -> dict:
    """Each driver snapshot: infinite_ammo's magazines topped up, infinite_tablets' case and infinite_stamina's gauge kept
    (at most every CHECK_S), only into the snapshot's own player; never raises."""
    with _LOCK:
        st = ORIG.get(id(ad))
        out = {"active": False, "writes": 0, "verified": True}
        keeping = st and any(st.get(k) for k in ("infinite_ammo", "infinite_tablets", "infinite_stamina",
                                                 "infinite_grenades"))
        if not keeping or not enabled:
            return out
        try:
            p = (snap or {}).get("player")
            now = clock()
            if p and now - st.get("ammo_at", -1e9) >= CHECK_S:
                st["ammo_at"] = now
                g = RE6Switch(ad)
                if st.get("infinite_ammo"):
                    out["writes"] += _top_up(ad, g, p["ptr"])
                if st.get("infinite_tablets"):
                    kept = _keep_tablets(ad, g, p["ptr"])
                    st["tablets_kept"] = st.get("tablets_kept", 0) + kept
                    out["writes"] += kept
                if st.get("infinite_grenades"):
                    out["writes"] += _keep_thrown(ad, g, p["ptr"])
                if st.get("infinite_stamina"):
                    kept = _keep_stamina(ad, p["ptr"])
                    st["stamina_kept"] = st.get("stamina_kept", 0) + kept
                    out["writes"] += kept
            out["active"] = True
        except Exception as e:                               # noqa: BLE001 - a missed top-up never stops a tick
            out.update(verified=False, reason=f"{type(e).__name__}: {e}"[:160])
        return out


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE6Switch | None = None, **_extra) -> dict:
    with _LOCK:
        g = g or RE6Switch(ad)
        op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
        op = {"fire": "fire_rate", "rapid_fire": "fire_rate", "rain_fire": "fire_rate", "ammo": "infinite_ammo",
              "unlimited_ammo": "infinite_ammo",
              "no_ammo": "infinite_ammo", "tablets": "infinite_tablets", "infinite_heal": "infinite_tablets",
              "heal_keep": "infinite_tablets", "stamina": "infinite_stamina", "combat_gauge": "infinite_stamina",
              "unlimited_stamina": "infinite_stamina", "characters": "unlock_characters", "loadout": "merc_loadout",
              "loadouts": "merc_loadout", "no_rocket": "merc_loadout", "grenades": "infinite_grenades",
              "infinite_mines": "infinite_grenades", "remote_bombs": "infinite_grenades",
              "all_characters": "unlock_characters", "unlock_all": "unlock_characters"}.get(op, op)
        if op == "status":
            return g.status()
        if op == "infinite_ammo":
            return infinite_ammo(g, bool(on))
        if op == "infinite_tablets":
            return infinite_tablets(g, bool(on))
        if op == "infinite_stamina":
            return infinite_stamina(g, bool(on))
        if op == "infinite_grenades":
            return infinite_grenades(g, bool(on))
        if op == "unlock_characters":
            return unlock_characters(g, bool(on))
        if op == "merc_loadout":
            return merc_loadout(g, bool(on), rocket=_extra.get("rocket", True) not in (False, "keep", "off"),
                                thrown=_extra.get("thrown", THROWN_MAX), seed=_extra.get("seed"))
        if op == "fire_rate":
            return fire_rate(g, 1.0 if on is False else multiplier)
        if op == "revert_all":
            return {"infinite_ammo": infinite_ammo(g, False), "infinite_tablets": infinite_tablets(g, False),
                    "infinite_stamina": infinite_stamina(g, False), "infinite_grenades": infinite_grenades(g, False),
                    "fire_rate": fire_rate(g, 1.0),
                    "merc_loadout": merc_loadout(g, False)}
        raise ValueError(f"re6_switch_mods: unknown op {op!r} (status, infinite_ammo, infinite_tablets, "
                         "infinite_stamina, infinite_grenades, unlock_characters, fire_rate, merc_loadout, revert_all)")
