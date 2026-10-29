"""Every engine round on a 2D map, for MercMode's run reviewer (operator 2026-10-27 20:28: "make sure that each of these
runs is being captured. And there is a 2D map that is showing the path that's being drawn by the bot as he's going
through and exploring the level ... so that way we can see how each and every run goes ... I'm not seeing a lot of
navigation. The bot is stuck in the very first area and never progresses.").

gbox.mercs.round_map's RoundTrace is fed by two brains of their own (RE5 PS3, RE4 GC). RunCapture is fed by the engine
(engine.play_round), so every engine title gets a map without a line in its brain - RE5 and RE6 on Switch first. A
brain that keeps its own round map (it has trace_finish) is left to it.

The bot loop pays a few appends: observe() keeps one sample every SAMPLE_S (5 a second) from what the engine already
holds that tick - the title's snapshot (his position, heading and health, the enemies, the statues / capsules, the
mines), the brain's decision (bot.doing / bot.why, stats phase) and the live counters (shots, hits, mines placed, prompt
presses, stuck) - into bounded lists. finish() (the round's evidence closing; inputs are released by then) returns the
round's exploration numbers for its curriculum row and hands the rest to a writer thread, which writes

    <data>/mercs/round_maps/<map id>/<stage>/<YYYYmmdd-HHMMSS>-<round id 8>.json   the run map (format below)
    ...                                     /<same stem>.svg                     the same map drawn
    ...                                     /extent/extent.json                  the stage's known extent (below)

and keeps the newest MAX_KEEP maps per stage folder. The JSON is a superset of RoundTrace's (title, room, round_id,
started, seconds, samples, distance, cells_visited, hotspots, verdict, stuck_events, hits_taken_events, standstills,
standing_still_s, time_by_phase, route [[t, x, z, y]], events) plus: format, stage, session_id, autoplay_job_id,
outcome, hp / heading (one per route sample), doing (run-length [sample, doing, phase, why]), enemies (every
ENEMY_EVERY-th sample, the ENEMY_MAX nearest [x, z]), clock ([sample, timer, score, combo, kills] once a second),
bonuses (each statue / capsule seen: where, when it went, how near he was, taken or not), cells (the visited cells) and
exploration (distance, cells, time within START_R of the spawn, the furthest from it, coverage of the known extent).

The known extent of a stage (extent.json): its navmesh's floor cells when the snapshot carries one (RE6 Switch), and
every cell any run of the stage saw him, an enemy or a statue in. Coverage = his cells / the known cells - so it starts
high on a stage seen only a few times and settles as runs add to it (the reviewer recomputes it against today's).

    python -m gbox.mercs.run_capture <run map .json>      # its exploration summary
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from pathlib import Path

FORMAT = "gbox.run_map/1"
SAMPLE_S = 0.2            # 5 samples a second
CELL = 250.0              # world units (cm on RE5 / RE6) of one exploration cell
START_R = 1000.0          # within 10 m of where he spawned: "the starting area"
JUMP_R = 1500.0           # further than this between two samples is a respawn / warp, not walked
ENEMY_EVERY = 5           # the enemies once a second
ENEMY_MAX = 16            # ... the nearest this many
CLOCK_EVERY = 5           # the clock / score once a second
ATTACKER_R = 600.0        # the live enemies this near when his health fell: the likely attackers (nearest 3)
BONUS_TAKE_R = 600.0      # a statue gone while he stood this near: taken
MAX_SAMPLES = 6000        # 20 minutes at 5 Hz; past it the last sample moves along (truncated_samples counts)
MAX_EVENTS = 4000
MAX_RUNS = 4000           # doing changes
MAX_BONUSES = 96
WHY_CHARS = 80
LABELLED_STILLS = 6       # the SVG names the longest standstills only (every one gets its ring)
MIN_SAMPLES = 10          # a round shorter than 2 s gets no map
MAX_KEEP = 200            # run maps kept per stage folder
EXTENT_MAX = 40000        # cells kept in a stage's extent
FLOOR_TRIS_MAX = 30000
THREADED = True           # finish() writes on its own thread (tests: False, on the caller's)

SHOT_KEYS = ("shots",)
HIT_KEYS = ("hits",)
MINE_KEYS = ("mines_placed", "bombs_placed")
PROMPT_KEYS = ("prompt_presses", "prompts_taken", "qte_presses", "tablet_presses", "resuscitate_presses")
STUCK_KEYS = ("stuck", "pursuit_stuck", "reloc_stuck", "reloc_dead_ends", "routes_blocked", "routes_given_up",
              "nav_fails")
TAKE_KEYS = ("bonuses_taken", "time_bonuses_taken", "yellows_taken", "greens_taken")
COUNTER_KEYS = SHOT_KEYS + HIT_KEYS + MINE_KEYS + PROMPT_KEYS + STUCK_KEYS + TAKE_KEYS

_EXTENT_LOCK = threading.Lock()
_FLOORS: dict = {}        # (id(mesh), triangles, cell) -> floor cells (a stage's navmesh is kept by its title module)
SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def slug(text, default: str = "unknown") -> str:
    s = SAFE.sub("_", str(text or "")).strip("_")[:60]
    return s or default


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if math.isfinite(v) else None


def _xyz(p):
    try:
        x, y, z = (float(c) for c in tuple(p)[:3])
    except (TypeError, ValueError):
        return None
    return (x, y, z) if all(math.isfinite(c) for c in (x, y, z)) else None


def _count(stats: dict, keys) -> dict:
    out = {}
    for k in keys:
        v = stats.get(k)
        if type(v) in (int, float):
            out[k] = v
    return out


def stage_of(stats: dict, snap: dict):
    """The round's stage name: stats stage_name / stage (RE6 Switch's draw), else the snapshot's stage; None unknown."""
    for v in (stats.get("stage_name"), stats.get("stage")):
        if isinstance(v, str) and v.strip() and v.strip().lower() != "unknown":
            return v.strip()[:60]
    st = snap.get("stage")
    for v in (st, getattr(st, "name", None), getattr(st, "key", None)):
        if isinstance(v, str) and v.strip() and v.strip().lower() != "unknown":
            return v.strip()[:60]
    return None


