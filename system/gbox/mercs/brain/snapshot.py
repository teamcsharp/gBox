"""The normalized snapshot: what every title adapter hands the brain, in the games' world units (cm, y up; radians).

    {"title": "010018100CD46000",
     "t": the brain's clock (seconds),
     "player": {"id": the title's own (an address, a slot), "pos": (x, y, z), "heading": radians (atan2(dx, dz):
                forward = (sin, 0, cos)), "pitch": radians or None (+ up), "hp": int, "hp_max": int,
                "state": STATES (what the body is doing, from the title's own bytes), "raw_state": those bytes,
                "weapon": {"id": int, "kind": str or None, "rounds": int or None, "auto": bool} or None},
     "aim": {"up": bool (the gun is up: the laser, or the title's motion byte vouching for it), "ray": ((ox, oy, oz),
             (dx, dy, dz)) or None (the laser's muzzle and dot), "fresh": bool (read this tick, not a stand-in)},
     "enemies": [{"id": the title's own, "pos": (x, y, z), "vel": (vx, vy, vz) cm/s or None, "hp": int,
                  "hp_max": int, "class": str or None (the class name or id), "state": int or None (an animation /
                  action byte), "boss": bool, "threat": {"grab": bool, "attacking": bool}}],
     "round": {"timer": seconds left or None, "kills": int or None, "combo": int or None, "combo_timer": float or None,
               "score": int or None}}

Unknown values are None (never a guess). Tracker fills each enemy's velocity from his last two positions under the same
id, which a title can also read from RAM directly (then it sets "vel" itself).
"""
from __future__ import annotations

import math

STATES = ("free", "aiming", "firing", "reloading", "held", "dying", "hit", "dead", "unknown")
VEL_WINDOW_S = 0.5                     # a position older than this gives no velocity (a respawn, a stall)


def blank(title: str, t: float) -> dict:
    return {"title": title, "t": t, "player": None, "aim": {"up": False, "ray": None, "fresh": False},
            "enemies": [], "round": {"timer": None, "kills": None, "combo": None, "combo_timer": None, "score": None}}


def check(snap: dict) -> list:
    """What is wrong with a normalized snapshot (an empty list: nothing): the adapters' tests run every snapshot through
    this, so a title cannot hand the brain a field in another shape."""
    bad = []
    if not isinstance(snap, dict) or not isinstance(snap.get("title"), str):
        return ["not a snapshot (title)"]
    p = snap.get("player")
    if p is not None:
        if not _vec(p.get("pos")):
            bad.append("player.pos")
        if not isinstance(p.get("heading"), (int, float)) or not math.isfinite(p["heading"]):
            bad.append("player.heading")
        if p.get("state") not in STATES:
            bad.append("player.state")
    aim = snap.get("aim") or {}
    ray = aim.get("ray")
    if ray is not None and not (isinstance(ray, (tuple, list)) and len(ray) == 2 and _vec(ray[0]) and _vec(ray[1])):
        bad.append("aim.ray")
    for k, e in enumerate(snap.get("enemies") or ()):
        if not _vec(e.get("pos")):
            bad.append(f"enemies[{k}].pos")
        if e.get("vel") is not None and not _vec(e["vel"]):
            bad.append(f"enemies[{k}].vel")
        if not isinstance(e.get("hp"), int):
            bad.append(f"enemies[{k}].hp")
    return bad


def _vec(v) -> bool:
    return isinstance(v, (tuple, list)) and len(v) == 3 and all(isinstance(x, (int, float)) and math.isfinite(x)
                                                                 for x in v)


class Tracker:
    """Enemy velocities from successive snapshots: each enemy id's last position and time."""

    def __init__(self):
        self.seen: dict = {}

    def update(self, snap: dict) -> dict:
        t = snap.get("t")
        live = set()
        for e in snap.get("enemies") or ():
            key = e.get("id")
            live.add(key)
            last = self.seen.get(key)
            if e.get("vel") is None and last is not None and isinstance(t, (int, float)) \
                    and 0.0 < t - last[0] <= VEL_WINDOW_S:
                dt = t - last[0]
                e["vel"] = tuple((e["pos"][k] - last[1][k]) / dt for k in range(3))
            if isinstance(t, (int, float)):
                self.seen[key] = (t, tuple(e["pos"]))
        for key in [k for k in self.seen if k not in live]:
            del self.seen[key]
        return snap


def flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


def lead(e: dict, seconds: float) -> tuple:
    """Where he will be in seconds at his tracked velocity (his position without one)."""
    v = e.get("vel")
    if not v:
        return tuple(e["pos"])
    return tuple(e["pos"][k] + v[k] * seconds for k in range(3))
