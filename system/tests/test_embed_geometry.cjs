const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const G = require('../clients/desktop/embed-geometry');

test('guest coordinates use measured viewport scale and clip to both view edges', () => {
  const host = { left:200, top:80, width:1000, height:800 };
  assert.deepEqual(G.guestRect({x:-20,y:100,w:1200,h:750}, host, {w:1000,h:800}),
    {x:200,y:180,w:1000,h:700});
  assert.deepEqual(G.guestRect({x:100,y:80,w:600,h:400}, host, {w:800,h:640}),
    {x:325,y:180,w:750,h:500});
  assert.equal(G.guestRect({x:1500,y:100,w:200,h:200}, host, {w:1000,h:800}), null);
});

test('popup cutouts and native windows share display DPI and Chromium zoom', () => {
  const r = G.nativePlacement({x:200,y:100,w:800,h:600},
    [{x:600,y:20,w:300,h:120},{x:1000,y:20,w:100,h:100}], 1.5, .8);
  assert.deepEqual(r, {op:'move',x:240,y:120,w:960,h:720,holes:[[720,24,240,144]]});
  for (const dpi of [1,1.25,1.5,2]) for (const zoom of [.8,1,1.25]) {
    const n = G.nativePlacement({x:20,y:30,w:800,h:600}, [{x:0,y:0,w:800,h:600}], dpi, zoom);
    assert.equal(n.holes[0][2], Math.round(800*dpi*zoom));
    assert.equal(n.holes[0][3], Math.round(600*dpi*zoom));
  }
});

test('fully covered or invalid rectangles never become a one-pixel native window', () => {
  assert.equal(G.intersect({x:800,y:10,w:100,h:100}, {x:0,y:0,w:600,h:800}), null);
  assert.equal(G.intersect({x:NaN,y:0,w:100,h:100}, {x:0,y:0,w:600,h:800}), null);
  assert.throws(() => G.nativePlacement({x:0,y:0,w:-1,h:100}), /Invalid native/);
  assert.throws(() => G.nativePlacement({x:0,y:0,w:100,h:100}, [], 0), /Invalid native/);
});

test('session layout refits after wrapping headers, resizing and changing views', () => {
  const source = fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8');
  const code = source.slice(source.indexOf('function fitSessionLayout()'), source.indexOf('async function show('));
  let top = 130, current, observer; const events = new Map();
  const header = {}, sessionHead = {}, layout = {style:{},getBoundingClientRect:()=>({top})};
  const context = vm.createContext({ innerHeight:800,
    document:{querySelector:s=>s==='header'?header:current,getElementById:()=>sessionHead},
    ResizeObserver:class {constructor(callback){this.callback=callback;this.observed=[];observer=this;}
      disconnect(){this.observed=[];} observe(node){this.observed.push(node);}},
    addEventListener:(name,callback)=>events.set(name,callback) });
  vm.runInContext(code,context); current=layout; context.watchSessionLayout();
  assert.equal(layout.style.height,'654px'); assert.deepEqual(observer.observed,[header,sessionHead]);
  top=190; observer.callback(); assert.equal(layout.style.height,'594px');
  context.innerHeight=600; events.get('resize')(); assert.equal(layout.style.height,'394px');
  current=null; context.watchSessionLayout(); assert.equal(layout.style.height,'394px');
});
