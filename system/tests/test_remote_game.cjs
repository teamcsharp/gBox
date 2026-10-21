// #2858: clicking a session another PC plays natively (its header icon with the cloud) shows that game live in the
// window: the worker's desktop stream cropped to the game window (else its gBox window, else its desktop), with
// "Pull it to this PC" and the other views in a bar under the picture. Before, a card asked to pull the game here.
// Pure choices run in node; the bar and its in-place updates run in a real headless Chromium (skipped without one);
// the shell itself runs against the PR's synthetic fixture (tests/fixtures/ui_evidence/session_click_shows_gameplay.json).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const RG = require('../clients/web/viz/remote-game.js');
const { findChrome, withPage } = require('../scripts/browser_lifecycle.cjs');

const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
// every browser test ends on a blank page: its open picture streams close before the browser does (a busy Windows PC
// otherwise kept renderers alive past withPage's cleanup check)
const page = fn => withPage(async (evaluate, send) => {
  try { await fn(evaluate, send); } finally { await send('Page.navigate', { url: 'about:blank' }).catch(() => {}); }
});
const SID = 'a68af3144f704f75-4a979744f8bc46d4';
const fresh = (more = {}) => ({ frames: 20, last_frame_age: 0.3, app_available: true, games: [SID], ...more });

test('the best picture: the game window while that screen shows it, else the gBox window, else the desktop', () => {
  assert.equal(RG.best(fresh(), SID), 'game');
  assert.equal(RG.best(fresh({ games: ['someone-else'] }), SID), 'app');
  assert.equal(RG.best(fresh({ games: [], app_available: false }), SID), 'desktop');
  assert.equal(RG.best(fresh({ games: undefined }), SID), 'app', 'a worker without the game crop: its gBox window');
  assert.equal(RG.best(fresh({ frames: 0 }), SID), null, 'no frame yet: nothing to judge by');
  assert.equal(RG.best(fresh({ last_frame_age: 40 }), SID), null, 'an old frame says nothing about that screen now');
  assert.equal(RG.best(null, SID), null);
  assert.equal(RG.best(fresh(), SID, ['game']), 'app', 'a view that showed nothing here is not chosen again');
  assert.equal(RG.best(fresh(), SID, ['game', 'app']), 'desktop');
  assert.equal(RG.next({ view: 'app', pinned: false, pending: null, shown: true, skip: ['game'] }, fresh(), SID).view, 'app');
});

test('a worse picture waits for a second poll, a better one and the first picture do not; the operator pick stays', () => {
  let st = { view: 'game', pinned: false, pending: null, shown: true };
  st = RG.next(st, fresh({ games: [] }), SID);
  assert.deepEqual([st.view, st.pending], ['game', 'app'], 'one poll without the game: keep it (a menu passing over it)');
  st = RG.next(st, fresh(), SID);
  assert.deepEqual([st.view, st.pending], ['game', null], 'back on screen: the pending switch is dropped');
  st = RG.next(RG.next(st, fresh({ games: [] }), SID), fresh({ games: [] }), SID);
  assert.equal(st.view, 'app', 'two polls in a row: the gBox window');
  assert.equal(RG.next(st, fresh(), SID).view, 'game', 'a better picture is taken at once');
  assert.equal(RG.next({ view: 'game', pinned: false, pending: null, shown: false }, fresh({ games: [], app_available: false }), SID).view,
    'desktop', 'before the first picture the best one is taken at once');
  assert.equal(RG.next({ view: 'desktop', pinned: true, pending: null, shown: true }, fresh(), SID).view, 'desktop');
  assert.equal(RG.next(st, fresh({ frames: 0 }), SID).view, 'app', 'no fresh status: keep what is shown');
});

