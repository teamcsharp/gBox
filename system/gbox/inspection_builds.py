"""Changed, reviewed recipes -> durable local inspection builds, never game launches.

Admission reserves measured RAM/disk headroom and one builder slot. It is not an
OS memory limit; writer working sets still need profiling and bounded algorithms.
"""
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from pydantic import BaseModel, Field
from .models import Permission as P
from .registry import tool

POLICY, PLAN, RUN = 'inspection_build_policy', 'inspection_build_plan', 'inspection_build_run'
DEFAULTS = {'enabled': False, 'node': 'JAYBUILTFINALE', 'allow_while_active': True,
            'memory_gib': 8, 'reserve_gib': 4, 'max_memory_percent': 80,
            'disk_gib': 8, 'reserve_disk_gib': 20, 'builds_per_hour': 3, 'debounce_s': 30}
ACTIVE = ('queued', 'running')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_inventory():
    root = Path(__file__).resolve().parents[1]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for p in (root / 'gbox').rglob('*.py') if p.is_file()}


def dependencies(names, root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    if not isinstance(names, list) or not 1 <= len(names) <= 24:
        raise ValueError('List 1–24 relevant writer/source dependencies')
    result = {}
    for name in names:
        if not isinstance(name, str) or not name.startswith('gbox/') or '\\' in name or not name.endswith('.py'):
            raise ValueError('Dependencies must be gbox/*.py source paths')
        p = root / name
        if not p.resolve().is_relative_to(root / 'gbox') or not p.is_file() or p.stat().st_size > 2*1024**2:
            raise ValueError('Dependency must be an existing small source file inside gbox')
        result[name] = hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    return result


def settings(body=None):
    value = DEFAULTS | (body or {})
    if type(value['enabled']) is not bool or type(value['allow_while_active']) is not bool:
        raise ValueError('enabled and allow_while_active must be booleans')
    if not isinstance(value['node'], str) or not value['node'].strip():
        raise ValueError('Choose a worker by name')
    for key, low, high in [('memory_gib', 1, 64), ('reserve_gib', 2, 64), ('max_memory_percent', 40, 90),
                           ('disk_gib', 1, 128), ('reserve_disk_gib', 5, 1024), ('builds_per_hour', 1, 12), ('debounce_s', 10, 600)]:
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}')
    return {k: value[k] for k in DEFAULTS}


def request_revisions(store, gid):
    result = {}
    for r in store.all('request'):
        c = r.get('context') or {}
        if c.get('game_id') != gid and not str(c.get('build') or '').startswith(gid + '/'):
            continue
        if r.get('automated') and not c.get('build_report'):
            continue
        messages = [{k: m.get(k) for k in ('text', 'attachments')} for m in r.get('messages', [])
                    if m.get('author') in ('operator', 'user', 'you')]
        result[r['id']] = digest({'body': r.get('body'), 'image': r.get('image'), 'messages': messages})
    return result


def recipe(gid, value):
    from .characters import CharIn
    if not isinstance(value, dict) or value.get('tool') != 'characters':
        raise ValueError('Publish a native characters cast_swap recipe')
    inp = dict(value.get('input') or {})
    if inp.get('op') != 'cast_swap' or (inp.get('target_game') or inp.get('game_id')) != gid:
        raise ValueError('The cast_swap recipe must target this exact game_id')
    if any(inp.get(k) and inp[k] != gid for k in ('game','game_id','target_game')):
        raise ValueError('Conflicting target game identifiers are not allowed')
    if inp.get('session_id') or inp.get('plan_only') or inp.get('showcase'):
        raise ValueError('Inspection recipes must be independent native builds, not session edits or showcases')
    inp.update(launch=False, rebuild=True, mod_name='')
    return {'tool': 'characters', 'input': CharIn.model_validate(inp).model_dump(mode='json', exclude_defaults=True) | {'launch':False, 'rebuild':True}}


def missing_reviews(store, plan):
    revisions = request_revisions(store, plan['game_id'])
    return {rid: rev for rid, rev in revisions.items() if plan.get('requests_ack', {}).get(rid) != rev}


def build_job(job):
    i = job.get('input') or {}
    return job.get('tool') == 'characters' and i.get('op') in ('cast_swap', 'use', 'match') and not i.get('plan_only')


