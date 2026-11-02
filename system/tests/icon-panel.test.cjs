const {test}=require('node:test');
const assert=require('node:assert/strict');
const {stageWeights,createRoundControls,bindReplayGesture,bindIconPanel}=require('../clients/web/viz/stream-interventions.js');
if(!globalThis.crypto)globalThis.crypto=require('node:crypto').webcrypto;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const rows=()=>[{id:0,name:'Village',enabled:true,weight:50,default_enabled:true},{id:1,name:'Castle',enabled:true,weight:30,default_enabled:true},{id:2,name:'Island',enabled:true,weight:20,default_enabled:true}];
const report=(extra={})=>({session_id:'one',title:'RE6',available:true,current_stage:0,stages:rows(),loop:{enabled:false,stage_id:null},replay_pending:false,quick_attack:{available:true,enabled:true,count:4,interval_s:24},...extra});
const evt=(extra={})=>({button:0,detail:1,clientX:10,clientY:10,preventDefault(){},stopPropagation(){},stopImmediatePropagation(){},...extra});

test('coupled weights keep100percent, preserve proportions, and reject an empty stage pool',()=>{
  const changed=stageWeights(rows(),0,80);
  assert.deepEqual(changed.map(r=>r.weight),[80,12,8]);
  assert.deepEqual(rows().map(r=>r.weight),[50,30,20],'input rows remain immutable');
  assert.equal(stageWeights([{id:1,enabled:true,weight:0}],1,10)[0].weight,100);
  const zero=stageWeights(rows().map(r=>({...r,weight:0})));
  assert.equal(zero.reduce((n,r)=>n+Math.round(r.weight*100),0),10000);
  assert.throws(()=>stageWeights(rows().map(r=>({...r,enabled:false}))),/at least one/);
  const partial=stageWeights(rows().map(r=>({...r,enabled:r.id!==0})));
  assert.deepEqual(partial.map(r=>r.weight),[0,60,40]);
});

test('replay and persistent loop send one bounded RPC and wait for authoritative report',async()=>{
  let resolve;const calls=[];
  const control=createRoundControls({sid:'one',uuid:()=> 'unique',api:async(path,body)=>{
    calls.push([path,body]);if(body.args.op==='status')return report();return new Promise(r=>resolve=r);
  }});
  await control.refresh();const request=control.loop(true);
  assert.equal(control.snapshot().report.loop.enabled,false);assert.equal(control.snapshot().pending.state,'sending');
  await assert.rejects(control.replay(),/previous request/);
  resolve(report({loop:{enabled:true,stage_id:0},receipt:{request_id:'unique',status:'applied'}}));await request;
  assert.equal(control.snapshot().report.loop.enabled,true);assert.equal(control.snapshot().pending,null);
  assert.deepEqual(calls[1],['/api/sessions/one/rpc',{op:'merc_round_controls',args:{op:'replay',request_id:'unique',mode:'loop',enabled:true}}]);
  control.dispose();
});

test('uncertain mutation is never resent; only matching status receipt resolves it',async()=>{
  let query=0,mutations=0;
  const control=createRoundControls({sid:'one',uuid:()=> 'once',api:async(_path,body)=>{
    if(body.args.op!=='status'){mutations++;throw Error('RPC504');}
    query++;return report(query<3?{}:{replay_pending:true,receipt:{request_id:'once',status:'queued'}});
  }});
  await control.refresh();await control.replay();assert.equal(control.snapshot().pending.state,'uncertain');
  await control.refresh();assert.equal(control.snapshot().pending.state,'uncertain');
  await control.refresh();assert.equal(control.snapshot().pending,null);assert.equal(mutations,1);
  assert.match(control.snapshot().message,/queued/);control.dispose();
});

test('a value match without request receipt does not claim success',async()=>{
  const control=createRoundControls({sid:'one',uuid:()=> 'x',api:async(_p,b)=>report(b.args.op==='status'?{}:{loop:{enabled:true,stage_id:0}})});
  await control.refresh();await control.loop(true);assert.equal(control.snapshot().pending.state,'uncertain');assert.match(control.snapshot().error,/matching receipt/);control.dispose();
});

