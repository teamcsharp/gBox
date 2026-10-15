'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http'), zlib = require('node:zlib');
const {withPage} = require('../scripts/browser_lifecycle.cjs');
const web = path.resolve(__dirname, '../clients/web');
function png(rgba, width = 64, height = 64) {
  const crc = bytes => { let value = -1; for (const byte of bytes) { value ^= byte; for (let n = 0; n < 8; n++) value = value >>> 1 ^ (value & 1 ? 0xedb88320 : 0); } return (value ^ -1) >>> 0; };
  const chunk = (type, data) => { const name = Buffer.from(type), size = Buffer.alloc(4), checksum = Buffer.alloc(4); size.writeUInt32BE(data.length); checksum.writeUInt32BE(crc(Buffer.concat([name, data]))); return Buffer.concat([size, name, data, checksum]); };
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 6;
  const pixels = Buffer.alloc(height * (width * 4 + 1));
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) for (let channel = 0; channel < 4; channel++) pixels[y * (width * 4 + 1) + 1 + x * 4 + channel] = rgba[channel];
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]);
}
async function fixture(fn) {
  const calls = [], sessions = new Map(), images = new Map(), hold = {revision: false, release: null};
  const first = 'a'.repeat(32), second = 'b'.repeat(32), source = 'c'.repeat(64);
  images.set('/image/0.png', png([32, 64, 224, 255])); images.set('/image/1.png', png([32, 192, 64, 255]));
  function session(index) { const id = index === 0 ? first : second; if (!sessions.has(id)) sessions.set(id, {id, character: 'fixture_person', image: index, width: 64, height: 64, label: index ? 'Clothing' : 'Face', revision: 0, source_sha256: source, material_indices: [index], model_url: '/model-snapshot', current_url: '/image/' + index + '.png', original_url: '/image/' + index + '.png'}); return sessions.get(id); }
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname === '/fixture-frame') {
      res.writeHead(200, {'content-type': 'text/html'});
      res.end(`<script>const nonce=new URLSearchParams(location.hash.slice(1)).get('bridge');window.received=[];parent.postMessage({type:'gbox-photocraft-ready',nonce},location.origin);addEventListener('message',e=>{if(e.data.type==='gbox-photocraft-open')received.push({name:e.data.name,mime:e.data.mime,size:e.data.bytes.byteLength});if(e.data.type==='fixture-export'){const m=e.data;parent.postMessage({type:'gbox-photocraft-export',nonce:m.nonce||nonce,name:m.name,mime:m.mime,bytes:m.bytes},location.origin,[m.bytes]);}});</script>`); return;
    }
    if (images.has(url.pathname)) { res.writeHead(200, {'content-type': 'image/png'}); res.end(images.get(url.pathname)); return; }
    if (url.pathname.startsWith('/api/')) {
      let raw = ''; for await (const piece of req) raw += piece;
      const body = raw ? JSON.parse(raw) : undefined; calls.push({path: url.pathname, method: req.method, body});
      let result;
      if (url.pathname === '/api/photocraft/status') result = {ready: true, version: '0.9.0'};
      else if (url.pathname === '/api/characters/fixture_person') result = {slug: 'fixture_person', name: 'Fixture person', model: 'model.glb', source: {game_title: 'Source title'}};
      else if (url.pathname.endsWith('/photocraft/maps')) result = {source_sha256: source, maps: [{index: 0, label: 'Face', width: 64, height: 64, material_indices: [0]}, {index: 1, label: 'Clothing', width: 64, height: 64, material_indices: [1]}]};
      else if (url.pathname === '/api/photocraft/sessions' && req.method === 'POST') result = session(body.image || 0);
      else if (/\/revisions$/.test(url.pathname)) {
        const id = url.pathname.split('/')[4], original = sessions.get(id);
        if (body.expected_revision !== original.revision) { res.writeHead(409, {'content-type': 'application/json'}); res.end(JSON.stringify({detail: 'Revision conflict'})); return; }
        const revision = original.revision + 1, current_url = '/revision/' + id + '-' + revision + '.png';
        images.set(current_url, Buffer.from(body.png_data_url.split(',')[1], 'base64'));
        result = {...original, revision, current_url, ...(body.project_data_url ? {project_url: '/project/' + id, project_format: body.project_format} : {})}; sessions.set(id, result);
        if (hold.revision) await new Promise(resolve => { hold.release = resolve; });
      } else if (url.pathname === '/api/photocraft/donors') result = {variant: 'fixture_person_painted', name: 'Painted fixture person', notice: 'Separate donor created'};
      else if (/\/api\/photocraft\/sessions\/[a-f0-9]{32}$/.test(url.pathname)) result = sessions.get(url.pathname.split('/')[4]);
      else result = {};
      res.writeHead(200, {'content-type': 'application/json'}); res.end(JSON.stringify(result)); return;
    }
    if (url.pathname === '/') { res.writeHead(200, {'content-type': 'text/html'}); res.end('<!doctype html><html><head><title>PhotoCraft popup test fixture</title><script src="/viz/model-texture-paint.js"></script><script src="/viz/photocraft-popup.js"></script></head><body style="margin:0;background:#10141d"></body></html>'); return; }
    const file = path.resolve(web, '.' + url.pathname);
    if (!file.startsWith(web + path.sep) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, {'content-type': 'text/javascript'}); res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    await withPage(async (evaluate, send) => {
      await send('Emulation.setDeviceMetricsOverride', {width: 1500, height: 1000, deviceScaleFactor: 1, mobile: false});
      await send('Page.navigate', {url: 'http://127.0.0.1:' + server.address().port + '/'});
      await evaluate(`(async()=>{for(let i=0;i<300&&!window.GBoxPhotoCraft;i++)await new Promise(r=>setTimeout(r,10));if(!window.GBoxPhotoCraft)throw Error('Popup scripts did not load');})()`);
      await evaluate(`window.waitFor=async predicate=>{for(let i=0;i<500;i++){if(predicate())return;await new Promise(r=>setTimeout(r,10));}throw Error('Popup fixture timeout');};
        window.makeImage=color=>{const c=document.createElement('canvas');c.width=c.height=64;c.getContext('2d').fillStyle=color;c.getContext('2d').fillRect(0,0,64,64);return c;};
        window.viewers=[];window.mapping=[];window.donors=[];window.confirms=[];
        window.io={frameURL:location.origin+'/fixture-frame',url:p=>p,confirm:text=>{confirms.push(text);return true},
          api:async(p,b)=>{const r=await fetch(p,{method:b===undefined?'GET':'POST',headers:{'content-type':'application/json'},...(b===undefined?{}:{body:JSON.stringify(b)})});if(!r.ok)throw Error('HTTP '+r.status);return r.json()},
          onDonor:value=>donors.push(value),mapDonor:value=>mapping.push(value),
          loadViewer:async()=>({createCharacterViewer:async()=>{const face={uuid:'face',name:'face',map:{image:makeImage('#2040e0'),flipY:false}},body={uuid:'body',name:'body',map:{image:makeImage('#20c040'),flipY:false}};
            const vector=()=>({copy(){return this}});const value={face,body,paintMaterialIds:true,disposed:false,THREE:{CanvasTexture:class{constructor(image){this.image=image;this.repeat=vector();this.offset=vector();this.center=vector()}dispose(){}updateMatrix(){}}},
              gltf:{parser:{getDependency:async(type,index)=>[face,body][index]},scene:{traverse:fn=>fn({isMesh:true,material:[face,body]})}},paint:handler=>value.paintHandler=handler,uvLines:()=>[],dispose(){this.disposed=true}};viewers.push(value);return value}})};
        window.q=name=>document.querySelector('[data-pc-'+name+']');window.pixel=(which='face')=>[...viewers.at(-1)[which].map.image.getContext('2d').getImageData(32,32,1,1).data];
        window.frame=()=>q('editor')?.querySelector('iframe');window.activeName=()=>frame()?.contentWindow.received?.at(-1)?.name;
        window.exportImage=async(name,color,mime='image/png',nonce)=>{const bytes=mime==='image/png'?await(await fetch(makeImage(color).toDataURL())).arrayBuffer():new TextEncoder().encode(color).buffer;frame().contentWindow.postMessage({type:'fixture-export',name,mime,nonce,bytes},location.origin,[bytes]);};
        window.openPopup=async()=>{window.panel=GBoxPhotoCraft.open({character:'fixture_person',name:'Test character'},io);await panel.ready;await waitFor(()=>!!activeName()&&!!document.querySelector('[data-mtp-canvas]')&&!q('load-map').disabled);};
        window.openMap=async index=>{q('map').value=String(index);q('load-map').click();await waitFor(()=>viewers.at(-1)&&!viewers.at(-1).disposed&&activeName()?.includes(index?'${second}':'${first}')&&!q('load-map').disabled);};
        window.sendExport=async(color,name=activeName())=>{await exportImage(name,color);await waitFor(()=>q('saved').textContent.includes('Unsaved'));};`);
      await fn({evaluate, send, calls, sessions, hold, first, second});
      await evaluate(`panel?.dispose()`);
    });
  } finally { hold.release?.(); await new Promise(resolve => server.close(resolve)); }
}

