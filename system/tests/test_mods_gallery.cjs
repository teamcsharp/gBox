// Mods gallery (clients/web/viz/mods-gallery.js over GET /api/mods/built): filters, card rendering (carousel, badges,
// donor -> slot rows, buttons), the controller's paging / filtering / image pop-up / Play / saved moment / screenshot /
// request flows on a fake host, and the Mods entry in both clients.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const MG = require('../clients/web/viz/mods-gallery.js');
const LP = require('../clients/desktop/live-poll.js');

const PSO = {
  key: 'pso/cast_pso_ult', name: 'cast_pso_ult', game_id: 'pso', title: 'Phantasy Star Online', mod_title: 'PSO: cast as <Wrestlers>',
  writer: 'pso_enemy', cast: true, built: 2000, size: 3 * 2 ** 30, own_size: 2 ** 20, verified: false,
  changes: [{ donor: 'hucast', slot: 'enemy:booma', status: 'built' }, { donor: 'ramar', slot: 'enemy:gobooma', status: 'failed', reason: 'too many triangles' }],
  images: [{ name: 'frames_preview.png', url: '/api/mods/built/pso/cast_pso_ult/image/frames_preview.png' }],
  donor_previews: [{ slug: 'hucast', url: '/api/characters/hucast/preview' }],
  shots: [{ sha256: 'a'.repeat(64), url: '/api/artifacts/' + 'a'.repeat(64) }],
  card_id: 'c-pso', state_slot: null, tickets: [], last_launch: null,
};
const VR = {
  key: 'mgsvr/mgsvr_hucast', name: 'mgsvr_hucast', game_id: 'mgsvr', title: 'Metal Gear Solid VR Missions', mod_title: 'HUcast in MGS VR',
  writer: 'mgsvr', built: 1000, size: 100, own_size: 100, verified: true, changes: [{ donor: 'hucast', slot: 'player' }],
  images: [], donor_previews: [], shots: [], card_id: 'card1', state_slot: 3,
  tickets: [{ number: 5, id: 'r5', title: 'Put HUcast in MGS VR', status: 'in_progress' }],
  last_launch: { state: 'failed', error: 'core crashed', ts: 900 },
};
const CF = {
  key: 'cf3/cf_hucast_taffy', name: 'cf_hucast_taffy', game_id: 'cf3', title: 'ClayFighter 63 1/3', mod_title: 'HUcast as Taffy',
  writer: 'clayfighter_swap', built: 3000, size: 10, own_size: 10, verified: false, changes: [], images: [], donor_previews: [],
  shots: [], card_id: '', state_slot: null, tickets: [{ number: 7 }], last_launch: null,
};

test('filters: game, writer, words over names / donors / slots / #tickets; newest build first', () => {
  const all = [VR, PSO, CF];
  assert.deepEqual(MG.filterMods(all).map(m => m.name), ['cf_hucast_taffy', 'cast_pso_ult', 'mgsvr_hucast']);
  assert.deepEqual(MG.filterMods(all, { game: 'pso' }).map(m => m.name), ['cast_pso_ult']);
  assert.deepEqual(MG.filterMods(all, { writer: 'mgsvr' }).map(m => m.name), ['mgsvr_hucast']);
  assert.deepEqual(MG.filterMods(all, { q: 'gobooma' }).map(m => m.name), ['cast_pso_ult']);
  assert.deepEqual(MG.filterMods(all, { q: 'HUCAST player' }).map(m => m.name), ['mgsvr_hucast']);
  assert.deepEqual(MG.filterMods(all, { q: '#7' }).map(m => m.name), ['cf_hucast_taffy']);
  assert.deepEqual(MG.filterMods(all, { q: 'nothing-like-this' }), []);
  const f = MG.facets(all);
  assert.deepEqual(f.games.map(g => [g.game_id, g.count]), [['cf3', 1], ['mgsvr', 1], ['pso', 1]]);
  assert.deepEqual(f.writers.map(w => w.writer), ['clayfighter_swap', 'mgsvr', 'pso_enemy']);
});

test('pictures: in-game shots, then the build previews, then the donors (URLs made loadable)', () => {
  const imgs = MG.imagesOf(PSO, u => u + '?token=t');
  assert.deepEqual(imgs.map(i => i.kind), ['shot', 'build', 'donor']);
  assert.equal(imgs[1].src, '/api/mods/built/pso/cast_pso_ult/image/frames_preview.png?token=t');
  assert.match(imgs[2].name, /Donor hucast/);
});

test('pictures: frames captured from sessions of the build follow the card shots (#1553)', () => {
  const m = { ...PSO, frames: [{ sha256: 'b'.repeat(64), url: '/api/artifacts/' + 'b'.repeat(64), session_id: 'w-12345678abc', source: 'save state 2' }] };
  const imgs = MG.imagesOf(m, u => u + '?token=t');
  assert.deepEqual(imgs.map(i => i.kind), ['shot', 'shot', 'build', 'donor']);
  assert.equal(imgs[1].src, '/api/artifacts/' + 'b'.repeat(64) + '?token=t');
  assert.match(imgs[1].name, /save state 2 \(session w-123456\)/);
  assert.deepEqual(MG.imagesOf({ ...PSO, frames: undefined }).map(i => i.kind), ['shot', 'build', 'donor']);
});

