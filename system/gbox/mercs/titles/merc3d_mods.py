"""Live mods for Resident Evil: The Mercenaries 3D (3DS, citra_libretro in RetroArch), the topbar/PiP panel's backend.

Every write goes through the adapter's write_memory (gbox.citra_memory page table) and is read back; an op answers
verified=True only when the read-back matches. Addresses are the ones merc3d_3ds measured live (sMission / sPlayer):
mission +0x68 f32 mLimitSec (seconds left), player unit +0xCC4 f32 vitality, +0xCCC f32 its maximum.
Nothing here touches saves or the ROM; the writes are to the running round's RAM only.
"""
from __future__ import annotations

import math
import struct
import threading
import time

from . import merc3d_3ds as T

GAME_IDS = frozenset({"0ed22ae742e1b56b"})
OPS = ("status", "add_time", "set_time", "heal", "unlimited_health", "revert_all")
TIME_MIN, TIME_MAX = 1.0, 3600.0
_LOCK = threading.RLock()
_STATE = {"unlimited_health": False}
_THREADS: dict[int, threading.Thread] = {}


def is_merc3d(g) -> bool:
    if not isinstance(g, dict):
        return False
    ids = {str(g.get(k) or "") for k in ("game_id", "title_id", "map_id")}
    return bool(ids & GAME_IDS) or T.TITLE_ID in {i.upper() for i in ids}


class _Mem:
    """The rd(addr, n) view merc3d_3ds expects, over an adapter."""
    def __init__(self, ad):
        self.ad = ad

    def rd(self, a, n):
        return bytes(self.ad.read_memory(a, n))

    def wr(self, a, data):
        self.ad.write_memory(a, bytes(data))


def _f32(m, addr):
    return struct.unpack("<f", m.rd(addr, 4))[0]


def _write_f32(m, addr, value) -> bool:
    data = struct.pack("<f", value)
    m.wr(addr, data)
    return m.rd(addr, 4) == data


def _mission_ptr(m):
    sm = T._u32(m, T.S_MISSION)
    return sm if T.ptr_ok(sm) else None


def _playing(m) -> bool:
    return T.snapshot(m).get("player") is not None and _mission_ptr(m) is not None


def status(ad, m=None) -> dict:
    m = m or _Mem(ad)
    mi = T.mission(m)
    pu = T.player_unit(m)
    hp = hp_max = None
    if pu:
        hp, hp_max = _f32(m, pu + T.P_VIT), _f32(m, pu + T.P_VIT_MAX)
    return {"verified": True, "title": "merc3d", "in_round": mi is not None and pu is not None,
            "timer": mi["timer"] if mi else None, "score": mi["score"] if mi else None,
            "combo": mi["combo"] if mi else None, "hp": hp, "hp_max": hp_max,
            "unlimited_health": _STATE["unlimited_health"]}


def set_time(ad, seconds, m=None) -> dict:
    m = m or _Mem(ad)
    sm = _mission_ptr(m)
    if sm is None:
        return {"verified": False, "error": "no round: sMission is not set"}
    seconds = float(seconds)
    if not math.isfinite(seconds):
        return {"verified": False, "error": "seconds must be finite"}
    value = min(max(seconds, TIME_MIN), TIME_MAX)
    ok = _write_f32(m, sm + T.M_LEFT, value)
    return {"verified": ok, "op": "set_time", "timer": value}


def add_time(ad, seconds, m=None) -> dict:
    m = m or _Mem(ad)
    sm = _mission_ptr(m)
    if sm is None:
        return {"verified": False, "error": "no round: sMission is not set"}
    seconds = float(seconds)
    if not math.isfinite(seconds) or abs(seconds) > TIME_MAX:
        return {"verified": False, "error": "seconds must be within -3600..3600"}
    return set_time(ad, _f32(m, sm + T.M_LEFT) + seconds, m) | {"op": "add_time", "added": seconds}


def heal(ad, m=None) -> dict:
    m = m or _Mem(ad)
    pu = T.player_unit(m)
    if pu is None:
        return {"verified": False, "error": "no player unit"}
    top = _f32(m, pu + T.P_VIT_MAX)
    if not math.isfinite(top) or top <= 0:
        return {"verified": False, "error": "implausible max vitality"}
    return {"verified": _write_f32(m, pu + T.P_VIT, top), "op": "heal", "hp": top}


def _loop(ad, token):
    m = _Mem(ad)
    while _STATE["unlimited_health"] and _THREADS.get(id(ad)) is token:
        try:
            pu = T.player_unit(m)
            if pu:
                hp, top = _f32(m, pu + T.P_VIT), _f32(m, pu + T.P_VIT_MAX)
                if 0 < hp < top and top > 0:      # never revive a unit already at 0
                    _write_f32(m, pu + T.P_VIT, top)
        except Exception:
            pass
        time.sleep(0.1)


def unlimited_health(ad, on: bool) -> dict:
    with _LOCK:
        _STATE["unlimited_health"] = bool(on)
        if on:
            t = threading.Thread(target=lambda: _loop(ad, _THREADS[id(ad)]), daemon=True)
            _THREADS[id(ad)] = t
            t.start()
        else:
            _THREADS.pop(id(ad), None)
    return {"verified": True, "op": "unlimited_health", "on": bool(on)}


def run(ad, op="status", multiplier=None, on=True, seconds=None, **_extra) -> dict:
    op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
    op = {"unlimited_hp": "unlimited_health", "god_mode": "unlimited_health", "health": "heal"}.get(op, op)
    if op not in OPS:
        return {"verified": False, "error": f"merc3d has no op {op!r}; ops: {', '.join(OPS)}"}
    if op == "status":
        return status(ad)
    if op == "revert_all":
        unlimited_health(ad, False)
        return {"verified": True, "op": "revert_all", "status": status(ad)}
    if op == "unlimited_health":
        return unlimited_health(ad, on)
    if op in ("add_time", "set_time"):
        if seconds is None:
            return {"verified": False, "error": f"{op} needs seconds"}
        return (add_time if op == "add_time" else set_time)(ad, seconds)
    return heal(ad)
