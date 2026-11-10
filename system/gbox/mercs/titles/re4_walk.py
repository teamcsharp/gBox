"""The RE4 (Switch) Mercenaries walker, the operator's map marks and the tactical map's hooks, for re4_switch.Bot.

The walk is the RE5 Switch bot's (re5_switch.Bot._approach / _mesh_waypoint / _mesh_guard / _never_stand, the rules
written down at re5_switch MESH_ROUTE .. NEVER_STAND) on the RE4 stage mesh (re4_nav.Mesh, mm), with RE4's controls
(Capcom's Switch manual, docs/research/mercenaries-character-specials.md 1.1): RE4 is tank-controlled - the left stick
up walks, left / right turn him, B + up runs, B + down is the 180-degree turn; Y is the action button (a jump-over, a
ladder, every prompt).

    walker = Walker(stats)
    walker.observe(snap, now)            # every tick (attach() does it): the player, the stage mesh
    keys = walker.approach(goal)         # the stick (and B, and a Y pulse at a crossing) toward goal by the mesh

Rules carried over, in mm (RE5's cm x 10):
* the route: re4_nav.Mesh.route with CLEARANCE_MM from the walkable rim, replanned every REPLAN_S or when the goal
  leaves its GOAL_CELL_MM square; a waypoint counts as passed within WP_MM only once the next lies on open floor from
  him (LOOKAHEAD; within WP_NEAR_MM whatever lies beyond); within DIRECT_R_MM the straight line - unless the mesh says
  the line is not open floor;
* a crossing (re5_nav.Traversal: a fence or sill jump-over, a ladder): walked to its approach on his own floor, then
  pushed through its portal toward the landing with Y pulsed (the game's prompt takes the press); crossed once he is
  past the portal (a level crossing) or nearer the landing's height (a ladder). LINK_TRY_S there without crossing and
  it is left out of the routes for AVOID_S (route(avoid=)) and another way planned. None of the crossings has been
  seen taken in game;
* the backstop: approach() called STAND_MAX_S without STAND_MOVE_MM of ground and he steps STAND_STEP_S along open
  floor (toward the route's point when it has one); a stall at the same waypoint CROSSING_PUSHES times refuses it;
* guard(act) / never_stand(act): RE5's mesh guard and never-stand, for the bot's own moves.

The turn sign: an error > 0 (the target at a larger heading, atan2(dx, dz)) turns LEFT - the convention the tactical
map's VIEW names as measured on RE5 and the GameCube RE4 (gbox.re4_merc_bot: "left" if err > 0). The Switch's own
facing field is not measured yet (re4_switch U_YAW); TURN_POSITIVE flips it in one place if the live read disagrees.

attach(cls) (a class decorator on re4_switch.Bot) wires it in without touching the fight: the bot gets .walker (the
fight's _approach takes it), snap["nav"] (re4_nav.attach, on a snapshot read from the game - one with module_base;
a synthetic one keeps whatever nav it carries) before its tick, the operator's map marks (receive_map_goal /
map_goal_plan, map_goals.Goals with RE4's distances) ahead of its own play, and plan() for the tactical map. Every
attribute it adds is created on first use (setdefault), so a bot that lives through a hot reload of re4_switch gets
them too.
"""
from __future__ import annotations

import functools
import json
import math
import time
from pathlib import Path

from .. import map_goals
from .. import tactical as T
from . import re4_nav

