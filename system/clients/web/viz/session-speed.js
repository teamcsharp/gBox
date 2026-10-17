// Fast-forward recovery is an explicit off command, never a blind toggle.
(function (root) {
  function create({ command, render, report }) {
    let state = {}, busy = false, generation = 0;
    const paint = () => render({ ...state, busy });
    function update(next, revision = generation) {
      if (busy || revision !== generation) return;
      state = next || {}; paint();
    }
    async function off() {
      if (busy) return;
      busy = true; generation++; paint();
      try {
        const reply = await command();
        if (reply?.on !== false) throw new Error('The emulator did not clear fast-forward. Try again.');
        state = reply;
        report(reply.source === 'emulator' ? 'Normal speed restored.' : 'Fast-forward cleared. Release the fast-forward shortcut before using it again.', false);
      } catch (error) { report(error.message, true); }
      finally { busy = false; paint(); }
    }
    return { update, off, revision: () => generation };
  }
  const api = { create };
  root.GBoxSessionSpeed = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
