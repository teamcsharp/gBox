/* Free space on a PC (operator 2026-10-26; gbox/storage_purge.py). The Workers menu's "🧹 Free space: N GB unplayed"
   runs a dry run of storage_purge on that PC (POST /api/workers/{name}/storage-purge), follows the job, and lists what
   would go - games that are not favorites and not played there for 14 days, builds that were sent there automatically -
   with size, last played and the reason, plus what stays and why. "Delete these" asks once more, then deletes exactly
   that reviewed list (dry_run=false + its paths; the PC re-checks every item). Helpers are pure
   (tests/test_storage_purge_panel.cjs); mount() wires the DOM. */
(function (root, factory) { const api = factory(); if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxStoragePurge = api; })(globalThis, function () {
  'use strict';
  const FINISHED = ['succeeded', 'invalid', 'failed', 'rejected', 'cancelled'];
  const ARM_MS = 6000;                                   // "Confirm: delete …" stays armed this long
  const ESC = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const CSS = `#storage-panel{position:fixed;z-index:60;right:16px;bottom:16px;width:560px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);display:flex;flex-direction:column;gap:6px;box-sizing:border-box;padding:10px 12px;background:#0b0d12f2;color:#e8e8ee;font:12px system-ui;border:1px solid #2b2f3a;border-radius:10px;box-shadow:0 10px 30px #000a}
    #storage-panel .sp-head{display:flex;align-items:center;gap:8px}#storage-panel .sp-head b{flex:1}
    #storage-panel .sp-close{border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;padding:0 6px;line-height:18px}
    #storage-panel .sp-status{min-height:15px}#storage-panel .sp-warn{color:#ffd59b}#storage-panel .sp-bad{color:#ffadad}#storage-panel .sp-ok{color:#9bffd6}
    #storage-panel .sp-list{flex:1;min-height:0;max-height:52vh;overflow:auto;background:#000a;border-radius:6px;padding:4px 8px}
    #storage-panel .sp-group{margin:6px 0 2px;font-weight:600}#storage-panel .sp-row{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:3px 0;border-top:1px solid #ffffff14}
    #storage-panel .sp-row small{grid-column:1/3;opacity:.7}#storage-panel .sp-size{text-align:right;white-space:nowrap}
    #storage-panel details{margin-top:4px}#storage-panel summary{cursor:pointer;opacity:.8}
    #storage-panel .sp-actions{display:flex;gap:8px;justify-content:flex-end}#storage-panel .sp-actions button{font-size:12px;padding:3px 10px;cursor:pointer}
    #storage-panel .sp-actions .sp-danger{background:#5a1d1d;color:#fff;border:1px solid #a33;border-radius:4px}
    #storage-panel .sp-actions .sp-danger.armed{background:#b02a2a}
    #storage-panel .sp-bar{height:5px;border-radius:3px;background:#ffffff26;overflow:hidden}#storage-panel .sp-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#5aa0ff,#9bffd6);transition:width .4s linear}`;

  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n >= 2 ** 30) return `${(n / 2 ** 30).toFixed(n >= 100 * 2 ** 30 ? 0 : 1)} GB`;
    if (n >= 2 ** 20) return `${Math.round(n / 2 ** 20)} MB`;
    if (n >= 1024) return `${Math.round(n / 1024)} KB`;
    return `${n} B`;
  }
  const day = ts => ts ? new Date(ts * 1000).toISOString().slice(0, 10) : '';
  // the menu button: the newest dry run's figure when there is one (GET /api/testing/workers row.storage)
  function buttonLabel(worker) {
    const s = worker && worker.storage;
    if (s && s.dry_run && Number.isFinite(+s.freed_bytes)) return `🧹 Free space: ${fmtBytes(s.freed_bytes)} unplayed`;
    return '🧹 Free space (check unplayed games and builds)';
  }
  function group(items) {
    const out = [];
    for (const [kind, label] of [['game', 'Games'], ['build', 'Builds']]) {
      const rows = (items || []).filter(i => i && i.kind === kind);
      if (rows.length) out.push({ kind, label, items: rows, bytes: rows.reduce((t, r) => t + (Number(r.size) || 0), 0) });
    }
    return out;
  }
  const deleteBody = result => ({ dry_run: false, unplayed_days: result.unplayed_days || 14,
                                 include: result.include || ['games', 'builds'], paths: (result.items || []).map(i => i.path) });
  const confirmLabel = result => `Confirm: delete ${(result.items || []).length} item${(result.items || []).length === 1 ? '' : 's'} (${fmtBytes(result.totals?.freed_bytes)})`;
  function rowHTML(it) {
    const name = it.title || it.game, what = it.kind === 'build' ? `${it.build}${it.part && it.part !== 'build' ? ` · ${it.part}` : ''}` : it.part;
    const played = it.last_played ? `last played ${day(it.last_played)}` : 'never played on this PC';
    return `<div class="sp-row"><span>${ESC(name)} <span style="opacity:.75">· ${ESC(what)}</span></span><span class="sp-size">${ESC(fmtBytes(it.size))}</span>` +
      `<small title="${ESC(it.path)}">${ESC(played)} · ${ESC(it.reason)}</small></div>`;
  }
  function listHTML(result) {
    const groups = group(result.items), kept = result.kept || [];
    let html = groups.map(g => `<div class="sp-group">${ESC(g.label)} · ${g.items.length} · ${ESC(fmtBytes(g.bytes))}</div>` + g.items.map(rowHTML).join('')).join('');
    if (!groups.length) html = '<div class="sp-ok" style="padding:6px 0">Nothing to free: every cached game is a favorite or played recently, and every build here was downloaded by you or is in use.</div>';
    if (kept.length) html += `<details><summary>Kept (${kept.length} · ${ESC(fmtBytes(result.totals?.kept_bytes))})</summary>` +
      kept.map(k => `<div class="sp-row"><span>${ESC(k.title || k.game)} <span style="opacity:.75">· ${ESC(k.kind === 'build' ? k.build : k.part)}</span></span>` +
                    `<span class="sp-size">${ESC(fmtBytes(k.size))}</span><small>${ESC(k.reason)}</small></div>`).join('') + '</details>';
    if ((result.skipped || []).length) html += `<div class="sp-group">Not deleted</div>` +
      result.skipped.map(s => `<div class="sp-row"><span title="${ESC(s.path)}">${ESC(String(s.path).split(/[\\/]/).slice(-2).join('/'))}</span><span></span><small>${ESC(s.reason)}</small></div>`).join('');
    return html;
  }
  function summaryText(state) {
    const r = state.result, pc = state.name;
    switch (state.status) {
      case 'checking': return `Checking ${pc}… ${state.msg || ''}`.trim();
      case 'listing': return r.items.length
        ? `${r.items.length} item${r.items.length === 1 ? '' : 's'} on ${pc} not played for ${r.unplayed_days}+ days: ${fmtBytes(r.totals?.freed_bytes)} can be freed`
        : `Nothing to free on ${pc}`;
      case 'deleting': return `Deleting on ${pc}… ${state.msg || ''}`.trim();
      case 'done': return `Deleted ${r.totals?.deleted ?? r.items.length} item(s) on ${pc}: ${fmtBytes(r.roots?.freed_measured ?? r.totals?.freed_bytes)} freed` +
        ((r.skipped || []).length ? ` · ${r.skipped.length} not deleted` : '');
      case 'failed': return `✗ ${state.error || 'The storage check failed'}`;
      default: return '';
    }
  }
  // a job to its end: GET /api/jobs/{id} until finished (onProgress gets pct + msg), then the job
  async function follow(api, jobId, onProgress, { wait = ms => new Promise(r => setTimeout(r, ms)), pollMs = 1000, limit = 3600 } = {}) {
    for (let i = 0; i < limit; i++) {
      let job = null;
      try { job = await api(`/api/jobs/${encodeURIComponent(jobId)}`, undefined, 'GET'); } catch { job = null; }
      if (job && FINISHED.includes(job.state)) return job;
      if (job && onProgress) onProgress(Number(job.progress?.pct) || 0, job.progress?.msg || '');
      await wait(pollMs);
    }
    throw Error('the storage job did not finish');
  }
  // the panel's steps: check (dry run) -> listing -> arm -> delete (the reviewed paths) -> done; draw(state) each change
  function create({ api, name, draw = () => {}, wait, now = Date.now, armMs = ARM_MS }) {
    let state = { name, status: 'checking', pct: 0, msg: '', result: null, error: '', armedAt: 0, deletable: false };
    const set = patch => { state = { ...state, ...patch }; draw({ ...state, text: summaryText(state) }); return state; };
    async function run(body, phase) {
      set({ status: phase, pct: 0, msg: '' });
      const queued = await api(`/api/workers/${encodeURIComponent(name)}/storage-purge`, body);
      const job = await follow(api, queued.job_id, (pct, msg) => set({ pct, msg }), { wait });
      if (job.state !== 'succeeded') throw Error(job.error || `the storage job ${job.state}`);
      const result = await api(`/api/workers/${encodeURIComponent(name)}/storage-purge?job_id=${encodeURIComponent(queued.job_id)}`, undefined, 'GET');
      return result;
    }
    async function check(unplayedDays = 14) {
      try {
        const result = await run({ dry_run: true, unplayed_days: unplayedDays }, 'checking');
        return set({ status: 'listing', pct: 100, result, deletable: !!result.deletable && (result.items || []).length > 0 });
      } catch (error) { return set({ status: 'failed', error: String(error?.message || error) }); }
    }
    // first press arms, a second press within armMs deletes: nothing goes without the operator seeing the list
    async function remove() {
      if (state.status !== 'listing' || !state.deletable) return state;
      if (!state.armedAt || now() - state.armedAt > armMs) return set({ armedAt: now() });
      const reviewed = state.result;
      try {
        const result = await run(deleteBody(reviewed), 'deleting');
        return set({ status: 'done', pct: 100, result, armedAt: 0, deletable: false });
      } catch (error) { return set({ status: 'failed', error: String(error?.message || error), armedAt: 0 }); }
    }
    return { check, remove, state: () => ({ ...state }) };
  }
  function render(state, now = Date.now()) {
    const r = state.result, pct = Math.max(0, Math.min(100, Number(state.pct) || 0));
    const armed = !!state.armedAt && now - state.armedAt <= ARM_MS && state.status === 'listing';
    const warn = (r?.warnings || []).map(w => `<div class="sp-warn">⚠ ${ESC(w)}</div>`).join('') +
      (r && !r.deletable && state.status === 'listing' && (r.items || []).length ? '<div class="sp-warn">Deleting needs the Spark\'s favorites and play history: open this menu while connected to the Spark.</div>' : '');
    return `<div class="sp-head"><b>Free space · ${ESC(state.name)}</b><button type="button" class="sp-close" data-sp-close title="Close (a running check continues on the PC)">✕</button></div>` +
      `<div class="sp-status ${state.status === 'failed' ? 'sp-bad' : state.status === 'done' ? 'sp-ok' : ''}" data-sp-status>${ESC(summaryText(state))}</div>` +
      (state.status === 'checking' || state.status === 'deleting' ? `<div class="sp-bar"><i style="width:${pct}%"></i></div>` : '') + warn +
      (r && state.status !== 'checking' ? `<div class="sp-list scroll">${listHTML(r)}</div>` : '') +
      `<div class="sp-actions">` + (state.status === 'listing' && (r?.items || []).length
        ? `<button type="button" class="sp-danger${armed ? ' armed' : ''}" data-sp-delete ${state.deletable ? '' : 'disabled'}>${ESC(armed ? confirmLabel(r) : `Delete these (${fmtBytes(r.totals?.freed_bytes)})`)}</button>` : '') +
      `<button type="button" data-sp-close>Close</button></div>`;
  }
  function mount(host, options) {
    host.id = 'storage-panel';
    const draw = state => { host.innerHTML = render(state); };
    const ctl = create({ ...options, draw });
    let closed = false;
    function close() { if (closed) return; closed = true; host.remove(); options.onClose?.(); }
    host.addEventListener('click', e => {
      if (e.target.closest?.('[data-sp-close]')) return close();
      if (e.target.closest?.('[data-sp-delete]')) ctl.remove().then(s => {
        if (s.status === 'listing' && s.armedAt) setTimeout(() => { if (!closed) draw(ctl.state()); }, ARM_MS + 50);   // disarm
        else options.onDone?.(s);
      }).catch(() => {});
    });
    draw(ctl.state());
    ctl.check(options.unplayedDays || 14).then(s => options.onChecked?.(s)).catch(() => {});
    return { ...ctl, close, host };
  }
  return { CSS, ARM_MS, fmtBytes, buttonLabel, group, deleteBody, confirmLabel, listHTML, summaryText, follow, create, render, mount };
});
