// Run with node system/tests/test_pad_map.cjs. Controller maps (2026-10-20): "I right click a button in the controller
// glyph ... map that to a function on the controller ... the analog stick by default to the left stick and the C stick
// to the right stick" (N64). Pure binding logic of clients/web/viz/pad-map.js, then the web client's real controller
// loop forwarding an N64 game's pad through it.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const P = require('../clients/web/viz/pad-map.js');

const pad = (pressed = [], axes = [0, 0, 0, 0]) => ({ id: 'Xbox One Controller', index: 0, mapping: 'standard', connected: true, axes,
  buttons: Array.from({ length: 17 }, (_, i) => ({ pressed: pressed.includes(i), value: pressed.includes(i) ? 1 : 0 })) });
const XA = 0, XB = 1, XX = 2, XY = 3, LB = 4, RB = 5, LT = 6, RT = 7, MENU = 9;
const sorted = s => [...s].sort();

// ---- consoles and their default layout ----
{
  for (const p of ['n64', 'N64', 'n64dd', 'Nintendo 64', 'Nintendo - Nintendo 64']) assert.equal(P.family(p), 'n64', p);
  const n64 = P.profile('n64');
  assert.equal(n64.sticks, true);
  assert.equal(P.family('snes'), 'snes');
  assert.equal(P.profile('snes').generic, true);
  // the default N64 map is empty: every control drives the input named like it
  const ctl = out => P.controlsFor(n64, {}, out);
  const fn = id => n64.functions.find(f => f.id === id).out;
  assert.deepEqual(ctl(fn('cup')), ['rup'], 'C-up = right stick up');
  assert.deepEqual(['cdown', 'cleft', 'cright'].map(id => ctl(fn(id))), [['rdown'], ['rleft'], ['rright']], 'C buttons = right stick');
  assert.deepEqual(['sup', 'sdown', 'sleft', 'sright'].map(id => ctl(fn(id))), [['lup'], ['ldown'], ['lleft'], ['lright']], 'N64 stick = left stick');
  assert.deepEqual([ctl(fn('a')), ctl(fn('b')), ctl(fn('z')), ctl(fn('start'))], [['b'], ['y'], ['l2'], ['start']], 'A = Xbox A, B = X, Z = LT');
  assert.deepEqual(ctl(fn('cmode')), ['r2'], 'RT stays the cores\' C-button mode');
}

// ---- reading the pad: what the game receives ----
{
  const n64 = P.profile('n64');
  let r = P.read(pad([], [0, 0, 0, -0.9]), null, n64, {});
  assert.deepEqual(sorted(r.keys), ['rup'], 'right stick up = C-up, never the d-pad');
  r = P.read(pad([], [-0.8, 0.3, 0, 0]), null, n64, {});
  assert.deepEqual(sorted(r.keys), ['lleft'], 'left stick = the N64 stick (analog), not the d-pad');
  assert.ok(Math.abs(r.stick.x + 0.8) < 1e-9 && Math.abs(r.stick.y - 0.3) < 1e-9, 'the stick keeps its analog strength');
  r = P.read(pad([XA, LT, MENU]), null, n64, {});
  assert.deepEqual(sorted(r.keys), ['b', 'l2', 'start'], 'Xbox A = N64 A (RetroPad B), LT = Z, Menu = Start');
  // other consoles keep the legacy forwarding: buttons, and the left stick as the d-pad (the Controllers switch)
  const snes = P.profile('snes');
  r = P.read(pad([XA], [-0.9, 0, 0, -0.9]), null, snes, {}, { stickAsDpad: true });
  assert.deepEqual(sorted(r.keys), ['b', 'left'], 'SNES: no stick inputs reach the game, left stick = d-pad');
  assert.ok(r.held.has('rup') && r.held.has('lleft'), 'the picture still shows the sticks');
  r = P.read(pad([], [-0.9, 0, 0, 0]), null, snes, {}, { stickAsDpad: false });
  assert.deepEqual(sorted(r.keys), [], 'left stick as d-pad off');
}

