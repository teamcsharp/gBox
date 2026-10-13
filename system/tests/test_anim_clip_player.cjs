// Animation clips in the model view (#1384): clients/web/viz/clip-player.js (clip list, play head, AnimationMixer
// player, panel controls) and its glue in the web model view + the desktop shell's 3D cards, on fakes.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../clients/web/viz/clip-player.js'), 'utf8');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const plain = x => JSON.parse(JSON.stringify(x));           // values built inside the vm realm compare by structure

function load(extra = {}) {
  const ctx = { window: {}, ...extra };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.window.GBoxClips;
}

class Mixer {
  constructor(root) { this.root = root; this.actions = []; this.updates = []; this.uncached = []; }
  clipAction(clip) {
    const a = { clip, time: 0, loop: null, played: false, stopped: false,
      setLoop(l, n) { this.loop = [l, n]; return this; }, play() { this.played = true; return this; }, stop() { this.stopped = true; return this; } };
    this.actions.push(a); return a;
  }
  update(dt) { const a = this.actions[this.actions.length - 1]; this.updates.push([dt, a && a.time]); }
  uncacheAction(c) { this.uncached.push(c.name); }
  stopAllAction() { this.allStopped = true; }
  uncacheRoot() {}
}
const THREE = { AnimationMixer: Mixer, LoopRepeat: 2201 };
function rootWith(objects = {}) {
  const posed = [];
  return { posed, getObjectByName: n => objects[n], traverse: fn => [{ skeleton: { pose: () => posed.push(1) } }, {}].forEach(fn) };
}
const walk = { name: 'walk', duration: 2, tracks: [] };

test('the clip list joins meta rows and embedded clips, sprites become 2D rows', () => {
  const C = load();
  const meta = { model: 'aya.glb', animations: [
    { name: 'kasumi_000', duration_s: 0.15, source: 'DOA2/KASUMI.MOT', file: 'doa2_kas.anims.glb', drives: 'controls' },
    { name: 'anim_00', duration_s: 1.5, source: 'embedded in aya.glb', file: 'aya.glb', drives: 'skeleton' },
    { name: 'kasumi_000', duration_s: 0.15, file: 'doa2_kas.anims.glb' }, { duration_s: 3 }] };
  const rows = plain(C.list(meta, [{ name: 'anim_00', duration: 1.5 }, { name: 'anim_01', duration: 0.5 }]));
  assert.deepEqual(rows.map(r => [r.name, r.file, r.drives, r.duration]), [
    ['kasumi_000', 'doa2_kas.anims.glb', 'controls', 0.15], ['anim_00', 'aya.glb', 'skeleton', 1.5], ['anim_01', 'aya.glb', 'skeleton', 0.5]]);
  assert.equal(rows[2].source, 'embedded');
  assert.deepEqual(plain(C.list(null, [{ name: 'take', duration: 1 }])).map(r => [r.kind, r.name, r.file]), [['3d', 'take', '']]);
  const sprites = plain(C.list({ kind: 'sprites', model: 'sheet.png', animations: [
    { clip: 'walk', name: 'Walk', preview: 'clips/walk/preview.apng', webp: 'clips/walk/preview.webp', mp4: 'clips/walk/clip.mp4', frames: 12, fps: 24 },
    { clip: 'idle', name: 'Idle', preview: 'clips/idle/preview.apng', webp: null, mp4: null, frames: 4, fps: 8 }] }));
  assert.deepEqual(sprites.map(r => [r.kind, r.name, r.preview, r.mp4, r.duration]), [
    ['2d', 'Walk', 'clips/walk/preview.webp', 'clips/walk/clip.mp4', 0.5], ['2d', 'Idle', 'clips/idle/preview.apng', null, 0.5]]);
  assert.deepEqual(plain(C.list({ model: 'm.glb' })), []);
});

test('the play head scales by speed, wraps when looping and stops at the end otherwise', () => {
  const { step } = load();
  const st = { t: 0.5, duration: 2, playing: true, loop: true, speed: 2 };
  assert.equal(step(st, 0.25).t, 1);
  assert.equal(step(st, 1).t, 0.5);                                // 0.5 + 2 wraps to 0.5
  assert.deepEqual(plain(step({ ...st, loop: false }, 1)), { ...st, loop: false, t: 2, playing: false });
  assert.equal(step({ ...st, playing: false }, 1).t, 0.5);
  assert.equal(step({ ...st, duration: 0 }, 1).t, 0);
  assert.equal(step(st, -5).t, 0.5);
  assert.equal(load().fmt(1.234), '1.23 s');
});