def mesh_of(snap: dict):
    """A navmesh in the snapshot (RE6 Switch: navmesh V / T; RE5 PS3: nav points / tris), else None."""
    for mesh in (snap.get("navmesh"), snap.get("nav")):
        if mesh is None:
            continue
        verts = getattr(mesh, "V", None) or getattr(mesh, "points", None)
        tris = getattr(mesh, "T", None) or getattr(mesh, "tris", None)
        if verts and tris:
            return mesh
    return None


def floor_cells(mesh, cell: float = CELL) -> set:
    """The cells a navmesh's triangles cover (a cell whose centre is inside one, or that holds a corner)."""
    verts = getattr(mesh, "V", None) or getattr(mesh, "points", None) or ()
    tris = getattr(mesh, "T", None) or getattr(mesh, "tris", None) or ()
    key = (id(mesh), len(tris), cell)
    if key in _FLOORS:
        return _FLOORS[key]
    out: set = set()
    for t in list(tris)[:FLOOR_TRIS_MAX]:
        try:
            (ax, _, az), (bx, _, bz), (cx, _, cz) = (tuple(verts[v])[:3] for v in tuple(t)[:3])
        except (IndexError, TypeError, ValueError):
            continue
        if not all(math.isfinite(c) for c in (ax, az, bx, bz, cx, cz)):
            continue
        for x, z in ((ax, az), (bx, bz), (cx, cz)):
            out.add((math.floor(x / cell), math.floor(z / cell)))
        area = (bx - ax) * (cz - az) - (cx - ax) * (bz - az)
        if abs(area) < 1e-6:
            continue
        i0, i1 = math.floor(min(ax, bx, cx) / cell), math.floor(max(ax, bx, cx) / cell)
        j0, j1 = math.floor(min(az, bz, cz) / cell), math.floor(max(az, bz, cz) / cell)
        if (i1 - i0 + 1) * (j1 - j0 + 1) > 4096:          # a degenerate / sentinel triangle
            continue
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                x, z = (i + .5) * cell, (j + .5) * cell
                d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
                d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
                d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
                if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
                    out.add((i, j))
    if len(_FLOORS) >= 8:
        _FLOORS.pop(next(iter(_FLOORS)))
    _FLOORS[key] = out
    return out


def exploration(route, cell: float = CELL) -> dict:
    """Distance walked (jumps left out), cells visited, time within START_R of the spawn and the furthest from it."""
    if not route:
        return {}
    sx, sz = route[0][1], route[0][2]
    dist = start_s = far = 0.0
    cells = {(math.floor(route[0][1] / cell), math.floor(route[0][2] / cell))}
    for a, b in zip(route, route[1:]):
        step = math.hypot(b[1] - a[1], b[2] - a[2])
        if step <= JUMP_R:
            dist += step
        if math.hypot(a[1] - sx, a[2] - sz) <= START_R:
            start_s += min(b[0] - a[0], 2.0)
        cells.add((math.floor(b[1] / cell), math.floor(b[2] / cell)))
    for p in route:
        far = max(far, math.hypot(p[1] - sx, p[2] - sz))
    seconds = sum(min(b[0] - a[0], 2.0) for a, b in zip(route, route[1:]))
    return {"seconds": round(seconds, 1), "distance_m": round(dist / 100.0, 1), "cells": len(cells),
            "cell": cell, "start_area_s": round(start_s, 1),
            "start_area_share": round(start_s / seconds, 3) if seconds > 0 else None,
            "start_r_m": START_R / 100.0, "max_from_spawn_m": round(far / 100.0, 1),
            "spawn": [round(sx), round(sz)], "end": [round(route[-1][1]), round(route[-1][2])]}


