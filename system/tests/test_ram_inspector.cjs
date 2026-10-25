// clients/web/viz/ram-inspector.js: the session header's RAM inspector (Live / Events / Hex / Search). Server side:
// tests/test_ram_inspector.py. The panel's logic runs here without a DOM (create + the pure renderers).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const R = require('../clients/web/viz/ram-inspector.js');

test('PS4 hex addresses and pointer following preserve all address bits', async () => {
  const address = 0x900000000, calls = [];
  assert.match(R.hexHTML(R.hexRows('aabbccdd', address)), /900000000/);
  assert.deepEqual(R.word('0400000009000000', 4, false, 8), { at: 0, value: address + 4 });
  assert.equal(R.word('ffffffffffffffff', 0, false, 8), null);
  const ctl = R.create({ sid: 'ps4-session', api: async path => {
    calls.push(path);
    return { address, hex: '0400000009000000', big_endian: false, pointer_size: 8 };
  }});
  await ctl.readHex({ address });
  await ctl.follow(4);
  assert.match(calls[0], /address=0x900000000/);
  assert.match(calls[1], /address=0x900000004/);
});

test('PS4 floating inspector does not invent a RAM address', async () => {
  const calls = [];
  const ctl = R.create({sid: 'ps4-session', api: async path => { calls.push(path); return {platform: 'ps4'}; }});
  assert.equal(await ctl.readHex(), null);
  assert.equal(calls.length, 1);
  assert.match(calls[0], /\/ram\/live/);
  assert.match(ctl.S.hex.error, /Enter a process address/);
});

const LIVE = {
  session_id: 'w1-re4', map: 'G4BE08', title: 'Resident Evil 4 (GameCube, NTSC-U)', hz: 10, reads: 3, bytes: 4100, age_s: 0.04,
  groups: { game: 'Where the game is', merc: 'The Mercenaries', enemies: 'Live Ganados' },
  reader: { kind: 'shm', how: 'Dolphin shared memory (/proc/4242/mem, read-only, no halt)' },
  rows: [
    { name: 'game.room', group: 'game', type: 'u16', value: 1024, display: 'Mercenaries: Pueblo (village) (0x0400)', label: 'Mercenaries: Pueblo (village)', address: '0x8027F778' },
    { name: 'merc.timer', group: 'merc', type: 'u32', value: 87.3, display: '87.3 s', address: '0x80279308' },
    { name: 'merc.combo', group: 'merc', type: 'u32', value: 12, display: '12', address: '0x80213954' },
    { name: 'player.hp', group: 'player', type: 's16', value: null, display: '?', error: 'null pointer: 0x802B2280 holds 0x00000000', address: null },
    { name: 'enemies', group: 'enemies', type: 'struct', value: null, display: '2 live of 80', address: '0x810D3000',
      sub: { pos: { type: 'f32' }, hp: { type: 's16' } },
      rows: [{ index: 3, address: '0x810D5A60', pos: [1000.25, 0, 4000.5], hp: 1000 }, { index: 7, address: '0x810D9220', pos: [5000, 0, 2000], hp: 300 }] }],
  events: [{ seq: 1, t: 1792534000.25, field: 'pad.held', old: 288, new: 256, old_label: 'R, A', new_label: 'A', frame: 1 }],
  seq: 1, error: null, map_error: null };

test('the header button', () => {
  const h = R.button('w1-<x>');
  assert.match(h, /id="ramibtn" data-sid="w1-&#60;x&#62;"/);
  assert.match(h, /aria-label="RAM inspector"/);
  assert.match(h, /aria-pressed="false"/);
  assert.equal(R.mount({ querySelector: () => null }, { sid: 's', api: async () => ({}) }), null);
});

