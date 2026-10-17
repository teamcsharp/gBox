'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {withPage} = require('../scripts/browser_lifecycle.cjs');
const source = fs.readFileSync(path.join(__dirname, '../clients/web/viz/model-texture-paint.js'), 'utf8');

// The real raycaster lives in character-model.js. This fixture exercises its exact hit contract
// against real browser pixels and CanvasTexture assignment, without calling a screenshot a mesh.
async function setup(evaluate, send, settings = {}) {
  await send('Emulation.setDeviceMetricsOverride', {width: 1200, height: 1000, deviceScaleFactor: 1, mobile: false});
  await evaluate(source);
  await evaluate(`document.body.innerHTML='<div id="host" style="width:700px"></div>';
    window.makeImage=(color,w=64,h=64)=>{const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').fillStyle=color;c.getContext('2d').fillRect(0,0,w,h);return c;};
    window.originalFace={image:makeImage('#2040e0'),flipY:false,wrapS:1,wrapT:2,minFilter:3,magFilter:4,colorSpace:'srgb',repeat:{x:2,y:1},offset:{x:.1,y:.2},center:{x:0,y:0},rotation:.2};
    window.originalBody={...originalFace,image:makeImage('#20c040')};
    window.face={uuid:'face-id',name:'face',map:originalFace},body={uuid:'body-id',name:'body',map:originalBody};
    window.disposedTextures=0;window.paintHandler=null;window.changes=[];window.commits=[];window.editPending=null;
    const vector=()=>({copy(v){this.x=v.x;this.y=v.y;return this}});
    window.viewer={THREE:{CanvasTexture:class{constructor(image){this.image=image;this.repeat=vector();this.offset=vector();this.center=vector()}updateMatrix(){}dispose(){disposedTextures++}}},
      gltf:{scene:{traverse(fn){fn({isMesh:true,material:[face,body]})}}},paint(handler){paintHandler=handler},uvLines(){return []}};
    window.options={viewer,onChange:value=>changes.push(value),onCommit:async value=>{commits.push(value);return {saved:true}},onEditImage:()=>new Promise(resolve=>editPending=resolve),...${JSON.stringify(settings)}};
    window.panel=GBoxModelTexturePaint.mount(document.querySelector('#host'),options);panel.ready;`);
  await evaluate(`window.pixel=(material,x,y)=>[...material.map.image.getContext('2d').getImageData(x,y,1,1).data];
    window.choose=(name,value)=>{const e=document.querySelector('[data-mtp-'+name+']');if(e.type==='checkbox')e.checked=value;else e.value=value;e.dispatchEvent(new Event('change'));};
    document.querySelector('[data-mtp-radius]').value='3';choose('wire',false);choose('color','#ff0000');`);
}
async function point(evaluate, u, v) {
  return evaluate(`(()=>{const r=document.querySelector('[data-mtp-canvas]').getBoundingClientRect();return {x:r.left+r.width*${u},y:r.top+r.height*${v}}})()`);
}
async function click(send, position) {
  await send('Input.dispatchMouseEvent', {type: 'mousePressed', ...position, button: 'left', buttons: 1, clickCount: 1});
  await send('Input.dispatchMouseEvent', {type: 'mouseReleased', ...position, button: 'left', buttons: 0, clickCount: 1});
}

