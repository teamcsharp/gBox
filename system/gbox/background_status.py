"""Read-only workstation evidence. A successful tool is not a completed game goal."""
from __future__ import annotations

import time
from . import background_testing as B


def snapshot(store, worker, *, online, now=None):
    now = time.time() if now is None else now
    policy = B.policy(store, worker['name'])
    reason = B.guarded_reason(store, worker, now=now)
    if not online:
        reason = 'Worker offline. Durable queued work remains on the server.'
    def matching(job):
        return (job.get('tool') in worker.get('tools', [])
                and job.get('require_os') in (None, worker.get('os'))
                and job.get('require_worker') in (None, worker['id'], worker['name']))
    active, queue = [], []
    keys = ('id','tool','state','created','started','finished','progress','error','receipt_id',
            'parent_request_id','admission_wait','worker_id')
    def small(job):
        return {k:job.get(k) for k in keys} | {'stage_log': (job.get('progress_log') or [])[-6:]}
    for job in store.jobs(states=('running','queued'), limit=200, reverse=True):
        if job.get('worker_id') == worker['id'] and job.get('state') == 'running':
            active.append(small(job))
        elif job.get('state') == 'queued' and matching(job):
            queue.append(small(job))
    recent = [small(j) for j in store.jobs(limit=200,reverse=True)
              if j.get('worker_id') == worker['id'] and j.get('state') not in ('queued','running')][:10]
    sessions=[]
    for session in store.running_sessions():
        sid=session['session_id']
        if session.get('state') != 'running' or sid.split('-')[0] != worker['id']:
            continue
        job=store.get('job',sid.split('-',1)[-1])
        observer=store.get('session_observer',sid) or {}
        sessions.append({k:session.get(k) for k in ('session_id','title','mod','state')} |
                        {'agent_owned':B.agent_owned(store.get('slabel',sid),job),
                         'local_window':bool(session.get('detail',{}).get('local_window')),
                         'presentation':observer.get('presentation'), 'gameplay_state':observer.get('gameplay_state')})
    state = 'offline' if not online else 'gaming' if not B.allowed(worker,B.excluded(store)) else (
            'operator' if any(not s['agent_owned'] for s in sessions) else 'working' if active else (
            'testing' if sessions else 'waiting' if reason else 'ready'))
    return {'worker':{k:worker.get(k) for k in ('id','name','os','resources','idle_seconds','active_jobs')},
            'online':online,'mode':state,'background_testing':B.allowed(worker,B.excluded(store)),
            'budget_percent':policy['budget_percent'],'hard_throttle':False,
            'admission':{'allowed':reason is None,'reason':reason},'active':active,'eligible_queue':queue[:10],
            'recent_results':recent,'sessions':sessions,
            'capabilities':{'available':len(worker.get('tools',[])),'unavailable':worker.get('unavailable',{})},
            'sampled_at':now,'history_scope':'Newest 200 jobs; at most 10 recent worker results.',
            'idle_reason':reason or ('No eligible queued job has been assigned yet.' if not active and not sessions else None)}
