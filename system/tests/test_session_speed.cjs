const {test} = require('node:test');
const assert = require('node:assert/strict');
const Speed = require('../clients/web/viz/session-speed.js');

test('active fast-forward clears with one off command; double clicks and stale polls cannot re-enable it', async () => {
  let resolve, calls = 0, latest;
  const ctl = Speed.create({ command: () => { calls++; return new Promise(r => resolve = r); }, render: s => latest = s, report() {} });
  ctl.update({supported:true, on:true, source:'emulator'});
  const old = ctl.revision();
  const pending = ctl.off(); await ctl.off();
  assert.equal(calls, 1); assert.equal(latest.on, true); assert.equal(latest.busy, true);
  resolve({supported:true, on:false, source:'emulator'}); await pending;
  ctl.update({supported:true, on:true}, old);
  assert.equal(latest.on, false); assert.equal(latest.busy, false);
});

test('failed or unconfirmed off retains the indicator and allows retry; unknown speed also has recovery', async () => {
  let latest, failure, reply = {};
  const ctl = Speed.create({command: async()=>reply, render:s=>latest=s, report:(s,e)=>failure=e});
  ctl.update({supported:true, on:true}); await ctl.off();
  assert.equal(latest.on,true); assert.equal(failure,true); assert.equal(latest.busy,false);
  ctl.update({supported:true, on:null}); reply={supported:true,on:false,source:'tracked'};
  await ctl.off(); assert.equal(latest.on,false); assert.equal(failure,false);
});
