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

import math
import struct
import threading
import time

from . import re4_switch as D

GAME = "010099A00BC1E000"
ENEMY_HEALTH_MIN = 0.05
CLOCK_MAX_S = 3600.0
KILL_TIME_S = 3.0
KILL_TIME_MAX_S = 30.0
CLOCK_HOLD_TOL = 1.5                    # the next read within this of what was written (the clock runs on meanwhile)

ORIG: dict = {}                         # id(adapter) -> this boot's settings
_LOCK = threading.RLock()
RELOAD_KEEP = ("ORIG", "_LOCK")


class Mem:
    """The session's guest memory for re4_switch's readers: rd() and the adapter (its guest rows find main)."""

    def __init__(self, ad):
        self.adapter = ad

    def rd(self, a: int, n: int) -> bytes:
        return self.adapter.read_memory(a, n)


def _state(ad) -> dict:
    return ORIG.setdefault(id(ad), {})


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
    capped = _cap_health(ad, (snap or {}).get("enemies"), frac) if frac < 1.0 and snap else 0
    return {"enemy_health_x": frac, "verified": True, "capped": capped,
            "note": "every living Ganado's health kept at most this share of his maximum (lowered only, read back)"}


def one_hit(ad, on: bool, snap: dict | None = None) -> dict:
    st = _state(ad)
    st["one_hit"] = bool(on)
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
            keep = {k: st[k] for k in ("enemy_health", "one_hit", "kill_time") if k in st}
            st.clear()
            st.update(keep, base=snap["module_base"])
        frac = 0.0 if st.get("one_hit") else st.get("enemy_health")
        if frac is not None and frac < 1.0:
            n = _cap_health(ad, snap.get("enemies"), frac)
            st["capped_total"] = st.get("capped_total", 0) + n
            out["capped"] = n
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
           "unlimited_health": None, "infinite_ammo": None,
           "capabilities": {
               "enemy_health": {"available": True}, "one_hit": {"available": True},
               "kill_time": {"available": True, "clock_found": bool((snap or {}).get("clock_addr")),
                             "note": "adds time once the driver has found the round clock"},
               "unlimited_health": {"available": False, "reason": "the player's life on Switch is not mapped yet "
                                                                  "(re4_switch PLAYER_HP_IN_UNIT)"},
               "infinite_ammo": {"available": False, "reason": "the RE4 Switch inventory is not mapped yet"}}}
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
        if op in ("unlimited_health", "infinite_ammo"):
            return {"verified": False, "reason": status(ad)["capabilities"][op]["reason"]}
        if op == "revert_all":
            st = _state(ad)
            for k in ("enemy_health", "one_hit", "kill_time"):
                st.pop(k, None)
            return {"verified": True, "note": "no more caps or time per kill (health already taken stays taken)"}
    raise ValueError(f"re4_switch_mods: unknown op {op!r}")
