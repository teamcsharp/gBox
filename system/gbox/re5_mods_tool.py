"""`re5_mods`: Resident Evil 5 Gold Edition (PS3 BLUS30491 app 01.01, RPCS3) live gameplay mods: data writes into the
running game, each read back, the originals kept and restored by the same op with multiplier=1 / on=false.
Register with:  from . import re5_mods_tool  # noqa: F401

ops (session_id = a running RE5 session on the Spark; in the worker the Mercenaries playbook applies the profile's
package through run() at round start, gbox/mercs_bot.py):
  status                          what is on: turn / fire / damage multipliers, the no-ammo flag count, the weapon in hand
  turn_speed multiplier=N         the stick turns the player N times faster, aimed and not (2 = default, "max" = 10)
  fire_rate multiplier=N          scales firing tables and the re-fire timer (80); measured shot rate may differ
  infinite_ammo on=true|false     no weapon spends rounds (the HUD shows the infinity sign; the Gatling's own flag)
  instant_qte on=true|false       native progress assistance for verified button-accumulation / stick-wiggle events;
                                  scoped solo Mercenaries resuscitation; other QTEs keep ordinary input automation
  unlimited_health on=true|false full living HP each snapshot, plus exact-signature-verified Muteki hit immunity
  infinite_spray on=true|false    an infinite First Aid Spray (alias auto_first_aid): every character's loadout template
                                  gets a spray record (the game builds the item at the round start), and when the bot has
                                  used its last recovery item the spray's own game-made record is replayed into its freed
                                  inventory slot, byte for byte (maintain_spray, each bot snapshot); the bot heals with it
  bullet_damage multiplier=N      every weapon's firepower x N at every upgrade level
  addresses                       this release's address table, with the evidence
Everything is RAM only: a relaunch of the game is the full revert.

Where (found 2026-10-21 in the executable dump and live in the Spark's RPCS3; guest addresses):
  sParameter [0x017FEB08]  the global tunables object (heap): +0x2C walk/run turn deg/s (110), +0x68 / +0x6C the
                           stick-to-turn-speed range (0.2 / 1.2, also the stand-still turn animation's speed),
                           +0x2D0 aim pitch deg/s (57.9), +0x2D4 aim yaw deg/s (57.9). Readers: the walk/run turn
                           helper 0xA1A930, the aim controller 0x86E1EC (the measured ~30 deg/s while aiming is 57.9
                           x the zoom factor). Live: aim yaw p90 85 -> 140 -> 231 deg/s at x1 / x2 / x3.
  0x01817530               the weapon definition table (static .data; its ctor 0x19258C runs once at boot): 0x24
                           records of 0x140, index = weapon id (0x02 M92F ... 0x15 Gatling ... 0x20 Dragunov):
                           +0x4 name, +0x14 = 1 "needs no ammo" (the Gatling's; the fire action's can-fire check
                           0x9D4DE4 and the consume check 0x9D3C70 read it), +0x90 the fire interval offset (-10
                           handguns, +5 machine guns, frames), +0x1C class bits.
  0x01823E1C               the weapon upgrade table (static): 0x24 blocks of 0x1E8 = 2 header words + 8 groups of
                           [header, 14 values per level]: group 0 (+0xC) firepower, group 1 (+0x48) firing speed
                           (frames between shots; the fire action 0xA37E64 adds the definition's +0x90), group 2
                           (+0x84) reload speed, group 3 (+0xC0, ints) capacity, group 5 (+0x138) piercing.
  0x0169E098               60.0f: the fire action's only frames-per-second constant (the re-fire timer of semi-auto
                           weapons: timer += dt * 60; its one reader is 0xA37F8C). x80 makes a held R1 repeat.
Live 2026-10-21 (session bd055f..., Barry's handgun): the Gatling's flag on his handgun = the HUD's infinity sign
and 28/30 rounds untouched through 40 s of fire (real frame docs/evidence/re5-mods/); the timer x80 = casing
ejections 1.6/s -> 8.1/s and kills 3 -> 6 per 40 s with the bot's own holds.
"""
from __future__ import annotations

import struct
import threading
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Unsupported, tool

GAME = "Resident Evil 5 Gold Edition (BLUS30491 app 01.01, PPU-a9b0ce57ebd318bd02879751067ceca83b508dd1)"
GAME_IDS = {"e7ca89bbeb67360d"}
S_PARAM_PTR = 0x017FEB08
TURN = {0x2C: ("turn_deg_s", 110.0), 0x68: ("stick_min", 0.2), 0x6C: ("stick_max", 1.2),
        0x2D0: ("aim_pitch_deg_s", 57.9), 0x2D4: ("aim_yaw_deg_s", 57.9)}
TURN_MAX = 10.0
DEF_TABLE, DEF_STRIDE, N_WEAPONS = 0x01817530, 0x140, 0x24
DEF_NAME, DEF_NOAMMO, DEF_CLASS, DEF_INTERVAL_OFS = 0x4, 0x14, 0x1C, 0x90
DEF_SIGNATURE = (0x0157C4D0, 0x013CFBA8)          # record 0: its class pointer and the name "WP00 NONE"
UPG_TABLE, UPG_STRIDE, UPG_SIGNATURE = 0x01823E1C, 0x1E8, 0x0157C598
UPG_GROUP0, UPG_GROUP, UPG_LEVELS = 0x8, 0x3C, 14
G_DAMAGE, G_FIRE, G_RELOAD, G_CAPACITY, G_PIERCE = 0, 1, 2, 3, 5
FIRE_TIMER_FPS, FIRE_TIMER_ORIG = 0x0169E098, 60.0
GATLING = 0x15
KNIVES = {0x01, 0x0E, 0x14, 0x23}
NO_WEAPON = {0x00, 0x18}
WEAPONS = {0x02: "M92F", 0x03: "VZ61", 0x04: "Ithaca M37", 0x05: "S75", 0x06: "hand grenade", 0x07: "incendiary grenade",
           0x08: "flash grenade", 0x09: "SIG 556", 0x0A: "proximity bomb", 0x0B: "S&W M29", 0x0C: "grenade launcher",
           0x0D: "rocket launcher", 0x0F: "longbow", 0x10: "H&K P8", 0x11: "SIG P226", 0x12: "Barry's handgun",
           0x13: "H&K MP5", 0x15: "Gatling gun", 0x16: "Benelli M3", 0x17: "Jail Breaker", 0x19: "Hydra",
           0x1A: "Lightning Hawk", 0x1B: "S&W M500", 0x1C: "H&K PSG-1", 0x1D: "AK-74", 0x1E: "M93R", 0x1F: "Px4",
           0x20: "Dragunov SVD", 0x21: "flamethrower", 0x22: "stun rod", 0x01: "knife", 0x0E: "knife (Sheva)",
           0x14: "knife (Excella)", 0x23: "knife (Wesker)"}
INV_OFS, INV_SLOTS, SLOT = 0x22E0, 24, 0x30     # the player's inventory: slot +0x8 id word 0x01II, +0xC rounds,
S_PLAYER = 0x017FEB34                           # +0x10 capacity, +0x20 = 1 in hand, byte +0x2D in use
P_HP, HEALTH_MAX = 0x14A4, 30000                # verified signed 16-bit current / maximum health pair
P_MUTEKI, P_HIT_STATE, P_HIT_LIST = 0x2F10, 0x2EFC, 0x13D0
MUTEKI_MASK, MUTEKI_ON, HIT_STATE_MASK = 0x30, 0x10, 0x40000
HIT_NODE_ENABLE, HIT_NODE_TYPE, HIT_LIST_LIMIT = 0xBD, 0xC4, 128
# Muteki's registered setter, its player helper, and its incoming-hit collision setter.
# Matched against the running BLUS30491 01.01 process on 2026-10-21. No code is modified.
IMMUNITY_SIGNATURES = {
    0x009BB0B0: bytes.fromhex("388000006000001038a000015400d07e5400303e901f2f10"),
    0x008348F4: bytes.fromhex("f821ff717c0802a6fb810070f80100a0fba10078fbe1008881232f10"
                             "7c681b787c6a1b78552006b47929e7e22f8000003969ffff2f0900007d6b2038409e0078"),
    0x009C38C8: bytes.fromhex("80e300182f8700004d9e00202f84000040de00702f86000040de0128394000004800000c"),
}
_HEALTH_LOCK = threading.RLock()
# The Mercenaries loadout templates (static .data): 30 blocks of 12 records x 0x2C, one block per character / costume
# (Barry = 24, Chris Heavy Metal = 18); a record is [item id 0xTTII, count (-1 = the weapon's own), -1, -1, -1, grid
# position, in hand, packed upgrade levels, flags, 0, 0]; the round start copies them into the inventory and builds
# the weapons, so a changed id here is a weapon the game itself makes.
TEMPLATE, TEMPLATE_BLOCK, TEMPLATE_BLOCKS, TEMPLATE_REC = 0x01730150, 0x210, 30, 0x2C
TEMPLATE_SIGNATURE = (9 * TEMPLATE_REC, 0x123)
# Native FUN_00A48BD4 copies twelve 0x2C records from each pointer/count
# descriptor. The last four physical blocks are reordered to indices4..7;
# the first26 are indices38..63. Never read past the verified64-entry table.
TEMPLATE_DESCRIPTORS = tuple(0x0175496C+8*i for i in range(26)) + tuple(0x0175485C+8*i for i in range(4))
POWERFUL = {0x11B: "S&W M500", 0x11A: "Lightning Hawk", 0x119: "Hydra", 0x115: "Gatling gun", 0x10D: "rocket launcher",
            0x11C: "H&K PSG-1", 0x11D: "AK-74", 0x116: "Benelli M3", 0x10C: "grenade launcher", 0x120: "Dragunov SVD",
            0x10B: "S&W M29"}
MAGNUMS = (0x10B, 0x11A, 0x11B)
REPLACE_WITH_MAGNUM = frozenset({0x10D, 0x105, 0x11C, 0x120})
OPERATOR_SETTINGS = frozenset({"fire_rate", "turn_speed", "bullet_damage", "infinite_ammo", "unlimited_health", "kill_time",
                               "infinite_spray", "instant_qte"})
