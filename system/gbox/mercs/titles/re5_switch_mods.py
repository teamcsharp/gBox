"""Resident Evil 5 (Nintendo Switch, title 010018100CD46000 v1.0.0, main build EBFFDB223149A725A93CD9B60979F6AA) live
Mercenaries mods on Citron / Eden: data writes into the running game through the Switch adapter (write_memory reads
every write back), the originals kept and put back by the same op with on=false / multiplier=1. Everything is RAM
only: a relaunch of the game is the full revert. A bot module (gbox.hot_reload reloads it in place; ORIG survives).

The Mercenaries playbook applies the profile's playing_ops through run() when a round starts (gbox/mercs_bot.py
apply_ops), and the driver (gbox.mercs.titles.re5_switch.RE5Switch.screen) calls maintain() on every snapshot.

ops:
  status                    what is on: the no-ammo flags, the fire-rate multiplier, the player's time scale
  infinite_ammo on=true     every gun and grenade gets the Gatling's "needs no ammo" flag: no round is spent, no reload
  fire_rate multiplier=N    the player's own time scale x N while his shot motion plays (1..80; 1 = off): a held ZR
                            repeats about N times faster, up to the frame rate. Aiming, walking and turning keep the
                            game's speed (the scale is 1 whenever the shot motion is not playing)

Where (measured live 2026-10-26 in a private Citron NEO session on the Spark; docs/research/re5-switch-ram.md):
  main+0x1D08680  the weapon definition records, 0x140 each, index = weapon id. A constructor fills them at boot (no
                  relocation names them): +0x8 -> "WPnn NAME", +0x10 class (2 handgun, 4 machine gun, 5 shotgun,
                  7 magnum), +0x18 1 = automatic, +0x1C 1 = needs no ammo (the Gatling's; the fire action tests it at
                  0x96E22C before the ammo check), +0x90 f32 the fire interval offset (-10 handguns, +5 machine guns).
  main+0x1D13B28  the upgrade table, 0x210 a weapon: firepower +0x18, firing speed +0x58, reload +0x98, capacity
                  +0xD8 (s32), 4 bytes a level; the in-hand inventory slot's +0x24..+0x27 hold its four levels.
  player +0x1A08  f32 the player's time scale (1.0), read by 966 sites: his animations and action timers. The fire
                  action (0x96E310) re-arms the trigger once the shot motion's frame (+0x93C) passes firing speed +
                  the interval offset, and the shot motion itself sets the pace: 2.7 shots/s held or tapped, with the
                  interval offset at -10 or -60, and no other definition field moved it.
  player +0x8F8   u8 motion: 29 while a shot plays (gbox.mercs.titles.re5_switch.P_MOTION).
Live (round starts, the M92F, held ZR): 2.7 shots/s at x1, 4.7 x2, 8.7 x4, 15.3 x8, 16.7 x32, 24.7 x80 (the frame
rate caps it; Citron ran 40-60 fps). With the no-ammo flag its rounds stayed at 50 through the fire.
"""
from __future__ import annotations

import struct
import threading
import time

from . import re5_switch as R

GAME = "Resident Evil 5 (Nintendo Switch 010018100CD46000 v1.0.0, main EBFFDB223149A725A93CD9B60979F6AA)"
MAP_ID = R.MAP_ID
DEF_TABLE, DEF_STRIDE, N_WEAPONS = 0x1D08680, 0x140, 0x2C   # the player's weapons (0x2C on are the enemies')
DEF_NAME, DEF_NOAMMO, DEF_INTERVAL_OFS = 0x8, 0x1C, 0x90
DEF_SIGNATURE = {0x00: "WP00 NONE", 0x02: "WP02 HAND_M92F", 0x15: "WP15 MACHINE_GATLING"}
NO_AMMO_SKIP = ("NONE", "Empty", "KNIFE", "STUNROD")         # no rounds to spend
UPG_TABLE, UPG_STRIDE = 0x1D13B28, 0x210
P_TIME_SCALE = 0x1A08
MOTION_SHOT = 29
FIRE_MAX = 80.0
CHECK_S = 2.0                                                # maintain reads the no-ammo flags back this often
SPRAY_ID = 0x304                                             # the First Aid Spray (Chris carries one at grid 7)
ORIG: dict = {}                                              # id(adapter) -> this boot's originals and settings
_LOCK = threading.RLock()
RELOAD_KEEP = ("ORIG", "_LOCK")                              # a bot hot reload keeps the originals and the settings


class Mem:
    """The session's guest memory for re5_switch's readers: rd() and the adapter (its guest rows find main)."""

    def __init__(self, ad):
        self.adapter = ad

    def rd(self, a: int, n: int) -> bytes:
        return self.adapter.read_memory(a, n)


