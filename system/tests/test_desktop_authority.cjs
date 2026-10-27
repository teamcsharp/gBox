const {test}=require('node:test');
const assert=require('node:assert/strict');
const A=require('../clients/desktop/desktop-authority.cjs');
const L=require('../clients/desktop/session-lease.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const local='http://127.0.0.1:18765',remote='http://offline.example:8765';
function deferred(){let resolve;return {promise:new Promise(r=>resolve=r),resolve:value=>resolve(value)};}
function connection(options={}){
  return A.create({localUrl:local,remoteUrl:remote,probe:async()=>({ok:true}),
    readLocalToken:async()=>'local-only',readRemoteToken:async()=>'remote-only',...options});
}
test('local readiness is reported without waiting for a hung remote probe',async()=>{
  const hang=deferred(),seen=[];
  const c=connection({probe:async(_url,kind)=>kind==='local'?{ok:true}:hang.promise,onChange:s=>seen.push(s)});
  const pending=c.check();await tick();
  assert.ok(seen.some(s=>s.local.ready));assert.equal(c.snapshot().mode,'local');
  hang.resolve({ok:false});await pending;
});
test('remote returns in background without changing authority or replaying anything',async()=>{
  let online=false,probes=0;const c=connection({probe:async(_url,kind)=>{probes++;return {ok:kind==='local'||online};}});
  await c.check();online=true;await c.check();
  assert.equal(c.snapshot().apiUrl,local);assert.equal(c.snapshot().remote.ready,true);assert.equal(probes,4);
  assert.equal(c.snapshot().generation,0);
});
test('credentials and explicit server selection remain scoped; native game blocks switching',async()=>{
  let busy=true;const c=connection({canSwitch:()=>!busy});
  assert.equal(await c.token(local),'local-only');assert.equal(await c.token(remote),'remote-only');
  await assert.rejects(c.token('http://another.example'),/different/);
  assert.throws(()=>c.select('remote'),/no game was stopped/);
  assert.equal(c.snapshot().mode,'local');busy=false;
  assert.equal(c.select('remote').apiUrl,remote);assert.equal(c.snapshot().generation,1);
});
test('many credential calls leave one asynchronous SMB attempt when it hangs',async()=>{
  const blocked=deferred(),timers=new Map();let calls=0,id=0;
  const read=A.tokenReader({read:()=>{calls++;return blocked.promise;},schedule:cb=>{timers.set(++id,cb);return id;},cancel:n=>timers.delete(n)});
  const attempts=Array.from({length:30},()=>read.get());await tick();
  assert.equal(calls,1);for(const timer of [...timers.values()])timer();
  assert.deepEqual(await Promise.all(attempts),Array(30).fill(null));
  const retry=read.get();await tick();assert.equal(calls,1);
  for(const timer of [...timers.values()])timer();assert.equal(await retry,null);
  blocked.resolve(' eventual credential ');await tick();assert.equal(await read.get(),'eventual credential');
});
test('failed credential reads have a cooldown and token reset never shares another reader',async()=>{
  let at=0,calls=0;
  const reader=A.tokenReader({read:async()=>{calls++;throw Error('offline');},now:()=>at});
  assert.equal(await reader.get(),null);assert.equal(await reader.get(),null);assert.equal(calls,1);
  at=30001;assert.equal(await reader.get(),null);assert.equal(calls,2);
  const own=A.tokenReader({read:async()=>'separate-local'});assert.equal(await own.get(),'separate-local');
});
test('a delayed response cannot populate another authority cache or reuse its session IDs',async()=>{
  let source=remote,calls=0;const delayed=deferred();
  const cache=L.cachedRead(async()=>{calls++;return source===remote?delayed.promise:{ok:true,data:['local-sid'],authority:local};},{authority:()=>source});
  const prior=cache.get();await tick();source=local;
  assert.equal(cache.peek(),null);const fresh=await cache.get();assert.deepEqual(fresh.data,['local-sid']);
  delayed.resolve({ok:true,data:['remote-sid'],authority:remote});assert.equal((await prior).ok,false);
  assert.deepEqual(cache.peek().data,['local-sid']);assert.equal(calls,2);
});
const session={session_id:'owned-sid',state:'running',started:1,detail:{pid:42,local_window:true,worker_name:'this-pc'}};
test('network loss and empty foreign listings retain the exact docked native game',async()=>{
  const probes=[];const lease=L.create({probe:async pid=>{probes.push(pid);return {ok:true,alive:true};},now:()=>1000});
  const initial=await lease.resolve(remote,{ok:true,data:[session]},{worker:'this-pc'});
  assert.equal(initial.retained,false);
  const missing=await lease.resolve(remote,{ok:false},{worker:'this-pc'});
  assert.equal(missing.session,session);assert.equal(missing.retained,true);
  const foreign=await lease.resolve(local,{ok:true,data:[{...session,session_id:'wrong-server'}]},{worker:'this-pc'});
  assert.equal(foreign.authority,remote);assert.equal(foreign.session.session_id,'owned-sid');
  await tick();assert.deepEqual(probes,[42]);
});
test('unknown native liveness preserves the dock; only exact dead-surface proof releases it',async()=>{
  let at=0,answer={ok:false};const lease=L.create({probe:async()=>answer,now:()=>at});
  await lease.resolve(local,{ok:true,data:[session]},{worker:'this-pc'});
  await lease.resolve(local,{ok:true,data:[]},{worker:'this-pc'});await tick();
  assert.equal(lease.current().session,session);
  at=2000;answer={ok:true,alive:false};await lease.resolve(local,{ok:false},{worker:'this-pc'});await tick();
  assert.equal(lease.current(),null);
});
test('an explicit closed session cannot be resurrected from the retained dock',async()=>{
  const lease=L.create({probe:async()=>({ok:true,alive:true})});
  await lease.resolve(local,{ok:true,data:[session]},{worker:'this-pc'});
  assert.equal(await lease.resolve(local,{ok:true,data:[session]},{worker:'this-pc',closed:new Set(['owned-sid'])}),null);
});

test('viewing remote gameplay still starts only the locally owned worker',async()=>{
  const fs=require('node:fs'),vm=require('node:vm');
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  const source=main.slice(main.indexOf('async function startWorkerInner(options)'),main.indexOf('// Reconnect only a stopped worker.'));
  const calls=[];let starts=0;
  const context=vm.createContext({STANDALONE:false,settings:()=>({apiUrl:remote}),
    startLocalControl:async()=>{starts++;return {running:true};},
    connection:{snapshot:()=>({mode:'remote',apiUrl:remote,localUrl:local,local:{ready:true}}),token:async url=>{assert.equal(url,local);return 'local-only';}},
    fetch:async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>({running:true,state:'running'})};},
    AbortSignal,spawn:()=>{throw Error('A second remote-connected worker must never be launched');}});
  vm.runInContext(source,context);
  const result=await context.startWorkerInner({});
  assert.equal(result.running,true);assert.equal(starts,1);assert.equal(calls.length,1);
  assert.equal(calls[0].url,local+'/api/desktop-local/worker');
  assert.equal(calls[0].opts.headers.authorization,'Bearer local-only');
});

// operator 2026-10-27 (JAYBUILTFINALE on Wi-Fi): the Spark's /api/health answered in up to ~1.3 s while streams filled
// the link (p95 1.14 s); one probe over 1.2 s marked the Spark offline for 5 s, every request failing meanwhile
test('the remote connection probe waits up to 3 s; the local one stays quick',async()=>{
  const fs=require('node:fs'),vm=require('node:vm');
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  const start=main.indexOf('probe:async(url,kind)=>{'),source=main.slice(start,main.indexOf('onChange:state=>',start));
  const budgets=[];
  const context=vm.createContext({STANDALONE:false,localControlInfo:{installation:'i'},localControlError:'',
    AbortSignal:{timeout:ms=>{budgets.push(ms);return null;}},
    fetch:async url=>({ok:true,json:async()=>url.includes('desktop-local')?{ok:true,kind:'gbox.desktop-local/1',installation:'i'}:{ok:true}})});
  const probe=vm.runInContext('({'+source.replace(/,\s*$/,'')+'})',context).probe;
  await probe(remote,'remote'); await probe(local,'local');
  assert.deepEqual(budgets,[3000,1200]);
});
