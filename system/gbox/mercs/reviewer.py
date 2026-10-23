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

LIMITS = (1, 5, 10, 20, 100)
MAX_SAMPLES = 2000
TITLE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
NAMES = {"BLUS30491": "Resident Evil 5", "G4BE08": "Resident Evil 4"}


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
                           "source_id": f"atlas:{title}:{row['id']}",
                           "notebook_source_id": f"gbox:mercs:{title}:{rid}" if notebook else None, "spatial": True})
        # Titles without an atlas still expose genuine saved reviews, with spatial playback explicitly absent.
        for row in recent_notes:
            if row["id"] in joined or any(r["round_id"] == row["id"] for r in result):
                continue
            result.append({"id": "notebook:"+row["id"], "round_id": row["id"], "title": title,
                           "geometry": row["stage"], "stage": row["stage"], "mode": row["mode"],
                           "character": row["character"], "started": row["ts"], "ended": row["ts"],
                           "timestamp_meaning": "review saved at", "outcome": row["outcome"], "active": False,
                           "spatial": False, "source_id": f"gbox:mercs:{title}:{row['id']}"})
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
                    "SELECT at,json_extract(payload,'$.frame.player.pos') AS pos FROM samples WHERE round_id=? AND (seq % ?=0 OR seq=?) ORDER BY seq",
                    (row["id"],stride,count[0]["last"])) if count else []
                row["path"] = [{"at": s["at"], "pos": decode(s["pos"])} for s in chosen if s["pos"]]
                previous = None
                for sample in row["path"]:
                    if previous is not None:
                        dt = sample["at"]-previous["at"]
                        sample["break"] = not (0<dt<=2.*stride and math.dist(sample["pos"],previous["pos"])<=800.*dt+30.)
                    previous = sample
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
        out["next_after"] = out["samples"][-1]["seq"] if out["samples"] else after
        out["more"] = len(out["samples"]) == MAX_SAMPLES
        out["suggestions"] = self.suggestions(title, summary["geometry"])
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
        from .titles.re5_nav import NavMesh
        raw = decode(rows[0]["geometry"], {})
        links = [[] for _ in raw["triangles"]]
        for u,v,edge,cost in raw["links"]:
            links[u].append((v,edge,cost if cost is not None else 1.))
        mesh = NavMesh(raw["points"], raw["triangles"], links)
        if mesh.learning_sig != geometry:
            raise ValueError("stored geometry/topology identity does not match")
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
               "points": points, "validation": checks, "status": "validated_floor_suggestion" if valid else "draft",
               "provenance": "operator-drawn annotation; not a measured optimal route", "bot_eligible": valid}
        with closing(self._annotations()) as db:
            db.execute("INSERT INTO suggestions VALUES(?,?,?,?,?)", (row["id"],title,geometry,row["created"],json.dumps(row,allow_nan=False)))
            db.commit()
        return row


def validated_suggestions(data_dir, title, mesh):
    """Optional planner hints. Consumers must still check live hazards and goal applicability before movement."""
    reviewer = Reviewer(data_dir)
    out = []
    for row in reviewer.suggestions(title, mesh.learning_sig):
        points = row.get("points") or []
        if row.get("bot_eligible") and len(points)>=2 and all(mesh.floor_segment(a,b) for a,b in zip(points,points[1:])):
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