test('UV pointer paint updates only selected material; masks, undo, explicit commit, and disposal preserve originals', async () => {
  await withPage(async (evaluate, send) => {
    await setup(evaluate, send);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [32, 64, 224, 255]);
    assert.deepEqual(await evaluate('[face.map.flipY,face.map.wrapS,face.map.repeat.x,face.map.offset.y,face.map.rotation]'), [false, 1, 2, .2, .2]);
    await click(send, await point(evaluate, .5, .5));
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [255, 0, 0, 255]);
    assert.deepEqual(await evaluate('pixel(body,32,32)'), [32, 192, 64, 255]);
    assert.equal(await evaluate('changes.length'), 1, 'one encoded export after the gesture');
    assert.equal(await evaluate('commits.length'), 0, 'painting does not save a donor or modify a game');
    await evaluate(`choose('tool','hide')`); await click(send, await point(evaluate, .5, .5));
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [32, 64, 224, 255]);
    await evaluate(`document.querySelector('[data-mtp-undo]').click()`);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [255, 0, 0, 255]);
    await evaluate(`document.querySelector('[data-mtp-redo]').click()`);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [32, 64, 224, 255]);
    await evaluate(`choose('tool','reveal')`); await click(send, await point(evaluate, .5, .5));
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [255, 0, 0, 255]);
    await evaluate(`choose('original',true)`);
    assert.equal(await evaluate('face.map===originalFace'), true);
    await evaluate(`choose('original',false);panel.commit()`);
    const payload = await evaluate('commits[0]');
    assert.equal(payload.version, 1); assert.equal(payload.textures.length, 1);
    assert.equal(payload.textures[0].material, 'face'); assert.equal(payload.textures[0].width, 64);
    assert.match(payload.textures[0].png_data_url, /^data:image\/png;base64,/);
    assert.match(payload.textures[0].mask_data_url, /^data:image\/png;base64,/);
    await evaluate('panel.dispose()');
    assert.equal(await evaluate('face.map===originalFace && body.map===originalBody && paintHandler===null'), true);
    assert.equal(await evaluate('disposedTextures'), 1);
  });
});

test('3D raycast UV hits avoid cross-island strokes and export only after pointer release', async () => {
  await withPage(async (evaluate, send) => {
    await setup(evaluate, send);
    await evaluate(`choose('paint',true);
      paintHandler({material:'body',u:.5,v:.5,event:{type:'pointerdown',pointerId:4}});
      paintHandler({material:'face',u:.1,v:.5,event:{type:'pointerdown',pointerId:4}});
      paintHandler({material:'face',u:.9,v:.5,event:{type:'pointermove',pointerId:4}});`);
    assert.equal(await evaluate('changes.length'), 0);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [32, 64, 224, 255], 'UV gap was not joined by a painted line');
    assert.deepEqual(await evaluate('pixel(face,6,32)'), [255, 0, 0, 255]);
    assert.deepEqual(await evaluate('pixel(face,57,32)'), [255, 0, 0, 255]);
    await evaluate(`document.dispatchEvent(new PointerEvent('pointerup',{pointerId:4}));`);
    assert.equal(await evaluate('changes.length'), 1);
    assert.equal(await evaluate('changes[0].kind'), 'stroke');
    const exported = await evaluate(`({w:panel.getImage().width,h:panel.getImage().height,png:panel.exportPNG()})`);
    assert.equal(exported.w, 64); assert.equal(exported.h, 64); assert.match(exported.png, /^data:image\/png;base64,/);
    await evaluate(`panel.dispose();document.dispatchEvent(new PointerEvent('pointerup',{pointerId:4}));`);
    assert.equal(await evaluate('changes.length'), 1, 'disposed editor has no pending event listener');
  });
});

test('PhotoCraft image replacement requires native dimensions; stale selection or close never alters another material', async () => {
  await withPage(async (evaluate, send) => {
    await setup(evaluate, send);
    await evaluate(`panel.setImage(makeImage('#ffff00'))`);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [255, 255, 0, 255]);
    const failure = await evaluate(`panel.setImage(makeImage('red',32,32)).then(()=>'',e=>e.message)`);
    assert.match(failure, /original texture size/);
    await evaluate(`document.querySelector('[data-mtp-edit]').click();panel.select('body');editPending(makeImage('red'));new Promise(r=>setTimeout(r,20));`);
    assert.deepEqual(await evaluate('pixel(body,32,32)'), [32, 192, 64, 255]);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [255, 255, 0, 255]);
    await evaluate(`window.NativeImage=Image;window.releaseDecode=null;
      window.Image=class extends NativeImage {decode(){return new Promise(resolve=>releaseDecode=async()=>{await super.decode();resolve()})}};
      window.loading=panel.setImage(makeImage('red').toDataURL());panel.select('face');releaseDecode();`);
    assert.equal(await evaluate('loading'), false);
    assert.deepEqual(await evaluate('pixel(body,32,32)'), [32, 192, 64, 255]);
    await evaluate(`window.loading=panel.setImage(makeImage('red').toDataURL());panel.dispose();releaseDecode();`);
    assert.equal(await evaluate('loading'), false);
    assert.equal(await evaluate('face.map===originalFace && body.map===originalBody'), true);
  });
});

