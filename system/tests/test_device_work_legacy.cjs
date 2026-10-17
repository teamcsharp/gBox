const {test}=require('node:test'),assert=require('node:assert/strict');
const P=require('../clients/desktop/device-work-legacy.js');
const legacy={generated_at:200,window_start:100,window_label:'Today',runs_total:80,
  providers:[{provider:'gbox-sparkDeux',runs_running:24,runs_completed:4,runs_failed:1,calls_ok:10,calls_failed:2,tokens:2000}],routes:[{provider:'gbox-sparkDeux',model:'same-model'}],
  runs:[{session_id:'one',name:'gBox queue inbox 0123456789abcdef',start:110,status:'running',provider:'gbox-sparkDeux',attribution:'log'},
        {session_id:'two',name:'Ended run',start:120,status:'completed',provider:'gbox-sparkDeux',attribution:'log'},
        {session_id:'three',name:'No attribution',start:130,status:'running',provider:'gbox-sparkDeux',attribution:'config'}]};
test('compatibility data keeps real activity and never invents delivery or finish timestamps',()=>{
  const d=P.snapshot(legacy,'today',{'0123456789abcdef':{number:123,title:'Actual game task',status:'open'}});
  const m=d.devices.find(d=>d.id==='sparkDeux').metrics;
  assert.equal(m.active_runs,24);assert.equal(m.calls_ok,10);assert.equal(m.tokens_total,2000);
  assert.equal(m.prs_merged,null);assert.equal(m.requests_resolved,null);assert.equal(m.peak_concurrency,null);
  assert.equal(d.runs[1].finished,null);assert.equal(d.runs[2].device_id,'unknown');
  assert.equal(d.runs[0].title,'#123: Actual game task');assert.equal(d.runs[0].log_available,false);
  assert.match(d.coverage.notice,/completion evidence is unavailable, not zero/);
  assert.match(d.coverage.notes[0],/3 of 80/);
});
test('fallback only activates on an explicit missing endpoint',()=>{
  assert.equal(P.missing({ok:false,error:'404 {"detail":"Not Found"}'}),true);
  assert.equal(P.missing({ok:false,status:404}),true);
  for(const error of ['401 Unauthorized','503 unavailable','500 file not found'])assert.equal(P.missing({ok:false,error}),false);
  assert.equal(P.missing({ok:true}),false);
});
test('compatibility reads existing provider/request APIs without task dispatch or token/model guesses',async()=>{
  const calls=[];const r=await P.read(async p=>{calls.push(p);return {ok:true,data:p.startsWith('/api/hermes/providers')?legacy:{id:'0123456789abcdef',number:123,title:'Named task',status:'done'}}},'today');
  assert.deepEqual(calls,['/api/hermes/providers?window=today','/api/requests/0123456789abcdef']);
  assert.equal(r.data.runs[0].tickets[0].status,'done');assert.deepEqual(r.data.runs[0].outcomes,[]);
  assert.equal(P.deviceId('custom'),'unknown');
});
