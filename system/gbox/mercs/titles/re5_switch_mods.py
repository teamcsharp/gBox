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
DESC_TABLE, DESC_STRIDE, DESC_N = 0x1AB6F48, 0x18, 68        # the loadout descriptors (block pointer, 0, 12)
MERC_DESC = tuple(range(14, DESC_N))                         # every loadout but the campaign's (0-13)
MAIN_SPAN = 0x2800000                                        # main's mapping (a block pointer is inside it)
REC_ID, REC_COUNT, REC_GRID, REC_HAND, REC_UPG = 0x0, 0x4, 0x14, 0x18, 0x1C
KNIFE_IDS = frozenset({0x100, 0x101, 0x10E, 0x114, 0x123, 0x124})   # the knives and WP00 (never a gun to replace)
POWERFUL = (0x11B, 0x11A, 0x119, 0x115, 0x10D, 0x11C, 0x11D, 0x116, 0x10C, 0x120, 0x10B)   # the PS3 tool's draw
MAGNUMS = (0x10B, 0x11A, 0x11B)
ROCKETS, LONG_GUNS = frozenset({0x10D}), frozenset({0x10D, 0x105, 0x11C, 0x120})   # rocket launcher; and the snipers
HEALTH_MAX = 30000                                           # unlimited_health's boosted maximum (the PS3's)
MINE_EVERY_DEFAULT = 9.0                                     # the Switch bot's cadence unless `mines` sets one
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
        for k in range(TEMPLATE_RECS):
            o = k * TEMPLATE_REC
            idw, = struct.unpack_from("<I", t, o + REC_ID)
            hand, = struct.unpack_from("<I", t, o + REC_HAND)
            new = None
            if override and _is_gun(idw) and (idw & 0xFF) not in THROWN_ITEMS and (override["only"] or hand == 1):
                new = 0x100 | override["item"]
            elif not override and draw and _is_gun(idw) and (idw & 0xFF) not in THROWN_ITEMS:
                pool = [w for w in draw["pool"] if w not in used] or draw["pool"]
                new = rng.choice(pool)
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


def loadout(g: RE5Switch, weapons=None, seed=None, on: bool = True) -> dict:
    """Every gun in every Mercenaries loadout drawn from the powerful campaign weapons (weapons: a pool of them),
    without repeats inside a block, the long guns as magnums (the PS3 tool's); on=False: the game's guns back. An
    active weapon_override wins over the draw."""
    import random
    if not on:
        g.state.pop("loadout", None)
        return {"loadout": "the game's", **compose_templates(g)}
    pool = [(int(w, 0) if isinstance(w, str) else int(w)) | 0x100 for w in (weapons or [])]
    pool = [w for w in pool if w in POWERFUL] or list(POWERFUL)
    g.state["loadout"] = {"seed": seed if seed is not None else random.random(), "pool": pool}
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
           "infinite_spray": infinite_spray(g, False)["verified"],
           "unlimited_health": unlimited_health(g, False)["verified"]}
    g.state.pop("mine_settings", None)
    for key in ("weapon_override", "loadout", "replace"):
        g.state.pop(key, None)
    out["mine_loadout"] = mine_loadout(g, False)["verified"]     # (composes every block from its original)
    return {"reverted": out, "verified": all(out.values()), "note": "a relaunch of the game is the full revert too"}


