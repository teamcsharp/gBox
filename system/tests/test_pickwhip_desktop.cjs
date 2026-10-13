// Desktop pick whip wiring (clients/desktop/index.html + main.js): right-click routing, the pause hold around the
// character menu and the eyedropper, the header model for local naming, and main's crash/close resume.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const mainJs = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
const slice = (src, a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i + 1); assert.ok(i >= 0 && j > i, `slice ${a}`); return src.slice(i, j); };

function desktop({ rclick = true, pause = true, eyeOn = false, model = 'gemma4:e4b' } = {}) {
  const seen = { acquire: [], release: [], menus: [], pip: [], reports: [], jobs: [] };
  const stub = {
    settings: () => ({ rclick, pause, cloud: false, name: true }),
    createHold: () => ({ acquire: async sid => { seen.acquire.push(sid); return { paused: true }; }, release: async sid => { seen.release.push(sid); } }),
    createConsole: () => ({ open: () => ({}), anchor() {} }),
    characterMenu: (doc, io, o) => { seen.menus.push({ io, o }); return {}; },
    runTool: async () => ({ ok: true, result: {}, job: {} }),
  };
  const ctx = { GBoxPickWhip: stub, EMB: { sid: 'w1-s1', game: '0123456789abcdef', title: 'AUF', rect: { x: 100, y: 50, w: 800, h: 600 } },
    EYE: { on: eyeOn, preview: eyeOn ? { picked: { class: 'bot' } } : null }, CH: { models: { models: [{ name: 'gemma4:e4b', capabilities: ['tools', 'vision'] }] } },
    S: { apiUrl: 'http://spark', workerName: 'PC' }, document: {}, window: {}, navigator: { clipboard: { writeText: async () => {} } },
    $: sel => sel === '#chatmodel' ? { value: model } : null, toast() {}, fitMenu() {}, dragAnywhere() {}, embedSoon() {}, blenderCopiedMsg() {},
    pipMenu: (x, y) => seen.pip.push([x, y]), retargetOpen() {}, gameJob: async (tool, input) => { seen.jobs.push({ tool, input }); return { status: 'ok' }; },
    autoWhipFailure: async o => { seen.reports.push(o); return { number: 1 }; },
    gbox: { api: async () => ({ ok: true, data: {} }), token: async () => 'tok' }, encodeURIComponent };
  vm.createContext(ctx);
  vm.runInContext(slice(html, 'const PW = GBoxPickWhip;', '// ---------------- game eyedropper (Ctrl+I') +
    '\nthis.pw = { pwRightClick, pwMenuAt, pwIO, pwModel, PWD };', ctx);
  return { ctx, seen, pw: ctx.pw };
}
const settle = () => new Promise(r => setTimeout(r, 0));
const plain = x => JSON.parse(JSON.stringify(x));                // objects made inside the vm context have other prototypes

test('right-click on a character opens its menu with the game paused; closing resumes', async () => {
  const d = desktop();
  d.pw.pwRightClick(500, 350); await settle();
  assert.deepEqual(d.seen.acquire, ['w1-s1']);
  const { o } = d.seen.menus[0];
  assert.equal(o.sid, 'w1-s1'); assert.deepEqual(plain(o.at), [0.5, 0.5]); assert.equal(o.aspect, 800 / 600); assert.equal(o.gid, '0123456789abcdef');
  assert.ok(o.extra.some(x => x.id === 'gamemenu'));
  o.onExtra('gamemenu'); assert.deepEqual(d.seen.pip, [[500, 350]]);
  o.onClose('dismiss'); assert.deepEqual(d.seen.release, ['w1-s1']);
});

test('right-click outside the game, or with the character menu off, opens the game menu', async () => {
  let d = desktop();
  d.pw.pwRightClick(50, 20); await settle();
  assert.equal(d.seen.menus.length, 0); assert.deepEqual(d.seen.pip, [[50, 20]]);
  d = desktop({ rclick: false });
  d.pw.pwRightClick(500, 350); await settle();
  assert.equal(d.seen.menus.length, 0); assert.equal(d.seen.pip.length, 1);
});

test('inside the eyedropper the frozen preview is reused and the eyedropper keeps the hold', async () => {
  const d = desktop({ eyeOn: true });
  await d.pw.pwMenuAt(500, 350);
  assert.deepEqual(d.seen.acquire, []);
  assert.equal(d.seen.menus[0].o.preview.picked.class, 'bot');
  d.seen.menus[0].o.onClose('picked'); assert.deepEqual(d.seen.release, []);
});