test('card: carousel, escaped title, badges, donor -> slot rows with the per-slot status, sizes and buttons', () => {
  const html = MG.cardHTML(PSO, { url: u => u + '?token=t', now: 2060 });
  assert.match(html, /data-key="pso\/cast_pso_ult"/);
  assert.ok(html.includes('PSO: cast as &#60;Wrestlers&#62;') && !html.includes('<Wrestlers>'));
  assert.match(html, /class="mg-badge mg-unv">unverified/);
  assert.match(html, /<img class="mg-img" loading="lazy"[^>]*data-i="0" src="\/api\/artifacts\/a{64}\?token=t"/);
  assert.match(html, /data-mg="prev"[\s\S]*data-mg="next"/);
  assert.match(html, /in-game · 1 \/ 3/);
  assert.match(html, /<b><button[^>]*data-slug="ramar"[^>]*>ramar<\/button><\/b> <button[^>]*data-mg="mapping"[^>]*>→ enemy:gobooma<\/button> <span class="mg-st mg-failed">failed<\/span> <span class="mut">too many triangles/);
  assert.match(html, /<b><button[^>]*data-slug="hucast"[^>]*>hucast<\/button><\/b> <button[^>]*data-mg="mapping"[^>]*>→ enemy:booma<\/button> <span class="mg-st mg-built">built/);
  assert.match(html, /1\.0 MB \(3\.00 GB with shared files\)/);
  assert.match(html, /built just now/); assert.match(html, /never launched/);
  assert.match(html, /data-mg="play">Play</);
  assert.ok(!html.includes('data-mg="moment"'), 'no saved moment linked: no moment button');
  assert.match(html, /data-mg="shot"[^>]*>Screenshot after launch/);
  assert.ok(!/data-mg="shot"[^>]*disabled/.test(html));
  assert.match(html, /data-mg-game="pso"/); assert.match(html, /data-mg-writer="pso_enemy"/); assert.match(html, /cast swap/);
  // the carousel index wraps both ways and the counter follows
  assert.match(MG.cardHTML(PSO, { idx: 4 }), /<span class="mg-count">2 \/ 3<\/span>/);
  assert.match(MG.cardHTML(PSO, { idx: -1 }), /donor · 3 \/ 3/);
  assert.match(MG.cardHTML(PSO, { idx: 1 }), /data-i="1" src="\/api\/mods\/built\/pso\/cast_pso_ult\/image\/frames_preview\.png"/);
});

