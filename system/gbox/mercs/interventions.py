"""Durable, per-click live actions shared by stream UI and MCP.

Claim before any game write. An uncertain/lost claim is never replayed, including
after worker/server reload. Requests are fenced to the reported player life and
expire rather than affecting a later round. No latest-value command coalescing.
"""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import threading
import time
import uuid
import weakref
from contextlib import contextmanager

KIND = "merc_interventions"
MAX_PENDING, KEEP, TTL, FRESH = 64, 128, 10.0, 3.0
TERMINAL = {"confirmed", "failed", "unavailable", "expired", "uncertain"}
OPERATIONS = {"flash_now", "equip_primary", "magnum_quick4", "grenade_ring", "grenade_scatter",
              "re4_harness_selftest", "set_infinite_ammo", "remote_mines", "first_aid_now",
              "proximity_mine_drop", "proximity_mine_ring", "detonate_mines", "re6_shell_probe"}
# The grenade-ring button's selectable types. "flash" is the default and the only one verified; the others
# are refused by the native controller with a reason (never silently substituted). A longer TTL covers the
# ten spawn/explode pairs the ring runs (each is the verified flash).
# The grenade-ring button's selectable types, cross-title: the flash / hand / incendiary grenades, the launcher's own
# rounds (RE6's shells; RE5/RE4 fire their grenades) and RE4's mine thrower (a probe). A title refuses the ones it does
# not build with its own reason - never a silent substitution.
GRENADE_RING_KINDS = ("flash", "hand", "incendiary", "launcher", "shell1302", "shell1303", "shell1304", "mine")
# The scatter barrage (RE6 Switch, 2026-11-10): a random kind a round ("random", the default) or one named; the native
# controller refuses an unverified one with its reason. Its TTL is the ring's.
GRENADE_SCATTER_KINDS = ("random",) + GRENADE_RING_KINDS
TIMED_OPS = ("grenade_ring", "grenade_scatter", "remote_mines", "proximity_mine_drop", "proximity_mine_ring")
GRENADE_RING_TTL = 25.0
RECEIPT_LIMIT = 4096
RECEIPT_ROOT = Path(__file__).resolve().parents[2] / 'gbox-data' / 'mercs' / 'native-intervention-receipts'

_WAKE_LOCK = threading.Lock()
_WAITERS = weakref.WeakValueDictionary()


