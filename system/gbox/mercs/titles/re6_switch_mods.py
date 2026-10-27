"""Resident Evil 6 (Nintendo Switch, title 01002A000CD48000 v1.0.2, main build 061D2A06CD700785E987C42CE2D72231) live
Mercenaries mods on Citron: data writes into the running game through the Switch adapter (write_memory reads every
write back). Everything is RAM only: a relaunch is the full revert. A bot module (gbox.hot_reload reloads it in place;
ORIG survives).

The Mercenaries playbook applies the profile's playing_ops through run() when a round starts (gbox/mercs_bot.py
apply_ops), and the driver (gbox.mercs.titles.re6_switch.RE6Switch.screen) calls maintain() on every snapshot.

ops:
  status                    what is on, and the in-hand weapon's rounds / capacity
  infinite_ammo on=true     every gun in the inventory keeps a full magazine: a slot whose rounds fell below its capacity
                            is topped up on the next snapshot, so the gun never empties and never reloads
  fire_rate multiplier=N    the bot's own trigger: with infinite ammo it presses ZR on every other tick on target (about
                            10 presses a second; the Wing Shooter fires on each, measured 6.7 a second with every press
                            a shot). RE6 has no measured game-side fire-rate multiplier: the shot motion's layer speed
                            (+0x5D8) leaves the pace where it is (live 2026-10-27: 20 shots in 3 s at x1, 20 at x4, 17
                            at x8), so N above 1 reports verified=False and changes nothing in the game

Where (measured live 2026-10-27 in a private Citron NEO session on the Spark; docs/research/re6-switch-ram.md):
  player +0x5070  the inventory: cItem slots of 0x28 (vtable main+0x2875848), +0xE s16 the rounds in the magazine,
                  +0x14 s16 its capacity (the Wing Shooter 18 / 18; three shots took it to 15, the HUD's magazine row),
                  +0x16 the carry limit
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
SLOT_VTABLE = 0x2875848                                  # cItem
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
        """The gun slots [(slot, rounds, capacity)]: cItem records with a magazine (0 < capacity <= CAP_MAX)."""
        out = []
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * N_SLOTS)
        except (ValueError, OSError):
            return out
        for i in range(N_SLOTS):
            o = SLOT_STRIDE * i
            vt = struct.unpack_from("<Q", raw, o)[0]
            if vt != self.base + SLOT_VTABLE:
                break
            rounds, cap = struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0], struct.unpack_from("<h", raw, o + SLOT_CAP)[0]
            if 0 < cap <= CAP_MAX:
                out.append((player + SLOTS + o, rounds, cap))
        return out

    def status(self) -> dict:
        st = {"game": GAME, "module_base": hex(self.base), "infinite_ammo": bool(self.state.get("infinite_ammo")),
              "fire_rate_x": self.state.get("fire_rate", 1.0)}
        snap = R.snapshot(self.m)
        p = snap.get("player")
        if p:
            st["guns"] = [{"rounds": r, "capacity": c} for _, r, c in self.slots(p["ptr"])]
            st["in_hand_rounds"] = p.get("ammo")
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
    """Each driver snapshot: infinite_ammo's magazines topped up (at most every CHECK_S), only into the snapshot's own
    player; never raises."""
    with _LOCK:
        st = ORIG.get(id(ad))
        out = {"active": False, "writes": 0, "verified": True}
        if not st or not st.get("infinite_ammo") or not enabled:
            return out
        try:
            p = (snap or {}).get("player")
            now = clock()
            if p and now - st.get("ammo_at", -1e9) >= CHECK_S:
                st["ammo_at"] = now
                out["writes"] += _top_up(ad, RE6Switch(ad), p["ptr"])
            out["active"] = True
        except Exception as e:                               # noqa: BLE001 - a missed top-up never stops a tick
            out.update(verified=False, reason=f"{type(e).__name__}: {e}"[:160])
        return out


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE6Switch | None = None, **_extra) -> dict:
    with _LOCK:
        g = g or RE6Switch(ad)
        op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
        op = {"fire": "fire_rate", "rapid_fire": "fire_rate", "ammo": "infinite_ammo", "unlimited_ammo": "infinite_ammo",
              "no_ammo": "infinite_ammo"}.get(op, op)
        if op == "status":
            return g.status()
        if op == "infinite_ammo":
            return infinite_ammo(g, bool(on))
        if op == "fire_rate":
            return fire_rate(g, 1.0 if on is False else multiplier)
        if op == "revert_all":
            return {"infinite_ammo": infinite_ammo(g, False), "fire_rate": fire_rate(g, 1.0)}
        raise ValueError(f"re6_switch_mods: unknown op {op!r} (status, infinite_ammo, fire_rate, revert_all)")
