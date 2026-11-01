"""Durable, per-click live actions shared by stream UI and MCP.

Claim before any game write. An uncertain/lost claim is never replayed, including
after worker/server reload. Requests are fenced to the reported player life and
expire rather than affecting a later round. No latest-value command coalescing.
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
import weakref
from contextlib import contextmanager

KIND = "merc_interventions"
MAX_PENDING, KEEP, TTL, FRESH = 64, 128, 10.0, 3.0
TERMINAL = {"confirmed", "failed", "unavailable", "expired", "uncertain"}
OPERATIONS = {"flash_now", "equip_primary", "magnum_quick4", "grenade_ring", "set_infinite_ammo"}
# The grenade-ring button's selectable types. "flash" is the default and the only one verified; the others
# are refused by the native controller with a reason (never silently substituted). A longer TTL covers the
# ten spawn/explode pairs the ring runs (each is the verified flash).
GRENADE_RING_KINDS = ("flash", "hand", "incendiary")
GRENADE_RING_TTL = 25.0

_WAKE_LOCK = threading.Lock()
_WAITERS = weakref.WeakValueDictionary()


@contextmanager
def wake_on_post(sid):
    """Local serve/worker dispatch wakes on commit; remote workers retain polling."""
    event = threading.Event()
    key = sid, id(event)
    with _WAKE_LOCK:
        _WAITERS[key] = event
    try:
        yield event
    finally:
        with _WAKE_LOCK:
            _WAITERS.pop(key, None)


def wake(sid):
    with _WAKE_LOCK:
        for (session, _), event in list(_WAITERS.items()):
            if session == sid:
                event.set()


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
                    ttl = GRENADE_RING_TTL if r["op"] == "grenade_ring" else TTL
                    if r["state"] == "queued" and r["expires"] <= now:
                        r.update(state="expired", reason="request expired before execution")
                        self._remember(sid, r)
                    if r["state"] == "claimed" and r["claimed_at"] + ttl <= now:
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
        if op == 'set_infinite_ammo':
            if not isinstance(args, dict) or set(args) != {'enabled'} or type(args['enabled']) is not bool:
                raise ValueError('infinite ammo needs an explicit boolean enabled value')
        elif op == 'grenade_ring':
            args = dict(args)
            kind = args.setdefault('kind', 'flash')
            if set(args) != {'kind'} or kind not in GRENADE_RING_KINDS:
                raise ValueError('invalid grenade ring arguments')
        elif not isinstance(args, dict) or (op in ('flash_now', 'magnum_quick4') and args) or (op == 'equip_primary' and
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
            if op == 'equip_primary':
                offered = next((w for w in d.get('options', {}).get('weapons', []) if w['item'] == args['item']), None)
                if offered is None:
                    raise ValueError('weapon is not offered by this session')
                if offered.get('available') is False:
                    raise ValueError(str(offered.get('reason') or 'weapon is unavailable for this session')[:300])
            if op == 'set_infinite_ammo' and d.get('options', {}).get('infinite_ammo', {}).get('available') is not True:
                raise ValueError('infinite ammo is unavailable for this session')
            kinds = d.get('options', {}).get('grenade_kinds')
            if op == 'grenade_ring' and kinds is not None and not any(
                    k['kind'] == args['kind'] and k['available'] is True for k in kinds):
                raise ValueError('this grenade kind is unavailable for this session')
            if sum(r["state"] in ("queued", "claimed") for r in d["rows"]) >= MAX_PENDING:
                raise ValueError("intervention queue is full")
            ttl = GRENADE_RING_TTL if op == "grenade_ring" else TTL
            row = {"id": request_id, "op": op, "args": dict(args), "source": source, "at": now, "expires": now + ttl,
                   "epoch": d["epoch"], "state": "queued"}
            d["rows"].append(row)
            self.store.db.execute("INSERT INTO docs VALUES(?,?,?)",
                (KIND + "_id", sid + ":" + request_id, json.dumps(row)))
            while len(d["rows"]) > KEEP:
                i = next(i for i,r in enumerate(d["rows"]) if r["state"] in TERMINAL)
                d["rows"].pop(i)
            return dict(row)
        row = self._change(sid, add)
        if row['state'] == 'queued':
            wake(sid)  # after commit: no lost notification before the row is visible
        return row

    def claim(self, sid, epoch, capabilities, reason="", options=None):
        options = options or {}
        def take(d, now):
            if epoch != d["epoch"] or capabilities != d["capabilities"] or options != d.get('options', {}) or now - d.get("seen", 0) >= 1:
                d.update(epoch=epoch, capabilities=capabilities, seen=now, reason=reason, options=options)
            out = []
            # Flashes precede queued equipment work. Claim at most one ordinary
            # operation so a batch of weapon changes cannot hide new flash taps.
            ordinary = 0
            for r in sorted(d["rows"], key=lambda r: r['op'] != 'flash_now'):
                if r["state"] != "queued":
                    continue
                if r["epoch"] != epoch or r["op"] not in capabilities:
                    r.update(state="expired", reason="active player or capability changed")
                    self._remember(sid, r)
                    continue
                if len(out) < 20 and (r['op'] == 'flash_now' or not ordinary):
                    r.update(state="claimed", claim=uuid.uuid4().hex, claimed_at=now)
                    self._remember(sid, r)
                    out.append(dict(r))
                    ordinary += r['op'] != 'flash_now'
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
                if (r['op'] == 'magnum_quick4' and result.get('state') == 'confirmed' and
                        any(type(result.get(k)) is not int or result[k] != 4
                            for k in ('requested', 'completed', 'presses'))):
                    raise ValueError('magnum confirmation requires exactly four verified quick shots')
                if r['op'] == 'set_infinite_ammo' and result.get('state') == 'confirmed' and \
                        result.get('enabled') is not r['args']['enabled']:
                    raise ValueError('infinite ammo confirmation needs the requested readback value')
                if r['op'] == 'equip_primary' and result.get('state') == 'confirmed' and \
                        result.get('item') != r['args']['item']:
                    raise ValueError('weapon confirmation does not match the requested weapon')
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
                not isinstance(w.get('weapon'), str) or len(w['weapon']) > 80 or
                'available' in w and type(w['available']) is not bool for w in weapons):
            raise HTTPException(422, 'invalid weapon choices')
        current = options.get('current_weapon')
        if current is not None and (type(current) is not int or not 1 <= current <= 255):
            raise HTTPException(422, 'invalid current weapon')
        ammo = options.get('infinite_ammo')
        primary = options.get('primary_weapon')
        kinds = options.get('grenade_kinds')
        options = {'weapons': weapons, 'current_weapon': current}
        if kinds is not None:
            if (not isinstance(kinds, list) or len(kinds) > len(GRENADE_RING_KINDS) or any(
                    not isinstance(k, dict) or k.get('kind') not in GRENADE_RING_KINDS or
                    type(k.get('available')) is not bool for k in kinds)
                    or len({k['kind'] for k in kinds}) != len(kinds)):
                raise HTTPException(422, 'invalid grenade kind status')
            options['grenade_kinds'] = [{'kind': k['kind'], 'available': k['available'],
                'reason': str(k.get('reason') or '')[:300]} for k in kinds]
        if ammo is not None:
            if (not isinstance(ammo, dict) or type(ammo.get('available')) is not bool
                    or ammo.get('enabled') is not None and type(ammo.get('enabled')) is not bool
                    or ammo.get('available') is True and type(ammo.get('enabled')) is not bool):
                raise HTTPException(422, 'invalid infinite ammo status')
            options['infinite_ammo'] = {k: ammo[k] for k in ('available', 'enabled') if k in ammo}
            options['infinite_ammo']['reason'] = str(ammo.get('reason') or '')[:300]
        if primary is not None:
            if (not isinstance(primary, dict) or type(primary.get('item')) is not int
                    or not 1 <= primary['item'] <= 255 or not isinstance(primary.get('weapon'), str)
                    or len(primary['weapon']) > 80 or type(primary.get('locked')) is not bool
                    or type(primary.get('lock_remaining_s')) not in (int, float)
                    or not math.isfinite(primary['lock_remaining_s']) or not 0 <= primary['lock_remaining_s'] <= 180):
                raise HTTPException(422, 'invalid weapon hold status')
            options['primary_weapon'] = {k: primary[k] for k in ('item', 'weapon', 'locked', 'lock_remaining_s')}
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
    from .titles import re5_switch_native, re6_switch_native, re4_gc_native
    reasons = []
    for module, attribute in ((re4_gc_native, "_re4_native_controls"),
                              (re6_switch_native, "_re6_native_flash"),
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
    with wake_on_post(sid) as event:
        _worker_loop(sid, server, headers, ad, stats_of, alive, event)


def _worker_loop(sid, server, headers, ad, stats_of, alive, event):
    import httpx
    from .titles import re6_switch_native as N, re6_magnum_quick4 as Q
    ctl, unsupported = None, ""
    try:
        ctl = native_controller(ad)
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        unsupported = str(exc)

    catalogue = {}

    def context(full=True):
        if ctl is None:
            return {"epoch": "unsupported", "capabilities": [], "reason": unsupported}
        try:
            prepare = getattr(ctl, "prepare", None)
            if full and prepare is not None:
                prepare()
            p, generation = ctl.ready()
            stats = stats_of() or {}
            epoch = f"{ctl.pid}:{ctl.identity[1]}:{p}:{generation}:{stats.get('round_evidence_id', '')}"
            if not full:
                return {'epoch': epoch}
            choices = getattr(ctl, 'weapon_choices', None)
            caps = ["flash_now"] + (["equip_primary"] if choices else [])
            if getattr(ctl, 'grenade_ring', None) is not None:
                caps.append("grenade_ring")
            if Q.available(ctl) and not stats.get('operator_control'):
                caps.append(Q.OP)
            current = getattr(ctl, 'current_weapon', None)
            ammo_status = getattr(ctl, 'ammo_status', None)
            grenade_kinds = getattr(ctl, 'grenade_kinds', None)
            if catalogue.get('epoch') != epoch or time.monotonic() - catalogue.get('at', 0) >= 1:
                catalogue.update(epoch=epoch, at=time.monotonic(),
                    options={'weapons': choices() if choices else [],
                             'current_weapon': current() if current else None})
                if grenade_kinds:
                    catalogue['options']['grenade_kinds'] = grenade_kinds()
                if ammo_status:
                    try:
                        catalogue['options']['infinite_ammo'] = ammo_status()
                    except (OSError, ValueError, RuntimeError) as exc:
                        catalogue['options']['infinite_ammo'] = {'available': False, 'enabled': None, 'reason': str(exc)[:300]}
                from . import primary_weapon
                primary = primary_weapon.snapshot(ad, {'mercenaries_phase': 1,
                    'player': {'ptr': p, 'generation': generation}}, pid=ctl.pid)
                if primary:
                    catalogue['options']['primary_weapon'] = primary
            if catalogue['options'].get('infinite_ammo', {}).get('available') is True:
                caps.append('set_infinite_ammo')
            return {"epoch": epoch, "capabilities": caps,
                    "options": catalogue['options'], "reason": ""}
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
            event.clear()  # before claim: a concurrent post is either read or wakes this iteration
            had_requests = False
            try:
                flush()
                if len(receipts) >= MAX_PENDING - 20:
                    time.sleep(.05)
                    continue
                ctx = context()
                response = client.post(f"/api/sessions/{sid}/interventions/claim", json=ctx)
                if response.status_code == 200:
                    rows = response.json().get("requests", [])
                    had_requests = bool(rows)
                    for row in rows:
                        if not alive() or row["expires"] <= time.time() or row["epoch"] != context(full=False)["epoch"]:
                            result = {"state": "unavailable", "reason": "player changed or request expired"}
                        else:
                            try:
                                stats = stats_of()
                                if row['op'] in ('equip_primary', Q.OP):
                                    from . import primary_weapon
                                    player, generation = ctl.ready()
                                    pending = {'id': row['id'], 'player': player, 'generation': generation,
                                               'until': time.monotonic() + (9.0 if row['op'] == Q.OP else 3.0)}
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
                                        if not alive() or row['epoch'] != context(full=False)['epoch'] or \
                                                stats.get('operator_control') or row['expires'] <= time.time():
                                            raise N.Unavailable('player changed, operator took control, or request expired')
                                        if row['op'] == Q.OP:
                                            result = Q.execute(ctl, expected=(player, generation), allowed=allowed)
                                        else:
                                            result = ctl.equip_primary(row['args']['item'], expected=(player, generation), allowed=allowed)
                                            primary_weapon.install(ad, result, ctl.pid)
                                    finally:
                                        if stats.get('native_weapon_pending') is pending:
                                            stats.pop('native_weapon_pending', None)
                                elif row['op'] == 'set_infinite_ammo':
                                    expected = ctl.ready()
                                    def allowed_ammo():
                                        return alive() and row['expires'] > time.time() and \
                                            row['epoch'] == context(full=False)['epoch']
                                    result = ctl.set_infinite_ammo(row['args']['enabled'], expected=expected, allowed=allowed_ammo)
                                    catalogue.clear()  # next published status must be read after this write
                                elif row['op'] == 'grenade_ring':
                                    result = ctl.grenade_ring(row['args'].get('kind', 'flash'))
                                    if stats is not None and result.get('state') == 'confirmed':
                                        stats["grenade_rings"] = stats.get("grenade_rings", 0) + 1
                                        stats["native_flash_confirmed_at"] = time.time()
                                else:
                                    result = ctl.flash()
                                    if stats is not None:
                                        stats["emergency_flashes"] = stats.get("emergency_flashes", 0) + 1
                                        stats["native_flash_confirmed_at"] = time.time()
                            except Exception as exc:  # a failure does not end worker health or retry the game effect
                                result = {"state": "uncertain" if isinstance(exc, N.Uncertain) else "failed", "reason": str(exc)[:300]}
                                if row['op'] == Q.OP:
                                    result.update(op=Q.OP, requested=4, completed=0, presses=0, verified=False)
                        receipts.append((row["id"], {"claim": row["claim"], "result": result}))
                flush()
            except (httpx.HTTPError, ValueError, OSError):
                pass
            if not had_requests:
                event.wait(.05 if ctl else 1.0)
