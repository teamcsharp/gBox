"""`re5_mods`: Resident Evil 5 Gold Edition (PS3 BLUS30491 app 01.01, RPCS3) live gameplay mods: data writes into the
running game, each read back, the originals kept and restored by the same op with multiplier=1 / on=false.
Register with:  from . import re5_mods_tool  # noqa: F401

ops (session_id = a running RE5 session on the Spark; in the worker the Mercenaries playbook applies the profile's
package through run() at round start, gbox/mercs_bot.py):
  status                          what is on: turn / fire / damage multipliers, the no-ammo flag count, the weapon in hand
  turn_speed multiplier=N         the stick turns the player N times faster, aimed and not (2 = default, "max" = 10)
  fire_rate multiplier=N          scales firing tables and the re-fire timer (80); measured shot rate may differ
  infinite_ammo on=true|false     no weapon spends rounds (the HUD shows the infinity sign; the Gatling's own flag)
  unlimited_health on=true|false full living HP each snapshot, plus exact-signature-verified Muteki hit immunity
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
TEMPLATE, TEMPLATE_BLOCK, TEMPLATE_BLOCKS, TEMPLATE_REC = 0x01730048, 0x210, 30, 0x2C   # the first record's id word
TEMPLATE_SIGNATURE = (0x84, 0x124)                               # block 0's knife record: id 0x124
POWERFUL = {0x11B: "S&W M500", 0x11A: "Lightning Hawk", 0x119: "Hydra", 0x115: "Gatling gun", 0x10D: "rocket launcher",
            0x11C: "H&K PSG-1", 0x11D: "AK-74", 0x116: "Benelli M3", 0x10C: "grenade launcher", 0x120: "Dragunov SVD",
            0x10B: "S&W M29"}
MAGNUMS = (0x10B, 0x11A, 0x11B)
KNIFE_IDS = {0x101, 0x10E, 0x114, 0x123, 0x124, 0x100}
ORIG: dict = {}                                 # id(adapter) -> the tables and values as the game had them

ADDRESSES = {
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
        st["infinite_ammo"] = all(flags[w] == 1 for w in WEAPONS if w not in KNIVES)
        dmg = struct.unpack(">f", self.rd(UPG_TABLE + 0x02 * UPG_STRIDE + UPG_GROUP0 + G_DAMAGE * UPG_GROUP + 4, 4))[0]
        st["bullet_damage_x"] = round(dmg / 150.0, 2)                 # the M92F's level-0 firepower is 150
        inv = self.inventory()
        st["in_hand"] = next((x for x in inv if x["in_hand"]), None)
        st["inventory"] = inv
        st["unlimited_health"] = bool(self.orig.get("health", {}).get("on"))
        st["health_maintenance"] = self.orig.get("health", {}).get("last")
        st["hit_immunity"] = bool((st["health_maintenance"] or {}).get("hit_immunity"))
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
    state = g.orig.setdefault("health", {})
    result = {"unlimited_health": True, "active": False, "verified": False, "hit_immunity": False}
    pl = _health_player(g)
    if not pl or (snap is not None and (snap.get("player") or {}).get("ptr") != pl):
        return {**result, "reason": "waiting for the current player"}
    hp, maximum = struct.unpack(">hh", g.rd(pl + P_HP, 4))
    if not 0 < hp <= maximum <= 32767:
        return {**result, "reason": "waiting for a living player with valid health", "hp": hp, "hp_max": maximum}
    if state.get("player") != pl or maximum != state.get("boosted_max"):
        state.update(player=pl, original_max=maximum, boosted_max=max(maximum, HEALTH_MAX))
    target = state["boosted_max"]
    if _health_player(g) != pl:              # A respawn must never send a write to the previous allocation.
        return {**result, "reason": "player changed during health check"}
    wanted = struct.pack(">hh", target, target)
    verified = (hp == maximum == target) or g.wr(pl + P_HP, wanted)
    if verified and snap is not None:
        snap["player"].update(hp=target, hp_max=target)
    return {**result, "active": verified, "verified": verified, "hp": target if verified else hp,
            "hp_max": target if verified else maximum, "refilled": verified and hp != target,
            **(_hit_immunity(g, pl, True) if verified else {})}


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
    _, m92 = _upg_group(u, 0x02, G_FIRE)
    return {"fire_rate_x": k, "verified": ok, "fire_timer_fps": round(g.f32(FIRE_TIMER_FPS), 2),
            "m92f_frames_between_shots": round(m92[0], 4),
            "note": "firing-speed table / N and fire-action timer x N; held fire still depends on weapon animation "
                    "and update gates, so N is not measured shots per second; 1 restores the game's values"}


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
    out = []
    for b in range(TEMPLATE_BLOCKS):
        for r in range(12):
            off = b * TEMPLATE_BLOCK + r * TEMPLATE_REC
            w = struct.unpack_from(">11I", t, off)
            if w[0] and w[0] != 0xFFFFFFFF and w[2] == w[3] == w[4] == 0xFFFFFFFF:
                out.append((off, w[0], w[1], w[5], w[6], w[7]))
    return out


def loadout(g: RE5, weapons=None, seed=None, on: bool = True) -> dict:
    """Every character's Mercenaries loadout template: each gun (table 1, not the knives) becomes one of the powerful
    campaign weapons, drawn at random per record without repeats inside a block (seed for a repeatable draw); the
    packed upgrade levels are reset to 0 so no level indexes past the new weapon's table. on=false restores."""
    import random
    if g.u32(TEMPLATE + TEMPLATE_SIGNATURE[0]) != TEMPLATE_SIGNATURE[1] and "template" not in g.orig:
        raise RuntimeError("the loadout templates are not where this build keeps them; not writing")
    t0 = g.keep("template", lambda: g.rd(TEMPLATE, TEMPLATE_BLOCKS * TEMPLATE_BLOCK))
    if not on:
        return {"loadout": "the game's", "verified": g.wr(TEMPLATE, t0)}
    pool = [int(str(w), 0) if isinstance(w, str) and str(w).startswith("0x") else w for w in (weapons or [])]
    pool = [w for w in pool if w in POWERFUL] or list(POWERFUL)
    rng = random.Random(seed)
    t = bytearray(t0)
    picks: dict = {}
    for off, idw, _, _, in_hand, _ in template_records(t0):
        if idw >> 8 != 1 or idw in KNIFE_IDS:
            continue
        block = off // TEMPLATE_BLOCK
        used = picks.setdefault(block, [])
        choice = rng.choice([w for w in pool if w not in used] or pool)
        if choice == 0x10D:
            choice = rng.choice([w for w in MAGNUMS if w not in used] or MAGNUMS)
        used.append(choice)
        struct.pack_into(">I", t, off, choice)
        struct.pack_into(">I", t, off + 7 * 4, 0)
    ok = g.wr(TEMPLATE, bytes(t))
    named = {b: [POWERFUL[w] for w in ws] for b, ws in picks.items()}
    return {"loadout": "random powerful campaign weapons", "verified": ok, "blocks": len(picks),
            "barry": named.get(24), "chris_heavy_metal": named.get(18), "picks": named,
            "note": "takes effect at the next round start (the game copies the template into the inventory then)"}


