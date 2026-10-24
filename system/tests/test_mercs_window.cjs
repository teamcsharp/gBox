'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm');
const {EventEmitter}=require('node:events'),{pathToFileURL}=require('node:url');
const create=require('../clients/desktop/mercs-window.cjs');
const viewer=require('../clients/desktop/mercs-window.js');
const FOLDER=path.resolve(__dirname,'../clients/desktop'),sid='a'.repeat(16)+'-'+'b'.repeat(16),jid='1'.repeat(16),route='2'.repeat(32);
function fixture(t){
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'gbox-mercs-window-'));t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));
  const handlers={},windows=[],calls=[],tokens=[],shell={};let data={games:[]};
  class Window extends EventEmitter{
    constructor(opts){super();this.opts=opts;this.bounds={x:opts.x,y:opts.y,width:opts.width,height:opts.height};this.top=opts.alwaysOnTop;
      const wc=this.webContents=new EventEmitter();wc.mainFrame={};wc.getURL=()=>this.url;wc.send=(...v)=>{this.last=v;};wc.setWindowOpenHandler=f=>this.popups=f;
      wc.session={setPermissionRequestHandler:f=>this.permissions=f};windows.push(this);}
    isDestroyed(){return !!this.dead;}async loadFile(file){this.file=file;this.url=pathToFileURL(file).href;}
    getBounds(){return this.bounds;}getNormalBounds(){return this.bounds;}isAlwaysOnTop(){return this.top;}
    setAlwaysOnTop(v){this.top=v;}show(){this.shown=true;}focus(){this.focused=true;}
    close(){this.emit('close');this.dead=true;this.emit('closed');}
  }
  const manager=create({BrowserWindow:Window,ipcMain:{handle:(k,f)=>handlers[k]=f},userData:temp,folder:FOLDER,
    screen:{getAllDisplays:()=>[{workArea:{x:0,y:0,width:1920,height:1080}}]},
    getOpeningScope:(event,v)=>{if(event.sender!==shell)throw Error('Untrusted shell');return v;},
    getToken:async origin=>{tokens.push(origin);return origin.includes('spark')?'spark-secret':'local-secret';},
    fetch:async(url,opts)=>{calls.push({url,opts});return {ok:true,status:200,json:async()=>typeof data==='function'?data(url,opts):data};}});
  t.after(()=>manager.close());const event=w=>({sender:w.webContents,senderFrame:w.webContents.mainFrame});
  return {manager,handlers,windows,calls,tokens,shell,temp,event,setData:v=>data=v};
}

test('separate sandboxed local window has no game parent, no credential URL and denies navigation/popups',async t=>{
  const f=fixture(t);await f.handlers['mercs-window:open']({sender:f.shell},{origin:'http://spark:8765',sid,mode:'map'});
  const w=f.windows[0];assert.equal(w.opts.parent,undefined);assert.equal(w.opts.webPreferences.sandbox,true);
  assert.equal(w.opts.webPreferences.nodeIntegration,false);assert.equal(w.opts.webPreferences.contextIsolation,true);
  assert.equal(w.opts.webPreferences.webviewTag,false);assert.match(w.file,/mercs-window\.html$/);assert.ok(!w.url.includes('?'));
  assert.equal(w.popups({url:'https://attacker/'}).action,'deny');
  let denied=false;w.webContents.emit('will-navigate',{preventDefault(){denied=true;}},'https://attacker/');assert.equal(denied,true);
  let allowed=null;w.permissions(null,'media',v=>allowed=v);assert.equal(allowed,false);
  assert.deepEqual(f.handlers['mercs-window:info'](f.event(w)),{origin:'http://spark:8765',sid,mode:'map',top:false});
  assert.equal(f.tokens.length,0,'opening the window never obtains or exposes a credential');
  assert.equal(f.manager.owns(w.webContents),true);assert.equal(f.manager.owns({}),false);
});

