"""The tactical map's data (docs/tactical_map.md): a live top-down view of a Mercenaries round beside the game's stream,
drawn by gBox from the game's own state (operator 2026-10-21: "a second camera where we're looking at the view from top
down in order to have a more manageable experience ... I want Chris to have an awareness of where the nearest time
bonus is and to be able to navigate to it"). gBox draws it from RAM rather than a second in-game camera: a second
viewport hooked into RPCS3's recompiled code is risky, and moving the game's own camera overhead would break the bot's
aim, which follows the camera's look ray.

Contract gbox.tactical/1 - two payloads, both JSON, world units of the title (RE5 cm, RE4 mm), headings in radians in
the engines' atan2(dx, dz) convention (0 = +z, + toward +x):

  frame   one per engine tick, at most MAX_HZ a second, the newest wins (a few KB): who is where now and what the bot
          means to do - {v, t, title, stage, units, screen, clock, player, enemies, bonuses, plan}
  stage   the stage's layout, once per stage key (the navmesh's triangles, its walls and its crossings, or a grid)

The worker builds both here and posts them through a Publisher, never on the engine's frame-synced tick: the engine
hands the publisher (snap, bot, screen) each tick (engine.play_round(tactical=)); the publisher takes bot.plan() there
(cheap: what the bot already holds) and builds and posts the frame on its own thread. POST /api/autoplay/tactical/{sid}
answers need_stage when the control plane lacks the frame's stage (a restart): the stage then goes up with PUT
/api/autoplay/tactical/stage/{key}. The panel (clients/web/viz/tactical-map.js) polls the frames and fetches each stage
once.

bot.plan() (the title's brain; every key optional, docs/tactical_map.md):
    {"phase": "gather_time" | "combo_bonus" | "stand" | "break_for_time" | <short str>,
     "target": {"kind": "enemy" | "bonus" | "stand" | "waypoint", "id": slot | bonus ptr, "pos": (x, y, z)},
     "route": [(x, y, z), ...],                       the waypoints still ahead, the next first
     "stand": {"pos": (x, y, z), "r": units},         the planned stand spot
     "nearest_bonus": {"id", "kind", "dist": units along the route, "eta_s"},
     "enemy_flags": {slot: ["attacking", "blocking", "no_los", ...]},
     "note": "<= 80 chars"}
Without plan() (a brain that predates it): the target and route from bot.target / bot.route, and the nearest bonus by
the navmesh's route length (straight line without one) at RUN_SPEED, marked "est".
"""
from __future__ import annotations

import math
import struct
import threading
import time
import zlib
from urllib.parse import quote

FORMAT = 1
MAX_HZ = 10.0                     # frames a second at most while a round runs
IDLE_S = 1.0                      # between rounds: a frame (the screen) a second
VIEW = {"x": -1, "z": 1}          # how to draw the world from above: +z up, +x to the left (the engines' worlds are
                                  # right-handed, y up: facing +z, +x is on the player's left - the stick's left turns
                                  # toward larger headings, measured on both titles)
UNITS = {"BLUS30491": "cm", "G4BE08": "mm"}
RUN_SPEED = {"cm": 450.0, "mm": 3300.0}   # world units a second running: the fallback ETA (RE4: Up+B ~3,300 measured)
LEVEL_DY = {"cm": 150.0, "mm": 1500.0}    # within this above / below: the player's own level
CLIMB_RISE = {"cm": 120.0, "mm": 1200.0}  # a navmesh triangle rising this much, CLIMB_SLOPE times steeper than it is
CLIMB_SLOPE, CLIMB_JOIN = 2.5, 0.8        # wide, is a ladder or a drop (RE5's navmesh walks them as near-vertical
                                          # triangles); those within CLIMB_JOIN x CLIMB_RISE of each other are one
ROUTE_EVERY_S = 1.0               # the fallback's route lengths on the navmesh at most this often (A* is ~ms)
ROUTE_TRIES = 3                   # ...for this many of the nearest bonuses in a straight line
MAX_ROUTE, MAX_FLAGS, MAX_NOTE = 64, 8, 80


def units_for(title: str) -> str:
    return UNITS.get(str(title or ""), "cm")


