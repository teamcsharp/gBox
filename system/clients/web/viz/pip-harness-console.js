/* Live harness console on the PiP picture: Ghidra hooks, model builds and ROM overlays.
 *
 * The PiP already shows the game; this panel shows what gBox is doing to it: every active switch_mods / re5_mods /
 * ghidra / launch job's console lines, plus the MercMode phase and the build that is applied. It is deliberately a
 * picture-in-picture child: a dismissed panel leaves a small pill so it can be brought back without hunting menus.
 *
 * No framework and no module system: index.html loads it after viz/mercmode.js, so the global `api` helper is present.
 */
(function (root) {
  'use strict';
  if (!root || !root.document) return;
  const doc = root.document;
  const WATCH = /^(switch_mods|re5_mods|re6_mods|session_op|launch_game|characters|mod|file_mod|ghidra(?:_bridge)?|re_inventory|autoplay|mercmode|build|disc|rom|iso|patch)$/i;
  const KEEP = 220;
  const POLL_MS = 1400;
  const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
  const state = {
    lines: [], seqByJob: {}, seen: new Set(), timer: null, busy: false, tick: 0,
    collapsed: false, hidden: false, lastPhase: '', lastScreen: '', lastBuild: '', started: 0,
    session: '', lastHarnessSeq: 0, frameHash: '', unchanged: 0, freezeReported: false, screen: '',
  };
  let host = null, panel = null, body = null, statusEl = null, titleEl = null, pill = null, spinEl = null, barEl = null;

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  }
  function cls(line) {
    const text = String(line);
    if (/^\[(rom|overlay|switch_mods|write)\]/i.test(text) || /^== /.test(text)) return 'head';
    if (/^\[(ghidra|hook|decomp|analysis)\]/i.test(text)) return 'hook';
    if (/^\[(freeze|hang|stall)\]/i.test(text)) return 'freeze';
    if (/^\[game\]/i.test(text)) return 'game';
    if (/^\[(probe|snapshot)\]/i.test(text)) return 'head';
    if (/^\[(runtime|launch|session)\]/i.test(text)) return 'run';
    if (/^\[(error|fail|failed)\]|error:|traceback/i.test(text)) return 'bad';
    if (/^\[(ok|done|verified)\]/i.test(text) || /✓/.test(text)) return 'ok';
    if (/^\[(harness|build|model|texture)\]/i.test(text)) return 'model';
    return '';
  }
  function stamp() {
    const d = new Date();
    return d.toTimeString().slice(0, 8);
  }
  function push(line, kind) {
    if (!line) return;
    const text = String(line).replace(/\s+$/, '');
    if (!text) return;
    const last = state.lines[state.lines.length - 1];
    if (last && last.text === text && Date.now() - last.at < 2500) return;   // a poll repeats the tail: no duplicate
    state.lines.push({ text, at: Date.now(), cls: kind || cls(text), time: stamp() });
    if (state.lines.length > KEEP) state.lines.splice(0, state.lines.length - KEEP);
    renderLines();
  }
  function renderLines() {
    if (!body) return;
    const atBottom = body.scrollHeight - body.clientHeight - body.scrollTop < 24;
    const html = state.lines.map((line, i) =>
      `<span class="phc-line ${line.cls}" data-i="${i}"><i>${esc(line.time)}</i>${esc(line.text)}</span>`).join('');
    body.innerHTML = html + '<span class="phc-cursor">▋</span>';
    if (atBottom) body.scrollTop = body.scrollHeight;
  }
  function jobsList(payload) {
    if (Array.isArray(payload)) return payload;
    return (payload && (payload.jobs || payload.items || payload.results)) || [];
  }
  function labelFor(job) {
    const tool = String((job && job.tool) || 'job');
    if (/ghidra/i.test(tool)) return '[ghidra]';
    if (/switch_mods/i.test(tool)) return '[rom]';
    if (/re5_mods|re6_mods|re_mods/i.test(tool)) return '[harness]';
    if (/launch_game|session_op/i.test(tool)) return '[runtime]';
    if (/characters|mod|file_mod/i.test(tool)) return '[model]';
    return '[' + tool + ']';
  }
  function describeInput(job) {
    const input = (job && job.input) || {};
    if (input.op) return `${input.op}${input.build ? ' · ' + input.build : ''}${input.character ? ' · ' + input.character : ''}`;
    if (input.session_id) return String(input.session_id).slice(0, 18);
    return '';
  }
  async function pullJob(job) {
    if (!job || !job.id) return;
    const id = job.id;
    const prev = state.seqByJob[id] || 0;
    let seq = prev, lines = [];
    try {
      const answer = await api(`/api/jobs/${encodeURIComponent(id)}/console?after=${prev}`, undefined, 'GET');
      if (answer) {
        seq = Number(answer.seq) || prev;
        lines = Array.isArray(answer.lines) ? answer.lines : [];
        if (answer.error) push(`${labelFor(job)} ${answer.error}`, 'bad');
        if (answer.steps && Array.isArray(answer.steps)) {
          const failed = answer.steps.filter(s => s && s.state === 'failed');
          if (failed.length) push(`${labelFor(job)} failed: ${failed.map(s => s.title || s.id).join(', ')}`, 'bad');
        }
      }
    } catch (e) {
      // the job may have ended between the list and this read: fall back to the job's own progress log
    }
    if (!lines.length && Array.isArray(job.progress_log)) lines = job.progress_log.slice(-20);
    if (!lines.length && job.progress && job.progress.msg) lines = [job.progress.msg];
    for (const raw of lines) {
      const text = String(raw == null ? '' : raw);
      if (!text) continue;
      const signature = id + '|' + text;
      if (state.seen.has(signature)) continue;
      state.seen.add(signature);
      push(`${labelFor(job)} ${text}`);
    }
    state.seqByJob[id] = Math.max(prev, seq, lines.length ? prev + lines.length : prev);
    if (job.state && /failed|cancelled|invalid|rejected/i.test(job.state)) {
      push(`${labelFor(job)} ${job.state}: ${job.error || 'see the task log'}`, 'bad');
    } else if (job.state === 'succeeded') {
      const note = `done${job.progress ? ' · ' + (job.progress.msg || '') : ''}`;
      if (!state.seen.has(id + '|done')) { state.seen.add(id + '|done'); push(`${labelFor(job)} ${note}`, 'ok'); }
    }
  }
  async function poll() {
    if (state.busy || state.hidden) return;
    state.busy = true;
    try {
      const jobs = jobsList(await api('/api/jobs?state=queued,running&limit=80', undefined, 'GET')).filter(j => j && WATCH.test(String(j.tool || '')));
      const active = jobs.filter(j => j.state === 'running' || j.state === 'queued' || j.state === 'assigned');
      for (const job of active.slice(0, 8)) await pullJob(job);
      if (!active.length && !state.lines.length) push('[harness] waiting for a build, a hook or a launch…', 'idle');
      await mercLine();
      await sessionConsole();
      await frameCheck();
      updateStatus(active);
    } catch (e) {
      if (statusEl) statusEl.textContent = 'control plane unreachable';
    } finally {
      state.busy = false;
    }
  }
  async function mercLine() {
    let data;
    try { data = await api('/api/mercmode', undefined, 'GET'); } catch { return; }
    const hosts = (data && data.hosts) || [];
    const hostRow = hosts.find(h => h && (h.current_run || h.now_playing)) || hosts.find(h => h && h.online) || null;
    if (!hostRow) return;
    const run = hostRow.current_run || {};
    const play = hostRow.now_playing || {};
    const build = String(run.mod || run.build || '');
    if (build && build !== state.lastBuild) {
      state.lastBuild = build;
      push(`[rom] build applied: ${build}`, 'head');
    }
    const phase = String(run.phase || '');
    if (phase && phase !== state.lastPhase) {
      state.lastPhase = phase;
      push(`[runtime] ${hostRow.name}: ${phase}${run.title ? ' · ' + run.title : ''}`, 'run');
    }
    const screen = String(play.screen || '');
    state.screen = screen || state.screen;
    if (screen && screen !== state.lastScreen) {
      state.lastScreen = screen;
      const detail = [play.character, play.stage, play.timer != null ? `t=${play.timer}` : ''].filter(Boolean).join(' · ');
      push(`[runtime] screen ${screen}${detail ? ' · ' + detail : ''}`, 'run');
    }
    const sel = run.mercmode && run.mercmode.selection;
    if (sel && sel.mod && sel.mod !== state.lastBuild) {
      state.lastBuild = sel.mod;
      push(`[harness] queued round build: ${sel.mod}`, 'model');
    }
  }
  async function currentSession() {
    try {
      const rows = await api('/api/sessions', undefined, 'GET');
      const list = Array.isArray(rows) ? rows : (rows && (rows.sessions || rows.items)) || [];
      const row = list.find(r => r && r.state === 'running') || list.find(r => r && r.session_id && !/ended|stopped|failed/.test(r.state || ''));
      if (row) {
        if (state.session && state.session !== row.session_id) {
          state.frameHash = ''; state.unchanged = 0; state.freezeReported = false; state.lastHarnessSeq = 0;
          push(`[runtime] session ${row.session_id}`, 'run');
        }
        state.session = row.session_id;
        return row.session_id;
      }
    } catch { /* the control plane may be restarting */ }
    return state.session || '';
  }
  async function sessionConsole() {
    const sid = await currentSession();
    if (!sid) return;
    let answer;
    try { answer = await api(`/api/sessions/${encodeURIComponent(sid)}/harness/console?after=${state.lastHarnessSeq}`, undefined, 'GET'); }
    catch { return; }
    if (!answer) return;
    state.lastHarnessSeq = Math.max(state.lastHarnessSeq, Number(answer.seq) || 0);
    for (const line of answer.lines || []) {
      const key = sid + '|h|' + line.seq;
      if (state.seen.has(key)) continue;
      state.seen.add(key);
      const tag = `[${line.source || 'game'}]`;
      push(`${tag} ${line.text}`, cls(`${tag} ${line.text}`));
    }
    const g = answer.ghidra || {};
    if (g.checked && g.status && !state.seen.has('ghidra|' + g.status)) {
      state.seen.add('ghidra|' + g.status);
      push(`[ghidra] ${g.status}${g.reason ? ': ' + g.reason : ''}`, g.status === 'available' ? 'hook' : 'bad');
    }
  }
  async function frameCheck() {
    const sid = await currentSession();
    if (!sid) return;
    let response;
    try {
      const headers = typeof tok !== 'undefined' && tok ? { authorization: 'Bearer ' + tok } : {};
      response = await fetch(`/api/sessions/${encodeURIComponent(sid)}/frame.jpg`, { headers, cache: 'no-store' });
    } catch { return; }
    if (!response || !response.ok) return;
    let buf;
    try { buf = await response.arrayBuffer(); } catch { return; }
    const bytes = new Uint8Array(buf);
    const hash = `${buf.byteLength}:${bytes[0] || 0}:${bytes[bytes.length >> 1] || 0}:${bytes[bytes.length - 1] || 0}`;
    if (!state.frameHash) { state.frameHash = hash; state.unchanged = 0; return; }
    if (hash === state.frameHash) {
      state.unchanged += 1;
      if (state.unchanged >= 7 && !state.freezeReported && /^(playing|loading|unknown|select_player)$/.test(state.screen || '') ) {
        state.freezeReported = true;
        const witness = { frame_sha: hash, unchanged_s: state.unchanged * 1.4, screen: state.screen || '',
                          session: sid, at: new Date().toISOString() };
        push(`[freeze] frame unchanged ${Math.round(witness.unchanged_s)} s on ${sid}`, 'freeze');
        try { await api(`/api/sessions/${encodeURIComponent(sid)}/harness/freeze`, witness); push('[freeze] report written beside the console', 'freeze'); }
        catch (e) { push(`[freeze] report failed: ${e.message || e}`, 'bad'); }
      }
    } else {
      state.frameHash = hash; state.unchanged = 0; state.freezeReported = false;
    }
  }
  async function probe() {
    const sid = await currentSession();
    if (!sid) { push('[probe] no running session to inspect', 'bad'); return; }
    push('[probe] capturing session, overlay, emulator log tail and Ghidra readiness…', 'head');
    let answer;
    try { answer = await api(`/api/sessions/${encodeURIComponent(sid)}/harness/probe`, {}, 'POST'); }
    catch (e) { push(`[probe] failed: ${e.message || e}`, 'bad'); return; }
    const g = (answer && answer.ghidra) || {};
    push(`[probe] ${sid} · ${(answer && answer.session && answer.session.mod) || 'stock'} · ${g.status || 'ghidra unknown'}${g.reason ? ' (' + g.reason + ')' : ''}`, 'head');
    const tail = String((answer && answer.emulator_log_tail) || '').split('\n').filter(Boolean).slice(-6);
    for (const line of tail) push(`[game] ${line}`, 'game');
  }

  async function ghidra() {
    const sid = await currentSession();
    if (!sid) { push('[ghidra] no running session to hook', 'bad'); return; }
    push('[ghidra] resolving the title main and asking the bridge to open it…', 'hook');
    let answer;
    try { answer = await api(`/api/sessions/${encodeURIComponent(sid)}/harness/ghidra`, { op: 'open' }, 'POST'); }
    catch (e) { push(`[ghidra] hook failed: ${e.message || e}`, 'bad'); return; }
    if (answer && answer.job) {
      push(`[ghidra] ${answer.binary_path} · job ${answer.job.id} on ${answer.worker}; follow it here`, 'hook');
    } else {
      push(`[ghidra] ${answer.status || 'not submitted'}${answer.reason ? ': ' + answer.reason : ''}`, answer.status === 'available' ? 'hook' : 'bad');
    }
  }

  function updateStatus(active) {
    if (!statusEl) return;
    const running = active.filter(j => j.state === 'running');
    if (running.length) {
      const pct = Math.max(0, ...running.map(j => Number(j.progress && j.progress.pct) || Number(j.pct) || 0));
      statusEl.textContent = `${spinEl.textContent} ${running.length} active · ${Math.round(pct)}%`;
      if (barEl) barEl.style.width = Math.max(4, Math.min(100, pct)) + '%';
      statusEl.className = 'phc-status live';
    } else if (active.length) {
      statusEl.textContent = 'queued';
      statusEl.className = 'phc-status queued';
      if (barEl) barEl.style.width = '8%';
    } else {
      statusEl.textContent = 'idle';
      statusEl.className = 'phc-status idle';
      if (barEl) barEl.style.width = '0%';
    }
    spinEl.textContent = SPIN[state.tick++ % SPIN.length];
  }
  function css() {
    if (doc.getElementById('phc-style')) return;
    const style = doc.createElement('style');
    style.id = 'phc-style';
    style.textContent = `
      #pip-harness-console{position:absolute;left:6px;right:6px;bottom:6px;height:min(36%,190px);z-index:9;display:flex;flex-direction:column;overflow:hidden;border:1px solid #39e2a2aa;border-radius:7px;background:linear-gradient(160deg,#04130fdd,#061b16ee 55%,#03100cee);box-shadow:0 8px 24px #000a, inset 0 0 30px #39e2a211;color:#bfffe7;font:11px/1.35 "JetBrains Mono",Consolas,monospace;pointer-events:auto;-webkit-app-region:no-drag;backdrop-filter:blur(3px)}
      #pip-harness-console[data-collapsed="true"]{height:26px}
      #pip-harness-console[data-hidden="true"]{display:none}
      .phc-head{display:flex;align-items:center;gap:7px;padding:4px 7px;border-bottom:1px solid #39e2a244;cursor:pointer;user-select:none;background:#39e2a20d;letter-spacing:.08em;text-transform:uppercase;font-size:10px;flex:0 0 auto}
      .phc-head b{font-weight:700;color:#7dffd0;text-shadow:0 0 8px #39e2a288}
      .phc-status{margin-left:auto;color:#8ab7a8;font-size:10px;white-space:nowrap}
      .phc-status.live{color:#7dffd0}.phc-status.queued{color:#ffd985}.phc-status.idle{color:#799a90}
      .phc-btn{border:0;background:transparent;color:#9cd7c2;font:inherit;cursor:pointer;padding:0 2px;line-height:1}
      .phc-btn:hover{color:#fff}
      .phc-body{position:relative;flex:1;overflow:auto;padding:4px 8px 14px;scrollbar-width:thin;scrollbar-color:#2c8f6b transparent}
      .phc-body::-webkit-scrollbar{width:6px}.phc-body::-webkit-scrollbar-thumb{background:#2c8f6b;border-radius:3px}
      .phc-line{display:block;white-space:pre-wrap;overflow-wrap:anywhere;padding:1px 0 1px 0;color:#9fd8c4;animation:phc-in 160ms ease-out both;text-shadow:0 0 6px #39e2a21a}
      .phc-line i{color:#4f8d77;font-style:normal;margin-right:6px}
      .phc-line.head{color:#7fe8ff}.phc-line.hook{color:#d7a5ff;text-shadow:0 0 8px #c07dff44}
      .phc-line.run{color:#9fb9ff}.phc-line.model{color:#ffd98a}.phc-line.ok{color:#7dff9e}
      .phc-line.game{color:#b7c7bd}.phc-line.game i{color:#4f6d60}.phc-line.freeze{color:#ff6b78;font-weight:700}
      .phc-line.bad{color:#ff8d96}.phc-line.idle{color:#5e7d72}
      .phc-cursor{display:inline-block;color:#7dffd0;animation:phc-blink 1s steps(2,start) infinite;margin-left:2px}
      .phc-bar{height:2px;background:#39e2a218;flex:0 0 auto;overflow:hidden}
      .phc-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#39e2a2,#7fe8ff);transition:width .35s ease;box-shadow:0 0 10px #39e2a2aa}
      .phc-scan{position:absolute;left:0;right:0;top:-40%;height:40%;pointer-events:none;background:linear-gradient(180deg,transparent,#39e2a20d,transparent);animation:phc-scan 5.5s linear infinite}
      #pip-harness-pill{position:absolute;left:6px;bottom:6px;z-index:9;border:1px solid #39e2a2aa;border-radius:999px;background:#04130fdd;color:#7dffd0;font:600 10px/1 monospace;letter-spacing:.1em;padding:5px 8px;cursor:pointer;pointer-events:auto;-webkit-app-region:no-drag;box-shadow:0 2px 10px #000a}
      #pip-harness-pill:hover{background:#0b2a20}
      @keyframes phc-in{from{opacity:0;transform:translateY(3px);filter:blur(1px)}to{opacity:1;transform:none;filter:none}}
      @keyframes phc-blink{50%{opacity:0}}
      @keyframes phc-scan{0%{top:-40%}100%{top:110%}}
      @media(prefers-reduced-motion:reduce){.phc-line,.phc-cursor,.phc-scan{animation:none}}
    `;
    doc.head.appendChild(style);
  }
  function buildUi() {
    css();
    host = doc.getElementById('pip');
    if (!host) return false;
    if (doc.getElementById('pip-harness-console')) return true;
    panel = doc.createElement('div');
    panel.id = 'pip-harness-console';
    panel.innerHTML =
      '<div class="phc-head" title="Click to collapse or expand the harness console">' +
        '<b>⌁ harness console</b><span class="phc-spin">⠋</span>' +
        '<span class="phc-status idle">idle</span>' +
        '<button type="button" class="phc-btn" data-phc-ghidra title="Hook this title’s analyzed main into the Ghidra Bridge (open/decompile)">G</button>' +
        '<button type="button" class="phc-btn" data-phc-probe title="Capture a game/RAM/log diagnostic snapshot">⌖</button>' +
        '<button type="button" class="phc-btn" data-phc-toggle title="Collapse or expand">–</button>' +
        '<button type="button" class="phc-btn" data-phc-hide title="Hide (a pill brings it back)">✕</button>' +
      '</div>' +
      '<div class="phc-bar"><i></i></div>' +
      '<div class="phc-body"><div class="phc-scan"></div></div>';
    host.appendChild(panel);
    body = panel.querySelector('.phc-body');
    statusEl = panel.querySelector('.phc-status');
    titleEl = panel.querySelector('.phc-head b');
    spinEl = panel.querySelector('.phc-spin');
    barEl = panel.querySelector('.phc-bar i');
    panel.querySelector('[data-phc-toggle]').addEventListener('click', ev => { ev.stopPropagation(); toggle(); });
    panel.querySelector('[data-phc-hide]').addEventListener('click', ev => { ev.stopPropagation(); hide(); });
    panel.querySelector('[data-phc-probe]').addEventListener('click', ev => { ev.stopPropagation(); probe(); });
    panel.querySelector('[data-phc-ghidra]').addEventListener('click', ev => { ev.stopPropagation(); ghidra(); });
    panel.querySelector('.phc-head').addEventListener('click', ev => { if (!ev.target.closest('button')) toggle(); });
    pill = doc.createElement('button');
    pill.type = 'button';
    pill.id = 'pip-harness-pill';
    pill.textContent = '⌁ console';
    pill.title = 'Show the harness console (Ghidra hooks, builds, ROM overlays)';
    pill.hidden = true;
    pill.addEventListener('click', () => show());
    host.appendChild(pill);
    state.started = Date.now();
    push('[harness] console attached to the PiP · watching switch_mods / re5_mods / ghidra / launch', 'head');
    return true;
  }
  function toggle() {
    state.collapsed = !state.collapsed;
    panel.dataset.collapsed = state.collapsed ? 'true' : 'false';
    panel.querySelector('[data-phc-toggle]').textContent = state.collapsed ? '+' : '–';
    if (panel) panel.style.height = '';
  }
  function hide() {
    state.hidden = true;
    state.collapsed = false;
    panel.dataset.hidden = 'true';
    pill.hidden = false;
  }
  function show() {
    state.hidden = false;
    panel.dataset.hidden = 'false';
    pill.hidden = true;
    if (state.lines.length === 0) push('[harness] console reopened', 'head');
  }
  function start() {
    if (!buildUi()) return false;
    if (state.timer) return true;
    state.timer = setInterval(poll, POLL_MS);
    poll();
    return true;
  }
  const apiFn = root.api;
  if (typeof apiFn !== 'function') return;    // the shell always defines api; a bare page has no control plane
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
  root.GBoxPipHarnessConsole = { start, toggle, show, hide, push, get lines() { return state.lines.slice(); } };
})(typeof window !== 'undefined' ? window : globalThis);
