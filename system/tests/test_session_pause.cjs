const { test } = require('node:test');
const assert = require('node:assert/strict');
const { create, paused } = require('../clients/web/viz/session-pause.js');

function emulator(initial = false) {
  let state = initial;
  const commands = [], paints = [], messages = [];
  const io = {
    read: async () => ({ state: state ? 'PAUSED' : 'PLAYING', running: true }),
    command: async op => { commands.push(op); state = op === 'pause'; },
    render: paint => paints.push(paint), report: (text, error) => messages.push({ text, error }), delay: async () => {}
  };
  return { io, commands, paints, messages, externalPause: value => { state = value; } };
}

test('clicks pause and then resume a running emulator', async () => {
  const e = emulator(), control = create(e.io);
  await control.refresh(); await control.toggle();
  assert.equal(e.paints.at(-1).paused, true);
  await control.toggle();
  assert.deepEqual(e.commands, ['pause', 'resume']);
  assert.deepEqual(e.paints.at(-1), { paused: false, busy: false });
});

test('a game already paused outside this button resumes on its next click', async () => {
  const e = emulator(), control = create(e.io);
  await control.refresh(); e.externalPause(true); await control.toggle();
  assert.deepEqual(e.commands, ['resume']);
});

test('delayed status replies do not falsely claim a failed pause', async () => {
  const e = emulator(); let reads = 0, sent = false;
  e.io.command = async () => { sent = true; };
  e.io.read = async () => ({ state: sent && ++reads >= 3 ? 'PAUSED' : 'PLAYING' });
  await create(e.io).toggle();
  assert.equal(e.paints.at(-1).paused, true);
  assert.equal(e.messages.at(-1).error, false);
});

test('a dropped pause command reports failure and keeps the actual icon', async () => {
  const e = emulator(); e.io.command = async () => {};
  await create(e.io).toggle();
  assert.equal(e.messages.at(-1).error, true);
  assert.deepEqual(e.paints.at(-1), { paused: false, busy: false });
});

test('two clicks while the first command is pending send only one command', async () => {
  const e = emulator(); let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const command = e.io.command; e.io.command = async op => { await pending; return command(op); };
  const control = create(e.io), first = control.toggle();
  await control.toggle(); finish(); await first;
  assert.deepEqual(e.commands, ['pause']);
});

test('unsupported, stopped and failed commands never claim success', async () => {
  for (const read of [async () => ({}), async () => ({ running: false, paused: false })]) {
    const e = emulator(); e.io.read = read; await create(e.io).toggle();
    assert.deepEqual(e.commands, []); assert.equal(e.messages.at(-1).error, true);
    assert.equal(e.paints.at(-1).busy, false);
  }
  const e = emulator(true); e.io.command = async () => { throw new Error('Worker unavailable'); };
  await create(e.io).toggle();
  assert.equal(e.paints.at(-1).paused, true); assert.equal(e.messages.at(-1).error, true);
});

test('Yuzu and RPCS3 boolean pause states are supported', () => {
  assert.equal(paused({ paused: true }), true);
  assert.equal(paused({ paused: false }), false);
});

test('an older background read cannot overwrite a newly confirmed toggle', async () => {
  const e = emulator(); let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  let first = true; const read = e.io.read;
  e.io.read = async () => { if (first) { first = false; return pending; } return read(); };
  const control = create(e.io), refresh = control.refresh();
  await control.toggle(); finish({ state: 'PLAYING' }); await refresh;
  assert.equal(e.paints.at(-1).paused, true);
});

test('the icon flips before the emulator answers and a confirming reply needs no polling', async () => {
  const e = emulator(); let reads = 0, finish;
  const read = e.io.read; e.io.read = async () => { reads++; return read(); };
  const pending = new Promise(resolve => { finish = resolve; });
  const command = e.io.command;
  e.io.command = async op => { await pending; await command(op); return { state: 'PAUSED', running: true }; };
  const click = create(e.io).toggle();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(e.paints.at(-1), { paused: true, busy: true });
  assert.deepEqual(e.commands, []);
  finish(); await click;
  assert.equal(reads, 1);
  assert.deepEqual(e.paints.at(-1), { paused: true, busy: false });
  assert.equal(e.messages.at(-1).error, false);
});

test('a stale command reply falls back to reading the emulator', async () => {
  const e = emulator(); let reads = 0;
  const read = e.io.read; e.io.read = async () => { reads++; return read(); };
  const command = e.io.command;
  e.io.command = async op => { await command(op); return { state: 'PLAYING' }; };
  await create(e.io).toggle();
  assert.deepEqual(e.commands, ['pause']);
  assert.equal(reads, 2);
  assert.deepEqual(e.paints.at(-1), { paused: true, busy: false });
});
