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
 const calls=[],listeners=new Map(),fields={'[data-rounds]':{value:'1'},'[data-stalemate]':{checked:false},'[data-stalemate-s]':{value:'12'}};
 const host={dataset:{host:'lilspark'},
  querySelectorAll:()=>[{dataset:{title:'re4'}},{dataset:{title:'re5'}}],
  querySelector:key=>fields[key]||{checked:true}};
 const button={closest:()=>host,hasAttribute:key=>key==='data-save'};
 const root={innerHTML:'',addEventListener:(n,fn)=>listeners.set(n,fn),removeEventListener:n=>listeners.delete(n)};
 const panel=M.mount({root,api:async(path,body)=>{calls.push([path,body]);return {hosts:[]};}});
 await panel.ready;await listeners.get('click')({target:{closest:()=>button}});
 assert.deepEqual(calls[1],['/api/mercmode',{host:'lilspark',enabled:true,presentation_priority:true,titles:['re4','re5'],rounds_per_title:1,
  stalemate_cut:false,stalemate_cut_s:12}]);
 panel.dispose();
});
test('the stalemate rule is a host setting: on by default at 5 s, saved from the panel and the PiP menu, bounded 1..60',async()=>{
 const full=M.render({hosts:[{name:'lilspark',id:'w1',online:true,settings:{enabled:true,titles:['re5'],rounds_per_title:1},titles:[]}]});
 assert.match(full,/data-stalemate checked/);assert.match(full,/data-stalemate-s min="1" max="60" value="5"/);
 const off=M.render({hosts:[{name:'lilspark',id:'w1',online:true,settings:{enabled:true,titles:['re5'],stalemate_cut:false,stalemate_cut_s:20},titles:[]}]});
 assert.match(off,/data-stalemate > Stalemate/);assert.doesNotMatch(off,/data-stalemate checked/);assert.match(off,/data-stalemate-s[^>]*value="20"/);
 const host={name:'lilspark',settings:{enabled:true,titles:['re4','re5'],stalemate_cut:true,stalemate_cut_s:5},titles:[]};
 assert.match(M.menuHTML(host,true),/data-mm-stalemate checked/);assert.match(M.menuHTML(host,true),/data-mm-stalemate-s min="1" max="60" value="5"/);
 assert.doesNotMatch(M.menuHTML({...host,settings:{...host.settings,stalemate_cut:false}},true),/data-mm-stalemate checked/);
 assert.equal(M.stalemateSeconds({stalemate_cut_s:'61'}),5);assert.equal(M.stalemateSeconds({stalemate_cut_s:'30'}),30);assert.equal(M.stalemateSeconds({}),5);
 const calls=[],api=async(path,body)=>{calls.push([path,body]);return {};};
 assert.match(await M.menuAction(api,host,'stalemate',{enabled:true,seconds:'8'}),/cuts the clock to 8 s/);
 assert.deepEqual(calls.at(-1),['/api/mercmode',{host:'lilspark',stalemate_cut:true,stalemate_cut_s:8}]);
 assert.match(await M.menuAction(api,host,'stalemate',{enabled:false}),/leaves the clock alone/);
 assert.deepEqual(calls.at(-1),['/api/mercmode',{host:'lilspark',stalemate_cut:false,stalemate_cut_s:5}]);
 await M.menuAction(api,host,'stalemate',{seconds:'999'});
 assert.deepEqual(calls.at(-1),['/api/mercmode',{host:'lilspark',stalemate_cut:true,stalemate_cut_s:5}],'an out-of-range number falls back to the default');
 const shell=require('node:fs').readFileSync(require('node:path').join(__dirname,'../clients/desktop/index.html'),'utf8');
 assert.match(shell,/\[data-mm-stalemate\]'\)\?\.addEventListener\('change', stalemate\)/);
 assert.match(shell,/act\('stalemate', \{ enabled: slot\.querySelector\('\[data-mm-stalemate\]'\)\?\.checked,/);
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
test('the DJ queue shows now playing, the queue ahead and a form built from each title roster',()=>{
 const catalog={re4:{modes:{mercenaries:['Leon','Ada']},stages:['Village','Castle']},re5:{modes:{mercenaries:['Chris (BSAA)'],reunion:['Barry']},stages:['Public Assembly','The Mines']}};
 const host={name:'lilspark',settings:{enabled:true,queue:[{title:'re5',mode:'reunion',character:'Barry',stage:1},{title:'re4',mode:null,character:null,stage:null}]},
  current_run:{title:'Resident Evil 4',mercmode:{title:'re4'}},now_playing:{character:'Ada',stage:'Castle'},
  titles:[{title:'re4',name:'Resident Evil 4',playable:true},{title:'re5',name:'Resident Evil 5',playable:true},{title:'re6',name:'Resident Evil 6',playable:false}]};
 const html=M.queueHTML(host,catalog);
 assert.match(html,/Now playing<\/b> <small>Resident Evil 4 · Ada · Castle/);
 assert.match(html,/Resident Evil 5 · reunion · Barry · The Mines/);assert.match(html,/Resident Evil 4 · random character · random stage/);
 assert.match(html,/data-mm-unqueue="1"/);assert.doesNotMatch(html,/value="re6"/);
 const opts=M.formOptions(catalog,'re5','reunion');assert.match(opts.characters,/Barry/);assert.doesNotMatch(opts.characters,/Chris/);
 assert.match(M.formOptions(catalog,'re5','').characters,/Chris \(BSAA\).*Barry/s);assert.match(opts.stages,/value="1">The Mines/);
 assert.match(M.queueHTML({settings:{queue:[]},titles:[]},catalog),/Random rotation/);
});
test('queue actions post the whole queue for the exact host',async()=>{
 const calls=[],api=async(path,body)=>{calls.push(body);return {};};
 const host={name:'lilspark',settings:{enabled:true,queue:[{title:'re4',character:'Ada'}]}};
 assert.match(await M.queueAction(api,host,'next',{title:'re5',mode:'reunion',character:'Barry',stage:0}),/Up next/);
 assert.deepEqual(calls[0],{host:'lilspark',queue:[{title:'re5',mode:'reunion',character:'Barry',stage:0},{title:'re4',character:'Ada'}]});
 await M.queueAction(api,host,'add',{title:'re4'});assert.equal(calls[1].queue.length,2);assert.equal(calls[1].queue[1].title,'re4');
 await M.queueAction(api,host,'remove','0');assert.deepEqual(calls[2].queue,[]);
 assert.match(await M.queueAction(api,host,'clear'),/random rotation/);
 assert.match(await M.queueAction(api,{name:'x',settings:{enabled:false}},'add',{title:'re4'}),/turn MercMode on/);
 await assert.rejects(M.queueAction(api,null,'add',{}),/No gBox PC/);
});