def replace_rockets(g: RE5, seed=None) -> dict:
    """Replace only rocket entries in live spawn templates; the game constructs the magnum next round.

    This deliberately does not relabel an already-created rocket weapon object as a magnum.
    It preserves grid, in-hand flags, unrelated records and other active loadout changes.
    """
    import random
    if g.u32(TEMPLATE + TEMPLATE_SIGNATURE[0]) != TEMPLATE_SIGNATURE[1]:
        raise RuntimeError("rocket replacement: loadout template signature differs")
    current = g.rd(TEMPLATE, TEMPLATE_BLOCKS * TEMPLATE_BLOCK)
    g.keep("template", lambda: current)
    rng, replaced, ok = random.Random(seed), [], True
    for off, idw, _, pos, hand, _ in template_records(current):
        if idw != 0x10D:
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
    return {"verified": ok, "rocket_replacements": replaced, "effective_next_round": True,
            "note": "spawn templates only; equipped weapon readback is required after the next round starts"}


def random_cheats(g: RE5, seed=None) -> dict:
    """The operator's per-round randomizer: fire_rate x80 always; turn x2 or x3; bullet damage x1 / x3 / x10;
    infinite ammo on; the loadout re-drawn. Returns what was picked as "telemetry" (the playbook shows it)."""
    import random
    rng = random.Random(seed)
    picked = {"fire_rate_x": 80.0, "turn_speed_x": rng.choice([2.0, 3.0]), "bullet_damage_x": rng.choice([1.0, 3.0, 10.0]),
              "infinite_ammo": True, "loadout": rng.random() < 0.75}
    out: dict = {}
    out["fire_rate"] = fire_rate(g, picked["fire_rate_x"])["verified"]
    out["turn_speed"] = turn_speed(g, picked["turn_speed_x"])["verified"]
    out["bullet_damage"] = bullet_damage(g, picked["bullet_damage_x"])["verified"]
    out["infinite_ammo"] = infinite_ammo(g, True)["verified"]
    if picked["loadout"]:
        lo = loadout(g, seed=rng.random())
        out["loadout"] = lo["verified"]
        picked["loadout_barry"] = lo.get("barry")
    else:
        out["loadout"] = loadout(g, on=False)["verified"]
    out["rocket_replacement"] = replace_rockets(g, rng.random())["verified"]
    return {"telemetry": picked, "verified": all(out.values()), "applied": out}


