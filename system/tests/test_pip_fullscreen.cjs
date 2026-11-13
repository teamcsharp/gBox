const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname,'../clients/desktop',name),'utf8');
const main=read('main.js'), html=read('index.html'), miniHTML=read('mini.html');
const between=(text,start,end)=>text.slice(text.indexOf(start),text.indexOf(end,text.indexOf(start)));

function fixture() {
  const seen=[], handlers={}, ipc={}, window=()=>({
    webContents:{mainFrame:{},send:(...args)=>seen.push(args)}, fullscreen:false,
    isFullScreen(){return this.fullscreen;},setFullScreen(on){this.fullscreen=on;},
    close(){seen.push(['mini-close']);}, isDestroyed:()=>false,
    bounds:{x:50,y:60,width:640,height:360},getBounds(){return {...this.bounds};},
    setBounds(value){this.bounds={...value};},setAspectRatio(value){this.aspect=value;}
  });
  const win=window(),mini=window(), compact={on:true};
  const ctx={win,mini,compactExplicitExit:false,compactExitSerial:0,miniFloatingBounds:null,miniAspect:16/9,seen,
    compactWindow:{state:()=>compact,restore:async()=>{compact.on=false;seen.push(['exit']);},
      toggleFullScreen:async()=>{win.fullscreen=!win.fullscreen;seen.push(['toggle']);return win.fullscreen;},
      setFullScreen:async on=>{win.fullscreen=on;seen.push(['set',on]);return on;},
      update:state=>{compact.on=state.on;seen.push(['update',state]);return {...compact};}},
    mercsWindows:{owns:()=>false},taskWindows:{owns:()=>false},GAME_KEYS:{F1:'replay',F3:'autoplay'},
    logPush:()=>{},ipcMain:{handle:(name,fn)=>{ipc[name]=fn;}},
    app:{on:(name,fn)=>{if(name==='web-contents-created')for(const wc of [win.webContents,mini.webContents]) fn({},wc);}}
  };
  for(const wc of [win.webContents,mini.webContents])wc.on=(_event,fn)=>handlers[wc===win.webContents?'main':'mini']=fn;
  vm.createContext(ctx);
  vm.runInContext(between(main,'function fullscreenOwner','ipcMain.handle("clip:image"'),ctx);
  vm.runInContext(between(main,'function miniFullscreen','async function openMini'),ctx);
  vm.runInContext(between(main,'app.on("web-contents-created", (_e, wc) => wc.on("before-input-event"','// Universal game hotkeys'),ctx);
  vm.runInContext(between(main,"ipcMain.handle('compact:view'",'function canonicalWorkerExe'),ctx);
  return {ctx,seen,compact,win,mini,ipc,
    press(key,extra={},where='main'){let prevented=0;handlers[where]({preventDefault(){prevented++;}},{type:'keyDown',key,...extra});return prevented;},
    event:owner=>({sender:owner.webContents,senderFrame:owner.webContents.mainFrame})};
}

test('main keyboard route reserves PiP exit for exact Alt+Enter; F11 toggles in place',()=>{
  const x=fixture();
  for(const extra of [{alt:true},{control:true},{shift:true},{meta:true}])x.press('F11',extra);
  for(const extra of [{control:true},{shift:true},{meta:true}])x.press('Enter',{alt:true,...extra});
  x.press('Escape');x.press('F11',{isAutoRepeat:true});x.press('Enter',{alt:true,isAutoRepeat:true});
  assert.deepEqual(x.seen,[]);assert.equal(x.compact.on,true);
  x.press('F11');assert.equal(x.win.fullscreen,true);assert.equal(x.compact.on,true);
  x.press('F11');assert.equal(x.win.fullscreen,false);assert.equal(x.compact.on,true);
  x.press('Enter',{alt:true});assert.equal(x.compact.on,false);assert.equal(x.ctx.compactExplicitExit,true);
  assert.deepEqual(x.seen,[['toggle'],['toggle'],['exit']]);
});

