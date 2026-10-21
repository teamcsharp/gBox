"""A game-agnostic bot brain for gBox: perception -> target -> route -> steering and aim -> an Intent per tick.

The algorithms are GoldenEye 007's guard AI, distilled (docs/goldeneye_bots.md cites the decomp functions):
  * seeing is a straight floor-tile line that must end on the target's tile (chrCanSeeBond); the game layer computes
    it and reports `visible` per contact. Noticing takes longer when the target is far or off to the side
    (chrCheckTargetInSight's roll): here a reaction delay that grows with distance and angle;
  * memory: where each target was last seen, kept 10 s (chrSawTargetRecently, 600 ticks);
  * routing: shortest path over a node graph (GoldenEye's waypointFindRoute is a BFS over waypoint groups, then
    waypoints; multiplayer stages ship no waypoints, so the GoldenEye bridge builds a pad graph and this is A*);
  * stuck: no progress for about a second -> step aside, press use (doors), penalise the edge and re-plan
    (chrlvTickGoPos re-plans after 60 ticks without a good move; chrlvTravelTick probes around obstacles);
  * aim: turn toward the target at a capped rate (chrlvSetSubroty), shoot when the gun points inside a cone that
    shrinks with distance (chrlvGetAimLimitAngle: 14.4 degrees close up, 1.07 past 16 m);
  * difficulty: reaction, aim error, turn rate and trigger discipline per level, after the per-difficulty
    multipliers GoldenEye applies to guards (lvlSetMultipliersForDifficulty).

Everything game-specific (reading state, which buttons turn or fire, weapon names) lives in the game's driver
(gbox/ge007_bots.py for GoldenEye); this module only sees positions, headings and booleans.

Conventions: positions are (x, y, z) with y up; headings and bearings are degrees in the atan2(dx, dz) convention,
0..360. Intent.turn > 0 asks for a larger heading.
"""
import heapq
import math
import random
from dataclasses import dataclass, field


def wrap180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def bearing(frm, to) -> float:
    return math.degrees(math.atan2(to[0] - frm[0], to[2] - frm[2])) % 360.0


def dist2d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def dist3d(a, b) -> float:
    return math.dist(a, b)


MELEE_SCORE = 0.15            # weapon_score below this: fists, a knife or an empty gun


def aim_cone_deg(distance: float) -> float:
    """GoldenEye's hit cone half-angle by distance (chrlvGetAimLimitAngle); world units are ~1 cm."""
    for limit, cone in ((1600, 1.07), (800, 2.16), (400, 4.29), (200, 8.6)):
        if distance > limit:
            return cone
    return 14.4


@dataclass(frozen=True)
class Difficulty:
    name: str
    reaction_s: float          # first sight -> first shot, at close range straight ahead
    aim_jitter_deg: float      # spread of the aim point, re-rolled every ~0.4 s
    turn_rate: float           # fraction of the full turn input
    cone_scale: float          # >1 shoots while the aim is still off target
    burst_s: float
    rest_s: float
    strafe: bool               # sidestep while fighting
    memory_s: float = 10.0


# Guard multipliers per GoldenEye difficulty (accuracy, reaction): Agent 0.6/0.2, Secret Agent 0.75/0.5,
# 00 Agent 1/1, 007 1/1 (lv.c lvlSetMultipliersForDifficulty); 007 here also gets the sharpest trigger.
PRESETS = {
    "agent": Difficulty("agent", 0.9, 9.0, 0.55, 1.7, 0.5, 0.8, False),
    "secret": Difficulty("secret", 0.6, 5.0, 0.75, 1.3, 0.8, 0.5, True),
    "00": Difficulty("00", 0.35, 2.5, 0.9, 1.0, 1.2, 0.3, True),
    "007": Difficulty("007", 0.2, 1.0, 1.0, 0.9, 2.0, 0.2, True),
}


def difficulty(name) -> Difficulty:
    if isinstance(name, Difficulty):
        return name
    return PRESETS.get(str(name or "00").lower().replace("agent ", ""), PRESETS["00"])


@dataclass
class Body:
    pos: tuple
    heading: float             # degrees, atan2(dx, dz) convention
    alive: bool = True
    node: int = -1             # nearest node reachable in a straight walk (-1: unknown)
    weapon_score: float = 1.0  # 0 = no usable weapon .. 1 = best; the driver rates its game's weapons


