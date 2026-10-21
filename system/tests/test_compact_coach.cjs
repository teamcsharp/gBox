const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('../clients/desktop/compact-coach');
const A = require('../clients/web/viz/autoplay-coach');

function fixture() {
  const mounts = [], gates = [], shown = [], focus = [];
  const coach = { html: sid => `coach:${sid}`, mount(host, options) {
    const control = { input: { setAttribute() {} }, disposed: false, dispose() { this.disposed = true; } };
    mounts.push({ host, options, control }); return control;
  }};
  const host = { innerHTML: '', contains: value => value === 'inside' };
  const ctl = C.create({ coach, api() {}, show: x => shown.push(x), gateInput: x => gates.push(x), focusApp: () => focus.push(true) });
  return { ctl, mounts, host, gates, shown, focus };
}

test('compact coaching pins its exact session and keeps the same mounted draft across aspect redraws', () => {
  const x = fixture();
  x.ctl.update({ on: true, sid: 'worker-selected', aspect: 1 }, x.host);
  x.mounts[0].control.input.value = 'aim at the exposed enemy';
  x.ctl.update({ on: true, sid: 'worker-selected', aspect: 16/9 }, x.host);
  assert.equal(x.mounts.length, 1);
  assert.equal(x.mounts[0].options.sid, 'worker-selected');
  assert.equal(x.mounts[0].options.idempotent, true);
  assert.equal(x.mounts[0].control.input.value, 'aim at the exposed enemy');
});

test('typing gates game input and keeps the topbar visible; capture tracking keeps it visible after blur', () => {
  const x = fixture(); x.ctl.update({ on: true, sid: 's' }, x.host);
  x.host.onfocusin(); assert.deepEqual(x.gates, [true]); assert.equal(x.focus.length, 1);
  assert.equal(x.ctl.pinned(), true);
  x.host.onfocusout({ relatedTarget: 'inside' }); assert.deepEqual(x.gates, [true]);
  x.mounts[0].options.onState({ state: 'pending' });
  x.host.onfocusout({ relatedTarget: null });
  assert.deepEqual(x.gates, [true, false]); assert.equal(x.ctl.pinned(), true);
  x.mounts[0].options.onState({ state: 'done' }); assert.equal(x.ctl.pinned(), false);
  assert.equal(x.shown.at(-1), false);
});

test('session changes and leaving PiP dispose the old watcher and release typing focus', () => {
  const x = fixture(); x.ctl.update({ on: true, sid: 'first' }, x.host); x.host.onfocusin();
  x.ctl.update({ on: true, sid: 'second' }, x.host);
  assert.equal(x.mounts[0].control.disposed, true); assert.deepEqual(x.gates, [true, false]);
  assert.equal(x.ctl.session(), 'second'); assert.equal(x.mounts[1].options.sid, 'second');
  x.ctl.update({ on: false, sid: 'second' }, x.host);
  assert.equal(x.mounts[1].control.disposed, true); assert.equal(x.ctl.session(), null);
  assert.equal(x.host.innerHTML, ''); assert.equal(x.host.onfocusin, null);
});

test('coach descendants are isolated from compact Escape and double click shortcuts', () => {
  assert.equal(C.isCoachTarget({ closest: selector => selector === '[data-compact-coach]' ? {} : null }), true);
  assert.equal(C.isCoachTarget({ closest: () => null }), false);
  assert.equal(C.isCoachTarget(undefined), false);
});

const settled = { message_id: 'note', note: 1, captures: { frame: {state: 'done'}, state: {state: 'skipped'}, ram: {state: 'done'} } };

test('double Enter in flight files one note and an uncertain retry uses the same submission ID', async () => {
  let release, count = 0;
  const calls = [];
  const ctl = A.create({ sid: 'dedup-compact', idempotent: true, makeId: () => `attempt-${++count}`, render() {},
    sleep: async () => {}, api: async (path, body) => {
      calls.push({path, body});
      if (!body) return {state: 'missing', session_id: 'dedup-compact', client_id: 'attempt-1'};
      if (calls.length === 1) return new Promise((resolve, reject) => { release = () => reject(Error('connection lost')); });
      return settled;
    }});
  const first = ctl.send(' stop walking into walls '), again = ctl.send('stop walking into walls');
  assert.equal(first, again); assert.equal(calls.length, 1);
  release(); await assert.rejects(first, /connection lost/);
  await ctl.send('stop walking into walls');
  const posts = () => calls.filter(x => x.body);
  assert.equal(posts()[0].body.client_id, posts()[1].body.client_id);
  assert.equal(posts()[1].path, '/api/sessions/dedup-compact/coach');
  await ctl.send('aim at the enemy');
  assert.notEqual(posts()[1].body.client_id, posts()[2].body.client_id);
  ctl.dispose();
});

