/* Shared Mods/session panel. Research updates are read on demand; no idle polling. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.GBoxLiveControls = factory();
})(typeof window === 'undefined' ? globalThis : window, function() {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function actionHTML(a, available) {
    return `<fieldset data-lc-action="${esc(a.id)}"${available ? '' : ' disabled'}><legend>${esc(a.label)}</legend>
      <small>${esc(a.scope)}</small><p>${esc(a.notes)}</p>${a.parameters.map(p => `<label>${esc(p.label)} ${p.kind === 'choice'
        ? `<select data-lc-param="${esc(p.id)}">${p.options.map(o => `<option value="${esc(o.value)}"${o.value === p.default ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`
        : `<input type="number" data-lc-param="${esc(p.id)}" min="${p.min}" max="${p.max}" value="${p.default}" step="1">`}</label>`).join('')}
      <button type="button" data-lc-apply="${esc(a.id)}">${esc(a.label)}</button><small data-lc-availability>${available ? 'Available in this session.' : 'Check the running revision and mode to enable.'}</small></fieldset>`;
  }
  function mount(host, io, initial = {}) {
    const token = {}; host._liveControls = token;
    let stopped = false, serial = 0, game = initial.game || '', pinned = initial.sid || '', data, sid = '', busy = false, pso;
    const current = () => !stopped && host._liveControls === token && host.isConnected !== false;
    const q = s => host.querySelector(s);
    host.innerHTML = `<style>.lc-panel{border:1px solid var(--line,#41414a);border-radius:8px;padding:12px;margin:10px 0;font-size:13px}.lc-panel summary{cursor:pointer;font-weight:600}.lc-panel .lc-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}.lc-panel fieldset{border:1px solid var(--line,#41414a);border-radius:5px;margin:8px 0}.lc-panel fieldset:disabled{opacity:.6}.lc-panel label{display:flex;gap:6px;align-items:center;margin:6px 0}.lc-panel input{max-width:100px}.lc-panel select{max-width:100%}.lc-panel small{display:block;color:var(--mut,#aaa)}.lc-panel p{margin:6px 0}.lc-panel [role=status]{white-space:pre-wrap}</style>
      <details class="lc-panel"${initial.open ? ' open' : ''}><summary>Inventory, world controls &amp; hidden content</summary>
      <p data-lc-game>Choose a game above to see its discovered controls.</p>
      <div class="lc-row"><select data-lc-session aria-label="Running session for live controls"></select>
        <button type="button" data-lc-check>Refresh / check mode</button></div>
      <div class="lc-row"><label><input type="checkbox" data-lc-unlocks> Require unlock-all in every custom build</label></div>
      <small data-lc-policy></small><div data-lc-actions></div><div data-lc-pso></div>
      <div data-lc-missing></div><button type="button" data-lc-discover>Research missing controls with Ghidra</button>
      <p role="status" aria-live="polite" data-lc-status></p></details>`;
    const say = s => { if(current()) q('[data-lc-status]').textContent = s; };
    function disable(on) {
      busy = on;
      for(const b of host.querySelectorAll('button,select,input')) b.disabled = on;
      if(!on) for(const f of host.querySelectorAll('[data-lc-action]')) f.disabled = true;
    }
    async function job(path, body) {
      let j = await io.api(path, body);
      while(current() && ['queued','running'].includes(j.state)) {
        await (io.wait || (ms => new Promise(r => setTimeout(r, ms))))(500);
        j = await io.api('/api/jobs/' + encodeURIComponent(j.id));
      }
      if(!current()) throw new Error('Controls closed');
      if(j.state !== 'succeeded') throw new Error(j.error || j.state);
      return j.output?.result || {};
    }
    function body(op, action, values) { return {session_id: sid, revision: data.profile.revision, op, action, values}; }
    async function probe(n) {
      if(!data?.profile || !sid) return;
      const r = await job(`/api/games/${encodeURIComponent(game)}/live-controls/run`, body('inspect'));
      if(!current() || n !== serial) return;
      for(const a of r.actions || []) {
        const f = Array.from(host.querySelectorAll('[data-lc-action]')).find(x => x.dataset.lcAction === a.id);
        if(f) { f.disabled = !a.available; f.dataset.available = String(a.available); f.querySelector('[data-lc-availability]').textContent=a.available ? 'Available in this session.' : 'Unavailable in the current mode or scene.'; }
      }
      say('Revision checked. Available controls apply to this session only; mode is checked again on every click.');
    }
    async function refresh() {
      if(!current() || busy) return;
      const n = ++serial; pso?.dispose(); pso = null;
      q('[data-lc-pso]').innerHTML = ''; q('[data-lc-actions]').innerHTML = '';
      q('[data-lc-missing]').innerHTML = ''; const previous = sid; sid = ''; data = null;
      if(!game) { q('[data-lc-game]').textContent = 'Choose a game above to see its discovered controls.'; q('[data-lc-session]').innerHTML = ''; disable(true); return; }
      disable(true); say('Reading discovered controls…');
      try {
        const [d, sessions] = await Promise.all([io.api(`/api/games/${encodeURIComponent(game)}/live-controls`), io.api('/api/sessions')]);
        if(!current() || n !== serial) return;
        data = d;
        const available = sessions.filter(s => s.game_id === game && s.state === 'running' && (!pinned || s.session_id === pinned));
        q('[data-lc-session]').innerHTML = `<option value="">Choose running session</option>` + available.map(s => `<option value="${esc(s.session_id)}">${esc(s.title || d.title)} · ${esc(s.worker_name || s.session_id)}${s.mod ? ' · '+esc(s.mod) : ''}</option>`).join('');
        sid = pinned && available.some(s=>s.session_id === pinned) ? pinned : available.some(s=>s.session_id === previous) ? previous : available.length === 1 ? available[0].session_id : '';
        q('[data-lc-session]').value = sid;
        q('[data-lc-game]').textContent = `${d.title}${d.profile ? ' · ' + d.profile.revision_label : ' · live research pending'}`;
        q('[data-lc-unlocks]').checked = !!d.unlock_policy.enabled;
        q('[data-lc-policy]').textContent = 'Shared default for all custom builds. Pending unlock research stays pending until each exact build is verified; base games and personal saves are preserved.';
        q('[data-lc-actions]').innerHTML = (d.profile?.actions || []).map(a=>actionHTML(a, false)).join('');
        const covered = new Set((d.profile?.actions || []).map(a=>a.category));
        q('[data-lc-missing]').innerHTML = Object.entries(d.categories).filter(([k])=>!covered.has(k)).map(([,label])=>`<p><small>${esc(label)} — needs game-specific discovery / verification, or an applicability assessment.</small></p>`).join('');
        say(d.task ? `Research request #${d.task.number}${d.task.error ? ': '+d.task.error : ' is tracked.'}` : sid ? 'Check the running mode to use published controls.' : 'Launch this game to apply live controls. Research is available without launching.');
      } catch(e) { say('Live controls unavailable: ' + e.message); }
      finally { if(current() && n === serial) disable(false); }
    }
    async function checkMode() {
      if(busy || !game) return;
      await refresh();
      if(!current() || !sid || !data) return;
      disable(true); const n = serial;
      try {
        // Reuse the native item panel rather than duplicate its catalogs / guards.
        if(io.pso?.isPSO(data.title)) pso = io.pso.mount(q('[data-lc-pso]'), {api:io.api,
          job:(tool,input)=>job('/api/jobs', {tool,input,require_worker:sid.split('-')[0]})}, {sid});
        if(data.profile) await probe(n);
      } catch(e) { say(e.message); }
      finally {
        if(current() && n === serial) {
          busy = false;
          for(const b of host.querySelectorAll('button,select,input')) if(!b.closest('[data-lc-pso]')) b.disabled = false;
          for(const f of host.querySelectorAll('[data-lc-action]')) f.disabled = f.dataset.available !== 'true';
        }
      }
    }
    async function click(e) {
      const b = e.target.closest?.('button'); if(!b || busy || !game) return;
      if(b.hasAttribute('data-lc-check')) return checkMode();
      if(b.hasAttribute('data-lc-discover')) {
        const n=serial;
        b.disabled = true;
        try { const r=await io.api(`/api/games/${encodeURIComponent(game)}/live-controls/discover`, {}); if(current() && n===serial) say(`Research request #${r.number}${r.error ? ': '+r.error : ' queued; findings will appear here after native verification.'}`); }
        catch(e) { if(n===serial) say(e.message); } finally { if(current() && n===serial) b.disabled=false; }
      }
      if(b.dataset.lcApply) {
        const a = data?.profile?.actions.find(a=>a.id===b.dataset.lcApply); if(!a || !sid) return;
        const values = {};
        for(const p of a.parameters) {
          const el = Array.from(b.closest('fieldset').querySelectorAll('[data-lc-param]')).find(el=>el.dataset.lcParam===p.id);
          if(!el.reportValidity()) return;
          values[p.id] = p.kind==='integer' ? Number(el.value) : el.value;
        }
        const n=serial; disable(true); say('Applying to the selected session…');
        try { const result = await job(`/api/games/${encodeURIComponent(game)}/live-controls/run`, body('apply', a.id, values));
          if(n===serial) say(result.result?.result?.error || `${a.label}: completed. Refresh / check mode before another action.`); }
        catch(e) { if(n===serial) say(e.message); }
        finally { if(current() && n===serial) disable(false); }
      }
    }
    host.addEventListener('click', click);
    const change = async e => {
      if(e.target.hasAttribute('data-lc-session')) { sid=e.target.value; pso?.dispose(); q('[data-lc-pso]').innerHTML=''; for(const f of host.querySelectorAll('[data-lc-action]')) f.disabled=true; say('Refresh / check mode to enable this session.'); }
      if(e.target.hasAttribute('data-lc-unlocks')) {
        const desired=e.target.checked, n=serial; e.target.disabled=true;
        try { await io.api('/api/custom-build-unlocks/policy', {enabled:desired}); if(n===serial) say(desired ? 'Unlock-all required for every custom build; each build needs its own verification.' : 'Shared unlock-all requirement disabled.'); }
        catch(err) { if(n===serial) { e.target.checked=!desired; say(err.message); } } finally { if(current() && n===serial) e.target.disabled=false; }
      }
    };
    host.addEventListener('change', change);
    return {refresh, checkMode, setGame(gid) { if(game === gid) return; ++serial; game=gid || ''; pinned=''; busy=false; data=null; refresh(); },
      dispose() { stopped=true; ++serial; pso?.dispose(); host.removeEventListener('click',click); host.removeEventListener('change',change); if(host._liveControls===token) host._liveControls=null; },
      ready: refresh()};
  }
  return {mount, actionHTML};
});