@dataclass
class Contact:
    id: int
    pos: tuple
    alive: bool = True
    visible: bool = False      # I can see it (the game's line-of-sight test)
    hostile: bool = True
    node: int = -1


@dataclass
class World:
    now: float
    me: Body
    contacts: list = field(default_factory=list)
    items: list = field(default_factory=list)      # (pos, value 0..1): pickups worth walking to
    nav: "NavGraph | None" = None


@dataclass
class Intent:
    forward: float = 0.0       # -1 back .. 1 forward
    strafe: float = 0.0        # -1 left .. 1 right
    turn: float = 0.0          # -1 .. 1, > 0 = larger heading
    fire: bool = False
    use: bool = False          # doors, switches
    cycle_weapon: bool = False
    respawn: bool = False
    target: int | None = None
    goal: str = "idle"


class NavGraph:
    """Nodes (x, y, z) and adjacency lists; A* with straight-line costs and per-edge penalties."""

    def __init__(self, nodes, adj):
        self.nodes = [tuple(n) for n in nodes]
        self.adj = [list(a) for a in adj]

    def __len__(self):
        return len(self.nodes)

    def nearest(self, pos, among=None) -> int:
        best, bd = -1, float("inf")
        for i in (range(len(self.nodes)) if among is None else among):
            n = self.nodes[i]
            d = (n[0] - pos[0]) ** 2 + (n[2] - pos[2]) ** 2 + 4.0 * (n[1] - pos[1]) ** 2
            if d < bd:
                best, bd = i, d
        return best

    def path(self, start: int, goal: int, penalty=None) -> list[int]:
        """Node ids from start to goal inclusive; [] when unreachable."""
        if not (0 <= start < len(self.nodes) and 0 <= goal < len(self.nodes)):
            return []
        if start == goal:
            return [start]
        penalty = penalty or {}
        g = {start: 0.0}
        came = {}
        heap = [(dist3d(self.nodes[start], self.nodes[goal]), start)]
        closed = set()
        while heap:
            _f, u = heapq.heappop(heap)
            if u == goal:
                out = [u]
                while u in came:
                    u = came[u]
                    out.append(u)
                return out[::-1]
            if u in closed:
                continue
            closed.add(u)
            for v in self.adj[u]:
                cost = g[u] + dist3d(self.nodes[u], self.nodes[v]) * penalty.get((u, v), 1.0)
                if cost < g.get(v, float("inf")):
                    g[v], came[v] = cost, u
                    heapq.heappush(heap, (cost + dist3d(self.nodes[v], self.nodes[goal]), v))
        return []

    def reachable(self, start: int) -> set:
        seen, todo = {start}, [start]
        while todo:
            for v in self.adj[todo.pop()]:
                if v not in seen:
                    seen.add(v)
                    todo.append(v)
        return seen


