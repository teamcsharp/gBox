"""Durable player-damage receipts and one normal Inbox investigation per autoplay run.

Each observed HP loss has its own ledger record/artifacts. Inbox summaries are bounded and link to the complete,
paged ledger; events are never evicted to make that summary fit. No direct Hermes dispatch or admission bypass.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import re
import threading
import time

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from . import coaching, coaching_evidence as E

KIND, RUN_KIND = "player_damage", "player_damage_run"
MAX_EVENT = 256 * 1024
ID = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
_lock = threading.RLock()


def key(sid, eid):
    return hashlib.sha256((sid + ":" + eid).encode()).hexdigest()


def validate(event, sid):
    if not isinstance(event, dict) or event.get("session_id") != sid or event.get("schema") != "gbox.player_damage/1":
        raise ValueError("damage event schema/session mismatch")
    if not all(ID.fullmatch(str(event.get(k) or "")) for k in ("event_id", "run_id", "round_id")):
        raise ValueError("invalid damage event/run/round ID")
    for k in ("observed_at", "hp_before", "hp_after", "hp_max", "loss"):
        if type(event.get(k)) not in (float, int):
            raise ValueError(f"invalid damage {k}")
    if not (0 <= event["hp_after"] < event["hp_before"] <= event["hp_max"]
            and event["loss"] == event["hp_before"] - event["hp_after"] and event["observed_at"] > 0):
        raise ValueError("not a positive same-maximum HP loss")
    data = json.dumps(event, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > MAX_EVENT:
        raise ValueError("damage event exceeds 256 KiB")
    from .mercs.incident import unpack_context
    unpack_context(event)                              # rejects corrupt or unbounded compressed evidence
    return hashlib.sha256(data).hexdigest()


def freeze(moment_provider, sid, event, received_at):
    from .mercs.incident import unpack_context
    event = unpack_context(event)
    packet = E.capture(moment_provider, sid, received_at)
    packet.update(damage_event_id=event["event_id"], event_observed_at=event["observed_at"],
                  delivery_delay_s=received_at - event["observed_at"], provenance=event.get("provenance"),
                  evidence_backpressure=event.get("evidence_backpressure", False))
    if event.get('packed_context'):
        packet['context_compression'] = {key: value for key, value in event['packed_context'].items() if key != 'data_b64'}
    image = event.get("frame_at_hit") or {"state": "unavailable-at-hit", "detail": "worker did not retain a frame"}
    packet["frame_at_hit"] = {k: v for k, v in image.items() if k != "data_b64"}
    if image.get("state") == "cached-at-observation":
        try:
            data = base64.b64decode(image["data_b64"], validate=True)
            at = image["at"]
            if (type(at) not in (int, float) or not math.isfinite(at) or at <= 0
                    or len(data) > 128 * 1024 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9")):
                raise ValueError("invalid local cached frame")
            packet["sources"]["stream"] = {"data": data, "source_at": at, "at": at,
                "age_s": received_at - at, "seq": image.get("seq"), "timestamp_basis": image.get("timestamp_basis"),
                "timing": "worker cache frozen at HP-loss observation; independent of the HP read"}
        except (KeyError, TypeError, ValueError) as exc:
            packet["frame_at_hit"] = {"state": "unavailable-at-hit", "detail": str(exc)[:200]}
    if packet["frame_at_hit"].get("state") != "cached-at-observation":
        packet["sources"]["stream"]["timing"] = "server cache copied at delivery; no image retained at HP-loss observation"
    # Snapshot-derived state/map is the actual pre-maintenance worker observation, not a later telemetry poll.
    old_map = packet["sources"]["tactical"]
    frame = copy.deepcopy(event.get("tactical") or {})
    stage = old_map.get("stage") if (old_map.get("frame") or {}).get("stage") == frame.get("stage") else None
    source = {"at": event["observed_at"], "source_at": event["observed_at"],
              "age_s": received_at - event["observed_at"], "timestamp_basis": "worker pre-maintenance observation"}
    packet["sources"]["tactical"] = source | {"frame": frame, "stage": stage,
        "geometry_status": "available" if stage else "missing; only observed positions can be rendered"}
    if not frame or frame.get("capture_error"):
        packet["sources"]["tactical"] = {"error": frame.get("capture_error") or "map snapshot missing due to evidence backpressure"}
    packet["sources"]["telemetry"] = source | {"data": event.get("logic") or {}}
    packet["sources"]["ram_fields"] = source | {"data": {"snapshot": event.get("snapshot"),
        "raw_hook_bytes": event.get("raw"), "held": event.get("held"), "plan": event.get("plan"),
        "preceding_history": event.get("preceding_history"), "ram_witness": event.get("ram_witness"),
        "map_at_observation_svg": event.get("map_at_observation_svg"),
        "cause": "unknown", "self_damage": "unknown", "limits": event.get("limits")}}
    for src in packet["sources"].values():
        if "source_at" in src:
            src["offset_from_event_s"] = src["source_at"] - event["observed_at"]
    return packet


def ingest(store, sid, event, moment_provider=None, now=None, frozen_moment=None):
    """Acknowledge only after both the original event and frozen evidence are durable. Retries never recapture."""
    fingerprint = validate(event, sid)
    session = store.get("session", sid)
    if not session:
        raise ValueError("unknown damage session")
    eid = key(sid, event["event_id"])
    old = store.get(KIND, eid)
    if old:
        if old["fingerprint"] != fingerprint:
            raise ValueError("damage event ID already names different data")
        return {"accepted": True, "event_id": event["event_id"], "state": old["state"], "deduplicated": True}
    received_at = time.time() if now is None else now
    packet = frozen_moment if frozen_moment is not None else freeze(moment_provider, sid, event, received_at)
    # The JPEG remains bytes in the live capture API; encode only for its durable receipt artifact.
    stream = packet["sources"]["stream"]
    if isinstance(stream.get("data"), bytes):
        stream["data_b64"] = base64.b64encode(stream.pop("data")).decode("ascii")
    with _lock:
        old = store.get(KIND, eid)
        if old:
            if old["fingerprint"] != fingerprint:
                raise ValueError("damage event ID already names different data")
            return {"accepted": True, "event_id": event["event_id"], "state": old["state"], "deduplicated": True}
        ref = store.put_artifact(json.dumps({"event": event, "moment": packet}, allow_nan=False).encode(),
            f"damage-{event['event_id']}-receipt.json", "application/json",
            {"session_id": sid, "damage_event_id": event["event_id"], "observed_at": event["observed_at"]})
        row = {"id": eid, "event_id": event["event_id"], "run_id": event["run_id"],
            "session_id": sid, "game_id": session.get("game_id"), "round_id": event["round_id"],
            "observed_at": event["observed_at"],
            "received_at": received_at, "fingerprint": fingerprint, "receipt": ref.sha256,
            "loss": event["loss"], "hp_before": event["hp_before"], "hp_after": event["hp_after"],
            "state": "pending", "attempts": 0, "cause": "unknown", "self_damage": "unknown"}
        store.put(KIND, eid, row)
    # Its cause-cluster incident (RE Mercenaries games only); never fails the acknowledged receipt.
    from .mercs import damage_clusters
    damage_clusters.record_event(store, row, event)
    return {"accepted": True, "event_id": event["event_id"], "state": "pending"}


def rows(store, sid, run_id, *, limit=100, offset=0, latest=False):
    with store.lock:
        found = store.db.execute("SELECT body FROM docs WHERE kind=? AND json_extract(body,'$.session_id')=? "
            "AND json_extract(body,'$.run_id')=? ORDER BY json_extract(body,'$.observed_at') " +
            ("DESC, id DESC" if latest else "ASC, id ASC") + " LIMIT ? OFFSET ?",
            (KIND, sid, run_id, min(100, max(1, limit)), max(0, offset))).fetchall()
    return [json.loads(r[0]) for r in found]


def counts(store, sid, run_id):
    with store.lock:
        total, pending, rounds = store.db.execute("SELECT COUNT(*), SUM(json_extract(body,'$.state')!='done'), "
            "COUNT(DISTINCT json_extract(body,'$.round_id')) FROM docs WHERE kind=? "
            "AND json_extract(body,'$.session_id')=? AND json_extract(body,'$.run_id')=?",
            (KIND, sid, run_id)).fetchone()
    return {"total": total, "pending": pending or 0, "rounds": rounds}


def request_for(store, create_request, event):
    rid_key = key(event["session_id"], event["run_id"])
    run = store.get(RUN_KIND, rid_key) or {}
    if run.get("request_id") and store.get("request", run["request_id"]):
        return run["request_id"]
    # An uncertain create may have persisted its request before raising. Look up its exact identity before retry.
    existing = next((r for r in store.all("request") if (r.get("context") or {}).get("damage_run_key") == rid_key), None)
    if existing is None:
        existing = create_request({"title": "Player damage: autoplay session batch " + event["run_id"][:12],
            "source": "player_damage", "author": "agent", "automated": True, "kind": "report",
            "context": {"game_id": event.get("game_id"), "session_id": event["session_id"],
                        "player_damage": True, "operator_requested": True, "auto_report": True,
                        "damage_run_key": rid_key, "damage_run_id": event["run_id"]},
            "body": "The operator requested automatic investigation of every observed player HP loss. "
                    "Use this run's complete event ledger and its timestamped screenshot, tactical map, snapshot, "
                    "raw hook bytes and supported save-state evidence. Diagnose and fix recurring avoidable damage, "
                    "publish a reviewed change, and verify actual play. Cause and self-damage are unknown unless "
                    "independent game evidence proves them. Preserve normal ownership, admission and review rules. "
                    "Do not claim every physical hit is separately observable between RAM samples."}, "gbox-auto")
    store.put(RUN_KIND, rid_key, {"id": rid_key, "session_id": event["session_id"], "run_id": event["run_id"],
                                "request_id": existing["id"], "updated": time.time()})
    return existing["id"]


def update_summary(store, event, rid):
    recent = rows(store, event["session_id"], event["run_id"], limit=20, latest=True)
    count = counts(store, event["session_id"], event["run_id"])
    url = f"/api/sessions/{event['session_id']}/damage/runs/{event['run_id']}"
    summary = {"id": "player-damage-run", "author": "agent", "ts": time.time(),
        "text": f"{count['total']} observed player HP-loss events across {count['rounds']} round(s) retained "
                "for this autoplay session batch. "
                f"Complete paged event/evidence ledger: {url}\n"
                "Recent events (earlier events remain in the ledger):\n" + "\n".join(
                    f"{r['event_id']}: HP {r['hp_before']} → {r['hp_after']} ({r['state']}); "
                    f"save state: {(r.get('save_state') or {}).get('state', 'pending')}"
                    for r in recent),
        "attachments": [a for r in recent[:4] for a in r.get("attachments", [])],
        "damage_run": {"events": count["total"], "ledger": url, "summary_events": len(recent),
                       "rounds": count["rounds"], "pending": count["pending"]}}
    with store.lock:
        req = store.get("request", rid)
        if req is None:
            raise ValueError("damage batch request disappeared")
        if req.get("status") == "done" and not (req.get("context") or {}).get("batched_into"):
            # A run batched into cause clusters (gbox.mercs.damage_clusters) stays closed: its batches take new damage.
            req.update(status="open", completed=None)
        req["messages"] = [m for m in req.get("messages", []) if m.get("id") != summary["id"]] + [summary]
        store.put("request", rid, req)


def materialize(store, create_request, submit, eid):
    with _lock:
        row = store.get(KIND, eid)
        if not row or row["state"] == "done":
            return row
        try:
            saved = json.loads(store.read_artifact(row["receipt"]))
            packet = saved["moment"]
            stream = packet["sources"]["stream"]
            if "data_b64" in stream:
                stream["data"] = base64.b64decode(stream.pop("data_b64"), validate=True)
            rid = request_for(store, create_request, row)
            worker_svg = (packet['sources'].get('ram_fields', {}).get('data') or {}).get('map_at_observation_svg')
            if isinstance(worker_svg, str) and worker_svg.startswith('<svg') and len(worker_svg.encode()) <= 512*1024:
                packet['_map'] = worker_svg.encode()      # includes the path preceding damage, frozen on the worker
            else:
                E.prepare_map(packet)
            evidence, attachments = E.attach(store, packet, row["event_id"], rid)
            evidence["stream"]["timing"] = stream.get("timing")
            evidence["stream"]["frame_at_hit"] = packet.get("frame_at_hit")
            if stream.get("timing"):
                evidence["stream"]["detail"] = stream["timing"]
            row.update(request_id=rid, evidence=evidence, attachments=attachments)
            # Save-state capture uses the existing supported operation and ordinary job queue. One per session.
            state = row.get("save_state")
            if state is None:
                session = store.get("session", row["session_id"]) or {"session_id": row["session_id"]}
                state = ({"state": "skipped_disruptive", "detail": "RPCS3 may advertise save_state, but its save "
                          "path can reload the game; no verified non-disruptive gBox-owned automatic damage capture"}
                         if str(session.get("adapter") or "").lower() == "rpcs3"
                         else coaching.plan(store, session)["state"])
                with store.reading() as db:
                    busy = db.execute("SELECT 1 FROM docs WHERE kind=? AND json_extract(body,'$.session_id')=? "
                        "AND json_extract(body,'$.save_state.state') IN ('pending','uncertain') LIMIT 1",
                        (KIND, row["session_id"])).fetchone() is not None
                if state.get("tool") and busy:
                    state = {"state": "skipped-backpressure", "detail": "another run save capture is pending; "
                             "no later substitute will be labelled the damage moment"}
                elif state.get("tool"):
                    # Persist the uncertain submission before calling a job-creating operation; never repeat it.
                    row["save_state"] = {"state": "uncertain", "detail": "save-state submission started"}
                    store.put(KIND, eid, row)
                    try:
                        job = submit(state["tool"], state["input"], rid, "gbox-auto")
                        state = {"state": "pending", "job": job["id"], "tool": state["tool"],
                                 "detail": "asynchronous capture after HP-loss receipt, not an atomic damage moment"}
                    except Exception as exc:
                        state = {"state": "uncertain", "detail": str(exc)[:300]}
                row["save_state"] = state
            row.update(state="done", error="", materialized_at=time.time())
            store.put(KIND, eid, row)
            update_summary(store, row, rid)
        except Exception as exc:
            attempts = row.get("attempts", 0) + 1
            row.update(state="retrying", attempts=attempts, error=str(exc)[:300],
                       next_attempt_at=time.time() + min(60, 2 ** min(attempts, 6)))
            store.put(KIND, eid, row)
        return row


def settle_states(store):
    with store.reading() as db:
        pending = db.execute("SELECT d.body FROM docs d LEFT JOIN docs j ON j.kind='job' "
            "AND j.id=json_extract(d.body,'$.save_state.job') WHERE d.kind=? "
            "AND json_extract(d.body,'$.save_state.state')='pending' "
            "AND (j.id IS NULL OR COALESCE(json_extract(j.body,'$.state'),'') NOT IN ('queued','running')) "
            "ORDER BY d.rowid LIMIT 32", (KIND,)).fetchall()
    for (body,) in pending:
        row = json.loads(body)
        state = row["save_state"]
        job = store.get("job", state.get("job") or "")
        if not job:
            row["save_state"] = state | {"state": "uncertain", "detail": "submitted save job is missing; "
                "no automatic resubmission of this capture", "timing": "asynchronous after observed HP loss"}
            store.put(KIND, row["id"], row)
            update_summary(store, row, row["request_id"])
            continue
        if job.get("state") in ("queued", "running"):
            continue
        result = coaching._finish(store, "state", job, row["event_id"], row["request_id"])
        row["save_state"] = result["capture"] | {"timing": "asynchronous after observed HP loss"}
        row["attachments"] += result.get("attachments", [])
        store.put(KIND, row["id"], row)
        update_summary(store, row, row["request_id"])


def pending_events(store, now):
    # The completed ledger grows forever. Poll only the partial index of work
    # still due, without taking the writer lock used by live viewer controls.
    with store.reading() as db:
        return [row[0] for row in db.execute(
            "SELECT id FROM docs WHERE kind=? AND json_extract(body,'$.state') != 'done' "
            "AND COALESCE(json_extract(body,'$.next_attempt_at'),0)<=? ORDER BY rowid LIMIT 32",
            (KIND, now)).fetchall()]


def routes(app, store, auth, create_request, submit, moment_provider=None):
    wake, stopped = threading.Event(), threading.Event()

    def flush():
        while not stopped.is_set():
            try:
                for eid in pending_events(store, time.time()):
                    if stopped.is_set():
                        return
                    materialize(store, create_request, submit, eid)
                settle_states(store)
            except Exception:
                pass                         # durable pending/retrying rows survive; next pass or restart retries
            wake.wait(2)
            wake.clear()

    @app.on_event("startup")
    def start():
        threading.Thread(target=flush, daemon=True, name="damage-reports").start()

    @app.on_event("shutdown")
    def stop():
        stopped.set()
        wake.set()

    @app.post("/api/autoplay/damage/{sid}")
    async def receive(sid: str, request: Request, actor=Depends(auth)):
        received_at = time.time()
        raw = await request.body()
        if len(raw) > MAX_EVENT:
            raise HTTPException(413, "damage event exceeds 256 KiB")
        try:
            event = json.loads(raw)
            validate(event, sid)
            packet = freeze(moment_provider, sid, event, received_at)
            out = await run_in_threadpool(ingest, store, sid, event, moment_provider, received_at, packet)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, "damage receipt not durable; retain and retry: " + str(exc)[:200]) from exc
        wake.set()
        return out

    @app.get("/api/sessions/{sid}/damage/runs/{run_id}")
    def ledger(sid: str, run_id: str, offset: int = 0, limit: int = 50, actor=Depends(auth)):
        if not store.get("session", sid) or not ID.fullmatch(run_id):
            raise HTTPException(404, "damage session/run not found")
        offset, limit = max(0, offset), min(100, max(1, limit))
        total = counts(store, sid, run_id)["total"]
        run = store.get(RUN_KIND, key(sid, run_id)) or {}
        return {"session_id": sid, "run_id": run_id, "total": total,
                "request_id": run.get("request_id"), "game_id": (store.get("session", sid) or {}).get("game_id"),
                "events": rows(store, sid, run_id, limit=limit, offset=offset),
                "next_offset": offset + limit if offset + limit < total else None}
