const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('game build dialog pins requests, retains uncertain IDs, and exposes only actual completed builds',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:1000,deviceScaleFactor:1,mobile:false});
  for(const file of ['sprite-face-editor.js','game-build-request.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`window.calls=[];window.items=[];window.fail=true;window.waitFor=async f=>{for(let n=0;n<500;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('build request timeout')};
   window.io={api:async(p,b)=>{calls.push({p,b});if(p.includes('sprite-faces'))throw Error('unsupported fixture');
    if(b){if(fail){fail=false;throw Error('network response lost');}items=[{id:'r',number:7,description:b.description,status:'open',jobs:[]}];return {id:'r',number:7};}return {items};},
    play:async(g,n)=>calls.push({play:[g,n]}),download:async(g,n)=>calls.push({download:[g,n]})};
   window.panel=GBoxGameBuildRequest.open({game_id:'pinned',title:'Pinned Game',session_id:'pinned-session',mod:'base-build'},io);
   document.querySelector('textarea').value='Create a build with my requested character';document.querySelector('form').requestSubmit();waitFor(()=>document.querySelector('[data-status]').textContent.includes('Retry uses'));`);
  const first=await evaluate(`calls.find(c=>c.b?.client_id).b`);assert.equal(first.session_id,'pinned-session');
  await evaluate(`document.querySelector('form').requestSubmit();waitFor(()=>document.querySelector('[data-status]').textContent.includes('#7'));`);
  assert.equal(await evaluate(`calls.filter(c=>c.b?.client_id).at(-1).b.client_id`),first.client_id);
  assert.equal(await evaluate(`document.querySelector('[data-play]')===null`),true);
  await evaluate(`items[0].build={name:'actual-build',verified:false};panel.close();panel=GBoxGameBuildRequest.open({game_id:'pinned',title:'Pinned Game',session_id:'pinned-session'},io);waitFor(()=>document.querySelector('[data-download]'));`);
  await evaluate(`document.querySelector('[data-download]').click();waitFor(()=>calls.some(c=>c.download));`);
  assert.deepEqual(await evaluate('calls.find(c=>c.download).download'),['pinned','actual-build']);
  await evaluate(`panel.close();waitFor(()=>document.querySelector('dialog')===null);`);assert.equal(await evaluate(`document.querySelector('dialog')===null`),true);
 });
});

test('photo sprite editor uploads original pixels, previews native mapping, and invalidates changed masks',async()=>{
 await withPage(async(evaluate,send)=>{
  for(const file of ['sprite-face-editor.js','game-build-request.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`window.calls=[];window.waitFor=async f=>{for(let n=0;n<500;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('photo UI timeout')};
   const c=document.createElement('canvas');c.width=16;c.height=32;c.getContext('2d').fillRect(0,0,16,32);window.picture=c.toDataURL();
   window.io={api:async(p,b)=>{calls.push({p,b});if(p==='/api/photo-skins/photos')return {photo:'a'.repeat(64)};
    if(p.endsWith('/preview'))return {id:'b'.repeat(32),before:picture,after:picture,report:{changed_pixels:20,shared_pixels_preserved:3}};
    if(p.includes('sprite-faces'))return {frame:0,count:26,image:picture,rect:[.2,.1,.8,.4]};
    if(b)return {id:'r',number:8};return {items:[]};}};
   window.panel=GBoxGameBuildRequest.open({game_id:'49b6a2f65aca26a2',title:'Mario',session_id:'s'},io);
   waitFor(()=>document.querySelector('[data-frame]').options.length===26);`);
  await evaluate(`document.querySelector('[data-face-editor] details').open=true;
   const bytes=Uint8Array.from(atob(picture.split(',')[1]),c=>c.charCodeAt(0));const transfer=new DataTransfer();transfer.items.add(new File([bytes],'face.png',{type:'image/png'}));
   const file=document.querySelector('[data-photo]');file.files=transfer.files;file.dispatchEvent(new Event('change'));
   waitFor(()=>!document.querySelector('[data-preview]').disabled);`);
  await evaluate(`document.querySelector('[data-preview]').click();waitFor(()=>!document.querySelector('[data-results]').hidden);`);
  assert.equal(await evaluate(`calls.find(c=>c.p.endsWith('/preview')).b.mapping.flip`),true);
  await evaluate(`document.querySelector('[name=recipe]').value='photo_face';document.querySelector('textarea').value='Map this original photo onto Mario';
   document.querySelector('form').requestSubmit();waitFor(()=>calls.some(c=>c.b?.recipe==='photo_face'));`);
  const body=await evaluate(`calls.find(c=>c.b?.recipe==='photo_face').b`);assert.equal(body.photo,'a'.repeat(64));assert.equal(body.mapping.candidate,'b'.repeat(32));
  await evaluate(`const opacity=document.querySelector('[data-opacity]');opacity.value=80;opacity.dispatchEvent(new Event('input',{bubbles:true}));
   document.querySelector('textarea').value='Changed mask';document.querySelector('form').requestSubmit();`);
  assert.equal(await evaluate(`calls.filter(c=>c.b?.recipe==='photo_face').length`),1);
  await evaluate(`panel.close();`);
 });
});

test('live edits coalesce, reject stale previews, retain layers, and distinguish the N64 boot target',async()=>{
 await withPage(async(evaluate,send)=>{
  for(const file of ['sprite-face-editor.js','game-build-request.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`const saved=new Map();Object.defineProperty(window,'localStorage',{value:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)}});
   window.calls=[];window.releases=[];window.waitFor=async f=>{for(let n=0;n<500;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('live edit timeout')};
   const c=document.createElement('canvas');c.width=32;c.height=64;window.picture=c.toDataURL();
   window.io={api:async(p,b)=>{calls.push({p,b});if(p==='/api/photo-skins/photos')return {photo:'a'.repeat(64)};
    if(p.endsWith('/preview'))return new Promise(resolve=>releases.push(()=>resolve({id:'b'.repeat(32),before:picture,after:picture,report:{changed_pixels:12,shared_pixels_preserved:0}})));
    if(p.includes('sprite-faces'))return {frame:0,count:1,image:picture,rect:[.1,.1,.9,.9]};if(b)return {id:'r',number:9};return {items:[]};}};
   window.panel=GBoxGameBuildRequest.open({game_id:'b7aecee966090bfa',title:'Mario 64'},io);waitFor(()=>document.querySelector('[data-frame]').options.length===1);`);
  assert.equal(await evaluate(`calls.find(c=>c.p.includes('sprite-faces')).p.endsWith('frame=0')`),true);
  await evaluate(`document.querySelector('details').open=true;const bytes=Uint8Array.from(atob(picture.split(',')[1]),c=>c.charCodeAt(0));const t=new DataTransfer();t.items.add(new File([bytes],'face.png',{type:'image/png'}));const file=document.querySelector('[data-photo]');file.files=t.files;file.dispatchEvent(new Event('change'));waitFor(()=>releases.length===1);`);
  await evaluate(`document.querySelector('[data-add-layer]').click();const x=document.querySelector('[data-layer-rotation]');for(let v=1;v<=20;v++){x.value=v;x.dispatchEvent(new Event('input',{bubbles:true}));}releases.shift()();waitFor(()=>releases.length===1);`);
  assert.equal(await evaluate(`document.querySelector('[data-results]').hidden`),true,'stale first response is not accepted');
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/preview')).length`),2);
  assert.equal(await evaluate(`calls.filter(c=>c.p.endsWith('/preview')).at(-1).b.mapping.layers[1].rotation`),20);
  await evaluate(`releases.shift()();waitFor(()=>!document.querySelector('[data-results]').hidden);document.querySelector('[name=recipe]').value='photo_face';document.querySelector('[name=projection_scope]').value='both';document.querySelector('textarea').value='Both faces';document.querySelector('form').requestSubmit();`);
  assert.equal(await evaluate(`calls.some(c=>c.b?.client_id)`),false);
  assert.match(await evaluate(`document.querySelector('[data-status]').textContent`),/boot-screen/);
  await evaluate(`panel.close();waitFor(()=>document.querySelector('dialog')===null);panel=GBoxGameBuildRequest.open({game_id:'b7aecee966090bfa',title:'Mario 64'},io);`);
  assert.equal(await evaluate(`document.querySelector('[data-layer]').options.length`),2);
  await evaluate('panel.close()');
 });
});

