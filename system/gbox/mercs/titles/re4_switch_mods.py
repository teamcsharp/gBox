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
  add_time seconds=N          the round clock (the HUD's CountDown, snap["clock_addr"] with clock_source "countdown":
                              frames at 30 a second in its +8; ClockFinder's float, seconds, only as the fallback) moved by N
                              (-3600..3600), never under 1 s; written, read back, and confirmed on the next snapshot (a
                              clock whose master copy rewrites it is reported as not holding)
  set_time seconds=N          the clock set to 1..CLOCK_MAX_S
  kill_time on=true seconds=S +S on the clock for every new kill the census counts (a Ganado whose health fell to 0)
                              while a round is playing
  random_weapon on=true       every round, once the game says it is live (playing, in control, clock running): a
                              random max-level campaign weapon written into the gun in his hand - a magnum or a
                              shotgun only (PRIMARY; MAGNUM_SHARE toward 1.0) - the item, the item manager's held id,
                              the game state's class / variant / levels - every byte read back, his own weapon put
                              back if one does not hold; the fire_rate tables are written again in the same round and
                              both the weapon and the tables reported (weapon_rounds)
  loadout_weapon weapon=id    the same with this weapon every round (0 = off). Data writes only: the loadout code
                              patch is off (LOADOUT_CODE_PATCH; why: the block above _give_weapon)

The player's life is not in his unit on Switch (re4_switch PLAYER_HP_IN_UNIT): unlimited health waits for that field
(the round probe looks for it), and ammo for the inventory's; both answer "not mapped yet" until then.
"""
from __future__ import annotations

import json
import math
import struct
import threading
import time
import weakref
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
FIRE_RATE_MAX_X = 40.0
FIRE_GAP_MIN_S = 0.025                 # the fight's trigger taps never closer than this (re4_switch.FIRE_GAP_S): 40 Hz
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
              "fire_rate", "infinite_ammo", "random_weapon", "loadout_weapon",
              # heal_below is what the threshold heal reads; without it here _load_saved drops the setting and the
              # heal silently never runs (live 2026-11-12: hp 658/2400 with mods_heals absent).
              "heal_below")


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


_FILES: dict = {}                        # id(ad) -> SETTINGS_FILE's mtime_ns when the state last took the file


def _state(ad) -> dict:
    """This adapter's state: the saved settings and what was put into its boot. Keyed by id(ad) and checked against
    the adapter itself, since a new session's adapter can be given a collected one's id.

    The file is the operator's (and the app's) hand on this title, so when it CHANGES the saved settings are taken
    again. Without that, a setting only becomes live at a new adapter: heal_below was added to SAVED_KEYS on a running
    session and the cached state kept the old filtered settings, so the threshold heal still never ran (live
    2026-11-12, hp 368/2400 with mods_heals absent).
    """
    st = ORIG.get(id(ad))
    owner = st.get("_owner") if st is not None else None
    fresh = st is None or (owner is not None and owner() is not ad)
    if fresh:
        st = ORIG[id(ad)] = _load_saved()
        try:
            st["_owner"] = weakref.ref(ad)
        except TypeError:
            pass
    try:
        mtime = SETTINGS_FILE.stat().st_mtime_ns
    except OSError:
        mtime = None
    if mtime is not None and _FILES.get(id(ad)) != mtime:
        _FILES[id(ad)] = mtime
        if not fresh:
            st.update(_load_saved())
    return st


def _boot(ad, base) -> str:
    """This boot's identity: the module base AND the emulator process (Eden loads RE4 at the same address every boot,
    so the base alone said "already applied" to every later boot of a worker's life)."""
    proc = getattr(ad, "proc", None)
    return f"{base:#x}/{getattr(proc, 'pid', None)}/{getattr(ad, 'restarts', None)}" if isinstance(base, int) \
        else f"{base}/{getattr(proc, 'pid', None)}"


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
        # The deficit BEFORE it is written away is the only honest measure of the blow: the heal runs on every snapshot,
        # so it restores within the same tick and the driver's per-tick health sample never sees the lower value (live
        # 2026-11-12: 4 heals in a round, health sampled at full every time, hit_events 0). A driver-side counter can
        # never see this damage - it has to be read here, where it still exists.
        st = _state(ad)
        st["last_heal_from"] = now
        st["max_deficit"] = max(int(st.get("max_deficit") or 0), top - now)
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
    st.pop("fp_applied_boot", None) if not rows else None
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
    """The bot's aim request (re4_switch.AIM_REQUEST) written to the player's facing (unit + U_YAW), read back. A
    request with steady (the gun up: re4_switch.AIM_RAM) also holds the gun itself (_steady).

    The write is smoothed (operator 2026-11-11: "jerking around with the aim unnaturally ... causes motion sickness"):
    a request under AIM_WRITE_DEADBAND from the facing is not written, and a write moves the facing at most
    AIM_WRITE_MAX_STEP toward the request - a turn the game's own camera can follow, never a teleport.
    """
    req = D.AIM_REQUEST
    p = (snap or {}).get("player") or {}
    if not req or req.get("ptr") != p.get("ptr") or time.monotonic() - req.get("at", -1e9) > AIM_FRESH_S:
        return 0
    want = req.get("yaw")
    if not isinstance(want, (int, float)) or not math.isfinite(want):
        return 0
    addr = p["ptr"] + D.U_YAW
    try:
        current = struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0]
    except (ValueError, OSError, RuntimeError, struct.error):
        return 0
    delta = D.wrap(float(want) - current)
    if abs(delta) <= AIM_WRITE_DEADBAND:
        return 0
    target = current + max(-AIM_WRITE_MAX_STEP, min(AIM_WRITE_MAX_STEP, delta))
    try:
        ad.write_memory(addr, struct.pack("<f", target))
        back = struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0]
    except (ValueError, OSError, RuntimeError, struct.error):
        return 0
    if req.get("steady") and getattr(D, "AIM_RAM", False):
        _steady(ad, snap, req)
    return 1 if abs(back - target) < 1e-3 else 0


# The steady aim (re4_switch AIM_RAM; the operator 2026-11-10: "I want the aim impeccable"): data writes only, each one
# re-read just before it (the chain player -> weapon control -> weapon object must still be the snapshot's) and read back:
#   * the sway's four bounds (weapon object + 0x3E0 .. +0x3EC) to 0: no random walk, no recoil kick (PlWepLockRand then
#     clamps the aim onto its centre every frame);
#   * the waist twist (unit + 0x524) and its centre (weapon control + 0x2C) to 0: the aim's yaw IS his facing, which the
#     facing write above puts on the target;
#   * the centre pitch (weapon control + 0x28) to the request's pitch (blend x pi/2, clamped to STEADY_PITCH_MAX): the
#     aim's pitch follows it.
# A weapon object read back with its sway restored (a new weapon's init) is zeroed again on the next snapshot. The
# counts go to the state (aim_ram_writes / aim_sway_zeroed / aim_ram_refused) and out through maintain().
STEADY_PITCH_MAX = 1.45
STEADY_EPS = 1e-4
#: The aim write's smoothing (the operator 2026-11-11: the aim jerked with the bow and made motion sickness): a
#: correction under this much is left alone, and one write turns the facing at most this far toward the request.
AIM_WRITE_DEADBAND = math.radians(0.5)
AIM_WRITE_MAX_STEP = math.radians(3.0)


