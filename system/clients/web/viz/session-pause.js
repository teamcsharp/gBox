// Pause controls follow the emulator, including changes made by other controls.
(function (root) {
  function paused(runtime) {
    if (runtime?.running === false) throw new Error('The emulator has stopped.');
    if (typeof runtime?.paused === 'boolean') return runtime.paused;
    const state = String(runtime?.state || '').toUpperCase();
    if (state === 'PAUSED') return true;
    if (state === 'PLAYING' || state === 'RUNNING') return false;
    throw new Error('The emulator did not report its pause state.');
  }

  function confirms(reply, wanted) {
    try { return reply != null && paused(reply) === wanted; } catch { return false; }
  }

  function create({ read, command, render, report, delay = ms => new Promise(r => setTimeout(r, ms)) }) {
    let value, busy = false, generation = 0;
    const paint = () => render({ paused: value, busy });
    async function refresh() {
      if (busy) return;
      const current = generation;
      const next = paused(await read());
      if (current === generation && !busy) { value = next; paint(); }
      return next;
    }
    async function toggle() {
      if (busy) return;
      busy = true; generation++; paint();
      try {
        const actual = paused(await read());
        const wanted = !actual;
        value = wanted; paint();               // the icon flips the moment the command leaves (#1123)
        let reply;
        try { reply = await command(wanted ? 'pause' : 'resume'); }
        catch (error) { value = actual; throw error; }
        if (confirms(reply, wanted)) {
          report(wanted ? 'Emulation paused.' : 'Emulation resumed.', false);
          return;
        }
        // Older workers answer with the status read sent right behind
        // PAUSE_TOGGLE, which can still hold the previous state.
        for (let attempt = 0; attempt < 12; attempt++) {
          value = paused(await read());
          if (value === wanted) {
            report(wanted ? 'Emulation paused.' : 'Emulation resumed.', false);
            return;
          }
          await delay(attempt < 4 ? 50 : 150);
        }
        throw new Error('The emulator did not confirm ' + (wanted ? 'pause.' : 'resume.'));
      } catch (error) {
        report(error.message, true);
      } finally {
        busy = false; paint();
      }
    }
    return { refresh, toggle };
  }

  const api = { paused, create };
  root.GBoxSessionPause = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
