const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/memory-cards.js'),'utf8');
const wait=`window.waitFor=async f=>{for(let n=0;n<500;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('memory-card UI timeout')};`;

test('VMU manager shows full cards, creates a PSO default, and explicitly selects its exact card and slot',async()=>{
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:1100,height:1000,deviceScaleFactor:1,mobile:false});
    await evaluate(source);
    await evaluate(wait+`window.calls=[];window.selection={};window.cards=[
      {id:'old',name:'Existing VMU',revision:3,capacity:{free_blocks:5,total_blocks:200,files:[{name:'PSO character',blocks:110}]}},
      {id:'leased',name:'Other PC card',revision:2,capacity:{free_blocks:120,total_blocks:200},lease:{session_id:'other',worker_id:'i9'}}];
      window.state={supported:true,live_switch:false,reason:'This core selects cards on the next game launch.',slots:[{slot:'A1',card_id:'old',name:'Existing VMU',revision:3,sync_state:'synced',capacity:cards[0].capacity},{slot:'A2'}]};
      window.io={api:async(p,b)=>{calls.push({p,b});if(p.startsWith('/api/memory-cards?'))return {cards,selection};
        if(p==='/api/memory-cards'){const card={id:'pso',name:b.name,revision:1,capacity:{free_blocks:200,total_blocks:200}};cards.push(card);if(b.game_id)selection.A1=card.id;return card;}
        if(b?.args?.input.op==='select'){state={...state,message:'Card selected for next launch. Your current card remains inserted.',slots:[{...state.slots[0],pending_card_id:b.args.input.card_id},state.slots[1]]};return state;}return state;}};
      window.panel=GBoxMemoryCards.open({sid:'pinned-session',game_id:'pso-disc',platform:'Sega Dreamcast',title:'Phantasy Star Online Ver. 2'},io);
      waitFor(()=>document.querySelectorAll('[data-insert]').length===2&&document.querySelector('[data-connection]').textContent.includes('next game launch'));`);
    assert.match(await evaluate(`document.querySelector('[data-slots]').textContent`),/5 \/ 200 blocks free/);
    assert.match(await evaluate(`document.querySelector('[data-slots]').textContent`),/PSO needs 30 free blocks/);
    assert.equal(await evaluate(`document.querySelector('[data-insert=leased]').disabled`),true);
    await evaluate(`document.querySelector('[data-pso]').click();waitFor(()=>document.querySelector('[data-insert=pso]'));`);
    const creation=await evaluate(`calls.find(c=>c.p==='/api/memory-cards').b`);
    assert.deepEqual(creation,{name:'PSO · Dreamcast',platform:'dreamcast',game_id:'pso-disc',clone_from:'old'});
    assert.match(await evaluate(`document.querySelector('[data-pso-note]').textContent`),/last synced revision/);
    assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='select').length`),0,'creating a default never silently swaps the live card');
    assert.match(await evaluate(`document.querySelector('[data-slots]').textContent`),/Selected for next launch: PSO/,'game defaults from Spark appear before a select RPC');
    await evaluate(`panel.close();waitFor(()=>!document.querySelector('dialog'));`);
    await evaluate(`panel=GBoxMemoryCards.open({sid:'pinned-session',game_id:'pso-disc',platform:'Sega Dreamcast',title:'Phantasy Star Online Ver. 2'},io);waitFor(()=>document.querySelector('[data-slots]').textContent.includes('Selected for next launch: PSO')&&!document.querySelector('[data-insert=pso]').disabled);`);
    assert.equal(await evaluate(`document.querySelector('[data-insert=pso]').textContent`),'Selected for next launch','reopening retains the Spark card selection');
    await evaluate(`document.querySelector('[data-insert=pso]').click();waitFor(()=>document.querySelector('[data-operation]').textContent.includes('next launch'));`);
    const command=await evaluate(`calls.find(c=>c.b?.args?.input.op==='select')`);
    assert.equal(command.p,'/api/sessions/pinned-session/rpc');assert.equal(command.b.op,'memory_cards');
    assert.deepEqual(command.b.args.input,{op:'select',slot:'A1',card_id:'pso'});
    assert.match(command.b.args.command_id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.ok(command.b.args.expires>Date.now()/1000-2&&command.b.args.expires<Date.now()/1000+10);
    assert.match(await evaluate(`document.querySelector('[data-slots]').textContent`),/Selected for next launch: PSO/);
    assert.deepEqual(await evaluate(`Array.from(document.querySelector('[data-slot]').options,o=>o.value)`),['A1','A2','B1','B2','C1','C2','D1','D2']);
    await evaluate(`document.querySelector('[data-slot]').value='D2';document.querySelector('[data-slot]').dispatchEvent(new Event('change'));document.querySelector('[data-insert=pso]').click();waitFor(()=>calls.filter(c=>c.b?.args?.input.op==='select').length===2);`);
    assert.deepEqual(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='select').at(-1).b.args.input`),{op:'select',slot:'D2',card_id:'pso'},'a valid empty VMU slot can receive a card');
    assert.equal(await evaluate(`calls.some(c=>JSON.stringify(c.b||{}).match(/delete|format/))`),false);
    await evaluate('panel.close();waitFor(()=>!document.querySelector("dialog"));');
  });
});

