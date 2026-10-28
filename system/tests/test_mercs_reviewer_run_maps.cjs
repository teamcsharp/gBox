// The run reviewer's run maps (gbox.mercs.run_capture, gbox.run_map/1): every captured RE5 / RE6 Switch round's 2D path,
// health, decisions, statues and events, scrubbed in time (operator 2026-10-27 20:28).
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const R=require('../clients/web/viz/mercs-reviewer.js');

function runMap(){
  const route=[],hp=[],heading=[];
  for(let i=0;i<40;i++){route.push([1000+i*.2,i*50,i<20?0:(i-20)*40,30]);hp.push(i<30?900:700);heading.push(.5);}
  return {format:'gbox.run_map/1',title:'01002A000CD48000',stage:'Rail Yard',round_id:'a'.repeat(32),session_id:'worker-session',outcome:'died',
    cell:250,hp_max:900,route,hp,heading,view:{x:-1,z:1},
    doing:[[0,'walk',null,'to the capsule'],[20,'fire','match','crowd'],[39,'dead',null,null]],
    enemies:[[0,[[300,0]]],[5,[[600,50],[900,0]]]],clock:[[0,120,0,0,0],[5,119,500,1,1]],
    bonuses:[{id:'5',kind:'time',secs:null,pos:[1000,0,30],seen_t:1000,gone_t:1004,gone_d:0,taken:true},{id:'6',kind:'time',secs:null,pos:[-3000,2000,30],seen_t:1000,gone_t:null,gone_d:null,taken:false}],
    events:[{t:1002,kind:'shots',x:500,z:0,n:3},{t:1006,kind:'hit',x:1500,z:400,loss:200,hp:700,attackers:[[1600,400,100]]},{t:1007.8,kind:'death',x:1950,z:760,doing:'fire'},{t:1003,kind:'kill',x:700,z:0,n:1},{t:1005,kind:'stuck',x:1000,z:0,counters:{stuck:1}}],
    standstills:[{from_s:4,seconds:3.2,at:[1000,0],phase:'fire'}],cells:[[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],[7,1],[7,2],[7,3]],
    exploration:{seconds:7.8,distance_m:17.6,cells:11,start_area_s:4,start_area_share:.513,start_r_m:10,max_from_spawn_m:20.9,coverage:{value:.5}},
    extent:{cell:250,runs:3,source:'observed: his paths, enemies and statues',known:[[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],[7,1],[7,2],[7,3],[-12,8],[4,1],[4,2]]},
    coverage_now:{value:.786,cells:11,known_cells:14,source:'observed: his paths, enemies and statues',runs:3},
    verdict:'stood still 3.2 s',hits_taken_events:1,deaths:1,bonuses_taken:1,bonuses_missed:1,time_by_phase:{walk:4,fire:3.8},file:'round_maps/01002A000CD48000/Rail_Yard/20261027-204100-aaaaaaaa.json'};
}

test('a run map becomes time-ordered playback frames without collision geometry',()=>{
  const map=runMap(),samples=R.roundMapSamples(map);
  assert.equal(samples.length,40);
  assert.deepEqual(samples[0].frame.players[0],{id:'p1',control:'bot',pos:[0,30,0],hp:900,hp_max:900,facing:.5});
  assert.deepEqual(samples[7].frame.enemies.map(e=>e.pos),[[600,30,50],[900,30,0]]);   // the enemies kept every 5th
  assert.notEqual(samples[4].frame.enemies[0].id,samples[5].frame.enemies[0].id,'nearest-ranked enemies are never lerped');
  assert.deepEqual(samples[6].frame.clock,{left:119,score:500,combo:1,kills:1});
  assert.equal(samples[25].frame.plan.doing,'fire');
  assert.equal(samples[19].frame.bonuses.find(b=>b.id==='5').taken,false);
  assert.equal(samples[20].frame.bonuses.find(b=>b.id==='5').taken,true);
  assert.equal(samples[39].frame.players[0].hp,700);
  const at=R.playbackFrame(samples,1000.1);assert.deepEqual(R.playerOf(at,'p1').pos,[25,30,0]);
  assert.deepEqual(R.roundMapEvents(map).map(e=>e.kind),['hit','death','stuck'],'shots and kills stay off the event list');
  assert.equal(R.roundMapSamples({route:[[1,'x',0]]}).length,0);
});

