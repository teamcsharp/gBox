// Restart session / Reconnect stream and triple-click PiP in a real page (headless Chromium via browser_lifecycle):
// the web shell's game-picture menu gets the two session entries (pick-whip.js), its triple-click handler reports only
// the third click and never blocks the game's clicks, and the desktop shell's PiP window (its menu, Reconnect, the whole
// Restart flow against a fake control plane: the reset job, the autoplay, the follow to the new session) works.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { withPage } = require('../scripts/browser_lifecycle.cjs');
const read = p => fs.readFileSync(path.join(__dirname, p), 'utf8').replace(/\r\n/g, '\n');
const restartSrc = read('../clients/web/viz/session-restart.js'), pickWhipSrc = read('../clients/web/viz/pick-whip.js');
const gestureSrc = read('../clients/desktop/pip-gesture.js');
const web = read('../clients/web/index.html'), desktop = read('../clients/desktop/index.html');
const between = (src, a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); assert.ok(i >= 0 && j > i, a); return src.slice(i, j + b.length); };
const webTriple = between(web, '// Triple-click the game picture', 'gboxTell({ ev: "gametriple", sid });\n});');
const deskSection = between(desktop, '// ---- triple-click the game display', "compactMenu(e.clientX, e.clientY);\n}, true);");

test('web shell: the game picture menu ends with Restart session / Reconnect stream; triple click reports the third click only', async () => {
  await withPage(async evaluate => {
    await evaluate(restartSrc); await evaluate(pickWhipSrc);
    await evaluate(`document.body.innerHTML = '<img id="scr" class="screen" data-sid="spark-1" style="width:320px;height:240px;display:block" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">';
      var picked = [];
      var PWW = GBoxPickWhip.mountOverlay(document, { api: async () => ({ id: 'j', state: 'succeeded', output: { result: {} } }),
        sid: () => 'spark-1', toast: () => {}, sessionExtra: sid => sid ? ['-', ...GBoxSessionRestart.menuItems()] : [],
        onSessionExtra: (id, sid) => picked.push([id, sid]) });
      PWW.menuAt(60, 60, document.querySelector('#scr'));`);
    await evaluate('new Promise(r => setTimeout(r, 300))');
    assert.deepEqual(await evaluate(`[...document.querySelectorAll('#pwmenu button[data-pw]')].slice(-2).map(b => [b.dataset.pw, b.textContent])`),
      [['restart', '↻Restart session'], ['reconnect', '⟳Reconnect stream']]);
    assert.equal(await evaluate(`document.querySelector('#pwmenu button[data-pw=report]') !== null`), true, 'Report stays first');
    await evaluate(`document.querySelector('#pwmenu button[data-pw=restart]').click(); new Promise(r => setTimeout(r, 50))`);
    assert.deepEqual(await evaluate('picked'), [['restart', 'spark-1']]);
    assert.equal(await evaluate(`document.querySelector('#pwmenu').style.display`), 'none', 'the menu closes');

    await evaluate(`var told = [], playing = 'spark-1', embedded = true;
      var PW_GAME_VIEW = "#scr, #nativeslot, .gbox-gpu-video, img.screen, img[src*='/mjpeg']";
      var gboxEmbedded = () => embedded, gboxTell = m => told.push(m);
      document.body.insertAdjacentHTML('beforeend', '<button id="other">x</button>');
      var click = (sel, detail, extra) => document.querySelector(sel).dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail, button: 0, ...(extra || {}) }));
      ${webTriple}`);
    assert.deepEqual(await evaluate(`[click('#scr', 1), click('#scr', 2), click('#scr', 3)]`), [true, true, true], 'nothing is prevented');
    assert.deepEqual(await evaluate('told'), [{ ev: 'gametriple', sid: 'spark-1' }]);
    await evaluate(`click('#scr', 3, { ctrlKey: true }); click('#scr', 4); click('#other', 3); embedded = false; click('#scr', 3);`);
    assert.equal(await evaluate('told.length'), 1, 'modified, fourth, off-game and plain-browser clicks are ignored');
  });
});

