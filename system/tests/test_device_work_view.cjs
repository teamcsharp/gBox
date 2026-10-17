'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const P=require('../clients/desktop/device-work.js');
const {withPage,findChrome}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/desktop/device-work.js'),'utf8');
const css=fs.readFileSync(path.join(__dirname,'../clients/desktop/device-work.css'),'utf8');
const desktop=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
const desktopStyles=[...desktop.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m=>m[1]).join('\n');
const NOW=1792272000;
function fixture() {
  const metrics={active_runs:24,ended_runs:3,failed_runs:1,prs_opened:1,prs_merged:1,requests_resolved:0,calls_ok:90,calls_failed:10,tokens_in:10000,tokens_out:2000,wall_s:7200,peak_concurrency:24};
  const runs=Array.from({length:24},(_,i)=>({id:'r'+i,device_id:'sparkDeux',title:'#'+(2400+i)+' '+['Sonic model extraction','Mario cast replacement','Resident Evil inventory controls'][i%3],current_action:i%2?'Running native-reader regression tests':'Inspecting source model structure',state:'running',started:NOW-3600-i*200,finished:null,tickets:[],outcomes:[],attribution:{source:'successful_model_calls'}}));
  runs.push({id:'delivered',device_id:'sparkDeux',title:'Reader fixes',current_action:'Tests passed; PR merged',state:'completed',started:NOW-7200,finished:NOW-1000,tickets:[{id:'request1',number:2410,title:'Reader fixes',status:'open'}],outcomes:[{kind:'pr_merged',title:'PR #999: Reader fixes',url:'https://github.com/teamcsharp/gBox/pull/999',status:'merged',verified:true},{kind:'request_status',title:'Request marked done',request_id:'request1',status:'done',verified:false,evidence:{boundary:'Resolving run/device not established.'}}]});
  runs.push({id:'old',device_id:'sparkDeux',title:'Earlier failed attempt',state:'failed',started:NOW-30000,finished:NOW-29000,outcomes:[]});
  runs.push({id:'unaccepted',device_id:'sparkDeux',title:'Run ended without acceptance',state:'completed',started:NOW-100,finished:NOW-10,outcomes:[]});
  runs.push({id:'other',device_id:'lilspark',title:'Other device work',state:'running',started:NOW-10,outcomes:[]});
  return {generated_at:NOW,window:{key:'today',label:'Today',start:NOW-43200,end:NOW},coverage:{partial:true,notes:['Fixture data for browser tests.']},devices:[{id:'lilspark',name:'lilspark',metrics:{active_runs:1,calls_ok:0,calls_failed:0}},{id:'sparkDeux',name:'Spark2',model:'Local model',metrics},{id:'unknown',name:'unknown',metrics:{active_runs:0,calls_ok:null,calls_failed:null}}],runs};
}
test('all 24 concurrent runs remain visible and device/filter counts are independent',()=>{
  const d=fixture();assert.equal(P.visibleRuns(d,'sparkDeux','active').length,24);
  assert.equal(P.visibleRuns(d,'sparkDeux').length,27);
  assert.equal(P.visibleRuns(d,'sparkDeux','results').length,1);
  assert.equal(P.visibleRuns(d,'sparkDeux','active','inventory').length,8);
  assert.equal(P.visibleRuns(d,'lilspark').length,1);
  assert.equal(P.friendly({id:'sparkDeux'}),'Spark2');assert.equal(P.friendly({id:'unknown'}),'Unattributed');
});
test('overlapping runs use exact intervals; ended runs do not count forever',()=>{
  assert.deepEqual(P.concurrency([{started:0,finished:20,state:'completed'},{started:10,state:'running'}],{start:0,end:30},3).map(x=>x.count),[1,2,1,1]);
  assert.match(P.graph([],{start:0,end:30}),/observed peak 0/);
  assert.match(P.graph([{started:100,finished:220,state:'completed'}],{start:0,end:21600}),/observed peak 1/,'short runs between chart samples still appear');
  assert.deepEqual(P.concurrency([{started:1,finished:2,state:'completed'},{started:2,finished:3,state:'completed'}],{start:0,end:10}).map(x=>x.count),[0,1,1,0,0],'adjacent intervals do not overlap');
  assert.notEqual(P.graph([],{start:NOW-7*86400,end:NOW}),P.graph([],{start:NOW-3600,end:NOW}),'multi-day graph has dated labels');
  assert.equal(P.stateLabel({state:'completed'}),'Run ended');
  assert.equal(P.outcomeLabel({kind:'request_status',status:'done'}),'Request done');
  assert.equal(P.outcomeLabel({kind:'request_resolved',status:'done'}),'Request resolved');
});
test('clipped and missing timestamps never invent bars; labels and links reject injected content',()=>{
  const bounds={start:NOW-3600,end:NOW};
  const old=P.row({id:'old',title:'<img onerror=attack()>',state:'completed',started:NOW-9000,finished:NOW-8000},bounds,null);
  assert.match(old,/outside range/);assert.doesNotMatch(old,/<i style/);assert.doesNotMatch(old,/<img /);assert.match(old,/&lt;img/);
  assert.doesNotMatch(P.row({id:'missing',state:'completed',started:null,finished:null},bounds,null),/<i style/);
  assert.match(P.row({id:'running',state:'running',started:NOW-9000},bounds,null),/left:0.000%;width:100.000%/);
  assert.equal(P.url('javascript:alert(1)'),'');assert.equal(P.url('file:///etc/passwd'),'');
  assert.equal(P.url('https://github.com/teamcsharp/gBox/pull/999'),'https://github.com/teamcsharp/gBox/pull/999');
});
test('desktop defaults to the dedicated read-only device view and suspends it on close',()=>{
  assert.match(desktop,/view: "devices", deviceView: null/);
  assert.match(desktop,/id="tk-devices-tab"[^>]+aria-selected="true"/);
  assert.match(desktop,/id="tk-visual-tab"[^>]+>Network</);
  assert.match(desktop,/async function tasksLoad\(\) \{\s*if \(TK.view === "devices"\) return TK.deviceView\?\.refresh\(\);/);
  assert.match(desktop,/#tk-close"\)\.onclick[^\n]+deviceView\?\.setActive\(false\)/);
  assert.match(desktop,/if \(pop === "#taskpanel"\)[^\n]+deviceView\?\.setActive\(false\)/);
  assert.match(desktop.slice(desktop.indexOf('async function tvOpen('),desktop.indexOf('async function tvOpen(')+400),/deviceView\?\.setActive\(false\)/);
});
const skip=!findChrome()&&'no Chromium installed';
async function setup(evaluate,send) {
  await send('Emulation.setDeviceMetricsOverride',{width:1500,height:950,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.head.innerHTML='<style>body{margin:0;background:#090d15;font-family:Segoe UI,Arial,sans-serif}#taskpanel{position:fixed}.th{height:47px;display:flex;align-items:center;padding:0 15px;gap:20px;border-bottom:1px solid #33425d;box-sizing:border-box}.th button{background:#334568;color:white;padding:8px;border:1px solid #5a6b8a;border-radius:5px}</style>';document.body.innerHTML='<div id="taskpanel" class="device-mode"><div class="th"><b>Tasks</b><button>Device work</button><span>Network</span><span>Technical</span><span style="margin-left:auto">Browser test fixture</span></div><div id="tk-devices"></div></div>';`);
  await evaluate(`{const style=document.createElement('style');style.textContent=${JSON.stringify(desktopStyles+'\n'+css)};document.head.append(style);document.querySelector('#taskpanel').classList.add('on');}${source}`);
  await evaluate(`window.snapshot=${JSON.stringify(fixture())};window.calls=[];window.opened=[];window.reply=()=>Promise.resolve({ok:true,data:structuredClone(snapshot)});window.view=GBoxDeviceWork.mount(document.querySelector('#tk-devices'),{api:p=>{calls.push(p);return reply(p)},onRun:id=>opened.push(['run',id]),onRequest:id=>opened.push(['request',id]),onExternal:url=>opened.push(['url',url])});view.setActive(true);`);
  await evaluate('Promise.resolve().then(()=>Promise.resolve())');
}
test('real browser: 24 active lanes, device selection, evidence links, and stable polling', {skip},async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    assert.deepEqual(await evaluate(`({device:view.state.device,rows:document.querySelectorAll('.dw-row.active').length,count:document.querySelector('.dw-count').textContent})`),{device:'sparkDeux',rows:24,count:'27 of 27 observed runs'});
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.dw-main')).display!=='none'&&document.querySelector('.dw-main').getBoundingClientRect().width>500&&getComputedStyle(document.querySelector('.dw-inspect')).display!=='none'`),true,'native desktop section styles cannot hide the timeline or evidence');
    const stable=await evaluate(`(async()=>{const pane=document.querySelector('.dw-runs');pane.scrollTop=600;const row=document.querySelector('[data-run="r8"]');row.focus({preventScroll:true});row.click();const before=pane.scrollTop;snapshot.generated_at+=20;snapshot.window.end+=20;await view.refresh();return {before,after:pane.scrollTop,selected:view.state.selected,focus:document.activeElement.dataset.run,calls:calls.length}})()`);
    assert.equal(stable.before,stable.after);assert.equal(stable.selected,'r8');assert.equal(stable.focus,'r8');assert.equal(stable.calls,2);
    assert.deepEqual(await evaluate(`(()=>{document.querySelector('[data-run="delivered"]').click();document.querySelector('[data-open-run]').click();document.querySelector('[data-request]').click();document.querySelector('[data-outcome="0"]').click();return opened})()`),[['run','delivered'],['request','request1'],['url','https://github.com/teamcsharp/gBox/pull/999']]);
    assert.match(await evaluate(`document.querySelector('.dw-detail').textContent`),/Resolving run\/device not established/);
    const filtered=await evaluate(`(()=>{const search=document.querySelector('[data-search]');search.focus();search.value='inventory';search.dispatchEvent(new Event('input'));return {rows:document.querySelectorAll('.dw-row').length,focus:document.activeElement===search}})()`);
    assert.equal(filtered.rows,8);assert.equal(filtered.focus,true);
    const metrics=await evaluate(`(()=>{document.querySelector('[data-device="lilspark"]').click();const zero=document.querySelector('.dw-detail').textContent;document.querySelector('[data-device="unknown"]').click();return {zero,unknown:document.querySelector('.dw-detail').textContent}})()`);
    assert.match(metrics.zero,/Model calls0/);assert.match(metrics.unknown,/Model calls—/);
    await evaluate(`document.querySelector('[data-device="sparkDeux"]').click();const search=document.querySelector('[data-search]');search.value='';search.dispatchEvent(new Event('input'));document.querySelector('.dw-runs').scrollTop=0;`);
    if(process.env.GBOX_DEVICE_WORK_SCREENSHOT){const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(process.env.GBOX_DEVICE_WORK_SCREENSHOT,Buffer.from(shot.result.data,'base64'));}
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
    await send('Emulation.setDeviceMetricsOverride',{width:700,height:900,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
    assert.equal(await evaluate(`document.querySelector('.dw-main').scrollWidth<=document.querySelector('.dw-main').clientWidth`),true);
  });
});
test('real browser: one in-flight read, stale responses discarded, errors retain evidence, close stops reads',{skip},async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    const pending=await evaluate(`(()=>{window.resolveOld=null;reply=()=>new Promise(r=>resolveOld=r);view.refresh();view.refresh();const picker=document.querySelector('[data-window]');picker.value='7d';picker.dispatchEvent(new Event('change'));return calls.length})()`);
    assert.equal(pending,2,'refresh/window switch cannot overlap the pending read');
    const changed=await evaluate(`(async()=>{reply=()=>Promise.resolve({ok:true,data:{...snapshot,window:{...snapshot.window,key:'7d',label:'7 days'}}});resolveOld({ok:true,data:{...snapshot,devices:[]}});await Promise.resolve();await Promise.resolve();await Promise.resolve();return {window:view.state.data.window.key,devices:view.state.data.devices.length,calls}})()`);
    assert.equal(changed.window,'7d');assert.equal(changed.devices,3);assert.match(changed.calls[2],/window=7d/);
    const error=await evaluate(`(async()=>{reply=()=>Promise.resolve({ok:false,error:'Offline <script>bad()</script>'});await view.refresh();return {rows:document.querySelectorAll('.dw-row').length,notice:document.querySelector('.dw-notice').textContent,scripts:document.querySelectorAll('.dw-notice script').length}})()`);
    assert.equal(error.rows,27);assert.match(error.notice,/Last successful snapshot is retained/);assert.equal(error.scripts,0);
    const closed=await evaluate(`(async()=>{reply=()=>new Promise(r=>resolveOld=r);view.refresh();view.setActive(false);const before=calls.length;resolveOld({ok:true,data:{...snapshot,devices:[]}});await Promise.resolve();await view.refresh();return {before,after:calls.length,devices:view.state.data.devices.length}})()`);
    assert.equal(closed.before,closed.after);assert.equal(closed.devices,3);
  });
});
