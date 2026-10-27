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
  fire_rate multiplier=N    the bot's own trigger: with infinite ammo it presses ZR on every other tick on target (about
                            10 presses a second; the Wing Shooter fires on each, measured 6.7 a second with every press
                            a shot). RE6 has no measured game-side fire-rate multiplier: the shot motion's layer speed
                            (+0x5D8) leaves the pace where it is (live 2026-10-27: 20 shots in 3 s at x1, 20 at x4, 17
                            at x8), so N above 1 reports verified=False and changes nothing in the game

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
CAP_MAX = 200                                            # a capacity above this is not a gun's magazine
CHECK_S = 0.25                                           # maintain tops up at most this often
FIRE_MAX = 80.0
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

    def status(self) -> dict:
        st = {"game": GAME, "module_base": hex(self.base), "infinite_ammo": bool(self.state.get("infinite_ammo")),
              "infinite_tablets": bool(self.state.get("infinite_tablets")), "fire_rate_x": self.state.get("fire_rate", 1.0)}
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
    ad.write_memory(slot + SLOT_ROUNDS, struct.pack("<h", TABLET_KEEP))
    return 1


def fire_rate(g: RE6Switch, mult) -> dict:
    try:
        k = float(mult if mult is not None else FIRE_MAX)
    except (TypeError, ValueError):
        raise ValueError("fire_rate multiplier: a number 1..80 (1 = the game's)") from None
    if not 1.0 <= k <= FIRE_MAX:
        raise ValueError("fire_rate multiplier: 1..80 (1 = the game's)")
    g.state["fire_rate"] = k
    return {"fire_rate_x": k, "verified": k == 1.0,
            "note": "RE6 has no measured game-side fire-rate multiplier (the shot motion's speed leaves the pace where "
                    "it is); the bot presses ZR on every other tick on target, and with infinite ammo every press is a "
                    "shot (the Wing Shooter: one per press, 6.7 a second measured)"}


def _top_up(ad, g: RE6Switch, player: int) -> int:
    n = 0
    for slot, rounds, cap in g.slots(player):
        if 0 <= rounds < cap:
            ad.write_memory(slot + SLOT_ROUNDS, struct.pack("<h", cap))
            n += 1
    return n


def maintain(ad, snap=None, *, enabled: bool = True, clock=time.monotonic) -> dict:
    """Each driver snapshot: infinite_ammo's magazines topped up and infinite_tablets' case kept (at most every
    CHECK_S), only into the snapshot's own player; never raises."""
    with _LOCK:
        st = ORIG.get(id(ad))
        out = {"active": False, "writes": 0, "verified": True}
        if not st or not (st.get("infinite_ammo") or st.get("infinite_tablets")) or not enabled:
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
            out["active"] = True
        except Exception as e:                               # noqa: BLE001 - a missed top-up never stops a tick
            out.update(verified=False, reason=f"{type(e).__name__}: {e}"[:160])
        return out


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE6Switch | None = None, **_extra) -> dict:
    with _LOCK:
        g = g or RE6Switch(ad)
        op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
        op = {"fire": "fire_rate", "rapid_fire": "fire_rate", "ammo": "infinite_ammo", "unlimited_ammo": "infinite_ammo",
              "no_ammo": "infinite_ammo", "tablets": "infinite_tablets", "infinite_heal": "infinite_tablets",
              "heal_keep": "infinite_tablets"}.get(op, op)
        if op == "status":
            return g.status()
        if op == "infinite_ammo":
            return infinite_ammo(g, bool(on))
        if op == "infinite_tablets":
            return infinite_tablets(g, bool(on))
        if op == "fire_rate":
            return fire_rate(g, 1.0 if on is False else multiplier)
        if op == "revert_all":
            return {"infinite_ammo": infinite_ammo(g, False), "infinite_tablets": infinite_tablets(g, False),
                    "fire_rate": fire_rate(g, 1.0)}
        raise ValueError(f"re6_switch_mods: unknown op {op!r} (status, infinite_ammo, infinite_tablets, fire_rate, "
                         "revert_all)")
