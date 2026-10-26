"""F5 keeps the autobot driving; F3 starts or stops it on the game a gBox window shows, whichever PC runs that game.

Operator 2026-10-26:
  "When i reload the stream via F5 because the bot got stuck or the stream freezes, bring it back up with the bot active
   and in control."
  "Allow me to start the Autobot on any game session by pressing the F3 key, even if I'm on a different computer using
   G Box."

Both run as in-server jobs, polled like a reset (GET /api/jobs/{id}). The desktop names the session its window shows; the
control plane follows a replaced session to the game running now and sends every autoplay command to the worker that
holds that session, so the keys work from any PC.

POST /api/sessions/{sid}/autoplay/ensure  (F5). A bot is only ever (re)started on a session that had one before the
  reload: the current MercMode / screensaver run, a bot demo, an autoplay start that nobody stopped or took over, or a bot
  whose last report (started on the pad, no job) said it was driving. The operator's own game without a bot is never
  touched. A bot reporting fresh telemetry is left alone; one that stopped is started again; one whose telemetry went stale
  (or that reported a hang) is stopped and started again. The game's saved menu settings are re-applied too (game_prefs).
POST /api/sessions/{sid}/autoplay {op: toggle|start|stop}  (F3). Asks that PC whether autoplay runs, then starts or stops
  it as the requester (the desktop app's requests are the operator's). Automation cannot drive the operator's own game
  through it.
POST /api/workers/{name}/bot-reload  (deploy_main.sh for a bot-only deploy; docs/hot-update.md). That PC's bot_reload
  tool reloads its changed bot modules in place (gbox/hot_reload.py): the games keep running and every autobot restarts
  in its session with its own input and job, so MercMode keeps owning its run. A session whose bot did not come back is
  handed to F5's path (ensure: Screensaver.restart_bot for a MercMode run). wait_s > 0 answers when the worker is done.
"""
from __future__ import annotations

import threading
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel

ENSURE_TOOL = 'autoplay_ensure'
TOGGLE_TOOL = 'autoplay_toggle'
FRESH_S = 15.0               # a report younger than this: the bot is driving (the PiP's "autobot" label uses the same)
STALE_S = 20.0               # no report for this long while it last said "running": four missed 5 s reports, stuck
STATUS_WAIT_S = 35.0         # an autoplay status read on the session's worker
QUEUE_WAIT_S = 25.0          # ... which must be picked up this soon, or that PC is offline / busy
STOP_WAIT_S = 30.0
STOP_SETTLE_S = 20.0         # a stopped bot's thread ends within this, or a restart would be refused ("stopping")
START_WAIT_S = 75.0          # the autoplay tool's own limit is 60 s
PENDING_START_S = 120.0      # an autoplay start younger than this, still queued / running: it is on its way
TERMINAL = ('succeeded', 'failed', 'invalid', 'rejected', 'cancelled')
RELAUNCHES = ('session_reset', 'session_swap', 'session_reload')   # the game is being replaced: its bot follows that
RELOAD_TOOL = 'bot_reload'
RELOAD_WAIT_S = 240.0        # the bot_reload tool's own limit is 180 s (a round preparation may make it wait 90 s)


class ToggleIn(BaseModel):
    op: str = 'toggle'           # toggle | start | stop
    source: str = 'F3'           # what the operator pressed (recorded on the autoplay jobs)
    continuous: bool = True      # a start allows recovery of this bot's frozen game (Stop still wins), as F3 always did
    assist: bool = False         # hold the player's HP while the bot plays


class EnsureIn(BaseModel):
    reason: str = 'F5'


class ReloadIn(BaseModel):
    modules: list[str] = []      # bot modules (dotted names); empty: every loaded bot module whose source changed
    settle_s: float = 5.0        # a restarted bot dying with an error this soon brings the old modules back
    wait_s: float = 0.0          # > 0: answer once the worker has finished (deploy_main.sh waits), else the queued job


def liveness(telemetry: dict) -> str:
    """driving | stuck | stopped | unknown, from the newest autoplay report (screensaver.telemetry_last)."""
    if not telemetry:
        return 'unknown'
    if telemetry.get('running') is False:
        return 'stopped'
    if (telemetry.get('stats') or {}).get('hung'):
        return 'stuck'
    age = telemetry.get('age_s')
    if not isinstance(age, (int, float)):
        return 'unknown'
    if age < FRESH_S:
        return 'driving'
    return 'stuck' if age >= STALE_S else 'unknown'


