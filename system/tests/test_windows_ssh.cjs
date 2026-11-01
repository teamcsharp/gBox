const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const W=require('../clients/desktop/windows-ssh.cjs');
const UI=require('../clients/desktop/windows-ssh-ui.js');
const state=(changes={})=>({installed:true,builtin:true,running:false,listening:false,reachable:false,firewall:'scoped',startup_type:'Manual',...changes});
function fixture(values=[],initial=false) {
  const calls=[],events=[];let preference=initial;
  const api=W.create({platform:'win32',systemRoot:'C:\\Windows',getPreference:()=>preference,
    savePreference:value=>{preference=value;},changed:value=>events.push(value),
    execute:(exe,args,opts,cb)=>{calls.push({exe,args,opts,source:Buffer.from(args.at(-1),'base64').toString('utf16le')});
      const value=values.shift();queueMicrotask(()=>cb(value?.error||null,JSON.stringify(value?.data||state())));}});
  return {api,calls,events};
}
test('read-only status separates missing, stopped, running and unreachable',async()=>{
  for(const [value,expected]of [[state({installed:false,builtin:false}),'not_installed'],[state(),'stopped'],
      [state({running:true,listening:true,reachable:true}),'running'],[state({running:true}),'unreachable']]){
    const f=fixture([{data:value}]);assert.equal((await f.api.status()).state,expected);
    assert.equal(f.calls.length,1);assert.equal(f.calls[0].source,W.STATUS);assert.equal(f.calls[0].opts.windowsHide,true);
  }
});
test('default app startup reads status without prompting or changing service',async()=>{
  const f=fixture();await f.api.startup();await f.api.startup();assert.equal(f.calls.length,1);
});
test('saved opt-in starts a stopped service once using the fixed UAC operation',async()=>{
  const f=fixture([{data:state()},{},{data:state({running:true,listening:true,reachable:true})}],true);
  assert.equal((await f.api.startup()).state,'running');await f.api.startup();assert.equal(f.calls.length,3);
  assert.match(f.calls[1].source,/-Verb RunAs -WindowStyle Hidden -PassThru/);
  assert.ok(f.calls[1].source.includes(Buffer.from(W.ENABLE,'utf16le').toString('base64')));
  assert.equal(f.calls[1].opts.timeout,1200000);assert.equal(f.calls[1].exe,'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe');
});
test('running or custom services and unreadable status never trigger startup elevation',async()=>{
  for(const value of [{data:state({running:true,reachable:true})},{data:state({builtin:false})},{error:{code:1}}]){
    const f=fixture([value],true);await f.api.startup();assert.equal(f.calls.length,1);
  }
});
test('preference persists explicitly without installing or starting anything',async()=>{
  const f=fixture();assert.equal((await f.api.preference(true)).auto_start,true);assert.equal(f.calls.length,0);
  assert.equal((await f.api.preference(false)).auto_start,false);
  await assert.rejects(f.api.preference('true'),/boolean/);
});
test('concurrent enable requests share one elevation; cancellation stays explicit',async()=>{
  const f=fixture([{error:{code:1223}},{data:state()}]);
  const [a,b]=await Promise.all([f.api.enable(),f.api.enable()]);
  assert.equal(f.calls.length,2);assert.match(a.message,/cancelled/);assert.equal(b.state,'stopped');
  assert.equal(f.api.snapshot().busy,false);
});
test('uncertain elevated operation is never automatically retried',async()=>{
  const f=fixture([{error:{code:'ETIMEDOUT',killed:true}},{data:state()}]);
  assert.equal((await f.api.enable()).uncertain,true);await f.api.enable();assert.equal(f.calls.length,2);
  assert.match(f.api.snapshot().message,/will not repeat/);
});
test('Windows setup failures remain failures even with installed status',async()=>{
  const f=fixture([{error:{code:22}},{data:state()}]);
  const result=await f.api.enable();assert.match(result.message,/could not configure/);assert.equal(result.state,'stopped');
});
test('unsupported hosts perform no subprocess or service operation',async()=>{
  const api=W.create({platform:'linux',execute:()=>assert.fail('no process')});
  assert.equal((await api.startup()).state,'unsupported');assert.equal((await api.enable()).supported,false);
});
test('setup limits firewall to local subnet and never changes credentials or boot startup policy',()=>{
  assert.match(W.ENABLE,/OpenSSH\.Server~~~~0\.0\.1\.0/);
  for(const line of W.ENABLE.split('\n').filter(line=>/\b(?:New|Set)-NetFirewallRule\b/.test(line))){
    assert.match(line,/-Profile Private,Domain/);assert.match(line,/-RemoteAddress LocalSubnet/);assert.match(line,/-Program \$expected/);
    assert.doesNotMatch(line,/-Profile Any|-RemoteAddress Any/);
  }
  assert.match(W.ENABLE,/if \(!\$defaultExisted/);
  assert.match(W.ENABLE,/Global\\gBox\.OpenSSH\.Setup/);
  assert.match(W.ENABLE,/\$rule\.Group -ne 'gBox.OpenSSH'/);
  assert.doesNotMatch(W.ENABLE,/authorized_keys|Set-LocalUser|Set-Content|StartupType Automatic|Restart-Service|Stop-Service/);
  assert.doesNotMatch(W.STATUS,/Start-Service|Set-Service|Add-WindowsCapability|New-NetFirewallRule|Set-NetFirewallRule/);
});
test('SSH IPC allows only owned local main frames, including legacy PiP',()=>{
  const main=fs.readFileSync(path.join(__dirname,'../clients/desktop/main.js'),'utf8');
  const source=main.slice(main.indexOf('function assertSshSender(event) {'),main.indexOf("ipcMain.handle('ssh:status'"));
  const base=path.resolve(__dirname,'../clients/desktop');
  const local=name=>require('node:url').pathToFileURL(path.join(base,name)).href;
  const windowAt=url=>({isDestroyed:()=>false,webContents:{mainFrame:{},getURL:()=>url}});
  const win=windowAt(local('index.html')),mini=windowAt(local('mini.html')+'?src=stream&title=test');
  const check=require('node:vm').runInNewContext(source+';assertSshSender',{win,mini,URL,require,path,__dirname:base});
  const event=owner=>({sender:owner.webContents,senderFrame:owner.webContents.mainFrame});
  check(event(win));check(event(mini));
  assert.throws(()=>check({...event(win),senderFrame:{}}));
  assert.throws(()=>check({sender:windowAt(local('index.html')).webContents,senderFrame:win.webContents.mainFrame}));
  for(const bad of ['https://example.org/mini.html',local('index.html'),local('mini.html')+'#remote']){
    mini.webContents.getURL=()=>bad;assert.throws(()=>check(event(mini)));
  }
  win.webContents.getURL=()=>local('index.html')+'?redirect=1';assert.throws(()=>check(event(win)));
  for(const op of ['status','enable','preference'])assert.match(main,new RegExp("ipcMain.handle\\('ssh:"+op+"',[^\\n]+assertSshSender\\(event\\)"));
});

test('status captions do not claim that local port reachability proves remote login',()=>{
  assert.match(UI.describe({supported:true,state:'running',firewall:'scoped'}),/local TCP port 22/);
  assert.match(UI.describe({supported:true,state:'unreachable'}),/not reachable/);
  assert.match(UI.describe({supported:true,state:'not_installed'}),/not installed/);
});
test('settings panel saves its opt-in and starts only on the explicit button',async()=>{
  const elements=new Map(),host={innerHTML:'',querySelector:key=>{
    if(!elements.has(key))elements.set(key,{textContent:'',checked:false,disabled:false});return elements.get(key);
  }};
  const sent=[];let current={supported:true,state:'stopped',auto_start:false},notify;
  UI.mount(host,{sshStatus:async()=>current,onSshChanged:fn=>{notify=fn;},
    sshPreference:async value=>{sent.push(['preference',value]);return current={...current,auto_start:value};},
    sshEnable:async()=>{sent.push(['enable']);return current={...current,state:'running',firewall:'scoped'};}});
  await new Promise(resolve=>setImmediate(resolve));
  const auto=host.querySelector('[data-ssh-auto]'),enable=host.querySelector('[data-ssh-enable]');
  assert.deepEqual(sent,[]);assert.equal(enable.disabled,false);
  auto.checked=true;await auto.onchange();assert.deepEqual(sent,[['preference',true]]);assert.equal(auto.checked,true);
  await enable.onclick();assert.deepEqual(sent,[['preference',true],['enable']]);
  assert.match(host.querySelector('[data-ssh-status]').textContent,/local TCP port 22/);
  notify({...current,busy:true});assert.equal(enable.disabled,true);
  notify({...current,uncertain:true});assert.equal(enable.disabled,true);
  auto.checked=false;await auto.onchange();assert.equal(auto.checked,false);
  assert.match(host.innerHTML,/does not verify remote login/);
});

function quickFixture(options={}) {
  function element(){return {textContent:'',checked:false,disabled:false,hidden:false,dataset:{},attributes:{},
    setAttribute(k,v){this.attributes[k]=v;},focus(){this.focused=true;this.focusCount=(this.focusCount||0)+1;},addEventListener(k,v){this[k]=v;}};}
  function host(){const nodes=new Map();return {...element(),innerHTML:'',querySelector:k=>{if(!nodes.has(k))nodes.set(k,element());return nodes.get(k);}};}
  const settings=host(),popup=host(),button=host(),calls=[];
  let mode=options.mode||'',modeChanged;
  button.ownerDocument={body:{classList:{contains:name=>name===mode}},defaultView:{MutationObserver:class{constructor(fn){modeChanged=fn;}observe(){}disconnect(){}}}};let current=options.current||{supported:true,state:'stopped',auto_start:false},notify,finish;
  const io={sshStatus:async()=>{calls.push('status');return current;},onSshChanged:fn=>{notify=fn;},
    sshPreference:async value=>{calls.push('preference');return current={...current,auto_start:value};},
    sshEnable:()=>{calls.push('enable');return new Promise(resolve=>{finish=resolve;});}};
  Object.assign(io,options.io||{});
  const control=UI.mount(settings,io,{button,popup,restart:options.restart});
  return {settings,popup,button,calls,control,setMode:value=>{mode=value;modeChanged?.();},notify:value=>{current=value;notify(value);},finish:value=>{current=value;finish(value);}};
}
test('persistent launcher starts SSH on click; running-state panel shares preference and explicit setup',async()=>{
  const f=quickFixture();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.button.querySelector('[data-ssh-caption]').textContent,'Enable SSH');
  assert.match(f.button.title,/Enable SSH on this PC/);assert.equal(f.popup.hidden,true);assert.deepEqual(f.calls,['status']);
  const first=f.button.onclick();assert.equal(f.calls.at(-1),'enable');
  f.finish({supported:true,state:'running',auto_start:false,setup_result:'success',message:'Windows SSH setup completed.'});await first;
  assert.equal(f.popup.hidden,false);assert.equal(f.button.attributes['aria-expanded'],'true');assert.deepEqual(f.calls,['status','enable']);
  assert.equal(f.button.querySelector('[data-ssh-caption]').textContent,'SSH: On');
  await f.control.refresh();assert.equal(f.button.querySelector('[data-ssh-caption]').textContent,'SSH: On');
  f.notify({supported:true,state:'running',auto_start:false,setup_result:'success',message:'Windows SSH setup completed.'});
  const auto=f.popup.querySelector('[data-ssh-auto]');auto.checked=true;await auto.onchange();
  assert.equal(f.settings.querySelector('[data-ssh-auto]').checked,true);assert.equal(f.calls.filter(x=>x==='enable').length,1);
  const pending=f.popup.querySelector('[data-ssh-enable]').onclick();
  assert.equal(f.settings.querySelector('[data-ssh-enable]').disabled,true);
  await f.settings.querySelector('[data-ssh-enable]').onclick();assert.equal(f.calls.filter(x=>x==='enable').length,2);
  f.finish({supported:true,state:'running',auto_start:true,firewall:'scoped'});await pending;
  assert.equal(f.button.querySelector('[data-ssh-caption]').textContent,'SSH: On');
  let stopped=false;f.popup.keydown({key:'Escape',preventDefault(){},stopPropagation(){stopped=true;}});
  assert.equal(f.popup.hidden,true);assert.equal(stopped,true);assert.equal(f.button.focused,true);
});
test('launcher preserves custom, unsupported, busy and uncertain setup guards even for direct handlers',async()=>{
  const f=quickFixture();await new Promise(resolve=>setImmediate(resolve));
  for(const state of [{supported:true,state:'custom_installation'},{supported:false,state:'unsupported'},
      {supported:true,state:'stopped',busy:true},{supported:true,state:'stopped',uncertain:true}]){
    f.notify(state);assert.equal(f.popup.querySelector('[data-ssh-enable]').disabled,true);
    await f.popup.querySelector('[data-ssh-enable]').onclick();
  }
  assert.equal(f.calls.includes('enable'),false);
  f.notify({supported:true,state:'stopped',setup_result:'failure',message:'Windows administrator prompt cancelled.'});
  assert.equal(f.button.querySelector('[data-ssh-caption]').textContent,'SSH: Error');
  assert.match(f.popup.querySelector('[data-ssh-status]').textContent,/cancelled/);
  f.notify({supported:false,state:'unsupported'});assert.equal(f.button.hidden,true);
});
test('SSH stays visible and receives native window holes in both compact and legacy PiP',()=>{
  const desktop=path.join(__dirname,'../clients/desktop');
  const index=fs.readFileSync(path.join(desktop,'index.html'),'utf8');
  const mini=fs.readFileSync(path.join(desktop,'mini.html'),'utf8');
  for(const html of [index,mini]){
    assert.match(html,/id="ssh-access-button"/);assert.match(html,/id="ssh-access-popover" role="dialog"/);
    assert.match(html,/GBoxWindowsSsh.mount/);
  }
  assert.match(index,/:not\(#ssh-access-button\):not\(#ssh-access-popover\)/);
  assert.match(index,/COMPACT.on \? "#ssh-access-button:not\(\[hidden\]\), #ssh-access-popover:not\(\[hidden\]\)/);
  assert.match(index,/const COMPACT_PANELS = '#ssh-access-button, #ssh-access-popover/);
  const f=quickFixture();assert.match(f.popup.innerHTML,/body.gbox-compact #ssh-access-button,body.ssh-mini #ssh-access-button/);
  assert.doesNotMatch(f.popup.innerHTML,/opacity:0|pointer-events:none/);
  assert.match(f.popup.innerHTML,/@media\(max-width:1500px\)/);
  assert.match(f.popup.innerHTML,/body.ssh-mini #ssh-access-button \{top:38px;right:8px;bottom:auto;/);
  assert.match(f.popup.innerHTML,/body.ssh-mini #ssh-access-popover \{top:74px/);
  assert.match(f.popup.innerHTML,/@media\(max-height:220px\)/);
  assert.match(f.popup.innerHTML,/width:calc\(100vw - 8px\);max-height:calc\(100vh - 8px\)/);
  assert.match(f.popup.innerHTML,/max-width:calc\(100vw - 16px\);box-sizing:border-box/);
});

test('successful setup remains On after later status reads; status failures recover explicitly',async()=>{
  const f=fixture([{}, {data:state({running:true,reachable:true})}, {data:state({running:true,reachable:true})},
    {error:{code:1}}, {data:state({running:true,reachable:true})}]);
  const done=await f.api.enable();assert.equal(done.setup_result,'success');assert.equal(UI.badge(done),'SSH: On');
  assert.equal(UI.badge(await f.api.status()),'SSH: On');
  assert.equal(UI.badge(await f.api.status()),'SSH: Error');
  const recovered=await f.api.status();assert.equal(UI.badge(recovered),'SSH: On');assert.equal(recovered.message,'');
});
test('unknown or custom launcher opens status without elevation',async()=>{
  const f=quickFixture();await new Promise(resolve=>setImmediate(resolve));
  for(const state of [{supported:true,state:'unknown'},{supported:true,state:'custom_installation'},
      {supported:true,state:'stopped',uncertain:true},{supported:true,state:'stopped',busy:true}]){
    f.popup.hidden=true;f.notify(state);await f.button.onclick();assert.equal(f.popup.hidden,false);
  }
  assert.equal(f.calls.includes('enable'),false);
});

test('setup completion reads fresh status after an older overlapping refresh',async()=>{
  const callbacks=[],events=[];
  const api=W.create({platform:'win32',changed:value=>events.push(value),
    execute:(_exe,_args,_opts,callback)=>callbacks.push(callback)});
  const old=api.status(),setup=api.enable();assert.equal(callbacks.length,2);
  assert.equal(events.at(-1).busy,true);
  callbacks[1](null,'');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(callbacks.length,2); // older probe must settle first
  callbacks[0](null,JSON.stringify(state()));await old;await new Promise(resolve=>setImmediate(resolve));
  assert.equal(callbacks.length,3);
  callbacks[2](null,JSON.stringify(state({running:true,reachable:true})));
  const result=await setup;assert.equal(result.state,'running');assert.equal(result.busy,false);
  assert.equal(UI.badge(result),'SSH: On');
});

test('unknown Windows status offers explicit force setup and never starts it on refresh or launcher',async()=>{
  const f=quickFixture({current:{supported:true,state:'unknown',status_error:true,status_error_kind:'status_command_failed'}});
  await new Promise(resolve=>setImmediate(resolve));
  const force=f.popup.querySelector('[data-ssh-force]');assert.equal(force.hidden,false);assert.equal(force.disabled,false);
  assert.equal(f.popup.querySelector('[data-ssh-enable]').disabled,true);
  await f.button.onclick();assert.equal(f.calls.includes('enable'),false);
  const setup=force.onclick();assert.equal(f.calls.filter(x=>x==='enable').length,1);assert.equal(force.disabled,true);
  await force.onclick();assert.equal(f.calls.filter(x=>x==='enable').length,1);
  f.finish({supported:true,state:'running',setup_result:'success'});await setup;
  assert.equal(f.button.querySelector('[data-ssh-caption]').textContent,'SSH: On');assert.equal(force.hidden,true);
});
test('force setup never bypasses unsupported custom busy or uncertain state',async()=>{
  const f=quickFixture();await new Promise(resolve=>setImmediate(resolve));
  for(const state of [{supported:false,state:'unknown'},{supported:true,state:'custom_installation'},
      {supported:true,state:'unknown',busy:true},{supported:true,state:'unknown',uncertain:true}]){
    f.notify(state);await f.popup.querySelector('[data-ssh-force]').onclick();
  }
  assert.equal(f.calls.includes('enable'),false);
});
test('missing bridge and missing IPC handler show restart and never invoke a force fallback',async()=>{
  for(const io of [{sshStatus:undefined},{sshStatus:async()=>{throw Error("Error invoking remote method 'ssh:status': Error: No handler registered for ssh:status");}}]){
    let restarts=0;
    const f=quickFixture({io:{sshPlatform:'win32',...io},restart:async()=>{restarts++;return {reason:'Guarded restart requested'};}});
    await new Promise(resolve=>setImmediate(resolve));
    const status=f.popup.querySelector('[data-ssh-status]').textContent;
    assert.match(status,/bridge|no SSH handler/);assert.match(status,/Restart/);
    assert.equal(f.popup.querySelector('[data-ssh-force]').disabled,true);
    await f.popup.querySelector('[data-ssh-force]').onclick();assert.equal(f.calls.includes('enable'),false);
    const restart=f.popup.querySelector('[data-ssh-restart]');assert.equal(restart.hidden,false);assert.equal(restart.disabled,false);
    await restart.onclick();assert.equal(restarts,1);assert.match(f.popup.querySelector('[data-ssh-status]').textContent,/Guarded restart/);
  }
});
test('window-identity rejection is distinct and cannot force setup',async()=>{
  const f=quickFixture({io:{sshPlatform:'win32',sshStatus:async()=>{throw Error('Only the local gBox window can manage Windows SSH.');}}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(f.popup.querySelector('[data-ssh-status]').textContent,/window identity/);
  assert.equal(f.popup.querySelector('[data-ssh-force]').disabled,true);
});
test('setup handler missing is safe to restart but an uncertain setup reply stays locked',async()=>{
  for(const [message,uncertain]of [["No handler registered for 'ssh:enable'",false],['IPC reply lost',true]]){
    let calls=0;
    const f=quickFixture({current:{supported:true,state:'unknown'},io:{sshEnable:async()=>{calls++;throw Error(message);}}});
    await new Promise(resolve=>setImmediate(resolve));await f.popup.querySelector('[data-ssh-force]').onclick();
    await f.popup.querySelector('[data-ssh-force]').onclick();assert.equal(calls,1);
    assert.equal(f.popup.querySelector('[data-ssh-restart]').hidden,uncertain);
    assert.equal(f.popup.querySelector('[data-ssh-force]').disabled,true);
  }
});
test('backend status failure categories remain supported and allow explicit fixed-script setup',async()=>{
  for(const [error,kind]of [[{code:1},'status_command_failed'],[{code:'ENOENT'},'powershell_missing'],[{code:'ETIMEDOUT',killed:true},'status_timeout']]){
    const f=fixture([{error},{},{data:state({running:true,reachable:true})}]);
    const status=await f.api.status();assert.equal(status.supported,true);assert.equal(status.status_error_kind,kind);
    assert.match(status.message,/Force enable SSH/);assert.equal(f.calls.length,1);
    assert.equal((await f.api.enable()).state,'running');assert.match(f.calls[1].source,/-Verb RunAs/);
  }
  const api=W.create({platform:'win32',execute:()=>{throw Object.assign(Error('spawn failed'),{code:'ENOENT'});}});
  assert.equal((await api.status()).status_error_kind,'powershell_missing');
});
test('restart guidance never invokes any reload or broad Spark relaunch',()=>{
  const index=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const block=index.slice(index.indexOf('const windowsSshPanel'),index.indexOf('const FIELDS'));
  assert.match(block,/GBoxWindowsSsh.restartGuidance\(gbox/);assert.doesNotMatch(block,/clientRefresh|clientReload|gbox.relaunch/);
  const mini=fs.readFileSync(path.join(__dirname,'../clients/desktop/mini.html'),'utf8');
  assert.match(mini,/restartLabel:'Open full app for recovery'/);assert.match(mini,/await gbox.miniRestore\(\)/);
});

test('update check reports each outcome with manual restart guidance and never consumes an F5 force latch',async()=>{
  let updated=0;const io={clientReload:()=>assert.fail('no reload'),relaunch:()=>assert.fail('no relaunch'),
    clientUpdate:async()=>{updated++;return {state:'current',restart:true,version:{restart:true}};}};
  const current=await UI.restartGuidance(io);assert.match(current.reason,/files are current/);assert.match(current.reason,/Quit the full/);assert.equal(updated,1);
  assert.match((await UI.restartGuidance({})).reason,/no local updater bridge/);
  for(const state of ['updated','waiting','skipped','failed']){
    io.clientUpdate=async()=>({state,detail:'Specific update result'});
    const result=await UI.restartGuidance(io);assert.match(result.reason,/Specific update result/);assert.match(result.reason,/Quit the full/);
    assert.equal(result.state,undefined); // no claimed activation or restart receipt
  }
});

test('unconfirmed Windows capability never advertises an executable force action after generic IPC failure',async()=>{
  const f=quickFixture({io:{sshStatus:async()=>{throw Error('IPC disconnected');}},restart:async()=>({reason:'Manual restart instructions'})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.popup.querySelector('[data-ssh-force]').disabled,true);
  assert.equal(f.popup.querySelector('[data-ssh-restart]').hidden,false);
  assert.match(f.popup.querySelector('[data-ssh-status]').textContent,/confirm its Windows backend/);
  await f.popup.querySelector('[data-ssh-force]').onclick();assert.equal(f.calls.includes('enable'),false);
  await f.popup.querySelector('[data-ssh-restart]').onclick();assert.match(f.popup.querySelector('[data-ssh-status]').textContent,/Manual restart instructions/);
});

test('healthy SSH hides only compact and mini launchers and closes a popup when its mode changes',async()=>{
  const f=quickFixture({current:{supported:true,state:'running',setup_result:'success'}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.button.hidden,false,'full app retains its launcher');assert.equal(f.button.dataset.healthy,'true');
  await f.button.onclick();assert.equal(f.popup.hidden,false);
  f.setMode('gbox-compact');assert.equal(f.popup.hidden,true);assert.equal(f.button.attributes['aria-expanded'],'false');
  f.setMode('');await f.button.onclick();assert.equal(f.popup.hidden,false);
  f.setMode('ssh-mini');assert.equal(f.popup.hidden,true);
  const focusCount=f.button.focusCount;f.notify({supported:true,state:'running'});f.setMode('ssh-mini');assert.equal(f.button.focusCount,focusCount,'repeated healthy paints never steal focus');
  assert.match(f.popup.innerHTML,/body.gbox-compact #ssh-access-button\[data-healthy=true\],body.ssh-mini #ssh-access-button\[data-healthy=true\] \{display:none!important;/);
  f.notify({supported:true,state:'running',setup_result:'failure',message:'Setup failed'});
  assert.equal(f.button.dataset.healthy,'false');assert.equal(f.button.hidden,false);
});
test('pending uncertain and failed SSH states remain visible even if service reports running',()=>{
  assert.equal(UI.healthy({state:'running',setup_result:'success'}),true);
  for(const value of [{state:'stopped'},{state:'unreachable'},{state:'running',busy:true},{state:'running',uncertain:true},
      {state:'running',setup_result:'failure'},{state:'running',status_error:true},{state:'running',ui_error:true}])assert.equal(UI.healthy(value),false);
});
