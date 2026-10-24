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
test('the desktop shell creates its refresh controller before settings load, then binds to the loaded origin', async () => {
  const html = await fs.readFile(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const call = html.slice(html.indexOf('GBoxClientRefresh.create('), html.indexOf('reload: async', html.indexOf('GBoxClientRefresh.create(')));
  assert.match(call, /origin: S\?\.apiUrl/); // `S` is undefined until loadSettings() resolves
  let settings;
  const x = fixture({ context: () => ({ origin: settings?.apiUrl, sid: 'old', compact: false, section: 'play' }) });
  settings = { apiUrl: 'http://10.0.0.5:8765' };
  x.ctl.remember({ tab: 'Sessions', playing: 'live', origin: 'http://10.0.0.5:8765' });
  assert.equal(x.ctl.checkpoint().guest.playing, 'live');
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
test('backend source stamp caches hot polls and reads only changed Python source, never credentials or config', async t => {
  const parent=path.resolve(os.tmpdir()),dir=await fs.mkdtemp(path.join(parent,'gbox-backend-stamp-'));
  t.after(()=>{assert.equal(path.dirname(path.resolve(dir)),parent);return fs.rm(dir,{recursive:true,force:true});});
  const a=path.join(dir,'worker.py'),b=path.join(dir,'server.py');
  await fs.writeFile(a,'worker1');await fs.writeFile(b,'server1');
  await fs.writeFile(path.join(dir,'api_token'),'PRIVATE');await fs.writeFile(path.join(dir,'settings.json'),'PRIVATE');
  let at=1000,walks=0;const reads=[];
  const stamp=V.sourceStamp(dir,{now:()=>at,io:{...fs,
    readdir:async(...args)=>{walks++;return fs.readdir(...args);},
    readFile:async file=>{reads.push(path.basename(file));return fs.readFile(file);}}});
  const original=await stamp.read();assert.deepEqual(reads,['server.py','worker.py']);
  for(let i=0;i<9;i++){at+=2000;assert.equal(await stamp.read(),original);}
  assert.equal(walks,1,'two-second polling must not traverse or rehash the backend');
  at+=2000;assert.equal(await stamp.read(),original);assert.equal(walks,2);assert.equal(reads.length,2);
  await fs.writeFile(a,'worker2');const changed=await stamp.read({fresh:true});assert.notEqual(changed,original);
  assert.deepEqual(reads,['server.py','worker.py','worker.py'],'unchanged modules remain cached');
  await fs.writeFile(a,'worker2');assert.equal(await stamp.read({fresh:true}),changed,'touching unchanged content is not an update');
  const c=path.join(dir,'added.py');await fs.writeFile(c,'new');const added=await stamp.read({fresh:true});
  assert.notEqual(added,changed);await fs.unlink(c);assert.equal(await stamp.read({fresh:true}),changed);
  assert.ok(reads.every(file=>file.endsWith('.py')));
});
test('backend-only changes request the normal guarded F5 handoff and an owned game retains the desktop', async t => {
  const parent=path.resolve(os.tmpdir()),dir=await fs.mkdtemp(path.join(parent,'gbox-backend-refresh-'));
  t.after(()=>{assert.equal(path.dirname(path.resolve(dir)),parent);return fs.rm(dir,{recursive:true,force:true});});
  const desktop=path.join(dir,'desktop'),web=path.join(dir,'web'),backend=path.join(dir,'gbox');
  for(const folder of [desktop,web,backend])await fs.mkdir(folder);
  const mainFile=path.join(desktop,'main.js'),module=path.join(backend,'desktop_local.py');
  await fs.writeFile(mainFile,'desktop');await fs.writeFile(path.join(web,'index.html'),'web');await fs.writeFile(module,'old backend');
  const versions=V.create({desktop,web,runtimeFiles:[mainFile],backendRoot:backend,apiUrl:()=> 'http://spark:8765',
    fetch:async()=>({ok:true,headers:new Map([['etag','same-server']])})});
  const initial=await versions.read();assert.equal(initial.restart,false);
  await fs.writeFile(module,'new backend');
  assert.equal((await versions.read()).restart,false,'hot poll uses its bounded source cache');
  const current=await versions.read({freshBackend:true});assert.equal(current.restart,true);assert.equal(current.renderer,initial.renderer);
  const main=await fs.readFile(path.join(__dirname,'../clients/desktop/main.js'),'utf8');
  const source=main.slice(main.indexOf('function assertClientSender('),main.indexOf('let clientVersions ='));
  let handler;const calls=[],wc={mainFrame:{},reloadIgnoringCache:()=>calls.push('renderer')};
  const context=vm.createContext({ipcMain:{handle:(_n,fn)=>{handler=fn;}},win:{webContents:wc},clientReloading:false,
    clientVersions:versions,clientActivation:{},worker:{pid:42},workerControl:{stop:()=>assert.fail('Owned game forbids worker stop')},
    clientHandoff:require('../clients/desktop/client-handoff.cjs'),inspectClientIdle:async()=> 'An owned local game is active.',
    process:{pid:12},mini:null,startWorker:async()=>calls.push('resume'),settings:()=>({autoStartWorker:true})});
  vm.runInContext(source,context);
  const result=await handler({sender:wc,senderFrame:wc.mainFrame},{v:1,sid:'watched-remote',compact:true});
  assert.equal(result.state,'pending');assert.match(result.reason,/owned local game/);assert.deepEqual(calls,['renderer']);
  assert.equal(context.worker.pid,42);assert.equal(context.clientHandoffBusy,false);
  assert.equal((await versions.read()).restart,true,'renderer refresh cannot clear the backend update');
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

test('missing saved session preserves window bounds and retains an automatic retry without selecting another game', async () => {
  const html = await fs.readFile(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const src = html.slice(html.indexOf('async function restoreClientView()'), html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  const calls = [], value = { sid: 'exact-old', compact: true, section: 'play' }, EMB = {};
  const ctx = vm.createContext({ EMB, clientViewNavigation: 0, clientViewRestoring: true,
    clientRefresh: { pending: () => value, retain() {}, remember() {}, done: () => calls.push('consumed') },
    document: { querySelector: selector => selector === '#wv' ? { gboxReady: Promise.resolve(), executeJavaScript: async () => ({ missing: [] }) } : { click() {} } }, loadPlay: async () => calls.push('load'),
    compactController: { enter: async v => { assert.equal(v.sid, 'exact-old'); throw Error('session unavailable'); } },
    gbox: { compactView: async v => calls.push(v.on) }, toast: text => calls.push(text) });
  vm.runInContext(src, ctx); await ctx.restoreClientView();
  assert.equal(EMB.sid, 'exact-old'); assert.equal(calls[0], 'load'); assert.ok(!calls.includes(false)); assert.ok(!calls.includes('consumed'));
  assert.ok(vm.runInContext('restoreClientView.retryAt > Date.now()',ctx));
});

test('restoration waits for the guest and restores two streams before entering native PiP without changing guest selection', async () => {
  const html=await fs.readFile(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const src=html.slice(html.indexOf('async function restoreClientView()'),html.indexOf('// Native desktop PiP has no browser gesture restriction.'));
  const calls=[], value={sid:'pip-B',compact:true,section:'play',guest:{tab:'Sessions',playing:'main-A',active:'main-A',pip:null}};
  let ready;const wv={gboxReady:new Promise(r=>ready=r),executeJavaScript:async script=>{assert.match(script,/main-A/);calls.push('guest');return {restored:['main-A'],missing:[]};}};
  let pending=value;
  const ctx=vm.createContext({EMB:{},clientViewNavigation:0,clientViewRestoring:true,
    clientRefresh:{pending:()=>pending,retain(){},remember(){},done:()=>{pending=null;calls.push('done');}},
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

async function restorationRig() {
 const html=await fs.readFile(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
 const src=html.slice(html.indexOf('let clientViewRestoring = true'),html.indexOf("document.addEventListener('gbox-stream-state'"));
 const timers=[],clicks=[],requests=[],modes=[],listeners={},messages=[];let at=1000,available=false,offline=false;
 let guest={tab:'Sessions',playing:'main-A',active:'pip-B',pip:'pip-B',revision:7,origin:'http://spark:8765'};
 const saved={sid:'native-old',compact:true,aspect:16/9,section:'play',origin:'http://spark:8765',guest};
 const storage=new Map(),EMB={};const interval=()=>timers[0]();
 const ctl=R.create({storage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
  context:()=>({origin:'http://spark:8765',sid:EMB.sid,compact:false,section:'play'}),now:()=>at,
  readState:async()=>guest,reload:async()=>{}});ctl.adopt(saved);
 let release;const wv={dataset:{ready:'true'},gboxReady:Promise.resolve(),executeJavaScript:async script=>{
  requests.push({kind:'guest',script});return {missing:available?[]:['native-old'],view:{...guest}};
 }};
 const context=vm.createContext({EMB,clientRefresh:ctl,
  Date:class extends Date{static now(){return at;}},
  document:{addEventListener:(type,fn)=>listeners[type]=fn,querySelector:selector=>selector==='#wv'?wv:{click:()=>clicks.push(selector)}},
  addEventListener:()=>{},setInterval:fn=>{timers.push(fn);return timers.length;},
  loadPlay:async()=>{if(offline)throw Error('server unavailable');},gboxState:async()=>({...guest}),
  compactController:{enter:async value=>{requests.push({kind:'compact',value});if(!available)throw Error('replacement link not registered');modes.push(true);}},
  gbox:{compactView:async value=>modes.push(value.on),clientViewSave:async()=>{}},toast:value=>messages.push(value),console:{warn:()=>{}}});
 vm.runInContext(src,context);
 return {context,ctl,timers,clicks,requests,modes,messages,wv,
  advance:value=>{at=value;},available:value=>{available=value;},offline:value=>{offline=value;},
  guest:value=>{guest={...guest,...value};},interval,
  navigate:()=>listeners.click({isTrusted:true,target:{closest:selector=>selector==='aside button[data-s]'?{}:null}}),
  waitGuest:()=>{wv.gboxReady=new Promise(resolve=>release=resolve);return()=>release();}};
}
const flushRestore=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};

test('actual desktop poll retries only every two seconds and restores the same saved stream pair once its link appears',async()=>{
 const r=await restorationRig();await r.context.restoreClientView();
 assert.equal(r.requests.filter(x=>x.kind==='compact').length,1);assert.deepEqual(r.modes,[]);
 r.advance(2999);r.interval();await flushRestore();assert.equal(r.requests.filter(x=>x.kind==='compact').length,1);
 r.advance(3000);r.interval();await flushRestore();assert.equal(r.requests.filter(x=>x.kind==='compact').length,2);
 r.available(true);r.advance(5000);r.interval();await flushRestore();
 const attempts=r.requests.filter(x=>x.kind==='compact');assert.equal(attempts.length,3);
 for(const attempt of attempts){assert.equal(attempt.value.sid,'native-old');assert.equal(attempt.value.guest.playing,'main-A');assert.equal(attempt.value.guest.pip,'pip-B');assert.equal(attempt.value.preserveGuest,true);}
 assert.ok(r.requests.filter(x=>x.kind==='guest').every(x=>x.script.includes('main-A')&&x.script.includes('pip-B')));
 assert.equal(r.ctl.pending(),null);assert.deepEqual(r.modes,[true]);assert.equal(r.messages.length,1);
 r.advance(7000);r.interval();await flushRestore();assert.equal(r.requests.filter(x=>x.kind==='compact').length,3);
});

test('trusted shell navigation and changed guest selection each cancel retry without restoring the saved view',async()=>{
 for(const shell of [true,false]){
  const r=await restorationRig();await r.context.restoreClientView();r.available(true);
  if(shell)r.navigate();else r.guest({tab:'Library',playing:'operator-new',active:'operator-new',pip:null,revision:8});
  r.advance(3000);r.interval();await flushRestore();
  assert.equal(r.requests.filter(x=>x.kind==='compact').length,1);assert.equal(r.ctl.pending(),null);assert.deepEqual(r.modes,[]);
 }
});

test('an initial restoration awaiting its guest is single-flight even when the retry clock advances',async()=>{
 const r=await restorationRig(),ready=r.waitGuest();const initial=r.context.restoreClientView();await flushRestore();
 r.advance(9000);for(let i=0;i<3;i++){r.interval();await r.context.restoreClientView();}
 await flushRestore();assert.equal(r.requests.length,0);ready();await initial;
 assert.equal(r.requests.filter(x=>x.kind==='compact').length,1);
});

test('server outage retries the exact saved view even before a guest frame is ready',async()=>{
 const r=await restorationRig();r.offline(true);r.wv.dataset.ready='false';
 await assert.rejects(r.context.restoreClientView(),/server unavailable/);assert.ok(r.ctl.pending());
 r.advance(3000);r.offline(false);r.available(true);r.interval();await flushRestore();
 assert.equal(r.requests.filter(x=>x.kind==='compact').length,1);assert.equal(r.requests.find(x=>x.kind==='compact').value.sid,'native-old');
 assert.equal(r.ctl.pending(),null);assert.deepEqual(r.modes,[true]);
});

test('trusted navigation during the actual compact resolver lookup cannot reopen or reset the game view',async()=>{
 const html=await fs.readFile(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
 const start=html.indexOf('resolve: async requested => {',html.indexOf('const compactController ='));
 const source=html.slice(start,html.indexOf('\n  windowMode:',start));
 let finish;const changes=[];
 const context=vm.createContext({clientViewNavigation:0,sessionById:()=>new Promise(resolve=>finish=resolve),
  S:{workerName:'windows',apiUrl:'http://spark:8765'},gbox:{token:async()=>'',api:async()=>assert.fail('No replacement lookup required')},
  document:{fullscreenElement:{},exitFullscreen:async()=>changes.push('exit fullscreen'),querySelector:()=>({click:()=>changes.push('navigate')})},
  sessionTitle:()=>{changes.push('title');return 'game';},closePops:()=>changes.push('close'),EYE:{on:false}});
 const resolve=vm.runInContext('({'+source+'}).resolve',context);
 const task=resolve({sid:'exact-old',preserveGuest:true,restoreNavigation:0});
 context.clientViewNavigation=1;
 finish({session_id:'exact-old',state:'running',detail:{worker_name:'spark'}});
 await assert.rejects(task,/superseded by your navigation/);
 assert.deepEqual(changes,[]);assert.equal(context.compactStreamUrl,undefined);assert.equal(context.compactSession,undefined);
});
