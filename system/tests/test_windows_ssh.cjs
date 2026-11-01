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
test('IPC service operations require the local main frame, not a guest or remote page',()=>{
  const main=fs.readFileSync(path.join(__dirname,'../clients/desktop/main.js'),'utf8');
  assert.match(main,/function assertSshSender\(event\) \{\s*assertClientSender\(event\);/);
  assert.match(main,/event\.sender\.getURL\(\) !== require\('node:url'\)\.pathToFileURL/);
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