test('card: verified build with a saved moment and a request; build without pictures or card', () => {
  const vr = MG.cardHTML(VR, { now: 1000 });
  assert.match(vr, /mg-badge mg-ok">verified/);
  assert.match(vr, /data-mg="moment"[^>]*>Play from saved moment/);
  assert.match(vr, /data-mg="request" data-n="5" title="Put HUcast in MGS VR">Open request #5 · in progress/);
  assert.match(vr, /mg-launch mg-bad">last launch failed: core crashed/);
  assert.match(vr, /No pictures yet/); assert.ok(!vr.includes('data-mg="prev"'));
  const cf = MG.cardHTML(CF);
  assert.match(cf, /No donor \/ slot record/);
  assert.match(cf, /data-mg="shot"[^>]*disabled/, 'no mod card yet: nothing to attach a screenshot to');
  assert.ok(!cf.includes('data-mg="moment"'));
  assert.match(cf, /Open request #7</);
});

// ------------------------------------------------------------------ the controller on a fake host

function el(extra = {}) {
  const n = { innerHTML: '', textContent: '', dataset: {}, disabled: false, value: '', ...extra };
  n.querySelector = () => null;
  return n;
}
function fakeHost() {
  const parts = { '[data-mg-grid]': el(), '[data-mg-sum]': el(), '[data-mg-more]': el() };
  const listeners = {};
  let html = '';
  const host = {
    get innerHTML() { return html; }, set innerHTML(v) { html = v; },
    querySelector: s => parts[s] || null, contains: () => false,
    addEventListener: (t, fn) => (listeners[t] ||= []).push(fn), removeEventListener() {},
  };
  const fire = async (type, target) => { for (const fn of listeners[type] || []) await fn({ target, clientX: 10, clientY: 20, preventDefault() {}, stopPropagation() {} }); };
  return { host, parts, fire, grid: () => parts['[data-mg-grid]'].innerHTML, more: () => parts['[data-mg-more]'].innerHTML };
}
// a click target: what closest() finds around it (card, [data-mg] action, button, image, chips, request number)
function target({ key, mg, img, game, writer, n } = {}) {
  const msg = el(), body = el();
  const card = key && el({ dataset: { key } });
  if (card) card.querySelector = s => s === '.mg-msg' ? msg : s === '.mg-body' ? body : null;
  const button = mg && el({ dataset: { mg } });
  const t = el();
  t.closest = s => s === '.mg-card' ? card : s === '[data-mg]' ? button : s === 'button' ? button : s === '.mg-img' ? (img ? t : null)
    : s === '[data-mg-game]' ? (game ? el({ dataset: { mgGame: game } }) : null) : s === '[data-mg-writer]' ? (writer ? el({ dataset: { mgWriter: writer } }) : null)
    : s === '[data-n]' ? el({ dataset: { n } }) : null;
  return Object.assign(t, { msg, button });
}
function fakeEnv(items, extra = {}) {
  const calls = [];
  let sessions = extra.sessions || [];
  const env = {
    poll: LP, here: 'MYPC', wait: async () => {}, url: u => u + '?token=t', calls, opened: [], toasts: [],
    setSessions: s => { sessions = s; },
    openImages: (list, i, at) => env.opened.push({ list, i, at }), toast: t => env.toasts.push(t),
    api: async (p, body) => {
      calls.push([p, body]);
      if (p.startsWith('/api/mods/built')) return { items, all: items.length, cache_dir: '/mnt/hdd/gbox-cache/mods' };
      if (p === '/api/workers') return [{ name: 'MYPC', os: 'windows', online: true }, { name: 'spark', os: 'linux', online: true }, { name: 'old', os: 'windows', online: false }];
      if (p === '/api/jobs') return { id: 'j' + calls.length, state: 'succeeded', output: { session_id: 'w1-s9' } };
      if (p.startsWith('/api/sessions')) return sessions;
      if (p.startsWith('/api/requests/')) return { number: 5, title: 'Put HUcast in <MGS>', status: 'done', messages: [{ author: 'agent', text: 'Built it' }] };
      if (p.startsWith('/api/mods/') && p.includes('/thumb')) { if (extra.onShot) extra.onShot(); return { id: 'card1', shots: ['b'] }; }
      throw new Error('unexpected ' + p);
    },
    ...extra,
  };
  return env;
}
const many = Array.from({ length: 30 }, (_, i) => ({ ...CF, key: `cf3/m${i}`, name: `m${i}`, mod_title: `Mod ${i}`, built: 5000 + i, card_id: 'c' + i }));

test('renders the toolbar facets, a first page of cards newest first, and pages on Show more', async () => {
  const h = fakeHost(), env = fakeEnv([...many, PSO, VR]);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    assert.match(h.host.innerHTML, /<option value="pso">Phantasy Star Online \(1\)/);
    assert.match(h.host.innerHTML, /<option value="clayfighter_swap">clayfighter_swap \(30\)/);
    assert.match(h.host.innerHTML, /Play on <select data-mg-f="node"><option value="" selected>This PC<\/option><option value="MYPC">MYPC \(windows\)<\/option><option value="spark">spark \(linux\)/);
    assert.ok(!h.host.innerHTML.includes('value="old"'), 'offline PCs are not offered');
    assert.equal((h.grid().match(/class="mg-card"/g) || []).length, MG.PAGE);
    assert.ok(h.grid().indexOf('data-key="cf3/m29"') < h.grid().indexOf('data-key="cf3/m28"'), 'newest first');
    assert.match(h.parts['[data-mg-sum]'].textContent, /32 of 32 builds · \/mnt\/hdd\/gbox-cache\/mods/);
    assert.match(h.more(), /Show 8 more \(8 not shown\)/);
    await h.fire('click', target({ mg: 'more' }));
    assert.equal((h.grid().match(/class="mg-card"/g) || []).length, 32); assert.equal(h.more(), '');
    assert.equal(env.calls.filter(c => c[0] === '/api/mods/built').length, 1, 'one read through the shared cached poll');
  } finally { ctl.stop(); }
});

test('search, game / writer selects and chips filter the cards', async () => {
  const h = fakeHost(), env = fakeEnv([PSO, VR, CF]);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    ctl.onInput({ target: { dataset: { mgF: 'q' }, value: 'booma' } });
    assert.match(h.grid(), /pso\/cast_pso_ult/); assert.ok(!h.grid().includes('mgsvr_hucast'));
    ctl.onInput({ target: { dataset: { mgF: 'q' }, value: '' } });
    ctl.onInput({ target: { dataset: { mgF: 'writer' }, value: 'mgsvr' } });
    assert.ok(h.grid().includes('mgsvr/mgsvr_hucast') && !h.grid().includes('cf3/'));
    ctl.onInput({ target: { dataset: { mgF: 'writer' }, value: '' } });
    await h.fire('click', target({ game: 'cf3' }));
    assert.ok(h.grid().includes('cf3/cf_hucast_taffy') && !h.grid().includes('pso/'));
    assert.match(h.host.innerHTML, /<option value="cf3" selected>/);
    ctl.onInput({ target: { dataset: { mgF: 'game' }, value: 'zzz' } });
    assert.match(h.grid(), /No built mod matches these filters/);
  } finally { ctl.stop(); }
});

test('a picture click opens the pop-up with the card\'s pictures at the carousel position', async () => {
  const h = fakeHost(), env = fakeEnv([PSO]);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: PSO.key, mg: 'next' }));
    assert.match(h.grid(), /data-i="1"/);
    await h.fire('click', target({ key: PSO.key, img: true }));
    const o = env.opened[0];
    assert.equal(o.i, 1); assert.equal(o.list.length, 3); assert.deepEqual(o.at, [10, 20]);
    assert.equal(o.list[0].src, '/api/artifacts/' + 'a'.repeat(64) + '?token=t');
    assert.deepEqual(Object.keys(o.list[0]).sort(), ['name', 'src']);
  } finally { ctl.stop(); }
});

test('Play launches through @launch on this PC or the chosen PC; the saved moment is loaded after boot', async () => {
  const h = fakeHost(), env = fakeEnv([PSO, VR]);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    const t = target({ key: PSO.key, mg: 'play' });
    await h.fire('click', t);
    assert.deepEqual(env.calls.find(c => c[0] === '/api/jobs')[1], { tool: '@launch', input: { game_id: 'pso', mod: 'cast_pso_ult', node: 'MYPC' } });
    assert.equal(t.msg.textContent, 'Launched'); assert.equal(t.button.disabled, false);
    ctl.onInput({ target: { dataset: { mgF: 'node' }, value: 'spark' } });
    env.calls.length = 0;
    await h.fire('click', target({ key: VR.key, mg: 'moment' }));
    const jobs = env.calls.filter(c => c[0] === '/api/jobs').map(c => c[1]);
    assert.deepEqual(jobs[0].input, { game_id: 'mgsvr', mod: 'mgsvr_hucast', node: 'spark' });
    assert.deepEqual(jobs[1], { tool: 'session_op', input: { session_id: 'w1-s9', op: 'load_state', args: { slot: 3 } }, require_worker: 'w1' });
  } finally { ctl.stop(); }
});

