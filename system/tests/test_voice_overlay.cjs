// Voice overlay (#250): the randomized transition visual shows over the game while the operator talks to gBox or it talks
// back (not for the whole voice session), a short hold bridges pauses, a fresh start asks for a new random mode, the setting
// turns it off, and the GPU surface and the native floating window get the same decision. Driven on the desktop shell's
// VOV section with fake globals, plus the wiring in main.js, overlay.html and the GPU surface.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
const overlay = fs.readFileSync(path.join(__dirname, '../clients/web/viz/overlay.html'), 'utf8');
const surface = fs.readFileSync(path.join(__dirname, '../clients/web/viz/gpu-game-surface.js'), 'utf8');

function fixture({ pref = null, surface: kind = 'native' } = {}) {
  const store = new Map(); if (pref) store.set('gbox_voice_overlay', pref);
  const calls = { viz: [], gpu: [] }, classes = new Set(), f = { now: 1000 };
  const ctx = {
    TALK: { on: false, audio: null, phase: 'idle', lvl: 0 }, EMB: { sid: 'w-1', rect: { x: 0, y: 0, w: 640, h: 480 }, surface: kind }, PTT: { down: false },
    gbox: { vizOverlay: st => calls.viz.push(st) }, gpuGameVoice: st => calls.gpu.push(st),
    document: { body: { classList: { contains: c => classes.has(c), add: c => classes.add(c), remove: c => classes.delete(c) } } },
    localStorage: { getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, v) },
    setInterval: fn => { f.tick = fn; return 0; }, Date: { now: () => f.now }, Math, JSON, Object,
  };
  vm.createContext(ctx);
  const a = desktop.indexOf('// ---------------- voice overlay (#250)'), b = desktop.indexOf('document.addEventListener("focusin"', a);
  assert.ok(a > 0 && b > a, 'the voice overlay section exists');
  vm.runInContext(desktop.slice(a, b), ctx);
  Object.assign(ctx, vm.runInContext('({ VOV, vovDecide, vovSignals, vovApply, vovEnable, vovEnabledPref, vovTick })', ctx));
  f.tick = ctx.vovTick;                                     // the loop body; its setInterval starts after TALK (below)
  return Object.assign(f, { ctx, calls, store, classes });
}
const plain = x => JSON.parse(JSON.stringify(x));
test('the overlay loop starts only after TALK and PTT are declared (no TDZ throw every 200 ms)', () => {
  const start = desktop.indexOf('setInterval(vovTick, 200);'), talk = desktop.indexOf('const TALK = {'), ptt = desktop.indexOf('const PTT = {');
  assert.ok(start > 0 && talk > 0 && ptt > 0, 'loop, TALK and PTT present');
  assert.ok(start > talk && start > ptt, 'setInterval(vovTick) comes after both declarations');
  assert.equal(desktop.split('setInterval(vovTick').length - 1, 1, 'one loop');
  const a = desktop.indexOf('// ---------------- voice overlay (#250)'), b = desktop.indexOf('document.addEventListener("focusin"', a);
  assert.doesNotMatch(desktop.slice(a, b), /setInterval\(/, 'the overlay section itself starts no timer');
});

test('the decision: on while someone talks, held briefly across pauses, a new random visual on each fresh start', () => {
  const f = fixture(), { vovDecide } = f.ctx, st = { on: false, last: 0, enabled: true, hold: 1500 };
  assert.equal(vovDecide({ game: false, me: true }, st, 1000).on, false, 'no game picture: nothing to overlay');
  let d = vovDecide({ game: true, me: true, level: 0.05 }, st, 1000);
  assert.deepEqual(plain({ on: d.on, restart: d.restart, mode: d.mode }), { on: true, restart: true, mode: 'random' });
  assert.ok(Math.abs(d.level - 0.6) < 1e-9, 'the level follows the microphone'); assert.equal(d.beat, false);
  st.on = true;
  d = vovDecide({ game: true, me: true, level: 0.001 }, st, 1200);
  assert.equal(d.restart, false); assert.equal(d.mode, undefined); assert.equal(d.level, 0.35, 'a quiet mic still breathes');
  assert.equal(vovDecide({ game: true }, st, 2000).on, true, 'a pause shorter than the hold keeps it up');
  assert.equal(vovDecide({ game: true }, st, 2800).on, false, 'past the hold it goes');
  st.on = false;
  d = vovDecide({ game: true, ai: true }, st, 3000);
  assert.equal(d.on, true); assert.equal(d.level, 0.9, "gBox's reply drives the visual hard"); assert.equal(typeof d.beat, 'boolean');
  st.enabled = false; st.on = true;
  assert.equal(vovDecide({ game: true, ai: true, me: true }, st, 3100).on, false, 'the setting wins');
});

test('the signals: listening, thinking and speaking phases count; merely waiting in voice mode does not', () => {
  const f = fixture(), { vovSignals, TALK, PTT } = f.ctx;
  TALK.on = true; TALK.phase = 'idle';
  assert.deepEqual(plain(vovSignals()), { ai: false, level: 0, game: true, me: false });
  TALK.phase = 'listening'; TALK.lvl = 0.03; assert.equal(vovSignals().me, true); assert.equal(vovSignals().level, 0.03);
  TALK.phase = 'thinking'; assert.equal(vovSignals().me, true);
  TALK.phase = 'speaking'; assert.deepEqual(plain(vovSignals()), { ai: true, level: 0.03, game: true, me: false });
  TALK.phase = 'idle'; PTT.down = true; assert.equal(vovSignals().me, true);
  PTT.down = false; f.classes.add('talking'); assert.equal(vovSignals().me, true);
  f.classes.delete('talking'); TALK.audio = { paused: false }; assert.equal(vovSignals().ai, true);
  TALK.audio = { paused: true }; assert.equal(vovSignals().ai, false);
  f.ctx.EMB.rect = null; assert.equal(vovSignals().game, false);
});

test('a native game gets the floating window with the game rect, a restart once, then plain updates, then off', () => {
  const f = fixture(), { TALK, VOV } = f.ctx;
  f.tick(); assert.deepEqual(f.calls.viz, [], 'nothing to do while idle');
  TALK.phase = 'listening'; TALK.lvl = 0.1; f.tick();
  assert.equal(f.calls.viz.length, 1);
  assert.deepEqual(plain(f.calls.viz[0]), { on: true, rect: { x: 0, y: 0, w: 640, h: 480 }, holes: [], level: 1, beat: false, mode: 'random', restart: true });
  assert.deepEqual(plain(f.calls.gpu), [{ on: false }], 'the GPU layer is told to stay off');
  f.now += 200; f.tick();
  assert.equal(f.calls.viz[1].restart, false); assert.equal('mode' in plain(f.calls.viz[1]), false);
  TALK.phase = 'idle'; f.now += 200; f.tick(); assert.equal(f.calls.viz[2].on, true, 'the hold keeps it up');
  f.now += 2000; f.tick(); assert.deepEqual(plain(f.calls.viz[3]), { on: false }); assert.equal(VOV.on, false);
  f.now += 200; f.tick(); assert.equal(f.calls.viz.length, 4, 'off stays quiet');
});

test('#1081: the floating visualizer receives the pop-up holes, so app menus stay above it like they do above the game', () => {
  const f = fixture(), { TALK } = f.ctx;
  f.ctx.EMB.holes = [{ x: 10, y: 20, w: 100, h: 50 }];
  TALK.phase = 'listening'; f.tick();
  assert.deepEqual(plain(f.calls.viz[0].holes), [{ x: 10, y: 20, w: 100, h: 50 }]);
  const main = require('node:fs').readFileSync(require('node:path').join(__dirname, '../clients/desktop/main.js'), 'utf8');
  assert.match(main, /vizOv\.setShape\(embedGeometry\.shapeMinusHoles\(bounds\.width, bounds\.height, st\.holes \|\| \[\], z\)\)/);
});

test('a GPU-surface game layers the visual itself: the floating window stays off and the mode travels once', () => {
  const f = fixture({ surface: 'gpu' }), { TALK } = f.ctx;
  TALK.phase = 'speaking'; f.tick(); f.now += 200; f.tick();
  assert.deepEqual(plain(f.calls.viz), [{ on: false }, { on: false }]);
  assert.deepEqual(plain(f.calls.gpu[0]), { on: true, level: 0.9, beat: f.calls.gpu[0].beat, mode: 'random' });
  assert.equal('mode' in plain(f.calls.gpu[1]), false);
  assert.equal(f.calls.gpu[1].on, true);
});

test('the setting: off is remembered, takes the overlay down at once and is read back by the Settings page', () => {
  const f = fixture(), { TALK, VOV, vovEnable, vovEnabledPref } = f.ctx;
  TALK.phase = 'speaking'; f.tick(); assert.equal(VOV.on, true);
  vovEnable(false);
  assert.equal(f.store.get('gbox_voice_overlay'), 'off'); assert.equal(VOV.on, false);
  assert.deepEqual(plain(f.calls.viz.at(-1)), { on: false }); assert.equal(vovEnabledPref(), false);
  f.now += 200; f.tick(); assert.equal(VOV.on, false, 'nothing comes back while off');
  vovEnable(true); f.now += 200; f.tick(); assert.equal(VOV.on, true); assert.equal(f.store.get('gbox_voice_overlay'), 'on');
  const g = fixture({ pref: 'off' }); assert.equal(g.ctx.VOV.enabled, false, 'the stored choice applies at start');
  assert.match(desktop, /name="voiceOverlay" \$\{vovEnabledPref\(\) \? "checked" : ""\}/, 'Settings shows the checkbox');
  assert.match(desktop, /vovEnable\(!!f\.get\("voiceOverlay"\)\)/, 'Save stores it');
  assert.match(desktop, /\["vov", VOV\.enabled \? "✨ Voice overlay on the game: on"/, "the game's right-click menu toggles it");
  assert.match(desktop, /a === "vov"\) \{ vovEnable\(!VOV\.enabled\)/);
});

test('the voice loop marks its phases and the overlay page restarts with a random transition on request', () => {
  assert.match(desktop, /const TALK = \{[^\n]*phase: "idle", lvl: 0/);
  assert.match(desktop, /speaking = true; TALK\.phase = "listening"; liveStatus\("Listening…"\)/);
  assert.match(desktop, /liveStatus\("Transcribing \(Spark faster-whisper\)…"\); TALK\.phase = "thinking";/);
  assert.match(desktop, /liveStatus\(`Speaking \(\$\{[^`]*`\); TALK\.phase = "speaking";/);
  assert.match(desktop, /liveStatus\("Waiting for you to speak…"\); TALK\.phase = "idle";/);
  assert.match(desktop, /TALK\.on = false; TALK\.phase = "idle";/, 'ending the talk ends the phase');
  assert.match(main, /\.\.\.\(st\.restart \? \{ mode: st\.mode \|\| "random" \} : \{\}\)/, 'main.js forwards the restart as a mode');
  assert.match(overlay, /window\.gboxVoiceMode = m => viz\.setMode\(m && m !== "random" \? m : pref\(\), \{ transition: Math\.random\(\) < 0\.5 \? "crossfade" : "dissolve" \}\)/);
  assert.match(overlay, /window\.gboxVoice = s => \{ if \(s\.mode\) window\.gboxVoiceMode\(s\.mode\);/);
  assert.match(overlay, /const pref = \(\) => want && want !== "random" \? want : readVizPref\(\)/, "a fixed picker choice is kept; 'random' rolls again");
  const script = overlay.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  const parsed = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: script, encoding: 'utf8' });
  assert.equal(parsed.status, 0, parsed.stderr);
  assert.match(surface, /voiceState = \{ level: st\.level, beat: st\.beat, \.\.\.\(st\.mode \? \{ mode: st\.mode \} : \{\}\) \}/, 'the GPU layer forwards the mode only when set');
});