test('window API stays pinned while shell authority changes, separate authorities never share credentials',async t=>{
  const f=fixture(t);await f.manager.open({origin:'http://spark:8765',sid});await f.manager.open({origin:'http://127.0.0.1:18765'});
  assert.equal(f.windows.length,2);await f.handlers['mercs-window:api'](f.event(f.windows[0]),{path:'/api/mercs/reviewer/catalog'});
  await f.handlers['mercs-window:api'](f.event(f.windows[1]),{path:'/api/mercs/reviewer/catalog'});
  assert.equal(f.calls[0].url,'http://spark:8765/api/mercs/reviewer/catalog');assert.equal(f.calls[0].opts.headers.authorization,'Bearer spark-secret');
  assert.equal(f.calls[1].opts.headers.authorization,'Bearer local-secret');assert.equal(f.calls[0].opts.redirect,'error');
  assert.equal(JSON.stringify(f.handlers['mercs-window:info'](f.event(f.windows[0]))).includes('secret'),false);
  await f.manager.open({origin:'http://spark:8765',sid:'next',mode:'map'});assert.equal(f.windows.length,2);
  assert.equal(f.windows[0].last[1].sid,'next');
});

test('foreign renderer, child frame and navigated renderer cannot access the viewer transport',async t=>{
  const f=fixture(t);await f.manager.open({origin:'http://spark:8765'});const w=f.windows[0];
  assert.throws(()=>f.handlers['mercs-window:info']({sender:{getURL:()=>w.url}}),/Only the owned/);
  assert.throws(()=>f.handlers['mercs-window:info']({sender:w.webContents,senderFrame:{}}),/Only the owned/);
  w.url='https://attacker/';assert.throws(()=>f.handlers['mercs-window:info'](f.event(w)),/Only the owned/);
  assert.throws(()=>f.handlers['mercs-window:open']({sender:{}},{origin:'http://spark'}),/Untrusted shell/);
  assert.equal(f.calls.length,0);
});

test('allowlist permits measured viewer reads but refuses input, launch, foreign jobs and URL tricks',()=>{
  const allow=['/api/mercs/reviewer/catalog','/api/mercs/reviewer/runs?title=BLUS30491','/api/sessions?include_ended=false','/api/sessions?include_ended=true&limit=60',
    '/api/autoplay/tactical/'+sid,'/api/autoplay/tactical/stage/BLUS30491%3Astage'];
  for(const p of allow)assert.equal(create.request({path:p},new Set()).method,'GET');
  for(const p of ['https://attacker/api/sessions','//attacker/api/sessions','/api/jobs/'+jid,'/api/../settings','/api/sessions?token=x','/api/sessions#x','/api/sessions\\x'])
    assert.throws(()=>create.request({path:p},new Set()),/Unsupported/);
  for(const body of [{tool:'launch_game',input:{}},{tool:'autoplay',input:{op:'start'}},{tool:'mercs_team',agent_use:false,input:{session_id:sid,op:'configure',role:'teammate_p2'}}])
    assert.throws(()=>create.request({path:'/api/jobs',body},new Set()),/only select/);
  assert.throws(()=>create.request({path:'/api/sessions/'+sid+'/input',body:{events:[]}},new Set()),/Unsupported/);
  for(const p of ['/api/sessions/'+sid,'/api/sessions/'+sid+'?include_ended=true','/api/sessions/%2e%2e','/api/sessions/'+sid+'/','/api/sessions/'+('x'.repeat(97))])
    assert.throws(()=>create.request({path:p},new Set()),/Unsupported/);
});

test('map collection transport allows observed entity intents and cancellation, never coordinates or input',()=>{
  const p='/api/autoplay/tactical/'+sid+'/goal',body={round:route,stage:'BLUS30491.nav1.abcd',kind:'bonus',id:123,seq:9};
  assert.deepEqual(create.request({path:p,body},new Set()),{path:p,method:'POST',body});
  assert.deepEqual(create.request({path:p,body:{cancel:true}},new Set()).body,{cancel:true});
  for(const patch of [{pos:[0,0,0]},{round:'other'},{id:true},{kind:'enemy'},{seq:NaN}])
    assert.throws(()=>create.request({path:p,body:{...body,...patch}},new Set()),/Invalid map/);
});

test('replacement follows only authoritative same-game links to a listed live session',async()=>{
  const next='new-session',middle='middle-session',calls=[];
  const live={session_id:next,game_id:'RE5',state:'running'};
  const records=[
    {session_id:sid,game_id:'RE5',state:'ended',replaced_by:middle},
    {session_id:middle,game_id:'RE5',state:'ended',replaced_by:next}];
  const result=await viewer.replacement(sid,[live],async p=>{calls.push(p);return records;},()=>true,'RE5');
  assert.equal(result,live);
  assert.deepEqual(calls,['/api/sessions?include_ended=true&limit=60']);
});

