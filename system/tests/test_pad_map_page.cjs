// Run with node system/tests/test_pad_map_page.cjs (needs Edge/Chrome; scripts/browser_lifecycle.cjs).
// The real web client on a fake control plane, an N64 game open in the play view: a real right-click on the
// controller picture's C-up opens "Map N64 C-up to…" (never the report menu, never a press in the game), picking RB
// saves the map on the server, and the operator's pad then reaches the streamed game through it.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const { withPage } = require('../scripts/browser_lifecycle.cjs');

function plane(session, posts, maps) {
  const web = path.resolve(__dirname, '../clients/web'), sid = session.session_id;
  return http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (!url.pathname.startsWith('/api/')) {
      const file = path.resolve(web, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
      if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'content-type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html' });
      res.end(fs.readFileSync(file)); return;
    }
    let body = '';
    req.on('data', c => { body += c; });
    req.on('end', () => {
      const json = body ? JSON.parse(body) : null;
      if (req.method === 'POST') posts.push({ path: url.pathname, body: json });
      let data = [];
      if (url.pathname === '/api/sessions') data = [session];
      else if (url.pathname === `/api/catalog/${session.game_id}`) data = { game_id: session.game_id, title: session.title, platform: 'n64', system: 'Nintendo 64' };
      else if (url.pathname === `/api/sessions/${sid}/pad`) data = { held: [], sources: {}, source: null, ts: 0, platform: 'n64', adapter: session.adapter };
      else if (url.pathname === '/api/controller-maps') data = { maps, updated: {} };
      else if (url.pathname === '/api/controller-maps/n64' && req.method === 'POST') { maps.n64 = json.map; data = { platform: 'n64', map: json.map, sticks: true }; }
      else if (url.pathname.endsWith('/input')) data = { queued: (json && json.events || []).length };
      else if (req.method === 'POST' || /\/api\/(jobs|requests|mods|registry|tasks)/.test(url.pathname)) data = {};
      res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(data));
    });
  });
}

async function open(evaluate, send, port, sid, first = true) {
  if (first) {
    await send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 1000, deviceScaleFactor: 1, mobile: false });
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__errs=[];addEventListener('error',e=>{if(__errs.length<8)__errs.push(e.message+' @'+e.lineno)});` });
  }
  await send('Page.navigate', { url: `http://127.0.0.1:${port}/#token=fixture&session=${sid}` });
  await evaluate(`(async()=>{const end=Date.now()+30000;while(!window.gboxViewReady||!document.querySelector('#padglyph [data-btn="cup"]')){
    if(Date.now()>end)throw Error('no controller picture; errors='+JSON.stringify(window.__errs));await new Promise(r=>setTimeout(r,50));}await window.gboxViewReady;})()`);
}
const center = (evaluate, sel) => evaluate(`(()=>{const b=document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();return {x:b.left+b.width/2,y:b.top+b.height/2}})()`);
async function mouse(send, p, button) {
  for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x: p.x, y: p.y, button, buttons: type === 'mousePressed' ? (button === 'right' ? 2 : 1) : 0, clickCount: 1 });
}
const settle = (evaluate, ms = 60) => evaluate(`new Promise(r=>requestAnimationFrame(()=>setTimeout(r,${ms})))`);
async function screenshot(send, name) {           // GBOX_PADMAP_EVIDENCE=<folder>: keep pictures of the dialog for a review
  const dir = process.env.GBOX_PADMAP_EVIDENCE;
  if (!dir) return;
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(path.join(dir, name + '.png'), Buffer.from(shot.result.data, 'base64'));
}
const xi = (evaluate, more) => evaluate(`window.gboxNativePad([${JSON.stringify({ slot: 0, buttons: 0, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0, ...more })}])`);

