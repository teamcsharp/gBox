// #2858 follow-up (operator 2026-10-20 16:45: "make sure that gBox isn't listing sessions for me to connect to that
// don't actually exist"): a session is offered for watching only while it is live (its PC's worker online under the id
// that started it, a picture of it recent), and one that is not is never an empty view. The rule runs in node; the
// view that says why (Retry / Stop / Relaunch under it, the game once a picture comes) runs in a real headless Chromium.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const SL = require('../clients/web/viz/session-live.js');
const { findChrome, withPage } = require('../scripts/browser_lifecycle.cjs');

const NOW = 1_800_000_000;
const JAY = { id: 'a68af3144f704f75', name: 'JAYBUILTFINALE', online: true, features: ['desktop_stream', 'desktop_game_crop', 'session_stills'] };
const OLDJAY = { ...JAY, features: ['desktop_stream'] };
const SPARK = { id: 'e2771e1c892e46e9', name: 'lilspark', online: true, features: [] };
const native = (more = {}) => ({ session_id: 'a68af3144f704f75-1268260454a84065', state: 'running', started: NOW - 1000, last_frame_age: 2,
  detail: { local_window: true, worker_name: 'JAYBUILTFINALE' }, ...more });
const streamed = (more = {}) => ({ session_id: 'e2771e1c892e46e9-7db81af4f7bf4711', state: 'running', started: NOW - 600, last_frame_age: 0.1,
  detail: { worker_name: 'lilspark' }, ...more });
const kind = (s, ws = [JAY, SPARK]) => SL.judge(s, ws, NOW).kind;

test('live: its PC online under that id and a recent picture (a stream frame, or a still of a native game)', () => {
  assert.deepEqual(SL.judge(native(), [JAY, SPARK], NOW), { live: true, kind: 'live', pc: 'JAYBUILTFINALE', text: '', why: '', age: 2 });
  assert.equal(kind(streamed()), 'live');
  assert.equal(kind(native({ last_frame_age: null, started: NOW - 10 })), 'starting', 'a new game may still be booting');
  assert.equal(SL.judge(native({ last_frame_age: null }), [OLDJAY], NOW).kind, 'screen',
    'a worker without stills: watched through its screen, the view checks the picture');
  assert.equal(kind(native(), null), 'unknown', 'PCs not loaded: say nothing');
  assert.equal(kind(native(), []), 'unknown', 'an empty worker list is a failed read, not every PC gone');
});