test('MercMode follows a different title only with its native terminal rotation receipt',async()=>{
  const from={session_id:'worker-old',game_id:'RE5',state:'ended',replaced_by:'worker-new'};
  const live={session_id:'worker-new',game_id:'RE4',state:'running'};
  const receipt={v:1,source:'native_terminal_reader',round_id:'a'.repeat(32),worker_id:'worker',
    from_game:'RE5',to_game:'RE4',successor_session_id:live.session_id};
  const check=r=>viewer.replacement(from.session_id,[live],async()=>[{...from,mercmode_rotation:r}],()=>true,'RE5');
  assert.equal(await check(receipt),live);
  for(const patch of [{round_id:'invalid'},{worker_id:'foreign'},{source:'telemetry'},
      {to_game:'RE6'},{from_game:'RE6'},{successor_session_id:'other'}])
    assert.equal(await check({...receipt,...patch}),null);
  assert.equal(await check(undefined),null);
  assert.equal(viewer.rotation({},null),false);
});

test('replacement refuses cycles, wrong game, unknown lineage and arbitrary same-game adoption',async()=>{
  const live={session_id:'new-session',game_id:'RE5',state:'running'},old={session_id:sid,game_id:'RE5',state:'ended'};
  const check=record=>viewer.replacement(sid,[live],async()=>[record]);
  assert.equal(await check(old),null);
  assert.equal(await check({...old,replaced_by:sid}),null);
  assert.equal(await check({...old,replaced_by:'http://foreign/session'}),null);
  assert.equal(await check({...old,game_id:undefined,replaced_by:live.session_id}),null);
  assert.equal(await check({...old,game_id:'RE6',replaced_by:live.session_id}),null);
  assert.equal(await check({...old,session_id:'foreign',replaced_by:live.session_id}),null);
  assert.equal(await check({...old,state:'running',replaced_by:live.session_id}),null);
  assert.equal(await viewer.replacement(sid,[live],async()=>[{...old,replaced_by:live.session_id}],()=>true,'RE6'),null);
  let calls=0;
  assert.equal(await viewer.replacement(sid,[live],async()=>{calls++;return [
    {...old,replaced_by:'middle'},{...old,session_id:'middle',replaced_by:sid}];}),null);
  assert.equal(calls,1);
  assert.equal(await viewer.replacement(sid,[{...live,stopping:true}],async()=>[{...old,replaced_by:live.session_id}]),null);
  assert.equal(await viewer.replacement(sid,[live],async()=>({sessions:[old]})),null,'API contract is a history array');
  assert.equal(await viewer.replacement(sid,[live],async()=>[{...old,replaced_by:'missing-intermediate'}]),null);
  assert.equal(await viewer.replacement(sid,[live],async()=>[{...old,replaced_by:'middle'},
    {...old,session_id:'middle',game_id:'RE6',replaced_by:live.session_id}]),null);
});

test('replacement bounds history to sixty records and eight links without following unlisted live rows',async()=>{
  let calls=0;
  const live={session_id:'target',game_id:'RE5',state:'running'},record=(id,next)=>({session_id:id,game_id:'RE5',state:'ended',replaced_by:next});
  const history=Array.from({length:8},(_,i)=>record(i?'step-'+i:sid,i===7?'target':'step-'+(i+1)));
  assert.equal(await viewer.replacement(sid,[live],async()=>{calls++;return history;}),live);
  assert.equal(calls,1);
  history[7].replaced_by='step-8';history.push(record('step-8','target'));
  assert.equal(await viewer.replacement(sid,[live],async()=>history),null);
  assert.equal(await viewer.replacement(sid,[],async()=>[record(sid,'target'),live]),null);
  const oversized=Array.from({length:60},(_,i)=>record('other-'+i,'target'));
  oversized.push(record(sid,'target'));
  assert.equal(await viewer.replacement(sid,[live],async()=>oversized),null,'never use an archive row outside the bounded sixty');
});