# --- the walk (mm) ---------------------------------------------------------------------------------------------------
REPLAN_S, REPLAN_MIN_S, GOAL_CELL_MM, GOAL_CELL_Y_MM = 1.0, 0.75, 2000.0, 1000.0
WP_MM, WP_NEAR_MM, CLEARANCE_MM, LOOKAHEAD = 1200.0, 450.0, 350.0, True
DIRECT_R_MM, LEVEL_DY_MM, RUN_R_MM = 3000.0, 1500.0, 6000.0
LINK_TRY_S, LINK_PUSH_MM, LINK_PAST_MM = 4.0, 1500.0, 150.0
CROSSING_PUSHES, AVOID_S, LINKS_AVOIDED = 3, 120.0, 24
PROBE_MM = 1500.0
TURNS = tuple(math.radians(d) for d in (22.5, -22.5, 45, -45, 67.5, -67.5, 90, -90, 112.5, -112.5, 135, -135))
FOLLOW_TOL = math.radians(25)
STAND_MAX_S, STAND_MOVE_MM, STAND_STEP_S, STAND_PROBE_MM = 3.0, 800.0, 1.2, 2500.0
# --- the stick (tank controls) ---
TURN_POSITIVE, TURN_NEGATIVE = "lleft", "lright"     # err > 0 turns left (see the module docstring)
FORWARD, BACK, RUN, ACTION = "lup", "ldown", "b", "y"
TURN_TOL = math.radians(14)                          # on his line: straight on
ARC_TOL = math.radians(50)                           # within this: on while turning (an arc); beyond: on the spot
RUN_ARC = math.radians(30)                           # B only while the arc is this gentle (a run turns wide)
QUICK_TURN_ERR, QUICK_TURN_S = math.radians(150), 1.0
ACTION_PULSE_S = 0.35                                # Y down this long, up this long, at a crossing
# --- the operator's marks (mm; re5_switch MAP_GOALS x 10) ---
GOAL_FIRE_MM, GOAL_THREAT_MM, GOAL_FIGHT_MM, GOAL_ARRIVE_MM = 15000.0, 2000.0, 6000.0, 2000.0
ROUTE_SOURCE = "room_collision"
# Every crossing taken or given up on (operator 2026-11-10: "have the bot log and internalize ... a keystroke may be
# needed to open a door or climb through a window"): the doors, windows and ladders come from the room's event data
# (re4_switch_nav), the key is ACTION (Y), and this log is what the walk did with each.
CROSSING_LOG = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "re4-crossings.jsonl"
MAX_ROUTE = 64


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _flat(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


class Walker:
    """See the module docstring. stats (the bot's) gets: walk_how, nav_status, mesh_routes, mesh_no_route,
    mesh_route_ticks, mesh_lookahead_holds, mesh_links_tried, mesh_links_taken, mesh_links_refused,
    mesh_crossings_refused, nav_near_walled, nav_direct_ticks, stand_breaks, quick_turns, mesh_steers, mesh_blocked."""

    def __init__(self, stats: dict | None = None, *, turn_positive: str = TURN_POSITIVE, clearance: float = CLEARANCE_MM):
        self.stats = stats if stats is not None else {}
        self.turn_pos = turn_positive
        self.turn_neg = TURN_NEGATIVE if turn_positive == TURN_POSITIVE else TURN_POSITIVE
        self.clearance = clearance
        self.snap: dict = {}
        self.p: dict | None = None
        self.mesh = None
        self.now = 0.0
        self._route = {"cell": None, "at": -1e9, "pts": None, "sig": None}
        self._avoid = {"sig": None, "pts": []}
        self._link = {"key": None, "since": 0.0}
        self._push = {"key": None, "n": 0, "at": -1e9}
        self._stand = {"pos": None, "at": 0.0, "until": -1e9, "keys": (), "n": 0}
        self._quick_at = -1e9
        self.wp = None                                  # (x, z, now) of the route's point steering this tick
        self.at_link = False
        self.how = ""

    # --- what he stands on ---
    def observe(self, snap: dict, now: float | None = None) -> None:
        self.snap = snap or {}
        self.p = self.snap.get("player") if isinstance(self.snap.get("player"), dict) else None
        mesh = self.snap.get("nav")
        self.mesh = mesh if mesh is not None and hasattr(mesh, "route") else None
        self.now = time.monotonic() if now is None else now

    def _pos(self):
        pos = (self.p or {}).get("pos")
        return tuple(pos) if pos is not None and len(pos) >= 3 else None

    # --- the stick ---
    def steer(self, err: float, run: bool = True) -> tuple:
        """Tank controls toward a bearing err (radians, + = his left): straight on within TURN_TOL, an arc within
        ARC_TOL, the 180 turn (B + down) past QUICK_TURN_ERR at most every QUICK_TURN_S, else a turn on the spot."""
        a = abs(err)
        turn = self.turn_pos if err > 0 else self.turn_neg
        if a <= TURN_TOL:
            return (FORWARD, RUN) if run else (FORWARD,)
        if a <= ARC_TOL:
            return (FORWARD, turn, RUN) if run and a <= RUN_ARC else (FORWARD, turn)
        if a >= QUICK_TURN_ERR and self.now - self._quick_at >= QUICK_TURN_S:
            self._quick_at = self.now
            self._count("quick_turns")
            return (BACK, RUN)
        return (turn,)

    def _count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    # --- the floor ---
    def _open(self, pos, x: float, z: float) -> bool:
        """Whether the straight way from pos to (x, z) is open floor on the mesh (the far end at its own floor height)."""
        mesh = self.mesh
        if mesh is None:
            return True
        end = (x, pos[1], z)
        try:
            tri = mesh.find(end, floor_only=True)
            h = mesh._height(tri, x, z) if tri is not None else None
            if h is not None:
                end = (x, h, z)
            return bool(mesh.floor_segment(tuple(pos), end))
        except Exception:                                  # noqa: BLE001 - the mesh never costs a tick
            return False

    def _avoid_pts(self) -> list:
        sig = getattr(self.mesh, "sig", None)
        if self._avoid["sig"] != sig:
            self._avoid = {"sig": sig, "pts": []}
        self._avoid["pts"] = [q for q in self._avoid["pts"] if q[3] > self.now]
        return [tuple(q[:3]) for q in self._avoid["pts"]]

    def refuse(self, point, why: str) -> None:
        """Leave this crossing (its portal) out of the stage's routes for AVOID_S; plan again at the next call."""
        self._avoid_pts()
        self._avoid["pts"] = [q for q in self._avoid["pts"] if math.dist(q[:3], point[:3]) >= 1.0] \
            + [tuple(point[:3]) + (self.now + AVOID_S,)]
        del self._avoid["pts"][:-LINKS_AVOIDED]
        self._route.update(at=-1e9, pts=None)
        self._link["key"] = None
        self.stats["mesh_refused_last"] = f"{why} at {point[0]:.0f},{point[1]:.0f},{point[2]:.0f}"[:120]

    def _log_crossing(self, event: str, q) -> None:
        """A door / window / ladder crossing (the room's own event data) taken or given up on, one line in
        CROSSING_LOG: the stage, the portal, the action key the walk pulses at it, how long it took."""
        try:
            row = {"t": round(time.time(), 2), "event": event, "room": getattr(self.mesh, "room", None),
                   "portal": [round(v) for v in q.portal], "landing": [round(v) for v in q[:3]],
                   "key": ACTION, "tried_s": round(self.now - self._link.get("since", self.now), 2)}
            CROSSING_LOG.parent.mkdir(parents=True, exist_ok=True)
            with CROSSING_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + chr(10))
        except Exception:                                  # noqa: BLE001 - a log never costs a tick
            pass

    # --- the route ---
    def _waypoint(self, goal):
        """The next point (x, z) of the mesh's route to goal, or None (no mesh, an end off it, no route). At a
        crossing's foot it is a point past the portal and self.at_link is True."""
        self.at_link = False
        mesh, pos = self.mesh, self._pos()
        if mesh is None or pos is None or len(goal) < 3:
            return None
        px, py, pz = pos
        r = self._route
        sig = getattr(mesh, "sig", None)
        cell = (round(goal[0] / GOAL_CELL_MM), round(goal[1] / GOAL_CELL_Y_MM), round(goal[2] / GOAL_CELL_MM))
        if r["sig"] != sig or (r["cell"] != cell and self.now - r["at"] >= REPLAN_MIN_S) or self.now - r["at"] >= REPLAN_S:
            r.update(cell=cell, at=self.now, sig=sig)
            avoid = tuple(self._avoid_pts())
            try:
                pts = mesh.route(pos, tuple(goal[:3]), avoid=avoid, clearance=self.clearance)
            except Exception as exc:                       # noqa: BLE001 - the mesh never costs a tick
                self.stats["nav_error"] = f"mesh {type(exc).__name__}: {exc}"[:120]
                pts = None
            r["pts"] = list(pts) if pts else None
            self._count("mesh_routes" if pts else "mesh_no_route")
            if pts:
                self.stats["nav_status"] = "route"
            else:
                free = None
                if avoid:
                    try:
                        free = mesh.route(pos, tuple(goal[:3]))
                    except Exception:                      # noqa: BLE001
                        free = None
                self.stats["nav_status"] = (
                    f"no usable exit from this floor region toward {goal[0]:.0f},{goal[2]:.0f}: "
                    f"{len(avoid)} crossing(s) refused" if free else
                    "no mesh route (an end off the mesh, or no floor path between them)")
        pts = r["pts"]
        while pts:
            q = pts[0]
            link = hasattr(q, "approach")
            point = q.approach if link else q
            d = math.hypot(point[0] - px, point[2] - pz)
            if link:
                dx, dz = q.portal[0] - q.approach[0], q.portal[2] - q.approach[2]
                n = math.hypot(dx, dz)
                if n < 1.0:
                    dx, dz = q[0] - q.approach[0], q[2] - q.approach[2]
                    n = math.hypot(dx, dz) or 1.0
                rise = q[1] - q.approach[1]
                past = ((px - q.portal[0]) * dx + (pz - q.portal[2]) * dz) / n
                landed = (abs(py - q[1]) < abs(py - q.approach[1])) if abs(rise) > LEVEL_DY_MM / 2 \
                    else past > LINK_PAST_MM
                if landed:
                    self._count("mesh_links_taken")
                    self._log_crossing("taken", q)
                    self._link["key"] = None
                    pts.pop(0)
                    continue
                if d <= WP_MM or self._link["key"] == tuple(round(v) for v in q.portal):
                    key = tuple(round(v) for v in q.portal)
                    if self._link["key"] != key:
                        self._link.update(key=key, since=self.now)
                        self._count("mesh_links_tried")
                    if self.now - self._link["since"] > LINK_TRY_S:
                        self.refuse(tuple(q.portal), "a crossing that never let him through")
                        self._count("mesh_links_refused")
                        self._log_crossing("refused", q)
                        return None
                    self.at_link = True
                    self._count("mesh_route_ticks")
                    out = (q.portal[0] + dx / n * LINK_PUSH_MM, q.portal[2] + dz / n * LINK_PUSH_MM)
                    self.wp = out + (self.now,)
                    return out
            elif len(pts) > 1 and d <= WP_MM:
                nxt = pts[1]
                nxt_pt = nxt.approach if hasattr(nxt, "approach") else nxt
                if not LOOKAHEAD or d <= WP_NEAR_MM or self._open(pos, nxt_pt[0], nxt_pt[2]):
                    pts.pop(0)
                    continue
                self._count("mesh_lookahead_holds")
            self._count("mesh_route_ticks")
            self.wp = (point[0], point[2], self.now)
            return point[0], point[2]
        return None

    def no_exit(self) -> bool:
        """The last plan failed only because of the crossings refused on this stage."""
        return self._route.get("pts") is None and str(self.stats.get("nav_status") or "").startswith("no usable exit")

    def route_ahead(self) -> list:
        """The waypoints still ahead (a crossing as its approach then its landing), for the tactical map."""
        out = []
        for q in (self._route.get("pts") or ())[:MAX_ROUTE]:
            if hasattr(q, "approach"):
                out.append(tuple(q.approach))
            out.append(tuple(q))
        return out[:MAX_ROUTE]

    def needs_prompt(self) -> bool:
        return any(hasattr(q, "approach") for q in (self._route.get("pts") or ()))

    # --- the walk ---
    def approach(self, goal, *, run: bool | None = None, link: bool = True, now: float | None = None) -> tuple:
        """The stick toward goal (x, y, z): along the mesh's route when the goal is beyond DIRECT_R_MM, on another
        level, or behind a wall; else the straight line. run None: B beyond RUN_R_MM. A Y pulse at a crossing."""
        if now is not None:
            self.now = now
        pos = self._pos()
        self.wp, self.at_link = None, False
        if pos is None or goal is None or len(goal) < 2:
            return ()
        px, py, pz = pos
        gx, gz = goal[0], goal[2] if len(goal) > 2 else goal[1]
        dist = math.hypot(gx - px, gz - pz)
        far = dist > DIRECT_R_MM or (link and len(goal) > 2 and abs(goal[1] - py) > LEVEL_DY_MM)
        if not far and LOOKAHEAD and self.mesh is not None and len(goal) > 2 and not self._open(pos, gx, gz):
            far = True                                     # near, but behind a wall: the mesh's way round
            self._count("nav_near_walled")
        wp = self._waypoint(tuple(goal)) if far else None
        if not far and self._route.get("pts"):             # straight on, but the route in hand is kept current (a
            self._waypoint(tuple(goal))                    # crossing he has just made is counted and dropped)
            self.wp, self.at_link = None, False
        if wp is not None:
            tx, tz, self.how = wp[0], wp[1], "the stage mesh" + (" (a crossing)" if self.at_link else "")
        else:
            tx, tz, self.how = gx, gz, "the line"
            self._count("nav_direct_ticks")
        self.stats["walk_how"] = self.how
        rot = (self.p or {}).get("rot", (self.p or {}).get("facing")) or 0.0
        err = wrap(heading(tx - px, tz - pz) - rot)
        keys = self.steer(err, dist > RUN_R_MM if run is None else bool(run))
        if self.at_link:
            keys = tuple(k for k in keys if k != RUN)
            if int(self.now / ACTION_PULSE_S) % 2 == 0:
                keys += (ACTION,)
        return self._backstop(keys)

    def _backstop(self, keys: tuple) -> tuple:
        """NEVER_STAND for the walk: approach() asked STAND_MAX_S with no STAND_MOVE_MM of ground -> a step."""
        pos = self._pos()
        st = self._stand
        if pos is None:
            return keys
        if self.now < st["until"]:
            return st["keys"]
        if st["pos"] is None or _flat(pos, st["pos"]) > STAND_MOVE_MM or self.now - st["at"] > STAND_MAX_S * 4:
            st.update(pos=pos, at=self.now)
            return keys
        if self.now - st["at"] < STAND_MAX_S:
            return keys
        if self.wp is not None and not self.at_link:     # the route steered him into this: the push counts there
            self._route_wall(pos)
        step = self.step(pos)
        st.update(pos=pos, at=self.now, until=self.now + STAND_STEP_S, keys=step)
        self._count("stand_breaks")
        self.stats["walk_how"] = f"stood {STAND_MAX_S:.0f} s: a step along open floor (he never stands)"
        return step

    def step(self, pos=None) -> tuple:
        """A step along open floor: the heading nearest the route's point (or straight on) whose STAND_PROBE_MM probe
        is open floor; another way each time when none is."""
        pos = pos or self._pos()
        rot = (self.p or {}).get("rot", (self.p or {}).get("facing")) or 0.0
        want = wrap(heading(self.wp[0] - pos[0], self.wp[1] - pos[2]) - rot) if self.wp is not None else 0.0
        turns = sorted((math.radians(d) for d in range(-135, 181, 45)), key=lambda a: abs(wrap(a - want)))
        go = None
        if self.mesh is not None:
            for a in turns:
                h = rot + a
                if self._open(pos, pos[0] + STAND_PROBE_MM * math.sin(h), pos[2] + STAND_PROBE_MM * math.cos(h)):
                    go = a
                    break
        if go is None:
            go = turns[self._stand.get("n", 0) % len(turns)]
        self._stand["n"] = self._stand.get("n", 0) + 1
        if abs(go) <= ARC_TOL:
            return (FORWARD, self.turn_pos) if go > TURN_TOL else (FORWARD, self.turn_neg) if go < -TURN_TOL \
                else (FORWARD,)
        return (BACK, RUN) if abs(go) >= QUICK_TURN_ERR else ((self.turn_pos,) if go > 0 else (self.turn_neg,))

    def _route_wall(self, pos) -> bool:
        """A stall at the route's waypoint: counted, and at CROSSING_PUSHES that crossing is refused for the stage."""
        if self.wp is None:
            return False
        key = (round(self.wp[0] / 500.0), round(self.wp[1] / 500.0))
        st = self._push
        if st["key"] != key or self.now - st["at"] > 30.0:
            st.update(key=key, n=0)
        st["n"], st["at"] = st["n"] + 1, self.now
        self._count("mesh_crossing_pushes")
        if st["n"] < CROSSING_PUSHES:
            return False
        st.update(key=None, n=0)
        self.refuse((self.wp[0], pos[1], self.wp[1]), "a crossing the game does not let him walk")
        self._count("mesh_crossings_refused")
        return True

    # --- for the bot's own moves ---
    def guard(self, act: dict) -> dict:
        """re5_switch _mesh_guard: walking on (FORWARD held, the gun down) toward a wall, a fence or a drop within
        PROBE_MM of his facing, he turns to the nearest clear heading instead - unless the route steers this tick."""
        hold = set(act.get("hold") or ())
        pos, mesh = self._pos(), self.mesh
        if mesh is None or pos is None or FORWARD not in hold or "zl" in hold:
            return act
        rot = (self.p or {}).get("rot", (self.p or {}).get("facing")) or 0.0

        def clear(h):
            try:
                if mesh.member(pos) is None:
                    return None
            except Exception:                              # noqa: BLE001
                return None
            return self._open(pos, pos[0] + PROBE_MM * math.sin(h), pos[2] + PROBE_MM * math.cos(h))
        if clear(rot) is not False:
            return act
        if self.wp is not None and self.wp[2] == self.now:
            err = wrap(heading(self.wp[0] - pos[0], self.wp[1] - pos[2]) - rot)
            if abs(err) <= FOLLOW_TOL:
                return act
            return dict(act, hold=(hold - {FORWARD, RUN, self.turn_pos, self.turn_neg}) | set(self.steer(err, False)))
        for turn in TURNS:
            if clear(rot + turn):
                self._count("mesh_steers")
                return dict(act, hold=(hold - {FORWARD, RUN, self.turn_pos, self.turn_neg}) | set(self.steer(turn, False)))
        self._count("mesh_blocked")
        return dict(act, hold=hold - {FORWARD, RUN})

    def never_stand(self, act: dict, *, busy: bool = False) -> dict:
        """re5_switch _never_stand for any tick: STAND_MAX_S without STAND_MOVE_MM of ground, not aiming (ZL / L),
        firing or busy -> a STAND_STEP_S step along open floor."""
        pos = self._pos()
        hold = set(act.get("hold") or ())
        st = self._stand
        if busy or pos is None or "zl" in hold or "l" in hold or act.get("tap") or (self.p or {}).get("hp", 1) == 0:
            st.update(pos=pos, at=self.now, until=-1e9)
            return act
        if self.now < st["until"]:
            return dict(act, hold=set(st["keys"]))
        if st["pos"] is None or _flat(pos, st["pos"]) > STAND_MOVE_MM:
            st.update(pos=pos, at=self.now)
            return act
        if self.now - st["at"] < STAND_MAX_S:
            return act
        step = self.step(pos)
        st.update(pos=pos, at=self.now, until=self.now + STAND_STEP_S, keys=step)
        self._count("stand_breaks")
        return dict(act, hold=set(step))


