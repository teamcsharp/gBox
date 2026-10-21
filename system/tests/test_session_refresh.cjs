const { test } = require('node:test');
const assert = require('node:assert/strict');
const R = require('../clients/web/viz/session-refresh.js');

function fixture(rows = [{session_id:'main-A',state:'running'}, {session_id:'pip-B',state:'running'}]) {
  const calls=[];
  const ctl=R.create({sessions:async()=>rows,tabs:['Home','Library','Sessions'],
    show:async(...args)=>calls.push(['show',...args]),active:s=>calls.push(['active',s?.session_id||null]),pip:()=>calls.push(['pip'])});
  return {ctl,calls};
}
test('two exact streams restore in their original main and PiP roles',async()=>{
  const x=fixture(); const out=await x.ctl.restore({tab:'Sessions',playing:'main-A',active:'pip-B',pip:'pip-B'});
  assert.deepEqual(x.calls,[['show','Sessions','main-A'],['active','pip-B'],['pip']]);
  assert.deepEqual(out,{restored:['main-A','pip-B'],missing:[]});
});
test('a missing main stream shows the list and retains a healthy second stream, without selecting a replacement',async()=>{
  const x=fixture([{session_id:'pip-B',state:'running'},{session_id:'new-unrelated',state:'running'}]);
  const out=await x.ctl.restore({playing:'main-A',active:'pip-B',pip:'pip-B'});
  assert.deepEqual(x.calls,[['show','Sessions'],['active','pip-B'],['pip']]);
  assert.deepEqual(out,{restored:['pip-B'],missing:['main-A']});
});
test('a missing PiP does not remove the valid foreground stream or claim successful restoration',async()=>{
  const x=fixture([{session_id:'main-A',state:'running'}]);
  const out=await x.ctl.restore({playing:'main-A',active:'pip-B',pip:'pip-B'});
  assert.deepEqual(out.missing,['pip-B']); assert.deepEqual(x.calls[1],['active','main-A']);
});
test('another tab can retain PiP and unknown saved fields never reach a URL or game operation',async()=>{
  const x=fixture(); await x.ctl.restore({tab:'Library',active:'pip-B',pip:'pip-B',token:'secret',playing:'https://bad/?token=secret'});
  assert.deepEqual(x.calls,[['show','Library'],['active','pip-B'],['pip']]);
  assert.deepEqual(R.normalize({tab:'<script>',active:'a/b',pip:'ok'}),{tab:'Home',playing:null,active:null,pip:'ok'});
});
test('a cancelled or superseded restoration cannot select an old stream after the read finishes',async()=>{
  let finish; const calls=[];
  const ctl=R.create({sessions:()=>new Promise(r=>finish=r),tabs:['Home'],show:async()=>calls.push('show'),active:()=>calls.push('active'),pip:()=>calls.push('pip')});
  const pending=ctl.restore({playing:'main-A'}); ctl.cancel(); finish([{session_id:'main-A',state:'running'}]);
  assert.equal((await pending).cancelled,true);assert.deepEqual(calls,[]);
});
test('operator navigation during a delayed session lookup cancels restoration before either stream changes',async()=>{
  let finish, revision=1;const calls=[];
  const ctl=R.create({sessions:()=>new Promise(r=>finish=r),revision:()=>revision,tabs:['Home'],
    show:async()=>calls.push('show'),active:()=>calls.push('active'),pip:()=>calls.push('pip')});
  const pending=ctl.restore({playing:'main-A',pip:'pip-B'}); revision++;
  finish([{session_id:'main-A',state:'running'},{session_id:'pip-B',state:'running'}]);
  assert.equal((await pending).cancelled,true);assert.deepEqual(calls,[]);
});
