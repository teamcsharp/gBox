/* Rebuild & relaunch <PC> from this gBox instance (operator 2026-10-26): a PiP-sized panel that follows another PC's
   rebuild_node job (GET /api/jobs/{jid}/console; gbox/node_rebuild.py) - its console lines streaming in (monospace,
   autoscroll), a loading bar from the job's pct, npm/npx's braille spinner with what runs right now, the PC's name and
   phase - then watches GET /api/workers until that PC's worker is back (online again after it went away, or a new
   worker id for the name) and says "Back online", so the PiP stream of its session can resume. Helpers are pure
   (tests/test_rebuild_panel.cjs); mount() wires the DOM. */
(function (root, factory) { const api = factory(); if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxRebuildPanel = api; })(globalThis, function () {
  'use strict';
  const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];      // the braille spinner npm / npx show
  const KEEP = 200, FINISHED = ['succeeded', 'invalid', 'failed', 'rejected'], TIMEOUT_MS = 5 * 60 * 1000;
  const ESC = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  // z-index under the PiP menu (#pipmenu 70) and the PiP bar (#compact-controls 100): both stay usable over the panel
  const CSS = `#rebuild-panel{position:fixed;z-index:60;display:flex;flex-direction:column;gap:6px;box-sizing:border-box;padding:10px 12px;background:#0b0d12f0;color:#e8e8ee;font:12px system-ui;border:1px solid #2b2f3a;border-radius:10px;box-shadow:0 10px 30px #000a;min-width:280px}
    #rebuild-panel.rbp-pip{inset:0;width:auto;height:auto;border-radius:0;border:0;background:#05060ad9}
    #rebuild-panel.rbp-float{right:16px;bottom:16px;width:440px;height:280px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px)}
    #rebuild-panel .rbp-head{display:flex;align-items:center;gap:8px;min-height:22px}
    #rebuild-panel .rbp-head b{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    #rebuild-panel .rbp-phase{opacity:.75;font-size:11px;white-space:nowrap}
    #rebuild-panel .rbp-close{border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;padding:0 6px;line-height:18px}
    #rebuild-panel .rbp-con{flex:1;min-height:0;margin:0;overflow:auto;font:11px/1.35 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word;background:#000a;border-radius:6px;padding:6px 8px;color:#cfe3cf}
    #rebuild-panel .rbp-l{display:block}#rebuild-panel .rbp-l.cmd{color:#9bd4ff}#rebuild-panel .rbp-l.head{color:#fff;font-weight:600;margin-top:3px}
    #rebuild-panel .rbp-l.warn,#rebuild-panel .rbp-l.bad{color:#ffb3b3}#rebuild-panel .rbp-l.ok{color:#9bffd6}
    #rebuild-panel .rbp-status{font:12px ui-monospace,Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-height:15px}
    #rebuild-panel[data-status=online] .rbp-status{color:#9bffd6}
    #rebuild-panel[data-status=failed] .rbp-status,#rebuild-panel[data-status=timeout] .rbp-status{color:#ffadad}
    #rebuild-panel .rbp-bar{height:6px;border-radius:3px;background:#ffffff26;overflow:hidden;flex:0 0 auto}
    #rebuild-panel .rbp-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#5aa0ff,#9bffd6);transition:width .5s linear}
    #rebuild-panel[data-status=restarting] .rbp-bar i{background:linear-gradient(90deg,#ffb86b,#ffd59b);animation:rbp-pulse 1.2s ease-in-out infinite}
    #rebuild-panel[data-status=failed] .rbp-bar i,#rebuild-panel[data-status=timeout] .rbp-bar i{background:#ff7b7b}
    @keyframes rbp-pulse{0%,100%{opacity:1}50%{opacity:.4}}`;

  const spinnerFrame = tick => SPINNER[((Math.trunc(tick) % SPINNER.length) + SPINNER.length) % SPINNER.length];
  const clampPct = v => Math.max(0, Math.min(100, Number.isFinite(+v) ? +v : 0));
  // the worker writes a header per step: "== 2/5 Python packages =="
  const HEADER = /^==\s*(\d+)\/(\d+)\s+(.+?)\s*==$/;
  function phaseOf(lines) {
    let phase = null;
    for (const line of lines || []) { const m = HEADER.exec(String(line)); if (m) phase = { n: +m[1], of: +m[2], title: m[3] }; }
    return phase;
  }
  // what runs right now, npx style ("⠋ Installing Python packages…"): the newest line that says so
  const VERBS = [
    [/^\$ git /, 'Pulling code'], [/^\$ .*pip install.* --upgrade pip/, 'Upgrading pip'], [/^\$ .*pip install/, 'Installing Python packages'],
    [/^\$ .*npm install/, 'Installing desktop packages'], [/^\$ .*gbox .* setup$/, 'Running gbox setup'], [/^\$ .*import gbox/, 'Importing the updated code'],
    [/^\$ .*check-idle/, 'Checking that the Spark is idle'], [/^Waiting for \d+ game session/, 'Waiting for games to close'],
    [/^== .*Code ==/, 'Updating code'], [/^== .*Python packages ==/, 'Installing Python packages'], [/^== .*Desktop app packages ==/, 'Checking desktop packages'],
    [/^== .*Self-check ==/, 'Self-check'], [/^== .*Restart ==/, 'Restarting'], [/^Rebuilding /, 'Starting']];
  function activityOf(lines) {
    for (let i = (lines || []).length - 1; i >= 0; i--) for (const [rx, verb] of VERBS) if (rx.test(String(lines[i]))) return verb;
    return 'Starting';
  }
  const lineClass = line => /^\$ /.test(line) ? 'cmd' : /^== /.test(line) ? 'head' : /^!/.test(line) ? 'warn' : /^\[exit /.test(line) ? 'bad' : /^(\[ok\]|Done:)/.test(line) ? 'ok' : '';
  // GET /api/jobs/{jid}/console?after=<seq>: `seq` counts every line the job ever wrote, `fetched` holds the newest of
  // them; only the lines beyond what we have are appended (the server already trims to after=, this tolerates more)
  function mergeConsole(have, haveSeq, fetched, seq) {
    have = have || []; fetched = fetched || [];
    if (!(seq > haveSeq)) return have;
    const fresh = fetched.slice(Math.max(0, fetched.length - (seq - haveSeq)));
    return have.concat(fresh).slice(-KEEP);
  }
  // online PCs for the "⟳ Rebuild & relaunch <PC>" menu items: the PiP's PC first, then this one, the Spark, the rest
  function pcs(workers, here, current) {
    const seen = new Set(), out = [];
    for (const w of Array.isArray(workers) ? workers : []) {
      if (!w || !w.name || w.online === false || seen.has(w.name)) continue;
      seen.add(w.name);
      const mine = !!here && w.name === here, spark = (w.os || '') === 'linux';
      out.push({ name: w.name, id: w.id, os: w.os || '', here: mine, current: !!current && w.name === current,
                 label: `⟳ Rebuild & relaunch ${w.name}${mine ? ' (this PC)' : spark ? ' (the Spark)' : ''}` });
    }
    const rank = p => p.current ? 0 : p.here ? 1 : p.os === 'linux' ? 2 : 3;
    return out.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }

  function initial({ name, workerId, jobId, now = Date.now() }) {
    return { name: String(name || ''), workerId: workerId || null, jobId: jobId || null, status: 'running', lines: [], seq: 0, pct: 0,
             phase: null, activity: 'Starting', error: '', restart: '', steps: null, failed: [], startedAt: now, finishedAt: 0,
             offlineSeen: false, onlineAt: 0, newWorkerId: null, tick: 0, apiError: '' };
  }
  // one GET /api/jobs/{jid}/console answer -> the next state
  function applyJob(state, job, now = Date.now()) {
    job = job || {};
    const lines = mergeConsole(state.lines, state.seq, job.lines, job.seq);
    const next = { ...state, lines, seq: Math.max(state.seq, +job.seq || 0), pct: Math.max(state.pct, clampPct(job.pct)),
                   phase: phaseOf(lines) || state.phase, activity: activityOf(lines), apiError: '' };
    if (!FINISHED.includes(job.state)) return next;
    next.finishedAt = now; next.error = job.error || ''; next.restart = job.restart || ''; next.steps = job.steps || null; next.failed = job.failed || [];
    if (job.state === 'succeeded' || job.state === 'invalid') {          // invalid: a step failed, but the tool ran through
      next.status = job.restart === 'scheduled' ? 'restarting' : 'done';
      next.pct = next.status === 'restarting' ? Math.min(96, Math.max(next.pct, 92)) : 100;   // full only once it is back
    } else { next.status = 'failed'; next.pct = 100; }
    return next;
  }
  // one GET /api/workers answer while the PC restarts -> the next state (null: the control plane did not answer; the
  // Spark's own restart takes it down for a moment, which proves nothing about the PC)
  function applyWorkers(state, workers, now = Date.now(), timeoutMs = TIMEOUT_MS) {
    const next = { ...state };
    if (Array.isArray(workers)) {
      const w = workers.find(x => x && x.name === state.name);
      const online = !!(w && w.online !== false);
      next.offlineSeen = state.offlineSeen || !online;
      if (online && (next.offlineSeen || (w.id && state.workerId && w.id !== state.workerId))) {
        return { ...next, status: 'online', onlineAt: now, pct: 100, newWorkerId: w.id || null };
      }
    }
    if (now - state.finishedAt > timeoutMs) next.status = 'timeout';
    return next;
  }
  function statusText(state, timeoutMs = TIMEOUT_MS) {
    const s = spinnerFrame(state.tick), pc = state.name || 'the PC';
    switch (state.status) {
      case 'running': return `${s} ${state.activity}…` + (state.apiError ? ` (${state.apiError})` : '');
      case 'restarting': return `${s} Restarting ${pc}… ${state.offlineSeen ? 'waiting for it to come back' : 'its worker is shutting down'}`;
      case 'online': return `✓ ${pc} is back online`;
      case 'timeout': return `✗ ${pc} did not come back within ${Math.round(timeoutMs / 60000)} min`;
      case 'failed': return `✗ Rebuild of ${pc} failed${state.error ? ': ' + state.error : ''}`;
      default: {
        const mark = state.restart === 'deferred' ? '⏸' : state.restart === 'blocked' ? '✗' : '✓';
        return `${mark} ${pc} rebuilt; restart ${state.restart || 'skipped'}` + (state.failed?.length ? ` (failed: ${state.failed.join(', ')})` : '');
      }
    }
  }
  const phaseText = state => state.phase ? `${state.phase.n}/${state.phase.of} ${state.phase.title}` : '';
  const consoleHTML = lines => (lines || []).map(l => `<span class="rbp-l ${lineClass(String(l))}">${ESC(l)}</span>`).join('\n');
  function render(state, timeoutMs = TIMEOUT_MS) {
    const pct = clampPct(state.pct);
    return `<div class="rbp-head"><b>Rebuild &amp; relaunch · ${ESC(state.name)}</b><span class="rbp-phase" data-rbp-phase>${ESC(phaseText(state))}</span>` +
      `<button type="button" class="rbp-close" data-rbp-close title="Hide this panel (the rebuild continues)">✕</button></div>` +
      `<pre class="rbp-con scroll" data-rbp-con>${consoleHTML(state.lines)}</pre>` +           // .scroll: never a drag handle
      `<div class="rbp-status" data-rbp-status>${ESC(statusText(state, timeoutMs))}</div>` +
      `<div class="rbp-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>`;
  }

  // follows one rebuild job: poll() reads the console while it runs, then the worker list while the PC restarts
  function create({ api, name, workerId, jobId, render: draw, now = Date.now, timeoutMs = TIMEOUT_MS, onOnline, onEnd }) {
    let state = initial({ name, workerId, jobId, now: now() }), stopped = false, polling = false, ended = false;
    const emit = () => draw && draw({ ...state, text: statusText(state, timeoutMs) });
    function end() { if (ended) return; ended = true; if (state.status === 'online') onOnline?.({ ...state }); onEnd?.({ ...state }); }
    async function poll() {
      if (stopped || polling) return { ...state };
      polling = true;
      try {
        if (state.status === 'running') {
          try { state = applyJob(state, await api(`/api/jobs/${encodeURIComponent(jobId)}/console?after=${state.seq}`, undefined, 'GET'), now()); }
          catch (error) { state = { ...state, apiError: String(error?.message || error).slice(0, 80) }; }
          if (state.status !== 'running' && state.status !== 'restarting') end();
        } else if (state.status === 'restarting') {
          let workers = null;
          try { workers = await api('/api/workers', undefined, 'GET'); } catch { workers = null; }
          state = applyWorkers(state, workers, now(), timeoutMs);
          if (state.status !== 'restarting') end();
        }
      } finally { polling = false; }
      emit();
      return { ...state };
    }
    function tick() { if (stopped) return; state = { ...state, tick: state.tick + 1 }; emit(); }
    return { poll, tick, stop: () => { stopped = true; }, state: () => ({ ...state }) };
  }

  // the DOM: the structure once, then only what changed (the console keeps its scroll/selection between ticks)
  function mount(host, options) {
    const { pip = () => false, pollMs = 1500, spinMs = 90, hideAfterMs = 8000, timeoutMs = TIMEOUT_MS } = options;
    host.id = 'rebuild-panel';
    let drawn = false, lastSeq = -1, lastStatus = '';
    const draw = state => {
      host.classList.toggle('rbp-pip', !!pip()); host.classList.toggle('rbp-float', !pip());
      host.dataset.status = state.status;
      if (!drawn) { host.innerHTML = render(state, timeoutMs); drawn = true; }
      const con = host.querySelector('[data-rbp-con]');
      if (con && (state.seq !== lastSeq || state.lines.length !== con.childElementCount)) {
        con.innerHTML = consoleHTML(state.lines); con.scrollTop = con.scrollHeight; lastSeq = state.seq;
      }
      const status = host.querySelector('[data-rbp-status]'); if (status) status.textContent = state.text || statusText(state, timeoutMs);
      const phase = host.querySelector('[data-rbp-phase]'); if (phase) phase.textContent = phaseText(state);
      const bar = host.querySelector('.rbp-bar'); const pct = clampPct(state.pct);
      if (bar) { bar.setAttribute('aria-valuenow', String(pct)); bar.querySelector('i').style.width = pct + '%'; }
      lastStatus = state.status;
    };
    const ctl = create({ ...options, timeoutMs, render: draw, onEnd: state => {
      options.onEnd?.(state);
      if (state.status === 'online' && hideAfterMs > 0) setTimeout(() => { if (lastStatus === 'online') close(); }, hideAfterMs);
    } });
    const poll = setInterval(() => ctl.poll(), pollMs), spin = setInterval(() => ctl.tick(), spinMs);
    host.addEventListener('click', e => { if (e.target.closest?.('[data-rbp-close]')) close(); });
    let closed = false;
    function close() {
      if (closed) return; closed = true;
      clearInterval(poll); clearInterval(spin); ctl.stop(); host.remove(); options.onClose?.();
    }
    draw(ctl.state());
    ctl.poll();
    return { ...ctl, close, host };
  }

  const api = { SPINNER, KEEP, TIMEOUT_MS, CSS, spinnerFrame, clampPct, phaseOf, activityOf, lineClass, mergeConsole, pcs, initial,
                applyJob, applyWorkers, statusText, phaseText, render, create, mount };
  return api;
});
