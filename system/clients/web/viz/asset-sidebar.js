// Shared by the desktop shell and standalone browser. No model/LLM work runs while listing assets.
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  window.GBoxAssets = { mount(options) {
    const root = document.createElement('div'); root.id = 'asset-sidebar'; root.setAttribute('aria-label', 'Extracted asset library');
    options.host.append(root);
    const css = document.createElement('style'); css.textContent = `
      .app.has-assets { grid-template-columns:200px minmax(0,1fr) var(--assets-width,280px); }
      body.navc .app.has-assets { grid-template-columns:0 minmax(0,1fr) var(--assets-width,280px); }
      .app.has-assets > main { min-width:0; }
      #asset-sidebar { box-sizing:border-box; width:var(--assets-width,280px); min-height:0; height:100%; display:flex; flex-direction:column; border-left:1px solid var(--line); background:var(--bg); color:var(--fg); overflow:hidden; font:13px/1.4 system-ui,sans-serif; }
      #asset-sidebar * { box-sizing:border-box; }
      #asset-sidebar button,#asset-sidebar select,#asset-sidebar input { font:inherit; color:var(--fg); background:var(--card); border:1px solid var(--line); border-radius:5px; padding:5px; min-width:0; }
      #asset-sidebar button { cursor:pointer; } #asset-sidebar button:disabled { cursor:wait; opacity:.55; }
      #asset-sidebar .as-head { display:flex; align-items:center; gap:6px; padding:9px; flex:none; border-bottom:1px solid var(--line); }
      #asset-sidebar .as-head b { flex:1; } #asset-sidebar .as-controls { display:grid; gap:6px; padding:9px; flex:none; }
      #asset-sidebar .as-pair { display:grid; grid-template-columns:1fr 1fr; gap:5px; }
      #asset-sidebar .as-count,#asset-sidebar .as-message { padding:3px 9px; font-size:12px; color:var(--mut); }
      #asset-sidebar .as-list { flex:1; min-height:0; overflow:auto; overscroll-behavior:contain; padding:0 7px 7px; }
      #asset-sidebar .as-row { display:grid; grid-template-columns:64px minmax(0,1fr); gap:7px; padding:8px 2px; border-bottom:1px solid var(--line); }
      #asset-sidebar .as-thumb { padding:0; border:0; background:var(--card); width:64px; height:64px; overflow:hidden; }
      #asset-sidebar .as-thumb img { width:100%; height:100%; object-fit:contain; display:block; }
      #asset-sidebar .as-name { font-weight:600; overflow-wrap:anywhere; } #asset-sidebar .as-sub { color:var(--mut); font-size:11px; overflow-wrap:anywhere; }
      #asset-sidebar .as-actions { display:flex; gap:4px; margin-top:4px; } #asset-sidebar .as-actions button { padding:2px 6px; font-size:11px; }
      #asset-sidebar .as-more { width:100%; margin-top:8px; } #asset-sidebar .as-changed { margin:0 9px 6px; }
      #asset-sidebar .as-group { border-bottom:1px solid var(--line); }
      #asset-sidebar .as-group > summary { display:flex; gap:6px; align-items:center; cursor:pointer; padding:9px 2px; list-style:none; }
      #asset-sidebar .as-group > summary::before { content:'›'; color:var(--mut); } #asset-sidebar .as-group[open] > summary::before { content:'⌄'; }
      #asset-sidebar .as-group > summary img { width:32px; height:32px; object-fit:contain; background:var(--card); }
      #asset-sidebar .as-group > summary b { flex:1; overflow-wrap:anywhere; font-size:12px; } #asset-sidebar .as-group > summary span { color:var(--mut); font-size:11px; }
      #asset-sidebar .as-group-rows { padding-left:7px; } #asset-sidebar .as-group-more { width:100%; margin:5px 0 9px; }
      #asset-sidebar .as-tex { margin-top:5px; } #asset-sidebar .as-tex summary { cursor:pointer; color:var(--mut); font-size:11px; list-style:none; }
      #asset-sidebar .as-tex summary::before { content:'› '; } #asset-sidebar .as-tex[open] summary::before { content:'⌄ '; }
      #asset-sidebar .as-tex .as-row { grid-template-columns:40px minmax(0,1fr); padding:5px 0; } #asset-sidebar .as-tex .as-thumb { width:40px; height:40px; }
      #asset-sidebar.closed .as-head { padding:5px 3px; } #asset-sidebar.closed .as-head > :not(.as-toggle),#asset-sidebar.closed > :not(.as-head) { display:none; }
      #asset-sidebar.closed .as-toggle { writing-mode:vertical-rl; padding:8px 4px; }
      .asset-dialog { background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:10px; width:min(600px,90vw); max-height:85vh; overflow:auto; padding:16px; }
      .asset-dialog::backdrop { background:#0009; } .asset-dialog img { width:100%; max-height:50vh; object-fit:contain; background:var(--card); }
      .asset-dialog .as-dialog-bar { display:flex; gap:8px; align-items:center; margin-bottom:10px; } .asset-dialog .as-dialog-bar b { flex:1; }
      .asset-dialog button,.asset-dialog a { font:inherit; color:var(--fg); border:1px solid var(--line); background:var(--card); border-radius:5px; padding:6px 10px; text-decoration:none; cursor:pointer; }
    `; document.head.append(css);
    const $ = selector => root.querySelector(selector), state = { items: [], textures: new Map(), groups: new Map(), revision: 0, busy: false, polling: false, signature: '', disposed: false, retryTimer: 0, retryDelay: 0 };
    let prefs = {}; try { prefs = JSON.parse(localStorage.getItem('gbox_asset_sidebar') || '{}'); } catch {}
    const expanded = new Set(prefs.expanded || []);
    root.innerHTML = `<div class="as-head"><b>Assets</b><button class="as-refresh" title="Refresh extracted assets" aria-label="Refresh extracted assets">↻</button><button class="as-toggle" aria-expanded="true" title="Collapse asset sidebar">›</button></div>
      <div class="as-controls"><input class="as-search" type="search" placeholder="Search all assets…" aria-label="Search extracted assets"><select class="as-sort" aria-label="Sort extracted assets"><option value="newest">Newest first</option><option value="copied">Recently copied</option><option value="oldest">Oldest first</option><option value="name">Name A–Z</option><option value="game">Game A–Z</option><option value="kind">Asset type</option><option value="size">Largest first</option></select><div class="as-pair"><select class="as-kind" aria-label="Filter asset type"><option value="">All types</option></select><select class="as-game" aria-label="Filter source game"><option value="">All games</option></select></div></div>
      <div class="as-count" aria-live="polite">Loading assets…</div><button class="as-changed" hidden>New assets available · Refresh</button><div class="as-message" role="status"></div><div class="as-list" tabindex="0" aria-label="Assets grouped by game title"><div class="as-rows"></div></div>`;
    $('.as-search').value = prefs.q || ''; $('.as-sort').value = prefs.sort || 'newest';
    function save() { try { localStorage.setItem('gbox_asset_sidebar', JSON.stringify({ q: $('.as-search').value, sort: $('.as-sort').value, kind: $('.as-kind').value, game: $('.as-game').value, closed: root.classList.contains('closed'), expanded: [...expanded] })); } catch {} }
    function collapse(closed) {
      root.classList.toggle('closed', closed); options.host.style.setProperty('--assets-width', closed ? '36px' : '280px');
      $('.as-toggle').textContent = closed ? 'Assets' : '›'; $('.as-toggle').setAttribute('aria-expanded', String(!closed)); save();
      if (!closed) load();
    }
    $('.as-toggle').onclick = () => collapse(!root.classList.contains('closed'));
    const url = path => options.url(path);
    const bytes = n => n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : n >= 1000 ? (n / 1000).toFixed(1) + ' KB' : n + ' B';
    const date = ts => ts ? new Date(ts * 1000).toLocaleString() : '';
    function row(a) {
      return `<div class="as-row" data-id="${esc(a.id)}"><button class="as-thumb" data-action="view" aria-label="Preview ${esc(a.name)}"><img loading="lazy" src="${esc(url(a.preview_url))}" alt="${esc(a.name)} thumbnail"></button><div><div class="as-name">${esc(a.name)}</div><div class="as-sub">${esc(a.game)} · ${esc(a.kind)} · ${esc(a.format)} · ${bytes(a.size)}</div><div class="as-sub" title="${esc(date(a.added))}">${$('.as-sort').value === 'copied' && a.copied ? 'Copied ' + esc(date(a.copied)) : 'Added ' + esc(date(a.added))}</div><div class="as-actions"><button data-action="copy">Copy</button><button data-action="download">Download</button></div>${a.texture_count || a.file_count ? textureTree(a) : ''}</div></div>`;
    }
    // Model companions stay collapsed; fetch their rows only when expanded.
    function textureTree(a) {
      const labels = [a.texture_count ? `Textures (${a.texture_count})` : '', a.file_count ? `Files (${a.file_count})` : ''].filter(Boolean);
      return `<details class="as-tex" data-owner="${esc(a.id)}"><summary>${labels.join(' / ')}</summary><div class="as-tex-rows"></div></details>`;
    }
    async function loadTextures(element) {
      if (element.dataset.loaded) return; element.dataset.loaded = '1';
      const owner = element.dataset.owner, revision = state.revision, rows = element.querySelector('.as-tex-rows');
      rows.innerHTML = '<div class="as-sub">Loading textures…</div>';
      try {
        const items = [];
        for (let offset = 0; ; offset += 200) {
          const page = await options.api('/api/assets?' + new URLSearchParams({ sort: $('.as-sort').value, game: $('.as-game').value, owner, offset, limit: 200 }));
          if (revision !== state.revision || state.disposed || !element.isConnected) return;
          items.push(...page.items); if (!page.has_more) break;
        }
        for (const t of items) state.textures.set(t.id, t);
        rows.innerHTML = items.length ? items.map(row).join('') : '<div class="as-sub">No companion files</div>';
      } catch (e) {
        if (revision !== state.revision || state.disposed || !element.isConnected) return;
        delete element.dataset.loaded; rows.innerHTML = `<div class="as-sub">Files failed to load: ${esc(e.message)}</div>`;
      }
    }
    function query(game, offset = 0, fresh = false) { return (game === undefined ? '/api/asset-groups?' : '/api/assets?') + new URLSearchParams({ q: $('.as-search').value, sort: $('.as-sort').value, kind: $('.as-kind').value, game: game ?? $('.as-game').value, offset, limit: 60, ...(fresh ? { fresh: 1 } : {}) }); }
    const signature = page => JSON.stringify([page.total, page.nested, page.hidden_assets, page.hidden_textures, page.groups.map(g => [g.title, g.count, g.copied, g.added])]);
    const groupElement = title => [...root.querySelectorAll('.as-group')].find(el => el.dataset.game === title);
    async function loadGroup(title) {
      const group = state.groups.get(title), revision = state.revision, element = groupElement(title);
      if (!group || group.loading || !group.more || !element) return;
      group.loading = true; const more = element.querySelector('.as-group-more'); more.disabled = true;
      try {
        const page = await options.api(query(title, group.items.length));
        if (revision !== state.revision || state.disposed) return;
        const known = new Set(group.items.map(a => a.id)), fresh = page.items.filter(a => !known.has(a.id));
        group.items.push(...fresh); state.items = [...state.groups.values()].flatMap(g => g.items);
        element.querySelector('.as-group-rows').insertAdjacentHTML('beforeend', fresh.map(row).join(''));
        group.more = page.has_more; more.hidden = !group.more;
        more.textContent = `Load more · ${group.items.length} of ${page.total}`;
      } catch (e) { if (revision === state.revision) $('.as-message').textContent = 'Could not load this title: ' + e.message; }
      finally { group.loading = false; more.disabled = false; }
    }
    function facets(selector, values, label, preferred) {
      const el = $(selector), selected = el.value || preferred || '';
      el.innerHTML = `<option value="">${label}</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
      if (values.includes(selected)) el.value = selected;
    }
    // The control plane indexes the asset folders in the background; until its first index exists (or while a slow
    // control plane times the request out) the list says so and asks again with backoff instead of failing.
    const slow = e => /timeout|timed out|abort/i.test(String(e?.name || '') + ' ' + String(e?.message || ''));
    function retryLater(revision) {
      clearTimeout(state.retryTimer);
      state.retryDelay = Math.min(Math.max(state.retryDelay * 2, 2000), 15000);
      $('.as-count').textContent = 'Indexing assets…'; $('.as-message').textContent = '';
      state.retryTimer = setTimeout(() => { if (revision === state.revision && !state.disposed) load(); }, state.retryDelay);
    }
    async function load(fresh = false) {
      if (state.disposed || root.classList.contains('closed')) return;
      const revision = ++state.revision; state.busy = true; clearTimeout(state.retryTimer);
      $('.as-message').textContent = '';
      try {
        const page = await options.api(query(undefined, 0, fresh));
        if (revision !== state.revision || state.disposed) return;
        if (page.indexing) { retryLater(revision); return; }
        state.retryDelay = 0;
        state.groups = new Map(page.groups.map(g => [g.title, {items: [], more: true, loading: false}])); state.items = []; state.textures = new Map();
        $('.as-rows').innerHTML = page.groups.map(g => `<details class="as-group" data-game="${esc(g.title)}" ${expanded.has(g.title) ? 'open' : ''}><summary><img loading="lazy" src="${esc(url(g.preview_url))}" alt=""><b>${esc(g.title)}</b><span>${g.count}</span></summary><div class="as-group-rows"></div><button class="as-group-more">Load assets · ${g.count}</button></details>`).join('');
        $('.as-list').scrollTop = 0;
        facets('.as-kind', page.kinds, 'All types', prefs.kind); facets('.as-game', page.games, 'All games', prefs.game);
        prefs = {}; $('.as-changed').hidden = true; state.signature = signature(page);
        $('.as-count').textContent = `${page.total} assets · ${page.groups.length} titles${page.nested ? ` · ${page.nested} files inside` : ''}${page.total + (page.hidden_assets ?? page.hidden_textures ?? 0) !== page.total_all ? ` · ${page.total_all} total` : ''}`;
        if (!page.total) $('.as-rows').innerHTML = '<p>No assets match these filters.</p>';
        await Promise.all(page.groups.filter(g => expanded.has(g.title)).map(g => loadGroup(g.title))); save();
      } catch (e) {
        if (revision !== state.revision || state.disposed) return;
        if (slow(e)) retryLater(revision); else $('.as-message').textContent = 'Could not load assets: ' + e.message;
      } finally { if (revision === state.revision) state.busy = false; }
    }
    const refresh = () => load();
    $('.as-refresh').onclick = () => load(true); $('.as-changed').onclick = refresh;   // ↻ also rescans every asset file
    let debounce;
    $('.as-search').oninput = () => { clearTimeout(debounce); debounce = setTimeout(refresh, 200); };
    for (const selector of ['.as-sort', '.as-kind', '.as-game']) $(selector).onchange = refresh;
    root.addEventListener('toggle', e => {
      if (e.target.classList.contains('as-tex')) { if (e.target.open && e.target.isConnected) loadTextures(e.target); return; }
      if (!e.target.classList.contains('as-group') || !e.target.isConnected) return;
      const title = e.target.dataset.game;
      if (e.target.open) { expanded.add(title); const group = state.groups.get(title); if (group && !group.items.length) loadGroup(title); }
      else expanded.delete(title);
      save();
    }, true);
    async function copy(a, button) {
      button.disabled = true; $('.as-message').textContent = 'Copying ' + a.name + '…';
      try { await options.api(`/api/assets/${a.id}/copy`, {});
        if ($('.as-sort').value === 'copied') await load();
        $('.as-message').textContent = a.format === 'GLB' || a.format === 'GLTF' || a.format === 'UAP' ? 'Copied. Paste in Blender with Ctrl+Shift+V (gBox add-on).' : 'Copied to the gBox asset clipboard.';
      } catch (e) { $('.as-message').textContent = 'Copy failed: ' + e.message; }
      finally { button.disabled = false; }
    }
    function preview(a) {
      const dialog = document.createElement('dialog'); dialog.className = 'asset-dialog';
      dialog.innerHTML = `<div class="as-dialog-bar"><b>${esc(a.name)}</b><button aria-label="Close asset preview">×</button></div><img src="${esc(url(a.preview_url))}" alt="${esc(a.name)} preview"><p>${esc(a.game)} · ${esc(a.kind)} · ${esc(a.format)} · ${bytes(a.size)}</p><p>Added ${esc(date(a.added))}${a.copied ? '<br>Last copied ' + esc(date(a.copied)) : ''}</p><button data-copy>Copy asset</button> <button data-download>Download</button>`;
      document.body.append(dialog); dialog.querySelector('.as-dialog-bar button').onclick = () => dialog.close();
      dialog.onclose = () => dialog.remove(); dialog.onclick = e => { if (e.target === dialog) dialog.close(); };
      dialog.querySelector('[data-copy]').onclick = e => copy(a, e.target);
      dialog.querySelector('[data-download]').onclick = () => download(a); dialog.showModal();
    }
    function download(a) { const path = url(a.file_url); if (options.download) options.download(path); else { const link = document.createElement('a'); link.href = path; link.download = a.name; link.click(); } }
    root.onclick = e => {
      const more = e.target.closest('.as-group-more'); if (more) { loadGroup(more.closest('.as-group').dataset.game); return; }
      const button = e.target.closest('[data-action]'), id = button?.closest('[data-id]')?.dataset.id;
      const a = state.items.find(a => a.id === id) || state.textures.get(id); if (!a) return;
      if (button.dataset.action === 'view') preview(a); else if (button.dataset.action === 'copy') copy(a, button); else download(a);
    };
    const interval = setInterval(async () => {
      if (state.busy || state.polling || state.disposed || root.classList.contains('closed') || (document.hidden && !options.backgroundUpdates)) return;
      state.polling = true;
      try {
        const revision = state.revision, page = await options.api(query());
        if (revision !== state.revision || state.disposed || root.classList.contains('closed')) return;
        if (signature(page) !== state.signature) { if ($('.as-list').scrollTop < 40 && state.items.length <= 60) load(); else $('.as-changed').hidden = false; }
      } catch { /* Keep the current list during a reconnect; manual refresh exposes the error. */ }
      finally { state.polling = false; }
    }, 10000);
    // Apply saved filters before the first query, then expand them from server facets.
    for (const [selector, value] of [['.as-kind', prefs.kind], ['.as-game', prefs.game]]) if (value) $(selector).insertAdjacentHTML('beforeend', `<option value="${esc(value)}" selected>${esc(value)}</option>`);
    collapse(!!prefs.closed);
    // reveal(q): open the sidebar filtered to q (the pick whip's "Show in Assets")
    function reveal(q) { collapse(false); $('.as-search').value = String(q || ''); save(); refresh(); root.scrollIntoView?.({ block: 'nearest' }); }
    return { refresh, reveal, dispose() { state.disposed = true; clearInterval(interval); clearTimeout(debounce); clearTimeout(state.retryTimer); root.remove(); css.remove(); } };
  } };
})();
