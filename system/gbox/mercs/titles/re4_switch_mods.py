"""Resident Evil 4 (Nintendo Switch, title 010099A00BC1E000 v1.0.2) live Mercenaries mods on Eden / Citron: data
writes into the running game through the Switch adapter (write_memory reads every write back). RAM only: a relaunch
is the full revert. A bot module (gbox.hot_reload reloads it in place; ORIG survives).

The RE4 playbook (gbox/re4switch_bot.py) calls maintain(ad, snap) on every RAM snapshot of a round, and the live
sidebar (gbox/merc_live_controls.py, through the re5_mods tool) sets these ops:

  status                      what is on, the Ganados' health, the clock's address and value
  enemy_health multiplier=x   every living Ganado's health kept at most x of its maximum (0.05..1; 1 = the game's own):
                              unit +0x3c2 (u16 health) lowered to ceil(+0x3c4 x x) when it reads higher, re-read just
                              before the write and read back after it; only a unit of a measured Ganado class
                              (re4_switch.ENEMY_CLASSES) whose maximum is 1..UNIT_HP_MAX, never a zero (a dead one stays
                              dead), never a raise. Measured fields: re4_switch U_HP / U_HP_MAX (Ganados 400/400 and
                              3500/3500 read live 2026-11-10); the damage routine FUN_004cd1c0 subtracts from +0x3c2.
  one_hit on=true             the same with a floor of 1: every Ganado dies to the first hit
  add_time seconds=N          the round clock (the f32 re4_switch.ClockFinder found: snap["clock_addr"]) moved by N
                              (-3600..3600), never under 1 s; written, read back, and confirmed on the next snapshot (a
                              clock whose master copy rewrites it is reported as not holding)
  set_time seconds=N          the clock set to 1..CLOCK_MAX_S
  kill_time on=true seconds=S +S on the clock for every new kill the census counts (a Ganado whose health fell to 0)
                              while a round is playing

The player's life is not in his unit on Switch (re4_switch PLAYER_HP_IN_UNIT): unlimited health waits for that field
(the round probe looks for it), and ammo for the inventory's; both answer "not mapped yet" until then.
"""
from __future__ import annotations

import json
import math
import struct
import threading
import time
from pathlib import Path

from . import re4_switch as D
from . import re4_weapons as W

GAME = "010099A00BC1E000"
ENEMY_HEALTH_MIN = 0.05
CLOCK_MAX_S = 3600.0
KILL_TIME_S = 3.0
KILL_TIME_MAX_S = 30.0
CLOCK_HOLD_TOL = 1.5                    # the next read within this of what was written (the clock runs on meanwhile)

# The firepower-per-level table (module data, rows of 7 f32: levels 1-5, a 6th, the exclusive), read from the
# decrypted executable 2026-11-10 (work/re4-nsp/main.bin, data segment file 0xae2100 -> mem 0xae2000). Rows named by
# their stats (inferred, RE4's published values): the first value is checked before any write.
FIREPOWER_ROWS = {"punisher": (0xAF0EA8, 0.9), "handgun": (0xAF0EC4, 1.0), "red9": (0xAF0EE0, 1.6),
                  "blacktail": (0xAF0EFC, 1.6), "broken_butterfly": (0xAF0F18, 13.0), "killer7": (0xAF0F34, 25.0),
                  "shotgun": (0xAF0F50, 4.0), "striker": (0xAF0F6C, 6.0), "rifle": (0xAF0F88, 4.0),
                  "semi_auto_rifle": (0xAF0FA4, 7.0), "tmp": (0xAF0FC0, 0.4), "handcannon": (0xAF1030, 30.0),
                  "riot_gun": (0xAF1228, 5.0)}
ROW_N, POWER_MAX_X = 7, 20.0
AIM_FRESH_S = 0.35                     # an aim request (re4_switch.AIM_REQUEST) older than this is not written
FIRE_RATE_MAX_X = 20.0
FIRE_GAP_MIN_S = 0.05                  # the fight's trigger taps never closer than this (re4_switch.FIRE_GAP_S)
RIFLE_TIMER_FLOOR = 1.0                # the scoped rifles' shot timer (frames) never under one frame

ORIG: dict = {}                         # id(adapter) -> this boot's settings
_LOCK = threading.RLock()
RELOAD_KEEP = ("ORIG", "_LOCK")


