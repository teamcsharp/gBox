(function(global){
 'use strict';
 const VERSION='0.9.0',MAX_BYTES=64*1024*1024;
 const RUNTIME='/photocraft/runtime/';
 const JS='photocraft-web-4cc0a6fe355463b6.js',WASM='photocraft-web-4cc0a6fe355463b6_bg.wasm';
 const EXPORTS={png:'image/png',psd:'image/vnd.adobe.photoshop',psb:'image/vnd.adobe.photoshop',pcraft:'application/octet-stream'};
 function nonceOf(hash){const value=new URLSearchParams(String(hash||'').replace(/^#/,'' )).get('bridge')||'';return /^[a-zA-Z0-9_-]{16,128}$/.test(value)?value:'';}
 function fileName(value){return String(value||'texture.png').replace(/^.*[\\/]/,'').replace(/[\x00-\x1f\x7f]/g,'').slice(0,200)||'texture.png';}
 function exportMime(name){return EXPORTS[fileName(name).split('.').pop().toLowerCase()]||'';}
 function validMessage(event,parent,origin,nonce){return !!nonce&&event.source===parent&&event.origin===origin&&event.data?.nonce===nonce;}
 function createBridge(win,options={}){
  const nonce=nonceOf(win.location.hash),origin=win.location.origin,parent=win.parent;
  let ready=false,pending=null,disposed=false;
  const originalClick=win.HTMLAnchorElement.prototype.click;
  const post=(type,fields={},transfer=[])=>{if(!disposed&&nonce&&parent!==win)parent.postMessage({type,nonce,version:VERSION,...fields},origin,transfer);};
  const error=message=>post('gbox-photocraft-error',{message:String(message).slice(0,500)});
  function open(message){
   if(!(message.bytes instanceof win.ArrayBuffer)||!message.bytes.byteLength||message.bytes.byteLength>MAX_BYTES)throw Error('An image or project up to 64 MiB is required.');
   const name=fileName(message.name),data=new win.DataTransfer();
   data.items.add(new win.File([message.bytes],name,{type:message.mime||'application/octet-stream'}));
   const canvas=win.document.querySelector('#photocraft_canvas');if(!canvas)throw Error('PhotoCraft canvas is unavailable.');
   for(const type of ['dragenter','dragover','drop'])canvas.dispatchEvent(new win.DragEvent(type,{bubbles:true,cancelable:true,dataTransfer:data}));
   post('gbox-photocraft-opened',{name});
  }
  const onMessage=event=>{
   if(!validMessage(event,parent,origin,nonce)||event.data.type!=='gbox-photocraft-open')return;
   try{if(!ready){if(!(event.data.bytes instanceof win.ArrayBuffer)||event.data.bytes.byteLength>MAX_BYTES)throw Error('Invalid PhotoCraft image bytes.');pending=event.data;}else open(event.data);}catch(e){error(e.message);}
  };
  // The unmodified upstream browser build exports by clicking a Blob download.
  // Capture supported documents here; other formats keep their normal download.
  function click(){
   const name=fileName(this.download),mime=exportMime(name);
   if(!nonce||!mime||!this.download||!this.href?.startsWith('blob:'))return originalClick.call(this);
   const href=this.href;
   Promise.resolve().then(async()=>{
    const response=await win.fetch(href),blob=await response.blob();
    if(!blob.size||blob.size>MAX_BYTES)throw Error('The exported document exceeds 64 MiB.');
    const bytes=await blob.arrayBuffer();post('gbox-photocraft-export',{name,mime,bytes},[bytes]);
   }).catch(e=>error('Could not return the PhotoCraft export: '+e.message));
  }
  win.HTMLAnchorElement.prototype.click=click;win.addEventListener('message',onMessage);
  return {
   ready(){if(disposed||ready)return;ready=true;post('gbox-photocraft-ready');if(pending){const message=pending;pending=null;try{open(message);}catch(e){error(e.message);}}},
   error,
   dispose(){disposed=true;pending=null;win.removeEventListener('message',onMessage);if(win.HTMLAnchorElement.prototype.click===click)win.HTMLAnchorElement.prototype.click=originalClick;},
  };
 }
 async function start(win){
  const bridge=createBridge(win),loading=win.document.querySelector('#photocraft_loading');
  if(!nonceOf(win.location.hash)){loading.textContent='Open PhotoCraft from the GBox texture editor.';return bridge;}
  let timer;
  try{
   const bindings=await import(RUNTIME+JS);
   await bindings.default({module_or_path:RUNTIME+WASM});
   const boot=Date.now();
   timer=win.setInterval(()=>{
    const notice=win.document.querySelector('#photocraft_loading');
    if(!notice){win.clearInterval(timer);bridge.ready();}
    else if(/failed to start/i.test(notice.textContent)){win.clearInterval(timer);bridge.error(notice.textContent);}
    else if(Date.now()-boot>90000){win.clearInterval(timer);bridge.error('PhotoCraft did not finish starting. Try reopening the editor or enabling WebGL2.');}
   },100);
  }catch(e){loading.textContent='PhotoCraft could not start. '+String(e.message||e);bridge.error(loading.textContent);}
  win.addEventListener('pagehide',()=>{win.clearInterval(timer);bridge.dispose();},{once:true});
  return bridge;
 }
 const api={VERSION,MAX_BYTES,nonceOf,fileName,exportMime,validMessage,createBridge,start};
 if(typeof module==='object'&&module.exports)module.exports=api;
 else {global.GBoxPhotoCraftFrame=api;start(global);}
})(typeof window==='object'?window:globalThis);
