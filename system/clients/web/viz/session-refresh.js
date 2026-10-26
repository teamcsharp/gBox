/* Restore the exact foreground and PiP streams after a client reload. No game or input operations. */
(function(root) {
  const continuity = typeof module === 'object' && module.exports ? require('./session-continuity.js') : root.GBoxSessionContinuity;
  const sid = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(value) ? value : null;
  function normalize(value) {
    return { tab: typeof value?.tab === 'string' && /^[A-Za-z]{1,40}$/.test(value.tab) ? value.tab : 'Home',
      playing: sid(value?.playing), active: sid(value?.active), pip: sid(value?.pip) };
  }
  function create(io) {
    let generation = 0;
    async function restore(value) {
      const mine = ++generation, revision = io.revision?.(), state = normalize(value), sessions = await io.sessions();
      if (mine !== generation || (io.revision && io.revision() !== revision)) return { cancelled: true, restored: [], missing: [] };
      const live = id => continuity.resolve(id, sessions);
      const wanted = [...new Set([state.playing, state.active, state.pip].filter(Boolean))];
      const missing = wanted.filter(id => !live(id));
      // a saved game whose PC is offline (#2870, worker_online) is reported apart from a merely absent one: the shell drops
      // the saved view instead of retrying it every 2 s (operator 2026-10-26, i9-NUC's dead Mercenaries 3D session)
      const rows = Array.isArray(sessions) ? sessions : [];
      const offline = missing.filter(id => { const row = rows.find(s => s?.session_id === id); return !!row && row.state === 'running' && row.worker_online === false; });
      // show() selects its view synchronously, then waits for the content. Keep
      // that revision so later operator navigation cannot restore an old PiP.
      const showing = state.playing && live(state.playing) ? io.show('Sessions', live(state.playing).session_id)
        : state.playing ? io.show('Sessions') // show the list, never substitute another live game
        : io.show(io.tabs.includes(state.tab) ? state.tab : 'Home');
      const shownRevision = io.revision?.();
      const superseded = () => mine !== generation || (io.revision && io.revision() !== shownRevision);
      try { await showing; }
      catch (error) {
        if (!superseded()) throw error;
      }
      if (superseded()) return { cancelled: true, restored: [], missing: [] };
      const active = live(state.pip || state.active) || live(state.playing);
      io.active(active || null);
      io.pip();
      return { restored: wanted.filter(id => live(id)), missing, ...(offline.length ? { offline } : {}) };
    }
    return { restore, cancel: () => { generation++; } };
  }
  const api = { create, normalize };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxSessionRefresh = api;
})(globalThis);
