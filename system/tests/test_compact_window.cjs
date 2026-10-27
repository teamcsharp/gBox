const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { create, fitBounds, wideBounds } = require('../clients/desktop/compact-window.cjs');

function fixture(options = {}) {
  class Window extends EventEmitter {
    constructor() { super(); this.bounds = {x:70,y:80,width:1500,height:950}; this.normal = {...this.bounds}; this.top = false;
      this.maximized = false; this.fullscreen = false; this.minimum = [320,240]; this.maximum = [2000,1400]; this.aspect = 0; this.overlay = 36; }
    isDestroyed() { return false; } getBounds() { return {...this.bounds}; } getNormalBounds() { return {...this.normal}; }
    setBounds(value) { this.bounds = {...value}; } isMaximized() { return this.maximized; } maximize() { this.maximized = true; }
    unmaximize() { this.maximized = false; } isFullScreen() { return this.fullscreen; } setFullScreen(value) { this.fullscreen = value; }
    isAlwaysOnTop() { return this.top; } setAlwaysOnTop(value) { this.top = value; }
    getMinimumSize() { return [...this.minimum]; } setMinimumSize(...value) { this.minimum = value; }
    getMaximumSize() { return [...this.maximum]; } setMaximumSize(...value) { this.maximum = value; }
    setAspectRatio(value) { this.aspect = value; } setTitleBarOverlay(value) { this.overlay = value; }
  }
  const win = new Window(), events = [], chrome = [], timers = [];
  const ctl = create({ getWin: () => win, screen: {getDisplayMatching: () => ({workArea:{x:0,y:0,width:1920,height:1040}})},
    nativeChrome: async on => { chrome.push(on); return options.chrome ? options.chrome(on) : {ok:true,aspect:4/3}; }, emit: value => events.push(value),
    schedule: (fn, ms) => { const timer = { fn, ms, live: true }; timers.push(timer); return timer; }, cancel: timer => { if (timer) timer.live = false; } });
  // run the retry that is due (the last one scheduled and not cancelled)
  const due = async () => { const timer = timers.filter(t => t.live).at(-1); if (!timer) return null; timer.live = false; timer.fn(); await new Promise(r => setTimeout(r, 0)); return timer.ms; };
  return {win,ctl,events,chrome,timers,due};
}

test('compact mode resizes the same live window and restores all prior desktop state', async () => {
  const {win,ctl,events,chrome} = fixture(); win.top = true; win.maximized = true; win.fullscreen = true;
  const before = win.getBounds();
  assert.deepEqual(await ctl.update({on:true,aspect:16/9,width:640}), {on:true,aspect:16/9});
  assert.equal(win.bounds.width,640); assert.equal(win.bounds.height,360); assert.equal(win.aspect,16/9);
  assert.equal(win.fullscreen,false); assert.equal(win.maximized,false); assert.equal(win.top,true);
  assert.equal(win.overlay.height,0);
  await ctl.restore();
  assert.deepEqual(win.bounds,before); assert.deepEqual(win.minimum,[320,240]); assert.deepEqual(win.maximum,[2000,1400]);
  assert.equal(win.aspect,0); assert.equal(win.fullscreen,true); assert.equal(win.maximized,true); assert.equal(win.top,true);
  assert.equal(win.overlay.height,36); assert.deepEqual(chrome,[true,false]);
  assert.deepEqual(events.map(event=>event.on),[true,false]);
});

test('source changes retain window bounds; explicit width changes preserve the chosen window ratio', async () => {
  const {win,ctl,chrome} = fixture(), original = win.getBounds();
  await ctl.update({on:true}); assert.equal(win.aspect,16/9);
  assert.equal(ctl.state().aspect,4/3,'native picture ratio remains independent of the widescreen window');
  win.bounds.x = 400; win.bounds.y = 300;
  await ctl.update({on:true}); assert.equal(win.bounds.x,400);
  const bounds=win.getBounds();
  for(const aspect of [16/9,4/3,2,16/9]){
    await ctl.update({on:true,aspect});
    assert.deepEqual(win.getBounds(),bounds,'title/frame aspect must never resize or move PiP');
    assert.equal(win.aspect,16/9,'native resize constraint belongs to the window');
    assert.equal(ctl.state().aspect,aspect,'the picture can still letterbox correctly');
  }
  await ctl.update({on:true,aspect:2,width:800}); assert.equal(win.bounds.height,450);
  await ctl.restore(); assert.deepEqual(win.bounds,original); assert.deepEqual(chrome,[true,false]);
  assert.equal(win.top,false);
});

