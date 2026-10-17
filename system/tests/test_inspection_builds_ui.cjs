const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const BV=require('../clients/web/viz/builds.js'),{withPage}=require('../scripts/browser_lifecycle.cjs');
const fixture={policy:{enabled:true,node:'JAYBUILTFINALE',memory_gib:8,builds_per_hour:3,max_memory_percent:80,reserve_gib:4},
 plans:[{game_id:'g',title:'Soul Calibur II',state:'needs_review',reason:'New operator feedback must be reviewed before producing another build.'}]};
test('inspection status explains budgets and pending work without a verified-game claim',()=>{
 const html=BV.inspectionHTML(fixture);
 assert.match(html,/8/);assert.match(html,/not an OS memory cap/);assert.match(html,/needs review/);
 assert.match(html,/do not auto-launch/);assert.match(BV.inspectionHTML({...fixture,plans:[]}),/Waiting for the agent/);
 assert.doesNotMatch(BV.inspectionHTML({...fixture,plans:[{title:'<script>',state:'blocked',reason:'<error>'}]}),/<script>|<error>/);
});
test('browser: pause/reservation save, polling preserves focused changes, no launches',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1150,height:800,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/builds.js'),'utf8'));
  await evaluate(`document.body.style='background:#15151a;color:#eee;font:14px system-ui;padding:20px';document.body.innerHTML='<div id="host"></div>';
   var snapshot=${JSON.stringify(fixture)},calls=[];var now=Date.now();Date.now=()=>now;
   var api=async(p,b)=>{calls.push({p,b});if(p==='/api/inspection-builds'){if(b)snapshot.policy={...snapshot.policy,...b};return snapshot;}
    if(p.startsWith('/api/build-retention'))return {default:3,games:{}};
    if(p==='/api/builds/scheduled')return {jobs:[],recent:[]};
    if(p.startsWith('/api/builds'))return {items:[],total:0};throw Error('unexpected '+p);};
   var ctl=GBoxBuilds.mount(document.querySelector('#host'),{api,here:'JAYBUILTFINALE',visible:()=>true,tick:1000000,toast:()=>{}});ctl.ready;`);
  assert.equal(await evaluate(`document.querySelector('[data-bv-inspection-memory]').value`),'8');
  await evaluate(`document.querySelector('[data-bv-inspection-memory]').focus();document.querySelector('[data-bv-inspection-memory]').value='12';now+=16000;ctl.tick();`);
  assert.equal(await evaluate(`document.querySelector('[data-bv-inspection-memory]').value`),'12');
  await evaluate(`document.querySelector('[data-bv-inspection-enabled]').checked=false;document.querySelector('[data-bv="inspection-save"]').click();new Promise(r=>setTimeout(r,20));`);
  assert.deepEqual(await evaluate(`calls.find(c=>c.p==='/api/inspection-builds'&&c.b).b`),{enabled:false,memory_gib:12});
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs'||c.p.includes('/launch'))`),false);
  if(process.env.GBOX_INSPECTION_EVIDENCE){
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_INSPECTION_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_INSPECTION_EVIDENCE,'inspection-queue.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate('ctl.stop()');
 });
});