test('popup rejects unrelated frame messages and only explicitly saves native-size exported texture revisions', async () => {
  await fixture(async ({evaluate, calls, first}) => {
    await evaluate('openPopup()');
    assert.deepEqual(await evaluate('pixel()'), [32, 64, 224, 255]);
    await evaluate(`(async()=>{const c=makeImage('red');c.width=32;const bytes=await(await fetch(c.toDataURL())).arrayBuffer();frame().contentWindow.postMessage({type:'fixture-export',name:activeName(),mime:'image/png',bytes},location.origin,[bytes]);await waitFor(()=>q('status').textContent.includes('requires'));})()`);
    assert.deepEqual(await evaluate('pixel()'), [32, 64, 224, 255], 'a resized PhotoCraft canvas cannot silently replace native texture dimensions');
    await evaluate('panel.save()');
    assert.equal(calls.filter(call => call.path.endsWith('/revisions')).length, 0, 'initial preview is not an edit');
    await evaluate(`(async()=>{const bytes=await(await fetch(makeImage('red').toDataURL())).arrayBuffer(),nonce=new URLSearchParams(frame().contentWindow.location.hash.slice(1)).get('bridge');
      dispatchEvent(new MessageEvent('message',{source:frame().contentWindow,origin:'https://unrelated.invalid',data:{type:'gbox-photocraft-export',nonce,name:activeName(),mime:'image/png',bytes}}));
      dispatchEvent(new MessageEvent('message',{source:window,origin:location.origin,data:{type:'gbox-photocraft-export',nonce,name:activeName(),mime:'image/png',bytes}}));
      await exportImage(activeName(),'red','image/png','wrong_nonce');await new Promise(r=>setTimeout(r,50));})()`);
    assert.deepEqual(await evaluate('pixel()'), [32, 64, 224, 255]);
    await evaluate(`sendExport('red');`);
    assert.deepEqual(await evaluate('pixel()'), [255, 0, 0, 255]);
    assert.equal(calls.filter(call => call.path.endsWith('/revisions')).length, 0, 'PNG preview never implicitly writes a revision');
    await evaluate('panel.save()');
    const writes = calls.filter(call => call.path.endsWith('/revisions'));
    assert.equal(writes.length, 1); assert.equal(writes[0].path, '/api/photocraft/sessions/' + first + '/revisions');
    assert.equal(writes[0].body.expected_revision, 0); assert.match(writes[0].body.png_data_url, /^data:image\/png;base64,/);
    await evaluate('panel.save()');
    assert.equal(calls.filter(call => call.path.endsWith('/revisions')).length, 1, 'saving an unchanged revision is idempotent in the UI');
  });
});

