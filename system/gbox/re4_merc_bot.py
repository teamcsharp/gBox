"""Resident Evil 4 (GameCube G4BE08) Mercenaries autoplay playbook: an "any means necessary" run, played like a game.

setup() applies the hack package through re_mods (Mercenaries unlocked, Leon's loadout = a full-auto Hand Cannon with
explosive rounds, infinite ammo, unlimited health, time pickups x3, combo window x3 and frozen, every Ganado cloned
twice more). play() then drives Leon from RAM at ~20 Hz with the pad only, the way a player would (operator
2026-10-20: "I want the game to be played like a normal game" - no facing writes, so no arm aiming behind him, and no
teleports):
  * reads Leon (player em: *0x802B3044, +0x94 position, +0xA4 facing) and every live Ganado (EmMgr 0x8027DF20 slots:
    flags & 0x601 and +0x398 != 0xFF, +0x94 position);
  * steering is closed loop on his real facing: the stick turns him (left = +heading, ~140-230 deg/s measured on the
    Spark), R aims (the stick then fine-turns ~30 deg/s), A fires once the aim is within FIRE_TOL (2 degrees); the aim
    pitch (+0x258) is written straight at the Ganado's head while aiming - headshots, the pose follows naturally;
  * fights any Ganado within ENGAGE;
  * with the disc's level map (gbox.re4_navmap: collision, the stage's item hourglasses, line of sight) it takes the
    reachable Time Bonus hourglasses in the planner's order (exact tour from where the round starts): runs its path
    (Up+B, ~3,300 units/s), pressing A at the fence / window waypoints, and takes each hourglass with A at its stand
    point (they are items: "TAKE"); a Combo Bonus when COMBO_CROWD Ganados are near (every kill in its 30 s scores
    more); then makes its stand: goes after the nearest Ganados; it fires only with a clear line of sight from the gun
    to the head. Without the map: the hourglass events in HOURGLASS, shot from range;
  * a learned map per stage (LearnedMap, saved after every round): every cell Leon walks is floor, the cell ahead of
    him when he runs into something is wall; paths are planned on it (A*) when the disc's level map is not there, so
    every round knows more of the level than the one before (operator 2026-10-20: "with every round that is played,
    the navigation map needs to improve");
  * shoots only what he can hit (operator 2026-10-20: "shooting into walls near him and blowing himself up"): fires
    inside SHOOT_RANGE, not steeper down than STEEP_DOWN (that is the roof edge in front of him), and backs off a
    Ganado closer than POINT_BLANK (an explosive round there blows up on Leon); further out he closes in; up on the
    start roof (HIGH_GROUND above the Ganados) he first runs to the edge towards them and jumps down;
  * blocked while running (moved < STUCK_MOVE in STUCK_S): taps A ("JUMP OVER" / "CLIMB" prompts), then detours; still
    blocked after that, a short hop past the obstacle (a teleport of every copy of his position: a hack, but no pose
    change) - the last resort until the level map (gbox.re4_navmap) routes him round it;
  * a target that soaks 6 s of fire without the combo moving (on a roof, behind a wall) is skipped for 10 s;
  * the Mercenaries clock stops while a prompt is up ("Take the Handgun Ammo?", a time pillar): answer Yes (A);
  * between rounds (results, the Mercenaries title, character / stage select, the briefing) it presses A until the
    next round starts: GAME START, Leon, the first stage, go - the hack package stays in RAM, so every round is
    played the same way and no menu stays on screen.
v1 (2026-10-20, facing writes + teleports): 19 in a row, 24,500 points on the Village; the operator saw Leon stuck at a
fence and aiming with his arm behind him.

Memory comes from Dolphin's shared RAM view (/proc/<pid>/mem on Linux, a whole EmMgr table per read) when available,
else the adapter's read_memory/write_memory. Input goes through the adapter's send_input with gBox pad names.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import struct
import time
from pathlib import Path

GAME_IDS = {"G4BE08"}
EMMGR, P_PLAYER, P_GLOBAL = 0x8027DF20, 0x802B9780 - 0x673C, 0x802B2280
G_ROOM, MERC_TIMER, MERC = 0x4FA8, 0x80279308, 0x8021392C
FIRE_RANGE, HOP_FAR, HOP_SHORT = 2600.0, 5500.0, 1400.0
ENGAGE = 3800.0                                  # Ganados this close are fought, else Leon goes for the time bonuses
TURN_TOL, FIRE_TOL = 0.35, 0.035                 # radians: turn with the stick until within TURN_TOL, aim-turn to FIRE_TOL
AIM_PITCH = 0x258                                # Leon (player em) +0x258: aim pitch, radians, + up (found 2026-10-20: a
                                                 # value written while R is held moves the laser; the aim pose follows)
HEAD_H, GUN_H, HOURGLASS_H = 1550.0, 1400.0, 900.0   # above the feet: a Ganado's head, Leon's gun, an hourglass
PITCH_MAX, PITCH_AFTER = 0.5, 0.25              # radians either way; write it only once R has been held this long
SHOOT_RANGE, POINT_BLANK = 2400.0, 700.0         # fire inside this; closer than POINT_BLANK the blast is on Leon
STEEP_DOWN = -0.5                                # a shot this far down (radians) hits the ledge in front: move instead
HIGH_GROUND = 1500.0                             # Leon this far above the Ganados (the start roof): get down first
TAKE_R, VAULT_R = 450.0, 900.0                   # take an item hourglass this close to its stand point; vault from here
COMBO_CROWD, COMBO_NEAR = 5, 3500.0              # this many Ganados this close: take a combo bonus first (TAS route)
CELL = 400.0                                     # the learned map's grid (world units)
STUCK_S, STUCK_MOVE = 0.9, 250.0                 # running but moved less than this in that long: blocked
ARRIVE = 650.0                                   # a waypoint this close is reached
COLLECT_R, COLLECT_TRY_S = 1500.0, 4.0           # shoot an hourglass from this close; give up on it after this long
# Village (r400) time bonuses: the room's four small AEV events (live RAM 2026-10-20), (x, z) in world units
HOURGLASS = {0x400: [(19401.0, -6857.0), (-20476.0, -5294.0), (-8452.0, -20283.0), (5592.0, 16384.0)]}
MENU_AFTER, MENU_EVERY = 2.0, 1.5                 # out of a stage this long: press A this often (next round)
TRANSIENT_MAX = 20.0                             # a gap in a live Mercenaries room (grabbed, a pickup) waits this long
PACKAGE = [("mercenaries_unlock", {"on": True}),
           ("merc_loadout", {"character": "leon", "items": ["handcannon", "handcannon ammo:200"], "on": True}),
           ("weapon_mod", {"item": "handcannon", "fire_rate": "auto", "damage": "99.9"}),
           ("infinite_ammo", {"on": True}), ("unlimited_health", {"on": True}),
           ("explosive_rounds", {"items": ["handcannon"], "on": True}),
           ("merc_time_bonus", {"multiplier": 3}), ("combo_time", {"multiplier": 3}),
           ("combo_freeze", {"on": True}), ("spawn_multiplier", {"count": 3, "on": True})]


def ptr_ok(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


class ShmMem:
    """Dolphin's 32 MiB MEM1 view in /dev/shm, read through /proc/<pid>/mem (Linux, same user): whole tables per read."""

    def __init__(self, game_id: bytes = b"G4BE08"):
        for pid in (p for p in os.listdir("/proc") if p.isdigit()):
            try:
                maps = open(f"/proc/{pid}/maps").read()
            except OSError:
                continue
            for line in maps.splitlines():
                if "/dev/shm/dolphin-emu" not in line:
                    continue
                a, b = (int(x, 16) for x in line.split()[0].split("-"))
                if b - a != 0x2000000:
                    continue
                try:
                    f = open(f"/proc/{pid}/mem", "r+b", 0)
                    f.seek(a)
                    if f.read(6) == game_id:
                        self.f, self.base = f, a
                        return
                except OSError:
                    continue
        raise OSError("no Dolphin MEM1 view for this game")

    def rd(self, addr: int, n: int) -> bytes:
        self.f.seek(self.base + (addr & 0x1FFFFFF))
        return self.f.read(n)

    def wr(self, addr: int, data: bytes) -> None:
        self.f.seek(self.base + (addr & 0x1FFFFFF))
        self.f.write(data)