class RE5Switch:
    """RE5 Switch in one session: main's base this boot, the weapon table checked against this build."""

    def __init__(self, ad):
        self.ad = ad
        self.m = Mem(ad)
        self.state = ORIG.setdefault(id(ad), {})
        if isinstance(self.state.get("base"), int):
            self.m.module_base = self.state["base"]          # checked with one read; searched again if it moved
        base = R.module_base(self.m)
        if base is None:
            raise RuntimeError("RE5 Switch's main is not in this session's memory (another title or build?)")
        self.base = base
        if self.state.get("base") != base:                   # a new boot: the old originals are void
            self.state.clear()
            self.state["base"] = base
        for wid, want in DEF_SIGNATURE.items():
            if self.name(wid) != want:
                raise RuntimeError(f"the weapon table does not match this build (record {wid:#x} is "
                                   f"{self.name(wid)!r}, not {want!r})")

    def rd(self, a: int, n: int) -> bytes:
        return self.ad.read_memory(a, n)

    def u32(self, a: int) -> int:
        return struct.unpack("<I", self.rd(a, 4))[0]

    def f32(self, a: int) -> float:
        return struct.unpack("<f", self.rd(a, 4))[0]

    def wr(self, a: int, data: bytes) -> bool:
        res = self.ad.write_memory(a, data)
        return bool(res.get("verified", True)) if isinstance(res, dict) else True

    def record(self, wid: int) -> int:
        return self.base + DEF_TABLE + DEF_STRIDE * wid

    def name(self, wid: int) -> str:
        try:
            p = struct.unpack("<Q", self.rd(self.record(wid) + DEF_NAME, 8))[0]
            return self.rd(p, 40).split(b"\0")[0].decode("ascii", "replace").strip()
        except (ValueError, OSError, struct.error):
            return ""

    def ammo_weapons(self) -> list[int]:
        """The weapons that spend rounds: every named record but NONE / Empty, the knives and the stun rod."""
        return [wid for wid in range(N_WEAPONS)
                if (n := self.name(wid)).startswith("WP") and not any(s in n for s in NO_AMMO_SKIP)]

    def status(self) -> dict:
        flags = {wid: self.u32(self.record(wid) + DEF_NOAMMO) for wid in self.ammo_weapons()}
        st = {"game": GAME, "module_base": hex(self.base),
              "no_ammo_weapons": [self.name(w) for w, f in flags.items() if f == 1],
              "infinite_ammo": bool(flags) and all(f == 1 for f in flags.values()),
              "fire_rate_x": self.state.get("fire_rate", 1.0)}
        snap = R.snapshot(self.m)
        if snap.get("player"):
            p = snap["player"]["ptr"]
            st["player_time_scale"] = round(self.f32(p + P_TIME_SCALE), 3)
            st["player_motion"] = snap["player"].get("motion")
        return st


def infinite_ammo(g: RE5Switch, on: bool) -> dict:
    orig = g.state.setdefault("noammo", {})
    ok = True
    for wid in g.ammo_weapons():
        at = g.record(wid) + DEF_NOAMMO
        cur = g.u32(at)
        orig.setdefault(wid, cur)
        want = 1 if on else orig[wid]
        if cur != want:
            ok = g.wr(at, struct.pack("<I", want)) and ok
    g.state["infinite_ammo"] = bool(on)
    flags = [g.u32(g.record(wid) + DEF_NOAMMO) for wid in g.ammo_weapons()]
    verified = ok and all(f == 1 for f in flags) if on else ok
    return {"infinite_ammo": bool(on), "verified": bool(verified), "weapons": len(flags),
            "note": "the Gatling's own 'needs no ammo' flag on every gun and grenade: rounds are never spent and no "
                    "reload is ever needed (the rounds word stays where it was)"}


def fire_rate(g: RE5Switch, mult) -> dict:
    try:
        k = float(mult if mult is not None else FIRE_MAX)
    except (TypeError, ValueError):
        raise ValueError("fire_rate multiplier: a number 1..80 (1 = the game's)") from None
    if not 1.0 <= k <= FIRE_MAX:
        raise ValueError("fire_rate multiplier: 1..80 (1 = the game's)")
    g.state["fire_rate"] = k
    restored = 0
    if k == 1.0 and g.state.get("scaled"):                   # off: the player's own pace back now (his round's player)
        p = R.snapshot(g.m).get("player")
        if p and p["ptr"] == g.state["scaled"][0]:
            restored = _restore_scale(g.ad, g.state)
        g.state.pop("scaled", None)
    return {"fire_rate_x": k, "verified": True, "restored": restored,
            "note": "the player's time scale x N while his shot motion plays (maintained every driver snapshot): a "
                    "held ZR repeats about N times faster, capped by the frame rate (live: x8 15 shots/s, x80 25)"}


def infinite_spray(g: RE5Switch, on: bool) -> dict:
    g.state["infinite_spray"] = bool(on)
    if not on:
        g.state.pop("spray", None)
    return {"infinite_spray": bool(on), "verified": True,
            "note": "the round's own First Aid Spray record is kept and written back into its slot once the spray is "
                    "used up (only into that emptied slot, never over another item): the bot heals with it again"}


