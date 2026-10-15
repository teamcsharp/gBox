const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
test('browser: photo crop, rotation, 3D candidate and separate-donor approval do not launch games',async()=>{
 await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1000,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/photo-skin.js'),'utf8'));
  await evaluate(`document.body.style='background:#17171c;color:#ddd;font:14px system-ui;max-width:620px;padding:12px';document.body.innerHTML='<div id="host"></div>';var calls=[],pending=[],previews=[],accepted=[];
   var canvas=document.createElement('canvas');canvas.width=16;canvas.height=16;var ctx=canvas.getContext('2d');ctx.fillStyle='#244968';ctx.fillRect(0,0,16,16);ctx.fillStyle='#d9ab72';ctx.beginPath();ctx.ellipse(8,8,4,6,0,0,Math.PI*2);ctx.fill();ctx.fillStyle='#171922';ctx.fillRect(6,6,1,1);ctx.fillRect(9,6,1,1);ctx.fillRect(7,10,2,1);var png=canvas.toDataURL();
   var io={url:u=>u.startsWith('/api/artifacts/')?png:u,api:async(p,b)=>{calls.push({p,b});if(p.endsWith('/texture-maps'))return {maps:[{index:0,name:'Face',size:[16,16],url:png}]};
    if(p==='/api/photo-skins/photos')return {photo:'a'.repeat(64),url:png};
    if(p.endsWith('/photo-skins'))return {id:'review',candidate:'b'.repeat(64),images:[{after:'c'.repeat(64)}],notice:'Synthetic photo projection; geometry unchanged'};
    if(p.endsWith('/decision'))return {status:'accepted',variant:'bla',name:'Bla on Leon'};throw Error('Unexpected '+p);}};
   var ctl=GBoxPhotoSkin.mount(document.querySelector('#host'),io,{slug:'leon',onPending:v=>pending.push(v),onPreview:v=>previews.push(v),onAccepted:v=>accepted.push(v)});
   document.querySelector('details').open=true;new Promise(r=>setTimeout(r,30));`);
  await evaluate(`var input=document.querySelector('[data-ps="file"]'),dt=new DataTransfer(),raw=atob(png.split(',')[1]);dt.items.add(new File([Uint8Array.from(raw,c=>c.charCodeAt(0))],'synthetic.png',{type:'image/png'}));input.files=dt.files;input.dispatchEvent(new Event('change'));new Promise(r=>setTimeout(r,30));`);
  await evaluate(`document.querySelector('[data-ps="rotate"]').click();document.querySelector('[data-ps="prepare"]').click();new Promise(r=>setTimeout(r,30));`);
  assert.equal(await evaluate(`pending.at(-1)`),true);
  assert.deepEqual(await evaluate(`calls.find(c=>c.p==='/api/characters/leon/photo-skins').b.quad`),[[1,0],[1,1],[0,1],[0,0]]);
  await evaluate(`document.querySelector('[data-ps="candidate"]').click();new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate(`previews[0].candidate`),'b'.repeat(64));
  await evaluate(`document.querySelector('[data-ps="accept"]').click();new Promise(r=>setTimeout(r,10));`);
  assert.equal(await evaluate(`accepted[0].variant`),'bla');assert.equal(await evaluate(`pending.at(-1)`),false);
  assert.equal(await evaluate(`calls.some(c=>c.p==='/api/jobs')`),false);
  if(process.env.GBOX_PHOTO_EVIDENCE){const shot=await send('Page.captureScreenshot',{format:'png'});fs.mkdirSync(process.env.GBOX_PHOTO_EVIDENCE,{recursive:true});fs.writeFileSync(path.join(process.env.GBOX_PHOTO_EVIDENCE,'photo-skin-controls.png'),Buffer.from(shot.result.data,'base64'));}
  await evaluate('ctl.dispose()');
 });
});
