"""Read-only run playback over the measured atlas and exact Notebook source IDs.

The reviewer exposes the latest 100 runs per title without deleting older evidence. User-drawn paths are separate
annotations. Only exact-geometry, currently revalidated floor paths are returned to navigation consumers; candidate
action links remain drafts until a title adapter can establish player traversal. No game input or memory writes.
"""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid
import hashlib

LIMITS = (1, 5, 10, 20, 100)
MAX_SAMPLES = 2000
TITLE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
NAMES = {"BLUS30491": "Resident Evil 5", "G4BE08": "Resident Evil 4", "BH6": "Resident Evil 6",
         "010018100CD46000": "Resident Evil 5 (Switch)", "01002A000CD48000": "Resident Evil 6 (Switch)"}
CONTROLS = {"human", "bot", "unknown"}
ASSISTANCE = {"unmodified", "mod_assisted", "unknown"}
RUN_MAP = re.compile(r"round_maps/([A-Za-z0-9_-]{1,64})/[A-Za-z0-9_-]{1,60}/\d{8}-\d{6}-[a-f0-9]{8}\.json\Z")
RUN_MAP_MAX = 16 * 1024 * 1024      # a run map is ~100-200 KB (gbox.mercs.run_capture bounds it); larger is refused
EXPLORE = ("seconds", "distance_m", "cells", "start_area_s", "start_area_share", "max_from_spawn_m")


def recorded_players(frame):
    """Controller ownership is recorded evidence; an old player trace is never called human."""
    players = frame.get("players")
    if not isinstance(players, list):
        player = frame.get("player")
        return [{**player, "id": "legacy", "control": "unknown"}] if isinstance(player, dict) else []
    result, seen = [], set()
    for player in players[:4]:
        if not isinstance(player, dict) or not isinstance(player.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", player["id"]):
            continue
        if player["id"] in seen:
            continue
        seen.add(player["id"])
        result.append({**player, "control": player.get("control") if player.get("control") in CONTROLS else "unknown"})
    return result


def assistance_context(value):
    value = value if isinstance(value, dict) else {}
    classification = value.get("classification")
    # Missing or unverified context is unknown, including old zero-damage rounds.
    if classification not in ASSISTANCE or classification == "unmodified" and value.get("verified") is not True:
        classification = "unknown"
    return {**value, "classification": classification, "verified": value.get("verified") is True}


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in value)


def _load_mesh(raw, geometry):
    if raw.get('geometry_available') is False:
        raise ValueError('This run records native coordinates; collision geometry is unavailable')
    from .titles.re5_nav import NavMesh
    links = [[] for _ in raw["triangles"]]
    for u, v, edge, cost in raw["links"]:
        links[u].append((v, edge, cost if cost is not None else 1.))
    mesh = NavMesh(raw["points"], raw["triangles"], links)
    if mesh.learning_sig != geometry:
        raise ValueError("stored geometry/topology identity does not match")
    return mesh


def traversal_allowed(mesh, waypoint, proofs):
    """A recorded completion may identify a candidate link; live prompts still own its execution."""
    if not hasattr(waypoint, "approach"):
        return False
    for proof in proofs:
        if proof.get("verified") is not True or proof.get("geometry") != mesh.learning_sig \
                or (proof.get("evidence") or {}).get("source") != "native_player_traversal":
            continue
        if not all(_point(proof.get(k)) for k in ("approach", "landing", "portal")):
            continue
        if mesh.find(proof["approach"], floor_only=True, height_slack=40.) != proof.get("from") \
                or mesh.find(proof["landing"], floor_only=True, height_slack=40.) != proof.get("to"):
            continue
        if all(math.dist(a, b) <= 30. for a,b in ((waypoint.approach,proof["approach"]),
                (waypoint,proof["landing"]),(waypoint.portal,proof["portal"]))):
            return True
    return False


def demonstrated_segment(mesh, a, b, proofs):
    if mesh.floor_segment(a, b):
        return True
    route = mesh.route(a, b)
    if not route or sum(hasattr(p, "approach") for p in route) != 1:
        return False
    previous = a
    for point in route:
        if hasattr(point, "approach"):
            if not mesh.floor_segment(previous, point.approach) or not traversal_allowed(mesh, point, proofs):
                return False
        elif not mesh.floor_segment(previous, point):
            return False
        previous = point
    return True


def decode(raw, fallback=None):
    try:
        return json.loads(raw, parse_constant=lambda _: None) if raw else fallback
    except (ValueError, TypeError):
        return fallback