test('a client can take over Play (desktop: the mod card path on this PC)', async () => {
  const h = fakeHost(), seen = [];
  const env = fakeEnv([VR], { play: async (m, how) => { seen.push([m.name, how]); } });
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: VR.key, mg: 'moment' }));
    assert.deepEqual(seen, [['mgsvr_hucast', { node: 'MYPC', moment: true }]]);
    assert.ok(!env.calls.some(c => c[0] === '/api/jobs'));
  } finally { ctl.stop(); }
});

test('Screenshot after launch: a frame of the running mod is attached to the card; nothing running = launch, wait, capture', async () => {
  const running = [{ session_id: 'w1-s1', state: 'running', game_id: 'mgsvr', mod: 'mgsvr_hucast', started: 5 },
                   { session_id: 'w1-s0', state: 'running', game_id: 'mgsvr', mod: 'other', started: 9 }];
  let h = fakeHost(), env = fakeEnv([VR], { sessions: running });
  let ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: VR.key, mg: 'shot' }));
    assert.ok(env.calls.some(c => c[0] === '/api/mods/card1/thumb?append=true&session_id=w1-s1'), JSON.stringify(env.calls));
    assert.ok(!env.calls.some(c => c[0] === '/api/jobs'), 'already running: no launch');
    assert.ok(env.calls.some(c => c[0] === '/api/mods/built?fresh=true'), 'the gallery rereads its pictures');
    assert.match(env.toasts.join(), /in-game picture added/);
  } finally { ctl.stop(); }
  h = fakeHost();
  let polls = 0;
  env = fakeEnv([VR]);
  const api = env.api;
  env.api = async (p, b) => { if (p.startsWith('/api/sessions') && ++polls > 2) return running; return api(p, b); };
  ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: VR.key, mg: 'shot' }));
    const order = env.calls.map(c => c[0]);
    assert.ok(order.indexOf('/api/jobs') >= 0 && order.indexOf('/api/jobs') < order.findIndex(p => p.includes('/thumb')));
    // nothing of the game runs: launched with swap off, so a game started meanwhile is never swapped silently
    assert.deepEqual(env.calls.find(c => c[0] === '/api/jobs')[1].input, { game_id: 'mgsvr', mod: 'mgsvr_hucast', node: 'MYPC', swap: false });
  } finally { ctl.stop(); }
});

// 2026-10-13: Screenshot on "Sonic as Snake" while "Sonic full cast" (same Twin Snakes disc) ran queued a session_swap
// of the operator's game. Another build running = the card asks; nothing changes until a second, explicit click.
const TS_SNAKE = { ...VR, key: 'ts/tts_sonic_as_snake', name: 'tts_sonic_as_snake', game_id: 'ts', title: 'MGS: The Twin Snakes',
  mod_title: 'Sonic as Snake', card_id: 'c-snake', shots: [], state_slot: null, tickets: [], last_launch: null };
const TS_CAST = { ...TS_SNAKE, key: 'ts/tts_sonic_full_cast', name: 'tts_sonic_full_cast', mod_title: 'Sonic full cast', card_id: 'c-cast' };
function tsEnv(sessions, extra = {}) {
  const env = fakeEnv([TS_SNAKE, TS_CAST], { sessions, ...extra });
  const base = env.api;
  env.api = async (p, b) => {
    if (/^\/api\/sessions\/[^/?]+\/swap$/.test(p)) { env.calls.push([p, b]); return { id: 'swapjob', state: 'running' }; }
    if (p === '/api/jobs/swapjob') { env.calls.push([p, b]); env.setSessions([{ session_id: 'w1-new', state: 'running', game_id: 'ts', mod: 'tts_sonic_as_snake', started: 20 }]);
      return { id: 'swapjob', state: 'succeeded', output: { session_id: 'w1-new' } }; }
    return base(p, b);
  };
  return env;
}
const tsRunning = [{ session_id: 'w1-op', state: 'running', game_id: 'ts', mod: 'tts_sonic_full_cast', title: 'MGS: The Twin Snakes', started: 10 }];
const shotCalls = env => env.calls.filter(c => /\/thumb|\/swap$|^\/api\/jobs$/.test(c[0]));

test('Screenshot with another build of the game running: no launch, no swap; the card offers the two choices', async () => {
  const h = fakeHost(), env = tsEnv(tsRunning);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    const t = target({ key: TS_SNAKE.key, mg: 'shot' });
    await h.fire('click', t);
    assert.deepEqual(shotCalls(env), [], 'nothing launched, swapped or captured on the first click');
    assert.match(t.msg.textContent, /Another build of this game is running: choose below/);
    const card = h.grid().slice(h.grid().indexOf('data-key="ts/tts_sonic_as_snake"'));
    assert.match(card, /is running <b>Sonic full cast<\/b>, not this build\. Nothing was changed\./);
    assert.match(card, /data-mg="shot-running"[^>]*>Capture from the running build instead \(adds to that build's card\)</);
    assert.match(card, /data-mg="shot-switch"[^>]*>Switch to this build</);
    assert.equal(ctl.st.choice.get(TS_SNAKE.key).session_id, 'w1-op');
    // second click: the frame goes to the running build's card, the running game is untouched
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot-running' }));
    assert.deepEqual(shotCalls(env).map(c => c[0]), ['/api/mods/c-cast/thumb?append=true&session_id=w1-op']);
    assert.ok(!ctl.st.choice.has(TS_SNAKE.key), 'the choice closes once done');
    assert.match(env.toasts.join(), /Sonic full cast: in-game picture added/);
  } finally { ctl.stop(); }
});

test('Screenshot choice "Switch to this build": a state-keeping swap of that session, then a frame of this build', async () => {
  const h = fakeHost(), env = tsEnv(tsRunning);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot' }));
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot-switch' }));
    const calls = shotCalls(env);
    assert.deepEqual(calls.map(c => c[0]), ['/api/sessions/w1-op/swap', '/api/mods/c-snake/thumb?append=true&session_id=w1-new']);
    assert.deepEqual(calls[0][1], { mod: 'tts_sonic_as_snake', keep_state: true });
  } finally { ctl.stop(); }
});

