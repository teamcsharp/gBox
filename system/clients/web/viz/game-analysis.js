/* Exact-title/session Analysis. UI renders measured evidence; it never infers completion percentages. */
(function (root) {
  'use strict';
  const ESC = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const terminal = s => ['completed', 'cancelled', 'interrupted', 'failed'].includes(s);
  const keyOf = target => JSON.stringify([target.session_id || '', target.game_id || '', target.build || '']);
  const n = v => Number.isFinite(v) ? v : null;
  const pretty = value => typeof value === 'object' ? JSON.stringify(value) : String(value ?? 'unavailable');
  function numbers(value, prefix = '', out = []) {
    if (!value || typeof value !== 'object') return out;
    for (const [key, v] of Object.entries(value)) {
      if (out.length >= 40) break;
      const path = prefix ? `${prefix}.${key}` : key;
      if (typeof v === 'number' && Number.isFinite(v)) out.push([path, v]);
      else if (v && typeof v === 'object' && prefix.split('.').length < 3) numbers(v, path, out);
    }
    return out;
  }
  function chart(samples) {
    const rows = (samples || []).filter(x => n(x.at) !== null && n(x.observations) !== null).slice(-100);
    if (!rows.length) return '<p>No evidence samples yet.</p>';
    const min = rows[0].at, span = Math.max(1, rows.at(-1).at - min), top = Math.max(1, ...rows.map(x => x.observations));
    const points = rows.map(x => `${(10 + (x.at - min) / span * 420).toFixed(1)},${(70 - x.observations / top * 55).toFixed(1)}`).join(' ');
    return `<svg viewBox="0 0 440 92" role="img" aria-label="Observed evidence count over elapsed seconds"><path d="M10 10V70H430" fill="none" stroke="#566078"/><polyline points="${points}" fill="none" stroke="#65d9b4" stroke-width="2"/><text x="10" y="87" fill="currentColor">0 s</text><text x="370" y="87" fill="currentColor">${Math.round(span)} s</text><text x="14" y="20" fill="currentColor">${top} observations</text></svg>`;
  }
  function jobDonut(jobs) {
    const counts = {};
    for (const job of jobs || []) counts[job.state || 'unknown'] = (counts[job.state || 'unknown'] || 0) + 1;
    const total = Object.values(counts).reduce((a, b) => a + b, 0), colors = ['#65d9b4','#74b7ff','#d7acff','#ffcf89','#ff7e86','#8192a8'];
    let offset = 0;
    const stops = Object.entries(counts).map(([state, count], i) => {
      const start = offset; offset += count / total * 100;
      return `${colors[i % colors.length]} ${start}% ${offset}%`;
    });
    return `<div class="ga-chart-row"><div class="ga-donut" role="img" aria-label="Linked job states: ${ESC(Object.entries(counts).map(([s,c])=>`${s} ${c}`).join(', ') || 'no jobs')}" style="background:${total ? `conic-gradient(${stops.join(',')})` : '#35435a'}"><b>${total}</b></div><div>${Object.entries(counts).map(([state,count],i)=>`<p><i style="background:${colors[i%colors.length]}"></i>${ESC(state)}: ${count}</p>`).join('') || '<p>No linked jobs</p>'}</div></div>`;
  }
  function bars(counts) {
    const rows = [['Observations', counts?.observations], ['Artifacts', counts?.artifacts], ['Linked jobs', counts?.jobs]].filter(x=>n(x[1])!==null);
    const top = Math.max(1,...rows.map(x=>x[1]));
    return `<div class="ga-bars" role="img" aria-label="Measured evidence counts">${rows.map(([name,value])=>`<div>${name}<span><i style="width:${Math.max(0,value)/top*100}%"></i></span><b>${value}</b></div>`).join('')}</div>`;
  }
  function report(run, assetUrl) {
    if (!run) return '<p>Opening an evidence run…</p>';
    const ev = run.evidence || {}, tel = ev.autoplay || {}, counts = run.counts || {};
    const obs = Object.values(run.observations || {}), latest = obs.at(-1);
    const jobRows = (run.jobs || []).map(j => `<tr><td>${ESC(j.tool)}<small>${ESC(j.id)}</small></td><td>${ESC(j.state)}</td><td>${ESC(j.admission_wait?.reason || j.error || '')}</td></tr>`).join('');
    const caps = (run.capabilities || []).map(c => `<tr><td><label><input type="checkbox" data-request="${ESC(c.feature)}" ${c.requested ? 'checked' : ''}>${ESC(c.feature)}</label></td><td>${ESC(c.state.replaceAll('_', ' '))}</td><td>${ESC(c.installed_hooks.join(', ') || 'No advertised hook')}<small>Execution disabled</small></td></tr>`).join('');
    const rows = numbers(tel.stats || {});
    const crystal = run.crystal?.sha256;
    const art = Object.values(run.artifacts || {}).map(a => `<li><a href="${ESC(assetUrl('/api/artifacts/' + a.sha256))}" target="_blank" rel="noopener">${ESC(a.name || a.sha256)}</a> · ${ESC(a.size)} bytes</li>`).join('');
    const duration = Math.max(0,(run.deadline||0)-(run.started||0)), elapsed = Math.max(0,Math.min(duration,(run.updated||0)-(run.started||0)));
    return `<div class="ga-counts">${[['Polls', counts.polls], ['Observations', counts.observations], ['Linked jobs', counts.jobs], ['Artifacts', counts.artifacts]].map(([k, v]) => `<span><b>${ESC(v ?? 0)}</b>${k}</span>`).join('')}</div>
      <p class="ga-muted">Evidence collected, not percent complete. Cached reports retain their source timestamps.</p><label>Collection window: ${Math.floor(elapsed)} / ${Math.floor(duration)} seconds <progress max="${duration||1}" value="${elapsed}" aria-label="Elapsed bounded collection window"></progress></label>${jobDonut(run.jobs)}${bars(counts)}${chart(run.samples)}
      <p class="ga-muted">Build verification: ${ESC(ev.build_verification || 'unverified: no build hash supplied')}</p>
      <details open><summary>Gameplay evidence</summary><p>Native report: ${ESC(ev.native_telemetry || 'unavailable')} ${n(tel.age_s) !== null ? `· ${ESC(tel.age_s)} seconds old` : ''}</p>
      <p>Observer: ${ESC(ev.observer?.gameplay_state || ev.observer?.state || 'unavailable')} · last checked ${ev.observer?.last_checked ? ESC(new Date(ev.observer.last_checked * 1000).toLocaleTimeString()) : 'unknown'}</p>
      ${latest ? `<p><b>Visual hypothesis:</b> ${ESC(latest.summary || pretty(latest))}</p>` : '<p>No visual observation is available for this exact session.</p>'}
      ${rows.length ? `<table><caption>Values reported by the session controller</caption><tbody>${rows.map(([k, v]) => `<tr><th>${ESC(k)}</th><td>${ESC(v)}</td></tr>`).join('')}</tbody></table>` : '<p>No measured native counters are available.</p>'}</details>
      <details open><summary>Live console · linked jobs only</summary><pre data-console aria-live="polite">${ESC((run.console || []).map(x => `${x.tool} · ${x.job_id}\n${x.line}`).join('\n') || 'No console lines reported yet.')}</pre><table><tbody>${jobRows}</tbody></table></details>
      <details><summary>Capabilities and requested work</summary><p>These preferences request future adapters. They do not authorize execution. Extraction and replacement stay disabled until the exact title/build has a verified adapter and an explicit operation.</p><table><tbody>${caps}</tbody></table></details>
      <details><summary>Source worker and resource measurements</summary><pre>${ESC(JSON.stringify(ev.worker || {}, null, 2))}</pre></details>
      ${run.model_hypothesis ? `<details open><summary>Local model hypothesis</summary><p>${ESC(run.model_hypothesis.text || pretty(run.model_hypothesis))}</p><small>Model: ${ESC(run.model_hypothesis.model)} · measured output tokens: ${ESC(run.model_hypothesis.usage?.eval_count ?? 'unavailable')}. GPU placement is not attested by this result.</small></details>` : ''}
      <details open><summary>Reusable crystals and source artifacts</summary>${crystal ? `<p><a data-crystal href="${ESC(assetUrl('/api/artifacts/' + crystal))}" target="_blank" rel="noopener">Download crystal checkpoint</a><small>SHA-256 ${ESC(crystal)}</small></p>` : '<p>Waiting for the first crystal.</p>'}${ev.pso_review?.crystal_url ? `<p><a href="${ESC(assetUrl(ev.pso_review.crystal_url))}" target="_blank" rel="noopener">PSO native run crystal</a> · source sequence ${ESC(ev.pso_review.seq)} · ${ESC(ev.pso_review.freshness)}</p>` : ''}<ul>${art}</ul><p>Reuse findings only with matching title hashes/build and provenance. Session addresses are not portable.</p></details>`;
  }
  function controller(io, target, update) {
    let epoch = 0, stopped = false, run = null, timer = null, busy = false;
    const valid = () => !stopped && (!io.valid || io.valid(target));
    const publish = error => { if (!stopped) update(run, error || ''); };
    const schedule = () => { if (valid() && run && !terminal(run.state)) timer = setTimeout(poll, io.pollMs || 2000); };
    async function poll() {
      clearTimeout(timer); timer = null;
      if (busy || stopped) return;
      if (!valid()) { clearTimeout(timer); publish('Session selection or service changed. This overlay is frozen; it will not follow another game.'); return; }
      busy = true; const token = epoch;
      try { const next = await io.api('/api/analysis/' + encodeURIComponent(run.id)); if (valid() && token === epoch) { run = next; publish(); } }
      catch (error) { if (token === epoch) publish(error.message); }
      finally { busy = false; schedule(); }
    }
    async function start() {
      const token = ++epoch;
      try { const next = await io.api('/api/analysis', target); if (valid() && token === epoch) { run = next; publish(); schedule(); } }
      catch (error) { if (token === epoch) publish(error.message); }
    }
    async function stop() {
      clearTimeout(timer); ++epoch;
      if (!run || !valid()) return;
      try { run = await io.api('/api/analysis/' + encodeURIComponent(run.id) + '/stop', {}); publish(); }
      catch (error) { publish(error.message); }
    }
    async function model(worker_id, allow_during_gameplay) {
      if (!run || !valid() || terminal(run.state)) throw Error('Start an active analysis run first.');
      return io.api('/api/analysis/' + encodeURIComponent(run.id) + '/model', { worker_id, allow_during_gameplay });
    }
    function dispose() { stopped = true; ++epoch; clearTimeout(timer); }
    return { start, poll, stop, model, dispose, get run() { return run; } };
  }
  function css(doc) {
    if (doc.getElementById('game-analysis-css')) return;
    const style = doc.createElement('style'); style.id = 'game-analysis-css';
    style.textContent = `.game-analysis{position:fixed;z-index:92;right:18px;top:70px;width:min(490px,calc(100vw - 28px));max-height:calc(100vh - 95px);overflow:auto;box-sizing:border-box;background:rgba(18,24,34,.96);color:#e9eef6;border:1px solid #54647c;border-radius:12px;box-shadow:0 15px 60px #0008;font:13px/1.45 system-ui;padding:16px}.game-analysis header{display:flex;align-items:center;gap:8px;position:static!important;min-height:0!important;padding:0!important;background:none!important;flex-wrap:wrap}.game-analysis h3{font-size:17px;margin:0;flex:1}.game-analysis button,.game-analysis select{font:inherit;background:#263449;color:inherit;border:1px solid #60728d;border-radius:5px;padding:5px 9px;cursor:pointer}.game-analysis button:disabled{opacity:.5;cursor:default}.game-analysis small{display:block;color:#a6b5cb;font-size:11px;overflow-wrap:anywhere}.game-analysis summary{cursor:pointer;font-weight:600;margin:10px 0}.game-analysis details{border-top:1px solid #35435a;margin-top:12px}.game-analysis pre{max-height:190px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#111822;padding:8px;font:11px/1.45 monospace}.game-analysis table{width:100%;border-collapse:collapse;font-size:11px}.game-analysis td,.game-analysis th{padding:5px;border-bottom:1px solid #35435a;text-align:left;overflow-wrap:anywhere}.game-analysis a{color:#8ed4ff}.game-analysis svg{width:100%;font-size:10px}.ga-muted{color:#a6b5cb;font-size:11px}.ga-counts{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:13px}.ga-counts span{background:#222e40;padding:8px;border-radius:6px;font-size:10px}.ga-counts b{display:block;font-size:20px}.ga-error{color:#ffcf89}.ga-toggle{position:fixed;z-index:93;right:18px;bottom:18px;background:#263449;color:white;border:1px solid #60728d;border-radius:7px;padding:8px;cursor:pointer}`;
    style.textContent += `.game-analysis progress{display:block;width:100%;height:7px;accent-color:#65d9b4}.ga-chart-row{display:flex;gap:20px;align-items:center;margin-top:14px}.ga-chart-row p{margin:3px 0;font-size:11px}.ga-chart-row i{display:inline-block;width:8px;height:8px;margin-right:6px}.ga-donut{width:72px;height:72px;border-radius:50%;display:grid;place-items:center;flex:none}.ga-donut b{background:#121822;width:48px;height:48px;border-radius:50%;display:grid;place-items:center;font-size:19px}.ga-bars{margin:12px 0}.ga-bars>div{display:grid;grid-template-columns:85px 1fr 35px;gap:8px;align-items:center;font-size:11px;margin:5px 0}.ga-bars span{background:#29374b;height:7px}.ga-bars i{display:block;height:100%;background:#74b7ff}.game-analysis[data-active=true] h3:before{content:'';display:inline-block;width:7px;height:7px;background:#65d9b4;border-radius:50%;margin-right:8px;animation:ga-pulse 1.5s ease-in-out infinite}@keyframes ga-pulse{50%{opacity:.3}}@media(prefers-reduced-motion:reduce){.game-analysis h3:before{animation:none!important}}`;
    doc.head.append(style);
  }
  let current = null;
  function open(io, target) {
    const doc = io.document || root.document, key = keyOf(target);
    if (current && current.key === key && current.io === io) { current.toggle(); return current; }
    if (current) current.destroy();
    css(doc);
    const host = doc.createElement('section'); host.className = 'game-analysis'; host.setAttribute('aria-label', 'Game Analysis');
    host.innerHTML = `<header><h3>Analysis</h3><button data-hide title="Hide overlay; bounded collection continues">Hide</button><button data-stop>Stop analysis</button></header><small data-target></small><p data-state></p><p class="ga-error" data-error role="status"></p><div data-model><label><input type="checkbox" data-auto checked>Automatically use this game's configured local model</label><p data-auto-status></p><label>Local Ollama worker <select data-worker><option value="">Loading…</option></select></label><p><label><input type="checkbox" data-coexist checked>Allow this bounded analysis during this game's play</label></p><button data-reason>Analyze evidence locally</button><small>Load, free memory, worker exclusions and exact-session checks remain active. No model downloads or cloud fallback. Automatic analysis uses only the exact session worker.</small><p data-model-status></p></div><div data-report></div>`;
    const toggle = doc.createElement('button'); toggle.className = 'ga-toggle'; toggle.textContent = 'Analysis'; toggle.hidden = true;
    doc.body.append(host, toggle);
    let hidden = false, closed = false;
    const hide = () => { hidden = !hidden; host.hidden = hidden; toggle.hidden = !hidden; };
    const assetUrl = io.assetUrl || (p => p);
    const control = controller(io, target, (run, error) => {
      if (closed) return;
      host.querySelector('[data-target]').textContent = `${run?.target?.title || target.game_id || target.session_id} · ${run?.target?.session_id || 'catalog evidence; no live session'} · ${run?.target?.mod || target.build || 'original build'}`;
      host.querySelector('[data-state]').textContent = run ? `${run.state} · ${Math.max(0, Math.floor((run.updated - run.started)))} s measured${run.reason ? ' · ' + run.reason : ''}` : 'Opening analysis…';
      host.querySelector('[data-error]').textContent = error;
      host.dataset.active = String(run?.state === 'running' || (run?.jobs || []).some(j=>j.state==='running'));
      host.querySelector('[data-auto]').checked = run?.local_model_preference !== false;
      host.querySelector('[data-auto-status]').textContent = run?.automatic_model?.reason || (target.session_id ? '' : 'Catalog evidence: no live session worker selected for automatic inference.');
      const region = host.querySelector('[data-report]'), console = region.querySelector('[data-console]');
      const scroll = console?.scrollTop || 0, follow = !console || console.scrollHeight-console.clientHeight-scroll < 20;
      const details = [...region.querySelectorAll('details')].map(x=>x.open), outerScroll = host.scrollTop;
      region.innerHTML = report(run, assetUrl);
      [...region.querySelectorAll('details')].forEach((x,i)=>{if(i<details.length)x.open=details[i];});
      const nextConsole=region.querySelector('[data-console]');if(nextConsole)nextConsole.scrollTop=follow?nextConsole.scrollHeight:scroll;
      host.scrollTop=outerScroll;
      host.querySelector('[data-stop]').disabled = !run || terminal(run.state);
      host.querySelector('[data-reason]').disabled = !run || terminal(run.state);
    });
    host.querySelector('[data-hide]').onclick = hide; toggle.onclick = hide;
    host.querySelector('[data-stop]').onclick = () => control.stop();
    host.querySelector('[data-reason]').onclick = async () => {
      const status = host.querySelector('[data-model-status]');
      try { const job = await control.model(host.querySelector('[data-worker]').value, host.querySelector('[data-coexist]').checked); status.textContent = `Local hypothesis job ${job.id}: ${job.state}. Admission waits appear in the job table.`; }
      catch (error) { status.textContent = error.message; }
    };
    host.addEventListener('change', async event => {
      if ((!event.target.dataset.request && !event.target.hasAttribute('data-auto')) || !control.run || (io.valid && !io.valid(target))) return;
      const requested = Object.fromEntries([...host.querySelectorAll('[data-request]')].map(x => [x.dataset.request, x.checked]));
      try { await io.api('/api/analysis-preferences/' + encodeURIComponent(control.run.target.game_id), { requested, local_model:host.querySelector('[data-auto]').checked }, 'PUT'); }
      catch (error) { host.querySelector('[data-error]').textContent = error.message; }
    });
    io.api('/api/ollama-assist').then(data => {
      if (closed) return;
      host.querySelector('[data-worker]').innerHTML = '<option value="">Choose configured local worker</option>' + (data.workers || []).map(w => `<option value="${ESC(w.id)}" ${w.policy?.enabled ? '' : 'disabled'}>${ESC(w.name)} · ${ESC(w.policy?.model || 'not enabled')}</option>`).join('');
    }).catch(error => { if (!closed) host.querySelector('[data-model-status]').textContent = error.message; });
    const panel = { key, io, host, control, toggle: hide, destroy() { closed = true; control.dispose(); host.remove(); toggle.remove(); if (current === panel) current = null; } };
    current = panel; control.start();
    return panel;
  }
  const api = { open, controller, report, chart, jobDonut, bars, numbers, keyOf };
  root.GBoxGameAnalysis = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window === 'object' ? window : globalThis);
