const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../clients/web/viz/mercmode.js');
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
