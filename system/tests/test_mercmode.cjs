const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../clients/web/viz/mercmode.js');
test('stay targets only the exact displayed MercMode session',async()=>{
 const calls=[],api=async(path,body)=>{calls.push([path,body]);return {hosts:[{name:'lilspark',current_run:{session_id:'w-current',mercmode:{title:'re5'}}}]};};
 assert.equal(await M.stay(api,'w-current'),'lilspark');
 assert.deepEqual(calls[1],['/api/mercmode',{host:'lilspark',enabled:false}]);
 await assert.rejects(M.stay(api,'w-old'),/no longer/);
 assert.equal(calls.filter(c=>c[1]).length,1);
});
test('each host owns its settings and unavailable RE6 gives its reason',()=>{
 const html=M.render({hosts:[{name:'lilspark',id:'w1',online:true,settings:{enabled:true,titles:['re4','re5','re6'],rounds_per_title:1},titles:[{title:'re6',name:'Resident Evil 6',playable:false,reason:'No verified combat driver <pending>'}]}]});
 assert.match(html,/data-host="lilspark"/);assert.match(html,/No verified combat driver &lt;pending&gt;/);
 assert.match(html,/unavailable/);assert.match(html,/Check cached assets/);assert.match(html,/instant saved-state loading is unavailable/);
 assert.doesNotMatch(html,/onclick|onerror|<pending>/);
});
test('opening the panel only reads status',async()=>{
 const calls=[],listeners=new Map(),root={innerHTML:'',addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
 const panel=M.mount({root,api:async(path,body)=>{calls.push([path,body]);return {hosts:[]};}});
 await panel.ready;assert.deepEqual(calls,[['/api/mercmode',undefined]]);panel.dispose();assert.equal(listeners.size,0);
});
test('operator can adopt the exact displayed solo bot without submitting a new launch',async()=>{
 const calls=[],listeners=new Map(),host={dataset:{host:'lilspark'}},sid='worker-current';
 const button={dataset:{adopt:sid},closest:()=>host,hasAttribute:key=>key==='data-adopt'};
 const root={innerHTML:'',addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
 const data={hosts:[{name:'lilspark',id:'worker',online:true,settings:{enabled:true},adoptable_solo_session:sid,titles:[]}]};
 const panel=M.mount({root,api:async(path,body)=>{calls.push([path,body]);return data;}});
 await panel.ready;assert.match(root.innerHTML,/Use current solo bot/);
 await listeners.get('click')({target:{closest:()=>button}});
 assert.deepEqual(calls,[['/api/mercmode',undefined],['/api/mercmode/adopt',{host:'lilspark',session_id:sid}],['/api/mercmode',undefined]]);
 panel.dispose();
});
test('continuous presentation saves an explicit host setting',async()=>{
 const calls=[],listeners=new Map(),host={dataset:{host:'lilspark'},
  querySelectorAll:()=>[{dataset:{title:'re4'}},{dataset:{title:'re5'}}],
  querySelector:key=>key==='[data-rounds]'?{value:'1'}:{checked:true}};
 const button={closest:()=>host,hasAttribute:key=>key==='data-save'};
 const root={innerHTML:'',addEventListener:(n,fn)=>listeners.set(n,fn),removeEventListener:n=>listeners.delete(n)};
 const panel=M.mount({root,api:async(path,body)=>{calls.push([path,body]);return {hosts:[]};}});
 await panel.ready;await listeners.get('click')({target:{closest:()=>button}});
 assert.deepEqual(calls[1],['/api/mercmode',{host:'lilspark',enabled:true,presentation_priority:true,titles:['re4','re5'],rounds_per_title:1}]);
 panel.dispose();
});
test('a paired PC distinguishes its observed settings from pending central requests',()=>{
 const html=M.render({hosts:[{name:'paired',id:'w1',online:true,scheduler_owner:'local',
   settings:{enabled:false,titles:['re5']},desired_settings:{enabled:true},command:{job:'j',state:'queued'},titles:[]}]});
 assert.match(html,/including while disconnected/);assert.match(html,/Requested setting: on/);
 assert.match(html,/queued/);assert.doesNotMatch(html,/data-enabled checked/);
});
test('the PiP menu resolves the host that owns the displayed session and renders one toggle plus the title list',()=>{
 const data={hosts:[{name:'i9-NUC',id:'w9',settings:{enabled:false,titles:['re4']},titles:[]},
  {name:'lilspark',id:'w1',settings:{enabled:true,titles:['re4','re5'],rounds_per_title:2},current_run:{session_id:'w1-abc',phase:'playing',title:'Resident Evil 5',mercmode:{title:'re5'},mercmode_rounds:3},
   titles:[{title:'re4',name:'Resident Evil 4',playable:true},{title:'re5',name:'Resident Evil 5',playable:true},{title:'re6',name:'Resident Evil 6',playable:false,reason:'no driver <x>'}]}]};
 assert.equal(M.hostFor(data,'w1-abc').name,'lilspark');
 assert.equal(M.hostFor(data,'w9-zzz').name,'i9-NUC');
 assert.equal(M.hostFor(data,'nope',' i9-NUC'.trim()).name,'i9-NUC');
 assert.equal(M.hostFor(data,null,null),null);
 const html=M.menuHTML(M.hostFor(data,'w1-abc'));
 assert.match(html,/rotating titles · click to stay/);assert.match(html,/data-mm-title="re4" checked/);assert.match(html,/data-mm-title="re6"[^>]*disabled/);
 assert.match(html,/no driver &lt;x&gt;/);assert.match(html,/value="2"/);assert.match(html,/3 verified rounds/);assert.match(html,/hidden/);
 assert.match(M.menuHTML(data.hosts[0],true),/play across titles · click to turn on/);
 assert.doesNotMatch(M.menuHTML(data.hosts[0],true),/hidden/);
 assert.match(M.menuHTML(null),/no gBox PC/);
});
test('menu actions post exact host settings and refuse an empty rotation',async()=>{
 const calls=[],api=async(path,body)=>{calls.push([path,body]);return {};};
 const host={name:'lilspark',settings:{enabled:true,titles:['re4','re5']}};
 assert.match(await M.menuAction(api,host,'toggle'),/rotation off/);
 assert.deepEqual(calls.at(-1),['/api/mercmode',{host:'lilspark',enabled:false}]);
 assert.match(await M.menuAction(api,{...host,settings:{enabled:false}},'toggle'),/MercMode on/);
 await M.menuAction(api,host,'title',{title:'re5',checked:false});
 assert.deepEqual(calls.at(-1),['/api/mercmode',{host:'lilspark',titles:['re4']}]);
 await assert.rejects(M.menuAction(api,{...host,settings:{titles:['re4']}},'title',{title:'re4',checked:false}),/at least one/);
 await M.menuAction(api,host,'rounds','7');
 assert.deepEqual(calls.at(-1),['/api/mercmode',{host:'lilspark',rounds_per_title:7}]);
 await assert.rejects(M.menuAction(api,null,'toggle'),/No gBox PC/);
});
test('between titles the transition shows a loading bar that follows the scheduler phase',()=>{
 const host=s=>({settings:{enabled:true},current_run:{mercmode:{title:'re5'},title:'Resident Evil 5',started:1000,up:1100,session_id:'w1-next',...s}});
 assert.deepEqual(M.transition(host({phase:'playing',session_id:'w1-cur'}),'w1-cur',1200),{show:false});
 const launching=M.transition(host({phase:'launching'}),'w1-cur',1045);
 assert.equal(launching.show,true);assert.equal(launching.progress,34);assert.match(launching.text,/Loading Resident Evil 5/);
 assert.equal(M.transition(host({phase:'launching'}),'w1-cur',5000).progress,60);
 assert.equal(M.transition(host({phase:'starting'}),'w1-cur',1115).progress,75);
 assert.equal(M.transition(host({phase:'playing'}),'w1-cur',1200).progress,92);
 assert.deepEqual(M.transition({settings:{enabled:false},current_run:{phase:'launching',mercmode:{}}},'w1-cur',1),{show:false});
 assert.deepEqual(M.transition(null,'w1-cur',1),{show:false});
});
