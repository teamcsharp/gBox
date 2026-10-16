// Real browser coverage for the cast chart's request/build integration and popup lifecycle.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { withPage, findChrome } = require('../scripts/browser_lifecycle.cjs');
const skip = !findChrome() && 'No Chromium browser installed';
const source = ['cast-mapper.js', 'cast-swap.js', 'character-popup.js'].map(name =>
  fs.readFileSync(path.join(__dirname, '../clients/web/viz', name), 'utf8')).join('\n');
const fixture = String.raw`
  document.body.innerHTML='';document.body.style.cssText='margin:0;background:#10151f;color:#eef;font-family:system-ui';
  window.calls=[];window.saved=[];window.inspected=[];window.built=[];
  window.game={gid:'target-game',title:'Original title'};
  window.sourceRows=[{key:'donor-a',label:'Replacement title A',kind:'game',count:3},{key:'donor-b',label:'Replacement title B',kind:'game',count:2},{key:'donor-c',label:'Replacement title C',kind:'game',count:2}];
  window.native=false;window.pendingRoster={};window.pendingSave=null;window.lastJob=null;
  window.memory=new Map();window.storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)};
  window.originalTimeout=window.setTimeout.bind(window);
  window.waitFor=async fn=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>originalTimeout(r,20));}throw Error('Timed out waiting for browser state');};
  window.rosterFor=(source='donor-a')=>({game:{game_id:game.gid,title:game.title,platform:'GameCube'},source:{key:source,label:'Replacement title '+source.slice(-1).toUpperCase()},requested_scope:'all',
    targets:[{id:'original-a',slot:'fighter:a',name:'Original Alpha',slug:'original_alpha',model_url:'/api/characters/original_alpha/model',buildable:true},
      {id:'original-b',slot:native?'fighter:b':null,name:'Original Beta',slug:'original_beta',model_url:'/api/characters/original_beta/model',buildable:native},
      {id:'original-c',slot:'fighter:c',name:'Original Gamma',slug:'original_gamma',model_url:'/api/characters/original_gamma/model',buildable:true}],
    donors:[0,1,2].map(i=>({id:source+'_'+i,slug:source+'_'+i,name:'Replacement '+source.slice(-1).toUpperCase()+' '+i,source_game_id:source,
      model:'body.glb',model_url:'/api/characters/'+source+'_'+i+'/model',preview_url:'',ready:true})),
    capability:{status:native?'ready':'needs_writer',combined_writer:native,writer:native?'fixture_writer':null,native_slots_count:native?3:2,blocking_reasons:native?[]:['Native cast support requires engineering.']}});
  window.requestRow=body=>({id:'request-1',number:42,status:'open',kind:'build',mapping:body.mapping,description:body.description,dispatch:{mode:'queue'},jobs:[]});
  window.api=async(p,b)=>{calls.push({p,b:b===undefined?null:structuredClone(b)});
    if(p.startsWith('/api/cast_swap/sources?'))return {sources:sourceRows,slots:native?['fighter:a','fighter:b','fighter:c']:[]};
    if(p.startsWith('/api/cast_swap/roster?')){const key=new URL('http://fixture'+p).searchParams.get('source');if(pendingRoster[key])return new Promise(r=>pendingRoster[key].push(r));return rosterFor(key);}
    if(p.startsWith('/api/home/games?'))return {items:[{game_id:'unextracted-game',title:'Unextracted game',platform:'Dreamcast'}]};
    if(p==='/api/cast_swap/plan')return {status:native?'planned':'unsupported_cast',message:native?'Reviewed native mapping':'Needs native writer',donors:rosterFor(b.source).donors,assignments:native?[
      {slot:'fighter:a',slot_name:'Original Alpha',character:'donor-a_2'},{slot:'fighter:b',slot_name:'Original Beta',character:''},{slot:'fighter:c',slot_name:'Original Gamma',character:'donor-a_0'}]:[]};
    if(p==='/api/games/target-game/build-requests'){
      if(!b)return {items:saved};
      if(pendingSave)return new Promise(r=>pendingSave.push(()=>{const row=requestRow(b);saved.push(row);r(row);}));
      const row=requestRow(b);saved.push(row);return row;
    }
    if(p==='/api/jobs'){lastJob=b;return {id:'job-1',state:'succeeded',output:{result:{status:'built',mod:'cast_fixture',message:'Fixture native cast built',report:[]}}};}
    if(/^\/api\/characters\/[^/]+$/.test(p))return {slug:p.split('/').pop(),name:'Inspected character',model:'body.glb',source:{game_title:'Fixture title'}};
    throw Error('Unexpected API '+p);
  };
  window.io={api:(...a)=>api(...a),storage,img:u=>u?u+'?token=fixture-token':'',inspect:async o=>{inspected.push(o);return {close(){}};},onBuilt:r=>built.push(r)};
  window.openCast=()=>window.panel=GBoxCastSwap.open(document,io,game);
  window.ready=()=>waitFor(()=>document.querySelectorAll('[data-cm-card=target]').length===3);
  window.card=(side,key)=>document.querySelector('[data-cm-card="'+side+'"][data-key="'+key+'"]');
  window.connect=(target,donor)=>{card('target',target).querySelector('[data-action=target]').click();card('donor',donor).querySelector('[data-action=donor]').click();};
  window.go=action=>document.querySelector('[data-cs-go="'+action+'"]').click();
  window.chooseSource=source=>{const s=document.querySelector('[data-cs=source]');s.value=source;s.dispatchEvent(new Event('change',{bubbles:true}));};
`;

