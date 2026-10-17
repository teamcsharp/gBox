const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const O=require('../clients/web/viz/operation-console.js');
function fixture(extra={}) {
  let t=10000,sid='a-game',frame={rows:[]};const callbacks=[],cleared=[];
  const c=O.create({session:()=>sid,now:()=>t,render:f=>frame=f,every:fn=>(callbacks.push(fn),callbacks.length),stop:id=>cleared.push(id),...extra});
  return {c,get frame(){return frame;},tick:n=>{t+=n;callbacks[0]();},switch:s=>{sid=s;callbacks[0]();},cleared};
}
test('only session-bound game tools are shown; background reads/builds stay quiet',()=>{
  assert.equal(O.describe('pso_mods',{op:'capabilities',session_id:'s'}),null);
  assert.equal(O.describe('file_mod',{op:'build',session_id:'s'}),null);
  assert.equal(O.describe('game_live_controls',{op:'apply'}),null);
  assert.equal(O.describe('game_live_controls',{op:'apply',session_id:'s',action:'boss_hp'}).sid,'s');
  assert.equal(O.describeRequest('/api/sessions/s/rpc',{op:'pso_controls',args:{input:{op:'floor_spawn'}}}).sid,'s');
});
test('trace reports actual request result, never delays or repeats the command',async()=>{
  const f=fixture();let calls=0,finish;
  const promise=f.c.request('/api/sessions/a-game/rpc',{op:'pso_controls',args:{input:{op:'floor_spawn'}}},()=>{calls++;return new Promise(r=>finish=r);});
  assert.equal(f.frame.rows[0].state,'running');f.tick(100000);assert.equal(f.frame.rows.length,1);
  finish({verified:true,spawned:3,elapsed_ms:12});assert.equal((await promise).spawned,3);
  assert.equal(calls,1);assert.equal(f.frame.rows[0].state,'succeeded');assert.match(f.frame.rows[0].lines.join(' '),/spawned: 3/);
  f.tick(4000);assert.equal(f.frame.rows[0].opacity,.5);f.tick(501);assert.equal(f.frame.rows.length,0);f.c.dispose();
});
test('errors and unverified outcomes are not presented as a success',async()=>{
  const f=fixture();let calls=0;
  await assert.rejects(f.c.request('/api/jobs',{tool:'re_inventory',input:{session_id:'a-game',op:'give'}},()=>{calls++;throw Error('Worker offline');}),/Worker offline/);
  assert.equal(f.frame.rows[0].state,'failed');f.tick(6200);assert.ok(f.frame.rows[0].opacity<1);assert.equal(calls,1);
  await f.c.request('/api/sessions/a-game/rpc',{op:'pso_controls',args:{input:{op:'give'}}},async()=>({verified:false}));
  assert.equal(f.frame.rows.at(-1).state,'unverified');f.c.dispose();
});
test('agent audit submission follows progress and a fast terminal result; never reopens on old snapshots',async()=>{
  let j={id:'j',tool:'game_live_controls',input:{session_id:'a-game',op:'apply'},state:'running',progress_log:['Revision verified','Calling native give']};
  const f=fixture({fetchJob:async()=>j});
  f.c.audit([{ts:11,action:'job.submit',subject:'j',data:{tool:j.tool,input:j.input}}]);
  assert.equal(f.frame.rows[0].state,'queued');await f.c.poll();assert.equal(f.frame.rows[0].state,'running');
  assert.deepEqual(f.frame.rows[0].lines,j.progress_log);
  j={...j,state:'succeeded',output:{result:{verified:true,message:'Item inserted'}}};await f.c.poll();
  assert.match(f.frame.rows[0].lines.join(' '),/Item inserted/);
  f.tick(4501);assert.equal(f.frame.rows.length,0);f.c.observe(j);assert.equal(f.frame.rows.length,0);f.c.dispose();
});
test('outputs clear on game switch and late responses for the previous session are ignored',async()=>{
  let finish;const f=fixture();
  const p=f.c.request('/api/sessions/a-game/rpc',{op:'pso_controls',args:{input:{op:'give'}}},()=>new Promise(r=>finish=r));
  f.switch('b-game');assert.equal(f.frame.rows.length,0);finish({verified:true});await p;
  assert.equal(f.frame.rows.length,0);f.c.dispose();assert.equal(f.cleared.length,2);
});
test('logs are bounded and redact credentials; unrelated/old audit history is ignored',()=>{
  const f=fixture();
  f.c.audit([{ts:1,action:'job.submit',subject:'old',data:{tool:'pso_mods',input:{op:'give',session_id:'a-game'}}}]);
  assert.equal(f.frame.rows.length,0);
  for(let n=0;n<50;n++)f.c.ingest({id:'x'+n,sid:'a-game',label:'Test',state:'running',lines:Array(100).fill('token=secret Bearer hidden '+ 'x'.repeat(900))});
  assert.equal(f.frame.rows.length,4);assert.equal(f.frame.rows[0].lines.length,6);
  assert.ok(f.frame.rows[0].lines[0].length<=600);assert.doesNotMatch(f.frame.rows[0].lines[0],/secret|hidden/);f.c.dispose();
});
test('status read failures show unknown outcome without retrying a mutation or claiming completion',async()=>{
  const f=fixture({fetchJob:async()=>{throw Error('API unavailable');}});
  f.c.observe({id:'j',tool:'pso_mods',input:{session_id:'a-game',op:'give'},state:'running'});
  await f.c.poll();f.tick(1);assert.equal(f.frame.rows[0].state,'running');assert.match(f.frame.rows[0].lines.join(' '),/outcome is unknown/);f.c.dispose();
});
test('both shells connect immediate commands, job progress and agent audit events',()=>{
  const web=fs.readFileSync(require.resolve('../clients/web/index.html'),'utf8');
  const desk=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  assert.match(web,/GBOX_OPERATION_CONSOLE\?\.request\(path,body,run\)/);assert.match(web,/controller.audit\(rows\)/);
  assert.match(desk,/GAME_OUTPUT.audit\(r.data\)/);assert.match(desk,/GAME_OUTPUT.observe\(j\)/);
  assert.match(desk,/m.ev === 'operationconsole'/);assert.match(main,/operationConsole.trace\(/);
  assert.match(main,/operationOutput.update\(state\)/);
});
