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
     - backoff(failures) paces the automatic poll: 5 s after the first failure, doubling to a minute. */
(function (root) {
  'use strict';
  const STEPS = [
    ['spark', 'Reach the Spark', 'control plane'], ['library', 'Spark library', 'this window'],
    ['mercmode', 'MercMode game', 'autobot'], ['stream', 'Live picture', 'encoder'], ['pip', 'Picture-in-picture', 'watch'],
  ];
  const RESUME_KEY = 'gbox.reconnect.resume';
  const RELOAD_KEY = 'gbox.reconnect.reloaded';     // when this window last reloaded itself to switch libraries
  const RELOAD_ONCE_MS = 120000;                     // a second reload this soon after one is refused: one per failure
  const BACKOFF_MS = [5000, 10000, 20000, 40000, 60000];
  // the automatic poll's delay after `failures` attempts in a row (0 = the first retry): 5 s doubling to a minute
  const backoff = failures => BACKOFF_MS[Math.max(0, Math.min(BACKOFF_MS.length - 1, Number.isFinite(failures) ? Math.trunc(failures) : 0))];
  const ENDED = ['ended', 'missing'];
  function create({ io, render = () => {}, sleep = ms => new Promise(r => setTimeout(r, ms)), now = Date.now }) {
    let busy = null;
    const state = { steps: STEPS.map(([id, label, sub]) => ({ id, label, sub, status: 'wait', detail: '' })), done: false, error: '' };
    const step = id => state.steps.find(s => s.id === id);
    const set = (id, status, detail = '') => { Object.assign(step(id), { status, detail }); render(clone()); };
    const clone = () => ({ ...state, steps: state.steps.map(s => ({ ...s })) });
    const shownPip = () => { try { return io.pipSession() || null; } catch { return null; } };
    const health = async sid => { if (!io.health) return null; try { return await io.health(sid); } catch { return null; } };
    const session = async sid => { if (!io.session) return null; try { return await io.session(sid); } catch { return null; } };
    // the game a PiP shows is kept unless its session ended or MercMode parked it for the next title (warm); an offline
    // PC or an unreadable answer keeps it too
    async function pipKept(sid) {
      const row = await session(sid);
      if (row && (row.warm || ENDED.includes(row.state))) return false;
      const h = await health(sid); return !h || !ENDED.includes(h.state);
    }
    // a MercMode run can be shown only while its PC answers (gbox/server.py stream health: worker_online, #2870)
    async function reachable(sid) { const h = await health(sid); return !h || (h.worker_online !== false && !ENDED.includes(h.state)); }
    async function waitFor(check, ms, every = 1000) {
      const end = now() + ms;
      for (;;) {
        try { const value = await check(); if (value) return value; } catch { /* keep trying until the deadline */ }
        if (now() >= end) return null;
        await sleep(every);
      }
    }
    async function spark(allowRestart) {
      set('spark', 'run', 'Checking the Spark…');
      if (await waitFor(async () => (await io.status())?.remote?.ready, 60000)) return set('spark', 'ok', 'The Spark answers');
      if (!allowRestart) throw Object.assign(Error('The Spark is not answering. Automatic reconnect will keep checking; Try again can repair the connection.'), { step: 'spark' });
      set('spark', 'run', 'No answer: restarting gBox on the Spark…');
      try { await io.restartSpark(); } catch (error) { set('spark', 'run', 'Restart request failed (' + error.message + '); still waiting…'); }
      if (await waitFor(async () => (await io.status())?.remote?.ready, 120000, 2000)) return set('spark', 'ok', 'The Spark is back');
      throw Object.assign(Error('The Spark is not answering on the network. This PC\'s library still works.'), { step: 'spark' });
    }
    async function library() {
      const st = await io.status();
      if (st?.mode === 'remote') return set('library', 'ok', 'Using the Spark library');
      // a reload closes the PiP (main.js restores the window on navigation): a game on screen stays on screen
      if (shownPip()) return set('library', 'ok', 'Keeping the game on screen; this window stays on its library');
      const last = Number(io.recall?.(RELOAD_KEY)) || 0;
      if (last && now() - last < RELOAD_ONCE_MS) throw Object.assign(Error('This window is still on This PC\'s library after a reload. Choose the Spark library from the connection button.'), { step: 'library' });
      set('library', 'run', 'Switching this window to the Spark…');
      io.remember(RESUME_KEY, '1');
      io.remember(RELOAD_KEY, String(Math.max(1, now())));
      try { await io.select('remote'); }
      catch (error) { io.forget(RESUME_KEY); throw Object.assign(Error(error.message || String(error)), { step: 'library' }); }
      await io.reload();
      return 'reloading';
    }
    async function mercmode() {
      // the game already on screen is the one being reconnected (never closed for another host's game)
      const shown = shownPip();
      if (shown && await pipKept(shown)) { set('mercmode', 'ok', 'Keeping the game already on screen'); return shown; }
      // Only a MercMode game that is already running is put on screen (operator 2026-10-24: "if it's not started, it
      // shouldn't even mention it ... it should just be trying to reconnect to the central server").
      set('mercmode', 'run', 'Checking for a running MercMode game…');
      const data = await waitFor(() => io.api('/api/mercmode'), 20000, 2000);
      // the PC whose game was on screen keeps the screen with its next MercMode title, else the usual choice
      const after = shown && (data?.hosts || []).find(h => h.online !== false && h.current_run?.session_id
        && ['playing', 'starting'].includes(h.current_run.phase)
        && (h.current_run.mercmode_predecessor?.session_id === shown || (h.id && shown.startsWith(h.id + '-'))));
      const host = after || (data ? io.pickHost(data) : null);
      const run = host?.current_run;
      if (!run?.session_id || !['playing', 'starting'].includes(run.phase)) { set('mercmode', 'wait', ''); return null; }
      if (!await reachable(run.session_id)) {       // a stale "playing" run of a PC that went offline: nothing to show
        set('mercmode', 'err', `${run.title || 'Game'} on ${host.name}: that PC is offline, so there is nothing to show yet`);
        return null;
      }
      set('mercmode', 'ok', `${run.title || 'Game'} on ${host.name}`);
      return run.session_id;
    }
    async function stream(sid) {
      set('stream', 'run', 'Checking the picture…');
      const fresh = async () => { const h = await io.api(`/api/sessions/${encodeURIComponent(sid)}/stream/health`);
        return h && h.age_s != null && h.age_s < 3 && h.state === 'running'; };
      if (await waitFor(fresh, 6000)) return set('stream', 'ok', 'Live');
      set('stream', 'run', 'Picture is stale: asking for a new encoder…');
      await io.api('/api/jobs', { tool: 'session_op', agent_use: false, require_worker: sid.split('-')[0],
        input: { session_id: sid, op: 'restart_stream', args: {} } }).catch(() => null);
      if (await waitFor(fresh, 30000, 1500)) return set('stream', 'ok', 'Live again');
      set('stream', 'err', 'Still no fresh picture; showing the last frame while it recovers');
    }
    async function pip(sid) {
      set('pip', 'run', 'Opening picture-in-picture…');
      const shown = shownPip();
      if (shown === sid) return set('pip', 'ok', 'Showing');
      if (shown) {                                   // never closes a picture that still plays; only an ended one gives way
        if (await pipKept(shown)) return set('pip', 'ok', 'Keeping the game already on screen');
        await io.pipRestore();
      }
      await io.pipEnter(sid);
      set('pip', 'ok', 'Showing');
    }
    async function run({ quiet = false, automatic = false } = {}) {
      if (busy) return busy;
      busy = (async () => {
        state.steps = STEPS.map(([id, label, sub]) => ({ id, label, sub, status: 'wait', detail: '' })); state.done = false; state.error = '';
        io.show?.(!quiet);
        try {
          await spark(!automatic);
          if (await library() === 'reloading') return clone();
          io.forget(RESUME_KEY); io.forget(RELOAD_KEY);
          const sid = await mercmode();
          if (sid) {
            await stream(sid); await pip(sid);
            // an operator's reconnect (F5, Try again) brings the game back with its autobot driving (operator
            // 2026-10-26); the control plane decides (gbox/bot_control.py). Automatic reconnects leave the bot alone.
            if (!automatic && io.ensureBot) try { await io.ensureBot(sid); } catch { /* never fails the reconnect */ }
          }
          else state.steps = state.steps.filter(s => ['spark', 'library'].includes(s.id) || s.status === 'err');   // connected; no game to show
          state.done = true; render(clone()); io.show?.(false);
        } catch (error) {
          state.error = error.message || String(error);
          if (error.step) set(error.step, 'err', state.error);
          io.show?.(true); render(clone());
        }
        return clone();
      })().finally(() => { busy = null; });
      return busy;
    }
    return { run, state: clone, STEPS };
  }
  // the PC whose MercMode the window should show: this PC's own if it runs one, else any PC playing, else the Spark.
  // A PC that is offline is never chosen, whatever its last known run says.
  function pickHost(data, workerName) {
    const hosts = (data?.hosts || []).filter(h => h.online !== false);
    const playing = h => h.current_run?.session_id && ['playing', 'starting'].includes(h.current_run.phase);
    return hosts.find(h => h.name === workerName && playing(h)) || hosts.find(playing)
      || hosts.find(h => h.name === 'lilspark') || hosts.find(h => h.settings?.enabled) || null;
  }
  const api = { create, pickHost, backoff, STEPS, RESUME_KEY, RELOAD_KEY, RELOAD_ONCE_MS };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxReconnectFlow = api;
})(globalThis);