test('a new main process restores both full-window origin and the moved compact bounds', async () => {
  const first = fixture(), origin = first.win.getBounds();
  first.win.maximized = true;
  await first.ctl.update({on:true,aspect:16/9,width:640});
  first.win.bounds.x = 212; first.win.bounds.y = 150;
  const saved = first.ctl.handoff();
  assert.deepEqual(saved.window.bounds,origin); assert.equal(saved.window.maximized,true);
  const next = fixture(); next.win.setBounds(saved.window.bounds); next.win.maximized = saved.window.maximized;
  next.ctl.seedBounds(saved.compactBounds); await next.ctl.update({on:true,aspect:4/3});
  assert.deepEqual(next.win.getBounds(),saved.compactBounds);
  await next.ctl.restore(); assert.deepEqual(next.win.getBounds(),origin); assert.equal(next.win.maximized,true);
});

test('client restart opens at retained PiP size and keeps its separate full-window restore point',async()=>{
  const {win,ctl}=fixture(),full=win.getBounds(),bounds={x:200,y:90,width:1058,height:595};
  win.setBounds(bounds);ctl.seedBounds(bounds,{bounds:full,maximized:false,fullscreen:false,top:false});
  await ctl.update({on:true,aspect:4/3});assert.deepEqual(win.getBounds(),bounds);
  await ctl.update({on:true,aspect:16/9});assert.deepEqual(win.getBounds(),bounds);
  await ctl.restore();assert.deepEqual(win.getBounds(),full);
});

test('older 4:3 windows become widescreen once, retaining height and the right edge',async()=>{
  const old={x:800,y:90,width:480,height:360},wide={x:640,y:90,width:640,height:360};
  assert.deepEqual(wideBounds(old),wide);assert.deepEqual(old,{x:800,y:90,width:480,height:360});
  assert.deepEqual(wideBounds(wide),wide);
  const {win,ctl}=fixture();ctl.seedBounds(old);await ctl.update({on:true,aspect:4/3});
  assert.deepEqual(win.getBounds(),wide);
  for(const aspect of [16/9,4/3,2]){await ctl.update({on:true,aspect});assert.deepEqual(win.getBounds(),wide);}
});

test('a failed native caption change rolls back bounds, fullscreen and controls without entering compact mode', async () => {
  const {win,ctl,events,chrome} = fixture({chrome: on => on ? {ok:false,error:'style rejected'} : {ok:true}});
  win.maximized = true; win.fullscreen = true; const before = win.getBounds();
  await assert.rejects(ctl.update({on:true}),/style rejected/);
  assert.deepEqual(ctl.state(),{on:false,aspect:4/3}); assert.deepEqual(win.bounds,before);
  assert.equal(win.maximized,true); assert.equal(win.fullscreen,true); assert.equal(win.overlay.height,36);
  assert.deepEqual(events,[]); assert.deepEqual(chrome,[true,false]);
});

test('a failed restoration stays recoverable and rapid requests serialize around the native helper', async () => {
  let unblock, fail = true;
  const {ctl,chrome} = fixture({chrome: async on => {
    if (on) await new Promise(resolve => { unblock=resolve; });
    else if (fail) { fail=false; return {ok:false,error:'busy'}; }
    return {ok:true};
  }});
  const entering = ctl.update({on:true,aspect:4/3}), leaving = ctl.restore();
  await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(chrome,[true]); unblock();
  await entering; await assert.rejects(leaving,/busy/); assert.equal(ctl.state().on,true);
  await ctl.restore(); assert.equal(ctl.state().on,false); assert.deepEqual(chrome,[true,false,false]);
});

