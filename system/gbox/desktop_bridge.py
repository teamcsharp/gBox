"""Outbound federation for the desktop's one local worker.

The bridge owns no adapters and never runs a tool. Central commands are submitted
to the real local authority once, with a durable identity, then observed there.
Remote disconnection does not stop local sessions or queue a new launch.
"""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

import httpx

MEDIA_READ_S, MEDIA_WRITE_S, MEDIA_GRACE_S = 30.0, 15.0, 10.0

from .store import canon, sha256

_ID = re.compile(r'^[a-f0-9]{16,64}$')
_TERMINAL = {'succeeded', 'failed', 'invalid', 'rejected'}
_MAX_FRAME = 8_000_000
_LOCAL_AUTHORITIES={}


def asset_source_context(ctx):
    """The verified originating server for a federated Blender copy's assets.

    Execution and clipboard writes stay local. Never trust an input URL or an
    origin header alone to select a server or send its pairing credential.
    """
    config = getattr(ctx, 'config', None)
    if config is None:
        return None
    bridge = _LOCAL_AUTHORITIES.get(str(Path(config.data_dir).resolve()))
    if bridge is None:
        return None
    with bridge.store.lock:
        job = bridge.store.get('job', getattr(ctx, 'job_id', '')) or {}
        provenance = job.get('origin') or {}
        key = provenance.get('desktop_federation_key')
        if not key:
            return None
        mapping = bridge.store.get('desktop_bridge_job', key) if isinstance(key, str) else None
        if not mapping or mapping.get('local_job_id') != job.get('id') \
                or mapping.get('authority') != bridge.authority \
                or provenance.get('desktop_federation_authority') != bridge.authority \
                or mapping.get('remote') != bridge.remote \
                or job.get('tool') != 'blender_copy' or mapping.get('tool') != job.get('tool') \
                or mapping.get('execution_input_sha256') != sha256(canon(job.get('input'))):
            raise ValueError('The Blender asset source does not match its paired job')
        if not bridge.remote or not bridge.token:
            raise ValueError('The originating asset server is not paired')
        from types import SimpleNamespace
        headers = {'authorization': 'Bearer ' + bridge.token, 'x-gbox-parent-job': mapping['id']}
        if job.get('actor'):
            headers['x-gbox-actor'] = job['actor']
        return SimpleNamespace(server=origin(bridge.remote), headers=headers)


def check_stop(ctx,sid):
    """Final mutation fence, registered only by this PC's loopback authority."""
    config=getattr(ctx,'config',None)
    if config is None:return
    bridge=_LOCAL_AUTHORITIES.get(str(Path(config.data_dir).resolve()))
    if bridge is None or not bridge.submissions:return
    with bridge.store.lock:
        session=bridge.store.get('session',sid) or {}
        if session.get('state')!='running':return
        job=bridge.store.get('job',getattr(ctx,'job_id','')) or {};source=job.get('origin') or {}
        key=source.get('desktop_federation_key')
        mapping=bridge.store.get('desktop_bridge_job',key) if isinstance(key,str) else None
        if not mapping or mapping.get('local_job_id')!=job.get('id') or mapping.get('remote')!=bridge.remote \
                or source.get('desktop_federation_authority')!=bridge.authority:return
        original=source.get('central_origin') or {}
        command={'tool':job.get('tool'),'input':job.get('input'),'actor':job.get('actor'),'origin':original}
        why=bridge.admit_command(command,{'id':sid.split('-',1)[0]})
        if why:
            from .registry import Unsupported
            raise Unsupported(why)


def origin(value):
    parsed = urlsplit(str(value))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password \
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Expected an HTTP server origin without credentials or a path')
    return str(value).rstrip('/')


def endpoint(app, path, method='POST'):
    return next(route.endpoint for route in app.routes
                if getattr(route, 'path', None) == path and method in (getattr(route, 'methods', None) or ()))


class SubmissionHeld(RuntimeError):
    """A previous attempt may have taken effect; repeating it is forbidden."""