KNIFE_IDS = {0x101, 0x10E, 0x114, 0x123, 0x124, 0x100}
# infinite_spray: the First Aid Spray is item word 0x304 (type 3 = recovery items; the herbs are 0x305 / 0x307 / 0x309:
# the same set as mercs/titles/re5_inventory_health.HEAL_IDS, which the bot heals with). An inventory slot (0x30 bytes
# at player + INV_OFS) keeps its id word at +0x8, its count at +0xC, its grid position at +0x1C, "in hand" at +0x20 and
# the in-use byte at +0x2D. A free template record's grid: the D-pad quick slots first (the bot equips those with one
# tap: re5_weapons.quick_key), 7 last (the mine / egg loadouts take grid 7).
SPRAY_ID = 0x304
HEAL_IDS = frozenset({0x304, 0x305, 0x307, 0x309})
TEMPLATE_HERBS = frozenset({0x305, 0x307, 0x309})
SLOT_ID, SLOT_COUNT, SLOT_GRID, SLOT_HAND, SLOT_USED = 0x8, 0xC, 0x1C, 0x20, 0x2D
SPRAY_GRIDS = (1, 5, 3, 0, 2, 4, 6, 8, 7)
SPRAY_RESTORE_GAP_S = 2.5                       # two replays of the spray record at least this far apart
# The HUD clock: sBioMain [0x0191CEE4] +0x182D4 -> cGameSys +0x3E0. The authoritative countdown is a DIFFERENT
# object: sArea [0x0191CA20] +0x3830 -> aGame +0x4DC. Native getter 0xBBCA0 and countdown 0x1361C prove this chain;
# 0x1361C rewrites the HUD every frame. Live 2026-10-23: HUD-only writes vanished within 50 ms; owner writes persisted.
# Native add-time 0x18C64(aGame, seconds) updates that owner and the HUD's +0x3E8/+0x3EC. Its callers: the melee
# finisher's `li r4, 5` at 0x000231A4 (the only +5 site:
# a code immediate, so the boot patch gbox/re5_boot_patches.py scales it per session) and the hourglass pickup, which
# passes the hourglass unit's own +0x14A4 s16 (30 or 60 s): data, scaled per round here.
S_MAIN, MAIN_GAMESYS = 0x0191CEE4, 0x182D4
GS_CLOCK, GS_LAST_BONUS, GS_SHOW_BONUS, GS_BONUS_TOTAL = 0x3E0, 0x3E8, 0x3EC, 0x4DC
S_AREA, AREA_GAME, AREA_VT, GAME_VT = 0x0191CA20, 0x3830, 0x0157A720, 0x01576B18
GAME_CLOCK, GAME_CLOCK_STATE = 0x4DC, 0x4D4
MELEE_BONUS_SITE, MELEE_BONUS_ORIG = 0x000231A4, 0x38800005          # li r4, 5
S_UNIT, UNIT_LINES, LINE_STRIDE, LINE_FIRST, UNIT_NEXT = 0x0191D700, 0x24, 0x20, 0xC, 0x8
OM_LINE, OM_MAX, HOURGLASS_VT, HG_SECONDS = 12, 600, 0x015EF5E0, 0x14A4
HOURGLASS_VALUES = (30, 60)
ORIG: dict = {}                                 # id(adapter) -> the tables and values as the game had them

ADDRESSES = {
    "mercs_authoritative_timer": {"address": S_AREA, "chain": "+0x3830 -> aGame +0x4DC",
                                  "native_getter": "0x000BBCA0", "native_update": "0x0001361C",
                                  "source": "Ghidra getter/countdown; native owner writes persist while HUD-only writes vanish",
                                  "live_checked": True},
    "sParameter_ptr": {"address": S_PARAM_PTR, "source": "executable dump: pool slot 0x0169699C; walk/run turn 0xA1A930, "
                                                          "aim controller 0x86E1EC", "live_checked": True},
    "weapon_definitions": {"address": DEF_TABLE, "source": "pool slot 0x0169CAB4 (can-fire 0x9D4DE4, consume check "
                                                            "0x9D3C70, fire action 0xA37E64)", "live_checked": True},
    "weapon_upgrades": {"address": UPG_TABLE, "source": "pool slot 0x0169E718 (fire action 0xA385B0: group 1 + "
                                                         "definition +0x90 = the interval)", "live_checked": True},
    "fire_timer_fps": {"address": FIRE_TIMER_FPS, "source": "pool constant read only by the fire action (0xA37F8C)",
                       "live_checked": True},
    "inventory": {"address": INV_OFS, "source": "player + 0x22E0, the item finder 0x9D309C", "live_checked": True},
    "player_health": {"address": P_HP, "source": "sPlayer + 0x28 -> player; player + 0x14A4: signed 16-bit hp/max, "
                                                "the verified Mercenaries RAM map", "live_checked": True},
    "player_hit_immunity": {"address": P_MUTEKI, "source": "Muteki setter 0x9BAFB0: mask 0x30 -> 0x10; "
        "helper 0x8348F4 clears +0x2EFC bit 0x40000 and disables type-1 incoming-hit nodes from +0x13D0. "
        "All three code signatures checked before writes; original bits and node bytes restored on disable",
        "live_checked": True},
}


class RE5:
    """One running RE5 Gold (BLUS30491) session's memory, checked to be that build."""

    def __init__(self, ad):
        self.ad = ad
        try:
            sig = struct.unpack(">2I", self.rd(DEF_TABLE, 8))
            usig = struct.unpack(">I", self.rd(UPG_TABLE, 4))[0]
        except Exception as e:                           # noqa: BLE001
            raise Unsupported(f"re5_mods needs the running game's memory (read_memory): {type(e).__name__}: {e}") from e
        if sig != DEF_SIGNATURE or usig != UPG_SIGNATURE:
            raise Unsupported(f"re5_mods: {GAME} only; the weapon tables are not where that build keeps them "
                              f"({sig[0]:08X} {sig[1]:08X} / {usig:08X})")
        self.orig = ORIG.setdefault(id(ad), {})
        from .mercs.titles import re5_controls
        re5_controls.bind_adapter(self.orig,ad)

    def rd(self, a: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(a, n))

    def wr(self, a: int, data: bytes) -> bool:
        self.ad.write_memory(a, data)
        return self.rd(a, len(data)) == data

    def u32(self, a: int) -> int:
        return struct.unpack(">I", self.rd(a, 4))[0]

    def f32(self, a: int) -> float:
        return struct.unpack(">f", self.rd(a, 4))[0]

    # ---- originals ----
    def param(self) -> int:
        p = self.u32(S_PARAM_PTR)
        if not 0x30000000 <= p < 0x40000000:
            raise RuntimeError("sParameter is not up yet (the game is still booting)")
        return p

    def keep(self, what: str, read):
        """The original of `what` (bytes), read once; later ops restore from it."""
        if what not in self.orig:
            self.orig[what] = read()
        return self.orig[what]

    def tables(self):
        self.keep("def", lambda: self.rd(DEF_TABLE, N_WEAPONS * DEF_STRIDE))
        self.keep("upg", lambda: self.rd(UPG_TABLE, N_WEAPONS * UPG_STRIDE))
        fps = self.keep("fps", lambda: self.rd(FIRE_TIMER_FPS, 4))
        if struct.unpack(">f", fps)[0] != FIRE_TIMER_ORIG and "fps_set" not in self.orig:
            raise RuntimeError(f"the fire timer constant is {struct.unpack('>f', fps)[0]} not 60.0: another tool "
                               "changed it; not touching the fire rate")
        # Each operation owns only its fields. Starting from the saved originals
        # silently undid the other mods: ammo reset fire intervals, and damage
        # reset firing-speed upgrades. Keep originals for scaling/restoration,
        # but preserve every other field from the current live tables.
        return (bytearray(self.rd(DEF_TABLE, N_WEAPONS * DEF_STRIDE)),
                bytearray(self.rd(UPG_TABLE, N_WEAPONS * UPG_STRIDE)), fps)

    # ---- state ----
    def inventory(self) -> list[dict]:
        sp = self.u32(S_PLAYER)
        pl = self.u32(sp + 0x28) if 0x30000000 <= sp < 0x40000000 else 0
        if not 0x30000000 <= pl < 0x40000000:
            return []
        d = self.rd(pl + INV_OFS, INV_SLOTS * SLOT)
        out = []
        for k in range(INV_SLOTS):
            s = d[k * SLOT:(k + 1) * SLOT]
            if not s[0x2D]:
                continue
            idw = struct.unpack_from(">I", s, 8)[0]
            out.append({"slot": k, "id": f"0x{idw:X}", "weapon": WEAPONS.get(idw & 0xFF) if idw >> 8 == 1 else None,
                        "rounds": struct.unpack_from(">I", s, 0xC)[0], "capacity": struct.unpack_from(">I", s, 0x10)[0],
                        "in_hand": struct.unpack_from(">I", s, 0x20)[0] == 1})
        return out

    def status(self) -> dict:
        st = {"game": GAME, "fire_timer_fps": round(self.f32(FIRE_TIMER_FPS), 2)}
        st["fire_rate_x"] = round(st["fire_timer_fps"] / FIRE_TIMER_ORIG, 2)
        try:
            p = self.param()
            st["turn"] = {name: round(self.f32(p + o), 3) for o, (name, _) in TURN.items()}
            st["turn_speed_x"] = round(st["turn"]["aim_yaw_deg_s"] / TURN[0x2D4][1], 2)
        except RuntimeError as e:
            st["turn"] = str(e)
        flags = [self.u32(DEF_TABLE + w * DEF_STRIDE + DEF_NOAMMO) for w in range(N_WEAPONS)]
        st["no_ammo_weapons"] = [WEAPONS.get(w, hex(w)) for w, f in enumerate(flags) if f == 1]
        from .mercs.titles import re5_mines
        mine_config = re5_mines.settings()
        st["infinite_ammo"] = all(flags[w] == 1 for w in WEAPONS
                                  if w not in KNIVES and not (w == 0x0A and mine_config["enabled"]))
        dmg = struct.unpack(">f", self.rd(UPG_TABLE + 0x02 * UPG_STRIDE + UPG_GROUP0 + G_DAMAGE * UPG_GROUP + 4, 4))[0]
        st["bullet_damage_x"] = round(dmg / 150.0, 2)                 # the M92F's level-0 firepower is 150
        inv = self.inventory()
        st["in_hand"] = next((x for x in inv if x["in_hand"]), None)
        st["inventory"] = inv
        from .mercs.titles import re5_mines
        st["mine_settings"] = mine_config
        from .mercs.titles import re5_ps3 as rotation
        st["mercs_rotation"] = rotation.coverage().status()
        st["mercs_catalog"] = {"rosters": rotation.MODE_ROSTERS, "stages": rotation.STAGE_NAMES}
        st["unlimited_health"] = bool(self.orig.get("health", {}).get("on"))
        st["health_maintenance"] = self.orig.get("health", {}).get("last")
        st["hit_immunity"] = bool((st["health_maintenance"] or {}).get("hit_immunity"))
        spray = self.orig.get("spray", {})
        st["infinite_spray"] = bool(spray.get("on"))
        st["sprays_restored"] = spray.get("restored", 0)
        st["spray_template_blocks"] = spray.get("blocks")
        st["spray_maintenance"] = spray.get("last")
        kt = self.orig.get("kill_time", {})
        st["kill_time_s"] = kt.get("seconds_max", kt.get("seconds", KILL_TIME_S)) if kt.get("on") else 0.0
        st["kill_time_on"] = bool(kt.get("on"))
        low, high = kt.get("seconds", KILL_TIME_RANGE[0]), kt.get("seconds_max", KILL_TIME_RANGE[1])
        st["kill_time_range"] = f"{low:g}-{high:g}" if high > low else f"{low:g}"
        st["fire_animation_enabled"] = bool(self.orig.get("fire_animation_on"))
        st["fire_animation_maintenance"] = self.orig.get("fire_animation_last")
        eggs=self.orig.get('rotten_eggs') or {}
        st.update(rotten_egg_only=bool(eggs.get('on')),egg_rate_x=eggs.get('rate',20.),
                  egg_status=eggs.get('status','disabled'),egg_native_equipped=bool(eggs.get('native_equipped')),
                  mine_animation_maintenance=self.orig.get('mine_animation_last'),
                  egg_animation_maintenance=self.orig.get('egg_animation_last'))
        from .mercs.titles import re5_controls
        with re5_controls.LOCK:
            st["capabilities"] = {op: {"available": True, "reason": "Verified build; readback required."}
                                  for op in OPERATOR_SETTINGS}
            st["capabilities"]["random_weapon"] = re5_controls.capability(self.orig)
            st['capabilities']['select_weapon']=re5_controls.capability(self.orig)
            st['available_weapons']=re5_controls.available(self.orig)
            st['preferred_weapon']=re5_controls.preference_status(self.orig)
            from .mercs.titles import re5_weapons
            st['all_weapons']=[{'item':k,'weapon':w.name,'family':w.family} for k,w in sorted(re5_weapons.WEAPONS.items())]
            st['weapon_override']=self.orig.get('weapon_override')
            st['capabilities']['weapon_override']={'available':True,'reason':'Loadout template; takes effect next round.'}
            from .mercs.titles import re5_live_weapon
            st['live_weapon'] = re5_live_weapon.status(self.orig)
            try:
                re5_live_weapon.validate(self)
                live_ready = re5_live_weapon.controller_ready(self.orig) and re5_live_weapon.adapter_identity(self.ad) is not None
                st['capabilities']['live_weapon'] = {'available': live_ready,
                    'reason': 'Native longbow pickup and ordinary equip during this round; waits for a safe ammo pickup.'
                    if live_ready else 'Waiting for a fresh active solo RE5 bot.'}
            except (ValueError, OSError, struct.error):
                st['capabilities']['live_weapon'] = {'available': False,
                    'reason': 'Native longbow construction signatures are not verified.'}
            st["capabilities"]["mines"] = {"available": True, "reason": "Mine cadence; loadout takes effect next round."}
            st["capabilities"]["mercs_select"] = {"available": True, "reason": "Choose the next Mercenaries round."}
            st['capabilities']['rotten_egg_only']={'available':True,
                'reason':'Native egg pickup/loadout then ordinary equip; active only after actual weapon confirmation.'}
            from .mercs.titles import re5_qte
            st['qte_assist'] = re5_qte.status(self.orig)
            st['capabilities']['instant_qte'] = re5_qte.capability(self)
            for op in ("aimbot", "auto_parry", "knife_knockback"):
                st["capabilities"][op] = {"available": False, "reason": "No verified live control for this hook."}
            st["operator_overrides"] = {k: dict(v) for k, v in self.orig.get("operator_overrides", {}).items()}
            st["random_weapon_request"] = re5_controls.request_status(self.orig)
        return st