class Reviewer:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "mercs"

    def path(self, family, title, name):
        if not isinstance(title, str) or not TITLE.fullmatch(title):
            raise ValueError("invalid title identifier")
        base = (self.root / family).resolve()
        path = (base / title / name).resolve()
        if not path.is_relative_to(base):
            raise ValueError("title data must stay inside the Mercenaries evidence directory")
        return path

    def read(self, family, title, name, query, args=()):
        path = self.path(family, title, name)
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=2.)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            return [dict(row) for row in db.execute(query, args)]

    def notebook(self, title, rid, geometry=None, mode=None):
        rows = self.read("curriculum", title, "rounds.sqlite", "SELECT * FROM rounds WHERE id=?", (rid,))
        if not rows:
            return None
        row = rows[0]
        if geometry is not None and row["stage"] != geometry or mode and row["mode"] != mode:
            return None
        row["observed"] = decode(row.pop("data"), {})
        row["vector"] = decode(row.get("vector"), [])
        from .notebook import FEATURES
        row["vector_kind"] = "normalized performance features, not semantic embeddings"
        row["vector_features"] = [{"name":key,"normalization_scale":scale} for key,scale in FEATURES] \
            if len(row["vector"])==len(FEATURES) else None
        row["source_id"] = f"gbox:mercs:{title}:{rid}"
        # Delivery is a measured outbox receipt, not a claim that a search was performed by the reviewer.
        try:
            outbox = self.read("curriculum", title, "rounds.sqlite",
                               "SELECT delivered FROM knowledge_outbox WHERE id=?", (rid,))
        except sqlite3.OperationalError:
            outbox = []
        row["knowledge_delivered"] = bool(outbox and outbox[0]["delivered"])
        return row

    def _atlas_rows(self, title):
        return self.read("navigation", title, "atlas.sqlite", "SELECT * FROM rounds ORDER BY started DESC,id DESC LIMIT 100")

    def summaries(self, title):
        result, joined = [], set()
        atlas = self._atlas_rows(title)
        recent_notes = self.read("curriculum", title, "rounds.sqlite", "SELECT id,ts,stage,mode,character,outcome FROM rounds ORDER BY ts DESC LIMIT 100")
        notes = {r["id"]: r for r in recent_notes}
        missing = {r["id"].split(":",1)[0] for r in atlas} - notes.keys()
        if missing:
            placeholders = ",".join("?" for _ in missing)
            for row in self.read("curriculum",title,"rounds.sqlite",
                                 "SELECT id,ts,stage,mode,character,outcome FROM rounds WHERE id IN ("+placeholders+")",tuple(missing)):
                notes[row["id"]] = row
        for row in atlas:
            meta = decode(row.get("metadata"), {})
            rid = row["id"].split(":", 1)[0]
            notebook = notes.get(rid)
            if notebook and (notebook["stage"] != row["stage"] or not meta.get("mode")
                             or notebook["mode"] != meta["mode"]):
                notebook = None
            if notebook:
                joined.add(rid)
            review = decode(row.get("review"), {})
            result.append({"id": row["id"], "round_id": rid, "title": title, "geometry": row["stage"],
                           "stage": meta.get("game_stage") or meta.get("stage_name") or row["stage"],
                           "character": meta.get("character") or (notebook or {}).get("character") or "Unknown",
                           "mode": meta.get("mode") or (notebook or {}).get("mode"),
                           "started": row["started"], "ended": row["ended"], "outcome": row["outcome"],
                           "active": row["outcome"] is None, "review": review,
                           "participants": meta.get("participants") or [],
                           "assistance": assistance_context(meta.get("assistance")),
                           "source_id": f"atlas:{title}:{row['id']}",
                           "notebook_source_id": f"gbox:mercs:{title}:{rid}" if notebook else None, "spatial": True})
        # Titles without an atlas still expose genuine saved reviews, with spatial playback explicitly absent.
        # A round the engine captured (gbox.mercs.run_capture) carries its run map: a 2D path, no collision geometry.
        maps = self.run_maps(title, [row["id"] for row in recent_notes if row["id"] not in joined])
        for row in recent_notes:
            if row["id"] in joined or any(r["round_id"] == row["id"] for r in result):
                continue
            mapped = maps.get(row["id"]) or {}
            stage = row["stage"] if row["stage"] not in (None, "", "unknown") else mapped.get("stage") or row["stage"]
            result.append({"id": "notebook:"+row["id"], "round_id": row["id"], "title": title,
                           "geometry": row["stage"], "stage": stage, "mode": row["mode"],
                           "character": row["character"], "started": row["ts"], "ended": row["ts"],
                           "timestamp_meaning": "review saved at", "outcome": row["outcome"], "active": False,
                           "participants": [], "assistance": assistance_context(None),
                           "spatial": False, "source_id": f"gbox:mercs:{title}:{row['id']}",
                           "round_map": mapped.get("round_map") or {"available": False},
                           "exploration": mapped.get("exploration")})
        return sorted(result, key=lambda r: (r["started"], r["id"]), reverse=True)[:100]

    def catalog(self):
        titles = set()
        for family, filename in (("navigation", "atlas.sqlite"), ("curriculum", "rounds.sqlite")):
            for path in (self.root/family).glob("*/"+filename):
                if TITLE.fullmatch(path.parent.name):
                    titles.add(path.parent.name)
        games, errors = [], []
        for title in sorted(titles):
            try:
                rows = self.summaries(title)
                stages = {}
                for row in rows:
                    key,label = row["geometry"],str(row["stage"])
                    if key not in stages or stages[key]==key and label!=key:
                        stages[key] = label
                games.append({"id": title, "name": NAMES.get(title, title), "visible_runs": len(rows),
                              "mapped_runs": sum(bool((r.get("round_map") or {}).get("available")) for r in rows),
                              "stages": [{"id": key, "name": label} for key,label in sorted(stages.items())],
                              "characters": sorted({r["character"] for r in rows}),
                              "active": sum(r["active"] for r in rows)})
            except (OSError, sqlite3.Error, ValueError) as exc:
                errors.append({"title": title, "error": type(exc).__name__})
        return {"version": 1, "games": games, "errors": errors, "retention": "latest 100 per title; older evidence is preserved",
                "source": "local measured atlas and exact-ID Notebook reviews", "at": time.time()}

    def runs(self, title, stage="", character="", limit=20, paths=False):
        if limit not in LIMITS:
            raise ValueError("limit must be 1, 5, 10, 20 or 100")
        rows = [r for r in self.summaries(title) if (not stage or r["geometry"] == stage)
                and (not character or r["character"] == character)][:limit]
        if paths:
            for row in rows:
                count = self.read("navigation",title,"atlas.sqlite","SELECT count(*) AS n,MAX(seq) AS last FROM samples WHERE round_id=?",(row["id"],)) if row["spatial"] else []
                stride = max(1, math.ceil((count[0]["n"] if count else 0)/2000))
                chosen = self.read("navigation",title,"atlas.sqlite",
                    "SELECT seq,at,payload FROM samples WHERE round_id=? AND (seq % ?=0 OR seq=?) ORDER BY seq",
                    (row["id"],stride,count[0]["last"])) if count else []
                tracks = {}
                for sample in chosen:
                    frame=(decode(sample['payload'],{}) or {}).get('frame') or {}
                    scale=10. if frame.get('units_per_m')==1000 else 1.
                    for player in recorded_players(frame):
                        if not _point(player.get("pos")):
                            continue
                        track = tracks.setdefault(player["id"], {"id":player["id"],"control":player["control"],"slot":player.get("slot"),"path":[]})
                        previous = track["path"][-1] if track["path"] else None
                        point = {"at":sample["at"],"seq":sample["seq"],"pos":player["pos"],"actor":player.get("actor",player.get("ptr")),"control":player["control"]}
                        if previous is not None:
                            dt = point["at"]-previous["at"]
                            point["break"] = not (0<dt<=2.*stride and math.dist(point["pos"],previous["pos"])<=(800.*dt+30.)*scale
                                and point["actor"]==previous["actor"] and point["control"]==previous["control"])
                        track["path"].append(point)
                        if track["control"] != player["control"]:
                            track["control"] = "unknown"
                row["paths"] = list(tracks.values())
                row["path"] = row["paths"][0]["path"] if row["paths"] else []
                row["path_sampled"] = stride > 1
        return {"runs": rows, "retention": "latest 100 per title; no stored runs deleted"}

    def samples(self, title, rid, after=-1, limit=MAX_SAMPLES):
        rows = self.read("navigation", title, "atlas.sqlite",
                         "SELECT seq,at,payload FROM samples WHERE round_id=? AND seq>? ORDER BY seq LIMIT ?",
                         (rid, after, limit))
        return [{"seq": row["seq"], "at": row["at"], **decode(row["payload"], {})} for row in rows]

    def round(self, title, rid, after=-1):
        rows = self.summaries(title)
        summary = next((r for r in rows if r["id"] == rid), None)
        if summary is None:
            raise FileNotFoundError("round is outside this title's latest 100 reviews")
        notebook = self.notebook(title, summary["round_id"], summary["geometry"], summary.get("mode")) \
            if summary.get("mode") or not summary["spatial"] else None
        out = {"run": summary, "notebook": notebook, "samples": [], "events": [], "geometry": None,
               "provenance": {"atlas_source": summary["source_id"], "notebook_join": "matched exact round ID, geometry and mode" if notebook else "no matching saved Notebook row",
                              "semantic_search_performed": False, "sample_interval": "recorded, not inferred"}}
        if summary["spatial"]:
            stage = self.read("navigation", title, "atlas.sqlite", "SELECT geometry,metadata FROM stages WHERE key=?",
                              (summary["geometry"],))
            out["geometry"] = decode(stage[0]["geometry"], {}) if stage else None
            out["samples"] = self.samples(title, rid, after)
            events = self.read("navigation", title, "atlas.sqlite",
                               "SELECT seq,at,kind,payload FROM events WHERE round_id=? ORDER BY seq LIMIT 20000", (rid,))
            out["events"] = [{"seq": e["seq"], "at": e["at"], "kind": e["kind"], "data": decode(e["payload"], {})} for e in events]
        out["round_map"] = None
        if (summary.get("round_map") or {}).get("available"):
            try:
                out["round_map"] = self.run_map(title, summary)
            except (FileNotFoundError, ValueError, OSError) as exc:     # pruned meanwhile: the round without it
                out["round_map_error"] = str(exc)[:200]
        out["next_after"] = out["samples"][-1]["seq"] if out["samples"] else after
        out["more"] = len(out["samples"]) == MAX_SAMPLES
        out["suggestions"] = self.suggestions(title, summary["geometry"])
        out["players"] = list({player["id"]: {k:player.get(k) for k in ("id","slot","control","provenance")}
                               for sample in out["samples"] for player in recorded_players(sample.get("frame") or {})}.values())
        out["navigation_learning"] = None
        for path in (self.root/"lessons"/(title+"-navigation.json"), self.root/"learned"/title/(title+"-navigation.json")):
            if path.resolve().is_relative_to(self.root.resolve()) and path.is_file() and path.stat().st_size<=4*1024*1024:
                learned = decode(path.read_text(encoding="utf-8"), {})
                stage = (learned.get("stages") or {}).get(summary["geometry"])
                if isinstance(stage,dict):
                    out["navigation_learning"] = {"geometry":summary["geometry"],"source_id":"navigation-learning:"+title+":"+summary["geometry"],
                                                   "observed":stage,"historical_snapshot":False}
                    break
        out["knowledge"] = {"search_performed_by_reviewer":False,"semantic_recall":None}
        if notebook:
            try:
                recall = self.read("curriculum",title,"rounds.sqlite","SELECT at,payload FROM semantic_recall WHERE stage=? AND mode=?",
                                   (summary["geometry"],summary.get("mode")))
                if recall:
                    out["knowledge"]["semantic_recall"] = {"at":recall[0]["at"],"receipt":decode(recall[0]["payload"],{})}
            except sqlite3.OperationalError:
                pass
        return out

    def run_maps(self, title, ids):
        """{round id: {"round_map": {"available", "file", "stage"}, "exploration", "stage"}} from the curriculum rows'
        run map fields (gbox.mercs.run_capture: round_map_file, explore_*). Rows without them are left out."""
        ids = [i for i in ids if isinstance(i, str)][:200]
        if not ids:
            return {}
        fields = ",".join(f"json_extract(data,'$.explore_{k}') AS explore_{k}" for k in EXPLORE)
        try:
            rows = self.read("curriculum", title, "rounds.sqlite",
                             "SELECT id,json_extract(data,'$.round_map_file') AS round_map_file,"
                             "json_extract(data,'$.round_map_stage') AS round_map_stage,json_extract(data,'$.stage') "
                             f"AS observed_stage,{fields} FROM rounds WHERE id IN ({','.join('?' for _ in ids)})",
                             tuple(ids))
        except sqlite3.OperationalError:           # an SQLite without JSON1: the runs list without maps
            return {}
        out = {}
        for row in rows:
            rel = row.get("round_map_file")
            stage = row.get("round_map_stage") if row.get("round_map_stage") not in (None, "", "unknown") else \
                row.get("observed_stage") if isinstance(row.get("observed_stage"), str) else None
            entry = {"stage": stage}
            if isinstance(rel, str) and (m := RUN_MAP.fullmatch(rel)) and m.group(1) == title:
                path = self._run_map_path(rel)
                entry["round_map"] = {"available": path is not None and path.is_file(), "file": rel, "stage": stage}
                entry["exploration"] = {k: row.get("explore_" + k) for k in EXPLORE}
            out[row["id"]] = entry
        return out

    def _run_map_path(self, rel):
        base = (self.root / "round_maps").resolve()
        path = (self.root / rel).resolve()
        return path if path.is_relative_to(base) else None

    def run_map(self, title, summary):
        """One run's map (gbox.mercs.run_capture's JSON) with its stage's known extent and the coverage against it
        today (the extent grows as runs add to it; the capture's own coverage is kept as captured)."""
        from . import run_capture
        rel = (summary.get("round_map") or {}).get("file")
        m = RUN_MAP.fullmatch(rel or "")
        path = self._run_map_path(rel) if m and m.group(1) == title else None
        if path is None or not path.is_file() or path.stat().st_size > RUN_MAP_MAX:
            raise FileNotFoundError("run map not available")
        data = decode(path.read_text(encoding="utf-8"), None)
        if not isinstance(data, dict) or data.get("round_id") != summary["round_id"]:
            raise ValueError("run map does not belong to this round")
        cell = float(data.get("cell") or run_capture.CELL)
        extent = run_capture.load_extent(path.parent / "extent" / "extent.json", cell)
        known, source = run_capture.known_cells(extent)
        visited = {tuple(c) for c in data.get("cells") or () if isinstance(c, list) and len(c) == 2}
        data["extent"] = {"cell": cell, "runs": extent["runs"], "source": source, "known": sorted(map(list, known)),
                          "updated": extent.get("updated")}
        data["coverage_now"] = run_capture.coverage(visited, extent)
        data["file"] = rel
        data["view"] = {"x": -1, "z": 1}          # drawn as the live tactical map draws (+x to the left, +z up)
        return data

    def _annotations(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root/"reviewer.sqlite", timeout=5.)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS suggestions(id TEXT PRIMARY KEY,title TEXT,geometry TEXT,created REAL,payload TEXT)")
        return db

    def suggestions(self, title, geometry):
        path = self.root/"reviewer.sqlite"
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2.)) as db:
            rows = db.execute("SELECT payload FROM suggestions WHERE title=? AND geometry=? ORDER BY created DESC LIMIT 100", (title,geometry)).fetchall()
        return [decode(row[0], {}) for row in rows]

    def validate(self, title, geometry, points):
        if not isinstance(geometry,str) or not 1<=len(geometry)<=256:
            raise ValueError("an exact measured geometry identifier is required")
        if not isinstance(points, list) or not 2 <= len(points) <= 256:
            raise ValueError("a route needs 2 to 256 world-coordinate points")
        clean = []
        for point in points:
            if not isinstance(point, (list,tuple)) or len(point) != 3 or any(type(v) not in (float,int)
                    or not math.isfinite(v) or abs(v)>1e8 for v in point):
                raise ValueError("route points must be finite x,y,z coordinates")
            clean.append(tuple(point))
        rows = self.read("navigation", title, "atlas.sqlite", "SELECT geometry FROM stages WHERE key=?", (geometry,))
        if not rows:
            raise FileNotFoundError("measured geometry not available for this title")
        raw = decode(rows[0]["geometry"], {})
        mesh = _load_mesh(raw, geometry)
        checks = []
        for index,(a,b) in enumerate(zip(clean,clean[1:])):
            floor = mesh.floor_segment(a,b)
            candidates = []
            if not floor:
                u,v = mesh.find(a,floor_only=True,height_slack=40.),mesh.find(b,floor_only=True,height_slack=40.)
                candidates = [link for link in raw.get("action_links",[]) if link["from"]==u and link["to"]==v]
            checks.append({"segment": index, "valid_floor": floor,
                           "candidate_action_links": candidates,
                           "reason": "measured directed floor support" if floor else
                           "action link needs observed player traversal; annotation is not authorized movement" if candidates else
                           "segment crosses a boundary, unsupported floor or another storey"})
        return clean, checks

    def save(self, body, actor):
        title, geometry = body.get("title"), body.get("geometry")
        points, checks = self.validate(title, geometry, body.get("points"))
        valid = all(c["valid_floor"] for c in checks)
        row = {"id": uuid.uuid4().hex, "title": title, "geometry": geometry, "created": time.time(),
               "name": str(body.get("name") or "Suggested route")[:100], "actor": str(actor)[:100],
               "kind": "drawn_suggestion",
               "points": points, "validation": checks, "status": "validated_floor_suggestion" if valid else "draft",
               "provenance": "operator-drawn annotation; not a measured optimal route", "bot_eligible": valid}
        with closing(self._annotations()) as db:
            db.execute("INSERT INTO suggestions VALUES(?,?,?,?,?)", (row["id"],title,geometry,row["created"],json.dumps(row,allow_nan=False)))
            db.commit()
        return row

    def demonstration(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("invalid demonstration identifier")
        path = self.root/"reviewer.sqlite"
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=2.)) as db:
                found = db.execute("SELECT payload FROM suggestions WHERE id=?", (identifier,)).fetchone()
            row = decode(found[0], {}) if found else {}
            if row.get("kind") == "recorded_demonstration":
                return row
        raise FileNotFoundError("recorded demonstration not found")

    def teach(self, body, actor):
        """Select durable human samples. Client-supplied coordinates/ownership never become evidence."""
        title, rid, player_id = body.get("title"), body.get("round_id"), body.get("player_id")
        if not isinstance(rid, str) or len(rid)>512 or not isinstance(player_id, str):
            raise ValueError("an exact recorded round and player identifier are required")
        summary = next((row for row in self.summaries(title) if row["id"] == rid and row["spatial"]), None)
        if summary is None:
            raise FileNotFoundError("recorded spatial round not found in this title's latest 100")
        if not summary.get("mode"):
            raise ValueError("a recorded mode is required before teaching a route")
        first, last = body.get("start_seq"), body.get("end_seq")
        if type(first) is not int or type(last) is not int or not 0<=first<last<=2**63-1:
            raise ValueError("choose an increasing recorded start/end sample range")
        saved = self.read("navigation", title, "atlas.sqlite",
            "SELECT seq,at,payload FROM samples WHERE round_id=? AND seq BETWEEN ? AND ? ORDER BY seq LIMIT 20001", (rid,first,last))
        if len(saved)<2 or len(saved)>20000 or saved[0]["seq"]!=first or saved[-1]["seq"]!=last:
            raise ValueError("choose 2 to 20000 existing recorded samples")
        frames, actor_id, contexts = [], None, []
        for sample in saved:
            frame = (decode(sample["payload"], {}) or {}).get("frame") or {}
            player = next((p for p in recorded_players(frame) if p["id"]==player_id), None)
            if player is None or player["control"]!="human":
                raise ValueError("every selected sample must identify the same recorded human player")
            provenance = player.get("provenance") or {}
            if provenance.get("native_actor_verified") is not True \
                    or provenance.get("control_source") != "operator_assignment_and_bot_input_fence":
                raise ValueError("human teaching requires recorded native actor and controller-ownership provenance")
            owner = player.get("actor", player.get("ptr"))
            if owner is None or not _point(player.get("pos")) or frame.get("title",title)!=title:
                raise ValueError("recorded player identity and finite positions are required")
            if actor_id is None:
                actor_id = owner
            if actor_id != owner:
                raise ValueError("player actor changed inside the selected demonstration")
            if frames:
                previous = frames[-1]
                dt = sample["at"]-previous["at"]
                max_speed = 8000. if frame.get("units")=="mm" else 800.
                if sample["seq"]!=previous["seq"]+1 or not 0<dt<=2. \
                        or math.dist(player["pos"], previous["pos"])>max_speed*dt+30.:
                    raise ValueError("the selected path has a recording gap or discontinuity; choose a continuous segment")
            frames.append({"seq":sample["seq"],"at":sample["at"],"pos":tuple(player["pos"]),"player":player,
                           "input_provenance":frame.get("input_provenance")})
            contexts.append(assistance_context(frame.get("assistance")))
        stage = self.read("navigation",title,"atlas.sqlite","SELECT geometry FROM stages WHERE key=?",(summary["geometry"],))
        if not stage:
            raise FileNotFoundError("measured stage geometry is unavailable")
        raw = decode(stage[0]["geometry"], {})
        mesh = _load_mesh(raw, summary["geometry"])
        events = self.read("navigation",title,"atlas.sqlite",
            "SELECT at,payload FROM events WHERE round_id=? AND kind='traversal_completed' AND at BETWEEN ? AND ? ORDER BY seq LIMIT 1000",
            (rid,frames[0]["at"],frames[-1]["at"]))
        by_seq = {f["seq"]:f for f in frames}
        proofs = []
        for event in events:
            proof = decode(event["payload"], {})
            a, b = by_seq.get(proof.get("start_seq")), by_seq.get(proof.get("end_seq"))
            if proof.get("player_id")!=player_id or proof.get("player_actor")!=actor_id or a is None or b is None \
                    or not a["seq"]<b["seq"] or not all(_point(proof.get(k)) for k in ("approach","landing","portal")):
                continue
            if math.dist(a["pos"],proof["approach"])>80. or math.dist(b["pos"],proof["landing"])>80.:
                continue
            if demonstrated_segment(mesh,a["pos"],b["pos"],[proof]) and not mesh.floor_segment(a["pos"],b["pos"]):
                proofs.append({**proof,"source_event_at":event["at"]})
        # Keep recorded action endpoints and drop only their already-proven animation samples.
        collapsed, index = [], 0
        while index<len(frames):
            sample = frames[index]
            collapsed.append(sample)
            proof = next((p for p in proofs if p["start_seq"]==sample["seq"]), None)
            if proof:
                index = next(i for i,f in enumerate(frames) if f["seq"]==proof["end_seq"])
            else:
                index += 1
        points, source_points = [], []
        protected = {p[k] for p in proofs for k in ("start_seq","end_seq")}
        for sample in collapsed:
            if points and math.dist(points[-1],sample["pos"])<1. and sample["seq"] not in protected:
                continue
            if len(points)>=2 and source_points[-1] not in protected and math.dist(points[-2],sample["pos"])<=300. \
                    and mesh.floor_segment(points[-2],sample["pos"]):
                points[-1], source_points[-1] = sample["pos"], sample["seq"]
            else:
                points.append(sample["pos"]); source_points.append(sample["seq"])
        if not 2<=len(points)<=4096:
            raise ValueError("choose a shorter segment containing at least two distinct positions")
        checks = []
        for i,(a,b) in enumerate(zip(points,points[1:])):
            floor = mesh.floor_segment(a,b)
            valid = floor or demonstrated_segment(mesh,a,b,proofs)
            checks.append({"segment":i,"valid_floor":floor,"valid_action":bool(valid and not floor),
                           "reason":"measured directed floor support" if floor else
                           "recorded native player traversal; live prompt required" if valid else
                           "unsupported segment or missing native player traversal completion"})
        eligible = all(c["valid_floor"] or c["valid_action"] for c in checks)
        classes = {c["classification"] for c in contexts}
        classification = "mod_assisted" if "mod_assisted" in classes else "unmodified" if classes=={"unmodified"} else "unknown"
        source = {"round_id":rid,"round_source_id":summary["source_id"],"title":title,"geometry":summary["geometry"],
                  "mode":summary["mode"],"player_id":player_id,"control":"human","player_actor":actor_id,
                  "start_seq":first,"end_seq":last,"started":frames[0]["at"],"ended":frames[-1]["at"],
                  "sample_count":len(frames),"input_replay":False,
                  "inputs_observed":all(f["player"].get("provenance",{}).get("inputs_observed") is True for f in frames),
                  "input_provenance":frames[0].get("input_provenance"),
                  "ownership_provenance":frames[0]["player"].get("provenance"),
                  "sample_digest_scope":"selected recorded sequence, time and position",
                  "sample_digest":hashlib.sha256(json.dumps([{k:f[k] for k in ("seq","at","pos")} for f in frames],sort_keys=True).encode()).hexdigest()}
        row = {"id":uuid.uuid4().hex,"title":title,"geometry":summary["geometry"],"mode":summary["mode"],
               "created":time.time(),"name":str(body.get("name") or "Recorded human route")[:100],"actor":str(actor)[:100],
               "kind":"recorded_demonstration","source":source,"points":points,"point_sample_seqs":source_points,
               "traversals":proofs,"validation":checks,"bot_eligible":eligible,
               "adopted":body.get("adopt") is True and eligible,
               "status":"validated_recorded_demonstration" if eligible else "draft",
               "assistance":{"classification":classification,"verified":classification!="unknown" and all(c["verified"] for c in contexts),
                             "source":"all selected durable sample contexts","effects":sorted({effect[:100] for c in contexts for effect in c.get("effects",[]) if isinstance(effect,str)})[:100]},
               "provenance":"recorded human positions; current floor, hazards and live action prompts remain authoritative"}
        with closing(self._annotations()) as db:
            db.execute("INSERT INTO suggestions VALUES(?,?,?,?,?)",(row["id"],title,row["geometry"],row["created"],json.dumps(row,allow_nan=False)))
            db.commit()
        return row

    def adopt(self, identifier, adopted):
        if type(adopted) is not bool:
            raise ValueError("adopted must be a boolean")
        row = self.demonstration(identifier)
        if adopted:
            stage = self.read("navigation",row["title"],"atlas.sqlite","SELECT geometry FROM stages WHERE key=?",(row["geometry"],))
            if not stage:
                raise FileNotFoundError("recorded geometry unavailable")
            mesh = _load_mesh(decode(stage[0]["geometry"],{}),row["geometry"])
            if not row.get("bot_eligible") or not all(demonstrated_segment(mesh,a,b,row.get("traversals") or [])
                    for a,b in zip(row["points"],row["points"][1:])):
                raise ValueError("a draft or invalidated route cannot be adopted for practice")
        row["adopted"] = adopted
        with closing(self._annotations()) as db:
            db.execute("UPDATE suggestions SET payload=? WHERE id=?",(json.dumps(row,allow_nan=False),identifier));db.commit()
        return row