def follow(store, sid: str) -> tuple[str, dict]:
    """The session a window shows, followed to the game running now: replacements of the same game (a relaunch) and
    MercMode's verified title rotation. (sid, session); 404 for an unknown session."""
    sess = store.get('session', sid)
    if not sess:
        raise HTTPException(404, 'Unknown game session.')
    seen = {sid}
    while sess.get('state') != 'running' and sess.get('replaced_by') and sess['replaced_by'] not in seen:
        nxt_sid = sess['replaced_by']
        nxt = store.get('session', nxt_sid)
        rotation = (sess.get('mercmode_rotation') or {}).get('successor_session_id') == nxt_sid
        if not nxt or (nxt.get('game_id') != sess.get('game_id') and not rotation):
            break
        seen.add(nxt_sid)
        sid, sess = nxt_sid, nxt
    return sid, sess


def intent(store, sid: str, telemetry: dict, *, runs=(), requester: str = 'operator', bot_pcs=(),
           worker_name: str = '', ignore_job: str = '', now: float | None = None) -> dict:
    """Whether F5 may bring a bot back on this session, and how: {kind, reason, ...}. kind None: leave the game alone.
    kind mercmode | screensaver: the scheduler's own run (restart it through the scheduler); bot_demo | autoplay |
    telemetry: start = the autoplay input, actor / agent_use = who starts it. ignore_job: our own stop of a stuck bot."""
    from . import autoplay_resume, screensaver
    from .background_testing import agent_owned
    now = time.time() if now is None else now

    def none(why, **kw):
        return {'kind': None, 'reason': why, **kw}
    sess = store.get('session', sid) or {}
    if sess.get('state') != 'running':
        return none('That game has ended.')
    label = store.get('slabel', sid) or {}
    if label.get('warm'):
        return none('This MercMode game waits paused for its turn; its autobot starts when it plays.')
    latest = autoplay_resume.latest_control(store, sid, exclude_job_id=ignore_job) or {}
    linp = autoplay_resume.effective_input(latest) if latest else {}
    if telemetry.get('autoplay_taken_over') or (latest and autoplay_resume.revoked(store, sid, latest.get('id'))):
        return none('You took over with the controller, so the autobot stays off. Press F3 to hand it back.')
    reported = now - float(telemetry.get('age_s') or 0) if telemetry else 0.0
    stopped_at = float(latest.get('finished') or latest.get('created') or 0)
    if linp.get('op') == 'stop' and latest.get('actor') != screensaver.ACTOR \
            and not (telemetry.get('running') is True and reported > stopped_at + STOP_SETTLE_S):
        return none('The autobot was stopped (control handed back), so it stays off. Press F3 to start it.')
    if linp.get('op') == 'start' and latest.get('state') in ('queued', 'assigned', 'running') \
            and now - float(latest.get('created') or now) < PENDING_START_S:
        return none('An autobot start is already on its way to that PC.', pending=True)
    for j in store.jobs(states=('queued', 'running')):
        if j.get('tool') in RELAUNCHES and (j.get('input') or {}).get('session_id') == sid:
            return none('This game is being relaunched; its autobot follows the new session.', pending=True)
    run = next((r for r in runs if r.get('session_id') == sid), None)
    if run and not run.get('handover'):
        if run.get('yield') or run.get('mercmode_rotate_requested'):
            return none('MercMode is moving on to its next game.', pending=True)
        if run.get('phase') != 'playing':
            return none('MercMode is starting the autobot on this game.', pending=True)
        return {'kind': 'mercmode' if run.get('mercmode') else 'screensaver', 'run': run,
                'reason': 'MercMode owns this game' if run.get('mercmode') else 'the autoplay screensaver owns this game'}
    started = linp.get('op') == 'start' and latest.get('state') == 'succeeded'
    # the same start again, never a reset (a replay from boot would restart the game) and never screensaver mode, which
    # belongs to the scheduler's own runs (it brings the game window to the front of that PC)
    resumed = ({k: v for k, v in linp.items() if k not in ('session_id', 'op', 'reset', 'screensaver')}
               | {'session_id': sid, 'op': 'start', 'reset': False}) if started else None
    demo = screensaver.bot_demo(store, sid)
    if demo:                                         # still a bot demo: polite input on a PC someone uses, as it launched
        start = (resumed or {'session_id': sid, 'op': 'start', 'mode': 'auto'}) | {'demo': True} \
            | ({'owns_keyboard': True} if worker_name and worker_name in bot_pcs else {})
        return {'kind': 'bot_demo', 'start': start, 'actor': screensaver.DEMO_ACTOR, 'agent_use': bool(demo.get('agent')),
                'reason': 'a bot demo plays this game'}
    if resumed:
        owned = agent_owned(label, store.get('job', sid.split('-', 1)[-1]))
        if owned and latest.get('agent_use'):
            actor, agent = latest.get('actor') or requester, True       # an agent's test session stays the agent's
        else:
            actor, agent = requester, False
        return {'kind': 'autoplay', 'start': resumed, 'actor': actor, 'agent_use': agent,
                'reason': 'autoplay was started on this game and never stopped'}
    if telemetry.get('running') is True:                    # a bot started on the pad (no job) was driving
        return {'kind': 'telemetry', 'start': {'session_id': sid, 'op': 'start', 'mode': 'auto'}, 'actor': requester,
                'agent_use': False, 'reason': 'an autobot was driving this game'}
    return none('No autobot was driving this game, so F5 leaves your game as it is.')