# --- the operator's marks ----------------------------------------------------------------------------------------------
class Goals(map_goals.Goals):
    """map_goals.Goals with RE4's distances (mm): a marked spot is reached within GOAL_ARRIVE_MM (map_goals.ARRIVE is
    RE5's 200 cm). The enemy rule is map_goals' own (no health reading is alive; a slot empty ENEMY_GONE_S is down)."""

    def resolve(self, snap, now):
        goal = self.goal
        if goal and goal.get("kind") == "point" and goal["state"] not in map_goals.TERMINAL:
            if now - self.received_at > 300.:
                goal.update(state="expired", reason="Map goal expired after five minutes; choose it again")
                return None
            if now - self.received_at > map_goals.POINT_S:
                goal.update(state="expired", reason="The marked spot was not reached in two minutes")
                return None
            at = (snap.get("player") or {}).get("pos")
            if at and math.hypot(at[0] - goal["pos"][0], at[2] - goal["pos"][2]) <= GOAL_ARRIVE_MM:
                goal.update(state="completed", reason="He is at the marked spot; back to his own play")
                return None
            goal.update(state="active", reason="On his way to the marked spot by the map")
            return {"kind": "point", "pos": tuple(goal["pos"])}
        return super().resolve(snap, now)


def _now(bot) -> float:
    clock = getattr(bot, "clock", None)
    try:
        return float(clock()) if callable(clock) else time.monotonic()
    except Exception:                                      # noqa: BLE001
        return time.monotonic()


