const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
const script=source.slice(source.indexOf('async function oaLoad()'),source.indexOf('// ---------------- Settings > Sonic showcase'));
test('preferences: opt-in, model selection, per-PC save and readable unavailable state',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:950,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.body.style='background:#17171b;color:#eee;font:14px system-ui;padding:20px';document.body.innerHTML='<aside><button data-s="settings">Preferences</button></aside><div id="ollama-assist" style="max-width:620px"></div>';
   var $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');var calls=[];
   var fixture={workers:[{id:'pc',name:'JAYBUILTFINALE',policy:{enabled:false,model:'',context_tokens:8192,max_output_tokens:1024,model_budget_gib:6,reserve_gib:8},inventory:{available:true,models:[{name:'qwen2.5-coder:3b'}]},reason:'Idle Ollama assistance is disabled on this PC.'},{id:'nuc',name:'i9-NUC',policy:{enabled:false,model:'',context_tokens:8192,max_output_tokens:1024,model_budget_gib:6,reserve_gib:8},inventory:{},reason:'Idle Ollama assistance is disabled on this PC.'}]};
   var gbox={api:async(p,b)=>{calls.push({p,b});return {ok:true,data:fixture};}};`);
  await evaluate(script);
  await evaluate('oaLoad()');
  assert.equal(await evaluate(`document.querySelectorAll('[data-oa]').length`),2);
  assert.equal(await evaluate(`document.querySelector('[name=enabled]').checked`),false);
  assert.match(await evaluate('document.body.textContent'),/Ollama unavailable/);
  await evaluate(`var form=document.querySelector('[data-oa=pc]');form.elements.enabled.checked=true;form.elements.model.value='qwen2.5-coder:3b';form.elements.reserve_gib.value=12;form.requestSubmit();`);
  assert.deepEqual(await evaluate('calls.find(c=>c.b).b'),{enabled:true,model:'qwen2.5-coder:3b',context_tokens:8192,max_output_tokens:1024,model_budget_gib:6,reserve_gib:12});
  assert.equal(await evaluate('calls.find(c=>c.b).p'),'/api/ollama-assist/pc');
  assert.equal(await evaluate(`calls.some(c=>/jobs|pull|launch/.test(c.p))`),false);
  if(process.env.GBOX_OLLAMA_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_OLLAMA_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_OLLAMA_EVIDENCE,'ollama-preferences.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate(`gbox.api=async()=>({ok:false,error:'Backend update pending'});oaLoad();`);
  assert.match(await evaluate('document.body.textContent'),/Backend update pending/);
 });
});