test('not live: says which PC and why, as the header, the list and the view show it', () => {
  const stale = SL.judge(native({ last_frame_age: 95.4 }), [JAY], NOW);
  assert.deepEqual([stale.live, stale.kind, stale.text], [false, 'stale', 'no picture from JAYBUILTFINALE for 95 s']);
  assert.match(stale.why, /^JAYBUILTFINALE hasn't shown this game on its screen for 95 s: it may be minimized, covered or closed there, or that screen may be asleep\.$/);
  assert.equal(SL.judge(native({ last_frame_age: 400 }), [JAY], NOW).text, 'no picture from JAYBUILTFINALE for 7 min');
  const never = SL.judge(native({ last_frame_age: null, started: NOW - 300 }), [JAY], NOW);
  assert.deepEqual([never.kind, never.text], ['stale', 'no picture from JAYBUILTFINALE yet']);
  assert.match(never.why, /since it started 5 min ago/);
  const spark = SL.judge(streamed({ last_frame_age: 42 }), [SPARK], NOW);
  assert.deepEqual([spark.kind, spark.why], ['stale', 'The game stream from lilspark hasn\'t sent a picture for 42 s.']);
  const offline = SL.judge(native(), [{ ...JAY, online: false }], NOW);
  assert.deepEqual([offline.kind, offline.text], ['offline', 'JAYBUILTFINALE is offline']);
  // 16:39: JAYBUILTFINALE came back as cd033cd7576a48aa; a game still listed under the old id has nothing behind it
  const gone = SL.judge(native(), [{ ...JAY, id: 'cd033cd7576a48aa' }], NOW);
  assert.deepEqual([gone.kind, gone.text], ['gone', 'JAYBUILTFINALE is no longer connected']);
  assert.equal(SL.judge(native(), [{ ...JAY, features: [] }], NOW).kind, 'noscreen');
  assert.equal(SL.judge(native({ state: 'ended' }), [JAY], NOW).kind, 'ended');
  assert.equal(SL.judge(streamed({ last_frame_age: SL.STALE_S }), [SPARK], NOW).live, true, 'the threshold itself is still live');
});

test('a row the server flagged worker_online false is offline even before the PC list is loaded (#2870)', () => {
  const dead = native({ worker_online: false });
  assert.deepEqual([kind(dead, null), kind(dead, []), kind(dead)], ['offline', 'offline', 'offline']);
  const v = SL.judge(dead, null, NOW);
  assert.equal(v.text, 'JAYBUILTFINALE is offline'); assert.match(v.why, /stopped answering/); assert.equal(v.live, false);
  assert.equal(kind(native({ worker_online: true }), [{ ...JAY, online: false }]), 'offline', 'a stale flag never overrides an offline PC');
  assert.equal(kind(native({ worker_online: true })), 'live');
});

test('the view for a game with no picture: why where the picture goes, Retry / Stop / Relaunch under it', () => {
  const verdict = SL.judge(native({ last_frame_age: 95.4 }), [JAY], NOW);
  const html = SL.html({ sid: native().session_id, verdict, title: 'SoulCalibur (USA)', auth: 'token=t', online: true });
  assert.match(html, /<img id="no-picture-last" alt="" data-base="\/api\/sessions\/a68af3144f704f75-1268260454a84065\/frame\.jpg\?token=t"/, 'the newest picture, dimmed');
  assert.match(html, /<b id="no-picture-title">No picture from JAYBUILTFINALE for 95 s<\/b>/);
  assert.match(html, /gBox keeps checking: the game shows here as soon as a picture of it comes/);
  assert.match(html, /data-live-action="retry"[^>]*>Retry<\/button>[\s\S]*data-live-action="stop"[^>]*>Stop<\/button>[\s\S]*data-live-action="relaunch"[^>]*>Relaunch<\/button>/);
  assert.match(html, /title="Start this game again on JAYBUILTFINALE: same game and build"/);
  const away = SL.html({ sid: 'x-y', verdict: SL.judge(native(), [{ ...JAY, online: false }], NOW), auth: '', online: false });
  assert.match(away, /title="Start this game again where you play: same game and build"/);
  assert.match(away, /title="Stop the game on JAYBUILTFINALE as soon as it is back"/);
  assert.doesNotMatch(html, /class="screen"[^>]*data-sid=/, 'not a game picture for the report menu or the pick whip');
});

test('the shell asks the rule everywhere a game elsewhere is offered', () => {
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(web, /<script src="\/viz\/session-live\.js"><\/script>/);
  assert.match(web, /pics = new Map\(run\.map\(x => \[x\.session_id, sessionIsLocal\(x\) && x\.worker_online !== false \? \{ live: true \} : GBoxSessionLive\.judge\(x, ws, nowS\)\]\)\)/, 'header icons (a game here on an offline worker too, #2870)');
  assert.match(web, /\$\{v\.live \? "" : '<i class="np">no picture<\/i>'\}/);
  assert.match(web, /const pic = s => s\.state === "running" && \(!sessionIsLocal\(s\) \|\| s\.worker_online === false\) \? GBoxSessionLive\.judge\(s, ws, nowS\) : \{ live: true \};/, 'the list (a game here on an offline worker too, #2870)');
  assert.match(web, /\$\{verdict && !verdict\.live \? GBoxSessionLive\.html\(\{ sid, verdict, title: s\.title, auth: tq\(\), online: !!hostPC\?\.online \}\)/, 'the view');
  assert.match(web, /if \(\$\("#no-picture"\)\) GBoxSessionLive\.mount\(document, \{ sid, api, stop, relaunch, onLive: \(\) => show\("Sessions", sid, mode\) \}\);/);
  const relaunch = web.slice(web.indexOf('async function relaunchSession('), web.indexOf('async function runJob('));
  assert.match(relaunch, /if \(s\.state === "running" && ws\.some\(w => w\.id === sid\.split\("-"\)\[0\] && w\.online\)\) return await restartGame\(sid, btn\);/,
    'its PC answers: the same game, build and PC again');
  assert.match(relaunch, /play\(s\.game_id, undefined, false, \{ disc: \(s\.collection_mod \|\| s\.mod \|\| ""\)\.split\("~"\)\[0\], slot: "" \}\)/, 'else where you play');
});

test('the view checks, says what it found, offers its actions and shows the game once a picture comes', { skip: !findChrome() && 'no Chromium installed' }, async () => {
  const st = { sessions: [native({ last_frame_age: 95 })], workers: [JAY], calls: 0 };
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/') {
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.end(`<!doctype html><html><head><meta charset="utf-8"><style>:root{--line:#333;--card:#222;--mut:#999;--bad:#f66}
        body{margin:0;background:#111;color:#eee;font:13px system-ui}.screen{height:420px;display:block;background:#000}</style></head>
        <body><div id="left"></div><script src="/session-live.js"></script></body></html>`);
      return;
    }
    if (url.pathname === '/session-live.js') {
      res.setHeader('Content-Type', 'text/javascript; charset=utf-8');
      res.end(fs.readFileSync(path.join(__dirname, '../clients/web/viz/session-live.js')));
      return;
    }
    res.setHeader('Content-Type', 'application/json');
    if (url.pathname === '/api/sessions') { st.calls++; res.end(JSON.stringify(st.sessions)); return; }
    if (url.pathname === '/api/workers') { res.end(JSON.stringify(st.workers)); return; }
    res.writeHead(404); res.end('{}');
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const until = async (evaluate, expr, what) => {
    for (let i = 0; i < 200; i++) { if (await evaluate(expr)) return; await new Promise(r => setTimeout(r, 25)); }
    assert.fail('timed out waiting for ' + what);
  };
  try {
    await withPage(async (evaluate, send) => { try {
      await send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
      await until(evaluate, `!!window.GBoxSessionLive`, 'the module');
      await evaluate(`(() => {
        const s = ${JSON.stringify(native({ last_frame_age: 95 }))};
        document.getElementById('left').innerHTML = GBoxSessionLive.html({ sid: s.session_id, verdict: GBoxSessionLive.judge(s, ${JSON.stringify([JAY])}, ${NOW}),
          title: 'SoulCalibur (USA)', auth: 'token=t', online: true });
        window.acted = []; window.lived = 0;
        window.ctl = GBoxSessionLive.mount(document, { sid: s.session_id, api: p => fetch(p).then(r => r.json()),
          stop: b => acted.push('stop'), relaunch: b => acted.push('relaunch'), onLive: v => { lived++; window.liveKind = v.kind; },
          setTimer: (f, ms) => setTimeout(f, Math.min(ms, 40)), now: () => ${NOW * 1000} });
      })()`);
      await until(evaluate, `/^Checked JAYBUILTFINALE at /.test(document.getElementById('no-picture-meta').textContent)`, 'the first check');
      st.sessions = [native({ last_frame_age: 400 })];
      await until(evaluate, `document.getElementById('no-picture-title').textContent === 'No picture from JAYBUILTFINALE for 7 min'`, 'the reason kept current');
      st.workers = [{ ...JAY, online: false }];
      await until(evaluate, `document.getElementById('no-picture').dataset.kind === 'offline'`, 'the PC going offline');
      assert.equal(await evaluate(`document.getElementById('no-picture-why').textContent`),
        "JAYBUILTFINALE's gBox worker stopped answering, so there is no picture of this game. It shows here again as soon as JAYBUILTFINALE is back.");
      await evaluate(`[...document.querySelectorAll('#no-picture-bar [data-live-action]')].forEach(b => b.click())`);
      assert.deepEqual(await evaluate(`acted`), ['stop', 'relaunch'], 'Retry checks, Stop and Relaunch are the shell\'s');
      assert.equal(await evaluate(`lived`), 0);
      st.workers = [JAY]; st.sessions = [native({ last_frame_age: 1 })];      // the game is on its screen again
      await until(evaluate, `lived === 1`, 'the game');
      const calls = st.calls;
      await new Promise(r => setTimeout(r, 300));
      assert.equal(await evaluate(`lived`), 1, 'shown once');
      assert.equal(await evaluate(`liveKind`), 'live');
      assert.equal(st.calls, calls, 'no more checks once the game shows');
    } finally { await send('Page.navigate', { url: 'about:blank' }).catch(() => {}); } });   // close the page before the browser
  } finally { await new Promise(r => server.close(r)); }
});