def validated_suggestions(data_dir, title, mesh):
    """Optional planner hints. Consumers must still check live hazards and goal applicability before movement."""
    reviewer = Reviewer(data_dir)
    out = []
    for row in reviewer.suggestions(title, mesh.learning_sig):
        points = row.get("points") or []
        demo = row.get("kind")=="recorded_demonstration"
        if demo and (not row.get("adopted") or not row.get("mode") or (row.get("source") or {}).get("control")!="human"):
            continue
        if row.get("bot_eligible") and 2<=len(points)<=4096 and all(_point(p) for p in points) \
                and all(demonstrated_segment(mesh,a,b,row.get("traversals") or []) if demo else mesh.floor_segment(a,b)
                        for a,b in zip(points,points[1:])):
            out.append(row)
    return out


def routes(app, config, auth):
    from fastapi import Depends, HTTPException
    service = Reviewer(config.data_dir)
    app.state.mercs_reviewer = service

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError as exc:
            raise HTTPException(404,str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc
        except (sqlite3.Error,OSError) as exc:
            raise HTTPException(503,"run evidence is temporarily unavailable") from exc

    @app.get("/api/mercs/reviewer/catalog")
    def catalog(actor=Depends(auth)):
        return call(service.catalog)

    @app.get("/api/mercs/reviewer/runs")
    def runs(title: str, stage: str="", character: str="", limit: int=20, paths: bool=True, actor=Depends(auth)):
        return call(service.runs,title,stage,character,limit,paths)

    @app.get("/api/mercs/reviewer/round")
    def round(title: str, id: str, after: int=-1, actor=Depends(auth)):
        return call(service.round,title,id,min(2**63-1,max(-1,after)))

    @app.get("/api/mercs/reviewer/round-map")
    def round_map(title: str, id: str, actor=Depends(auth)):
        # One run's 2D map (gbox.mercs.run_capture) by its reviewer id ("notebook:<round id>") or curriculum row id.
        def one():
            rid = id.split(":", 1)[1] if id.startswith("notebook:") else id
            run = next((r for r in service.summaries(title) if r["round_id"] == rid
                        and (r.get("round_map") or {}).get("available")), None)
            if run is None:
                raise FileNotFoundError("no run map for this round in the title's latest 100")
            return {"run": run, "round_map": service.run_map(title, run)}
        return call(one)

    @app.get("/api/mercs/reviewer/live")
    def live(title: str, id: str, actor=Depends(auth)):
        # Join live RAM frames only when the active recorded UUID and full geometry match current telemetry.
        row = next((r for r in call(service._atlas_rows,title) if r["id"]==id and r["outcome"] is None),None)
        tactical = getattr(app.state,"tactical_map",None)
        store = getattr(app.state,"store",None)
        if row is None or tactical is None or store is None:
            return {"live":False,"reason":"no matching active measured round"}
        from ..screensaver import telemetry_get
        for session in store.running_sessions():
            sid = session["session_id"]
            telemetry = telemetry_get(sid)
            stats = telemetry.get("stats") or {}
            if not telemetry.get("running") or telemetry.get("age_s",999)>10 \
                    or stats.get("round_evidence_id") != id.split(":",1)[0] or stats.get("nav_geometry") != row["stage"]:
                continue
            frame = tactical.get_frame(sid)
            if frame.get("live") and frame.get("title")==title and frame.get("screen")=="playing" \
                    and isinstance(frame.get("t"),(int,float)) and frame["t"]>=row["started"]:
                return {"live":True,"frame":frame,"stats":stats,"session_id":sid,
                        "provenance":{"source":"live RAM tactical publisher and autoplay telemetry",
                                      "recorded":False,"round_id":id,"geometry":row["stage"]}}
        return {"live":False,"reason":"waiting for a fresh exact-round live frame"}

    @app.post("/api/mercs/reviewer/suggestions")
    def suggest(body: dict, actor=Depends(auth)):
        return call(service.save,body,actor)

    @app.post("/api/mercs/reviewer/demonstrations")
    def teach(body: dict, actor=Depends(auth)):
        return call(service.teach,body,actor)

    @app.get("/api/mercs/reviewer/demonstrations/{identifier}")
    def demonstration(identifier: str, actor=Depends(auth)):
        return call(service.demonstration,identifier)

    @app.post("/api/mercs/reviewer/demonstrations/{identifier}/adopt")
    def adopt(identifier: str, body: dict, actor=Depends(auth)):
        return call(service.adopt,identifier,body.get("adopted"))

    @app.get("/api/mercs/enemy-knowledge")
    def enemy_knowledge(title: str = "", enemy_class: str = "", recent: int = 20, actor=Depends(auth)):
        # The enemy knowledge database, read only (gbox.mercs.enemy_db.inspect): without a title the titles it holds;
        # with one, per enemy class the learned plan, its sample counts and the recent outcomes. Imported here, not
        # at the top: enemy_db is a bot module that reloads in place, this route module is not.
        from . import enemy_db
        if title and not TITLE.fullmatch(title):
            raise HTTPException(400, "invalid title identifier")
        return call(enemy_db.inspect, title or None, root_dir=service.root / "knowledge",
                    enemy_class=enemy_class or None, recent=max(0, min(100, recent)))
