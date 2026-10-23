const {test}=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const {EventEmitter}=require('node:events'), vm=require('node:vm');
const H=require('../clients/desktop/client-handoff.cjs');
const value=()=>({state:{v:1,sid:'pip-B',compact:true,guest:{tab:'Sessions',playing:'main-A',active:'pip-B',pip:'pip-B'},token:'SECRET'},
  window:{bounds:{x:100,y:120,width:1200,height:800},maximized:true},compactBounds:{x:900,y:600,width:480,height:360},
  mini:{sid:'legacy-C',title:'Game',bounds:{x:20,y:30,width:480,height:360},url:'http://host/?token=SECRET'},startWorker:true});

test('durable handoff is sanitized, exact, one-use and expires',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'gbox-handoff-')), file=path.join(dir,'view.json');
  try {
    const id=H.save(file,value(),{now:()=>1000,owner:23});
    assert.doesNotMatch(fs.readFileSync(file,'utf8'),/SECRET|token|url/);
    assert.equal(H.consume(file,[H.ARG+'f'.repeat(64)],{now:()=>2000}).value,null);
    assert.equal(fs.existsSync(file),true,'wrong identity cannot consume the handoff');
    const out=H.consume(file,[H.ARG+id],{now:()=>2000});
    assert.equal(out.value.state.guest.playing,'main-A'); assert.equal(out.value.state.sid,'pip-B'); assert.equal(out.value.mini.sid,'legacy-C');
    assert.equal(fs.existsSync(file),false); assert.equal(H.consume(file,[H.ARG+id],{now:()=>2000}).value,null);
    const old=H.save(file,value(),{now:()=>1000}); assert.equal(H.consume(file,[H.ARG+old],{now:()=>122000}).value,null);
  } finally { fs.rmSync(dir,{recursive:true,force:true}); }
});

test('malformed identities, bounds and credentials cannot become a relaunch state',()=>{
  const out=H.view({...value(),state:{sid:'../../other',guest:{playing:'token?secret',active:'safe'},compact:true}},1000);
  assert.equal(out.state.sid,null);assert.equal(out.state.compact,false);assert.equal(out.state.guest.playing,null);
  assert.throws(()=>H.view({...value(),window:{bounds:{x:0,y:0,width:Infinity,height:100}}},1),/unavailable/);
});

function pipe(options={}) {
  const child=new EventEmitter(); child.pid=42;
  const writes=[],timers=[]; child.stdin={writable:true,write:(s,cb)=>{writes.push(JSON.parse(s));cb?.();}};
  const control=H.workerChannel(child,'a'.repeat(64),{now:()=>100000,setTimer:f=>{timers.push(f);return f;},clearTimer:()=>{},...options});
  const feed=v=>control.feed(H.PREFIX+JSON.stringify({v:1,pid:42,secret:'a'.repeat(64),...v})+'\n');
  return {child,writes,timers,control,feed};
}
test('legacy and wrong-process capabilities never authorize worker stop',async()=>{
  const x=pipe(); await assert.rejects(x.control.stop(),/does not support/);assert.equal(x.writes.length,0);
  x.feed({event:'ready',pid:99}); await assert.rejects(x.control.stop(),/does not support/);
  x.feed({event:'ready',secret:'wrong'});assert.equal(x.control.ready(),false);
});

test('venv child protocol requires asynchronous process proof and then binds to that exact peer',async()=>{
  let verify,verified=[];
  const x=pipe({verifyPid:pid=>{verified.push(pid);return new Promise(resolve=>{verify=resolve;});}});
  x.feed({event:'ready',pid:99,secret:'wrong'});assert.deepEqual(verified,[]);
  x.feed({event:'ready',pid:99});
  assert.equal(x.control.ready(),false);assert.equal(x.control.pid(),null);
  await assert.rejects(x.control.stop(),/does not support/);
  x.feed({event:'ready',pid:100});assert.deepEqual(verified,[99],'one lineage probe at a time');
  verify(true);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(x.control.ready(),true);assert.equal(x.control.pid(),99);
  let done=false;const stopping=x.control.stop().then(()=>{done=true;});const id=x.writes[0].id;
  x.feed({event:'stopping',id,pid:42});assert.equal(done,false,'launcher cannot acknowledge for actual peer');
  x.feed({event:'stopping',id,pid:99});x.child.emit('close',0);await stopping;
  assert.equal(x.control.pid(),null);
});