// operator 2026-10-27: F5 ended inert on "Error invoking remote method 'compact:view': Error: Game-window helper timed out;
// the current dock was preserved" - the helper had not started yet, and the PiP was refused for it.
test('a helper that does not answer never keeps the game out of the PiP; its controls stay visible until a retry hides them', async () => {
  let answer = {ok:false,unavailable:true,error:'Game-window helper timed out; the current dock was preserved'};
  const {win,ctl,events,chrome,timers,due} = fixture({chrome: on => on ? answer : {ok:true}});
  const before = win.getBounds();
  assert.deepEqual(await ctl.update({on:true,aspect:16/9,width:640}), {on:true,aspect:16/9});
  assert.equal(win.bounds.width,640); assert.equal(win.top,true); assert.deepEqual(events.map(e=>e.on),[true]);
  assert.equal(win.overlay,36,'controls the helper did not remove keep their overlay: never invisible but clickable');
  assert.equal(timers.length,1); assert.equal(timers[0].ms,2000);
  assert.equal(await due(),2000); assert.deepEqual(chrome,[true,true]);
  assert.equal(timers.at(-1).ms,4000,'a helper still silent is asked again, backing off'); assert.equal(win.overlay,36);
  answer = {ok:true,bits:0xcb0000};
  assert.equal(await due(),4000); assert.deepEqual(chrome,[true,true,true]);
  assert.equal(win.overlay.height,0,'hidden once the helper answers'); assert.equal(timers.filter(t=>t.live).length,0);
  await ctl.restore(); assert.deepEqual(win.bounds,before); assert.equal(win.overlay.height,36); assert.equal(ctl.state().on,false);
});

test('controls the helper never hid come back without it; once hidden, a silent helper keeps the PiP for another try', async () => {
  const silent = {ok:false,unavailable:true,error:'Game-window helper timed out; the current dock was preserved'};
  const never = fixture({chrome: () => silent}), full = never.win.getBounds();
  await never.ctl.update({on:true,aspect:4/3});
  await never.ctl.restore();
  assert.equal(never.ctl.state().on,false); assert.deepEqual(never.win.bounds,full); assert.deepEqual(never.chrome,[true,false]);
  assert.equal(never.timers.filter(t=>t.live).length,0,'no retry after the PiP closed');
  const hid = fixture({chrome: on => on ? {ok:true,bits:1} : silent});
  await hid.ctl.update({on:true});
  await assert.rejects(hid.ctl.restore(),/helper timed out/); assert.equal(hid.ctl.state().on,true);
  const slow = fixture({chrome: on => on ? silent : {ok:true}});            // retries back off to their ceiling
  await slow.ctl.update({on:true});
  const waits = []; for (let i=0;i<7;i++) waits.push(await slow.due());
  assert.deepEqual(waits,[2000,4000,8000,16000,30000,30000,30000]);
});

test('a helper started while the PiP is open is told about it again; the hidden controls stay hidden', async () => {
  const {win,ctl,chrome} = fixture({chrome: on => on ? {ok:true,bits:1} : {ok:true}});
  await ctl.update({on:true}); assert.equal(win.overlay.height,0);
  await ctl.rechrome(); assert.deepEqual(chrome,[true,true]); assert.equal(win.overlay.height,0); assert.equal(ctl.state().on,true);
  await ctl.restore(); await ctl.rechrome(); assert.deepEqual(chrome,[true,true,false],'a closed PiP is not hidden again');
});

test('compact geometry fits landscape and portrait sources within the current monitor work area', () => {
  const area = {x:-1600,y:20,width:1600,height:900};
  for (const aspect of [4/3,16/9,.5]) {
    const bounds = fitBounds({x:7000,y:7000,width:3000},aspect,area);
    assert.ok(bounds.x>=area.x && bounds.y>=area.y);
    assert.ok(bounds.x+bounds.width<=area.x+area.width && bounds.y+bounds.height<=area.y+area.height);
    assert.ok(Math.abs(bounds.width/bounds.height-aspect)<.003);
  }
});
