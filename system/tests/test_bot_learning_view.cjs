// Bot learning view (clients/web/viz/bot-learning.js): GET /api/mercs/learning rendered per title - causes with their
// rate per round, trend per turn, batch and the measured effect of the last change; round faults; learned tuning; changes.
const test=require('node:test'),assert=require('node:assert/strict');
const V=require('../clients/web/viz/bot-learning.js');

const DATA={generated_at:1793160000,effect_rounds:10,target_drop:0.2,last_pass:{at:1793159990},
 what_kills_him:['RE5 Switch: swarmed (4+ within 2 m) with the gun lowered - 20 deaths, 366 episodes, 61000 HP (#5101)'],
 titles:{'010018100CD46000':{game:'RE5 Switch',rounds_24h:214,deaths_per_round:0.285,stages:{unknown:214},
  changes:[{id:'c1',kind:'reload',at:1793150000,modules:['gbox.mercs.titles.re5_switch'],
            effects:{crowd_gun_down:{before:1.7,after:1.1,verdict:'improved',rounds_before:30,rounds_after:12}}},
           {id:'c2',kind:'tuning',at:1793155000,param:'re5_switch.RELOC_CROWD_N',old:null,new:5,status:'trial',effects:{}}],
  tuner:{overrides:{'*':{'re5_switch.RELOC_CROWD_N':5}},avoid:{'The Mines':[[100,200,250]]},
         trials:{'*':{param:'re5_switch.RELOC_CROWD_N',old:null,new:5,at:1793155000,baseline:3.6}},
         log:[{at:1793155000,status:'trial',param:'re5_switch.RELOC_CROWD_N',old:null,new:5,reason:'crowd: metric 3.6 <per round>'}]}}},
 clusters:[{id:'a1',title:'010018100CD46000',signature:'crowd_gun_down',label:'swarmed (4+ within 2 m) with the gun lowered',
   suspect:'the gun comes down <while> four or more stand within 2 m',deaths:20,rate_per_round:1.696,deaths_per_round:0.093,
   trend:'rising',round_turns:[{rate:1.2},{rate:1.9},{rate:2.4}],request_id:'r1',number:5101,status:'open',last_verdict:null}],
 round_faults:[{id:'f1',title:'010018100CD46000',signature:'round:bonus_missed',label:'time bonus seen, not taken',marked_rounds:33,
   rounds:214,share_of_rounds:0.154,rate_per_round:1.229,trend:'flat',turns:[{rate:1},{rate:1.5}],request_id:null}]};

test('each title shows its causes with rate per round, batch, trend and the measured effect of the last change',()=>{
 const html=V.render(DATA);
 assert.match(html,/RE5 Switch/);assert.match(html,/214 rounds in 24 h/);assert.match(html,/0\.285 deaths per round/);
 assert.match(html,/swarmed \(4\+ within 2 m\) with the gun lowered/);assert.match(html,/1\.7→1\.1 \/round \(better\)/);
 assert.match(html,/#5101 open/);assert.match(html,/<svg class="bl-bars"/);assert.match(html,/What kills him/);
 assert.match(html,/time bonus seen, not taken/);assert.match(html,/33\/214 \(15%\)/);assert.match(html,/below batch size/);
 assert.match(html,/every stage<\/b>: RELOC_CROWD_N=5/);assert.match(html,/1 learned dead-end spot/);assert.match(html,/On trial/);
 assert.match(html,/reload re5_switch/);assert.match(html,/1 cause\(s\) better, 0 worse/);
});

test('everything from the server is escaped',()=>{
 const html=V.render(DATA);
 assert.match(html,/&lt;while&gt;/);assert.match(html,/&lt;per round&gt;/);assert.doesNotMatch(html,/<while>|<per round>|onerror|onclick/);
});

test('an empty loop says what will fill it',()=>{
 assert.match(V.render({titles:{}}),/learning pass runs on the Spark once a minute/);
});

test('the panel only reads /api/mercs/learning, the game filter narrows it, dispose removes its listeners',async()=>{
 const calls=[],listeners=new Map();
 const root={innerHTML:'',addEventListener:(n,f)=>listeners.set(n,f),removeEventListener:n=>listeners.delete(n)};
 const panel=V.mount({root,api:async(path,body)=>{calls.push([path,body]);return DATA;},refreshMs:0});
 await panel.ready;
 assert.deepEqual(calls,[['/api/mercs/learning',undefined]]);assert.match(root.innerHTML,/RE5 Switch/);
 await listeners.get('change')({target:{matches:s=>s==='[data-bl-game]',value:'re6'}});
 await listeners.get('click')({target:{closest:s=>s==='[data-bl-refresh]'?{}:null}});
 assert.deepEqual(calls.map(c=>c[0]),['/api/mercs/learning','/api/mercs/learning?game=re6','/api/mercs/learning?game=re6']);
 assert.ok(calls.every(c=>c[1]===undefined));
 panel.dispose();assert.equal(listeners.size,0);
});

test('an unreachable server is said, not thrown',async()=>{
 const root={innerHTML:'',addEventListener(){},removeEventListener(){}};
 const panel=V.mount({root,api:async()=>{throw new Error('Spark <down>');},refreshMs:0});
 await panel.ready;assert.match(root.innerHTML,/Bot learning unavailable: Spark &lt;down&gt;/);panel.dispose();
});