test('popup preserves dirty drafts across maps, batches exact saved revisions, and hands a separate asset to mod mapping', async () => {
  await fixture(async ({evaluate, calls, first, second}) => {
    await evaluate(`openPopup();`); await evaluate(`sendExport('red')`);
    await evaluate('openMap(1)'); await evaluate(`sendExport('#ffff00')`);
    assert.deepEqual(await evaluate(`pixel('body')`), [255, 255, 0, 255]);
    await evaluate('openMap(0)');
    assert.deepEqual(await evaluate('pixel()'), [255, 0, 0, 255], 'returning to an unsaved map restores its draft');
    await evaluate(`q('donor').click();waitFor(()=>donors.length===1)`);
    const donorCall = calls.find(call => call.path === '/api/photocraft/donors');
    assert.ok(donorCall); assert.deepEqual(donorCall.body.sessions, [{id: first, revision: 1}, {id: second, revision: 1}]);
    assert.equal(calls.filter(call => call.path.endsWith('/revisions')).length, 2);
    await evaluate(`q('mapping').click()`);
    assert.equal(await evaluate(`document.querySelector('#photocraft-popup')===null`), true);
    assert.deepEqual(await evaluate('mapping'), [{character: 'fixture_person', name: 'Painted fixture person', slug: 'fixture_person_painted'}]);
    assert.equal(await evaluate('viewers.every(value=>value.disposed)'), true);
  });
});

