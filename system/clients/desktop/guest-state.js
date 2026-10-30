/* Bound shell reads of a busy guest without queuing repeated executeJavaScript calls. */
(function (root) {
  'use strict';
  function create({read, deadlineMs = 250, schedule = setTimeout, cancel = clearTimeout}) {
    const guests = new WeakMap();
    function reset(guest) { guests.delete(guest); }
    function get(guest) {
      if (!guest) return Promise.resolve({});
      const existing = guests.get(guest);
      if (existing) return existing.answer;
      const entry = {};
      let timer, finish;
      entry.answer = new Promise(resolve => { finish = resolve; });
      guests.set(guest, entry);
      timer = schedule(() => finish({}), deadlineMs);
      Promise.resolve().then(() => read(guest)).then(value => {
        if (guests.get(guest) === entry) finish(value || {});
        else finish({});
      }, () => finish({})).finally(() => {
        cancel(timer);
        if (guests.get(guest) === entry) guests.delete(guest);
      });
      // A deadline releases callers, not ownership of the still-pending IPC.
      // More polls share its settled empty answer until it exits or navigation
      // invalidates the guest. No stale session is used as a substitute.
      return entry.answer;
    }
    return {get, reset};
  }
  const api = {create};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GBoxGuestState = api;
})(globalThis);