// one browser for both games: the shared harness's process cleanup is the slow part on a busy PC
test('page: N64 streamed (right-click C-up, map it to RB, the pad presses C-up through it) and native (applies at next start)', async () => {
  const streamed = { session_id: 'spark-1-n64', game_id: 'sm64', title: 'Super Mario 64', state: 'running', adapter: 'retroarch', platform: 'n64', detail: {} };
  const native = { session_id: 'jay-2-n64', game_id: 'sm64', title: 'Super Mario 64', state: 'running', adapter: 'retroarch', platform: 'n64',
                   detail: { local_window: true, worker_name: 'JAYBUILTFINALE', pid: 1 } };
  const posts = [], maps = {}, server = plane(streamed, posts, maps);
  const posts2 = [], maps2 = { n64: { r: 'rup', rup: 'r' } }, server2 = plane(native, posts2, maps2);
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  await new Promise(r => server2.listen(0, '127.0.0.1', r));
  try {
    await withPage(async (evaluate, send) => {
      await open(evaluate, send, server.address().port, streamed.session_id);
      assert.equal(await evaluate('typeof GBoxPadMap'), 'object');
      const inputs = () => posts.filter(p => p.path.endsWith('/input')).flatMap(p => p.body.events.map(e => `${e.key}:${e.down ? 'down' : 'up'}`));
      // the default N64 layout over the desktop's XInput reading: right stick up = C-up, left stick = the N64 stick
      await xi(evaluate, { ry: 30000, lx: -30000 }); await settle(evaluate, 150);
      assert.deepEqual(inputs().sort(), ['lleft:down', 'rup:down']);
      assert.equal(await evaluate(`document.querySelector('#padglyph [data-btn="cup"]').classList.contains('on')`), true, 'the picture lights C-up');
      await xi(evaluate, {}); await settle(evaluate, 150);
      posts.length = 0;
      // a real right-click on C-up
      await mouse(send, await center(evaluate, '#padglyph [data-btn="cup"]'), 'right'); await settle(evaluate);
      assert.match(await evaluate(`document.querySelector('#padmapdlg')?.innerText||''`), /Map N64 C-up to…[\s\S]*Now: Right stick up[\s\S]*Streamed game: a change works at once/);
      await screenshot(send, 'n64-c-up-dialog');
      assert.equal(await evaluate(`!!document.querySelector('#issuemenu') && getComputedStyle(document.querySelector('#issuemenu')).display !== 'none'`), false, 'no report menu');
      assert.deepEqual(inputs(), [], 'a right-click presses nothing in the game');
      await evaluate(`document.querySelector('#padmapdlg [data-src="r"]').click()`); await settle(evaluate, 200);
      assert.deepEqual(posts.find(p => p.path === '/api/controller-maps/n64').body, { map: { r: 'rup' } }, 'saved on the server');
      assert.match(await evaluate(`document.querySelector('#padmapdlg').innerText`), /RB → C-up \(Right stick up too\) · saved[\s\S]*No control: R\./);
      await screenshot(send, 'n64-c-up-on-rb-saved');
      await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
      posts.length = 0;
      await xi(evaluate, { buttons: 0x0200 }); await settle(evaluate, 150);           // XInput RB
      assert.deepEqual(inputs(), ['rup:down'], 'RB presses C-up in the streamed game');
      assert.equal(await evaluate(`document.querySelector('#padglyph [data-btn="cup"]').classList.contains('on')`), true);
      await xi(evaluate, {}); await settle(evaluate, 150);
      // a left-click on the picture's C-up still presses C-up (the right stick, which the cores read as C-up)
      posts.length = 0;
      await mouse(send, await center(evaluate, '#padglyph [data-btn="cup"]'), 'left'); await settle(evaluate, 200);
      assert.deepEqual(inputs(), ['rup:down', 'rup:up']);
      assert.deepEqual(await evaluate('window.__errs'), []);

      // the same N64 game in a native RetroArch window on this PC, C-up already on RB
      await open(evaluate, send, server2.address().port, native.session_id, false);
      await settle(evaluate, 200);
      await mouse(send, await center(evaluate, '#padglyph [data-btn="lstick"]'), 'right'); await settle(evaluate);
      const text = await evaluate(`document.querySelector('#padmapdlg')?.innerText||''`);
      assert.match(text, /Map N64 Stick to…[\s\S]*Now: Left stick/);
      assert.match(text, /reads controller maps when it starts/);
      // a map that moved right stick up alone (as an older swap did): RetroArch would drop right stick down
      assert.match(text, /In this RetroArch window a stick axis only moves as a whole: Right stick down does nothing/);
      assert.equal(await evaluate(`!!document.querySelector('#padmapdlg [data-apply]')`), true, 'Restart now (keeps your moment)');
      await screenshot(send, 'n64-stick-dialog-native');
      await xi(evaluate, { buttons: 0x0200 }); await settle(evaluate, 150);
      assert.deepEqual(posts2.filter(p => p.path.endsWith('/input')), [], 'RetroArch reads the pad itself: nothing is forwarded');
      assert.equal(await evaluate(`document.querySelector('#padglyph [data-btn="cup"]').classList.contains('on')`), true,
        'the picture shows the saved map (RB = C-up), as the remap file gives it to RetroArch');
      await xi(evaluate, {});
    });
  } finally { server.close(); server2.close(); }
});
