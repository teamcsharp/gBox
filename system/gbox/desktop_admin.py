"""Bounded administration of a paired Windows desktop, with no remote shell.

The per-user supervisor is the only relaunch executor. Its outbound channel is
independent of game workers; offering a command binds it to that supervisor
instance forever. A lost/ambiguous execution is never assigned to another one.
Rebuilds keep the existing tool, permissions, console and result receipts.
"""
from __future__ import annotations

import math
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .store import canon, sha256

LEASE_S = 30
COMMAND_S = 120
RETURN_S = 180
ACTIVE = {'queued', 'offered', 'requested', 'service_returned', 'rebuilding'}


class AdminRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    installation: str = Field(pattern=r'^[a-f0-9]{64}$')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    op: Literal['relaunch', 'rebuild']
    force: StrictBool = False
    enable_remote_admin: StrictBool = False


class AdminPoll(BaseModel):
    model_config = ConfigDict(extra='forbid')
    controller_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    epoch: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    worker_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{16,64}$')
    worker_state: Literal['running', 'unavailable'] = 'unavailable'


class AdminResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    controller_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    status: Literal['requested', 'failed', 'unknown']
    # Labels, not exception text, paths, command lines or credentials.
    detail: str = Field(default='', max_length=120, pattern=r'^[a-z0-9_ .-]*$')
    closed_sessions: list['ClosedSession'] = Field(default_factory=list, max_length=16)


