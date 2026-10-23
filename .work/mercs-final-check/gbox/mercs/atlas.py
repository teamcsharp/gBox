"""Durable stage geometry, checkpoint routes and round reviews from measured state.

Coordinates and directed links are supplied by the title's verified RAM reader.
An enemy navigation boundary is kept as a navigation boundary, not asserted to be a
physical wall. Doors, windows, stairs and item kinds require explicit observed
evidence; geometry alone never manufactures those labels.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
import sqlite3


def _json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _position(value):
    try:
        point = tuple(float(v) for v in value)
        return point if len(point) == 3 and all(math.isfinite(v) for v in point) else None
    except (TypeError, ValueError):
        return None


def _safe(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def mesh_geometry(mesh):
    """A complete directed mesh and its explicitly unlinked boundary edges."""
    points = [list(p) for p in mesh.points]
    triangles = [list(t) for t in mesh.tris]
    boundaries, action_links, links = [], [], []
    for u, triangle in enumerate(mesh.tris):
        open_edges = set()
        for v, edge, cost in mesh.links[u]:
            if not 0 <= v < len(mesh.tris) or not 0 <= edge < 3:
                continue
            pair = (triangle[edge], triangle[(edge + 1) % 3])
            ordinary = set(pair) <= set(mesh.tris[v]) and not mesh.steep[u] and not mesh.steep[v] \
                and abs(mesh.centre[u][1] - mesh.centre[v][1]) < 110.
            links.append([u, v, edge, cost if math.isfinite(cost) else None])
            if ordinary:
                open_edges.add(edge)
            else:
                action_links.append({"from": u, "to": v, "edge": list(pair), "status": "candidate",
                                     "evidence": "ram_navigation_link"})
        for edge in range(3):
            if edge not in open_edges:
                boundaries.append([u, triangle[edge], triangle[(edge + 1) % 3]])
    return {"points": points, "triangles": triangles, "links": links,
            "boundaries": boundaries, "action_links": action_links,
            "evidence": "ram_navigation_mesh", "boundary_meaning": "no ordinary directed floor link"}


class NavigationAtlas:
    """One title's SQLite atlas; call from a single background writer.

    Each run retains exact samples, inputs and observations as well as an SVG map
    and JSON review. Cross-round aggregates use stable geometry/landmark keys;
    relocated RAM pointers cannot change checkpoint identity.
    """
    def __init__(self, root, title):
        self.root = Path(root) / str(title)
        self.root.mkdir(parents=True, exist_ok=True)
        self.title = str(title)
        self.db = sqlite3.connect(self.root / "atlas.sqlite", timeout=5.)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS stages (
                key TEXT PRIMARY KEY, title TEXT NOT NULL, geometry TEXT NOT NULL,
                metadata TEXT NOT NULL, rounds INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS landmarks (
                key TEXT NOT NULL, stage TEXT NOT NULL, kind TEXT NOT NULL,
                x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL, evidence TEXT NOT NULL,
                sightings INTEGER NOT NULL DEFAULT 0, acquired INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(stage,key));
            CREATE TABLE IF NOT EXISTS rounds (
                id TEXT PRIMARY KEY, stage TEXT NOT NULL, started REAL NOT NULL,
                ended REAL, outcome TEXT, metadata TEXT NOT NULL, review TEXT,
                json_path TEXT, map_path TEXT);
            CREATE TABLE IF NOT EXISTS samples (
                round_id TEXT NOT NULL, seq INTEGER NOT NULL, at REAL NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(round_id,seq));
            CREATE TABLE IF NOT EXISTS events (
                round_id TEXT NOT NULL, seq INTEGER NOT NULL, at REAL NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(round_id,seq));
            CREATE TABLE IF NOT EXISTS checkpoint_routes (
                stage TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
                best_seconds REAL, best_distance REAL, best_path TEXT,
                PRIMARY KEY(stage,origin,destination));
            CREATE INDEX IF NOT EXISTS samples_round ON samples(round_id,seq);
            CREATE INDEX IF NOT EXISTS rounds_stage ON rounds(stage,started);
        """)
        self.active = {}

    def stage(self, mesh, metadata=None):
        key = mesh.learning_sig
        if not self.db.execute("SELECT 1 FROM stages WHERE key=?", (key,)).fetchone():
            self.db.execute("INSERT INTO stages(key,title,geometry,metadata) VALUES(?,?,?,?)",
                            (key, self.title, _json(mesh_geometry(mesh)), _json(metadata or {})))
            self.db.commit()
        return key

    def begin(self, round_id, stage, at, metadata=None):
        if round_id in self.active:
            return
        self.db.execute("INSERT OR IGNORE INTO rounds(id,stage,started,metadata) VALUES(?,?,?,?)",
                        (round_id, stage, at, _json(metadata or {})))
        seq = self.db.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM samples WHERE round_id=?", (round_id,)).fetchone()[0]
        ev_seq = self.db.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM events WHERE round_id=?", (round_id,)).fetchone()[0]
        self.active[round_id] = {"stage": stage, "seq": seq, "event_seq": ev_seq, "seen": {},
                                 "previous": None, "segment": [], "checkpoint": "spawn", "checkpoint_at": at,
                                 "checkpoint_distance": 0., "checkpoint_path": [], "pending": 0}
        self.active[round_id]["checkpoint_continuous"] = True
        self.db.commit()

    @staticmethod
    def landmark_key(kind, pos):
        return str(kind)[:40] + ":" + ":".join(str(round(v)) for v in pos)

    def landmark(self, stage, kind, pos, evidence):
        pos = _position(pos)
        if pos is None or not evidence:
            return None
        key = self.landmark_key(kind, pos)
        self.db.execute("INSERT INTO landmarks(key,stage,kind,x,y,z,evidence,sightings) VALUES(?,?,?,?,?,?,?,1) "
                        "ON CONFLICT(stage,key) DO UPDATE SET sightings=sightings+1,evidence=excluded.evidence",
                        (key, stage, str(kind)[:40], *pos, _json(evidence)))
        return key

    def event(self, round_id, at, kind, payload):
        state = self.active[round_id]
        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                        (round_id, state["event_seq"], at, str(kind)[:64], _json(payload)))
        state["event_seq"] += 1

    def sample(self, round_id, at, frame, *, inputs=(), prompt=None, events=None, observations=()):
        """Record one bounded-frequency frame. Acquisition requires caller-confirmed evidence.

        Observations: {kind,pos,evidence,acquired?}; `acquired` must be backed by
        the title reader's object-state transition, never inferred just from proximity.
        """
        state = self.active[round_id]
        player = frame.get("player") or {}
        pos = _position(player.get("pos"))
        payload = {"frame": frame, "inputs": sorted(inputs), "prompt": prompt}
        self.db.execute("INSERT INTO samples VALUES(?,?,?,?)",
                        (round_id, state["seq"], at, _json(payload)))
        state["seq"] += 1
        previous = state["previous"]
        if pos is not None:
            if state["previous"] is None and state["checkpoint"] == "spawn":
                state["checkpoint"] = self.landmark_key("spawn", pos)
            if previous is not None:
                before, before_at = previous
                # Loading/teleport jumps must not become a learned walkable route.
                if 0 < at - before_at <= 2. and math.dist(pos, before) <= 800. * (at - before_at) + 30.:
                    state["checkpoint_distance"] += math.dist(pos, before)
                else:
                    state["checkpoint_path"] = []
                    state["checkpoint_continuous"] = False
            state["previous"] = (pos, at)
            state["checkpoint_path"].append([at, *pos])
            state["segment"].append((at, pos, tuple(sorted(inputs))))
            state["segment"] = state["segment"][-24:]
        for event, value in (events or {}).items():
            self.event(round_id, at, event, {"value": value, "pos": pos,
                                          "plan": frame.get("plan"), "enemies": frame.get("enemies", [])})
        for event in (frame.get("mine_events") or ())[:128]:
            if not isinstance(event,dict) or not event.get("kind"):
                continue
            # Controller records are emitted once by Recorder. A detonation flag
            # witnesses an explosion state, never proof of a kill or its owner.
            details = dict(event)
            kind = str(details.pop("kind"))[:48]
            event_at = details.pop("at",at)
            details.setdefault("pos",pos)
            details["evidence"] = "ram_proximity_bomb_controller"
            if kind == "detonation_observed":
                details["kill_attribution"] = "unverified"
            self.event(round_id,event_at,"mine_"+kind,details)
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            landmark_pos = _position(observation.get("pos"))
            if landmark_pos is None:
                continue
            key = self.landmark(state["stage"], observation.get("kind", "unclassified"), landmark_pos,
                                observation.get("evidence"))
            if key is not None and observation.get("acquired") and key not in state["seen"]:
                state["seen"][key] = True
                self._acquire(round_id, at, key, landmark_pos, observation)
        state["pending"] += 1
        if state["pending"] >= 16:
            self.db.commit()
            state["pending"] = 0

    def _acquire(self, round_id, at, key, pos, observation):
        state = self.active[round_id]
        self.db.execute("UPDATE landmarks SET acquired=acquired+1 WHERE stage=? AND key=?", (state["stage"], key))
        self.event(round_id, at, "checkpoint_acquired", {"key": key, "pos": pos, "evidence": observation["evidence"]})
        if observation.get("kind") != "time":
            return
        seconds, distance = at - state["checkpoint_at"], state["checkpoint_distance"]
        route = state["checkpoint_path"]
        # Do not persist a shortcut if the samples are discontinuous or path is missing.
        complete = state["checkpoint_continuous"] and bool(route) and seconds > 0 and len(route) >= 2 \
            and math.dist(route[-1][1:], pos) <= 200.
        self.db.execute("INSERT INTO checkpoint_routes(stage,origin,destination,attempts,completed,best_seconds,best_distance,best_path) "
                        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(stage,origin,destination) DO UPDATE SET "
                        "attempts=attempts+1,completed=completed+excluded.completed,"
                        "best_path=CASE WHEN excluded.completed=1 AND (best_seconds IS NULL OR excluded.best_seconds<best_seconds) "
                        "THEN excluded.best_path ELSE best_path END,"
                        "best_distance=CASE WHEN excluded.completed=1 AND (best_seconds IS NULL OR excluded.best_seconds<best_seconds) "
                        "THEN excluded.best_distance ELSE best_distance END,"
                        "best_seconds=CASE WHEN excluded.completed=1 AND (best_seconds IS NULL OR excluded.best_seconds<best_seconds) "
                        "THEN excluded.best_seconds ELSE best_seconds END",
                        (state["stage"], state["checkpoint"], key, 1, int(complete),
                         seconds if complete else None, distance if complete else None, _json(route) if complete else None))
        state.update(checkpoint=key, checkpoint_at=at, checkpoint_distance=0., checkpoint_path=[], checkpoint_continuous=True)

    def finish(self, round_id, at, outcome, metrics=None):
        state = self.active.get(round_id)
        if state is None:
            return None
        samples = [json.loads(raw) | {"at": t} for t, raw in self.db.execute(
            "SELECT at,payload FROM samples WHERE round_id=? ORDER BY seq", (round_id,))]
        events = [{"at": t, "kind": kind, **json.loads(raw)} for t, kind, raw in self.db.execute(
            "SELECT at,kind,payload FROM events WHERE round_id=? ORDER BY seq", (round_id,))]
        review = self.review(samples, events, metrics or {})
        geometry = json.loads(self.db.execute("SELECT geometry FROM stages WHERE key=?", (state["stage"],)).fetchone()[0])
        landmarks = [{"key": k, "kind": kind, "pos": [x,y,z], "acquired": acquired}
                     for k,kind,x,y,z,acquired in self.db.execute(
                         "SELECT key,kind,x,y,z,acquired FROM landmarks WHERE stage=?", (state["stage"],))]
        dest = self.root / "rounds" / _safe(round_id)
        dest.mkdir(parents=True, exist_ok=True)
        artifact = {"version": 1, "round_id": round_id, "title": self.title, "stage": state["stage"],
                    "outcome": outcome, "review": review, "geometry": geometry,
                    "landmarks": landmarks, "samples": samples, "events": events}
        json_path, map_path = dest / "round.json", dest / "map.svg"
        json_path.write_text(_json(artifact), encoding="utf-8")
        map_path.write_text(render_map(geometry, samples, events, landmarks), encoding="utf-8")
        self.db.execute("UPDATE rounds SET ended=?,outcome=?,review=?,json_path=?,map_path=? WHERE id=?",
                        (at, str(outcome), _json(review), str(json_path), str(map_path), round_id))
        self.db.execute("UPDATE stages SET rounds=rounds+1 WHERE key=?", (state["stage"],))
        self.db.commit()
        del self.active[round_id]
        return {"review": review, "json": str(json_path), "map": str(map_path), "database": str(self.root / "atlas.sqlite")}

    @staticmethod
    def review(samples, events, metrics):
        positions = [(s["at"], _position((s.get("frame", {}).get("player") or {}).get("pos")), s) for s in samples]
        positions = [(t,p,s) for t,p,s in positions if p is not None]
        distance = stationary = 0.
        targets, reversals, recent = [], 0, []
        for (t,p,s),(nt,np,ns) in zip(positions, positions[1:]):
            dt, moved = nt-t, math.dist(p,np)
            if not 0 < dt <= 2. or moved > 800.*dt+30.:
                recent = []
                continue
            distance += moved
            if moved < 12. and any(k in ns.get("inputs", ()) for k in ("lup", "ldown", "lleft", "lright")):
                stationary += dt
            cell = (round(np[0]/100.), round(np[1]/80.), round(np[2]/100.))
            if not recent or recent[-1] != cell:
                recent.append(cell)
                if len(recent) >= 4 and recent[-4] == recent[-2] and recent[-3] == recent[-1]:
                    reversals += 1
                recent = recent[-4:]
            target = ((ns.get("frame", {}).get("plan") or {}).get("target") or {}).get("id")
            if target is not None and (not targets or targets[-1] != target):
                targets.append(target)
        checkpoints = [e["key"] for e in events if e["kind"] == "checkpoint_acquired" and str(e.get("key", "")).startswith("time:")]
        actions = []
        if stationary >= 2.:
            actions.append("Replan the failed portal after bounded stationary movement; retain the checkpoint goal.")
        if reversals:
            actions.append("Apply measured reversal penalties and hold the checkpoint through optional combat.")
        if not checkpoints:
            actions.append("No time-bonus acquisition was confirmed; inspect object-state and route evidence before scoring this route.")
        mine_events = [event for event in events if event["kind"].startswith("mine_")]
        ground_actors = {str(mine.get("actor")) for sample in samples for mine in sample.get("frame",{}).get("mines",())}
        placements = {str(event.get("actor")) for event in mine_events if event["kind"] == "mine_placement_verified"}
        observed_placements = metrics.get("mines_placed")
        observed_placements = max(0,int(observed_placements)) if isinstance(observed_placements,(int,float)) \
            and math.isfinite(observed_placements) else 0
        mine_review = {"placements_verified": max(len(placements),observed_placements),
                       "ground_actors_observed": len(ground_actors),
                       "detonation_events_observed": sum(e["kind"] == "mine_detonation_observed" for e in mine_events),
                       "retreats_completed": sum(e["kind"] == "mine_retreat_complete" for e in mine_events),
                       "unconfirmed_placements": sum(e["kind"] == "mine_placement_unconfirmed" for e in mine_events),
                       "actor_disappearances_unknown": sum(e["kind"] == "mine_actor_disappeared" for e in mine_events),
                       "kills_attributed": None, "damage_attributed": None}
        if mine_review["placements_verified"] > mine_review["retreats_completed"]:
            actions.append("Check measured separation after every planted mine; deployment does not prove the escape completed.")
        return {"distance": round(distance,2), "commanded_stationary_s": round(stationary,2),
                "oscillations": reversals, "target_changes": max(0,len(targets)-1),
                "time_bonuses_acquired": len(set(checkpoints)), "checkpoint_order": checkpoints,
                "mines": mine_review,
                "events": {kind: sum(e["kind"] == kind for e in events) for kind in sorted({e["kind"] for e in events})},
                "metrics": metrics, "next_round_actions": actions,
                "rank_verified": bool(metrics.get("rank_verified")), "rank": metrics.get("rank")}

    def close(self):
        self.db.commit()
        self.db.close()


