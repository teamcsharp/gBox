'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const P=require('../clients/desktop/device-outcomes.js');
const {withPage,findChrome}=require('../scripts/browser_lifecycle.cjs');
const read=n=>fs.readFileSync(path.join(__dirname,'../clients/desktop/'+n),'utf8');
const source=read('device-outcomes.js')+'\n'+read('device-work.js');
const desktop=read('index.html');
const styles=[...desktop.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m=>m[1]).join('\n')+'\n'+read('device-work.css');
function fixture(){
  return {generated_at:2000,window:{key:'today',label:'Today',start:0,end:2000},coverage:{partial:true,notes:['Synthetic test fixture.']},
    devices:[{id:'sparkDeux',name:'Spark2',provider:'gbox-sparkDeux',metrics:{active_runs:2}},{id:'provider:nous',name:'nous',metrics:{active_runs:0}},{id:'unknown',metrics:{}}],
    runs:Array.from({length:55},(_,i)=>({id:'r'+i,device_id:'sparkDeux',title:'Task '+i,state:i<2?'running':'completed',started:100+i,finished:i<2?null:200+i,current_action:'Handling step '+i,tickets:[],outcomes:[]})).concat([
      {id:'nous',device_id:'provider:nous',title:'Nous contribution',state:'completed',started:500,finished:510,tickets:[],outcomes:[{kind:'pr_published',status:'open',verified:true,url:'https://github.com/teamcsharp/gBox/pull/3',title:'PR #3'}]},
      {id:'unknown',device_id:'unknown',title:'Unattributed completion',state:'completed',finished:1000,outcomes:[{kind:'request_resolved',verified:true}]}]),
    contributions:[{id:'reviewed',device_id:'sparkDeux',run_id:null,published_at:800,request_id:'request42',ticket:{id:'request42',number:2394,title:'Expanded graph'},attribution:{scope:'Observed inference contribution; independent review is separate.'},outcomes:[{kind:'pr_reviewed_merge',verified:true,status:'merged_after_review',observed_at:900,url:'https://github.com/teamcsharp/gBox/pull/42',title:'PR #42'},{kind:'request_status',status:'open',verified:false,observed_at:2000}]}]};
}
test('retained records use exact device evidence and deduplicate linked history',()=>{
  const d=fixture();d.runs.push({...d.runs[0]});d.contributions.push({...d.contributions[0]},{...d.contributions[0],id:'linked',run_id:'r0'});
  const r=P.records(d,'sparkDeux');assert.equal(r.length,56);assert.equal(r.filter(x=>x.kind==='contribution').length,1);
  assert.equal(P.records(d,'provider:nous').length,1);assert.equal(P.records(d,'new-provider').length,0);
  assert.equal(P.records(d,'unknown')[0].category,'resolved');assert.equal(r.some(x=>x.category==='resolved'),false);
  assert.equal(r.find(x=>x.id==='reviewed').at,900,'observing current request status is not a new delivery event');
});
test('run endings, unverified completion, publication, merge and request acceptance remain distinct',()=>{
  const classify=(state,outcomes)=>P.category({state,outcomes});
  assert.equal(classify('completed',[]),'ended');assert.equal(classify('failed',[]),'failed');
  assert.equal(classify('running',[]),'active');
  assert.equal(classify('completed',[{kind:'request_resolved',verified:false}]),'reported');
  assert.equal(classify('completed',[{kind:'request_resolved',verified:'true'}]),'reported');
  assert.equal(classify('completed',[{kind:'pr_published',verified:true}]),'published');
  assert.equal(classify('completed',[{kind:'pr_reviewed_merge',verified:true}]),'merged');
  assert.equal(classify('completed',[{kind:'pr_merged',verified:true},{kind:'request_resolved',verified:true}]),'resolved');
  const rows=P.records(fixture(),'sparkDeux'),dist=P.distribution(rows);assert.equal(dist.reduce((n,v)=>n+v.count,0),rows.length);
  assert.match(P.pie(rows),/PR merged 1/);assert.doesNotMatch(P.pie([]),/NaN|Infinity/);
});
test('ordering is stable, missing timestamps remain unknown, and evidence strings are escaped',()=>{
  const rows=[{key:'z',at:null},{key:'b',at:12},{key:'a',at:12},{key:'c',at:3}];
  assert.deepEqual(P.ordered(rows).map(r=>r.key),['a','b','c','z']);assert.deepEqual(P.ordered(rows,'oldest').map(r=>r.key),['c','a','b','z']);
  assert.equal(P.records({runs:[{id:'x',device_id:'d',started:null,finished:'100'}]},'d')[0].at,null);
  assert.equal(P.link('javascript:alert(1)'),'');assert.equal(P.link('file:///secret'),'');
  assert.equal(P.linkLabel('https://evilgithub.com/a/b/pull/42'),'Open recorded evidence');
  assert.equal(P.linkLabel('https://github.com/a/b/pull/42'),'GitHub PR #42');
  const r=P.records({runs:[{id:'bad',title:'<img src=x onerror=attack()>',device_id:'d'}]},'d');
  assert.doesNotMatch(P.bubble(r,'<script>'),/<img|<script>/);assert.match(P.bubble(r,'Test'),/&lt;img/);
});
async function setup(evaluate,send){
  await send('Emulation.setDeviceMetricsOverride',{width:1500,height:950,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.head.innerHTML='<style>body{margin:0;background:#090d15;font-family:Segoe UI,Arial,sans-serif}</style>';document.body.innerHTML='<div id="taskpanel" class="device-mode on"><div class="th" style="padding:12px">Tasks — synthetic test fixture</div><div id="tk-devices"></div></div>';const st=document.createElement('style');st.textContent=${JSON.stringify(styles)};document.head.append(st);${source}`);
  await evaluate(`window.snapshot=${JSON.stringify(fixture())};window.calls=[];window.opened=[];window.view=GBoxDeviceWork.mount(document.querySelector('#tk-devices'),{api:async p=>{calls.push(p);return {ok:true,data:structuredClone(snapshot)}},onRun:id=>opened.push(['run',id]),onRequest:id=>opened.push(['request',id]),onExternal:url=>opened.push(['url',url])});view.setActive(true);`);
  await evaluate('Promise.resolve().then(()=>Promise.resolve())');
  await evaluate("view.showProvider('gbox-sparkDeux')");
}
const skip=!findChrome()&&'no Chromium installed';
test('browser: every entry is reachable through chronological pages, charts and evidence links',{skip},async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    const initial=await evaluate(`({visible:!document.querySelector('.dw-outcomes-host').hidden,rows:document.querySelectorAll('.dwo tbody tr').length,bubbles:document.querySelectorAll('.dwo-node').length,count:document.querySelector('[data-work-count]').textContent,first:document.querySelector('.dwo tbody [data-work-select]').textContent})`);
    assert.equal(initial.visible,true);assert.equal(initial.rows,24);assert.equal(initial.bubbles,24);assert.match(initial.count,/of 56 entries/);assert.match(initial.first,/Expanded graph/);
    assert.deepEqual(await evaluate(`(()=>{document.querySelector('[data-work-link]').click();document.querySelector('[data-work-request]').click();return opened})()`),[['url','https://github.com/teamcsharp/gBox/pull/42'],['request','request42']]);
    const keys=await evaluate(`(()=>{const keys=[];do{keys.push(...[...document.querySelectorAll('.dwo tbody [data-work-select]')].map(b=>b.dataset.workSelect));const next=document.querySelector('[data-work-next]');if(next.disabled)break;next.click();}while(true);return keys})()`);
    assert.equal(keys.length,56);assert.equal(new Set(keys).size,56);
    assert.equal(await evaluate(`(()=>{const order=document.querySelector('[data-work-order]');order.value='oldest';order.dispatchEvent(new Event('change'));return document.querySelector('.dwo tbody [data-work-select]').textContent})()`),'Task 0');
    const selected=await evaluate(`(()=>{const node=document.querySelector('.dwo-node');node.focus();node.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));return {selected:view.state.selected,focus:document.activeElement.dataset.workSelect}})()`);
    assert.deepEqual(selected,{selected:'r0',focus:'run:r0'});
    await evaluate(`document.querySelector('[data-open-run]').click()`);assert.deepEqual(await evaluate('opened.at(-1)'),['run','r0']);
    await evaluate(`const order=document.querySelector('[data-work-order]');order.value='newest';order.dispatchEvent(new Event('change'));document.querySelector('#tk-devices').scrollTop=0;`);
    if(process.env.GBOX_OUTCOMES_SCREENSHOT){const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(process.env.GBOX_OUTCOMES_SCREENSHOT,Buffer.from(shot.result.data,'base64'));}
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
    await send('Emulation.setDeviceMetricsOverride',{width:700,height:900,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
    assert.equal(await evaluate("document.querySelector('.dw-main').scrollWidth<=document.querySelector('.dw-main').clientWidth"),true);
  });
});
test('browser: refresh preserves filters, page and focus; provider with no evidence never falls back to Spark2',{skip},async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    const stable=await evaluate(`(async()=>{const q=document.querySelector('[data-work-search]');q.value='Task';q.dispatchEvent(new Event('input'));document.querySelector('[data-work-next]').click();q.focus();const before=document.querySelector('[data-work-count]').textContent;const n=calls.length;snapshot.runs.find(r=>r.id==='r30').current_action='New recorded action';await view.refresh();return {before,after:document.querySelector('[data-work-count]').textContent,focus:document.activeElement===q,query:q.value,calls:calls.length-n,text:document.querySelector('.dwo tbody').textContent}})()`);
    assert.equal(stable.before,stable.after);assert.equal(stable.focus,true);assert.equal(stable.query,'Task');assert.equal(stable.calls,1);assert.match(stable.text,/New recorded action/);
    const cloud=await evaluate(`(async()=>{view.showProvider('nous','7d');await Promise.resolve();return {device:view.state.device,title:document.querySelector('[data-work-name]').textContent,rows:document.querySelectorAll('.dwo tbody tr').length,call:calls.at(-1)}})()`);
    assert.equal(cloud.device,'provider:nous');assert.equal(cloud.title,'nous');assert.equal(cloud.rows,1);assert.match(cloud.call,/window=7d/);
    const empty=await evaluate(`(async()=>{view.showProvider('new-provider','7d');await Promise.resolve();return {device:view.state.device,rows:document.querySelectorAll('.dwo tbody tr').length,empty:document.querySelector('.dwo-empty').textContent,metric:document.querySelector('.dw-metrics b').textContent}})()`);
    assert.equal(empty.device,'provider:new-provider');assert.equal(empty.rows,0);assert.match(empty.empty,/No attributed entries/);assert.equal(empty.metric,'\u2014');
    const shared=await evaluate(`(async()=>{snapshot.devices.unshift({id:'lilspark',provider:'custom',metrics:{}});snapshot.devices.find(d=>d.id==='sparkDeux').provider='custom';await view.refresh();view.showProvider('sparkDeux');await Promise.resolve();const exact=view.state.device;view.showProvider('custom');await Promise.resolve();return {exact,ambiguous:view.state.device,rows:document.querySelectorAll('.dwo tbody tr').length}})()`);
    assert.deepEqual(shared,{exact:'sparkDeux',ambiguous:'provider:custom',rows:0},'a shared route name cannot select an arbitrary local machine');
    assert.equal(await evaluate(`(async()=>{view.setActive(false);const n=calls.length;await view.refresh();return calls.length-n})()`),0);
  });
});
test('browser: provider cards and technical buttons open outcomes while task controls stay independent',{skip},async()=>{
  await withPage(async(evaluate)=>{
    const handler=desktop.slice(desktop.indexOf('async function tkProvidersWindow('),desktop.indexOf('\n}',desktop.indexOf('async function tkProvidersWindow('))+2);
    assert.match(handler,/showProvider/);
    await evaluate(`${read('hermes-providers.js')}window.opened=[];window.controlCalls=[];window.gbox={api:async(...args)=>{controlCalls.push(args);return {ok:true}}};window.toast=()=>{};window.tkProvidersLoad=()=>{};window.TK={providersWindow:'7d',deviceView:{showProvider:(...args)=>opened.push(args)}};window.tkView=v=>opened.push(v);document.body.innerHTML=GBoxProviders.cards({routes:[{key:'nous/m',provider:'nous',model:'m'}],pool:{nodes:[{name:'sparkDeux',provider:'gbox-sparkDeux',concurrency_choices:[1,2],capacity:1,enabled:true}]}});${handler};document.body.addEventListener('click',tkProvidersWindow);`);
    const result=await evaluate(`(async()=>{document.querySelector('[data-tkp-route] [data-tkp-open-work]').click();document.querySelector('[data-tkp-capacity]').click();document.querySelector('[data-tkp-node]').closest('label').click();return opened})()`);
    assert.deepEqual(result,['devices',['nous','7d']]);
    assert.equal(await evaluate('controlCalls.length'),1,'node checkbox still updates the node independently');
    await evaluate(`document.querySelector('[data-tkp-machine] [data-tkp-open-work]').click()`);assert.deepEqual(await evaluate('opened.slice(-2)'),['devices',['sparkDeux','7d']]);
  });
});