// ---- binding: "Map N64 C-up to RB" ----
{
  const n64 = P.profile('n64');
  // a stick direction never moves alone (RetroArch would silence its opposite in a native window): the right stick
  // keeps C-up, RB adds it, and R - RB's old job - is reported as having no control
  let b = P.bind(n64, {}, 'rup', 'r');
  assert.deepEqual(b.map, { r: 'rup' });
  assert.deepEqual(b.moved, []);
  assert.deepEqual(b.lost, ['r'], 'R has no control now (the dialog says so)');
  assert.deepEqual(P.unbound(n64, b.map).map(f => f.label), ['R']);
  assert.deepEqual(P.splitAxes(n64, b.map), [], 'no half stick axis: works the same in a native RetroArch window');
  assert.deepEqual(sorted(P.read(pad([RB]), null, n64, b.map).keys), ['rup'], 'RB presses C-up');
  assert.deepEqual(sorted(P.read(pad([], [0, 0, 0, -1]), null, n64, b.map).keys), ['rup'], 'the right stick still does too');
  assert.deepEqual(P.bind(n64, b.map, 'rup', 'r').map, b.map, 'binding what is already bound changes nothing');
  assert.deepEqual(P.reset(n64, b.map, 'rup').map, {}, 'Reset C-up');
  b = P.bind(n64, b.map, 'r', 'select');                                 // then R onto View
  assert.deepEqual([b.map, b.lost], [{ r: 'rup', select: 'r' }, []]);
  // buttons swap: N64 A onto Xbox B, Xbox A takes Xbox B's old job (C-right while C mode is held)
  b = P.bind(n64, {}, 'b', 'a');
  assert.deepEqual([b.map, b.moved, b.lost], [{ a: 'b', b: 'a' }, [{ source: 'b', output: 'a' }], []]);
  assert.deepEqual(P.reset(n64, b.map, 'b').map, {}, 'Reset A undoes the swap');
  // a control with no N64 function of its own (Xbox Y = RetroPad X: C-up only while C mode is held)
  b = P.bind(n64, {}, 'rup', 'x');
  assert.deepEqual([b.map, b.lost], [{ x: 'rup' }, []], 'its C-mode extra is not a console function: nothing reported');
  assert.equal(P.describe(n64, 'x'), 'C-up (C mode)');
  assert.equal(P.describe(n64, 'select'), '—');
  assert.equal(P.describe(n64, 'l3', { l3: 'lstick' }), '—', 'the picture\'s part names never relabel an N64 input (no stick click)');
  assert.equal(P.describe(P.profile('ps1'), 'x', { x: 'triangle' }), 'Triangle', 'other consoles: the picture\'s button names');
  // a function moved ONTO one stick direction does split its axis: the dialog warns for a RetroArch window
  b = P.bind(n64, {}, 'r', 'rup');
  assert.deepEqual(b.map, { rup: 'r', r: 'rup' });
  assert.deepEqual(P.splitAxes(n64, b.map), ['rdown'], 'right stick down would do nothing in a native window');
  assert.deepEqual(P.splitAxes(n64, { rup: 'r', rdown: 'l' }), [], 'both directions moved: the axis is whole');
  assert.deepEqual(P.splitAxes(P.profile('snes'), { b: 'a' }), []);
  assert.deepEqual(P.bind(n64, b.map, 'zz', 'r').map, P.clean(n64, b.map), 'unknown inputs are refused');
}

// ---- whole groups: "N64 stick -> right stick" swaps the two sticks; Reset all is an empty map ----
{
  const n64 = P.profile('n64'), stick = n64.groups.find(g => g.id === 'stick');
  const outs = stick.fns.map(id => n64.functions.find(f => f.id === id).out);
  const right = P.PHYS.find(p => p.id === 'rstick');
  const g = P.bindGroup(n64, {}, outs, right.srcs);
  assert.deepEqual(g.map, { rup: 'lup', rdown: 'ldown', rleft: 'lleft', rright: 'lright', lup: 'rup', ldown: 'rdown', lleft: 'rleft', lright: 'rright' });
  assert.equal(P.physOf(n64, g.map, stick).id, 'rstick');
  assert.equal(P.physOf(n64, g.map, n64.groups.find(x => x.id === 'c')).id, 'lstick', 'the C buttons moved to the left stick');
  assert.deepEqual([g.lost, P.splitAxes(n64, g.map)], [[], []], 'whole sticks swap: nothing lost, no half axis');
  const dpad = P.bindGroup(n64, {}, n64.groups.find(x => x.id === 'c').fns.map(id => n64.functions.find(f => f.id === id).out), P.PHYS.find(p => p.id === 'dpad').srcs);
  assert.deepEqual(dpad.map, { up: 'rup', down: 'rdown', left: 'rleft', right: 'rright', rup: 'up', rdown: 'down', rleft: 'left', rright: 'right' },
    'C buttons on the d-pad: the right stick takes the N64 d-pad');
  const r = P.read(pad([], [0, 0, 0.2, -0.7]), null, n64, g.map);
  assert.deepEqual(sorted(r.keys), ['lup']);
  assert.ok(Math.abs(r.stick.y + 0.7) < 1e-9 && Math.abs(r.stick.x - 0.2) < 1e-9, 'the N64 stick follows the right stick, analog');
  assert.deepEqual(P.bindGroup(n64, g.map, outs, P.PHYS.find(p => p.id === 'lstick').srcs).map, {}, 'back to the left stick');
  assert.deepEqual(P.summary(n64, { r: 'rup', rup: 'r' }).map(x => `${x.name} → ${x.does}`), ['RB → C-up', 'Right stick up → R']);
}

