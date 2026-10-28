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
 const calls=[],listeners=new Map(),fields={'[data-rounds]':{value:'1'},'[data-stalemate]':{checked:false},'[data-stalemate-s]':{value:'12'},'[data-coop]':{value:'off'}};
 const host={dataset:{host:'lilspark'},
  querySelectorAll:()=>[{dataset:{title:'re4'}},{dataset:{title:'re5'}}],
  querySelector:key=>fields[key]||{checked:true}};
 const button={closest:()=>host,hasAttribute:key=>key==='data-save'};
 const root={innerHTML:'',addEventListener:(n,fn)=>listeners.set(n,fn),removeEventListener:n=>listeners.delete(n)};
 const panel=M.mount({root,api:async(path,body)=>{calls.push([path,body]);return {hosts:[]};}});
 await panel.ready;await listeners.get('click')({target:{closest:()=>button}});
 assert.deepEqual(calls[1],['/api/mercmode',{host:'lilspark',enabled:true,presentation_priority:true,titles:['re4','re5'],rounds_per_title:1,
  stalemate_cut:false,stalemate_cut_s:12,coop_ratio:'off'}]);
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
 assert.deepEqual(M.transition(host({phase:'playing'}),'w1-cur',1200),{show:false,follow:'w1-next'});   // live: go to it, no loading screen
 assert.deepEqual(M.transition({settings:{enabled:false},current_run:{phase:'launching',mercmode:{}}},'w1-cur',1),{show:false});
 assert.deepEqual(M.transition(null,'w1-cur',1),{show:false});
 // a warm switch has a live game from its first moment: no loading screen, whatever its phase (2026-10-26: "I hate waiting")
 for(const phase of ['starting','playing'])assert.equal(M.transition(host({phase,warm_from:'ready'}),'w1-cur',1200).show,false);
 assert.equal(M.transition(host({phase:'launching',warm_from:'prelaunch',session_id:undefined}),'w1-cur',1045).show,true);
});
test('a viewer left on a dead or paused MercMode session follows the live run; another game there moves only once it ended',()=>{
 // operator 2026-10-26: "so why is still here? i just want mercenaries perpetual" - after a service restart the PiP kept the
 // dead session (an earlier worker id) and showed "Loading Resident Evil 5..." for 13 minutes while RE5 played
 const host=(run,warm=[])=>({id:'w2',name:'lilspark',settings:{enabled:true},warm,
   current_run:{mercmode:{title:'re5'},title:'Resident Evil 5',started:1000,session_id:'w2-live',...run}});
 assert.deepEqual(M.transition(host({phase:'playing'}),'w1-dead',1200),{show:false,follow:'w2-live'});        // before the restart
 assert.deepEqual(M.transition(host({phase:'playing'},[{session_id:'w2-warm'}]),'w2-warm',1200),{show:false,follow:'w2-live'});
 assert.deepEqual(M.transition(host({phase:'playing',mercmode_predecessor:{session_id:'w2-prev'}}),'w2-prev',1200),{show:false,follow:'w2-live'});
 assert.deepEqual(M.transition(host({phase:'playing'}),'w2-mine',1200),{show:false,follow:'w2-live',only_if_ended:true});   // maybe the operator's own game: moved only once it ended
 assert.equal(M.transition(host({phase:'launching',session_id:null}),'w1-dead',1045).show,true);     // a cold start: the bar
 assert.deepEqual(M.transition(host({phase:'playing'}),'w2-live',1200),{show:false});
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
test('bot+bot split-screen turns: a co-op : solo ratio, off by default, set from the panel and the PiP menu',async()=>{
 const host={name:'lilspark',id:'w1',online:true,settings:{enabled:true,titles:['re5','re6']},titles:[]};
 const html=M.render({hosts:[host]});
 assert.match(html,/<select data-coop aria-label="Bot\+bot split-screen turns"><option value="off" selected>Off \(solo turns only\)<\/option>/);
 assert.match(html,/RE5 plays Mercenaries United in split screen \(its No Mercy is single-player only\)/);
 assert.match(M.render({hosts:[{...host,settings:{...host.settings,coop_ratio:'6:1'}}]}),/<option value="6:1" selected>6:1 co-op to solo<\/option>/);
 assert.match(M.menuHTML(host,true),/<select data-mm-coop/);
 assert.doesNotMatch(M.menuHTML(host,true),/data-mm-play-bot/);                      // no Switch session: no button
 assert.match(M.menuHTML(host,true,null,{session_id:'w1-a',game_id:'115f9cdbba115432'}),/data-mm-play-bot[^>]*>🎮 Play with bot \(RE6 split screen\)/);
 const calls=[],api=async(path,body)=>{calls.push([path,body]);return {};};
 assert.match(await M.menuAction(api,host,'coop','6:1'),/6:1 co-op to solo/);
 assert.match(await M.menuAction(api,host,'coop','off'),/play solo/);
 await assert.rejects(M.menuAction(api,host,'coop',true),/co-op ratio/);
 assert.deepEqual(calls,[['/api/mercmode',{host:'lilspark',coop_ratio:'6:1'}],['/api/mercmode',{host:'lilspark',coop_ratio:'off'}]]);
});
test('play with bot: the team role, Player 2 by an in-place restart, then the autobot, each confirmed in turn',async()=>{
 const calls=[],api=async(path,body)=>{calls.push([path,body]);
  return path==='/api/jobs'?{id:'j'+calls.length,state:'succeeded',output:{result:{}}}:{};};
 const out=await M.menuAction(api,{name:'lilspark'},'play_with_bot',{session_id:'w1-sw',game_id:'52d15709be0fda1a'});
 assert.match(out,/the bot joins as Player 2/);
 assert.deepEqual(calls.map(c=>[c[1].tool,c[1].input]),[
  ['mercs_team',{session_id:'w1-sw',op:'configure',role:'teammate_p2'}],
  ['mercs_team',{session_id:'w1-sw',op:'prepare_player2',restart:true}],
  ['autoplay',{session_id:'w1-sw',op:'start',mode:'auto',continuous:true}]]);
 assert.ok(calls.every(c=>c[1].require_worker==='w1'&&c[1].agent_use===false));
 await assert.rejects(M.menuAction(api,{name:'lilspark'},'play_with_bot',{session_id:'w1-x',game_id:'e7ca89bbeb67360d'}),/RE5 or RE6 Switch/);
 const failing=async(path,body)=>path==='/api/jobs'?{id:'x',state:'failed',error:'no pad'}:{};
 await assert.rejects(M.menuAction(failing,{name:'lilspark'},'play_with_bot',{session_id:'w1-sw',game_id:'52d15709be0fda1a'}),/mercs_team: no pad/);
});