def _health_player(g: RE5) -> int:
    sp = g.u32(S_PLAYER)
    pl = g.u32(sp + 0x28) if 0x30000000 <= sp <= 0x40000000 - 0x2C and sp % 4 == 0 else 0
    return pl if 0x30000000 <= pl <= 0x40000000 - P_HP - 4 and pl % 4 == 0 else 0


def _heap_range(address: int, size: int) -> bool:
    return address % 4 == 0 and 0x30000000 <= address <= 0x40000000 - size


def _hit_list(g: RE5, pl: int) -> tuple[bytes, list[tuple[int, int, int]]]:
    """Read and validate the player's own bounded collision list before any mutation."""
    if not _heap_range(pl, P_MUTEKI + 4):
        raise ValueError("player outside the verified heap")
    header = g.rd(pl + P_HIT_LIST, 0x1C)
    _, table, _, _, owner, capacity, count = struct.unpack(">7I", header)
    if owner != pl or not 0 < count <= capacity <= HIT_LIST_LIMIT or not _heap_range(table, capacity * 4):
        raise ValueError("waiting for the player's bounded hit list")
    nodes = []
    for index, node in enumerate(struct.unpack(f">{count}I", g.rd(table, count * 4))):
        if not node:
            continue
        if not _heap_range(node, HIT_NODE_TYPE + 4):
            raise ValueError("hit node outside the verified heap")
        if g.u32(node + HIT_NODE_TYPE) != 1:  # Leave outgoing attacks and other collision kinds alone.
            continue
        enabled = g.rd(node + HIT_NODE_ENABLE, 1)[0]
        if enabled not in (0, 1):
            raise ValueError("invalid incoming-hit enable byte")
        nodes.append((index, node, enabled))
    if not nodes:
        raise ValueError("waiting for incoming-hit collision nodes")
    return header, nodes


def _hit_list_current(g: RE5, pl: int, header: bytes, index=None, node=None) -> bool:
    if _health_player(g) != pl or g.rd(pl + P_HIT_LIST, len(header)) != header:
        return False
    hp, maximum = struct.unpack(">hh", g.rd(pl + P_HP, 4))
    if not 0 < hp <= maximum <= 32767:
        return False
    if index is not None:
        table = struct.unpack_from(">I", header, 4)[0]
        return g.u32(table + index * 4) == node and g.u32(node + HIT_NODE_TYPE) == 1
    return True


def _hit_immunity(g: RE5, pl: int, on: bool) -> dict:
    """Mirror the game's named Muteki action in RAM; never patch executable instructions."""
    result = {"hit_immunity": False, "immunity_verified": False}
    try:
        if any(g.rd(address, len(expected)) != expected for address, expected in IMMUNITY_SIGNATURES.items()):
            return {**result, "immunity_reason": "health only: immunity code signatures did not match"}
        header, nodes = _hit_list(g, pl)
        state = g.orig["health"].setdefault("immunity", {})
        if not on and state.get("player") != pl:
            return {**result, "immunity_verified": True, "immunity_restored": False}
        if on and state.get("player") != pl:
            state.clear()
            state.update(player=pl, flags=g.u32(pl + P_MUTEKI) & MUTEKI_MASK,
                         hit_state=g.u32(pl + P_HIT_STATE) & HIT_STATE_MASK, nodes={})
        if on and state.get("header") != header:
            # A replacement list can reuse node addresses. Never restore bytes from its predecessor.
            state.update(header=header, nodes={})
        restore_nodes = state.get("header") == header
        for _, node, enabled in nodes:
            if on:
                state["nodes"].setdefault(node, enabled)
        changes = ((P_MUTEKI, MUTEKI_MASK, MUTEKI_ON, state["flags"]),
                   (P_HIT_STATE, HIT_STATE_MASK, 0, state["hit_state"]))
        for offset, mask, enabled_bits, original in changes:
            if not _hit_list_current(g, pl, header):
                raise ValueError("player or hit list changed before flag write")
            current = g.u32(pl + offset)
            if not on and current & mask != enabled_bits:
                continue  # The game changed these bits; do not overwrite its new state.
            wanted = current & ~mask | (enabled_bits if on else original)
            if wanted != current and not g.wr(pl + offset, struct.pack(">I", wanted)):
                raise ValueError("immunity flag readback failed")
        for index, node, _ in nodes:
            if not _hit_list_current(g, pl, header, index, node):
                raise ValueError("player or collision entry changed before node write")
            current = g.rd(node + HIT_NODE_ENABLE, 1)[0]
            if current not in (0, 1):
                raise ValueError("incoming-hit enable byte changed to invalid value")
            if not on and (not restore_nodes or node not in state["nodes"] or current != 0):
                continue
            wanted = 0 if on else state["nodes"][node]
            if wanted != current and not g.wr(node + HIT_NODE_ENABLE, bytes([wanted])):
                raise ValueError("incoming-hit collision readback failed")
        if not _hit_list_current(g, pl, header):
            raise ValueError("player or hit list changed after immunity update")
        if on and (g.u32(pl + P_MUTEKI) & MUTEKI_MASK != MUTEKI_ON or
                   g.u32(pl + P_HIT_STATE) & HIT_STATE_MASK or
                   any(not _hit_list_current(g, pl, header, index, node) or
                       g.rd(node + HIT_NODE_ENABLE, 1) != b"\0" for index, node, _ in nodes)):
            raise ValueError("immunity state changed during verification")
        return {"hit_immunity": on, "immunity_verified": True, "immunity_colliders": len(nodes),
                "immunity_restored": not on and restore_nodes,
                "immunity_restore_skipped": not on and not restore_nodes}
    except Exception as error:
        return {**result, "immunity_reason": f"health only: {type(error).__name__}: {error}"}


def _maintain_health(g: RE5, snap=None) -> dict:
    from .mercs.titles.re5_ps3 import recovery_active
    state = g.orig.setdefault("health", {})
    result = {"unlimited_health": True, "active": False, "verified": False, "hit_immunity": False}
    pl = _health_player(g)
    if not pl or (snap is not None and (snap.get("player") or {}).get("ptr") != pl):
        return {**result, "reason": "waiting for the current player"}
    hp, maximum = struct.unpack(">hh", g.rd(pl + P_HP, 4))
    if not 0 < hp <= maximum <= 32767:
        return {**result, "reason": "waiting for a living player with valid health", "hp": hp, "hp_max": maximum}
    if hp == 1 and recovery_active(g, pl):
        return {**result, "resuscitating": True, "reason": "waiting for game-controlled resuscitation",
                "hp": hp, "hp_max": maximum}
    if state.get("player") != pl or maximum != state.get("boosted_max"):
        state.update(player=pl, original_max=maximum, boosted_max=max(maximum, HEALTH_MAX))
    target = state["boosted_max"]
    if _health_player(g) != pl:              # A respawn must never send a write to the previous allocation.
        return {**result, "reason": "player changed during health check"}
    hp, latest_max = struct.unpack(">hh", g.rd(pl + P_HP, 4))
    if not 0 < hp <= latest_max <= 32767 or latest_max != maximum:
        return {**result, "reason": "health changed during maintenance", "hp": hp, "hp_max": latest_max}
    if hp == 1 and recovery_active(g, pl):
        return {**result, "resuscitating": True, "reason": "waiting for game-controlled resuscitation",
                "hp": hp, "hp_max": maximum}
    wanted = struct.pack(">hh", target, target)
    verified = (hp == maximum == target) or g.wr(pl + P_HP, wanted)
    if verified and snap is not None:
        snap["player"].update(hp=target, hp_max=target)
    return {**result, "active": verified, "verified": verified, "hp": target if verified else hp,
            "hp_max": target if verified else maximum, "refilled": verified and hp != target,
            **(_hit_immunity(g, pl, True) if verified else {})}