async function page(fn) {
  return withPage(async (evaluate, send) => { await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });
    await evaluate(source); await evaluate(fixture); evaluate.run = body => evaluate(`(async()=>{${body}})()`); return fn(evaluate, send); });
}

test('opening mounts the full chart without mutations; engineering request saves exact nullable connections', { skip }, async () => {
  await page(async (evaluate, send) => {
    await evaluate(`openCast();ready()`);
    assert.equal(await evaluate(`calls.some(c=>c.b!==null)`), false);
    assert.equal(await evaluate(`document.querySelectorAll('[data-cm-card=donor]').length`), 3);
    assert.equal(await evaluate(`document.querySelector('[data-cs=chart]').textContent.includes('Loading both character rosters')`), false);
    await evaluate(`connect('original-b','donor-a_1');go('request');waitFor(()=>saved.length===1)`);
    const body = await evaluate(`calls.find(c=>c.p.endsWith('/build-requests')&&c.b)?.b`);
    assert.deepEqual(body.mapping.cast_chart.connections, [
      { target_id: 'original-a', slot: 'fighter:a', character: '' },
      { target_id: 'original-b', slot: null, character: 'donor-a_1' },
      { target_id: 'original-c', slot: 'fighter:c', character: '' },
    ]);
    assert.equal(body.mapping.cast_chart.source, 'donor-a');
    assert.deepEqual(body.mapping.cast_chart.donors.map(d => d.slug), ['donor-a_1']);
    assert.deepEqual(body.mapping.assignments, [{ slot: 'fighter:a', character: '' }, { slot: 'fighter:c', character: '' }]);
    assert.match(body.description, /null slot.*requiring native slot discovery/);
    assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs')`), false);
    assert.match(await evaluate(`document.querySelector('[data-cs=request]').textContent`), /No playable build has been published/);
    if (process.env.GBOX_CAST_FLOW_EVIDENCE) {
      const directory = process.env.GBOX_CAST_FLOW_EVIDENCE; fs.mkdirSync(directory, { recursive: true });
      let result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      fs.writeFileSync(path.join(directory, 'wide.png'), Buffer.from(result.result.data, 'base64'));
      await send('Emulation.setDeviceMetricsOverride', { width: 660, height: 1000, deviceScaleFactor: 1, mobile: false });
      await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
      result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      fs.writeFileSync(path.join(directory, '660.png'), Buffer.from(result.result.data, 'base64'));
    }
    await evaluate(`panel.close()`);
  });
});

