const test = require('node:test');
const assert = require('node:assert/strict');
const A = require('../clients/web/viz/game-analysis.js');
const done = () => new Promise(resolve => setImmediate(resolve));
const run = {id:'run',state:'running',target:{game_id:'game',session_id:'w-launch'},counts:{polls:3,observations:2,jobs:1,artifacts:0},
  evidence:{autoplay:{age_s:2,stats:{kills:5,shots:10}},native_telemetry:'reported_by_exact_session'},
  samples:[{at:100,observations:1},{at:110,observations:2}],console:[{job_id:'owned',tool:'autoplay',line:'<script>alert(1)</script>'}],
  capabilities:[{feature:'replacement',requested:true,state:'adapter_verification_required',installed_hooks:['characters']}],
  crystal:{sha256:'abc'}};

test('desktop compact visibility and native/guest holes preserve both review overlays',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const html=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const hide=html.split('\n').find(x=>x.includes('body.gbox-compact > :not'));
  for(const name of ['game-analysis','ga-toggle','pso-review-window'])assert.ok(hide.includes(`:not(.${name})`));
  for(const marker of ['const EMB_HOLES =','const EMB_GUEST_MENUS =','querySelectorAll(COMPACT.on ?']){
    const line=html.split('\n').find(x=>x.includes(marker));
    for(const name of ['game-analysis','ga-toggle','pso-review-window'])assert.ok(line.includes('.'+name),marker+' '+name);
  }
});

test('report shows measured counts, hypotheses, disabled mutations, escaped console and artifact links',()=>{
  const html=A.report({...run,model_hypothesis:{text:'Maybe door',model:'local',usage:{eval_count:8}}},p=>'https://local'+p);
  assert.match(html,/not percent complete/);assert.match(html,/5/);assert.match(html,/seconds old/);
  assert.match(html,/Execution disabled/);assert.match(html,/Local model hypothesis/);
  assert.match(html,/measured output tokens: 8/);assert.match(html,/GPU placement is not attested/);
  assert.ok(!html.includes('<script>'));assert.match(html,/https:\/\/local\/api\/artifacts\/abc/);
});
test('unavailable telemetry never becomes zero-valued native counters',()=>{
  const html=A.report({state:'running',evidence:{}},p=>p);
  assert.match(html,/No measured native counters/);assert.match(html,/Native report: unavailable/);
});
test('chart uses only finite actual samples and elapsed time',()=>{
  const html=A.chart([{at:100,observations:1},{at:110,observations:4},{at:NaN,observations:3}]);
  assert.match(html,/10 s/);assert.match(html,/4 observations/);assert.ok(!html.includes('NaN'));
});
test('donut and bars count observed jobs and evidence, no invented completion',()=>{
  const pie=A.jobDonut([{state:'running'},{state:'succeeded'},{state:'succeeded'}]);
  assert.match(pie,/running: 1/);assert.match(pie,/succeeded: 2/);assert.match(pie,/conic-gradient/);
  assert.match(A.bars({observations:7,artifacts:2,jobs:3}),/>7</);
  const html=A.report({...run,started:100,updated:160,deadline:400},p=>p);
  assert.match(html,/Collection window: 60 \/ 300 seconds/);assert.match(html,/value="60"/);
});
test('session and build keys distinguish concurrent instances',()=>{
  assert.notEqual(A.keyOf({session_id:'a',game_id:'g'}),A.keyOf({session_id:'b',game_id:'g'}));
  assert.notEqual(A.keyOf({game_id:'g',build:'one'}),A.keyOf({game_id:'g',build:'two'}));
});
test('controller calls only evidence routes and stops its own run',async()=>{
  const calls=[],updates=[];
  const c=A.controller({api:async(p,b)=>{calls.push([p,b]);return p.endsWith('/stop')?{...run,state:'cancelled'}:run;},pollMs:60000},
    {session_id:'w-launch'},(r,e)=>updates.push([r,e]));
  await c.start();await c.poll();await c.stop();c.dispose();
  assert.deepEqual(calls.map(x=>x[0]),['/api/analysis','/api/analysis/run','/api/analysis/run/stop']);
  assert.equal(updates.at(-1)[0].state,'cancelled');
});
test('disposed controller drops a late start response',async()=>{
  let resolve;const updates=[];
  const c=A.controller({api:()=>new Promise(r=>resolve=r)}, {session_id:'a'}, (...x)=>updates.push(x));
  const pending=c.start();c.dispose();resolve(run);await pending;
  assert.equal(updates.length,0);assert.equal(c.run,null);
});
test('changed authority cannot submit model, Stop, or follow-up polls',async()=>{
  let valid=true;const calls=[],updates=[];
  const c=A.controller({valid:()=>valid,api:async p=>{calls.push(p);return run;},pollMs:60000},{session_id:'a'},(r,e)=>updates.push(e));
  await c.start();valid=false;await c.poll();await c.stop();
  await assert.rejects(c.model('worker',true),/active analysis/);c.dispose();
  assert.deepEqual(calls,['/api/analysis']);assert.match(updates.at(-1),/frozen/);
});
test('local compute explicitly carries checked opt-in and exact run only',async()=>{
  const calls=[];
  const c=A.controller({api:async(p,b)=>{calls.push([p,b]);return run;},pollMs:60000},{session_id:'a'},()=>{});
  await c.start();await c.model('worker',false);await c.model('worker',true);c.dispose();
  assert.deepEqual(calls.at(-1),['/api/analysis/run/model',{worker_id:'worker',allow_during_gameplay:true}]);
  assert.equal(calls[1][1].allow_during_gameplay,false);
});
test('terminal run blocks new inference',async()=>{
  const c=A.controller({api:async()=>({...run,state:'interrupted'})},{session_id:'a'},()=>{});
  await c.start();await assert.rejects(c.model('worker',true),/active analysis/);c.dispose();
});