def message(out: dict) -> str:
    """One line for the operator's toast from an ensure / toggle job's output."""
    title = out.get('title') or 'this game'
    where = f" ({out['worker']})" if out.get('worker') else ''
    action = out.get('action')
    if action == 'started' and out.get('kind'):
        return f'Autobot back in control of {title}{where}.'
    if action == 'started':
        what = f": {out['objective']}" if out.get('objective') else ''
        return f'Autobot started on {title}{where}{what}.'
    return {'restarted': f'The autobot on {title}{where} had stopped reporting: restarted it.',
            'driving': f'The autobot is driving {title}{where}.',
            'already_running': f'The autobot was already driving {title}{where}.',
            'stopped': f'Autobot stopped: you have control of {title}{where}.',
            'already_stopped': f'The autobot was not running on {title}{where}.'}.get(
        action, out.get('reason') or 'Nothing to do.')


class BotControl:
    def __init__(self, store, *, submit, workers, wid, saver=None, prefs=None, server_jobs=None,
                 clock=time.time, sleep=time.sleep, spawn=None):
        self.store, self.submit, self.workers, self.wid = store, submit, workers, wid
        self.saver, self.prefs = saver, prefs
        self.server_jobs = server_jobs if server_jobs is not None else set()
        self.clock, self.sleep = clock, sleep
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.lock = threading.Lock()

    # --- facts ---
    def worker(self, sid: str) -> dict:
        wid = self.wid(sid.split('-', 1)[0])
        return next((w for w in self.workers() if w.get('id') == wid), None) or {'id': wid}

    def runs(self) -> list[dict]:
        from .screensaver import STATE
        return self.store.all(STATE)

    def decide(self, sid: str, requester: str, ignore_job: str = '') -> dict:
        from . import screensaver
        w = self.worker(sid)
        return intent(self.store, sid, screensaver.telemetry_last(sid, self.clock()), runs=self.runs(),
                      requester=requester, bot_pcs=screensaver.settings(self.store).get('bot_pcs') or [],
                      worker_name=w.get('name') or '', ignore_job=ignore_job, now=self.clock())

    # --- worker jobs ---
    def job(self, tool: str, inp: dict, actor: str, *, worker: str, wait: float, queue_wait: float | None = None,
            agent_use: bool = False, origin: dict | None = None) -> tuple[str, dict]:
        """Submit one worker job through the normal path (guards, routing to the session's worker) and wait for it."""
        from .server import JobRequest
        j = self.submit(JobRequest(tool=tool, input=inp, require_worker=worker, agent_use=agent_use), actor, origin or {})
        jid = getattr(j, 'id', None) or (j.get('id') if isinstance(j, dict) else None)
        name = (self.store.get('worker', self.wid(worker)) or {}).get('name') or worker
        what = f"autoplay {inp.get('op')}" if tool == 'autoplay' else tool
        t0 = self.clock()
        while True:
            rec = self.store.get('job', jid) or {}
            state = str(rec.get('state') or '')
            if state == 'succeeded':
                return jid, rec.get('output') or {}
            if state in TERMINAL:
                raise HTTPException(409, f"{what} on {name}: {rec.get('error') or state}")
            waited = self.clock() - t0
            if queue_wait and state == 'queued' and waited >= queue_wait:
                with self.store.lock:
                    cur = self.store.get('job', jid) or {}
                    if cur.get('state') == 'queued':
                        self.store.put('job', jid, cur | {'state': 'failed', 'finished': self.clock(), 'cancel': True,
                                                          'error': f'not picked up by {name} within {queue_wait:.0f} s'})
                raise HTTPException(409, f'{name} did not answer within {queue_wait:.0f} s (offline or busy). '
                                         'Nothing was changed.')
            if waited >= wait:
                raise HTTPException(409, f'{name} did not finish {what} within {wait:.0f} s.')
            self.sleep(0.5)

    def status(self, sid: str, requester: str, origin: dict) -> bool:
        _, out = self.job('autoplay', {'session_id': sid, 'op': 'status'}, requester, worker=sid.split('-', 1)[0],
                          wait=STATUS_WAIT_S, queue_wait=QUEUE_WAIT_S, origin=origin)
        return bool((out.get('result') or {}).get('running'))

    def settled(self, sid: str, requester: str, origin: dict) -> bool:
        """True once the worker no longer reports the bot running (a stopped thread may take a moment to end)."""
        t0 = self.clock()
        while self.clock() - t0 < STOP_SETTLE_S:
            if not self.status(sid, requester, origin):
                return True
            self.sleep(2.0)
        return False

    # --- in-server job records ---
    def record(self, tool: str, sid: str, sess: dict, actor: str, origin: dict | None, extra: dict) -> dict:
        from . import operator_guard
        from .models import Job, JobState
        job = Job(tool=tool, input={'session_id': sid, 'game_id': sess.get('game_id'), **extra}, state=JobState.RUNNING,
                  started=self.clock(), actor=actor, agent_use=operator_guard.is_agent(actor),
                  origin={'via': tool, **{k: v for k, v in (origin or {}).items() if k != 'via'}})
        self.store.put('job', job.id, job.model_dump(mode='json'))
        self.server_jobs.add(job.id)
        return job.model_dump(mode='json')

    def progress(self, jid: str, pct: float, msg: str):
        with self.store.lock:
            j = self.store.get('job', jid) or {}
            j['progress'] = {'pct': round(float(pct), 1), 'msg': msg, 'ts': self.clock()}
            j['progress_log'] = (j.get('progress_log') or [])[-49:] + [msg]
            self.store.put('job', jid, j)

    def finish(self, jid: str, state: str, out: dict | None, err: str | None, actor: str, action: str):
        with self.store.lock:
            j = self.store.get('job', jid) or {}
            if out is not None:
                out = out | {'message': message(out)}
            self.store.put('job', jid, j | {'state': state, 'finished': self.clock(), 'output': out, 'error': err})
            self.server_jobs.discard(jid)
        self.store.audit(actor, action, (j.get('input') or {}).get('session_id', ''),
                         {'job': jid, 'state': state, 'error': err, 'action': (out or {}).get('action')})

    def running_record(self, tool: str, sid: str) -> dict | None:
        """The same request still in flight for this session (a second key press joins it)."""
        for j in self.store.jobs(states=('running',)):
            if j.get('tool') == tool and (j.get('input') or {}).get('session_id') == sid and j.get('id') in self.server_jobs:
                return j
        return None

    def background(self, rec: dict, steps, actor: str, action: str):
        def go():
            try:
                out, state, err = steps(lambda pct, msg: self.progress(rec['id'], pct, msg)), 'succeeded', None
            except HTTPException as e:
                out, state, err = None, 'failed', str(e.detail)
            except Exception as e:                       # noqa: BLE001 - the job says what broke
                out, state, err = None, 'failed', f'{type(e).__name__}: {e}'
            self.finish(rec['id'], state, out, err, actor, action)
        try:
            self.spawn(go)
        except Exception as exc:
            self.finish(rec['id'], 'failed', None, f'The background task could not start ({type(exc).__name__}); '
                                                   'nothing was changed.', actor, action)
            raise HTTPException(503, 'The autobot request could not start; nothing was changed.') from exc
        return self.store.get('job', rec['id']) or rec

    def base(self, sid: str, sess: dict) -> dict:
        return {'session_id': sid, 'game_id': sess.get('game_id'), 'title': sess.get('title') or sess.get('game_id') or '',
                'worker': self.worker(sid).get('name') or sid.split('-', 1)[0]}

    # --- F5 ---
    def ensure(self, sid: str, actor: str, reason: str = 'F5', origin: dict | None = None) -> dict:
        sid, sess = follow(self.store, sid)
        if self.prefs is not None and sess.get('state') == 'running':
            try:
                self.prefs.force(sid)                    # the game's saved menu settings go back on as well
            except Exception as exc:                     # noqa: BLE001 - settings never block the bot
                self.store.audit(actor, 'game_prefs.force_failed', sid, {'error': str(exc)[:300]})
        with self.lock:
            existing = self.running_record(ENSURE_TOOL, sid)
            if existing:
                return existing
            decision = self.decide(sid, actor)
            rec = self.record(ENSURE_TOOL, sid, sess, actor, origin, {'reason': reason[:40], 'kind': decision['kind']})
        base = self.base(sid, sess) | {'kind': decision['kind'], 'reason': decision['reason']}
        if not decision['kind']:
            self.finish(rec['id'], 'succeeded', base | {'action': 'pending' if decision.get('pending') else 'none'},
                        None, actor, 'autoplay.ensure')
            return self.store.get('job', rec['id'])
        return self.background(rec, lambda say: self.ensure_steps(sid, sess, decision, actor, reason, say),
                               actor, 'autoplay.ensure')

    def ensure_steps(self, sid, sess, decision, actor, reason, say) -> dict:
        from . import screensaver
        base = self.base(sid, sess) | {'kind': decision['kind'], 'reason': decision['reason']}
        origin = {'via': f'{reason} recovery', 'session_id': sid, 'requested_by': actor}
        live = liveness(screensaver.telemetry_last(sid, self.clock()))
        if live == 'driving':
            return base | {'action': 'driving'}
        say(15, f"Asking {base['worker']} whether the autobot runs")
        running = self.status(sid, actor, origin)
        restarted, own_stop = False, ''
        if running and live == 'unknown':
            return base | {'action': 'driving', 'detail': 'The PC reports the autobot running; its live report follows.'}
        if running:
            say(35, 'The autobot stopped reporting: stopping it')
            own_stop = self.stop_for(sid, decision, actor, origin)
            if not self.settled(sid, actor, origin):
                raise HTTPException(409, 'The stuck autobot did not stop within 20 s; press F5 again in a moment.')
            restarted = True
        current = self.decide(sid, actor, ignore_job=own_stop)      # a Stop or a takeover meanwhile wins
        if not current['kind'] or current.get('pending'):
            return base | {'action': 'none', 'reason': current['reason']}
        say(65, 'Starting the autobot again')
        return base | {'action': 'restarted' if restarted else 'started', **self.start_for(sid, current, actor, reason, origin)}

    def stop_for(self, sid, decision, actor, origin) -> str:
        from . import screensaver
        if decision['kind'] in ('mercmode', 'screensaver'):
            jid, _ = self.job('autoplay', {'session_id': sid, 'op': 'stop'}, screensaver.ACTOR,
                              worker=decision['run']['worker_id'], wait=STOP_WAIT_S, queue_wait=QUEUE_WAIT_S,
                              agent_use=True, origin=origin | {'via': 'autoplay screensaver', 'recovery': origin['via']})
            return jid
        jid, _ = self.job('autoplay', {'session_id': sid, 'op': 'stop'}, decision['actor'], worker=sid.split('-', 1)[0],
                          wait=STOP_WAIT_S, queue_wait=QUEUE_WAIT_S, agent_use=decision['agent_use'], origin=origin)
        return jid

    def start_for(self, sid, decision, actor, reason, origin) -> dict:
        if decision['kind'] in ('mercmode', 'screensaver'):
            jid = self.saver.restart_bot(sid, requested_by=actor, why=f'{reason} recovery') if self.saver else None
            if not jid:
                raise HTTPException(409, 'MercMode moved on from this game; nothing was started.')
            out = self.wait(jid, START_WAIT_S)
        else:
            _, out = self.job('autoplay', decision['start'], decision['actor'], worker=sid.split('-', 1)[0],
                              wait=START_WAIT_S, queue_wait=QUEUE_WAIT_S, agent_use=decision['agent_use'],
                              origin=origin | {'kind': decision['kind']})
        res = out.get('result') or {}
        if not (res.get('started') or res.get('already_running')):
            raise HTTPException(409, str(res.get('error') or 'The autobot did not confirm that it started.'))
        return {'objective': res.get('objective') or res.get('started') or res.get('already_running'),
                'mode': res.get('mode')}

    def wait(self, jid: str, limit: float) -> dict:
        t0 = self.clock()
        while self.clock() - t0 < limit:
            rec = self.store.get('job', jid) or {}
            if rec.get('state') == 'succeeded':
                return rec.get('output') or {}
            if rec.get('state') in TERMINAL:
                raise HTTPException(409, f"autoplay start: {rec.get('error') or rec.get('state')}")
            self.sleep(0.5)
        raise HTTPException(409, f'The autobot start was not confirmed within {limit:.0f} s.')

    # --- F3 ---
    def toggle(self, sid: str, body: ToggleIn, actor: str, origin: dict | None = None, *, automated: bool = False) -> dict:
        from .background_testing import agent_owned
        if body.op not in ('toggle', 'start', 'stop'):
            raise HTTPException(422, 'op: toggle | start | stop')
        sid, sess = follow(self.store, sid)
        title = sess.get('title') or sess.get('game_id') or 'That game'
        if sess.get('state') != 'running':
            raise HTTPException(409, f'{title} has ended. Open the game that is playing and press F3 there.')
        label = self.store.get('slabel', sid) or {}
        if automated and not agent_owned(label, self.store.get('job', sid.split('-', 1)[-1])):
            raise HTTPException(409, "That game is the operator's session; automated tasks can't start or stop its "
                                     'autobot.')
        if label.get('warm'):
            raise HTTPException(409, f'{title} waits paused for its MercMode turn; press F3 on the game that is playing.')
        w = self.worker(sid)
        if not w.get('online'):
            raise HTTPException(409, f"{w.get('name') or 'The PC'} (running {title}) is offline, so the autobot "
                                     "can't be reached there right now.")
        with self.lock:
            existing = self.running_record(TOGGLE_TOOL, sid)
            if existing:
                return existing
            rec = self.record(TOGGLE_TOOL, sid, sess, actor, origin, {'op': body.op, 'source': body.source[:40]})
        return self.background(rec, lambda say: self.toggle_steps(sid, sess, body, actor, say), actor, 'autoplay.toggle')

    def toggle_steps(self, sid, sess, body: ToggleIn, actor, say) -> dict:
        base = self.base(sid, sess)
        origin = {'via': body.source[:40] or 'F3', 'session_id': sid}
        say(10, f"Asking {base['worker']} whether the autobot runs")
        running = self.status(sid, actor, origin)
        want = ('stop' if running else 'start') if body.op == 'toggle' else body.op
        if want == 'start' and running:
            return base | {'action': 'already_running', 'running': True}
        if want == 'stop' and not running:
            return base | {'action': 'already_stopped', 'running': False}
        if want == 'stop':
            say(50, 'Handing control back')
            self.job('autoplay', {'session_id': sid, 'op': 'stop'}, actor, worker=sid.split('-', 1)[0],
                     wait=STOP_WAIT_S, queue_wait=QUEUE_WAIT_S, origin=origin)
            return base | {'action': 'stopped', 'running': False}
        say(50, 'Starting the autobot')
        _, out = self.job('autoplay', {'session_id': sid, 'op': 'start', 'mode': 'auto', 'continuous': body.continuous,
                                       'assist': body.assist}, actor, worker=sid.split('-', 1)[0],
                          wait=START_WAIT_S, queue_wait=QUEUE_WAIT_S, origin=origin)
        res = out.get('result') or {}
        if not (res.get('started') or res.get('already_running')):
            raise HTTPException(409, str(res.get('error') or 'The autobot did not confirm that it started.'))
        return base | {'action': 'started', 'running': True, 'mode': res.get('mode'),
                       'objective': res.get('objective') or res.get('started') or res.get('already_running')}

    # --- bot hot reload (gbox/hot_reload.py, docs/hot-update.md) ---
    def bot_reload(self, name: str, body: ReloadIn, actor: str, origin: dict | None = None) -> dict:
        """That PC's bot_reload tool: its changed bot modules reload in place, the games keep running, every autobot
        restarts in its session with its own input and job. With wait_s, the answer carries the worker's result, and a
        session whose bot did not come back goes through F5's path (ensure -> Screensaver.restart_bot for MercMode)."""
        from .server import JobRequest
        cands = [w for w in self.workers() if w.get('name') == name or w.get('id') == self.wid(name)]
        w = next((x for x in cands if x.get('online')), cands[0] if cands else None)
        if w is None:
            raise HTTPException(404, f"no gBox worker '{name}'")
        if not w.get('online'):
            raise HTTPException(409, f"{w['name']} is offline: its bots can't be reloaded now.")
        if RELOAD_TOOL not in (w.get('tools') or []):
            raise HTTPException(409, f"{w['name']} runs gBox code without {RELOAD_TOOL}: bot changes go live there with a "
                                     'service restart.')
        inp = {'modules': list(body.modules), 'settle_s': body.settle_s}
        origin = {**(origin or {}), 'via': 'bot reload'}
        info = {'id': w['id'], 'name': w['name'], 'os': w.get('os')}
        if body.wait_s <= 0:
            j = self.submit(JobRequest(tool=RELOAD_TOOL, input=inp, require_worker=w['id']), actor, origin)
            rec = j.model_dump(mode='json') if hasattr(j, 'model_dump') else dict(j)
            if rec.get('state') == 'rejected':
                raise HTTPException(409, rec.get('error') or 'the bot reload was rejected')
            return {'job_id': rec.get('id'), 'state': rec.get('state'), 'worker': info}
        jid, out = self.job(RELOAD_TOOL, inp, actor, worker=w['id'], wait=min(body.wait_s, RELOAD_WAIT_S),
                            queue_wait=QUEUE_WAIT_S, origin=origin)
        result = out.get('result') or {}
        recovered = []
        for r in result.get('restarted') or []:
            if r.get('recover') and r.get('session_id'):
                try:
                    rec = self.ensure(r['session_id'], actor, reason='bot reload', origin=origin)
                    recovered.append({'session_id': r['session_id'], 'job_id': rec.get('id'), 'state': rec.get('state')})
                except HTTPException as exc:
                    recovered.append({'session_id': r['session_id'], 'error': str(exc.detail)})
        self.store.audit(actor, 'autoplay.bot_reload', w['id'], {'job': jid, 'ok': result.get('ok'),
                                                                 'reloaded': result.get('reloaded'),
                                                                 'reason': str(result.get('reason') or '')[:300]})
        return {'job_id': jid, 'state': 'succeeded', 'worker': info, 'result': result, 'recovered': recovered}