test('exports from another material need explicit assignment and are cleared when the selected map changes', async () => {
  await fixture(async ({evaluate, calls}) => {
    await evaluate('openPopup()');
    await evaluate(`window.oldName=activeName();openMap(1)`);
    await evaluate(`exportImage(oldName,'red');waitFor(()=>!q('use-export').hidden)`);
    assert.deepEqual(await evaluate(`pixel('body')`), [32, 192, 64, 255]);
    await evaluate('openMap(0)');
    assert.equal(await evaluate(`q('use-export').hidden`), true);
    await evaluate(`q('use-export').click();new Promise(r=>setTimeout(r,20))`);
    assert.deepEqual(await evaluate('pixel()'), [32, 64, 224, 255]);
    assert.equal(calls.filter(call => call.path.endsWith('/revisions')).length, 0);
  });
});

test('late revision completion after closing cannot restore UI or create a donor', async () => {
  await fixture(async ({evaluate, calls, hold}) => {
    await evaluate('openPopup()'); await evaluate(`sendExport('red')`);
    hold.revision = true;
    await evaluate(`window.saving=panel.save();waitFor(()=>q('save').disabled)`);
    for (let i = 0; i < 100 && !hold.release; i++) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(hold.release, 'revision request reached server');
    await evaluate('panel.dispose()'); hold.release();
    await evaluate('saving');
    assert.equal(await evaluate(`document.querySelector('#photocraft-popup')===null`), true);
    assert.equal(await evaluate('viewers.every(value=>value.disposed)'), true);
    assert.equal(calls.some(call => call.path === '/api/photocraft/donors'), false);
    assert.deepEqual(await evaluate('donors'), []);
  });
});