test('Screenshot choice: Cancel changes nothing; a choice made after the game changed is offered again', async () => {
  const h = fakeHost(), env = tsEnv(tsRunning);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot' }));
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot-cancel' }));
    assert.ok(!ctl.st.choice.has(TS_SNAKE.key) && !h.grid().includes('shot-switch'));
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot' }));
    env.setSessions([{ ...tsRunning[0], session_id: 'w1-other', started: 30 }]);       // the operator relaunched meanwhile
    const t = target({ key: TS_SNAKE.key, mg: 'shot-switch' });
    await h.fire('click', t);
    assert.deepEqual(shotCalls(env), [], 'a stale choice never swaps');
    assert.match(t.msg.textContent, /running game changed: choose again/);
    assert.equal(ctl.st.choice.get(TS_SNAKE.key).session_id, 'w1-other');
  } finally { ctl.stop(); }
});

test('Screenshot of the build that runs (staged copy, collection_mod or hot-swapped live model) = a frame now', async () => {
  for (const s of [{ mod: 'tts_sonic_as_snake~3f9a01' }, { mod: 'tts_sonic_as_snake~3f9a01', collection_mod: 'tts_sonic_as_snake' },
                   { mod: 'tts_sonic_full_cast', live_mod: 'tts_sonic_as_snake' }]) {
    const h = fakeHost(), env = tsEnv([{ session_id: 'w1-op', state: 'running', game_id: 'ts', started: 10, ...s }]);
    const ctl = MG.mount(h.host, env); await ctl.ready;
    try {
      await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot' }));
      assert.deepEqual(shotCalls(env).map(c => c[0]), ['/api/mods/c-snake/thumb?append=true&session_id=w1-op'], JSON.stringify(s));
    } finally { ctl.stop(); }
  }
  // the original game running: no card to capture into, so that choice is shown disabled; Switch stays offered
  const h = fakeHost(), env = tsEnv([{ session_id: 'w1-op', state: 'running', game_id: 'ts', mod: '', started: 10 }]);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: TS_SNAKE.key, mg: 'shot' }));
    assert.match(h.grid(), /data-mg="shot-running" disabled[^>]*>Capture from the running build instead \(no card for the original game\)/);
    assert.match(h.grid(), /data-mg="shot-switch"/);
  } finally { ctl.stop(); }
});

test('Open request: the thread shows under the card (web) or the client opens its inbox (desktop)', async () => {
  const h = fakeHost(), env = fakeEnv([VR, CF]);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    const t = target({ key: VR.key, mg: 'request', n: '5' });
    let box = null;
    const body = t.closest('.mg-card').querySelector('.mg-body');
    body.insertAdjacentHTML = () => { box = el(); };
    t.closest('.mg-card').querySelector = s => s === '.mg-body' ? body : s === '.mg-reqview' ? box : s === '.mg-msg' ? t.msg : null;
    await h.fire('click', t);
    assert.ok(env.calls.some(c => c[0] === '/api/requests/r5'));
    assert.match(box.innerHTML, /#5 Put HUcast in &#60;MGS&#62;/); assert.match(box.innerHTML, /Agent<\/b> Built it/);
    const t7 = target({ key: CF.key, mg: 'request', n: '7' });
    await h.fire('click', t7);
    assert.match(t7.msg.textContent, /#7 is not in the inbox/);
  } finally { ctl.stop(); }
  const h2 = fakeHost(), opened = [];
  const env2 = fakeEnv([VR], { openRequest: t => opened.push(t) });
  const ctl2 = MG.mount(h2.host, env2); await ctl2.ready;
  try {
    await h2.fire('click', target({ key: VR.key, mg: 'request', n: '5' }));
    assert.deepEqual(opened, [VR.tickets[0]]);
  } finally { ctl2.stop(); }
});

test('a failed read shows the error; an unchanged answer does not redraw', async () => {
  const h = fakeHost();
  const env = fakeEnv([]);
  env.api = async p => { if (p === '/api/workers') return []; throw new Error('502 Spark down'); };
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try { assert.match(h.grid(), /502 Spark down/); } finally { ctl.stop(); }
  const h2 = fakeHost(), env2 = fakeEnv([PSO]);
  const ctl2 = MG.mount(h2.host, env2); await ctl2.ready;
  try {
    h2.parts['[data-mg-grid]'].innerHTML = 'kept';
    await ctl2.load(0);
    assert.equal(h2.grid(), 'kept');
  } finally { ctl2.stop(); }
});

test('while the server indexes: "indexing…" in the summary and on unsized cards, faster cached polls, sizes as they arrive', async () => {
  const unsized = { ...PSO, size: null, own_size: null, files: null };
  const answers = [{ items: [], indexing: true, sizing: 0 },
                   { items: [unsized, CF], indexing: false, sizing: 1, cache_dir: '/mnt/hdd/gbox-cache/mods' },
                   { items: [PSO, CF], indexing: false, sizing: 0, cache_dir: '/mnt/hdd/gbox-cache/mods' }];
  const ages = [];
  let n = 0;
  const poll = { cachedRead: fetcher => ({ get: async maxAge => { ages.push(maxAge); return fetcher(); }, invalidate() {} }) };
  const h = fakeHost(), env = fakeEnv([], { poll });
  const api = env.api;
  env.api = async (p, b) => p === '/api/mods/built' ? answers[Math.min(n++, answers.length - 1)] : api(p, b);
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    assert.match(h.grid(), /Indexing the built mods…/);                       // a cold index: nothing listed yet
    assert.match(h.parts['[data-mg-sum]'].textContent, /0 of 0 builds · indexing…/);
    assert.equal(ctl.busy(), true);
    await ctl.tick();
    assert.equal(ages.at(-1), MG.TICK - 500, 'polls every tick while the index works');
    assert.match(h.grid(), /cast_pso_ult · built [^<]* · <span class="mg-sizing">size: indexing…<\/span>/);
    assert.ok(!h.grid().includes('· 0 B'), 'an unsized folder is not "0 B"');
    assert.match(h.parts['[data-mg-sum]'].textContent, /2 of 2 builds · \/mnt\/hdd\/gbox-cache\/mods · indexing… \(1 folder size to go\)/);
    await ctl.tick();
    assert.match(h.grid(), /1\.0 MB \(3\.00 GB with shared files\)/); assert.ok(!h.grid().includes('size: indexing'));
    assert.doesNotMatch(h.parts['[data-mg-sum]'].textContent, /indexing/);
    assert.equal(ctl.busy(), false);
    await ctl.tick();
    assert.equal(ages.at(-1), 30000, 'back to the slow cadence once the index is done');
    await h.fire('click', target({ mg: 'refresh' }));
    assert.ok(env.calls.some(c => c[0] === '/api/mods/built/refresh' && c[1]), 'Refresh asks for an index pass (POST)');
  } finally { ctl.stop(); }
});

