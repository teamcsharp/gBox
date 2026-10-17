const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const T=require('../clients/desktop/request-tokens.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const row=(id,input,output,extra={})=>({id,status:'done',metrics:{tokens_in:input,tokens_out:output},...extra});

test('project totals count ledger input/output once, including cached input, independent of rollups',()=>{
 const rows=[row('a',3_280_758_089,17_323_695,{metrics:{tokens_in:3_280_758_089,tokens_out:17_323_695,tokens_detail:{cache_read:3_000_000_000},usage_by_solver:[{tokens_in:3_280_758_089,tokens_out:17_323_695}]}}),row('b',10_000,5_000,{parent_request_id:'a'}),row('c',0,0,{status:'in_progress'})];
 const s=T.analyze([...rows,rows[0]]);
 assert.equal(s.total,3_298_096_784n);assert.equal(s.requests,3);assert.equal(s.reported,2);assert.equal(s.missing,1);
 assert.equal(s.tasks.get('a').combined.total,s.total);assert.equal(s.tasks.get('a').own.total,3_298_081_784n);
 assert.equal(s.completed.total,s.total);assert.equal(s.completed.requests,2);
 assert.match(T.taskHTML('a',s),/includes linked work/);assert.match(T.taskHTML('c',s),/not recorded/);
});

test('integer precision and invalid/missing measurements are explicit',()=>{
 assert.equal(T.format(T.count('999999999999999999999')), '999,999,999,999,999,999,999');
 for(const x of [NaN,Infinity,-1,1.5,true,null,undefined,'-1','oops',Number.MAX_SAFE_INTEGER+1])assert.equal(T.count(x),null);
 const s=T.analyze([row('a','999999999999999999999','1'),row('b',0,0,{metrics:{tokens_in:0,tokens_out:0,turns:10}}),row('c',0,0,{metrics:{tokens_in:0,tokens_out:0,tokens_detail:{availability:'measured_final'}}}),row('d',20,3,{metrics:{tokens_in:20,tokens_out:3,tokens_detail:{token_count_unavailable:1}}})]);
 assert.equal(s.total,1_000_000_000_000_000_000_023n);assert.equal(s.missing,2);assert.equal(s.reported,3);
 assert.match(T.taskHTML('d',s),/partial/);
});

test('linked task cycles and hostile ids do not inflate the global sum or inject HTML',()=>{
 const s=T.analyze([row('a',10,2,{parent_request_id:'b'}),row('b',20,3,{parent_request_id:'a'}),row('"<x>',4,1)]);
 assert.equal(s.total,40n);assert.ok(s.tasks.get('a').cycle);assert.doesNotMatch(T.taskHTML('"<x>',s),/data-group-key="token-usage-"<x>/);
});

async function pageFixture(evaluate,send,reduced=false){
 await send('Emulation.setDeviceMetricsOverride',{width:1320,height:920,deviceScaleFactor:1,mobile:false});
 if(reduced)await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
 await evaluate(fs.readFileSync(path.join(__dirname,'../clients/desktop/request-tokens.js'),'utf8'));
 const html=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8'),a=html.indexOf('<section id="requests">'),b=html.indexOf('<section id="tools">',a);
 await evaluate(`document.body.innerHTML=${JSON.stringify(html.slice(a,b))};document.querySelector('#requests').classList.add('on');
  document.head.insertAdjacentHTML('beforeend','<style>:root{--bg:#16161b;--card:#222228;--fg:#f1f1f6;--mut:#a2a6b5;--line:#383842;--accent:#8c9bff}body{margin:0;background:var(--bg);color:var(--fg);font:13px system-ui}section{height:100vh;overflow:auto}.pane{padding:24px;margin:auto;max-width:1100px}.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0 16px}button{font:inherit;background:var(--card);color:var(--fg);border:1px solid var(--line);padding:6px 10px;border-radius:5px}.mut{color:var(--mut)}.fixture-card{padding:18px;background:var(--card);border:1px solid var(--line);border-radius:8px;margin:12px 0}h3{font-size:13px;margin:8px 0}</style>');
  window.rows=[{id:'task',status:'done',metrics:{tokens_in:3280758089,tokens_out:17323695,tokens_detail:{cache_read:3000000000}}},{id:'child',status:'done',parent_request_id:'task',metrics:{tokens_in:10000,tokens_out:5000}},{id:'pending',status:'in_progress',metrics:{tokens_in:0,tokens_out:0}}];
  window.snapshot=GBoxRequestTokens.analyze(rows);window.host=document.querySelector('#reqtokens');window.section=document.querySelector('#requests');
  window.ctl=GBoxRequestTokens.mount(host,{analysis:document.querySelector('#reqtoken-analysis'),section});
  document.querySelector('#reqsum').textContent='UI fixture · all project requests, independent of the current filter';
  document.querySelector('#reqlist').innerHTML='<div class="fixture-card"><b>#241 · completed</b><h3>Verify the corrected character build</h3>'+GBoxRequestTokens.taskHTML('task',snapshot)+'</div><div class="fixture-card"><b>#242 · completed</b><h3>Native gameplay verification</h3>'+GBoxRequestTokens.taskHTML('child',snapshot)+'</div><div class="fixture-card"><b>#243 · in progress</b><h3>Follow-up awaiting usage report</h3>'+GBoxRequestTokens.taskHTML('pending',snapshot)+'</div><p class="mut">Animation and accounting UI fixture; illustrative task records.</p>';
  ctl.update(snapshot);`);
}

test('odometer rolls up left-to-right, pops the label, grows without replaying on unchanged polls, and replays on entry',async()=>{
 await withPage(async(evaluate,send)=>{
  await pageFixture(evaluate,send);
  assert.equal(await evaluate(`host.querySelector('.rt-accessible').textContent`),'3,298,096,784 recorded tokens spent on this project; some usage is unreported.');
  const timings=await evaluate(`host.querySelectorAll('.rt-digit .rt-track').length&&[...host.querySelectorAll('.rt-track')].map(e=>e.getAnimations()[0].effect.getTiming().duration)`);
  assert.ok(timings.every((v,i)=>!i||v>timings[i-1]),'each digit settles after its left neighbor');
  assert.equal(await evaluate(`host.querySelector('.rt-label').getAnimations()[0].effect.getTiming().delay`),timings.at(-1)+150);
  if(process.env.GBOX_TOKEN_EVIDENCE){
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_TOKEN_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_TOKEN_EVIDENCE,'request-tokens-rolling.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate(`host._tokenRevealDone.then(()=>new Promise(r=>setTimeout(r,450)))`);
  assert.equal(await evaluate(`[...host.querySelectorAll('.rt-digit')].map(e=>e.dataset.digit).join('')`),'3298096784');
  assert.equal(await evaluate(`getComputedStyle(host.querySelector('.rt-label')).opacity`),'1');
  assert.equal(await evaluate(`(()=>{const old=host.querySelector('.rt-track');ctl.update(snapshot);return old===host.querySelector('.rt-track');})()`),true,'unchanged polling preserves the digits');
  await evaluate(`rows[1].metrics.tokens_out+=7;ctl.update(GBoxRequestTokens.analyze(rows));host._tokenRevealDone;`);
  assert.match(await evaluate(`host.querySelector('.rt-accessible').textContent`),/3,298,096,791/);
  await evaluate(`section.classList.remove('on');new Promise(r=>setTimeout(r,20));`);
  assert.equal(await evaluate(`host.getAnimations({subtree:true}).filter(a=>a.playState==='running').length`),0);
  await evaluate(`section.classList.add('on');new Promise(r=>setTimeout(r,20));`);
  assert.ok(await evaluate(`host.getAnimations({subtree:true}).some(a=>a.playState==='running')`));
  await evaluate(`host._tokenRevealDone.then(()=>new Promise(r=>setTimeout(r,450)));`);
  if(process.env.GBOX_TOKEN_EVIDENCE){
   const shot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(process.env.GBOX_TOKEN_EVIDENCE,'request-tokens-settled.png'),Buffer.from(shot.result.data,'base64'));
  }
  await evaluate('ctl.dispose()');
 });
});

test('reduced motion shows the exact final value without animations',async()=>{
 await withPage(async(evaluate,send)=>{
  await pageFixture(evaluate,send,true);
  assert.equal(await evaluate(`host.getAnimations({subtree:true}).length`),0);
  assert.match(await evaluate(`host.querySelector('.rt-accessible').textContent`),/3,298,096,784/);
  await evaluate(`host.querySelector('.rt-coverage').click()`);
  assert.equal(await evaluate(`document.querySelector('#reqtoken-analysis').open`),true);
  assert.match(await evaluate(`document.querySelector('#reqtoken-analysis').textContent`),/Unreported tokens are not treated as zero spend/);
  await evaluate('ctl.dispose()');
 });
});