test('stream urls, bar words and the markup', () => {
  assert.equal(RG.streamUrl('w 1', 'game', SID, 'token=t'), `/api/workers/w%201/desktop/stream?view=game&session=${SID}&token=t`);
  assert.equal(RG.streamUrl('w1', 'app', SID, 'token=t'), '/api/workers/w1/desktop/stream?view=app&token=t');
  assert.equal(RG.describe('game', 'JAYBUILTFINALE', fresh(), { shown: true, sid: SID }), 'Live · JAYBUILTFINALE · game window');
  assert.equal(RG.describe('game', 'JAYBUILTFINALE', fresh({ games: [] }), { shown: true, sid: SID }),
    "Live · JAYBUILTFINALE · game window · the game isn't on its screen right now");
  assert.equal(RG.describe('app', 'JAYBUILTFINALE', fresh({ games: ['someone-else'] }), { shown: true, sid: SID }),
    "Live · JAYBUILTFINALE · gBox window · the game isn't on its screen right now", 'a worker that reports its game windows tells');
  assert.equal(RG.describe('app', 'JAYBUILTFINALE', fresh({ games: undefined }), { shown: true, sid: SID }),
    'Live · JAYBUILTFINALE · gBox window', 'one that does not, says nothing it cannot know');
  assert.equal(RG.describe('app', 'JAYBUILTFINALE', fresh({ last_frame_age: 31 }), { shown: true, sid: SID }),
    'Live · JAYBUILTFINALE · gBox window · picture 31 s old');
  assert.equal(RG.describe('app', 'JAYBUILTFINALE', null, {}), "Connecting to JAYBUILTFINALE's screen…");
  assert.equal(RG.describe('app', 'JAYBUILTFINALE', null, { errors: 2 }), "Reconnecting to JAYBUILTFINALE's screen…");
  assert.match(RG.waiting('JAYBUILTFINALE', fresh({ frames: 0 }), 12000), /isn't sending its screen/);
  assert.equal(RG.waiting('JAYBUILTFINALE', fresh(), 12000), "Connecting to JAYBUILTFINALE's screen…");

  const html = RG.html({ sid: SID, wid: 'a68af3144f704f75', worker: 'JAYBUILTFINALE', title: 'Metal Gear Solid', auth: 'token=t', crop: true, pull: true });
  assert.match(html, /<img id="remote-game-img" data-view="game"[^>]*src="\/api\/workers\/a68af3144f704f75\/desktop\/stream\?view=game&#38;session=a68af3144f704f75-4a979744f8bc46d4&#38;token=t"/);
  assert.match(html, /<div id="remote-game-bar" role="toolbar"/);
  assert.match(html, /data-remote-view="game"[^>]*>Game<\/button>/);
  assert.match(html, /data-remote-view="app"[^>]*>gBox window<\/button>/);
  assert.match(html, /data-remote-view="desktop"[^>]*>Desktop<\/button>/);
  assert.match(html, /id="remote-game-pull"[^>]*>Pull it to this PC<\/button>/);
  assert.match(html, /<span id="remote-game-acts" hidden><button[^>]*data-live-action="retry"[^>]*>Retry<\/button>\s*<button[^>]*data-live-action="stop"[^>]*>Stop<\/button>\s*<button[^>]*data-live-action="relaunch"[^>]*>Relaunch<\/button><\/span>/,
    'Retry / Stop / Relaunch wait in the bar for a picture that does not come');
  assert.match(html, /Inspect, memory edits and Blender copy still work from here/, 'the old card\'s note lives on as the bar\'s tooltip');
  assert.doesNotMatch(html, /<h3>|Running natively on [^:]*<\/h3>/, 'no card in the picture');
  assert.doesNotMatch(html, /class="screen"[^>]*data-sid=/, 'not a game view for the report menu or the pick whip');
  const old = RG.html({ sid: SID, wid: 'w', worker: 'OLDPC', auth: '', crop: false, pull: false });
  assert.match(old, /data-view="app"/, 'a worker without the game crop starts on its gBox window');
  assert.match(old, /data-remote-view="game"[^>]*disabled/);
  assert.doesNotMatch(old, /remote-game-pull/, 'no Pull without a worker on this PC');
});

test('the Sessions view shows the other PC\'s game live where the card was, watched only', () => {
  const view = web.slice(web.indexOf('async function sessionsView('), web.indexOf('// ---- smart search'));
  assert.doesNotMatch(view, /Running natively on/, 'the card asking about the game is gone');
  assert.match(view, /const elsewhere = local && s\.detail\.worker_name !== window\.GBOX_LOCAL\?\.worker, here = local && !elsewhere;/);
  assert.match(view, /const workers = here \? null : await api\("\/api\/workers"\)\.catch\(\(\) => null\);/, 'a game on this PC asks no PC list');
  assert.match(view, /GBoxRemoteGame\.html\(\{ sid, wid: sid\.split\("-"\)\[0\], worker: s\.detail\.worker_name \|\| "another PC", title: s\.title, auth: tq\(\),\r?\n\s*crop: !!hostPC\?\.features\?\.includes\("desktop_game_crop"\), pull: !!window\.GBOX_LOCAL\?\.worker \}\)/);
  assert.match(view, /`<div id="nativeslot" data-sid="\$\{esc\(sid\)\}" class="screen" style="background:#000"><\/div>`/, 'a game on this PC still docks');
  const after = web.slice(web.indexOf('sessionsView.after = (sid, mode) => {'), web.indexOf('// ---------------- workbench under the game'));
  assert.match(after, /const stop = btn => hardStop\(sid, btn\), relaunch = btn => relaunchSession\(sid, btn\);/);
  assert.match(after, /if \(\$\("#remote-game"\)\) GBoxRemoteGame\.mount\(document, \{ api, auth: tq, pull: btn => moveHere\(sid, btn\), stop, relaunch \}\);/);
  assert.ok(after.indexOf('GBoxRemoteGame.mount') < after.indexOf('if (!$("#scr")) return;'), 'mounted before the stream-only wiring returns');
  // no #scr: active.local stays true, so this PC's pad is never forwarded to the other PC's game and no PiP follows it
  assert.match(after, /local: mode === "examine" \? \$\("#exam"\)\?\.dataset\.local === "1" : !\$\("#scr"\) && mode !== "inspect"/);
  assert.match(web, /<script src="\/viz\/remote-game\.js"><\/script>/);
});

// ---------- the bar and the picture in a real browser: a focused page around the module, a live status ----------
function focusedServer() {
  const st = { status: fresh(), streams: [], statusCalls: 0, gameView: 200 };
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/') {
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.end(`<!doctype html><html><head><meta charset="utf-8"><style>:root{--line:#333;--card:#222;--mut:#999;--ok:#3c3}body{margin:0;background:#111;color:#eee;font:13px system-ui}
        .play{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;height:560px}.play>div{min-height:0;overflow:auto}
        .play>div:first-child{display:flex;flex-direction:column;overflow:hidden}.screen{flex:1 1 auto;min-height:200px;background:#000;width:100%;display:block}
        .tabs2{display:inline-flex}button.pri{background:#36d;color:#fff}</style></head>
        <body><div class="play" id="playview"><div id="left"></div><div id="side"><div style="height:3000px">sidebar</div></div></div>
        <script src="/remote-game.js"></script></body></html>`);
      return;
    }
    if (url.pathname === '/remote-game.js') {
      res.setHeader('Content-Type', 'text/javascript; charset=utf-8');
      res.end(fs.readFileSync(path.join(__dirname, '../clients/web/viz/remote-game.js')));
      return;
    }
    if (url.pathname === '/api/workers/w1/desktop/status') {
      st.statusCalls++; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(st.status)); return;
    }
    if (url.pathname === '/api/workers/w1/desktop/stream') {
      const view = url.searchParams.get('view');
      st.streams.push(view + (url.searchParams.get('session') ? ':' + url.searchParams.get('session') : ''));
      if (st.mute || (view === 'game' && st.gameView === 'silent')) {   // nothing comes / none can be cropped to this view
        res.writeHead(200, { 'Content-Type': 'multipart/x-mixed-replace; boundary=frame' }); return;
      }
      if (view === 'game' && st.gameView !== 200) { res.writeHead(st.gameView); res.end('{"detail":"view must be app or desktop"}'); return; }
      const fill = { game: '#3a6', app: '#36a', desktop: '#a63' }[view] || '#666';
      res.setHeader('Content-Type', 'image/svg+xml');
      res.end(`<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="${fill}"/></svg>`);
      return;
    }
    res.writeHead(404); res.end();
  });
  return { server, st };
}
const until = async (evaluate, expr, what, n = 200) => {
  for (let i = 0; i < n; i++) { if (await evaluate(expr)) return; await new Promise(r => setTimeout(r, 25)); }
  assert.fail('timed out waiting for ' + what);
};
const served = async (st, view, what) => {                     // the page asked: the request reached the server
  for (let i = 0; i < 200; i++) { if (st.streams.at(-1)?.split(':')[0] === view) return; await new Promise(r => setTimeout(r, 25)); }
  assert.fail('the server never got the stream for ' + what);
};
const mountJs = crop => `(() => {
  document.getElementById('left').innerHTML = GBoxRemoteGame.html({ sid: ${JSON.stringify(SID)}, wid: 'w1', worker: 'TESTPC', title: 'Twin Snakes', auth: 'token=t', crop: ${crop}, pull: true });
  window.pulled = []; window.acted = []; window.box = document.getElementById('remote-game'); window.skew = 0;
  window.ctl = GBoxRemoteGame.mount(document, { api: p => fetch(p).then(r => r.json()), auth: () => 'token=t',
    pull: b => pulled.push(b.id), stop: b => acted.push('stop'), relaunch: b => acted.push('relaunch'),
    setTimer: (f, ms) => setTimeout(f, Math.min(ms, 60)), now: () => Date.now() + skew });
  return true; })()`;