test('desktop shell: PiP window menu, Reconnect, the full Restart flow and the triple-click gesture (fake control plane)', async () => {
  await withPage(async evaluate => {
    await evaluate(restartSrc); await evaluate(gestureSrc);
    await evaluate(`document.body.innerHTML = '<img id="compact-stream" class="on" style="width:320px;height:240px;display:block"><div id="gpu-game" style="width:200px;height:100px"></div>';
      var T = 10000, calls = [], toasts = [], jobs = [], polls = 0, failNext = false;
      var COMPACT = { on: false, sid: null, local: false }, EMB = { sid: 'pc-1' };
      var pipGesture = GBoxPipGesture.create({ now: () => T });
      var compactController = {
        enter: async r => { calls.push(['enter', r && r.sid]); Object.assign(COMPACT, { on: true, sid: r && r.sid }); pipGesture.changed(true); },
        follow: async (from, s) => { calls.push(['follow', from, s.sid, s.local]); COMPACT.sid = s.sid; return true; } };
      var compactRestore = async () => { calls.push(['restore']); COMPACT.on = false; pipGesture.changed(false); };
      var toast = t => toasts.push(t), GBoxCompactCoach = { isCoachTarget: () => false };
      var S = { apiUrl: 'http://spark:8000', workerName: 'PC' }, compactStreamUrl = '', compactTitle = '';
      var sessions = { 'spark-old': { session_id: 'spark-old', state: 'running', title: 'RE5', detail: { worker_name: 'spark' } },
                       'spark-new': { session_id: 'spark-new', state: 'running', title: 'RE5', detail: { worker_name: 'spark' } },
                       'spark-x': { session_id: 'spark-x', state: 'ended', replaced_by: 'spark-new' } };
      var sessionById = async sid => sessions[sid] || null, sessionTitle = s => s.title;
      var $ = s => document.querySelector(s), esc = s => String(s), fitMenu = (m, x, y) => { m.style.left = x + 'px'; m.style.top = y + 'px'; };
      var confirm = t => { calls.push(['confirm', t.split('\\n')[0]]); return true; };
      var gameJob = async (tool, input) => { jobs.push([tool, input.session_id, input.op, input.mode || '']);
        return input.op === 'status' ? { running: input.session_id === 'spark-old', mode: 'playbook' } : { objective: 'merc' }; };
      var gbox = { token: async () => 'TOK', api: async (p, b) => {
        calls.push(['api', p, b && b.mode]);
        if (p.endsWith('/reset')) return { ok: true, data: { id: 'job1', state: 'running' } };
        if (p === '/api/jobs/job1') return { ok: true, data: ++polls < 2 ? { id: 'job1', state: 'running', progress: { pct: 40, msg: 'Booting RE5' } }
          : failNext ? { id: 'job1', state: 'failed', error: 'The PC that ran this game is offline' } : { id: 'job1', state: 'succeeded', output: { session_id: 'spark-new' } } };
        return { ok: false, error: 'unexpected ' + p }; } };
      ${deskSection}
      var click = (sel, detail, extra) => document.querySelector(sel).dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail, button: 0, ...(extra || {}) }));`);
    // triple click on the game picture: PiP for the docked game; the same run's echo does nothing; later the PiP window leaves
    await evaluate(`click('#gpu-game', 1); click('#gpu-game', 2); click('#gpu-game', 3, { altKey: true }); click('#gpu-game', 3); new Promise(r => setTimeout(r, 10))`);
    assert.deepEqual(await evaluate('calls'), [['enter', 'pc-1']]);
    await evaluate(`T += 200; click('#compact-stream', 3); T += 2000; click('#compact-stream', 3); new Promise(r => setTimeout(r, 10))`);
    assert.deepEqual(await evaluate('calls.slice(1)'), [['restore']]);
    // the PiP window of a streamed game: right-click menu, Reconnect
    await evaluate(`calls.length = 0; Object.assign(COMPACT, { on: true, sid: 'spark-old', local: false });
      document.querySelector('#compact-stream').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 30, clientY: 40 }));`);
    assert.deepEqual(await evaluate(`[...document.querySelectorAll('#compact-menu button')].map(b => b.dataset.a)`), ['restart', 'reconnect', 'full']);
    await evaluate(`document.querySelector('#compact-menu [data-a=reconnect]').click(); new Promise(r => setTimeout(r, 20))`);
    assert.match(await evaluate(`document.querySelector('#compact-stream').getAttribute('src')`), /^http:\/\/spark:8000\/api\/sessions\/spark-old\/mjpeg\?token=TOK&reconnect=\d+$/);
    assert.equal(await evaluate(`document.querySelector('#compact-menu').style.display`), 'none');
    // Restart: the reset job, the autoplay stopped and started again on the new copy, the PiP window follows it
    await evaluate(`document.querySelector('#compact-stream').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 30, clientY: 40 }));
      document.querySelector('#compact-menu [data-a=restart]').click(); new Promise(r => setTimeout(r, 2500))`);
    const after = await evaluate('({ calls, jobs, src: document.querySelector("#compact-stream").getAttribute("src"), status: document.querySelector("#compact-status").textContent, bad: document.querySelector("#compact-status").classList.contains("bad"), sid: COMPACT.sid })');
    assert.deepEqual(after.calls.filter(c => c[0] !== 'api' || !c[1].startsWith('/api/jobs/')).slice(0, 3),
      [['confirm', 'Restart RE5 on spark?'], ['api', '/api/sessions/spark-old/reset', 'restart'], ['follow', 'spark-old', 'spark-new', false]]);
    assert.deepEqual(after.jobs, [['autoplay', 'spark-old', 'status', ''], ['autoplay', 'spark-old', 'stop', ''], ['autoplay', 'spark-new', 'start', 'playbook']]);
    assert.equal(after.sid, 'spark-new');
    assert.match(after.src, /^http:\/\/spark:8000\/api\/sessions\/spark-new\/mjpeg\?token=TOK&reconnect=\d+$/, 'the new stream is attached');
    assert.equal(after.status, '↻ RE5 restarted · autoplay back on'); assert.equal(after.bad, false);
    // a failed restart: the PiP window says why, in red
    await evaluate(`calls.length = 0; jobs.length = 0; polls = 0; failNext = true; Object.assign(COMPACT, { sid: 'spark-old' }); desktopRestart('spark-old').then(() => new Promise(r => setTimeout(r, 50)))`);
    const failed = await evaluate('({ status: document.querySelector("#compact-status").textContent, bad: document.querySelector("#compact-status").classList.contains("bad"), follow: calls.some(c => c[0] === "follow"), jobs })');
    assert.equal(failed.status, '⚠ Restart failed: The PC that ran this game is offline'); assert.equal(failed.bad, true); assert.equal(failed.follow, false);
    assert.deepEqual(failed.jobs.at(-1), ['autoplay', 'spark-old', 'start', 'playbook'], 'the old copy gets its autoplay back');
    // a game replaced elsewhere (swap, chat agent): PiP follows instead of closing
    await evaluate(`calls.length = 0; Object.assign(COMPACT, { sid: 'spark-x' });`);
    assert.equal(await evaluate(`compactKeep('spark-x')`), true);
    assert.deepEqual(await evaluate('calls'), [['follow', 'spark-x', 'spark-new', false]]);
  });
});
