"""Resident Evil 6 (Xbox 360 / Xenia) Mercenaries driver: the first slice.

What is verified (docs/re6.md, gbox/re6_tool.py): sPlayer = [0x83CA52FC], +0x28 = player 1's uPlayer, uPlayer +0x50
position (x, y, z big-endian f32), +0xF20 / +0xF22 s16 Life / LifeMax.

What is NOT yet found in RAM (no live Xenia session read it): the round timer, the enemy array, the time bonuses, the
aim yaw, the navmesh root. Those addresses are None in ADDR and the snapshot reports them as unknown; set them from a
live search (``configure(...)``) rather than guessing. Until then the bot has nothing to shoot at and never fires.

The one rule this module enforces regardless of the map: **fire only at an enemy with proven sight** (the game's own
visible flag, or a navmesh floor segment between player and enemy within SIGHT_R). With nobody in sight it walks the
navmesh route to the nearest reachable time bonus, else to the nearest enemy; with no mesh it holds still.

Pad keys are gbox's Xenia names (gbox/xenia.py PAD_VK): l2 aim, r2 fire, lup walk, rleft / rright turn, a = confirm.
"""
from __future__ import annotations

import math
import struct

from ..driver import Driver

S_PLAYER, PL_FIRST, PL_POS, PL_LIFE, PL_LIFE_MAX = 0x83CA52FC, 0x28, 0x50, 0xF20, 0xF22

# Unverified: None = unknown, the snapshot leaves the field out. Enemy / bonus arrays: (base, stride, count, field
# offsets) once found; "s_ai" is the static the navmesh chain starts at (re5_nav.read's s_ai).
ADDR: dict = {"timer": None, "rot": None, "enemies": None, "bonuses": None, "s_ai": None}

SIGHT_R = 2200.0                 # an enemy is fought from where the player stands within this, with open floor
SIGHT_BEND, SIGHT_SLACK = 1.1, 50.0
AIM_TOL = math.radians(8)        # fire only this close to the target's bearing
TURN_TOL = math.radians(12)
FLOOR_DY = 150.0                 # enemies this far above/below the player are on another level
ARRIVE_R = 80.0                  # a waypoint is reached this close


def configure(**addrs) -> None:
    """Set discovered addresses (keys of ADDR); an unknown key raises."""
    for k, v in addrs.items():
        if k not in ADDR:
            raise KeyError(k)
        ADDR[k] = v


def _u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def _ok(p) -> bool:
    return isinstance(p, int) and 0x40000000 <= p < 0x50000000


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def snapshot(m) -> dict:
    """The round as the bot reads it; {} off-round (no player object). Fields whose address is unknown are absent."""
    try:
        sp = _u32(m, S_PLAYER)
        pl = _u32(m, sp + PL_FIRST) if _ok(sp) else 0
        if not _ok(pl):
            return {}
        pos = struct.unpack(">3f", m.rd(pl + PL_POS, 12))
        hp, hp_max = struct.unpack(">2h", m.rd(pl + PL_LIFE, 4))
    except Exception:
        return {}
    if not all(math.isfinite(v) for v in pos):
        return {}
    snap = {"player": {"pos": pos, "hp": hp, "hp_max": hp_max}, "enemies": [], "bonuses": []}
    if ADDR["rot"] is not None:
        snap["player"]["rot"] = struct.unpack(">f", m.rd(pl + ADDR["rot"], 4))[0]
    if ADDR["timer"] is not None:
        snap["timer"] = struct.unpack(">f", m.rd(ADDR["timer"], 4))[0]
    for key in ("enemies", "bonuses"):
        spec = ADDR[key]
        if spec:
            snap[key] = _read_array(m, spec)
    return snap


def _read_array(m, spec) -> list:
    """spec: {"base": addr, "stride": n, "count": n, "pos": off, "hp": off | None, "visible": off | None}."""
    out = []
    for i in range(spec["count"]):
        a = spec["base"] + i * spec["stride"]
        pos = struct.unpack(">3f", m.rd(a + spec["pos"], 12))
        if not all(math.isfinite(v) for v in pos):
            continue
        e = {"pos": pos}
        if spec.get("hp") is not None:
            e["hp"] = struct.unpack(">h", m.rd(a + spec["hp"], 2))[0]
        if spec.get("visible") is not None:
            e["visible"] = bool(m.rd(a + spec["visible"], 1)[0])
        out.append(e)
    return out


def read_mesh(m, cache: dict | None = None):
    """The navmesh through the unverified s_ai chain, or None while that address is unknown."""
    if ADDR["s_ai"] is None:
        return None
    from . import re5_nav
    return re5_nav.read(m, cache, s_ai=ADDR["s_ai"])