test('mini keyboard toggles only its window and exits only on Alt+Enter',()=>{
  const x=fixture(),floating=x.mini.getBounds();
  x.press('F11',{},'mini');assert.equal(x.mini.fullscreen,true);assert.equal(x.win.fullscreen,false);
  x.mini.bounds={x:0,y:0,width:1920,height:1080};x.press('Escape',{},'mini');
  assert.equal(x.mini.fullscreen,true);
  x.press('F11',{},'mini');assert.deepEqual(x.mini.getBounds(),floating);
  x.press('Enter',{alt:true},'mini');assert.deepEqual(x.seen,[['mini-close']]);
  assert.equal(x.compact.on,true,'the hidden main window is not restored by a mini fullscreen toggle');
});

test('fullscreen IPC accepts only the owning main frame and preserves compact state',async()=>{
  const x=fixture();
  assert.throws(()=>x.ipc['win:toggle-fullscreen']({sender:{}}),/Only the gBox app/);
  assert.throws(()=>x.ipc['win:fullscreen']({sender:x.win.webContents,senderFrame:{}},true),/Only the gBox app/);
  await x.ipc['win:toggle-fullscreen'](x.event(x.win));assert.equal(x.win.fullscreen,true);
  await x.ipc['win:fullscreen'](x.event(x.win),false);assert.equal(x.win.fullscreen,false);
  assert.equal(x.compact.on,true);assert.deepEqual(x.seen,[['toggle'],['set',false]]);
  x.ipc['win:toggle-fullscreen'](x.event(x.mini));assert.equal(x.mini.fullscreen,true);
  assert.equal(x.win.fullscreen,false);
});

test('Alt+Enter during renderer load rejects a delayed saved PiP restoration but allows a new manual entry',async()=>{
  const x=fixture();x.press('Enter',{alt:true});
  const result=await x.ipc['compact:view'](x.event(x.win),{on:true,restoring:true});
  assert.equal(result.on,false);assert.equal(x.compact.on,false);
  assert.equal(x.seen.filter(row=>row[0]==='update').length,0);
  await x.ipc['compact:view'](x.event(x.win),{on:true});assert.equal(x.compact.on,true);
  await x.ipc['compact:view'](x.event(x.win),{on:false,explicit:true});
  assert.equal((await x.ipc['compact:view'](x.event(x.win),{on:true,restoring:true})).on,false);
});

test('failed native and menu exits retain recoverable PiP without suppressing saved restoration',async()=>{
  const x=fixture();x.ctx.compactWindow.restore=async()=>{throw Error('helper unavailable');};
  x.press('Enter',{alt:true});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(x.compact.on,true);assert.equal(x.ctx.compactExplicitExit,false);
  x.ctx.compactWindow.update=async state=>{if(!state.on)throw Error('helper unavailable');return {on:true};};
  await assert.rejects(x.ipc['compact:view'](x.event(x.win),{on:false,explicit:true}),/helper unavailable/);
  assert.equal(x.ctx.compactExplicitExit,false);
  assert.equal((await x.ipc['compact:view'](x.event(x.win),{on:true,restoring:true})).on,true);
});

test('native old and new double-click event names both toggle fullscreen without a PiP exit',async()=>{
  const x=fixture();let config;
  Object.assign(x.ctx,{require:()=>({create:value=>{config=value;return {};}}),hotkeys:{setFront(){}},
    pickWhip(){},screen:{getDisplayMatching:()=>({scaleFactor:1})}});
  vm.runInContext(between(main,"const embedHelper = require('./embed-helper.cjs').create",'function embedCmd'),x.ctx);
  config.onEvent({event:'pipfullscreen'});config.onEvent({event:'piprestore'});
  assert.deepEqual(x.seen,[['toggle'],['toggle']]);assert.equal(x.compact.on,true);
  x.compact.on=false;config.onEvent({event:'piprestore'});assert.equal(x.seen.length,2);
});

