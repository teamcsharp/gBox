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
test('a paired PC distinguishes its observed settings from pending central requests',()=>{
 const html=M.render({hosts:[{name:'paired',id:'w1',online:true,scheduler_owner:'local',
   settings:{enabled:false,titles:['re5']},desired_settings:{enabled:true},command:{job:'j',state:'queued'},titles:[]}]});
 assert.match(html,/including while disconnected/);assert.match(html,/Requested setting: on/);
 assert.match(html,/queued/);assert.doesNotMatch(html,/data-enabled checked/);
});
