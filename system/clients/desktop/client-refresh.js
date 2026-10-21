/* Client-only reload state. Never stores credentials, launches a game, or substitutes a different session. */
(function(root) {
  const KEY = 'gbox.client.refresh.v1';
  const session = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(value) ? value : null;
  function guestState(value) {
    return { tab: typeof value?.tab === 'string' && /^[A-Za-z]{1,40}$/.test(value.tab) ? value.tab : 'Home',
      playing: session(value?.playing), active: session(value?.active || value?.session), pip: session(value?.pip) };
  }
  function snapshot(value, at = Date.now()) {
    const sid = session(value?.sid);
    return { v: 1, at, sid, guest: guestState(value?.guest || (sid ? { tab: 'Sessions', playing: sid, active: sid } : null)), compact: !!(sid && value?.compact),
      aspect: Number.isFinite(value?.aspect) && value.aspect >= .2 && value.aspect <= 8 ? value.aspect : 4 / 3,
      returnMode: ['auto', 'full', 'pip'].includes(value?.returnMode) ? value.returnMode : 'auto',
      section: typeof value?.section === 'string' && /^[a-z-]{1,40}$/.test(value.section) ? value.section : 'play' };
  }
  function create({ storage, context, readState, reload, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout }) {
    let busy = null, lastGuest = null;
    const remember = value => { if (value && typeof value === 'object' && ('tab' in value || 'playing' in value)) lastGuest = guestState(value); };
    const pending = () => {
      try { const value = JSON.parse(storage.getItem(KEY));
        if (value?.v === 1 && Number.isFinite(value.at) && now() - value.at >= 0 && now() - value.at <= 300000) return snapshot(value, value.at);
      } catch {} return null;
    };
    const done = () => storage.removeItem(KEY);
    function checkpoint(guest) {
      remember(guest);
      const before = context(), value = snapshot({ ...before, guest: lastGuest || before.guest,
        sid: before.compact ? before.sid : lastGuest?.playing || lastGuest?.active || before.sid }, now());
      storage.setItem(KEY, JSON.stringify(value)); return value;
    }
    function refresh() {
      if (busy) return busy;
      busy = (async () => {
        const retry = pending();
        if (retry) { await reload(retry); return retry; } // a partial reconnect must not overwrite the missing stream's intent
        let timer;
        // A hung guest renderer must not prevent reloading the shell; its known selected session is the fallback.
        const guest = await Promise.race([Promise.resolve().then(readState).catch(() => ({})),
          new Promise(resolve => { timer = setTimer(() => resolve({}), 1500); })]);
        clearTimer(timer);
        const value = checkpoint(guest);
        await reload(value); return value;
      })().finally(() => { busy = null; });
      return busy;
    }
    const adopt = value => { const saved = snapshot(value, now()); storage.setItem(KEY, JSON.stringify(saved)); return saved; };
    return { refresh, pending, done, checkpoint, remember, adopt };
  }
  function changed(baseline, current) {
    if (!baseline || !current) return { pending: false, restart: false };
    const renderer = !!(baseline.renderer && current.renderer && baseline.renderer !== current.renderer);
    const remote = !!(baseline.remote && current.remote && baseline.remote !== current.remote);
    const restart = !!current.restart;
    return { pending: renderer || remote || restart, restart, renderer, remote };
  }
  const api = { create, snapshot, guestState, changed };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxClientRefresh = api;
})(globalThis);
