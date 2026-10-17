const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');const {withPage,findChrome,status}=require('../scripts/browser_lifecycle.cjs');
const skip=!findChrome()&&'no Chromium installed';
const state=fs.mkdtempSync(path.join(os.tmpdir(),'gbox-browser-test-'));
const env={GBOX_BROWSER_STATE:state,GBOX_BROWSER_MAX_SESSIONS:'1',GBOX_BROWSER_MAX_QUEUE:'4'};
const options={env};
async function gone(profile){for(let i=0;i<150;i++){if(!fs.existsSync(profile))return;await new Promise(r=>setTimeout(r,100));}throw new Error('Profile still exists: '+profile);}

test('normal, exception, cancellation and timeout always remove owned profiles',{skip},async()=>{
  let info;assert.equal(await withPage(async(e,s,i)=>{info=i;assert.equal(i.sandboxed,true);return e('21*2');},options),42);await gone(info.profile);
  await assert.rejects(withPage(async(e,s,i)=>{info=i;throw new Error('fixture task failed');},options),/fixture task failed/);await gone(info.profile);
  const controller=new AbortController();
  await assert.rejects(withPage(async(e,s,i)=>{info=i;controller.abort();await new Promise(()=>{});},{...options,signal:controller.signal}),/cancelled/);await gone(info.profile);
  await assert.rejects(withPage(async(e,s,i)=>{info=i;await new Promise(()=>{});},{...options,timeoutMs:150}),/timed out/);await gone(info.profile);
  await assert.rejects(withPage(async e=>e('new Promise(()=>{})'),{...options,requestTimeoutMs:200}),/timed out|timeout/i);
  await assert.rejects(withPage(async()=>{}, {env:{...env,GBOX_BROWSER_SESSION_MB:'1'}}),/memory limit/);
  await assert.rejects(withPage(async()=>{}, {...options,browser:path.join(state,'missing-browser.exe')}),/WinError|FileNotFound|No such file/);
});

test('concurrent clients share a bounded browser slot and queue',{skip},async()=>{
  let active=0,peak=0;const profiles=[];
  const run=()=>withPage(async(e,s,i)=>{profiles.push(i.profile);peak=Math.max(peak,++active);await new Promise(r=>setTimeout(r,300));active--;return e('document.readyState');},options);
  assert.deepEqual(await Promise.all([run(),run(),run()]),['complete','complete','complete']);assert.equal(peak,1);
  for(const p of profiles)await gone(p);
});

test('a hard-killed client releases its browser tree through the supervisor pipe',{skip},async()=>{
  const worker=spawn(process.execPath,[path.join(__dirname,'fixtures/browser_lifecycle_worker.cjs')],{env:{...process.env,...env},windowsHide:true,stdio:['ignore','pipe','pipe']});
  let text='';const info=await new Promise((yes,no)=>{const timer=setTimeout(()=>no(new Error('worker startup timed out')),30000);worker.stdout.on('data',b=>{text+=b;const line=text.split('\n')[0];try{const i=JSON.parse(line);clearTimeout(timer);yes(i);}catch{}});worker.once('error',no);});
  const exit=new Promise(r=>worker.once('exit',r));worker.kill('SIGKILL');await exit;
  // Windows may terminate both worker and supervisor: the job still closes,
  // while the next lease recovers the disposable profile from its manifest.
  let row;for(let n=0;n<50;n++){row=(await status(options)).leases.find(r=>r.id===info.lease);if(!row.live_members.length)break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(row.browser_alive,false);assert.deepEqual(row.live_members,[]);
  await withPage(async()=>{},options);await gone(info.profile);
});

test('application process exit closes its owned browser without awaiting async finally',{skip},async()=>{
  const worker=spawn(process.execPath,[path.join(__dirname,'fixtures/browser_lifecycle_worker.cjs'),'--exit'],{env:{...process.env,...env},windowsHide:true,stdio:['ignore','pipe','pipe']});
  const exit=new Promise(r=>worker.once('exit',r));let text='';
  const info=await new Promise((yes,no)=>{const timer=setTimeout(()=>no(new Error('worker startup timed out')),30000);worker.stdout.on('data',b=>{text+=b;try{const i=JSON.parse(text.split('\n')[0]);clearTimeout(timer);yes(i);}catch{}});worker.once('error',no);});
  await exit;await withPage(async()=>{},options);await gone(info.profile);
  const row=(await status(options)).leases.find(r=>r.id===info.lease);assert.equal(row.browser_alive,false);assert.deepEqual(row.live_members,[]);
});

test('supervisor hard-crash kills Windows job children; next lease recovers its disposable profile',{skip:skip||process.platform!=='win32'&&'Windows Job Object check'},async()=>{
  let info;const pending=withPage(async(e,s,i)=>{info=i;const record=JSON.parse(fs.readFileSync(path.join(i.profile,'gbox-owner.json'),'utf8'));process.kill(record.broker_pid,'SIGKILL');await new Promise(()=>{});},options);
  await assert.rejects(pending,/supervisor|socket|Browser/);
  // Recovery refuses a still-live recorded member, so successful removal also checks job death.
  await withPage(async()=>{},options);await gone(info.profile);
});

test('repeated startup/shutdown and a longer automation task return to baseline',{skip},async()=>{
  const profiles=[];const cycles=Number(process.env.GBOX_BROWSER_SOAK_CYCLES||8);
  for(let n=0;n<cycles;n++)await withPage(async(e,s,i)=>{profiles.push(i.profile);assert.equal(await e('6*7'),42);},options);
  await withPage(async e=>{const end=Date.now()+Number(process.env.GBOX_BROWSER_LONG_TEST_MS||1000);while(Date.now()<end){assert.equal(await e('document.readyState'),'complete');await new Promise(r=>setTimeout(r,100));}},options);
  for(const p of profiles)await gone(p);
  assert.deepEqual(fs.readdirSync(path.join(state,'profiles')),[]);
  const snapshot=await status(options);
  assert.ok(snapshot.leases.every(r=>!r.browser_alive&&!r.live_members.length),'all owned browser processes returned to baseline');
  console.log(JSON.stringify({soakCycles:cycles,profilesRemaining:0,liveProcesses:0,peakSessionRss:Math.max(...snapshot.leases.map(r=>r.peak_rss||0)),peakSessionHandles:Math.max(...snapshot.leases.map(r=>r.peak_handles||r.handles||0)),sampledCpuSeconds:snapshot.leases.reduce((n,r)=>n+(r.cpu_seconds||0),0),state}));
});