def resource_reason(store, worker, policy, jobs, *, require_gpu=False, now=None):
    from . import background_testing as B
    reason = B.guarded_reason(store, worker, now=now, allow_active=policy['allow_while_active'], require_gpu=require_gpu)
    if reason: return reason
    if any(j.get('state') == 'running' and j.get('worker_id') == worker['id'] and build_job(j) for j in jobs):
        return 'One build is already running on this PC; next revision is preserved.'
    r = worker.get('resources') or {}
    available, total, free_disk = r.get('memory_available_bytes'), r.get('memory_total_bytes'), r.get('cache_free_bytes')
    def measured(v):return type(v) in (int,float) and math.isfinite(v) and v >= 0
    if not measured(total) or total <= 0 or not measured(available) or available > total:
        return 'Waiting for total/free RAM telemetry from an updated worker.'
    after = available - policy['memory_gib'] * 1024**3
    if after < policy['reserve_gib']*1024**3 or (total-after)*100/total > policy['max_memory_percent']:
        return f"Waiting for {policy['memory_gib']} GiB build headroom within the {policy['max_memory_percent']}% RAM admission limit."
    if not measured(free_disk):
        return 'Waiting for local build-cache disk telemetry from an updated worker.'
    if free_disk < (policy['disk_gib'] + policy['reserve_disk_gib'])*1024**3:
        return 'Waiting for local disk headroom; saved builds and retention preferences remain protected.'
    return None


def build_input(plan, key, *, normalized=True):
    """Freeze the same validated input that server submission stores."""
    inp = dict(plan['recipe']['input'], launch=False, rebuild=True,
               mod_name='inspect_'+key[:16], feedback_ack=plan['feedback_ack'])
    if not normalized:
        return inp
    from .characters import CharIn
    return CharIn.model_validate(inp).model_dump(mode='json')


def reservation_matches(plan, run, job):
    """Compare against the reviewed recipe, including server-added defaults.

    Legacy reservations hashed the sparse recipe. Accept them only when that exact
    recipe still hashes to the reservation and the job is its full validated form.
    Never derive authorization from the submitted job's own digest.
    """
    try:
        expected = build_input(plan, run['id'])
        accepted = {digest(expected), digest(build_input(plan, run['id'], normalized=False))}
        return (run.get('input_digest') in accepted and build_job(job)
                and job['input'].get('launch') is False and digest(job['input']) == digest(expected))
    except (KeyError, TypeError, ValueError):
        return False


def claim_reason(store, worker, job):
    """Authoritative recheck under the normal claim lock; no broad idle bypass."""
    run_id = (job.get('origin') or {}).get('inspection_run')
    run = store.get(RUN, run_id) if run_id else None
    if not run or run.get('job_id') != job['id']:
        return 'Inspection job has no matching durable reservation.'
    p = settings(store.get(POLICY, 'default'))
    plan = store.get(PLAN, run['game_id'])
    if not p['enabled'] or worker['name'] != p['node']:
        return 'Continuous builds are paused or assigned to another PC.'
    if not plan or not plan.get('enabled') or not plan.get('reviewed', True) or plan.get('revision') != run['plan_revision'] or missing_reviews(store, plan):
        return 'A newer request/recipe needs review; this inspection build is superseded.'
    try: expected = dependencies(plan['dependencies'])
    except (ValueError, OSError): return 'Writer dependency is missing; inspection build is deferred.'
    if expected != run['sources']:
        return 'Writer source changed; this queued inspection build is superseded.'
    if any(worker.get('build_sources', {}).get(path) != sha for path, sha in expected.items()):
        return 'Worker must refresh safely to load the changed writer code.'
    # A malicious/stale job cannot borrow a real reservation to launch a game.
    if not reservation_matches(plan, run, job):
        return 'Inspection recipe or launch policy does not match its reservation.'
    return resource_reason(store, worker, p, store.jobs(states=('running',)), require_gpu=plan['requires_gpu'])