class Brain:
    """One bot. Call tick(world) about 20-60 times a second; it returns what to press."""

    ARRIVE = 90.0             # node reached within this many units (GoldenEye's guards use 30 at walking speed)
    STUCK_WINDOW = 1.0        # seconds of wanted forward motion ...
    STUCK_MOVE = 40.0         # ... that moved less than this -> stuck
    REPLAN_S = 2.0

    def __init__(self, diff="00", rng=None):
        self.d = difficulty(diff)
        self.rng = rng or random.Random()
        self.target = None
        self.first_seen: dict[int, float] = {}
        self.last_seen: dict[int, tuple] = {}
        self.route: list[int] = []
        self.route_goal = None
        self.route_at = -1e9
        self.penalty: dict[tuple, float] = {}
        self.last_node = -1
        self.track: list[tuple] = []          # (t, pos, wanted_forward)
        self.stuck_until = 0.0
        self.stuck_side = 1.0
        self.stucks = 0
        self.aim_off = 0.0
        self.aim_off_at = -1e9
        self.burst_end = 0.0
        self.rest_end = 0.0
        self.strafe_dir = 1.0
        self.strafe_flip_at = 0.0
        self.respawn_at = 0.0
        self.roam_node = -1
        self.skip_items: dict[tuple, float] = {}
        self.stats = {"kills_seen": 0, "replans": 0, "stuck": 0, "shots": 0}

    @staticmethod
    def _item_key(pos) -> tuple:
        return (round(pos[0] / 50.0), round(pos[2] / 50.0))

    # ------------------------------------------------------------------ perception

    def _remember(self, w: World):
        now = w.now
        for c in w.contacts:
            if not c.hostile:
                continue
            if c.alive and c.visible:
                self.first_seen.setdefault(c.id, now)
                self.last_seen[c.id] = (c.pos, now)
            else:
                self.first_seen.pop(c.id, None)
                if not c.alive:
                    self.last_seen.pop(c.id, None)
        for cid, (_p, t) in list(self.last_seen.items()):
            if now - t > self.d.memory_s:
                del self.last_seen[cid]

    def _notice_s(self, me: Body, c: Contact) -> float:
        """Reaction delay: GoldenEye's roll makes far or off-angle targets slower to notice."""
        d = dist3d(me.pos, c.pos)
        off = abs(wrap180(bearing(me.pos, c.pos) - me.heading))
        return self.d.reaction_s * (1.0 + d / 3000.0) * (1.0 + max(0.0, off - 45.0) / 90.0)

    def _pick_target(self, w: World):
        me = w.me
        seen = [c for c in w.contacts if c.hostile and c.alive and c.visible]
        if not seen:
            self.target = None
            return None

        def score(c):
            return dist3d(me.pos, c.pos) * (1.0 + abs(wrap180(bearing(me.pos, c.pos) - me.heading)) / 90.0)
        best = min(seen, key=score)
        cur = next((c for c in seen if c.id == self.target), None)
        if cur is not None and score(cur) < 1.5 * score(best):
            best = cur                         # hysteresis: don't flick between two similar targets
        self.target = best.id
        return best

    # ------------------------------------------------------------------ steering

    def _steer(self, me: Body, toward, intent: Intent, speed: float = 1.0):
        err = wrap180(bearing(me.pos, toward) - me.heading)
        intent.turn = self._turn(err)
        intent.forward = speed if abs(err) < 35 else (0.4 * speed if abs(err) < 80 else 0.0)
        return err

    def _turn(self, err: float) -> float:
        t = max(-1.0, min(1.0, err / 30.0)) * self.d.turn_rate
        if abs(err) > 2.0 and abs(t) < 0.15:
            t = math.copysign(0.15, err)
        return t

    def _goal(self, w: World):
        """Where to go when nobody is in sight: a pickup when poorly armed, a remembered target, the nearest enemy,
        else a random node. Returns (pos, node or -1, label)."""
        me = w.me
        items = [it for it in w.items if self.skip_items.get(self._item_key(it[0]), 0.0) <= w.now]
        if items and me.weapon_score < 0.5:
            pos, _v = min(items, key=lambda it: dist3d(me.pos, it[0]) / (0.2 + it[1]))
            if dist2d(me.pos, pos) < self.ARRIVE:   # standing on it and it is still there: not ours to take
                self.skip_items[self._item_key(pos)] = w.now + 20.0
            return pos, -1, "pickup"
        if self.last_seen:
            cid, (pos, _t) = max(self.last_seen.items(), key=lambda kv: kv[1][1])
            if dist2d(me.pos, pos) > self.ARRIVE:
                return pos, -1, "chase"
            del self.last_seen[cid]
        live = [c for c in w.contacts if c.hostile and c.alive]
        if live:
            c = min(live, key=lambda c: dist3d(me.pos, c.pos))
            return c.pos, c.node, "hunt"
        nav = w.nav
        if nav and len(nav):
            if self.roam_node < 0 or dist2d(me.pos, nav.nodes[self.roam_node]) < self.ARRIVE:
                self.roam_node = self.rng.randrange(len(nav))
            return nav.nodes[self.roam_node], self.roam_node, "roam"
        return None, -1, "idle"

    def _follow(self, w: World, goal_pos, goal_node: int, intent: Intent):
        me, nav = w.me, w.nav
        if nav is None or not len(nav) or me.node < 0:
            if goal_pos is not None:
                self._steer(me, goal_pos, intent)
            return
        if goal_node < 0:
            goal_node = nav.nearest(goal_pos)
        stale = w.now - self.route_at > self.REPLAN_S
        emptied = not self.route and me.node != goal_node and w.now - self.route_at > 0.3
        if goal_node != self.route_goal or stale or emptied:
            start = me.node
            self.route = nav.path(start, goal_node, self.penalty)
            self.route_goal, self.route_at = goal_node, w.now
            self.stats["replans"] += 1
            if self.route and self.route[0] == start and len(self.route) > 1 and \
                    dist2d(me.pos, nav.nodes[start]) < self.ARRIVE * 1.5:
                self.last_node = self.route.pop(0)
        while self.route and dist2d(me.pos, nav.nodes[self.route[0]]) < self.ARRIVE:
            self.last_node = self.route.pop(0)
        if self.route:
            self._steer(me, nav.nodes[self.route[0]], intent)
        elif goal_pos is not None and dist2d(me.pos, goal_pos) > self.ARRIVE:
            self._steer(me, goal_pos, intent)

    def _check_stuck(self, w: World, intent: Intent):
        now, me = w.now, w.me
        self.track.append((now, me.pos, intent.forward))
        while self.track and now - self.track[0][0] > self.STUCK_WINDOW:
            self.track.pop(0)
        if now < self.stuck_until:
            intent.forward, intent.strafe, intent.use = -0.3, self.stuck_side, True
            return
        if len(self.track) < 4 or self.track[-1][0] - self.track[0][0] < self.STUCK_WINDOW * 0.9:
            return
        if min(f for _t, _p, f in self.track) < 0.5:
            return
        if dist2d(self.track[0][1], me.pos) < self.STUCK_MOVE:
            self.stucks += 1
            self.stats["stuck"] += 1
            self.stuck_side = self.rng.choice((-1.0, 1.0))
            self.stuck_until = now + 0.6 + 0.2 * min(self.stucks, 4)
            if self.route:
                edge = (self.last_node, self.route[0])
                self.penalty[edge] = self.penalty.get(edge, 1.0) * 4.0
            self.route = []
            self.track.clear()
            intent.forward, intent.strafe, intent.use = -0.3, self.stuck_side, True
        else:
            self.stucks = 0

    # ------------------------------------------------------------------ fighting

    def _fight(self, w: World, c: Contact, intent: Intent):
        me, now = w.me, w.now
        d = dist3d(me.pos, c.pos)
        if now - self.aim_off_at > 0.4:
            self.aim_off = self.rng.gauss(0.0, self.d.aim_jitter_deg)
            self.aim_off_at = now
        want = bearing(me.pos, c.pos)
        err = wrap180(want + self.aim_off - me.heading)
        intent.turn = self._turn(err)
        true_err = abs(wrap180(want - me.heading))
        ready = now - self.first_seen.get(c.id, now) >= self._notice_s(me, c)
        if me.weapon_score < MELEE_SCORE:          # fists or an empty gun: charge and hit at arm's length
            intent.forward = 1.0 if true_err < 40 else 0.3
            intent.fire = ready and d < 160 and true_err < 25
            intent.target, intent.goal = c.id, "melee"
            return
        if ready and true_err <= aim_cone_deg(d) * self.d.cone_scale + abs(self.aim_off) * 0.5:
            if now >= self.rest_end:
                if self.burst_end <= now:
                    self.burst_end = now + self.d.burst_s
                intent.fire = True
                self.stats["shots"] += 1
                if now >= self.burst_end:
                    self.rest_end = now + self.d.rest_s
        if d > 1400:
            intent.forward = 1.0 if true_err < 45 else 0.3
        elif d < 300:
            intent.forward = -0.6
        else:
            intent.forward = 0.25 if true_err < 30 else 0.0
        if self.d.strafe:
            if now >= self.strafe_flip_at:
                self.strafe_dir = -self.strafe_dir
                self.strafe_flip_at = now + self.rng.uniform(0.8, 1.6)
            intent.strafe = 0.8 * self.strafe_dir
        intent.target = c.id
        intent.goal = "fight"

    # ------------------------------------------------------------------ tick

    def tick(self, w: World) -> Intent:
        intent = Intent()
        if not w.me.alive:
            self.route, self.target, self.track = [], None, []
            self.first_seen.clear()
            if w.now >= self.respawn_at:
                intent.respawn = True
                self.respawn_at = w.now + 0.6
            intent.goal = "dead"
            return intent
        self._remember(w)
        c = self._pick_target(w)
        unarmed = w.me.weapon_score < MELEE_SCORE
        if c is not None and unarmed and w.items and dist3d(w.me.pos, c.pos) > 400:
            c = None                                 # unarmed and the enemy is not on top of us: arm first
        if c is not None:
            self._fight(w, c, intent)
        else:
            pos, node, label = self._goal(w)
            intent.goal = label
            self._follow(w, pos, node, intent)
        if w.me.weapon_score <= 0.0:
            intent.cycle_weapon = True
        self._check_stuck(w, intent)
        return intent
