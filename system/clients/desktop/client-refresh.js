/* Client-only reload state. Never stores credentials, launches a game, or substitutes a different session. */
(function(root) {
  const KEY = 'gbox.client.refresh.v1';
  function snapshot(value, at = Date.now()) {
    const sid = typeof value?.sid === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(value.sid) ? value.sid : null;
    return { v: 1, at, sid, compact: !!(sid && value?.compact),
      aspect: Number.isFinite(value?.aspect) && value.aspect >= .2 && value.aspect <= 8 ? value.aspect : 4 / 3,
      returnMode: ['auto', 'full', 'pip'].includes(value?.returnMode) ? value.returnMode : 'auto',
      section: typeof value?.section === 'string' && /^[a-z-]{1,40}$/.test(value.section) ? value.section : 'play' };
  }
  function create({ storage, context, readState, reload, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout }) {
    let busy = null;
    const pending = () => {
      try { const value = JSON.parse(storage.getItem(KEY));
        if (value?.v === 1 && Number.isFinite(value.at) && now() - value.at >= 0 && now() - value.at <= 300000) return snapshot(value, value.at);
      } catch {} return null;
    };
    const done = () => storage.removeItem(KEY);
    function refresh() {
      if (busy) return busy;
      busy = (async () => {
        const before = context(); let timer;
        // A hung guest renderer must not prevent reloading the shell; its known selected session is the fallback.
        const guest = await Promise.race([Promise.resolve().then(readState).catch(() => ({})),
          new Promise(resolve => { timer = setTimer(() => resolve({}), 1500); })]);
        clearTimer(timer);
        const value = snapshot({ ...before, sid: before.compact ? before.sid : guest.playing || guest.session || before.sid }, now());
        storage.setItem(KEY, JSON.stringify(value));
        await reload(value); return value;
      })().finally(() => { busy = null; });
      return busy;
    }
    return { refresh, pending, done };
  }
  function changed(baseline, current) {
    if (!baseline || !current) return { pending: false, restart: false };
    const renderer = !!(baseline.renderer && current.renderer && baseline.renderer !== current.renderer);
    const remote = !!(baseline.remote && current.remote && baseline.remote !== current.remote);
    const restart = !!current.restart;
    return { pending: renderer || remote || restart, restart, renderer, remote };
  }
  const api = { create, snapshot, changed };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxClientRefresh = api;
})(globalThis);
