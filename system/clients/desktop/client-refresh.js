/* Client-only reload state. Never stores credentials, launches a game, or substitutes a different session. */
(function(root) {
  const KEY = 'gbox.client.refresh.v1';
  const session = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(value) ? value : null;
  function origin(value) {
    try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.origin : null; }
    catch { return null; }
  }
  function guestState(value) {
    return { tab: typeof value?.tab === 'string' && /^[A-Za-z]{1,40}$/.test(value.tab) ? value.tab : 'Home',
      playing: session(value?.playing), active: session(value?.active || value?.session), pip: session(value?.pip) };
  }
  function snapshot(value, at = Date.now()) {
    const sid = session(value?.sid);
    return { v: 1, at, origin: origin(value?.origin), sid, guest: guestState(value?.guest || (sid ? { tab: 'Sessions', playing: sid, active: sid } : null)), compact: !!(sid && value?.compact),
      aspect: Number.isFinite(value?.aspect) && value.aspect >= .2 && value.aspect <= 8 ? value.aspect : 4 / 3,
      returnMode: ['auto', 'full', 'pip'].includes(value?.returnMode) ? value.returnMode : 'auto',
      section: typeof value?.section === 'string' && /^[a-z-]{1,40}$/.test(value.section) ? value.section : 'play' };
  }
  function create({ storage, context, readState, reload, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout }) {
    let busy = null, lastGuest = null, retained = null, restoreBaseline = null;
    let lastOrigin = origin(context().origin), originReset = false, staleCompact = null;
    function scope() {
      const expected = origin(context().origin);
      if (expected !== lastOrigin) {
        lastOrigin = expected; lastGuest = null; originReset = true;
        staleCompact = context().compact ? context().sid : null;
      }
      return expected;
    }
    const compatible = value => { const expected = origin(context().origin); return !expected || origin(value?.origin) === expected; };
    const remember = value => {
      const expected = scope(), source = origin(value?.origin);
      if ((source && expected && source !== expected) || (originReset && expected && source !== expected)) return;
      if (value && typeof value === 'object' && ('tab' in value || 'playing' in value)) {
        lastGuest = guestState(value); originReset = false;
      }
    };
    const pending = () => {
      if (retained) { if (compatible(retained)) return retained; done(); return null; }
      try { const value = JSON.parse(storage.getItem(KEY));
        if (value && !compatible(value)) { done(); return null; }
        if (value?.v === 1 && Number.isFinite(value.at) && now() - value.at >= 0 && now() - value.at <= 300000) return snapshot(value, value.at);
      } catch {} return null;
    };
    const done = () => { retained = restoreBaseline = null; storage.removeItem(KEY); };
    function current(guest) {
      remember(guest);
      const before = { ...context() };
      if (staleCompact && (!before.compact || before.sid !== staleCompact)) staleCompact = null;
      if (staleCompact) { before.compact = false; before.sid = null; }
      if (originReset) return snapshot({ ...before, sid: null, compact: false, guest: guestState(null) }, now());
      const value = snapshot({ ...before, guest: lastGuest || before.guest,
        sid: before.compact ? before.sid : lastGuest ? lastGuest.playing || lastGuest.active : before.sid }, now());
      return value;
    }
    function checkpoint(guest) { const value = current(guest); storage.setItem(KEY, JSON.stringify(value)); return value; }
    const navigation = guest => JSON.stringify({ revision: Number.isSafeInteger(guest?.revision) ? guest.revision : null,
      guest: guestState(guest), section: context().section, compact: !!context().compact, sid: context().compact ? context().sid : null });
    function retain(value, guest) {
      if (!compatible(value)) { done(); return null; }
      retained = snapshot(value, now()); storage.setItem(KEY, JSON.stringify(retained));
      restoreBaseline = guest && typeof guest.tab === 'string' ? navigation(guest) : null;
    }
    function observe(guest) {
      if (!guest || typeof guest.tab !== 'string') return null; // unreadable guest must not erase the last good view
      const expected = scope(), source = origin(guest.origin);
      if (expected && source && source !== expected) return null;
      if (retained) {
        const next = navigation(guest);
        if (restoreBaseline === null) restoreBaseline = next;
        else if (next !== restoreBaseline) done(); // a later selected view or explicit PiP close supersedes missing intent
      }
      if (retained) { retain(retained, guest); return retained; }
      return current(guest);
    }
    function refresh() {
      if (busy) return busy;
      busy = (async () => {
        let retry = pending();
        if (retry && !retained) { await reload(retry); return retry; }
        let timer;
        // A hung guest renderer must not prevent reloading the shell; its known selected session is the fallback.
        const guest = await Promise.race([Promise.resolve().then(readState).catch(() => ({})),
          new Promise(resolve => { timer = setTimer(() => resolve({}), 1500); })]);
        clearTimer(timer);
        if (retained) observe(guest);
        retry = pending();
        if (retry) { await reload(retry); return retry; } // retain absent streams unless the operator changed views
        const value = checkpoint(guest);
        await reload(value); return value;
      })().finally(() => { busy = null; });
      return busy;
    }
    const adopt = value => { if (!compatible(value)) { done(); return null; }
      const saved = snapshot(value, now()); storage.setItem(KEY, JSON.stringify(saved)); return saved; };
    return { refresh, pending, done, checkpoint, current, remember, adopt, retain, observe };
  }
  function changed(baseline, current) {
    if (!baseline || !current) return { pending: false, restart: false };
    const renderer = !!(baseline.renderer && current.renderer && baseline.renderer !== current.renderer);
    const remote = !!(baseline.remote && current.remote && baseline.remote !== current.remote);
    const restart = !!current.restart;
    return { pending: renderer || remote || restart, restart, renderer, remote };
  }
  const api = { create, snapshot, guestState, origin, changed };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxClientRefresh = api;
})(globalThis);