def _steady(ad, snap: dict, req: dict) -> int:
    aim = (snap or {}).get("aim") or {}
    p = (snap or {}).get("player") or {}
    st = _state(ad)
    wep, obj = aim.get("wep"), aim.get("obj")
    if not isinstance(wep, int) or not isinstance(obj, int) or req.get("wep") not in (None, wep):
        st["aim_ram_refused"] = st.get("aim_ram_refused", 0) + 1
        return 0
    n = 0
    try:
        if struct.unpack("<Q", bytes(ad.read_memory(p["ptr"] + D.PL_WEP, 8)))[0] != wep \
                or struct.unpack("<Q", bytes(ad.read_memory(wep + D.WEP_OBJ, 8)))[0] != obj:
            st["aim_ram_refused"] = st.get("aim_ram_refused", 0) + 1
            return 0
        sway = struct.unpack("<4f", bytes(ad.read_memory(obj + D.OBJ_SWAY, 16)))
        if not all(math.isfinite(v) and 0.0 <= v <= D.SWAY_SANE for v in sway):
            st["aim_ram_refused"] = st.get("aim_ram_refused", 0) + 1
            return 0
        if any(v > STEADY_EPS for v in sway):
            ad.write_memory(obj + D.OBJ_SWAY, struct.pack("<4f", 0.0, 0.0, 0.0, 0.0))
            if all(v == 0.0 for v in struct.unpack("<4f", bytes(ad.read_memory(obj + D.OBJ_SWAY, 16)))):
                st["aim_sway_zeroed"] = st.get("aim_sway_zeroed", 0) + 1
                st["aim_sway_was"] = [round(v, 4) for v in sway]
                n += 1
        writes = [(p["ptr"] + D.PL_WAIST_YAW, 0.0), (wep + D.WEP_CENTER_Y, 0.0)]
        pitch = req.get("pitch")
        if isinstance(pitch, (int, float)) and math.isfinite(pitch):
            writes.append((wep + D.WEP_PITCH, max(-STEADY_PITCH_MAX, min(STEADY_PITCH_MAX, float(pitch)))))
        for addr, want in writes:
            now = struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0]
            if not math.isfinite(now) or abs(now) > D.PITCH_SANE:
                st["aim_ram_refused"] = st.get("aim_ram_refused", 0) + 1
                continue
            if abs(now - want) <= STEADY_EPS:
                continue
            ad.write_memory(addr, struct.pack("<f", want))
            if abs(struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0] - want) <= 1e-4:
                n += 1
    except (ValueError, OSError, RuntimeError, struct.error, KeyError, TypeError) as exc:
        st["aim_ram_error"] = f"{type(exc).__name__}: {exc}"[:120]
        return n
    st["aim_ram_writes"] = st.get("aim_ram_writes", 0) + n
    return n


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
    st["fire_tables_last"] = n                          # tables that read back (0: unreadable - retried, see below)
    return n


FIRE_RETRY_S = 3.0


def _fire_tables_due(st: dict, boot) -> bool:
    """Whether this boot's 20x tables still have to be written (Hermes #9560): pre_round / maintain marked the boot done
    even when the module was unreadable (0 tables), so no 20x rate was written until the round's own give. A boot is
    only marked done once a table read back; retries are paced FIRE_RETRY_S."""
    if st.get("fire_rate", 1.0) == 1.0 or st.get("rf_applied_boot") == boot:
        return False
    return time.monotonic() - st.get("fire_try_at", -1e9) >= FIRE_RETRY_S


def _apply_fire_rate_boot(ad, base: int, st: dict, boot) -> int:
    st["fire_try_at"] = time.monotonic()
    st["fire_tries"] = st.get("fire_tries", 0) + 1
    n = _apply_fire_rate(ad, base, st)
    if n > 0:
        st["rf_applied_boot"] = boot
    return n


