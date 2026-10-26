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
test('the overlay hands a live run on another session to follow(), one at a time, retried each poll',async()=>{
 const followed=[],rendered=[];let release;
 const data={hosts:[{name:'lilspark',id:'w2',settings:{enabled:true},warm:[],current_run:{phase:'playing',session_id:'w2-live',title:'Resident Evil 5',mercmode:{title:'re5'}}}]};
 const ctl=T.create({mercmode:M,api:async()=>data,current:()=>'w1-dead',worker:()=>'lilspark',render:s=>rendered.push(s),
   follow:sid=>{followed.push(sid);return new Promise(r=>{release=r;});},now:()=>1200});
 await ctl.poll();await ctl.poll();                   // the first follow still running: no second one
 assert.deepEqual(followed,['w2-live']);assert.equal(rendered.at(-1).show,false);
 release();await new Promise(r=>setTimeout(r,0));
 await ctl.poll();assert.deepEqual(followed,['w2-live','w2-live']);   // not there yet (a black first frame): tried again
});
test('a hung status read and an overlay up too long never leave the PiP on a frozen loading screen',async()=>{
 // operator 2026-10-26: "mercmode is just sitting here frozen" - the PiP on "Loading Resident Evil 5..." while RE5 played
 const rendered=[];let t=1000;
 const data={hosts:[{name:'lilspark',id:'w1',settings:{enabled:true},current_run:{phase:'launching',title:'Resident Evil 5',started:990,mercmode:{title:'re5'}}}]};
 const hang=T.create({mercmode:M,api:()=>new Promise(()=>{}),current:()=>'w1-old',render:s=>rendered.push(s),
   timeout:()=>Promise.reject(Error('timed out')),now:()=>t});
 await hang.poll();assert.equal(rendered.at(-1).show,false);            // the read never answered: hidden, not frozen
 const ctl=T.create({mercmode:M,api:async()=>data,current:()=>'w1-old',render:s=>rendered.push(s),now:()=>t});
 await ctl.poll();assert.equal(rendered.at(-1).show,true);
 t+=241;await ctl.poll();assert.equal(rendered.at(-1).show,false);      // four minutes "launching": not a boot any more
});