// One browser for every focused scenario, each on its own server: every launch is one more chance for a busy PC to keep
// a renderer alive past withPage's cleanup check
test('in a real browser the picture follows that screen in place, falls back, steps down and offers its actions', { skip: !findChrome() && 'no Chromium installed' }, async t => {
  await page(async (evaluate, send) => {
    const scenario = (name, setup, body) => t.test(name, async () => {
      const { server, st } = focusedServer();
      setup(st);
      await new Promise(r => server.listen(0, '127.0.0.1', r));
      try {
        await send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
        await until(evaluate, `location.port === "${server.address().port}" && !!window.GBoxRemoteGame`, 'the module');
        await body(st);
      } finally {                                                // leave the page first: its open picture requests end
        await send('Page.navigate', { url: 'about:blank' }).catch(() => {});
        server.closeAllConnections?.(); await new Promise(r => server.close(r));
      }
    });

    await scenario('the picture follows that screen in place and keeps the operator\'s place and pick', () => {}, async st => {
      await evaluate(mountJs(true));
      await until(evaluate, `document.getElementById('remote-game-img').naturalWidth > 0 && document.getElementById('remote-game-wait').hidden`, 'the first picture');
      assert.match(await evaluate(`document.getElementById('remote-game-img').src`), /view=game&session=a68af3144f704f75-4a979744f8bc46d4&token=t$/,
        'the game window right away: no question first');
      await until(evaluate, `document.getElementById('remote-game-what').textContent === 'Live · TESTPC · game window'`, 'the bar to say what is shown');
      assert.equal(await evaluate(`document.querySelector('[data-remote-view=game]').getAttribute('aria-pressed')`), 'true');
      await evaluate(`document.getElementById('side').scrollTop = 900`);

      st.status = fresh({ games: [] });                         // the game window left that screen
      await until(evaluate, `document.getElementById('remote-game-img').dataset.view === 'app'`, 'the gBox window');
      assert.ok(st.statusCalls >= 2);
      st.status = fresh({ games: [], app_available: false });   // and gBox too: the whole desktop
      await until(evaluate, `document.getElementById('remote-game-img').dataset.view === 'desktop'`, 'the desktop');
      st.status = fresh();                                      // back on screen: at once
      await until(evaluate, `document.getElementById('remote-game-img').dataset.view === 'game'`, 'the game again');
      await served(st, 'game', 'the game again');
      assert.deepEqual(st.streams, [`game:${SID}`, 'app', 'desktop', `game:${SID}`], 'one new stream per change of view, never a reload loop');

      await evaluate(`document.querySelector('[data-remote-view=app]').click()`);
      await until(evaluate, `document.getElementById('remote-game-img').dataset.view === 'app'`, 'the operator pick');
      await served(st, 'app', 'the operator pick');
      const pinnedStreams = st.streams.length;
      await new Promise(r => setTimeout(r, 400));                // several polls that all say "game"
      assert.equal(await evaluate(`document.getElementById('remote-game-img').dataset.view`), 'app', 'the operator pick stays');
      assert.equal(st.streams.length, pinnedStreams);
      await evaluate(`document.getElementById('remote-game-pull').click()`);
      assert.deepEqual(await evaluate(`pulled`), ['remote-game-pull']);

      assert.deepEqual(await evaluate(`({ same: document.getElementById('remote-game') === box, scroll: document.getElementById('side').scrollTop,
        bar: !!document.querySelector('#left > #remote-game-bar'), after: document.getElementById('remote-game').nextElementSibling?.id })`),
        { same: true, scroll: 900, bar: true, after: 'remote-game-bar' }, 'updated in place: same nodes, the sidebar where it was, the bar under the picture');
      assert.equal(await evaluate(`GBoxRemoteGame.html({ sid: ${JSON.stringify(SID)}, wid: 'w1', worker: 'T', auth: '', crop: true }).includes('data-view="app"')`), true,
        'built again (a swap re-renders the view), the session keeps the operator pick');

      await evaluate(`document.getElementById('left').innerHTML = ''`);   // the operator moved on: nothing keeps polling
      const calls = st.statusCalls;
      await new Promise(r => setTimeout(r, 400));
      assert.ok(st.statusCalls <= calls + 1, 'polling stops once the view is gone');
    });

    await scenario('an older control plane without the game view falls back to the gBox window instead of retrying',
      st => { st.gameView = 422; st.status = fresh({ games: undefined, frames: 0, last_frame_age: null }); }, async st => {
        await evaluate(mountJs(true));
        await until(evaluate, `document.getElementById('remote-game-img').naturalWidth > 0`, 'a picture');
        assert.equal(await evaluate(`document.getElementById('remote-game-img').dataset.view`), 'app');
        assert.deepEqual(st.streams.slice(0, 2), [`game:${SID}`, 'app']);
        assert.equal(st.streams.filter(v => v.startsWith('game')).length, 1, 'the refused view is not retried');
      });

    await scenario('a view that shows nothing while that PC sends frames gives way to the next one, for good',
      st => { st.gameView = 'silent'; }, async st => {
        await evaluate(mountJs(true));
        await new Promise(r => setTimeout(r, 300));
        assert.equal(await evaluate(`document.getElementById('remote-game-img').dataset.view`), 'game', 'patient while it is new');
        assert.match(await evaluate(`document.getElementById('remote-game-wait').textContent`), /Connecting to TESTPC's screen/);
        await evaluate(`skew = 11000`);                             // ten seconds on: frames came, none for the game window
        await until(evaluate, `document.getElementById('remote-game-img').naturalWidth > 0`, 'the gBox window picture');
        assert.equal(await evaluate(`document.getElementById('remote-game-img').dataset.view`), 'app');
        await new Promise(r => setTimeout(r, 400));                // polls keep listing the game window: no flip back
        assert.equal(await evaluate(`document.getElementById('remote-game-img').dataset.view`), 'app');
        assert.deepEqual(st.streams, [`game:${SID}`, 'app']);
      });

    await scenario('no picture from that screen is never an empty view: it says why and offers Retry, Stop and Relaunch',
      st => { st.mute = true; st.status = fresh({ frames: 0, last_frame_age: null, games: [] }); }, async st => {   // no screen at all
        await evaluate(mountJs(false));
        await new Promise(r => setTimeout(r, 300));
        assert.equal(await evaluate(`document.getElementById('remote-game-acts').hidden`), true, 'not while it is connecting');
        await evaluate(`skew = 11000`);
        await until(evaluate, `!document.getElementById('remote-game-acts').hidden`, 'the actions');
        assert.match(await evaluate(`document.getElementById('remote-game-wait').textContent`),
          /No picture from TESTPC yet: its gBox worker isn't sending its screen\. The game keeps playing there\./);
        const before = st.streams.length;
        await evaluate(`document.querySelector('#remote-game-acts [data-live-action=retry]').click()`);
        for (let i = 0; i < 200 && st.streams.length === before; i++) await new Promise(r => setTimeout(r, 25));
        assert.deepEqual(st.streams.slice(before), ['app'], 'Retry connects again');
        await evaluate(`document.querySelector('#remote-game-acts [data-live-action=stop]').click();
          document.querySelector('#remote-game-acts [data-live-action=relaunch]').click()`);
        assert.deepEqual(await evaluate(`acted`), ['stop', 'relaunch']);
      });
  });
});

// ---------- the real shell against the PR's synthetic fixture: the i9-NUC's desktop app, the games on JAYBUILTFINALE ----------
function fixtureServer() {
  const py = process.env.GBOX_BROWSER_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const root = path.join(__dirname, '..');
  const proc = spawn(py, [path.join(root, 'scripts/ui_evidence.py'), '--clients', path.join(root, 'clients'),
    '--fixtures', path.join(__dirname, 'fixtures/ui_evidence/session_click_shows_gameplay.json'), '--serve'], { windowsHide: true });
  const url = new Promise((resolve, reject) => {
    let out = '';
    proc.stdout.on('data', b => { out += b; const m = /http:\/\/127\.0\.0\.1:\d+\//.exec(out); if (m) resolve(m[0]); });
    proc.once('exit', code => reject(new Error('fixture server exited ' + code)));
  });
  return { proc, url };
}

test('the real shell: a game elsewhere shows at once when live, and says why when there is no picture of it', { skip: !findChrome() && 'no Chromium installed' }, async t => {
  const { proc, url } = fixtureServer();
  const SOUL = 'a68af3144f704f75-1268260454a84065';
  try {
    const base = await url;
    await page(async (evaluate, send) => {
      await send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });
      const open = async () => {                                 // a fresh shell each time: a blank page first
        await send('Page.navigate', { url: 'about:blank' });
        await until(evaluate, `location.href === 'about:blank'`, 'a blank page');
        await send('Page.navigate', { url: `${base}?embedded=1#token=fixture&worker=i9-NUC` });
        await until(evaluate, `!!document.querySelector('#tray .tchip[data-sid="${SID}"]')`, 'the session icons in the header', 400);
      };

      await t.test('clicking the cloud icon shows the gameplay at once; switching views keeps the page, its scroll and this PC\'s pad', async () => {
        await open();
        assert.equal(await evaluate(`!!document.querySelector('#tray .tchip[data-sid="${SID}"] .where title')?.textContent.startsWith('Remote')`), true, 'the cloud icon');
        await evaluate(`document.querySelector('#tray .tchip[data-sid="${SID}"]').click()`);
        await until(evaluate, `document.getElementById('remote-game-img')?.naturalWidth > 0`, 'the gameplay picture', 400);
        const shown = await evaluate(`({ src: document.getElementById('remote-game-img').getAttribute('src'),
          text: document.getElementById('view').innerText, pull: document.getElementById('remote-game-pull')?.textContent,
          local: active.local, pad: padSid(), dialog: !!document.querySelector('#view h3') })`);
        assert.match(shown.src, new RegExp(`^/api/workers/a68af3144f704f75/desktop/stream\\?view=game&session=${SID}&token=fixture$`));
        assert.doesNotMatch(shown.text, /Running natively on/);
        assert.equal(shown.dialog, false, 'no card over the picture');
        assert.equal(shown.pull, 'Pull it to this PC');
        assert.equal(shown.local, true); assert.equal(shown.pad, null, 'watching never forwards this PC\'s controller to that game');

        await evaluate(`window.playNode = document.querySelector('#view > .play'); document.querySelector('.sidecol').scrollTop = 240;
          window.scrollMark = document.querySelector('.sidecol').scrollTop`);
        await evaluate(`document.querySelector('[data-remote-view=desktop]').click()`);
        await until(evaluate, `document.getElementById('remote-game-img').getAttribute('src').includes('view=desktop')`, 'the desktop view');
        await new Promise(r => setTimeout(r, 300));
        assert.deepEqual(await evaluate(`({ same: document.querySelector('#view > .play') === playNode, scroll: document.querySelector('.sidecol').scrollTop === scrollMark,
          pressed: document.querySelector('[data-remote-view=desktop]').getAttribute('aria-pressed') })`), { same: true, scroll: true, pressed: 'true' });
      });

      // The follow-up (operator 16:45: "make sure gBox isn't listing sessions for me to connect to that don't actually
      // exist"): SoulCalibur on JAYBUILTFINALE whose newest still is 95 s old is marked in the header and the list, and
      // opening it says why
      await t.test('a game with no recent picture is marked, not offered to Watch, and opens on why with Retry / Stop / Relaunch', async () => {
        await open();
        const chips = await evaluate(`[...document.querySelectorAll('#tray .tchip')].map(c => ({ sid: c.dataset.sid, nopic: c.classList.contains('nopic'), title: c.title }))`);
        assert.deepEqual(chips.map(c => [c.sid, c.nopic]), [[SOUL, true], [SID, false]]);
        assert.match(chips[0].title, /no picture from JAYBUILTFINALE for 95 s/);

        await evaluate(`document.querySelector('#tabs button[data-t=Sessions]').click()`);
        await until(evaluate, `!!document.querySelector('#view table')`, 'the session list', 400);
        const rows = await evaluate(`[...document.querySelectorAll('#view table tr')].slice(1).map(r => [r.cells[1].innerText.trim(), r.cells[4].querySelector('button')?.innerText])`);
        assert.deepEqual(rows, [['running', 'Watch'], ['no picture from JAYBUILTFINALE for 95 s', 'Open']]);

        await evaluate(`document.querySelector('#tray .tchip[data-sid="${SOUL}"]').click()`);
        await until(evaluate, `!!document.getElementById('no-picture-bar')`, 'the reason and its actions', 400);
        const view = await evaluate(`({ title: document.getElementById('no-picture-title').textContent, why: document.getElementById('no-picture-why').textContent,
          actions: [...document.querySelectorAll('#no-picture-bar [data-live-action]')].map(b => b.textContent),
          empty: !!document.querySelector('#remote-game, #scr'), local: active.local, pad: padSid() })`);
        assert.equal(view.title, 'No picture from JAYBUILTFINALE for 95 s');
        assert.match(view.why, /hasn't shown this game on its screen for 95 s: it may be minimized, covered or closed there/);
        assert.deepEqual(view.actions, ['Retry', 'Stop', 'Relaunch']);
        assert.equal(view.empty, false, 'no empty picture is offered to watch');
        assert.equal(view.local, true); assert.equal(view.pad, null);
        await until(evaluate, `/^Checked JAYBUILTFINALE at /.test(document.getElementById('no-picture-meta').textContent)`, 'its first check');
      });
    });
  } finally { proc.kill(); }
});

