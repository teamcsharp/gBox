(function (root) {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function card(row) {
    const d = row.delivery || {};
    const section = (title, values, empty) => `<div><h4>${title}</h4>${values?.length ? `<ul>${values.map(x => `<li style="white-space:pre-wrap">${esc(x)}</li>`).join('')}</ul>` : `<p class="mut">${empty}</p>`}</div>`;
    return `<article class="req" data-id="${esc(row.id)}" style="padding:14px">
      <button class="act" data-feature-report="${esc(row.id)}" style="float:right">Full task &amp; evidence</button>
      <b>#${esc(row.number)} ${esc(row.title)}</b>
      <p class="mut">${row.automated ? 'Backend subtask' : 'Task'}${row.completed ? ' · ' + esc(new Date(row.completed * 1000).toLocaleString()) : ''} · ${row.documented ? 'Delivery notes recorded' : 'Legacy completion — details need documenting'}</p>
      ${section('What was added', d.added, 'Not recorded for this task.')}
      ${section('What was accomplished', d.accomplished, 'See the recorded task reply below.')}
      ${section('Where to find / experience it', d.where, 'Open Full task & evidence for the original conversation.')}
      ${section('What to test', d.test_steps, 'No reproducible test steps were recorded.')}
      ${section('New mods', d.mods, row.linked_mods?.length ? 'Linked playable mods:' : 'No new mods recorded.')}
      ${(row.linked_mods || []).map(m => `<p>${esc(m.title)} · ${esc(m.game_title)} · ${m.verified ? 'Verified' : 'Not verified'} <button class="act" data-feature-mod="${esc(m.id)}">Open / play mod</button></p>`).join('')}
      <p><b>Verification:</b> ${esc(d.verification || 'Not recorded in delivery notes; completion status alone is not proof.')}</p>
      <details><summary>Recorded task reply &amp; changed files</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(row.completion_note)}</pre>${section('Files changed', row.files_changed, 'No files recorded.')}</details>
    </article>`;
  }
  function create(host, api, onReport, onMod) {
    let offset = 0, query = '', serial = 0, timer, signature = '';
    host.innerHTML = `<p class="mut">Every completed task and backend subtask, with delivery notes, tests and linked mods. Reopened work leaves this list until completed again.</p><div style="display:flex;gap:8px"><input type="search" data-search aria-label="Search features" placeholder="Search task, feature, game, mod or file" style="flex:1;min-width:0"><button class="act" data-refresh>Refresh</button></div><p data-count role="status"></p><div data-rows></div><div style="display:flex;gap:8px;margin-top:12px"><button class="act" data-prev>Previous</button><button class="act" data-next>Next</button></div>`;
    async function refresh() {
      const current = ++serial;
      const result = await api(`/api/requests/features?offset=${offset}&limit=25&q=${encodeURIComponent(query)}`).catch(e => ({error:e.message}));
      if (current !== serial) return;
      if (!result.ok) { host.querySelector('[data-count]').textContent = result.error || 'Features could not be loaded. Try Refresh.'; return; }
      const data = result.data;
      if (offset && offset >= data.matched) { offset = Math.max(0, Math.floor((data.matched - 1) / 25) * 25); return refresh(); }
      host.querySelector('[data-count]').textContent = `${data.total} completed tasks · ${data.matched} matching · ${data.matched ? offset + 1 : 0}–${offset + data.items.length}`;
      const nextSignature = JSON.stringify(data.items);
      if (signature !== nextSignature) { host.querySelector('[data-rows]').innerHTML = data.items.map(card).join('') || '<p class="mut">No matching completed tasks yet.</p>'; signature = nextSignature; }
      host.querySelector('[data-prev]').disabled = offset === 0;
      host.querySelector('[data-next]').disabled = offset + data.items.length >= data.matched;
    }
    host.querySelector('[data-search]').oninput = e => { query = e.target.value; offset = 0; ++serial; clearTimeout(timer); timer = setTimeout(refresh, 250); };
    host.querySelector('[data-prev]').onclick = () => { offset = Math.max(0, offset - 25); refresh(); };
    host.querySelector('[data-next]').onclick = () => { offset += 25; refresh(); };
    host.querySelector('[data-refresh]').onclick = refresh;
    host.onclick = e => { const report = e.target.closest('[data-feature-report]'), mod = e.target.closest('[data-feature-mod]'); if (report) onReport(report.dataset.featureReport); if (mod) onMod(mod.dataset.featureMod); };
    return {refresh};
  }
  const api = {card, create};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GBoxRequestFeatures = api;
})(typeof window !== 'undefined' ? window : globalThis);