class Controller:
    def __init__(self, store, workers, submit, *, clock=time.time, sources=dependencies):
        self.store, self.workers, self.submit, self.clock, self.sources = store, workers, submit, clock, sources
        self.lock = threading.RLock()

    def tick(self):
        with self.lock:
            s, now = self.store, self.clock()
            policy = settings(s.get(POLICY, 'default'))
            if not policy['enabled']: return {'state':'paused'}
            workers = self.workers()
            w = next((w for w in workers if w.get('name') == policy['node'] and w.get('online')), None)
            jobs = s.jobs(states=ACTIVE)
            runs = s.all(RUN)
            for plan in sorted(s.all(PLAN), key=lambda p:p.get('changed_at', 0)):
                if not plan.get('enabled'): continue
                gid = plan['game_id']
                def save(state, reason=None, **extra):
                    s.put(PLAN, gid, plan | {'state':state, 'reason':reason, 'checked_at':now} | extra)
                try:
                    sources = self.sources(plan['dependencies'])
                except (ValueError, OSError) as e:
                    save('blocked', str(e)); continue
                key = digest({'plan':plan['revision'], 'sources':sources})
                # A queued older revision is superseded; a running build is allowed to finish.
                for r in runs:
                    if r['game_id'] == gid and r['id'] != key and r.get('job_id'):
                        j = s.get('job', r['job_id'])
                        if j and j['state'] == 'queued':
                            s.put('job', j['id'], j | {'state':'failed', 'finished':now, 'error':'Superseded by newer inspection changes'})
                if not plan.get('reviewed', True) or missing_reviews(s, plan):
                    save('needs_review', 'New operator feedback must be reviewed before producing another build.'); continue
                previous = s.get(RUN, key)
                if previous:
                    j = s.get('job', previous.get('job_id')) if previous.get('job_id') else None
                    if not j and not previous.get('job_id'):
                        matches = [j for j in s.jobs(limit=200, reverse=True) if (j.get('origin') or {}).get('inspection_run') == key]
                        if len(matches) == 1:
                            j = matches[0]
                            s.put(RUN, key, previous | {'job_id':j['id']})
                    if j:
                        result = (j.get('output') or {}).get('result') or {}
                        state, reason = j['state'], j.get('error')
                        if state == 'succeeded':
                            from .special_builds import FAILED
                            usable = result.get('mod') and not any(x in str(result.get('status','')) for x in FAILED)
                            state = 'ready_for_inspection' if usable else 'blocked'
                            if not usable: reason = 'Writer did not produce a native inspection build; implementation still needs work.'
                        save(state, reason, job_id=j['id'], build=result.get('mod'), verification='pending gameplay inspection')
                    else: save('reconcile_required', 'A prior submission is uncertain; it will not be duplicated.')
                    continue
                if plan.get('desired') != key:
                    save('settling', 'Waiting for edits to settle.', desired=key, settled_since=now); continue
                if now - plan.get('settled_since', now) < policy['debounce_s']:
                    save('settling', 'Waiting for edits to settle.'); continue
                if not w:
                    save('waiting', 'Local worker offline; latest requested revision is preserved.'); continue
                reason = resource_reason(s, w, policy, jobs, require_gpu=plan['requires_gpu'], now=now)
                if reason: save('waiting', reason); continue
                if any(j.get('state') in ACTIVE and (j.get('origin') or {}).get('inspection_run') for j in jobs):
                    save('waiting', 'One inspection build is queued/running; changes are coalesced.'); continue
                if sum(r.get('created',0) > now-3600 for r in runs) >= policy['builds_per_hour']:
                    save('waiting', 'Hourly inspection-build limit reached; latest revision remains queued.'); continue
                if any(w.get('build_sources', {}).get(path) != sha for path, sha in sources.items()):
                    save('waiting', 'Worker must refresh safely to load changed writer code.'); continue
                inp = build_input(plan, key)
                run = {'id':key, 'game_id':gid, 'plan_revision':plan['revision'], 'sources':sources,
                       'input_digest':digest(inp), 'created':now, 'node':policy['node']}
                # Claim and linkage are atomic relative to worker admission. A crash after
                # submission leaves a recoverable origin ID, never an automatic repeat.
                with s.lock:
                    s.put(RUN, key, run)
                    try:
                        j = self.submit({'tool':'characters', 'input':inp, 'require_worker':w['id'], 'agent_use':True,
                            'low_priority':True, 'parent_request_id':plan.get('parent_request_id')}, key)
                        j = j.model_dump(mode='json') if hasattr(j,'model_dump') else j
                        s.put(RUN, key, run | {'job_id':j['id']})
                        jobs.append(j); runs.append(run)
                        save(j['state'], j.get('error'), job_id=j['id'])
                    except Exception as e:
                        save('blocked', str(getattr(e,'detail',e)))
            return {'state':'running', 'node':policy['node']}