test('explicit worker rejection retains readback and permits a later distinct request',async()=>{
  let n=0;const posts=[];
  const control=createRoundControls({sid:'one',uuid:()=>String(++n),api:async(_p,b)=>{
    if(b.args.op==='status')return report();posts.push(b.args);
    return report({receipt:{request_id:b.args.request_id,status:'rejected',error:'Current stage is not observed'}});
  }});
  await control.refresh();await control.replay();assert.equal(control.snapshot().pending,null);
  assert.match(control.snapshot().error,/not observed/);assert.equal(control.snapshot().report.replay_pending,false);
  await control.replay();assert.deepEqual(posts.map(p=>p.request_id),['1','2']);control.dispose();
});

test('late pre-mutation status cannot replace the saved loop state',async()=>{
  let calls=0,oldRead;
  const control=createRoundControls({sid:'one',uuid:()=> 'x',api:async(_p,b)=>{
    if(b.args.op!=='status')return report({loop:{enabled:true,stage_id:0},receipt:{request_id:'x',status:'applied'}});
    if(++calls===1)return report();return new Promise(r=>oldRead=r);
  }});
  await control.refresh();const old=control.refresh();await control.loop(true);oldRead(report());await old;
  assert.equal(control.snapshot().report.loop.enabled,true);control.dispose();
});

test('status confirmation wins over a later mutation transport error',async()=>{
  let reject,reads=0;
  const control=createRoundControls({sid:'one',uuid:()=> 'x',api:async(_p,b)=>{
    if(b.args.op!=='status')return new Promise((_r,r)=>reject=r);
    return ++reads===1?report():report({replay_pending:true,receipt:{request_id:'x',status:'queued'}});
  }});
  await control.refresh();const mutation=control.replay();await control.refresh();reject(Error('lost reply'));await mutation;
  assert.equal(control.snapshot().pending,null);assert.equal(control.snapshot().error,'');control.dispose();
});

test('session switch rejects old status and mutation responses',async()=>{
  let sid='one',resolve;
  const control=createRoundControls({sid:()=>sid,uuid:()=> 'x',api:async(_p,b)=>b.args.op==='status'?report({session_id:sid}):new Promise(r=>resolve=r)});
  await control.refresh();const old=control.replay();sid='two';control.update();await control.refresh();
  resolve(report({replay_pending:true,receipt:{request_id:'x',status:'queued'}}));await old;
  assert.equal(control.snapshot().report.session_id,'two');assert.equal(control.snapshot().report.replay_pending,false);control.dispose();
});

test('wrong session reports and unavailable titles cannot enable mutations',async()=>{
  let mode='wrong',mutations=0;
  const control=createRoundControls({sid:'one',api:async(_p,b)=>{if(b.args.op!=='status')mutations++;return mode==='wrong'?report({session_id:'two'}):report({available:false,reason:'Unsupported title'});}});
  await control.refresh();assert.equal(control.snapshot().report,null);assert.match(control.snapshot().error,/this session/);
  mode='unavailable';await control.refresh();await assert.rejects(control.replay(),/Unsupported/);assert.equal(mutations,0);control.dispose();
});

test('malformed quick-attack data is not presented as the default4per24 setting',async()=>{
  const control=createRoundControls({sid:'one',api:async()=>report({quick_attack:{available:true,enabled:true,count:99,interval_s:24}})});
  await control.refresh();assert.equal(control.snapshot().report,null);assert.match(control.snapshot().error,/could not be verified/);control.dispose();
});

test('stage payload excludes labels and normalizes; quick attacks validate title and bounds',async()=>{
  const calls=[];let quick=true;
  const control=createRoundControls({sid:'one',uuid:()=> 'x',api:async(_p,b)=>{
    calls.push(b.args);return report({quick_attack:{available:quick,enabled:true,count:4,interval_s:24},receipt:b.args.op==='status'?undefined:{request_id:'x',status:'applied'}});
  }});
  await control.refresh();await control.stages(rows().map(r=>({...r,weight:1})));
  assert.equal(calls[1].stages.reduce((n,r)=>n+Math.round(r.weight*100),0),10000);assert.equal('name' in calls[1].stages[0],false);
  await control.quickAttack({enabled:true,count:4,interval_s:24});assert.equal(calls.at(-1).count,4);
  await assert.rejects(control.quickAttack({enabled:true,count:9,interval_s:24}),/1-8/);
  await assert.rejects(control.quickAttack({enabled:true,count:4,interval_s:7}),/8-120/);
  quick=false;await control.refresh();await assert.rejects(control.quickAttack({enabled:true,count:4,interval_s:24}),/unavailable/);control.dispose();
});