class Submissions:
    def __init__(self, store, submit, authority, remote, *, resolve=None, admit=None):
        self.store, self.submit = store, submit
        self.authority, self.remote = authority, origin(remote)
        self.scope = sha256(self.remote.encode())
        self.resolve=resolve
        self.admit=admit

    def key(self, jid):
        if not isinstance(jid, str) or not _ID.fullmatch(jid):
            raise ValueError('Invalid central job identity')
        return self.scope + '/' + jid

    def rows(self):
        return [row for row in self.store.all('desktop_bridge_job') if row.get('remote') == self.remote]

    def accept(self, command, worker):
        jid, tool, inp = command.get('id'), command.get('tool'), command.get('input')
        key = self.key(jid)
        if not isinstance(tool, str) or not isinstance(inp, dict) or tool not in worker.get('tools', ()):
            raise ValueError('Command must name an available tool on the actual local worker')
        if command.get('origin') is not None and not isinstance(command['origin'],dict):
            raise ValueError('Command origin must be an object')
        digest = sha256(canon(inp))
        complete = sha256(canon({'tool': tool, 'input': inp}))
        if command.get('input_sha256') != digest or command.get('command_sha256', complete) != complete:
            raise ValueError('Central command digest does not match its input')
        sid = inp.get('session_id')
        if sid and (not isinstance(sid, str) or not sid.startswith(worker['id'] + '-')):
            raise ValueError('Command belongs to a different native worker')
        if command.get('require_worker') not in (None, '', worker['id'], worker.get('name')):
            raise ValueError('Command names a different worker')
        with self.store.lock:
            if self.admit:
                why=self.admit(command,worker)
                if why:raise SubmissionHeld(why)
            saved = self.store.get('desktop_bridge_job', key)
            if saved:
                if saved.get('command_sha256') != complete:
                    raise ValueError('A central job identity cannot change tool or input')
                if saved.get('local_job_id'):
                    job = self.store.get('job', saved['local_job_id'])
                    if job is None:raise SubmissionHeld('The previously submitted local job is unavailable')
                    return job
                # Recover the job if submission committed before its reply/map.
                matches = [job for job in self.store.all('job')
                           if (job.get('origin') or {}).get('desktop_federation_key') == key]
                if len(matches) == 1:
                    job = matches[0]
                    if job.get('tool') != tool or sha256(canon(job.get('input'))) != saved.get('execution_input_sha256',digest):
                        raise SubmissionHeld('Recovered job input differs from its reservation')
                    self.store.put('desktop_bridge_job', key, saved | {'local_job_id': job['id']})
                    return job
                raise SubmissionHeld('Previous submission has an uncertain outcome; it was not repeated')
            execution=self.resolve(tool,inp) if self.resolve else inp
            execution_digest=sha256(canon(execution))
            saved = {'id': jid, 'remote': self.remote, 'authority': self.authority, 'tool': tool,
                     'input_sha256': digest, 'command_sha256': complete, 'reserved_at': time.time()}
            saved['execution_input_sha256']=execution_digest
            self.store.put('desktop_bridge_job', key, saved)
            trusted_origin = {**(command.get('origin') or {}), 'via': 'desktop_federation',
                              'desktop_federation_key': key, 'desktop_federation_authority': self.authority,
                              'central_origin':command.get('origin') or {},
                              'central_input_sha256':digest,'execution_input_sha256':execution_digest}
            job = self.submit({**command,'input':execution}, worker, trusted_origin)
            if hasattr(job, 'model_dump'):job = job.model_dump(mode='json')
            if not isinstance(job, dict) or not isinstance(job.get('id'), str):
                raise SubmissionHeld('Local submit returned no durable job identity')
            persisted = self.store.get('job', job['id'])
            if persisted is None:raise SubmissionHeld('Local submit did not persist the returned job')
            self.store.put('desktop_bridge_job', key, saved | {'local_job_id': job['id']})
            return persisted


def jpeg_parts(chunks):
    """Read bounded multipart JPEGs without assuming HTTP chunk boundaries."""
    buf = bytearray()
    for chunk in chunks:
        buf.extend(chunk)
        while True:
            start = buf.find(b'\xff\xd8')
            if start < 0:
                if len(buf) > 65536:del buf[:-2]
                break
            if start:del buf[:start]
            end = buf.find(b'\xff\xd9', 2)
            if end < 0:
                if len(buf) > _MAX_FRAME:raise ValueError('Oversized local JPEG frame')
                break
            if end + 2 > _MAX_FRAME:raise ValueError('Oversized local JPEG frame')
            yield bytes(buf[:end + 2]);del buf[:end + 2]


def remote_pad_events(events,lease,secret,now):
    from .desktop_input_lease import MARKER
    ordinary=[]
    for event in events:
        if not isinstance(event,dict) or event.get('rpc'):continue
        expiry=event.get('_federation_expires_at')
        if event.get('_federation_expired') is True or type(expiry) not in (float,int) \
                or not math.isfinite(expiry) or expiry<=now:
            # A key-up may expire in transit after central dequeued it. Clear
            # only this lease's existing hold, even while polling stays healthy.
            lease.expired(event);continue
        ordinary.append({**{key:value for key,value in event.items()
                            if key not in (MARKER,'_federation_expires_at','_federation_expired')},MARKER:secret})
    return ordinary


