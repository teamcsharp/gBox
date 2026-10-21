const { test } = require('node:test');
const assert = require('node:assert/strict'), fs = require('node:fs/promises'), os = require('node:os'), path = require('node:path'), vm = require('node:vm');
const R = require('../clients/desktop/client-refresh.js'), V = require('../clients/desktop/client-version.cjs');
const C = require('../clients/desktop/compact-game.js');
function fixture(options = {}) {
  const saved = new Map(), calls = [], timers = new Map(); let id = 0;
  const storage = { getItem: k => saved.get(k), setItem: (k, v) => saved.set(k, v), removeItem: k => saved.delete(k) };
  const ctl = R.create({ storage, now: () => 1000, context: () => ({ sid: 'old', compact: false, section: 'play' }),
    readState: async () => ({ playing: 'selected' }), reload: async state => calls.push(state),
    setTimer: fn => { timers.set(++id, fn); return id; }, clearTimer: id => timers.delete(id), ...options });
  return { ctl, saved, calls, timers, storage };
}
test('F5 saves exact session and no credentials, then invokes only client reload', async () => {
  const x = fixture({ readState: async () => ({ playing: 'spark-exact', hash: '#token=SECRET' }) });
  const value = await x.ctl.refresh(); assert.equal(value.sid, 'spark-exact'); assert.equal(x.calls.length, 1);
  assert.doesNotMatch([...x.saved.values()].join(''), /SECRET|token/); assert.equal(x.timers.size, 0);
  assert.equal(x.ctl.pending().sid, 'spark-exact'); x.ctl.done(); assert.equal(x.ctl.pending(), null);
});
test('compact reload preserves its session, ratio and original return mode over a different guest selection', async () => {
  const x = fixture({ context: () => ({ sid: 'compact-game', compact: true, aspect: 16/9, returnMode: 'full', section: 'play' }) });
  const value = await x.ctl.refresh(); assert.equal(value.sid, 'compact-game'); assert.equal(value.aspect, 16/9); assert.equal(value.returnMode, 'full');
  const calls = [], ctl = C.create({ mode: () => 'auto', resolve: async request => { calls.push(request); return { sid: request.sid, local: false }; },
    windowMode: async value => ({ ...value }), render() {}, present() {}, pad() {} });
  await ctl.enter(value); assert.equal(calls[0].sid, 'compact-game'); assert.equal(ctl.state.returnMode, 'full'); assert.equal(ctl.state.aspect, 16/9);
});
test('hung guest is bounded, overlapping F5 is deduplicated, and known session is retained', async () => {
  const x = fixture({ readState: () => new Promise(() => {}) }); const a = x.ctl.refresh(), b = x.ctl.refresh(); assert.equal(a, b);
  for (const fn of x.timers.values()) fn(); const value = await a;
  assert.equal(value.sid, 'old'); assert.equal(x.calls.length, 1);
});
test('F5 retains distinct main stream, guest PiP and native compact origin without credentials', async () => {
  const x=fixture({context:()=>({sid:'native-pip',compact:true,aspect:16/9,returnMode:'full',section:'play'}),
    readState:async()=>({tab:'Sessions',playing:'main-A',active:'guest-B',pip:'guest-B',hash:'#token=SECRET'})});
  const value=await x.ctl.refresh();
  assert.equal(value.sid,'native-pip');
  assert.deepEqual(value.guest,{tab:'Sessions',playing:'main-A',active:'guest-B',pip:'guest-B'});
  assert.doesNotMatch(JSON.stringify(value),/SECRET|token/);
});
test('hung guest and Ctrl+R use the last confirmed pair; partial reconnect retries retain the absent stream', async () => {
  const x=fixture({readState:()=>new Promise(()=>{})});
  x.ctl.remember({tab:'Sessions',playing:'main-A',active:'pip-B',pip:'pip-B'});
  const task=x.ctl.refresh();for(const f of x.timers.values())f();
  const value=await task;assert.equal(value.guest.pip,'pip-B');assert.equal(value.guest.playing,'main-A');
  x.ctl.remember({tab:'Sessions',playing:'main-A',active:'main-A'});
  const retry=await x.ctl.refresh();assert.deepEqual(retry,value);
  x.ctl.done();x.ctl.remember({tab:'Library',active:'pip-B',pip:'pip-B'});
  assert.equal(x.ctl.checkpoint().guest.pip,'pip-B');assert.equal(x.ctl.pending().guest.tab,'Library');
});
test('invalid or expired reload state cannot select a session or inject a selector', () => {
  const x = fixture(); x.storage.setItem('gbox.client.refresh.v1', JSON.stringify({ v: 1, at: -500000, sid: 'old', compact: true }));
  assert.equal(x.ctl.pending(), null);
  const s = R.snapshot({ sid: '../bad?token=x', compact: true, section: '"] button', aspect: Infinity, returnMode: 'fake' });
  assert.equal(s.sid, null); assert.equal(s.compact, false); assert.equal(s.section, 'play'); assert.equal(s.aspect, 4/3);
});
test('update indication uses actual changed identities and does not call offline an update', () => {
  const baseline = { renderer: 'A', remote: 'R' };
  assert.equal(R.changed(baseline, { renderer: 'A', remote: null }).pending, false);
  assert.equal(R.changed(baseline, { renderer: 'B', remote: 'R' }).pending, true);
  assert.equal(R.changed(baseline, { renderer: 'A', remote: 'S' }).remote, true);
  assert.equal(R.changed(baseline, { renderer: 'A', restart: true }).restart, true);
  assert.equal(R.changed(baseline, null).pending, false);
});
test('file fingerprints detect equal-size edits independent of timestamps and retain main-process restart state across reloads', async t => {
  const parent = path.resolve(os.tmpdir()), dir = await fs.mkdtemp(path.join(parent, 'gbox-client-version-'));
  t.after(() => { assert.equal(path.dirname(path.resolve(dir)), parent); assert.match(path.basename(dir), /^gbox-client-version-/); return fs.rm(dir, { recursive: true, force: true }); });
  const desktop = path.join(dir, 'desktop'), web = path.join(dir, 'web'); await fs.mkdir(desktop); await fs.mkdir(web);
  const main = path.join(desktop, 'main.js'), html = path.join(desktop, 'index.html');
  await fs.writeFile(main, 'main1'); await fs.writeFile(html, 'html1'); await fs.writeFile(path.join(web, 'index.html'), 'web1');
  let etag = 'server-1'; const requests = [];
  const ctl = V.create({ desktop, web, runtimeFiles: [main], apiUrl: () => 'http://localhost:8765',
    fetch: async (url, opts) => { requests.push(opts); return { ok: true, headers: new Map([['etag', etag]]) }; } });
  const a = await ctl.read(); assert.equal(a.restart, false);
  const stamp = await fs.stat(html); await fs.writeFile(html, 'html2'); await fs.utimes(html, stamp.atime, stamp.mtime);
  const b = await ctl.read(); assert.notEqual(a.renderer, b.renderer); assert.equal(b.restart, false);
  await fs.writeFile(main, 'main2'); const c = await ctl.read(); assert.equal(c.restart, true);
  assert.equal((await ctl.read()).restart, true); etag = 'server-2'; assert.notEqual((await ctl.read()).remote, c.remote);
  assert.ok(requests.every(r => r.method === 'GET' && r.signal && r.cache === 'no-store'));
});
test('desktop reload IPC is main-frame only and reloads without restarting jobs or dropping compact state', async () => {
  const main = await fs.readFile(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
  const src = main.slice(main.indexOf('function assertClientSender('), main.indexOf('let clientVersions ='));
  let handler, reloads = 0; const wc = { mainFrame: {}, reloadIgnoringCache: () => reloads++ };
  let miniReloads = 0;
  const ctx = vm.createContext({ ipcMain: { handle: (name, fn) => { handler = fn; } }, win: { webContents: wc }, clientReloading: false,
    clientVersions: null, clientActivation: {state:'active'},
    mini: { isDestroyed: () => false, webContents: { reloadIgnoringCache: () => miniReloads++ } } });
  vm.runInContext(src, ctx);
  await assert.rejects(handler({ sender: {}, senderFrame: {} }), /Only the gBox app/);
  await assert.rejects(handler({ sender: wc, senderFrame: {} }), /Only the gBox app/);
  assert.equal((await handler({ sender: wc, senderFrame: wc.mainFrame })).state, 'active'); assert.equal(reloads, 1);
  assert.equal(await handler({ sender: wc, senderFrame: wc.mainFrame }), false); assert.equal(reloads, 1);
  assert.equal(miniReloads, 1); // a second connected stream keeps its own window and URL while refreshing
  assert.match(main, /F5: "client-refresh"/); assert.match(main, /if \(!clientReloading && compactWindow.state\(\).on\)/);
});
test('update border is exactly 2px around the fitted gameplay and never intercepts input', async () => {
  const html = await fs.readFile(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const src = html.slice(html.indexOf('function renderClientUpdate()'), html.indexOf("addEventListener('resize', () => renderClientUpdate())"));
  const nodes = new Map([['#brand', { classList: { toggle() {} }, dataset: {} }]]);
  const ctx = vm.createContext({ clientUpdateState: { pending: true }, COMPACT: { on: true, aspect: 16/9 }, GBoxCompactGame: C,
    innerWidth: 800, innerHeight: 600, $: id => nodes.get(id), document: { body: { classList: { toggle() {} }, append: el => nodes.set('#' + el.id, el) },
      createElement: () => ({ style: {}, setAttribute() {} }) } });
  vm.runInContext(src + ';renderClientUpdate()', ctx); const border = nodes.get('#client-update-border');
  assert.equal(border.style.border, '2px solid red'); assert.equal(border.style.pointerEvents, 'none');
  assert.equal(border.style.top, '75px'); assert.equal(border.style.height, '450px');
  ctx.COMPACT.on = false; vm.runInContext('renderClientUpdate()', ctx); assert.equal(border.style.display, 'none');
  assert.match(html, /requested\?\.sid\) throw Error\('The selected session is unavailable/);
  assert.doesNotMatch(html.slice(html.indexOf('gbox.onHotkey?.'), html.indexOf('gbox.onHotkey?.') + 600), /resetGame/);
});

test('missing saved session restores the original app window and retains retry intent without selecting another game', async () => {
  const html = await fs.readFile(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const src = html.slice(html.indexOf('async function restoreClientView()'), html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  const calls = [], value = { sid: 'exact-old', compact: true, section: 'play' }, EMB = {};
  const ctx = vm.createContext({ EMB, clientRefresh: { pending: () => value, done: () => calls.push('consumed') },
    document: { querySelector: selector => selector === '#wv' ? { gboxReady: Promise.resolve(), executeJavaScript: async () => ({ missing: [] }) } : { click() {} } }, loadPlay: async () => calls.push('load'),
    compactController: { enter: async v => { assert.equal(v.sid, 'exact-old'); throw Error('session unavailable'); } },
    gbox: { compactView: async v => calls.push(v.on) }, toast: text => calls.push(text) });
  vm.runInContext(src, ctx); await ctx.restoreClientView();
  assert.equal(EMB.sid, 'exact-old'); assert.deepEqual(calls.slice(0, 2), ['load', false]); assert.ok(!calls.includes('consumed'));
});

test('restoration waits for the guest and restores two streams before entering native PiP without changing guest selection', async () => {
  const html=await fs.readFile(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const src=html.slice(html.indexOf('async function restoreClientView()'),html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  const calls=[], value={sid:'pip-B',compact:true,section:'play',guest:{tab:'Sessions',playing:'main-A',active:'main-A',pip:null}};
  let ready;const wv={gboxReady:new Promise(r=>ready=r),executeJavaScript:async script=>{assert.match(script,/main-A/);calls.push('guest');return {restored:['main-A'],missing:[]};}};
  const ctx=vm.createContext({EMB:{},clientRefresh:{pending:()=>value,done:()=>calls.push('done')},
    document:{querySelector:s=>s==='#wv'?wv:{click(){}}},loadPlay:async()=>calls.push('load'),
    compactController:{enter:async v=>{assert.equal(v.sid,'pip-B');assert.equal(v.preserveGuest,true);calls.push('compact');}},
    gbox:{compactView:async()=>{}},toast:()=>{}});
  vm.runInContext(src,ctx);const restoring=ctx.restoreClientView();await Promise.resolve();
  assert.deepEqual(calls,['load']);ready();await restoring;
  assert.deepEqual(calls,['load','guest','compact','done']);assert.equal(ctx.EMB.sid,'main-A');
});

test('all edited desktop and web inline classic scripts parse', async () => {
  for (const name of ['desktop', 'web']) {
    const html = await fs.readFile(path.join(__dirname, '../clients', name, 'index.html'), 'utf8');
    for (const m of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
      const type = /type\s*=\s*["']([^"']+)["']/.exec(m[1])?.[1];
      if ((!type || ['text/javascript', 'application/javascript'].includes(type)) && !/\bsrc\s*=/.test(m[1])) new vm.Script(m[2], { filename: name + '/index.html' });
    }
  }
});