class AdMem:
    def __init__(self, ad):
        self.ad = ad

    def rd(self, addr: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(addr, n))

    def wr(self, addr: int, data: bytes) -> None:
        self.ad.write_memory(addr, data)


def memory(ad):
    try:
        return ShmMem()
    except OSError:
        return AdMem(ad)


def u32(m, a):
    return struct.unpack(">I", m.rd(a, 4))[0]


def snapshot(m) -> dict:
    """room, Merc clock (s), combo, Leon {ptr, pos, rot}, live Ganados [{slot, pos}]."""
    pg = u32(m, P_GLOBAL)
    room = struct.unpack(">H", m.rd(pg + G_ROOM, 2))[0] if ptr_ok(pg) else None
    pl = u32(m, P_PLAYER)
    player = None
    if ptr_ok(pl):
        player = {"ptr": pl, "pos": struct.unpack(">3f", m.rd(pl + 0x94, 12)),
                  "rot": struct.unpack(">f", m.rd(pl + 0xA4, 4))[0]}
    base, n, stride = u32(m, EMMGR), u32(m, EMMGR + 4), u32(m, EMMGR + 8)
    enemies = []
    if ptr_ok(base) and 0 < n <= 128 and 0x100 < stride < 0x2000:
        d = m.rd(base, n * stride)
        for k in range(1, n):
            o = k * stride
            if not (struct.unpack_from(">I", d, o)[0] & 0x601) or d[o + 0x398] == 0xFF:
                continue
            enemies.append({"slot": k, "pos": struct.unpack_from(">3f", d, o + 0x94)})
    return {"room": room, "timer": round(u32(m, MERC_TIMER) / 30.0, 1), "combo": u32(m, MERC + 0x28),
            "player": player, "enemies": enemies}


