const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto');
const FW=require('../clients/web/viz/face-warp-editor.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/face-warp-editor.js'),'utf8');

test('deformation validates bounded reversible recipes and rejects folded or ambiguous grids',()=>{
  assert.deepEqual(FW.normalize(null),{version:1,lattice:null,strokes:[]});
  const g=FW.identity(3);g.points[4].x=.55;
  const recipe={version:1,lattice:g,strokes:[{x:.5,y:.5,dx:.02,dy:0,radius:.2}]};
  assert.deepEqual(FW.normalize(recipe),recipe);
  const bad=FW.identity(3);bad.points[4].x=2;
  assert.throws(()=>FW.normalize({...recipe,lattice:bad}),/outside/);
  bad.points[4].x=-.1;assert.throws(()=>FW.normalize({...recipe,lattice:bad}),/fold/);
  for(const stroke of [{x:.5,y:.5,dx:.1,dy:0,radius:.1},{x:.5,y:.5,dx:NaN,dy:0,radius:.1},{x:2,y:.5,dx:0,dy:0,radius:.1}])assert.throws(()=>FW.normalize({...recipe,strokes:[stroke]}),/range/);
  assert.throws(()=>FW.normalize({...recipe,strokes:Array(257).fill(recipe.strokes[0])}),/256/);
  assert.throws(()=>FW.normalize({version:2}),/version/);
});

test('photo warping keeps exact identity, maps lattice cells, and interpolates transparent masks without dark fringe',()=>{
  const pixels=new Uint8ClampedArray([255,0,0,255,0,0,0,0,0,255,0,255,0,0,255,255]);
  assert.deepEqual(FW.warpPixels(pixels,2,2,null),pixels);
  assert.deepEqual(FW.warpPixels(pixels,2,2,{version:1,lattice:FW.identity(3),strokes:[]}),pixels);
  const g=FW.identity(3);g.points[4].x=.6;
  const p=FW.makeInverse({version:1,lattice:g,strokes:[]})({x:.6,y:.5});
  assert.ok(Math.abs(p.x-.5)<1e-8&&Math.abs(p.y-.5)<1e-8);
  const shifted=FW.identity(2);shifted.points.forEach(p=>p.x+=.25);
  const out=FW.warpPixels(new Uint8ClampedArray([255,0,0,255,0,0,0,0]),2,1,{version:1,lattice:shifted,strokes:[]});
  assert.equal(out[4],255,'partially transparent red edge retains its RGB');assert.ok(out[7]>0&&out[7]<255);
});

test('shared native RGBA fixture matches the reviewed inverse lattice and sequential liquify sampler',()=>{
  const p=new Uint8ClampedArray(8*8*4);
  for(let y=0;y<8;y++)for(let x=0;x<8;x++)p.set([x*31,y*29,(x+y)*15,(x+y)%3?255:64],(y*8+x)*4);
  const lattice=FW.identity(3);lattice.points[4]={x:.58,y:.46};
  const out=FW.warpPixels(p,8,8,{version:1,lattice,strokes:[{x:.5,y:.5,dx:.025,dy:-.015,radius:.35}]});
  assert.equal(crypto.createHash('sha256').update(out).digest('hex'),'959fc83976a656799ce25de943d5efe009df2da0af8e986f78def31c8000566d');
});

