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
  mines multiplier=S on=    the PS3 tool's op: mine_loadout plus the Switch bot's cadence (one every S seconds; the
                            settings reach the bot through the driver's snapshot "mine_settings"); "only" is PS3-only yet
  unlimited_health on=      the PS3's: living health refilled to a boosted maximum (HEALTH_MAX) every driver snapshot
                            (never a dead or dying player); the PS3's Muteki hit immunity is not mapped here yet
  weapon_override weapon=W only=   any RE5 weapon as every character's main gun (only: every gun slot, e.g. the longbow
                            only), loadout weapons=[...] seed=  every gun drawn from the powerful campaign weapons,
  replace_rockets / replace_long_guns seed=   the rocket launcher (and the sniper rifles) as a magnum: all in the
                            Mercenaries loadout templates, from the next round's start (the PS3's semantics, below)
  random_cheats seed=       the PS3's randomizer with the ops this edition has (fire_rate x80, infinite_ammo, loadout,
                            the long guns replaced); addresses: this build's address table

The PS3 tool (gbox.re5_mods_tool, `re5_mods`) routes a Switch session here (tool_run): the same op names, parameters and
result shape ({op, ..., status}); an op this edition cannot do yet answers verified False with "not yet on Switch: why",
and status()["capabilities"] says the same for the panel.

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
  main+0x1AB6F48  the loadout descriptors (static data, main's ELF, its relocations): 68 entries of 0x18 (the block's
                  pointer, 0, the record count 12), the PS3's descriptor table: 0-13 the campaign's, 14-23 and 24-33 the
                  Mercenaries' two banks (Chris (BSAA) at 14 and 24 = the blocks above), 34-67 the rest. A record is
                  the PS3's plus a word: id +0x0, count +0x4 (-1: the weapon's own), -1 x3, grid +0x14, in hand +0x18,
                  packed upgrade levels +0x1C, flags +0x20.
