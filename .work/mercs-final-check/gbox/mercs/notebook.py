"""Round evidence, a generated guide, and a local vector store consumed before play.

Vectors are transparent numerical performance features, not invented semantic embeddings.
The per-stage guide reports observed results, including deaths and missing bonus pickups.
This is shared infrastructure: title adapters provide metadata and navigation identifiers.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
import threading
from pathlib import Path

FEATURES = (("kills", 150), ("score", 100000), ("bonuses_taken", 10),
            ("accuracy", 1), ("stuck", 10), ("nav_route_arrivals", 10))


def reflect(outcome, stats):
    """Diagnose measured failures; acceptance requires positive observations."""
    remaining = stats.get('time_bonuses_remaining')
    rank = outcome == 'completed' and stats.get('result_rank') in ('S','SS','S+','S++')
    damage = stats.get('player_damage_events')
    findings, changes = [], []
    if isinstance(remaining, int) and remaining > 0:
        findings.append(f'{remaining} observed time bonuses remained')
        changes.append('Finish the held time-bonus checkpoint before optional combo pursuit.')
    if (stats.get('motion_idle_spin_s') or 0)>3 or (stats.get('stuck') or 0)>0:
        findings.append('stationary turning or failed movement observed')
        changes.append('Penalize measured failed directed crossings; use supported floor recovery.')
    if (stats.get('nav_oscillations') or 0)>0:
        findings.append('repeated directed route reversal observed')
        changes.append('Keep checkpoint commitment across combat; apply recorded reversal costs.')
    if isinstance(damage, (int,float)) and damage > 0:
        findings.append(f'{damage} sampled HP-loss events')
        changes.append('Review each incident map, prior inputs, and bounded RAM witness before attributing cause.')
    if not rank:
        findings.append('completed S-rank result not verified')
    return {'schema': 'gbox.mercs.round-review/1', 'findings': findings, 'next_run_actions': changes,
            'acceptance': {'completed_s_rank': rank,
                'all_observed_time_bonuses': remaining == 0 if remaining is not None else None,
                'no_sampled_hp_loss': damage == 0 if damage is not None else None},
            'policy': {'bonus_commitment': True, 'learn_failed_crossings': True,
                       'allow_unverified_routes': False}}


class Notebook:
    def __init__(self, root, map_id):
        self.root = Path(root) / "curriculum" / str(map_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "rounds.sqlite"
        self.map_id = map_id
        self._publishing = False
        with self.connect() as db:
            db.execute("create table if not exists rounds(id text primary key, ts real, stage text, mode text, "
                       "character text, outcome text, data text, vector text)")
            db.execute("create table if not exists knowledge_outbox(id text primary key, payload text, delivered integer default 0)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("pragma journal_mode=WAL")
        return db

    @staticmethod
    def vector(stats):
        return [max(0., min(4., float(stats.get(k) or 0) / scale)) for k, scale in FEATURES]

    def recall(self, stage, mode, stats=None, limit=5):
        """Stage and mode are hard filters; unrelated game geometries never become routes."""
        query = self.vector(stats or {})
        with self.connect() as db:
            rows = db.execute("select id,outcome,data,vector from rounds where stage=? and mode=? "
                              "order by ts desc limit 200", (str(stage), mode)).fetchall()
        ranked = sorted(rows, key=lambda r: sum((a-b)**2 for a,b in zip(query, json.loads(r[3]))))
        return [{"id": r[0], "outcome": r[1], "observed": json.loads(r[2])} for r in ranked[:limit]]

    def finish(self, stage, mode, character, outcome, stats, *, round_id=None):
        rid = round_id or uuid.uuid4().hex
        data = {k: v for k, v in stats.items() if isinstance(v, (str, int, float, bool, type(None)))}
        data["result_rank_observed"] = stats.get("result_rank")
        data["s_rank_verified"] = outcome == "completed" and stats.get("result_rank") in ("S", "SS", "S+", "S++")
        data['reflection'] = reflect(outcome, stats)
        row = {"id": rid, "ts": time.time(), "stage": str(stage), "mode": mode,
               "character": character, "outcome": outcome, "observed": data}
        with self.connect() as db:
            inserted = db.execute("insert or ignore into rounds values(?,?,?,?,?,?,?,?)",
                (rid, row["ts"], str(stage), mode, character, outcome, json.dumps(data),
                 json.dumps(self.vector(data)))).rowcount
            payload = {"source": f"gbox:mercs:{self.map_id}:{rid}", "game": str(self.map_id), "kind": "mercs_round",
                       "title": f"Mercenaries {self.map_id} {mode} {stage}",
                       "text": f"Observed Mercenaries round {rid}: {mode}, {stage}, {character}, outcome {outcome}. "
                               + json.dumps(data, sort_keys=True)}
            db.execute("insert or ignore into knowledge_outbox(id,payload) values (?,?)", (rid,json.dumps(payload)))
        if inserted:
            with (self.root / "rounds.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(row) + "\n")
        self.guide()
        return row

    def publish(self, server, token):
        """Durable, idempotent delivery to gBox's existing semantic vector KB off the input thread."""
        if self._publishing or not server or not token: return
        self._publishing = True
        def deliver():
            try:
                import httpx
                with self.connect() as db:
                    rows = db.execute("select id,payload from knowledge_outbox where delivered=0 order by rowid limit 20").fetchall()
                for rid, payload in rows:
                    response = httpx.post(server.rstrip('/')+'/api/kb', headers={'authorization':'Bearer '+token},
                                          json=json.loads(payload), timeout=150)
                    response.raise_for_status()
                    with self.connect() as db:
                        db.execute("update knowledge_outbox set delivered=1 where id=?", (rid,))
            except Exception as exc:
                (self.root/'knowledge-delivery-error.json').write_text(json.dumps({'error':str(exc),'ts':time.time()}),encoding='utf-8')
            finally:
                self._publishing = False
        threading.Thread(target=deliver, name='mercs-round-knowledge', daemon=True).start()

    def guide(self):
        with self.connect() as db:
            rows = db.execute("select stage,mode,character,outcome,data from rounds order by ts").fetchall()
        stages = {}
        for stage, mode, char, outcome, raw in rows:
            data = json.loads(raw)
            entry = stages.setdefault(f"{mode}/{stage}", {"rounds": 0, "completed": 0,
                "best_score": 0, "best_bonus_count": 0, "verified_s_ranks": 0, "characters": []})
            entry["rounds"] += 1
            entry["completed"] += outcome == "completed"
            entry["best_score"] = max(entry["best_score"], data.get("score") or 0)
            entry["best_bonus_count"] = max(entry["best_bonus_count"], data.get("bonuses_taken") or 0)
            entry["verified_s_ranks"] += bool(data.get("s_rank_verified"))
            if char not in entry["characters"]: entry["characters"].append(char)
        guide = {"version": 1, "updated": time.time(), "rounds": len(rows), "stages": stages,
                 "policy": "Use verified directed navmesh routes. Avoid recorded failed crossings; "
                           "seek uncollected time bonuses; dispatch immediate exposed threats en route. "
                           "Missing pickups and unobserved result ranks remain unproven."}
        guide['latest_reviews'] = {f'{mode}/{stage}': json.loads(raw).get('reflection')
                                  for stage,mode,char,outcome,raw in rows}
        temp = self.root / "guide.tmp"
        temp.write_text(json.dumps(guide, indent=2), encoding="utf-8")
        temp.replace(self.root / "guide.json")
        return guide