// ------------------------------------------------------------------ #1656: rename on the card, favorites

test('favorites (★) list first, the ★ Favorites filter and its count', () => {
  const all = [VR, { ...PSO, favorite: true }, CF];
  assert.deepEqual(MG.filterMods(all, {sort:'favorites'}).map(m => m.name), ['cast_pso_ult', 'cf_hucast_taffy', 'mgsvr_hucast'], 'explicit favorites sort');
  assert.deepEqual(MG.filterMods(all, { fav: true }).map(m => m.name), ['cast_pso_ult']);
  assert.equal(MG.facets(all).favorites, 1);
  const bar = MG.toolbarHTML({ q: '', game: '', writer: '', node: '', fav: true }, MG.facets(all));
  assert.match(bar, /<input type="checkbox" data-mg-f="fav" checked> ★ Favorites \(1\)/);
  assert.equal(MG.buildPath({ game_id: 'g 1', name: 'a/b' }), '/api/builds/g%201/a%2Fb');
});

test('card: the title renames (click or ✎), ☆/★, "was" line, ⋯ options with Rename…', () => {
  const html = MG.cardHTML(PSO, { now: 2060 });
  assert.match(html, /<b class="mg-title" data-mg="rename" role="button" tabindex="0" title="Click to rename · folder cast_pso_ult">PSO: cast as &#60;Wrestlers&#62;<\/b>/);
  assert.match(html, /<button class="mg-ico" type="button" data-mg="rename" title="Rename this build \(the folder keeps its name\)" aria-label="Rename">✎<\/button>/);
  assert.match(html, /data-mg="fav" aria-pressed="false"[^>]*>☆</);
  assert.match(html, /data-mg="menu" aria-haspopup="menu" aria-expanded="false"/);
  assert.ok(!html.includes('mg-menu"') && !html.includes('mg-was'));
  const named = MG.cardHTML({ ...PSO, favorite: true, display_name: 'Booma Brawl', mod_title: 'Booma Brawl', original_title: 'PSO: cast as <Wrestlers>' },
                            { menu: true, note: 'Renamed' });
  assert.match(named, /class="mg-card mg-fav"/);
  assert.match(named, /data-mg="fav" aria-pressed="true"[^>]*>★</);
  assert.match(named, /<div class="mg-was mut">was “PSO: cast as &#60;Wrestlers&#62;”<\/div>/);
  assert.match(named, /<div class="mg-menu" role="menu" data-mg-menu="pso\/cast_pso_ult"><button[^>]*data-mg="rename"[^>]*>✎ Rename…<\/button>/);
  assert.match(named, /data-mg="fav">☆ Remove from favorites</);
  assert.match(named, /data-mg="unname">↺ Restore “PSO: cast as &#60;Wrestlers&#62;”</);
  assert.match(named, /data-mg="play">▶ Play</);
  assert.match(named, /<span class="mg-msg mut">Renamed<\/span>/);
  const field = MG.cardHTML(PSO, { renaming: true });
  assert.match(field, /<input class="mg-rename" data-mg-rename="pso\/cast_pso_ult" value="PSO: cast as &#60;Wrestlers&#62;" maxlength="120" aria-label="Build name"/);
  assert.match(field, /placeholder="cast_pso_ult"/, 'empty restores the writer title (here: no original_title, the folder)');
  assert.match(field, / data-nomic>/, 'the web shell\'s dictation wrapper would move (blur, so close) the field');
  assert.ok(!field.includes('class="mg-title"'));
});

function buildsApi(env, state = {}) {
  const base = env.api;
  env.sent = [];
  env.api = async (p, body, method) => {
    if (p.startsWith('/api/builds/') && !p.startsWith('/api/builds/local?')) {   // (this PC's copies: the download icon)
      env.sent.push([method, p, body]);
      if (state.fail) throw new Error('409 busy');
      if (p.endsWith('/favorite')) return { key: 'x', favorite: body.favorite };
      return { key: 'x', display_name: body.display_name, label: body.display_name || state.original || 'Original' };
    }
    return base(p, body);
  };
  return env;
}
const renameField = (key, value) => ({ closest: s => s === '[data-mg-rename]' ? { dataset: { mgRename: key }, value } : null });
const key = (k, t) => ({ key: k, target: t, preventDefault() {}, stopPropagation() {} });

test('rename on the card: a click on the title opens the field, Enter saves (PATCH), Esc cancels, empty restores', async () => {
  const h = fakeHost(), env = buildsApi(fakeEnv([PSO, VR]), { original: 'PSO: cast as <Wrestlers>' });
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: PSO.key, mg: 'rename' }));
    assert.equal(ctl.st.renaming, PSO.key);
    assert.match(h.grid(), /<input class="mg-rename" data-mg-rename="pso\/cast_pso_ult"/);
    // a poll while typing never redraws under the field
    const before = h.grid(); ctl.st.sig = ''; await ctl.load(0); assert.equal(h.grid(), before);
    // Esc: nothing sent, the title is back
    ctl.onKey(key('Escape', renameField(PSO.key, 'nope')));
    assert.equal(ctl.st.renaming, null); assert.match(h.grid(), /class="mg-title"/); assert.equal(env.sent.length, 0);
    // Enter: PATCH {display_name}, the card shows the new name and says the folder stays
    await h.fire('click', target({ key: PSO.key, mg: 'rename' }));
    ctl.onKey(key('Enter', renameField(PSO.key, '  Booma Brawl ')));
    await new Promise(r => setTimeout(r, 0));
    assert.deepEqual(env.sent[0], ['PATCH', '/api/builds/pso/cast_pso_ult', { display_name: 'Booma Brawl' }]);
    assert.match(h.grid(), /data-mg="rename" role="button"[^>]*>Booma Brawl<\/b>/);
    assert.match(h.grid(), /Renamed \(the folder stays cast_pso_ult\)/);
    assert.deepEqual(env.toasts.slice(-1), ['Renamed: Booma Brawl']);
    // the same name again: nothing sent
    await h.fire('click', target({ key: PSO.key, mg: 'rename' }));
    ctl.onKey(key('Enter', renameField(PSO.key, 'Booma Brawl')));
    assert.equal(env.sent.length, 1);
    // empty: "" restores the writer's title
    await h.fire('click', target({ key: PSO.key, mg: 'rename' }));
    await ctl.rename(PSO.key, '   ');
    assert.deepEqual(env.sent[1], ['PATCH', '/api/builds/pso/cast_pso_ult', { display_name: '' }]);
    assert.match(h.grid(), /Original name restored: PSO: cast as &#60;Wrestlers&#62;/);
    // leaving the field keeps what was typed (focusout), the title (a button) renames on Enter too
    ctl.onKey(key('Enter', { closest: s => s === '.mg-title' ? {} : s === '.mg-card' ? { dataset: { key: VR.key } } : null }));
    assert.equal(ctl.st.renaming, VR.key);
    ctl.onFocusOut({ target: renameField(VR.key, 'Snake in a suit') });
    await new Promise(r => setTimeout(r, 0));
    assert.deepEqual(env.sent[2], ['PATCH', '/api/builds/mgsvr/mgsvr_hucast', { display_name: 'Snake in a suit' }]);
  } finally { ctl.stop(); }
});

