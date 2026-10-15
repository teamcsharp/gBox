const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const M=require('../clients/desktop/gameplay-memory.js'),{withPage}=require('../scripts/browser_lifecycle.cjs');
const fixture={events:2,file:'/spark/gameplay-memory.sqlite3',vector_kind:'Feature hashing; not neural embeddings',
 demonstrations:{reason:'Waiting for a validated native run'},runs:[{id:'pc-human',title:'PSO <test>',updated:1792025400,mod:'sonic',replay_status:'observations only; not a TAS'}]};
test('memory shows actual capture status and escapes run metadata',()=>{
 const h=M.html(fixture);assert.match(h,/not a TAS/);assert.match(h,/PSO &lt;test&gt;/);assert.doesNotMatch(h,/<test>/);
 assert.match(M.html({...fixture,runs:[]}),/No gameplay has been captured/);
});
test('browser: search, timeline and notes use evidence APIs and never launch a game',async()=>{
 await withPage(async(evaluate,send)=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/desktop/gameplay-memory.js'),'utf8'));
  await evaluate(`document.body.style='background:#16161c;color:#e4e4ed;font:14px system-ui;padding:20px;max-width:680px';document.head.insertAdjacentHTML('beforeend','<style>button,input{background:#22232c;color:#eee;border:1px solid #444552;border-radius:5px;padding:8px;margin:3px}input{min-width:250px}p{line-height:1.5}summary{padding:6px}.mut{color:#a8afc4}</style>');document.body.innerHTML='<div id="memory"></div>';var calls=[];var fixture=${JSON.stringify(fixture)};
   var ctl=GBoxGameplayMemory.mount(document.querySelector('#memory'),{api:async(p,b)=>{calls.push({p,b});
   if(p.endsWith('/note'))return {saved:true};if(p.includes('/runs/'))return {events:[{id:1,at:1792025401,kind:'mod_action',payload:{weapon:'saber',evidence:'Tool receipt; effect not independently verified'}}]};return fixture;}});ctl.load();`);
  await evaluate(`document.querySelector('[data-run]').click();new Promise(r=>setTimeout(r,20));`);
  assert.match(await evaluate(`document.querySelector('[data-events]').textContent`),/saber/);
  await evaluate(`document.querySelector('[data-note] input').value='Forest 1 completed';document.querySelector('[data-note]').requestSubmit();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`calls.find(c=>c.p.endsWith('/note')).b.text`),'Forest 1 completed');
  await evaluate(`document.querySelector('[data-memory-search] input').value='saber';document.querySelector('[data-memory-search]').requestSubmit();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/gameplay-memory?q=saber')`),true);
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs'||c.p.includes('launch'))`),false);
  if(process.env.GBOX_MEMORY_EVIDENCE){
   await evaluate(`document.querySelector('[data-run]').click();new Promise(r=>setTimeout(r,20));`);
   await evaluate(`document.querySelector('[data-events] details').open=true;`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_MEMORY_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_MEMORY_EVIDENCE,'gameplay-memory.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate('ctl.stop()');
 });
});
test('browser: observed demo play/loop and idle preference use isolated replay routes',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/desktop/gameplay-memory.js'),'utf8'));
  await evaluate(`document.body.innerHTML='<div id="memory"></div>';var calls=[];var fixture=${JSON.stringify(fixture)};fixture.runs[0].observed_demo={ready:true};
   var ctl=GBoxGameplayMemory.mount(document.querySelector('#memory'),{api:async(p,b)=>{calls.push({p,b});return b?{id:'demo-job'}:fixture;}});ctl.load();`);
  await evaluate(`document.querySelector('[data-demo]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`calls.find(c=>c.p.endsWith('/demo/play')).b.loop`),false);
  await evaluate(`document.querySelector('[data-demo-loop]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/demo/play'))[1].b.loop`),true);
  await evaluate(`document.querySelector('[data-demo-idle]').click();new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`calls.find(c=>c.p.endsWith('/demo/idle')).b.enabled`),true);
  assert.match(await evaluate(`document.querySelector('[data-demo-status]').textContent`),/separate available PCs/);
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs'||c.p.includes('session_op'))`),false);
  await evaluate('ctl.stop()');
 });
});
