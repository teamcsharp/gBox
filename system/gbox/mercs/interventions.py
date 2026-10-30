"""Durable, per-click live actions shared by stream UI and MCP.

Claim before any game write. An uncertain/lost claim is never replayed, including
after worker/server reload. Requests are fenced to the reported player life and
expire rather than affecting a later round. No latest-value command coalescing.
"""
from __future__ import annotations

import json
import time
import uuid

KIND = "merc_interventions"
MAX_PENDING, KEEP, TTL, FRESH = 64, 128, 10.0, 3.0
TERMINAL = {"confirmed", "failed", "unavailable", "expired", "uncertain"}
OPERATIONS = {"flash_now", "equip_primary"}


class Queue:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def _remember(self, sid, row):
        self.store.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?)",
            (KIND + "_id", sid + ":" + row["id"], json.dumps(row)))

    def _change(self, sid, fn):
        # Cross-process atomic as well as thread-safe. Never call Store.put
        # inside this transaction (it commits independently).
        s = self.store
        with s.lock:
            s.db.execute("BEGIN IMMEDIATE")
            try:
                raw = s.db.execute("SELECT body FROM docs WHERE kind=? AND id=?", (KIND, sid)).fetchone()
                doc = json.loads(raw[0]) if raw else {"rows": [], "epoch": "", "capabilities": []}
                before = json.dumps(doc, separators=(",", ":"))
                now = self.clock()
                for r in doc["rows"]:
                    if r["state"] == "queued" and r["expires"] <= now:
                        r.update(state="expired", reason="request expired before execution")
                        self._remember(sid, r)
                    if r["state"] == "claimed" and r["claimed_at"] + TTL <= now:
                        r.update(state="uncertain", reason="worker receipt missing; not replayed")
                        self._remember(sid, r)
                result = fn(doc, now)
                after = json.dumps(doc, separators=(",", ":"))
                if before != after:
                    s.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?)", (KIND, sid, after))
                s.db.commit()
                return result
            except BaseException:
                s.db.rollback()
                raise

    def status(self, sid):
        def view(d, now):
            return {"session_id": sid, "available": now - d.get("seen", 0) <= FRESH,
                    "capabilities": d["capabilities"], "reason": d.get("reason", "worker not connected"),
                    "options": d.get("options", {}),
                    "requests": [{k:v for k,v in r.items() if k != "claim"} for r in d["rows"]]}
        return self._change(sid, view)

    def post(self, sid, op, request_id, source, args=None):
        if op not in OPERATIONS:
            raise ValueError("unsupported intervention")
        args = {} if args is None else args
        if not isinstance(args, dict) or (op == 'flash_now' and args) or (op == 'equip_primary' and
                (set(args) != {'item'} or type(args['item']) is not int or not 1 <= args['item'] <= 255)):
            raise ValueError('invalid intervention arguments')
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, AttributeError):
            raise ValueError("request_id must be a UUID, unique for each click") from None
        def add(d, now):
            # A separate tombstone survives trimming the UI's recent history.
            saved = self.store.db.execute("SELECT body FROM docs WHERE kind=? AND id=?",
                (KIND + "_id", sid + ":" + request_id)).fetchone()
            old = json.loads(saved[0]) if saved else None
            if old:
                if old["op"] != op or old.get('args', {}) != args:
                    raise ValueError("request_id already names another operation")
                return {k:v for k,v in old.items() if k != "claim"}
            if now - d.get("seen", 0) > FRESH or op not in d["capabilities"]:
                raise ValueError(d.get("reason") or "native intervention is unavailable")
            if op == 'equip_primary' and args['item'] not in {
                    w['item'] for w in d.get('options', {}).get('weapons', [])}:
                raise ValueError('weapon is not offered by this session')
            if sum(r["state"] in ("queued", "claimed") for r in d["rows"]) >= MAX_PENDING:
                raise ValueError("intervention queue is full")
            row = {"id": request_id, "op": op, "args": dict(args), "source": source, "at": now, "expires": now + TTL,
                   "epoch": d["epoch"], "state": "queued"}
            d["rows"].append(row)
            self.store.db.execute("INSERT INTO docs VALUES(?,?,?)",
                (KIND + "_id", sid + ":" + request_id, json.dumps(row)))
            while len(d["rows"]) > KEEP:
                i = next(i for i,r in enumerate(d["rows"]) if r["state"] in TERMINAL)
                d["rows"].pop(i)
            return dict(row)
        return self._change(sid, add)

    def claim(self, sid, epoch, capabilities, reason="", options=None):
        options = options or {}
        def take(d, now):
            if epoch != d["epoch"] or capabilities != d["capabilities"] or options != d.get('options', {}) or now - d.get("seen", 0) >= 1:
                d.update(epoch=epoch, capabilities=capabilities, seen=now, reason=reason, options=options)
            out = []
            for r in d["rows"]:
                if r["state"] != "queued":
                    continue
                if r["epoch"] != epoch or r["op"] not in capabilities:
                    r.update(state="expired", reason="active player or capability changed")
                    self._remember(sid, r)
                    continue
                if len(out) < 20:
                    r.update(state="claimed", claim=uuid.uuid4().hex, claimed_at=now)
                    self._remember(sid, r)
                    out.append(dict(r))
            return out
        return self._change(sid, take)

    def finish(self, sid, rid, claim, result):
        return self.finish_many(sid, [{"id":rid,"claim":claim,"result":result}])[0]

    def finish_many(self, sid, results):
        if not isinstance(results, list) or not 1 <= len(results) <= MAX_PENDING:
            raise ValueError("invalid completion batch")
        for item in results:
            result = item.get("result") or {}
            state = result.get("state")
            if state not in ("confirmed", "failed", "unavailable", "uncertain") or (state == "confirmed" and result.get("verified") is not True):
                raise ValueError("completion needs an explicit verified result")
            if len(json.dumps(result)) > 4096:
                raise ValueError("receipt too large")
        def done(d, now):
            out = []
            for item in results:
                rid, claim, result = item["id"], item.get("claim"), item["result"]
                r = next((r for r in d["rows"] if r["id"] == rid), None)
                if not r or r.get("claim") != claim:
                    raise ValueError("unknown claim")
                if r["state"] in ("claimed", "uncertain"):
                    r.update(state=result["state"], result=result, finished_at=now)
                    self.store.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?)",
                        (KIND + "_id", sid + ":" + rid, json.dumps(r)))
                out.append({k:v for k,v in r.items() if k != "claim"})
            return out
        return self._change(sid, done)