# Time per kill: user setting 2026-10-23 is three seconds. Kills come from cGameSys; time belongs to aGame.
S_MAIN, MAIN_GAMESYS, GS_TIMER, GS_KILLS = 0x0191CEE4, 0x182D4, 0x3E0, 0x3F4
KILL_TIME_S = 10.0
KILL_TIME_RANGE = (10.0, 10.0)  # operator setting: ten seconds per dispatched enemy
KILL_TIME_MAX_S = 30.0
_KILL_LOCK = threading.RLock()


def kill_time(g: RE5, on: bool, seconds=None, seconds_max=None) -> dict:
    """Switch the per-kill time bonus; the Mercenaries observer applies it each snapshot (maintain_kill_time). seconds
    alone: that many per kill; seconds and seconds_max: a random whole number of seconds in that range per kill; neither:
    the last setting (KILL_TIME_RANGE the first time), so the panel's on / off keeps the range."""
    with _KILL_LOCK:
        state = g.orig.setdefault("kill_time", {})
        if seconds is None:
            low, high = state.get("seconds", KILL_TIME_RANGE[0]), state.get("seconds_max", KILL_TIME_RANGE[1])
        else:
            low = float(seconds)
            high = float(seconds_max) if seconds_max is not None else low
        low, high = float(low), float(high)
        if not 0 < low <= high <= KILL_TIME_MAX_S:
            raise ValueError(f"kill_time seconds: more than 0, at most {KILL_TIME_MAX_S:g}, and the minimum first")
        state.update(on=bool(on), seconds=low, seconds_max=high, gs=None, kills=None)
        return {"kill_time": state["on"], "seconds": low, "seconds_max": high, "verified": True}


def _kill_seconds(state) -> float:
    """One kill's seconds: the configured fixed value (ten by default), or an explicit random range."""
    import random
    low, high = state.get("seconds", KILL_TIME_S), state.get("seconds_max", state.get("seconds", KILL_TIME_S))
    if high <= low:
        return low
    if float(low).is_integer() and float(high).is_integer():
        return float(random.randint(int(low), int(high)))
    return round(random.uniform(low, high), 1)


def maintain_kill_time(ad, snap=None) -> dict:
    """+seconds on the round clock for each kill since the last snapshot. A new round (another cGameSys, or the count
    going down) starts counting afresh; a clock at 0 (the round is over) is never written."""
    with _KILL_LOCK:
        state = ORIG.get(id(ad), {}).get("kill_time", {})
        if not state.get("on"):
            return {"kill_time": False, "added": 0.0, "verified": True}
        try:
            rd = lambda a, n: bytes(ad.read_memory(a, n))
            ptr = lambda v: 0x30000000 <= v < 0x40000000
            main = struct.unpack(">I", rd(S_MAIN, 4))[0]
            gs = struct.unpack(">I", rd(main + MAIN_GAMESYS, 4))[0] if ptr(main) else 0
            if not ptr(gs):
                return {"kill_time": True, "added": 0.0, "verified": True, "reason": "no round"}
            kills = struct.unpack(">i", rd(gs + GS_KILLS, 4))[0]
            if not 0 <= kills <= 150:
                return {"kill_time": True, "added": 0.0, "verified": False, "reason": "invalid Mercenaries kill count"}
            last = state.get("kills")
            if state.get("gs") != gs or last is None or kills < last:
                state.update(gs=gs, kills=kills)
                return {"kill_time": True, "added": 0.0, "verified": True, "kills": kills}
            if kills == last:
                return {"kill_time": True, "added": 0.0, "verified": True, "kills": kills}
            state["kills"] = kills
            clock = struct.unpack(">f", rd(gs + GS_TIMER, 4))[0]
            if clock <= 0:
                return {"kill_time": True, "added": 0.0, "verified": True, "kills": kills, "reason": "round over"}
            added = sum(_kill_seconds(state) for _ in range(kills - last))
            result = _add_clock(ad, gs, added)
            verified = result["verified"]
            return {"kill_time": True, "added": added if verified else 0.0, "verified": verified, "kills": kills,
                    "clock": result["clock_after"], "clock_owner": result["clock_owner"],
                    **({"reason": result["reason"]} if result.get("reason") else {})}
        except Exception as error:         # A lost adapter must not stop the bot's next snapshot.
            return {"kill_time": True, "added": 0.0, "verified": False,
                    "reason": f"kill time unavailable: {type(error).__name__}: {str(error)[:120]}"}


def maintain_health(ad, snap=None) -> dict:
    """The Mercenaries observer calls this each snapshot; only an explicitly enabled session is written.

    Resolve the player anew after every respawn and verify the build and each write. Named Muteki hit immunity
    is enabled only after its three code signatures match. A refill cannot undo an already-triggered death.
    """
    with _HEALTH_LOCK:
        state = ORIG.get(id(ad), {}).get("health", {})
        if not state.get("on"):
            return {"unlimited_health": False, "active": False, "verified": True}
        try:
            result = _maintain_health(RE5(ad), snap)
        except Exception as error:         # A lost adapter must not stop the bot's next snapshot.
            result = {"unlimited_health": True, "active": False, "verified": False,
                      "reason": f"health maintenance unavailable: {type(error).__name__}"}
        state["last"] = result
        return result


def unlimited_health(g: RE5, on: bool) -> dict:
    with _HEALTH_LOCK:
        state = g.orig.setdefault("health", {})
        state["on"] = bool(on)
        if on:
            result = _maintain_health(g)
        else:
            result = {"unlimited_health": False, "active": False, "verified": True, "restored": False,
                      "hit_immunity": False}
            pl = _health_player(g)
            if pl and pl == state.get("player"):
                hp, maximum = struct.unpack(">hh", g.rd(pl + P_HP, 4))
                if maximum == state.get("boosted_max") and 0 < hp <= maximum and _health_player(g) == pl:
                    original = state["original_max"]
                    result["verified"] = g.wr(pl + P_HP, struct.pack(">hh", min(hp, original), original))
                    result["restored"] = result["verified"]
                if 0 < hp <= maximum and state.get("immunity"):
                    result.update(_hit_immunity(g, pl, False))
                    result["verified"] &= result["immunity_verified"]
        state["last"] = result
        return {**result, "note": "maintained on every Mercenaries bot snapshot, including prompts and walking; "
                                 "living HP/max refill plus signature-verified Muteki incoming-hit immunity; "
                                 "does not resurrect an already-dead player"}


def _animation_scope(ad):
    """A cached guest PID alone cannot distinguish exit/reuse or a save-state generation."""
    pid, base = ad._guest()
    if type(pid) is not int or pid <= 0 or type(base) is not int or base <= 0:
        raise ValueError("invalid animation process identity")
    stat = Path(f"/proc/{pid}/stat").read_text()
    start = stat[stat.rfind(")") + 2:].split()[19]
    return id(ad), pid, base, start, getattr(ad, "generation", 0)


def maintain_fire_animation(ad, snap=None, *, enabled=True) -> dict:
    """Maintain the explicit fire-rate package's bounded magnum playback component.

    Unsupported adapters never acquire write access. The helper verifies exact live code, action, weapon and
    motion identities; this wrapper also checks the current process generation immediately before every write.
    """
    with _HEALTH_LOCK:
        state = ORIG.get(id(ad), {})
        configured = bool(state.get("fire_animation_on"))
        helper = state.get("fire_animation_helper")
        result = {"enabled": configured and bool(enabled), "active": False, "verified": True,
                  "writes": 0, "restored": 0, "reason": "firing animation is not enabled"}
        if not configured and helper is None:
            return result
        try:
            from .mercs.titles.re5_fire_animation import FireAnimation, MAX_MULTIPLIER
            scope = _animation_scope(ad)
            game = RE5(ad)

            class ScopedMemory:
                def rd(self, address, size):
                    return game.rd(address, size)

                def wr(self, address, data):
                    if _animation_scope(ad) != scope:
                        raise ValueError("animation process identity changed before write")
                    return game.wr(address, data)

            if helper is None:
                helper = state["fire_animation_helper"] = FireAnimation()
            multiplier = min(MAX_MULTIPLIER, max(1.0, state.get("fps_set", 1.0)))
            result = helper.update(ScopedMemory(), snap, enabled=configured and bool(enabled),
                                   multiplier=multiplier, scope=scope)
        except Exception as error:  # A missed animation update must not block a QTE or the next control tick.
            result.update(verified=False, reason=f"firing animation unavailable: {type(error).__name__}")
        state["fire_animation_last"] = result
        return result


def maintain_item_animation(ad,snap=None,*,enabled=True):
    """Owned rate floats for verified native mine placement or egg FIRE."""
    with _HEALTH_LOCK:
        state=ORIG.setdefault(id(ad),{});eggs=state.get('rotten_eggs') or {}
        output={}
        try:
            from .mercs.titles import re5_item_animation as A
            scope=_animation_scope(ad);game=RE5(ad)
            class ScopedMemory:
                def rd(self,address,size):return game.rd(address,size)
                def wr(self,address,data):
                    if _animation_scope(ad)!=scope:raise ValueError('item animation process changed')
                    return game.wr(address,data)
            memory=ScopedMemory()
            for key,make,active,rate in (
                ('mine',A.mine_helper,enabled and not eggs.get('on'),A.MINE_RATE),
                ('egg',A.egg_helper,enabled and bool(eggs.get('on')),eggs.get('rate',20.))):
                helper=state.get(key+'_animation_helper')
                if helper is None:helper=state[key+'_animation_helper']=make()
                result=helper.update(memory,snap,enabled=bool(active),multiplier=rate,scope=scope)
                state[key+'_animation_last']=result;output[key]=result
        except Exception as error:
            output['error']=type(error).__name__
        output['verified']='error' not in output and all(
            result.get('verified',False) for result in output.values() if isinstance(result,dict))
        return output


def _mult(v, default=2.0) -> float:
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("max", "maximum", "unlimited"):
            return TURN_MAX
        v = float(s or default)
    return float(v if v is not None else default)


def turn_speed(g: RE5, mult) -> dict:
    k = _mult(mult)
    if not 0.25 <= k <= 50:
        raise ValueError("turn_speed multiplier: 0.25 .. 50 (1 = the game's; 2 = default; max = 10)")
    p = g.param()
    live = {o: g.f32(p + o) for o in TURN}                   # the game's own values, or an earlier multiple of them
    bad = {TURN[o][0]: v for o, v in live.items() if not 0.2 <= v / TURN[o][1] <= 60}
    if bad:
        raise RuntimeError(f"sParameter does not hold this build's turn rates ({bad}); not writing")
    g.orig["turn"] = {o: base for o, (_, base) in TURN.items()}
    out, ok = {}, True
    for o, (name, base) in TURN.items():
        want = struct.pack(">f", base * k)
        ok &= g.wr(p + o, want)
        out[name] = round(g.f32(p + o), 4)
    return {"turn_speed_x": k, "values": out, "verified": ok, "sParameter": f"0x{p:08X}",
            "note": "the stick turns the player this many times faster, aiming (yaw and pitch) and not; the bot's "
                    "aim pulses settle up to x3 (a 50 ms pulse at x3 is ~4.5 deg)"}