class DesktopBridge:
    def __init__(self, app, cfg, authority, worker):
        self.app, self.store, self.cfg, self.authority, self.worker = app, app.state.store, cfg, authority, worker
        self.lock = threading.RLock();self.stop = threading.Event();self.thread = None
        self.remote = None;self.token = None;self.secret = None;self.epoch = secrets.token_hex(16)
        self.submissions = None;self.watched = set();self.channels = {};self.streams = {}
        self.active_worker_id=None;self.catalog_offset=0;self.catalog_at=0
        self.input_secret=secrets.token_hex(32);self.input_leases={}
        self.clock_offset=None
        self.state = {'configured': False, 'connected': False, 'state': 'not_configured'}
        self._submit_endpoint = endpoint(app, '/api/jobs')
        self._boundary_endpoint = endpoint(app, '/api/autoplay-screensaver/round-boundary')

    def status(self):
        with self.lock:return dict(self.state,epoch=self.epoch,installation=self.authority,
                                   worker_id=self.active_worker_id)

    def configure(self, remote, token):
        remote = origin(remote)
        if remote == origin(self.cfg.public_url):raise ValueError('A local authority cannot federate to itself')
        if not isinstance(token, str) or not token.strip() or len(token) > 16384:
            raise ValueError('Expected a paired central credential')
        with self.lock:
            if self.remote and remote != self.remote:
                raise ValueError('Changing the paired central authority requires an idle local service restart')
            self.remote, self.token = remote, token.strip()
            file = self.cfg.data_dir / ('desktop-federation-' + sha256(remote.encode())[:20] + '.key')
            file.parent.mkdir(parents=True, exist_ok=True)
            try:
                with file.open('x', encoding='ascii') as out:out.write(secrets.token_hex(32))
                try:file.chmod(0o600)
                except OSError:pass
            except FileExistsError:pass
            self.secret = file.read_text(encoding='ascii').strip()
            if not re.fullmatch(r'[a-f0-9]{64}', self.secret):raise ValueError('Invalid local federation identity')
            # The opt-in recovery supervisor needs the existing paired channel
            # after this desktop exits. DPAPI keeps it bound to this Windows user.
            from .registry import HOST_OS
            if HOST_OS == 'windows':
                try:
                    from .desktop_supervisor import save_pairing
                    saved=save_pairing(self.cfg,self.authority,self.remote,self.secret,self.token)
                    self.state['admin_pairing']='saved' if saved else 'not_enabled'
                except (ImportError,OSError,ValueError,RuntimeError):
                    self.state['admin_pairing']='unavailable'
            self.submissions = Submissions(self.store, self._submit, self.authority, remote,
                                           resolve=self.resolve_input,admit=self.admit_command)
            self.state.update(configured=True, remote=remote, state='connecting')
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True, name='desktop-federation')
                self.thread.start()
            from .mercs import evidence_sync
            evidence_sync.start(self)
        return self.status()

    def resolve_input(self,tool,inp):
        if tool!='launch_game':return inp
        from .desktop_local import local_entry
        game=inp.get('game')
        if not isinstance(game,dict) or not isinstance(game.get('game_id'),str):return inp
        known=self.store.catalog_get(game['game_id']) or game
        local=local_entry(known,self.cfg)
        if not local:return inp # Normal local launch admission remains authoritative.
        if local.get('platform')!=game.get('platform') or local['game_id']!=game['game_id']:
            raise ValueError('Resolved local title identity differs from the requested game')
        original_launch=game.get('launch') or {};local_launch=local.get('launch') or {}
        if original_launch.get('kind')!=local_launch.get('kind'):
            raise ValueError('Resolved local launch recipe differs from the requested game')
        launch=dict(original_launch)
        if local_launch.get('path'):launch['path']=local_launch['path']
        if launch.get('kind')=='steam' and str(launch.get('appid'))!=str(local_launch.get('appid')):
            raise ValueError('Resolved Steam title differs from the requested app')
        resolved={**game,'source_paths':local['source_paths'],'library':local.get('library'),
                  'rel_path':local.get('rel_path'),'launch':launch}
        return {**inp,'game':resolved}

    def _submit(self, command, worker, provenance):
        from .server import JobRequest
        # Central already owns its request hierarchy. Do not invent an absent
        # local request, but retain its ID as provenance for central reconciliation.
        provenance = {**provenance, 'central_parent_request_id': command.get('parent_request_id')}
        request = JobRequest(tool=command['tool'], input=command['input'], require_worker=worker['id'],
                             agent_use=bool(command.get('agent_use')), low_priority=bool(command.get('low_priority')))
        from fastapi import HTTPException
        try:return self._submit_endpoint(request, actor=command.get('actor') or 'desktop-federation', origin=provenance)
        except HTTPException as error:
            raise SubmissionHeld('Local admission refused ('+str(error.status_code)+'); no automatic repeat') from error

    def actual_worker(self):
        if not self.worker.state.get('running') or self.worker.state.get('state') != 'running':return None
        name = self.worker.name or __import__('platform').node()
        rows = [row for row in self.store.all('worker')
                if row.get('name') == name and time.time() - row.get('last_seen', 0) < 30]
        return max(rows, key=lambda row: row.get('last_seen', 0), default=None)

    def sessions(self, worker):
        own=[row for row in self.store.recent('session',256)
             if str(row.get('session_id', '')).startswith(worker['id'] + '-')]
        seen={row['session_id'] for row in own}
        # An old but still active session must never fall out of the snapshot.
        own.extend(row for row in self.store.running_sessions()
                   if row['session_id'].startswith(worker['id']+'-') and row['session_id'] not in seen)
        return sorted(own,key=lambda row:(row.get('state')!='running',-(row.get('started') or 0)))[:256]

    def catalog_batch(self):
        if time.monotonic()-self.catalog_at<30:return []
        from .desktop_local import local_entry
        with self.store.lock:
            rows=self.store.db.execute('SELECT rowid,body FROM catalog WHERE rowid>? ORDER BY rowid LIMIT 500',
                                       (self.catalog_offset,)).fetchall()
        accepted=[];size=0
        for rowid,encoded in rows:
            row=local_entry(json.loads(encoded),self.cfg)
            if row:
                length=len(canon(row))
                if size+length>1_000_000:break
                accepted.append(row);size+=length
            self.catalog_offset=rowid
        if len(rows)<500:self.catalog_offset=0
        self.catalog_at=time.monotonic()
        return accepted

    def scheduler_snapshot(self,worker):
        from . import mercmode as M
        name=worker['name']
        history=self.store.get(M.HISTORY,name) or {}
        return {'settings':M.settings(self.store,name),'history':history,
                'preparation':M.host_preparation(self.store,worker)}

    def scheduler_live(self,worker):
        """This PC's own MercMode run, warm pool, next pick and the app's dispatch here, for the central's status (its
        MercMode panel and every PiP following this PC). A separate snapshot field: an older central ignores it."""
        from . import mercmode as M
        saver=getattr(self.app.state,'autoplay_screensaver',None)
        return M.live_snapshot(self.store,worker['name'],note=(getattr(saver,'notes',None) or {}).get(worker['name']))

    def install_demo_marker(self,command,job):
        marker=command.get('autoplay_on_launch')
        if not isinstance(marker,dict) or command.get('tool')!='launch_game':return False
        gid=(command.get('input') or {}).get('game',{}).get('game_id')
        if marker.get('game_id')!=gid or job.get('tool')!='launch_game' \
                or (job.get('input') or {}).get('game',{}).get('game_id')!=gid:
            raise ValueError('Autoplay marker differs from its exact launch title')
        key=self.submissions.key(command['id'])
        from . import screensaver as S
        pending={'job':job['id'],'game_id':gid,'at':time.time(),'actor':marker.get('actor') or 'operator',
                 'agent':bool(marker.get('agent'))}
        demo={**pending,'by':pending['actor']}
        # Marker consumption and PENDING creation are one durable transaction.
        # A later command replay cannot reinstall an already consumed request.
        with self.store.lock:
            if self.store.get('desktop_bridge_demo',key):return False
            try:
                self.store.db.execute('BEGIN IMMEDIATE')
                for kind,identity,body in ((S.PENDING,job['id'],pending),(S.BOT_DEMO,job['id'],demo),
                        ('desktop_bridge_demo',key,{'central_job_id':command['id'],'local_job_id':job['id'],'game_id':gid})):
                    self.store.db.execute('INSERT INTO docs(kind,id,body) VALUES(?,?,?)',
                                          (kind,identity,json.dumps(body)))
                self.store.db.commit()
            except Exception:
                self.store.db.rollback();raise
        return True

    def mapped_autoplay(self,body,parent):
        sid=body.get('session_id')
        if not self.submissions or not isinstance(sid,str) or not isinstance(parent,str) or not _ID.fullmatch(parent):return None
        job=self.store.get('job',parent) or {};inp=job.get('input') or {}
        if job.get('tool')!='autoplay' or inp.get('op')!='start' or inp.get('session_id')!=sid:return None
        rows=[row for row in self.submissions.rows() if row.get('local_job_id')==parent and row.get('tool')=='autoplay']
        return rows[0] if len(rows)==1 else None

    def admit_command(self,command,worker):
        from .screensaver import ACTOR
        inp=command.get('input') or {};source=command.get('origin') or {}
        if command.get('tool')!='session_op' or inp.get('op')!='stop_game' or command.get('actor')!=ACTOR \
                or source.get('via')!='autoplay screensaver' or source.get('session_id')!=inp.get('session_id'):
            return None
        sid=inp.get('session_id')
        if self.submissions and self.store.get('desktop_bridge_handover',self.submissions.scope+'/'+str(sid)):
            return 'The operator took over this exact local session; its automatic stop was refused'

    def note_handover(self,body,parent,mapped):
        sid=body['session_id'];key=self.submissions.scope+'/'+sid
        with self.store.lock:
            self.store.put('desktop_bridge_handover',key,{'session_id':sid,'local_parent_job_id':parent,
                'central_parent_job_id':mapped['id'],'reason':body.get('reason'), 'at':time.time(),'owner':'human'})
            self.store.put('slabel',sid,{'owner':'you','session_id':sid,'label':'Local operator took over the game','ts':time.time()})
            # A command already submitted locally but not claimed must not race
            # the next delivery pass or a delayed central handover response.
            from .screensaver import ACTOR
            for job in self.store.jobs(states=('queued',)):
                inp=job.get('input') or {};source=job.get('origin') or {};original=source.get('central_origin') or {}
                if job.get('tool')=='session_op' and inp.get('op')=='stop_game' and inp.get('session_id')==sid \
                        and job.get('actor')==ACTOR and source.get('desktop_federation_authority')==self.authority \
                        and original.get('via')=='autoplay screensaver' and original.get('session_id')==sid:
                    self.store.put('job',job['id'],job|{'state':'rejected','finished':time.time(),
                        'error':'The local operator took over this session before its automatic stop was claimed'})

    def autoplay_report(self,kind,body,parent):
        mapped=self.mapped_autoplay(body,parent)
        if mapped is None:return None
        if kind not in ('yield','result') or len(canon(body))>8000:raise ValueError('Invalid bounded autoplay report')
        if kind=='yield':self.note_handover(body,parent,mapped)
        payload={'kind':kind,'body':body,'local_job_id':parent}
        key=self.submissions.scope+'/'+sha256(canon(payload))
        if not self.store.get('desktop_bridge_report',key):
            self.store.put('desktop_bridge_report',key,{'id':key,'remote':self.remote,'payload':payload,'queued_at':time.time()})
        try:
            with httpx.Client(base_url=self.remote,headers=self._headers(),timeout=3) as client:
                return self._send_report(client,self.store.get('desktop_bridge_report',key))
        except (httpx.HTTPError,OSError,ValueError):
            return {'saved':False,'yielded':False,'queued':True}

    def _send_report(self,client,row):
        if row.get('ack') is not None:return row['ack']
        ack=self._central(client,'POST','/autoplay-report',json=row['payload'])
        self.store.put('desktop_bridge_report',row['id'],row|{'ack':ack})
        return ack

    def _reports(self,client):
        for row in self.store.all('desktop_bridge_report'):
            if row.get('remote')==self.remote and row.get('ack') is None:self._send_report(client,row)

    def _headers(self):
        return {'authorization': 'Bearer ' + self.token, 'x-gbox-federation-key': self.secret,
                'x-gbox-actor': 'desktop-federation'}

    def _central(self, client, method, path, **kwargs):
        started=time.time()
        response = client.request(method, '/api/federation/' + self.authority + path, **kwargs)
        response.raise_for_status()
        body=response.json()
        if isinstance(body,dict):
            server_time=body.get('server_time')
            if type(server_time) in (int,float) and math.isfinite(server_time):
                # Server time is no earlier than request start. This upper
                # bound on offset shortens, never extends, a remote input TTL.
                self.clock_offset=server_time-started
        return body

    def result(self, job, central_id):
        result = {'job_id': central_id, 'ok': job.get('state') == 'succeeded',
                  'output': job.get('output'), 'error': job.get('error'), 'log': [], 'artifacts': []}
        if not result['ok'] and not result['error']:
            result['error']='Local authority reported '+str(job.get('state'))
        if job.get('log_sha'):
            data = self.store.read_artifact(job['log_sha'])
            if data:result['log'] = data.decode('utf-8', 'replace').splitlines()[-5000:]
        receipt = self.store.get('receipt', job.get('receipt_id')) if job.get('receipt_id') else None
        total = 0
        for ref in (receipt or {}).get('artifacts', ()):
            declared=ref.get('size')
            if isinstance(declared,int) and declared+total>64*1024*1024:
                raise SubmissionHeld('Result exceeds the bounded bridge artifact transfer')
            data = self.store.read_artifact(ref['sha256'])
            if data is None:raise SubmissionHeld('Local result artifact is unavailable')
            total += len(data)
            if total > 64 * 1024 * 1024:raise SubmissionHeld('Result exceeds the bounded bridge artifact transfer')
            result['artifacts'].append({'name': ref['name'], 'media_type': ref['media_type'],
                'provenance': {**ref.get('provenance', {}), 'local_sha256': ref['sha256']},
                'b64': base64.b64encode(data).decode('ascii')})
        return result

    def _report_jobs(self, client):
        holds=[]
        for row in self.submissions.rows():
            if not row.get('local_job_id') or row.get('central_acked'):continue
            try:
                job = self.store.get('job', row['local_job_id'])
                if not job:raise SubmissionHeld('A mapped local job is unavailable')
                body = {'local_job_id': job['id'], 'state': job['state']}
                if row.get('tool') == 'rebuild_node' and job.get('progress') is not None:
                    source = job.get('origin') or {}
                    if job['id'] != row['local_job_id'] or job.get('tool') != row['tool'] \
                            or row.get('authority') != self.submissions.authority \
                            or source.get('desktop_federation_authority') != self.submissions.authority \
                            or source.get('desktop_federation_key') != self.submissions.key(row['id']) \
                            or job.get('worker_id') != self.active_worker_id or not self.active_worker_id \
                            or sha256(canon(job.get('input') or {})) != row.get('execution_input_sha256'):
                        raise SubmissionHeld('Rebuild progress does not match its original local execution')
                    from .federated_progress import snapshot
                    try:
                        body['rebuild_progress'] = snapshot(job, (self.token, self.secret, self.input_secret, self.cfg.token()))
                    except ValueError:
                        # Optional telemetry cannot strand the actual tool result or change its error.
                        row = row | {'progress_delivery_error': 'invalid_rebuild_progress'}
                        self.store.put('desktop_bridge_job', self.submissions.key(row['id']), row)
                terminal = job['state'] in _TERMINAL
                if terminal:body['result'] = self.result(job, row['id'])
                if len(canon(body))>120*1024*1024:raise SubmissionHeld('Serialized result exceeds the bounded bridge transfer')
                ack = self._central(client, 'POST', '/jobs/' + row['id'], json=body)
                if terminal and ack.get('accepted'):
                    self.store.put('desktop_bridge_job', self.submissions.key(row['id']), row | {'central_acked': True})
            except (SubmissionHeld,httpx.HTTPError,OSError,ValueError) as error:
                reason=str(error)[:180] if isinstance(error,SubmissionHeld) else type(error).__name__
                holds.append({'central_job_id':row['id'],'local_job_id':row['local_job_id'],'reason':reason})
                # A delivery failure says nothing about the actual tool result.
                # Keep its identity/outcome and let unrelated work/media proceed.
                if row.get('delivery_held')!=reason:
                    self.store.put('desktop_bridge_job',self.submissions.key(row['id']),row|{'delivery_held':reason})
        self.state['delivery_holds']=holds[:8]

    def _run(self):
        with httpx.Client(base_url=self.remote, headers=self._headers(), timeout=5) as client:
            while not self.stop.is_set():
                try:
                    client.headers.update(self._headers())
                    worker = self.actual_worker()
                    if not worker:
                        self.active_worker_id=None
                        self.state.update(connected=False, state='waiting_local_owner')
                        self.watched = set();self.stop.wait(2);continue
                    sessions = self.sessions(worker)
                    self._central(client, 'POST', '/snapshot', json={'epoch': self.epoch, 'worker': worker,
                                  'sessions': sessions,'catalog':self.catalog_batch(),
                                  'scheduler_owner':'local','mercmode':self.scheduler_snapshot(worker),
                                  'mercmode_run':self.scheduler_live(worker)})
                    self.active_worker_id=worker['id']
                    self.state.update(connected=True, state='connected', last_connected=time.time(),
                                      worker_id=worker['id'], sessions=len(sessions), error=None)
                    self._report_jobs(client)
                    # Register the exact autoplay parent mapping before a fast
                    # handover report references it; reports still precede any
                    # newly offered central stop or launch command.
                    self._reports(client)
                    commands = self._central(client, 'POST', '/commands', json={'maximum': 2}).get('commands', [])
                    command_holds=[]
                    for command in commands:
                        try:
                            job=self.submissions.accept(command, worker)
                            self.install_demo_marker(command,job)
                        except (SubmissionHeld,ValueError) as error:
                            command_holds.append({'central_job_id':command.get('id'),'reason':str(error)[:180]})
                    self.state['command_holds']=command_holds[:8]
                    self._report_jobs(client)
                    watch = self._central(client, 'GET', '/watch').get('sessions', [])
                    running = {row['session_id'] for row in sessions if row.get('state') == 'running'}
                    from .screensaver import telemetry_get
                    for sid in running:
                        telemetry=telemetry_get(sid)
                        if telemetry and telemetry.get('age_s',99)<3:
                            actual={k:v for k,v in telemetry.items() if k!='age_s'}
                            client.post('/api/autoplay/telemetry/'+sid,json=actual).raise_for_status()
                    self.watched = running.intersection(watch)
                    self._ensure_relays(worker['id'], running)
                    self.stop.wait(1)
                except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
                    # Offline local jobs continue normally. No emulator/process
                    # action is coupled to this retry or the central lease.
                    self.state.update(connected=False, state='reconnecting', error=type(error).__name__)
                    self.watched = set();self.stop.wait(3)

    def _ensure_relays(self, wid, running):
        for sid in running:
            if sid not in self.channels or not self.channels[sid].is_alive():
                thread = threading.Thread(target=self._input, args=(sid,), daemon=True, name='desktop-input-relay')
                self.channels[sid] = thread;thread.start()
        for sid in list(self.watched)[:4]:
            if sid not in self.streams or not self.streams[sid].is_alive():
                thread = threading.Thread(target=self._media, args=(wid, sid), daemon=True, name='desktop-media-relay')
                self.streams[sid] = thread;thread.start()

    def _running(self, sid):
        return not self.stop.is_set() and self.active_worker_id and sid.startswith(self.active_worker_id+'-') \
            and (self.store.get('session', sid) or {}).get('state') == 'running'

    def _input(self, sid):
        from .desktop_input_lease import MARKER,attach
        from .tools import SESSIONS
        from . import padstate
        entry=SESSIONS.get(sid)
        if not entry:return # No adapter adoption or synthetic input receiver.
        initial=[{'key':key,'down':True} for key in padstate.snapshot(sid).get('held',())]
        lease=attach(entry[0],self.input_secret,initial_local=initial)
        self.input_leases[sid]=lease
        local_headers = {'authorization': 'Bearer ' + self.cfg.token(), 'x-gbox-actor': 'desktop-federation'}
        with httpx.Client(base_url=self.remote, headers=self._headers(), timeout=8) as remote, \
             httpx.Client(base_url=self.cfg.public_url, headers=local_headers, timeout=12) as local:
            while self._running(sid):
                try:
                    events = self._central(remote, 'GET', '/sessions/' + sid + '/input', params={'wait': 3})
                    offset=self.clock_offset
                    now=time.time()+offset if offset is not None else float('inf')
                    ordinary=remote_pad_events(events,lease,self.input_secret,now)
                    if ordinary:local.post('/api/sessions/' + sid + '/input', json={'events': ordinary}).raise_for_status()
                    for event in events:
                        if not isinstance(event, dict) or not event.get('rpc'):continue
                        rid = event['rpc']
                        if not isinstance(rid, str) or not _ID.fullmatch(rid):continue
                        expires=event.get('expires_at')
                        if type(expires) not in (int,float) or not math.isfinite(expires) or expires<=now:continue
                        key = self.submissions.scope + '/' + sid + '/' + rid
                        prior = self.store.get('desktop_bridge_rpc', key)
                        if prior is None:
                            # Reserve before mutation. A lost result is reported
                            # as unknown, never executed twice after a restart.
                            prior = {'ok': False, 'error': 'Previous RPC outcome is unknown; it was not repeated'}
                            self.store.put('desktop_bridge_rpc', key, prior)
                            try:
                                args = event.get('args') or {}
                                speed_change = event.get('op') == 'pso_controls' and (args.get('input') or {}).get('op') == 'autoplay_speed'
                                reply = local.post('/api/sessions/' + sid + '/rpc',
                                                   json={'op': event['op'], 'args': args},
                                                   **({'timeout': 50} if speed_change else {}))
                                if reply.is_success:prior = {'ok': True, 'data': reply.json()}
                                else:prior = {'ok': False, 'error': 'Local RPC was refused (' + str(reply.status_code) + ')'}
                            except (httpx.HTTPError, ValueError):
                                prior = {'ok': False, 'error': 'Local RPC outcome is unknown; it was not repeated'}
                            self.store.put('desktop_bridge_rpc', key, prior)
                        self._central(remote, 'POST', '/sessions/' + sid + '/rpc/' + rid, json=prior)
                except (httpx.HTTPError, OSError, ValueError):
                    try:lease.release()
                    except (OSError,RuntimeError):pass
                    self.stop.wait(2)
        try:lease.release()
        except (OSError,RuntimeError):pass

    def _media(self, wid, sid):
        # A steady relay (operator 2026-10-29: the i9's stream kept "Reconnecting"; the central plane logged its upload
        # cut every ~10 s): the upload's writes may wait MEDIA_WRITE_S for a busy receiver and the local stream's reads
        # MEDIA_READ_S for a quiet picture (they were 5 s and 8 s), and a watch that blinks out for under MEDIA_GRACE_S
        # keeps the relay up instead of tearing it down and starting again.
        headers = {'authorization': 'Bearer ' + self.cfg.token()}
        with httpx.Client(base_url=self.cfg.public_url, headers=headers,
                          timeout=httpx.Timeout(10, read=MEDIA_READ_S)) as local, \
             httpx.Client(base_url=self.remote, headers=self._headers(),
                          timeout=httpx.Timeout(10, read=None, write=MEDIA_WRITE_S)) as remote:
            try:
                # Use the sole worker's existing desktop capture/crop channel.
                # This never starts another capture process in the bridge.
                with local.stream('GET', '/api/workers/' + wid + '/desktop/stream',
                                  params={'view': 'game', 'session': sid}) as response:
                    response.raise_for_status()
                    def frames():
                        unwatched = None
                        for jpeg in jpeg_parts(response.iter_bytes()):
                            if not self._running(sid):break
                            if sid in self.watched:unwatched = None
                            elif unwatched is None:unwatched = time.monotonic()
                            elif time.monotonic() - unwatched > MEDIA_GRACE_S:break
                            yield len(jpeg).to_bytes(4,'big')+jpeg
                    remote.post('/api/sessions/' + sid + '/stream',content=frames(),
                                headers={'content-type': 'application/octet-stream'}).raise_for_status()
            except (httpx.HTTPError, OSError, ValueError):pass

    def boundary(self, body, parent=None):
        sid = body.get('session_id')
        if not self.submissions or not isinstance(sid, str):return None
        if not isinstance(parent,str) or not _ID.fullmatch(parent):return None
        mapped=self.mapped_autoplay(body,parent)
        if mapped is None:return None
        try:
            with httpx.Client(base_url=self.remote, headers=self._headers(), timeout=3) as client:
                return self._central(client, 'POST', '/round-boundary',
                    json={'body': body, 'local_job_id': mapped['local_job_id']})
        except (httpx.HTTPError, OSError, ValueError):
            return {'saved': False, 'rotate_requested': False, 'reason': 'Central authority is unavailable'}