def routes(app, store, auth, submit, workers):
    from fastapi import Depends, HTTPException
    controller = Controller(store, workers, submit)
    stop, wake = threading.Event(), threading.Event()
    app.state.inspection_builds = controller

    def snapshot():
        return {'policy':settings(store.get(POLICY,'default')), 'plans':store.all(PLAN),
                'runs':sorted(store.all(RUN), key=lambda r:-r['created'])[:30], 'hard_memory_cap':False}

    @app.get('/api/inspection-builds')
    def status(actor=Depends(auth)):return snapshot()

    @app.post('/api/inspection-builds')
    def configure(body:dict, actor=Depends(auth)):
        try: p=settings(settings(store.get(POLICY,'default')) | body)
        except (ValueError, TypeError) as e:raise HTTPException(422,str(e)) from e
        store.put(POLICY,'default',p);store.audit(actor,'inspection_builds.policy','default',p);wake.set()
        return snapshot()

    @app.get('/api/inspection-builds/{gid}')
    def get_plan(gid:str, actor=Depends(auth)):
        from .build_feedback import rows
        return {'plan':store.get(PLAN,gid), 'request_revisions':request_revisions(store,gid), 'feedback':rows(store,gid)}

    @app.post('/api/inspection-builds/{gid}')
    def publish(gid:str, body:dict, actor=Depends(auth)):
        if not store.catalog_get(gid):raise HTTPException(404,'Game not in owned catalog')
        try:
            change = body.get('change_id')
            if not isinstance(change,str) or not change.strip() or len(change)>300:raise ValueError('Describe the reviewed change_id')
            deps = list(dependencies(body.get('dependencies')))
            draft=body.get('draft',False)
            if type(draft) is not bool:raise ValueError('draft must be a boolean')
            requests = request_revisions(store,gid)
            if not draft and any((body.get('requests_ack') or {}).get(rid) != rev for rid,rev in requests.items()):
                raise ValueError('Read the operator requests and acknowledge their current request_revisions')
            from .build_feedback import check
            call = recipe(gid,body.get('recipe'))
            ack=body.get('feedback_ack') or {}
            if not draft: check(store,call | {'input':call['input'] | {'feedback_ack':ack}})
            enabled, gpu = body.get('enabled',True), body.get('requires_gpu',False)
            if type(enabled) is not bool or type(gpu) is not bool:raise ValueError('Use boolean enabled/requires_gpu')
            value={'game_id':gid,'title':store.catalog_get(gid).get('title'),'recipe':call,'change_id':change,'dependencies':deps,'requests_ack':body.get('requests_ack') or {},
                   'feedback_ack':ack,'requires_gpu':gpu,'enabled':enabled,'reviewed':not draft,'parent_request_id':body.get('parent_request_id')}
            revision=digest(value);old=store.get(PLAN,gid) or {}
            if old.get('revision') != revision:
                store.put(PLAN,gid,value | {'revision':revision,'changed_at':time.time(),'state':'needs_review' if draft else 'settling'})
            store.audit(actor,'inspection_builds.plan',gid,{'revision':revision});wake.set()
            return store.get(PLAN,gid)
        except (ValueError, TypeError) as e:raise HTTPException(422,str(e)) from e

    def loop():
        while not stop.is_set():
            wake.wait(15);wake.clear()
            if stop.is_set():break
            try:controller.tick()
            except Exception as e:print(f'Inspection builds deferred: {e}',flush=True)
    app.on_event('startup')(lambda:threading.Thread(target=loop,daemon=True,name='inspection-builds').start())
    app.on_event('shutdown')(lambda:(stop.set(),wake.set()))


class WatchIn(BaseModel):
    op:str='status'
    game_id:str=''
    value:dict=Field(default_factory=dict)


class WatchOut(BaseModel):
    result:dict


@tool('inspection_builds','1.0',WatchIn,WatchOut,permissions=[P.EXECUTE],timeout_s=30)
def watch(inp,ctx):
    """Continuous local builds: status, plan (game_id), configure (value policy), publish (game_id,value reviewed
    cast_swap recipe/change_id/dependencies/requests_ack/feedback_ack). Publish after implementing operator feedback;
    never acknowledge unread reports. New revisions assemble without launching games; old/unchanged builds never loop."""
    import httpx
    from urllib.parse import quote
    if not ctx.server:raise ValueError('Control plane required')
    url=ctx.server+'/api/inspection-builds'
    if inp.op in ('plan','publish'):url+='/'+quote(inp.game_id,safe='')
    if inp.op in ('status','plan'):r=httpx.get(url,headers=ctx.headers,timeout=20)
    elif inp.op in ('configure','publish'):r=httpx.post(url,headers=ctx.headers,json=inp.value,timeout=20)
    else:raise ValueError('Use status, plan, configure or publish')
    r.raise_for_status();return {'result':r.json()}
