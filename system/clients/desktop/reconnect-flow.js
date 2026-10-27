/* Reconnect to the Spark and put MercMode on screen, whatever it takes (operator 2026-10-24: "when I click on this button,
   I want it doing whatever it takes ... showing it reconnecting and rebuilding the platform. I want F5 to just solve and fix
   any issue"; "90% of the time I open gBox it is to watch an autobot MercMode play").

   Steps, each retried before the next escalation, rendered as a live flowchart over gBox's 3D visualizer:
     spark    the Spark answers (waits for the connection probe; if it stays down, restarts gbox.service over SSH and waits)
     library  this window uses the Spark's library, not This PC's (switching reloads the window, the flow resumes after it)
     mercmode a MercMode game runs on the chosen PC (turns MercMode on there if needed and waits for its launch)
     stream   its picture is fresh (asks that PC for a new encoder when it is not)
     pip      the game is shown in picture-in-picture (an operator's reconnect then asks io.ensureBot to keep its
              autobot driving)
   Automatic reconnects never restart the shared service. An explicit reconnect action may restart it after a full
   minute without an answer; this allows a planned service restart to finish before considering another one.

   A picture already on screen is kept (operator 2026-10-26, i9-NUC: the app watching the Spark's MercMode game was pulled
   into this PC's own "running" Mercenaries 3D session whose worker had been offline for 43 h, and reloaded over and over):
     - a PiP that shows a game is never closed or replaced by a reconnect; the flow repairs that game's picture instead.
       Only a PiP whose session ended, or that MercMode parked for its next title (warm), gives way to the running
       MercMode game, the next title on that same PC first.
     - a MercMode run on a PC that is offline (its session health says worker_online false) is never put on screen.
     - the library switch never reloads a window with a PiP on it, and reloads at most once per failure (RELOAD_KEY).
     - backoff(failures) paces the automatic poll: 5 s after the first failure, doubling to a minute.

   F5 is one deterministic recovery (operator 2026-10-26: "when i encounter issues. I just want to press F5 reconnect it to
   the source and reboot the stream and build and update the gbox app and get the pip stream back autoplaying
   seamlessly"). run({ f5: true }) - F5 and the dialog's Try again - goes through F5_STEPS; automatic reconnects keep the
   five steps and the rules above:
     update   this PC's gBox first: main.js client:update fast-forwards its git checkout to GitHub's main (only on main,
              with no local changes; app-update.cjs), and when anything new arrived - there or in the Spark's client - the
              window reloads once (new main-process or worker code relaunches gBox, when this PC is idle). The F5 goes on
              after the reload: F5_KEY (localStorage) carries it once, for F5_RESUME_MS
     spark, library   as above
     mercmode MercMode's CURRENT game: host.current_run.session_id (playing / starting) of an online PC - never a game of
              the warm pool (host.warm, paused), an ended session or an offline PC's. A title still launching is waited
              for (TITLE_WAIT_MS); the PiP's own transition shows it meanwhile and follows it when it plays. The
              operator's own game on this PC stays on screen; with no MercMode game the game on screen is repaired
     stream   live within F5_FIRST_LOOK_MS (3 s), else a new encoder (session_op restart_stream) and a wait for a fresh
              frame (stream/health age_s < 3); a picture that never comes back asks MercMode again
     pip      that game in picture-in-picture: a PiP showing another game moves to it in place (same window and bounds;
              asked again from where it is when the PiP's own follower moved it meanwhile)
     bot      POST /api/sessions/{sid}/autoplay/ensure (gbox/bot_control.py), and its answer
     view     the main window's Sessions view shows the same game, never a paused warm one
   An F5 never waits behind an automatic reconnect: it takes over, and the older run stops at its next step. */
