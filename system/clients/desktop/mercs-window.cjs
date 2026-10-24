'use strict';
// This local window owns no emulator and never receives an API credential.
const path=require('node:path'),fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const SID=/^[A-Za-z0-9_-]{1,96}$/,RID=/^[0-9a-f]{32}$/,JID=/^(?:[0-9a-f]{16}|[0-9a-f]{32})$/;
function origin(value){try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?u.origin:null;}catch{return null;}}
function scope(value){const server=origin(value?.origin);if(!server)throw Error('Choose a connected gBox server first.');
  const sid=value?.sid||null;if(sid!==null&&(!SID.test(sid)||typeof sid!=='string'))throw Error('Invalid game session.');
  return {origin:server,sid,mode:value?.mode==='map'?'map':'reviewer'};}
function placement(value,displays=[]){
  const w=Math.round(Math.max(640,Math.min(2400,Number(value?.width)||1240))),h=Math.round(Math.max(440,Math.min(1600,Number(value?.height)||850)));
  let x=Math.round(Number(value?.x)||100),y=Math.round(Number(value?.y)||100);
  if(!Number.isFinite(x)||!Number.isFinite(y)||Math.abs(x)>100000||Math.abs(y)>100000)x=y=100;
  const areas=displays.map(d=>d.workArea||d.bounds||d).filter(a=>[a.x,a.y,a.width,a.height].every(Number.isFinite));
  if(areas.length&&!areas.some(a=>Math.min(x+w,a.x+a.width)-Math.max(x,a.x)>=100&&Math.min(y+h,a.y+a.height)-Math.max(y,a.y)>=80)){
    x=areas[0].x+30;y=areas[0].y+30;
  }
  return {x,y,width:w,height:h};
}
function request(value,ownedJobs){
  if(!value||typeof value.path!=='string'||value.path.length>4096||!value.path.startsWith('/api/')||value.path.includes('\\'))throw Error('Unsupported viewer request.');
  const u=new URL(value.path,'http://viewer.invalid');
  if(u.origin!=='http://viewer.invalid'||u.hash||u.pathname!==value.path.split('?')[0]||/[\u0000-\u001f]/.test(value.path)
      ||[...u.searchParams.keys()].some(k=>/token|authorization/i.test(k)))throw Error('Unsupported viewer request.');
  const method=String(value.method||(value.body===undefined?'GET':'POST')).toUpperCase(),p=u.pathname;
  const read=/^\/api\/mercs\/reviewer\/(catalog|runs|round|live)$/.test(p)||p==='/api/sessions'
    ||/^\/api\/autoplay\/tactical\/(?:stage\/)?[A-Za-z0-9_:%.-]{1,180}$/.test(p);
  const job=/^\/api\/jobs\/((?:[0-9a-f]{16}|[0-9a-f]{32}))$/.exec(p);
  if(method==='GET'&&value.body===undefined&&(read||p==='/api/jobs'||job&&ownedJobs.has(job[1])))return {path:u.pathname+u.search,method};
  if(method==='POST'&&/^\/api\/autoplay\/tactical\/[A-Za-z0-9_-]{1,96}\/goal$/.test(p)){
    const b=value.body;
    if(!b||typeof b!=='object'||JSON.stringify(b).length>2048
      ||!(b.cancel===true&&Object.keys(b).length===1
        ||Object.keys(b).length===5&&Object.keys(b).every(k=>['round','stage','kind','id','seq'].includes(k))
          &&RID.test(b.round||'')&&/^[A-Za-z0-9._-]{1,120}$/.test(b.stage||'')
          &&['bonus','item'].includes(b.kind)&&Number.isSafeInteger(b.id)&&Number.isSafeInteger(b.seq)&&b.seq>0))
      throw Error('Invalid map collection goal.');
    return {path:p,method,body:b};
  }
  if(method==='POST'&&(/^\/api\/mercs\/reviewer\/(suggestions|demonstrations)$/.test(p)
      ||/^\/api\/mercs\/reviewer\/demonstrations\/[0-9a-f]{32}\/adopt$/.test(p))){
    if(!value.body||typeof value.body!=='object'||JSON.stringify(value.body).length>2*1024*1024)throw Error('Invalid route request.');
    return {path:p,method,body:value.body};
  }
  if(method==='POST'&&p==='/api/jobs'){
    const b=value.body,i=b?.input;
    if(b?.tool!=='mercs_team'||b.agent_use!==false||!i||!SID.test(i.session_id||'')
      ||!['status','configure'].includes(i.op)||Object.keys(b).some(k=>!['tool','input','require_worker','agent_use'].includes(k))
      ||Object.keys(i).some(k=>!['session_id','op','selected_route_id'].includes(k))
      ||i.op==='configure'&&!RID.test(i.selected_route_id||'')||i.op==='status'&&i.selected_route_id!==undefined)
      throw Error('This viewer can only select a validated practice route.');
    return {path:p,method,body:b,session:i.session_id};
  }
  throw Error('Unsupported viewer request.');
}
module.exports=function({BrowserWindow,ipcMain,getOpeningScope,getToken,fetch:fetcher=globalThis.fetch,userData,screen,
                         folder=__dirname,setTimer=setTimeout,clearTimer=clearTimeout}){
  const windows=new Map(),stateFile=path.join(userData,'mercs-window.json'),file=path.join(folder,'mercs-window.html');
  const fileURL=pathToFileURL(file).href;let saved={};
  try{if(fs.statSync(stateFile).size<16384){const value=JSON.parse(fs.readFileSync(stateFile,'utf8'));if(value&&typeof value==='object'&&!Array.isArray(value))saved=value;}}catch{}
  function rowOf(event){const row=[...windows.values()].find(r=>!r.win.isDestroyed()&&event.sender===r.win.webContents);
    if(!row||(event.senderFrame&&event.senderFrame!==row.win.webContents.mainFrame)||event.sender.getURL()!==fileURL)
      throw Error('Only the owned Mercenaries window can make this request.');return row;}
  function persist(row){if(row.win.isDestroyed())return;const b=row.win.getNormalBounds?.()||row.win.getBounds();
    saved[row.scope.origin]={bounds:placement(b,screen?.getAllDisplays?.()||[]),top:row.win.isAlwaysOnTop()};
    const tmp=stateFile+'.tmp';try{fs.mkdirSync(userData,{recursive:true});fs.writeFileSync(tmp,JSON.stringify(saved),{mode:0o600});fs.renameSync(tmp,stateFile);}catch{try{fs.unlinkSync(tmp);}catch{}}}
  function notify(row){row.win.webContents.send('mercs-window:scope',{...row.scope,top:row.win.isAlwaysOnTop()});}
  async function open(value){const target=scope(value);let row=windows.get(target.origin);
    if(row&&!row.win.isDestroyed()){row.scope=target;notify(row);row.win.show();row.win.focus();return {opened:true,...target};}
    const prefs=saved[target.origin]||{},bounds=placement(prefs.bounds,screen?.getAllDisplays?.()||[]);
    const win=new BrowserWindow({...bounds,minWidth:640,minHeight:440,show:false,title:'gBox · Mercenaries',backgroundColor:'#11151c',
      alwaysOnTop:prefs.top===true,webPreferences:{preload:path.join(folder,'mercs-window-preload.js'),
      contextIsolation:true,sandbox:true,nodeIntegration:false,webviewTag:false,backgroundThrottling:false,partition:'mercs-window'}});
    row={win,scope:target,jobs:new Set(),timer:null};windows.set(target.origin,row);
    win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    win.webContents.on('will-navigate',(event,url)=>{if(url!==fileURL)event.preventDefault();});
    win.webContents.on('will-attach-webview',event=>event.preventDefault());
    win.webContents.session?.setPermissionRequestHandler?.((_wc,_permission,reply)=>reply(false));
    for(const event of ['move','resize'])win.on(event,()=>{if(row.timer)clearTimer(row.timer);row.timer=setTimer(()=>{row.timer=null;persist(row);},250);});
    win.on('close',()=>persist(row));win.on('closed',()=>{if(row.timer)clearTimer(row.timer);if(windows.get(target.origin)===row)windows.delete(target.origin);});
    await win.loadFile(file);if(!win.isDestroyed()){notify(row);win.show();}return {opened:true,...target};
  }
  async function api(row,input){const q=request(input,row.jobs),server=row.scope.origin,credential=await getToken(server);
    if(!credential)throw Error('This server is reconnecting. The game was not changed.');
    const read=async(path,method='GET',body)=>{const r=await fetcher(server+path,{method,redirect:'error',
      headers:{authorization:'Bearer '+credential,'content-type':'application/json'},
      ...(body!==undefined?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000)});
      if(!r.ok){let detail='';try{const v=await r.json();if(typeof v.detail==='string')detail=': '+v.detail.slice(0,240);}catch{}
        throw Error('Viewer request failed ('+r.status+')'+detail);}return r.json();};
    if(q.session){const sessions=await read('/api/sessions?include_ended=false'),session=sessions.find(s=>s.session_id===q.session&&s.state==='running');
      if(!session||(session.worker_id||q.session.split('-')[0])!==q.body.require_worker)throw Error('The selected live session is unavailable on this server.');}
    const value=await read(q.path,q.method,q.body);
    if(q.method==='POST'&&q.path==='/api/jobs'&&JID.test(value?.id||''))row.jobs.add(value.id);
    if(q.method==='GET'&&q.path.split('?')[0]==='/api/jobs'&&Array.isArray(value))return value.map(j=>({id:j.id,tool:j.tool,state:j.state,input:{session_id:j.input?.session_id}}));
    return value;
  }
  ipcMain.handle('mercs-window:open',(event,value)=>open(getOpeningScope(event,value)));
  ipcMain.handle('mercs-window:info',event=>{const r=rowOf(event);return {...r.scope,top:r.win.isAlwaysOnTop()};});
  ipcMain.handle('mercs-window:api',(event,value)=>api(rowOf(event),value));
  ipcMain.handle('mercs-window:top',(event,top)=>{const r=rowOf(event);r.win.setAlwaysOnTop(top===true);persist(r);return r.win.isAlwaysOnTop();});
  return {open,owns(wc){return [...windows.values()].some(r=>!r.win.isDestroyed()&&r.win.webContents===wc);},
    close(){for(const r of windows.values())if(!r.win.isDestroyed())r.win.close();},windows};
};
module.exports.origin=origin;module.exports.scope=scope;module.exports.placement=placement;module.exports.request=request;