def random_cheats(g: RE5Switch, seed=None) -> dict:
    """The PS3 tool's per-round randomizer with what this edition has: fire_rate x80, infinite ammo, the loadout
    re-drawn three rounds in four, the long guns replaced (turn speed and bullet damage: not on Switch yet)."""
    import random
    rng = random.Random(seed)
    picked = {"fire_rate_x": 80.0, "infinite_ammo": True, "loadout": rng.random() < 0.75}
    out = {"fire_rate": fire_rate(g, 80.0)["verified"], "infinite_ammo": infinite_ammo(g, True)["verified"]}
    if picked["loadout"] or g.state.get("weapon_override"):
        out["loadout"] = loadout(g, seed=rng.random())["verified"]
        if g.state.get("weapon_override"):
            picked["weapon_override"] = g.state["weapon_override"]
    else:
        out["loadout"] = loadout(g, on=False)["verified"]
    out["weapon_replacement"] = replace_long_guns(g, rng.random())["verified"]
    return {"telemetry": picked, "verified": all(out.values()), "applied": out,
            "note": "turn_speed and bullet_damage are not on Switch yet"}


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
    "turn_speed": "sParameter's turn and aim rates (the PS3's +0x2C / +0x68 / +0x2D4) are not mapped on Switch yet",
    "bullet_damage": "the firepower group of the upgrade table (sParameter::WEAPON_LEVEL_STRUCT) is not verified on "
                     "Switch yet",
    "kill_time": "the authoritative Mercenaries countdown (the PS3's sArea -> aGame) is not mapped on Switch yet",
    "add_time": "the authoritative Mercenaries countdown (the PS3's sArea -> aGame) is not mapped on Switch yet",
    "set_time": "the authoritative Mercenaries countdown (the PS3's sArea -> aGame) is not mapped on Switch yet",
    "time_bonus_multiplier": "the hourglass's seconds (uOmHourGlass) are not mapped on Switch yet",
    "instant_qte": "the QTE progress fields are not mapped on Switch yet",
    "rotten_egg_only": "the rotten egg loadout and supply are not ported to Switch yet",
    "mercs_select": "the next round's stage, character and mode through the Switch menus are not wired yet",
    "live_weapon": "the native pickup that builds a weapon mid-round (the PS3's 1AEE90 path) is not found on Switch yet",
    "select_weapon": "the Switch bot's weapon choice is not wired yet",
    "random_weapon": "the Switch bot's weapon choice is not wired yet",
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
    "random_cheats": "fire rate, infinite ammo, the loadout and the long guns (no turn speed or damage yet)",
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
    st.update(turn_speed_x=None, bullet_damage_x=None, unlimited_health=bool(hs.get("on")),
              health_maintenance=hs.get("last"), hit_immunity=False,
              infinite_spray=bool(g.state.get("infinite_spray")), mine_loadout=bool(g.state.get("mine_loadout")),
              mine_settings=g.state.get("mine_settings") or {"enabled": bool(g.state.get("mine_loadout")),
                                                            "interval_s": MINE_EVERY_DEFAULT, "only": False},
              weapon_override=g.state.get("weapon_override"),
              loadout=bool(g.state.get("loadout")),
              weapon_replacements=sorted(f"{w:#x}" for w in (g.state.get("replace") or {}).get("unwanted", ())),
              kill_time_on=False, kill_time_s=0.0, rotten_egg_only=False,
              all_weapons=[{"item": k, "weapon": w.name, "family": w.family}
                           for k, w in sorted(re5_weapons.WEAPONS.items())],
              capabilities=capabilities(), edition="switch")
    snap = R.snapshot(g.m)
    st["merc_seconds_left"] = snap.get("timer")
    inv = snap.get("inventory") or []
    st["inventory"] = [{"slot": s["slot"], "id": f"0x{s['id']:X}", "rounds": s["rounds"], "capacity": s["cap"],
                        "in_hand": s["hand"],
                        "weapon": re5_weapons.WEAPONS[s["item"]].name if s["type"] == 1 and s["item"] in
                        re5_weapons.WEAPONS else None} for s in inv]
    st["in_hand"] = next((x for x in st["inventory"] if x["in_hand"]), None)
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
        elif op == "mines":
            res.update(mines(g, multiplier, bool(on)))
        elif op == "weapon_override":
            res.update(weapon_override(g, extra.get("weapon") if on else None, bool(extra.get("only"))))
        elif op == "loadout":
            res.update(loadout(g, extra.get("weapons"), extra.get("seed"), bool(on)))
        elif op == "replace_rockets":
            res.update(replace_rockets(g, extra.get("seed")))
        elif op == "replace_long_guns":
            res.update(replace_long_guns(g, extra.get("seed")))
        elif op == "random_cheats":
            res.update(random_cheats(g, extra.get("seed")))
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