def in_mercenaries(snap: dict) -> bool:
    return snap["room"] is not None and (snap["room"] >> 8) == 4 and snap["player"] is not None


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def teleport(m, pl: int, x: float, y: float, z: float) -> int:
    """Every copy of Leon's position (pos, old pos, collision) moves; returns how many were written."""
    d = m.rd(pl, 0x300)
    pos = struct.unpack_from(">3f", d, 0x94)
    n = 0
    for o in range(0, 0x2F4, 4):                     # all three coordinates must match: zeros are everywhere
        if all(abs(a - b) < 2 for a, b in zip(struct.unpack_from(">3f", d, o), pos)):
            m.wr(pl + o, struct.pack(">3f", x, y, z))
            n += 1
    return n


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _navmap():
    """gbox.re4_navmap (the level from the disc: walls, vault edges, hourglasses, paths) when it is installed."""
    try:
        from . import re4_navmap
        return re4_navmap
    except Exception:                                # noqa: BLE001 - straight lines and stuck handling without it
        return None


class LearnedMap:
    """What Leon has learned about one stage, round after round: cells he walked (floor) and cells he ran into (walls).
    path() plans on it with A*: walked cells are cheapest, unknown ones a little dearer, walls are avoided (a cell
    walked far more often than it blocked him is floor again: a Ganado was in the way, not a wall)."""

    def __init__(self, path: Path | None = None):
        self.path_file = path
        self.walked: dict[tuple, int] = {}
        self.blocked: dict[tuple, int] = {}
        if path is not None and path.is_file():
            try:
                d = json.loads(path.read_text())
                self.walked = {(i, j): n for i, j, n in d.get("walked", [])}
                self.blocked = {(i, j): n for i, j, n in d.get("blocked", [])}
            except (OSError, ValueError, TypeError):
                pass

    @staticmethod
    def cell(x: float, z: float) -> tuple:
        return int(math.floor(x / CELL)), int(math.floor(z / CELL))

    def walk(self, x: float, z: float) -> None:
        k = self.cell(x, z)
        self.walked[k] = min(self.walked.get(k, 0) + 1, 10000)

    def block(self, x: float, z: float) -> None:
        k = self.cell(x, z)
        self.blocked[k] = self.blocked.get(k, 0) + 1

    def wall(self, k: tuple) -> bool:
        b = self.blocked.get(k, 0)
        return b > 0 and b * 40 > self.walked.get(k, 0)

    def path(self, start: tuple, goal: tuple) -> list:
        """[(x, z)] waypoints from start to goal round the learned walls; [goal] when nothing is known."""
        a, b = self.cell(*start), self.cell(*goal)
        if not self.blocked or a == b:
            return [goal]
        known = list(self.walked) + list(self.blocked) + [a, b]
        lo_i, hi_i = min(k[0] for k in known) - 6, max(k[0] for k in known) + 6
        lo_j, hi_j = min(k[1] for k in known) - 6, max(k[1] for k in known) + 6
        h = lambda k: math.hypot(k[0] - b[0], k[1] - b[1])        # noqa: E731
        best, came, todo = {a: 0.0}, {}, [(h(a), a)]
        while todo:
            _, k = heapq.heappop(todo)
            if k == b:
                break
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (k[0] + di, k[1] + dj)
                    if n == k or not (lo_i <= n[0] <= hi_i and lo_j <= n[1] <= hi_j) or (self.wall(n) and n != b):
                        continue
                    if di and dj and (self.wall((k[0] + di, k[1])) or self.wall((k[0], k[1] + dj))):
                        continue                                      # no squeezing past a wall corner
                    cost = best[k] + math.hypot(di, dj) * (1.0 if n in self.walked else 1.3)
                    if cost < best.get(n, float("inf")):
                        best[n], came[n] = cost, k
                        heapq.heappush(todo, (cost + h(n), n))
        if b not in came:
            return [goal]
        cells = [b]
        while cells[-1] != a:
            cells.append(came[cells[-1]])
        cells.reverse()
        way, last_dir = [], None                                      # keep only the corners
        for c0, c1 in zip(cells, cells[1:]):
            d = (c1[0] - c0[0], c1[1] - c0[1])
            if d != last_dir and c0 != a:
                way.append(((c0[0] + 0.5) * CELL, (c0[1] + 0.5) * CELL))
            last_dir = d
        return way + [goal]

    def save(self) -> None:
        if self.path_file is None:
            return
        try:
            self.path_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"cell": CELL, "walked": [[i, j, n] for (i, j), n in self.walked.items()],
                                       "blocked": [[i, j, n] for (i, j), n in self.blocked.items()]}))
            tmp.replace(self.path_file)
        except OSError:
            pass


