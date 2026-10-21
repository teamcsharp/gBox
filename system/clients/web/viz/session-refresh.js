/* Restore the exact foreground and PiP streams after a client reload. No game or input operations. */
(function(root) {
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
      const live = id => sessions.find(s => s.session_id === id && s.state === 'running');
      const wanted = [...new Set([state.playing, state.active, state.pip].filter(Boolean))];
      const missing = wanted.filter(id => !live(id));
      // show() selects its view synchronously, then waits for the content. Keep
      // that revision so later operator navigation cannot restore an old PiP.
      const showing = state.playing && live(state.playing) ? io.show('Sessions', state.playing)
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
      return { restored: wanted.filter(id => live(id)), missing };
    }
    return { restore, cancel: () => { generation++; } };
  }
  const api = { create, normalize };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxSessionRefresh = api;
})(globalThis);