test('an unresponsive emulator cannot block named card creation but cannot enable card insertion',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+`window.calls=[];const originalTimeout=window.setTimeout;window.setTimeout=(f,ms,...rest)=>originalTimeout(f,ms===12000?100:ms,...rest);
      window.cards=[];window.io={api:async(p,b)=>{calls.push({p,b});if(p.startsWith('/api/memory-cards?'))return {cards};
        if(p==='/api/memory-cards'){const card={id:'named',name:b.name,revision:1,capacity:{free_blocks:127,total_blocks:127}};cards.push(card);return {card};}
        return new Promise(()=>{});}};
      window.panel=GBoxMemoryCards.open({sid:'running',game_id:'disc',platform:'GameCube',title:'Other game'},io);
      document.querySelector('[name=card_name]').value='My second card';document.querySelector('form').requestSubmit();
      waitFor(()=>document.querySelector('[data-insert=named]'));`);
    assert.deepEqual(await evaluate(`calls.find(c=>c.p==='/api/memory-cards').b`),{name:'My second card',platform:'gamecube'});
    assert.equal(await evaluate(`document.querySelector('[data-pso]')===null`),true);
    await evaluate(`waitFor(()=>document.querySelector('[data-connection]').textContent.includes('outcome may be unknown'));`);
    assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='status').length`),1);
    assert.equal(await evaluate(`document.querySelector('[data-create]').disabled`),false);
    assert.equal(await evaluate(`document.querySelector('[data-insert=named]').disabled`),true);
    assert.equal(await evaluate(`document.querySelector('[data-sync]').disabled`),true);
    await evaluate(`document.querySelector('[data-insert=named]').click();`);
    assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='select').length`),0);
    await evaluate('panel.close();waitFor(()=>!document.querySelector("dialog"));');
  });
});

test('sync conflicts remain visible, server text is escaped, and closing does not cancel or revive an operation',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+`window.calls=[];window.resolveSync=null;window.unsafe=0;
      const card={id:'local',name:'<img src=x onerror="unsafe++">',revision:8,capacity:{free_blocks:20,total_blocks:200,files:[{name:'<script>unsafe++</script>',blocks:100}]},lease:{owner:'pinned'}};
      window.state={supported:true,live_switch:true,slots:[{slot:'A',card_id:'local',name:card.name,revision:8,sync_state:'conflict',capacity:card.capacity,error:'Local changes retained. Spark has a newer revision.'}]};
      window.io={api:async(p,b)=>{calls.push({p,b});if(p.startsWith('/api/memory-cards?'))return {cards:[card]};
        if(b.args.input.op==='sync')return new Promise(resolve=>{resolveSync=resolve;});return state;}};
      window.panel=GBoxMemoryCards.open({sid:'pinned',game_id:'pso',platform:'Nintendo GameCube',title:'Phantasy Star Online'},io);
      waitFor(()=>!document.querySelector('[data-sync]').disabled);`);
    assert.equal(await evaluate('unsafe'),0);assert.equal(await evaluate(`document.querySelectorAll('#memory-card-manager img,#memory-card-manager script').length`),0);
    assert.match(await evaluate(`document.querySelector('[data-slots]').textContent`),/Local changes retained/);
    assert.deepEqual(await evaluate(`Array.from(document.querySelector('[data-slot]').options,o=>o.value)`),['A','B'],'both GameCube slots remain available when only A is inserted');
    assert.equal(await evaluate(`document.querySelector('[data-insert=local]').disabled`),false,'the lease owner alias identifies this session');
    await evaluate(`document.querySelector('[data-sync]').click();waitFor(()=>resolveSync!==null);panel.close();waitFor(()=>!document.querySelector('dialog'));resolveSync({...state,message:'Sync conflict. Your local save was preserved.'});`);
    assert.equal(await evaluate(`calls.filter(c=>c.b?.args?.input.op==='sync').length`),1);
    assert.deepEqual(await evaluate(`calls.find(c=>c.b?.args?.input.op==='sync').b.args.input`),{op:'sync',slot:'A'});
    assert.equal(await evaluate(`document.querySelector('dialog')===null`),true);
  });
});