class ClosedSession(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    session_id: str = Field(pattern=r'^[a-f0-9]{16,64}-[a-f0-9]{16,64}$')
    pid: int = Field(gt=0, strict=True)
    created: float = Field(gt=0, strict=True)


AdminResult.model_rebuild()


def identity(authority, rid):
    return authority + ':' + rid


def authorized_rebuild(store, job):
    """Only the exact admin-created job may bypass background scheduling.

    A client origin header alone never qualifies. Federated copies must have an
    existing durable bridge mapping to the same central command and input.
    """
    if job.get('tool') != 'rebuild_node' or (job.get('input') or {}).get('force') is not True:
        return False
    origin = job.get('origin') or {}
    stamp = origin.get('desktop_admin')
    if not isinstance(stamp, dict) or stamp.get('worker_id') != job.get('require_worker'):
        return False
    row = store.get('desktop_admin', str(stamp.get('key')))
    if row and row.get('job_id') == job.get('id') and row.get('op') == 'rebuild' \
            and row.get('worker_id') == job.get('require_worker') and row.get('actor') == job.get('actor'):
        return sha256(canon(job.get('input'))) == row.get('job_input_sha256')
    key = origin.get('desktop_federation_key')
    mapping = store.get('desktop_bridge_job', key) if isinstance(key, str) else None
    return bool(mapping and mapping.get('local_job_id') == job.get('id')
                and mapping.get('authority') == stamp.get('authority')
                and mapping.get('authority') == origin.get('desktop_federation_authority')
                and mapping.get('id') == stamp.get('job_id')
                and mapping.get('tool') == 'rebuild_node'
                and (origin.get('central_origin') or {}).get('desktop_admin') == stamp
                and mapping.get('execution_input_sha256') == sha256(canon(job.get('input'))))


class AdminQueue:
    def __init__(self, fed, *, submit=None):
        self.fed, self.store, self.submit = fed, fed.store, submit

    def _rows(self, authority):
        return [row for row in self.store.all('desktop_admin') if row['authority'] == authority]

    def _worker(self, wid, authority):
        worker = self.store.get('worker', wid)
        owner = self.store.get('federation', authority)
        if not worker or worker.get('os') != 'windows' or not owner \
                or owner.get('worker_id') != wid or (worker.get('federation') or {}).get('authority') != authority:
            raise HTTPException(409, 'The exact paired Windows installation and current worker are required')
        return worker, owner

    def request(self, wid, body, actor):
        key = identity(body.installation, body.request_id)
        digest = sha256(canon({'worker_id': wid, **body.model_dump()}))
        with self.store.lock:
            saved = self.store.get('desktop_admin', key)
            if saved:
                if saved['request_sha256'] != digest or saved['actor'] != actor:
                    raise HTTPException(409, 'An admin request identity cannot change target, actor or operation')
                return self.status(wid, body.installation, body.request_id)
            worker, owner = self._worker(wid, body.installation)
            if body.force is not True:
                raise HTTPException(409, 'Remote administration requires explicit force for this exact PC')
            if body.op != 'rebuild' and body.enable_remote_admin:
                raise HTTPException(422, 'Supervisor installation is available only through a verified rebuild')
            now = self.fed.clock()
            # Never overlap a second recovery with an outstanding one.
            for previous in self._rows(body.installation):
                if previous['state'] in ACTIVE:
                    previous = self.status(previous['worker_id'], body.installation, previous['id'])
                    if previous['state'] in ACTIVE:
                        raise HTTPException(409, 'This installation already has an outstanding admin request')
            health = self.store.get('desktop_admin_health', body.installation) or {}
            if body.op == 'relaunch' and now - health.get('last_seen', 0) > LEASE_S:
                raise HTTPException(409, 'No live recovery supervisor; an explicit rebuild must install it first')
            if body.op == 'relaunch' and health.get('worker_id') not in (None, wid):
                raise HTTPException(409, 'The local worker changed; wait for its current paired snapshot')
            if body.op == 'rebuild' and (now - worker.get('last_seen', 0) > LEASE_S
                                          or 'rebuild_node' not in worker.get('tools', ())):
                raise HTTPException(409, 'A rebuild requires a live worker with rebuild_node')
            row = {'id': body.request_id, 'authority': body.installation, 'worker_id': wid,
                   'actor': actor, 'op': body.op, 'force': True, 'created': now,
                   'expires_at': now + COMMAND_S, 'state': 'queued', 'request_sha256': digest,
                   'epoch': health.get('epoch', owner.get('epoch')),
                   'controller_id': health.get('controller_id'), 'enable_remote_admin': body.enable_remote_admin}
            row['sessions'] = [{'session_id': session['session_id'], 'pid': session['detail']['pid'],
                                'created': session['detail']['process_created']}
                               for session in self.store.running_sessions()
                               if session['session_id'].startswith(wid+'-')
                               and type((session.get('detail') or {}).get('pid')) is int
                               and session['detail']['pid'] > 0
                               and type(session['detail'].get('process_created')) in (int,float)
                               and math.isfinite(session['detail']['process_created'])
                               and session['detail']['process_created'] > 0]
            if len(row['sessions']) > 16:
                raise HTTPException(409, 'Recovery supports at most sixteen verified native sessions on one PC')
            self.store.put('desktop_admin', key, row)
            self.store.audit(actor, 'desktop.admin.request', wid,
                             {'request_id': body.request_id, 'installation': body.installation,
                              'op': body.op, 'force': True, 'enable_remote_admin': body.enable_remote_admin})
            if body.op == 'rebuild':
                # Reserve before submit: an interrupted submission is unknown,
                # never an automatic second package update/restart.
                row['state'] = 'unknown'
                self.store.put('desktop_admin', key, row)
                try:
                    job = self.submit(wid, body.enable_remote_admin, actor,
                                      {'key': key, 'authority': body.installation, 'worker_id': wid})
                    if hasattr(job, 'model_dump'):
                        job = job.model_dump(mode='json')
                    row.update(state='failed' if job['state'] == 'rejected' else 'rebuilding',
                               job_id=job['id'], job_input_sha256=sha256(canon(job['input'])))
                    # The central job identity is sent through the bridge as
                    # part of the server-owned admin provenance.
                    job['origin']['desktop_admin']['job_id'] = job['id']
                    self.store.put('job', job['id'], job)
                    self.store.put('desktop_admin', key, row)
                except Exception:
                    self.store.put('desktop_admin', key, row | {'detail': 'rebuild_submission_unknown'})
                    raise
            return self.public(row)

    @staticmethod
    def public(row):
        return {k: v for k, v in row.items() if k not in ('request_sha256', 'job_input_sha256')}

    def status(self, wid, authority, rid):
        with self.store.lock:
            return self.public(self._status(wid, authority, rid))

    def _status(self, wid, authority, rid):
        key = identity(authority, rid)
        row = self.store.get('desktop_admin', key)
        if not row or row['worker_id'] != wid:
            raise HTTPException(404, 'No admin request for this exact PC')
        now = self.fed.clock()
        if row['state'] == 'queued' and now >= row['expires_at']:
            row = row | {'state': 'expired', 'detail': 'not_delivered_before_expiry'}
        if row['state'] == 'offered' and now >= row['expires_at']:
            row = row | {'state': 'unknown', 'detail': 'delivery_outcome_unknown'}
        if row['state'] == 'rebuilding':
            job = self.store.get('job', row['job_id']) or {}
            if job.get('state') in ('failed', 'invalid', 'rejected'):
                row = row | {'state': 'failed', 'detail': 'rebuild_job_failed'}
            elif job.get('state') == 'succeeded':
                output = job.get('output') or {}
                row = row | {'state': 'requested' if output.get('restart') == 'scheduled' else 'failed',
                             'detail': 'rebuild_' + str(output.get('restart', 'unknown')), 'reported_at': now}
        if row['state'] in ('requested', 'service_returned') and now - row.get('reported_at', now) > RETURN_S:
            row = row | {'state': 'unknown', 'detail': 'worker_return_not_confirmed'}
        self.store.put('desktop_admin', key, row)
        return row

    def poll(self, authority, secret, body):
        # Paired ownership is required; a fresh game worker is deliberately not.
        owner = self.fed.owner(authority, secret)
        now = self.fed.clock()
        with self.store.lock:
            prior = self.store.get('desktop_admin_health', authority) or {}
            if prior.get('controller_id') not in (None, body.controller_id) \
                    and now - prior.get('last_seen', 0) <= LEASE_S:
                raise HTTPException(409, 'Another recovery supervisor owns this installation lease')
            health = {'authority': authority, **body.model_dump(), 'last_seen': now}
            self.store.put('desktop_admin_health', authority, health)
            commands = []
            for row in self._rows(authority):
                row = self._status(row['worker_id'], authority, row['id'])
                key = identity(authority, row['id'])
                executed = row.get('offered_at') is not None or (row['op'] == 'rebuild' and row.get('job_id'))
                if row['state'] in ('requested', 'unknown', 'service_returned') and executed \
                        and body.epoch and body.epoch != row.get('epoch'):
                    state = ('unknown' if now - row.get('reported_at', row.get('offered_at', now)) > RETURN_S
                             else 'service_returned')
                    if body.worker_state == 'running' and body.worker_id == owner['worker_id'] \
                            and body.epoch == owner['epoch'] and now - owner['last_seen'] <= LEASE_S:
                        state = 'recovered'
                    row = row | {'state': state, 'returned_epoch': body.epoch,
                                 'returned_worker_id': body.worker_id, 'returned_at': now}
                    self.store.put('desktop_admin', key, row)
                if row['op'] != 'relaunch' or row['state'] not in ('queued', 'offered'):
                    continue
                if row.get('controller_id') != body.controller_id:
                    state = 'unknown' if row['state'] == 'offered' else 'expired'
                    self.store.put('desktop_admin', key, row | {'state': state, 'detail': 'supervisor_instance_changed'})
                    continue
                if now >= row['expires_at']:
                    self.store.put('desktop_admin', key, row | {'state': 'unknown', 'detail': 'delivery_expired'})
                    continue
                if body.epoch != row.get('epoch'):
                    self.store.put('desktop_admin', key, row | {'state': 'expired', 'detail': 'desktop_instance_changed'})
                    continue
                self.store.put('desktop_admin', key, row | {'state': 'offered', 'offered_at': now})
                commands.append({k: row[k] for k in ('id', 'op', 'authority', 'worker_id', 'controller_id',
                                                     'expires_at', 'force', 'epoch', 'sessions')})
            return {'commands': commands[:1], 'server_time': now}

    def result(self, authority, secret, rid, body):
        self.fed.owner(authority, secret)
        key = identity(authority, rid)
        with self.store.lock:
            row = self.store.get('desktop_admin', key)
            if not row or row['op'] != 'relaunch' or row.get('controller_id') != body.controller_id:
                raise HTTPException(409, 'Admin result does not belong to this supervisor request')
            receipt = body.model_dump()
            if row.get('result'):
                if row['result'] != receipt:
                    raise HTTPException(409, 'An admin result cannot change after delivery')
                return {'accepted': True, 'state': row['state']}
            if row['state'] not in ('offered', 'unknown', 'service_returned', 'recovered') or row.get('offered_at') is None:
                raise HTTPException(409, 'The admin command was not offered to this supervisor')
            allowed = {session['session_id']: session for session in row.get('sessions', ())}
            closed = []
            for evidence in body.closed_sessions:
                session = self.store.get('session', evidence.session_id) or {}
                expected = allowed.get(evidence.session_id) or {}
                if body.status != 'requested' or expected.get('pid') != evidence.pid \
                        or expected.get('created') != evidence.created \
                        or not evidence.session_id.startswith(row['worker_id']+'-') \
                        or (session.get('detail') or {}).get('pid') != evidence.pid \
                        or (session.get('detail') or {}).get('process_created') != evidence.created \
                        or (session.get('federation') or {}).get('authority') != authority:
                    raise HTTPException(409, 'Closed-session evidence differs from this exact recovery request')
                if session.get('state') == 'running':
                    closed.append((session, evidence))
            for session, evidence in closed:
                self.store.put('session', evidence.session_id, session | {'state': 'ended', 'ended': self.fed.clock(),
                    'exit': {'via': 'desktop_admin_recovery', 'request_id': rid,
                             'pid': evidence.pid, 'created': evidence.created}})
            state = row['state'] if body.status == 'requested' and row['state'] in ('service_returned', 'recovered') else body.status
            row = row | {'state': state, 'detail': body.detail, 'result': receipt, 'reported_at': self.fed.clock()}
            self.store.put('desktop_admin', key, row)
            self.store.audit(row['actor'], 'desktop.admin.result', row['worker_id'],
                             {'request_id': rid, 'state': body.status, 'detail': body.detail})
            return {'accepted': True, 'state': row['state']}


def routes(app, fed, config, auth):
    from .desktop_bridge import endpoint
    from .server import JobRequest
    def submit(wid, enable, actor, stamp):
        submit_job = endpoint(app, '/api/jobs')
        origin = {'via': 'desktop_admin', 'desktop_admin': stamp}
        stops = []
        for session in fed.store.running_sessions():
            if session['session_id'].startswith(wid+'-'):
                stop = submit_job(JobRequest(tool='session_op', require_worker=wid,
                    input={'session_id': session['session_id'], 'op': 'stop_game', 'args': {'moment': True}}),
                    actor=actor, origin=origin)
                stops.append(stop.id)
        return submit_job(JobRequest(tool='rebuild_node', require_worker=wid,
            input={'force': True, 'restart': True, 'enable_remote_admin': enable, 'stop_jobs': stops}),
            actor=actor, origin=origin)
    queue = AdminQueue(fed, submit=submit)
    app.state.desktop_admin = queue

    @app.post('/api/workers/{wid}/admin')
    def request(wid: str, body: AdminRequest, actor=Depends(auth)):
        if 'execute' not in config.granted_permissions or (body.op == 'rebuild' and 'install' not in config.granted_permissions):
            raise HTTPException(403, 'This control plane does not grant the required admin permissions')
        return queue.request(wid, body, actor)

    @app.get('/api/workers/{wid}/admin/{rid}')
    def status(wid: str, rid: str, installation: str, actor=Depends(auth)):
        return queue.status(wid, installation, rid)

    @app.post('/api/federation/{authority}/admin/poll')
    def poll(authority: str, body: AdminPoll, request: Request, actor=Depends(auth)):
        return queue.poll(authority, request.headers.get('x-gbox-federation-key', ''), body)

    @app.post('/api/federation/{authority}/admin/{rid}/result')
    def result(authority: str, rid: str, body: AdminResult, request: Request, actor=Depends(auth)):
        return queue.result(authority, request.headers.get('x-gbox-federation-key', ''), rid, body)