class RunCapture:
    """One round's run map: observe() every engine tick (cheap, throttled to SAMPLE_S), prompt() for the engine's own
    prompt presses, finish() once at the round's end."""

    def __init__(self, root, title: str, round_id: str | None = None, provenance: dict | None = None,
                 clock=time.time, cell: float = CELL, sample_s: float = SAMPLE_S, threaded: bool | None = None):
        self.root = Path(root) if root is not None else None      # <data>/mercs/round_maps
        self.title = slug(title)
        self.round_id = round_id or uuid.uuid4().hex
        prov = provenance or {}
        self.session_id = prov.get("source_session_id")
        self.job_id = prov.get("source_autoplay_job_id")
        self.clock, self.cell, self.sample_s = clock, float(cell), float(sample_s)
        self.threaded = THREADED if threaded is None else threaded
        self.route: list = []           # [t, x, z, y]
        self.hp: list = []
        self.heading: list = []
        self.hp_max = None
        self.doing: list = []           # [sample, doing, phase, why]
        self.enemies: list = []         # [sample, [[x, z(, kind index)], ...]]
        self.kinds: list = []           # the enemies' RAM classes, indexed by the rows' third value (enemy_kinds)
        self.clock_rows: list = []      # [sample, timer, score, combo, kills]
        self.bonuses: dict = {}         # id -> record
        self.events: list = []
        self.dropped = {"samples": 0, "events": 0, "doing": 0, "bonuses": 0}
        self.stage = None
        self.player_index = None
        self.mesh = None
        self.last_t = -math.inf
        self.started = self.ended = None
        self._ptr = self._last_hp = None
        self._dead = False
        self._counters: dict = {}
        self._kills = None
        self._take_sum = 0
        self.thread = None
        self.status: dict = {}

    # --- the bot loop's side: appends only -------------------------------------------------------------------------
    def observe(self, now: float, where: str, snap: dict, bot=None, stats: dict | None = None) -> bool:
        """One engine tick: a sample when SAMPLE_S has passed and the round is up (playing / dead). Never raises."""
        try:
            return self._observe(now, where, snap or {}, bot, stats if stats is not None else {})
        except Exception as exc:                            # noqa: BLE001 - the map never costs the round a tick
            self.status["observe_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return False

    def _observe(self, now, where, snap, bot, stats) -> bool:
        if where not in ("playing", "dead") or now - self.last_t < self.sample_s * 0.95:
            return False
        p = snap.get("player")
        pos = _xyz(p.get("pos")) if isinstance(p, dict) else None
        if pos is None:
            return False
        self.last_t = now
        self.started = self.started if self.started is not None else now
        self.ended = now
        x, y, z = pos
        hp, hp_max = _num(p.get("hp")), _num(p.get("hp_max"))
        head = _num(p.get("rot", p.get("facing")))
        row = [round(now, 2), round(x, 1), round(z, 1), round(y, 1)]
        if len(self.route) >= MAX_SAMPLES:                  # bounded: the end keeps moving, nothing more is kept
            self.route[-1], self.hp[-1] = row, hp
            self.heading[-1] = round(head, 2) if head is not None else None
            self.dropped["samples"] += 1
            return True
        self.route.append(row)
        self.hp.append(int(hp) if hp is not None else None)
        self.heading.append(round(head, 2) if head is not None else None)
        if hp_max is not None and hp_max > 0:
            self.hp_max = int(hp_max)
        i = len(self.route) - 1
        stage = stage_of(stats, snap)
        if stage:
            self.stage = stage
        if snap.get("player_index") is not None:
            self.player_index = snap.get("player_index")
        if self.mesh is None:
            self.mesh = mesh_of(snap)
        # what he is doing (the brain's decision; the operator's when they hold the pad)
        before = self.doing[-1][1] if self.doing else None
        doing = getattr(bot, "doing", None)
        doing = doing if isinstance(doing, str) and doing and doing != "none" else None
        phase = stats.get("phase") if isinstance(stats.get("phase"), str) else None
        if stats.get("operator_control") is True:
            doing = "operator"
        if where == "dead":
            doing = "dead"
        if doing is None and phase is None and type(bot).__name__ == "HumanObserver":
            doing = "human"
        if not self.doing or (self.doing[-1][1], self.doing[-1][2]) != (doing, phase):
            if len(self.doing) < MAX_RUNS:
                why = getattr(bot, "why", None)
                self.doing.append([i, doing, phase, str(why)[:WHY_CHARS] if isinstance(why, str) and why else None])
            else:
                self.dropped["doing"] += 1
        hit = hp is not None and self._last_hp is not None and p.get("ptr") == self._ptr and hp < self._last_hp
        live = [e for e in snap.get("enemies") or () if isinstance(e, dict) and _xyz(e.get("pos")) is not None
                and (_num(e.get("hp")) is None or e["hp"] > 0) and (_num(e.get("hp_max")) is None or e["hp_max"] > 1)]             if hit or i % ENEMY_EVERY == 0 else ()           # the enemies only when this sample keeps them
        if i % ENEMY_EVERY == 0:
            near = sorted(live, key=lambda e: math.hypot(e["pos"][0] - x, e["pos"][2] - z))[:ENEMY_MAX]
            self.enemies.append([i, [[round(e["pos"][0]), round(e["pos"][2])] + self._kind(e) for e in near]])
        if i % CLOCK_EVERY == 0:
            self.clock_rows.append([i, _num(snap.get("timer")), _num(snap.get("score")), _num(snap.get("combo")),
                                    _num(snap.get("kills"))])
        # his health: a fall is a hit (with who stood near), zero a death
        ptr = p.get("ptr")
        if hit:
            near = sorted(((math.hypot(e["pos"][0] - x, e["pos"][2] - z), e) for e in live), key=lambda de: de[0])
            near = [(d, e) for d, e in near if d <= ATTACKER_R][:3]
            self.event(now, "hit", x, z, loss=int(self._last_hp - hp), hp=int(hp),
                       dist=round(near[0][0]) if near else None,
                       attackers=[[round(e["pos"][0]), round(e["pos"][2]), round(d)] for d, e in near],
                       doing=doing, why=self.doing[-1][3] if self.doing else None)
        dead = where == "dead" or (hp is not None and hp <= 0)
        if dead and not self._dead:
            self.event(now, "death", x, z, doing=before if doing == "dead" else doing)
        self._dead = dead
        self._ptr, self._last_hp = ptr, hp
        # the counters: shots / hits, mines placed, prompts pressed, stuck
        counts = _count(stats, COUNTER_KEYS)
        if self._counters:
            d = {k: v - self._counters.get(k, v) for k, v in counts.items() if v > self._counters.get(k, v)}
            shots = sum(d.get(k, 0) for k in SHOT_KEYS)
            if shots or any(k in d for k in HIT_KEYS):
                self.event(now, "shots", x, z, n=shots, hits=sum(d.get(k, 0) for k in HIT_KEYS))
            if any(k in d for k in MINE_KEYS):
                self.event(now, "mine", x, z, n=sum(d.get(k, 0) for k in MINE_KEYS))
            if any(k in d for k in PROMPT_KEYS):
                self.event(now, "prompt", x, z, source="bot", counters={k: d[k] for k in PROMPT_KEYS if k in d},
                           prompt=_prompt_token(snap))
            if any(k in d for k in STUCK_KEYS):
                self.event(now, "stuck", x, z, counters={k: d[k] for k in STUCK_KEYS if k in d}, doing=doing)
        self._counters = counts
        kills = _num(snap.get("kills"))
        if kills is not None and self._kills is not None and kills > self._kills:
            self.event(now, "kill", x, z, n=int(kills - self._kills))
        if kills is not None:
            self._kills = kills
        self._bonus_tick(now, snap.get("bonuses"), x, z, sum(counts.get(k, 0) for k in TAKE_KEYS))
        return True

    def _kind(self, e) -> list:
        """[index into self.kinds] for an enemy of a known RAM class (the reviewer's legend), else []."""
        from . import enemy_kinds
        cls = e.get("class")
        if not enemy_kinds.valid_class(cls):
            return []
        if cls not in self.kinds:
            if len(self.kinds) >= 64:
                return []
            self.kinds.append(cls)
        return [self.kinds.index(cls)]

    def _bonus_tick(self, now, bonuses, x, z, take_sum) -> None:
        """The statues / capsules: first seen, and gone (taken when he stood near or a take counter rose meanwhile)."""
        if not isinstance(bonuses, list):                   # None: the scan failed this time - nothing is known gone
            return
        present = set()
        for b in bonuses:
            if not isinstance(b, dict) or _xyz(b.get("pos")) is None:
                continue
            bid = b.get("ptr", b.get("id"))
            bid = str(bid)[:24] if bid is not None else None
            if bid is None:
                continue
            present.add(bid)
            rec = self.bonuses.get(bid)
            if rec is None:
                if len(self.bonuses) >= MAX_BONUSES:
                    self.dropped["bonuses"] += 1
                    continue
                bx, by, bz = _xyz(b["pos"])
                rec = self.bonuses[bid] = {"id": bid, "kind": str(b.get("kind") or "time")[:16],
                                           "secs": _num(b.get("secs")), "pos": [round(bx), round(bz), round(by)],
                                           "seen_t": round(now, 2), "gone_t": None, "gone_d": None, "taken": False}
            rec["_take"] = take_sum
            if rec["gone_t"] is not None:                   # back in RAM: it never went
                rec.update(gone_t=None, gone_d=None, taken=False)
        for bid, rec in self.bonuses.items():
            if bid in present or rec["gone_t"] is not None:
                continue
            d = math.hypot(rec["pos"][0] - x, rec["pos"][1] - z)
            rec.update(gone_t=round(now, 2), gone_d=round(d), taken=d <= BONUS_TAKE_R or take_sum > rec.get("_take", 0))
            if rec["taken"]:
                self.event(now, "bonus", rec["pos"][0], rec["pos"][1], id=bid, bonus=rec["kind"], secs=rec["secs"],
                           dist=round(d))

    def prompt(self, now: float, chords) -> None:
        """The engine pressed the game's prompt (reactions.PromptPresser): where he stood, which buttons."""
        try:
            if not self.route:
                return
            _t, x, z, _y = self.route[-1]
            self.event(now, "prompt", x, z, source="engine", chord=["+".join(map(str, c)) for c in chords][:4])
        except Exception:                                   # noqa: BLE001
            pass

    def event(self, now: float, kind: str, x: float, z: float, **info) -> None:
        if len(self.events) >= MAX_EVENTS:
            self.dropped["events"] += 1
            return
        self.events.append({"t": round(now, 2), "kind": kind, "x": round(x, 1), "z": round(z, 1),
                            **{k: v for k, v in info.items() if v is not None}})

    # --- the round's end -------------------------------------------------------------------------------------------
    def finish(self, now: float, outcome: str | None, stage: str | None = None) -> dict:
        """The round is over: its exploration numbers now (flat, for the curriculum row) and the files on a writer
        thread. {} when the round was too short for a map."""
        try:
            if len(self.route) < MIN_SAMPLES or self.root is None:
                return {}
            if not self.stage and isinstance(stage, str) and stage.strip() and stage.strip().lower() != "unknown":
                self.stage = stage.strip()[:60]
            room = slug(self.stage)
            stem = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.started)) + "-" + self.round_id[:8]
            rel = f"round_maps/{self.title}/{room}/{stem}.json"
            ex = exploration(self.route, self.cell)
            self.status.update(file=rel, outcome=outcome)
            snapshot = self._snapshot(now, outcome, room, ex)
            if self.threaded:
                self.thread = threading.Thread(target=self._write, args=(snapshot, room, stem), daemon=True,
                                               name="mercs-run-map")
                self.thread.start()
            else:
                self._write(snapshot, room, stem)
            return {"round_map_file": rel, "round_map_stage": self.stage or "unknown",
                    "explore_seconds": ex["seconds"], "explore_distance_m": ex["distance_m"],
                    "explore_cells": ex["cells"], "explore_start_area_s": ex["start_area_s"],
                    "explore_start_area_share": ex["start_area_share"],
                    "explore_max_from_spawn_m": ex["max_from_spawn_m"], "explore_samples": len(self.route)}
        except Exception as exc:                            # noqa: BLE001 - a lost map never costs the round its row
            self.status["finish_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return {"round_map_error": self.status["finish_error"]}

    def wait(self, timeout: float = 5.0) -> dict:
        if self.thread is not None:
            self.thread.join(timeout)
        return self.status

    def _snapshot(self, now, outcome, room, ex) -> dict:
        """The round's buffers, detached from the capture (the writer thread works on these)."""
        bonuses = [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in self.bonuses.values()]
        return {"format": FORMAT, "title": self.title, "room": room, "stage": self.stage or "unknown",
                "round_id": self.round_id, "session_id": self.session_id, "autoplay_job_id": self.job_id,
                "player_index": self.player_index, "outcome": outcome, "started": self.started,
                "ended": round(self.ended if self.ended is not None else now, 2), "units": "cm", "cell": self.cell,
                "sample_s": self.sample_s, "hp_max": self.hp_max, "exploration": ex,
                "route": [list(r) for r in self.route], "hp": list(self.hp), "heading": list(self.heading),
                "doing": [list(r) for r in self.doing], "enemies": [list(r) for r in self.enemies], "kinds": list(self.kinds),
                "clock": [list(r) for r in self.clock_rows], "bonuses": bonuses, "events": list(self.events),
                "truncated": {k: v for k, v in self.dropped.items() if v},
                "_mesh": self.mesh}

    def _write(self, rec: dict, room: str, stem: str) -> None:
        try:
            mesh = rec.pop("_mesh", None)
            rec.update(summarize(rec))
            folder = self.root / self.title / room
            folder.mkdir(parents=True, exist_ok=True)
            floor = floor_cells(mesh, self.cell) if mesh is not None else set()
            seen = {(math.floor(x / self.cell), math.floor(z / self.cell))
                    for _i, rows in rec["enemies"] for x, z, *_kind in rows}
            seen |= {(math.floor(b["pos"][0] / self.cell), math.floor(b["pos"][1] / self.cell)) for b in rec["bonuses"]}
            visited = {tuple(c) for c in rec["cells"]}
            extent = merge_extent(folder / "extent" / "extent.json", self.cell, visited, seen, floor)
            rec["exploration"]["coverage"] = coverage(visited, extent)
            path = folder / f"{stem}.json"
            _atomic(path, json.dumps(rec, separators=(",", ":"), allow_nan=False))
            _atomic(folder / f"{stem}.svg", svg(rec, extent))
            self.status.update(written=str(path), coverage=rec["exploration"]["coverage"].get("value"))
            for old in sorted(folder.glob("*.json"))[:-MAX_KEEP]:
                old.unlink(missing_ok=True)
                old.with_suffix(".svg").unlink(missing_ok=True)
        except Exception as exc:                            # noqa: BLE001
            self.status["write_error"] = f"{type(exc).__name__}: {exc}"[:200]


def _prompt_token(snap: dict):
    pr = snap.get("prompt")
    if isinstance(pr, dict):
        pr = pr.get("button") or pr.get("kind") or pr.get("name")
    return str(pr)[:24] if pr not in (None, "", False) else None


def summarize(rec: dict) -> dict:
    """RoundTrace's numbers for a run map (hotspots, standstills, time by doing, the verdict), its visited cells."""
    from .round_map import RoundTrace, HOT_SHARE
    route, cell = rec.get("route") or [], float(rec.get("cell") or CELL)
    rt = RoundTrace(None, rec.get("title") or "", rec.get("room") or "", rec.get("round_id") or "", cell)
    rt.samples = [tuple(r) for r in route]
    runs = rec.get("doing") or []
    states, k = [], 0
    for i in range(len(route)):
        while k + 1 < len(runs) and runs[k + 1][0] <= i:
            k += 1
        st = {}
        if runs and runs[k][0] <= i:
            if runs[k][1] or runs[k][2]:
                st["phase"] = runs[k][1] or runs[k][2]
        states.append(st)
    rt.states, rt.mines, rt.started = states, [[] for _ in route], route[0][0] if route else None
    dwell = rt.dwell()
    total = sum(dwell.values()) or 1.0
    hot = sorted(dwell.items(), key=lambda kv: -kv[1])[:5]
    hotspots = [{"cell": list(c), "seconds": round(s, 1), "share": round(s / total, 3),
                 "center": [round((c[0] + .5) * cell), round((c[1] + .5) * cell)]} for c, s in hot]
    still = rt.standstills()
    still_s = round(sum(s["seconds"] for s in still), 1)
    verdict = None
    if hotspots and hotspots[0]["share"] >= HOT_SHARE:
        verdict = f"{hotspots[0]['share']:.0%} of the round in one {cell:g}-unit cell {tuple(hotspots[0]['cell'])}"
    ex = rec.get("exploration") or {}
    if ex.get("start_area_share") is not None and ex["start_area_share"] >= 0.8:
        verdict = (f"{ex['start_area_share']:.0%} of the round within {ex.get('start_r_m', 10):g} m of the spawn, "
                   f"never more than {ex.get('max_from_spawn_m', 0):g} m from it" + (f"; {verdict}" if verdict else ""))
    if still and still_s >= 0.2 * total:
        worst = max(still, key=lambda s: s["seconds"])
        verdict = (f"stood still {still_s:g} s ({still_s / total:.0%}) in {len(still)} stretch(es); worst "
                   f"{worst['seconds']:g} s doing {worst['phase'] or '?'}" + (f"; {verdict}" if verdict else ""))
    events = rec.get("events") or []
    cells = sorted({(math.floor(r[1] / cell), math.floor(r[2] / cell)) for r in route})
    return {"seconds": round(total, 1), "samples": len(route), "distance": round(ex.get("distance_m", 0) * 100),
            "cells_visited": len(dwell), "hotspots": hotspots, "verdict": verdict,
            "stuck_events": sum(e.get("kind") == "stuck" for e in events),
            "hits_taken_events": sum(e.get("kind") == "hit" for e in events),
            "deaths": sum(e.get("kind") == "death" for e in events),
            "standstills": still, "standing_still_s": still_s, "time_by_phase": rt.time_by_phase(),
            "bonuses_taken": sum(1 for b in rec.get("bonuses") or () if b.get("taken")),
            "bonuses_missed": sum(1 for b in rec.get("bonuses") or () if b.get("gone_t") is None),
            "cells": [list(c) for c in cells]}


def merge_extent(path: Path, cell: float, visited: set, seen: set, floor: set) -> dict:
    """The stage's known extent, with this run added (atomic; one writer at a time in this process)."""
    with _EXTENT_LOCK:
        old = load_extent(path, cell)
        ext = {"v": 1, "cell": cell, "runs": old["runs"] + 1, "updated": round(time.time(), 1),
               "visited": old["visited"] | visited, "seen": old["seen"] | seen, "floor": floor or old["floor"]}
        out = {k: (sorted([list(c) for c in v])[:EXTENT_MAX] if isinstance(v, set) else v) for k, v in ext.items()}
        try:
            _atomic(path, json.dumps(out, separators=(",", ":")))
        except OSError:
            pass
        return ext


def load_extent(path: Path, cell: float = CELL) -> dict:
    """A stage's extent.json as sets of cells ({"runs": 0, ...} empty when missing, unreadable or another cell size)."""
    empty = {"runs": 0, "visited": set(), "seen": set(), "floor": set(), "cell": cell}
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(d, dict) or float(d.get("cell") or 0) != float(cell):
        return empty
    cells = lambda k: {(int(c[0]), int(c[1])) for c in d.get(k) or () if isinstance(c, list) and len(c) == 2}
    return {"runs": int(d.get("runs") or 0), "visited": cells("visited"), "seen": cells("seen"),
            "floor": cells("floor"), "cell": cell, "updated": d.get("updated")}


def known_cells(extent: dict) -> tuple[set, str]:
    """The cells of a stage known to exist, and where that knowledge comes from."""
    if extent.get("floor"):
        return set(extent["floor"]) | set(extent["visited"]), "navmesh floor + his paths"
    return set(extent["visited"]) | set(extent["seen"]), "observed: his paths, enemies and statues"


def coverage(visited: set, extent: dict) -> dict:
    known, source = known_cells(extent)
    value = round(len(set(visited) & known) / len(known), 3) if known else None
    return {"value": value, "cells": len(set(visited) & known), "known_cells": len(known), "source": source,
            "runs": extent.get("runs", 0)}


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# --- the map drawn -----------------------------------------------------------------------------------------------------
RAMP = ((0.0, (56, 189, 248)), (0.4, (167, 139, 250)), (0.7, (244, 114, 182)), (1.0, (251, 191, 36)))


def ramp(f: float) -> str:
    """Early (cyan) -> late (amber) along the round."""
    f = max(0.0, min(1.0, f))
    for (a, ca), (b, cb) in zip(RAMP, RAMP[1:]):
        if f <= b:
            u = (f - a) / (b - a) if b > a else 0.0
            return "#%02x%02x%02x" % tuple(round(x + (y - x) * u) for x, y in zip(ca, cb))
    return "#%02x%02x%02x" % RAMP[-1][1]


def svg(rec: dict, extent: dict | None = None) -> str:
    route, cell = rec.get("route") or [], float(rec.get("cell") or CELL)
    known, _src = known_cells(extent) if extent else (set(), "")
    visited = {tuple(c) for c in rec.get("cells") or ()}
    xs = [r[1] for r in route] + [(c[0] + .5) * cell for c in known] + [b["pos"][0] for b in rec.get("bonuses") or ()]
    zs = [r[2] for r in route] + [(c[1] + .5) * cell for c in known] + [b["pos"][1] for b in rec.get("bonuses") or ()]
    if not xs:
        xs, zs = [0.0], [0.0]
    x0, x1, z0, z1 = min(xs) - cell, max(xs) + cell, min(zs) - cell, max(zs) + cell
    scale = 900.0 / max(x1 - x0, z1 - z0, 1.0)
    W, H = (x1 - x0) * scale, (z1 - z0) * scale
    X = lambda x, w=W: (x0 - x) * scale + w                # +x to the left (tactical.VIEW), +z up the page
    Z = lambda z: (z1 - z) * scale
    c = cell * scale
    W = max(W, 760.0)                                       # room for the words under a narrow stage
    foot = 20 + 19 * (5 if rec.get("verdict") else 4)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + foot:.0f}" viewBox="0 0 {W:.0f} '
           f'{H + foot:.0f}" font-family="sans-serif" font-size="13"><rect width="100%" height="100%" fill="#0e1116"/>']
    for (j, i0, i1), fill in _cell_runs(known, visited):     # each row's runs of one shade: one rect apiece
        out.append(f'<rect x="{X((i1 + 1) * cell):.1f}" y="{Z((j + 1) * cell):.1f}" width="{c * (i1 - i0 + 1):.1f}" '
                   f'height="{c:.1f}" fill="{fill}"/>')
    if route:
        sx, sz = route[0][1], route[0][2]
        out.append(f'<circle cx="{X(sx):.1f}" cy="{Z(sz):.1f}" r="{START_R * scale:.1f}" fill="none" stroke="#3ddc84" '
                   f'stroke-width="1.5" stroke-dasharray="6 5" stroke-opacity="0.7"/>')
    t0, t1 = (route[0][0], route[-1][0]) if route else (0, 1)
    for a, b in zip(route, route[1:]):
        if math.hypot(b[1] - a[1], b[2] - a[2]) > JUMP_R:
            continue
        col = ramp((a[0] - t0) / max(t1 - t0, 1e-6))
        out.append(f'<line x1="{X(a[1]):.1f}" y1="{Z(a[2]):.1f}" x2="{X(b[1]):.1f}" y2="{Z(b[2]):.1f}" stroke="{col}" '
                   f'stroke-width="2.5" stroke-linecap="round"/>')
    stills = rec.get("standstills") or ()
    named = {id(st) for st in sorted(stills, key=lambda st: -st["seconds"])[:LABELLED_STILLS]}
    for st in stills:                                      # every ring; words on the longest few
        x, z = X(st["at"][0]), Z(st["at"][1])
        out.append(f'<circle cx="{x:.1f}" cy="{z:.1f}" r="{6 + min(st["seconds"], 30) / 2:.1f}" fill="none" '
                   f'stroke="#ffd166" stroke-width="1.5" stroke-opacity="0.8"/>')
        if id(st) in named:
            out.append(f'<text x="{x + 10:.1f}" y="{z - 10:.1f}" fill="#ffd166" font-size="11">'
                       f'{_esc("%gs %s" % (st["seconds"], st.get("phase") or "?"))}</text>')
    for bo in rec.get("bonuses") or ():
        x, z = X(bo["pos"][0]), Z(bo["pos"][1])
        if bo.get("taken"):
            out.append(f'<circle cx="{x:.1f}" cy="{z:.1f}" r="7" fill="#f3cb70"/>')
        elif bo.get("gone_t") is None:
            out.append(f'<circle cx="{x:.1f}" cy="{z:.1f}" r="7" fill="none" stroke="#f3cb70" stroke-width="2"/>')
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{z:.1f}" r="6" fill="none" stroke="#8a8f98" stroke-width="2"/>')
    for e in rec.get("events") or ():
        x, z, k = X(e["x"]), Z(e["z"]), e.get("kind")
        if k == "hit":
            out.append(f'<circle cx="{x:.1f}" cy="{z:.1f}" r="{4 + min((e.get("loss") or 0) / 60.0, 8):.1f}" '
                       f'fill="#ff5c5c" fill-opacity="0.75"/>')
        elif k == "death":
            out.append(f'<path d="M{x - 9:.1f},{z - 9:.1f}L{x + 9:.1f},{z + 9:.1f}M{x - 9:.1f},{z + 9:.1f}L{x + 9:.1f},'
                       f'{z - 9:.1f}" stroke="#ff2d2d" stroke-width="4"/>')
        elif k == "mine":
            out.append(f'<path d="M{x:.1f},{z - 7:.1f}L{x + 7:.1f},{z:.1f}L{x:.1f},{z + 7:.1f}L{x - 7:.1f},{z:.1f}Z" '
                       f'fill="#82d89d"/>')
        elif k == "prompt":
            out.append(f'<rect x="{x - 4:.1f}" y="{z - 4:.1f}" width="8" height="8" fill="none" stroke="#5ee0f0" '
                       f'stroke-width="2"/>')
        elif k == "stuck":
            out.append(f'<path d="M{x - 6:.1f},{z - 6:.1f}L{x + 6:.1f},{z + 6:.1f}M{x - 6:.1f},{z + 6:.1f}L{x + 6:.1f},'
                       f'{z - 6:.1f}" stroke="#e6e6e6" stroke-width="2.5"/>')
    if route:
        out.append(f'<circle cx="{X(route[0][1]):.1f}" cy="{Z(route[0][2]):.1f}" r="7" fill="#3ddc84" stroke="#0e1116" '
                   f'stroke-width="2"/>')
        out.append(f'<circle cx="{X(route[-1][1]):.1f}" cy="{Z(route[-1][2]):.1f}" r="7" fill="#ffffff" '
                   f'stroke="#0e1116" stroke-width="2"/>')
    ex = rec.get("exploration") or {}
    cov = (ex.get("coverage") or {}).get("value")
    lines = [(f'{rec.get("title")} {rec.get("stage")} - {rec.get("outcome") or "?"} - {ex.get("seconds", 0):g} s, '
              f'{ex.get("distance_m", 0):g} m walked, {ex.get("cells", 0)} cells'
              + (f' ({cov:.0%} of the known stage)' if cov is not None else ""), "#e6e6e6"),
             (f'{ex.get("start_area_s", 0):g} s within {ex.get("start_r_m", 10):g} m of the spawn, furthest '
              f'{ex.get("max_from_spawn_m", 0):g} m from it; {rec.get("hits_taken_events", 0)} hits taken, '
              f'{rec.get("bonuses_taken", 0)} statues taken, {rec.get("bonuses_missed", 0)} left standing', "#e6e6e6")]
    if rec.get("verdict"):
        lines.append((rec["verdict"], "#ffd166"))
    lines += [("path cyan (start) to amber (end); green start, white end, dashed the starting area; red hits, red X "
               "death;", "#9aa0a6"),
              ("gold statue taken (ring: left standing, grey: gone); green mine, cyan square prompt, white x stuck, "
               "yellow ring standing still; grey cells the known stage", "#9aa0a6")]
    for k, (text, col) in enumerate(lines):
        out.append(f'<text x="8" y="{H + 20 + 19 * k:.0f}" fill="{col}" font-size="12">{_esc(text)}</text>')
    return "".join(out) + "</svg>"


def _cell_runs(known: set, visited: set):
    """[((row j, first i, last i), fill)]: consecutive cells of a row in one shade (his cells / the known stage)."""
    out, rows = [], {}
    for i, j in known | visited:
        rows.setdefault(j, []).append(i)
    for j in sorted(rows):
        run = None
        for i in sorted(rows[j]):
            fill = "#2b3a4d" if (i, j) in visited else "#1a212b"
            if run and run[1] == i - 1 and run[2] == fill:
                run[1] = i
            else:
                if run:
                    out.append(((j, run[0], run[1]), run[2]))
                run = [i, i, fill]
        if run:
            out.append(((j, run[0], run[1]), run[2]))
    return out


def _esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    import sys
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps({k: d.get(k) for k in ("title", "stage", "round_id", "outcome", "exploration", "verdict",
                                            "hits_taken_events", "deaths", "bonuses_taken", "bonuses_missed")},
                     indent=2))