test('the exploration summary, the path colours and the mirrored view',()=>{
  const tiles=Object.fromEntries(R.exploreSummary(runMap()).map(([k,...v])=>[k,v]));
  assert.deepEqual(tiles['Explored'],['79%','11 of 14 known cells']);
  assert.deepEqual(tiles['Starting area'],['4 s','51% within 10 m of the spawn']);
  assert.deepEqual(tiles['Statues'],['1 taken','1 left standing']);
  assert.equal(tiles['Furthest from spawn'][0],'20.9 m');
  assert.equal(R.ramp(0),'rgb(56,189,248)');assert.equal(R.ramp(1),'rgb(251,191,36)');
  assert.notEqual(R.hpColor(1),R.hpColor(.1));
  const plain=R.transform([[0,0,0],[1000,0,1000]],500,500),mirror=R.transform([[0,0,0],[1000,0,1000]],500,500,1,[0,0],true);
  assert.ok(plain.point([1000,0,0])[0]>plain.point([0,0,0])[0]);
  assert.ok(mirror.point([1000,0,0])[0]<mirror.point([0,0,0])[0],'+x to the left, as the live tactical map draws');
  const p=[300,12,700],[x,y]=mirror.point(p);mirror.world(x,y,12).forEach((v,i)=>assert.ok(Math.abs(v-p[i])<1e-8));
  assert.equal(R.atIndex([[0,'a'],[5,'b']],4)[1],'a');assert.equal(R.atIndex([[2,'a']],1),null);
});