test('failed process proofs and late ready responses cannot revive a closed worker',async()=>{
  for(const result of [false,new Error('CIM unavailable')]){
    const x=pipe({verifyPid:()=>result instanceof Error?Promise.reject(result):Promise.resolve(result)});
    x.feed({event:'ready',pid:99});await new Promise(resolve=>setImmediate(resolve));
    assert.equal(x.control.ready(),false);assert.equal(x.control.pid(),null);
  }
  let complete;const x=pipe({verifyPid:()=>new Promise(resolve=>{complete=resolve;})});
  x.feed({event:'ready',pid:99});x.child.emit('close',0);complete(true);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(x.control.ready(),false);
});

function workerInspection(extra={}){
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  const source=main.slice(main.indexOf('function canonicalWorkerExe('),main.indexOf('function assertClientSender('));
  const launcher='C:\\gbox\\venv\\Scripts\\python.exe',base='C:\\uv\\python\\python.exe';
  const cmd='-P -m gbox --config C:\\repo\\gbox.toml worker --server http://spark:8765 --name mine';
  const rows=[{ProcessId:42,ParentProcessId:12,ExecutablePath:launcher,CommandLine:`"${launcher}" ${cmd}`},
    {ProcessId:99,ParentProcessId:42,ExecutablePath:base,CommandLine:`"${base}" ${cmd}`}];
  const calls=[];
  const context=vm.createContext({path:path.win32,fs:{realpathSync:v=>v,readFileSync:()=>`home = C:\\uv\\python\n`},
    venvPython:()=>launcher,process:{pid:12,platform:'win32',env:{}},psq:s=>"'"+s+"'",
    STANDALONE:false,startupHandoff:null,workerStarting:null,procs:new Map(),rec:null,recFitBusy:false,embedded:null,embedSyncPending:0,
    worker:{pid:42,exitCode:null},workerControl:{pid:()=>99},settings:()=>({repoLocal:'C:\\repo'}),
    execFile:(file,args,opts,cb)=>{calls.push({file,args});cb(null,JSON.stringify(file==='powershell.exe'?rows:{runtime:'C:\\repo\\runtime',reason:null}));},...extra});
  vm.runInContext(source,context);
  return {context,rows,calls,launcher,base};
}

test('idle process exclusion requires exact protocol PID, app-owned lineage and canonical venv executable',()=>{
  const f=workerInspection();const allowed=[f.launcher.toLowerCase(),f.base.toLowerCase()];
  const verify=()=>[...f.context.ownedWorkerPids(f.rows,99,42,12,allowed)];
  assert.deepEqual(verify(),[42,99]);
  assert.deepEqual([...f.context.ownedWorkerPids(f.rows,42,42,12,allowed)],[42]);
  f.rows[1].ParentProcessId=555;assert.deepEqual(verify(),[]);f.rows[1].ParentProcessId=42;
  f.rows[1].ExecutablePath='C:\\foreign\\python.exe';assert.deepEqual(verify(),[]);f.rows[1].ExecutablePath=f.base;
  f.rows[1].CommandLine+=' --different-job';assert.deepEqual(verify(),[]);
  f.rows[1].CommandLine=f.rows[0].CommandLine.replace(f.launcher,f.base);
  f.rows[0].ParentProcessId=888;assert.deepEqual(verify(),[]);
});

test('actual idle preflight excludes only verified launcher and peer, while unknown games and workers still block',async()=>{
  const f=workerInspection();
  assert.equal(await f.context.inspectClientIdle(),null);
  assert.match(f.calls[1].args.at(-1),/ParentProcessId,ExecutablePath,CommandLine/);
  assert.doesNotMatch(f.calls[1].args.at(-1),/ProcessId -ne 42/,'the PowerShell scan must retain the launcher for lineage proof');
  f.rows.push({ProcessId:777,ParentProcessId:1,ExecutablePath:'C:\\gBox\\runtime\\game.exe',CommandLine:'game.exe'});
  assert.match(await f.context.inspectClientIdle(),/Another local game or worker/);
  f.rows.pop();f.rows[1].ParentProcessId=777;
  assert.match(await f.context.inspectClientIdle(),/ownership could not be verified/);
  f.context.workerControl={pid:()=>null};
  assert.match(await f.context.inspectClientIdle(),/verified desktop control channel/);
  f.context.worker=null;f.context.workerControl=null;
  assert.match(await f.context.inspectClientIdle(),/Another local game or worker/,'remaining child is not excused after its owner exits');
});