function rendererFixture(){
  const nodes=new Map(),maps=[],requests=[];let read=async()=>[],scopeChanged;
  const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',children:[],hidden:false,checked:false,textContent:'',
    replaceChildren(){this.children=[];},append(item){this.children.push(item);},setAttribute(){}});return nodes.get(id);};
  const doc={getElementById:node,createElement:()=>({})};
  const bridge={info:async()=>({origin:'http://spark:8765',sid,mode:'map'}),
    onScope:fn=>{scopeChanged=fn;return()=>{};},alwaysOnTop:async on=>on,
    api:async p=>{requests.push(p);return read(p);}};
  const control=viewer.mount(doc,bridge,{reviewer:null,tactical:{html:id=>id,mount:(_doc,{sid})=>{maps.push(sid);return {stop(){}};},detach(){}},
    setTimer:()=>1,clearTimer(){}});
  return {node,maps,requests,control,setRead:fn=>read=fn,scope:value=>scopeChanged(value)};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('viewer map follows replacement lineage while preserving server and live selector',async()=>{
  const f=rendererFixture(),next='replacement-live';
  const live={session_id:next,game_id:'RE5',state:'running',title:'RE5'};
  f.setRead(async p=>p==='/api/sessions?include_ended=false'?[live]:[{session_id:sid,game_id:'RE5',state:'ended',replaced_by:next}]);
  try{await f.control.ready;await settle();
    assert.deepEqual(f.maps,[sid,next]);assert.equal(f.node('sessions').value,next);
    assert.equal(f.node('authority').textContent,'http://spark:8765');
    assert.deepEqual(f.requests,['/api/sessions?include_ended=false','/api/sessions?include_ended=true&limit=60']);
  }finally{f.control.dispose();}
});

test('manual session selection wins a pending lineage request without another map attachment',async()=>{
  const f=rendererFixture(),manual='manual-live',next='replacement-live';
  const live=id=>({session_id:id,game_id:'RE5',state:'running',title:'RE5'});
  f.setRead(async()=>[live(sid),live(manual)]);
  try{await f.control.ready;await settle();let resolve;
    assert.deepEqual(f.requests,['/api/sessions?include_ended=false'],'live selection never reads history');
    const history=new Promise(yes=>resolve=yes);
    f.setRead(async p=>p==='/api/sessions?include_ended=false'?[live(next),live(manual)]:history);
    const poll=f.control.sessions();await settle();
    f.node('sessions').value=manual;f.node('sessions').onchange();
    resolve([{session_id:sid,game_id:'RE5',state:'ended',replaced_by:next}]);await poll;
    assert.deepEqual(f.maps,[sid,manual]);assert.equal(f.node('sessions').value,manual);
    assert.equal(f.node('authority').textContent,'http://spark:8765');
  }finally{f.control.dispose();}
});

test('practice-route binding requires exact live worker and grants polling only its created job',async t=>{
  const f=fixture(t);await f.manager.open({origin:'http://spark:8765'});const event=f.event(f.windows[0]);
  const body={tool:'mercs_team',agent_use:false,require_worker:'a'.repeat(16),input:{session_id:sid,op:'configure',selected_route_id:route}};
  f.setData([]);await assert.rejects(f.handlers['mercs-window:api'](event,{path:'/api/jobs',body}),/unavailable/);
  f.calls.length=0;f.manager.windows.get('http://spark:8765').jobs.clear();
  f.setData(url=>url.includes('/api/sessions?')?[{session_id:sid,state:'running',worker_id:'a'.repeat(16)}]:{id:jid,state:'queued'});
  const row=f.manager.windows.get('http://spark:8765');
  const response=await f.handlers['mercs-window:api'](event,{path:'/api/jobs',body});
  assert.equal(f.calls.length,2);assert.equal(f.calls[1].opts.method,'POST');
  assert.equal(response.id,jid);assert.equal(row.jobs.has(jid),true);f.setData({id:jid,state:'succeeded'});
  assert.equal((await f.handlers['mercs-window:api'](event,{path:'/api/jobs/'+jid})).state,'succeeded');
  assert.throws(()=>create.request({path:'/api/jobs/'+'f'.repeat(16)},row.jobs),/Unsupported/);
});