// ---- other consoles: buttons only ----
{
  const snes = P.profile('snes');
  assert.deepEqual(P.clean(snes, { b: 'a', a: 'b', rup: 'b', x: 'lup', y: 'nope' }), { b: 'a', a: 'b' }, 'sticks are not part of a SNES map');
  const r = P.read(pad([XA], [0, 0, 0, 0]), null, snes, { b: 'a', a: 'b' });
  assert.deepEqual(sorted(r.keys), ['a'], 'Xbox A presses SNES A after the swap');
  assert.ok(P.target(snes, { keys: ['l3', 'lup'], stick: true }).error, 'stick mapping is N64-only for now');
  assert.deepEqual(P.target(snes, { keys: ['a'], label: 'A' }).fn, { id: 'a', label: 'A', out: 'a' });
}

// ---- "Press a control to bind" ----
{
  const n64 = P.profile('n64'), st = { armed: false };
  assert.equal(P.captureStep(st, new Set(['b']), n64), null, 'a control already held when listening starts is ignored');
  assert.equal(st.armed, false);
  assert.equal(P.captureStep(st, new Set(), n64), null);
  assert.equal(st.armed, true, 'armed once everything is let go');
  assert.equal(P.captureStep(st, P.sources(pad([], [0, 0, 0, -0.95]), { threshold: 0.6 }), n64), 'rup', 'axes bind as well as buttons');
  const st2 = { armed: true };
  assert.equal(P.captureStep(st2, P.sources(pad([], [0, 0, 0.55, 0]), { threshold: 0.6 }), n64), null, 'a stick resting a bit off centre is not a press');
  assert.equal(P.captureStep(st2, P.sources(pad([RT])), n64), 'r2', 'triggers bind');
  assert.equal(P.captureStep({ armed: true }, new Set(['rup']), P.profile('snes')), null, 'a SNES map has no stick controls');
}

// ---- the controller picture's parts are the console's functions ----
{
  const glyph = fs.readFileSync(path.join(__dirname, '../clients/web/padglyph.js'), 'utf8');
  const n64Def = glyph.match(/\n {2}n64: \{ m: (\{[^}]*\})/)[1];
  const m = Function(`return (${n64Def})`)();
  const n64 = P.profile('n64'), part = k => ({ keys: m[k].split(' ') });
  assert.equal(P.target(n64, part('cup')).fn.id, 'cup', 'right-click C-up maps C-up');
  assert.equal(m.cup.split(' ')[0], 'rup', 'a click on C-up deflects the right stick (what the cores read as C-up)');
  assert.deepEqual(['cright', 'cdown', 'cleft'].map(k => P.target(n64, part(k)).fn.out), ['rright', 'rdown', 'rleft']);
  assert.equal(P.target(n64, part('a')).fn.label, 'A');
  assert.equal(P.target(n64, part('z')).fn.label, 'Z');
  assert.equal(P.target(n64, { keys: 'l3 lup ldown lleft lright'.split(' '), stick: true }).group.id, 'stick', 'right-click the stick maps the stick');
  assert.ok(!/cup: "x |cright: "a /.test(glyph), 'Xbox Y / B alone no longer light C-up / C-right (they only do with RT held)');
}