def render_map(geometry, samples, events, landmarks=()):
    """Standalone evidence map, retaining altitude and event details in tooltips."""
    points = geometry.get("points", [])
    positions = [_position((s.get("frame", {}).get("player") or {}).get("pos")) for s in samples]
    positions = [p for p in positions if p is not None]
    all_points = points + positions or [(0.,0.,0.),(100.,0.,100.)]
    x0,z0 = min(p[0] for p in all_points)-100., min(p[2] for p in all_points)-100.
    width,height = max(p[0] for p in all_points)-x0+100., max(p[2] for p in all_points)-z0+100.
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {z0} {width} {height}">',
            f'<rect x="{x0}" y="{z0}" width="{width}" height="{height}" fill="#101820"/>']
    for _,a,b in geometry.get("boundaries", []):
        p,q = points[a],points[b]
        body.append(f'<path d="M {p[0]} {p[2]} L {q[0]} {q[2]}" stroke="#748495" stroke-width="7"/>')
    previous = None
    for sample in samples:
        p = _position((sample.get("frame", {}).get("player") or {}).get("pos"))
        if p is None:
            previous = None
            continue
        if previous is not None and 0 < sample["at"]-previous[0] <= 2. \
                and math.dist(p,previous[1]) <= 800.*(sample["at"]-previous[0])+30.:
            q = previous[1]
            escaping = (sample.get("frame",{}).get("plan") or {}).get("phase") == "leave_proximity_bomb"
            color = "#edaa61" if escaping else "#42d9f3"
            kind = "mine-retreat" if escaping else "travel"
            body.append(f'<path data-kind="{kind}" d="M {q[0]} {q[2]} L {p[0]} {p[2]}" stroke="{color}" stroke-width="12"/>')
        previous = sample["at"],p
    mines = {}
    for sample in samples:
        for mine in sample.get("frame",{}).get("mines",()):
            p = _position(mine.get("pos"))
            if p is not None:
                mines[str(mine.get("actor"))] = dict(mine)
    for mine in mines.values():
        p = mine["pos"]
        tip = html.escape(_json(mine))
        body.append(f'<rect data-kind="proximity-bomb" x="{p[0]-24}" y="{p[2]-24}" width="48" height="48" '
                    f'fill="#c7df6c" stroke="#173322" stroke-width="6"><title>{tip}</title></rect>')
    for landmark in landmarks:
        p = landmark["pos"]
        tip = html.escape(_json(landmark))
        color = "#f4c95d" if landmark["kind"] == "time" else "#af94ee"
        body.append(f'<circle cx="{p[0]}" cy="{p[2]}" r="35" fill="{color}"><title>{tip}</title></circle>')
    for event in events:
        p = _position(event.get("pos"))
        if p is not None:
            tip = html.escape(_json(event))
            mine_kind = event["kind"].removeprefix("mine_") if event["kind"].startswith("mine_") else None
            color = {"placement_verified":"#98da79", "detonation_observed":"#ff9d35", "retreat_complete":"#c794ee"}.get(mine_kind,"#ff6655")
            body.append(f'<circle data-kind="{html.escape(event["kind"])}" cx="{p[0]}" cy="{p[2]}" r="45" '
                        f'fill="{color}"><title>{tip}</title></circle>')
    body.append("</svg>")
    return "\n".join(body)
