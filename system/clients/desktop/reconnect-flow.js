/* Reconnect to the Spark and put MercMode on screen, whatever it takes (operator 2026-10-24: "when I click on this button,
   I want it doing whatever it takes ... showing it reconnecting and rebuilding the platform. I want F5 to just solve and fix
   any issue"; "90% of the time I open gBox it is to watch an autobot MercMode play").

   Steps, each retried before the next escalation, rendered as a live flowchart over gBox's 3D visualizer:
     spark    the Spark answers (waits for the connection probe; if it stays down, restarts gbox.service over SSH and waits)
     library  this window uses the Spark's library, not This PC's (switching reloads the window, the flow resumes after it)
     mercmode a MercMode game runs on the chosen PC (turns MercMode on there if needed and waits for its launch)
     stream   its picture is fresh (asks that PC for a new encoder when it is not)
     pip      the game is shown in picture-in-picture
   Nothing here stops or restarts a game; a restart of the Spark service only happens when the Spark itself is not answering. */
(function (root) {
  'use strict';
  const STEPS = [
    ['spark', 'Reach the Spark', 'control plane'], ['library', 'Spark library', 'this window'],
    ['mercmode', 'MercMode game', 'autobot'], ['stream', 'Live picture', 'encoder'], ['pip', 'Picture-in-picture', 'watch'],
  ];
  const RESUME_KEY = 'gbox.reconnect.resume';
  function create({ io, render = () => {}, sleep = ms => new Promise(r => setTimeout(r, ms)), now = Date.now }) {
    let busy = null;
    const state = { steps: STEPS.map(([id, label, sub]) => ({ id, label, sub, status: 'wait', detail: '' })), done: false, error: '' };
    const step = id => state.steps.find(s => s.id === id);
    const set = (id, status, detail = '') => { Object.assign(step(id), { status, detail }); render(clone()); };
    const clone = () => ({ ...state, steps: state.steps.map(s => ({ ...s })) });
    async function waitFor(check, ms, every = 1000) {
      const end = now() + ms;
      for (;;) {
        try { const value = await check(); if (value) return value; } catch { /* keep trying until the deadline */ }
        if (now() >= end) return null;
        await sleep(every);
      }
    }
    async function spark() {
      set('spark', 'run', 'Checking the Spark…');
      if (await waitFor(async () => (await io.status())?.remote?.ready, 12000)) return set('spark', 'ok', 'The Spark answers');
      set('spark', 'run', 'No answer: restarting gBox on the Spark…');
      try { await io.restartSpark(); } catch (error) { set('spark', 'run', 'Restart request failed (' + error.message + '); still waiting…'); }
      if (await waitFor(async () => (await io.status())?.remote?.ready, 120000, 2000)) return set('spark', 'ok', 'The Spark is back');
      throw Object.assign(Error('The Spark is not answering on the network. This PC\'s library still works.'), { step: 'spark' });
    }
    async function library() {
      const st = await io.status();
      if (st?.mode === 'remote') return set('library', 'ok', 'Using the Spark library');
      set('library', 'run', 'Switching this window to the Spark…');
      io.remember(RESUME_KEY, '1');
      await io.select('remote');
      await io.reload();
      return 'reloading';
    }
    async function mercmode() {
      set('mercmode', 'run', 'Looking for the MercMode game…');
      const pick = data => io.pickHost(data);
      let data = await io.api('/api/mercmode');
      let host = pick(data);
      if (!host) throw Object.assign(Error('No gBox PC is registered for MercMode.'), { step: 'mercmode' });
      if (!host.settings?.enabled) {
        set('mercmode', 'run', `Turning MercMode on for ${host.name}…`);
        await io.api('/api/mercmode', { host: host.name, enabled: true });
      }
      const sid = await waitFor(async () => {
        data = await io.api('/api/mercmode'); host = (data.hosts || []).find(h => h.name === host.name) || host;
        const run = host.current_run;
        if (run?.session_id && ['playing', 'starting'].includes(run.phase)) return run.session_id;
        set('mercmode', 'run', run?.phase ? `${run.title || 'Next title'}: ${run.phase}…` : `Waiting for ${host.name} to start a game…`);
        return null;
      }, 180000, 3000);
      if (!sid) throw Object.assign(Error(`${host.name} did not start a MercMode game in 3 minutes.`), { step: 'mercmode' });
      set('mercmode', 'ok', `${host.current_run?.title || 'Game'} on ${host.name}`);
      return sid;
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
      if (io.pipSession() === sid) return set('pip', 'ok', 'Showing');
      if (io.pipSession()) await io.pipRestore();
      await io.pipEnter(sid);
      set('pip', 'ok', 'Showing');
    }
    async function run({ quiet = false } = {}) {
      if (busy) return busy;
      busy = (async () => {
        state.steps.forEach(s => Object.assign(s, { status: 'wait', detail: '' })); state.done = false; state.error = '';
        io.show?.(!quiet);
        try {
          await spark();
          if (await library() === 'reloading') return clone();
          io.forget(RESUME_KEY);
          const sid = await mercmode();
          await stream(sid);
          await pip(sid);
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
  // the PC whose MercMode the window should show: this PC's own if it runs one, else any PC playing, else the Spark
  function pickHost(data, workerName) {
    const hosts = (data?.hosts || []).filter(h => h.online !== false);
    const playing = h => h.current_run?.session_id && ['playing', 'starting'].includes(h.current_run.phase);
    return hosts.find(h => h.name === workerName && playing(h)) || hosts.find(playing)
      || hosts.find(h => h.name === 'lilspark') || hosts.find(h => h.settings?.enabled) || null;
  }
  const api = { create, pickHost, STEPS, RESUME_KEY };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxReconnectFlow = api;
})(globalThis);