test('transparent original pixels remain exact and texture/history memory budgets are enforced', async () => {
  await withPage(async (evaluate, send) => {
    await setup(evaluate, send, {maxPixels: 4096, historyBytes: 0});
    await evaluate(`panel.dispose();originalFace.image=makeImage('rgba(0,100,200,.5)');panel=GBoxModelTexturePaint.mount(document.querySelector('#host'),options);panel.ready;`);
    assert.equal(await evaluate('pixel(face,32,32)[3]'), 128, 'initial preview must not double transparent texel alpha');
    await evaluate(`document.querySelector('[data-mtp-wire]').checked=false;document.querySelector('[data-mtp-radius]').value=3;`);
    await click(send, await point(evaluate, .5, .5));
    assert.equal(await evaluate(`document.querySelector('[data-mtp-undo]').disabled`), true);
    assert.equal(await evaluate(`panel.select('body')`), false, 'second map cannot exceed total preview pixel budget');
    assert.equal(await evaluate('body.map===originalBody'), true, 'memory rejection happens before native map replacement');
    await evaluate('panel.dispose()');
  });
});

test('image-index groups update shared base-color bindings while duplicate material names stay isolated by raycast UUID', async () => {
  await withPage(async (evaluate, send) => {
    await setup(evaluate, send);
    await evaluate(`panel.dispose();body.name='face';window.body2={uuid:'body2-id',name:'other',map:{...originalBody,offset:{x:.7,y:.8}}};
      viewer.gltf.scene.traverse=fn=>fn({isMesh:true,material:[face,body,body2]});viewer.paintMaterialIds=true;
      window.selections=[];options.onSelect=row=>selections.push(row);
      options.materials=[{id:'0',name:'Head map',image:0,materials:[face]},{id:'1',name:'Shared clothing map',image:1,materials:[body,body2]}];
      panel=GBoxModelTexturePaint.mount(document.querySelector('#host'),options);panel.ready;`);
    await evaluate(`panel.select('1');panel.setImage(makeImage('#ffff00'))`);
    assert.deepEqual(await evaluate('pixel(body,32,32)'), [255, 255, 0, 255]);
    assert.deepEqual(await evaluate('pixel(body2,32,32)'), [255, 255, 0, 255]);
    assert.deepEqual(await evaluate('[body.map.offset.x,body2.map.offset.x]'), [.1, .7], 'each material keeps its own transform');
    await evaluate(`choose('paint',true);choose('color','#ff0000');document.querySelector('[data-mtp-radius]').value='3';
      paintHandler({material:'face',materialId:'face-id',u:.5,v:.5,event:{type:'pointerdown'}});`);
    assert.deepEqual(await evaluate('pixel(body,32,32)'), [255, 255, 0, 255], 'same-named material from a different image is not painted');
    await evaluate(`paintHandler({material:'face',materialId:'body-id',u:.5,v:.5,event:{type:'pointerdown'}});document.dispatchEvent(new PointerEvent('pointerup'));`);
    assert.deepEqual(await evaluate('pixel(body,32,32)'), [255, 0, 0, 255]);
    assert.deepEqual(await evaluate('pixel(body2,32,32)'), [255, 0, 0, 255]);
    assert.deepEqual(await evaluate('pixel(face,32,32)'), [32, 64, 224, 255]);
    assert.equal(await evaluate('changes.at(-1).image'), 1);
    await evaluate(`selections=[];panel.select('0');panel.select('1');Promise.resolve();`);
    assert.deepEqual(await evaluate('selections.map(row=>row.image)'), [1], 'stale material selections are not sent to PhotoCraft');
    await evaluate('panel.dispose()');
    assert.equal(await evaluate('face.map===originalFace && body.map===originalBody'), true);
  });
});