test('real UV brush gestures update the popup draft at fitted image coordinates and save only the bound image', async () => {
  await fixture(async ({evaluate, send, calls, first}) => {
    await evaluate('openPopup()');
    await evaluate(`document.querySelector('[data-mtp-wire]').checked=false;document.querySelector('[data-mtp-color]').value='#ff0000';document.querySelector('[data-mtp-radius]').value=3;
      document.querySelector('[data-mtp-canvas]').scrollIntoView({block:'center'});new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));`);
    const position = await evaluate(`(()=>{const c=document.querySelector('[data-mtp-canvas]'),r=c.getBoundingClientRect(),scale=Math.min(r.width/c.width,r.height/c.height),w=c.width*scale,h=c.height*scale;return {x:r.left+(r.width-w)/2+w*.25,y:r.top+(r.height-h)/2+h*.5}})()`);
    await send('Input.dispatchMouseEvent', {type: 'mousePressed', ...position, button: 'left', buttons: 1, clickCount: 1});
    await send('Input.dispatchMouseEvent', {type: 'mouseReleased', ...position, button: 'left', buttons: 0, clickCount: 1});
    await evaluate(`waitFor(()=>q('saved').textContent.includes('Unsaved'))`);
    assert.deepEqual(await evaluate(`[...viewers.at(-1).face.map.image.getContext('2d').getImageData(16,32,1,1).data]`), [255, 0, 0, 255]);
    assert.deepEqual(await evaluate(`pixel('body')`), [32, 192, 64, 255]);
    await evaluate('panel.save()');
    const revisions = calls.filter(call => call.path.endsWith('/revisions'));
    assert.equal(revisions.length, 1); assert.equal(revisions[0].path, '/api/photocraft/sessions/' + first + '/revisions');
  });
});

test('layered PhotoCraft projects are bound explicitly and retained per texture while switching maps', async () => {
  await fixture(async ({evaluate, calls, first, second}) => {
    await evaluate('openPopup()');
    await evaluate(`window.faceProjectName=activeName().replace(/\.png$/,'.psd');exportImage(faceProjectName,'face layers','image/vnd.adobe.photoshop');waitFor(()=>q('saved').textContent.includes('Layered'))`);
    await evaluate('openMap(1)');
    await evaluate(`exportImage(faceProjectName,'body layers','image/vnd.adobe.photoshop');waitFor(()=>!q('use-export').hidden)`);
    assert.match(await evaluate(`q('use-export').textContent`), /project/i);
    await evaluate('panel.save()');
    assert.equal(calls.filter(call => call.path.endsWith('/revisions')).length, 0, 'an export from another document is not silently bound');
    await evaluate(`q('use-export').click();panel.save()`);
    await evaluate('openMap(0)'); await evaluate('panel.save()');
    const revisions = calls.filter(call => call.path.endsWith('/revisions'));
    assert.equal(revisions.length, 2);
    const faceWrite = revisions.find(call => call.path.includes(first)), bodyWrite = revisions.find(call => call.path.includes(second));
    assert.equal(faceWrite.body.project_format, 'psd'); assert.equal(bodyWrite.body.project_format, 'psd');
    assert.equal(Buffer.from(faceWrite.body.project_data_url.split(',')[1], 'base64').toString(), 'face layers');
    assert.equal(Buffer.from(bodyWrite.body.project_data_url.split(',')[1], 'base64').toString(), 'body layers');
  });
});

test('PNG exports decoded out of order cannot overwrite a newer PhotoCraft edit', async () => {
  await fixture(async ({evaluate}) => {
    await evaluate('openPopup()');
    await evaluate(`window.NativeImage=Image;window.releaseSlow=null;let held=false;
      window.Image=class extends NativeImage {decode(){if(held)return super.decode();held=true;return new Promise(resolve=>releaseSlow=async()=>{await super.decode();resolve()});}};
      exportImage(activeName(),'red');waitFor(()=>!!releaseSlow);`);
    await evaluate(`exportImage(activeName(),'#ffff00');waitFor(()=>pixel()[0]===255&&pixel()[1]===255)`);
    await evaluate(`releaseSlow();new Promise(resolve=>setTimeout(resolve,100))`);
    assert.deepEqual(await evaluate('pixel()'), [255, 255, 0, 255], 'the older red decode cannot replace the latest yellow export');
    await evaluate(`held=false;releaseSlow=null;exportImage(activeName(),'red');waitFor(()=>!!releaseSlow)`);
    await evaluate(`document.querySelector('[data-mtp-paint]').checked=true;document.querySelector('[data-mtp-paint]').dispatchEvent(new Event('change'));document.querySelector('[data-mtp-color]').value='#0000ff';document.querySelector('[data-mtp-radius]').value=3;
      viewers.at(-1).paintHandler({material:'face',materialId:'face',u:.5,v:.5,event:{type:'pointerdown'}});document.dispatchEvent(new PointerEvent('pointerup'));`);
    await evaluate(`releaseSlow();new Promise(resolve=>setTimeout(resolve,100))`);
    assert.deepEqual(await evaluate('pixel()'), [0, 0, 255, 255], 'a pending PNG does not overwrite a newer mesh brush gesture');
    await evaluate('window.Image=NativeImage');
  });
});

