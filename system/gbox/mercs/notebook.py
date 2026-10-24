"""Round evidence, a generated guide, and bounded recall consumed before play.

Local vectors are numerical performance features. Semantic KB results can select
measured local reviews, but their prose never supplies actions or coordinates.
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
SEMANTIC_REFRESH_S = 300.
SEMANTIC_RETRY_S = 60.
SEMANTIC_MAX_AGE_S = 3600.


def reflect(outcome, stats):
    """Diagnose measured failures; acceptance requires positive observations."""
    remaining = stats.get('time_bonuses_remaining')
    rank = outcome == 'completed' and stats.get('result_rank') in ('S','SS','S+','S++')
    assistance = stats.get('assistance') or {}
    clean = assistance.get('classification') == 'unmodified' and assistance.get('verified') is True
    damage = stats.get('player_damage_events')
    protection = stats.get('round_used_health_protection', stats.get('health_protection_used'))
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
    if rank and not clean:
        findings.append('observed rank does not establish unmodified mastery: assistance is '+
                        str(assistance.get('classification', 'unknown')))
    return {'schema': 'gbox.mercs.round-review/1', 'findings': findings, 'next_run_actions': changes,
            'acceptance': {'completed_s_rank': rank,
                'unmodified_s_rank': rank and clean,
                'all_observed_time_bonuses': remaining == 0 if remaining is not None else None,
                'no_sampled_hp_loss': (False if isinstance(damage,(int,float)) and damage > 0
                                       else True if damage == 0 and protection is False else None)},
            'health_protection_used': protection if type(protection) is bool else None,
            'policy': {'bonus_commitment': True, 'learn_failed_crossings': True,
                       'allow_unverified_routes': False}}


class Notebook:
    def __init__(self, root, map_id):
        self.root = Path(root) / "curriculum" / str(map_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "rounds.sqlite"
        self.map_id = map_id
        self._publishing = False
        self._knowledge = None
        self._semantic_lock = threading.Lock()
        self._semantic_jobs = set()
        with self.connect() as db:
            db.execute("create table if not exists rounds(id text primary key, ts real, stage text, mode text, "
                       "character text, outcome text, data text, vector text)")
            db.execute("create table if not exists knowledge_outbox(id text primary key, payload text, delivered integer default 0)")
            db.execute("create table if not exists semantic_recall(stage text, mode text, at real, payload text, "
                       "primary key(stage,mode))")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("pragma journal_mode=WAL")
        return db

    @staticmethod
    def vector(stats):
        return [max(0., min(4., float(stats.get(k) or 0) / scale)) for k, scale in FEATURES]

    def recall(self, stage, mode, stats=None, limit=5):
        """Recall measured reviews; semantic search runs separately from gameplay.

        Stage and mode are hard filters. Up to two cached KB source IDs can add
        relevant local reviews; KB text is never parsed as policy or navigation.
        """
        query = self.vector(stats or {})
        with self.connect() as db:
            rows = db.execute("select id,outcome,data,vector from rounds where stage=? and mode=? "
                              "order by ts desc limit 200", (str(stage), mode)).fetchall()
            cached = db.execute("select at,payload from semantic_recall where stage=? and mode=?",
                                (str(stage), mode)).fetchone()
        ranked = sorted(rows, key=lambda r: sum((a-b)**2 for a,b in zip(query, json.loads(r[3]))))
        receipt = json.loads(cached[1]) if cached else {}
        valid_cache = cached is not None and 0 <= time.time()-cached[0] <= SEMANTIC_MAX_AGE_S
        by_id = {row[0]:row for row in rows}
        selected = [by_id[rid] for rid in receipt.get("accepted_round_ids", ())[:2]
                    if valid_cache and rid in by_id]
        selected.extend(row for row in ranked if row[0] not in {r[0] for r in selected})
        selected = selected[:max(0, min(5, limit))]
        semantic_ids = [row[0] for row in selected if row[0] in receipt.get("accepted_round_ids", ())[:2]
                        and valid_cache]
        if stats is not None:
            status = receipt.get("status", "pending" if self._knowledge else "unconfigured")
            if not rows:
                status = "no_measured_reviews"
            elif cached and not valid_cache:
                status = "expired"
            chunks = [int(chunk) for chunk,rid in receipt.get("chunk_round_ids",{}).items() if rid in semantic_ids]
            stats.update(round_semantic_status=status,
                         round_semantic_recalled=len(semantic_ids), round_semantic_round_ids=semantic_ids,
                         round_semantic_kb_chunks=chunks)
        if semantic_ids:
            receipt.update(consumed_at=time.time(), consumed_round_ids=semantic_ids,
                           consumption_count=receipt.get("consumption_count", 0)+1)
            with self.connect() as db:
                db.execute("update semantic_recall set payload=? where stage=? and mode=?",
                           (json.dumps(receipt), str(stage), mode))
        if rows:
            self._queue_semantic(stage, mode, cached)
        return [{"id": r[0], "outcome": r[1], "observed": json.loads(r[2]),
                 "recall_source": "semantic_local_review" if r[0] in semantic_ids else "performance_vector"}
                for r in selected]

    def configure_knowledge(self, server, token):
        """Use the same authenticated KB as round publication; never persist its token."""
        if server and token:
            self._knowledge = (server.rstrip('/'), token)

    def _queue_semantic(self, stage, mode, cached=None):
        if not self._knowledge:
            return
        if cached:
            old = json.loads(cached[1])
            refresh = SEMANTIC_RETRY_S if old.get("status") == "error" else SEMANTIC_REFRESH_S
            if 0 <= time.time()-cached[0] < refresh:
                return
        key = (str(stage), mode)
        with self._semantic_lock:
            if key in self._semantic_jobs:
                return
            self._semantic_jobs.add(key)
        server, token = self._knowledge
        def retrieve():
            receipt = {"schema":"gbox.mercs.semantic-recall/1", "stage":key[0], "mode":mode,
                       "status":"ready", "accepted_round_ids":[], "accepted_chunk_ids":[],
                       "selection_only":True}
            try:
                import httpx
                query = (f"Observed Mercenaries round {self.map_id} {mode} {key[0]}. "
                         "Time bonuses checkpoint routes failed movement stuck oscillation damage next run actions.")
                response = httpx.get(server+'/api/kb/search', headers={'authorization':'Bearer '+token},
                                     params={'q':query[:1200], 'game':str(self.map_id), 'k':20}, timeout=10.)
                response.raise_for_status()
                if len(response.content) > 128*1024:
                    raise ValueError('semantic response exceeds 128 KiB')
                hits = response.json()
                if not isinstance(hits,list):
                    raise ValueError('semantic response must contain a list')
                with self.connect() as db:
                    allowed = {r[0] for r in db.execute('select id from rounds where stage=? and mode=? '
                                                       'order by ts desc limit 200', key)}
                prefix = f'gbox:mercs:{self.map_id}:'
                accepted_chunks = []
                for hit in hits[:20]:
                    if not isinstance(hit,dict) or hit.get('kind') != 'mercs_round' \
                            or str(hit.get('game','')).lower() != str(self.map_id).lower():
                        continue
                    source, score = hit.get('source'), hit.get('score')
                    if not isinstance(source,str) or not source.startswith(prefix) \
                            or type(score) not in (int,float) or not math.isfinite(score) or not .55 <= score <= 1.05:
                        continue
                    rid = source[len(prefix):]
                    if rid not in allowed:
                        continue
                    chunk = hit.get('id')
                    if type(chunk) is int and chunk >= 0:
                        accepted_chunks.append((rid,chunk))
                    if rid not in receipt['accepted_round_ids']:
                        receipt['accepted_round_ids'].append(rid)
                receipt['accepted_round_ids'] = receipt['accepted_round_ids'][:2]
                receipt['accepted_chunk_ids'] = list(dict.fromkeys(chunk for rid,chunk in accepted_chunks
                                                                  if rid in receipt['accepted_round_ids']))
                receipt['chunk_round_ids'] = {str(chunk):rid for rid,chunk in accepted_chunks
                                             if rid in receipt['accepted_round_ids']}
            except Exception as exc:
                # Keep secrets and arbitrary server text out of persisted evidence.
                receipt.update(status='error', error_type=type(exc).__name__)
            try:
                with self.connect() as db:
                    db.execute('insert into semantic_recall values(?,?,?,?) on conflict(stage,mode) '
                               'do update set at=excluded.at,payload=excluded.payload',
                               (*key,time.time(),json.dumps(receipt)))
            finally:
                with self._semantic_lock:
                    self._semantic_jobs.discard(key)
        threading.Thread(target=retrieve,name='mercs-semantic-recall',daemon=True).start()

    def finish(self, stage, mode, character, outcome, stats, *, round_id=None):
        rid = round_id or uuid.uuid4().hex
        data = {k: v for k, v in stats.items() if isinstance(v, (str, int, float, bool, type(None)))}
        for key, limit in (('round_policy_source_ids',5),('round_semantic_round_ids',2)):
            values=stats.get(key)
            if isinstance(values,list):
                data[key]=[value for value in values[:limit] if isinstance(value,str) and len(value)==32
                           and all(c in '0123456789abcdef' for c in value)]
        data["result_rank_observed"] = stats.get("result_rank")
        data["s_rank_verified"] = outcome == "completed" and stats.get("result_rank") in ("S", "SS", "S+", "S++")
        assistance = stats.get('assistance')
        if not isinstance(assistance, dict):
            assistance = {'classification': 'unknown', 'verified': False, 'effects': []}
        data['assistance'] = assistance
        data['unmodified_s_rank_verified'] = bool(data['s_rank_verified']
            and assistance.get('classification') == 'unmodified' and assistance.get('verified') is True)
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
        self.configure_knowledge(server,token)
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
            semantic = {f'{mode}/{stage}': {'searched_at':at, **json.loads(payload)}
                        for stage,mode,at,payload in db.execute('select stage,mode,at,payload from semantic_recall')}
        stages = {}
        for stage, mode, char, outcome, raw in rows:
            data = json.loads(raw)
            entry = stages.setdefault(f"{mode}/{stage}", {"rounds": 0, "completed": 0,
                "best_score": 0, "best_bonus_count": 0, "verified_s_ranks": 0, "characters": [],
                'unmodified_s_ranks': 0, 'assisted_rounds': 0, 'unknown_rules_rounds': 0})
            entry["rounds"] += 1
            entry["completed"] += outcome == "completed"
            entry["best_score"] = max(entry["best_score"], data.get("score") or 0)
            entry["best_bonus_count"] = max(entry["best_bonus_count"], data.get("bonuses_taken") or 0)
            entry["verified_s_ranks"] += bool(data.get("s_rank_verified"))
            entry['unmodified_s_ranks'] += bool(data.get('unmodified_s_rank_verified'))
            classification = (data.get('assistance') or {}).get('classification', 'unknown')
            entry['assisted_rounds'] += classification == 'mod_assisted'
            entry['unknown_rules_rounds'] += classification == 'unknown'
            if char not in entry["characters"]: entry["characters"].append(char)
        guide = {"version": 1, "updated": time.time(), "rounds": len(rows), "stages": stages,
                 "policy": "Use verified directed navmesh routes. Avoid recorded failed crossings; "
                           "seek uncollected time bonuses; dispatch immediate exposed threats en route. "
                           "Missing pickups and unobserved result ranks remain unproven."}
        guide['latest_reviews'] = {f'{mode}/{stage}': json.loads(raw).get('reflection')
                                  for stage,mode,char,outcome,raw in rows}
        guide['semantic_recall'] = semantic
        guide['training_policy'] = {'target': 'Repeated S ranks under original gameplay rules',
            'automatic_modifier_reduction': False,
            'assisted_scores_qualify_as_unmodified': False,
            'legacy_rules': 'unknown',
            'reason': 'Retain operator training aids until a separately verified unmodified evaluation.'}
        temp = self.root / "guide.tmp"
        temp.write_text(json.dumps(guide, indent=2), encoding="utf-8")
        temp.replace(self.root / "guide.json")
        return guide
