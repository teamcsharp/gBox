'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,execFile}=require('node:child_process'),readline=require('node:readline');
function findChrome(){
  if(process.env.GBOX_CHROME&&fs.existsSync(process.env.GBOX_CHROME))return process.env.GBOX_CHROME;
  if(process.platform==='win32')for(const p of [path.join(process.env['PROGRAMFILES(X86)']||'','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'','Google/Chrome/Application/chrome.exe')])if(fs.existsSync(p))return p;
  for(const base of [path.join(os.homedir(),'.cache/ms-playwright'),path.join(process.env.LOCALAPPDATA||'','ms-playwright')]){
    if(!fs.existsSync(base))continue;
    for(const dir of fs.readdirSync(base).sort().reverse())if(/^chromium/.test(dir))for(const rel of ['chrome-linux/headless_shell','headless_shell','chrome-linux/chrome','chrome-linux64/chrome','chrome-win/chrome.exe']){
      const p=path.join(base,dir,rel);if(fs.existsSync(p))return p;
    }
  }return null;
}
function python(){
  if(process.env.GBOX_BROWSER_PYTHON)return process.env.GBOX_BROWSER_PYTHON;
  for(const p of [path.join(__dirname,'../.venv/Scripts/python.exe'),path.join(process.env.LOCALAPPDATA||'','Programs/Python/Python312/python.exe'),path.join(__dirname,'../.venv/bin/python')])if(fs.existsSync(p))return p;
  return process.platform==='win32'?'python':'python3';
}
function deadline(p,ms,label){let timer;return Promise.race([p,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(label)),ms);})]).finally(()=>clearTimeout(timer));}
async function withPage(fn,options={}){
  const chrome=options.browser||findChrome();if(!chrome)throw new Error('No Chromium browser installed');
  if(options.signal?.aborted)throw new Error('Browser task cancelled');
  const host=spawn(python(),[path.join(__dirname,'browser_lifecycle.py'),'host','--browser',chrome,...(options.softwareGL?['--software-gl']:[])],
    {stdio:['pipe','pipe','pipe'],windowsHide:true,env:{...process.env,...options.env}});
  let ws,hostError='',closing=false,cleanupError;const waiting=new Map(),events=[];let seq=0;
  let rejectLife;const life=new Promise((_,no)=>{rejectLife=no;});life.catch(()=>{});
  host.stdin.on('error',err=>{if(!closing)rejectLife(err);});
  const exited=new Promise(resolve=>{host.once('exit',(code,signal)=>{resolve({code,signal});if(!closing)rejectLife(new Error('Browser supervisor exited before the task completed'));});host.once('error',err=>{resolve({error:err.message});rejectLife(err);});});
  host.stderr.on('data',b=>{hostError=(hostError+b.toString()).slice(-3000);});
  const lines=readline.createInterface({input:host.stdout});let first=true;
  const ready=new Promise((yes,no)=>{
    host.once('error',no);lines.on('line',line=>{try{const v=JSON.parse(line);if(v.error){no(new Error(v.error));rejectLife(new Error(v.error));}if(v.closed)cleanupError=v.cleanup_error;if(first&&v.ready){first=false;yes(v);}}catch(err){no(err);}});
    host.once('exit',()=>{if(first)no(new Error('Browser startup failed: '+hostError));});
  });
  const abort=()=>rejectLife(new Error('Browser task cancelled'));options.signal?.addEventListener('abort',abort,{once:true});
  const pendingError=err=>{for(const {reject,timer}of waiting.values()){clearTimeout(timer);reject(err);}waiting.clear();};
  const onExit=()=>{closing=true;try{host.stdin.end('close\n');}catch{}};
  process.once('exit',onExit);const interrupted=()=>{onExit();rejectLife(new Error('Browser task interrupted'));};
  process.once('SIGTERM',interrupted);process.once('SIGINT',interrupted);
  try{
    const info=await Promise.race([ready,life]),requestMs=options.requestTimeoutMs||Number(process.env.GBOX_BROWSER_RPC_TIMEOUT_MS||30000);
    const get=async endpoint=>{const r=await fetch(`http://127.0.0.1:${info.port}${endpoint}`,{signal:AbortSignal.timeout(requestMs)});if(!r.ok)throw new Error(`Local browser returned ${r.status}`);return r.json();};
    let page;for(const end=Date.now()+requestMs;!page;){page=(await get('/json/list')).find(t=>t.type==='page'&&t.webSocketDebuggerUrl);if(!page){if(Date.now()>end)throw new Error('No browser page target');await new Promise(r=>setTimeout(r,50));}}
    const endpoint=new URL(page.webSocketDebuggerUrl);
    if(endpoint.hostname!=='127.0.0.1'||+endpoint.port!==info.port||endpoint.protocol!=='ws:')throw new Error('Refusing a nonlocal debugging endpoint');
    ws=new WebSocket(endpoint);
    await Promise.race([deadline(new Promise((yes,no)=>{ws.onopen=yes;ws.onerror=()=>no(new Error('Browser socket failed'));}),requestMs,'Browser socket connection timed out'),life]);
    ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id===undefined){events.push(m.method);if(events.length>200)events.shift();return;}const p=waiting.get(m.id);if(p){clearTimeout(p.timer);waiting.delete(m.id);p.resolve(m);}};
    ws.onclose=()=>{pendingError(new Error('Browser socket closed'));if(!closing)rejectLife(new Error('Browser socket closed'));};
    const send=(method,params={})=>new Promise((resolve,reject)=>{
      const id=++seq,timer=setTimeout(()=>{waiting.delete(id);reject(new Error(`Browser request timed out: ${method}`));},requestMs);
      waiting.set(id,{resolve,reject,timer});try{ws.send(JSON.stringify({id,method,params}));}catch(err){clearTimeout(timer);waiting.delete(id);reject(err);}
    });
    await send('Page.enable');events.length=0;await send('Page.navigate',{url:'about:blank'});
    for(const end=Date.now()+requestMs;!events.includes('Page.loadEventFired');){if(Date.now()>end)throw new Error('Browser page load timed out');await new Promise(r=>setTimeout(r,20));}
    const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.error||r.result?.exceptionDetails)throw new Error(JSON.stringify(r.error||r.result.exceptionDetails));return r.result?.result?.value;};
    return await deadline(Promise.race([Promise.resolve().then(()=>fn(evaluate,send,info)),life]),options.timeoutMs||Number(process.env.GBOX_BROWSER_TIMEOUT_S||600)*1000,'Browser task timed out');
  }finally{
    closing=true;options.signal?.removeEventListener('abort',abort);pendingError(new Error('Browser session closing'));
    if(ws?.readyState===WebSocket.OPEN)try{ws.send(JSON.stringify({id:++seq,method:'Browser.close'}));}catch{}
    try{host.stdin.end('close\n');}catch{}
    try{await deadline(exited,15000,'Browser supervisor shutdown timed out');}catch{host.kill('SIGKILL');await deadline(exited,5000,'Browser supervisor did not exit');}
    ws?.close();lines.close();host.stdin.destroy();host.stdout.destroy();host.stderr.destroy();
    process.removeListener('exit',onExit);process.removeListener('SIGTERM',interrupted);process.removeListener('SIGINT',interrupted);
    if(cleanupError)throw new Error('Browser cleanup needs attention: '+cleanupError);
  }
}
function status(options={}){return new Promise((resolve,reject)=>execFile(python(),[path.join(__dirname,'browser_lifecycle.py'),'status'],{windowsHide:true,env:{...process.env,...options.env},maxBuffer:4*1024*1024,timeout:15000},(err,out)=>{if(err)return reject(err);try{resolve(JSON.parse(out));}catch(e){reject(e);}}));}
module.exports={withPage,findChrome,status};