def walker_of(bot) -> Walker:
    """The bot's walker (bot.walker), made on first use with the bot's stats."""
    w = getattr(bot, "walker", None)
    if not isinstance(w, Walker):
        stats = getattr(bot, "stats", None)
        w = Walker(stats if isinstance(stats, dict) else None)
        bot.walker = w
    return w


def goals_of(bot) -> Goals:
    g = bot.__dict__.get("_re4_goals")
    if g is None:
        g = bot.__dict__.setdefault("_re4_goals", Goals())
    return g


def receive_map_goal(bot, value) -> None:
    """The tactical publisher's hand-over (engine thread): the operator's click."""
    g = goals_of(bot)
    before = (g.goal or {}).get("id")
    g.receive(value, _now(bot))
    stats = getattr(bot, "stats", None)
    if isinstance(stats, dict) and g.goal and g.goal.get("id") != before and g.goal.get("state") == "queued":
        stats["map_goals_taken"] = stats.get("map_goals_taken", 0) + 1


def map_goal_plan(bot) -> dict:
    g = goals_of(bot)
    return {"goal_round": g.round, "goal_capabilities": ["enemy", "point"], "operator_goal": g.public()}


def operator_goal_act(bot, snap: dict, now: float, fight) -> dict | None:
    """This tick's action for the operator's mark, None when there is none (his own play then). fight(snap) is the
    bot's own tick on a snapshot narrowed to the enemies to fight: the marked one in range with a clear line, or the
    ones on the way (within GOAL_FIGHT_MM on his level, GOAL_THREAT_MM on any)."""
    g = bot.__dict__.get("_re4_goals")
    if g is None or g.goal is None:
        return None
    try:
        row = g.resolve(snap, now)
    except Exception as exc:                               # noqa: BLE001 - a mark never stops the bot
        bot.stats["map_goal_error"] = f"{type(exc).__name__}: {exc}"[:120]
        return None
    stats = bot.stats if isinstance(getattr(bot, "stats", None), dict) else {}
    stats["map_goal_status"] = f"{g.goal.get('label')}: {g.goal.get('state')}"[:120]
    p = snap.get("player") or {}
    if row is None or not p.get("pos"):
        return None
    w = walker_of(bot)
    px, py, pz = p["pos"]
    flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)       # noqa: E731
    live = [e for e in snap.get("enemies") or () if e.get("pos") and (e.get("hp") is None or e.get("hp") > 0)]
    if row.get("kind") == "point":
        near = [e for e in live if flat(e) <= GOAL_THREAT_MM]
        if near:
            g.defer(f"Fighting off {len(near)} at arm's length")
            stats["map_goal_fight_ticks"] = stats.get("map_goal_fight_ticks", 0) + 1
            return fight(dict(snap, enemies=near))
        gx, _gy, gz = row["pos"]
        if g.goal.get("floor_y") is None:
            fy = None
            mesh = snap.get("nav")
            try:
                fy = mesh.floor_y(gx, gz, py) if mesh is not None and hasattr(mesh, "floor_y") else None
            except Exception:                              # noqa: BLE001
                fy = None
            g.goal["floor_y"] = py if fy is None else fy
        keys = w.approach((gx, g.goal["floor_y"], gz), run=math.hypot(gx - px, gz - pz) > RUN_R_MM)
        if w.no_exit():
            g.goal.update(state="unavailable", reason=str(stats.get("nav_status") or "no usable exit")[:140])
            return None
        stats["map_goal_walk_ticks"] = stats.get("map_goal_walk_ticks", 0) + 1
        bot.doing = "walk"
        bot.why = f"the operator's spot on the map, {math.hypot(gx - px, gz - pz) / 1000:.0f} m off - by the map"
        return {"hold": set(keys)}
    marked = row.get("ptr", row.get("slot"))
    near = [e for e in live if e.get("ptr", e.get("slot")) != marked
            and ((flat(e) <= GOAL_FIGHT_MM and abs(e["pos"][1] - py) <= LEVEL_DY_MM) or flat(e) <= GOAL_THREAT_MM)]
    if near:
        g.defer(f"Fighting through {len(near)} on the way")
        stats["map_goal_fight_ticks"] = stats.get("map_goal_fight_ticks", 0) + 1
        act = fight(dict(snap, enemies=near))
        bot.why = "the operator's mark, fighting through: " + str(getattr(bot, "why", ""))
        return act
    d, dy = flat(row), row["pos"][1] - py
    mesh = snap.get("nav")
    seg = getattr(mesh, "clear_segment", None) if mesh is not None else None
    try:
        clear = bool(seg(tuple(p["pos"]), tuple(row["pos"]))) if callable(seg) else True
    except Exception:                                      # noqa: BLE001
        clear = False
    engage = abs(dy) <= LEVEL_DY_MM and d <= GOAL_FIRE_MM and clear
    key = "map_goal_fight_ticks" if engage else "map_goal_walk_ticks"
    stats[key] = stats.get(key, 0) + 1
    if engage:
        act = fight(dict(snap, enemies=[row]))             # the fight, on him alone
        bot.why = "the operator's target: " + str(getattr(bot, "why", ""))
        return act
    keys = w.approach(row["pos"], run=True)
    if w.no_exit():
        g.goal.update(state="unavailable", reason=str(stats.get("nav_status") or "no usable exit")[:140])
        return None
    bot.doing = "walk"
    bot.why = (f"the operator's target {d / 1000:.0f} m off" + (f", {dy:+.0f} mm off his floor"
                                                                if abs(dy) > LEVEL_DY_MM else "") + " - by the map")
    return {"hold": set(keys)}