def shell_probe_args(args, source):
    """Research-only, one named shell at one point; no pointers/counts/code input."""
    if source not in ('agent', 'gbox-agent', 'mcp', 'probe'):
        raise ValueError('shell probe is an agent research operation')
    if not isinstance(args, dict) or set(args) != {'kind', 'point', 'allow_unverified'} or \
            args.get('allow_unverified') is not True or args.get('kind') not in ('shell1302', 'shell1303', 'shell1304'):
        raise ValueError('shell probe needs one shell kind and explicit allow_unverified=true')
    point = args['point']
    try:
        valid = isinstance(point, (list, tuple)) and len(point) == 3 and all(
            type(v) in (float, int) and math.isfinite(float(v)) for v in point)
    except (OverflowError, ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('shell probe needs three finite world coordinates')
    return {**args, 'point': [float(v) for v in point]}


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
                    ttl = GRENADE_RING_TTL if r["op"] in TIMED_OPS else TTL
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
        if op == 're6_shell_probe':
            args = shell_probe_args(args, source)
        elif op == 'set_infinite_ammo':
            if not isinstance(args, dict) or set(args) != {'enabled'} or type(args['enabled']) is not bool:
                raise ValueError('infinite ammo needs an explicit boolean enabled value')
        elif op in ('proximity_mine_drop', 'proximity_mine_ring'):
            if not isinstance(args, dict) or set(args) - {'allow_unverified', 'count'} or (
                    'allow_unverified' in args and type(args['allow_unverified']) is not bool):
                raise ValueError('invalid proximity mine arguments')
            if 'count' in args and (type(args['count']) is not int or args['count'] not in (1, 5, 8)
                                   or op == 'proximity_mine_drop' and args['count'] != 1):
                raise ValueError('invalid proximity mine count')
        elif op == 'grenade_ring':
            args = dict(args)
            kind = args.setdefault('kind', 'flash')
            if set(args) - {'kind', 'allow_unverified'} or kind not in GRENADE_RING_KINDS:
                raise ValueError('invalid grenade ring arguments')
            if 'allow_unverified' in args and type(args['allow_unverified']) is not bool:
                raise ValueError('allow_unverified must be a boolean')
        elif op == 'grenade_scatter':
            args = dict(args)
            kind = args.setdefault('kind', 'random')
            if set(args) != {'kind'} or kind not in GRENADE_SCATTER_KINDS:
                raise ValueError('invalid grenade scatter arguments')
        elif not isinstance(args, dict) or (op in ('flash_now', 'magnum_quick4', 'first_aid_now', 'detonate_mines') and args) or (op == 'equip_primary' and
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
            if op in ('proximity_mine_drop', 'proximity_mine_ring') and args.get('allow_unverified') is not True \
                    and d.get('options', {}).get('proximity_mines', {}).get('available') is not True:
                raise ValueError('native proximity-mine placement is unavailable for this session')
            # allow_unverified is the research probe's path (a kind whose first live receipt is being taken): it is
            # never sent by the PiP, and without it a refused kind stays refused. The queue still needs the title's
            # capability and a live worker.
            if op == 'grenade_ring' and kinds is not None and args.get('allow_unverified') is not True \
                    and not any(k['kind'] == args['kind'] and k['available'] is True for k in kinds):
                raise ValueError('this grenade kind is unavailable for this session')
            if sum(r["state"] in ("queued", "claimed") for r in d["rows"]) >= MAX_PENDING:
                raise ValueError("intervention queue is full")
            ttl = GRENADE_RING_TTL if op in TIMED_OPS else TTL
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
            if len(json.dumps(result)) > RECEIPT_LIMIT:
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
    from . import grenade_status
    queue = Queue(store)

    def live(sid):
        s = store.get("session", sid)
        if not s or s.get("state") != "running":
            raise HTTPException(409, "session is not running")

    def present(sid, out):
        """The status a viewer sees, with the grenade kinds named even before a worker claims.

        A title with no ring, or one whose worker has not connected yet, must still say what it can do per kind
        ("the grenade ring is not built for RE4 Switch yet") instead of leaving the PiP's chooser with only a
        generic "worker not connected". Read-only: nothing is stored, the worker's own rows always win.
        """
        if (out.get('options') or {}).get('grenade_kinds'):
            return out
        try:
            rows = grenade_status.rows(store.get('session', sid) or {}, None)
        except Exception:                                 # noqa: BLE001 - a status page never fails on the table
            rows = None
        if rows:
            options = dict(out.get('options') or {})
            options.setdefault('weapons', [])
            options.setdefault('current_weapon', None)
            options['grenade_kinds'] = rows
            out['options'] = options
        return out

    @app.get("/api/sessions/{sid}/interventions")
    def status(sid: str, actor=Depends(auth)):
        return present(sid, queue.status(sid))

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
        mines = options.get('proximity_mines')
        options = {'weapons': weapons, 'current_weapon': current}
        if mines is not None:
            if not isinstance(mines, dict) or type(mines.get('available')) is not bool \
                    or mines.get('radius_cm') != 152.4 or type(mines.get('count')) is not int or mines['count'] not in (5, 8):
                raise HTTPException(422, 'invalid proximity mine status')
            options['proximity_mines'] = {'available': mines['available'], 'radius_cm': 152.4, 'count': mines['count'],
                                          'reason': str(mines.get('reason') or '')[:300]}
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
    import importlib
    from .titles import re6_switch_native
    reasons = []
    for dotted, attribute in (("gbox.mercs.titles.re4_switch_native", "_re4_switch_harness"),
                              ("gbox.mercs.titles.re4_gc_native", "_re4_native_controls"),
                              ("gbox.mercs.titles.re6_switch_native", "_re6_native_flash"),
                              ("gbox.mercs.titles.re5_switch_native", "_re5_native_flash")):
        try:
            module = importlib.import_module(dotted)
            with module._CREATE_LOCK:
                ctl = getattr(ad, attribute, None)
                if ctl is None:
                    ctl = module.Controller(ad)
                    setattr(ad, attribute, ctl)
                return ctl
        except Exception as exc:                          # noqa: BLE001 - a module for another platform must be skipped
            # A module whose Controller rejects this adapter (re4_gc_native on an eden session raised a wrapped
            # ValueError from eden_memory: "Switch address 0x80000000 is outside the guest arena") must fall through to
            # the next module. The narrower tuple let that escape and killed the whole witness worker thread, which is
            # why no native round boundary was ever posted for RE5 Switch (2026-11-05). The import is inside the try as
            # well: a test double that replaces a base class must not stop the search for the title's own controller.
            reasons.append(f"{dotted.rsplit('.', 1)[-1]}: {exc}")
    raise re6_switch_native.Unavailable("; ".join(dict.fromkeys(reasons)))


def completion_receipt(result, *, session_id=None, request_id=None):
    """A returned native call is not proof that its in-game effect happened.

    Keep that evidence, but use the queue's uncertainty state. Otherwise one
    unverified ring rejects the whole completion batch, stranding later clicks.
    Receipt retries must never repeat the native action.
    """
    result = dict(result)
    if result.get('state') == 'confirmed' and result.get('verified') is not True:
        result.update(native_state='confirmed', state='uncertain', verified=False,
                      verification_reason='native call returned; in-game effect has not been verified')
    if len(json.dumps(result)) > RECEIPT_LIMIT:
        # A five-mine result includes both prepared and published actor details.
        # Rejecting that payload at /results stranded the entire pending batch.
        # Preserve the complete evidence locally and send a bounded summary;
        # retries repeat only delivery, never the native operation.
        from .follow_report_delivery import _write
        full = json.dumps(result, allow_nan=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(full.encode('utf-8')).hexdigest()
        record = {'schema': 'gbox.mercs.intervention-receipt/1', 'session_id': session_id,
                  'request_id': request_id, 'sha256': digest, 'result': result}
        key = hashlib.sha256(json.dumps([session_id, request_id, digest]).encode('utf-8')).hexdigest()
        summary = {k: result[k] for k in (
            'state', 'verified', 'native_state', 'op', 'kind', 'effect', 'requested', 'placed', 'armed',
            'triggered', 'detonated', 'completed', 'presses', 'item', 'enabled', 'consumed',
            'inventory_consumed', 'weapon_before', 'weapon_after', 'weapon_unchanged', 'player_generation',
            'hp_before', 'hp_after', 'self_damage', 'hp_loss_observed', 'flash_detonated',
            'elapsed_ms', 'placement_span_ms', 'radius_cm', 'probe')
            if k in result and (result[k] is None or type(result[k]) in (bool, int, float, str))}
        for k in ('reason', 'verification_reason', 'detach_error'):
            if k in result:
                summary[k] = str(result[k])[:300]
        for k in ('mines', 'prepared', 'grenades'):
            if isinstance(result.get(k), (list, tuple)):
                summary[k + '_records'] = len(result[k])
        summary.update(receipt_compacted=True, receipt_sha256=digest)
        try:
            _write(RECEIPT_ROOT / (key + '.json'), record)
            summary['receipt_archive'] = 'mercs/native-intervention-receipts/' + key + '.json'
        except (OSError, ValueError) as exc:
            summary['receipt_archive_error'] = f'{type(exc).__name__}: {exc}'[:240]
        # Native receipts use short names, but retain a fixed bound even if a
        # future backend puts a large string into a scalar evidence field.
        for k, v in list(summary.items()):
            if isinstance(v, str):
                summary[k] = v[:300]
        if len(json.dumps(summary)) > RECEIPT_LIMIT:
            summary = {k: summary[k] for k in ('state', 'verified', 'native_state', 'op', 'item', 'enabled',
                'requested', 'completed', 'presses', 'receipt_compacted', 'receipt_sha256', 'receipt_archive',
                'receipt_archive_error') if k in summary}
        return summary
    return result


def worker_loop(sid, server, headers, ad, stats_of, alive, game=None):
    """Independent of video/input/UI requests; serialized native mailbox owner."""
    with wake_on_post(sid) as event:
        _worker_loop(sid, server, headers, ad, stats_of, alive, event, game)


def _worker_loop(sid, server, headers, ad, stats_of, alive, event, game=None):
    import httpx
    from .titles import re6_switch_native as N, re6_magnum_quick4 as Q
    from . import grenade_status
    ctl, unsupported = None, ""
    try:
        ctl = native_controller(ad)
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        unsupported = str(exc)

    catalogue = {}

    def kinds(full=True, reason=""):
        """The three grenade kinds as this session can honestly fire them (see gbox.mercs.grenade_status).

        Published with every claim, including when no native controller exists, so the PiP's menu says "not built
        for this title" / "no living player" per kind instead of greying everything out with one reason."""
        try:
            return grenade_status.rows(game, ctl, reason)
        except Exception:                                 # noqa: BLE001 - a status read never breaks the worker
            return None

    def context(full=True):
        if ctl is None:
            out = {"epoch": "unsupported", "capabilities": [], "reason": unsupported}
            if full:
                rows = kinds(reason=unsupported)
                if rows:
                    out["options"] = {"weapons": [], "current_weapon": None, "grenade_kinds": rows}
            return out
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
            if getattr(ctl, "selftest", None) is not None:
                caps.append("re4_harness_selftest")
            if type(ctl) is N.Controller:
                # Agent-only research, deliberately absent from grenade-kind/UI choices.
                caps.append('re6_shell_probe')
            if getattr(ctl, "first_aid_now", None) is not None:
                caps.append("first_aid_now")
            if getattr(ctl, 'proximity_mines', None) is not None:
                caps.extend(('proximity_mine_drop', 'proximity_mine_ring'))
            if getattr(ctl, 'detonate_mines', None) is not None:
                caps.append('detonate_mines')
            if getattr(ctl, 'grenade_ring', None) is not None:
                caps.append("grenade_ring")
            if getattr(ctl, 'grenade_scatter', None) is not None:
                caps.append("grenade_scatter")
            if getattr(ctl, 'drop_bomb', None) is not None:
                # remote mines: a ring of four ejected from his body, and the detonator's own flag (no animation)
                caps.append("remote_mines")
            if Q.available(ctl) and not stats.get('operator_control'):
                caps.append(Q.OP)
            current = getattr(ctl, 'current_weapon', None)
            ammo_status = getattr(ctl, 'ammo_status', None)
            if catalogue.get('epoch') != epoch or time.monotonic() - catalogue.get('at', 0) >= 1:
                catalogue.update(epoch=epoch, at=time.monotonic(),
                    options={'weapons': choices() if choices else [],
                             'current_weapon': current() if current else None})
                rows = kinds()
                if rows:
                    catalogue['options']['grenade_kinds'] = rows
                if getattr(ctl, 'proximity_mine_status', None) is not None:
                    catalogue['options']['proximity_mines'] = ctl.proximity_mine_status()
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
        except Exception as exc:                          # noqa: BLE001 - a status read answers, never dies
            reason = str(exc)[:300]
            return {"epoch": "unavailable", "capabilities": [], "reason": reason,
                    **({'options': {'weapons': [], 'current_weapon': None, 'grenade_kinds': rows}}
                       if full and (rows := kinds(reason=reason)) else {})}

    # Keep completion receipts across transient HTTP failures, never game calls.
    receipts, faults = [], 0
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
                if response.status_code == 422:
                    # A report the control plane refuses (one bad option row) must not leave the status stale for the
                    # whole round: report the capability-free context with the refusal as its reason instead.
                    detail = str(response.json().get("detail") if response.headers.get(
                        "content-type", "").startswith("application/json") else response.text)[:200]
                    response = client.post(f"/api/sessions/{sid}/interventions/claim", json={
                        "epoch": "refused", "capabilities": [], "reason": f"worker report refused: {detail}"})
                if response.status_code == 200:
                    faults = 0
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
                                               'until': time.monotonic() + (9.0 if row['op'] == Q.OP or "re4_switch_native" in type(ctl).__module__ else 3.0)}
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
                                elif row['op'] == 'detonate_mines':
                                    result = ctl.detonate_mines()
                                elif row['op'] == 'set_infinite_ammo':
                                    expected = ctl.ready()
                                    def allowed_ammo():
                                        return alive() and row['expires'] > time.time() and \
                                            row['epoch'] == context(full=False)['epoch']
                                    result = ctl.set_infinite_ammo(row['args']['enabled'], expected=expected, allowed=allowed_ammo)
                                    catalogue.clear()  # next published status must be read after this write
                                elif row['op'] == 'grenade_ring' and row['args'].get('kind') == 'mine' \
                                        and 're4_switch_native' in type(ctl).__module__:
                                    # RE4's native harness cannot carry a ring on this build (it attaches, but the
                                    # dispatcher the clone redirects is never called - live selftest 2026-11-12: ticks 0).
                                    # The mine-thrower ring is the bot's own: hand the click to its next tick
                                    # (re4_switch.Bot._mine_ring_step reads the force marker) and receipt that truth.
                                    if stats is None:
                                        raise N.Unavailable('autoplay state is unavailable')
                                    stats['mine_ring_force'] = time.time()
                                    result = {'state': 'confirmed', 'verified': False, 'op': 'grenade_ring',
                                              'kind': 'mine', 'requested': 10, 'detonated': 0, 'scheduled': True,
                                              'reason': "queued to the bot's mine-thrower ring: it sweeps ten darts "
                                                        "round him (mine_ring_shots), not the native harness"}
                                elif row['op'] == 'grenade_ring':
                                    result = ctl.grenade_ring(row['args'].get('kind', 'flash'),
                                                              allow_unverified=row['args'].get('allow_unverified') is True)
                                    if stats is not None and result.get('state') == 'confirmed':
                                        # The same counters the bot's own rule keeps (gbox.mercs.grenade_ring):
                                        # a ring fired by a click is deployed like any other, and its kills are
                                        # attributed inside the same window by the engine's per-tick observer.
                                        stats["grenade_rings"] = stats.get("grenade_rings", 0) + 1
                                        stats["rings_deployed"] = stats.get("rings_deployed", 0) + 1
                                        kills = stats.get("kills")
                                        stats["ring_pending"] = {"at": time.time(),
                                                                 "kills": kills if isinstance(kills, int) else None}
                                        stats["native_flash_confirmed_at"] = time.time()
                                elif row['op'] == 'grenade_scatter':
                                    result = ctl.grenade_scatter(row['args'].get('kind', 'random'))
                                    if stats is not None:
                                        if result.get('state') == 'confirmed':
                                            stats["scatters_fired"] = stats.get("scatters_fired", 0) + 1
                                            stats["scatter_rounds"] = stats.get("scatter_rounds", 0) + int(
                                                result.get("detonated") or 0)
                                            # A click's flash is a flash too (checkpoint D1): the same one clock the
                                            # bot's own rules read, so his next automatic flash waits the minute.
                                            kinds = result.get('kinds')
                                            if isinstance(kinds, (list, tuple)) and \
                                                    'flash' in [str(k) for k in kinds]:
                                                stats["native_flash_confirmed_at"] = time.time()
                                            kills = stats.get("kills")
                                            stats["scatter_pending"] = {"at": time.time(),
                                                                        "kills": kills if isinstance(kills, int) else None}
                                        else:
                                            stats["scatter_failures"] = stats.get("scatter_failures", 0) + 1
                                elif row['op'] in ('proximity_mine_drop', 'proximity_mine_ring'):
                                    round_id = (stats or {}).get('round_evidence_id')
                                    def allowed_mines():
                                        return (alive() and row['expires'] > time.time() and
                                                row['epoch'] == context(full=False)['epoch'] and
                                                (stats or {}).get('round_evidence_id') == round_id)
                                    from .titles.re5_mine_escape import execute as mine_escape
                                    result = mine_escape(ctl,
                                        row['args'].get('count', 5 if row['op'] == 'proximity_mine_ring' else 1),
                                        ring=row['op'] == 'proximity_mine_ring',
                                        allow_unverified=row['args'].get('allow_unverified') is True,
                                        allowed=allowed_mines, stats=stats, request_id=row['id'], round_id=round_id)
                                elif row['op'] == 'first_aid_now':
                                    result = ctl.first_aid_now()
                                    if stats is not None and result.get('consumed'):
                                        stats['first_aid_used'] = stats.get('first_aid_used', 0) + 1
                                elif row['op'] == 're4_harness_selftest':
                                    result = ctl.selftest()
                                elif row['op'] == 're6_shell_probe':
                                    if type(ctl) is not N.Controller:
                                        raise N.Unavailable('shell probe requires the shared RE6 native controller')
                                    args = shell_probe_args(row['args'], row.get('source'))
                                    def probe_idle():
                                        return stats is not None and not any(stats.get(key) for key in (
                                            'operator_control', 'mine_bombs_since_detonate', 'mine_avoid_positions',
                                            'mine_ring_pending', 'mine_deadline_pending', 'mine_allocation_blocked_reason'))
                                    if not probe_idle():
                                        raise N.Unavailable('shell research waits for bot ownership and no pending remote bombs')
                                    from .titles.re6_switch_shell_probe import probe_one
                                    expected, round_id = ctl.ready(), stats.get('round_evidence_id')
                                    def allowed_probe():
                                        return (alive() and row['expires'] > time.time() and
                                                row['epoch'] == context(full=False)['epoch'] and
                                                stats.get('round_evidence_id') == round_id and
                                                probe_idle())
                                    result = probe_one(ctl, args['point'], kind=args['kind'],
                                                       expected=expected, allowed=allowed_probe)
                                elif row['op'] == 'remote_mines':
                                    args = row.get('args') or {}
                                    from .titles import re6_switch_native
                                    if str(args.get('action') or 'ring').lower() == 'detonate':
                                        result = re6_switch_native.bomb_detonate_now(ad, snap=None)
                                    else:
                                        result = re6_switch_native.bomb_ring_now(ad, count=args.get('count') or 4,
                                                                                 radius_cm=args.get('radius_cm') or 200.0)
                                    if stats is not None:
                                        if result.get('state') == 'confirmed':
                                            stats["mine_rings_dropped"] = stats.get("mine_rings_dropped", 0) + 1
                                            stats["mine_ring_bombs"] = stats.get("mine_ring_bombs", 0) + int(
                                                result.get("placed") or 0)
                                        elif result.get('op') == 'bomb_detonate' and result.get('verified'):
                                            stats["mine_flag_detonations"] = stats.get("mine_flag_detonations", 0) + 1
                                else:
                                    result = ctl.flash()
                                    if stats is not None:
                                        stats["emergency_flashes"] = stats.get("emergency_flashes", 0) + 1
                                        stats["native_flash_confirmed_at"] = time.time()
                            except Exception as exc:  # a failure does not end worker health or retry the game effect
                                result = {"state": "uncertain" if isinstance(exc, N.Uncertain) else "failed", "reason": str(exc)[:300]}
                                if row['op'] == Q.OP:
                                    result.update(op=Q.OP, requested=4, completed=0, presses=0, verified=False)
                        receipts.append((row["id"], {"claim": row["claim"], "result": completion_receipt(
                            result, session_id=sid, request_id=row['id'])}))
                flush()
            except Exception as exc:                      # noqa: BLE001 - the status loop outlives any one claim
                # A worker that dies here leaves the PiP saying "worker not connected" for the rest of the round,
                # so no single fault (a module's own exception type, a malformed claim, a torn read) ends the loop.
                # A fault that never clears is a defect, not a transient one: it surfaces instead of spinning.
                faults += 1
                if faults > 100:
                    raise
                time.sleep(min(.5, .02 * faults))
            if not had_requests:
                event.wait(.05 if ctl else 1.0)