test('live rows are grouped as the map orders them and a changed value is marked', () => {
  const first = R.liveModel(LIVE, null);
  assert.deepEqual(first.groups.map(g => g.name), ['game', 'merc', 'enemies', 'player']);   // map groups first, then the rest
  assert.equal(first.groups[1].rows[0].short, 'timer');
  assert.ok(first.groups.flatMap(g => g.rows).every(r => !r.changed));
  assert.equal(first.foot, 'Resident Evil 4 (GameCube, NTSC-U) · shm read · 10 Hz · 3 reads · 4 KiB · 40 ms old');
  const next = R.liveModel({ ...LIVE, rows: LIVE.rows.map(r => r.name === 'merc.timer' ? { ...r, value: 86.9, display: '86.9 s' } : r) }, first.shown);
  const changed = next.groups.flatMap(g => g.rows).filter(r => r.changed).map(r => r.name);
  assert.deepEqual(changed, ['merc.timer']);
  const html = R.liveHTML(next);
  assert.match(html, /<div class="ri-row chg"[^>]*><span class="ri-n">timer<\/span><b>86\.9 s<\/b><a href="#" class="ri-addr" data-addr="0x80279308"/);
  assert.match(html, /<div class="ri-row err"[^>]*title="player\.hp · s16 · null pointer: 0x802B2280 holds 0x00000000"><span class="ri-n">hp<\/span><b>\?<\/b>/);
  assert.match(html, /<th>#<\/th><th>pos<\/th><th>hp<\/th>/);
  assert.match(html, /<td>1000\.25, 0, 4000\.5<\/td><td>1000<\/td>/);
  assert.match(R.liveHTML(R.liveModel({ rows: [], map_error: 'no RAM map for this game yet' }, null)), /no RAM map for this game yet/);
});

test('struct cells follow the sub-field format and the same events are not counted twice', async () => {
  const rows = [{ name: 'enemies', group: 'enemies', display: '1 live of 80', address: '0x810D3000',
    sub: { flags: { type: 'u32', format: 'hex' }, facing: { type: 'f32', format: 'deg' } },
    rows: [{ index: 3, address: '0x810D5A60', flags: 33562727, facing: Math.PI / 2 }] }];
  const html = R.liveHTML(R.liveModel({ rows }, null));
  assert.match(html, /<td>0x2002067<\/td><td>90°<\/td>/);
  const { api } = fakeApi({ '/api/sessions/w1-re4/ram/live': LIVE });       // a server that ignores since
  const ctl = R.create({ sid: 'w1-re4', api });
  await ctl.refreshLive(); await ctl.refreshLive();
  assert.deepEqual(ctl.S.events.map(e => e.seq), [1]);
  const restarted = R.create({ sid: 'w1-re4', api: async () => ({ ...LIVE, seq: 0, events: [] }) });
  restarted.S.seq = 5; restarted.S.events = [{ seq: 5 }];
  await restarted.refreshLive();
  assert.deepEqual([restarted.S.seq, restarted.S.events.length], [0, 0]);        // the server started over
});

test('events read old → new by their labels, with the frame of that moment', () => {
  assert.equal(R.eventText(LIVE.events[0]), 'pad.held: R, A → A');
  assert.equal(R.eventText({ field: 'game.room', old: 1024, new: 1025, old_label: 'Mercenaries: Pueblo (village)', new_label: null }),
    'game.room: Mercenaries: Pueblo (village) → 1025');
  const h = R.eventsHTML(LIVE.events, fid => `/api/sessions/w1-re4/ram/frames/${fid}.jpg?token=t`);
  assert.match(h, /<b>pad\.held: R, A → A<\/b><a href="\/api\/sessions\/w1-re4\/ram\/frames\/1\.jpg\?token=t" target="_blank"/);
  assert.match(R.eventsHTML([], null), /No state changes yet/);
});

test('hex rows mark the bytes that changed and a click follows the word as a pointer', () => {
  const rows = R.hexRows('810d3000' + '41'.repeat(12) + '00ff', 0x802B3040, '810d3001' + '41'.repeat(14));
  assert.equal(rows.length, 2);
  assert.equal(rows[0].ascii, '..0.AAAAAAAAAAAA');
  assert.deepEqual(rows[0].bytes.filter(b => b.chg).map(b => b.o), [3]);
  assert.deepEqual(rows[1].bytes.map(b => b.chg), [true, true]);
  const h = R.hexHTML(rows);
  assert.match(h, /<span class="ri-ha">802B3040<\/span> <span class="ri-hb" data-o="0">81<\/span>/);
  assert.match(h, /<span class="ri-hb chg" data-o="3">00<\/span>/);
  assert.deepEqual(R.word('810d3000aabbccdd', 6), { at: 4, value: 0xAABBCCDD });
  assert.deepEqual(R.word('810d3000', 1, false), { at: 0, value: 0x00300D81 });
  assert.equal(R.word('810d', 0), null);
});

test('candidates show their values per label and Add to map drafts the enum from them', () => {
  const st = { active: true, type: 'u8', base: 0x80000000, size: 0x1800000, candidates: 3, mode: 'sparse', memory: 3 << 20,
    samples: { on: 6, off: 7, plain: 1 }, tolerance: 0,
    candidates_list: [{ address: 0x80456789, address_hex: '0x80456789', value: 0, on: [{ value: 3, n: 4 }, { value: 5, n: 2 }], off: [{ value: 0, n: 7 }] }],
    auto: { source: 'screen_prompt', button: 'a', label: 'off', samples: { on: 6, off: 7 }, discarded: 2, note: 'no prompt', running: true } };
  assert.equal(R.searchLine(st), 'u8 · 0x80000000 + 24 MiB · 3 candidates (sparse) · on 6 · off 7 · plain 1 · 3 MiB');
  assert.equal(R.searchLine({ active: false }), 'No search running.');
  assert.equal(R.autoLine(st.auto), 'Auto: screen prompt A · now off · sampled on 6 / off 7 · 2 not confirmed · no prompt');
  assert.equal(R.searchLine({ ...st, tolerance: 2 }), 'u8 · 0x80000000 + 24 MiB · 3 candidates (sparse) · on 6 · off 7 · plain 1 · 2 mislabels ok · 3 MiB');
  const loose = R.candidatesHTML({ ...st, candidates_list: [{ ...st.candidates_list[0], mislabeled: 1 }] });
  assert.match(loose, /<th title="labeled samples on the wrong side">±<\/th>/);
  assert.match(loose, /<td>0 ×7<\/td><td>1<\/td>/);
  const h = R.candidatesHTML(st);
  assert.match(h, /<td>3 ×4 · 5 ×2<\/td><td>0 ×7<\/td>/);
  assert.match(h, /<button class="ri-b ri-add" data-i="0"/);
  assert.equal(R.enumDraft(st.candidates_list[0]), '3 = \n5 = \n0 = ');
  assert.deepEqual(R.parseEnum('3 = TAKE\n5 = JUMP OVER\n0 =\n0x10: KICK\nnot a line'), { 3: 'TAKE', 5: 'JUMP OVER', 16: 'KICK' });
  assert.match(R.candidatesHTML({ ...st, candidates: 2000000, candidates_list: [] }), /Too many candidates to list/);
  assert.equal(R.num('0x80000000'), 0x80000000);
  assert.ok(Number.isNaN(R.num('zz')));
});

function fakeApi(answers) {
  const calls = [];
  const api = async (path, body, method) => {
    calls.push({ path, body, method });
    const key = Object.keys(answers).find(k => path.startsWith(k) && (answers[k].method || 'any') !== 'never');
    const a = answers[key];
    if (a instanceof Error) throw a;
    return typeof a === 'function' ? a(path, body, method) : a;
  };
  return { api, calls };
}

test('the panel polls live values and keeps the events after the last seq it saw', async () => {
  let n = 0;
  const { api, calls } = fakeApi({ '/api/sessions/w1-re4/ram/live': () => (++n === 1 ? LIVE
    : { ...LIVE, events: [{ seq: 2, t: 1792534001, field: 'game.room', old: 1024, new: 1025 }], seq: 2 }) });
  const renders = [];
  const ctl = R.create({ sid: 'w1-re4', api, render: (S, what) => renders.push(what) });
  await ctl.refreshLive();
  await ctl.refreshLive();
  assert.deepEqual(calls.map(c => c.path), ['/api/sessions/w1-re4/ram/live?since=0', '/api/sessions/w1-re4/ram/live?since=1']);
  assert.deepEqual(ctl.S.events.map(e => e.seq), [1, 2]);
  assert.equal(ctl.S.seq, 2);
  assert.deepEqual(renders, ['live', 'live']);
});

test('hex reads an address or a pointer chain, and follows a word', async () => {
  const { api, calls } = fakeApi({
    '/api/sessions/w1-re4/ram/hex?pointer': { address: 0x810D3094, hex: '447a0000', chain: [{ at: '0x802B3044', value: '0x810D3000', offset: '0x94' }], big_endian: true },
    '/api/sessions/w1-re4/ram/hex?address': (p) => ({ address: parseInt(p.match(/address=0x([0-9A-F]+)/)[1], 16), hex: '810d3000', chain: [], big_endian: true }) });
  const ctl = R.create({ sid: 'w1-re4', api });
  await ctl.readHex({ address: 0x802B3044, length: 64 });
  assert.equal(calls[0].path, '/api/sessions/w1-re4/ram/hex?address=0x802B3044&length=64');
  await ctl.follow(2);
  assert.equal(calls[1].path, '/api/sessions/w1-re4/ram/hex?address=0x810D3000&length=64');
  await ctl.readHex({ pointer: '0x802B3044,0x94' });
  assert.equal(calls[2].path, '/api/sessions/w1-re4/ram/hex?pointer=0x802B3044%2C0x94&length=64');
  assert.equal(ctl.S.hex.at, 0x810D3094);
  assert.equal(ctl.S.hex.chain.length, 1);
});

test('search: start, labels, filters, a labeler, add to map, end', async () => {
  const st = { active: true, type: 'u8', base: 0x80000000, size: 0x1800000, candidates: 1, mode: 'sparse', samples: { on: 1, off: 1, plain: 1 },
    candidates_list: [{ address: 0x80456789, address_hex: '0x80456789', value: 3, on: [{ value: 3, n: 1 }], off: [{ value: 0, n: 1 }] }] };
  const { api, calls } = fakeApi({
    '/api/sessions/w1-re4/ram/search/auto': { source: 'field' },
    '/api/sessions/w1-re4/ram/search/sample': st,
    '/api/sessions/w1-re4/ram/search?limit': st,
    '/api/sessions/w1-re4/ram/search': (p, b, m) => (m === 'DELETE' ? { active: false } : st),
    '/api/sessions/w1-re4/ram/promote': (p, b) => ({ map: 'G4BE08', field: { name: b.name }, overlay: '/data/ram_maps/G4BE08-ram.json' }) });
  const errors = [];
  const ctl = R.create({ sid: 'w1-re4', api, onError: e => errors.push(e) });
  await ctl.start('u8', null, null, 0);
  await ctl.sample('on');
  await ctl.sample(null);
  await ctl.filter('range', '', '0x10', '20');
  await ctl.auto({ source: 'field', field: 'pad.held', cond: { ne: 0, mask: 256 } });
  assert.deepEqual(calls.map(c => [c.path, c.body]), [
    ['/api/sessions/w1-re4/ram/search', { type: 'u8' }],
    ['/api/sessions/w1-re4/ram/search/sample', { label: 'on' }],
    ['/api/sessions/w1-re4/ram/search/sample', {}],
    ['/api/sessions/w1-re4/ram/search/sample', { op: 'range', lo: '0x10', hi: '20' }],
    ['/api/sessions/w1-re4/ram/search/auto', { source: 'field', field: 'pad.held', cond: { ne: 0, mask: 256 } }],
    ['/api/sessions/w1-re4/ram/search?limit=60', undefined]]);
  assert.equal(await ctl.promote(st.candidates_list[0], { name: 'Prompt Action' }), null);
  assert.match(errors.at(-1), /Name it like group\.name/);
  const out = await ctl.promote(st.candidates_list[0], { name: 'prompt.action', description: 'the action offered', enum: '3 = TAKE\n0 = none' });
  assert.equal(out.map, 'G4BE08');
  assert.deepEqual(calls.at(-1).body, { name: 'prompt.action', type: 'u8', address: 0x80456789, description: 'the action offered', group: '',
    enum: { 3: 'TAKE', 0: 'none' } });
  await ctl.end();
  assert.deepEqual(calls.at(-1), { path: '/api/sessions/w1-re4/ram/search', body: undefined, method: 'DELETE' });
  assert.deepEqual(ctl.S.search, { active: false });
});

test('a failed request shows its message and the panel keeps going', async () => {
  const { api } = fakeApi({ '/api/sessions/w1-re4/ram/live': new Error('409 This session has ended') });
  const renders = [];
  const ctl = R.create({ sid: 'w1-re4', api, render: (S, what) => renders.push([what, S.error]) });
  assert.equal(await ctl.refreshLive(), null);
  assert.deepEqual(renders, [['error', '409 This session has ended']]);
});