def _upg_group(u: bytearray, wid: int, group: int) -> tuple[int, list[float]]:
    at = wid * UPG_STRIDE + UPG_GROUP0 + group * UPG_GROUP + 4
    return at, list(struct.unpack_from(f">{UPG_LEVELS}f", u, at))


def fire_rate(g: RE5, mult) -> dict:
    k = _mult(mult, 80.0)
    if not 0.1 <= k <= 1000:
        raise ValueError("fire_rate multiplier: 0.1 .. 1000 (1 = the game's; 80 = the operator's)")
    d, u, fps = g.tables()
    d0, u0 = ORIG[id(g.ad)]["def"], ORIG[id(g.ad)]["upg"]
    for wid in range(N_WEAPONS):
        if wid in KNIVES or wid in NO_WEAPON:
            continue
        ofs = struct.unpack_from(">f", d0, wid * DEF_STRIDE + DEF_INTERVAL_OFS)[0]
        struct.pack_into(">f", d, wid * DEF_STRIDE + DEF_INTERVAL_OFS, ofs if k == 1 else 0.0)
        at, _ = _upg_group(u, wid, G_FIRE)
        _, vals = _upg_group(bytearray(u0), wid, G_FIRE)
        struct.pack_into(f">{UPG_LEVELS}f", u, at, *[v / k for v in vals])
    ok = g.wr(DEF_TABLE, bytes(d)) and g.wr(UPG_TABLE, bytes(u))
    ok &= g.wr(FIRE_TIMER_FPS, struct.pack(">f", FIRE_TIMER_ORIG * k))
    g.orig["fps_set"] = k
    g.orig["fire_animation_on"] = bool(ok and k > 1)
    if not g.orig["fire_animation_on"]:
        maintain_fire_animation(g.ad, enabled=False)
    _, m92 = _upg_group(u, 0x02, G_FIRE)
    return {"fire_rate_x": k, "verified": ok, "fire_timer_fps": round(g.f32(FIRE_TIMER_FPS), 2),
            "m92f_frames_between_shots": round(m92[0], 4),
            "magnum_animation_rate_x": min(k, 8.0) if k > 1 and ok else 1.0,
            "note": "firing-speed table / N and fire-action timer x N; held fire still depends on weapon animation "
                    "and update gates, so N is not measured shots per second. The bot's guarded magnum animation "
                    "component is capped at 8x; other animation types are unchanged. 1 restores the game's values"}


def infinite_ammo(g: RE5, on: bool) -> dict:
    d, _, _ = g.tables()
    d0 = ORIG[id(g.ad)]["def"]
    for wid in range(N_WEAPONS):
        if wid in KNIVES or wid in NO_WEAPON:
            continue
        v = 1 if on else struct.unpack_from(">I", d0, wid * DEF_STRIDE + DEF_NOAMMO)[0]
        struct.pack_into(">I", d, wid * DEF_STRIDE + DEF_NOAMMO, v)
    ok = g.wr(DEF_TABLE, bytes(d))
    return {"infinite_ammo": on, "verified": ok,
            "note": "the Gatling's own 'needs no ammo' flag on every gun and grenade: rounds are never spent, the HUD "
                    "shows the infinity sign, no reload is ever needed (the rounds word stays where it was)"}


def bullet_damage(g: RE5, mult) -> dict:
    k = _mult(mult, 10.0)
    if not 0.1 <= k <= 1000:
        raise ValueError("bullet_damage multiplier: 0.1 .. 1000 (1 = the game's)")
    _, u, _ = g.tables()
    u0 = ORIG[id(g.ad)]["upg"]
    for wid in range(N_WEAPONS):
        if wid in NO_WEAPON:
            continue
        at, _ = _upg_group(u, wid, G_DAMAGE)
        _, vals = _upg_group(bytearray(u0), wid, G_DAMAGE)
        struct.pack_into(f">{UPG_LEVELS}f", u, at, *[v * k for v in vals])
    ok = g.wr(UPG_TABLE, bytes(u))
    _, m92 = _upg_group(u, 0x02, G_DAMAGE)
    return {"bullet_damage_x": k, "verified": ok, "m92f_firepower_level0": round(m92[0], 1),
            "note": "every weapon's firepower at every upgrade level x N (a Majini has 800 health; the M92F's 150 "
                    "becomes a one-shot kill from x6)"}