test('a timed out POST recovers its exact durable receipt using GET without sending another report', async () => {
  const calls = [], views = [], result = {...settled, change_id: 'c', implementation_number: 45, dispatch_state: 'queued'};
  let reads = 0;
  const ctl = A.create({sid: 'receipt-sid', idempotent: true, makeId: () => 'receipt-id', render: x => views.push(x),
    sleep: async () => {}, api: async (path, body) => {
      calls.push({path, body});
      if (body) throw Error('The operation was aborted due to timeout');
      return {session_id: 'receipt-sid', client_id: 'receipt-id', state: ++reads === 1 ? 'pending' : 'saved', result};
    }});
  assert.equal((await ctl.send('shoot')).message_id, result.message_id);
  assert.equal(calls.filter(x => x.body).length, 1);
  assert.ok(calls.filter(x => !x.body).every(x => x.path === '/api/sessions/receipt-sid/coach/submissions/receipt-id'));
  assert.match(views.at(-1).text, /task #45 queued/); ctl.dispose();
});

test('an older server cannot turn an ambiguous retry into a duplicate POST', async () => {
  const calls = [], views = [];
  const ctl = A.create({sid: 'old-server', idempotent: true, makeId: () => 'old-report-id', render: x => views.push(x),
    sleep: async () => {}, api: async (path, body) => { calls.push({path, body}); throw Error(body ? 'The operation timed out' : '404 Not Found'); }});
  await assert.rejects(ctl.send('shoot'), /timed out/);
  await assert.rejects(ctl.send('shoot'), /Delivery unconfirmed/);
  assert.equal(calls.filter(x => x.body).length, 1);
  assert.match(views.at(-1).text, /Delivery unconfirmed/);
  assert.doesNotMatch(views.at(-1).text, /Note not sent/); ctl.dispose();
});

test('an old-server timeout stays blocked after the upgraded server has no legacy receipt index', async () => {
  let posts=0, upgraded=false;
  const ctl=A.create({sid:'upgraded-server',idempotent:true,makeId:()=>'upgrade-id',render(){},sleep:async()=>{},
    api:async(path,body)=>{if(body){posts++;throw Error('timeout');} if(!upgraded)throw Error('404 missing route');
      return {state:'missing',session_id:'upgraded-server',client_id:'upgrade-id'};}});
  await assert.rejects(ctl.send('shoot'),/timeout/); upgraded=true;
  await assert.rejects(ctl.send('shoot'),/Delivery unconfirmed/);
  await assert.rejects(ctl.send('shoot'),/Delivery unconfirmed/);
  assert.equal(posts,1);ctl.dispose();
});

test('F5 preserves an uncertain submission without credentials and never replays it against a newer server', async () => {
  const fs=require('node:fs'),vm=require('node:vm'), source=fs.readFileSync(require.resolve('../clients/web/viz/autoplay-coach'),'utf8');
  const data=new Map(), storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
  const fresh=()=>{const ctx=vm.createContext({module:{exports:{}},sessionStorage:storage});vm.runInContext(source,ctx);return ctx.module.exports;};
  let posts=0;
  const first=fresh().create({sid:'reload-sid',idempotent:true,makeId:()=>'reload-id',render(){},sleep:async()=>{},
    api:async(path,body)=>{if(body){posts++;throw Error('timeout');}throw Error('404 old server');}});
  await assert.rejects(first.send('shoot'),/timeout/);first.dispose();
  assert.match(data.get('gbox.coach.uncertain.v1'),/reload-id/);
  assert.doesNotMatch(data.get('gbox.coach.uncertain.v1'),/authorization|token/);
  let finish; const recovering=new Promise(resolve=>finish=resolve);
  const next=fresh().create({sid:'reload-sid',idempotent:true,makeId:()=>{throw Error('must retain ID');},render(){},sleep:async()=>{},
    api:async(path,body)=>{if(body){posts++;throw Error('duplicate');}await recovering;return {state:'missing',session_id:'reload-sid',client_id:'reload-id'};}});
  const task=next.send('shoot');
  assert.equal(JSON.parse(data.get('gbox.coach.uncertain.v1'))[0].replayBlocked,true,'F5 during receipt recovery must retain the duplicate fence');
  finish();await assert.rejects(task,/Delivery unconfirmed/);assert.equal(posts,1);next.dispose();
});

test('a receipt for another session or submission never acknowledges this note', async () => {
  for (const [sid,receipt] of [
    ['bound-one',{session_id:'other', client_id:'bound-id'}], ['bound-two',{session_id:'bound-two', client_id:'other'}]
  ]) {
    const ctl = A.create({sid, idempotent:true, makeId:()=>'bound-id', render(){}, sleep:async()=>{},
      api:async(path,body)=>{ if(body) throw Error('connection lost'); return {...receipt,state:'saved',result:settled}; }});
    await assert.rejects(ctl.send('aim'), /connection lost/); ctl.dispose();
  }
});

test('an old server acknowledgement reports saved evidence without claiming a dispatched task', async () => {
  const views=[];
  const ctl=A.create({sid:'legacy-ack', idempotent:true, render:x=>views.push(x), sleep:async()=>{}, api:async()=>settled});
  await ctl.send('aim'); await new Promise(r=>setImmediate(r));
  assert.match(views.at(-1).text,/saved; task dispatch needs server update/);
  assert.equal(views.at(-1).state,'error'); ctl.dispose();
});

test('only exact coaching submission POSTs receive the longer bounded desktop deadline', () => {
  const T=require('../clients/desktop/coach-transport');
  assert.equal(T.timeoutMs('/api/sessions/worker-session/coach','POST'),60000);
  for(const [path,method] of [['/api/sessions/s/coach','GET'],['/api/sessions/s/input','POST'],
    ['/api/sessions/s/coach/note','POST'],['/api/sessions/s/coach?x=1','POST']]) assert.equal(T.timeoutMs(path,method),0);
});

test('capture timeout releases the pending state instead of pinning PiP controls forever', async () => {
  let now = 0; const views = [];
  const pending = {...settled, captures: {...settled.captures, ram: {state: 'pending'}}};
  const ctl = A.create({ sid: 'compact-timeout', render: x => views.push(x), now: () => now, timeout: 10, interval: 10,
    sleep: async ms => { now += ms; }, api: async () => pending });
  await ctl.send('test'); await new Promise(r => setImmediate(r));
  assert.equal(views.at(-1).state, 'error'); assert.match(views.at(-1).text, /captures still pending/);
  ctl.dispose();
});

test('a deleted report releases pending state and stops its watcher', async () => {
  const views = []; let polls = 0;
  const ctl = A.create({ sid: 'compact-deleted', render: x => views.push(x), sleep: async () => {},
    api: async (path, body) => { if (body) return {...settled, captures: {ram: {state: 'pending'}}}; polls++; throw Error('404 missing'); } });
  await ctl.send('test'); await new Promise(r => setImmediate(r));
  assert.equal(polls, 1); assert.equal(views.at(-1).state, 'error');
  assert.match(views.at(-1).text, /no longer available/); ctl.dispose();
});

test('task acknowledgement is visible and uncertainty is an error even when captures are complete', async () => {
  for (const dispatch_state of ['queued', 'uncertain']) {
    const views = [], out = {...settled, change_id: 'change', dispatch_state,
      implementation_number: dispatch_state === 'queued' ? 42 : null};
    const ctl = A.create({sid: `task-${dispatch_state}`, api: async () => out, render: x => views.push(x), sleep: async () => {}});
    await ctl.send('fix aim'); await new Promise(r => setImmediate(r));
    if (dispatch_state === 'queued') {
      assert.match(views.at(-1).text, /task #42 queued/); assert.equal(views.at(-1).state, 'done');
    } else {
      assert.match(views.at(-1).text, /saved; task creation unconfirmed/); assert.equal(views.at(-1).state, 'error');
      assert.doesNotMatch(views.at(-1).text, /queued/);
    }
    ctl.dispose();
  }
});

test('report-moment image, map failure and source age remain visible after captures settle', async () => {
  const views = [], out = {...settled, evidence: {
    stream: {state: 'done', age_s: 0.2, detail: 'cached source age 0.200s'},
    map: {state: 'failed', detail: 'node unavailable'}, moment: {state: 'done'},
    ram_fields: {state: 'skipped', detail: 'no cached RAM fields for this session'}}};
  const ctl = A.create({sid: 'report-evidence', api: async () => out, render: x => views.push(x), sleep: async () => {}});
  await ctl.send('capture this'); await new Promise(r => setImmediate(r));
  assert.match(views.at(-1).text, /report image/); assert.match(views.at(-1).text, /map/);
  assert.equal(views.at(-1).state, 'error'); assert.match(views.at(-1).title, /node unavailable/);
  assert.match(views.at(-1).title, /age 0.2s/); assert.match(views.at(-1).title, /no cached RAM fields/);
  ctl.dispose();
});

test('a remounted coach keeps the resolved implementation acknowledgement from its status poll', async () => {
  const views = [], sid = 'resolved-task-poll';
  const pending = {...settled, change_id: 'c', dispatch_state: 'uncertain',
    captures: {...settled.captures, ram: {state: 'pending'}}};
  const resolved = {...settled, change_id: 'c', dispatch_state: 'queued', implementation_number: 73};
  const ctl = A.create({sid, api: async (path, body) => body ? pending : resolved,
    render: x => views.push(x), sleep: async () => {}});
  await ctl.send('fix tracking'); await new Promise(r => setImmediate(r)); ctl.dispose();
  const remounted = A.create({sid, api: async () => {throw Error('no fresh capture');}, render: x => views.push(x)});
  assert.equal(remounted.resume(), true); assert.match(views.at(-1).text, /task #73 queued/);
  assert.equal(views.at(-1).state, 'done'); remounted.dispose();
});
