/* Remember the last game launched, and offer to relaunch it after a restart (docs/pso-checkpoints/CP-relaunch-prompt.md).

   The operator's request: "whenever I close and reload the application, if I previously had PSO up, I need it to ask me in pip mode if I want to relaunch the
   game and offer to relaunch the game so that way you can continuously reload gBox and relaunch this game as needed to troubleshoot."

   Two halves:

   * `gboxRememberGame(game)` is called by every launch path (the PiP panel's `launch`, the add-game panel, the recent strip) and stores the catalog entry.
   * on load, if a game is remembered and nothing is running, a small card appears in the PiP with the title and a Relaunch button.

   The card carries `pip-relaunch-prompt` so the compact-mode allow-list can let it through, and it launches through `launch_game` - the tool that actually works -
   so the session it starts belongs to the operator and the bot can drive it. That last property is the point: an agent-launched session cannot be driven. */
(function () {
  'use strict';

  const KEY = 'gbox.lastGame';
  const CLASS = 'pip-relaunch-prompt';
  let card = null;

  function remember(game) {
    try {
      if (game && (game.game_id || game.id)) localStorage.setItem(KEY, JSON.stringify(game));
    } catch {}
  }

  function remembered() {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; }
  }

  function dismiss() {
    if (card) { card.remove(); card = null; }
  }

  async function api(path, body) {
    const helper = globalThis.gbox && globalThis.gbox.api;
    if (!helper) throw new Error('no api helper');
    const answer = await helper(path, body);
    if (answer && answer.ok === false) throw new Error(answer.error || 'request failed');
    return answer && typeof answer === 'object' && 'data' in answer ? answer.data : answer;
  }

  async function liveSessions() {
    try {
      const rows = await api('/api/sessions');
      const list = Array.isArray(rows) ? rows : (rows && (rows.items || [])) || [];
      return list.filter(row => row && (row.state === 'running' || row.state === 'starting'));
    } catch { return []; }
  }

  function show(game) {
    dismiss();
    const title = String(game.title || game.alt_title || game.game_id || 'the last game');
    card = document.createElement('div');
    card.className = CLASS;
    card.setAttribute('role', 'dialog');
    card.style.cssText = 'position:fixed;z-index:9998;left:50%;top:16%;transform:translateX(-50%);' +
      'width:min(380px,80vw);padding:12px;border-radius:10px;background:#1b1f2a;border:1px solid #3a4152;' +
      'box-shadow:0 10px 32px rgba(0,0,0,.6);color:#e6edf3;font:14px/1.4 system-ui,sans-serif';

    const heading = document.createElement('div');
    heading.textContent = 'Relaunch your last game?';
    heading.style.cssText = 'font-weight:600;margin-bottom:4px';

    const line = document.createElement('div');
    line.textContent = title;
    line.style.cssText = 'font-size:12px;color:#9aa3b4;margin-bottom:10px';

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';

    const no = document.createElement('button');
    no.type = 'button';
    no.textContent = 'Not now';
    no.style.cssText = 'padding:6px 10px;border-radius:6px;background:#222836;color:#c7d0dd;border:1px solid #3a4152;cursor:pointer;font:inherit';
    no.addEventListener('click', dismiss);

    const yes = document.createElement('button');
    yes.type = 'button';
    yes.textContent = 'Relaunch';
    yes.style.cssText = 'padding:6px 12px;border-radius:6px;background:#2f6fd0;color:#fff;border:1px solid #4a86e8;cursor:pointer;font:inherit;font-weight:600';
    yes.addEventListener('click', async () => {
      yes.disabled = true;
      yes.textContent = 'Launching…';
      try {
        await api('/api/jobs', { tool: 'launch_game', input: { game } });
        yes.textContent = 'Launched';
        setTimeout(dismiss, 1200);
      } catch (error) {
        yes.disabled = false;
        yes.textContent = 'Relaunch';
        line.textContent = 'Could not launch: ' + String(error && error.message || error);
      }
    });

    row.appendChild(no);
    row.appendChild(yes);
    card.appendChild(heading);
    card.appendChild(line);
    card.appendChild(row);
    document.body.appendChild(card);
    yes.focus();
  }

  async function maybeAsk() {
    const game = remembered();
    if (!game) return;
    const live = await liveSessions();
    if (live.length) return;                       // something is already running; nothing to ask
    if (document.body.classList.contains('gbox-compact') === false && !document.querySelector('#gpu-game')) {
      // still offer it: the app may be starting into compact mode a moment later
    }
    show(game);
  }

  globalThis.gboxRememberGame = remember;
  globalThis.gboxRelaunchPrompt = { show, maybeAsk, remembered, dismiss };

  // After the app has settled: ask once, a few seconds in.
  setTimeout(() => { maybeAsk().catch(() => {}); }, 4500);

  console.log('relaunch prompt ready');
})();