test('always-on-top and bounded position persist without touching game or application settings',async t=>{
  const f=fixture(t);await f.manager.open({origin:'http://spark:8765',sid});const w=f.windows[0];
  w.bounds={x:99999,y:99999,width:99999,height:99999};f.handlers['mercs-window:top'](f.event(w),true);w.close();
  const saved=JSON.parse(fs.readFileSync(path.join(f.temp,'mercs-window.json'),'utf8'))['http://spark:8765'];
  assert.equal(saved.top,true);assert.deepEqual(saved.bounds,{x:30,y:30,width:2400,height:1600});
  assert.deepEqual(fs.readdirSync(f.temp),['mercs-window.json']);assert.equal(JSON.stringify(saved).includes('secret'),false);
  await f.manager.open({origin:'http://spark:8765'});assert.equal(f.windows[1].opts.alwaysOnTop,true);
});

test('narrow preload exposes no credential/general IPC and compact/global menus open the viewer',()=>{
  const preload=fs.readFileSync(path.join(FOLDER,'mercs-window-preload.js'),'utf8'),html=fs.readFileSync(path.join(FOLDER,'mercs-window.html'),'utf8');
  assert.match(preload,/exposeInMainWorld\('mercsWindow'/);assert.doesNotMatch(preload,/\.token\(|"token"|'token'|\.settings\(|\.send\(/);
  assert.match(html,/connect-src 'none'/);assert.doesNotMatch(html,/https?:\/\/|[?&](?:token|key)=/);
  const desktop=fs.readFileSync(path.join(FOLDER,'index.html'),'utf8'),main=fs.readFileSync(path.join(FOLDER,'main.js'),'utf8');
  assert.match(desktop,/\["mercs-map",/);assert.match(desktop,/\["mercs-review",/);assert.match(desktop,/id="mercs-reviewer-open"/);
  assert.match(main,/CmdOrCtrl\+Shift\+M/);assert.match(main,/require\('\.\/mercs-window\.cjs'\)/);
  const code=desktop.slice(desktop.indexOf("async function openMercsWindow("),desktop.indexOf("$('#mercmode-open').onclick"));
  const sent=[],button={};const ctx={gbox:{mercsOpen:o=>{sent.push(o);return Promise.resolve();}},S:{apiUrl:'http://spark:8765'},EMB:{authority:'http://spark:8765',sid},COMPACT:{on:false},$:()=>button,toast(){},URL,window:{}};
  vm.runInNewContext(code+';openMercsWindow("map");',ctx);assert.equal(sent[0].sid,sid);assert.equal(sent[0].mode,'map');
  ctx.EMB.authority='http://other';vm.runInNewContext('openMercsWindow("reviewer")',ctx);assert.equal(sent[1].sid,null);
  ctx.EMB.authority='http://spark:8765';ctx.COMPACT={on:true,sid:'stale-metadata'};
  ctx.window.gboxStreamWatchdog={sessionOf:()=>sid};ctx.$=()=>({getAttribute:()=>`http://spark:8765/api/sessions/${sid}/mjpeg`});
  vm.runInNewContext('openMercsWindow("map")',ctx);assert.equal(sent[2].sid,sid,'displayed replacement stream wins over stale cached metadata');
  const hook=main.slice(main.indexOf('app.on("web-contents-created", (_e, wc) => wc.on("before-input-event"'),main.indexOf('// Universal game hotkeys'));
  let handler,events=[];const viewer={on(_event,fn){handler=fn;}},game={on(_event,fn){handler=fn;}};
  const keyContext={app:{on(_event,fn){fn({},viewer);}},mercsWindows:{owns:wc=>wc===viewer},
    win:{webContents:{send:(...v)=>events.push(v)}},GAME_KEYS:{F3:'autoplay'}};
  vm.runInNewContext(hook,keyContext);for(const key of ['F3','F4','F5','Escape','F11'])handler({preventDefault(){}},{key,type:'keyDown'});
  assert.deepEqual(events,[],'viewer key presses cannot toggle autoplay, reload the shell or exit game PiP');
});

test('browser: real reviewer and tactical map mount in their own local window and survive missing sessions',async()=>{
  const {withPage}=require('../scripts/browser_lifecycle.cjs');
  await withPage(async(evaluate,send)=>{
    await send('Page.addScriptToEvaluateOnNewDocument',{source:`window.calls=[];window.scopeValue={origin:'http://spark:8765',sid:${JSON.stringify(sid)},mode:'map',top:false};
      window.sessionLive=[{session_id:scopeValue.sid,game_id:'RE5',state:'running',title:'Resident Evil 5',detail:{worker_name:'lilspark'}}];window.sessionHistory=[];
      window.mercsWindow={info:async()=>scopeValue,onScope:fn=>{window.scopeChanged=fn;return()=>{}},alwaysOnTop:async on=>on,
      api:async p=>{calls.push(p);if(p==='/api/sessions?include_ended=false')return sessionLive;if(p==='/api/sessions?include_ended=true&limit=60')return sessionHistory;
      if(p.endsWith('/catalog'))return {games:[]};if(p.includes('/tactical/stage/'))return {v:1,key:'stage',units:'cm',bounds:[-1000,-1000,1000,1000],points:[],triangles:[],walls:[],links:[]};
      if(p.includes('/tactical/'))return {v:1,seq:1,t:Date.now()/1000,screen:'playing',units:'cm',stage:'stage',player:{pos:[0,0,0],hp:804,hp_max:1000,facing:0},clock:{left:120,score:1234,combo:2},enemies:[],bonuses:[],plan:{phase:'gather_time'}};
      throw Error(p);}};`});
    await send('Page.navigate',{url:pathToFileURL(path.join(FOLDER,'mercs-window.html')).href});
    for(let i=0;i<80&&!await evaluate(`calls.some(p=>p.includes('/tactical/'))`);i++)await new Promise(r=>setTimeout(r,20));
    assert.equal(await evaluate(`document.querySelector('#authority').textContent`),'http://spark:8765');
    assert.equal(await evaluate(`document.querySelector('#live-view').hidden`),false);
    assert.equal(await evaluate(`document.querySelector('#map canvas')!==null`),true);
    assert.equal(await evaluate(`document.querySelector('[data-tm=score]').textContent.includes('1,234')`),true);
    const replacement='c'.repeat(16)+'-'+'d'.repeat(16);
    await evaluate(`sessionHistory=[{session_id:scopeValue.sid,game_id:'RE5',state:'ended',replaced_by:${JSON.stringify(replacement)}}];
      sessionLive=[{session_id:${JSON.stringify(replacement)},game_id:'RE5',state:'running',title:'Resident Evil 5'}];document.querySelector('#refresh').click();`);
    for(let i=0;i<80&&!await evaluate(`document.querySelector('#sessions').value===${JSON.stringify(replacement)}`);i++)await new Promise(r=>setTimeout(r,20));
    assert.equal(await evaluate(`document.querySelector('#sessions').value`),replacement);
    assert.equal(await evaluate(`calls.some(p=>p==='/api/sessions?include_ended=true&limit=60')`),true);
    assert.equal(await evaluate(`calls.some(p=>p.includes('/tactical/'+${JSON.stringify(replacement)}))`),true);
    assert.equal(await evaluate(`calls.some(p=>/^\\/api\\/sessions\\//.test(p))`),false,'no nonexistent detail endpoint');
    await evaluate(`document.querySelector('#top').checked=true;document.querySelector('#top').dispatchEvent(new Event('change'));document.querySelector('#review-tab').click()`);
    for(let i=0;i<80&&!await evaluate(`document.querySelector('.mr-empty')?.textContent.includes('No recorded')`);i++)await new Promise(r=>setTimeout(r,20));
    assert.equal(await evaluate(`document.querySelector('#review-view').hidden`),false);
    assert.equal(await evaluate(`document.querySelector('#top').checked`),true);
    assert.equal(await evaluate(`calls.some(p=>p.includes('/catalog'))`),true);
    await evaluate(`scopeChanged({...scopeValue,sid:null,mode:'map'});`);
    assert.equal(await evaluate(`document.querySelector('#map').children.length`),0);
    assert.equal(await evaluate(`document.querySelector('#map-note').textContent.includes('Choose a session')`),true);
    assert.equal(await evaluate(`calls.some(p=>/input|launch_game|autoplay.*start/.test(p))`),false);
    await evaluate(`dispatchEvent(new Event('pagehide'))`);
  },{timeoutMs:45000});
});