test('actual ready PID verification refuses changed worker owner and unavailable process inventory',async()=>{
  const f=workerInspection();
  assert.equal(await f.context.verifyWorkerPeer(f.context.worker,99),true);
  assert.equal(await f.context.verifyWorkerPeer({pid:42,exitCode:null},99),false);
  f.context.execFile=(_file,_args,_opts,cb)=>cb(Error('denied'));
  assert.equal(await f.context.verifyWorkerPeer(f.context.worker,99),false);
  f.context.worker.exitCode=0;assert.equal(await f.context.verifyWorkerPeer(f.context.worker,99),false);
});
test('matching acknowledgement must be followed by actual clean child exit',async()=>{
  const x=pipe();x.feed({event:'ready'});let done=false;
  const stopping=x.control.stop().then(()=>{done=true;});const request=x.writes[0];
  assert.equal(request.expires,110); assert.equal(request.op,'stop_if_idle');
  x.feed({event:'stopping',id:request.id});await Promise.resolve();assert.equal(done,false);
  x.child.emit('close',0);await stopping;assert.equal(done,true);
});
test('busy, expiry, nonzero exit and missing acknowledgement all refuse relaunch',async()=>{
  for(const kind of ['busy','timeout','failed','unconfirmed']) {
    const x=pipe();x.feed({event:'ready'});const p=x.control.stop();const id=x.writes[0].id;
    if(kind==='busy')x.feed({event:'refused',id,reason:'busy job'});
    if(kind==='timeout')x.timers[0]();
    if(kind==='failed'){x.feed({event:'stopping',id});x.child.emit('close',1);}
    if(kind==='unconfirmed')x.child.emit('close',0);
    await assert.rejects(p);assert.equal(x.writes.length,1,'never repeats or force-kills a worker');
  }
});
test('protocol records split across stdout chunks stay private and ordinary logs survive',()=>{
  const x=pipe(),line=H.PREFIX+JSON.stringify({v:1,pid:42,secret:'a'.repeat(64),event:'ready'})+'\n';
  assert.equal(x.control.feed('hello\n'+line.slice(0,10)),'hello\n');
  assert.equal(x.control.feed(line.slice(10)), '');assert.equal(x.control.ready(),true);
});
function actions(overrides={}) {
  const calls=[];
  const io={lock:v=>calls.push('lock:'+v),inspect:async()=>{calls.push('inspect');return null;},
    stopWorker:async()=>calls.push('stop'),save:()=>{calls.push('save');return 'nonce';},launch:()=>calls.push('launch'),
    resumeWorker:async()=>calls.push('resume'),...overrides};
  return {calls,io};
}
test('restart saves and launches only after the idle worker has actually closed and final inspection passes',async()=>{
  const x=actions();assert.equal((await H.perform(x.io,value().state)).state,'relaunching');
  assert.deepEqual(x.calls,['lock:true','inspect','stop','inspect','save','launch']);
});
test('busy before shutdown, activity after shutdown, disk failure, or launch failure preserve current desktop',async()=>{
  for(const failure of ['busy','late','save','launch']) {
    let count=0; const x=actions();
    x.io.inspect=async()=>{x.calls.push('inspect');return ++count===(failure==='busy'?1:failure==='late'?2:0)?'active work':null;};
    if(failure==='save')x.io.save=()=>{throw Error('disk failure');};
    if(failure==='launch')x.io.launch=()=>{throw Error('launch failure');};
    assert.equal((await H.perform(x.io,value().state)).state,'pending');
    assert.deepEqual(x.calls.slice(-2),['lock:false','resume']);
    if(failure==='busy')assert.ok(!x.calls.includes('stop'));
  }
});
test('desktop compact stream receives non-bubbling watchdog status through capture',()=>{
  const html=fs.readFileSync(require.resolve('../clients/desktop/index.html'),'utf8');
  const src=html.slice(html.indexOf("document.addEventListener('gbox-stream-state'"),html.indexOf('function compactHover('));
  let listener,capture;const sent=[];
  vm.runInNewContext(src,{COMPACT:{on:true,sid:'exact-B'},JSON,document:{addEventListener:(_n,fn,c)=>{listener=fn;capture=c;},
    querySelector:()=>({executeJavaScript:s=>{sent.push(s);return Promise.resolve();}})}});
  assert.equal(capture,true);
  // DOM capture visits the document even when the target's custom event does not bubble.
  if(capture)listener({target:{id:'compact-stream'},detail:{connected:false},bubbles:false});
  assert.match(sent[0],/exact-B/);assert.match(sent[0],/false/);
});
test('handoff shutdown and startup skip broad cleanup, game snapshots and Spark bootstrap',()=>{
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  const branch=main.slice(main.indexOf('if (clientRefreshExit)'),main.indexOf('try { embedder && embedder.stdin.write',main.indexOf('if (clientRefreshExit)')));
  assert.match(branch,/return;/);assert.doesNotMatch(branch,/cleanupSessions|taskkill|keepMoments|ssh\(/);
  const startup=main.slice(main.indexOf('if (startupHandoff.requested) {'),main.indexOf('} else cleanupSessions',main.indexOf('if (startupHandoff.requested) {')));
  assert.match(startup,/startWorker\(\)/);assert.doesNotMatch(startup.replace(/\/\/[^\n]*/g,''),/cleanupSessions|bootstrap|ssh\(/);
});

test('actual F5 IPC relaunches exactly once only after idle exit, otherwise refreshes views and reports pending',async()=>{
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  const src=main.slice(main.indexOf('function assertClientSender('),main.indexOf('let clientVersions ='));
  for(const busy of [false,true]) {
    const calls=[],timers=[];let handler;
    const wc={mainFrame:{},reloadIgnoringCache:()=>calls.push('renderer')};
    const ctx=vm.createContext({ipcMain:{handle:(_n,fn)=>{handler=fn;}},win:{webContents:wc},clientReloading:false,
      clientVersions:{read:async()=>({restart:true})},clientActivation:{},worker:{pid:42},workerControl:{stop:async()=>{calls.push('idle-exit');ctx.worker=null;}},
      clientHandoff:{...H,save:(_file,v)=>{assert.equal(v.state.sid,'pip-B');assert.equal(v.state.guest.playing,'main-A');calls.push('save');return 'opaque';}},
      clientViews:require('../clients/desktop/client-view-store.cjs'),
      inspectClientIdle:async()=>busy?'active local game':null,compactWindow:{handoff:()=>({window:value().window})},
      settings:()=>({autoStartWorker:true}),mini:null,pendingMini:null,miniSession:null,CLIENT_HANDOFF_FILE:'owned-fixture',
      process:{pid:12,argv:['electron','app',H.ARG+'old']},app:{relaunch:args=>{calls.push('launch');assert.deepEqual([...args.args],['app',H.ARG+'opaque']);},exit:()=>calls.push('exit')},
      setTimeout:f=>timers.push(f),shutdownSessions:()=>calls.push('safe-cleanup'),startWorker:async()=>calls.push('resume')});
    vm.runInContext(src,ctx);
    const result=await handler({sender:wc,senderFrame:wc.mainFrame},value().state);
    if(busy){assert.equal(result.state,'pending');assert.deepEqual(calls,['renderer']);assert.equal(ctx.clientHandoffBusy,false);}
    else{assert.equal(result.state,'relaunching');assert.deepEqual(calls,['idle-exit','save','launch']);assert.equal(ctx.clientRefreshExit,true);
      assert.equal(await handler({sender:wc},value().state),false);timers[0]();assert.deepEqual(calls.slice(-2),['safe-cleanup','exit']);}
  }
});

test('queued and in-flight native attach or GPU capture refuse idle handoff before embedded PID is published',async()=>{
  const main=fs.readFileSync(require.resolve('../clients/desktop/main.js'),'utf8');
  const inspect=main.slice(main.indexOf('async function inspectClientIdle()'),main.indexOf('function assertClientSender('));
  const handler=main.slice(main.indexOf('ipcMain.handle("embed:sync"'),main.indexOf('async function syncEmbeddedGame('));
  let sync,release;const ctx=vm.createContext({ipcMain:{handle:(_n,fn)=>{sync=fn;}},embedSyncQueue:Promise.resolve(),embedSyncPending:0,
    clientHandoffBusy:false,STANDALONE:false,startupHandoff:null,workerStarting:null,procs:new Map(),rec:null,recFitBusy:false,embedded:null,
    syncGameSurface:()=>new Promise(r=>{release=r;}),settings:()=>assert.fail('pending native work must stop before process inspection')});
  vm.runInContext(inspect+handler,ctx);
  const pending=sync({}, {pid:123});
  assert.equal(ctx.embedSyncPending,1);assert.equal(ctx.embedded,null);
  assert.match(await ctx.inspectClientIdle(),/pending game-window/);
  await Promise.resolve();assert.equal(ctx.embedSyncPending,1);assert.match(await ctx.inspectClientIdle(),/pending game-window/);
  ctx.clientHandoffBusy=true;assert.equal(sync({}, {pid:456}).ok,false);assert.equal(ctx.embedSyncPending,1);
  release({ok:true});await pending;assert.equal(ctx.embedSyncPending,0);
  ctx.clientHandoffBusy=false;ctx.syncGameSurface=async()=>{throw Error('capture failed');};
  await assert.rejects(sync({}, {pid:123}),/capture failed/);assert.equal(ctx.embedSyncPending,0);
});