function gestureFixture(identity=()=>null){
  const handlers={},timers=new Map();let counter=0,replays=0,loops=0;
  const button={addEventListener:(n,f)=>handlers[n]=f,removeEventListener:n=>delete handlers[n]};
  const control=bindReplayGesture(button,{identity,replay:()=>replays++,loop:()=>loops++,schedule:f=>{timers.set(++counter,f);return counter;},cancel:id=>timers.delete(id)});
  return {control,handlers,timers,counts:()=>[replays,loops],fire(){const entries=[...timers.values()];timers.clear();entries.forEach(f=>f());}};
}
test('long press toggles once and consumes the subsequent click',()=>{
  const f=gestureFixture();f.handlers.pointerdown(evt());f.fire();f.handlers.pointerup(evt());f.handlers.click(evt());
  assert.deepEqual(f.counts(),[0,1]);f.handlers.pointerdown(evt());f.handlers.pointerup(evt());f.handlers.click(evt());assert.deepEqual(f.counts(),[1,1]);f.control.dispose();
});
test('Ctrl-click toggles loop and canceled or moved long presses do not fire',()=>{
  const f=gestureFixture();f.handlers.pointerdown(evt({ctrlKey:true}));assert.equal(f.timers.size,0);f.handlers.click(evt({ctrlKey:true}));
  f.handlers.pointerdown(evt());f.handlers.pointermove(evt({clientX:30}));f.fire();
  f.handlers.pointerdown(evt());f.handlers.pointercancel(evt());f.fire();
  assert.deepEqual(f.counts(),[0,1]);f.control.dispose();assert.equal(Object.keys(f.handlers).length,0);
});

test('pointer gesture belongs to the session where it began, including late timer and click',()=>{
  let identity='one:1';const f=gestureFixture(()=>identity);
  f.handlers.pointerdown(evt());identity='two:2';f.fire();f.handlers.pointerup(evt());f.handlers.click(evt());
  assert.deepEqual(f.counts(),[0,0]);
  f.handlers.pointerdown(evt({ctrlKey:true}));identity='one:3';f.handlers.click(evt({ctrlKey:true}));
  assert.deepEqual(f.counts(),[0,0]);
  f.handlers.pointerdown(evt());const late=[...f.timers.values()][0];identity='two:4';f.control.cancelPending();late();f.handlers.click(evt());
  assert.deepEqual(f.counts(),[0,0]);
  f.handlers.click(evt({detail:0}));assert.deepEqual(f.counts(),[1,0],'new keyboard action targets the current selection');f.control.dispose();
});

class Element {
  constructor(doc,tag){this.ownerDocument=doc;this.tagName=tag.toUpperCase();this.children=[];this.style={};this.dataset={};this.attributes={};this.listeners={};this.value='';this.disabled=false;this.hidden=false;this.offsetWidth=360;this.offsetHeight=300;}
  append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);}
  addEventListener(k,v){this.listeners[k]=v;}
  removeEventListener(k){delete this.listeners[k];}
  contains(n){return this===n||this.children.some(c=>c.contains?.(n));}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);}
  getBoundingClientRect(){return {left:10,right:35,top:0,bottom:25};}
  focus(){this.ownerDocument.activeElement=this;}
}
function domFixture(){
  const timers=new Map();let timer=0;const doc={listeners:{},activeElement:null,createElement(tag){return new Element(doc,tag);},createTextNode(text){const n=new Element(doc,'text');n.textContent=text;return n;},addEventListener(k,v){this.listeners[k]=v;},removeEventListener(k){delete this.listeners[k];}};
  doc.defaultView={innerWidth:480,innerHeight:360,setTimeout(fn){timers.set(++timer,fn);return timer;},clearTimeout(id){timers.delete(id);},addEventListener(){},removeEventListener(){}};doc.body=new Element(doc,'body');
  const button=new Element(doc,'button'),menuButton=new Element(doc,'button'),posts=[];let saved=report(),sid='one',mutation=null;
  const control=bindIconPanel(button,{sid:()=>sid,menuButton,api:async(_path,body)=>{const args=body.args;if(args.op==='status')return {...saved,session_id:sid};posts.push(args);
    if(mutation)return mutation(args);
    if(args.op==='stages'&&args.stages)saved={...saved,stages:args.stages.map(r=>({...rows().find(x=>x.id===r.id),...r}))};
    if(args.op==='quick_attack')saved={...saved,quick_attack:{available:true,enabled:args.enabled,count:args.count,interval_s:args.interval_s}};
    return {...saved,receipt:{request_id:args.request_id,status:'applied'}};}});
  const all=()=>{const walk=n=>[n,...n.children.flatMap(walk)];return walk(doc.body);};
  return {doc,button,menuButton,posts,control,all,setSid(value){sid=value;control.update();},setMutation(value){mutation=value;}};
}

