/* Shared Mods/session panel. Research updates are read on demand; no idle polling. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.GBoxLiveControls = factory();
})(typeof window === 'undefined' ? globalThis : window, function() {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const commandId = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6]=(bytes[6]&15)|64; bytes[8]=(bytes[8]&63)|128;
    return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('').replace(/^(.{8})(.{4})(.{4})(.{4})(.{12})$/,'$1-$2-$3-$4-$5');
  };
  const toggle = a => a.control === 'toggle' && a.parameters.some(p=>p.id === a.toggle_parameter && p.kind === 'boolean');
  function actionHTML(a, available) {
    const isToggle = toggle(a);
    return `<fieldset data-lc-action="${esc(a.id)}"${available ? '' : ' disabled'}><legend>${esc(a.label)}</legend>
      <small>${esc(a.scope)}</small><p>${esc(a.notes)}</p>${a.parameters.filter(p=>!isToggle || p.id !== a.toggle_parameter).map(p => `<label>${esc(p.label)} ${p.kind === 'choice'
        ? `<select data-lc-param="${esc(p.id)}">${p.options.map(o => `<option value="${esc(o.value)}"${o.value === p.default ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`
        : p.kind === 'boolean' ? `<input type="checkbox" data-lc-param="${esc(p.id)}"${p.default ? ' checked' : ''}>`
        : `<input type="number" data-lc-param="${esc(p.id)}" min="${p.min}" max="${p.max}" value="${p.default}" step="1">`}</label>`).join('')}
      ${isToggle ? `<label><input type="checkbox" role="switch" data-lc-toggle="${esc(a.id)}" aria-label="${esc(a.label)}"> Enabled</label>`
      : `<button type="button" data-lc-apply="${esc(a.id)}">${esc(a.label)}</button>`}<small data-lc-availability>${available ? 'Available in this session.' : 'Check the running revision and mode to enable.'}</small></fieldset>`;
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
      const until = Date.now() + (io.jobTimeoutMs || 90000);
      while(current() && ['queued','running'].includes(j.state)) {
        if(Date.now() >= until) throw Error('Completion was not confirmed. No action was retried. Refresh / check mode before another action.');
        await (io.wait || (ms => new Promise(r => setTimeout(r, ms))))(500);
        j = await io.api('/api/jobs/' + encodeURIComponent(j.id));
      }
      if(!current()) throw new Error('Controls closed');
      if(j.state !== 'succeeded') throw new Error(j.error || j.state);
      return j.output?.result || {};
    }
    function body(op, action, values) { return {session_id: sid, revision: data.profile.revision, op, action, values,
      ...(op === 'apply' ? {command_id:commandId(), expires:Date.now()/1000+15} : {})}; }
    async function probe(n) {
      if(!data?.profile || !sid) return;
      for(const f of host.querySelectorAll('[data-lc-action]')) { f.disabled=true; f.dataset.available='false'; }
      const r = await job(`/api/games/${encodeURIComponent(game)}/live-controls/run`, body('inspect'));
      if(!current() || n !== serial) return;
      for(const a of r.actions || []) {
        const f = Array.from(host.querySelectorAll('[data-lc-action]')).find(x => x.dataset.lcAction === a.id);
        if(f) {
          const sw = f.querySelector('[data-lc-toggle]');
          let ready = a.available === true && (!sw || typeof a.value === 'boolean');
          if(a.item_choices) {
            const select=Array.from(f.querySelectorAll('select[data-lc-param]')).find(el=>el.dataset.lcParam===a.item_choices.parameter);
            if(select) {
              const allowed=new Set(Array.isArray(a.item_choices.values) ? a.item_choices.values : []);
              for(const option of select.options) option.disabled=!allowed.has(option.value);
              if(!Array.from(select.options).some(o=>o.value===select.value&&!o.disabled)) select.value=Array.from(select.options).find(o=>!o.disabled)?.value || '';
              if(!select.value) ready=false;
            } else ready=false;
          }
          f.disabled = !ready; f.dataset.available = String(ready);
          if(sw && typeof a.value === 'boolean') { sw.checked = a.value; sw.dataset.confirmed = String(a.value); }
          f.querySelector('[data-lc-availability]').textContent=ready ? (sw ? (a.value ? 'On' : 'Off') + ' in this session.' : 'Available in this session.') : a.reason || 'Unavailable in the current mode or scene.';
        }
      }
      say('Revision checked. Available controls apply to this session only; mode is checked again on every click.');
    }
    function enableChecked(n) {
      if(!current() || n !== serial) return;
      busy = false;
      for(const b of host.querySelectorAll('button,select,input')) if(!b.closest('[data-lc-pso]')) b.disabled = false;
      for(const f of host.querySelectorAll('[data-lc-action]')) f.disabled = f.dataset.available !== 'true';
    }
    function valuesFor(a, field, desired) {
      const values = {};
      for(const p of a.parameters) {
        if(toggle(a) && p.id === a.toggle_parameter) { values[p.id]=desired; continue; }
        const el = Array.from(field.querySelectorAll('[data-lc-param]')).find(el=>el.dataset.lcParam===p.id);
        if(!el || !el.reportValidity()) return null;
        values[p.id] = p.kind==='integer' ? Number(el.value) : p.kind==='boolean' ? el.checked : el.value;
      }
      return values;
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
        q('[data-lc-missing]').innerHTML = Object.entries(d.categories).filter(([k])=>!covered.has(k)).map(([key,label])=>{
          const assessment=d.profile?.assessments?.[key];
          return `<p><small>${esc(label)} — ${assessment ? esc(assessment.reason)+' ('+esc(assessment.scope)+')' : 'needs game-specific discovery / verification, or an applicability assessment.'}</small></p>`;
        }).join('');
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
        enableChecked(n);
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
        const values = valuesFor(a, b.closest('fieldset')); if(!values) return;
        const n=serial; disable(true); say('Applying to the selected session…');
        try { const result = await job(`/api/games/${encodeURIComponent(game)}/live-controls/run`, body('apply', a.id, values));
          if(n===serial) say(result.result?.result?.error || `${a.label}: completed. Refresh / check mode before another action.`); }
        catch(e) { if(n===serial) say(e.message); }
        finally { if(current() && n===serial) disable(false); }
      }
    }
    host.addEventListener('click', click);
    const change = async e => {
      if(e.target.hasAttribute('data-lc-toggle')) {
        const sw=e.target, f=sw.closest('[data-lc-action]'), a=data?.profile?.actions.find(a=>a.id===sw.dataset.lcToggle);
        if(busy || !game || !sid || !a || !toggle(a) || f.dataset.available !== 'true') { sw.checked=sw.dataset.confirmed==='true'; return; }
        const desired=sw.checked, values=valuesFor(a,f,desired), n=serial; if(!values) { sw.checked=sw.dataset.confirmed==='true'; return; }
        disable(true); say(`${a.label}: ${desired ? 'enabling' : 'disabling'}...`);
        try {
          await job(`/api/games/${encodeURIComponent(game)}/live-controls/run`,body('apply',a.id,values));
          if(!current() || n!==serial) return;
          await probe(n);
          if(!current() || n!==serial) return;
          if(f.dataset.available!=='true' || sw.checked!==desired) throw Error('The requested switch state was not confirmed. Refresh / check mode before another action.');
          say(`${a.label}: ${desired ? 'on' : 'off'}. Native state checked.`);
          enableChecked(n);
        } catch(error) {
          if(current() && n===serial) { sw.checked=sw.dataset.confirmed==='true'; say(error.message); disable(false); }
        }
        return;
      }
      if(e.target.hasAttribute('data-lc-session')) {
        ++serial; sid=e.target.value; pso?.dispose(); q('[data-lc-pso]').innerHTML='';
        for(const f of host.querySelectorAll('[data-lc-action]')) { f.disabled=true; f.dataset.available='false'; }
        enableChecked(serial); say('Refresh / check mode to enable this session.');
      }
      if(e.target.hasAttribute('data-lc-unlocks')) {
        const desired=e.target.checked, n=serial; e.target.disabled=true;
        try { await io.api('/api/custom-build-unlocks/policy', {enabled:desired}); if(n===serial) say(desired ? 'Unlock-all required for every custom build; each build needs its own verification.' : 'Shared unlock-all requirement disabled.'); }
        catch(err) { if(n===serial) { e.target.checked=!desired; say(err.message); } } finally { if(current() && n===serial) e.target.disabled=false; }
      }
    };
    host.addEventListener('change', change);
    return {refresh, checkMode, setGame(gid) { if(game === gid) return; ++serial; game=gid || ''; pinned=''; busy=false; data=null; refresh(); },
      dispose() { stopped=true; ++serial; pso?.dispose(); host.removeEventListener('click',click); host.removeEventListener('change',change); if(host._liveControls===token) host._liveControls=null; },
      ready: refresh().then(()=>initial.autoCheck ? checkMode() : undefined)};
  }
  return {mount, actionHTML};
});
