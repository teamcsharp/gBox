const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { create, fitBounds } = require('../clients/desktop/compact-window.cjs');

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
  const win = new Window(), events = [], chrome = [];
  const ctl = create({ getWin: () => win, screen: {getDisplayMatching: () => ({workArea:{x:0,y:0,width:1920,height:1040}})},
    nativeChrome: async on => { chrome.push(on); return options.chrome ? options.chrome(on) : {ok:true,aspect:4/3}; }, emit: value => events.push(value) });
  return {win,ctl,events,chrome};
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

test('repeated activation updates aspect or size without overwriting the original restore point', async () => {
  const {win,ctl,chrome} = fixture(), original = win.getBounds();
  await ctl.update({on:true}); assert.equal(win.aspect,4/3);
  win.bounds.x = 400; win.bounds.y = 300;
  await ctl.update({on:true}); assert.equal(win.bounds.x,400);
  await ctl.update({on:true,aspect:2,width:800}); assert.equal(win.bounds.height,400);
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
  next.ctl.seedBounds(saved.compactBounds); await next.ctl.update({on:true,aspect:16/9});
  assert.deepEqual(next.win.getBounds(),saved.compactBounds);
  await next.ctl.restore(); assert.deepEqual(next.win.getBounds(),origin); assert.equal(next.win.maximized,true);
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

test('compact geometry fits landscape and portrait sources within the current monitor work area', () => {
  const area = {x:-1600,y:20,width:1600,height:900};
  for (const aspect of [4/3,16/9,.5]) {
    const bounds = fitBounds({x:7000,y:7000,width:3000},aspect,area);
    assert.ok(bounds.x>=area.x && bounds.y>=area.y);
    assert.ok(bounds.x+bounds.width<=area.x+area.width && bounds.y+bounds.height<=area.y+area.height);
    assert.ok(Math.abs(bounds.width/bounds.height-aspect)<.003);
  }
});