def install(app, cfg, authority, worker, auth):
    """Register only on the loopback authority, never a second server worker."""
    from fastapi import Depends, HTTPException
    bridge = DesktopBridge(app, cfg, authority, worker)
    local_key=str(cfg.data_dir.resolve());_LOCAL_AUTHORITIES[local_key]=bridge
    app.state.desktop_bridge = bridge

    @app.get('/api/desktop-local/bridge')
    def status(_actor=Depends(auth)):
        return bridge.status()

    @app.post('/api/desktop-local/bridge')
    def configure(body: dict, _actor=Depends(auth)):
        try:return bridge.configure(body.get('remote_url'), body.get('token'))
        except ValueError as error:raise HTTPException(422, str(error))

    @app.post('/api/desktop-local/federated-jobs')
    def submit(body: dict, _actor=Depends(auth)):
        actual = bridge.actual_worker()
        if not bridge.submissions or not actual:raise HTTPException(409, 'Local native owner is not ready')
        try:return bridge.submissions.accept(body, actual)
        except SubmissionHeld as error:raise HTTPException(409, str(error))
        except ValueError as error:raise HTTPException(422, str(error))

    # Wrap only this local app's existing boundary endpoint. Its validation and
    # operator path remain unchanged when no central parent mapping exists.
    route = next(route for route in app.routes if getattr(route, 'path', '') == '/api/autoplay-screensaver/round-boundary')
    original = route.endpoint
    def boundary(*args, **kwargs):
        body = kwargs.get('body') or next((value for value in args if hasattr(value, 'model_dump')), None)
        plain = body.model_dump() if hasattr(body, 'model_dump') else body
        remote = bridge.boundary(plain,kwargs.get('parent_job')) if isinstance(plain, dict) else None
        return original(*args, **kwargs) if remote is None else remote
    route.dependant.call = boundary

    def wrap_report(route,kind):
        original=route.endpoint
        def report(*args,**kwargs):
            body=kwargs.get('body') or next((value for value in args if hasattr(value,'model_dump')),None)
            plain=body.model_dump() if hasattr(body,'model_dump') else body
            remote=bridge.autoplay_report(kind,plain,kwargs.get('parent_job')) if isinstance(plain,dict) else None
            return original(*args,**kwargs) if remote is None else remote
        route.dependant.call=report
    for route in app.routes:
        path=getattr(route,'path','')
        if path in ('/api/autoplay-screensaver/yield','/api/autoplay-screensaver/result'):
            wrap_report(route,path.rsplit('/',1)[-1])

    @app.on_event('shutdown')
    def close():
        bridge.stop.set()
        if _LOCAL_AUTHORITIES.get(local_key) is bridge:_LOCAL_AUTHORITIES.pop(local_key,None)
    return bridge