test('the AnimationMixer player loads, plays, loops, seeks, changes speed and stops', () => {
  const C = load(), root = rootWith(), seen = [];
  const p = C.player(THREE, root, st => seen.push({ ...st }));
  assert.equal(p.mixer.root, root);
  assert.equal(p.update(1), false);                                // nothing loaded
  p.load(walk);
  const a = p.mixer.actions[0];
  assert.deepEqual(plain(a.loop), [2201, null]); assert.ok(a.played);
  assert.deepEqual(plain(p.state), { name: 'walk', t: 0, duration: 2, playing: true, loop: true, speed: 1 });
  p.setSpeed(2); p.update(0.75);
  assert.equal(p.state.t, 1.5); assert.equal(a.time, 1.5);
  assert.deepEqual(plain(p.mixer.updates[p.mixer.updates.length - 1]), [0, 1.5]);   // pose applied at the play head, dt 0
  p.update(0.5); assert.equal(p.state.t, 0.5);                    // wrapped
  p.setSpeed(3); assert.equal(p.state.speed, 1);                   // only the offered speeds
  p.seek(9); assert.equal(p.state.t, 2); p.seek(-1); assert.equal(p.state.t, 0);
  p.toggle(); assert.equal(p.state.playing, false); assert.equal(p.update(1), false);
  p.setLoop(false); p.seek(2); p.play(); assert.equal(p.state.t, 0); // play at the end restarts
  p.update(5); assert.equal(p.state.playing, false); assert.equal(p.state.t, 2);
  p.load({ name: 'run', duration: 1, tracks: [] });
  assert.ok(a.stopped); assert.deepEqual(plain(p.mixer.uncached), ['walk']);
  p.stop();
  assert.deepEqual(plain(p.state), { name: '', t: 0, duration: 0, playing: false, loop: false, speed: 1 });
  assert.deepEqual(root.posed, [1]);                               // back to the bind pose
  assert.ok(seen.length > 8);
  p.dispose(); assert.ok(p.mixer.allStopped);
});

test('control clips report bar heights from their helper nodes', () => {
  const C = load();
  const clip = { name: 'kasumi_000', duration: 1, tracks: [
    { name: 'mot_ch01.position', values: [0, 0, 0, 10, 0, 0] }, { name: 'mot_ch00.position', values: [-1, 0, 0, 1, 0, 0] },
    { name: 'mot_ch02.position', values: [5, 0, 0, 5, 0, 0] }] };
  assert.deepEqual(plain(C.ranges(clip)), { mot_ch01: [0, 10], mot_ch00: [-1, 1], mot_ch02: [5, 5] });
  const nodes = { mot_ch00: { position: { x: 0 } }, mot_ch01: { position: { x: 2.5 } }, mot_ch02: { position: { x: 5 } } };
  const p = C.player(THREE, rootWith(nodes));
  p.load(clip, 'controls');
  assert.deepEqual(plain(p.bars()), [0.5, 0.25, 0.5]);
  p.load(clip, 'skeleton'); assert.deepEqual(plain(p.bars()), []);
  assert.deepEqual(plain(C.bars([['x', 20]], { x: [0, 10] })), [1]);
});

test('panel HTML escapes clip names, offers a filter for long lists and MP4 for sprites', () => {
  const C = load();
  const h = C.html([{ kind: '3d', name: '<b>x</b>', duration: 1, drives: 'controls' }]);
  assert.ok(!h.includes('<b>x</b>') && h.includes('&#60;b&#62;x'));
  assert.match(h, /data-c="scrub"/); assert.match(h, /data-c="loop" aria-pressed="true"/); assert.match(h, /· controls/);
  assert.ok(!h.includes('gbc-q'));
  const many = Array.from({ length: 13 }, (_, i) => ({ kind: '3d', name: 'c' + i, duration: 1 }));
  assert.match(C.html(many), /gbc-q/); assert.match(C.html(many), /13 clips/);
  const s = C.html([{ kind: '2d', name: 'walk', frames: 12 }]);
  assert.match(s, /data-c="mp4"/); assert.ok(!s.includes('data-c="scrub"')); assert.match(s, /12 frames/);
  assert.equal(C.html([]), '');
});