test('browser: a Switch run shows its run map, exploration, legend and scrubber',async()=>{
  const {withPage}=require('../scripts/browser_lifecycle.cjs');
  const map=process.env.GBOX_RUN_MAP?JSON.parse(fs.readFileSync(process.env.GBOX_RUN_MAP,'utf8')):runMap();
  const run={id:'notebook:'+map.round_id,round_id:map.round_id,title:'01002A000CD48000',geometry:'unknown',stage:map.stage,mode:'mercenaries',character:'Chris',
    started:map.started||1793000000,ended:map.ended||1793000000,outcome:map.outcome,active:false,spatial:false,source_id:'gbox:mercs:01002A000CD48000:'+map.round_id,
    round_map:{available:true,file:map.file},exploration:map.exploration,assistance:{classification:'unknown',verified:false}};
  const older={...run,id:'notebook:'+'c'.repeat(32),round_id:'c'.repeat(32),round_map:{available:false},exploration:null};
  const detail={run,round_map:map,samples:[],events:[],geometry:null,notebook:{source_id:run.source_id,observed:{}},suggestions:[],next_after:-1,more:false,provenance:{}};
  const server=http.createServer((req,res)=>{res.setHeader('content-type','text/html');res.end('<!doctype html><html><body style="margin:0;padding:16px;background:#16161a;color:#eee;font:14px system-ui"><main id="host"></main></body></html>');});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    await withPage(async(evaluate,send)=>{
      await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
      for(let i=0;i<100&&!await evaluate(`document.readyState==='complete'`);i++)await new Promise(r=>setTimeout(r,10));
      await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1100,deviceScaleFactor:1,mobile:false});
      const shellStyle=fs.readFileSync(path.join(__dirname,'../clients/web/index.html'),'utf8').match(/<style>([\s\S]*?)<\/style>/)[1];
      await evaluate(`document.documentElement.dataset.embedded='true';document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(shellStyle)}+'</style>');`);
      await evaluate(`document.head.insertAdjacentHTML('beforeend','<style>'+${JSON.stringify(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mercs-reviewer.css'),'utf8'))}+'</style>');`);
      await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/mercs-reviewer.js'),'utf8'));
      await evaluate(`window.detail=${JSON.stringify(detail)};window.older=${JSON.stringify(older)};window.calls=[];
        window.api=async p=>{calls.push(p);if(p.endsWith('/catalog'))return {games:[{id:'01002A000CD48000',name:'Resident Evil 6 (Switch)',visible_runs:2,mapped_runs:1,stages:[],characters:['Chris']}]};
          if(p.includes('/runs?'))return {runs:[detail.run,older]};
          if(p.includes('/round?'))return new URLSearchParams(p.split('?')[1]).get('id')===older.id?{...detail,run:older,round_map:null}:detail;
          if(p.includes('/live?'))return {live:false,reason:'not active'};throw Error(p);};
        window.ctl=GBoxMercsReviewer.mount(document.querySelector('#host'),{api});`);
      for(let i=0;i<100&&!await evaluate(`document.querySelector('.mr-status').textContent==='Recorded run'`);i++)await new Promise(r=>setTimeout(r,20));
      assert.match(await evaluate(`document.querySelector('.mr-run .mr-run-map').textContent`),/^Run map · [\d.]+ m · furthest/);
      assert.equal(await evaluate(`document.querySelectorAll('.mr-run')[1].querySelector('.mr-run-nomap').textContent`),'No run map');
      assert.match(await evaluate(`document.querySelector('.mr-map-note').textContent`),/run map · \d+% of the known stage/);
      assert.equal(await evaluate(`document.querySelector('.mr-explore').hidden`),false);
      assert.equal(await evaluate(`document.querySelectorAll('.mr-explore .mr-kpi').length`),7);
      assert.equal(await evaluate(`document.querySelector('.mr-colour').hidden`),false);
      assert.equal(await evaluate(`document.querySelector('.mr-teachbar').hidden&&document.querySelector('.mr-editbar').hidden`),true,'no floor to teach or draw on');
      assert.ok(await evaluate(`[...document.querySelectorAll('.mr-legend span')].some(s=>s.textContent==='Statue taken ● left ○')`));
      assert.ok(await evaluate(`!document.querySelector('.mr-events').textContent.includes('shots')`));
      assert.ok(await evaluate(`(()=>{const c=document.querySelector('.mr-map'),x=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let lit=0;for(let i=0;i<x.length;i+=4)if(x[i]+x[i+1]+x[i+2]>300)lit++;return lit>50;})()`),'the path is drawn');
      if(!process.env.GBOX_RUN_MAP){
        await evaluate(`{const s=document.querySelector('.mr-controls input');s.value='1000';s.dispatchEvent(new Event('input'));}`);
        assert.equal(await evaluate(`document.querySelectorAll('.mr-kpi b')[2].textContent`),'700 / 900');
        await evaluate(`{const s=document.querySelector('.mr-controls input');s.value='0';s.dispatchEvent(new Event('input'));}`);
        assert.equal(await evaluate(`document.querySelectorAll('.mr-kpi b')[2].textContent`),'900 / 900');
        await evaluate(`{const c=document.querySelector('.mr-colour');c.value='hp';c.dispatchEvent(new Event('change'));}`);
        await evaluate(`document.querySelector('.mr-sidebar details:nth-of-type(4) .mr-param')?.click()`);
        await evaluate(`document.querySelector('dialog').open&&document.querySelector('dialog').close()`);
      }else{                                  // evidence from a real run map: scrubbed to GBOX_RUN_MAP_AT (per mille)
        await evaluate(`{const s=document.querySelector('.mr-controls input');s.value=${JSON.stringify(String(+(process.env.GBOX_RUN_MAP_AT||620)))};s.dispatchEvent(new Event('input'));}`);
        if(process.env.GBOX_RUN_MAP_COLOUR)await evaluate(`{const c=document.querySelector('.mr-colour');c.value=${JSON.stringify(process.env.GBOX_RUN_MAP_COLOUR)};c.dispatchEvent(new Event('change'));}`);
      }
      if(process.env.GBOX_REVIEWER_EVIDENCE){fs.mkdirSync(process.env.GBOX_REVIEWER_EVIDENCE,{recursive:true});await new Promise(r=>setTimeout(r,150));
        const metrics=await send('Page.getLayoutMetrics'),size=metrics.result.cssContentSize||metrics.result.contentSize;
        const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:size.width,height:Math.min(size.height,1600),scale:1}});
        fs.writeFileSync(path.join(process.env.GBOX_REVIEWER_EVIDENCE,process.env.GBOX_REVIEWER_SHOT||'mercs-reviewer-run-map.png'),Buffer.from(shot.result.data,'base64'));}
      await evaluate(`document.querySelectorAll('.mr-run')[1].click()`);
      for(let i=0;i<80&&!await evaluate(`document.querySelector('.mr-explore').hidden`);i++)await new Promise(r=>setTimeout(r,20));
      assert.equal(await evaluate(`document.querySelector('.mr-explore').hidden`),true);
      assert.match(await evaluate(`document.querySelector('.mr-map-note').textContent`),/No run map for this round/);
      await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
      await evaluate(`document.querySelectorAll('.mr-run')[0].click()`);
      for(let i=0;i<80&&await evaluate(`document.querySelector('.mr-explore').hidden`);i++)await new Promise(r=>setTimeout(r,20));
      await new Promise(r=>setTimeout(r,100));
      const fit=await evaluate(`({scroll:document.documentElement.scrollWidth,width:innerWidth})`);
      assert.ok(fit.scroll<=fit.width,JSON.stringify(fit));
      await evaluate(`ctl.dispose()`);
    },{timeoutMs:45000});
  }finally{await new Promise(resolve=>server.close(resolve));}
});