def template_records(t: bytes):
    """[(offset, id word, count, position, in_hand, levels)] of every item record in the template image."""
    if len(t) % TEMPLATE_BLOCK:
        raise ValueError('loadout template bank is truncated')
    out = []
    for b in range(len(t) // TEMPLATE_BLOCK):
        for r in range(12):
            off = b * TEMPLATE_BLOCK + r * TEMPLATE_REC
            w = struct.unpack_from(">11I", t, off)
            if w[0] and w[0] != 0xFFFFFFFF and w[2] == w[3] == w[4] == 0xFFFFFFFF:
                out.append((off, w[0], w[1], w[5], w[6], w[7]))
    return out


def verify_preset_descriptors(g,base,descriptors):
    for index,address in enumerate(descriptors):
        if tuple(struct.unpack('>2I',g.rd(address,8))) != (base+index*TEMPLATE_BLOCK,12):
            raise RuntimeError('native preset descriptor pointer/count differs')


def verify_main_presets(g):
    verify_preset_descriptors(g,TEMPLATE,TEMPLATE_DESCRIPTORS)
    if g.u32(TEMPLATE+TEMPLATE_SIGNATURE[0])!=TEMPLATE_SIGNATURE[1]:
        raise RuntimeError('loadout template signature differs')


def spray_model(t: bytes) -> bytes | None:
    """The game's own First Aid Spray template record (Sheva Business and Rebecca carry one; docs/mercenaries_re5_meta.md),
    the model for the words of a record this module does not interpret (the flags); None in an image without one."""
    for off, idw, *_ in template_records(t):
        if idw == SPRAY_ID:
            return bytes(t[off:off + TEMPLATE_REC])
    return None


def spray_overlay(t: bytes, model: bytes | None = None) -> tuple[bytearray, list, list]:
    """Every template block with a First Aid Spray record: (the image, [converted {block, record, grid, source, from}],
    [skipped {block, reason}]). A block without one gets a spray in the place of one record the round can do without:
    its last ammo record (type 2; the autobot's guns spend no rounds), else its last herb record (the spray heals more),
    else its last free record (id 0, a game-owned grid slot: re5_mines) at a free grid position; a block with none of
    those is left alone and reported. The spray record is the game's own (model) with count 1, that grid position, not
    in hand, level 0; without a model the shape the mine / egg loadouts use (flags 0)."""
    t = bytearray(t)
    base_rec = list(struct.unpack(">11I", model)) if model else [SPRAY_ID, 1, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0, 0, 0, 0, 0, 0]
    converted, skipped = [], []
    for b in range(TEMPLATE_BLOCKS):
        base = b * TEMPLATE_BLOCK
        rows = [list(struct.unpack_from(">11I", t, base + r * TEMPLATE_REC)) for r in range(12)]
        if any(r[0] == SPRAY_ID for r in rows):
            continue

        def item(r):                                  # a carried item record, placed on the grid, not the one in hand
            return r[0] and r[0] != 0xFFFFFFFF and r[2] == r[3] == r[4] == 0xFFFFFFFF and r[5] < 9 and r[6] == 0

        ammo = [i for i, r in enumerate(rows) if item(r) and r[0] >> 8 == 2]
        herbs = [i for i, r in enumerate(rows) if item(r) and r[0] in TEMPLATE_HERBS]
        if ammo:
            idx, source, grid = ammo[-1], "ammo", rows[ammo[-1]][5]
        elif herbs:
            idx, source, grid = herbs[-1], "herb", rows[herbs[-1]][5]
        else:
            occupied = {r[5] for r in rows if r[0] and r[0] != 0xFFFFFFFF and r[5] < 9}
            free = [i for i, r in enumerate(rows) if r[0] == 0 and r[5] < 9]
            grid = next((x for x in SPRAY_GRIDS if x not in occupied), None)
            if not free or grid is None:
                skipped.append({"block": b, "reason": "no ammo, herb or free record to turn into a spray"})
                continue
            idx, source = free[-1], "free"
        rec = list(base_rec)
        rec[0], rec[1], rec[5], rec[6], rec[7] = SPRAY_ID, 1, grid, 0, 0
        struct.pack_into(">11I", t, base + idx * TEMPLATE_REC, *rec)
        converted.append({"block": b, "record": idx, "grid": grid, "source": source, "from": f"0x{rows[idx][0]:X}"})
    return t, converted, skipped


def _with_spray(g: RE5, t: bytearray) -> bytearray:
    """A template image about to be written, with infinite_spray's records in it when that op is on (the per-round
    loadout rewrites the whole template from the original: the sprays go back in on the same write). The records'
    first-seen bytes are kept per offset for infinite_spray on=false."""
    state = g.orig.get("spray") or {}
    if not state.get("on"):
        return t
    model = state.get("model") or spray_model(g.orig.get("template") or bytes(t))
    out, converted, skipped = spray_overlay(t, model)
    owned = state.setdefault("template_records", {})
    for c in converted:
        off = c["block"] * TEMPLATE_BLOCK + c["record"] * TEMPLATE_REC
        rec = owned.setdefault(off, {"before": bytes(t[off:off + TEMPLATE_REC])})
        rec["after"] = bytes(out[off:off + TEMPLATE_REC])
    state.update(blocks=sum(1 for b in range(TEMPLATE_BLOCKS)
                            if any(idw == SPRAY_ID for off, idw, *_ in template_records(out) if off // TEMPLATE_BLOCK == b)),
                 converted=len(converted), skipped=skipped)
    return out


def infinite_spray(g: RE5, on: bool) -> dict:
    """The operator's infinite First Aid Spray for the autobot (2026-10-24), with unlimited_health off: (a) every
    character's loadout template holds a spray record, so each round starts with one the game itself builds
    (spray_overlay: an ammo, herb or free record becomes the spray; takes effect at the next round start); (b) each bot
    snapshot maintain_spray replays the game-made spray record into its slot once the bot has used it and carries no
    other recovery item. on=false puts the converted template records back (the ones still holding our bytes) and stops
    the replay; the live inventory is never touched by off."""
    with _HEALTH_LOCK:
        verify_main_presets(g)
        current = g.rd(TEMPLATE, TEMPLATE_BLOCKS * TEMPLATE_BLOCK)
        t0 = g.keep("template", lambda: current)
        state = g.orig.setdefault("spray", {})
        state.setdefault("restored", 0)
        if not on:
            state["on"] = False
            state.pop("spray_record", None)
            owned, ok, back = state.pop("template_records", {}), True, 0
            for off, rec in owned.items():
                if g.rd(TEMPLATE + off, TEMPLATE_REC) == rec["after"]:
                    ok &= g.wr(TEMPLATE + off, rec["before"])
                    back += 1
            state.update(blocks=None, converted=0, skipped=[])
            return {"infinite_spray": False, "verified": ok, "template_records_restored": back,
                    "sprays_restored": state["restored"], "effective_next_round": True,
                    "note": "the template records this op converted are the game's again (next round start); a spray "
                            "already built into the inventory stays until used"}
        state["on"] = True
        state["model"] = spray_model(t0) or spray_model(current)
        t = _with_spray(g, bytearray(current))
        ok, written = True, 0
        for off, rec in state.get("template_records", {}).items():
            if current[off:off + TEMPLATE_REC] != rec["after"]:
                if g.rd(TEMPLATE + off, TEMPLATE_REC) != current[off:off + TEMPLATE_REC]:
                    raise RuntimeError("infinite_spray: template changed during validation")
                ok &= g.wr(TEMPLATE + off, rec["after"])
                written += 1
        return {"infinite_spray": True, "verified": bool(ok), "blocks_with_spray": state.get("blocks"),
                "blocks_converted": state.get("converted", 0), "records_written": written, "skipped": state.get("skipped"),
                "model": "the game's own spray record" if state["model"] else "mine/egg record shape (flags 0)",
                "sprays_restored": state["restored"], "effective_next_round": True,
                "note": "every character's loadout template now holds one First Aid Spray (built by the game at the "
                        "round start; an ammo or herb record made room for it); the bot's snapshots replay the spray's "
                        "game-made record into its slot after each use (maintain_spray). Live RAM check pending."}


def _slot_rows(raw: bytes) -> list[dict]:
    """The used inventory slots of a raw player + INV_OFS image: slot, id, count, grid, hand."""
    rows = []
    for k in range(INV_SLOTS):
        s = raw[k * SLOT:(k + 1) * SLOT]
        if not s[SLOT_USED]:
            continue
        rows.append({"slot": k, "id": struct.unpack_from(">I", s, SLOT_ID)[0], "count": struct.unpack_from(">I", s, SLOT_COUNT)[0],
                     "grid": struct.unpack_from(">I", s, SLOT_GRID)[0], "hand": struct.unpack_from(">I", s, SLOT_HAND)[0] == 1,
                     "bytes": bytes(s)})
    return rows


def _maintain_spray(g: RE5, state: dict, snap, now: float) -> dict:
    result = {"infinite_spray": True, "active": False, "restored": False, "verified": True,
              "sprays_restored": state.get("restored", 0)}
    pl = _health_player(g)
    if not pl or (snap is not None and (snap.get("player") or {}).get("ptr") != pl):
        return {**result, "reason": "waiting for the current player"}
    hp, maximum = struct.unpack(">hh", g.rd(pl + P_HP, 4))
    if not 0 < hp <= maximum <= 32767:
        return {**result, "reason": "waiting for a living player with valid health", "hp": hp}
    rec = state.get("spray_record")
    if rec and rec.get("player") != pl:                     # another player allocation: its records are not this one's
        state.pop("spray_record", None)
        rec = None
    rows = _slot_rows(g.rd(pl + INV_OFS, INV_SLOTS * SLOT))
    carried = [r for r in rows if r["id"] in HEAL_IDS and r["count"] > 0]
    for r in rows:                                          # the spray as the game made it, unequipped: remembered
        if r["id"] == SPRAY_ID and r["count"] >= 1 and not r["hand"]:
            state["spray_record"] = rec = {"player": pl, "slot": r["slot"], "grid": r["grid"], "bytes": r["bytes"], "armed": True}
    result["active"] = True
    if carried:
        return {**result, "carried": len(carried)}
    if rec is None:
        return {**result, "reason": "no game-created First Aid Spray record seen for this player yet"}
    if not rec.get("armed"):
        return {**result, "reason": "spray record replayed; waiting for the game to hold it again"}
    last = state.get("last_restore_at")
    if last is not None and now - last < SPRAY_RESTORE_GAP_S:
        return {**result, "reason": f"restore gap ({SPRAY_RESTORE_GAP_S - (now - last):.1f} s left)"}
    k, grid = rec["slot"], rec["grid"]
    held = next((r for r in rows if r["slot"] == k), None)
    if held is not None:
        return {**result, "reason": f"slot {k} is in use (0x{held['id']:X}); a held record is never overwritten"}
    taken = next((r for r in rows if r["grid"] == grid), None)
    if taken is not None:
        return {**result, "reason": f"grid {grid} is held by slot {taken['slot']} (0x{taken['id']:X}); not restoring over it"}
    at = pl + INV_OFS + k * SLOT
    if _health_player(g) != pl or g.rd(at + SLOT_USED, 1) != b"\0":   # re-checked right before the write
        return {**result, "reason": "player or slot changed before the write"}
    if not g.wr(at, rec["bytes"]):
        return {**result, "verified": False, "reason": "spray record readback failed"}
    rec["armed"] = False
    state["restored"] = state.get("restored", 0) + 1
    state["last_restore_at"] = now
    if snap is not None and isinstance(snap.get("inventory"), list):     # this snapshot's heal logic sees it
        snap["inventory"].append({"slot": k, "id": SPRAY_ID, "type": SPRAY_ID >> 8, "item": SPRAY_ID & 0xFF,
                                  "rounds": struct.unpack_from(">I", rec["bytes"], SLOT_COUNT)[0], "cap": 1,
                                  "grid": grid if grid < INV_SLOTS else None, "grid_raw": grid, "hand": False})
    return {**result, "restored": True, "slot": k, "grid": grid, "sprays_restored": state["restored"]}


def maintain_spray(ad, snap=None, now: float | None = None) -> dict:
    """The Mercenaries observer calls this each playing snapshot; only a session with infinite_spray on is written.

    The restore is an exact byte replay of a record the game itself created: the First Aid Spray's 0x30-byte inventory
    slot as it was observed, unequipped, in this player's inventory. It goes back into that same slot only when the slot
    is free (its in-use byte is 0), no record holds its grid position, the player is alive and carries no recovery item,
    and at least SPRAY_RESTORE_GAP_S passed since the last replay. Nothing is ever created from scratch, and nothing is
    written while the slot or the grid is in use.
    """
    import time
    with _HEALTH_LOCK:
        state = ORIG.get(id(ad), {}).get("spray", {})
        if not state.get("on"):
            return {"infinite_spray": False, "active": False, "verified": True}
        try:
            result = _maintain_spray(RE5(ad), state, snap, time.monotonic() if now is None else now)
        except Exception as error:         # A lost adapter must not stop the bot's next snapshot.
            result = {"infinite_spray": True, "active": False, "restored": False, "verified": False,
                      "reason": f"spray maintenance unavailable: {type(error).__name__}"}
        state["last"] = result
        return result


def loadout(g: RE5, weapons=None, seed=None, on: bool = True) -> dict:
    """Every character's Mercenaries loadout template: each gun (table 1, not the knives) becomes one of the powerful
    campaign weapons, drawn at random per record without repeats inside a block (seed for a repeatable draw); the
    packed upgrade levels are reset to 0 so no level indexes past the new weapon's table. on=false restores (with
    infinite_spray's records kept in either case: the whole template is rewritten from the original here)."""
    import random
    verify_main_presets(g)
    t0 = g.keep("template", lambda: g.rd(TEMPLATE, TEMPLATE_BLOCKS * TEMPLATE_BLOCK))
    if not on:
        return {"loadout": "the game's", "verified": g.wr(TEMPLATE, bytes(_with_spray(g, bytearray(t0))))}
    override = g.orig.get("weapon_override")
    if override:                                             # the operator's chosen weapon beats a random draw
        return weapon_override(g, override["item"], override.get("only", False))
    pool = [int(str(w), 0) if isinstance(w, str) and str(w).startswith("0x") else w for w in (weapons or [])]
    pool = [w for w in pool if w in POWERFUL or w in REPLACE_WITH_MAGNUM] or list(POWERFUL)
    rng = random.Random(seed)
    t = bytearray(t0)
    picks: dict = {}
    for off, idw, _, _, in_hand, _ in template_records(t0):
        if idw >> 8 != 1 or idw in KNIFE_IDS:
            continue
        block = off // TEMPLATE_BLOCK
        used = picks.setdefault(block, [])
        choice = rng.choice([w for w in pool if w not in used] or pool)
        if choice in REPLACE_WITH_MAGNUM:
            choice = rng.choice([w for w in MAGNUMS if w not in used] or MAGNUMS)
        used.append(choice)
        struct.pack_into(">I", t, off, choice)
        struct.pack_into(">I", t, off + 7 * 4, 0)
    ok = g.wr(TEMPLATE, bytes(_with_spray(g, t)))
    named = {b: [POWERFUL[w] for w in ws] for b, ws in picks.items()}
    return {"loadout": "random powerful campaign weapons", "verified": ok, "blocks": len(picks),
            "barry": named.get(24), "chris_heavy_metal": named.get(18), "picks": named,
            "note": "takes effect at the next round start (the game copies the template into the inventory then)"}


def weapon_override(g: RE5, weapon=None, only: bool = False) -> dict:
    """Any RE5 weapon as every character's main gun (only=True: every gun slot, e.g. longbow-only rounds), written into
    the Mercenaries loadout templates the game copies into the inventory at the next round start; weapon=None restores
    the game's loadout (operator 2026-10-24: "Allow me choose any weapon from the game in general and replace the main
    weapon equipped with it" / "rounds where everyone is using a bow as the only weapon and they are rapid firing it").
    Kept across rounds: loadout() honours it instead of drawing random guns."""
    from .mercs.titles import re5_weapons
    from .mercs.titles import re5_mines
    verify_main_presets(g)
    re5_mines.verify_original_presets(g)
    banks = [(TEMPLATE, TEMPLATE_BLOCKS, "template"),
             *((address, 10, f"mine_bank_{address:x}") for address in re5_mines.ORIGINAL_BANKS)]
    originals = [(address, g.keep(key, lambda a=address, n=blocks: g.rd(a, n * TEMPLATE_BLOCK)))
                 for address, blocks, key in banks]
    if any(len(original) != blocks * TEMPLATE_BLOCK
           for (_, blocks, _), (_, original) in zip(banks, originals)):
        raise ValueError('loadout template bank size differs')
    if weapon in (None, "", "auto"):
        ok = True
        for address, original in originals:
            data = _with_spray(g, bytearray(original)) if address == TEMPLATE else original
            ok = g.wr(address, bytes(data)) and ok
        if ok:
            g.orig.pop("weapon_override", None)
        return {"weapon_override": g.orig.get("weapon_override"), "verified": ok,
                "effective_next_round": True,
                "note": "the game's loadout from the next round start"}
    item = int(str(weapon), 0) if isinstance(weapon, str) else int(weapon)
    item &= 0xFF
    w = re5_weapons.WEAPONS.get(item)
    if w is None:
        raise ValueError(f"unknown RE5 weapon {item:#x}")
    changed, ok = 0, True
    for address, original in originals:
        t = bytearray(original)
        for off, idw, _, _, in_hand, _ in template_records(original):
            if idw >> 8 != 1 or idw in KNIFE_IDS or not (only or in_hand):
                continue
            struct.pack_into(">I", t, off, 0x100 | item)
            struct.pack_into(">I", t, off + 7 * 4, 0)      # upgrade levels reset: none indexes past the new table
            changed += 1
        ok = g.wr(address, bytes(_with_spray(g, t) if address == TEMPLATE else t)) and ok
    if ok:
        g.orig["weapon_override"] = {"item": item, "weapon": w.name, "only": bool(only)}
    return {"weapon_override": g.orig.get("weapon_override"), "records": changed, "verified": ok,
            "effective_next_round": True, "template_banks": len(banks),
            "note": "takes effect at the next round start (the game copies the template into the inventory then)"}


def replace_rockets(g: RE5, seed=None) -> dict:
    """Replace only rocket entries in live spawn templates; the game constructs the magnum next round.

    This deliberately does not relabel an already-created rocket weapon object as a magnum.
    It preserves grid, in-hand flags, unrelated records and other active loadout changes.
    """
    return _replace_spawn_guns(g, {0x10D}, seed, "rocket_replacements")


def replace_long_guns(g: RE5, seed=None) -> dict:
    """Replace rockets and all three sniper rifles at the next game-created loadout."""
    return _replace_spawn_guns(g, REPLACE_WITH_MAGNUM, seed, "weapon_replacements")


def _replace_spawn_guns(g: RE5, unwanted, seed, result_key):
    import random
    verify_main_presets(g)
    current = g.rd(TEMPLATE, TEMPLATE_BLOCKS * TEMPLATE_BLOCK)
    g.keep("template", lambda: current)
    rng, replaced, ok = random.Random(seed), [], True
    for off, idw, _, pos, hand, _ in template_records(current):
        if idw not in unwanted:
            continue
        before = current[off:off + TEMPLATE_REC]
        if g.rd(TEMPLATE + off, TEMPLATE_REC) != before:
            raise RuntimeError("rocket replacement: template changed during validation")
        item = rng.choice(MAGNUMS)
        record = bytearray(before)
        struct.pack_into(">II", record, 0, item, 0xFFFFFFFF)  # its own full magazine
        struct.pack_into(">I", record, 0x1C, 0)              # valid level-zero upgrades
        ok &= g.wr(TEMPLATE + off, bytes(record))
        replaced.append({"address": f"0x{TEMPLATE + off:X}", "item": item,
                         "weapon": WEAPONS[item & 0xFF], "grid": pos, "in_hand": bool(hand)})
    return {"verified": ok, result_key: replaced, "effective_next_round": True,
            "note": "spawn templates only; equipped weapon readback is required after the next round starts"}


def random_cheats(g: RE5, seed=None) -> dict:
    """The operator's per-round randomizer: fire_rate x80; turn speed the game's own (operator 2026-10-22: "lower their turn speed back to regular"); bullet damage x10;
    infinite ammo on; the loadout re-drawn. Returns what was picked as "telemetry" (the playbook shows it)."""
    import random
    rng = random.Random(seed)
    picked = {"fire_rate_x": 80.0, "turn_speed_x": 1.0, "bullet_damage_x": 10.0,
              "infinite_ammo": True, "loadout": rng.random() < 0.75}
    out: dict = {}
    for op, field in (("fire_rate", "fire_rate_x"), ("turn_speed", "turn_speed_x"),
                      ("bullet_damage", "bullet_damage_x"), ("infinite_ammo", "infinite_ammo")):
        result = run(g.ad, op, picked[field] if op != "infinite_ammo" else None, g=g)
        out[op] = result["verified"]
        picked[field] = result["status"][field]
    if picked["loadout"] or g.orig.get("weapon_override"):
        lo = loadout(g, seed=rng.random())
        out["loadout"] = lo["verified"]
        picked["loadout_barry"] = lo.get("barry")
        if lo.get("weapon_override"):
            picked["weapon_override"] = lo["weapon_override"]
    else:
        out["loadout"] = loadout(g, on=False)["verified"]
    out["weapon_replacement"] = replace_long_guns(g, rng.random())["verified"]
    return {"telemetry": picked, "verified": all(out.values()), "applied": out}


def gamesys(g: RE5) -> int:
    main = g.u32(S_MAIN)
    gs = g.u32(main + MAIN_GAMESYS) if 0x30000000 <= main < 0x40000000 else 0
    if not 0x30000000 <= gs < 0x40000000:
        raise RuntimeError("no Mercenaries round is up (cGameSys is not there)")
    return gs


def _add_clock(ad, gs: int, seconds: float) -> dict:
    """Mirror the verified native aGame add-time data path; never fall back to a transient HUD-only write."""
    import math
    rd = lambda address, size: bytes(ad.read_memory(address, size))
    u32 = lambda address: struct.unpack(">I", rd(address, 4))[0]
    f32 = lambda address: struct.unpack(">f", rd(address, 4))[0]
    ptr = lambda value: 0x30000000 <= value < 0x40000000
    main = u32(S_MAIN)
    if not ptr(main) or u32(main + MAIN_GAMESYS) != gs or u32(gs + 0x58) not in (2, 5):
        raise RuntimeError("active original/Reunion Mercenaries round unavailable")
    area = u32(S_AREA)
    if not ptr(area) or u32(area) != AREA_VT:
        raise RuntimeError("verified sArea timer owner unavailable")
    owner = u32(area + AREA_GAME)
    if not ptr(owner) or u32(owner) != GAME_VT or u32(owner + GAME_CLOCK_STATE) != 0:
        raise RuntimeError("verified active aGame timer owner unavailable")
    clock, before = f32(gs + GS_CLOCK), f32(owner + GAME_CLOCK)
    if not all(math.isfinite(v) and 0 < v < 86400 for v in (clock, before)) or abs(clock-before) > 2:
        raise RuntimeError("authoritative countdown disagrees with the live HUD or round is over")
    if u32(S_AREA) != area or u32(area + AREA_GAME) != owner or u32(owner) != GAME_VT \
            or u32(S_MAIN) != main or u32(main + MAIN_GAMESYS) != gs:
        raise RuntimeError("timer owner changed before the write")
    ad.write_memory(owner + GAME_CLOCK, struct.pack(">f", before + seconds))
    after = f32(owner + GAME_CLOCK)
    verified = math.isfinite(after) and before + seconds - .5 <= after <= before + seconds + .01
    if verified:
        # The game copies owner -> HUD on its next frame; do not overwrite a concurrently advancing HUD clock.
        ad.write_memory(gs + GS_LAST_BONUS, struct.pack(">i", int(round(seconds))))
        ad.write_memory(gs + GS_SHOW_BONUS, b"\x01")
    return {"verified": verified, "clock_before": round(clock, 2), "clock_after": round(after, 2),
            "clock_owner": hex(owner), **({"reason": "authoritative countdown write not confirmed"} if not verified else {})}


def add_time(g: RE5, seconds: float = 60.0) -> dict:
    """Add to the authoritative aGame countdown and publish the native HUD bonus notification."""
    n = int(round(float(seconds or 60)))
    if not 1 <= n <= 3600:
        raise ValueError("add_time seconds: 1 .. 3600")
    gs = gamesys(g)
    result = _add_clock(g.ad, gs, n)
    return {**result, "added_seconds": n if result["verified"] else 0,
            "note": "the HUD shows +NN Sec. like a finisher's bonus"}


def hourglasses(g: RE5) -> list[int]:
    su = g.u32(S_UNIT)
    out: list[int] = []
    if not 0x30000000 <= su < 0x40000000:
        return out
    u, n = g.u32(su + UNIT_LINES + LINE_STRIDE * OM_LINE + LINE_FIRST), 0
    while 0x30000000 <= u < 0x40000000 and n < OM_MAX:
        if g.u32(u) == HOURGLASS_VT:
            out.append(u)
        u, n = g.u32(u + UNIT_NEXT), n + 1
    return out


def time_bonus_multiplier(g: RE5, mult) -> dict:
    """Every time bonus x N: the standing hourglasses' own seconds (+0x14A4: 30 / 60) x N, applied once per round
    (a value already scaled is left); the melee finisher's +5 is a code immediate, scaled by the boot patch per
    session (re5_boot_patches) and read back here."""
    k = _mult(mult, 1.0)
    if not 1 <= k <= 20:
        raise ValueError("time_bonus_multiplier: 1 .. 20")
    written = g.orig.setdefault("hourglass_scaled", {})     # unit -> the seconds this op wrote there
    done, seen, wanted = [], 0, 0
    for u in hourglasses(g):
        v = struct.unpack(">h", g.rd(u + HG_SECONDS, 2))[0]
        seen += 1
        if written.get(u) == v:                             # scaled by an earlier call (30 x2 = 60 is not raw 60)
            continue
        if v in HOURGLASS_VALUES:
            wanted += 1
            want = min(32000, int(v * k))
            if g.wr(u + HG_SECONDS, struct.pack(">h", want)) \
                    and struct.unpack(">h", g.rd(u + HG_SECONDS, 2))[0] == want:
                written[u] = want
                done.append((v, want))
    melee = g.u32(MELEE_BONUS_SITE)
    melee_x = (melee & 0xFFFF) / 5.0 if melee >> 16 == MELEE_BONUS_ORIG >> 16 else None
    return {"time_bonus_x": k, "hourglasses": seen, "scaled": len(done), "hourglass_seconds": sorted({w for _, w in done}),
            "melee_bonus_x": melee_x, "verified": len(done) == wanted,   # every raw 30 / 60 read back scaled
            "note": "hourglasses are scaled where they stand (a round's own; rerun each round); the melee +5 s "
                    "comes from the boot patch: melee_bonus_x is what this session's executable says"}


def revert_all(g: RE5) -> dict:
    out = {}
    o = g.orig
    if o.get('qte_assist'):
        from .mercs.titles import re5_qte
        out['instant_qte'] = re5_qte.configure(g, False)['verified']
    if o.get('live_weapon'):
        from .mercs.titles import re5_live_weapon
        out['live_weapon'] = re5_live_weapon.configure(g, on=False)['verified']
    if o.get('rotten_eggs',{}).get('on'):
        from .mercs.titles import re5_eggs
        out['rotten_eggs']=re5_eggs.configure(g,False)['verified']
    if o.get('mine_animation_helper') is not None or o.get('egg_animation_helper') is not None:
        out['item_animation']=maintain_item_animation(g.ad,enabled=False)['verified']
    from .mercs.titles.re5_mines import ORIGINAL_BANKS
    for address in ORIGINAL_BANKS:
        key = f"mine_bank_{address:x}"
        if key in o:
            out[key] = g.wr(address, o[key])
    o.pop("operator_overrides", None)
    if "kill_time" in o:
        o["kill_time"]["on"] = False
        out["kill_time"] = True
    from .mercs.titles import re5_controls
    with re5_controls.LOCK:
        o.pop("weapon_pin", None)
        o.pop('preferred_weapon',None)
        if (o.get("random_weapon_request") or {}).get("state") in ('pending','deferred'):
            o["random_weapon_request"].update(state="rejected", reason="Cancelled by revert all.")
    o["fire_animation_on"] = False
    if o.get("fire_animation_helper") is not None:
        out["fire_animation"] = maintain_fire_animation(g.ad, enabled=False)["verified"]
    if "def" in o:
        out["definitions"] = g.wr(DEF_TABLE, o["def"])
    if "upg" in o:
        out["upgrades"] = g.wr(UPG_TABLE, o["upg"])
    if "fps" in o:
        out["fire_timer"] = g.wr(FIRE_TIMER_FPS, o["fps"])
        o.pop("fps_set", None)
    if "turn" in o:
        p = g.param()
        out["turn"] = all(g.wr(p + k, struct.pack(">f", v)) for k, v in o["turn"].items())
    if "spray" in o:
        o["spray"].update(on=False, template_records={})
        o["spray"].pop("spray_record", None)
        out["infinite_spray"] = True
    if "template" in o:
        out["loadout"] = g.wr(TEMPLATE, o["template"])
    if "health" in o:
        out["health"] = unlimited_health(g, False)["verified"]
    return {"reverted": out, "verified": all(out.values()), "note": "a relaunch of the game is the full revert too"}


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE5 | None = None, **extra) -> dict:
    # Round hooks and UI jobs share table snapshots and retained operator settings.
    with _HEALTH_LOCK:
        return _run(ad, op, multiplier, on, g, **extra)


def _run(ad, op="status", multiplier=None, on=True, g=None, **extra):
    g = g or RE5(ad)
    op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
    op = {"turn": "turn_speed", "aim_turn_speed": "turn_speed", "rotation": "turn_speed", "turnaround": "turn_speed",
          "fire": "fire_rate", "rapid_fire": "fire_rate", "machine_gun": "fire_rate", "ammo": "infinite_ammo",
          "unlimited_ammo": "infinite_ammo", "no_ammo": "infinite_ammo", "damage": "bullet_damage",
          "firepower": "bullet_damage", "powerful_bullets": "bullet_damage", "revert": "revert_all", "reset": "revert_all",
          "off": "revert_all", "address_table": "addresses", "weapons": "loadout", "merc_loadout": "loadout",
          "random_weapons": "loadout", "randomize": "random_cheats", "randomizer": "random_cheats",
          "random": "random_cheats", "unlimited_life": "unlimited_health", "infinite_health": "unlimited_health",
          "infinite_life": "unlimited_health", "time_per_kill": "kill_time", "kill_bonus": "kill_time",
          "add_minute": "add_time", "merc_time": "add_time", "more_time": "add_time", "time_bonus": "time_bonus_multiplier",
          "merc_time_bonus": "time_bonus_multiplier", "auto_first_aid": "infinite_spray", "first_aid": "infinite_spray",
          "first_aid_spray": "infinite_spray", "infinite_first_aid": "infinite_spray",
          "auto_qte": "instant_qte", "qte_assist": "instant_qte"}.get(op, op)
    operator = bool(extra.get("operator"))
    override = None
    if not operator and op in OPERATOR_SETTINGS:
        override = g.orig.get("operator_overrides", {}).get(op)
        if override:
            multiplier, on = override["multiplier"], override["on"]
    res: dict = {"op": op}
    if op == "status":
        pass
    elif op == "mines":
        from .mercs.titles import re5_mines
        only = str(multiplier).lower() == "only" or multiplier == 0
        cfg = re5_mines.configure(2 if only else (multiplier if multiplier is not None else 60), only, on)
        res.update(mine_settings=cfg, verified=True, effective_next_round=True)
        if on:
            res.update(re5_mines.templates(g))
    elif op == "mercs_select":
        from .mercs.titles import re5_ps3 as R
        rotation = R.coverage()
        with rotation.lock:
            selected = rotation.request(extra.get("mode", "reunion"), extra.get("character", R.CHARACTERS[0]),
                                        extra.get("stage", 0))
            request = rotation.status()["selection_request"]
        res.update(verified=True, queued=True, selection=selected, request_id=request["id"],
                   native_start_verified=False, effective_next_round=True,
                   note="Selection saved for the next native menu boundary; current round continues. "
                        "Awaiting the exact mode, character and stage to begin.")
    elif op == 'rotten_egg_only':
        from .mercs.titles import re5_eggs
        res.update(re5_eggs.configure(g,on,multiplier))
        if on:re5_eggs.queue_supply(g.ad)
    elif op == "addresses":
        res.update(game=GAME, addresses={k: {**v, "address": f"0x{v['address']:08X}"} for k, v in ADDRESSES.items()},
                   weapons={f"0x{k:02X}": v for k, v in sorted(WEAPONS.items())})
        return res
    elif op == "turn_speed":
        res.update(turn_speed(g, multiplier if on else 1.0))
    elif op == "fire_rate":
        res.update(fire_rate(g, (multiplier if multiplier is not None else 80.0) if on else 1.0))
    elif op == "infinite_ammo":
        res.update(infinite_ammo(g, on))
    elif op == "unlimited_health":
        res.update(unlimited_health(g, on))
    elif op == "infinite_spray":
        res.update(infinite_spray(g, on))
    elif op == 'instant_qte':
        from .mercs.titles import re5_qte
        res.update(re5_qte.configure(g, on))
    elif op == "bullet_damage":
        res.update(bullet_damage(g, (multiplier if multiplier is not None else 10.0) if on else 1.0))
    elif op == "loadout":
        res.update(loadout(g, extra.get("weapons"), extra.get("seed"), on))
    elif op == "weapon_override":
        res.update(weapon_override(g, extra.get("weapon") if on else None, bool(extra.get("only"))))
    elif op == 'live_weapon':
        from .mercs.titles import re5_live_weapon
        res.update(re5_live_weapon.configure(g, extra.get('weapon'), on))
        if res.get('queued'):
            re5_live_weapon.queue_supply(g.ad)
    elif op == "replace_rockets":
        res.update(replace_rockets(g, extra.get("seed")))
    elif op == "replace_long_guns":
        res.update(replace_long_guns(g, extra.get("seed")))
    elif op in ("random_weapon",'select_weapon'):
        from .mercs.titles import re5_controls
        from .mercs.titles import re5_mines
        mine_cfg=re5_mines.settings()
        deferred=bool(g.orig.get('rotten_eggs',{}).get('on') or mine_cfg['enabled'] and mine_cfg['only'])
        if op=='select_weapon' and not on:
            res.update(re5_controls.clear_preference(g.orig))
        elif op=='select_weapon' and type(extra.get('weapon')) is not int:
            raise ValueError('select_weapon requires an available native weapon ID')
        else:
            res.update(re5_controls.request(g.orig,weapon=extra.get('weapon') if op=='select_weapon' else None,
                                           deferred=deferred))
    elif op == "random_cheats":
        res.update(random_cheats(g, extra.get("seed")))
    elif op == "kill_time":
        seconds = multiplier if override and not operator and multiplier is not None else extra.get("seconds")
        if seconds is None and multiplier is not None:
            seconds = multiplier                      # the panel and the retained override carry the seconds as the value
        res.update(kill_time(g, on, seconds, None if override and multiplier is not None else extra.get("seconds_max")))
        # the retained operator override: a fixed value carries its seconds; a range (the default) only the on / off,
        # so a later playing_ops call retains the operator's seconds and switch
        multiplier = res["seconds"] if res["seconds_max"] == res["seconds"] else None
    elif op == "add_time":
        res.update(add_time(g, extra.get("seconds") or multiplier or 60))
    elif op == "time_bonus_multiplier":
        res.update(time_bonus_multiplier(g, multiplier if multiplier is not None else extra.get("x", 1)))
    elif op == "revert_all":
        res.update(revert_all(g))
    else:
        raise ValueError("op: status | turn_speed | fire_rate | infinite_ammo | unlimited_health | infinite_spray | bullet_damage | loadout | "
                         "replace_rockets | random_cheats | kill_time | add_time | time_bonus_multiplier | revert_all | addresses")
    if operator and op in OPERATOR_SETTINGS and res.get("verified"):
        g.orig.setdefault("operator_overrides", {})[op] = {"multiplier": multiplier, "on": bool(on)}
    res["status"] = g.status()
    return res


class RE5ModsIn(BaseModel):
    session_id: str
    op: str = "status"            # status | turn_speed | fire_rate | infinite_ammo | unlimited_health | bullet_damage | revert_all | addresses
    multiplier: str | float | None = None   # turn_speed (2; "max" = 10) / fire_rate (80) / bullet_damage (10); 1 = the game's
    on: bool = True               # infinite_ammo / unlimited_health on/off; multiplier off restores the game's values
    mode: str = "reunion"
    character: str = "Chris (Heavy Metal)"
    stage: int = 0
    weapon: int | None = None      # existing loaded quick-slot gun; selection is retained for this session
    only: bool = False             # weapon_override: the chosen weapon in every gun slot (e.g. longbow-only rounds)


class RE5ModsOut(BaseModel):
    result: dict


@tool("re5_mods", "1.0", RE5ModsIn, RE5ModsOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      timeout_s=120)
def re5_mods(inp: RE5ModsIn, ctx):
    """Resident Evil 5 Gold (PS3, RPCS3) live mods, each write read back: turn_speed multiplier=N (the stick turns N
    times faster, aimed and not; "max" = 10), fire_rate multiplier=N (firing tables and timer scaling; 80 is not
    measured shots per second; guarded magnum animation capped at8x), infinite_ammo on= (no rounds spent, the HUD's infinity sign), unlimited_health on=
    (living HP refill and signature-verified Muteki incoming-hit immunity each snapshot), bullet_damage multiplier=N,
    revert_all, status, addresses. The Mercenaries playbook applies the profile's package at round start."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    if g.get("platform") != "ps3":
        raise Unsupported(f"re5_mods: Resident Evil 5 on PS3 (RPCS3); this session is {g.get('title')} ({g.get('platform')})")
    return {"result": run(ad, inp.op, inp.multiplier, inp.on, operator=True,
                           mode=inp.mode, character=inp.character, stage=inp.stage,weapon=inp.weapon,only=inp.only)}