// a panel whose querySelector knows the elements html() wrote
function fakePanel() {
  const cls = () => { const set = new Set(); return { set, add: c => set.add(c), toggle: (c, f) => (f ? set.add(c) : set.delete(c)), contains: c => set.has(c) }; };
  const el = (extra = {}) => ({ hidden: true, textContent: '', value: '', href: '', attrs: {}, dataset: {}, classList: cls(),
    setAttribute(k, v) { this.attrs[k] = v; }, ...extra });
  const els = {}, rows = [];
  const marks = { '[data-c="play"]': 'data-c="play"', '[data-c="loop"]': 'data-c="loop"', '[data-c="speed"]': 'data-c="speed"',
    '[data-c="scrub"]': 'data-c="scrub"', '[data-c="time"]': 'data-c="time"', '[data-c="mp4"]': 'data-c="mp4"', '.gbc-note': 'gbc-note',
    '.gbc-ctl': 'gbc-ctl', '.gbc-media': 'gbc-media', '.gbc-bars': 'gbc-bars' };
  const panel = el({ hidden: true, querySelector: s => els[s] ?? null, querySelectorAll: s => (s === '.gbc-row' ? rows : []) });
  let html = '';
  Object.defineProperty(panel, 'innerHTML', { get: () => html, set(h) {
    html = h; rows.length = 0;
    for (const m of h.matchAll(/data-ci="(\d+)"/g)) rows.push(el({ dataset: { ci: m[1] } }));
    for (const [sel, mark] of Object.entries(marks)) els[sel] = h.includes(mark) ? el() : null;
  } });
  const target = (sel, extra = {}) => ({ ...extra, classList: { contains: () => false }, closest: s => (s === sel ? { dataset: extra.dataset || {}, value: extra.value } : null) });
  return { panel, els, rows, target };
}
const tick = () => new Promise(r => setImmediate(r));

test('the 3D panel loads a clip on select and drives the player from its controls', async () => {
  const C = load(), f = fakePanel(), loads = [];
  let ui = null;
  const p = C.player(THREE, rootWith(), st => ui && ui.render(st));
  const rows = [{ kind: '3d', name: 'walk', duration: 2, file: 'm.glb', drives: 'skeleton' },
    { kind: '3d', name: 'kasumi_000', duration: 1, file: 'x.anims.glb', drives: 'controls' }];
  ui = C.mount(f.panel, rows, { url: x => x, load: async row => { loads.push(row.name); if (row.name === 'bad') throw new Error('gone'); return { player: p, clip: { ...walk, name: row.name, duration: row.duration } }; } });
  assert.equal(f.panel.hidden, false); assert.ok(f.panel.classList.contains('gbclips'));
  assert.equal(f.els['.gbc-ctl'].hidden, true);
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '0' } }) }); await tick();
  assert.deepEqual(loads, ['walk']); assert.equal(f.els['.gbc-ctl'].hidden, false);
  assert.equal(f.els['.gbc-note'].hidden, true); assert.equal(f.els['.gbc-bars'].hidden, true);
  assert.ok(f.rows[0].classList.contains('on') && !f.rows[1].classList.contains('on'));
  assert.equal(f.els['[data-c="play"]'].textContent, '❚❚');
  f.panel.onclick({ target: f.target('[data-c]', { dataset: { c: 'play' } }) });
  assert.equal(p.state.playing, false); assert.equal(f.els['[data-c="play"]'].textContent, '▶');
  f.panel.onclick({ target: f.target('[data-c]', { dataset: { c: 'loop' } }) });
  assert.equal(p.state.loop, false); assert.equal(f.els['[data-c="loop"]'].attrs['aria-pressed'], 'false');
  f.panel.oninput({ target: f.target('[data-c]', { dataset: { c: 'scrub' }, value: '500' }) });
  assert.equal(p.state.t, 1); assert.equal(f.els['[data-c="time"]'].textContent, '1.00 s / 2.00 s');
  f.panel.oninput({ target: f.target('[data-c]', { dataset: { c: 'speed' }, value: '0.5' }) });
  assert.equal(p.state.speed, 0.5); assert.equal(f.els['[data-c="speed"]'].value, '0.5');
  p.play(); p.update(1); assert.equal(f.els['[data-c="scrub"]'].value, '750');   // 1 + 1 × 0.5 of 2 s
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '1' } }) }); await tick();
  assert.equal(p.state.name, 'kasumi_000'); assert.equal(f.els['.gbc-bars'].hidden, false);
  assert.match(f.els['.gbc-note'].textContent, /does not move/);
  f.panel.onclick({ target: f.target('[data-c]', { dataset: { c: 'stop' } }) });
  assert.equal(p.state.name, '');
});