def fire_rate(ad, multiplier, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["fire_rate"] = _num(multiplier, 1.0, FIRE_RATE_MAX_X, "fire_rate")
    _save(st)
    base = (snap or {}).get("module_base")
    n = _apply_fire_rate(ad, base, st) if isinstance(base, int) else 0
    return {"fire_rate_x": st["fire_rate"], "verified": True, "tables": n, "trigger_gap_s": round(D.FIRE_GAP_S, 3),
            "note": "every weapon's frames between shots / this (never under the shot gate's 3-frame floor); the bow "
                    "and the grenades, which no table paces, play their weapon routine's motions this much faster "
                    "(_motion_rate, every snapshot while one is in hand)"}


# The bow / throwables' rate (re4_weapons.MOTION_RATE_CLASSES; the operator 2026-11-10 #9508: "fire the bow 20x
# faster"; 2026-11-11: "the character with the bow rapid firing arrows at 40 times a second"): while the class in hand
# is one of them and the player is in its weapon routine, his motion speed (unit +
# P_MOTION_SPEED) and his weapon object's (+ OBJ_MOTION_SPEED) are the fire_rate multiplier (at most MOTION_RATE_MAX_X);
# the routine ends, each one put back to what it read before the first write. Every write is preceded by a fresh read
# of the routine bytes and the speed (outside MOTION_SPEED_SANE: refused, nothing written) and read back. The state:
# st["motion_rate"] = {"kind", "addrs": {address: the speed it read}, "speed"} while it is on.
MOTION_RATE_MAX_X = 40.0
#: The bow's own rate floor: the operator 2026-11-11 wants 40 arrows a second whatever the fire-rate setting is.
BOW_MOTION_X = 40.0


def _motion_rate(ad, snap: dict, st: dict) -> int:
    """One snapshot of the bow's rate (see above). -> writes made (on, refreshed or put back)."""
    mult = min(float(st.get("fire_rate", 1.0) or 1.0), MOTION_RATE_MAX_X)
    p = (snap or {}).get("player") or {}
    on = st.get("motion_rate")
    ptr = p.get("ptr")
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    n = 0
    try:
        kind = None
        if isinstance(ptr, int) and D.ptr_ok(ptr):
            routine = tuple(rd(ptr + W.P_ROUTINE, 4))
            st["motion_rate_class"] = snap.get("weapon_class")
            st["motion_rate_routine"] = list(routine)    # why the rate is or is not on: the live class + routine
            kind = W.motion_rate_kind(snap.get("weapon_class"), routine)
            if kind is None and snap.get("equipped_id") == W.BOW_ITEM:
                # The item id is the second witness for the class byte (the same fix _bow_in_hand took). Without it a
                # misread class leaves the 40x motion rate off and Krauser's arrows at the game's own pace - which is
                # exactly the "the bow isn't 20x" report. The routine gate still applies to the grenades.
                kind = "bow"
        if kind == "bow":
            mult = max(mult, BOW_MOTION_X)               # the operator: 40 arrows a second, whatever the fire rate
        if kind is None or mult <= 1.0:
            if on:                                       # the routine is over: each speed back to what it was
                for addr, was in list(on["addrs"].items()):
                    cur = struct.unpack("<f", rd(addr, 4))[0]
                    if abs(cur - on["speed"]) <= 1e-3:   # (still ours: a speed the game set since is the game's)
                        ad.write_memory(addr, struct.pack("<f", was))
                        n += abs(struct.unpack("<f", rd(addr, 4))[0] - was) <= 1e-4
                st["motion_rate"] = None
                st["motion_rate_restores"] = st.get("motion_rate_restores", 0) + 1
            return n
        addrs = [ptr + W.P_MOTION_SPEED]
        wep = struct.unpack("<Q", rd(ptr + D.PL_WEP, 8))[0]
        if D.ptr_ok(wep):
            obj = struct.unpack("<Q", rd(wep + D.WEP_OBJ, 8))[0]
            if D.ptr_ok(obj):
                addrs.append(obj + W.OBJ_MOTION_SPEED)
        if on is None or on.get("ptr") != ptr:
            on = st["motion_rate"] = {"kind": kind, "ptr": ptr, "addrs": {}, "speed": mult}
        on["speed"], on["kind"] = mult, kind
        lo, hi = W.MOTION_SPEED_SANE
        for addr in addrs:
            cur = struct.unpack("<f", rd(addr, 4))[0]
            if not math.isfinite(cur) or not lo <= cur <= hi:
                st["motion_rate_refused"] = st.get("motion_rate_refused", 0) + 1
                st["motion_rate_refused_last"] = f"{addr:#x} read {cur!r}: not a motion speed"[:120]
                continue
            if abs(cur - mult) <= 1e-3:
                continue                                 # ours already
            on["addrs"][addr] = cur                      # the game's own (set since or not): what goes back at the end
            ad.write_memory(addr, struct.pack("<f", mult))
            if abs(struct.unpack("<f", rd(addr, 4))[0] - mult) <= 1e-4:
                n += 1
        st["motion_rate_kind"] = kind
        st["motion_rate_writes"] = st.get("motion_rate_writes", 0) + n
    except (ValueError, OSError, RuntimeError, struct.error, TypeError) as exc:
        st["motion_rate_error"] = f"{type(exc).__name__}: {exc}"[:120]
    return n


def _keep_arrows(ad, base: int, st: dict) -> int:
    """Infinite ammo for the bow (its arrows are an item of their own, re4_weapons.ARROWS, not a magazine _keep_mag
    can fill): with the bow in hand each arrows stack in his case kept at the most it held this boot (never above
    ARROWS_MAX), read back. -> stacks refilled."""
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    try:
        reader = W.Reader(rd, base)
        held = reader.equipped()
        if held is None or W.CLASS_OF.get(held["id"]) not in (0x1C,):
            return 0
        tops = st.setdefault("arrows_top", {})
        n = 0
        for it in reader.items():
            if it["id"] != W.ARROWS or not it.get("addr"):
                continue
            key = str(it["addr"])
            top = min(W.ARROWS_MAX, max(tops.get(key, 0), it["count"]))
            tops[key] = top
            # `0 < it["count"] < top` never refilled a stack that had run out, so once the arrows reached 0 the bow was
            # dry for the rest of the round - and at BOW_MOTION_X 40 arrows a second a 30-arrow stack empties in under a
            # second. The top is remembered from an earlier read, so 0 refills to it (live 2026-11-12, the operator's
            # "rain arrows at enemies defending themselves effortlessly").
            if it["count"] < top:
                ad.write_memory(it["addr"] + 2, struct.pack("<H", top))
                n += struct.unpack("<H", rd(it["addr"] + 2, 2))[0] == top
        return n
    except (ValueError, OSError, RuntimeError, struct.error, KeyError, TypeError):
        return 0


def _keep_mag(ad, base: int, st: dict) -> int:
    """Infinite ammo: the equipped gun's magazine kept full - item+8 = its capacity at its capacity level << 3, the
    empty bit and the game state's magazine-empty byte cleared - every snapshot, the way unlimited life keeps his life.

    Not the capacity table's infinite value (0x8000, re4_weapons.CAP_INFINITE), which the first live run (2026-11-10,
    Leon "EMPTY" from the round's start) showed cannot be used: the magazine is sized as capacity << 19 in a 32-bit
    word (the loadout code's ORR w8, w8, w0, LSL #19, and the reload's), so 0x8000 comes out as 0 rounds."""
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    try:
        held = W.Reader(rd, base).equipped()
        if held is None or not held.get("addr"):
            return 0
        rows = st.get("weapon_rows")
        if rows is None:
            rows = st["weapon_rows"] = W.decode_weapon_table(rd(base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
        row = rows.get(held["id"])
        if row is None:
            return 0                                     # not a gun (a grenade, the knife)
        caps = row["capacity"]
        cap = caps[min(held["levels"]["capacity"], len(caps) - 1)] or max(caps)
        if cap <= 0 or cap >= W.CAP_INFINITE:
            return 0
        cap = min(cap, 0x1FFF)
        if held["loaded"] >= cap and not held["empty"]:
            return 0
        raw = struct.unpack("<H", rd(held["addr"] + 8, 2))[0]
        ad.write_memory(held["addr"] + 8, struct.pack("<H", (cap << 3) | (raw & 0b110)))
        ad.write_memory(base + W.GAME_OBJ + W.G_EMPTY, b"\x00")
    except (ValueError, OSError, RuntimeError, struct.error, KeyError, IndexError):
        return 0
    return 1


def infinite_ammo(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["infinite_ammo"] = bool(on)
    _save(st)
    base = (snap or {}).get("module_base")
    n = _keep_mag(ad, base, st) if on and isinstance(base, int) else 0
    return {"infinite_ammo": bool(on), "verified": True, "refilled": n,
            "note": "the gun in his hand is kept full every snapshot (its magazine never runs dry)"}


# --- the random weapon: in his hand once the round is live (data writes only) -------------------------------------
# The Mercenaries loadout as CODE (_patch_loadout over re4_weapons.LOADOUT_SLOTS) is OFF. Every boot with it on hung
# at the stage load (lilspark, 2026-11-10 08:05-09:49; the last one's Citron log ends on "Unhandled NCE prefetch
# abort: pc=0x0" at the stage load, the game's thread gone), and it cannot be made safe from outside the emulator:
#   - Citron / Eden run the guest natively (NCE) and the Spark's cores report CTR_EL0.DIC = 0: new instructions are
#     seen only after an IC IVAU by the process itself. These writes go through /proc/<pid>/mem into a writable,
#     non-executable alias of the code page, for which the kernel does no instruction-cache maintenance, so a core can
#     run a slot's old words beside its new ones (a give without its searches) - the read-back reads data, not what
#     the CPU executes;
#   - the give (0x3578E0) leaves out an item the case has no room for (re4_weapons.case_layout): 26 of 156 Ada draws
#     and 30 of 156 Wesker draws lost the semi-auto rifle, a grenade or the spray, and the code after the give reads
#     the missing item through a null pointer (Citron skips the data abort and goes on with garbage).
# Every word the patch writes was checked against the disassembly and decodes as intended: the code was right, the
# route was not. So the drawn weapon goes into his hand by data writes once the game says the round is live
# (_round_weapon), each write read back and the old bytes put back if any does not hold.
LOADOUT_CODE_PATCH = False
ROUND_WEAPON_TRIES = 3                 # gives tried per round before it is reported and left alone
# what a random weapon may replace in his hand: a gun with a max-level row, or a loadout's own equipped weapon
# (Krauser's bow) - never a grenade the bot holds (THROWS) or the knife
SWAPPABLE = frozenset(W.MAX_LEVELS) | frozenset(lo["equips"] for lo in W.MERC_LOADOUTS.values())
# The magnums and shotguns come up often (operator 2026-11-10: "the scatter works if they have a magnum and 20x
# firerate. Its boring with the pistol"; then: "I need the bot firing relentlessly with any weapon type magnum or
# shotgun with rapid fire"), and the operator 2026-11-11: "randomize the weapon being used between rounds between all
# of the weapons available in the campaign at random emphasizing magnums and shotguns": PRIMARY_SHARE of the rounds a
# magnum or a shotgun (a magnum MAGNUM_SHARE of those), the rest any campaign weapon in HIGH_POWER at random.
MAGNUMS = frozenset({0x29, 0x2A, 0x37})        # Broken Butterfly, Killer7, Handcannon
SHOTGUNS = frozenset({0x2C, 0x2D, 0x94})       # Shotgun, Striker, Riot Gun
PRIMARY = MAGNUMS | SHOTGUNS
MAGNUM_SHARE = 0.5
# Operator 2026-11-11 22:15: "I want to see more weapon variance between the rounds ... maxed out weapons from the
# campaign, ranging from the PRL to the magnum." 1.0 forced a magnum every round (no variance at all); half the
# primary draws are magnums now and the rest of the primary draws are shotguns.
PRIMARY_SHARE = 0.7
# ...and 30% of the rounds draw ANY campaign high-power weapon (re4_weapons.HIGH_POWER: PRL 0x94, rocket launcher
# 0x35, Chicago Typewriter 0x34, TMP, rifles) at max level - the "ranging from the PRL to the magnum" spread. The
# 15:59 no-pistols rule holds: HIGH_POWER carries no handgun.
                                               # magnum or a shotgun, both max level (the pistols upset the stream)


def _code_patch_refusal(ad) -> str | None:
    """Why the loadout code patch is not written into this boot (None: it may be)."""
    if not LOADOUT_CODE_PATCH:
        return "off (LOADOUT_CODE_PATCH): the weapon goes in his hand once the round is live"
    if getattr(ad, "use_nce", False) or getattr(ad, "cpu_backend", None) == "nce":
        return "refused under NCE: no instruction-cache maintenance for code written from outside the emulator"
    return None


def _give_weapon(ad, base: int, st: dict, rng, fixed: int | None = None, exclude=()) -> dict | None:
    """A random high-powered campaign weapon (re4_weapons.HIGH_POWER; `fixed` instead when given) at max level, full,
    into the gun in his hand: the item's id, levels and rounds, the item manager's held id, the game state's class /
    variant / level nibbles and reload. Every byte is read back; if any does not hold, the hand's old bytes go back.
    None when the hand cannot be read."""
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    r = W.Reader(rd, base)
    errors = (ValueError, OSError, RuntimeError, struct.error)
    try:
        held = r.equipped()
        rows = st.get("weapon_rows")
        if rows is None:
            rows = st["weapon_rows"] = W.decode_weapon_table(rd(base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
        g = r.game_obj()
    except errors:
        return None
    if held is None or not held.get("addr") or g != base + W.GAME_OBJ:
        return None
    if held["id"] not in SWAPPABLE:
        return {"verified": False, "was": held["name"], "reason": f"{held['name']} in his hand is not a gun to swap"}
    if fixed is not None:
        picks = [fixed] if fixed in rows and W.max_levels(fixed) is not None else []
    else:
        pool = [i for i in W.HIGH_POWER if i in rows and W.max_levels(i) is not None and i != held["id"]]
        primary = [i for i in pool if i in PRIMARY]       # the magnums/shotguns, emphasised (PRIMARY_SHARE)
        if primary and rng.random() < PRIMARY_SHARE:
            magnums = [i for i in primary if i in MAGNUMS]
            picks = [rng.choice(magnums)] if (magnums and rng.random() < MAGNUM_SHARE) else primary
        else:
            picks = pool                                  # every campaign weapon at random
        picks = [i for i in picks if i not in exclude] or picks
    if not picks:
        return {"verified": False, "was": held["name"], "reason": "no weapon row to give"}
    iid = rng.choice(picks) if len(picks) > 1 else picks[0]
    row, lv = rows[iid], W.max_levels(iid)
    cap = row["capacity"][lv["capacity"]] or max(row["capacity"])
    loaded = 99 if cap in (0, W.CAP_INFINITE) else min(cap, 0x1FFF)
    item, mgr = held["addr"], base + W.ITEM_MGR
    nibbles = (lv["firepower"], lv["firing_speed"], lv["capacity"])
    try:
        saved = {"item": rd(item, W.ITEM_SZ), "held": rd(mgr + W.M_EQUIPPED_ID, 2),
                 "cls": rd(g + W.G_CLASS, HAND_CLASS_N), "reload": rd(g + W.G_RELOAD, 1)}
    except errors:
        return None
    ok = False
    try:
        _write_hand(ad, base, item, g, iid, row, lv["packed"], loaded, nibbles, lv["reload"])
        back = W.decode_item(rd(item, W.ITEM_SZ), item)
        # The identity is what the swap must own: the item is the new gun, the manager holds it, and the game state's
        # class byte is the new row's class. The level/rounds/reload bytes are the game's own state - a stale cosmetic
        # byte must not discard a good magnum (live 2026-11-11 19:46: the strict all-fields read-back kept putting the
        # shotgun back, so the operator saw class 15 in a fight despite MAGNUM_SHARE 1.0).
        ok = (back["id"] == iid and not back["empty"]
              and struct.unpack("<H", rd(mgr + W.M_EQUIPPED_ID, 2))[0] == iid
              and rd(g + W.G_CLASS, 1) == bytes([row["class"]]))
    except errors:
        ok = False
    if not ok:
        try:                                             # the hand as it was: never half a weapon
            ad.write_memory(item, saved["item"])
            ad.write_memory(mgr + W.M_EQUIPPED_ID, saved["held"])
            ad.write_memory(g + W.G_CLASS, saved["cls"])
            ad.write_memory(g + W.G_RELOAD, saved["reload"])
        except errors:
            pass
        return {"id": iid, "name": W.name(iid), "was": held["name"], "verified": False,
                "reason": "the swap did not read back: his own weapon put back"}
    return {"id": iid, "name": W.name(iid), "was": held["name"], "loaded": loaded, "levels": lv["packed"],
            "verified": True}


def _round_weapon(ad, snap: dict, st: dict) -> dict | None:
    """random_weapon / loadout_weapon for this snapshot: once a round, as soon as the game's own state says it is live
    (playing, in control, its clock running, the player in RAM) - never on a load, an intro or a menu. A round is the
    game's: a new intro (a boot's first, or the Continue after a death) starts one. Returns the give when one was
    made."""
    game = snap.get("game")
    if not isinstance(game, dict):
        return None                                     # no game state read: nothing is written
    phase, last = game.get("phase"), st.get("rw_phase")
    st["rw_phase"] = phase
    # A round is the game's: he enters play from the load's intro, from the results screen's next round, from the death
    # screen's Continue, or (no screen read) from nothing at all. Every such entry is a new round, so every round gets
    # its weapon - a results -> playing restart used to keep the last round's epoch (the operator: "mods_weapon_given was
    # 4 for a whole session"). A case / grab / hold screen in the same round is not an entry.
    if phase == "playing" and last in (None, "intro", "results", "dead", "none", "paused"):
        st["rw_epoch"] = st.get("rw_epoch", 0) + 1
    elif phase in D.ROUND_PHASES and phase != "playing" and "rw_epoch" not in st:
        st["rw_epoch"] = 0                              # watching before the first round: nothing given yet
    epoch = st.get("rw_epoch")
    if epoch is None or st.get("rw_given_epoch") == epoch:
        return None
    if not (phase == "playing" and game.get("in_control") and game.get("clock_running")):
        return None
    if not isinstance((snap.get("player") or {}).get("ptr"), int) or st.get("hand_saved") is not None:
        return None                                     # no player yet, or a grenade in his hand (after it)
    base = snap["module_base"]
    try:
        ch = bytes(ad.read_memory(base + W.GAME_OBJ + W.G_CHARACTER, 1))[0]
    except (ValueError, OSError, IndexError):
        return None
    if W.CHARACTERS.get(ch, ch) in (st.get("loadouts") or {}):
        st["rw_given_epoch"] = epoch                    # the code patch built his loadout (LOADOUT_CODE_PATCH)
        return None
    tries = (st.get("rw_tries", 0) if st.get("rw_tries_epoch") == epoch else 0) + 1
    st["rw_tries"], st["rw_tries_epoch"] = tries, epoch
    import random as _random
    last_id = (st.get("weapon_given") or {}).get("id")
    given = _give_weapon(ad, base, st, _random.Random(), fixed=st.get("loadout_weapon") or None,
                         exclude=() if last_id is None else (last_id,))
    if given is None:
        if tries >= ROUND_WEAPON_TRIES:
            st["rw_given_epoch"] = epoch
            st["weapon_given"] = {"verified": False, "round": epoch, "reason": "his hand could not be read"}
        return None
    given.update(round=epoch, character=W.CHARACTERS.get(ch, ch))
    if given.get("verified") and float(st.get("fire_rate", 1.0) or 1.0) > 1.0:
        # The 20x tables in the round's own give, every round (not only pre_round's boot): a stage load re-reads the
        # module's data, and the round the weapon is drawn into must be built with them. Reported per round with the
        # weapon (the operator: "there is no fire-table stat").
        n = _apply_fire_rate(ad, base, st)
        given["fire_tables"] = n
        st["rf_applied_round"], st["rf_tables_round"] = epoch, n
        st["fire_tables_total"] = st.get("fire_tables_total", 0) + n
        rounds = st.setdefault("weapon_rounds", [])
        rounds.append({"round": epoch, "weapon": given.get("name"), "id": given.get("id"), "fire_tables": n,
                       "at": round(time.time(), 1)})
        del rounds[:-12]
    st["weapon_given"] = given
    if given.get("verified") or tries >= ROUND_WEAPON_TRIES or ("reason" in given and "id" not in given):
        st["rw_given_epoch"] = epoch                    # given, tried enough, or nothing in his hand to swap
    return given


def _write_hand(ad, base: int, item: int, g: int, iid: int, row: dict, packed: int, loaded: int, nibbles: tuple,
                reload: int) -> None:
    """The in-hand swap's writes (the random weapon's, and the bot's grenades): the held item's id, its levels and
    rounds, the item manager's held id, the game state's class / variant / level nibbles and its reload nibble."""
    ad.write_memory(item, struct.pack("<H", iid))
    ad.write_memory(item + 6, struct.pack("<HH", packed, loaded << 3))
    ad.write_memory(base + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack("<H", iid))
    ad.write_memory(g + W.G_CLASS, bytes([row["class"], row["variant"], 0, *nibbles]))
    ad.write_memory(g + W.G_RELOAD, bytes([reload]))


# The bot's grenades (re4_switch.THROWS): re4_switch.HAND_REQUEST asks for an item in his hand (a hand / incendiary / flash
# grenade), then None for the gun back; HAND_STATE is the answer. The swap is _give_weapon's (_write_hand) on the held
# item, after the hand's own bytes are kept (the held item's 14 bytes, the item manager's held pointer and id, the game
# state's class bytes and reload) - written back, and read back, for the gun. A request older than HAND_FRESH_S (a bot
# gone mid-throw) is the gun back. A new boot drops what was kept (maintain: the state's counts go), never writing an
# old boot's bytes. NOT seen live yet: re4_switch.THROWS stays off until a watched round.
HAND_FRESH_S = 5.0
HAND_CLASS_N = W.G_CAPACITY - W.G_CLASS + 1             # class, variant, the byte between, firepower, speed, capacity


def _hand_save(ad, base: int) -> dict | None:
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    r = W.Reader(rd, base)
    held, g = r.equipped(), r.game_obj()
    if held is None or g != base + W.GAME_OBJ:
        return None
    mgr = base + W.ITEM_MGR
    return {"item": held["addr"], "item_bytes": rd(held["addr"], W.ITEM_SZ), "was": held["id"], "g": g,
            "mgr": rd(mgr + W.M_EQUIPPED, W.M_EQUIPPED_ID + 2 - W.M_EQUIPPED), "cls": rd(g + W.G_CLASS, HAND_CLASS_N),
            "reload": rd(g + W.G_RELOAD, 1)}


def _hand_hold(ad, base: int, iid: int, saved: dict) -> bool:
    rd = lambda a, n: bytes(ad.read_memory(a, n))                         # noqa: E731
    rows = W.decode_weapon_table(rd(base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
    row = rows.get(iid)
    if row is None:
        raise ValueError(f"no weapon row for {W.name(iid)}")
    _write_hand(ad, base, saved["item"], saved["g"], iid, row, 0, 1, (0, 0, 0), 0)
    return W.decode_item(rd(saved["item"], W.ITEM_SZ), saved["item"])["id"] == iid


def _hand_restore(ad, base: int, saved: dict) -> bool:
    ad.write_memory(saved["item"], saved["item_bytes"])
    ad.write_memory(base + W.ITEM_MGR + W.M_EQUIPPED, saved["mgr"])
    ad.write_memory(saved["g"] + W.G_CLASS, saved["cls"])
    ad.write_memory(saved["g"] + W.G_RELOAD, saved["reload"])
    return bytes(ad.read_memory(saved["item"], W.ITEM_SZ)) == saved["item_bytes"]


def _hand(ad, snap: dict) -> int:
    """re4_switch.HAND_REQUEST on this snapshot (see above): the writes made (0 / 1); HAND_STATE says what is in hand."""
    req, ans = D.HAND_REQUEST, D.HAND_STATE
    base, seq = snap.get("module_base"), req.get("seq")
    if seq is None or not isinstance(base, int):
        return 0
    st = _state(ad)
    fresh = isinstance(req.get("at"), (int, float)) and time.monotonic() - req["at"] <= HAND_FRESH_S
    want = req.get("item") if fresh else None
    saved = st.get("hand_saved")
    errors = (ValueError, OSError, RuntimeError, struct.error, KeyError)
    if want is None:
        if saved is None:
            if ans.get("seq") != seq:
                ans.update(seq=seq, item=None, verified=True, error="")
            return 0
        try:
            ok, err = _hand_restore(ad, base, saved), ""
        except errors as exc:
            ok, err = False, f"{type(exc).__name__}: {exc}"[:120]
        st.pop("hand_saved", None)
        st["hand_restores"] = st.get("hand_restores", 0) + 1
        ans.update(seq=seq, item=None, verified=ok, error=err or ("" if ok else "the gun's bytes did not read back"))
        return 1
    if ans.get("seq") == seq:
        return 0
    try:
        if saved is None:
            saved = _hand_save(ad, base)
            if saved is None:
                ans.update(seq=seq, item=None, verified=False, error="nothing in his hand to swap")
                return 0
            st["hand_saved"] = saved
        ok, err = _hand_hold(ad, base, int(want), saved), ""
    except errors as exc:
        ok, err = False, f"{type(exc).__name__}: {exc}"[:120]
    if not ok and st.get("hand_saved") is not None:      # a swap that did not take: the gun's bytes straight back
        try:
            _hand_restore(ad, base, st["hand_saved"])
        except errors:
            pass
        st.pop("hand_saved", None)
    st["hand_swaps"] = st.get("hand_swaps", 0) + 1
    ans.update(seq=seq, item=int(want) if ok else None, verified=bool(ok),
               error=err or ("" if ok else "the item did not read back"))
    return 1


def _patch_loadout(ad, base: int, picks: dict) -> dict:
    """The Mercenaries loadout's code rewritten slot by slot (re4_weapons.LOADOUT_SLOTS): picks {character: [weapon id
    per slot]} (None puts a slot's own weapon back). A slot is all or nothing: every word of it (the give, the
    inventory searches, the levels, the first magazine, the mask) is read and checked against the build's own word or
    one this writes first (re4_weapons.slot_word_ok); a slot with any other word is never touched. Then each word is
    written and read back; a write that fails part-way puts the slot's words written so far back. Returns
    {character: [weapon id per patched slot]}."""
    done: dict = {}
    for ch, ids in picks.items():
        slots = W.LOADOUT_SLOTS.get(ch)
        if not slots:
            continue
        for k, slot in enumerate(slots):
            want = ids[k] if k < len(ids) else None
            try:
                words = W.slot_words(slot, want)
                roles = {off: role for off, role, _ in slot["code"]}
                cur = {off: struct.unpack("<I", bytes(ad.read_memory(base + off, 4)))[0] for off, _, _ in words}
            except (ValueError, OSError, RuntimeError, struct.error):
                continue
            if not all(W.slot_word_ok(roles[off], orig, cur[off]) for off, orig, _ in words):
                continue                                     # not this build's code: never patched
            written: list = []
            ok = True
            for off, _orig, new in words:
                word = struct.pack("<I", new)
                try:
                    ad.write_memory(base + off, word)
                    ok = bytes(ad.read_memory(base + off, 4)) == word
                except (ValueError, OSError, RuntimeError, struct.error):
                    ok = False
                if not ok:
                    break
                written.append(off)
            if not ok:
                for off in written:                          # never leave a give without its searches
                    try:
                        ad.write_memory(base + off, struct.pack("<I", cur[off]))
                    except (ValueError, OSError, RuntimeError, struct.error):
                        pass
                continue
            done.setdefault(ch, []).append(want if want is not None else slot["id"])
    return done


def _fits(ch: int, ids) -> bool:
    try:
        return W.case_fits(W.merc_gives(ch, ids))
    except ValueError:                                   # a weapon with no measured case shape: never given as code
        return False


def _fitting(draws: dict) -> dict:
    """The draws with every character whose gives the case cannot hold put back to his own (None per slot)."""
    return {ch: (ids if _fits(ch, ids) else [None] * len(ids)) for ch, ids in draws.items()}


def _draw_loadouts(rng, fixed: int | None = None, tries: int = 64) -> dict:
    """{character: [weapon id per slot]}: the fixed pick in the equipped slot, else random high-powered campaign
    weapons (no repeat within a character) - only a draw whose every give fits the case (re4_weapons.case_fits: the
    give leaves out what has no room, and the code after it then reads a null item). A character with no fitting draw
    in `tries` keeps his own loadout (None per slot)."""
    out = {}
    for ch, slots in W.LOADOUT_SLOTS.items():
        out[ch] = [None] * len(slots)
        for _ in range(tries):
            pool = [i for i in W.HIGH_POWER if W.max_levels(i) is not None and i in W.ITEM_SHAPE]
            rng.shuffle(pool)
            ids = pool[:len(slots)]
            if fixed is not None:
                k = [bool(s.get("equipped")) for s in slots].index(True)
                ids = [i for i in ids if i != fixed][:len(slots)]
                ids.insert(k, fixed)
                ids = ids[:len(slots)]
            if _fits(ch, ids):
                out[ch] = ids
                break
    return out


def loadout_weapon(ad, weapon, snap: dict | None = None) -> dict:
    """Every character's equipped gun from the next round: this campaign weapon at max level (RE5's weapon_override).
    None / 0 puts the game's own loadouts back."""
    st = _state(ad)
    iid = int(weapon) if weapon else None
    if iid is not None and W.max_levels(iid) is None:
        return {"verified": False, "reason": f"no max-level row for weapon {iid:#x} ({W.name(iid)})"}
    refused = _code_patch_refusal(ad)
    if refused:
        st["loadout_weapon"] = iid
        _save(st)
        st.pop("rw_given_epoch", None)                 # the round under way gets it too
        return {"verified": True, "weapon": W.name(iid) if iid else "the game's own", "route": "in_hand",
                "note": "every round: this weapon in his hand at max level as soon as the round is live (data writes, "
                        "read back; no code is written)"}
    base = (snap or {}).get("module_base")
    if not isinstance(base, int):
        return {"verified": False, "reason": "RE4 is not in memory yet"}
    picks = _fitting({ch: [iid if s.get("equipped") else None for s in slots] for ch, slots in W.LOADOUT_SLOTS.items()})
    done = _patch_loadout(ad, base, picks)
    st["loadout_weapon"] = iid
    _save(st)
    return {"verified": bool(done), "weapon": W.name(iid) if iid else "the game's own", "characters": len(done),
            "note": "from the next round: every character starts with it, equipped, at max level"}


def random_weapon(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["random_weapon"] = bool(on)
    _save(st)
    st.pop("rw_given_epoch", None)                     # a fresh pick on the next live snapshot of a round
    st.pop("loadout_drawn", None)
    return {"random_weapon": bool(on), "verified": True,
            "route": "in_hand" if _code_patch_refusal(ad) else "code_patch",
            "note": "every round: a random max-level high-powered campaign weapon in his hand as soon as the round is "
                    "live (data writes, read back; his own weapon put back if a write does not hold)"}


def one_hit(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["one_hit"] = bool(on)
    _save(st)
    capped = _cap_health(ad, (snap or {}).get("enemies"), 0.0) if on and snap else 0
    return {"one_hit": bool(on), "verified": True, "capped": capped,
            "note": "every living Ganado at 1 health: the first hit kills"}


# --- the clock ----------------------------------------------------------------------------------------------------
def _clock(ad, snap: dict | None) -> tuple[int, float, float] | None:
    """(address of the clock's f32, seconds left, units per second) or None. The HUD's own clock (snap clock_source
    "countdown": re4_switch.COUNTDOWN, the struct's address) keeps frames at 30 a second in its +8; ClockFinder's float
    (the fallback) is seconds."""
    addr = (snap or {}).get("clock_addr")
    if not isinstance(addr, int):
        return None
    scale = 1.0
    if (snap or {}).get("clock_source") == "countdown":
        addr, scale = addr + D.CD_FRAME, D.CD_FPS
    try:
        v = struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0] / scale
    except (ValueError, OSError, struct.error):
        return None
    return (addr, v, scale) if math.isfinite(v) and -1.0 <= v <= CLOCK_MAX_S else None


def _write_clock(ad, addr: int, value: float, scale: float = 1.0) -> float:
    """The clock at `value` seconds (in its own units: x scale); the value read back, in seconds."""
    ad.write_memory(addr, struct.pack("<f", value * scale))
    return struct.unpack("<f", bytes(ad.read_memory(addr, 4)))[0] / scale


def _clock_op(ad, snap, *, add=None, absolute=None) -> dict:
    found = _clock(ad, snap)
    if found is None:
        return {"verified": False, "reason": "the round clock is not read yet (re4_switch.game_state's CountDown): a "
                                              "round must be playing"}
    addr, now, scale = found
    want = (now + add) if absolute is None else absolute
    want = min(max(want, 1.0), CLOCK_MAX_S)
    try:
        back = _write_clock(ad, addr, want, scale)
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
    static tables (fire rate, firepower) - so the round the walk is about to start is built with them. The random /
    chosen weapon is NOT code here (LOADOUT_CODE_PATCH is off): maintain puts it in his hand once the round is live.
    Only with the patch on (and not under NCE) are the Mercenaries loadouts rewritten, from case-fitting draws."""
    mem = m if m is not None else Mem(ad)
    base = D.module_base(mem)
    if base is None:
        # The runner calls this once a boot, on the first menu it reads: RE4's module may not be readable yet. A
        # background retry puts the settings in as soon as it is (the menus take far longer than that to a round).
        _retry_pre_round(ad, mem)
        return {"skipped": "RE4's module not readable yet: retrying in the background"}
    out: dict = {}
    with _LOCK:
        st = _state(ad)
        boot = _boot(ad, base)
        if st.get("pre_round_boot") == boot:
            return {"skipped": "already put into this boot", "boot": boot}
        st["pre_round_boot"] = out["boot"] = boot
        if st.get("weapon_power", 1.0) != 1.0 or st.get("max_level"):
            out["power_rows"] = _apply_power(ad, base, st)
            st["fp_applied_boot"] = boot
        if st.get("fire_rate", 1.0) != 1.0:
            out["fire_tables"] = _apply_fire_rate_boot(ad, base, st, boot)
        refused = _code_patch_refusal(ad) if st.get("random_weapon") or st.get("loadout_weapon") else None
        if refused:
            st["loadouts"] = {}                         # nobody's loadout is code: _round_weapon gives in hand
            out["loadout_route"], out["loadout_code"] = "in_hand", refused
        elif st.get("random_weapon") or st.get("loadout_weapon"):
            import random as _random
            fixed = st.get("loadout_weapon")
            draws = _draw_loadouts(_random.Random(), fixed) if st.get("random_weapon") else \
                {ch: [fixed if s.get("equipped") else None for s in slots] for ch, slots in W.LOADOUT_SLOTS.items()}
            draws = _fitting(draws)
            done = _patch_loadout(ad, base, draws)
            st["loadout_drawn"] = boot
            # only a character whose loadout was changed: one left stock gets the weapon in hand (_round_weapon)
            st["loadouts"] = {W.CHARACTERS.get(ch, ch): [W.name(i) for i in ids] for ch, ids in done.items()
                              if any(i is not None for i in draws.get(ch, ()))}
            out["loadouts"] = len(done)
        st["pre_round_result"] = dict(out, at=round(time.time()))
    return out


def _retry_pre_round(ad, mem, limit_s: float = 60.0) -> None:
    """pre_round again once a second until RE4's module is readable (at most limit_s); one retry per adapter."""
    st = _state(ad)
    if st.get("pre_round_retrying"):
        return
    st["pre_round_retrying"] = True

    def run():
        end = time.monotonic() + limit_s
        try:
            while time.monotonic() < end:
                time.sleep(1.0)
                try:
                    if D.module_base(mem) is not None:
                        pre_round(ad, mem)
                        return
                except Exception as exc:                     # noqa: BLE001 - a retry never takes the worker down
                    st["pre_round_result"] = {"error": f"{type(exc).__name__}: {exc}"[:160]}
                    return
            st["pre_round_result"] = {"skipped": f"RE4's module never readable in {limit_s:.0f} s"}
        finally:
            st["pre_round_retrying"] = False

    threading.Thread(target=run, name="re4-pre-round", daemon=True).start()


def _unstick(ad, snap) -> int:
    """Clear the CATCHED status bit while it is set, so a grab (a QTE) can no longer hold him.

    ``Status_flg`` is u32[4] at player + PG_STATUS (0x5090) and a Ganado's hold is word 1 & 0x8000 (re4_switch
    STA_PL_CATCHED); the game's own mash frees him through the same flag, so clearing it ends the hold immediately -
    the operator, 2026-11-12: "the bot is still failing QTE events ... make sure that they always succeed and that the
    bot is fully reactive to QTE events no matter what, and they never fail". Tapping A at a fixed rate was the whole
    of the old answer (NOT_IN_CONTROL_KEYS), which cannot win a stick-wiggle QTE at all. -> writes made.
    """
    p = (snap or {}).get("player") or {}
    base = (snap or {}).get("module_base")
    if not isinstance(base, int):
        return 0
    # The status block lives off pG, the player GLOBAL at module + PG_PTR_VAR - not off the player unit in
    # snap["player"]["ptr"]. Reading the unit's address instead silently cleared nothing (the write landed on unrelated
    # memory), which is why a grab still killed him with mods_qte_unstuck never appearing: live 2026-11-12, doing=grabbed
    # with hp 0/1560.
    try:
        ptr = struct.unpack("<Q", bytes(ad.read_memory(base + D.PG_PTR_VAR, 8)))[0]
    except (ValueError, OSError, RuntimeError, struct.error):
        return 0
    if not isinstance(ptr, int) or not D.ptr_ok(ptr):
        return 0
    word_i, mask = D.STA_PL_CATCHED
    addr = ptr + D.PG_STATUS + 4 * word_i
    try:
        word = struct.unpack("<I", bytes(ad.read_memory(addr, 4)))[0]
        if not word & mask:
            return 0
        want = word & ~mask
        ad.write_memory(addr, struct.pack("<I", want))
        return int(struct.unpack("<I", bytes(ad.read_memory(addr, 4)))[0] == want)
    except (ValueError, OSError, RuntimeError, struct.error):
        return 0


def maintain(ad, snap: dict | None = None) -> dict:
    """Every RAM snapshot of a round: the health caps, the time per kill, the clock write's confirmation."""
    if not snap or snap.get("module_base") is None:
        return {}
    out: dict = {}
    with _LOCK:
        st = _state(ad)
        boot = _boot(ad, snap["module_base"])
        if st.get("boot") is None:
            st["boot"] = boot
        elif st["boot"] != boot:                         # a new boot: the operator's settings stay, the counts go
            keep = {k: st[k] for k in SAVED_KEYS + ("fire_gap_orig", "_owner", "weapon_rows") if k in st}
            if st.get("pre_round_boot") == boot:         # what pre_round already put into this boot
                keep.update({k: st[k] for k in ("pre_round_boot", "pre_round_result", "loadouts", "loadout_drawn",
                                                 "fp_applied_boot", "rf_applied_boot") if k in st})
            st.clear()
            st.update(keep, boot=boot)
        n = _hand(ad, snap)                              # the bot's grenade in hand / the gun back (re4_switch.THROWS)
        if n:
            out["hand_writes"] = n
        # a hold is a QTE: clear its status bit rather than hoping a mash wins it
        n = _unstick(ad, snap)
        if n:
            st["qte_unstuck"] = st.get("qte_unstuck", 0) + n
            out["qte_unstuck"] = n
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
        # The THRESHOLD heal (the operator, 2026-11-12: "they have unlimited healing items, so they should always have
        # the ability to use a first aid spray and heal themselves if they need to in the game ... I don't want them
        # bringing up the item screen"). This is NOT unlimited life: nothing is written while he is at or above
        # heal_below, and one write happens per hurt snapshot, so it behaves as using a healing item the moment he is
        # hurt. It is the only route that exists - the hand swap resolves WEAPON rows (re4_switch_mods._hand_hold raises
        # "no weapon row for First Aid Spray") and RE4 has no "hold a spray" state, so the swap can never do it.
        below = st.get("heal_below")
        if below and not st.get("unlimited_health"):
            p = (snap or {}).get("player") or {}
            hp, top = p.get("hp"), p.get("hp_max")
            if isinstance(hp, int) and isinstance(top, int) and top > 0 and 0 < hp <= top * float(below):
                n = _keep_life(ad, snap)
                if n:
                    st["heals"] = st.get("heals", 0) + n
                    out["heals"] = n
                    out["heal_from"] = st.get("last_heal_from")
                    out["max_deficit"] = st.get("max_deficit")
        if (st.get("weapon_power", 1.0) != 1.0 or st.get("max_level")) and st.get("fp_applied_boot") != boot:
            out["power_rows"] = _apply_power(ad, snap["module_base"], st)   # once a boot (the table is static data)
            st["fp_applied_boot"] = boot
        if _fire_tables_due(st, boot):
            out["fire_tables"] = _apply_fire_rate_boot(ad, snap["module_base"], st, boot)
        if st.get("infinite_ammo"):
            n = _keep_mag(ad, snap["module_base"], st)
            st["mag_refills"] = st.get("mag_refills", 0) + n
            if n:
                out["mag_refills"] = n
            n = _keep_arrows(ad, snap["module_base"], st)    # the bow's arrows: an item of their own
            st["arrow_refills"] = st.get("arrow_refills", 0) + n
            if n:
                out["arrow_refills"] = n
        if st.get("fire_rate", 1.0) > 1.0 or st.get("motion_rate"):
            n = _motion_rate(ad, snap, st)                   # the bow / throwables: their motion x fire_rate
            if n:
                out["motion_rate_writes"] = n
        # The random (or chosen) weapon: in his hand by data writes once the round is live, every round
        # (_round_weapon). The loadout code patch is off (LOADOUT_CODE_PATCH: it hung every stage load).
        if st.get("random_weapon") or st.get("loadout_weapon"):
            given = _round_weapon(ad, snap, st)
            if given is not None and given.get("verified"):
                # every value in this dict is summed by the playbook's mods panel (re4switch_bot._maintain_mods): numbers
                # only, or the mission dies with "int + dict". The weapon's name/round live in status()'s
                # weapon_given / weapon_rounds (st["weapon_rounds"]), which is where the round report reads them.
                out["weapon_given"] = 1
                if given.get("fire_tables"):
                    out["fire_tables"] = given["fire_tables"]      # this round's 20x tables, with its weapon
        if st.get("aim_lock"):
            ram0, sway0 = st.get("aim_ram_writes", 0), st.get("aim_sway_zeroed", 0)
            n = _aim(ad, snap)
            st["aim_writes"] = st.get("aim_writes", 0) + n
            if n:
                out["aim_writes"] = n
            if st.get("aim_ram_writes", 0) > ram0:              # the steady aim's writes (_steady)
                out["aim_ram_writes"] = st["aim_ram_writes"] - ram0
            if st.get("aim_sway_zeroed", 0) > sway0:
                out["aim_sway_zeroed"] = st["aim_sway_zeroed"] - sway0
        new = _kills_of(snap, st)
        kt = st.get("kill_time") or {}
        if new and kt.get("on") and kt.get("seconds", 0) > 0:
            found = _clock(ad, snap)
            if found is not None and found[1] > 0:
                try:
                    _write_clock(ad, found[0], min(found[1] + new * kt["seconds"], CLOCK_MAX_S), found[2])
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
           # heal_below is shown so the threshold heal can be verified from the live telemetry alone: a setting that
           # never loaded cannot be distinguished from one that loaded and never triggered (live 2026-11-12: the heal
           # was configured, dropped by SAVED_KEYS, and the only symptom was a health bar that kept falling).
           "heal_below": st.get("heal_below"), "heals": st.get("heals", 0),
           "infinite_ammo": bool(st.get("infinite_ammo")), "fire_rate_x": st.get("fire_rate", 1.0),
           "random_weapon": bool(st.get("random_weapon")), "weapon_given": st.get("weapon_given"),
           "random_weapon_route": "in_hand" if _code_patch_refusal(ad) else "code_patch",
           "weapon_primary": sorted(W.name(i) for i in PRIMARY), "magnum_share": MAGNUM_SHARE,
           "weapon_rounds": st.get("weapon_rounds") or [], "fire_tables_round": st.get("rf_tables_round"),
           "fire_tables_total": st.get("fire_tables_total", 0),
           "loadouts": st.get("loadouts"), "loadout_weapon": st.get("loadout_weapon"),
           "weapon_power_x": st.get("weapon_power", 1.0), "max_level": bool(st.get("max_level")),
           "aim_lock": bool(st.get("aim_lock")), "aim_writes": st.get("aim_writes", 0),
           "aim_ram_writes": st.get("aim_ram_writes", 0), "aim_sway_zeroed": st.get("aim_sway_zeroed", 0),
           "aim_sway_was": st.get("aim_sway_was"), "aim_ram_refused": st.get("aim_ram_refused", 0),
           "mag_refills": st.get("mag_refills", 0), "pre_round": st.get("pre_round_result"),
           "motion_rate_on": (st.get("motion_rate") or {}).get("kind"), "motion_rate_kind": st.get("motion_rate_kind"),
           "motion_rate_writes": st.get("motion_rate_writes", 0), "motion_rate_restores": st.get("motion_rate_restores", 0),
           "motion_rate_refused": st.get("motion_rate_refused", 0), "arrow_refills": st.get("arrow_refills", 0),
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
            _state(ad).pop("fp_applied_boot", None)
            return r
        if op == "aim_lock":
            return aim_lock(ad, on)
        if op == "infinite_ammo":
            r = infinite_ammo(ad, on, snap)
            _state(ad).pop("rf_applied_boot", None)
            return r
        if op == "fire_rate":
            r = fire_rate(ad, 1.0 if multiplier is None else multiplier, snap)
            _state(ad).pop("rf_applied_boot", None)
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