test('a failed rename says so on the card and keeps the old name', async () => {
  const h = fakeHost(), env = buildsApi(fakeEnv([PSO]), { fail: true });
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await ctl.rename(PSO.key, 'X');
    assert.match(h.grid(), /⚠ rename failed: 409 busy/);
    assert.match(h.grid(), />PSO: cast as &#60;Wrestlers&#62;<\/b>/);
  } finally { ctl.stop(); }
});

test('☆/★ toggles a favorite (PUT), the card moves first, the filter shows only favorites; right-click opens the options', async () => {
  const h = fakeHost(), env = buildsApi(fakeEnv([PSO, VR, CF]));
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    assert.ok(h.grid().indexOf('cf3/') < h.grid().indexOf('mgsvr/'), 'newest first while nothing is starred');
    await h.fire('click', target({ key: VR.key, mg: 'fav' }));
    assert.deepEqual(env.sent[0], ['PUT', '/api/builds/mgsvr/mgsvr_hucast/favorite', { favorite: true }]);
    assert.ok(h.grid().indexOf('cf3/') < h.grid().indexOf('mgsvr/'), 'newest remains first after favoriting');
    ctl.onInput({target:{dataset:{mgF:'sort'},value:'favorites'}});
    assert.ok(h.grid().indexOf('mgsvr/') < h.grid().indexOf('cf3/'), 'explicit favorites sort moves it first');
    assert.match(h.grid(), /class="mg-card mg-fav" data-key="mgsvr\/mgsvr_hucast"/);
    assert.match(h.host.innerHTML, /★ Favorites \(1\)/);
    ctl.onInput({ target: { dataset: { mgF: 'fav' }, type: 'checkbox', checked: true } });
    assert.ok(h.grid().includes('mgsvr/') && !h.grid().includes('pso/') && !h.grid().includes('cf3/'));
    ctl.onInput({ target: { dataset: { mgF: 'fav' }, type: 'checkbox', checked: false } });
    // right-click a card: its options menu; Rename… from there opens the field; a click elsewhere closes the menu
    ctl.onContext({ target: { closest: s => s === '.mg-card' ? { dataset: { key: PSO.key } } : null }, preventDefault() {}, stopPropagation() {} });
    assert.equal(ctl.st.menu, PSO.key); assert.match(h.grid(), /data-mg-menu="pso\/cast_pso_ult"/);
    await h.fire('click', target({ key: CF.key }));
    assert.equal(ctl.st.menu, null);
    await h.fire('click', target({ key: PSO.key, mg: 'menu' }));
    assert.equal(ctl.st.menu, PSO.key);
    await h.fire('click', target({ key: PSO.key, mg: 'rename' }));
    assert.equal(ctl.st.menu, null); assert.equal(ctl.st.renaming, PSO.key);
    ctl.onKey(key('Escape', renameField(PSO.key, '')));
    // ★ un-star from the menu
    await h.fire('click', target({ key: VR.key, mg: 'fav' }));
    assert.deepEqual(env.sent.slice(-1)[0], ['PUT', '/api/builds/mgsvr/mgsvr_hucast/favorite', { favorite: false }]);
    assert.ok(h.grid().indexOf('cf3/') < h.grid().indexOf('mgsvr/'));
  } finally { ctl.stop(); }
});