def install(app, store, auth):
    from fastapi import Depends, HTTPException
    queue = Queue(store)

    def live(sid):
        s = store.get("session", sid)
        if not s or s.get("state") != "running":
            raise HTTPException(409, "session is not running")

    @app.get("/api/sessions/{sid}/interventions")
    def status(sid: str, actor=Depends(auth)):
        return queue.status(sid)

    @app.post("/api/sessions/{sid}/interventions")
    def post(sid: str, body: dict, actor=Depends(auth)):
        live(sid)
        try:
            row = queue.post(sid, body.get("op"), body.get("request_id"), str(actor), body.get('args'))
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return {"request": row}

    @app.post("/api/sessions/{sid}/interventions/claim")
    def claim(sid: str, body: dict, actor=Depends(auth)):
        live(sid)
        epoch, caps = body.get("epoch"), body.get("capabilities")
        if not isinstance(epoch, str) or len(epoch) > 256 or not isinstance(caps, list) or any(c not in OPERATIONS for c in caps):
            raise HTTPException(422, "invalid worker capability report")
        options = body.get('options') or {}
        weapons = options.get('weapons', []) if isinstance(options, dict) else None
        if not isinstance(weapons, list) or len(weapons) > 64 or any(not isinstance(w, dict) or
                type(w.get('item')) is not int or not 1 <= w['item'] <= 255 or
                not isinstance(w.get('weapon'), str) or len(w['weapon']) > 80 for w in weapons):
            raise HTTPException(422, 'invalid weapon choices')
        options = {'weapons': weapons} if weapons else {}
        reason = str(body.get("reason") or "")[:300]
        return {"requests": queue.claim(sid, epoch, caps, reason, options)}

    @app.post("/api/sessions/{sid}/interventions/{rid}/result")
    def finish(sid: str, rid: str, body: dict, actor=Depends(auth)):
        try:
            return {"request": queue.finish(sid, rid, body.get("claim"), body.get("result") or {})}
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/sessions/{sid}/interventions/results")
    def finish_many(sid: str, body: dict, actor=Depends(auth)):
        try:
            return {"requests":queue.finish_many(sid, body.get("results"))}
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise HTTPException(409, str(e)) from None


def native_controller(ad):
    """One serialized native controller per adapter, shared by UI and MCP."""
    from .titles import re5_switch_native, re6_switch_native
    reasons = []
    for module, attribute in ((re6_switch_native, "_re6_native_flash"),
                              (re5_switch_native, "_re5_native_flash")):
        try:
            with module._CREATE_LOCK:
                ctl = getattr(ad, attribute, None)
                if ctl is None:
                    ctl = module.Controller(ad)
                    setattr(ad, attribute, ctl)
                return ctl
        except (OSError, ValueError, RuntimeError, AttributeError) as exc:
            reasons.append(str(exc))
    raise re6_switch_native.Unavailable("; ".join(dict.fromkeys(reasons)))


