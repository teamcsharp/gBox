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
  mine_loadout on=true      Chris (BSAA)'s loadout template: proximity bomb x5 at grid 1 (D-pad up) in place of his
                            hand grenades. The game builds the stack itself at the next round's start (no item record or
                            pointer is ever written); with infinite_ammo's flag on the bomb (WP0A) a placement spends
                            none. Off: the grenades back (the next round)

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
  main+0x1AAD9A8  the Mercenaries loadout templates (read 2026-10-27 in MercMode's session): 12 records of 0x30 per
                  costume (u32 id, count, -1 x3, grid, then weapon words), the game's constructor copies one block into
                  the round's inventory. Chris (BSAA): 0x201 x50 @0, 0x106 x5 @1 (hand grenades), 0x203 x30 @2, 0x102
                  M92F @3, 0x104 Ithaca @5, 0x304 spray @7, 0x101 knife @9, 0x100 @11; the same block again at
                  main+0x1AAF208 (a second bank). Other costumes carry 0x10A, the proximity bomb (x3, x5).
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
SPRAY_KEEP = 2                                               # infinite_spray keeps its count here (a use leaves one)
MINE_ID, GRENADE_ID = 0x10A, 0x106                           # WP0A the proximity bomb, WP06 the hand grenade
TEMPLATE_REC, TEMPLATE_RECS = 0x30, 12
CHRIS_TEMPLATES = (0x1AAD9A8, 0x1AAF208)                     # Chris (BSAA)'s loadout block, both banks (this build)
CHRIS_RECORDS = {0: (0x201, 50, 0), 2: (0x203, 30, 2), 3: (0x102, None, 3), 5: (0x104, None, 5), 7: (0x304, None, 7),
                 9: (0x101, None, 9), 11: (0x100, None, 11)}  # (id, count or None, grid) that name the block
MINE_SLOT = 1                                                # record 1: the grenades' (x5, grid 1 = D-pad up)
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


def chris_block(g: RE5Switch, off: int) -> bool:
    """Whether main+off holds Chris (BSAA)'s loadout block: its records as read live, record 1 the grenades or the bomb."""
    raw = g.rd(g.base + off, TEMPLATE_REC * TEMPLATE_RECS)
    for k, (idw, count, grid) in CHRIS_RECORDS.items():
        w = struct.unpack_from("<6I", raw, k * TEMPLATE_REC)
        if w[0] != idw or w[5] != grid or (count is not None and w[1] != count):
            return False
    w = struct.unpack_from("<6I", raw, MINE_SLOT * TEMPLATE_REC)
    return w[0] in (GRENADE_ID, MINE_ID) and w[1] == 5 and w[2:5] == (0xFFFFFFFF,) * 3 and w[5] == 1


def mine_loadout(g: RE5Switch, on: bool) -> dict:
    """Chris (BSAA)'s loadout template, both banks: record 1 the proximity bomb (on) or the hand grenades (off). Only the
    id word of a block whose records match is written; the round after builds its inventory from it."""
    want = MINE_ID if on else GRENADE_ID
    blocks, ok = [], True
    for off in CHRIS_TEMPLATES:
        if not chris_block(g, off):
            continue
        at = g.base + off + MINE_SLOT * TEMPLATE_REC
        if g.u32(at) != want:
            ok = g.wr(at, struct.pack("<I", want)) and ok
        blocks.append(off)
        ok = ok and g.u32(at) == want
    g.state["mine_loadout"] = bool(on)
    return {"mine_loadout": bool(on), "verified": bool(ok and blocks), "blocks": [hex(b) for b in blocks],
            "effective": "the next round's start",
            "note": "Chris (BSAA) carries the proximity bomb x5 at grid 1 (D-pad up) instead of his hand grenades"
                    if on else "Chris (BSAA)'s hand grenades back at grid 1"}


def infinite_spray(g: RE5Switch, on: bool) -> dict:
    g.state["infinite_spray"] = bool(on)
    return {"infinite_spray": bool(on), "verified": True,
            "note": "the round's First Aid Spray is kept at %d while its slot is alive (count and capacity ints only), so "
                    "a use leaves one and the game never clears the slot" % SPRAY_KEEP}


def _maintain_spray(ad, st, snap) -> int:
    """infinite_spray: the round's First Aid Spray kept at SPRAY_KEEP while its slot is alive (id 0x304, count 1 or
    more, its item object +0x30 set), so a use leaves one and the game never clears the slot or releases the item's
    object. Only the count and capacity ints of that live slot are written. Never a cleared slot, never a count of 0
    (a use under way), never a slot without its object: a replay of the saved record would put back a pointer to the
    object the game released (live 2026-10-27: +0x30 zeroed two seconds after the last use)."""
    if not (snap or {}).get("player"):
        return 0
    writes = 0
    for s in (snap or {}).get("inventory") or ():
        if s["id"] != SPRAY_ID or not 1 <= s["rounds"] < SPRAY_KEEP:
            continue
        rec = ad.read_memory(s["addr"], R.INV_SLOT)
        idw, count, cap = struct.unpack_from("<Iii", rec, R.INV_ID)
        if idw != SPRAY_ID or not 1 <= count < SPRAY_KEEP or not struct.unpack_from("<Q", rec, R.INV_OBJ)[0]:
            continue                                         # changed since the snapshot, or no item object: leave it
        ad.write_memory(s["addr"] + R.INV_ROUNDS, struct.pack("<ii", SPRAY_KEEP, max(SPRAY_KEEP, cap)))
        writes += 1
    st["sprays_kept"] = st.get("sprays_kept", 0) + writes
    return writes


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
                kept = _maintain_spray(ad, st, snap)
                out["writes"] += kept
                if kept:
                    out["spray_kept"] = True
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
        if op in ("mine_loadout", "mines", "proximity_bombs"):
            return mine_loadout(g, bool(on))
        if op == "revert_all":
            return {"infinite_ammo": infinite_ammo(g, False), "fire_rate": fire_rate(g, 1.0),
                    "infinite_spray": infinite_spray(g, False), "mine_loadout": mine_loadout(g, False)}
        raise ValueError(f"re5_switch_mods: unknown op {op!r} (status, infinite_ammo, fire_rate, infinite_spray, "
                         f"mine_loadout, revert_all)")