test('naming uses the header model; replace falls back to live_use, then a rebuild request', async () => {
  let d = desktop();
  assert.deepEqual(plain(d.pw.pwModel()), { name: 'gemma4:e4b', vision: true });
  assert.equal(desktop({ model: 'auto' }).pw.pwModel().name, '');
  const io = await d.pw.pwIO();
  await io.fallbackLive({ character: 'amy', x: 0.5, y: 0.4 });
  assert.deepEqual(plain(d.seen.jobs[0]), { tool: 'characters', input: { op: 'live_use', character: 'amy', session_id: 'w1-s1', x: 0.5, y: 0.4 } });
  await io.fallbackBuild({ character: 'amy', name: 'Amy', target: 'bot', kind: 'npc', slot: 'npc_3', x: 0.5, y: 0.4, steps: [{ via: 'characters live_use', mode: 'live', status: 'unsupported' }] });
  const rep = d.seen.reports[0];
  assert.equal(rep.requested, true); assert.equal(rep.rebuild, true); assert.equal(rep.character, 'amy');
  assert.match(rep.detail, /slot npc_3.*characters live_use live: unsupported/);
});

test('closing the eyedropper resumes the game it paused', () => {
  const released = [];
  const ctx = { EYE: { on: true, sid: 'w1-s1', hover: { stop() { this.stopped = true; } }, lab: { remove() {} } }, EMB: {}, PWD: { hold: { release: sid => released.push(sid) } },
    $: () => null, removeEventListener() {}, embedTick() {}, cancelAnimationFrame() {} };
  vm.createContext(ctx);
  vm.runInContext(slice(html, 'function eyeStop() {', 'function eyeHover() {') + '\neyeStop();', ctx);
  assert.deepEqual(released, ['w1-s1']); assert.equal(ctx.EYE.sid, null); assert.equal(ctx.EYE.hover.stopped, true);
});

test('main resumes held games when the window crashes, reloads or closes', async () => {
  const calls = [], logs = [];
  const ctx = { api: async (p, b) => { calls.push([p, b]); }, logPush: (k, m) => logs.push(m) };
  vm.createContext(ctx);
  vm.runInContext(slice(mainJs, 'const PICK_HOLDS = new Map();', 'ipcMain.handle("api"') + '\nthis.m = { pickHoldTrack, pickHoldReleaseAll, PICK_HOLDS };', ctx);
  const { pickHoldTrack, pickHoldReleaseAll, PICK_HOLDS } = ctx.m;
  pickHoldTrack('/api/pickwhip/w1-s1/hold', { op: 'pause', holder: 'desktop-x' });
  pickHoldTrack('/api/pickwhip/w1-s2/hold', { op: 'pause', holder: 'desktop-x' });
  pickHoldTrack('/api/pickwhip/w1-s2/hold', { op: 'release', holder: 'desktop-x' });
  pickHoldTrack('/api/jobs', { tool: 'pick' });
  assert.deepEqual(plain([...PICK_HOLDS.keys()]), ['w1-s1']);
  pickHoldReleaseAll('window crashed');
  assert.deepEqual(plain(calls), [['/api/pickwhip/w1-s1/hold', { op: 'release', holder: 'desktop-x' }]]);
  assert.equal(PICK_HOLDS.size, 0); assert.match(logs[0], /resuming w1-s1 \(window crashed\)/);
  assert.match(mainJs, /render-process-gone[\s\S]{0,300}pickHoldReleaseAll\("window crashed"\)/);
  assert.match(mainJs, /win\.on\("closed", \(\) => pickHoldReleaseAll\("window closed"\)\)/);
});

test('the shell loads the shared module and cuts its menu and console out of the docked game', () => {
  assert.match(html, /<script src="\.\.\/web\/viz\/pick-whip\.js"><\/script>/);
  assert.match(html, /const EMB_HOLES = "[^"]*#pwmenu, #pwcon"/);
  assert.match(html, /if \(ev\.event === "rclick"\) pwRightClick\(ev\.x, ev\.y\)/);
  assert.match(html, /m\.ev === "gamecontext"\) pwRightClick/);
});