test('one-to-one animation editor keeps source crop, group transforms, layer toggles and exact build snapshot',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1200,height:1100,deviceScaleFactor:1,mobile:false});
  for(const file of ['sprite-pair-editor.js','game-build-request.js'])await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz',file),'utf8'));
  await evaluate(`const saved=new Map();Object.defineProperty(window,'localStorage',{value:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)}});
   window.calls=[];window.waitFor=async f=>{for(let n=0;n<500;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('sprite pair timeout')};
   const c=document.createElement('canvas');c.width=16;c.height=32;const ctx=c.getContext('2d');ctx.fillStyle='blue';ctx.fillRect(4,8,8,24);window.picture=c.toDataURL();
   const template={game_id:'49b6a2f65aca26a2',target_top:Array(26).fill(0),groups:[{name:'Big Mario run',rows:[0,1,2]}],target_frames:Array(26).fill(picture),default_sources:Array(26).fill(picture),
    donor:{animation:'walk',clips:['walk','run'],frames:Array(4).fill(picture),timing:[100,100,100,100]}};
   window.io={api:async(p,b)=>{calls.push({p,b});if(p.includes('sprite-pairs')&&!p.endsWith('/preview'))return template;
    if(p.endsWith('/preview'))return {id:'c'.repeat(32),frames:Array(26).fill(picture),report:{tiles_used:70,tile_budget:91}};
    if(b)return {id:'r',number:10};return {items:[]};}};
   window.panel=GBoxGameBuildRequest.open({game_id:'49b6a2f65aca26a2',title:'Mario',session_id:'native-session'},io);
   document.querySelector('[data-pair-open]').click();waitFor(()=>document.querySelector('#sprite-pair-editor [data-use]')?.disabled===false);`);
  await evaluate(`const editor=document.querySelector('#sprite-pair-editor');editor.querySelector('[data-animate]').checked=false;const scale=editor.querySelector('[data-transform=scale]');scale.value=1.25;scale.dispatchEvent(new Event('input',{bubbles:true}));waitFor(()=>calls.filter(c=>c.p.endsWith('/preview')).at(-1)?.b.profile.frames['0']?.scale===1.25);`);
  const changed=await evaluate(`calls.filter(c=>c.p.endsWith('/preview')).at(-1).b.profile.frames`);
  assert.deepEqual(Object.keys(changed),['0','1','2']);assert.equal(changed['2'].scale,1.25);
  await evaluate(`document.querySelector('#sprite-pair-editor [data-toggle]').click();`);
  assert.equal(await evaluate(`document.querySelector('#sprite-pair-editor [data-layer=result]').checked`),true);
  await evaluate(`document.querySelector('#sprite-pair-editor [data-build]').click();waitFor(()=>calls.some(c=>c.b?.recipe==='sonic2_player'));`);
  const request=await evaluate(`calls.find(c=>c.b?.recipe==='sonic2_player').b`);assert.equal(request.mapping.candidate,'c'.repeat(32));assert.equal(request.session_id,'native-session');
  await evaluate(`panel.close();`);
 });
});
