'use strict';
// A comparison-only Electron entry point. It deliberately never imports main.js.
// Existing runtime: gBox.exe <this-file> --token-file <path> [--build <name>] --api <origin>
// On Windows keep the API URL last: Electron refuses subsequent switches before loading the entry.
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {request}=require('./decrypt-lab.cjs');
const ARC='nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc';
const NAME=/^[A-Za-z0-9_.-]{1,64}$/;

function options(argv){
  const out={title:'re5_switch',build:'',arcPath:ARC};
  const keys=new Set(['api','token-file','build','title','animation-entry','animation-index']);
  for(let i=0;i<argv.length;i++){
    const key=argv[i].replace(/^--/,'');
    if(!argv[i].startsWith('--')||!keys.has(key)||!argv[i+1]||argv[i+1].startsWith('--'))throw Error('Use --token-file <path>, an optional --build <name>, then --api <origin> last.');
    const value=argv[++i];
    if(key==='api')out.origin=value;
    else if(key==='token-file')out.tokenFile=path.resolve(value);
    else if(key==='animation-entry'||key==='animation-index'){
      if(!/^\d+$/.test(value)||Number(value)>65535)throw Error('Animation indices must be bounded whole numbers.');
      out[key==='animation-entry'?'animationEntry':'animationIndex']=Number(value);
    }else out[key]=value;
  }
  let origin;try{origin=new URL(out.origin);}catch{throw Error('Choose the existing gBox API origin with --api.');}
  if(!/^https?:$/.test(origin.protocol)||origin.username||origin.password||origin.pathname!=='/'||origin.search||origin.hash)throw Error('The API must be an HTTP(S) origin without a path or credentials.');
  out.origin=origin.origin;
  if(!out.tokenFile)throw Error('Choose the existing API token file with --token-file.');
  if(!NAME.test(out.title)||(out.build&&!NAME.test(out.build)))throw Error('Invalid title or candidate build.');
  return out;
}

async function open({app,BrowserWindow,ipcMain,config,fetcher=globalThis.fetch,readFile=fs.promises.readFile,folder=__dirname}){
  const file=path.join(folder,'decrypt-lab-compare-window.html'),fileURL=pathToFileURL(file).href;
  const win=new BrowserWindow({width:1450,height:1000,minWidth:900,minHeight:640,show:false,
    title:'gBox · Model comparison',backgroundColor:'#101822',autoHideMenuBar:true,
    webPreferences:{preload:path.join(folder,'decrypt-lab-preload.js'),contextIsolation:true,sandbox:true,
      nodeIntegration:false,webviewTag:false,backgroundThrottling:false,partition:'model-comparison-window'}});
  const owned=event=>{if(win.isDestroyed()||event.sender!==win.webContents||(event.senderFrame&&event.senderFrame!==win.webContents.mainFrame)||event.sender.getURL()!==fileURL)throw Error('Only this comparison window can read its models.');};
  ipcMain.handle('decrypt-lab:info',event=>{owned(event);return {origin:config.origin,title:config.title,arcPath:config.arcPath,build:config.build,animationEntry:config.animationEntry,animationIndex:config.animationIndex};});
  ipcMain.handle('decrypt-lab:api',async(event,input)=>{
    owned(event);
    const q=request(input);
    if(q.path!=='/api/decrypt-lab/model-compare'||q.method!=='POST'||q.body.title!==config.title||q.body.arc_path!==config.arcPath)throw Error('This window only reads its model comparison.');
    const token=String(await readFile(config.tokenFile,'utf8')).trim();
    if(!token||token.length>16384)throw Error('The selected API token file is empty or invalid.');
    const response=await fetcher(config.origin+q.path,{method:'POST',redirect:'error',headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:JSON.stringify(q.body),signal:AbortSignal.timeout(60000)});
    if(!response.ok){let detail='';try{const body=await response.json();if(typeof body.detail==='string')detail=': '+body.detail.slice(0,400);}catch{}throw Error('Comparison request failed ('+response.status+')'+detail);}
    return response.json();
  });
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',(event,url)=>{if(url!==fileURL)event.preventDefault();});
  win.webContents.on('will-attach-webview',event=>event.preventDefault());
  win.webContents.session?.setPermissionRequestHandler?.((_wc,_permission,reply)=>reply(false));
  win.on('closed',()=>{ipcMain.removeHandler('decrypt-lab:info');ipcMain.removeHandler('decrypt-lab:api');app.quit();});
  await win.loadFile(file);
  if(!win.isDestroyed()){win.show();win.focus();}
  return win;
}

async function run(electron,argv=process.argv.slice(2)){
  const config=options(argv),{app}=electron;
  // Isolated ownership: no running desktop profile, settings, process or worker is adopted.
  app.setPath('userData',fs.mkdtempSync(path.join(app.getPath('temp'),'gbox-model-compare-')));
  app.setName('gBox Model comparison');
  app.on('window-all-closed',()=>app.quit());
  await app.whenReady();
  return open({...electron,config});
}

function isEntry(argv=process.argv,versions=process.versions){
  // Electron 38 imports a CJS app entry through ESM, where require.main is undefined.
  return !!versions.electron&&typeof argv[1]==='string'&&path.resolve(argv[1])===__filename;
}
module.exports={options,open,run,isEntry};
if(require.main===module||isEntry()){const electron=require('electron');run(electron).catch(error=>{electron.dialog.showErrorBox('Model comparison',error.message);electron.app.quit();});}