def revert_all(g: RE5) -> dict:
    out = {}
    o = g.orig
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
    if "template" in o:
        out["loadout"] = g.wr(TEMPLATE, o["template"])
    if "health" in o:
        out["health"] = unlimited_health(g, False)["verified"]
    return {"reverted": out, "verified": all(out.values()), "note": "a relaunch of the game is the full revert too"}


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE5 | None = None, **extra) -> dict:
    g = g or RE5(ad)
    op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
    op = {"turn": "turn_speed", "aim_turn_speed": "turn_speed", "rotation": "turn_speed", "turnaround": "turn_speed",
          "fire": "fire_rate", "rapid_fire": "fire_rate", "machine_gun": "fire_rate", "ammo": "infinite_ammo",
          "unlimited_ammo": "infinite_ammo", "no_ammo": "infinite_ammo", "damage": "bullet_damage",
          "firepower": "bullet_damage", "powerful_bullets": "bullet_damage", "revert": "revert_all", "reset": "revert_all",
          "off": "revert_all", "address_table": "addresses", "weapons": "loadout", "merc_loadout": "loadout",
          "random_weapons": "loadout", "randomize": "random_cheats", "randomizer": "random_cheats",
          "random": "random_cheats", "unlimited_life": "unlimited_health", "infinite_health": "unlimited_health",
          "infinite_life": "unlimited_health"}.get(op, op)
    res: dict = {"op": op}
    if op == "status":
        pass
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
    elif op == "bullet_damage":
        res.update(bullet_damage(g, (multiplier if multiplier is not None else 10.0) if on else 1.0))
    elif op == "loadout":
        res.update(loadout(g, extra.get("weapons"), extra.get("seed"), on))
    elif op == "replace_rockets":
        res.update(replace_rockets(g, extra.get("seed")))
    elif op == "random_cheats":
        res.update(random_cheats(g, extra.get("seed")))
    elif op == "revert_all":
        res.update(revert_all(g))
    else:
        raise ValueError("op: status | turn_speed | fire_rate | infinite_ammo | unlimited_health | bullet_damage | loadout | replace_rockets | random_cheats | "
                         "revert_all | addresses")
    res["status"] = g.status()
    return res


class RE5ModsIn(BaseModel):
    session_id: str
    op: str = "status"            # status | turn_speed | fire_rate | infinite_ammo | unlimited_health | bullet_damage | revert_all | addresses
    multiplier: str | float | None = None   # turn_speed (2; "max" = 10) / fire_rate (80) / bullet_damage (10); 1 = the game's
    on: bool = True               # infinite_ammo / unlimited_health on/off; multiplier off restores the game's values


class RE5ModsOut(BaseModel):
    result: dict


@tool("re5_mods", "1.0", RE5ModsIn, RE5ModsOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      timeout_s=120)
def re5_mods(inp: RE5ModsIn, ctx):
    """Resident Evil 5 Gold (PS3, RPCS3) live mods, each write read back: turn_speed multiplier=N (the stick turns N
    times faster, aimed and not; "max" = 10), fire_rate multiplier=N (every gun N times faster, a handgun held fires
    like a machine gun; 80), infinite_ammo on= (no rounds spent, the HUD's infinity sign), unlimited_health on=
    (living HP refill and signature-verified Muteki incoming-hit immunity each snapshot), bullet_damage multiplier=N,
    revert_all, status, addresses. The Mercenaries playbook applies the profile's package at round start."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    if g.get("platform") != "ps3":
        raise Unsupported(f"re5_mods: Resident Evil 5 on PS3 (RPCS3); this session is {g.get('title')} ({g.get('platform')})")
    return {"result": run(ad, inp.op, inp.multiplier, inp.on)}