def _n(v, nd: int = 0):
    """A finite number rounded (ints at nd 0), else None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return int(round(f)) if nd == 0 else round(f, nd)


def _xyz(p) -> list | None:
    try:
        x, y, z = (_n(c) for c in tuple(p)[:3])
    except (TypeError, ValueError):
        return None
    return None if None in (x, y, z) else [x, y, z]


def _id(v):
    """An entity id as JSON keeps it: ints stay ints (slots, pointers), anything else a short string."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None if v is None else str(v)[:40]


def _flat(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _path_len(start, pts) -> float:
    out, prev = 0.0, start
    for q in pts:
        out += math.dist(prev, q)
        prev = q
    return out


# --- the stage -------------------------------------------------------------------------------------------------------
def stage_key(title: str, mesh) -> str:
    """A stable key for a navmesh's stage: the same stage gets the same key every round and on every PC (the mesh's
    triangle count and a CRC of its points to the unit), so the panel's cache and the control plane's survive rounds."""
    pts = [int(round(c)) for p in mesh.points for c in p[:3]]
    crc = zlib.crc32(struct.pack(f"<{len(pts)}i", *pts)) & 0xFFFFFFFF if pts else 0
    return f"{title}.nav{len(mesh.tris)}.{crc:08x}"


def climbs_of(points, tris, units: str = "cm") -> list:
    """The ladders and drops of a navmesh: its near-vertical triangles (CLIMB_RISE, CLIMB_SLOPE), joined where they
    touch, as [x, z, y low, y high] (whole units)."""
    rise_min, out = CLIMB_RISE.get(units, 120.0), []
    for t in tris:
        try:
            a, b, c = (points[v] for v in t[:3])
        except (IndexError, TypeError):
            continue
        ys = (a[1], b[1], c[1])
        rise = max(ys) - min(ys)
        wide = max(math.hypot(p[0] - q[0], p[2] - q[2]) for p, q in ((a, b), (b, c), (c, a)))
        if rise < rise_min or rise < CLIMB_SLOPE * wide:
            continue
        cx, cz = (a[0] + b[0] + c[0]) / 3.0, (a[2] + b[2] + c[2]) / 3.0
        for cl in out:
            if math.hypot(cl[0] - cx, cl[1] - cz) < CLIMB_JOIN * rise_min:
                n = cl[4]
                cl[0], cl[1] = (cl[0] * n + cx) / (n + 1), (cl[1] * n + cz) / (n + 1)   # the climb's middle
                cl[2], cl[3], cl[4] = min(cl[2], min(ys)), max(cl[3], max(ys)), n + 1
                break
        else:
            out.append([cx, cz, min(ys), max(ys), 1])
    return [[int(round(v)) for v in cl[:4]] for cl in out]


def stage_from_navmesh(mesh, title: str, units: str = "cm", name: str | None = None) -> dict:
    """The stage payload of a navmesh (gbox.mercs.titles.re5_nav.NavMesh: points, tris, links (neighbour, edge, cost)):
    its points (flat ints), triangles (flat indices), its walls - each triangle edge nothing walks across - its
    crossings - links between triangles that do not share the edge's two ends (a jump: the bot takes them with the
    stage's prompt; some only the Majini can) - and its climbs (climbs_of: the ladders and drops). An edge whose link
    reaches a triangle sharing both of its ends (by position, to the unit) is open floor."""
    pts = [tuple(p[:3]) for p in mesh.points]
    key_of = [(int(round(p[0])), int(round(p[1])), int(round(p[2]))) for p in pts]
    tris = [tuple(t[:3]) for t in mesh.tris]
    used = sorted({v for t in tris for v in t if 0 <= v < len(pts)})
    remap = {v: i for i, v in enumerate(used)}
    walls, cross = [], []
    for i, t in enumerate(tris):
        if not all(0 <= v < len(pts) for v in t):
            continue
        links = mesh.links[i] if i < len(mesh.links) else ()
        open_edges, cross_edges = set(), set()
        for nb, edge, _cost in links:
            e = int(edge) % 3
            a, b = key_of[t[e]], key_of[t[(e + 1) % 3]]
            if 0 <= nb < len(tris) and {a, b} <= {key_of[v] for v in tris[nb] if 0 <= v < len(pts)}:
                open_edges.add(e)
            else:
                cross_edges.add(e)
        for e in range(3):
            pair = [remap[t[e]], remap[t[(e + 1) % 3]]]
            if e in cross_edges and e not in open_edges:
                cross += pair
            elif e not in open_edges:
                walls += pair
    xs = [key_of[v][0] for v in used] or [0]
    ys = [key_of[v][1] for v in used] or [0]
    zs = [key_of[v][2] for v in used] or [0]
    out = {"v": FORMAT, "key": stage_key(title, mesh), "title": title, "units": units, "kind": "mesh", "view": dict(VIEW),
           "bounds": [min(xs), min(zs), max(xs), max(zs)], "y": [min(ys), max(ys)],
           "points": [c for v in used for c in key_of[v]],
           "tris": [remap[v] for t in tris if all(0 <= v < len(pts) for v in t) for v in t],
           "walls": walls, "cross": cross, "climbs": climbs_of(pts, tris, units)}
    if name:
        out["name"] = str(name)[:60]
    return out


# --- the plan --------------------------------------------------------------------------------------------------------
def take_plan(bot) -> dict:
    """What the bot means to do, taken on the engine's thread (the bot changes its route as it walks): bot.plan() when
    the brain has one, else what an older brain holds (target, route). Never raises."""
    if bot is None:
        return {}
    fn = getattr(bot, "plan", None)
    if callable(fn):
        try:
            raw = fn()
        except Exception:                                   # noqa: BLE001 - a plan that fails is no plan
            raw = None
        if isinstance(raw, dict):
            out = dict(raw)
            if isinstance(out.get("route"), list):
                out["route"] = list(out["route"])           # the bot pops waypoints as it walks: a copy goes on
            return out
    out: dict = {"fallback": True}
    tgt = getattr(bot, "target", None)
    if isinstance(tgt, str) and tgt.startswith("bonus "):
        try:
            out["target"] = {"kind": "bonus", "id": int(tgt.split()[1], 16)}
        except (IndexError, ValueError):
            pass
    elif isinstance(tgt, int) and not isinstance(tgt, bool):
        out["target"] = {"kind": "enemy", "id": tgt}
    route = getattr(bot, "route", None)
    if route and (out.get("target") or {}).get("kind") == "bonus" and getattr(bot, "route_for", None) == out["target"]["id"]:
        out["route"] = [tuple(w) for w in list(route)[:MAX_ROUTE]]
    return out


def _clean_plan(raw: dict, enemies: dict, bonuses: dict) -> dict:
    """bot.plan() as the contract carries it: positions to the unit, sizes bounded, a target's position filled in from
    the frame when the plan leaves it out."""
    out: dict = {}
    if raw.get("phase"):
        out["phase"] = str(raw["phase"])[:32]
    tgt = raw.get("target")
    if isinstance(tgt, dict):
        kind, tid = str(tgt.get("kind") or "")[:16], _id(tgt.get("id"))
        pos = _xyz(tgt["pos"]) if tgt.get("pos") is not None else None
        if pos is None and kind == "enemy":
            pos = (enemies.get(tid) or {}).get("pos")
        if pos is None and kind == "bonus":
            pos = (bonuses.get(tid) or {}).get("pos")
        if kind or pos is not None:
            out["target"] = {k: v for k, v in (("kind", kind), ("id", tid), ("pos", pos)) if v is not None and v != ""}
    route = [p for p in (_xyz(w) for w in (raw.get("route") or ())[:MAX_ROUTE]) if p is not None]
    if route:
        out["route"] = route
    trail = [p for p in (_xyz(w) for w in (raw.get("trail") or ())[-240:]) if p is not None]
    if trail:
        out["trail"] = trail
    hazards = [{"pos": p, "reason": str(row.get("reason", ""))[:160]}
               for row in (raw.get("hazards") or ())[-64:] if isinstance(row, dict)
               and (p := _xyz(row.get("pos") or ())) is not None]
    if hazards:
        out["hazards"] = hazards
    st = raw.get("stand")
    if isinstance(st, dict) and _xyz(st.get("pos") or ()) is not None:
        out["stand"] = {"pos": _xyz(st["pos"])} | ({"r": _n(st["r"])} if _n(st.get("r")) else {})
    nb = raw.get("nearest_bonus")
    if isinstance(nb, dict):
        bid = _id(nb.get("id"))
        pos = _xyz(nb["pos"]) if nb.get("pos") is not None else (bonuses.get(bid) or {}).get("pos")
        near = {"id": bid, "kind": str(nb.get("kind") or (bonuses.get(bid) or {}).get("kind") or "time")[:16],
                "pos": pos, "dist": _n(nb.get("dist")), "eta_s": _n(nb.get("eta_s"), 1)}
        if nb.get("est"):
            near["est"] = True
        out["nearest_bonus"] = {k: v for k, v in near.items() if v is not None}
    flags = {}
    for k, v in (raw.get("enemy_flags") or {}).items() if isinstance(raw.get("enemy_flags"), dict) else ():
        fl = [str(f)[:16] for f in (v if isinstance(v, (list, tuple, set, frozenset)) else [v]) if f][:MAX_FLAGS]
        if fl:
            flags[_id(int(k) if isinstance(k, str) and k.lstrip("-").isdigit() else k)] = sorted(set(fl))
    if flags:
        out["enemy_flags"] = flags
    if raw.get("note"):
        out["note"] = str(raw["note"])[:MAX_NOTE]
    return out


# --- the frame -------------------------------------------------------------------------------------------------------
class Tracker:
    """Frames of one title's rounds (one per session, on the publisher's thread): remembers the hourglasses seen this
    round, so a taken one stays on the map (faded) after it leaves RAM; the stage of the navmesh in the snapshot, built
    once per mesh; the fallback's nearest bonus, routed at most every ROUTE_EVERY_S."""

    def __init__(self, title: str, units: str | None = None):
        self.title, self.units = str(title or ""), units or units_for(title)
        self.stage_key = ""
        self.stages: dict = {}                     # key -> stage payload (the newest few)
        self._mesh = None                          # the NavMesh object the stage key belongs to
        self.seen: dict = {}                       # bonus id -> {"pos", "kind"} this round
        self.taken: dict = {}                      # bonus id -> {"pos", "kind", "at"}
        self._near = (float("-inf"), {})           # (when, {bonus id: route length}) for the fallback ETA

    def stage_for(self, mesh) -> str:
        if mesh is self._mesh and self.stage_key:
            return self.stage_key
        st = stage_from_navmesh(mesh, self.title, self.units)
        if len(self.stages) >= 4:
            self.stages.pop(next(iter(self.stages)))
        self.stages[st["key"]] = st
        self._mesh, self.stage_key = mesh, st["key"]
        return self.stage_key

    def _forget_round(self):
        self.seen.clear()
        self.taken.clear()
        self._near = (float("-inf"), {})

    def nearest(self, ppos, standing: list, mesh, now: float) -> dict | None:
        """The fallback's nearest bonus: by route length on the navmesh (re-routed every ROUTE_EVERY_S for the
        ROUTE_TRIES nearest in a straight line), else the straight line; eta_s at RUN_SPEED, marked est."""
        if not standing:
            return None
        by_line = sorted(standing, key=lambda b: _flat(ppos, b["pos"]))
        lengths = self._near[1]
        if mesh is not None and now - self._near[0] >= ROUTE_EVERY_S:
            lengths = {}
            for b in by_line[:ROUTE_TRIES]:
                try:
                    rl = getattr(mesh, "route_length", None)
                    if callable(rl):
                        d = rl(tuple(ppos), tuple(b["pos"]))
                    else:
                        r = mesh.route(tuple(ppos), tuple(b["pos"]))
                        d = _path_len(tuple(ppos), r) if r else None
                except Exception:                           # noqa: BLE001 - no route: the straight line
                    d = None
                lengths[b["id"]] = d
            self._near = (now, lengths)
        cands = [(lengths[b["id"]], b) for b in by_line[:ROUTE_TRIES] if lengths.get(b["id"]) is not None]
        d, b = min(cands, key=lambda c: c[0]) if cands else (_flat(ppos, by_line[0]["pos"]), by_line[0])
        return {"id": b["id"], "kind": b["kind"], "pos": b["pos"], "dist": _n(d),
                "eta_s": _n(d / RUN_SPEED.get(self.units, 450.0), 1), "est": True}

    def frame(self, snap: dict | None, plan: dict | None = None, screen: str | None = None,
              now: float | None = None) -> dict:
        """One frame from the title's snapshot (the RE5 driver's shape: player {pos, rot, hp, hp_max, state, action},
        enemies [{slot, pos, hp, hp_max}], bonuses [{ptr, pos, kind}], timer, timer_start, combo, combo_timer, score,
        kills, nav) and the bot's plan (take_plan)."""
        now = time.time() if now is None else now
        snap = snap or {}
        p = snap.get("player")
        mesh = snap.get("nav")
        if mesh is not None and hasattr(mesh, "tris"):
            prev = self.stage_key
            if self.stage_for(mesh) != prev and prev:
                self._forget_round()                        # another stage: its hourglasses are new
        out: dict = {"v": FORMAT, "t": round(now, 3), "title": self.title, "stage": self.stage_key,
                     "units": self.units, "screen": str(screen or ("playing" if p else "loading"))[:24]}
        clock = {k: v for k, v in (("left", _n(snap.get("timer"), 2)), ("start", _n(snap.get("timer_start"), 1)),
                                   ("combo", _n(snap.get("combo"))), ("combo_left", _n(snap.get("combo_timer"), 2)),
                                   ("score", _n(snap.get("score"))), ("kills", _n(snap.get("kills"))))
                 if v is not None}
        if clock:
            out["clock"] = clock
        if not p or _xyz(p.get("pos") or ()) is None:
            self._forget_round()                            # between rounds: the next round's hourglasses are new
            return out
        ppos = _xyz(p["pos"])
        facing = p.get("rot", p.get("facing"))
        state = p.get("state")
        out["player"] = {k: v for k, v in (("pos", ppos), ("facing", _n(facing, 3)), ("hp", _n(p.get("hp"))),
                                           ("hp_max", _n(p.get("hp_max"))),
                                           ("state", None if state is None else str(state)[:16]),
                                           ("aim", True if state == "aim" or p.get("action") == 2 else None))
                         if v is not None}
        enemies: dict = {}
        awareness = {row.get("id"): row for row in (plan or {}).get("enemy_awareness", ())[:512]
                     if isinstance(row, dict) and row.get("visibility") in ("clear", "blocked", "unknown")}
        for e in snap.get("enemies") or ():
            pos = _xyz(e.get("pos") or ())
            hp, hp_max = _n(e.get("hp")), _n(e.get("hp_max"))
            if pos is None or (hp is not None and hp <= 0) or (hp_max is not None and hp_max <= 1):
                continue                                    # the dead, and the crows (1 health)
            eid = _id(e.get("slot", e.get("id")))
            row = {"id": eid, "pos": pos}
            if self.title == "BLUS30491":
                row["visibility"] = awareness.get(e.get("ptr", eid), {}).get("visibility", "unknown")
                if ppos is not None:
                    row["distance_cm"] = _n(math.dist(ppos, pos), 1)
            for k, v in (("hp", hp), ("hp_max", hp_max), ("facing", _n(e.get("rot", e.get("facing")), 3))):
                if v is not None:
                    row[k] = v
            enemies[eid] = row
        standing: dict = {}
        for b in snap.get("bonuses") or ():
            pos = _xyz(b.get("pos") or ())
            if pos is None:
                continue
            bid = _id(b.get("ptr", b.get("id")))
            standing[bid] = {"id": bid, "pos": pos, "kind": str(b.get("kind") or "time")[:16]}
        for bid, b in standing.items():
            self.seen[bid] = b
            self.taken.pop(bid, None)                       # back in RAM: it was never taken
        for bid, b in self.seen.items():
            if bid not in standing and bid not in self.taken:
                self.taken[bid] = dict(b, at=now)
        plan = _clean_plan(plan or {}, enemies, standing)
        tgt = plan.get("target") or {}
        flags = plan.pop("enemy_flags", {})
        for eid, row in enemies.items():
            fl = set(flags.get(eid, ()))
            if tgt.get("kind") == "enemy" and tgt.get("id") == eid:
                fl.add("target")
            if fl:
                row["flags"] = sorted(fl)
        out["enemies"] = list(enemies.values())
        out["bonuses"] = [dict(b, taken=False) for b in standing.values()] + \
                         [{"id": bid, "pos": b["pos"], "kind": b["kind"], "taken": True} for bid, b in self.taken.items()]
        if "nearest_bonus" not in plan:
            near = self.nearest(ppos, list(standing.values()), mesh if hasattr(mesh, "route") else None, now)
            if near:
                plan["nearest_bonus"] = near
        if plan:
            out["plan"] = plan
        return out


# --- posting ---------------------------------------------------------------------------------------------------------
class HttpSink:
    """The control plane's tactical routes for one session (the worker's own headers: its token, x-gbox-actor
    autoplay)."""

    def __init__(self, server: str, headers: dict, sid: str, timeout: float = 3.0, client=None):
        import httpx
        self.sid = sid
        self.client = client or httpx.Client(base_url=server.rstrip("/"), headers=dict(headers), timeout=timeout)

    def frame(self, body: dict) -> dict:
        r = self.client.post(f"/api/autoplay/tactical/{quote(self.sid, safe='')}", json=body)
        r.raise_for_status()
        return r.json()

    def stage(self, key: str, body: dict) -> dict:
        r = self.client.put(f"/api/autoplay/tactical/stage/{quote(key, safe='')}", json=body)
        r.raise_for_status()
        return r.json()

    def damage(self, body: dict) -> dict:
        # Durable replay can belong to an ended earlier session. Keep its original identity throughout delivery.
        sid = body.get("session_id") or self.sid
        r = self.client.post(f"/api/autoplay/damage/{quote(sid, safe='')}", json=body)
        r.raise_for_status()
        return r.json()

    def close(self):
        try:
            self.client.close()
        except Exception:                                   # noqa: BLE001
            pass


class Publisher:
    """The engine's tactical hook: publisher(snap, bot, screen) every tick. At most hz a second it takes the bot's plan
    (on the engine's thread: take_plan) and hands (snap, plan, screen) to its own thread, which builds the frame
    (Tracker) and posts it through the sink - the newest wins, so a slow or absent control plane never costs the round
    a tick. A reply with need_stage sends the frame's stage. idle(screen) between rounds (a frame a second); close()
    posts a last frame (screen "stopped") and ends the thread. stats: sent, stages, errors, last_error."""

    def __init__(self, sink, title: str, units: str | None = None, hz: float = MAX_HZ, clock=time.time,
                 tracker: Tracker | None = None, threaded: bool = True):
        self.sink, self.clock, self.min_dt = sink, clock, 1.0 / max(hz, 0.1)
        self.tracker = tracker or Tracker(title, units)
        self.stats = {"sent": 0, "stages": 0, "errors": 0, "last_error": ""}
        self._last = float("-inf")
        self._pending = None
        self._cv = threading.Condition()
        self._closed = False
        self._backoff_until = float("-inf")
        self._thread = None
        self.threaded = threaded

    # --- the engine's side (cheap) ---
    def __call__(self, snap, bot=None, screen=None):
        now = self.clock()
        if self._closed or now - self._last < self.min_dt * 0.95:     # (a tick's jitter never halves the rate)
            return False
        self._last = now
        self._offer((snap, take_plan(bot), screen, now))
        return True

    def idle(self, screen: str | None = None):
        """Between rounds (the menus): the screen once a second, no player."""
        now = self.clock()
        if self._closed or now - self._last < IDLE_S:
            return False
        self._last = now
        self._offer(({}, {}, screen or "menu", now))
        return True

    def close(self, screen: str = "stopped", wait: float = 2.0):
        if self._closed:
            return
        self._offer(({}, {}, screen, self.clock()))
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        th = self._thread
        if th is not None:
            th.join(wait)
        close = getattr(self.sink, "close", None)
        if callable(close):
            close()

    def _offer(self, item):
        if not self.threaded:
            self._send(item)
            return
        with self._cv:
            self._pending = item
            if self._thread is None and not self._closed:
                self._thread = threading.Thread(target=self._run, daemon=True, name="tactical-map")
                self._thread.start()
            self._cv.notify_all()

    # --- the publisher's thread ---
    def _run(self):
        while True:
            with self._cv:
                while self._pending is None and not self._closed:
                    self._cv.wait(1.0)
                item, self._pending = self._pending, None
                closed = self._closed
            if item is not None:
                self._send(item)
            if closed and self._pending is None:
                return

    def _send(self, item):
        snap, plan, screen, now = item
        try:
            f = self.tracker.frame(snap, plan, screen, now=now)
        except Exception as e:                              # noqa: BLE001 - a frame that can't be built is skipped
            self._error(e)
            return
        if self.clock() < self._backoff_until and screen != "stopped":
            return
        try:
            reply = self.sink.frame(f) or {}
            self.stats["sent"] += 1
            key = f.get("stage")
            if reply.get("need_stage") and key in self.tracker.stages:
                self.sink.stage(key, self.tracker.stages[key])
                self.stats["stages"] += 1
            self._backoff_until = float("-inf")
        except Exception as e:                              # noqa: BLE001 - the control plane away: try again shortly
            self._error(e)
            self._backoff_until = self.clock() + min(10.0, 1.0 + self.stats["errors"])

    def _error(self, e: Exception):
        self.stats["errors"] += 1
        self.stats["last_error"] = f"{type(e).__name__}: {e}"[:160]