test('native review and build preserve every real slot and unchanged rows; later connections require a new review', { skip }, async () => {
  await page(async evaluate => {
    await evaluate(`native=true;openCast();ready();`);
    await evaluate(`connect('original-a','donor-a_2');connect('original-c','donor-a_0');go('plan');waitFor(()=>!document.querySelector('[data-cs-go=build]').disabled)`);
    const expected = [{ slot: 'fighter:a', character: 'donor-a_2' }, { slot: 'fighter:b', character: '' }, { slot: 'fighter:c', character: 'donor-a_0' }];
    assert.deepEqual(await evaluate(`calls.find(c=>c.p==='/api/cast_swap/plan').b.assignments`), expected);
    assert.equal(await evaluate(`[...document.querySelectorAll('[data-cs=plan] select, [data-cs=plan] input, [data-cs=plan] button')].every(control=>control.matches(':disabled'))`), true);
    assert.equal(await evaluate(`card('target','original-a').querySelector('[data-action=lock]').checked`), true);
    // Reviewing an unchanged diagram must not reset the manually locked choices.
    await evaluate(`document.querySelector('[data-action=pool-none]').click();card('donor','donor-a_1').querySelector('[data-action=pool]').click();document.querySelector('[data-action=shuffle]').click()`);
    assert.equal(await evaluate(`panel.controller.state.chartRows.find(r=>r.target_id==='original-a').character`), 'donor-a_2');
    assert.equal(await evaluate(`panel.controller.state.chartRows.find(r=>r.target_id==='original-c').character`), 'donor-a_0');
    await evaluate(`card('target','original-b').querySelector('[data-action=remove]').click()`);
    await evaluate(`connect('original-a','donor-a_1')`);
    assert.equal(await evaluate(`document.querySelector('[data-cs-go=build]').disabled`), true);
    assert.equal(await evaluate(`panel.controller.state.reviewedChart`), null);
    await evaluate.run(`connect('original-a','donor-a_2');go('plan');await waitFor(()=>!document.querySelector('[data-cs-go=build]').disabled);go('build');await waitFor(()=>lastJob!==null);`);
    assert.deepEqual(await evaluate(`lastJob.input.assignments`), expected);
    assert.equal(await evaluate(`lastJob.input.launch`), false);
    assert.equal(await evaluate(`lastJob.input.seed===document.querySelector('[data-seed]').value`), true);
    assert.equal(await evaluate(`document.querySelector('[data-cs=seed]').offsetParent===null`), true);
    assert.equal(await evaluate(`built[0].mod`), 'cast_fixture');
    await evaluate(`panel.close()`);
  });
});

test('catalog search selects an unextracted title without inventing a model or losing pending donor choices', { skip }, async () => {
  await page(async evaluate => {
    await evaluate.run(`const originalRoster=rosterFor;rosterFor=key=>key==='unextracted-game'?{...originalRoster(key),source:{key,label:'Unextracted game'},donors:[{id:'pending-character',slug:'pending-character',name:'Pending character',ready:false,reason:'No decoded model available',model_url:'',source_game_id:key}]}:originalRoster(key);openCast();await ready();
      const search=document.querySelector('[data-cs=title-search]');search.value='Unextracted';search.dispatchEvent(new Event('input',{bubbles:true}));await waitFor(()=>document.querySelector('[data-cs-title]'));`);
    await evaluate(`document.querySelector('[data-cs-title]').click();waitFor(()=>document.querySelector('[data-key=pending-character]'))`);
    assert.equal(await evaluate(`document.querySelector('[data-cs=source]').value`), 'unextracted-game');
    assert.equal(await evaluate(`card('donor','pending-character').querySelector('[data-action=inspect]').disabled`), true);
    assert.equal(await evaluate(`card('donor','pending-character').querySelectorAll('img').length`), 0);
    assert.match(await evaluate(`card('donor','pending-character').textContent`), /Needs extraction\/support/);
    await evaluate(`connect('original-a','pending-character');go('request');waitFor(()=>saved.length===1)`);
    assert.equal(await evaluate(`saved[0].mapping.cast_chart.connections[0].character`), 'pending-character');
    assert.equal(await evaluate(`saved[0].mapping.source_label`), 'Unextracted game');
    await evaluate(`panel.close()`);
  });
});

