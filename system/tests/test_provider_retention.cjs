const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const html=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
const providers=fs.readFileSync(path.join(__dirname,'../clients/desktop/hermes-providers.js'),'utf8');
function between(a,b){const i=html.indexOf(a),j=html.indexOf(b,i+a.length);assert.ok(i>=0&&j>i);return html.slice(i,j);}
const helper=between('const TK_OWNER','async function tasksLocalLoad()');
const render=between('function tkProvidersRender()','async function tkProvidersWindow(e)');
const fixture=`
 document.body.innerHTML='<style>#tk-visual{width:640px;height:260px;overflow:auto}.tkp-cards{display:flex;gap:8px;overflow-x:auto}.tkp-card{flex:0 0 240px}#below{height:500px}</style><div id="taskpanel" class="on"><div id="tk-visual"><div id="tkv-providers"></div><div id="below"></div></div><div id="tk-technical"><div id="tk-providers"></div></div></div>';
 const $=s=>document.querySelector(s),TK={pointerDown:0,scrolledAt:0,providersWindow:'today'};
 ${providers}
 ${helper}
 ${render}
 const rows=Array.from({length:6},(_,i)=>({provider:'provider'+i,key:'route'+i,model:'fixture',calls_ok:10}));
 TK.providers={routes:rows,pool:{nodes:rows.map((r,i)=>({name:'machine'+i,capacity:2})),model_management:{recommendation:{current:true,title:'Recommendation',model:'fixture',reason:'fixture'},access:{ready:false}}}};
 tkProvidersRender();
 const pane=$('#tk-visual'),box=$('#tkv-providers'),strips=[...box.querySelectorAll('.tkp-cards')],detail=box.querySelector('details');
 strips[0].scrollLeft=310;strips[1].scrollLeft=590;detail.open=true;pane.scrollTop=80;
 const before={left:strips.map(x=>x.scrollLeft),top:pane.scrollTop};
`;
test('actual provider refresh preserves both card strips, pane, and expanded or collapsed details',async()=>{
 await withPage(async evaluate=>{
  const result=await evaluate(`(()=>{${fixture}
   TK.providers.routes[0].calls_ok++;tkProvidersRender();
   const first={left:[...box.querySelectorAll('.tkp-cards')].map(x=>x.scrollLeft),top:pane.scrollTop,open:box.querySelector('details').open};
   box.querySelector('details').open=false;TK.providers.pool.model_management.recommendation.current=false;
   TK.providers.routes[0].calls_ok++;tkProvidersRender();
   return{before,first,closed:!box.querySelector('details').open,updated:box.textContent.includes('12')};
  })()`);
  console.log('provider-refresh',JSON.stringify(result));
  assert.deepEqual(result.first.left,result.before.left);assert.equal(result.first.top,result.before.top);
  assert.equal(result.first.open,true);assert.equal(result.closed,true);assert.equal(result.updated,true);
 });
});
test('actual provider refresh defers while a pointer or text selection is active',async()=>{
 await withPage(async evaluate=>{
  const result=await evaluate(`(()=>{${fixture}
   const original=box.querySelector('.tkp-card');TK.pointerDown=Date.now();TK.providers.routes[0].calls_ok++;tkProvidersRender();
   const pointer=original.isConnected;TK.pointerDown=0;
   const range=document.createRange();range.selectNodeContents(original);getSelection().removeAllRanges();getSelection().addRange(range);
   const selected=getSelection().toString();tkProvidersRender();
   const selection=original.isConnected&&getSelection().toString()===selected;
   getSelection().removeAllRanges();tkProvidersRender();
   return{pointer,selection,updated:!original.isConnected,left:[...box.querySelectorAll('.tkp-cards')].map(x=>x.scrollLeft),before:before.left};
  })()`);
  assert.equal(result.pointer,true);assert.equal(result.selection,true);assert.equal(result.updated,true);assert.deepEqual(result.left,result.before);
 });
});


test('popup child controls stay open while a genuine native gameclick still dismisses it',async()=>{
 const pops=between('const POPS =','async function gameplayRecordingRect()');
 const native=between('gbox.onEmbedEvent?.(', 'gbox.onHotkey?.(');
 await withPage(async evaluate=>{
  const result=await evaluate(`(async()=>{
   document.body.innerHTML='<div id="taskpanel" class="on"><select id="filter"><option>All tasks</option></select><details><summary id="summary">Task details</summary><p>Details</p></details></div><div id="pipmenu"></div><button id="outside">Outside</button>';
   const $=s=>document.querySelector(s),TK={t:null,deviceView:{setActive:()=>{}},graph:null},GM={},EMB={};
   let bridge;const gbox={onEmbedEvent:fn=>{bridge=fn;}};
   ${pops}
   ${native}
   $('#filter').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));const filterOpen=$('#taskpanel').classList.contains('on');
   $('#summary').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));$('#summary').click();
   const detailOpen=$('#taskpanel').classList.contains('on')&&$('details').open;
   await bridge({event:'gameclick'});const gameClosed=!$('#taskpanel').classList.contains('on');
   $('#taskpanel').classList.add('on');$('#outside').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
   return{filterOpen,detailOpen,gameClosed,outsideClosed:!$('#taskpanel').classList.contains('on')};
  })()`);
  assert.deepEqual(result,{filterOpen:true,detailOpen:true,gameClosed:true,outsideClosed:true});
 });
});


test('a long-lived selection remains intact and refresh resumes outside the pane or after dismissal',async()=>{
 await withPage(async evaluate=>{
  const result=await evaluate(`(()=>{${fixture}
   const original=box.querySelector('.tkp-card'),range=document.createRange();range.selectNodeContents(original);
   getSelection().removeAllRanges();getSelection().addRange(range);
   const now=Date.now,base=now();Date.now=()=>base;
   TK.providers.routes[0].calls_ok++;tkProvidersRender();Date.now=()=>base+31001;tkProvidersRender();
   const retained=original.isConnected&&getSelection().toString().length>0;
   const outside=document.createElement('p');outside.textContent='Outside the task pane';document.body.append(outside);
   range.selectNodeContents(outside);getSelection().removeAllRanges();getSelection().addRange(range);tkProvidersRender();
   const outsideUpdated=!original.isConnected;
   const current=box.querySelector('.tkp-card');range.selectNodeContents(current);getSelection().removeAllRanges();getSelection().addRange(range);
   $('#taskpanel').classList.remove('on');TK.pointerDown=Date.now();TK.providers.routes[0].calls_ok++;tkProvidersRender();
   const inactiveUpdated=!current.isConnected;Date.now=now;
   return{retained,outsideUpdated,inactiveUpdated};
  })()`);
  assert.deepEqual(result,{retained:true,outsideUpdated:true,inactiveUpdated:true});
 });
});
