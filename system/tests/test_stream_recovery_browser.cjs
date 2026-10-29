const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const http=require('node:http');
const {withPage,findChrome}=require('../scripts/browser_lifecycle.cjs');

test('real MJPEG survives failed health polls and reconnect holds the current decoded frame',
  {skip:!findChrome(),timeout:45000},async()=>{
  let frames=[],sequence=0,connections=0;
  const source=fs.readFileSync(require.resolve('../clients/web/viz/stream-watchdog.js'),'utf8');
  const server=http.createServer((req,res)=>{
    if(!req.url.startsWith('/api/sessions/w-s/mjpeg')){res.end('<body style="margin:0"><img id="game" width="320" height="180"></body>');return;}
    connections++;res.writeHead(200,{'content-type':'multipart/x-mixed-replace; boundary=f','cache-control':'no-store'});
    const send=()=>{const frame=frames[Math.min(sequence,frames.length-1)];if(frame&&!res.destroyed)res.write(Buffer.concat([
      Buffer.from('--f\r\nContent-Type: image/jpeg\r\nContent-Length: '+frame.length+'\r\n\r\n'),frame,Buffer.from('\r\n')]));};
    let timer;const delay=setTimeout(()=>{send();timer=setInterval(send,50);},connections>1?500:0);
    res.on('close',()=>{clearTimeout(delay);clearInterval(timer);});
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
  // Do not exhaust the finite frame sequence while the browser supervisor boots.
  const clock=setInterval(()=>{if(connections&&frames.length)sequence++;},50);
  try{await withPage(async(evaluate,send)=>{
    frames=(await evaluate(`Array.from({length:220},(_,i)=>{const c=document.createElement('canvas');c.width=c.height=8;
      const x=c.getContext('2d');x.fillStyle='rgb('+i+',0,0)';x.fillRect(0,0,8,8);return c.toDataURL('image/jpeg',1).split(',')[1];})`))
      .map(s=>Buffer.from(s,'base64'));
    await send('Page.navigate',{url});
    await evaluate(`new Promise(r=>{const ready=()=>document.getElementById('game')?r():setTimeout(ready,10);ready();})`);
    await evaluate(`globalThis.module={exports:{}};${source}\nglobalThis.W=module.exports;delete globalThis.module;
      globalThis.el=document.getElementById('game');el.src='/api/sessions/w-s/mjpeg';
      globalThis.pixel=im=>{const c=document.createElement('canvas');c.width=c.height=1;c.getContext('2d').drawImage(im,0,0,1,1);return c.getContext('2d').getImageData(0,0,1,1).data[0];};
      new Promise(r=>{const ready=()=>el.naturalWidth&&pixel(el)>15?r():setTimeout(ready,20);ready();})`);
    const result=await evaluate(`(async()=>{
      let failHealth=false;
      const healthDog=W.createStreamWatchdog({doc:document,fetchHealth:async()=>{
        if(failHealth)throw Error('health unavailable');return {state:'running',age_s:0.1};
      }});
      await healthDog.checkHealth(el);failHealth=true;
      const src=el.src,start=pixel(el);
      for(let i=0;i<5;i++){await new Promise(r=>setTimeout(r,500));await healthDog.checkHealth(el);}
      const uninterrupted=el.src===src&&!healthDog.state(el).pending&&pixel(el)>start;
      healthDog.stop();
      const before=pixel(el);el.style.backgroundImage='url("data:image/jpeg;base64,${frames[1].toString('base64')}")';
      const dog=W.createStreamWatchdog({doc:document,fetchHealth:null});dog.reconnect(el,'fixture interruption');
      await new Promise((resolve,reject)=>{const end=Date.now()+5000;const ready=()=>dog.state(el).poster?.startsWith('data:')?resolve():Date.now()>end?reject(Error('No held picture')):setTimeout(ready,10);ready();});
      const held=new Image();held.src=dog.state(el).poster;await held.decode();const heldPixel=pixel(held);
      await new Promise((resolve,reject)=>{const end=Date.now()+5000;const ready=()=>el.naturalWidth&&pixel(el)>heldPixel?resolve():Date.now()>end?reject(Error('No newer picture')):setTimeout(ready,20);ready();});
      const after=pixel(el);dog.stop();return {before,held:heldPixel,after,uninterrupted};})()`);
    assert.equal(result.uninterrupted,true,'failed health checks must not reconnect moving MJPEG');
    assert.ok(result.held>=result.before-2,JSON.stringify(result));
    assert.ok(result.held>10,'the old cached still must not be the reconnect picture');
    assert.ok(result.after>result.held,JSON.stringify(result));
  },{timeoutMs:30000});}finally{clearInterval(clock);server.closeAllConnections();await new Promise(r=>server.close(r));}
});