test('rapid source changes discard stale roster responses and close/reopen restores reviewed draft connections', { skip }, async () => {
  await page(async evaluate => {
    await evaluate.run(`openCast();await ready();connect('original-a','donor-a_1');document.querySelector('[data-seed]').value='reopen-seed';document.querySelector('[data-seed]').dispatchEvent(new Event('change',{bubbles:true}));card('donor','donor-a_2').querySelector('[data-action=pool]').click();pendingRoster['donor-b']=[];pendingRoster['donor-c']=[];chooseSource('donor-b');chooseSource('donor-c');await waitFor(()=>pendingRoster['donor-b'].length&&pendingRoster['donor-c'].length);`);
    await evaluate(`pendingRoster['donor-c'][0](rosterFor('donor-c'));waitFor(()=>document.querySelector('[data-key=donor-c_0]'))`);
    await evaluate(`pendingRoster['donor-b'][0](rosterFor('donor-b'));Promise.resolve()`);
    assert.equal(await evaluate(`document.querySelectorAll('[data-key=donor-b_0]').length`), 0);
    assert.equal(await evaluate(`panel.controller.state.roster.source.key`), 'donor-c');
    await evaluate(`panel.close();openCast();ready()`);
    assert.equal(await evaluate(`panel.controller.state.chartRows.find(r=>r.target_id==='original-a').character`), 'donor-a_1');
    assert.match(await evaluate(`card('target','original-a').querySelector('.cm-assignment').textContent`), /Replacement A 1/);
    assert.equal(await evaluate(`card('target','original-a').querySelector('[data-action=lock]').checked`), true);
    assert.equal(await evaluate(`document.querySelector('[data-seed]').value`), 'reopen-seed');
    assert.equal(await evaluate(`card('donor','donor-a_2').querySelector('[data-action=pool]').checked`), false);
    await evaluate.run(`pendingRoster['donor-b']=[];chooseSource('donor-b');await waitFor(()=>pendingRoster['donor-b'].length===1);panel.close();pendingRoster['donor-b'][0](rosterFor('donor-b'));await Promise.resolve();`);
    assert.equal(await evaluate(`document.querySelectorAll('#castdlg').length`), 0);
  });
});

test('actual 3D popup receives authenticated model/file URLs and a late viewer closes with its parent', { skip }, async () => {
  await page(async evaluate => {
    await evaluate.run(`window.viewerCalls=[];window.viewerDisposals=0;window.resolveViewer=null;
      io.inspect=o=>{inspected.push(o);return GBoxCharacterPopup.open(o,{document,api:io.api,url:u=>{if(!u.startsWith('/api/'))throw Error('Nonlocal asset URL');return 'https://gbox.invalid'+u+'?token=fixture-token';},loadViewer:async()=>({createCharacterViewer:async(stage,url,options)=>{viewerCalls.push({url,file:options.fileUrl('body texture.png')});return {dispose(){viewerDisposals++;}};}})});};
      openCast();await ready();card('donor','donor-a_0').querySelector('[data-action=inspect]').click();await waitFor(()=>viewerCalls.length===1);`);
    assert.deepEqual(await evaluate(`viewerCalls[0]`), { url: 'https://gbox.invalid/api/characters/donor-a_0/model?token=fixture-token', file: 'https://gbox.invalid/api/characters/donor-a_0/file/body%20texture.png?token=fixture-token' });
    assert.equal(await evaluate(`inspected[0].modelUrl`), '/api/characters/donor-a_0/model');
    await evaluate(`waitFor(()=>document.querySelector('[data-status]').textContent.includes('Model ready'))`);
    await evaluate(`panel.close();waitFor(()=>!document.querySelector('.cp-modal'))`);
    assert.equal(await evaluate(`viewerDisposals`), 1);
    await evaluate.run(`io.inspect=o=>GBoxCharacterPopup.open(o,{document,api:io.api,url:u=>u,loadViewer:()=>new Promise(r=>resolveViewer=r)});openCast();await ready();card('target','original-a').querySelector('[data-action=inspect]').click();await waitFor(()=>resolveViewer!==null);`);
    await evaluate(`panel.close();resolveViewer({createCharacterViewer:async()=>({dispose(){viewerDisposals++;}})});waitFor(()=>!document.querySelector('.cp-modal'))`);
    assert.equal(await evaluate(`document.querySelectorAll('#castdlg').length`), 0);
    assert.equal(await evaluate(`viewerDisposals`), 2);
  });
});

