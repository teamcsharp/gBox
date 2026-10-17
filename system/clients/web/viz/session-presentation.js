/* Presentation state is independent of the emulator controls and video backend.
   A closed native window must retire the stale black view just like an ended stream. */
(function (root) {
  function message(health) {
    if (health.state === 'ended' || health.state === 'missing') return 'This session has ended.';
    if (health.worker_online === false) return 'Worker offline. Waiting to reconnect; gameplay is unverified.';
    if (health.gameplay_state === 'covered') return 'The emulator window is covered. Gameplay is unverified.';
    if (health.gameplay_state === 'no_window') return 'The emulator window is missing. Gameplay is unverified.';
    if (health.gameplay_state === 'black_screen') return 'The observer reports a black frame. Gameplay is unverified.';
    if (health.gameplay_state === 'stopped') return 'The worker reports the emulator stopped. Waiting for session status.';
    if (health.local_window) return ''; // local HWND/GPU frames are not the MJPEG source
    if (health.age_s == null) return 'Waiting for the first game frame. Gameplay is unverified.';
    if (health.age_s > 10) return 'No recent game frame. Waiting for the capture connection.';
    return '';
  }
  function create({ read, render, ended, current = () => true, setTimer = setTimeout, clearTimer = clearTimeout }) {
    let timer, stopped = false, terminal = false;
    async function poll() {
      if (stopped || terminal || !current()) return;
      try {
        const health = await read();
        if (stopped || !current()) return;
        const text = message(health);
        render({ text, health, disconnected: false });
        if (health.state === 'ended' || health.state === 'missing') {
          terminal = true; ended(health); return;
        }
      } catch (error) {
        if (!stopped && current()) render({ text: 'Status unavailable: ' + error.message + '. Retrying.', disconnected: true });
      }
      if (!stopped && !terminal && current()) timer = setTimer(poll, 3000);
    }
    return { poll, stop() { stopped = true; clearTimer(timer); } };
  }
  root.GBoxSessionPresentation = { message, create };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.GBoxSessionPresentation;
})(globalThis);