def own_screen(snap: dict) -> str:
    p = snap.get("player") if snap else None
    if not p:
        return "loading"
    if p["hp"] <= 0:
        return "dead"
    if snap.get("timer") is not None and snap["timer"] <= 0:
        return "results"
    return "playing"


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


class Bot:
    def __init__(self, m=None, clock=None, stats=None, mesh=None):
        self.m, self.clock = m, clock
        self.stats = stats if stats is not None else {}
        for k in ("ticks", "shots", "withheld", "walked"):
            self.stats.setdefault(k, 0)
        self._mesh = mesh                # a fixed mesh (tests); else read from RAM on demand
        self._cache: dict = {}
        self._last = None                # (pos) for the heading estimate when the yaw address is unknown
        self._rot = 0.0

    def mesh(self):
        return self._mesh if self._mesh is not None else (read_mesh(self.m, self._cache) if self.m else None)

    def _facing(self, p) -> float:
        if p.get("rot") is not None:
            return p["rot"]
        if self._last is not None and _dist(self._last, p["pos"]) > 5.0:
            self._rot = heading(p["pos"][0] - self._last[0], p["pos"][2] - self._last[2])
        self._last = p["pos"]
        return self._rot

    def sighted(self, p, e, mesh) -> bool:
        """Proof that p can see and shoot e: the game's flag, else open mesh floor between them. No proof = False."""
        if abs(e["pos"][1] - p["pos"][1]) > FLOOR_DY:
            return False
        d = _dist(p["pos"], e["pos"])
        if d > SIGHT_R:
            return False
        if e.get("visible") is not None:
            return e["visible"]
        if mesh is None or not mesh.floor_segment(p["pos"], e["pos"]):
            return False
        r = mesh.route(p["pos"], e["pos"])
        if r is None:
            return False
        length, cur = 0.0, p["pos"]
        for w in r:
            length += _dist(cur, w)
            cur = w
        return length <= d * SIGHT_BEND + SIGHT_SLACK

    def _turn(self, err: float) -> set:
        if abs(err) <= TURN_TOL:
            return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _walk_to(self, p, goal, mesh, rot) -> set:
        route = mesh.route(p["pos"], goal) if mesh is not None else None
        if not route:
            return set()
        wp = route[0]
        if len(route) > 1 and _dist(p["pos"], wp) < ARRIVE_R:
            wp = route[1]
        err = wrap(heading(wp[0] - p["pos"][0], wp[2] - p["pos"][2]) - rot)
        keys = self._turn(err)
        if abs(err) < math.radians(60):
            keys.add("lup")
        self.stats["walked"] += 1
        return keys

    def _route_len(self, mesh, a, b):
        r = mesh.route(a, b) if mesh is not None else None
        if not r:
            return None
        n, cur = 0.0, a
        for w in r:
            n += _dist(cur, w)
            cur = w
        return n

    def tick(self, snap: dict) -> dict:
        self.stats["ticks"] += 1
        p = snap.get("player") if snap else None
        if not p:
            return {"hold": set()}
        if p["hp"] <= 0:
            return {"tap": "a"}
        mesh = self.mesh()
        rot = self._facing(p)
        foes = [e for e in snap.get("enemies", []) if e.get("hp", 1) > 0]
        seen = sorted((e for e in foes if self.sighted(p, e, mesh)), key=lambda e: _dist(p["pos"], e["pos"]))
        if foes and not seen:
            self.stats["withheld"] += 1           # enemies exist, none provably in sight: no shot
        if seen:
            t = seen[0]
            err = wrap(heading(t["pos"][0] - p["pos"][0], t["pos"][2] - p["pos"][2]) - rot)
            keys = {"l2"} | self._turn(err)
            if abs(err) <= AIM_TOL:
                keys.add("r2")
                self.stats["shots"] += 1
            return {"hold": keys}
        for pool in (snap.get("bonuses", []), foes):
            scored = [(self._route_len(mesh, p["pos"], b["pos"]), b) for b in pool]
            scored = [(n, b) for n, b in scored if n is not None]
            if scored:
                return {"hold": self._walk_to(p, min(scored, key=lambda s: s[0])[1]["pos"], mesh, rot)}
        return {"hold": set()}

    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self) -> None:
        pass


class RE6X360(Driver):
    map_id = "0871eee3b68cdea3"

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        return own_screen(self.snapshot(m) if snap is None else snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(m, clock=clock, stats=stats)

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer")}


DRIVER = RE6X360