def worker_loop(sid, server, headers, ad, stats_of, alive):
    """Independent of video/input/UI requests; serialized native mailbox owner."""
    import httpx
    from .titles import re6_switch_native as N
    ctl, unsupported = None, ""
    try:
        ctl = native_controller(ad)
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        unsupported = str(exc)

    def context():
        if ctl is None:
            return {"epoch": "unsupported", "capabilities": [], "reason": unsupported}
        try:
            prepare = getattr(ctl, "prepare", None)
            if prepare is not None:
                prepare()
            p, generation = ctl.ready()
            stats = stats_of() or {}
            epoch = f"{ctl.pid}:{ctl.identity[1]}:{p}:{generation}:{stats.get('round_evidence_id', '')}"
            choices = getattr(ctl, 'weapon_choices', None)
            return {"epoch": epoch, "capabilities": ["flash_now"] + (["equip_primary"] if choices else []),
                    "options": {"weapons": choices()} if choices else {}, "reason": ""}
        except (OSError, ValueError, RuntimeError) as exc:
            return {"epoch": "unavailable", "capabilities": [], "reason": str(exc)[:300]}

    # Keep completion receipts across transient HTTP failures, never game calls.
    receipts = []
    with httpx.Client(base_url=server, headers=headers, timeout=2) as client:
        def flush():
            if receipts:
                response = client.post(f"/api/sessions/{sid}/interventions/results",
                    json={"results":[{"id":rid, **payload} for rid,payload in receipts]})
                if response.status_code == 200:
                    receipts.clear()
        while alive():
            try:
                flush()
                if len(receipts) >= MAX_PENDING - 20:
                    time.sleep(.05)
                    continue
                ctx = context()
                response = client.post(f"/api/sessions/{sid}/interventions/claim", json=ctx)
                if response.status_code == 200:
                    for row in response.json().get("requests", []):
                        if not alive() or row["expires"] <= time.time() or row["epoch"] != context()["epoch"]:
                            result = {"state": "unavailable", "reason": "player changed or request expired"}
                        else:
                            try:
                                stats = stats_of()
                                if row['op'] == 'equip_primary':
                                    from . import primary_weapon
                                    player, generation = ctl.ready()
                                    pending = {'id': row['id'], 'player': player, 'generation': generation,
                                               'until': time.monotonic() + 3.0}
                                    if stats is None:
                                        raise N.Unavailable('autoplay state is unavailable')
                                    stats['native_weapon_pending'] = pending
                                    round_id = stats.get('round_evidence_id')
                                    def allowed():
                                        return (alive() and not stats.get('operator_control') and
                                                stats.get('round_evidence_id') == round_id and
                                                row['expires'] > time.time() and
                                                time.monotonic() < pending['until'])
                                    try:
                                        # The engine acknowledges after sending its key releases. A fixed
                                        # delay can expire during an existing tap/prompt or a slow snapshot.
                                        release_deadline = time.monotonic() + .9
                                        while not pending.get('released') and time.monotonic() < release_deadline:
                                            if not alive() or stats.get('operator_control'):
                                                break
                                            time.sleep(.01)
                                        if not pending.get('released'):
                                            raise N.Unavailable('bot did not release its inputs for the weapon change')
                                        if not alive() or row['epoch'] != context()['epoch'] or \
                                                stats.get('operator_control') or row['expires'] <= time.time():
                                            raise N.Unavailable('player changed, operator took control, or request expired')
                                        result = ctl.equip_primary(row['args']['item'], expected=(player, generation), allowed=allowed)
                                        primary_weapon.install(ad, result, ctl.pid)
                                    finally:
                                        if stats.get('native_weapon_pending') is pending:
                                            stats.pop('native_weapon_pending', None)
                                else:
                                    result = ctl.flash()
                                    if stats is not None:
                                        stats["emergency_flashes"] = stats.get("emergency_flashes", 0) + 1
                                        stats["native_flash_confirmed_at"] = time.time()
                            except Exception as exc:  # a failure does not end worker health or retry the game effect
                                result = {"state": "uncertain" if isinstance(exc, N.Uncertain) else "failed", "reason": str(exc)[:300]}
                        receipts.append((row["id"], {"claim": row["claim"], "result": result}))
                flush()
            except (httpx.HTTPError, ValueError, OSError):
                pass
            time.sleep(.05 if ctl else 1.0)