async function setup(evaluate,send){
  await send('Emulation.setDeviceMetricsOverride',{width:1200,height:1100,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.body.style='margin:12px';document.body.innerHTML='<div id="host" style="width:800px"></div>';`);
  await evaluate(source);
  await evaluate(`var reference=document.createElement('canvas'),layer=document.createElement('canvas');reference.width=layer.width=64;reference.height=layer.height=64;
    reference.getContext('2d').fillStyle='#2040e0';reference.getContext('2d').fillRect(0,0,64,64);
    layer.getContext('2d').fillStyle='#ef3020';layer.getContext('2d').fillRect(25,25,14,14);
    var changes=[],commits=[],editStarts=[],host=document.querySelector('#host');var editor=GBoxFaceWarpEditor.mount(host,{reference,layer,onEditStart:(d,m)=>editStarts.push({d,m}),onChange:(d,m)=>changes.push({d,m}),onCommit:d=>commits.push(d)});editor.ready;`);
  await evaluate(`var fwPointerId,fwEvents=[],canvasElement=host.querySelector('[data-fw-canvas]');for(const name of ['pointerdown','pointermove','pointerup','pointercancel','gotpointercapture','lostpointercapture'])canvasElement.addEventListener(name,e=>{fwPointerId=e.pointerId;fwEvents.push([name,e.pointerId,e.buttons]);});`);
  await evaluate(`host.querySelector('[data-fw-zoom]').value='4';host.querySelector('[data-fw-zoom]').dispatchEvent(new Event('change'));host.querySelector('[data-fw-opacity]').value='100';host.querySelector('[data-fw-opacity]').dispatchEvent(new Event('input'));new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));`);
}
async function pos(evaluate,x,y){return evaluate(`(()=>{const b=host.querySelector('[data-fw-canvas]').getBoundingClientRect();return {x:b.left+b.width*${x},y:b.top+b.height*${y}}})()`);}
async function pointer(send,type,p){await send('Input.dispatchMouseEvent',{type,x:p.x,y:p.y,button:'left',buttons:type==='mouseReleased'?0:1,clickCount:type==='mouseMoved'?0:1});}
async function settle(evaluate){await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);}

test('browser: real pointer liquify updates only photo pixels live, commits once per gesture, supports history and comparison',async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    const start=await pos(evaluate,.5,.5),end=await pos(evaluate,.57,.5);
    await pointer(send,'mousePressed',start);await pointer(send,'mouseMoved',end);await settle(evaluate);
    assert.equal(await evaluate('editStarts.length'),1,'native candidate is invalidated before a gesture can race its response');
    assert.equal(await evaluate('editStarts[0].d.strokes.length'),0);
    assert.equal(await evaluate('changes.length'),0,'pointer motion never causes native preview/network callbacks');
    assert.ok(await evaluate('editor.getDeformation().strokes.length')>0);
    assert.equal(await evaluate(`host.querySelector('[data-fw-canvas]').hasPointerCapture(fwPointerId)`),true,JSON.stringify(await evaluate('fwEvents')));
    await pointer(send,'mouseReleased',end);await settle(evaluate);
    assert.equal(await evaluate('changes.length'),1);assert.equal(await evaluate('changes[0].m.reason'),'liquify');
    assert.ok(await evaluate(`host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(38,32,1,1).data[0]`)>100,'dragged photo has moved to the right');
    assert.deepEqual(await evaluate(`Array.from(reference.getContext('2d').getImageData(32,32,1,1).data)`),[32,64,224,255],'reference source stays unmodified');
    await evaluate(`host.querySelector('[data-fw-compare]').click();`);await settle(evaluate);
    assert.deepEqual(await evaluate(`Array.from(host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(32,32,1,1).data)`),[32,64,224,255]);
    await evaluate(`host.querySelector('[data-fw-compare]').click();host.querySelector('[data-fw-undo]').click();`);await settle(evaluate);
    assert.equal(await evaluate('editor.getDeformation().strokes.length'),0);
    await evaluate(`host.querySelector('[data-fw-redo]').click();host.querySelector('[data-fw-commit]').click();`);
    assert.equal(await evaluate('commits.length'),1);assert.ok(await evaluate('commits[0].strokes.length')>0);
    await evaluate(`host.querySelector('[data-fw-reset]').click();`);
    assert.deepEqual(await evaluate('editor.getDeformation()'),{version:1,lattice:null,strokes:[]});
    await evaluate('editor.dispose()');
  });
});

test('browser: lattice drag, folded-cell rejection, pointer cancellation and capture across an outside release',async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);await evaluate(`host.querySelector('[data-fw-tool="lattice"]').click();`);await settle(evaluate);
    const start=await pos(evaluate,.5,.5),end=await pos(evaluate,.56,.53);
    await pointer(send,'mousePressed',start);await pointer(send,'mouseMoved',end);await pointer(send,'mouseReleased',end);await settle(evaluate);
    const p=await evaluate('editor.getDeformation().lattice.points[12]');assert.ok(p.x>.55&&p.y>.52);assert.equal(await evaluate('changes.length'),1);
    await pointer(send,'mousePressed',end);await pointer(send,'mouseMoved',await pos(evaluate,.95,.95));await settle(evaluate);
    assert.deepEqual(await evaluate('editor.getDeformation().lattice.points[12]'),p,'a fold cannot corrupt the last valid lattice');
    await evaluate(`host.querySelector('[data-fw-canvas]').dispatchEvent(new PointerEvent('pointercancel',{pointerId:fwPointerId,bubbles:true}));`);
    assert.deepEqual(await evaluate('editor.getDeformation().lattice.points[12]'),p);assert.equal(await evaluate('changes.length'),1,'cancelled gesture is not saved');
    await evaluate(`host.querySelector('[data-fw-tool="liquify"]').click();`);
    await pointer(send,'mousePressed',await pos(evaluate,.9,.5));await pointer(send,'mouseMoved',await pos(evaluate,1.1,.5));await pointer(send,'mouseReleased',await pos(evaluate,1.1,.5));await settle(evaluate);
    assert.equal(await evaluate(`host.querySelector('[data-fw-canvas]').hasPointerCapture(fwPointerId)`),false);
    assert.equal(await evaluate('changes.length'),2,'release beyond canvas still completes the gesture');
    await evaluate('editor.dispose()');
  });
});

test('browser: stale image loads and disposal cannot replace another face or send edits',async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    await evaluate(`var originalImage=window.Image,srcDescriptor=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src'),releaseImages=[];
      var oldUrl=layer.toDataURL();window.Image=function(){const img=new originalImage();Object.defineProperty(img,'src',{set(value){if(value==='deferred'){const loaded=img.onload;img.onload=()=>{releaseImages.push(()=>loaded.call(img))};srcDescriptor.set.call(img,oldUrl);}else srcDescriptor.set.call(img,value);}});return img;};
      var oldUpdate=editor.update({reference:'deferred',layer:'deferred',deformation:{version:1,lattice:null,strokes:[]}});new Promise(r=>setTimeout(r,30));`);
    await evaluate(`var fresh=document.createElement('canvas');fresh.width=32;fresh.height=16;fresh.getContext('2d').fillStyle='#00ff00';fresh.getContext('2d').fillRect(0,0,32,16);editor.update({reference:fresh,layer:fresh});`);
    assert.equal(await evaluate(`releaseImages.splice(0).forEach(fn=>fn());oldUpdate;`),false,'late images from the previous face are rejected');
    assert.equal(await evaluate(`host.querySelector('[data-fw-canvas]').width`),32);
    assert.equal(await evaluate(`host.querySelector('[data-fw-canvas]').height`),16);
    assert.equal(await evaluate('changes.length'),0,'changing faces never serializes an old edit into the new face');
    await evaluate(`var disposedUpdate=editor.update({reference:'deferred',layer:'deferred'});new Promise(r=>setTimeout(r,30));`);
    await evaluate(`editor.dispose();releaseImages.splice(0).forEach(fn=>fn());window.Image=originalImage;disposedUpdate;`);
    assert.equal(await evaluate('host.innerHTML'),'');assert.equal(await evaluate('changes.length'),0);
    await evaluate(`editor.undo();editor.redo();editor.reset();`);
  });
});

test('browser: fixed face coverage clips the warped photo while reference and external texture pixels stay intact',async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    await evaluate(`var mask=document.createElement('canvas');mask.width=64;mask.height=64;mask.getContext('2d').fillStyle='white';mask.getContext('2d').fillRect(0,0,32,64);
      var fullPhoto=document.createElement('canvas');fullPhoto.width=64;fullPhoto.height=64;fullPhoto.getContext('2d').fillStyle='#ff0000';fullPhoto.getContext('2d').fillRect(0,0,64,64);
      editor.update({reference,layer:fullPhoto,coverage:mask,deformation:{version:1,lattice:null,strokes:[{x:.5,y:.5,dx:.04,dy:0,radius:.3}]}});`);
    await settle(evaluate);
    assert.deepEqual(await evaluate(`Array.from(host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(40,32,1,1).data)`),[32,64,224,255]);
    assert.equal(await evaluate(`host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(20,32,1,1).data[0]`),255);
    await evaluate('editor.dispose()');
  });
});

test('browser: respecting native transparency keeps the original alpha while blending the warped face',async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    await evaluate(`editor.dispose();var native=document.createElement('canvas'),photo=document.createElement('canvas');native.width=photo.width=16;native.height=photo.height=16;
      native.getContext('2d').fillStyle='rgba(0,0,255,0.5)';native.getContext('2d').fillRect(0,0,8,16);photo.getContext('2d').fillStyle='red';photo.getContext('2d').fillRect(0,0,16,16);
      editor=GBoxFaceWarpEditor.mount(host,{reference:native,layer:photo,respectAlpha:true});editor.ready;`);
    await evaluate(`host.querySelector('[data-fw-opacity]').value=100;host.querySelector('[data-fw-opacity]').dispatchEvent(new Event('input'));`);await settle(evaluate);
    const pixels=await evaluate(`Array.from(host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(4,8,1,1).data)`);
    assert.ok(pixels[0]>=126&&pixels[0]<=130);assert.ok(pixels[2]>=125&&pixels[2]<=130,'native alpha also limits the photo RGB blend');assert.ok(pixels[3]>=127&&pixels[3]<=128,'native semi-transparent alpha is preserved');
    assert.equal(await evaluate(`host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(12,8,1,1).data[3]`),0);
    await evaluate(`host.querySelector('[data-fw-reference]').click();`);await settle(evaluate);
    assert.ok(await evaluate(`host.querySelector('[data-fw-canvas]').getContext('2d').getImageData(4,8,1,1).data[3]`)<=128);
    await evaluate('editor.dispose()');
  });
});

test('browser: hover and view controls reuse cached warps while large-texture drags use a responsive preview',async()=>{
  await withPage(async(evaluate,send)=>{
    await setup(evaluate,send);
    await evaluate(`var big=document.createElement('canvas');big.width=big.height=256;big.getContext('2d').fillStyle='red';big.getContext('2d').fillRect(100,100,50,50);editor.update({reference:big,layer:big});`);await settle(evaluate);
    await evaluate(`host.querySelector('[data-fw-zoom]').value='1';host.querySelector('[data-fw-zoom]').dispatchEvent(new Event('change'));var rasterizations=[],originalPut=CanvasRenderingContext2D.prototype.putImageData;CanvasRenderingContext2D.prototype.putImageData=function(data,...args){rasterizations.push([data.width,data.height]);return originalPut.call(this,data,...args);};`);
    await pointer(send,'mouseMoved',await pos(evaluate,.3,.3));await settle(evaluate);
    for(const event of ["host.querySelector('[data-fw-radius]').dispatchEvent(new Event('input'))","host.querySelector('[data-fw-opacity]').dispatchEvent(new Event('input'))","host.querySelector('[data-fw-compare]').click()","host.querySelector('[data-fw-compare]').click()"]){await evaluate(event);await settle(evaluate);}
    assert.equal(await evaluate('rasterizations.length'),0,'view changes and brush cursor motion do not resample photo pixels');
    await pointer(send,'mousePressed',await pos(evaluate,.5,.5));await pointer(send,'mouseMoved',await pos(evaluate,.55,.5));await settle(evaluate);
    assert.deepEqual(await evaluate('rasterizations.at(-1)'),[128,128],'large textures use a smaller local raster during the drag');
    assert.equal(await evaluate('changes.length'),0);
    await pointer(send,'mouseReleased',await pos(evaluate,.55,.5));await settle(evaluate);
    assert.deepEqual(await evaluate('rasterizations.at(-1)'),[256,256],'release restores full local texture resolution');
    assert.equal(await evaluate('changes.length'),1);
    await evaluate('CanvasRenderingContext2D.prototype.putImageData=originalPut;editor.dispose()');
  });
});