test('a slow clip load never replaces a newer selection and a failed one says why', async () => {
  const C = load(), f = fakePanel(), p = C.player(THREE, rootWith());
  const waits = {};
  const rows = [{ kind: '3d', name: 'slow', duration: 1 }, { kind: '3d', name: 'fast', duration: 1 }, { kind: '3d', name: 'bad', duration: 1 }];
  C.mount(f.panel, rows, { url: x => x, load: row => new Promise((ok, no) => { waits[row.name] = { ok: () => ok({ player: p, clip: { ...walk, name: row.name } }), no }; }) });
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '0' } }) });
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '1' } }) });
  waits.fast.ok(); await tick(); waits.slow.ok(); await tick();
  assert.equal(p.state.name, 'fast');
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '2' } }) });
  waits.bad.no(new Error('gone')); await tick();
  assert.equal(f.els['.gbc-note'].textContent, 'Clip unavailable: gone'); assert.equal(f.els['.gbc-note'].hidden, false);
});

test('a 2D sprite clip plays its preview loop and offers its MP4', () => {
  const C = load(), f = fakePanel(), shown = [];
  const rows = C.list({ kind: 'sprites', animations: [{ clip: 'walk', name: 'Walk', preview: 'clips/walk/preview.apng', mp4: 'clips/walk/clip.mp4', frames: 12, fps: 24 },
    { clip: 'idle', name: 'Idle', preview: 'clips/idle/preview.apng', frames: 4, fps: 8 }] });
  C.mount(f.panel, rows, { url: rel => '/api/characters/s/file/' + rel, sprite: row => shown.push(row.preview) });
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '0' } }) });
  assert.deepEqual(shown, ['clips/walk/preview.apng']);
  assert.equal(f.els['.gbc-media'].hidden, false); assert.equal(f.els['[data-c="mp4"]'].hidden, false);
  assert.equal(f.els['[data-c="mp4"]'].href, '/api/characters/s/file/clips/walk/clip.mp4');
  assert.equal(f.els['.gbc-note'].textContent, '12 frames at 24 fps');
  f.panel.onclick({ target: f.target('[data-ci]', { dataset: { ci: '1' } }) });
  assert.equal(f.els['[data-c="mp4"]'].hidden, true);
  assert.equal(C.mount(fakePanel().panel, [], {}), null);
});

test('the web model view mounts clips under the model and the desktop 3D cards play embedded clips', () => {
  assert.match(web, /<script src="\/viz\/clip-player\.js"><\/script>/);
  assert.match(desktop, /<script src="\.\.\/web\/viz\/clip-player\.js"><\/script>/);
  assert.match(web, /createCharacterViewer\(preview, modelUrl, \{ model: model\.model, fileUrl \}\)/);
  assert.match(web, /<div id="model-clips" hidden><\/div>/);
  assert.match(desktop, /GBoxClips\.player\(T, g\.scene, st => ui\?\.render\(st\)\)/);
  assert.match(desktop, /v\.player\?\.update\(dt\)/);
  // the web glue, run on fakes
  const start = web.indexOf('// ---------------- model clips (#1384)'), end = web.indexOf('// ---------------- loading screen', start);
  assert.ok(start > 0 && end > start);
  const C = load(), mounted = [], players = [];
  const clips = { ...C, mount: (el, rows, hooks) => { mounted.push({ el, rows, hooks }); return { render() {} }; },
    player: (T, root, cb) => { players.push({ T, root }); return { kind: 'player' }; } };
  const panel = { id: 'model-clips' }, preview = { isConnected: true, innerHTML: '' };
  const ctx = vm.createContext({ window: { GBoxClips: clips }, GBoxClips: clips, $: s => (s === '#model-clips' ? panel : null), esc: String });
  vm.runInContext(web.slice(start, end), ctx);
  const fileUrl = rel => '/f/' + rel;
  ctx.modelClips({ kind: 'sprites', animations: [{ clip: 'walk', name: 'Walk', preview: 'clips/walk/preview.apng' }] }, null, fileUrl, preview);
  assert.equal(mounted[0].el, panel); assert.equal(mounted[0].rows.length, 1);
  mounted[0].hooks.sprite(mounted[0].rows[0]);
  assert.match(preview.innerHTML, /src="\/f\/clips\/walk\/preview\.apng"/);
  let set = null;
  const viewer = { THREE: 'T', holder: 'H', embedded: [{ name: 'wave', duration: 1 }], setPlayer: p => { set = p; }, clip: async row => 'clip:' + row.name };
  ctx.modelClips({ model: 'm.glb', animations: [] }, viewer, fileUrl);
  assert.deepEqual(players, [{ T: 'T', root: 'H' }]); assert.deepEqual(set, { kind: 'player' });
  assert.deepEqual(plain(mounted[1].rows.map(r => r.name)), ['wave']);
  return mounted[1].hooks.load(mounted[1].rows[0]).then(got => assert.equal(got.clip, 'clip:wave'));
});
