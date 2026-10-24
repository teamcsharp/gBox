const test=require('node:test'),assert=require('node:assert/strict');
const T=require('../clients/web/viz/mercmode-transition.js'),M=require('../clients/web/viz/mercmode.js');
test('the overlay polls MercMode and renders show/progress without any job or launch',async()=>{
 const calls=[],rendered=[];
 const data={hosts:[{name:'lilspark',id:'w1',settings:{enabled:true},current_run:{phase:'launching',title:'Resident Evil 4',started:900,mercmode:{title:'re4'}}}]};
 const ctl=T.create({mercmode:M,api:async(path,body,method)=>{calls.push([path,body,method]);return data;},current:()=>'w1-old',render:s=>rendered.push(s),now:()=>945});
 await ctl.poll();
 assert.deepEqual(calls,[['/api/mercmode',undefined,'GET']]);
 assert.equal(rendered[0].show,true);assert.equal(rendered[0].progress,34);assert.match(rendered[0].text,/Resident Evil 4/);
 data.hosts[0].current_run={phase:'playing',session_id:'w1-old',mercmode:{title:'re4'}};
 await ctl.poll();assert.equal(rendered[1].show,false);
 ctl.stop();await ctl.poll();assert.equal(rendered.length,2);
});
test('a failed status read hides the overlay instead of throwing',async()=>{
 const rendered=[];const ctl=T.create({mercmode:M,api:async()=>{throw Error('offline');},current:()=>'w1-old',render:s=>rendered.push(s)});
 await ctl.poll();assert.equal(rendered[0].show,false);
});
