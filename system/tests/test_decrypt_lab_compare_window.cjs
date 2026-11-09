'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {pathToFileURL}=require('node:url');
const C=require('../clients/desktop/decrypt-lab-compare-window.cjs');
const path=require('node:path');
const argv=['--api','http://127.0.0.1:8765','--token-file','known-token','--build','candidate','--animation-index','25'];

function setup(){
  const handlers=new Map(),calls=[];let quits=0;
  class Window extends EventEmitter{
    constructor(options){super();this.options=options;this.destroyed=false;this.webContents=new EventEmitter();this.webContents.mainFrame={};this.webContents.getURL=()=>this.url;
      this.webContents.setWindowOpenHandler=fn=>this.popup=fn;this.webContents.session={setPermissionRequestHandler:fn=>this.permission=fn};}
    isDestroyed(){return this.destroyed;}
    async loadFile(file){this.url=pathToFileURL(file).href;}
    show(){this.shown=true;}
    focus(){this.focused=true;}
  }
  const input={app:{quit:()=>quits++},BrowserWindow:Window,ipcMain:{handle:(key,value)=>handlers.set(key,value),removeHandler:key=>handlers.delete(key)},config:C.options(argv),
    readFile:async()=>{calls.push('read-token');return 'private-token';},fetcher:async(url,init)=>{calls.push({url,init});return {ok:true,json:async()=>({motions:[]})};}};
  return {input,handlers,calls,quits:()=>quits};
}

test('standalone comparison takes an explicit API/token file without credential command-line values',()=>{
  const parsed=C.options(argv);
  assert.equal(parsed.origin,'http://127.0.0.1:8765');assert.equal(parsed.animationIndex,25);
  for(const bad of [[],['--api','https://user:secret@host','--token-file','x'],['--api','https://host/elsewhere','--token-file','x'],[...argv,'--build','../escape'],[...argv,'--token','secret'],[...argv,'--animation-index','-1']])assert.throws(()=>C.options(bad));
});

test('Electron CJS entry detection works without require.main and does not run when imported',()=>{
  const entry=path.resolve(__dirname,'../clients/desktop/decrypt-lab-compare-window.cjs');
  assert.equal(C.isEntry(['gBox.exe',entry],{electron:'38.0.0'}),true);
  assert.equal(C.isEntry(['gBox.exe',entry],{}),false);
  assert.equal(C.isEntry(['gBox.exe',path.resolve(__dirname,'unrelated.cjs')],{electron:'38.0.0'}),false);
});

test('owned standalone window exposes only its read-only comparison route and keeps credentials in main',async()=>{
  const s=setup(),win=await C.open(s.input),event={sender:win.webContents,senderFrame:win.webContents.mainFrame};
  assert.deepEqual([...s.handlers.keys()].sort(),['decrypt-lab:api','decrypt-lab:info']);
  assert.equal(win.shown,true);assert.equal(win.options.webPreferences.sandbox,true);assert.equal(win.options.webPreferences.nodeIntegration,false);
  assert.equal(JSON.stringify(s.handlers.get('decrypt-lab:info')(event)).includes('token'),false);
  const body={title:'re5_switch',arc_path:s.input.config.arcPath,op:'list'};
  assert.deepEqual(await s.handlers.get('decrypt-lab:api')(event,{path:'/api/decrypt-lab/model-compare',body}),{motions:[]});
  assert.equal(s.calls[1].url,'http://127.0.0.1:8765/api/decrypt-lab/model-compare');
  assert.equal(s.calls[1].init.headers.authorization,'Bearer private-token');
  for(const input of [{path:'/api/decrypt-lab/stage',body:{}},{path:'/api/decrypt-lab/state'},{path:'/api/decrypt-lab/model-compare',body:{...body,title:'other'}}])await assert.rejects(()=>s.handlers.get('decrypt-lab:api')(event,input));
  assert.equal(s.calls.length,2,'rejected actions must not read credentials or contact the server');
  assert.throws(()=>s.handlers.get('decrypt-lab:info')({...event,senderFrame:{}}),/Only this comparison/);
  assert.equal(win.popup().action,'deny');
  let denied=false;win.permission(null,'camera',allowed=>denied=!allowed);assert.equal(denied,true);
  let prevented=false;win.webContents.emit('will-navigate',{preventDefault:()=>prevented=true},'https://example.invalid');assert.equal(prevented,true);
  win.emit('closed');assert.equal(s.quits(),1);assert.equal(s.handlers.size,0);
});

test('comparison connection errors preserve actionable API details without exposing tokens',async()=>{
  const s=setup();s.input.fetcher=async()=>({ok:false,status:409,json:async()=>({detail:'Game IK preview needs explicit selection'})});
  const win=await C.open(s.input),event={sender:win.webContents,senderFrame:win.webContents.mainFrame};
  await assert.rejects(()=>s.handlers.get('decrypt-lab:api')(event,{path:'/api/decrypt-lab/model-compare',body:{title:'re5_switch',arc_path:s.input.config.arcPath}}),/409.*Game IK/);
});