class Bot:
    """One decision per tick; the caller sends what it returns ({'hold': keys} / {'tap': key}) and sleeps. Pad only:
    the stick turns Leon, R aims, A fires / vaults, B runs."""

    def __init__(self, m, clock=time.time, nav=None, learn_dir: Path | None = None):
        self.m, self.clock = m, clock
        self.nav = nav if nav is not None else _navmap()
        self.learn_dir = learn_dir
        self.learned: LearnedMap | None = None
        self.r_since = None                           # since when the bot has held R (the aim pose is up after a moment)
        self.st, self.items, self.combos, self.ordered = None, [], [], False
        self.hist: list = []
        self.last_timer, self.timer_since = None, clock()
        self.skip: dict[int, float] = {}
        self.aim = {"slot": None, "since": 0.0, "combo": 0}
        self.room = None
        self.bonus: list = []                         # time bonuses left this round [(x, z)]
        self.goal = None                              # {"pos", "since", "path"} the time bonus Leon is going for
        self.unstick = None                           # {"stage": "vault" | "detour", "until", "dir"}
        self.detour_dir = 1
        self.last_hop, self.stuck_n = 0.0, 0
        self.stats = {"prompts": 0, "max_combo": 0, "vaults": 0, "detours": 0, "hops": 0, "time_bonus": 0, "shots_s": 0.0,
                      "learned_walls": 0, "replans": 0}

    # -- the round's time bonuses --
    def _round(self, room):
        if room != self.room:
            if self.learned is not None:
                self.learned.save()
            self.room = room
            self.learned = LearnedMap(self.learn_dir / f"r{room:03x}.json" if self.learn_dir else None)
            self.stats["learned_walls"] = len(self.learned.blocked)
            self.st, self.items, self.combos = None, [], []
            if self.nav is not None:
                try:
                    st = self.nav.stage(f"r{room:03x}")
                    hg = [h for h in st["hourglasses"] if h.get("reachable")]
                    self.st = st
                    self.items = [h for h in hg if h.get("kind") == "time_bonus"]
                    self.combos = [h for h in hg if h.get("kind") == "combo_bonus"]
                except Exception:                     # noqa: BLE001 - no map for this stage: the old way
                    self.st = None
            self.ordered = False
            self.bonus = [] if self.st is not None else list(HOURGLASS.get(room, []))
            self.goal = None

    def _path(self, start, goal):
        if self.st is not None:
            try:
                way = self.nav.path(self.st, start, goal)
                if way:
                    return [(w.x, w.z, w.action) if hasattr(w, "action") else tuple(w) for w in way]
            except Exception:                         # noqa: BLE001
                pass
        elif self.nav is not None and self.room is not None:
            try:
                way = self.nav.path(self.nav.stage(f"r{self.room:03x}"), start, goal)
                if way:
                    return [tuple(w) for w in way]
            except Exception:                         # noqa: BLE001
                pass
        if self.learned is not None:
            return self.learned.path(start[0::2] if len(start) == 3 else start, goal)
        return [goal]

    def _sight(self, p, target_xyz) -> bool:
        """A clear line from Leon's gun to target_xyz on the level map (True without a map)."""
        if self.st is None:
            return True
        try:
            gun = [p["pos"][0], p["pos"][1] + GUN_H, p["pos"][2]]
            return bool(self.nav.sight(self.st, gun, list(target_xyz)))
        except Exception:                             # noqa: BLE001
            return True

    def save(self):
        """Keep what this round taught (the caller calls it between rounds and at the end)."""
        if self.learned is not None:
            self.learned.save()

    # -- steering --
    def _turn(self, err: float, aiming: bool) -> set:
        keys = {"r"} if aiming else set()
        if err > (FIRE_TOL if aiming else TURN_TOL):
            keys.add("left")
        elif err < -(FIRE_TOL if aiming else TURN_TOL):
            keys.add("right")
        return keys

    def _fight(self, p, tgt, now, s) -> dict:
        px, _, pz = p["pos"]
        tx, _, tz = tgt["pos"]
        err = wrap(heading(tx - px, tz - pz) - p["rot"])
        if tgt["slot"] != self.aim["slot"] or s["combo"] != self.aim["combo"]:
            self.aim = {"slot": tgt["slot"], "since": now, "combo": s["combo"]}
        elif now - self.aim["since"] > 6:                              # soaked 6 s of fire: out of reach
            self.skip[tgt["slot"]] = now + 10
            self.aim = {"slot": None, "since": now, "combo": s["combo"]}
            return {"hold": set()}
        dist = math.hypot(tx - px, tz - pz)
        down = math.atan2(tgt["pos"][1] + HEAD_H - (p["pos"][1] + GUN_H), max(dist, 1.0))
        if p["pos"][1] - tgt["pos"][1] > HIGH_GROUND or down < STEEP_DOWN:   # up on a roof: get down to them
            self.r_since = None
            return self._go(p, (tx, tz), now)
        if dist > SHOOT_RANGE or not self._sight(p, (tx, tgt["pos"][1] + HEAD_H, tz)):   # can't hit him from here
            self.r_since = None
            return self._run_to(p, (tx, tgt["pos"][1], tz), now)
        if abs(err) > TURN_TOL:
            self.r_since = None
            return {"hold": self._turn(err, aiming=False)}               # turn round first (fast)
        if dist < POINT_BLANK:                                         # the blast would be on Leon: step back
            self.r_since = None
            return {"hold": {"down"} | self._turn(err, aiming=False)}
        self.r_since = now if self.r_since is None else self.r_since
        self._pitch(p, tgt["pos"][1] + HEAD_H, dist)                   # the gun onto his head
        if abs(err) > FIRE_TOL or now - self.r_since < PITCH_AFTER:
            return {"hold": self._turn(err, aiming=True)}                # aim (pose up), fine-turn onto him
        self.stats["shots_s"] = round(self.stats["shots_s"] + 0.05, 2)
        return {"hold": {"r", "a"}}                                       # on target: fire

    def _pitch(self, p, target_y: float, dist: float) -> None:
        """Aim pitch straight at target_y (an aimbot on the vertical: the game draws the aim pose from it). Only in a live
        round whose clock runs: a write while the round ends (Leon's object torn down for the evac) is a risk."""
        if not (self.last_timer or 0) > 2 or self.clock() - self.timer_since > 0.5:
            return
        if self.r_since is None or self.clock() - self.r_since < PITCH_AFTER:
            return                                    # the aim pose is not up yet: the arms would bend to it
        a = math.atan2(target_y - (p["pos"][1] + GUN_H), max(dist, 1.0))
        try:
            self.m.wr(p["ptr"] + AIM_PITCH, struct.pack(">f", max(-PITCH_MAX, min(PITCH_MAX, a))))
        except Exception:                             # noqa: BLE001 - a read-only memory view: level aim
            pass

    def _take(self, p, h: dict, now, pool: list) -> dict:
        """Run to an item hourglass's stand point on the map's path and take it with A."""
        px, py, pz = p["pos"]
        sx, sy, sz = h["stand"]
        if not self.goal or self.goal.get("item") is not h:
            self.goal = {"item": h, "pos": (sx, sz), "since": now, "path": self._path((px, py, pz), (sx, sy, sz))}
        if math.hypot(sx - px, sz - pz) < TAKE_R:
            if now - self.goal.setdefault("take_since", now) > COLLECT_TRY_S:  # not taking it: leave it this round
                pool.remove(h)
                self.goal = None
                return {"hold": set()}
            self.r_since = None
            return {"tap": "a"}                                           # TAKE
        return self._follow(p, now)

    def _run_to(self, p, target_xyz, now) -> dict:
        """Close in on a Ganado round the walls (map path, refreshed as he moves) or straight without a map."""
        if self.st is None:
            return self._go(p, (target_xyz[0], target_xyz[2]), now)
        g = self.goal or {}
        if g.get("chase") is None or now - g.get("since", 0) > 1.5:
            self.goal = {"chase": True, "pos": (target_xyz[0], target_xyz[2]), "since": now,
                         "path": self._path(tuple(p["pos"]), tuple(target_xyz))}
        return self._follow(p, now)

    def _follow(self, p, now) -> dict:
        """Run the goal's path: drop waypoints as they are reached, A at a fence / window waypoint."""
        px, _, pz = p["pos"]
        way = self.goal["path"]
        while way:
            w = way[0]
            d = math.hypot(w[0] - px, w[1] - pz)
            if len(w) > 2 and w[2] == "vault" and d < VAULT_R:           # a fence / window: JUMP OVER it first
                way[0] = (w[0], w[1], "vaulted")
                self.stats["vaults"] += 1
                return {"tap": "a"}
            if len(way) > 1 and d < ARRIVE:
                way.pop(0)
                continue
            break
        w = way[0]
        self.r_since = None
        return self._go(p, (w[0], w[1]), now)

    def _go(self, p, goal_xz, now) -> dict:
        px, _, pz = p["pos"]
        if self.unstick and now < self.unstick["until"]:
            if self.unstick["stage"] == "detour":
                return {"hold": {"up", "b", "left" if self.unstick["dir"] > 0 else "right"}}
        self.unstick = None
        self.hist = [h for h in self.hist if now - h[0] < STUCK_S + 0.3] + [(now, px, pz)]
        span = now - self.hist[0][0]
        moved = math.hypot(px - self.hist[0][1], pz - self.hist[0][2])
        if span >= STUCK_S and moved < STUCK_MOVE:                       # running into something
            self.hist = []
            self.stuck_n += 1
            if self.learned is not None:                                 # learn the wall ahead of him; plan round it
                self.learned.block(px + math.sin(p["rot"]) * CELL * 0.8, pz + math.cos(p["rot"]) * CELL * 0.8)
                self.stats["learned_walls"] = len(self.learned.blocked)
                if self.goal and self.goal.get("pos") and self.st is None:
                    self.goal["path"] = self._path((px, pz), self.goal["pos"])
                    self.stats["replans"] += 1
            gx, gz = goal_xz
            dist = math.hypot(gx - px, gz - pz)
            if self.stuck_n == 1:
                self.stats["vaults"] += 1
                return {"tap": "a"}                                       # a fence / window: JUMP OVER
            if self.stuck_n >= 3 and dist > HOP_SHORT and now - self.last_hop > 3:
                k = min(HOP_SHORT, dist - ARRIVE) / dist        # last resort (a hack): a short hop past the obstacle
                teleport(self.m, p["ptr"], px + (gx - px) * k, p["pos"][1], pz + (gz - pz) * k)
                self.last_hop, self.stuck_n = now, 0
                self.stats["hops"] += 1
                return {"hold": set()}
            self.detour_dir = -self.detour_dir
            self.unstick = {"stage": "detour", "until": now + 0.8, "dir": self.detour_dir}
            self.stats["detours"] += 1
            return {"hold": {"up", "b", "left" if self.detour_dir > 0 else "right"}}
        if span >= STUCK_S and moved > 3 * STUCK_MOVE:
            self.stuck_n = 0                                              # running freely again
        if self.learned is not None:
            self.learned.walk(px, pz)
        gx, gz = goal_xz
        err = wrap(heading(gx - px, gz - pz) - p["rot"])
        keys = {"up", "b"}
        if err > TURN_TOL / 2:
            keys.add("left")
        elif err < -TURN_TOL / 2:
            keys.add("right")
        if abs(err) > 1.6:                                               # behind him: turn on the spot first
            keys -= {"up", "b"}
        return {"hold": keys}

    def tick(self, s: dict) -> dict:
        now, p = self.clock(), s["player"]
        self.stats["max_combo"] = max(self.stats["max_combo"], s["combo"])
        if not p:
            return {"hold": set()}
        self._round(s["room"])
        if s["timer"] != self.last_timer:
            if self.last_timer is not None and self.last_timer > 1 and 5 < s["timer"] - self.last_timer < 100 and self.bonus:   # a time bonus (not the next round's clock)
                px, _, pz = p["pos"]
                got = min(self.bonus, key=lambda b: (b[0] - px) ** 2 + (b[1] - pz) ** 2)
                self.bonus.remove(got)
                self.stats["time_bonus"] += 1
                self.goal = None
            elif self.last_timer is not None and self.last_timer > 1 and 5 < s["timer"] - self.last_timer < 100 \
                    and (self.items or self.combos):
                px, _, pz = p["pos"]
                pool = self.items + self.combos
                got = min(pool, key=lambda h: (h["stand"][0] - px) ** 2 + (h["stand"][2] - pz) ** 2)
                (self.items if got in self.items else self.combos).remove(got)
                self.stats["time_bonus"] += 1
                self.goal = None
            self.last_timer, self.timer_since = s["timer"], now
        elif now - self.timer_since > 1.2 and s["timer"] > 0:           # the clock stopped: a prompt is up
            self.stats["prompts"] += 1
            return {"tap": "b" if now - self.timer_since > 6 else "a"}
        px, _, pz = p["pos"]
        pool = [e for e in s["enemies"] if self.skip.get(e["slot"], float("-inf")) < now]
        near = min(pool, key=lambda e: (e["pos"][0] - px) ** 2 + (e["pos"][2] - pz) ** 2) if pool else None
        dist = math.hypot(near["pos"][0] - px, near["pos"][2] - pz) if near else None
        crowd = sum(1 for e in pool if math.hypot(e["pos"][0] - px, e["pos"][2] - pz) < COMBO_NEAR)
        if self.st is not None and self.combos and crowd >= COMBO_CROWD:     # a combo window while they crowd in
            c = min(self.combos, key=lambda h: math.hypot(h["stand"][0] - px, h["stand"][2] - pz))
            if math.hypot(c["stand"][0] - px, c["stand"][2] - pz) < 2 * COMBO_NEAR:
                return self._take(p, c, now, self.combos)
        if near and dist < ENGAGE:
            return self._fight(p, near, now, s)
        if self.st is not None:
            if self.items and not self.ordered:                            # the round's route: best order from here
                try:
                    order = self.nav.tour(self.st, tuple(p["pos"]), targets=self.items)
                    self.items = [self.items[i] for i in order]
                except Exception:                     # noqa: BLE001
                    pass
                self.ordered = True
            if self.items:
                return self._take(p, self.items[0], now, self.items)
        if self.bonus:                                                    # the time bonuses, nearest first
            if not self.goal or self.goal["pos"] not in self.bonus:
                pos = min(self.bonus, key=lambda b: (b[0] - px) ** 2 + (b[1] - pz) ** 2)
                self.goal = {"pos": pos, "since": now, "path": self._path((px, pz), pos)}
            gx, gz = self.goal["pos"]
            d = math.hypot(gx - px, gz - pz)
            if d < COLLECT_R:                                             # break it: aim at it and fire
                if now - self.goal.setdefault("shoot_since", now) > COLLECT_TRY_S:
                    self.bonus.remove(self.goal["pos"])                  # not breaking: leave it for this round
                    self.goal = None
                    return {"hold": set()}
                err = wrap(heading(gx - px, gz - pz) - p["rot"])
                if abs(err) > TURN_TOL:
                    self.r_since = None
                    return {"hold": self._turn(err, aiming=False)}
                self.r_since = now if self.r_since is None else self.r_since
                self._pitch(p, p["pos"][1] + HOURGLASS_H, d)
                return {"hold": {"r", "a"} | (self._turn(err, aiming=True) - {"r"})}
            way = self.goal["path"]
            while len(way) > 1 and math.hypot(way[0][0] - px, way[0][1] - pz) < ARRIVE:
                way.pop(0)
            self.r_since = None
            return self._go(p, way[0], now)
        if near:                                                          # the stand: go and meet them
            self.r_since = None
            return self._go(p, (near["pos"][0], near["pos"][2]), now)
        return {"hold": set()}


