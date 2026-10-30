const {test} = require('node:test');
const assert = require('node:assert/strict');
const {create} = require('../clients/desktop/guest-state.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const reads = [], timers = [];
  const reader = create({read: guest => new Promise((resolve,reject) => reads.push({guest,resolve,reject})),
    schedule: fn => (timers.push(fn), timers.length - 1), cancel: () => {}});
  return {reader, reads, timers};
}
test('busy guest returns promptly to all shell callers without accumulating IPC', async () => {
  const x=fixture(), guest={};
  const pending=Array.from({length:100},()=>x.reader.get(guest));
  await flush(); assert.equal(x.reads.length,1);
  x.timers[0]();
  for(const answer of await Promise.all(pending)) assert.deepEqual(answer,{});
  for(let i=0;i<100;i++) assert.deepEqual(await x.reader.get(guest),{});
  assert.equal(x.reads.length,1,'a deadline must not spawn another hung IPC');
  x.reads[0].resolve({session:'late'}); await flush();
  const next=x.reader.get(guest); await flush(); assert.equal(x.reads.length,2);
  x.reads[1].resolve({session:'current'}); assert.equal((await next).session,'current');
});
test('navigation rejects an old-frame result and allows the new frame to answer', async () => {
  const x=fixture(), guest={};
  const old=x.reader.get(guest); await flush();
  x.reader.reset(guest);
  const current=x.reader.get(guest); await flush();
  x.reads[0].resolve({session:'old'}); assert.deepEqual(await old,{});
  assert.equal(x.reader.get(guest),current,'old completion must not clear new ownership');
  x.reads[1].resolve({session:'new'}); assert.equal((await current).session,'new');
});
test('separate guest elements cannot share session state', async () => {
  const x=fixture(); const a=x.reader.get({}), b=x.reader.get({}); await flush();
  x.reads[0].resolve({session:'a'}); x.reads[1].resolve({session:'b'});
  assert.equal((await a).session,'a'); assert.equal((await b).session,'b');
});
test('missing, disposed and synchronously failing guests are harmless', async () => {
  const x=fixture(); assert.deepEqual(await x.reader.get(null),{});
  const pending=x.reader.get({}); await flush(); x.reads[0].reject(Error('disposed'));
  assert.deepEqual(await pending,{});
  assert.deepEqual(await create({read(){throw Error('gone');}}).get({}),{});
});
