const { test } = require('node:test');
const assert = require('node:assert/strict');
const { create, message } = require('../clients/web/viz/session-presentation.js');

test('ended native session retires the view once without restarting anything', async () => {
  let ends = 0; const frames = [], timers = [];
  const control = create({ read: async () => ({ state:'ended',local_window:true }),
    render: value => frames.push(value), ended: () => ends++, setTimer: f => timers.push(f) });
  await control.poll(); await control.poll();
  assert.equal(ends,1); assert.equal(timers.length,0);
  assert.match(frames[0].text,/ended/);
});
test('an observation failure or offline worker is not proof the game ended', async () => {
  let ends = 0, result, fail = true; const timers = [];
  const control = create({ read: async () => { if (fail) throw Error('timeout'); return { state:'running',worker_online:false }; },
    render: v => result=v, ended: () => ends++, setTimer: f => timers.push(f) });
  await control.poll(); assert.match(result.text,/Retrying/); assert.equal(ends,0);
  fail=false; await timers.shift()(); assert.match(result.text,/Worker offline/); assert.equal(ends,0);
});
test('navigating away ignores an in-flight reply and schedules no more polling', async () => {
  let reply, present=true, rendered=0, ended=0, scheduled=0;
  const control=create({read:()=>new Promise(r=>reply=r),current:()=>present,
    render:()=>rendered++,ended:()=>ended++,setTimer:()=>scheduled++});
  const pending=control.poll();present=false;reply({state:'ended'});await pending;
  assert.equal(rendered+ended+scheduled,0);
});
test('unknown, stale and observed black frames describe evidence, not successful gameplay', () => {
  assert.match(message({state:'running',age_s:null}),/unverified/);
  assert.match(message({state:'running',age_s:50}),/No recent game frame/);
  assert.match(message({state:'running',gameplay_state:'black_screen'}),/unverified/);
  assert.equal(message({state:'running',age_s:null,local_window:true}),'');
});