def _maintain_spray(ad, st, snap) -> int:
    """infinite_spray: keep the round's spray slot record (the game's own bytes, the in-hand flag cleared); once that
    slot holds no spray any more (empty, or a spray of count 0), write the record back. Never into a slot holding
    something else (the inventory moved), never for another round's player."""
    p, inv = (snap or {}).get("player"), (snap or {}).get("inventory")
    if not p or inv is None:
        return 0
    spray = next((s for s in inv if s["id"] == SPRAY_ID and s["rounds"] >= 1), None)
    saved = st.get("spray")
    if spray is not None:
        if not saved or saved["player"] != p.get("ptr") or saved["addr"] != spray["addr"]:
            rec = bytearray(ad.read_memory(spray["addr"], R.INV_SLOT))
            struct.pack_into("<i", rec, R.INV_HAND, 0)
            st["spray"] = {"player": p.get("ptr"), "addr": spray["addr"], "record": bytes(rec)}
        return 0
    if not saved or saved["player"] != p.get("ptr"):
        return 0
    cur = ad.read_memory(saved["addr"], R.INV_SLOT)
    idw = struct.unpack_from("<I", cur, R.INV_ID)[0]
    count = struct.unpack_from("<i", cur, R.INV_ROUNDS)[0]
    if idw in R.EMPTY_IDS or (idw == SPRAY_ID and count < 1):
        ad.write_memory(saved["addr"], saved["record"])
        st["sprays_restored"] = st.get("sprays_restored", 0) + 1
        return 1
    return 0


def _restore_scale(ad, st) -> int:
    scaled = st.pop("scaled", None)
    if not scaled:
        return 0
    ptr, before = scaled
    try:
        if struct.unpack("<f", ad.read_memory(ptr + P_TIME_SCALE, 4))[0] != before:
            ad.write_memory(ptr + P_TIME_SCALE, struct.pack("<f", before))
            return 1
    except (ValueError, OSError, RuntimeError):
        pass                                                 # the round's player is gone: nothing to put back
    return 0


def maintain(ad, snap=None, *, enabled: bool = True, clock=time.monotonic) -> dict:
    """Each driver snapshot: fire_rate's time scale up while the shot motion plays and the game's own value otherwise
    (and whenever enabled is False: out of a round, the bot stopping); infinite_ammo's flags read back every CHECK_S
    and put back if the game reset them. Writes only for a setting an op turned on, and only into the snapshot's own
    player (a raised scale on a player the round already freed is dropped, never written); never raises."""
    with _LOCK:
        st = ORIG.get(id(ad))
        out = {"active": False, "writes": 0, "verified": True}
        if not st:
            return out
        try:
            p = (snap or {}).get("player")
            k = st.get("fire_rate", 1.0)
            scaled = st.get("scaled")
            if scaled and (not p or p.get("ptr") != scaled[0]):
                st.pop("scaled", None)                       # that player is gone with his round: nothing to put back
            elif scaled and (not enabled or k <= 1.0 or p.get("motion") != MOTION_SHOT):
                out["writes"] += _restore_scale(ad, st)
            elif enabled and p and k > 1.0 and p.get("motion") == MOTION_SHOT and not scaled:
                at = p["ptr"] + P_TIME_SCALE
                before = struct.unpack("<f", ad.read_memory(at, 4))[0]
                if abs(before - 1.0) < 1e-3:                 # the game's own pace only (not a slow-motion moment)
                    ad.write_memory(at, struct.pack("<f", k))
                    st["scaled"] = (p["ptr"], before)
                    out["writes"] += 1
            out["active"] = bool(st.get("scaled"))
            now = clock()
            if enabled and st.get("infinite_ammo") and now - st.get("ammo_checked", -1e9) >= CHECK_S:
                st["ammo_checked"] = now
                g = RE5Switch(ad)
                if any(g.u32(g.record(w) + DEF_NOAMMO) != 1 for w in g.ammo_weapons()):
                    out["ammo_restored"] = infinite_ammo(g, True)["verified"]
                    out["writes"] += 1
            if enabled and st.get("infinite_spray"):
                restored = _maintain_spray(ad, st, snap)
                out["writes"] += restored
                if restored:
                    out["spray_restored"] = True
        except Exception as e:                               # noqa: BLE001 - a missed update never stops a tick
            out.update(verified=False, reason=f"{type(e).__name__}: {e}"[:160])
        return out


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE5Switch | None = None, **_extra) -> dict:
    with _LOCK:
        g = g or RE5Switch(ad)
        op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
        op = {"fire": "fire_rate", "rapid_fire": "fire_rate", "ammo": "infinite_ammo", "unlimited_ammo": "infinite_ammo",
              "no_ammo": "infinite_ammo", "auto_first_aid": "infinite_spray"}.get(op, op)
        if op == "status":
            return g.status()
        if op == "infinite_ammo":
            return infinite_ammo(g, bool(on))
        if op == "fire_rate":
            return fire_rate(g, 1.0 if on is False else multiplier)
        if op == "infinite_spray":
            return infinite_spray(g, bool(on))
        if op == "revert_all":
            return {"infinite_ammo": infinite_ammo(g, False), "fire_rate": fire_rate(g, 1.0),
                    "infinite_spray": infinite_spray(g, False)}
        raise ValueError(f"re5_switch_mods: unknown op {op!r} (status, infinite_ammo, fire_rate, infinite_spray, "
                         f"revert_all)")