class Mem:
    """The session's guest memory for re4_switch's readers: rd() and the adapter (its guest rows find main)."""

    def __init__(self, ad):
        self.adapter = ad

    def rd(self, a: int, n: int) -> bytes:
        return self.adapter.read_memory(a, n)


# The operator's settings outlive a session (MercMode plays one RE4 round per boot): every setter saves them here
# and a new session's state starts from them, the way RE5's saved mods profile is applied each round.
SETTINGS_FILE = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "re4-mods.json"
SAVED_KEYS = ("enemy_health", "one_hit", "kill_time", "unlimited_health", "weapon_power", "max_level", "aim_lock",
              "fire_rate", "infinite_ammo", "random_weapon", "loadout_weapon")


def _load_saved() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k in SAVED_KEYS} if isinstance(data, dict) else {}


def _save(st: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: st[k] for k in SAVED_KEYS if k in st}, indent=1), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    except OSError:
        pass


def _state(ad) -> dict:
    st = ORIG.get(id(ad))
    if st is None:
        st = ORIG[id(ad)] = _load_saved()
    return st


def _num(value, lo: float, hi: float, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} needs a number") from None
    if not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{name} must be within {lo:g}..{hi:g}")
    return v


# --- the Ganados' health -----------------------------------------------------------------------------------------
def _cap_for(e: dict, frac: float) -> int | None:
    """The health this Ganado is kept at or under, or None to leave him alone."""
    hp, top = e.get("hp"), e.get("hp_max")
    if e.get("class") not in D.ENEMY_CLASSES or not isinstance(hp, int) or not isinstance(top, int):
        return None
    if hp <= 0 or not 1 <= top <= D.UNIT_HP_MAX:
        return None
    return max(1, math.ceil(top * frac))


def _cap_health(ad, enemies, frac: float) -> int:
    """Each living Ganado above frac x his maximum lowered to it (re-read before, read back after). Returns how many."""
    n = 0
    for e in enemies or ():
        cap = _cap_for(e, frac)
        if cap is None or e["hp"] <= cap or not isinstance(e.get("ptr"), int):
            continue
        addr = e["ptr"] + D.U_HP
        try:
            now = struct.unpack("<H", bytes(ad.read_memory(addr, 2)))[0]
            if now <= cap or now > D.UNIT_HP_MAX:
                continue                                   # he took damage meanwhile, or the slot is not his any more
            ad.write_memory(addr, struct.pack("<H", cap))
            back = struct.unpack("<H", bytes(ad.read_memory(addr, 2)))[0]
        except (ValueError, OSError, RuntimeError, struct.error):
            continue
        if back <= cap:                                     # a hit landing between the write and the read is fine
            n += 1
    return n


def enemy_health(ad, multiplier, snap: dict | None = None) -> dict:
    frac = _num(multiplier, ENEMY_HEALTH_MIN, 1.0, "enemy_health")
    st = _state(ad)
    st["enemy_health"] = frac
    if frac >= 1.0:
        st.pop("enemy_health", None)
    _save(st)
    capped = _cap_health(ad, (snap or {}).get("enemies"), frac) if frac < 1.0 and snap else 0
    return {"enemy_health_x": frac, "verified": True, "capped": capped,
            "note": "every living Ganado's health kept at most this share of his maximum (lowered only, read back)"}


def _keep_life(ad, snap) -> int:
    """Unlimited life: the player's life (re4_switch.PLAYER_LIFE) back at its maximum when it fell. 1 = written."""
    p = (snap or {}).get("player") or {}
    hp, top = p.get("hp"), p.get("hp_max")
    base = (snap or {}).get("module_base")
    if D.PLAYER_LIFE is None or not isinstance(base, int) or not isinstance(hp, int) or not isinstance(top, int):
        return 0
    if hp <= 0 or hp >= top:
        return 0                                       # dead (the round's end is the game's), or full
    addr = base + D.PLAYER_LIFE
    try:
        now = struct.unpack("<H", bytes(ad.read_memory(addr, 2)))[0]
        if now <= 0 or now >= top:
            return 0
        ad.write_memory(addr, struct.pack("<H", top))
        return 1 if struct.unpack("<H", bytes(ad.read_memory(addr, 2)))[0] == top else 0
    except (ValueError, OSError, RuntimeError, struct.error):
        return 0


