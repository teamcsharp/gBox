"""An outbound desktop bridge advertises one real local authority, never another executor.

Central commands retain their original identity until the sole local worker has
answered. Native sessions retain their local SID; transport loss is not an exit.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import sqlite3
import threading
import time

from fastapi import Depends, HTTPException, Request

from .models import CatalogEntry, WorkerInfo
from .store import canon, sha256
from .worker_results import normalized_result

LEASE_S = 30.
# An older worker of the same local authority (the same PC install) unseen this long owns no live game any more: its
# local authority restarted (a new epoch, a new worker id) and would report a game it still ran. 2026-10-24 16:51 the
# i9-NUC's local scheduler started Mercenaries 3D, its app restarted, and that "running" row refused every later
# snapshot ("An existing worker still owns a native game") for 49 hours.
STALE_OWNER_S = 30 * 60.
TERMINAL = {'succeeded', 'failed', 'invalid', 'rejected'}
AUTHORITY = re.compile(r'[a-f0-9]{64}\Z')
IDENTITY = re.compile(r'[a-f0-9]{16,64}\Z')
_REPORT_LOCK=threading.RLock()


def foreground_session_job(store, job, worker_id, *, require_live=True):
    """Exact-worker operator launches and live controls must reach their authority."""
    if job.get('agent_use') is not False:
        return False
    if job.get('tool') == 'launch_game':
        # A launch has no native session yet. Only an explicitly pinned operator
        # request qualifies; ordinary claim/admission still decides if it can run.
        game = (job.get('input') or {}).get('game')
        return (job.get('require_worker') == worker_id and isinstance(game,dict)
                and isinstance(game.get('game_id'),str) and bool(game['game_id']))
    if job.get('tool') not in ('session_op','get_frame','autoplay'):
        return False
    sid = (job.get('input') or {}).get('session_id')
    if not isinstance(sid,str) or not sid.startswith(worker_id+'-'):
        return False
    if not require_live:
        return True  # an offered control retains its reservation until its result arrives
    session = store.get('session',sid)
    return bool(session and session.get('state') == 'running'
                and session.get('worker_id',worker_id) == worker_id)


def _worker_names(store):
    """{'id', 'name'} of every registered worker, extracted by SQLite when the store can (Store.fields)."""
    fields = getattr(store, 'fields', None)
    if fields is not None:
        try:
            return fields('worker', ('id', 'name'))
        except sqlite3.Error:
            pass
    return store.all('worker')


def _bounded(value, maximum):
    try:
        if len(json.dumps(value, allow_nan=False).encode()) > maximum:
            raise HTTPException(413, 'Federation payload is too large')
    except (ValueError, TypeError):
        raise HTTPException(422, 'Finite JSON data required') from None


class Federation:
    def __init__(self, store, *, claim, accept_result, watch=lambda wid: [],
                 take_input=None, rpc_result=None, boundary=None, clock=time.time):
        self.store,self.claim,self.accept_result=store,claim,accept_result
        self.watch,self.take_input,self.rpc_result,self.boundary=watch,take_input,rpc_result,boundary
        self.clock=clock

    @staticmethod
    def key_hash(key):
        if not isinstance(key,str) or not AUTHORITY.fullmatch(key):
            raise HTTPException(403, 'A paired authority key is required')
        return hashlib.sha256(key.encode()).hexdigest()

    def owner(self, authority, key, *, fresh=False):
        if not AUTHORITY.fullmatch(str(authority)):
            raise HTTPException(422, 'Invalid installation identity')
        digest=self.key_hash(key)
        row=self.store.get('federation',authority)
        if not row or not hmac.compare_digest(row['key_hash'],digest):
            raise HTTPException(403, 'Authority ownership does not match')
        if fresh and self.clock()-row['last_seen']>LEASE_S:
            raise HTTPException(409, 'The local authority must renew its snapshot first')
        return row

    def session(self, owner, sid, *, running=True):
        row=self.store.get('session',sid)
        if not row or (row.get('federation') or {}).get('authority')!=owner['authority'] \
                or not sid.startswith(owner['worker_id']+'-'):
            raise HTTPException(403, 'Session belongs to another authority')
        if running and row.get('state')!='running':
            raise HTTPException(409, 'Session has ended')
        return row

    def _end_stale_owned(self, authority, others, wid):
        """Running rows of this same authority's older workers, unseen for STALE_OWNER_S, end as stale (call under the
        store lock). A worker of another authority, or one seen recently, keeps its game: the guard below refuses."""
        now=self.clock()
        for row in self.store.running_sessions():
            owner_id=row['session_id'].split('-',1)[0]
            if owner_id not in others:
                continue
            owner=self.store.get('worker',owner_id) or {}
            mine=((owner.get('federation') or {}).get('authority')==authority
                  and (row.get('federation') or {}).get('authority') in (None,authority))
            if not mine or now-float(owner.get('last_seen') or 0)<STALE_OWNER_S:
                continue
            self.store.put('session',row['session_id'],row|{'state':'ended','ended':now,
                'exit':{'via':'stale_owner','worker':owner_id,'superseded_by':wid}})
            self.store.audit('desktop-federation','session.ended',row['session_id'],
                             {'via':'stale_owner','worker':owner_id,'superseded_by':wid})

    def mappings(self, authority):
        return [{'central_job_id':r['id'],'local_job_id':r.get('local_job_id')}
                for r in self.store.all('federation_command')
                if r['authority']==authority and r.get('local_job_id')][-256:]

    def snapshot(self, authority, key, body, address=''):
        _bounded(body,2*1024*1024)
        if not AUTHORITY.fullmatch(str(authority)):
            raise HTTPException(422,'Invalid installation identity')
        digest=self.key_hash(key)
        try:
            worker=WorkerInfo.model_validate(body['worker']).model_dump()
            epoch=body['epoch'];sessions=body['sessions']
        except (KeyError,ValueError,TypeError):
            raise HTTPException(422,'Exact worker, epoch and session snapshots are required') from None
        wid=worker['id']
        if not IDENTITY.fullmatch(wid) or not re.fullmatch(r'[a-f0-9]{32}',str(epoch)) \
                or not isinstance(sessions,list) or len(sessions)>256:
            raise HTTPException(422,'Invalid bounded authority snapshot')
        catalog=body.get('catalog',[])
        if not isinstance(catalog,list) or len(catalog)>500:
            raise HTTPException(422,'At most 500 verified local catalog entries are accepted')
        for entry in catalog:
            try:
                CatalogEntry.model_validate(entry)
                if (entry.get('local_availability') or {}).get('verified') is not True:
                    raise ValueError('Local file verification is required')
            except (ValueError,TypeError,AttributeError):
                raise HTTPException(422,'Catalog entries require verified local files and original game IDs') from None
        observed=body.get('mercmode')
        scheduler=body.get('scheduler_owner')
        if scheduler not in (None,'local'):
            raise HTTPException(422,'The local authority owns its automatic scheduler')
        if observed is not None:
            from . import mercmode
            _bounded(observed,24000)
            if not isinstance(observed,dict) or set(observed)-{'settings','history','preparation'} \
                    or not isinstance(observed.get('history'),(dict,list)) \
                    or not isinstance(observed.get('preparation'),dict):
                raise HTTPException(422,'Bounded observed scheduler metadata is required')
            try:observed={**observed,'settings':mercmode.normalize(observed['settings'])}
            except (KeyError,ValueError):raise HTTPException(422,'Invalid observed MercMode settings') from None
        # its own scheduler's current run, warm pool, next pick and the app's dispatch there (GET /api/mercmode shows
        # them for this PC); a report that is not this worker's own, or too large, is dropped, never the whole snapshot
        live=body.get('mercmode_run')
        if live is not None:
            from . import mercmode
            if not mercmode.valid_live(live,wid):live=None
        with self.store.lock:
            old=self.store.get('federation',authority)
            if old and not hmac.compare_digest(old['key_hash'],digest):
                raise HTTPException(403,'Authority is already paired to another key')
            registered=self.store.get('worker',wid)
            if registered and (registered.get('federation') or {}).get('authority')!=authority:
                raise HTTPException(409,'This worker identity already has another owner')
            # Do not retire/adopt an older remote worker's still-owned emulator.
            # id and name only: the worker kind is 32 rows / 3 MB on the Spark (source hashes, tool lists) and every
            # PC's snapshot decoded all of it while holding the store lock (2026-10-27).
            others={w['id'] for w in _worker_names(self.store) if w['name']==worker['name'] and w['id']!=wid}
            self._end_stale_owned(authority,others,wid)
            if any(s['session_id'].split('-',1)[0] in others for s in self.store.running_sessions()):
                raise HTTPException(409,'An existing worker still owns a native game; it was preserved')
            if old and old['worker_id']!=wid and any(s['session_id'].startswith(old['worker_id']+'-')
                                                     for s in self.store.running_sessions()):
                raise HTTPException(409,'The previous local worker still owns a session')
            validated=[]
            for item in sessions:
                if not isinstance(item,dict):raise HTTPException(422,'Invalid session row')
                sid=item.get('session_id','')
                if not isinstance(sid,str) or not sid.startswith(wid+'-') \
                        or not IDENTITY.fullmatch(sid[len(wid)+1:]) \
                        or item.get('state') not in ('running','ended') \
                        or not isinstance(item.get('game_id'),str) or not item['game_id'] \
                        or not isinstance(item.get('adapter'),str) or not item['adapter'] \
                        or not isinstance(item.get('detail',{}),dict):
                    raise HTTPException(422,'Session SID must belong to the actual worker')
                previous=self.store.get('session',sid)
                if previous and (previous.get('federation') or {}).get('authority')!=authority:
                    raise HTTPException(409,'Session already has another owner')
                if previous and any(previous.get(k)!=item.get(k) for k in ('game_id','adapter')):
                    raise HTTPException(409,'Native session identity changed')
                if previous and previous.get('state')=='ended' and item['state']!='ended':
                    raise HTTPException(409,'An ended native session cannot be resurrected')
                validated.append((sid,item,previous))
            now=self.clock()
            owner={'authority':authority,'key_hash':digest,'epoch':epoch,'worker_id':wid,'last_seen':now}
            self.store.put('federation',authority,owner)
            provenance={'authority':authority,'epoch':epoch,'last_seen':now,'single_owner':True,'media':'session_stream'}
            scheduler=scheduler or ((registered or {}).get('federation') or {}).get('scheduler_owner')
            if scheduler:provenance['scheduler_owner']=scheduler
            self.store.put('worker',wid,worker|{'last_seen':now,'address':address,'federation':provenance})
            if observed is not None:
                self.store.put('mercmode_observed',worker['name'],{'authority':authority,'worker_id':wid,'at':now,**observed})
            if live is not None:
                self.store.put('mercmode_observed_run',worker['name'],{'authority':authority,'worker_id':wid,'at':now,**live})
            for sid,item,previous in validated:
                # Omitted sessions remain last-known; only a positive ended row closes one.
                row=(previous or {})|item|{'worker_id':wid,'federation':provenance}
                self.store.put('session',sid,row)
                if item.get('agent_owned') is True:
                    self.store.put('slabel',sid,{'owner':'agent','task':'local authority automation'})
            for entry in catalog:
                existing=self.store.catalog_get(entry['game_id'])
                if not existing:
                    self.store.upsert_catalog([entry|{'federation_source':authority}])
                self.store.catalog_update(entry['game_id'],cached_on=sorted(set((existing or {}).get('cached_on') or [])
                                                                            |{worker['name']}))
                self.store.put('federation_catalog',authority+':'+entry['game_id'],
                               {'authority':authority,'worker_id':wid,'game_id':entry['game_id'],'last_seen':now})
            return {'ok':True,'worker_id':wid,'epoch':epoch,'lease_seconds':LEASE_S,
                    'server_time':self.clock(),'watch':self.watch(wid),'job_mappings':self.mappings(authority)}

    def commands(self,authority,key,request,maximum=4):
        if type(maximum) is not int or not 1<=maximum<=4:
            raise HTTPException(422,'maximum must be 1 through 4')
        owner=self.owner(authority,key,fresh=True);wid=owner['worker_id']
        with self.store.lock:
            # Recover even a claim response lost before its delivery row was saved.
            jobs=[j for j in self.store.jobs(states=('running',)) if j.get('worker_id')==wid]
            is_stop=lambda j:j['tool']=='session_op' and j.get('input',{}).get('op')=='stop_game'
            is_control=lambda j:foreground_session_job(self.store,j,wid)
            is_inflight_control=lambda j:foreground_session_job(self.store,j,wid,require_live=False)
            name=(self.store.get('worker',wid) or {}).get('name')
            pending=[j for j in self.store.queued_jobs() if j.get('require_worker') in (None,wid,name)]
            # A central "running" command may still be queued at the local
            # authority (e.g. background work waiting for idle). Reserve one
            # delivery opportunity for foreground control without cancelling
            # those jobs or bypassing the ordinary claim/admission checks.
            priority=(any(is_stop(j) for j in pending) and not any(is_stop(j) for j in jobs)) \
                or (any(is_control(j) for j in pending) and not any(is_stop(j) or is_inflight_control(j) for j in jobs))
            while len(jobs)<maximum or priority:
                job=self.claim(wid,request,foreground_only=True) if len(jobs)>=maximum else self.claim(wid,request)
                if not isinstance(job,dict):break
                jobs.append(job)
                priority=False
            jobs.sort(key=lambda j:(not is_stop(j),not is_inflight_control(j),j['created']))
            commands=[]
            for job in jobs[:maximum]:
                record=self.store.get('federation_command',job['id'])
                if record and record['authority']!=authority:
                    raise HTTPException(409,'Command belongs to another authority')
                payload={k:job.get(k) for k in ('id','tool','input','agent_use','parent_request_id','actor','origin')}
                payload['input_sha256']=sha256(canon(job.get('input') or {}))
                payload['command_sha256']=sha256(canon({'tool':job['tool'],'input':job.get('input') or {}}))
                pending=self.store.get('autoplay_on_launch',job['id'])
                gid=(job.get('input',{}).get('game') or {}).get('game_id')
                if job['tool']=='launch_game' and pending and pending.get('job')==job['id'] \
                        and gid and pending.get('game_id')==gid:
                    payload['autoplay_on_launch']={k:pending.get(k) for k in ('game_id','actor','agent')}
                if not record:
                    record={'id':job['id'],'authority':authority,'worker_id':wid,'command_sha256':payload['command_sha256'],
                            'offered':self.clock()}
                    self.store.put('federation_command',job['id'],record)
                commands.append(payload|{'local_job_id':record.get('local_job_id')})
            return {'commands':commands}

    def job(self,authority,key,jid,body):
        _bounded(body,128*1024*1024)
        owner=self.owner(authority,key)
        local_id=body.get('local_job_id');state=body.get('state')
        if not isinstance(local_id,str) or not IDENTITY.fullmatch(local_id) or state not in TERMINAL|{'queued','running'}:
            raise HTTPException(422,'An exact local job ID and state are required')
        with self.store.lock:
            record=self.store.get('federation_command',jid)
            job=self.store.get('job',jid)
            if not record or not job or record['authority']!=authority or record['worker_id']!=owner['worker_id'] \
                    or job.get('worker_id')!=owner['worker_id']:
                raise HTTPException(403,'Job belongs to another authority')
            if record.get('local_job_id') not in (None,local_id):
                raise HTTPException(409,'Central command is already bound to another local job')
            conflict=self.store.get('federation_local_job',owner['worker_id']+'-'+local_id)
            if conflict and conflict['central_job_id']!=jid:
                raise HTTPException(409,'Local job is already bound to another central command')
            result=body.get('result')
            if state in TERMINAL:
                if not isinstance(result,dict) or result.get('job_id')!=jid or type(result.get('ok')) is not bool \
                        or result['ok']!=(state=='succeeded'):
                    raise HTTPException(422,'An exact terminal worker result is required')
                try:
                    normalized_result(result)
                    if result.get('output') is not None and not isinstance(result['output'],dict):
                        raise ValueError('Result output must be an object')
                    if result.get('error') is not None and not isinstance(result['error'],str):
                        raise ValueError('Result error must be text')
                except ValueError as exc:
                    raise HTTPException(422,str(exc)) from None
                if result['ok'] and job['tool']=='launch_game':
                    output=result.get('output') or {};sid=output.get('session_id','')
                    if sid!=owner['worker_id']+'-'+local_id:
                        raise HTTPException(409,'Launch output must retain its actual local SID')
            elif record.get('ack'):
                return record['ack']               # a delayed running update cannot undo a completed delivery
            record.update(local_job_id=local_id,local_state=state,updated=self.clock())
            self.store.put('federation_command',jid,record)
            self.store.put('federation_local_job',owner['worker_id']+'-'+local_id,
                           {'authority':authority,'central_job_id':jid,'local_job_id':local_id})
            if state not in TERMINAL:return {'mapped':True,'central_job_id':jid,'local_job_id':local_id}
            ack=self.accept_result(owner['worker_id'],result,'federation:'+authority[:12])
            record['ack']=ack
            self.store.put('federation_command',jid,record)
            # Acceptance creates the session through the normal validated launch callback.
            sid=(result.get('output') or {}).get('session_id')
            if job['tool']=='launch_game' and sid and (session:=self.store.get('session',sid)):
                self.store.put('session',sid,session|{'federation':{'authority':authority,'epoch':owner['epoch'],
                    'last_seen':self.clock(),'single_owner':True,'media':'session_stream'},
                    'central_launch_job_id':jid,'local_launch_job_id':local_id})
            return ack


def routes(app,store,config,auth,*,claim,accept_result,watch,take_input,rpc_result):
    fed=Federation(store,claim=claim,accept_result=accept_result,watch=watch,
                   take_input=take_input,rpc_result=rpc_result,
                   boundary=lambda body,parent:app.state.autoplay_screensaver.round_boundary(body,parent))
    app.state.federation=fed

    def key(request):return request.headers.get('x-gbox-federation-key','')

    @app.post('/api/federation/{authority}/snapshot')
    def snapshot(authority:str,body:dict,request:Request,actor=Depends(auth)):
        return fed.snapshot(authority,key(request),body,request.client.host if request.client else '')

    @app.post('/api/federation/{authority}/commands')
    def commands(authority:str,body:dict,request:Request,actor=Depends(auth)):
        return fed.commands(authority,key(request),request,body.get('maximum',4))

    @app.post('/api/federation/{authority}/jobs/{jid}')
    def job(authority:str,jid:str,body:dict,request:Request,actor=Depends(auth)):
        return fed.job(authority,key(request),jid,body)

    @app.get('/api/federation/{authority}/watch')
    def watched(authority:str,request:Request,actor=Depends(auth)):
        owner=fed.owner(authority,key(request))
        return {'sessions':watch(owner['worker_id']),'lease_seconds':LEASE_S,'server_time':fed.clock()}

    @app.get('/api/federation/{authority}/sessions/{sid}/input')
    def inputs(authority:str,sid:str,request:Request,wait:float=0,actor=Depends(auth)):
        owner=fed.owner(authority,key(request),fresh=True);fed.session(owner,sid)
        events=take_input(sid,min(max(wait,0),5))
        def fresh_event(event):
            if not isinstance(event,dict):return False
            expiry=event.get('expires_at') if event.get('rpc') else event.get('_federation_expires_at')
            return type(expiry) in (int,float) and math.isfinite(expiry) and expiry>fed.clock()
        filtered=[]
        for event in events:
            if fresh_event(event):filtered.append(event)
            elif isinstance(event,dict) and not event.get('rpc') and isinstance(event.get('key'),str) \
                    and type(event.get('player',1)) is int and 1<=event.get('player',1)<=4:
                # A release hint is not player input. The local bridge may only
                # clear an existing key in its private remote lease.
                filtered.append({'key':event['key'],'player':event.get('player',1),'down':False,
                                 '_federation_expired':True,'src':'bridge'})
        events=filtered
        with store.lock:
            for event in events:
                if isinstance(event,dict) and event.get('rpc'):
                    store.put('federation_rpc',event['rpc'],{'authority':authority,'sid':sid,'at':fed.clock()})
        return events

    @app.post('/api/federation/{authority}/sessions/{sid}/rpc/{rid}')
    def rpc_reply(authority:str,sid:str,rid:str,body:dict,request:Request,actor=Depends(auth)):
        _bounded(body,8*1024*1024)
        owner=fed.owner(authority,key(request));fed.session(owner,sid)
        with store.lock:
            pending=store.get('federation_rpc',rid)
            if not pending or pending['authority']!=authority or pending['sid']!=sid:
                raise HTTPException(403,'RPC was not offered to this authority/session')
            digest=sha256(canon(body))
            if pending.get('digest'):
                if pending['digest']!=digest:raise HTTPException(409,'RPC outcome changed')
                return pending['ack']
            if fed.clock()-pending['at']>15:
                raise HTTPException(409,'RPC expired; its outcome must not be replayed')
            ack=rpc_result(sid,rid,body)
            store.put('federation_rpc',rid,pending|{'digest':digest,'ack':ack})
            return ack

    @app.post('/api/federation/{authority}/round-boundary')
    def boundary(authority:str,body:dict,request:Request,actor=Depends(auth)):
        _bounded(body,10000)
        owner=fed.owner(authority,key(request),fresh=True)
        native=body.get('body')
        if not isinstance(native,dict) or not isinstance(body.get('local_job_id'),str):
            raise HTTPException(422,'An exact native boundary and local parent job are required')
        sid=native.get('session_id','')
        fed.session(owner,sid)
        local=body.get('local_job_id','')
        mapping=store.get('federation_local_job',owner['worker_id']+'-'+local)
        if not mapping or mapping['authority']!=authority:
            raise HTTPException(403,'Native boundary has no owning central autoplay command')
        parent=store.get('job',mapping['central_job_id']) or {}
        try:return fed.boundary(native,parent)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @app.post('/api/federation/{authority}/autoplay-report')
    def autoplay_report(authority:str,body:dict,request:Request,actor=Depends(auth)):
        _bounded(body,64000)
        owner=fed.owner(authority,key(request));native=body.get('body');kind=body.get('kind')
        local=body.get('local_job_id')
        if kind not in ('yield','result') or not isinstance(native,dict) or not isinstance(local,str):
            raise HTTPException(422,'An exact autoplay report is required')
        sid=native.get('session_id','');fed.session(owner,sid,running=kind=='yield')
        mapping=store.get('federation_local_job',owner['worker_id']+'-'+local)
        parent=store.get('job',(mapping or {}).get('central_job_id','')) or {}
        if not mapping or mapping.get('authority')!=authority or parent.get('tool')!='autoplay' \
                or parent.get('state') not in ('running','succeeded') \
                or parent.get('worker_id')!=owner['worker_id'] or parent.get('require_worker')!=owner['worker_id'] \
                or (parent.get('input') or {}).get('session_id')!=sid or (parent.get('input') or {}).get('op')!='start':
            raise HTTPException(403,'The report has no exact owning central autoplay parent')
        digest=sha256(canon(native));identifier=authority+':'+local+':'+kind+':'+digest
        if kind=='yield':
            reason=native.get('reason')
            if not isinstance(reason,str) or len(reason)>500:raise HTTPException(422,'A bounded handover reason is required')
        else:
            value=native.get('result')
            if not isinstance(value,dict):raise HTTPException(422,'An observed autoplay result is required')
        with _REPORT_LOCK:
            with store.lock:
                previous=store.get('federation_autoplay_report',identifier)
                if previous and previous.get('ack') is not None:return previous['ack']
                store.put('federation_autoplay_report',identifier,{'digest':digest,'ack':None})
            # Both callbacks merge an observation or hand ownership to the
            # operator idempotently. A pending record survives a central crash
            # and retries that same observation, never a launch or stop.
            # Do not hold Store while taking the scheduler lock.
            saver=app.state.autoplay_screensaver
            saved=saver.yield_to_operator(sid,reason) if kind=='yield' else saver.report(sid,value)
            ack={'saved':bool(saved)}
            store.put('federation_autoplay_report',identifier,{'digest':digest,'ack':ack})
            return ack

    from .mercs import evidence_sync
    evidence_sync.routes(app,store,config,auth,fed)