def plan(bot, base: dict | None = None) -> dict:
    """bot.plan() for the tactical map (tactical.take_plan): phase, note, the target (an enemy by its slot, the map's
    id), the walker's route (route_source room_collision) and the map-goal fields."""
    out = dict(base or {})
    w = getattr(bot, "walker", None)
    if getattr(bot, "doing", None):
        out.setdefault("phase", str(bot.doing)[:32])
    if getattr(bot, "why", None):
        out.setdefault("note", str(bot.why)[:80])
    target = getattr(bot, "target", None)
    if "target" not in out and target is not None and isinstance(w, Walker):
        row = next((e for e in (w.snap.get("enemies") or ()) if target in (e.get("ptr"), e.get("slot"))), None)
        if row is not None:
            out["target"] = {"kind": "enemy", "id": row.get("slot", row.get("ptr")), "pos": row.get("pos")}
    if isinstance(w, Walker) and "route" not in out and w.wp is not None and w.now - w.wp[2] <= 1.0:
        route = w.route_ahead()
        if route:
            out.update(route=route, route_source=ROUTE_SOURCE, route_requires_prompt=w.needs_prompt())
    out.update(map_goal_plan(bot))
    return out


def attach(cls):
    """A class decorator for re4_switch.Bot: see the module docstring. Idempotent."""
    tick = cls.__dict__.get("tick")
    if callable(tick) and not getattr(tick, "_re4_walk", False):
        @functools.wraps(tick)
        def wrapped(self, snap, *args, **kw):
            now = kw.get("now", args[0] if args else None)
            now = _now(self) if now is None else now
            if isinstance(snap, dict) and snap.get("module_base") is not None:
                re4_nav.attach(snap)                       # the stage mesh, before the fight reads it (a snapshot read
                                                           # from the game: synthetic ones keep the nav they carry)
            walker_of(self).observe(snap or {}, now)
            game = (snap or {}).get("game") if isinstance(snap, dict) else None
            if isinstance(game, dict) and not game.get("in_control"):
                return tick(self, snap, *args, **kw)       # not in control (re4_switch.game_state): the mark waits
            act = operator_goal_act(self, snap or {}, now, lambda s: tick(self, s, *args, **kw))
            return tick(self, snap, *args, **kw) if act is None else act
        wrapped._re4_walk = True
        cls.tick = wrapped
    if "receive_map_goal" not in cls.__dict__:
        cls.receive_map_goal = lambda self, value: receive_map_goal(self, value)
    if "map_goal_plan" not in cls.__dict__:
        cls.map_goal_plan = lambda self: map_goal_plan(self)
    own = cls.__dict__.get("plan")
    if own is None:
        cls.plan = lambda self: plan(self)
    elif not getattr(own, "_re4_walk", False):
        @functools.wraps(own)
        def merged(self):
            return plan(self, own(self))
        merged._re4_walk = True
        cls.plan = merged
    return cls


# --- the tactical map's publisher for the RE4 Switch playbook --------------------------------------------------------
MAP_ID = "010099A00BC1E000"


def publisher(sink):
    """The tactical map's publisher over the worker's sink (tools._start_playbook passes it as play(tactical=)), or
    None without one. Frames in mm."""
    if sink is None:
        return None
    return T.Publisher(sink, MAP_ID, "mm")


def publish(pub, snap: dict | None, bot=None, screen: str | None = None) -> None:
    """One tick's frame (pub(snap, bot, screen)) in a round, an idle frame between rounds; never raises."""
    if pub is None:
        return
    try:
        if snap and (snap.get("player") or {}).get("pos") is not None:
            re4_nav.attach(snap)
            pub(snap, bot, screen or "playing")
        else:
            pub.idle(screen or "menu")
    except Exception:                                      # noqa: BLE001 - the map never costs the bot a tick
        pass