(function (root) {
  'use strict';
  const STEPS = [
    ['spark', 'Reach the Spark', 'control plane'], ['library', 'Spark library', 'this window'],
    ['mercmode', 'MercMode game', 'autobot'], ['stream', 'Live picture', 'encoder'], ['pip', 'Picture-in-picture', 'watch'],
  ];
  const F5_STEPS = [['update', 'Update gBox', 'this PC + Spark'], ...STEPS, ['bot', 'Autobot', 'in control'],
    ['view', 'Main window', 'same game']];
  const RESUME_KEY = 'gbox.reconnect.resume';
  const RELOAD_KEY = 'gbox.reconnect.reloaded';     // when this window last reloaded itself to switch libraries
  const RELOAD_ONCE_MS = 120000;                     // a second reload this soon after one is refused: one per failure
  const F5_KEY = 'gbox.f5.resume';                   // localStorage: the F5 that an update reload (or relaunch) interrupted
  const F5_RESUME_MS = 180000;                       // ... goes on after it when gBox is back within 3 minutes
  const FRESH_S = 3;                                 // stream/health age_s below this: the picture is live
  const F5_FIRST_LOOK_MS = 3000, F5_RESTART_WAIT_MS = 25000;
  const TITLE_WAIT_MS = 45000;                       // a MercMode title that is still launching
  const F5_STREAM_BUDGET_MS = 40000;                 // no further stream attempt this far into an F5 (it ends in ~45 s)
  const BOT_WAIT_MS = 15000;                         // the autobot check's answer in the dialog (a later one is toasted)
  const LINGER_MS = 2500;                            // a finished F5 leaves its results up this long
  const SWITCH_TRIES = 3;                            // F5: in-place PiP moves, 1 s apart, before it is closed and reopened
  const BACKOFF_MS = [5000, 10000, 20000, 40000, 60000];
  // the automatic poll's delay after `failures` attempts in a row (0 = the first retry): 5 s doubling to a minute
  const backoff = failures => BACKOFF_MS[Math.max(0, Math.min(BACKOFF_MS.length - 1, Number.isFinite(failures) ? Math.trunc(failures) : 0))];
  const ENDED = ['ended', 'missing'];
  const PLAYING = ['playing', 'starting'];
  const fresh = list => list.map(([id, label, sub]) => ({ id, label, sub, status: 'wait', detail: '' }));
  // a session MercMode owns on some PC: its current game, the one before it, or a game waiting in its warm pool
  const mercOwned = (data, sid) => !!sid && (data?.hosts || []).some(h => h.current_run?.session_id === sid
    || h.current_run?.mercmode_predecessor?.session_id === sid || (h.warm || []).some(w => w?.session_id === sid));
  function create({ io, render = () => {}, sleep = ms => new Promise(r => setTimeout(r, ms)), now = Date.now }) {
    let busy = null, busyF5 = false, generation = 0;
    const state = { steps: fresh(STEPS), done: false, error: '', f5: false };
    const clone = () => ({ ...state, steps: state.steps.map(s => ({ ...s })) });
    // a run that an F5 took over stops at its next step and never writes into the F5's dialog
    const alive = ctx => { if (ctx.id !== generation) throw Object.assign(Error('An F5 took over this reconnect.'), { superseded: true }); };
    const step = id => state.steps.find(s => s.id === id);
    const set = (ctx, id, status, detail = '') => { alive(ctx); const s = step(id); if (s) Object.assign(s, { status, detail }); render(clone()); };
    const shownPip = () => { try { return io.pipSession() || null; } catch { return null; } };
    const health = async sid => { if (!io.health) return null; try { return await io.health(sid); } catch { return null; } };
    const session = async sid => { if (!io.session) return null; try { return await io.session(sid); } catch { return null; } };
    const ask = async (fn, ...args) => { try { return await fn(...args); } catch { return null; } };
    // the game a PiP shows is kept unless its session ended or MercMode parked it for the next title (warm); an offline
    // PC or an unreadable answer keeps it too
    async function pipKept(sid) {
      const row = await session(sid);
      if (row && (row.warm || ENDED.includes(row.state))) return false;
      const h = await health(sid); return !h || !ENDED.includes(h.state);
    }
    // a MercMode run can be shown only while its PC answers (gbox/server.py stream health: worker_online, #2870)
    async function reachable(sid) { const h = await health(sid); return !h || (h.worker_online !== false && !ENDED.includes(h.state)); }
    async function waitFor(ctx, check, ms, every = 1000) {
      const end = now() + ms;
      for (;;) {
        alive(ctx);
        try { const value = await check(); if (value) return value; } catch { /* keep trying until the deadline */ }
        if (now() >= end) return null;
        await sleep(every);
      }
    }
    async function spark(ctx, allowRestart) {
      set(ctx, 'spark', 'run', 'Checking the Spark…');
      if (await waitFor(ctx, async () => (await io.status())?.remote?.ready, 60000)) return set(ctx, 'spark', 'ok', 'The Spark answers');
      if (!allowRestart) throw Object.assign(Error('The Spark is not answering. Automatic reconnect will keep checking; Try again can repair the connection.'), { step: 'spark' });
      set(ctx, 'spark', 'run', 'No answer: restarting gBox on the Spark…');
      try { await io.restartSpark(); } catch (error) { set(ctx, 'spark', 'run', 'Restart request failed (' + error.message + '); still waiting…'); }
      if (await waitFor(ctx, async () => (await io.status())?.remote?.ready, 120000, 2000)) return set(ctx, 'spark', 'ok', 'The Spark is back');
      throw Object.assign(Error('The Spark is not answering on the network. This PC\'s library still works.'
        + (ctx.f5 ? ' Check that the Spark is on and connected, then press F5 again.' : '')), { step: 'spark' });
    }
    // what an F5 carries over a reload: its start (for the total time) and the update step's result
    const carry = ctx => ({ started: ctx.started, update: { status: step('update')?.status === 'warn' ? 'warn' : 'ok',
      detail: step('update')?.detail || '' } });
    async function library(ctx) {
      const st = await io.status();
      if (st?.mode === 'remote') return set(ctx, 'library', 'ok', 'Using the Spark library');
      // a reload closes the PiP (main.js restores the window on navigation): a game on screen stays on screen
      if (shownPip()) return set(ctx, 'library', 'ok', 'Keeping the game on screen; this window stays on its library');
      const last = Number(io.recall?.(RELOAD_KEY)) || 0;
      if (last && now() - last < RELOAD_ONCE_MS) throw Object.assign(Error('This window is still on This PC\'s library after a reload. Choose the Spark library from the connection button.'), { step: 'library' });
      set(ctx, 'library', 'run', 'Switching this window to the Spark…');
      io.remember(RESUME_KEY, '1');
      io.remember(RELOAD_KEY, String(Math.max(1, now())));
      try { await io.select('remote'); }
      catch (error) { io.forget(RESUME_KEY); throw Object.assign(Error(error.message || String(error)), { step: 'library' }); }
      alive(ctx);
      if (ctx.f5) io.f5Mark?.(carry(ctx));             // the reload goes on with this F5, not an automatic reconnect
      await io.reload();
      return 'reloading';
    }
    async function mercmode(ctx) {
      // the game already on screen is the one being reconnected (never closed for another host's game)
      const shown = shownPip();
      if (shown && await pipKept(shown)) { set(ctx, 'mercmode', 'ok', 'Keeping the game already on screen'); return shown; }
      // Only a MercMode game that is already running is put on screen (operator 2026-10-24: "if it's not started, it
      // shouldn't even mention it ... it should just be trying to reconnect to the central server").
      set(ctx, 'mercmode', 'run', 'Checking for a running MercMode game…');
      const data = await waitFor(ctx, () => io.api('/api/mercmode'), 20000, 2000);
      // the PC whose game was on screen keeps the screen with its next MercMode title, else the usual choice
      const after = shown && (data?.hosts || []).find(h => h.online !== false && h.current_run?.session_id
        && PLAYING.includes(h.current_run.phase)
        && (h.current_run.mercmode_predecessor?.session_id === shown || (h.id && shown.startsWith(h.id + '-'))));
      const host = after || (data ? io.pickHost(data) : null);
      const run = host?.current_run;
      if (!run?.session_id || !PLAYING.includes(run.phase)) { set(ctx, 'mercmode', 'wait', ''); return null; }
      if (!await reachable(run.session_id)) {       // a stale "playing" run of a PC that went offline: nothing to show
        set(ctx, 'mercmode', 'err', `${run.title || 'Game'} on ${host.name}: that PC is offline, so there is nothing to show yet`);
        return null;
      }
      set(ctx, 'mercmode', 'ok', `${run.title || 'Game'} on ${host.name}`);
      return run.session_id;
    }
    // F5: one PC's MercMode run, checked. 'none' (no run), 'loading' (its next title is still launching, or the status
    // still names a game that just ended or was parked), 'offline', or {sid, host, run}: its current game
    async function verdict(ctx, host) {
      const run = host.current_run;
      if (!run) return 'none';
      if (run.phase === 'launching') return 'loading';
      if (!run.session_id || !PLAYING.includes(run.phase)) return 'none';
      if ((host.warm || []).some(w => w?.session_id === run.session_id)) return 'loading';    // never a parked game
      const row = await session(run.session_id);
      alive(ctx);
      if (row?.worker_online === false) return 'offline';
      if (row && (row.warm || row.state !== 'running')) return 'loading';                   // ended: the run moves on
      const h = await health(run.session_id);
      alive(ctx);
      if (h?.worker_online === false) return 'offline';
      if (h && ENDED.includes(h.state)) return 'loading';
      return { sid: run.session_id, host, run };
    }
    // F5: which PC's MercMode run to show. The PC whose game is on screen first - its next title keeps the screen, so a
    // title switch there is waited for - then this PC's own run, then any PC's.
    async function choose(ctx, data) {
      const shown = shownPip(), worker = io.workerName?.() || '';
      const hosts = (data?.hosts || []).filter(h => h.online !== false);
      const onScreen = shown && hosts.find(h => mercOwned({ hosts: [h] }, shown) || (h.id && String(shown).startsWith(h.id + '-')));
      let offline = null, loading = null;
      for (const host of [...new Set([onScreen, hosts.find(h => h.name === worker), ...hosts].filter(Boolean))]) {
        const v = await verdict(ctx, host);
        if (v?.sid) return v;
        if (v === 'loading' && host === onScreen) return { loading: host };
        if (v === 'loading') loading ||= host;
        if (v === 'offline') offline ||= host;
      }
      return loading ? { loading } : offline ? { offline } : null;
    }
    // F5: the game to bring back. {sid, host, run}: MercMode's current game; {sid, own, native}: the operator's own game
    // on this PC, kept where it is; {loading}: a title still launching after TITLE_WAIT_MS; null: no MercMode game
    async function current(ctx) {
      set(ctx, 'mercmode', 'run', 'Asking MercMode for its current game…');
      const deadline = now() + TITLE_WAIT_MS;
      for (;;) {
        const data = await waitFor(ctx, () => io.api('/api/mercmode'), 20000, 2000);
        const own = io.ownGame ? await ask(io.ownGame) : null;
        alive(ctx);
        if (own?.sid && !mercOwned(data, own.sid)) {
          set(ctx, 'mercmode', 'ok', 'Your own game on this PC stays on screen');
          return { sid: own.sid, own: true, native: !!own.native };
        }
        if (!data) { set(ctx, 'mercmode', 'err', 'MercMode did not answer within 20 s (the Spark may be busy). Press F5 again in a moment.'); return null; }
        const pick = await choose(ctx, data);
        if (pick?.sid) { set(ctx, 'mercmode', 'ok', `${pick.run.title || 'Game'} on ${pick.host.name}`); return pick; }
        if (pick?.offline) {
          const run = pick.offline.current_run;
          set(ctx, 'mercmode', 'err', `${run.title || 'Game'} on ${pick.offline.name}: that PC is offline, so there is nothing to show. Relaunch its worker, then press F5.`);
          return null;
        }
        if (!pick?.loading) { set(ctx, 'mercmode', 'wait', ''); return null; }
        const title = pick.loading.current_run?.title || 'the next title';
        if (now() >= deadline) {
          set(ctx, 'mercmode', 'warn', `${title} is still loading on ${pick.loading.name}: the PiP follows it when it plays (press F5 again if it does not)`);
          return { loading: pick.loading };
        }
        set(ctx, 'mercmode', 'run', `MercMode is switching titles: loading ${title} on ${pick.loading.name}…`);
        await sleep(2000);
      }
    }
    // F5 with no MercMode game: the game this window shows, if its session (or its running replacement) plays
    async function repairable(ctx) {
      const sid = io.shownSession ? await ask(io.shownSession) : shownPip();
      alive(ctx);
      if (!sid) return null;
      return io.repairTarget ? ask(io.repairTarget, sid) : sid;
    }
    async function stream(ctx, sid, f5 = false) {
      set(ctx, 'stream', 'run', 'Checking the picture…');
      const live = async () => { const h = await io.api(`/api/sessions/${encodeURIComponent(sid)}/stream/health`);
        return h && h.age_s != null && h.age_s < FRESH_S && h.state === 'running'; };
      if (await waitFor(ctx, live, f5 ? F5_FIRST_LOOK_MS : 6000)) { set(ctx, 'stream', 'ok', 'Live'); return true; }
      set(ctx, 'stream', 'run', f5 ? 'No fresh picture within 3 s: rebooting its stream (new encoder)…' : 'Picture is stale: asking for a new encoder…');
      alive(ctx);
      await io.api('/api/jobs', { tool: 'session_op', agent_use: false, require_worker: sid.split('-')[0],
        input: { session_id: sid, op: 'restart_stream', args: {} } }).catch(() => null);
      ctx.restarted = sid;
      if (await waitFor(ctx, live, f5 ? F5_RESTART_WAIT_MS : 30000, 1500)) { set(ctx, 'stream', 'ok', f5 ? 'Live again (stream rebooted)' : 'Live again'); return true; }
      set(ctx, 'stream', 'err', f5 ? 'Still no fresh picture after a new encoder; the last frame stays up. Press F5 again; if it stays frozen, use Report & fix in the PiP menu.'
        : 'Still no fresh picture; showing the last frame while it recovers');
      return false;
    }
    async function pip(ctx, sid, { f5 = false, own = false } = {}) {
      set(ctx, 'pip', 'run', 'Opening picture-in-picture…');
      const shown = shownPip();
      if (shown === sid) {
        if (f5 && ctx.restarted === sid) io.reconnectPicture?.(sid);      // the new encoder's picture on a new connection
        return set(ctx, 'pip', 'ok', own ? 'Keeping your game on screen' : 'Showing');
      }
      if (f5 && own) return set(ctx, 'pip', 'ok', 'Your game stays where it is');
      if (f5 && shown && io.pipSwitch) {            // the PiP moves to it in place: the same window, bounds and aspect
        // a PiP that its own follower moved meanwhile (its MercMode or continuity poll) is moved again from where it is:
        // closing and reopening it needs the native window helper, which may be slow or stuck (operator 2026-10-27)
        for (let attempt = 0; attempt < SWITCH_TRIES; attempt++) {
          alive(ctx);
          const from = shownPip();
          if (from === sid) return set(ctx, 'pip', 'ok', 'Switched the PiP to it');
          if (!from) break;                          // the PiP closed meanwhile: it opens again below
          if (await ask(io.pipSwitch, from, sid)) return set(ctx, 'pip', 'ok', 'Switched the PiP to it');
          if (attempt + 1 < SWITCH_TRIES) await sleep(1000);
        }
      }
      if (shown) {                                   // never closes a picture that still plays; only an ended one gives way
        if (!f5 && await pipKept(shown)) return set(ctx, 'pip', 'ok', 'Keeping the game already on screen');
        alive(ctx);
        try { await io.pipRestore(); }
        catch (error) {
          if (!f5) throw error;
          throw Object.assign(Error(`The picture-in-picture could not move to it (${error.message || error}). Press F5 again.`), { step: 'pip' });
        }
      }
      alive(ctx);
      try { await io.pipEnter(sid); }
      catch (error) {
        if (!f5) throw error;
        throw Object.assign(Error(`Picture-in-picture did not open (${error.message || error}). Press F5 again.`), { step: 'pip' });
      }
      const after = shownPip();                      // a saved view came back meanwhile: the PiP still moves to this game
      if (f5 && after && after !== sid && io.pipSwitch) await ask(io.pipSwitch, after, sid);
      set(ctx, 'pip', 'ok', 'Showing');
    }
    // F5: the control plane brings the autobot back (gbox/bot_control.py decides: never the operator's own game without
    // one); its answer is shown here when it comes within BOT_WAIT_MS, else toasted when it comes (index.html). A
    // MercMode game left without its autobot is flagged; any other game may well have none.
    async function bot(ctx, sid, { expected = true } = {}) {
      if (!io.ensureBot) return set(ctx, 'bot', 'ok', 'Not checked from this window');
      set(ctx, 'bot', 'run', 'Asking the control plane to keep the autobot driving…');
      let job;
      try { job = await io.ensureBot(sid); }
      catch (error) { return set(ctx, 'bot', 'err', `The autobot could not be checked (${error.message || error}). Press F3 to start it.`); }
      if (!job) return set(ctx, 'bot', 'ok', 'Checked moments ago');
      let done = job;
      if (io.jobResult && ['queued', 'running'].includes(job.state)) {
        set(ctx, 'bot', 'run', job.progress?.msg || 'The control plane is checking the autobot…');
        try { done = await io.jobResult(job, BOT_WAIT_MS); }
        catch (error) {
          const late = /still running/i.test(String(error.message || error));
          return set(ctx, 'bot', late ? 'ok' : 'err', late ? 'Still checking; its answer pops up when it is done'
            : `${error.message || error}. Press F3 to start the autobot.`);
        }
      }
      const out = done?.output || {};
      set(ctx, 'bot', expected && out.action === 'none' ? 'warn' : 'ok', out.message || out.reason || 'Autobot checked');
    }
    async function view(ctx, sid) {
      if (!io.mainFollow) return;
      set(ctx, 'view', 'run', 'The main window follows the game…');
      let out;
      try { out = await io.mainFollow(sid); }
      catch (error) { return set(ctx, 'view', 'warn', `The main window did not follow (${error.message || error})`); }
      set(ctx, 'view', out ? 'ok' : 'warn', out === 'same' ? 'Already on it' : out ? 'Showing it in Sessions'
        : 'The main window is still loading; open Sessions to see the game');
    }
    async function update(ctx) {
      if (!io.update) return set(ctx, 'update', 'ok', 'Not checked from this window');
      set(ctx, 'update', 'run', 'Looking for a gBox update…');
      let plan;
      try { plan = await io.update(); }
      catch (error) { return set(ctx, 'update', 'warn', `The update check failed (${error.message || error}); this F5 goes on with the current version`); }
      alive(ctx);
      const status = plan?.status === 'warn' ? 'warn' : 'ok';
      if (!plan?.reload) return set(ctx, 'update', status, plan?.detail || 'Up to date');
      set(ctx, 'update', 'run', `${plan.detail}: reloading gBox…`);
      const info = { started: ctx.started, update: { status, detail: plan.detail } };
      if (await io.applyUpdate(info) !== false) return 'reloading';
      set(ctx, 'update', 'warn', `${plan.detail}; the reload did not happen, so this F5 goes on with the current version`);
    }
    // F5 after the Spark and its library: MercMode's current game, its picture, the PiP, its autobot, the main window
    async function recover(ctx) {
      if (io.settleView) { await ask(io.settleView); alive(ctx); }     // a saved view being restored never undoes this F5
      let pick = await current(ctx);
      if (!pick?.sid && !pick?.loading) {            // no MercMode game: the game on screen is repaired instead
        const sid = await repairable(ctx);
        if (sid) pick = { sid, shown: true };
      }
      if (!pick?.sid) return;
      if (pick.native) set(ctx, 'stream', 'ok', 'Shown from this PC directly (no stream)');
      else for (let attempt = 0; attempt < 3; attempt++) {
        if (await stream(ctx, pick.sid, true)) break;
        // a picture that never comes back: MercMode may have moved on to a new session (a service restart): follow it
        if (pick.own || pick.shown || now() - ctx.started > F5_STREAM_BUDGET_MS) break;
        const next = await current(ctx);
        if (!next?.sid || next.sid === pick.sid || next.own) break;
        pick = next;
      }
      if (!pick.shown) await pip(ctx, pick.sid, { f5: true, own: pick.own });
      else if (shownPip() === pick.sid) set(ctx, 'pip', 'ok', 'Showing');
      await bot(ctx, pick.sid, { expected: !pick.own && !pick.shown });
      if (!pick.own && !pick.shown) await view(ctx, pick.sid);
    }
    function run({ quiet = false, automatic = false, f5 = false, resumed = null } = {}) {
      if (busy && (!f5 || busyF5)) return busy;       // one run at a time; an F5 takes over an automatic reconnect
      if (f5) { quiet = false; automatic = false; }
      const carried = Number(resumed?.started);
      const ctx = { id: ++generation, f5, started: resumed && Number.isFinite(carried) ? carried : now() };
      busyF5 = f5;
      const job = (async () => {
        state.steps = fresh(f5 ? F5_STEPS : STEPS); state.done = false; state.error = ''; state.f5 = f5;
        io.show?.(!quiet);
        try {
          if (f5 && resumed) set(ctx, 'update', resumed.update?.status === 'warn' ? 'warn' : 'ok',
            `${resumed.update?.detail || 'Updated'}; gBox reloaded`);
          else if (f5 && await update(ctx) === 'reloading') return clone();
          await spark(ctx, !automatic);
          if (await library(ctx) === 'reloading') return clone();
          io.forget(RESUME_KEY); io.forget(RELOAD_KEY);
          if (f5) {
            await recover(ctx);
            state.steps = state.steps.filter(s => s.status !== 'wait');   // what ran (no MercMode game: no mention of it)
            const failed = state.steps.find(s => s.status === 'err');
            state.done = !failed; state.error = failed ? failed.detail : '';
            render(clone());
            if (failed) io.show?.(true);                // its step says what to do; Try again runs the F5 again
            else { await sleep(LINGER_MS); alive(ctx); io.show?.(false); }
            return clone();
          }
          let sid = await mercmode(ctx);
          // a picture that never comes back: MercMode may have moved on (a service restart starts its run on a new
          // session, and right after it the status still names the dead one - operator 2026-10-26: "gbox reloaded to
          // this", Resident Evil 5 on lilspark with no fresh picture while RE4 already played): ask again, follow it
          for (let attempt = 0; sid && attempt < 3; attempt++) {
            if (await stream(ctx, sid)) break;
            const next = await mercmode(ctx);
            if (!next || next === sid) break;
            sid = next;
          }
          if (sid) {
            await pip(ctx, sid);
            // an operator's reconnect brings the game back with its autobot driving (operator 2026-10-26); the control
            // plane decides (gbox/bot_control.py). Automatic reconnects leave the bot alone.
            if (!automatic && io.ensureBot) try { await io.ensureBot(sid); } catch { /* never fails the reconnect */ }
          }
          else state.steps = state.steps.filter(s => ['spark', 'library'].includes(s.id) || s.status === 'err');   // connected; no game to show
          state.done = true; render(clone()); io.show?.(false);
        } catch (error) {
          if (error.superseded) return { superseded: true, done: false, error: '', steps: [] };
          state.error = error.message || String(error);
          if (error.step) { const s = step(error.step); if (s) Object.assign(s, { status: 'err', detail: state.error }); }
          io.show?.(true); render(clone());
        }
        return clone();
      })().finally(() => { if (busy === job) { busy = null; busyF5 = false; } });
      busy = job;
      return job;
    }
    return { run, state: clone, STEPS };
  }
  // the PC whose MercMode the window should show: this PC's own if it runs one, else any PC playing, else the Spark.
  // A PC that is offline is never chosen, whatever its last known run says.
  function pickHost(data, workerName) {
    const hosts = (data?.hosts || []).filter(h => h.online !== false);
    const playing = h => h.current_run?.session_id && PLAYING.includes(h.current_run.phase);
    return hosts.find(h => h.name === workerName && playing(h)) || hosts.find(playing)
      || hosts.find(h => h.name === 'lilspark') || hosts.find(h => h.settings?.enabled) || null;
  }
  // F5's update step decides from main.js's client:update answer (pull; null from an older main process without it) and
  // this window's client version at load (baseline) against now (latest; client-version.cjs): one reload when anything
  // new arrived - pulled commits, the Spark's client, newer app files on disk, or gBox's own code when it may relaunch
  function updatePlan({ pull = null, baseline = null, latest = null } = {}) {
    const moved = key => !!(baseline?.[key] && latest?.[key] && baseline[key] !== latest[key]);
    const pulled = pull?.state === 'updated';
    const notes = [];
    let status = 'ok';
    if (!pull) { notes.push('This gBox was started before F5 could update it: close and reopen it once'); status = 'warn'; }
    else {
      notes.push(pull.detail || (pulled ? 'Updated' : 'Up to date'));
      if (!['updated', 'current'].includes(pull.state)) status = 'warn';
    }
    const restart = !!(pull?.restart ?? latest?.restart);
    const activation = pull?.activation || latest?.activation;
    // a relaunch refused before this window loaded is not retried on every F5: it waits until this PC is idle
    const refused = restart && !!baseline?.restart && activation?.state === 'pending';
    const relaunch = restart && !pull?.busy && !refused;
    if (moved('remote')) notes.push('the Spark serves a newer gBox client');
    else if (moved('renderer') && !pulled) notes.push('newer app files are on this PC');
    if (restart && !relaunch) {
      notes.push(`gBox restarts with its new code once this PC is idle (${pull?.busy || activation?.reason || 'a local game or task runs'})`);
      status = 'warn';
    } else if (relaunch) notes.push('gBox restarts to load its new code');
    if (pull?.packages) { notes.push('new packages are needed: use Rebuild & relaunch for this PC'); status = 'warn'; }
    return { reload: pulled || moved('renderer') || moved('remote') || relaunch, status, detail: notes.join('; ') };
  }
  // one line for the toast after an F5: the game, its picture, its autobot
  function summary(state) {
    const parts = ['mercmode', 'stream', 'bot'].map(id => state?.steps?.find(s => s.id === id))
      .filter(s => s?.detail && s.status !== 'wait').map(s => s.detail);
    return parts.join(' · ') || 'connected';
  }
  const api = { create, pickHost, backoff, updatePlan, summary, STEPS, F5_STEPS, RESUME_KEY, RELOAD_KEY, RELOAD_ONCE_MS,
    F5_KEY, F5_RESUME_MS, TITLE_WAIT_MS };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxReconnectFlow = api;
})(globalThis);