def install(app, store, auth, *, submit, workers, wid, automated, origin_dep, server_jobs, saver=None, prefs=None):
    ctl = BotControl(store, submit=submit, workers=workers, wid=wid, saver=saver, prefs=prefs, server_jobs=server_jobs)
    app.state.bot_control = ctl

    @app.post('/api/sessions/{sid}/autoplay/ensure')
    def autoplay_ensure(sid: str, body: EnsureIn, actor=Depends(auth), origin=Depends(origin_dep)):
        """F5: keep the autobot of a bot session driving (never starts one on the operator's own game)."""
        if automated(actor, origin):
            raise HTTPException(409, 'F5 recovery is an operator request; automation keeps its own bots running.')
        return ctl.ensure(sid, actor, body.reason or 'F5', origin)

    @app.post('/api/sessions/{sid}/autoplay')
    def autoplay_toggle(sid: str, body: ToggleIn, actor=Depends(auth), origin=Depends(origin_dep)):
        """F3: start or stop the autobot on the session a gBox window shows, from any PC."""
        return ctl.toggle(sid, body, actor, origin, automated=automated(actor, origin))

    @app.post('/api/workers/{name}/bot-reload')
    def worker_bot_reload(name: str, body: ReloadIn | None = None, actor=Depends(auth), origin=Depends(origin_dep)):
        """Reload that PC's bot modules in place (no service restart: the games and MercMode's warm pool keep running).
        The operator's or the deploy script's request (x-gbox-actor: deploy); automation never restarts the bots."""
        if automated(actor, origin):
            raise HTTPException(403, 'Only the operator or the deploy script reloads the bots.')
        return ctl.bot_reload(name, body or ReloadIn(), actor, origin)

    return ctl
