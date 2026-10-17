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

test('#1081: overlay windows over the game are shaped around the app\'s pop-ups (zoomed, clipped, exact cover)', () => {
  assert.deepEqual(G.shapeMinusHoles(100, 80, []), [{ x: 0, y: 0, width: 100, height: 80 }]);
  const shape = G.shapeMinusHoles(200, 100, [{ x: 40, y: 20, w: 40, h: 20 }, { x: 120, y: 60, w: 40, h: 40 }], 1.5);
  const area = shape.reduce((a, s) => a + s.width * s.height, 0);
  assert.equal(area, 200 * 100 - 60 * 30 - 20 * 10, 'everything but the zoomed holes (one clipped at the corner)');
  const inside = (x, y) => shape.some(s => x >= s.x && x < s.x + s.width && y >= s.y && y < s.y + s.height);
  assert.equal(inside(70, 40), false, 'the menu shows through');
  assert.equal(inside(10, 10), true); assert.equal(inside(199, 99), false);
  for (const a of shape) for (const b of shape) if (a !== b)       // no double-covered pixels
    assert.ok(a.x >= b.x + b.width || b.x >= a.x + a.width || a.y >= b.y + b.height || b.y >= a.y + a.height);
  const overlay = fs.readFileSync(require.resolve('../clients/desktop/overlay.js'), 'utf8');
  assert.match(overlay, /ov\.setShape\(shapeMinusHoles\(w, h, st\.holes, z\)\)/, 'the overlay swap uses the same shape');
});

// #1081: which DOM changes must re-cut the docked native game window (fake DOM: each node lists the selectors it matches)
function fakeDom() {
  const make = (id, sels = [], parent = null) => {
    const n = { nodeType: 1, id, sels: new Set(sels), parentElement: parent, kids: [],
      matches(sel) { return sel.split(',').some(s => this.sels.has(s.trim())); },
      closest(sel) { for (let x = this; x; x = x.parentElement) if (x.matches(sel)) return x; return null; },
      querySelector(sel) { for (const k of this.kids) { if (k.matches(sel)) return k; const d = k.querySelector(sel); if (d) return d; } return null; } };
    if (parent) parent.kids.push(n);
    return n;
  };
  return { make, body: make('body') };
}
const attr = target => ({ type: 'attributes', target });
const list = (target, added = [], removed = []) => ({ type: 'childList', target, addedNodes: added, removedNodes: removed });

test('embedded task panels cut native input out as they open, resize and close', () => {
  const source = fs.readFileSync(require.resolve('../clients/desktop/index.html'), 'utf8');
  const holes = source.match(/const EMB_GUEST_MENUS = "([^"]+)";/)[1];
  const { make, body } = fakeDom();
  const opts = { body, holes, bodyChildren: false };
  for (const id of ['pwcon', 'pwmenu', 'pwreport']) {
    const panel = make(id, ['#' + id], body);
    assert.equal(panel.matches(holes), true, id + ' must receive clicks above the native emulator');
    assert.equal(G.popupMutation([list(body, [panel])], opts), true);
    assert.equal(G.popupMutation([attr(make('button', [], panel))], opts), true);
    assert.equal(G.popupMutation([list(body, [], [panel])], opts), true);
  }
});
test('pop-up mutations: body pop-ups, cut-out panels opening and closing, never the sync\'s own game bar', () => {
  const { make, body } = fakeDom();
  const opts = { body, holes: '#chatpanel.on, #pipmenu, #chatbar .sugg', ignore: '#piph, .piprz' };
  const menu = make('recmenu', [], body), chat = make('chatpanel', [], body), bar = make('chatbar', [], body);
  const deep = make('msg', [], make('log', [], make('main', [], body)));
  const piph = make('piph', ['#piph'], body), grip = make('', ['.piprz'], body);
  assert.equal(G.popupMutation([list(body, [menu])], opts), true, 'a floating menu appended to body');
  assert.equal(G.popupMutation([list(body, [], [menu])], opts), true, 'and removed again');
  assert.equal(G.popupMutation([attr(menu)], opts), true, 'a body pop-up shown or moved by style');
  assert.equal(G.popupMutation([attr(chat)], opts), true, 'chat panel closing (its .on class gone) still counts by id');
  assert.equal(G.popupMutation([list(bar, [make('', ['#chatbar .sugg'])])], opts), true, 'a suggestion list added inside the chat bar');
  assert.equal(G.popupMutation([attr(deep), list(deep.parentElement, [make('x')])], opts), false, 'page content updates elsewhere do not resync');
  assert.equal(G.popupMutation([attr(piph), attr(grip)], opts), false, 'the game bar and grips placed by the sync itself cannot loop');
  assert.equal(G.popupMutation([list(body, [{ nodeType: 3 }])], opts), false, 'text nodes are ignored');
});
test('embedded-view menus: only the listed menus count, so a busy session page does not resync the game', () => {
  const { make, body } = fakeDom();
  const page = make('page', [], body), gmenu = make('gmenu', [], page), role = make('', ['[role=menu]']), stats = make('stats', [], page);
  const opts = { body, holes: '#gmenu, [role=menu]', bodyChildren: false };
  assert.equal(G.popupMutation([attr(page)], opts), false);
  assert.equal(G.popupMutation([attr(stats)], opts), false);
  assert.equal(G.popupMutation([attr(gmenu)], opts), true);
  assert.equal(G.popupMutation([list(page, [role])], opts), true);
  const src = String(G.popupMutation);                          // injected into the embedded view as source text
  assert.ok(!/GBoxEmbedGeometry|require\(/.test(src));
  const again = new Function('return ' + src)();
  assert.equal(again([attr(gmenu)], opts), true);
});