"""
from __future__ import annotations

import math
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
FIRE_MAX = 30.0                                              # the operator's round loadout, 2026-10-28
FIRE_TOP = 1000.0                                            # the PS3 panel's top; the frame rate caps it long before
CHECK_S = 2.0                                                # maintain reads the no-ammo flags back this often
SPRAY_ID = 0x304                                             # the First Aid Spray (Chris carries one at grid 7)
SPRAY_KEEP = 2                                               # infinite_spray keeps its count here (a use leaves one)
MINE_ID, GRENADE_ID = 0x10A, 0x106                           # WP0A the proximity bomb, WP06 the hand grenade
TEMPLATE_REC, TEMPLATE_RECS = 0x30, 12
CHRIS_TEMPLATES = (0x1AAD9A8, 0x1AAF208)                     # Chris (BSAA)'s loadout block, both banks (this build)
CHRIS_RECORDS = {0: (0x201, 50, 0), 2: (0x203, 30, 2), 3: (0x102, None, 3), 5: (0x104, None, 5), 7: (0x304, None, 7),
                 9: (0x101, None, 9), 11: (0x100, None, 11)}  # (id, count or None, grid) that name the block
MINE_SLOT = 1                                                # record 1: the grenades' (x5, grid 1 = D-pad up)
DESC_TABLE, DESC_STRIDE, DESC_N = 0x1AB6F48, 0x18, 68        # the loadout descriptors (block pointer, 0, 12)
MERC_DESC = tuple(range(14, DESC_N))                         # every loadout but the campaign's (0-13)
MAIN_SPAN = 0x2800000                                        # main's mapping (a block pointer is inside it)
REC_ID, REC_COUNT, REC_GRID, REC_HAND, REC_UPG = 0x0, 0x4, 0x14, 0x18, 0x1C
KNIFE_IDS = frozenset({0x100, 0x101, 0x10E, 0x114, 0x123, 0x124})   # the knives and WP00 (never a gun to replace)
POWERFUL = (0x11B, 0x11A, 0x119, 0x115, 0x10D, 0x11C, 0x11D, 0x116, 0x10C, 0x120, 0x10B)   # the PS3 tool's draw
LOADOUT_WEAPONS = frozenset(POWERFUL) | {0x104, 0x117}          # explicit pools also accept Ithaca and Jail Breaker
MAGNUMS = (0x10B, 0x11A, 0x11B)
# rampage_loadout (the 5 m rampage, operator 16:05: "blasting endless magnums or shotguns"): a block with no shotgun or
# magnum on a D-pad slot gets RAMPAGE_GUN in its first such gun slot that is not the gun in hand (its own full
# magazine). Chris (BSAA) already carries the Ithaca M37 on the D-pad's right: his block stays as it is.
RAMPAGE_GUN, QUICK_GRIDS = 0x119, frozenset({1, 3, 5, 7})   # WP19 Hydra
ROCKETS, LONG_GUNS = frozenset({0x10D}), frozenset({0x10D, 0x105, 0x11C, 0x120})   # rocket launcher; and the snipers
HEALTH_MAX = 30000                                           # unlimited_health's boosted maximum (the PS3's)
MINE_EVERY_DEFAULT = 120.0                                   # the Switch bot's cadence unless `mines` sets one
THROWN_ITEMS = frozenset({0x06, 0x07, 0x08, 0x0A})           # grenades and the bomb: a loadout draw keeps them
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
        raise ValueError(f"fire_rate multiplier: a number 1..{FIRE_TOP:g} (1 = the game's)") from None
    if 0.1 <= k < 1.0:
        raise ValueError("fire_rate multiplier: not yet on Switch: slower than the game's own rate (1..%g)" % FIRE_TOP)
    if not 1.0 <= k <= FIRE_TOP:
        raise ValueError(f"fire_rate multiplier: 1..{FIRE_TOP:g} (1 = the game's)")
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
    if g.state.get("tpl_orig") is not None:              # the template ops own the blocks now: compose them
        g.state["mine_loadout"] = bool(on)
        res = compose_templates(g)
        at = [g.base + off + MINE_SLOT * TEMPLATE_REC for off in CHRIS_TEMPLATES]
        done = [hex(off) for off, a in zip(CHRIS_TEMPLATES, at) if g.u32(a) == want]
        return {"mine_loadout": bool(on), "verified": bool(res["verified"] and done), "blocks": done,
                "effective": "the next round's start",
                "note": "Chris (BSAA)'s record 1 the proximity bomb x5 at grid 1" if on else
                        "Chris (BSAA)'s hand grenades back at grid 1"}
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


# --- the Mercenaries loadout templates: weapon_override, loadout, the replacements (the PS3 tool's semantics) ----------
def template_blocks(g: RE5Switch) -> list:
    """[(descriptor index, block address)] of every loadout but the campaign's, each block checked to be one: 12
    records of 0x30 whose words 2-4 are -1, whose grid is 0-11 and whose id is an item word."""
    raw = g.rd(g.base + DESC_TABLE, DESC_STRIDE * DESC_N)
    out = []
    for i in MERC_DESC:
        ptr, _zero, n = struct.unpack_from("<QQQ", raw, DESC_STRIDE * i)
        if n != TEMPLATE_RECS or not g.base <= ptr < g.base + MAIN_SPAN:
            raise RuntimeError(f"the loadout descriptors do not match this build (entry {i}: {ptr:#x}, {n})")
        block = g.rd(ptr, TEMPLATE_REC * TEMPLATE_RECS)
        for k in range(TEMPLATE_RECS):
            w = struct.unpack_from("<6I", block, k * TEMPLATE_REC)
            if w[2:5] != (0xFFFFFFFF,) * 3 or w[5] > 11 or w[0] > 0xFFF:
                raise RuntimeError(f"the loadout block at main+{ptr - g.base:#x} is not one (record {k})")
        out.append((i, ptr))
    return out


def _tpl_orig(g: RE5Switch) -> dict:
    """Every loadout block as the game had it (read once a boot; mine_loadout's bomb in Chris's record 1 counted as
    the grenades it replaced, so a block read after it is still the original)."""
    orig = g.state.get("tpl_orig")
    if orig is None:
        orig = {}
        for _i, ptr in template_blocks(g):
            t = bytearray(g.rd(ptr, TEMPLATE_REC * TEMPLATE_RECS))
            if ptr - g.base in CHRIS_TEMPLATES and struct.unpack_from("<I", t, MINE_SLOT * TEMPLATE_REC)[0] == MINE_ID:
                struct.pack_into("<I", t, MINE_SLOT * TEMPLATE_REC, GRENADE_ID)
            orig[ptr] = bytes(t)
        g.state["tpl_orig"] = orig
    return orig


def _is_gun(idw: int) -> bool:
    return idw >> 8 == 1 and idw not in KNIFE_IDS


def compose_templates(g: RE5Switch) -> dict:
    """Every loadout block from its original and the template ops on now, in order: weapon_override (else loadout's
    draw), then the rocket / long-gun replacements, then mine_loadout's bomb in Chris's record 1. A replaced weapon's
    upgrade levels go to 0 (none indexes past the new weapon's table). Only a block that differs is written, then read
    back. Effective at the next round's start (the game copies the block into the inventory then)."""
    import random
    orig = _tpl_orig(g)
    override, draw, repl = g.state.get("weapon_override"), g.state.get("loadout"), g.state.get("replace")
    writes, records, ok = 0, 0, True
    for ptr, raw in orig.items():
        t = bytearray(raw)
        used: list = []
        rng = random.Random(f"{(draw or {}).get('seed')}:{ptr - g.base:x}")
        choice = rng.choice(draw["pool"]) if draw and draw.get("only") else None
        for k in range(TEMPLATE_RECS):
            o = k * TEMPLATE_REC
            idw, = struct.unpack_from("<I", t, o + REC_ID)
            hand, = struct.unpack_from("<I", t, o + REC_HAND)
            new = None
            if override and _is_gun(idw) and (idw & 0xFF) not in THROWN_ITEMS and (override["only"] or hand == 1):
                new = 0x100 | override["item"]
            elif not override and draw and _is_gun(idw) and (idw & 0xFF) not in THROWN_ITEMS:
                pool = [w for w in draw["pool"] if w not in used] or draw["pool"]
                new = choice if choice is not None else rng.choice(pool)
                if new in LONG_GUNS:
                    new = rng.choice([w for w in MAGNUMS if w not in used] or MAGNUMS)
                used.append(new)
            cur = new if new is not None else idw
            if repl and cur in repl["unwanted"]:
                new = random.Random(f"{repl['seed']}:{ptr - g.base:x}:{k}").choice(MAGNUMS)
                struct.pack_into("<i", t, o + REC_COUNT, -1)          # its own full magazine
            if new is not None:
                struct.pack_into("<I", t, o + REC_ID, new)
                struct.pack_into("<I", t, o + REC_UPG, 0)
                records += 1
        if g.state.get("rampage_loadout"):
            records += int(_rampage_block(t))
        if g.state.get("mine_loadout") and ptr - g.base in CHRIS_TEMPLATES \
                and struct.unpack_from("<I", t, MINE_SLOT * TEMPLATE_REC)[0] == GRENADE_ID:
            struct.pack_into("<I", t, MINE_SLOT * TEMPLATE_REC, MINE_ID)
        if g.rd(ptr, len(t)) != bytes(t):
            ok = g.wr(ptr, bytes(t)) and ok
            ok = ok and g.rd(ptr, len(t)) == bytes(t)
            writes += 1
    return {"verified": bool(ok), "blocks": len(orig), "blocks_written": writes, "records_changed": records,
            "effective_next_round": True,
            "note": "takes effect at the next round start (the game copies the template into the inventory then)"}


def _rampage_block(t: bytearray) -> bool:
    """One block: a shotgun or magnum on a D-pad slot (RAMPAGE_GUN in the first other gun slot there if none)."""
    from . import re5_weapons
    quick = []
    for k in range(TEMPLATE_RECS):
        o = k * TEMPLATE_REC
        idw, = struct.unpack_from("<I", t, o + REC_ID)
        grid, = struct.unpack_from("<I", t, o + REC_GRID)
        hand, = struct.unpack_from("<I", t, o + REC_HAND)
        if _is_gun(idw) and (idw & 0xFF) not in THROWN_ITEMS and grid in QUICK_GRIDS:
            quick.append((o, idw, hand))
    fam = lambda idw: getattr(re5_weapons.WEAPONS.get(idw & 0xFF), "family", None)
    if any(fam(idw) in ("shotgun", "magnum") for _o, idw, _h in quick):
        return False
    spare = next((o for o, idw, hand in quick if hand != 1), None)
    if spare is None:
        return False
    struct.pack_into("<I", t, spare + REC_ID, RAMPAGE_GUN)
    struct.pack_into("<I", t, spare + REC_UPG, 0)
    struct.pack_into("<i", t, spare + REC_COUNT, -1)
    return True


def rampage_loadout(g: RE5Switch, on: bool = True) -> dict:
    """Every Mercenaries loadout with a shotgun or a magnum on a D-pad slot (the 5 m rampage's gun), from the next
    round; off: the blocks composed without it."""
    g.state["rampage_loadout"] = bool(on)
    res = compose_templates(g)
    return {"rampage_loadout": bool(on), **res,
            "note": "a shotgun or magnum on a D-pad slot in every loadout from the next round (the Hydra where none)"}


def _item(weapon) -> int:
    from . import re5_weapons
    item = (int(str(weapon), 0) if isinstance(weapon, str) else int(weapon)) & 0xFF
    if item not in re5_weapons.WEAPONS:
        raise ValueError(f"unknown RE5 weapon {item:#x}")
    return item


def weapon_override(g: RE5Switch, weapon=None, only: bool = False) -> dict:
    """Any RE5 weapon as every character's main gun (only: every gun slot, e.g. longbow-only rounds); None: the game's
    loadout. Kept across rounds; loadout() honours it instead of drawing (the PS3 tool's). Grenades and the bomb stay
    what they are (a gun slot is not a grenade's), so the Switch bot's bombs survive a bow-only round."""
    from . import re5_weapons
    if weapon in (None, "", "auto"):
        g.state.pop("weapon_override", None)
    else:
        item = _item(weapon)
        g.state["weapon_override"] = {"item": item, "weapon": re5_weapons.WEAPONS[item].name, "only": bool(only)}
    res = compose_templates(g)
    return {"weapon_override": g.state.get("weapon_override"), "records": res["records_changed"], **res,
            "template_banks": res["blocks"]}


def loadout(g: RE5Switch, weapons=None, seed=None, on: bool = True, each_round: bool = False, only: bool = False) -> dict:
    """Every gun in every Mercenaries loadout drawn from the powerful campaign weapons (weapons: a pool of them),
    without repeats inside a block, the long guns as magnums (the PS3 tool's); on=False: the game's guns back. An
    active weapon_override wins over the draw. only: one draw per character loadout, shared by all its gun slots.
    The profile's round_ops draws before native inventory construction. each_round: maintain() draws again whenever a new round's player shows
    up, so every round brings other guns (operator 2026-10-27: "i want the characters using random weapons from the
    game and campaign in mercenaries"; the game copies the blocks at a round's start, so a draw lands a round later)."""
    import random
    if not on:
        g.state.pop("loadout", None)
        return {"loadout": "the game's", **compose_templates(g)}
    pool = [(int(w, 0) if isinstance(w, str) else int(w)) | 0x100 for w in (weapons or [])]
    if any(w not in LOADOUT_WEAPONS for w in pool):
        raise ValueError("loadout: unsupported weapon in the requested pool")
    pool = pool or list(POWERFUL)
    g.state["loadout"] = {"seed": seed if seed is not None else random.random(), "pool": pool,
                          "each_round": bool(each_round), "only": bool(only)}
    res = compose_templates(g)
    if g.state.get("weapon_override"):
        return {"loadout": "the weapon override", "weapon_override": g.state["weapon_override"], **res}
    return {"loadout": "random powerful campaign weapons", **res}


def replace_rockets(g: RE5Switch, seed=None) -> dict:
    """The rocket launcher in every loadout a magnum (its own full magazine) from the next round (the PS3 tool's)."""
    return _replace(g, ROCKETS, seed, "rocket_replacements")


def replace_long_guns(g: RE5Switch, seed=None) -> dict:
    """The rocket launcher and the three sniper rifles as magnums from the next round (the PS3 tool's)."""
    return _replace(g, LONG_GUNS, seed, "weapon_replacements")


def _replace(g: RE5Switch, unwanted, seed, key) -> dict:
    import random
    prev = g.state.get("replace") or {"unwanted": frozenset()}
    g.state["replace"] = {"unwanted": frozenset(prev["unwanted"]) | frozenset(unwanted),
                          "seed": seed if seed is not None else random.random()}
    res = compose_templates(g)
    return {key: sorted(f"{w:#x}" for w in g.state["replace"]["unwanted"]), **res}


# --- unlimited health (the PS3 tool's living-health refill) -------------------------------------------------------------
def unlimited_health(g: RE5Switch, on: bool) -> dict:
    st = g.state.setdefault("health", {})
    st["on"] = bool(on)
    res = {"unlimited_health": bool(on), "verified": True, "hit_immunity": False}
    p = R.snapshot(g.m).get("player")
    if on:
        res.update(_maintain_health(g.ad, st, {"player": dict(p)} if p else None))
        res["verified"] = True                       # on: the refill follows every snapshot (res "active" says now)
    elif p and p.get("ptr") == st.get("player") and st.get("original_max"):
        hp, mx = struct.unpack("<hh", g.rd(p["ptr"] + R.P_HP, 4))
        if mx == st.get("boosted_max") and 0 < hp:
            orig = st["original_max"]
            res["verified"] = g.wr(p["ptr"] + R.P_HP, struct.pack("<hh", min(hp, orig), orig))
            res["restored"] = res["verified"]
    return {**res, "note": "living health refilled to a boosted maximum on every driver snapshot; never a dead or "
                           "dying player; the PS3's Muteki hit immunity is not on Switch yet"}


def _maintain_health(ad, st, snap) -> dict:
    """Health refilled to HEALTH_MAX (the maximum raised to it) for the snapshot's own living player: never a dead one
    (0) or the dying state (exactly 1: the game resuscitates), read again just before the write."""
    p = (snap or {}).get("player")
    if not p:
        return {"active": False, "reason": "waiting for the round's player"}
    at = p["ptr"] + R.P_HP
    hp, mx = struct.unpack("<hh", ad.read_memory(at, 4))
    if not 1 < hp <= mx <= 32767:
        return {"active": False, "reason": "waiting for a living player", "hp": hp, "hp_max": mx}
    if st.get("player") != p["ptr"]:
        st.update(player=p["ptr"], original_max=mx, boosted_max=max(mx, HEALTH_MAX))
    target = st["boosted_max"]
    if hp == mx == target:
        return {"active": True, "hp": hp, "hp_max": mx}
    ad.write_memory(at, struct.pack("<hh", target, target))
    ok = struct.unpack("<hh", ad.read_memory(at, 4)) == (target, target)
    if ok and snap.get("player") is not None:
        snap["player"].update(hp=target, hp_max=target)
    return {"active": ok, "refilled": ok, "hp": target if ok else hp, "hp_max": target if ok else mx}


# --- mines: the bomb loadout and the Switch bot's cadence ---------------------------------------------------------------
def mines(g: RE5Switch, interval=None, on: bool = True) -> dict:
    """The PS3 tool's `mines`: on: Chris (BSAA)'s bombs (mine_loadout) and the bot places one every `interval` s;
    off: the grenades back and no placements. "only" (mines-only rounds) is the PS3's alone yet."""
    only = str(interval).lower() == "only" or interval == 0
    try:
        every = MINE_EVERY_DEFAULT if interval is None or only else float(interval)
    except (TypeError, ValueError):
        raise ValueError("mines: the interval in seconds (2..600), or 'only'") from None
    if not 2.0 <= every <= 600.0:
        raise ValueError("mines: the interval in seconds, 2..600")
    g.state["mine_settings"] = {"enabled": bool(on), "interval_s": every, "only": False}
    res = mine_loadout(g, bool(on))
    out = {"mine_settings": dict(g.state["mine_settings"]), "verified": res["verified"], "effective_next_round": True,
           "mine_loadout": res}
    if only:
        out["note"] = "not yet on Switch: mines-only rounds (the bot places bombs between its fights instead)"
    return out


def mercs_select(g: RE5Switch, mode=None, character=None, stage=None) -> dict:
    """The PS3 tool's mercs_select: the next round's stage and character. The Switch's own menus (re5_switch.screen)
    walk the stage and character selects to them at the next menu boundary; the current round goes on. No Mercy's
    original roster (re5_switch.CHARACTERS); the Reunion roster's select positions are not mapped here yet."""
    m = str(mode or "no_mercy").strip().lower().replace(" ", "_")
    if m in ("reunion", "mercenaries_reunion"):
        return {"verified": False, "queued": False,
                "reason": "not yet on Switch: the Reunion roster's select positions are not mapped"}
    if m not in ("no_mercy", "mercenaries", "mercenaries_united", "united"):
        raise ValueError("mercs_select mode: no_mercy (mercenaries) on Switch")
    if stage in (None, ""):
        st = R.stage_target()
    elif isinstance(stage, str) and not stage.strip().isdigit():
        names = [n.lower() for n in R.STAGE_NAMES]
        if stage.strip().lower() not in names:
            raise ValueError("mercs_select stage: 0..7 or one of " + ", ".join(R.STAGE_NAMES))
        st = names.index(stage.strip().lower())
    else:
        st = int(stage)
    if not 0 <= st < len(R.STAGE_NAMES):
        raise ValueError("mercs_select stage: 0..7")
    if character in (None, ""):
        ch = R.player_target()
    elif isinstance(character, int) or str(character).strip().isdigit():
        ch = int(character)
    else:
        names = [n.lower() for n in R.CHARACTERS]
        if str(character).strip().lower() not in names:
            return {"verified": False, "queued": False,
                    "reason": f"not yet on Switch: {character!r} is not on No Mercy's original roster here "
                              f"({', '.join(R.CHARACTERS)})"}
        ch = names.index(str(character).strip().lower())
    if not 0 <= ch < len(R.CHARACTERS):
        raise ValueError("mercs_select character: 0..9")
    R.SELECTION.update(stage=st, character=ch)
    sel = {"mode": "no_mercy", "stage": st, "stage_name": R.STAGE_NAMES[st], "character": R.CHARACTERS[ch]}
    return {"verified": True, "queued": True, "selection": sel, "effective_next_round": True,
            "native_start_verified": False,
            "note": "Selection saved for the next native menu boundary; current round continues."}


# --- the operator's gun: select_weapon / random_weapon (the PS3 tool's, re5_controls) ------------------------------------
GUN_FAMILIES = frozenset({"handgun", "automatic", "shotgun", "magnum", "bow"})   # the PS3's: no rockets or sniper rifles
WEAPON_REQUEST_S = 30.0


def eligible_guns(inv) -> list:
    """The round's guns the bot can equip by one D-pad tap (the PS3's eligible families, loaded or with no-ammo)."""
    from . import re5_weapons
    out = []
    for s in inv or ():
        spec = re5_weapons.WEAPONS.get(s.get("item"))
        if s.get("type") == 1 and s.get("grid") in R.QUICK and spec is not None and spec.family in GUN_FAMILIES:
            out.append({"item": s["item"], "weapon": spec.name, "slot": s.get("slot"), "grid": s.get("grid"),
                        "rounds": s.get("rounds"), "equipped": bool(s.get("hand"))})
    return out


def select_weapon(g: RE5Switch, weapon=None, on: bool = True, *, random_pick: bool = False) -> dict:
    """The operator's gun from the round's inventory: the bot equips it with its D-pad slot (re5_switch.Bot._gun_back)
    and keeps to it for the session; on=False: the bot's own choice again. A request is confirmed when the snapshot
    shows that gun in hand (maintain), rejected after WEAPON_REQUEST_S."""
    import random
    import uuid
    if not on:
        g.state.pop("preferred_weapon", None)
        req = g.state.get("weapon_request")
        if req and req.get("state") == "pending":
            req.update(state="rejected", reason="Automatic gun selection resumed.")
        return {"verified": True, "preference_saved": True, "automatic": True}
    guns = eligible_guns(R.snapshot(g.m).get("inventory"))
    if not guns:
        return {"queued": False, "verified": False, "reason": "No loaded quick-slot gun or longbow in this round."}
    if random_pick:
        pool = [w for w in guns if not w["equipped"]] or guns
        pick = random.SystemRandom().choice(pool)
    else:
        if type(weapon) is not int:
            raise ValueError("select_weapon requires an available native weapon ID")
        pick = next((w for w in guns if w["item"] == weapon), None)
        if pick is None:
            return {"queued": False, "verified": False, "reason": "The selected gun is not currently available."}
    req = {"id": uuid.uuid4().hex, "state": "pending", "weapon": pick["weapon"], "item": pick["item"],
           "expires": time.monotonic() + WEAPON_REQUEST_S}
    g.state["weapon_request"] = req
    g.state["preferred_weapon"] = {"item": pick["item"], "weapon": pick["weapon"]}
    return {"queued": True, "verified": False, "request": {k: v for k, v in req.items() if k != "expires"},
            "preference_saved": True, "deferred": False}


def preferred_weapon(ad) -> dict | None:
    st = ORIG.get(id(ad)) or {}
    return dict(st["preferred_weapon"]) if st.get("preferred_weapon") else None


def _confirm_weapon(st, snap) -> None:
    """A pending gun request: confirmed when its gun is in hand, rejected when it expires."""
    req = st.get("weapon_request")
    if not req or req.get("state") != "pending":
        return
    held = next((s for s in (snap or {}).get("inventory") or () if s.get("hand")), None)
    if held is not None and held.get("item") == req["item"]:
        req["state"] = "confirmed"
    elif time.monotonic() >= req["expires"]:
        req.update(state="rejected", reason="No equipment confirmation before the request expired.")


# --- bullet_damage and turn_speed (the PS3 tool's, on this edition's tables; live 2026-10-27 10:43) ---------------------
# sParameter::WEAPON_LEVEL_STRUCT (UPG_TABLE, 0x210 a weapon): 8 groups 0x40 apart from +0x10, each two header words
# then 14 levels; group 0 firepower (the M92F's 150 / 170 / 190 / 210 / 230 / 250 at +0x18, the PS3's 150 at level 0),
# group 1 firing speed (+0x58, the M92F's 26 frames). sParameter (its pointer at main+0x1CF1C30): +0x34 the walk / run
# turn deg/s (110), +0x70 / +0x74 the stick range (0.2 / 1.2), +0x2D0 / +0x2D4 aim pitch / yaw deg/s (57.9): the PS3's
# fields (its +0x2C / +0x68 / +0x6C / +0x2D0 / +0x2D4).
UPG_GROUP0, UPG_GROUP, UPG_LEVELS, G_DAMAGE = 0x10 + 8, 0x40, 14, 0
M92F_FIREPOWER = 150.0
S_PARAM_PTR = 0x1CF1C30
TURN = {0x34: ("turn_deg_s", 110.0), 0x70: ("stick_min", 0.2), 0x74: ("stick_max", 1.2),
        0x2D0: ("aim_pitch_deg_s", 57.9), 0x2D4: ("aim_yaw_deg_s", 57.9)}
TURN_MAX = 10.0


def _mult(v, default) -> float:
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("max", "maximum", "unlimited"):
            return TURN_MAX
        v = float(s or default)
    return float(v if v is not None else default)


def _firepower_at(g: RE5Switch, wid: int) -> int:
    return g.base + UPG_TABLE + UPG_STRIDE * wid + UPG_GROUP0 + UPG_GROUP * G_DAMAGE


def bullet_damage(g: RE5Switch, mult) -> dict:
    """Every weapon's firepower x N at every upgrade level (the PS3 tool's), from the originals kept on first use."""
    k = _mult(mult, 10.0)
    if not 0.1 <= k <= 1000:
        raise ValueError("bullet_damage multiplier: 0.1 .. 1000 (1 = the game's)")
    orig = g.state.setdefault("firepower", {})
    if not orig:
        m92 = struct.unpack(f"<{UPG_LEVELS}f", g.rd(_firepower_at(g, 0x02), 4 * UPG_LEVELS))
        if abs(m92[0] - M92F_FIREPOWER) > 0.5:
            raise RuntimeError(f"the upgrade table does not hold this build's firepower (M92F level 0: {m92[0]})")
        for wid in range(N_WEAPONS):
            orig[wid] = g.rd(_firepower_at(g, wid), 4 * UPG_LEVELS)
    ok = True
    for wid, raw in orig.items():
        vals = struct.unpack(f"<{UPG_LEVELS}f", raw)
        want = struct.pack(f"<{UPG_LEVELS}f", *[v * k for v in vals])
        at = _firepower_at(g, wid)
        if g.rd(at, len(want)) != want:
            ok = g.wr(at, want) and ok
        ok = ok and g.rd(at, len(want)) == want
    g.state["bullet_damage"] = k
    m92 = struct.unpack("<f", g.rd(_firepower_at(g, 0x02), 4))[0]
    return {"bullet_damage_x": k, "verified": bool(ok), "m92f_firepower_level0": round(m92, 1),
            "note": "every weapon's firepower x N at every upgrade level; 1 restores the game's values"}


def _param(g: RE5Switch) -> int:
    p = struct.unpack("<Q", g.rd(g.base + S_PARAM_PTR, 8))[0]
    if not R.ptr_ok(p):
        raise RuntimeError("sParameter is not up yet (the game is still booting)")
    return p


def turn_speed(g: RE5Switch, mult) -> dict:
    """The stick turns the player N times faster, aimed and not (the PS3 tool's: sParameter's turn and aim rates)."""
    k = _mult(mult, 2.0)
    if not 0.25 <= k <= 50:
        raise ValueError("turn_speed multiplier: 0.25 .. 50 (1 = the game's; 2 = default; max = 10)")
    p = _param(g)
    live = {o: struct.unpack("<f", g.rd(p + o, 4))[0] for o in TURN}
    bad = {TURN[o][0]: v for o, v in live.items() if not 0.2 <= v / TURN[o][1] <= 60}
    if bad:
        raise RuntimeError(f"sParameter does not hold this build's turn rates ({bad}); not writing")
    out, ok = {}, True
    for o, (name, base) in TURN.items():
        want = struct.pack("<f", base * k)
        ok = g.wr(p + o, want) and ok
        got = struct.unpack("<f", g.rd(p + o, 4))[0]
        ok = ok and abs(got - base * k) < 1e-3
        out[name] = round(got, 4)
    g.state["turn_speed"] = k
    return {"turn_speed_x": k, "values": out, "verified": bool(ok), "sParameter": hex(p),
            "note": "the stick turns the player this many times faster, aiming (yaw and pitch) and not"}


def turn_speed_x(g: RE5Switch):
    try:
        return round(struct.unpack("<f", g.rd(_param(g) + 0x2D4, 4))[0] / TURN[0x2D4][1], 2)
    except (RuntimeError, ValueError, OSError, struct.error):
        return None


def bullet_damage_x(g: RE5Switch):
    try:
        return round(struct.unpack("<f", g.rd(_firepower_at(g, 0x02), 4))[0] / M92F_FIREPOWER, 2)
    except (ValueError, OSError, struct.error):
        return None


# --- the Mercenaries clock: add_time / set_time / kill_time / time_bonus_multiplier (the PS3 tool's) ---------------------
# Found in main's code 2026-10-27 (the RE6 lesson: the HUD clock is a copy): aGame's update (vtable main+0x1A9B9B8 slot 8,
# 0xD9080 -> 0xEADD0) counts the authoritative clock down at aGame +0x7C0 (its end flag +0x7B8) and copies it into
# cGameSys +0x948 every frame (unless cGameSys +0x82C); a write to the copy alone is overwritten. The hourglass pickup
# (uOmHourGlass 0x6C5824) reaches aGame through the sArea pointer (main+0x26A1460) +0x7040, adds the hourglass unit's
# own s16 at +0x1EB8 (30 / 60 / 90 s) to +0x7C0, and shows "+NN Sec." through cGameSys +0x950 (seconds) / +0x954 (on).
# The melee finisher's +5 is an FP immediate in the code (0xF89BC): not data, not scaled here.
S_AREA_PTR, AREA_GAME, GAME_CLOCK, GAME_CLOCK_END = 0x26A1460, 0x7040, 0x7C0, 0x7B8
GS_LAST_BONUS, GS_SHOW_BONUS = 0x950, 0x954
# The standing hourglasses are uOm0100 (DTI main+0x1D639F0, a child of uOmHourGlass's main+0x1D639B8, both 0x2570
# bytes): their vtable is main+0x1BD6D58 (its getDTI returns uOm0100; the newInstance at 0x6C6220 constructs it and
# sets +0x1EB8 to 60). main+0x1BD71D8 is uOmHourGlass's own (the parent; its destructor is shared), never placed, so a
# scan for it alone found no hourglass in a round (10-27 13:14). Both are accepted.
# Live 14:24: a round's eight stood at 60 s and 90 s (s16 +0x1EB8, the same at +0x1EBA).
HOURGLASS_VT, HOURGLASS_PARENT_VT, HG_SECONDS, HOURGLASS_VALUES = 0x1BD6D58, 0x1BD71D8, 0x1EB8, (30, 60, 90)
MIN_CLOCK_S = 1.0                 # no write leaves the countdown at or under this: 0 is the round's end
ADD_TIME_RANGE, SET_TIME_RANGE = (-3600, 3600), (1, 3600)
KILL_TIME_S, KILL_TIME_MAX_S = 5.0, 30.0   # operator 2026-10-27 21:5x: "five seconds added to the timer" per kill


def _u64(g: RE5Switch, a: int) -> int:
    return struct.unpack("<Q", g.rd(a, 8))[0]


def _clock_owner(g: RE5Switch) -> tuple:
    """(cGameSys, aGame, HUD seconds, authoritative seconds) of a running round, each link checked."""
    main = _u64(g, g.base + R.S_MAIN)
    gs = _u64(g, main + R.MAIN_GAMESYS) if R.ptr_ok(main) else 0
    if not R.ptr_ok(gs) or struct.unpack("<i", g.rd(gs + R.GS_PHASE, 4))[0] != R.PHASE_PLAYING:
        raise RuntimeError("no Mercenaries round is running (cGameSys or its phase)")
    area = _u64(g, g.base + S_AREA_PTR)
    owner = _u64(g, area + AREA_GAME) if R.ptr_ok(area) else 0
    if not R.ptr_ok(owner) or struct.unpack("<I", g.rd(owner + GAME_CLOCK_END, 4))[0] != 0:
        raise RuntimeError("the round's clock owner (sArea -> aGame) is not running")
    hud = struct.unpack("<f", g.rd(gs + R.GS_TIMER, 4))[0]
    master = struct.unpack("<f", g.rd(owner + GAME_CLOCK, 4))[0]
    if not all(math.isfinite(v) and 0 < v < 86400 for v in (hud, master)) or abs(hud - master) > 2:
        raise RuntimeError(f"the authoritative countdown ({master}) disagrees with the HUD ({hud}), or the round is over")
    return gs, owner, hud, master


def _add_clock(g: RE5Switch, seconds: float = 0.0, absolute=None) -> dict:
    """The authoritative countdown += seconds (or = absolute), never under MIN_CLOCK_S, read back; a rise also shows
    the game's own "+NN Sec." (cGameSys +0x950 / +0x954), a cut shows nothing."""
    gs, owner, hud, before = _clock_owner(g)
    wanted = float(absolute) if absolute is not None else before + float(seconds)
    target = max(MIN_CLOCK_S, wanted)
    delta = target - before
    g.wr(owner + GAME_CLOCK, struct.pack("<f", target))
    after = struct.unpack("<f", g.rd(owner + GAME_CLOCK, 4))[0]
    ok = math.isfinite(after) and target - 0.5 <= after <= target + 0.01
    if ok and delta >= 1:
        g.wr(gs + GS_LAST_BONUS, struct.pack("<i", int(round(delta))))
        g.wr(gs + GS_SHOW_BONUS, b"\x01")
    return {"verified": bool(ok), "clock_before": round(hud, 2), "clock_after": round(after, 2),
            "clock_owner": hex(owner), "applied_seconds": round(delta, 2), "clamped": target != wanted,
            **({} if ok else {"reason": "authoritative countdown write not confirmed"})}


def _seconds(value, what: str) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError(f"{what} seconds: a number") from None


def add_time(g: RE5Switch, seconds=60.0) -> dict:
    n = _seconds(60 if seconds is None else seconds, "add_time")
    if n == 0 or not ADD_TIME_RANGE[0] <= n <= ADD_TIME_RANGE[1]:
        raise ValueError("add_time seconds: -3600 .. 3600, not 0 (negative takes time away)")
    res = _add_clock(g, n)
    return {**res, "requested_seconds": n, "added_seconds": int(round(res["applied_seconds"])) if res["verified"] else 0,
            "note": "the HUD shows +NN Sec. like an hourglass" if n > 0 else
            "time taken from the authoritative countdown; the HUD follows next frame, no bonus notice"
            + (f"; stopped at {MIN_CLOCK_S:g} s" if res.get("clamped") else "")}


def set_time(g: RE5Switch, seconds) -> dict:
    n = _seconds(seconds, "set_time")
    if not SET_TIME_RANGE[0] <= n <= SET_TIME_RANGE[1]:
        raise ValueError("set_time seconds: 1 .. 3600")
    return {**_add_clock(g, absolute=n), "set_seconds": n,
            "note": "the authoritative countdown set; the HUD follows next frame"}


def kill_time(g: RE5Switch, on: bool, seconds=None) -> dict:
    """Seconds added to the authoritative clock for each kill (maintain: cGameSys kills, every snapshot)."""
    kt = g.state.setdefault("kill_time", {"seconds": KILL_TIME_S})
    if seconds is not None:
        s = float(seconds)
        if not 0.1 <= s <= KILL_TIME_MAX_S:
            raise ValueError("kill_time seconds: 0.1 .. 30")
        kt["seconds"] = s
    kt["on"] = bool(on)
    kt.pop("kills", None)
    return {"kill_time": bool(on), "seconds": kt["seconds"], "seconds_max": kt["seconds"], "verified": True,
            "note": "each kill adds this many seconds to the authoritative Mercenaries clock (every driver snapshot)"}


def _maintain_kill_time(g: RE5Switch, kt: dict, snap) -> int:
    kills = (snap or {}).get("kills")
    if not isinstance(kills, int) or not (snap or {}).get("player"):
        return 0
    last = kt.get("kills")
    kt["kills"] = kills
    if last is None or kills <= last:
        return 0                                         # the first look, or a new round (its kills start again)
    try:
        res = _add_clock(g, (kills - last) * kt["seconds"])
    except RuntimeError:
        return 0
    kt["added"] = kt.get("added", 0) + (1 if res["verified"] else 0)
    return 1 if res["verified"] else 0


def hourglasses(g: RE5Switch) -> list:
    """The round's standing hourglasses (uOm0100 units, or uOmHourGlass's own, by vtable) on sUnit's move lines."""
    out = []
    su = _u64(g, g.base + R.S_UNIT)
    if not R.ptr_ok(su):
        return out
    vts = (g.base + HOURGLASS_VT, g.base + HOURGLASS_PARENT_VT)
    for line in range(R.N_LINES):
        u, n = _u64(g, su + R.UNIT_LINES + R.LINE_STRIDE * line), 0
        while R.ptr_ok(u) and n < 1024:
            if _u64(g, u) in vts:
                out.append(u)
            u, n = _u64(g, u + R.UNIT_NEXT), n + 1
    return out


def time_bonus_multiplier(g: RE5Switch, mult) -> dict:
    """Every standing hourglass's own seconds (+0x1EB8: 30 / 60 / 90) x N, once a unit (the PS3 tool's; rerun each round)."""
    k = float(mult if mult is not None else 1)
    if not 1 <= k <= 20:
        raise ValueError("time_bonus_multiplier: 1 .. 20")
    written = g.state.setdefault("hourglass_scaled", {})
    done, seen, wanted = [], 0, 0
    for u in hourglasses(g):
        v = struct.unpack("<h", g.rd(u + HG_SECONDS, 2))[0]
        seen += 1
        if written.get(u) == v:
            continue
        if v in HOURGLASS_VALUES:
            wanted += 1
            want = min(32000, int(v * k))
            if g.wr(u + HG_SECONDS, struct.pack("<h", want)) and struct.unpack("<h", g.rd(u + HG_SECONDS, 2))[0] == want:
                written[u] = want
                done.append((v, want))
    return {"time_bonus_x": k, "hourglasses": seen, "scaled": len(done), "hourglass_seconds": sorted({w for _, w in done}),
            "melee_bonus_x": None, "verified": len(done) == wanted,
            "note": "hourglasses are scaled where they stand (a round's own; rerun each round); the melee +5 s is a code "
                    "constant on Switch and stays"}


# --- rotten eggs only (the PS3 tool's rotten_egg_only) ---------------------------------------------------------------------
# Live 2026-10-27 10:42: definition 0x36 is WP36 EGG_X here too; 0x136 in a loadout template gives the round the egg (x5
# at its grid); a ZL tap only raises it (motions 22 / 24): it throws with ZL + ZR, as a gun fires.
EGG_ID, EGG_ITEM = 0x136, 0x36
EGG_RATE_DEFAULT, EGG_RATE_MAX = 20.0, 20.0


def rotten_egg_only(g: RE5Switch, on: bool, rate=None) -> dict:
    """Every character's guns become the rotten egg (the template, from the next round), its no-ammo flag set (the
    stock never runs out), and its throw sped up by fire_rate's time scale (rate: 1..20). Off: the guns and the flag
    back. Uses weapon_override's composition, so the bombs and the other template ops still compose."""
    st = g.state.setdefault("eggs", {"rate": EGG_RATE_DEFAULT})
    value = st["rate"] if rate is None else float(rate)
    if not math.isfinite(value) or not 1 <= value <= EGG_RATE_MAX:
        raise ValueError("egg rate must be 1..20")
    name = g.name(EGG_ITEM)
    if not name.startswith("WP36 EGG_X"):
        raise ValueError(f"definition 0x36 is not the rotten egg on this build ({name!r})")
    at = g.record(EGG_ITEM) + DEF_NOAMMO
    st.setdefault("original_noammo", g.u32(at))
    st.update(on=bool(on), rate=value)
    if on:
        ok = g.wr(at, struct.pack("<I", 1)) and g.u32(at) == 1
        st["previous_override"] = g.state.get("weapon_override")
        res = weapon_override(g, EGG_ITEM, True)
        fire_rate(g, value)
        st["status"] = "requested; the eggs come with the next round"
        return {"verified": bool(ok and res["verified"]), "rotten_egg_only": True, "egg_rate_x": value,
                "native_equipped": False, "effective_next_round": True, "records": res["records"]}
    ok = g.wr(at, struct.pack("<I", st["original_noammo"])) and g.u32(at) == st["original_noammo"]
    prev = st.pop("previous_override", None)
    res = weapon_override(g, prev["item"] if prev else None, prev["only"] if prev else False)
    st["status"] = "disabled; the guns come back with the next round"
    return {"verified": bool(ok and res["verified"]), "rotten_egg_only": False, "egg_rate_x": value,
            "native_equipped": False, "effective_next_round": True}


def mine_settings(ad) -> dict | None:
    """The session's mine settings for the Switch bot (None: never set: the bot's defaults)."""
    st = ORIG.get(id(ad)) or {}
    return dict(st["mine_settings"]) if st.get("mine_settings") else None


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
            _confirm_weapon(st, snap)
            dr = st.get("loadout")
            if enabled and dr and dr.get("each_round") and p and p.get("ptr"):
                if dr.get("player") is None:
                    dr["player"] = p["ptr"]
                elif dr["player"] != p["ptr"]:               # a new round's player: the next round's guns drawn now
                    import random
                    dr["player"], dr["seed"] = p["ptr"], random.random()
                    drawn = compose_templates(RE5Switch(ad))
                    out["loadout_redrawn"] = bool(drawn.get("verified"))
                    out["writes"] += drawn.get("blocks_written", 0)
            kt = st.get("kill_time")
            if enabled and kt and kt.get("on"):
                out["writes"] += _maintain_kill_time(RE5Switch(ad), kt, snap)
            hs = st.get("health")
            if enabled and hs and hs.get("on"):
                hs["last"] = res = _maintain_health(ad, hs, snap)
                out["writes"] += 1 if res.get("refilled") else 0
        except Exception as e:                               # noqa: BLE001 - a missed update never stops a tick
            out.update(verified=False, reason=f"{type(e).__name__}: {e}"[:160])
        return out


def revert_all(g: RE5Switch) -> dict:
    """Every op off: the no-ammo flags and the fire rate back, the spray and health upkeep off (the original maximum
    back), the bombs and every template op gone (the original loadouts written back)."""
    out = {"infinite_ammo": infinite_ammo(g, False)["verified"], "fire_rate": fire_rate(g, 1.0)["verified"],
           **({"bullet_damage": bullet_damage(g, 1.0)["verified"]} if g.state.get("firepower") else {}),
           **({"turn_speed": turn_speed(g, 1.0)["verified"]} if g.state.get("turn_speed") else {}),
           "infinite_spray": infinite_spray(g, False)["verified"],
           "unlimited_health": unlimited_health(g, False)["verified"]}
    g.state.pop("mine_settings", None)
    if (g.state.get("eggs") or {}).get("on"):
        out["rotten_eggs"] = rotten_egg_only(g, False)["verified"]
    if g.state.get("kill_time"):
        g.state["kill_time"]["on"] = False
    for key in ("weapon_override", "loadout", "replace", "preferred_weapon", "rampage_loadout"):
        g.state.pop(key, None)
    req = g.state.get("weapon_request")
    if req and req.get("state") == "pending":
        req.update(state="rejected", reason="Cancelled by revert all.")
    out["mine_loadout"] = mine_loadout(g, False)["verified"]     # (composes every block from its original)
    return {"reverted": out, "verified": all(out.values()), "note": "a relaunch of the game is the full revert too"}


def random_cheats(g: RE5Switch, seed=None) -> dict:
    """The PS3 tool's per-round randomizer: fire_rate x80, the game's turn speed, bullet damage x10, infinite ammo,
    the loadout re-drawn three rounds in four, the long guns replaced."""
    import random
    rng = random.Random(seed)
    picked = {"fire_rate_x": 80.0, "turn_speed_x": 1.0, "bullet_damage_x": 10.0, "infinite_ammo": True,
              "loadout": rng.random() < 0.75}
    out = {"fire_rate": fire_rate(g, 80.0)["verified"], "infinite_ammo": infinite_ammo(g, True)["verified"],
           "turn_speed": turn_speed(g, 1.0)["verified"], "bullet_damage": bullet_damage(g, 10.0)["verified"]}
    if picked["loadout"] or g.state.get("weapon_override"):
        out["loadout"] = loadout(g, seed=rng.random())["verified"]
        if g.state.get("weapon_override"):
            picked["weapon_override"] = g.state["weapon_override"]
    else:
        out["loadout"] = loadout(g, on=False)["verified"]
    out["weapon_replacement"] = replace_long_guns(g, rng.random())["verified"]
    return {"telemetry": picked, "verified": all(out.values()), "applied": out}


ADDRESSES = {
    "weapon_definitions": {"offset": DEF_TABLE, "source": "main+0x1D08680, 0x140 a weapon (sParameter::"
                           "WEAPON_INFO_STRUCT): +0x8 name, +0x1C needs no ammo; live 2026-10-26", "live_checked": True},
    "weapon_upgrades": {"offset": UPG_TABLE, "source": "main+0x1D13B28, 0x210 a weapon (sParameter::"
                        "WEAPON_LEVEL_STRUCT)", "live_checked": False},
    "loadout_descriptors": {"offset": DESC_TABLE, "source": "68 x (block, 0, 12), static data with its relocations in "
                            "main's ELF; the PS3's template descriptors", "live_checked": True},
    "chris_bsaa_templates": {"offset": CHRIS_TEMPLATES[0], "source": "descriptors 14 and 24 (main+0x1AAD9A8, "
                             "main+0x1AAF208); mine_loadout live 2026-10-27", "live_checked": True},
    "player_time_scale": {"offset": P_TIME_SCALE, "source": "player +0x1A08 f32 (fire_rate)", "live_checked": True},
    "player_health": {"offset": R.P_HP, "source": "player +0x1EB8 s16 health, +0x1EBA maximum", "live_checked": True},
    "player_inventory": {"offset": R.P_INV, "source": "player +0x30F0, 9 slots of 0x38", "live_checked": True},
    "ground_bombs": {"offset": R.MINE_LINE, "source": "sUnit move line 11, class uWp0a, position +0x60",
                     "live_checked": True},
}

# What the PS3 tool has and this edition does not yet, and why (the panel shows these on its buttons).
NOT_YET = {
    "instant_qte": "the QTE progress fields are not mapped on Switch yet",
    "live_weapon": "the native pickup that builds a weapon mid-round (the PS3's 1AEE90 path) is not found on Switch yet",
    "aimbot": "no verified live control for this hook",
    "auto_parry": "no verified live control for this hook",
    "knife_knockback": "no verified live control for this hook",
}
AVAILABLE = {
    "fire_rate": "the player's time scale while his shot motion plays; read back every snapshot",
    "infinite_ammo": "the Gatling's no-ammo flag on every gun and grenade, read back every 2 s",
    "infinite_spray": "the round's First Aid Spray kept from emptying",
    "unlimited_health": "living health refilled to a boosted maximum every snapshot (no hit immunity yet)",
    "mines": "the bomb loadout and the Switch bot's cadence; the loadout takes effect next round",
    "weapon_override": "Loadout template; takes effect next round.",
    "loadout": "Loadout template; takes effect next round.",
    "replace_rockets": "Loadout template; takes effect next round.",
    "replace_long_guns": "Loadout template; takes effect next round.",
    "random_cheats": "fire rate, turn speed, damage, infinite ammo, the loadout and the long guns",
    "mercs_select": "Choose the next Mercenaries round (No Mercy's original roster; Reunion not yet on Switch).",
    "select_weapon": "Equips a loaded quick-slot gun or longbow; excludes rockets and sniper rifles.",
    "turn_speed": "sParameter's turn and aim rates (main+0x1CF1C30), read back",
    "add_time": "Authoritative aGame countdown write, read back; a running round.",
    "set_time": "Authoritative aGame countdown write, read back; a running round.",
    "kill_time": "Seconds added to the authoritative clock per kill, every snapshot.",
    "time_bonus_multiplier": "The round's standing hourglasses' seconds x N; rerun each round.",
    "rotten_egg_only": "Every gun the rotten egg (infinite) from the next round; the throw sped up by the fire rate.",
    "bullet_damage": "every weapon's firepower group (the upgrade table), read back",
    "random_weapon": "Equips a loaded quick-slot gun or longbow; excludes rockets and sniper rifles.",
}


def capabilities() -> dict:
    caps = {op: {"available": True, "reason": why} for op, why in AVAILABLE.items()}
    caps.update({op: {"available": False, "reason": f"not yet on Switch: {why}"} for op, why in NOT_YET.items()})
    return caps


def full_status(g: RE5Switch) -> dict:
    """The PS3 tool's status fields this edition has (the panel reads them), plus the capabilities."""
    from . import re5_weapons
    st = g.status()
    hs = g.state.get("health") or {}
    st.update(turn_speed_x=turn_speed_x(g), bullet_damage_x=bullet_damage_x(g), unlimited_health=bool(hs.get("on")),
              health_maintenance=hs.get("last"), hit_immunity=False,
              infinite_spray=bool(g.state.get("infinite_spray")), mine_loadout=bool(g.state.get("mine_loadout")),
              mine_settings=g.state.get("mine_settings") or {"enabled": bool(g.state.get("mine_loadout")),
                                                            "interval_s": MINE_EVERY_DEFAULT, "only": False},
              weapon_override=g.state.get("weapon_override"),
              loadout=bool(g.state.get("loadout")),
              weapon_replacements=sorted(f"{w:#x}" for w in (g.state.get("replace") or {}).get("unwanted", ())),
              kill_time_on=bool((g.state.get("kill_time") or {}).get("on")),
              kill_time_s=(g.state.get("kill_time") or {}).get("seconds", KILL_TIME_S)
              if (g.state.get("kill_time") or {}).get("on") else 0.0,
              kill_time_range=f"{(g.state.get('kill_time') or {}).get('seconds', KILL_TIME_S):g}",
              rotten_egg_only=bool((g.state.get("eggs") or {}).get("on")),
              egg_rate_x=(g.state.get("eggs") or {}).get("rate", EGG_RATE_DEFAULT),
              egg_status=(g.state.get("eggs") or {}).get("status", "disabled"),
              egg_native_equipped=False,
              all_weapons=[{"item": k, "weapon": w.name, "family": w.family}
                           for k, w in sorted(re5_weapons.WEAPONS.items())],
              capabilities=capabilities(), edition="switch",
              mercs_selection={"stage": R.STAGE_NAMES[R.stage_target()], "character": R.CHARACTERS[R.player_target()]}
              if 0 <= R.stage_target() < 8 and 0 <= R.player_target() < 10 else None,
              mercs_catalog={"rosters": {"mercenaries": list(R.CHARACTERS)}, "stages": list(R.STAGE_NAMES)})
    nxt = {"mode": "mercenaries", "character": R.CHARACTERS[R.player_target() % len(R.CHARACTERS)],
           "stage": R.stage_target() % len(R.STAGE_NAMES)}
    st["mercs_rotation"] = {"next": nxt, "combinations_played": 0, "combinations_total": len(R.CHARACTERS) * 8,
                            "selection_request": {"selection": nxt, "state": "queued"} if R.SELECTION else None}
    snap = R.snapshot(g.m)
    st["merc_seconds_left"] = snap.get("timer")
    inv = snap.get("inventory") or []
    st["inventory"] = [{"slot": s["slot"], "id": f"0x{s['id']:X}", "rounds": s["rounds"], "capacity": s["cap"],
                        "in_hand": s["hand"],
                        "weapon": re5_weapons.WEAPONS[s["item"]].name if s["type"] == 1 and s["item"] in
                        re5_weapons.WEAPONS else None} for s in inv]
    st["in_hand"] = next((x for x in st["inventory"] if x["in_hand"]), None)
    guns = eligible_guns(inv)
    st["available_weapons"] = guns
    pw = g.state.get("preferred_weapon")
    st["preferred_weapon"] = {**pw, "persistent": True, "available": any(w["item"] == pw["item"] for w in guns),
                              "equipped": any(w["item"] == pw["item"] and w["equipped"] for w in guns)} if pw else None
    req = g.state.get("weapon_request")
    st["random_weapon_request"] = {k: v for k, v in req.items() if k != "expires"} if req else None
    caps = st["capabilities"]
    if not guns:
        for op in ("select_weapon", "random_weapon"):
            caps[op] = {"available": False, "reason": "No supported loaded gun or longbow in a quick slot (no round up?)."}
    return st


ALIASES = {"fire": "fire_rate", "rapid_fire": "fire_rate", "machine_gun": "fire_rate", "ammo": "infinite_ammo",
           "unlimited_ammo": "infinite_ammo", "no_ammo": "infinite_ammo", "auto_first_aid": "infinite_spray",
           "first_aid": "infinite_spray", "first_aid_spray": "infinite_spray", "infinite_first_aid": "infinite_spray",
           "revert": "revert_all", "reset": "revert_all", "off": "revert_all", "address_table": "addresses",
           "weapons": "loadout", "merc_loadout": "loadout", "random_weapons": "loadout", "randomize": "random_cheats",
           "randomizer": "random_cheats", "random": "random_cheats", "unlimited_life": "unlimited_health",
           "infinite_health": "unlimited_health", "infinite_life": "unlimited_health", "turn": "turn_speed",
           "aim_turn_speed": "turn_speed", "rotation": "turn_speed", "turnaround": "turn_speed",
           "damage": "bullet_damage", "firepower": "bullet_damage", "powerful_bullets": "bullet_damage",
           "time_per_kill": "kill_time", "kill_bonus": "kill_time", "add_minute": "add_time", "merc_time": "add_time",
           "more_time": "add_time", "subtract_time": "add_time", "cut_time": "add_time", "set_clock": "set_time",
           "merc_time_set": "set_time", "clock": "set_time", "time_bonus": "time_bonus_multiplier",
           "merc_time_bonus": "time_bonus_multiplier", "auto_qte": "instant_qte", "qte_assist": "instant_qte",
           "mine_loadout": "mine_loadout", "proximity_bombs": "mine_loadout"}


def tool_run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE5Switch | None = None, **extra) -> dict:
    """The PS3 tool's ops on a Switch session (gbox.re5_mods_tool routes them here): the same names, parameters and
    result shape, {"op", ..., "status"}; an op not on Switch yet answers verified False with the reason."""
    with _LOCK:
        g = g or RE5Switch(ad)
        op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
        op = ALIASES.get(op, op)
        res: dict = {"op": op, "edition": "switch"}
        if op == "status":
            pass
        elif op == "addresses":
            res.update(game=GAME, addresses={k: {**v, "address": f"main+0x{v['offset']:X}"} for k, v in ADDRESSES.items()},
                       weapons={f"0x{k:02X}": w.name for k, w in sorted(_weapons().items())})
            return res
        elif op in NOT_YET:
            res.update(verified=False, supported=False, reason=f"not yet on Switch: {NOT_YET[op]}")
        elif op in ("fire_rate", "infinite_ammo", "infinite_spray", "mine_loadout"):
            res.update(run(ad, op, multiplier, on, g=g))
        elif op == "unlimited_health":
            res.update(unlimited_health(g, bool(on)))
        elif op == "rampage_loadout":
            res.update(rampage_loadout(g, bool(on)))
        elif op == "add_time":
            secs = extra.get("seconds")
            res.update(add_time(g, (multiplier if multiplier is not None else 60) if secs is None else secs))
        elif op == "set_time":
            secs = extra.get("seconds")
            res.update(set_time(g, multiplier if secs is None else secs))
        elif op == "kill_time":
            res.update(kill_time(g, bool(on), extra.get("seconds") if extra.get("seconds") is not None else multiplier))
        elif op == "time_bonus_multiplier":
            res.update(time_bonus_multiplier(g, multiplier if multiplier is not None else extra.get("x", 1)))
        elif op == "turn_speed":
            res.update(turn_speed(g, multiplier if on else 1.0))
        elif op == "bullet_damage":
            res.update(bullet_damage(g, (multiplier if multiplier is not None else 10.0) if on else 1.0))
        elif op == "mines":
            res.update(mines(g, multiplier, bool(on)))
        elif op == "weapon_override":
            res.update(weapon_override(g, extra.get("weapon") if on else None, bool(extra.get("only"))))
        elif op == "loadout":
            res.update(loadout(g, extra.get("weapons"), extra.get("seed"), bool(on), bool(extra.get("each_round")),
                               bool(extra.get("only"))))
        elif op == "replace_rockets":
            res.update(replace_rockets(g, extra.get("seed")))
        elif op == "replace_long_guns":
            res.update(replace_long_guns(g, extra.get("seed")))
        elif op == "random_cheats":
            res.update(random_cheats(g, extra.get("seed")))
        elif op in ("select_weapon", "random_weapon"):
            res.update(select_weapon(g, extra.get("weapon"), bool(on), random_pick=op == "random_weapon"))
        elif op == "rotten_egg_only":
            res.update(rotten_egg_only(g, bool(on), multiplier))
        elif op == "mercs_select":
            res.update(mercs_select(g, extra.get("mode"), extra.get("character"), extra.get("stage")))
        elif op == "revert_all":
            res.update(revert_all(g))
        else:
            raise ValueError(f"re5_mods on Switch: unknown op {op!r} ({', '.join(sorted({*AVAILABLE, *NOT_YET, 'status', 'addresses', 'revert_all'}))})")
        res["status"] = full_status(g)
        return res


