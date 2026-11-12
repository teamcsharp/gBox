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
    // Only live instances on online workers. 'offline' is dropped too (operator 2026-11-04: the Streams menu must
    // never list dead "PC offline" games). Such sessions are auto-reaped server-side; until a reap lands this keeps
    // them out of the menu immediately. 'starting'/'switching' stay: those are live games on an online worker.
    return rows.filter(row => !['ended', 'warm', 'offline'].includes(status(row, hosts)))
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
    const now = io.now || Date.now;
    let lastChoiceAt = now(); // a reload must restore its saved choice, not replay an old dispatch
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
    const canDispatch = d => {
      load();
      return !pending && !!d?.pip && !d.lapsed && ['start','switch'].includes(d.command)
        && /^[a-f0-9]{32}$/.test(d.id || '') && Number.isFinite(d.at) && d.at * 1000 > lastChoiceAt;
    };
    return {
      get preference() { return load(); },
      get revision() { load(); return generation; },
      canDispatch,
      allows(row) { const p = load(); return !p?.pinned || sameInstance(p, row); },
      remember(row) {
        const p = load();
        if (!row || pending || (p?.pinned && !sameInstance(p, row))) return;
        persist(preference(row, p?.pinned));
      },
      async target() { const p = load(), rev = generation, source = loadedOrigin; if (!p) return null;
        const data = await io.read(); return rev === generation && source === origin(io.origin()) ? resolve(p, data.rows, data.hosts) : null; },
      async broadcast(sid, valid = () => true) {
        load();
        const source = loadedOrigin;
        if (!source || !io.broadcast || !valid()) return false;
        const data = await io.read();
        if (!valid() || source !== origin(io.origin())) return false;
        const row = sid === 'auto' ? null : data.rows.find(r => r.session_id === sid && status(r, data.hosts) === 'ready');
        if (sid !== 'auto' && !row) throw Error('That stream is no longer ready. Choose a current game.');
        await io.broadcast(sid, row);
        return true;
      },
      async select(sid, valid = () => true, {dispatch} = {}) {
        load();
        if (dispatch && !canDispatch(dispatch)) return false;
        if (!dispatch) lastChoiceAt = now();
        const rev = ++generation, source = loadedOrigin; pending = null;
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
          if (dispatch) lastChoiceAt = now();
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
  function html(entries, sid, title = row => row.title || row.game_title || row.game_id || 'Game', broadcast = false) {
    return '<div class="pip-stream-heading"><strong>Streams</strong><span>View another instance</span>' +
      (broadcast ? '<button type="button" data-stream-broadcast="auto" title="Let the broadcast follow the active game again">Broadcast: Auto</button>' : '') + '</div>' +
      '<div class="pip-stream-carousel"><button type="button" data-stream-step="-1" aria-label="Previous stream" title="Previous stream">‹</button>' +
      '<div class="pip-stream-cards" role="group" aria-label="Running game streams">' + (entries.length ? entries.map(({row,status:state}) =>
        `<div class="pip-stream-entry"><button type="button" class="pip-stream-card${row.session_id === sid ? ' selected' : ''}" data-stream-sid="${esc(row.session_id)}" aria-pressed="${row.session_id === sid}" ${state === 'ready' ? '' : 'disabled'} title="${esc(name(row))} · ${esc(title(row))} · ${esc(row.session_id)}">` +
        `<span class="pip-stream-picture"><img alt="" data-stream-preview="${esc(row.session_id)}"><span data-stream-state>${esc(labels[state])}</span>${row.session_id === sid ? '<b class="pip-stream-selected">Watching</b>' : ''}</span>` +
        `<strong>${esc(name(row) || identity(row).workerId || 'Instance')}</strong><span>${esc(title(row))}</span></button>` +
        (broadcast ? `<button type="button" class="pip-stream-broadcast" data-stream-broadcast="${esc(row.session_id)}" ${state === 'ready' ? '' : 'disabled'} aria-label="Broadcast ${esc(title(row))} on ${esc(name(row))}">Broadcast</button>` : '') + '</div>').join('') :
        '<p class="pip-stream-empty">No active streams. Waiting for a game to be ready.</p>') + '<button type="button" class="pip-stream-card pip-stream-add-tile" data-stream-add title="Start a recent game into the PiP" aria-label="Add a game">' + '<span class="pip-stream-picture" style="display:flex;align-items:center;justify-content:center;font-size:34px;font-weight:300;line-height:1">+</span>' + '<strong>Add game</strong><span>Recent launches</span></button>' + '</div>' +
      '<button type="button" data-stream-step="1" aria-label="Next stream" title="Next stream">›</button></div>' +
      '<p class="pip-stream-status" role="status">Switching views keeps every game running.</p>';
  }
  function mount(root, io) {
    let stopped = false, entries = [], preview = null, busy = false;
    root.innerHTML = '<p class="pip-stream-empty" role="status">Loading streams…</p>';
    const valid = () => !stopped && io.valid?.() !== false;
    const message = value => { if (valid()) root.querySelector('.pip-stream-status').textContent = value; };
    // Right-click a stream entry to close that game. The stop itself is the operator's own action,
    // provided by the host as io.close(sid, row) (it confirms, then stops the session); this component
    // only draws the menu. Closing a game here is how the operator frees a worker (e.g. for MercMode).
    let menuEl = null;
    // Recently played games, for the + button: launch one into the PiP without leaving it.
    let addMenu = null;
    function dismissAdd() { if (addMenu) { addMenu.remove(); addMenu = null; } }
    async function openAdd(event) {
      const button = event.target.closest?.('[data-stream-add]');
      if (!button || !valid()) return;
      event.preventDefault(); event.stopPropagation();
      dismissAdd(); dismissMenu();
      const rect = button.getBoundingClientRect();
      addMenu = document.createElement('div');
      addMenu.className = 'pip-stream-menu pip-stream-add';
      addMenu.setAttribute('role', 'dialog');
      addMenu.style.cssText = 'position:fixed;z-index:95;width:min(360px,86vw);padding:8px;' +
        'background:#1b1f2a;border:1px solid #3a4152;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.55);' +
        'left:' + Math.round(Math.min(rect.left, window.innerWidth - 372)) + 'px;top:' + Math.round(rect.bottom + 6) + 'px;';
      addMenu.innerHTML = '<div style="padding:2px 2px 6px;font-size:11px;color:#9aa3b4">Start a game</div>' +
        '<input data-add-search type="search" placeholder="Search title or system…" autocomplete="off" ' +
        'style="width:100%;box-sizing:border-box;padding:6px 8px;margin-bottom:6px;background:#0d1117;color:#e6edf3;' +
        'border:1px solid #30363d;border-radius:5px;font:inherit">' +
        '<div data-add-list style="max-height:50vh;overflow:auto"></div>';
      document.body.appendChild(addMenu);

      let recent = [], catalog = [];
      try {
        const [sessionAnswer, catalogAnswer] = await Promise.all([
          io.api ? io.api('/api/sessions') : null,
          io.api ? io.api('/api/catalog') : null,
        ]);
        const sessions = Array.isArray(sessionAnswer) ? sessionAnswer : (sessionAnswer?.items || []);
        catalog = (Array.isArray(catalogAnswer) ? catalogAnswer
          : (catalogAnswer?.items || catalogAnswer?.games || [])).filter(game => game && (game.game_id || game.id));
        const byId = new Map(catalog.map(game => [String(game.game_id || game.id), game]));
        const seen = new Set();
        for (const row of (sessions || []).filter(item => item && item.agent_owned === false && item.game_id)
          .sort((a, b) => Number(b.started || 0) - Number(a.started || 0))) {
          const id = String(row.game_id);
          if (seen.has(id)) continue;
          seen.add(id);
          const entry = byId.get(id);
          if (entry && !/mercenar/i.test(String(entry.title || entry.alt_title || ''))) recent.push(entry);
        }
      } catch { recent = []; }

      const all = [];
      const push = (game, tag) => {
        if (all.some(item => item.id === String(game.game_id || game.id))) return;
        all.push({ id: String(game.game_id || game.id), game, tag });
      };
      for (const game of recent) push(game, 'recent');
      for (const game of catalog) {
        if (/mercenar/i.test(String(game.title || game.alt_title || ''))) continue;
        push(game, 'catalog');
      }

      if (!addMenu) return;
      const list = addMenu.querySelector('[data-add-list]');
      const rowHTML = (item, index) => {
        const game = item.game;
        const label = String(game.title || game.alt_title || game.game_id);
        const system = String(game.platform || game.collections?.[0] || '');
        return '<button type="button" role="option" data-add-index="' + index + '" ' +
          'data-needle="' + esc((label + ' ' + system).toLowerCase()) + '" ' +
          'style="display:block;width:100%;text-align:left;padding:7px 8px;background:transparent;border:0;border-radius:5px;' +
          'color:#e6edf3;font:inherit;cursor:pointer">' + esc(label) +
          '<span style="display:block;font-size:11px;color:#9aa3b4">' + esc(system) +
          (item.tag === 'recent' ? ' · recent' : '') + '</span></button>';
      };
      const draw = query => {
        const needle = String(query || '').trim().toLowerCase();
        const shown = needle ? all.filter(item => item.needleCache === undefined) : all;
        list.innerHTML = all.map((item, index) => ({ item, index }))
          .filter(({ item }) => {
            if (!needle) return true;
            const game = item.game;
            const text = (String(game.title || game.alt_title || game.game_id) + ' ' +
              String(game.platform || game.collections?.[0] || '')).toLowerCase();
            return text.includes(needle);
          })
          .slice(0, 60)
          .map(({ item, index }) => rowHTML(item, index)).join('') ||
          '<div style="padding:8px;font-size:12px;color:#9aa3b4">No games match</div>';
        list.querySelectorAll('[data-add-index]').forEach(buttonEl => {
          buttonEl.addEventListener('click', () => start(all[Number(buttonEl.dataset.addIndex)]?.game));
        });
      };
      const start = async game => {
        if (!game) return;
        dismissAdd();
        const label = String(game.title || game.game_id);
        if (valid()) message('Starting ' + label + '…');
        try {
          const body = { tool: '@launch', input: { game, node: io.node ? io.node() : undefined } };
          if (typeof io.launch === 'function') { await io.launch(game); }
          else if (io.api) {
            const answer = await io.api('/api/jobs', body);
            if (answer && answer.ok === false) throw new Error(answer.error || 'refused');
          } else throw new Error('no way to launch from here');
        } catch (error) { if (valid()) message('Could not start it: ' + String(error?.message || error)); }
      };
      draw('');
      if (!addMenu) return;
      const search = addMenu.querySelector('[data-add-search]');
      search.addEventListener('input', () => draw(search.value));
      setTimeout(() => search.focus(), 30);
    }

    function onAddAway(event) {
      if (event.target.closest?.('[data-stream-add]')) return;   // that press is opening it, not dismissing it
      if (!addMenu || !addMenu.contains(event.target)) dismissAdd();
    }
    document.addEventListener('pointerdown', onAddAway, true);
    function onAway(event) { if (!menuEl || !menuEl.contains(event.target)) dismissMenu(); }
    function onKey(event) { if (event.key === 'Escape') dismissMenu(); }
    function dismissMenu() {
      if (menuEl) { menuEl.remove(); menuEl = null; }
      document.removeEventListener('pointerdown', onAway, true);
      document.removeEventListener('keydown', onKey, true);
    }
    function contextMenu(event) {
      const card = event.target.closest?.('[data-stream-sid]');
      if (!card || !valid() || typeof io.close !== 'function') return;
      const row = entries.find(e => e.row.session_id === card.dataset.streamSid)?.row;
      if (!row) return;
      event.preventDefault(); event.stopPropagation();
      dismissMenu();
      const label = io.title ? io.title(row) : (row.title || row.game_title || row.game_id || 'Game');
      menuEl = document.createElement('div');
      menuEl.className = 'pip-stream-menu'; menuEl.setAttribute('role', 'menu');
      menuEl.style.cssText = 'position:fixed;z-index:90;min-width:176px;max-width:280px;padding:5px;' +
        'background:#1b1f2a;border:1px solid #3a4152;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.55);';
      const head = document.createElement('div');
      head.textContent = (name(row) || identity(row).workerId || 'Instance') + ' · ' + label;
      head.style.cssText = 'padding:4px 8px 6px;font-size:11px;color:#9aa3b4;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;';
      const btn = document.createElement('button');
      btn.type = 'button'; btn.textContent = 'Close this game';
      btn.style.cssText = 'display:block;width:100%;text-align:left;padding:7px 8px;border:0;border-radius:6px;' +
        'background:transparent;color:#ff9a9a;cursor:pointer;font:inherit;';
      btn.addEventListener('mouseenter', () => { btn.style.background = '#33323a'; });
      btn.addEventListener('mouseleave', () => { btn.style.background = 'transparent'; });
      btn.addEventListener('click', async ev => {
        ev.stopPropagation(); dismissMenu();
        if (busy) return;
        busy = true; message('Closing ' + (name(row) || 'game') + '…');
        try {
          const done = await io.close(row.session_id, row);
          await refresh();
          message(done === false ? 'Switching views keeps every game running.' : 'Closed. The slot is free now.');
          setTimeout(() => { if (valid()) refresh(); }, 1500);
        } catch (error) { await refresh(); message('Could not close: ' + error.message); }
        finally { busy = false; }
      });
      menuEl.appendChild(head); menuEl.appendChild(btn); root.appendChild(menuEl);
      const rect = menuEl.getBoundingClientRect();
      menuEl.style.left = Math.max(6, Math.min(event.clientX, innerWidth - rect.width - 6)) + 'px';
      menuEl.style.top = Math.max(6, Math.min(event.clientY, innerHeight - rect.height - 6)) + 'px';
      document.addEventListener('pointerdown', onAway, true);
      document.addEventListener('keydown', onKey, true);
    }
    async function refresh() {
      dismissMenu();
      try {
        const data = await io.read(); if (!valid()) return;
        entries = candidates(data.rows, data.hosts);
        root.innerHTML = html(entries, io.current(), io.title, !!io.broadcast);
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
      if (event.target.closest?.('[data-stream-add]')) { openAdd(event); return; }
      const button = event.target.closest?.('[data-stream-sid], [data-stream-step], [data-stream-broadcast]');
      if (!button || !valid() || busy || button.disabled) return;
      event.stopPropagation();
      if (button.dataset.streamBroadcast) {
        busy = true; button.disabled = true; message('Switching broadcast...');
        try {
          const changed = await io.broadcast(button.dataset.streamBroadcast, valid);
          if (changed) message(button.dataset.streamBroadcast === 'auto' ? 'Broadcast follows the active game.' : 'This stream is now broadcast through gBox to Pine Box.');
        } catch (error) { message(error.message); }
        finally { busy = false; if (valid()) button.disabled = false; }
        return;
      }
      const row = button.dataset.streamSid ? entries.find(e => e.row.session_id === button.dataset.streamSid)?.row :
        cycle(entries.filter(e => e.status === 'ready').map(e => e.row), io.current(), Number(button.dataset.streamStep));
      if (!row) return;
      busy = true; message('Opening stream…');
      try { await io.select(row.session_id, valid); }
      catch (error) { message(error.message); }
      finally { busy = false; }
    }
    root.addEventListener('click', click);
    root.addEventListener('contextmenu', contextMenu);
    const ready = refresh();
    return {ready, stop() { stopped = true; preview?.stop(); dismissMenu(); root.removeEventListener('click',click);
      root.removeEventListener('contextmenu',contextMenu);
      root.querySelectorAll('[data-stream-preview]').forEach(img => img.removeAttribute('src')); }};
  }
  return {KEY, identity, sameInstance, status, candidates, resolve, cycle, create, previews, previewImage, html, mount};
});