test('desktop: the Mods view passes the method (PATCH / PUT) through its IPC api; the main process honours it', () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
  const preload = fs.readFileSync(path.join(__dirname, '../clients/desktop/preload.js'), 'utf8');
  assert.match(desktop, /const api = async \(path, body, method\) => \{ const r = await gbox\.api\(path, body, method\);[^\n]*\r?\n\s*MODSG\.ctl = GBoxModsGallery\.mount/);
  assert.match(preload, /api: \(path, body, method\) => ipcRenderer\.invoke\("api", path, body, method\)/);
  assert.match(main, /ipcMain\.handle\("api", async \(_e, p, body, method\) =>/);
  assert.match(main, /async function api\(p, body, method\)/);
  for (const f of [main, preload]) assert.ok(!/[^\r]\n/.test(f), 'CRLF line endings kept');
});

test('both clients have a Mods view wired to the shared gallery', () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(desktop, /<button data-s="play" class="on">Play &amp; Library<\/button>\r?\n\s*<button data-s="mods"[^>]*>Mods<\/button>/);
  assert.match(desktop, /<section id="mods">[\s\S]*?<div id="modsgallery"><\/div>/);
  assert.match(desktop, /<script src="\.\.\/web\/viz\/mods-gallery\.js"><\/script>/);
  assert.ok(desktop.indexOf('live-poll.js') < desktop.indexOf('mods-gallery.js'));
  assert.match(desktop, /if \(b\.dataset\.s === "mods"\) modsGalleryOpen\(\);/);
  assert.match(desktop, /GBoxModsGallery\.mount\(\$\("#modsgallery"\), \{ api, poll: GBoxLivePoll/);
  assert.match(desktop, /openImages: \(list, i, at\) => texPopOpen\(list, i, at\)/);
  assert.match(desktop, /return modPlay\(m\.mod_title \? \{ \.\.\.card, title: m\.mod_title \} : card, moment && card\.state_slot != null \? "moment" : "play"\)/);
  assert.match(web, /const tabs = \{ Library: library, Mods: modsView,/);
  assert.match(web, /<script src="\/live-poll\.js"><\/script>\r?\n(?:<script src="\/viz\/character-popup\.js"><\/script>\r?\n)?<script src="\/viz\/mods-gallery\.js"><\/script>/);
  assert.match(web, /openImages: \(list, i\) => lbOpen\(null, list, i\)/);
  assert.match(web, /poll: window\.GBoxLivePoll/);
  for (const f of [desktop, web]) assert.ok(!/[^\r]\n/.test(f), 'CRLF line endings kept');
});


test('#2393: a build report opens with its id and flagged, a launch failure with its id (neither is in m.tickets)', async () => {
  const REP = { ...CF, key: 'cf3/cf_reported', name: 'cf_reported', tickets: [], reported: { number: 9, id: 'r9' },
                launch_report: { number: 11, request_id: 'r11', label: 'core crashed', count: 1, verified: false } };
  const h = fakeHost(), opened = [];
  const env = fakeEnv([REP], { openRequest: t => opened.push(t) });
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await h.fire('click', target({ key: REP.key, mg: 'request', n: '9' }));
    await h.fire('click', target({ key: REP.key, mg: 'request', n: '11' }));
    await h.fire('click', target({ key: REP.key, mg: 'request', n: '12' }));
  } finally { ctl.stop(); }
  assert.deepEqual(opened, [{ number: 9, id: 'r9', build_report: true }, { number: 11, id: 'r11' }, { number: 12 }]);
});

test('#2393: the desktop opens a build report as its three.js presentation', () => {
  const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  const a = html.indexOf('async function modsGalleryRequest(t)');
  const fn = html.slice(a, html.indexOf('// A click on the docked native game window', a));
  assert.match(fn, /if \(t\.build_report\) return reportStoryOpen\(t\.id\);/);
  assert.match(fn, /if \(!t\.id\) \{ toast\(/);
});