test('PiP session change cancels an in-flight long press and its subsequent click',async()=>{
  const f=domFixture();await tick();f.button.listeners.pointerdown(evt());
  f.setSid('two');await tick();await new Promise(resolve=>setTimeout(resolve,650));
  f.button.listeners.pointerup(evt());f.button.listeners.click(evt());await tick();
  assert.deepEqual(f.posts,[]);f.control.dispose();
});
test('popup weights stay draft until Apply; no empty inversion is sent',async()=>{
  const f=domFixture();await tick();f.menuButton.listeners.click(evt());await tick();
  const slider=f.all().find(n=>n.attributes['aria-label']==='Village stage probability');slider.value='80';slider.oninput();assert.equal(f.posts.length,0);
  const apply=f.all().find(n=>n.textContent==='Apply stages');assert.equal(apply.disabled,false);await apply.onclick();
  assert.deepEqual(f.posts[0].stages.map(r=>r.weight),[80,12,8]);
  f.all().find(n=>n.textContent==='Invert').onclick();assert.equal(f.posts.length,1);assert.match(f.all().find(n=>n.attributes.role==='status').textContent,/at least one/);
  f.control.dispose();assert.equal(f.doc.body.children.length,0);
});
test('popup quick attacks send explicit4per24 defaults and status follows report',async()=>{
  const f=domFixture();await tick();f.menuButton.listeners.click(evt());await tick();
  const count=f.all().find(n=>n.attributes['aria-label']==='Quick attacks per burst'),interval=f.all().find(n=>n.attributes['aria-label']==='Quick attack interval in seconds');
  assert.equal(count.value,'4');assert.equal(interval.value,'24');f.doc.activeElement=interval;interval.value='32';interval.oninput();assert.equal(f.posts.length,0);await interval.onchange();
  assert.deepEqual(Object.fromEntries(Object.entries(f.posts[0]).filter(([k])=>k!=='request_id')),{op:'quick_attack',enabled:true,count:4,interval_s:32});
  f.setSid('two');assert.equal(f.doc.body.children.length,0);f.control.dispose();
});

test('old menu completion cannot clear the next session draft or submit removed controls',async()=>{
  const f=domFixture();await tick();f.menuButton.listeners.click(evt());await tick();
  const oldSlider=f.all().find(n=>n.attributes['aria-label']==='Village stage probability');oldSlider.value='80';oldSlider.oninput();
  let complete;f.setMutation(()=>new Promise(r=>complete=r));
  const oldApply=f.all().find(n=>n.textContent==='Apply stages'),saving=oldApply.onclick();
  f.setSid('two');await tick();f.menuButton.listeners.click(evt());await tick();
  const newSlider=f.all().find(n=>n.attributes['aria-label']==='Village stage probability');newSlider.value='70';newSlider.oninput();
  await oldApply.onclick();assert.equal(f.posts.length,1,'removed old controls cannot submit to the new session');
  complete(report({receipt:{request_id:f.posts[0].request_id,status:'applied'}}));await saving;
  assert.equal(newSlider.value,'70');assert.equal(f.all().find(n=>n.textContent==='Apply stages').disabled,false);
  f.control.dispose();
});