def setup(ad) -> list[str]:
    """Apply the hack package (re_mods); returns the ops that failed."""
    from . import re_mods_tool as RM
    g = RM.RE4(ad)
    failed = []
    for op, kw in PACKAGE:
        try:
            RM.run(ad, op, g=g, **kw)
        except Exception as e:                       # noqa: BLE001 - one failed mod never stops the run
            failed.append(f"{op}: {e}")
    return failed


def learn_dir_for(ad) -> Path:
    """Where the learned stage maps live: the worker's runtime folder (or ~/.gbox for a standalone run)."""
    rt = getattr(getattr(ad, "config", None), "runtime", None)
    return (Path(rt) if rt else Path.home() / ".gbox") / "re4_learned"


def play(ad, send, stopped, sleep=time.sleep, m=None, tick_s: float = 0.05, stats: dict | None = None,
         clock=time.time, learn_dir: Path | None = None, rerun=None) -> dict:
    """Drive Leon until stopped(); send(rows) presses keys. Returns the run's stats (stats, when given, is filled live:
    the watch panel shows it): hops, prompts, max_combo, combo, timer, rounds, menu_presses."""
    m = m or memory(ad)
    bot, held = Bot(m, clock=clock, learn_dir=learn_dir or learn_dir_for(ad)), set()
    if stats is not None:
        stats.update(bot.stats)
        bot.stats = stats
    bot.stats.update(rounds=1, menu_presses=0)
    out_since, last_press, was_in = None, 0.0, True

    def hold(keys):
        nonlocal held
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            send(rows)
        held = set(keys)
    while not stopped():
        s = snapshot(m)
        now = clock()
        if not in_mercenaries(s) or s["timer"] <= 0:   # the Result screen (same room, clock at 0), the title, select
            hold(set())
            out_since = out_since or now
            # Leon grabbed / a pickup animation: still the Mercenaries room with time on the clock - not the round's
            # end (a 2 s gap there reran a 49,370 round with 21 s left, 2026-10-20); wait it out
            transient = s["room"] is not None and (s["room"] >> 8) == 4 and s["timer"] > 0.5
            if transient and now - out_since < TRANSIENT_MAX:
                sleep(0.25)
                continue
            if rerun is not None and now - out_since > MENU_AFTER:
                # the menu save state (Select Player, taken before the hooks): load it, hooks back in, character,
                # stage, go - blind A presses walked from the Result screen to the main title and started a story
                # game with the Mercenaries hooks in, which crashed the game (2026-10-20)
                try:
                    rerun()
                    bot.stats["reruns"] = bot.stats.get("reruns", 0) + 1
                except Exception as e:             # noqa: BLE001 - the next pass tries again
                    bot.stats["rerun_error"] = f"{type(e).__name__}: {e}"[:200]
                out_since, last_press = None, clock()
                sleep(1.0)
                continue
            if now - out_since > MENU_AFTER and now - last_press > MENU_EVERY:
                send([{"key": "a", "down": True}])
                sleep(0.2)
                send([{"key": "a", "down": False}])
                last_press = clock()
                bot.stats["menu_presses"] += 1
            was_in = False
            sleep(0.25)
            continue
        if not was_in:
            bot.stats["rounds"] += 1
            bot.save()                                 # what the last round taught
            was_in = True
        out_since = None
        bot.stats.update(combo=s["combo"], timer=s["timer"])
        act = bot.tick(s)
        if "tap" in act:
            hold(set())
            sleep(0.15)
            send([{"key": act["tap"], "down": True}])
            sleep(0.25)
            send([{"key": act["tap"], "down": False}])
            sleep(0.4)
            continue
        hold(act["hold"])
        sleep(tick_s)
    hold(set())
    bot.save()
    return bot.stats


def matches(ad, g: dict) -> bool:
    """This playbook plays this session: RE4 GameCube NTSC-U in a Mercenaries stage."""
    if g.get("platform") != "gamecube":
        return False
    try:
        m = memory(ad)
        return m.rd(0x80000000, 6).decode("ascii", "replace") in GAME_IDS and in_mercenaries(snapshot(m))
    except Exception:                                # noqa: BLE001
        return False