test('game picture double-click toggles in either PiP size while panels, fields and modifiers remain inert',()=>{
  const events={}, calls=[],state={on:true};
  vm.runInNewContext(between(html,'gbox.onCompactView?.','setInterval(() => {'),{
    gbox:{onCompactView(){}},compactController:{changed(){}},COMPACT:state,
    GBoxCompactCoach:{isCoachTarget:t=>!!t.coach},compactFullscreen:async()=>calls.push('toggle'),
    compactHover(){},cancelCompactRestoration(){},addEventListener:(name,fn)=>events[name]=fn
  });
  const event=extra=>({target:{closest:()=>null},preventDefault(){},stopPropagation(){},...extra});
  events.dblclick(event());events.dblclick(event());
  for(const key of ['altKey','ctrlKey','shiftKey','metaKey'])events.dblclick(event({[key]:true}));
  events.dblclick(event({target:{closest:()=>({})}}));events.dblclick(event({target:{closest:()=>null,coach:true}}));
  events.keydown?.(event({key:'Escape'}));assert.deepEqual(calls,['toggle','toggle']);
  state.on=false;events.dblclick(event());assert.equal(calls.length,2);
});

test('legacy mini double-click and Escape keep PiP; its explicit context action still exits',()=>{
  const events={},calls=[];
  for(const line of miniHTML.split('\n').filter(line=>line.includes('addEventListener("dblclick"')||line.includes('addEventListener("keydown"')))
    vm.runInNewContext(line,{gbox:{toggleFullScreen:()=>calls.push('toggle'),miniRestore:()=>calls.push('exit')},
      modifierMenu:null,closeModifiers:()=>calls.push('close-menu'),addEventListener:(name,fn)=>events[name]=fn});
  events.dblclick({target:{closest:()=>null},preventDefault(){}});
  events.dblclick({target:{closest:()=>({})},preventDefault(){}});events.keydown({key:'Escape'});
  assert.deepEqual(calls,['toggle']);
  assert.match(miniHTML,/exit\.onclick = \(\) => \{ closeModifiers\(\); gbox\.miniRestore\(\); \}/);
  assert.match(html,/\["exit-pip", "Exit PiP   Alt\+Enter"\]/);
});

test('generic navigation and saved fullscreen preferences cannot exit or resize PiP',()=>{
  const calls=[];const ctx={COMPACT:{on:true},gbox:{setFullScreen:async on=>calls.push(['full',on])},toast:text=>calls.push(['toast',text])};
  vm.runInNewContext(between(html,'function viewAction(a, auto = false)','gbox.onFullscreen?.'),ctx);
  for(const a of ['main','library','home','full'])ctx.viewAction(a,true);
  assert.deepEqual(calls,[]);
  for(const a of ['main','library','home'])ctx.viewAction(a);
  assert.ok(calls.every(row=>row[0]==='toast'));ctx.viewAction('full');
  assert.deepEqual(calls.at(-1),['full',true]);assert.equal(ctx.COMPACT.on,true);
});

test('a replaced mini closing late cannot close or expose the app behind its successor',()=>{
  const line=main.split('\n').find(line=>line.includes('mini.on("closed"'));
  const first={},second={},seen=[];
  const ctx={mini:{on:(_event,fn)=>{ctx.closed=fn;}},miniWindow:first,miniSession:{sid:'second'},miniFloatingBounds:{width:640},
    queueClientView:()=>seen.push('save'),win:{isDestroyed:()=>false,webContents:{send:()=>seen.push('closed')},show:()=>seen.push('show')}};
  vm.createContext(ctx);vm.runInContext(line,ctx);
  ctx.mini=second;ctx.closed();assert.equal(ctx.mini,second);assert.deepEqual(seen,[]);
  ctx.mini=first;ctx.closed();assert.equal(ctx.mini,null);assert.deepEqual(seen,['save','closed','show']);
});
