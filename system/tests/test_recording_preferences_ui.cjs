const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const html=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
const menu=html.slice(html.indexOf('// These preferences belong'),html.indexOf('document.addEventListener("mousedown", e => { if (!e.target.closest("#recmenu'));
const actions=html.slice(html.indexOf('async function recordAction(mode)'),html.indexOf('// ---------------- replay ring pop-up'));
test('record icon defaults to gameplay and per-instance export preferences persist through the menu',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:960,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.body.innerHTML='<button id="tb-rec">Record</button><button id="tb-recopt" style="margin-left:500px">Recording preferences</button>';
   document.head.insertAdjacentHTML('beforeend',${JSON.stringify('<style>:root{--bg:#16161a;--card:#22252c;--fg:#eee;--line:#535d74;--acc:#8b9fff}body{background:#16161a;color:#eee;font:14px system-ui}button,input,select{background:#22252c;color:#eee;border:1px solid #535d74;padding:6px}'+html.slice(html.indexOf('  #recmenu {'),html.indexOf('  #ringpop {'))+'</style>')});
   window.$=s=>document.querySelector(s);window.toasts=[];window.toast=s=>toasts.push(s);window.ringPopOpen=()=>{};
   window.REC={};window.modes=[];window.toggleRecording=async mode=>modes.push(mode);window.alert=s=>{throw Error(s)};
   window.saved={targetMB:20,speed:'balanced',keep:true,capture:'gameplay',exportDir:''};window.saves=[];
   Object.defineProperty(window,'localStorage',{value:{getItem:()=>JSON.stringify({targetMB:12,speed:'fast',keep:false})},configurable:true});
   window.gbox={settings:async()=>({}),recPreferences:async()=>({...saved}),saveRecPreferences:async p=>{saved={...p};saves.push(p);return {...p};},
    pickFolder:async()=>'/chosen/export',recOpen:async()=>{},openPath:async()=>{}};`);
  await evaluate(menu);await evaluate(actions);
  await evaluate(`(async()=>{await recordingPrefsReady;await document.querySelector('#tb-rec').onclick();await openRecMenu({stopPropagation(){}});})()`);
  assert.deepEqual(await evaluate('modes'),['gameplay']);
  assert.equal(await evaluate(`document.querySelector('#rec-keep').checked`),true,'old destructive default must not override original preservation');
  assert.equal(await evaluate(`document.querySelector('#rec-target').value`),'12','migrate existing size preference');
  const folder='\\\\10.89.1.246\\spark_ext\\samples_grabbed\\user\\gBox';
  await evaluate(`(async()=>{document.querySelector('#rec-export').value=${JSON.stringify(folder)};document.querySelector('#rec-capture').value='app';await saveRecOpts();await document.querySelector('#tb-rec').onclick();})()`);
  assert.deepEqual(await evaluate('modes'),['gameplay','app']);
  assert.equal(await evaluate('saved.exportDir'),folder);
  assert.equal(await evaluate('saved.keep'),true);
  await evaluate(`(async()=>{await openRecMenu({stopPropagation(){}});document.querySelector('#rec-keep').checked=false;await saveRecOpts();})()`);
  assert.equal(await evaluate('saved.keep'),false);
  assert.match(await evaluate(`document.querySelector('#rec-pref-status').textContent`),/Saved for this gBox instance/);
  assert.equal(await evaluate(`(async()=>{REC.mr={};recordingPrefsSave=Promise.reject(Error('invalid folder'));recordingPrefsSave.catch(()=>{});const n=modes.length;await recordAction();delete REC.mr;recordingPrefsSave=Promise.resolve();return modes.length===n+1;})()`),true,'invalid export settings cannot prevent stopping a recording');
  if(process.env.GBOX_RECORDING_EVIDENCE){
   await evaluate(`(async()=>{document.querySelector('#rec-capture').value='gameplay';document.querySelector('#rec-keep').checked=true;await saveRecOpts();document.querySelector('#recmenu').classList.add('on');document.body.insertAdjacentHTML('beforeend','<p style="position:fixed;bottom:8px">Recording preferences UI fixture; no gameplay captured</p>');})()`);
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_RECORDING_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_RECORDING_EVIDENCE,'recording-preferences.png'),Buffer.from(shot.result.data,'base64'));
  }
 });
});