test('opening another editor preserves the existing dialog when discarding unsaved changes is declined', async () => {
  await fixture(async ({evaluate}) => {
    await evaluate('openPopup()'); await evaluate(`sendExport('red')`);
    await evaluate(`io.confirm=()=>false;window.existingPanel=panel;window.secondPanel=GBoxPhotoCraft.open({character:'another_character'},io);void 0;`);
    assert.equal(await evaluate('secondPanel===existingPanel'), true);
    assert.equal(await evaluate(`document.querySelectorAll('#photocraft-popup').length`), 1);
    assert.deepEqual(await evaluate('pixel()'), [255, 0, 0, 255]);
    assert.equal(await evaluate('viewers.at(-1).disposed'), false);
  });
});

test('collection-model and image-lightbox entrypoints preserve the selected asset and target-game mapping context', async () => {
  const characterSource = fs.readFileSync(path.join(web, 'viz/character-popup.js'), 'utf8');
  const indexSource = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const lightboxStart = indexSource.indexOf('document.body.insertAdjacentHTML("beforeend", `<div id="lbox"');
  const lightboxEnd = indexSource.indexOf('// right-click any option:', lightboxStart);
  assert.ok(lightboxStart > 0 && lightboxEnd > lightboxStart, 'real image-lightbox implementation is available');
  await fixture(async ({evaluate, calls}) => {
    await evaluate(characterSource);
    await evaluate(`(async()=>{window.entryCalls=[];window.characterPanel=await GBoxCharacterPopup.open({slug:'fixture_person',name:'Fixture person',gid:'target-game',title:'Target game',slot:'enemy'},
      {...io,editTextures:opts=>{entryCalls.push(opts);window.panel=GBoxPhotoCraft.open({...opts,character:opts.slug},io)}});
      window.entryViewer=viewers.at(-1);document.querySelector('[data-cp=paint]').click();
      await waitFor(()=>frame()&&!!activeName()&&!!document.querySelector('[data-mtp-canvas]')&&!q('load-map').disabled);})()`);
    assert.deepEqual(await evaluate('entryCalls[0]'), {slug: 'fixture_person', name: 'Fixture person', gid: 'target-game', title: 'Target game', slot: 'enemy'});
    assert.equal(await evaluate(`document.querySelector('.cp-modal')===null && document.querySelectorAll('#photocraft-popup').length===1`), true);
    assert.equal(await evaluate('entryViewer.disposed'), true, 'the former model preview is disposed before opening the editor');
    assert.ok(calls.some(call => call.path === '/api/photocraft/sessions' && call.body?.character === 'fixture_person'));
    assert.equal(calls.some(call => call.path === '/api/jobs'), false, 'opening a texture editor queues no build or game operation');
    await evaluate(`panel.dispose();window.$=selector=>document.querySelector(selector);window.photocraftOpen=opts=>entryCalls.push(opts);`);
    await evaluate(indexSource.slice(lightboxStart, lightboxEnd));
    await evaluate(`window.sourceImage=makeImage('red').toDataURL();lbOpen(null,[{src:sourceImage,name:'Selected face texture'}],0);document.querySelector('#lbox [data-z=edit]').click();`);
    assert.deepEqual(await evaluate('entryCalls.at(-1)'), await evaluate(`({src:sourceImage,name:'Selected face texture'})`));
    assert.equal(await evaluate(`document.querySelector('#lbox').style.display`), 'none', 'the lightbox yields to the editor');
  });
});