def unlimited_health(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["unlimited_health"] = bool(on)
    _save(st)
    kept = _keep_life(ad, snap) if on else 0
    return {"unlimited_health": bool(on), "verified": True, "kept": kept,
            "note": "the player's life put back to its maximum whenever it falls (re4_switch.PLAYER_LIFE)"}


def _rows(ad, base: int, st: dict) -> dict:
    """{name: (address, the boot's own 7 values)} of the firepower rows whose first value is the expected one
    (read once a boot and kept: a scaled row is never taken for the original)."""
    orig = st.setdefault("fp_orig", {})
    out = {}
    for name, (off, first) in FIREPOWER_ROWS.items():
        if name not in orig:
            try:
                vals = struct.unpack("<7f", bytes(ad.read_memory(base + off, 4 * ROW_N)))
            except (ValueError, OSError, struct.error):
                continue
            if abs(vals[0] - first) > 1e-3 or any(not math.isfinite(v) or v <= 0 for v in vals):
                continue                               # not the row this build was measured with
            orig[name] = vals
        out[name] = (base + off, orig[name])
    return out


def _apply_power(ad, base: int, st: dict) -> int:
    """Every known firepower row written as (its max if max_level else its own) x weapon_power, read back."""
    mult = float(st.get("weapon_power", 1.0))
    top = bool(st.get("max_level"))
    n = 0
    for name, (addr, vals) in _rows(ad, base, st).items():
        want = tuple(((max(vals) if top else v) * mult) for v in vals)
        try:
            ad.write_memory(addr, struct.pack("<7f", *want))
            back = struct.unpack("<7f", bytes(ad.read_memory(addr, 4 * ROW_N)))
        except (ValueError, OSError, RuntimeError, struct.error):
            continue
        n += all(abs(a - b) < 1e-3 * max(1.0, abs(a)) for a, b in zip(back, want))
    return n


def weapon_power(ad, multiplier, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["weapon_power"] = _num(multiplier, 1.0, POWER_MAX_X, "weapon_power")
    _save(st)
    base = (snap or {}).get("module_base")
    rows = _apply_power(ad, base, st) if isinstance(base, int) else 0
    st.pop("fp_applied_base", None) if not rows else None
    return {"weapon_power_x": st["weapon_power"], "verified": True, "rows": rows,
            "note": "every weapon's firepower table x this (RAM; a relaunch restores the game's)"}


def max_level(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["max_level"] = bool(on)
    _save(st)
    base = (snap or {}).get("module_base")
    rows = _apply_power(ad, base, st) if isinstance(base, int) else 0
    return {"max_level": bool(on), "verified": True, "rows": rows,
            "note": "every weapon fires at its top (exclusive) firepower at any upgrade level"}


def aim_lock(ad, on: bool) -> dict:
    st = _state(ad)
    st["aim_lock"] = bool(on)
    _save(st)
    return {"aim_lock": bool(on), "verified": True,
            "note": "the player's facing written onto the bot's target each snapshot (re4_switch.AIM_REQUEST)"}


def _aim(ad, snap: dict) -> int:
    """The bot's aim request (re4_switch.AIM_REQUEST) written to the player's facing (unit + U_YAW), read back."""
    req = D.AIM_REQUEST
    p = (snap or {}).get("player") or {}
    if not req or req.get("ptr") != p.get("ptr") or time.monotonic() - req.get("at", -1e9) > AIM_FRESH_S:
        return 0
    addr = p["ptr"] + D.U_YAW
    try:
        ad.write_memory(addr, struct.pack("<f", req["yaw"]))
        back = struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0]
    except (ValueError, OSError, RuntimeError, struct.error):
        return 0
    return 1 if abs(back - req["yaw"]) < 1e-3 else 0


# --- fire rate, infinite ammo, a random max-level campaign weapon (re4_weapons: the static analysis) ------------
def _table(ad, base: int, st: dict, key: str, off: int, n: int, fmt: str):
    """A table's boot-original values (read once a boot, kept), or None when it cannot be read."""
    orig = st.setdefault("tbl_orig", {})
    if key not in orig:
        size = struct.calcsize("<" + fmt) * n
        try:
            orig[key] = struct.unpack("<" + fmt * n, bytes(ad.read_memory(base + off, size)))
        except (ValueError, OSError, struct.error):
            return None
    return orig[key]


def _write_table(ad, base: int, off: int, fmt: str, values) -> bool:
    data = struct.pack("<" + fmt * len(values), *values)
    try:
        ad.write_memory(base + off, data)
        return bytes(ad.read_memory(base + off, len(data))) == data
    except (ValueError, OSError, RuntimeError, struct.error):
        return False


def _apply_fire_rate(ad, base: int, st: dict) -> int:
    """Every class's frames between shots (re4_weapons.FIRE_RATE_TBL) / fire_rate, never under the gate's floor; the
    scoped rifles' timer too; the fight's trigger taps paced to match. Returns the tables written."""
    mult = float(st.get("fire_rate", 1.0))
    n = 0
    fr = _table(ad, base, st, "fire", W.FIRE_RATE_TBL, W.N_CLASSES * W.FIRE_RATE_COLS, "f")
    if fr is not None:
        want = [W.rapid_fire_value(v, mult) if v > 0 else v for v in fr] if mult > 1 else list(fr)
        n += _write_table(ad, base, W.FIRE_RATE_TBL, "f", want)
    rifle = _table(ad, base, st, "rifle", W.RIFLE_FIRE_TBL, 2 * W.FIRE_RATE_COLS, "f")
    if rifle is not None:
        want = [max(RIFLE_TIMER_FLOOR, v / mult) if v > 0 else v for v in rifle] if mult > 1 else list(rifle)
        n += _write_table(ad, base, W.RIFLE_FIRE_TBL, "f", want)
    gap0 = st.setdefault("fire_gap_orig", D.FIRE_GAP_S)
    D.FIRE_GAP_S = max(FIRE_GAP_MIN_S, gap0 / mult)
    return n


def fire_rate(ad, multiplier, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["fire_rate"] = _num(multiplier, 1.0, FIRE_RATE_MAX_X, "fire_rate")
    _save(st)
    base = (snap or {}).get("module_base")
    n = _apply_fire_rate(ad, base, st) if isinstance(base, int) else 0
    return {"fire_rate_x": st["fire_rate"], "verified": True, "tables": n, "trigger_gap_s": round(D.FIRE_GAP_S, 3),
            "note": "every weapon's frames between shots / this (never under the shot gate's 3-frame floor)"}


def _apply_ammo(ad, base: int, st: dict) -> int:
    """Infinite ammo: every weapon row's capacity entries 0x8000 (use_ammo never consumes; re4_weapons.CAP_INFINITE),
    the boot's own back when off. Returns the rows written."""
    raw = _table(ad, base, st, "weapons", W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ, "B")
    if raw is None:
        return 0
    blob = bytearray(bytes(raw))
    if st.get("infinite_ammo"):
        for k in range(W.WEAPON_N):
            o = k * W.WEAPON_SZ + 8
            caps = struct.unpack_from("<7H", blob, o)
            struct.pack_into("<7H", blob, o, *[(W.CAP_INFINITE if c else 0) for c in caps])
    return W.WEAPON_N if _write_table(ad, base, W.WEAPON_TBL, "B", list(blob)) else 0


def infinite_ammo(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["infinite_ammo"] = bool(on)
    _save(st)
    base = (snap or {}).get("module_base")
    n = _apply_ammo(ad, base, st) if isinstance(base, int) else 0
    return {"infinite_ammo": bool(on), "verified": True, "rows": n,
            "note": "every weapon's magazine never empties (the game's own infinite-capacity value)"}


def _give_weapon(ad, base: int, st: dict, rng) -> dict | None:
    """A random high-powered campaign weapon (re4_weapons.HIGH_POWER) at max level, full, into the equipped slot:
    the item's id, levels and rounds, the item manager's held id, the game state's class / variant / level nibbles."""
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    r = W.Reader(rd, base)
    try:
        held = r.equipped()
        rows = W.decode_weapon_table(rd(base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
        g = r.game_obj()
    except (ValueError, OSError, struct.error):
        return None
    if held is None or g != base + W.GAME_OBJ:
        return None
    picks = [i for i in W.HIGH_POWER if i in rows and W.max_levels(i) is not None and i != held["id"]]
    if not picks:
        return None
    iid = rng.choice(picks)
    row, lv = rows[iid], W.max_levels(iid)
    cap = row["capacity"][lv["capacity"]] or max(row["capacity"])
    loaded = 99 if cap in (0, W.CAP_INFINITE) else min(cap, 0x1FFF)
    item = held["addr"]
    try:
        ad.write_memory(item, struct.pack("<H", iid))
        ad.write_memory(item + 6, struct.pack("<HH", lv["packed"], loaded << 3))
        ad.write_memory(base + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack("<H", iid))
        ad.write_memory(g + W.G_CLASS, bytes([row["class"], row["variant"], 0, lv["firepower"], lv["firing_speed"],
                                             lv["capacity"]]))
        ad.write_memory(g + W.G_RELOAD, bytes([lv["reload"]]))
        back = W.decode_item(rd(item, W.ITEM_SZ), item)
    except (ValueError, OSError, RuntimeError, struct.error):
        return None
    return {"id": iid, "name": W.name(iid), "was": held["name"], "loaded": back["loaded"],
            "verified": back["id"] == iid}


def _patch_loadout(ad, base: int, picks: dict) -> dict:
    """The Mercenaries loadout's weapon / level immediates rewritten (re4_weapons.LOADOUT_SITES): picks {character:
    [weapon id per site]} (None keeps a site's own). Each site is checked against its original instruction (this
    build) or the one written last before it is written; read back. Returns {character: [ids written]}."""
    done: dict = {}
    for ch, ids in picks.items():
        sites = W.LOADOUT_SITES.get(ch)
        if not sites:
            continue
        for k, (wsite, lsite) in enumerate(zip(sites["weapons"], sites["levels"])):
            want = ids[k] if k < len(ids) else None
            off, rd, orig = wsite
            iid = orig if want is None else want
            lv = W.max_levels(iid) if want is not None else None
            writes = [(off, rd, orig, iid)]
            if lsite is not None:
                loff, lrd, lorig = lsite
                writes.append((loff, lrd, lorig, lv["packed"] if lv else lorig))
            ok = True
            for o, r_, orig_imm, imm in writes:
                try:
                    cur = struct.unpack("<I", bytes(ad.read_memory(base + o, 4)))[0]
                    got = W.movz_imm(cur)
                    if got is None or got[0] != r_:
                        ok = False                       # not this build's instruction: never patched
                        break
                    word = struct.pack("<I", W.movz_w(r_, imm))
                    ad.write_memory(base + o, word)
                    ok &= bytes(ad.read_memory(base + o, 4)) == word
                except (ValueError, OSError, RuntimeError, struct.error):
                    ok = False
                    break
            if ok:
                done.setdefault(ch, []).append(iid)
    return done


def _draw_loadouts(rng, fixed: int | None = None) -> dict:
    """{character: [weapon id per site]}: the fixed pick in the equipped slot, else random high-powered campaign
    weapons (no repeat within a character)."""
    out = {}
    for ch, sites in W.LOADOUT_SITES.items():
        pool = [i for i in W.HIGH_POWER if W.max_levels(i) is not None]
        rng.shuffle(pool)
        ids = pool[:len(sites["weapons"])]
        if fixed is not None:
            ids[0] = fixed
        out[ch] = ids
    return out


def loadout_weapon(ad, weapon, snap: dict | None = None) -> dict:
    """Every character's equipped gun from the next round: this campaign weapon at max level (RE5's weapon_override).
    None / 0 puts the game's own loadouts back."""
    st = _state(ad)
    base = (snap or {}).get("module_base")
    if not isinstance(base, int):
        return {"verified": False, "reason": "RE4 is not in memory yet"}
    iid = int(weapon) if weapon else None
    if iid is not None and W.max_levels(iid) is None:
        return {"verified": False, "reason": f"no max-level row for weapon {iid:#x} ({W.name(iid)})"}
    picks = {ch: [iid] if iid is not None else [None, None] for ch in W.LOADOUT_SITES}
    done = _patch_loadout(ad, base, picks)
    st["loadout_weapon"] = iid
    _save(st)
    return {"verified": bool(done), "weapon": W.name(iid) if iid else "the game's own", "characters": len(done),
            "note": "from the next round: every character starts with it, equipped, at max level"}


def random_weapon(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["random_weapon"] = bool(on)
    _save(st)
    st.pop("weapon_given_round", None)                 # a fresh pick on the next snapshot of a round
    st.pop("loadout_drawn", None)
    return {"random_weapon": bool(on), "verified": True,
            "note": "a random max-level high-powered campaign weapon put in his hand each round"}


def one_hit(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["one_hit"] = bool(on)
    _save(st)
    capped = _cap_health(ad, (snap or {}).get("enemies"), 0.0) if on and snap else 0
    return {"one_hit": bool(on), "verified": True, "capped": capped,
            "note": "every living Ganado at 1 health: the first hit kills"}


# --- the clock ----------------------------------------------------------------------------------------------------
def _clock(ad, snap: dict | None) -> tuple[int, float] | None:
    addr = (snap or {}).get("clock_addr")
    if not isinstance(addr, int):
        return None
    try:
        v = struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0]
    except (ValueError, OSError, struct.error):
        return None
    return (addr, v) if math.isfinite(v) and -1.0 <= v <= CLOCK_MAX_S else None


def _write_clock(ad, addr: int, value: float) -> float:
    ad.write_memory(addr, struct.pack("<f", value))
    return struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0]


def _clock_op(ad, snap, *, add=None, absolute=None) -> dict:
    found = _clock(ad, snap)
    if found is None:
        return {"verified": False, "reason": "the round clock is not found yet (re4_switch.ClockFinder): a round must "
                                              "be playing for a few seconds"}
    addr, now = found
    want = (now + add) if absolute is None else absolute
    want = min(max(want, 1.0), CLOCK_MAX_S)
    try:
        back = _write_clock(ad, addr, want)
    except (ValueError, OSError, RuntimeError, struct.error) as exc:
        return {"verified": False, "reason": f"clock write failed: {type(exc).__name__}: {exc}"[:160]}
    st = _state(ad)
    st["clock_pending"] = {"addr": addr, "value": want, "at": time.monotonic()}
    return {"verified": abs(back - want) < 0.01, "clock_addr": hex(addr), "before": round(now, 2),
            "after": round(back, 2), "note": "the next snapshot confirms the clock kept it (clock_holds)"}


def add_time(ad, seconds, snap=None) -> dict:
    return _clock_op(ad, snap, add=_num(seconds, -3600.0, 3600.0, "add_time"))


def set_time(ad, seconds, snap=None) -> dict:
    return _clock_op(ad, snap, absolute=_num(seconds, 1.0, CLOCK_MAX_S, "set_time"))


def kill_time(ad, on: bool, seconds=None) -> dict:
    st = _state(ad)
    s = KILL_TIME_S if seconds is None else _num(seconds, 0.0, KILL_TIME_MAX_S, "kill_time seconds")
    st["kill_time"] = {"on": bool(on), "seconds": s}
    _save(st)
    return {"kill_time_on": bool(on), "kill_time_s": s, "verified": True,
            "note": "+seconds on the round clock for every kill the census counts"}


def _confirm_clock(ad, st: dict, snap: dict) -> None:
    pend = st.get("clock_pending")
    if not pend:
        return
    found = _clock(ad, snap)
    if found is None or found[0] != pend["addr"]:
        return
    elapsed = time.monotonic() - pend["at"]
    holds = abs(found[1] - (pend["value"] - elapsed)) <= CLOCK_HOLD_TOL + elapsed * 0.5
    st["clock_holds"] = bool(holds)
    st.pop("clock_pending", None)


def _kills_of(snap: dict, st: dict) -> int:
    """New kills since the last snapshot: the game's counter when mapped, else Ganados whose health fell to 0."""
    k = snap.get("kills")
    if isinstance(k, int) and not isinstance(k, bool):
        new = max(0, k - st.get("kills_seen", k))
        st["kills_seen"] = k
        return new
    seen, new = {}, 0
    last = st.get("hp_seen") or {}
    for e in snap.get("enemies") or ():
        if e.get("class") not in D.ENEMY_CLASSES or not isinstance(e.get("ptr"), int):
            continue
        hp = e.get("hp") or 0
        if last.get(e["ptr"], 0) > 0 and hp <= 0:
            new += 1
        seen[e["ptr"]] = hp
    st["hp_seen"] = seen
    return new


def pre_round(ad, m=None) -> dict:
    """On the menus before a round (re4switch_bot calls it once a boot): the saved settings put into this boot - the
    static tables (fire rate, ammo, firepower) and the Mercenaries loadouts (a random draw, or the chosen weapon) -
    so the round the walk is about to start is built with them."""
    base = D.module_base(m if m is not None else Mem(ad))
    if base is None:
        return {}
    out: dict = {}
    with _LOCK:
        st = _state(ad)
        if st.get("pre_round_base") == base:
            return {}
        st["pre_round_base"] = base
        if st.get("weapon_power", 1.0) != 1.0 or st.get("max_level"):
            out["power_rows"] = _apply_power(ad, base, st)
            st["fp_applied_base"] = base
        if st.get("fire_rate", 1.0) != 1.0:
            out["fire_tables"] = _apply_fire_rate(ad, base, st)
        if st.get("infinite_ammo"):
            out["ammo_rows"] = _apply_ammo(ad, base, st)
        st["rf_applied_base"] = base
        if st.get("random_weapon") or st.get("loadout_weapon"):
            import random as _random
            fixed = st.get("loadout_weapon")
            draws = _draw_loadouts(_random.Random(), fixed) if st.get("random_weapon") else \
                {ch: [fixed] for ch in W.LOADOUT_SITES}
            done = _patch_loadout(ad, base, draws)
            st["loadout_drawn"] = base
            st["loadouts"] = {W.CHARACTERS.get(ch, ch): [W.name(i) for i in ids] for ch, ids in done.items()}
            out["loadouts"] = len(done)
    return out


def maintain(ad, snap: dict | None = None) -> dict:
    """Every RAM snapshot of a round: the health caps, the time per kill, the clock write's confirmation."""
    if not snap or snap.get("module_base") is None:
        return {}
    out: dict = {}
    with _LOCK:
        st = _state(ad)
        if st.get("base") is None:
            st["base"] = snap["module_base"]
        elif st["base"] != snap["module_base"]:          # a new boot: the operator's settings stay, the counts go
            keep = {k: st[k] for k in ("enemy_health", "one_hit", "kill_time", "unlimited_health", "weapon_power",
                                      "max_level", "aim_lock", "fire_rate", "infinite_ammo", "random_weapon",
                                      "fire_gap_orig") if k in st}
            st.clear()
            st.update(keep, base=snap["module_base"])
        frac = 0.0 if st.get("one_hit") else st.get("enemy_health")
        if frac is not None and frac < 1.0:
            n = _cap_health(ad, snap.get("enemies"), frac)
            st["capped_total"] = st.get("capped_total", 0) + n
            out["capped"] = n
        if st.get("unlimited_health"):
            n = _keep_life(ad, snap)
            st["life_kept"] = st.get("life_kept", 0) + n
            if n:
                out["life_kept"] = n
        if (st.get("weapon_power", 1.0) != 1.0 or st.get("max_level")) and not st.get("fp_applied_base") == snap["module_base"]:
            out["power_rows"] = _apply_power(ad, snap["module_base"], st)   # once a boot (the table is static data)
            st["fp_applied_base"] = snap["module_base"]
        if (st.get("fire_rate", 1.0) != 1.0 or st.get("infinite_ammo")) and st.get("rf_applied_base") != snap["module_base"]:
            out["fire_tables"] = _apply_fire_rate(ad, snap["module_base"], st) if st.get("fire_rate", 1.0) != 1.0 else 0
            out["ammo_rows"] = _apply_ammo(ad, snap["module_base"], st) if st.get("infinite_ammo") else 0
            st["rf_applied_base"] = snap["module_base"]
        rnd = snap.get("round_key") or snap["module_base"]
        if st.get("random_weapon") and st.get("loadout_drawn") != rnd:
            import random as _random
            done = _patch_loadout(ad, snap["module_base"], _draw_loadouts(_random.Random()))
            st["loadout_drawn"] = rnd                   # the next round's loadouts (the game builds them)
            st["loadouts"] = {W.CHARACTERS.get(ch, ch): [W.name(i) for i in ids] for ch, ids in done.items()}
            out["loadouts_drawn"] = len(done)
        if st.get("random_weapon") and snap.get("player") and st.get("weapon_given_round") != rnd:
            st["weapon_given_round"] = rnd
            try:
                ch = bytes(ad.read_memory(snap["module_base"] + W.GAME_OBJ + W.G_CHARACTER, 1))[0]
            except (ValueError, OSError):
                ch = None
            if ch is not None and ch not in W.LOADOUT_SITES:  # no loadout sites (HUNK): the in-hand swap
                import random as _random
                given = _give_weapon(ad, snap["module_base"], st, _random.Random())
                if given is not None:
                    st["weapon_given"] = given
                    out["weapon_given"] = 1
        if st.get("aim_lock"):
            n = _aim(ad, snap)
            st["aim_writes"] = st.get("aim_writes", 0) + n
            if n:
                out["aim_writes"] = n
        new = _kills_of(snap, st)
        kt = st.get("kill_time") or {}
        if new and kt.get("on") and kt.get("seconds", 0) > 0:
            found = _clock(ad, snap)
            if found is not None and found[1] > 0:
                try:
                    _write_clock(ad, found[0], min(found[1] + new * kt["seconds"], CLOCK_MAX_S))
                    st["kill_time_added"] = st.get("kill_time_added", 0.0) + new * kt["seconds"]
                    out["kill_time_added"] = new * kt["seconds"]
                except (ValueError, OSError, RuntimeError, struct.error) as exc:
                    st["kill_time_error"] = f"{type(exc).__name__}: {exc}"[:120]
        _confirm_clock(ad, st, snap)
    return out


def status(ad, snap: dict | None = None) -> dict:
    st = dict(_state(ad))
    kt = st.get("kill_time") or {}
    out = {"game": GAME, "enemy_health_x": st.get("enemy_health", 1.0), "one_hit": bool(st.get("one_hit")),
           "kill_time_on": bool(kt.get("on")), "kill_time_s": kt.get("seconds", KILL_TIME_S),
           "kill_time_added": round(st.get("kill_time_added", 0.0), 1), "capped_total": st.get("capped_total", 0),
           "clock_holds": st.get("clock_holds"),
           "unlimited_health": bool(st.get("unlimited_health")), "life_kept": st.get("life_kept", 0),
           "infinite_ammo": bool(st.get("infinite_ammo")), "fire_rate_x": st.get("fire_rate", 1.0),
           "random_weapon": bool(st.get("random_weapon")), "weapon_given": st.get("weapon_given"),
           "loadouts": st.get("loadouts"), "loadout_weapon": st.get("loadout_weapon"),
           "weapon_power_x": st.get("weapon_power", 1.0), "max_level": bool(st.get("max_level")),
           "aim_lock": bool(st.get("aim_lock")), "aim_writes": st.get("aim_writes", 0),
           "capabilities": {
               "enemy_health": {"available": True}, "one_hit": {"available": True},
               "kill_time": {"available": True, "clock_found": bool((snap or {}).get("clock_addr")),
                             "note": "adds time once the driver has found the round clock"},
               "unlimited_health": {"available": True},
               "infinite_ammo": {"available": True}}}
    if snap:
        found = _clock(ad, snap)
        out["clock"] = {"addr": hex(found[0]), "value": round(found[1], 2)} if found else None
        out["ganados"] = [{"hp": e.get("hp"), "hp_max": e.get("hp_max")} for e in snap.get("enemies") or ()
                          if e.get("class") in D.ENEMY_CLASSES][:24]
    return out


def run(ad, op: str = "status", multiplier=None, on: bool = True, snap: dict | None = None, **extra) -> dict:
    """One op (see the module docstring). snap: a fresh RE4 snapshot when the caller has one, else one is read."""
    op = (op or "status").strip().lower()
    if snap is None:
        try:
            snap = D.snapshot(Mem(ad), search=False)
        except Exception:                                   # noqa: BLE001 - a status without a snapshot still answers
            snap = None
    with _LOCK:
        if op == "status":
            return {"verified": True, "status": status(ad, snap)}
        if op == "enemy_health":
            return enemy_health(ad, 1.0 if multiplier is None else multiplier, snap)
        if op == "one_hit":
            return one_hit(ad, on, snap)
        if op == "add_time":
            return add_time(ad, extra.get("seconds", 60.0), snap)
        if op == "set_time":
            return set_time(ad, extra.get("seconds"), snap)
        if op == "kill_time":
            return kill_time(ad, on, extra.get("seconds"))
        if op == "unlimited_health":
            return unlimited_health(ad, on, snap)
        if op == "weapon_power":
            return weapon_power(ad, 1.0 if multiplier is None else multiplier, snap)
        if op == "max_level":
            r = max_level(ad, on, snap)
            _state(ad).pop("fp_applied_base", None)
            return r
        if op == "aim_lock":
            return aim_lock(ad, on)
        if op == "infinite_ammo":
            r = infinite_ammo(ad, on, snap)
            _state(ad).pop("rf_applied_base", None)
            return r
        if op == "fire_rate":
            r = fire_rate(ad, 1.0 if multiplier is None else multiplier, snap)
            _state(ad).pop("rf_applied_base", None)
            return r
        if op == "random_weapon":
            return random_weapon(ad, on, snap)
        if op == "loadout_weapon":
            return loadout_weapon(ad, extra.get("weapon"), snap)
        if op == "revert_all":
            st = _state(ad)
            for k in ("enemy_health", "one_hit", "kill_time", "unlimited_health"):
                st.pop(k, None)
            return {"verified": True, "note": "no more caps or time per kill (health already taken stays taken)"}
    raise ValueError(f"re4_switch_mods: unknown op {op!r}")