test('closing clears title-search and request-poll timers while an in-flight request stays saved', { skip }, async () => {
  await page(async (evaluate, send) => {
    await evaluate.run(`window.intervals=new Map();window.searches=new Map();window.timerSequence=50000;
      window.realClearTimeout=window.clearTimeout.bind(window);window.realClearInterval=window.clearInterval.bind(window);
      window.setInterval=(fn,ms)=>{const id=++timerSequence;intervals.set(id,{fn,ms});return id;};window.clearInterval=id=>{intervals.delete(id);realClearInterval(id);};
      window.setTimeout=(fn,ms,...args)=>{if(ms===250){const id=++timerSequence;searches.set(id,{fn,args});return id;}return originalTimeout(fn,ms,...args);};
      window.clearTimeout=id=>{searches.delete(id);realClearTimeout(id);};
      openCast();await ready();connect('original-a','donor-a_0');go('request');await waitFor(()=>saved.length===1);`);
    assert.equal(await evaluate(`intervals.size`), 1);
    await evaluate(`const search=document.querySelector('[data-cs=title-search]');search.value='Queued search';search.dispatchEvent(new Event('input',{bubbles:true}));panel.close()`);
    assert.equal(await evaluate(`intervals.size`), 0);
    assert.equal(await evaluate(`searches.size`), 0);
    assert.equal(await evaluate(`calls.some(c=>c.p.startsWith('/api/home/games?'))`), false);
    // A saved request is separate from its UI. Closing during POST cannot cancel or duplicate it.
    await evaluate.run(`memory.clear();openCast();await ready();connect('original-b','donor-a_2');pendingSave=[];go('request');await waitFor(()=>pendingSave.length===1);`);
    assert.equal(await evaluate(`document.querySelector('[data-cs=chart]').inert`), true);
    assert.equal(await evaluate(`[...document.querySelectorAll('[data-cs=source],[data-cs=mapping],[data-cs=slots],[data-cs=title-search]')].every(control=>control.disabled)`), true);
    const point = await evaluate(`(()=>{const r=card('donor','donor-a_0').querySelector('.cm-main').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
    assert.equal(await evaluate(`panel.controller.state.chartRows.find(r=>r.target_id==='original-b').character`), 'donor-a_2');
    await evaluate.run(`panel.close();pendingSave[0]();await waitFor(()=>saved.length===2);`);
    assert.equal(await evaluate(`document.querySelectorAll('#castdlg').length`), 0);
    assert.equal(await evaluate(`intervals.size`), 0);
    assert.equal(await evaluate(`saved[1].mapping.cast_chart.connections.find(r=>r.target_id==='original-b').character`), 'donor-a_2');
  });
});

test('opening another cast dialog disposes the previous dialog instead of orphaning its work', { skip }, async () => {
  await page(async evaluate => {
    await evaluate.run(`window.oldPopupCloses=0;io.inspect=async()=>({close(){oldPopupCloses++;}});openCast();await ready();connect('original-a','donor-a_2');card('donor','donor-a_0').querySelector('[data-action=inspect]').click();await Promise.resolve();window.firstPanel=panel;openCast();await ready();`);
    assert.equal(await evaluate(`oldPopupCloses`), 1);
    assert.equal(await evaluate(`document.querySelectorAll('#castdlg').length`), 1);
    assert.equal(await evaluate(`panel.controller.state.chartRows[0].character`), 'donor-a_2');
    await evaluate(`panel.close()`);
  });
});

test('closing a native queued build stops UI polling while retaining the submitted job', { skip }, async () => {
  await page(async evaluate => {
    await evaluate.run(`native=true;window.releaseDelay=null;const originalApi=api;
      api=async(p,b)=>{if(p==='/api/jobs'){calls.push({p,b:structuredClone(b)});lastJob=b;return {id:'queued-native-job',state:'queued'};}return originalApi(p,b);};
      io.delay=()=>new Promise(r=>releaseDelay=r);openCast();await ready();connect('original-a','donor-a_2');connect('original-c','donor-a_0');go('plan');await waitFor(()=>!document.querySelector('[data-cs-go=build]').disabled);go('build');await waitFor(()=>releaseDelay!==null);panel.close();releaseDelay();await Promise.resolve();await Promise.resolve();`);
    assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/jobs').length`), 1);
    assert.equal(await evaluate(`calls.some(c=>c.p.includes('queued-native-job'))`), false);
    assert.equal(await evaluate(`calls.some(c=>/cancel|abort|stop/.test(c.p))`), false);
    assert.equal(await evaluate(`document.querySelectorAll('#castdlg').length`), 0);
  });
});