def _weapons() -> dict:
    from . import re5_weapons
    return re5_weapons.WEAPONS


SAVED_OPS = frozenset({"fire_rate", "infinite_ammo", "infinite_spray", "unlimited_health", "mines", "weapon_override"})


def apply_saved(ad, ops) -> dict:
    """The game's saved menu settings (gbox.game_prefs) on a new Switch session, each with its own read-back; an op
    not on Switch yet reports its reason; one failed item never stops the others (the PS3 tool's apply_saved)."""
    results: dict = {}
    try:
        g = RE5Switch(ad)
    except Exception as e:                                   # noqa: BLE001 - no game yet: every item says why
        return {"op": "apply_saved", "results": {}, "verified": False, "reason": f"{type(e).__name__}: {e}"[:200]}
    for item in list(ops or [])[:16]:
        item = item if isinstance(item, dict) else {}
        op = str(item.get("op") or "")
        name = str(item.get("name") or op)[:40]
        try:
            if op in NOT_YET:
                results[name] = {"op": op, "verified": False, "reason": f"not yet on Switch: {NOT_YET[op]}"}
                continue
            res = tool_run(ad, op, item.get("multiplier"), bool(item.get("on", True)), g=g, weapon=item.get("weapon"),
                           only=bool(item.get("only")))
            ok = res.get("verified") is True
            results[name] = {"op": op, "verified": ok,
                             **({} if ok else {"reason": str(res.get("reason") or res.get("note") or "not verified")[:200]})}
        except Exception as e:                               # noqa: BLE001 - this item's reason; the rest still go in
            results[name] = {"op": op, "verified": False, "reason": f"{type(e).__name__}: {e}"[:200]}
    return {"op": "apply_saved", "results": results, "status": full_status(g),
            "verified": bool(results) and all(r["verified"] for r in results.values())}


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE5Switch | None = None, **extra) -> dict:
    """The playbook's ops (gbox/mercs_bot.py apply_ops: the profile's playing_ops at a round's start): the original
    four answer their own dicts; every other op goes through tool_run (the PS3 tool's names and result shape)."""
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
        if op in ("mine_loadout", "proximity_bombs"):
            return mine_loadout(g, bool(on))
        if op == "revert_all":
            return revert_all(g)
        return tool_run(ad, op, multiplier, on, g=g, **extra)
