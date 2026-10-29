(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GBoxPipStreamPicker = api;
})(globalThis, function() {
  'use strict';
  const KEY = 'gbox.pip.stream.v1:';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const origin = value => { try { const u = new URL(value); return /^https?:$/.test(u.protocol) ? u.origin : ''; } catch { return ''; } };
  const name = row => String(row?.detail?.worker_name || row?.worker_name || '');
  function identity(row) {
    return { worker: name(row), workerId: String(row?.worker || row?.worker_id || ''),
      installation: String(row?.federation?.authority || row?.detail?.installation_id || '') };
  }
  function sameInstance(saved, row) {
    if (!saved || !row) return false;
    const target = identity(row);
    if (saved.installation && target.installation) return saved.installation === target.installation;
    if (saved.worker && target.worker) return saved.worker.toLowerCase() === target.worker.toLowerCase();
    return !!saved.workerId && saved.workerId === target.workerId;
  }
  function preference(row, pinned = false) {
    return { sid: String(row.session_id), ...identity(row), pinned: !!pinned };
  }
  function status(row, hosts = []) {
    if (!row || row.warm || row.stopping || row.state !== 'running') return 'ended';
    const host = hosts.find(h => h.current_run?.session_id === row.session_id ||
      (h.warm || []).some(w => w.session_id === row.session_id) || h.current_run?.mercmode_predecessor?.session_id === row.session_id);
    if ((host?.warm || []).some(w => w.session_id === row.session_id)) return 'warm';
    if (host?.current_run?.mercmode_predecessor?.session_id === row.session_id && host.current_run.session_id !== row.session_id) return 'warm';
    if (row.worker_online === false || host?.online === false) return 'offline';
    if (host?.current_run?.session_id === row.session_id) {
      if (host.current_run.handover) return 'switching';
      if (host.current_run.phase !== 'playing') return 'starting';
    }
    return 'ready';
  }
  function candidates(rows = [], hosts = []) {
    return rows.filter(row => !['ended', 'warm'].includes(status(row, hosts)))
      .map(row => ({ row, status: status(row, hosts) }))
      .sort((a, b) => name(a.row).localeCompare(name(b.row)) || String(a.row.session_id).localeCompare(String(b.row.session_id)));
  }
  function resolve(saved, rows = [], hosts = []) {
    if (!saved) return null;
    const live = rows.filter(row => sameInstance(saved, row) && status(row, hosts) === 'ready');
    const exact = live.find(row => row.session_id === saved.sid);
    if (exact) return exact;
    // The scheduler's committed turn beats a parked predecessor, including a different title after rotation.
    const current = hosts.find(h => (h.name && h.name.toLowerCase() === saved.worker?.toLowerCase()) || h.id === saved.workerId)?.current_run;
    if (current?.phase === 'playing' && !current.handover) {
      const next = live.find(row => row.session_id === current.session_id);
      if (next) return next;
    }
    return live.sort((a,b) => (b.started || 0) - (a.started || 0))[0] || null;
  }
  function cycle(rows, sid, direction) {
    if (!rows.length) return null;
    const i = rows.findIndex(row => row.session_id === sid), step = direction < 0 ? -1 : 1;
    return rows[i < 0 ? (step < 0 ? rows.length - 1 : 0) : (i + step + rows.length) % rows.length];
  }
  function create(io) {
    let loadedOrigin = null, saved = null, pending = null, generation = 0;
    const load = () => {
      const source = origin(io.origin());
      if (source !== loadedOrigin) {
        loadedOrigin = source; saved = null; pending = null; generation++;
        try {
          const value = JSON.parse(io.storage?.getItem(KEY + source) || 'null');
          if (source && value && /^[a-zA-Z0-9_-]{1,160}$/.test(value.sid) &&
            [value.worker, value.workerId, value.installation].some(x => typeof x === 'string' && x.length > 0 && x.length <= 160))
            saved = {sid:value.sid, worker:String(value.worker || '').slice(0,160), workerId:String(value.workerId || '').slice(0,160),
              installation:String(value.installation || '').slice(0,160), pinned:value.pinned === true};
        } catch {}
      }
      return pending || saved;
    };
    const persist = value => { saved = value; try { if (loadedOrigin) io.storage?.setItem(KEY + loadedOrigin, JSON.stringify(saved)); } catch {} };
    return {
      get preference() { return load(); },
      get revision() { load(); return generation; },
      allows(row) { const p = load(); return !p?.pinned || sameInstance(p, row); },
      remember(row) {
        const p = load();
        if (!row || pending || (p?.pinned && !sameInstance(p, row))) return;
        persist(preference(row, p?.pinned));
      },
      async target() { const p = load(), rev = generation, source = loadedOrigin; if (!p) return null;
        const data = await io.read(); return rev === generation && source === origin(io.origin()) ? resolve(p, data.rows, data.hosts) : null; },
      async select(sid, valid = () => true) {
        load(); const rev = ++generation, source = loadedOrigin; pending = null;
        const data = await io.read();
        if (rev !== generation || !valid() || source !== origin(io.origin())) return false;
        const row = data.rows.find(r => r.session_id === sid && status(r, data.hosts) === 'ready');
        if (!row) throw Error('That stream is no longer ready. Choose a current game.');
        pending = preference(row, true);
        // Once accepted, closing the menu as part of showing the stream must not cancel its own selection.
        const current = () => rev === generation && source === origin(io.origin());
        try {
          const shown = await io.show(row, current);
          if (!current() || shown === false) return false;
          persist(pending); return true;
        } finally { if (current()) pending = null; }
      }
    };
  }
  // A single outstanding JPEG, at most four visible cards per pass. Stop aborts the current image and the next timer.
  function previews(io) {
    let stopped = false, timer = null, active = null;
    const later = io.setTimeout || setTimeout, clear = io.clearTimeout || clearTimeout;
    async function refresh() {
      for (const item of io.items().slice(0,4)) {
        if (stopped) return;
        active = new AbortController();
        const abort = active, timeout = later(() => abort.abort(), 3500);
        try { await io.load(item, abort.signal); } catch {} finally { clear(timeout); }
      }
      if (!stopped) timer = later(refresh, 5000);
    }
    const ready = refresh();
    return {ready, stop() { stopped = true; clear(timer); active?.abort(); }};
  }
  const labels = {ready:'Loading preview…', offline:'PC offline', starting:'Starting game…', switching:'Switching game…'};
  function previewImage(img, url, valid, signal) {
    return new Promise(resolve => {
      const badge = img.parentElement.querySelector('[data-stream-state]');
      let settled = false;
      const finish = text => {
        if (settled) return;
        settled = true; img.onload = img.onerror = null; signal.removeEventListener('abort', abort);
        if (valid()) badge.textContent = text;
        resolve();
      };
      const abort = () => { if (!settled) { img.removeAttribute('src'); finish('Preview unavailable'); } };
      signal.addEventListener('abort', abort, {once:true});
      img.onload = () => { if (valid()) img.classList.add('loaded'); finish('Live'); };
      img.onerror = () => finish('Preview unavailable');
      Promise.resolve().then(url).then(source => {
        if (settled) return; // an earlier URL lookup must not clear a newer load's image or handlers
        if (valid() && !signal.aborted) img.src = source; else abort();
      }, () => finish('Preview unavailable'));
    });
  }
  function html(entries, sid, title = row => row.title || row.game_title || row.game_id || 'Game') {
    return '<div class="pip-stream-heading"><strong>Streams</strong><span>View another instance</span></div>' +
      '<div class="pip-stream-carousel"><button type="button" data-stream-step="-1" aria-label="Previous stream" title="Previous stream">‹</button>' +
      '<div class="pip-stream-cards" role="group" aria-label="Running game streams">' + (entries.length ? entries.map(({row,status:state}) =>
        `<button type="button" class="pip-stream-card${row.session_id === sid ? ' selected' : ''}" data-stream-sid="${esc(row.session_id)}" aria-pressed="${row.session_id === sid}" ${state === 'ready' ? '' : 'disabled'} title="${esc(name(row))} · ${esc(title(row))} · ${esc(row.session_id)}">` +
        `<span class="pip-stream-picture"><img alt="" data-stream-preview="${esc(row.session_id)}"><span data-stream-state>${esc(labels[state])}</span>${row.session_id === sid ? '<b class="pip-stream-selected">Watching</b>' : ''}</span>` +
        `<strong>${esc(name(row) || identity(row).workerId || 'Instance')}</strong><span>${esc(title(row))}</span></button>`).join('') :
        '<p class="pip-stream-empty">No active streams. Waiting for a game to be ready.</p>') + '</div>' +
      '<button type="button" data-stream-step="1" aria-label="Next stream" title="Next stream">›</button></div>' +
      '<p class="pip-stream-status" role="status">Switching views keeps every game running.</p>';
  }
  function mount(root, io) {
    let stopped = false, entries = [], preview = null, busy = false;
    root.innerHTML = '<p class="pip-stream-empty" role="status">Loading streams…</p>';
    const valid = () => !stopped && io.valid?.() !== false;
    const message = value => { if (valid()) root.querySelector('.pip-stream-status').textContent = value; };
    async function refresh() {
      try {
        const data = await io.read(); if (!valid()) return;
        entries = candidates(data.rows, data.hosts);
        root.innerHTML = html(entries, io.current(), io.title);
        root.querySelectorAll('[data-stream-step]').forEach(button => { button.disabled = entries.filter(e => e.status === 'ready').length < 2; });
        root.querySelector('.selected')?.scrollIntoView?.({block:'nearest',inline:'nearest'});
        io.resized?.();
        preview = previews({
          items: () => {
            const bounds = root.querySelector('.pip-stream-cards').getBoundingClientRect();
            return [...root.querySelectorAll('[data-stream-preview]')].filter(img => {
              const rect = img.getBoundingClientRect();
              return entries.some(e => e.row.session_id === img.dataset.streamPreview && e.status === 'ready') && rect.right > bounds.left && rect.left < bounds.right;
            });
          },
          load: (img, signal) => previewImage(img, () => io.preview(img.dataset.streamPreview), valid, signal)
        });
      } catch (error) { if (valid()) root.textContent = 'Streams unavailable: ' + error.message; }
    }
    async function click(event) {
      const button = event.target.closest?.('[data-stream-sid], [data-stream-step]');
      if (!button || !valid() || busy || button.disabled) return;
      event.stopPropagation();
      const row = button.dataset.streamSid ? entries.find(e => e.row.session_id === button.dataset.streamSid)?.row :
        cycle(entries.filter(e => e.status === 'ready').map(e => e.row), io.current(), Number(button.dataset.streamStep));
      if (!row) return;
      busy = true; message('Opening stream…');
      try { await io.select(row.session_id, valid); }
      catch (error) { message(error.message); }
      finally { busy = false; }
    }
    root.addEventListener('click', click);
    const ready = refresh();
    return {ready, stop() { stopped = true; preview?.stop(); root.removeEventListener('click',click);
      root.querySelectorAll('[data-stream-preview]').forEach(img => img.removeAttribute('src')); }};
  }
  return {KEY, identity, sameInstance, status, candidates, resolve, cycle, create, previews, previewImage, html, mount};
});