test('one visible chart seed is saved exactly, and explicit Clear in random mode stays unchanged on Review', { skip }, async () => {
  await page(async evaluate => {
    await evaluate(`openCast();ready()`);
    await evaluate(`document.querySelector('[data-action=shuffle]').click()`);
    const seed = await evaluate(`document.querySelector('[data-seed]').value`);
    assert.ok(seed.length > 0);
    assert.equal(await evaluate(`document.querySelector('[data-cs=seed]').offsetParent===null`), true);
    await evaluate(`go('request');waitFor(()=>saved.length===1)`);
    assert.equal(await evaluate(`saved[0].mapping.seed`), seed);
    await evaluate(`document.querySelector('[data-cs=mapping]').value='random';document.querySelector('[data-cs=mapping]').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('[data-action=clear]').click();go('plan');waitFor(()=>calls.some(c=>c.p==='/api/cast_swap/plan'))`);
    assert.equal(await evaluate(`panel.controller.state.chartRows.every(row=>row.character==='')`), true);
    assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/cast_swap/plan').at(-1).b.assignments.every(row=>row.character==='')`), true);
    assert.equal(await evaluate(`calls.filter(c=>c.p==='/api/cast_swap/plan').at(-1).b.seed`), seed);
    await evaluate(`panel.close()`);
  });
});

test('a planner that changes the reviewed native connections cannot submit a native build', { skip }, async () => {
  await page(async evaluate => {
    await evaluate.run(`native=true;const originalApi=api;api=async(p,b)=>{const result=await originalApi(p,b);return p==='/api/cast_swap/plan'?{...result,assignments:[{slot:'fighter:a',character:'donor-a_0'},{slot:'fighter:b',character:''}]}:result;};openCast();await ready();connect('original-a','donor-a_2');connect('original-c','donor-a_0');go('plan');await waitFor(()=>panel.controller.state.plan!==null);`);
    assert.equal(await evaluate(`document.querySelector('[data-cs-go=build]').disabled`), true);
    assert.equal(await evaluate(`document.querySelector('[data-cs-go=request]').hidden`), false);
    assert.equal(await evaluate(`panel.controller.state.chartRows.find(r=>r.target_id==='original-a').character`), 'donor-a_2');
    assert.equal(await evaluate(`panel.controller.state.chartRows.find(r=>r.target_id==='original-c').character`), 'donor-a_0');
    await evaluate(`go('request');waitFor(()=>saved.length===1)`);
    assert.deepEqual(await evaluate(`saved[0].mapping.assignments`), [{ slot: 'fighter:a', character: 'donor-a_2' }, { slot: 'fighter:b', character: '' }, { slot: 'fighter:c', character: 'donor-a_0' }]);
    assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs')`), false);
    await evaluate(`panel.close()`);
  });
});
