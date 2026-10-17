const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),zlib=require('node:zlib');
const F=require('../clients/web/viz/photocraft-frame.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const manifest=require('../gbox/photocraft_runtime.json');
const nonce='a_valid_gbox_nonce_123456789';

function windowFixture(){
 const events={},sent=[],drops=[],downloads=[];
 class Anchor{click(){downloads.push(this.href);}}
 class File{constructor(parts,name,options){Object.assign(this,{parts,name,...options});}}
 class Transfer{constructor(){this.files=[];this.items={add:file=>this.files.push(file)};}}
 class Drag{constructor(type,options){Object.assign(this,{type,...options});}}
 const canvas={dispatchEvent:event=>drops.push(event)};
 const parent={postMessage:(message,origin,transfers)=>sent.push({message,origin,transfers})};
 const win={location:{origin:'http://gbox.test',hash:'#bridge='+nonce},parent,HTMLAnchorElement:Anchor,ArrayBuffer,DataTransfer:Transfer,File,DragEvent:Drag,
  document:{querySelector:()=>canvas},addEventListener:(kind,fn)=>events[kind]=fn,removeEventListener:(kind,fn)=>{if(events[kind]===fn)delete events[kind];},fetch:async()=>({blob:async()=>new Blob([new Uint8Array([1,2,3])])})};
 return {win,events,sent,drops,downloads,Anchor};
}

test('PhotoCraft bridge validates parent, origin, nonce and bounded binary imports',()=>{
 assert.equal(F.nonceOf('#bridge='+nonce),nonce);assert.equal(F.nonceOf('#bridge=short'),'');assert.equal(F.nonceOf('#bridge=<script>'),'');
 assert.equal(F.fileName('C:\\photos\\face.png'),'face.png');assert.equal(F.fileName('../face\u0000.png'),'face.png');assert.equal(F.exportMime('face.PNG'),'image/png');assert.equal(F.exportMime('face.html'),'');
 const {win,events,sent,drops}=windowFixture(),bridge=F.createBridge(win);
 const message={type:'gbox-photocraft-open',nonce,name:'face.png',bytes:new Uint8Array([1,2,3]).buffer};
 events.message({source:{},origin:win.location.origin,data:message});events.message({source:win.parent,origin:'http://wrong.test',data:message});events.message({source:win.parent,origin:win.location.origin,data:{...message,nonce:'wrong'}});bridge.ready();
 assert.equal(drops.length,0);assert.equal(sent[0].message.type,'gbox-photocraft-ready');
 events.message({source:win.parent,origin:win.location.origin,data:message});
 assert.deepEqual(drops.map(e=>e.type),['dragenter','dragover','drop']);assert.equal(drops[2].dataTransfer.files[0].name,'face.png');
 events.message({source:win.parent,origin:win.location.origin,data:{...message,bytes:'not binary'}});
 assert.equal(sent.at(-1).message.type,'gbox-photocraft-error');assert.equal(drops.length,3);bridge.dispose();assert.equal(events.message,undefined);
});

test('PhotoCraft queues one import before boot and returns supported Blob exports without duplicate downloads',async()=>{
 const {win,events,sent,drops,downloads,Anchor}=windowFixture(),original=Anchor.prototype.click,bridge=F.createBridge(win);
 const bytes=new Uint8Array([1]).buffer;
 for(const name of ['old.png','latest.png'])events.message({source:win.parent,origin:win.location.origin,data:{type:'gbox-photocraft-open',nonce,name,bytes}});
 assert.equal(drops.length,0);bridge.ready();assert.equal(drops[2].dataTransfer.files[0].name,'latest.png');
 const png=new Anchor();Object.assign(png,{href:'blob:http://gbox.test/export',download:'texture.png'});png.click();await new Promise(r=>setTimeout(r,0));
 const result=sent.find(v=>v.message.type==='gbox-photocraft-export');assert.equal(result.message.mime,'image/png');assert.equal(result.message.nonce,nonce);assert.deepEqual(Array.from(new Uint8Array(result.message.bytes)),[1,2,3]);assert.equal(result.transfers[0],result.message.bytes);assert.deepEqual(downloads,[]);
 const other=new Anchor();Object.assign(other,{href:'blob:http://gbox.test/other',download:'texture.jpg'});other.click();assert.deepEqual(downloads,[other.href]);
 bridge.dispose();assert.equal(Anchor.prototype.click,original);
});

function checkerPng(){
 const crc=buffer=>{let n=0xffffffff;for(const v of buffer){n^=v;for(let j=0;j<8;j++)n=(n>>>1)^((n&1)?0xedb88320:0);}return(n^0xffffffff)>>>0;};
 const chunk=(name,data)=>{const k=Buffer.from(name),l=Buffer.alloc(4),c=Buffer.alloc(4);l.writeUInt32BE(data.length);c.writeUInt32BE(crc(Buffer.concat([k,data])));return Buffer.concat([l,k,data,c]);};
 const header=Buffer.alloc(13);header.writeUInt32BE(128);header.writeUInt32BE(128,4);header[8]=8;header[9]=6;
 const rows=Buffer.alloc(128*513);for(let y=0;y<128;y++)for(let x=0;x<128;x++){let i=y*513+1+x*4,p=((x>>4)+(y>>4))%2;rows[i]=p?255:20;rows[i+1]=p?120:30;rows[i+2]=p?40:200;rows[i+3]=255;}
 return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',zlib.deflateSync(rows)),chunk('IEND',Buffer.alloc(0))]);
}
const runtime=path.resolve(__dirname,'../gbox-data',manifest.runtime_dir);
const installed=Object.keys(manifest.files).every(name=>fs.existsSync(path.join(runtime,name)));
test('real pinned WASM imports, paints and returns changed PNG through the same-origin popup bridge',{skip:!installed,timeout:180000},async()=>{
 const input=checkerPng();
 const server=http.createServer((req,res)=>{
  const route=new URL(req.url,'http://fixture').pathname;
  if(route==='/'){
   res.setHeader('Content-Type','text/html');res.end(`<!doctype html><style>body{margin:0}iframe{position:fixed;inset:0;border:0;width:100%;height:100%}</style><iframe src="/viz/photocraft-frame.html?webgl#bridge=${nonce}"></iframe><script>window.messages=[];addEventListener('message',e=>{if(e.source!==document.querySelector('iframe').contentWindow||e.origin!==location.origin)return;messages.push(e.data);if(e.data.type==='gbox-photocraft-ready'){let bytes=Uint8Array.from(atob('${input.toString('base64')}'),c=>c.charCodeAt(0)).buffer;e.source.postMessage({type:'gbox-photocraft-open',nonce:'${nonce}',name:'gbox-test.png',mime:'image/png',bytes},location.origin,[bytes]);}})</script>`);return;
  }
  let file,mime;
  if(route.startsWith('/viz/')){const name=route.slice(5);if(!['photocraft-frame.html','photocraft-frame.js'].includes(name)){res.writeHead(404).end();return;}file=path.join(__dirname,'../clients/web/viz',name);mime=name.endsWith('.js')?'text/javascript':'text/html';}
  else if(route.startsWith('/photocraft/runtime/')){const name=route.slice('/photocraft/runtime/'.length);if(!manifest.files[name]){res.writeHead(404).end();return;}file=path.join(runtime,name);mime=manifest.files[name].mime;}
  else {res.writeHead(404).end();return;}
  res.setHeader('Content-Type',mime);res.end(fs.readFileSync(file));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{await withPage(async(evaluate,send)=>{
  await send('Emulation.setDeviceMetricsOverride',{width:1400,height:900,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
  await evaluate(`(async()=>{for(let i=0;i<900;i++){const error=window.messages?.find(m=>m.type==='gbox-photocraft-error');if(error)throw Error(error.message);if(window.messages?.some(m=>m.type==='gbox-photocraft-opened'))return;await new Promise(r=>setTimeout(r,100));}throw Error('PhotoCraft boot timeout')})()`);
  await new Promise(r=>setTimeout(r,1800));
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:520,y:460});await send('Input.dispatchMouseEvent',{type:'mousePressed',x:520,y:460,button:'left',buttons:1,clickCount:1});
  for(let i=0;i<=20;i++){await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:520+i*3,y:460+i*2,button:'left',buttons:1});await new Promise(r=>setTimeout(r,16));}
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:580,y:500,button:'left',clickCount:1});await new Promise(r=>setTimeout(r,300));
  for(const [x,y,hover]of[[57,16,false],[130,385,true],[380,385,false]]){
   if(hover){await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y});await new Promise(r=>setTimeout(r,500));}
   else {await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});await send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});await new Promise(r=>setTimeout(r,300));}
  }
  const result=await evaluate(`(async()=>{for(let i=0;i<100;i++){const result=messages.find(m=>m.type==='gbox-photocraft-export');if(result)return{name:result.name,mime:result.mime,bytes:Array.from(new Uint8Array(result.bytes))};await new Promise(r=>setTimeout(r,100));}throw Error('No exported PNG returned');})()`);
  const output=Buffer.from(result.bytes);assert.equal(result.name,'gbox-test.png');assert.equal(result.mime,'image/png');assert.equal(output.readUInt32BE(16),128);assert.equal(output.readUInt32BE(20),128);assert.notDeepEqual(output,input);assert.ok(output.length>input.length);
 },{timeoutMs:150000,softwareGL:true});}finally{await new Promise(r=>server.close(r));}
});