// ---- the web client's real controller loop, an N64 game streamed from the Spark ----
async function forwarding() {
  const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const source = html.slice(html.indexOf('const RETRO ='), html.indexOf('async function snap(sid)'));
  assert.match(html, /<script src="\/viz\/pad-map\.js"><\/script>/, 'the page loads the map module');
  assert.match(html, /closest\("[^"]*#padglyph[^"]*"\)\) return;\s+\/\/ game and editor surfaces/, 'right-click on the picture never opens the report menu');
  assert.match(html, /pg\.onpointerdown = e => \{ if \(e\.button !== 0\) return;/, 'a right-click presses nothing in the game');
  assert.match(html, /pg\.oncontextmenu = e => padMapMenu\(e, sid\)/, 'native and streamed games both get the dialog');
  const storage = new Map(), sent = [];
  const ctx = vm.createContext({ navigator: { getGamepads: () => ctx.devices }, devices: [], console,
    localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) },
    api: async (url, body) => { sent.push({ url, ...body }); return { map: body && body.map }; },
    requestAnimationFrame() {}, addEventListener() {}, setInterval() {}, $: () => null, cur: 'Sessions', show() {},
    esc: v => String(v), GBoxPadMap: P });
  ctx.window = ctx;
  vm.runInContext(source, ctx);
  const run = code => vm.runInContext(code, ctx);
  const SID = 'spark-n64';
  run(`active = ${JSON.stringify({ sid: SID, title: 'Super Mario 64', local: false, platform: 'n64', adapter: 'retroarch' })}`);
  const flush = () => run('Promise.all([...padQueues.values()])');
  const events = () => sent.filter(s => s.events).flatMap(s => s.events.map(e => `${e.key}:${e.down ? 'down' : 'up'}`));
  const xi = (more = {}) => run(`window.gboxNativePad(${JSON.stringify([{ slot: 0, buttons: 0, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0, ...more }])})`);
  xi({ ry: 30000 }); await flush();                                       // XInput: +y is up
  assert.deepEqual(events(), ['rup:down'], 'right stick up reaches the game as the right analog (C-up)');
  xi({ lx: -30000 }); await flush();
  assert.deepEqual(events().slice(1).sort(), ['lleft:down', 'rup:up'], 'left stick = the N64 stick, not the d-pad');
  xi(); await flush();
  // the operator maps C-up to RB in the dialog (saved through the server, cached here)
  const saved = await run(`savePadMap('n64', { r: 'rup', rup: 'r' })`);
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), { r: 'rup', rup: 'r' });
  assert.equal(sent.at(-1).url, '/api/controller-maps/n64');
  assert.deepEqual(JSON.parse(storage.get('gbox_pad_maps')).n64, { r: 'rup', rup: 'r' }, 'cached on this computer');
  sent.length = 0;
  xi({ buttons: 0x0200 }); await flush();                                  // XInput RB
  assert.deepEqual(events(), ['rup:down'], 'RB now presses C-up');
  xi(); await flush();
  // listening for a control in the dialog: what was held is released, nothing new reaches the game
  sent.length = 0;
  xi({ buttons: 0x1000 }); await flush();
  run('padCapture = true'); xi({ buttons: 0x1000 | 0x2000 }); await flush();
  assert.deepEqual(events(), ['b:down', 'b:up'], 'capture releases and sends nothing else');
  run('padCapture = false'); xi(); await flush();
  // a Dreamcast game is unchanged: no map, left stick as the d-pad, the right stick is not forwarded
  sent.length = 0;
  run(`active = ${JSON.stringify({ sid: 'spark-doa2', title: 'Dead or Alive 2', local: false, platform: 'dreamcast' })}`);
  xi({ lx: -30000, ry: 30000 }); await flush();
  assert.deepEqual(events(), ['left:down'], 'other consoles forward exactly as before');
  xi(); await flush();
  // a native window on this PC forwards nothing: RetroArch reads the pad itself (through the remap file)
  sent.length = 0;
  run(`active = ${JSON.stringify({ sid: 'JAY-n64', title: 'Super Mario 64', local: true, platform: 'n64', adapter: 'retroarch' })}`);
  xi({ ry: 30000 }); await flush();
  assert.deepEqual(events(), [], 'native game: no forwarding');
  // the controller picture shows the mapped pad (desktop XInput reading)
  run(`padMaps = { n64: { r: 'rup', rup: 'r' } }`);
  xi({ buttons: 0x0200, lx: 20000 });
  const local = run('padGlyphLocal()');
  assert.deepEqual(sorted(local.held), ['lright', 'rup'], 'the picture lights C-up for RB');
  assert.ok(local.stick.x > 0.5 && local.rstick.x === 0, 'and moves the N64 stick');
  xi();
  // the Controllers page lists each console's map, what lost its control, and a reset
  run(`padMaps = { n64: { r: 'rup' } }`);
  const page = run('padMapsHTML()');
  assert.match(page, /<b>Nintendo 64<\/b> <span class="pill">RB → C-up<\/span>/);
  assert.match(page, /no control: R</);
  assert.match(page, /resetPadMap\("n64"\)/);
  assert.match(run(`padMaps = {}; padMapsHTML()`), /Every console uses its default layout/);
}

forwarding().then(() => console.log('Controller map checks passed')).catch(e => { console.error(e); process.exitCode = 1; });
