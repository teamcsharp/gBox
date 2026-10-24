/* Measured Mercenaries playback, independent of a running game. No gameplay control requests. */
(function(root){
  'use strict';
  const BASE='/api/mercs/reviewer', colors=['#50d9e8','#b19bff','#f3cb70','#82d89d','#eb9ece'];
  const finite=v=>typeof v==='number'&&Number.isFinite(v), xyz=p=>Array.isArray(p)&&p.length===3&&p.every(finite);
  const clock=t=>{t=Math.max(0,Number(t)||0);return `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;};
  const measuredGeometry=data=>!!data?.geometry&&data.geometry.geometry_available!==false;
  function playersOf(frame){return Array.isArray(frame?.players)?frame.players.filter(p=>p&&typeof p.id==='string').map(p=>({...p,control:['human','bot'].includes(p.control)?p.control:'unknown'})):frame?.player?[{...frame.player,id:'legacy',control:'unknown'}]:[];}
  function playerOf(frame,id){return playersOf(frame).find(p=>p.id===id);}
  function assistanceLabel(value){return value?.verified===true&&value.classification==='unmodified'?'Unmodified':value?.classification==='mod_assisted'?'Mod-assisted':'Modification status unknown';}
  function rangeAssistance(samples){const labels=new Set(samples.map(s=>assistanceLabel(s.frame?.assistance)));return labels.has('Mod-assisted')?{classification:'mod_assisted',verified:samples.every(s=>s.frame?.assistance?.verified===true)}:labels.size===1&&labels.has('Unmodified')?{classification:'unmodified',verified:true}:{classification:'unknown',verified:false};}
  function sampleIndex(samples,at){let lo=0,hi=samples.length;while(lo<hi){const mid=(lo+hi)>>>1;if(samples[mid].at<=at)lo=mid+1;else hi=mid;}return Math.max(0,lo-1);}
  function playbackFrame(samples,at){
    if(!samples.length)return null;const i=sampleIndex(samples,at),a=samples[i],b=samples[i+1],frame=a.frame||{};
    if(!b||b.at-a.at<=0||b.at-a.at>2||(frame.units_per_m||100)!==(b.frame.units_per_m||100))return frame;
    const nativeScale=frame.units_per_m===1000?10:1;
    const f=Math.max(0,Math.min(1,(at-a.at)/(b.at-a.at))),lerp=(p,q)=>p.map((v,k)=>v+(q[k]-v)*f);
    const interpolate=(p,n)=>n&&xyz(p?.pos)&&xyz(n.pos)&&p.actor===n.actor&&p.control===n.control&&Math.hypot(...p.pos.map((v,k)=>v-n.pos[k]))<=(800*(b.at-a.at)+30)*nativeScale?{...p,pos:lerp(p.pos,n.pos)}:p;
    const next=new Map((b.frame.enemies||[]).map(e=>[String(e.id),e]));
    const nextPlayers=new Map(playersOf(b.frame).map(p=>[p.id,p]));
    return {...frame,player:frame.player?interpolate(frame.player,b.frame.player):undefined,
      ...(Array.isArray(frame.players)?{players:playersOf(frame).map(p=>interpolate(p,nextPlayers.get(p.id)))}:{}),enemies:(frame.enemies||[]).map(e=>{
      const n=next.get(String(e.id));return n&&xyz(e.pos)&&xyz(n.pos)&&Math.hypot(...e.pos.map((v,k)=>v-n.pos[k]))<=(800*(b.at-a.at)+30)*nativeScale?{...e,pos:lerp(e.pos,n.pos)}:e;})};
  }
  function sameGeometry(runs,selected){return runs.filter(r=>r.title===selected?.title&&r.geometry===selected?.geometry);}
  function appendSamples(old,incoming){const ids=new Set(old.map(s=>s.seq));return old.concat(incoming.filter(s=>!ids.has(s.seq))).sort((a,b)=>a.seq-b.seq);}
  function geometryPoints(geometry){const points=geometry?.points||[],used=new Set((geometry?.triangles||[]).flat());return [...used].map(i=>points[i]).filter(xyz);}
  function transform(points,width,height,zoom=1,pan=[0,0]){
    const good=points.filter(xyz),xs=good.map(p=>p[0]),zs=good.map(p=>p[2]);
    const x0=good.length?Math.min(...xs):0,x1=good.length?Math.max(...xs):100,z0=good.length?Math.min(...zs):0,z1=good.length?Math.max(...zs):100;
    const scale=Math.min((width-50)/Math.max(1,x1-x0),(height-50)/Math.max(1,z1-z0))*zoom,cx=(x0+x1)/2,cz=(z0+z1)/2;
    return {point:p=>[width/2+pan[0]+(p[0]-cx)*scale,height/2+pan[1]-(p[2]-cz)*scale],world:(x,y,h)=>[cx+(x-width/2-pan[0])/scale,h,cz-(y-height/2-pan[1])/scale],scale};
  }
  function mount(host,{api,visible=()=>true}={}){
    const doc=host.ownerDocument;let dead=false,revision=0,raf=0,poll=0,feed=0,busy=false,liveBusy=false,pollBusy=false,lastPoll=0,liveFrame=null,liveStats=null,liveSource=null;
    let games=[],runs=[],current=null,data=null,samples=[],events=[],at=0,playing=false,speed=1,live=true,lastRaf=0;
    let drawn=[],editing=false,drag=null,zoom=1,pan=[0,0],background=null,mapTransform=null,lastSide=0,saveBusy=false,teachBusy=false,fromMark=null,toMark=null,playerChoices='',sessions=[],sessionBusy=false,binding=false;
    const adoptionBusy=new Set();
    const el=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
    const button=(label,fn)=>{const n=el('button','act',label);n.type='button';n.onclick=fn;return n;};
    const select=()=>el('select'),box=()=>{const n=el('input');n.type='checkbox';return n;};
    const text=(n,s)=>{n.textContent=s==null?'—':String(s);};
    host.classList.add('mercs-reviewer');host.replaceChildren();
    const heading=el('div','mr-heading'),title=el('div'),status=el('div','mr-status','Loading recorded runs…');
    title.append(el('h1',null,'Mercenaries run reviewer'),el('p',null,'Recorded routes, decisions and outcomes. Available with or without a game running.'));heading.append(title,status);
    const filters=el('div','mr-filters'),game=select(),stage=select(),character=select(),count=select(),player=select(),liveInput=box();liveInput.checked=true;
    function labeled(name,input){const label=el('label',null,name);label.append(input);filters.append(label);}
    labeled('Game',game);labeled('Stage / geometry',stage);labeled('Character',character);labeled('Path history',count);
    labeled('Recorded player',player);player.className='mr-player-select';player.onchange=()=>{fromMark=toMark=null;background=null;render();};
    [1,5,10,20,100].forEach(n=>count.add(new Option(`Last ${n} run${n===1?'':'s'}`,String(n))));count.value='20';
    const liveLabel=el('label','mr-live');liveLabel.append(liveInput,doc.createTextNode('Follow live run'));filters.append(liveLabel,button('Refresh',()=>refresh(true)));
    const error=el('div','mr-error');error.hidden=true;
    const layout=el('div','mr-layout'),list=el('div','mr-list'),center=el('div','mr-center'),side=el('aside','mr-sidebar');
    const mapWrap=el('div','mr-map-wrap'),canvas=el('canvas','mr-map'),mapNote=el('div','mr-map-note','Choose a recorded run'),legend=el('div','mr-legend');
    for(const [label,color] of [['Human','#50d9e8'],['Bot','#b19bff'],['Unknown control','#b7c1cd'],['Enemies','#ff8282'],['Time bonus','#f3cb70'],['Mine','#82d89d']]){const span=el('span'),dot=el('i');dot.style.background=color;span.append(dot,doc.createTextNode(label));legend.append(span);}
    mapWrap.append(canvas,mapNote,legend);const ctx=canvas.getContext('2d');
    const controls=el('div','mr-controls'),play=button('Play',()=>{live=false;liveInput.checked=false;playing=!playing;if(playing&&at>=end())at=start();text(play,playing?'Pause':'Play');});
    const seek=el('input');seek.type='range';seek.min='0';seek.max='1000';seek.value='0';seek.setAttribute('aria-label','Playback position');
    const elapsed=el('span','mr-time','0:00 / 0:00'),rate=select();[.25,.5,1,2,4,8].forEach(v=>rate.add(new Option(`${v}×`,v)));rate.value='1';rate.setAttribute('aria-label','Playback speed');
    controls.append(play,seek,elapsed,rate,button('Fit map',()=>{zoom=1;pan=[0,0];background=null;render();}));rate.onchange=()=>speed=+rate.value;seek.oninput=()=>{live=false;liveInput.checked=false;at=start()+(end()-start())*(+seek.value/1000);render();};
    const kpis=el('div','mr-kpis'),values={};for(const key of ['Score','Combo','HP','Clock']){const card=el('div','mr-kpi'),value=el('b',null,'—');card.append(el('small',null,key),value);values[key]=value;kpis.append(card);}
    const chart=el('canvas','mr-chart'),chartKey=el('div','mr-chart-key');chartKey.append(el('span',null,'Score · cyan'),el('span',null,'HP · red'),el('span',null,'Combo · gold'),el('span',null,'Each series scaled independently · click to seek'));
    chart.onclick=e=>{const rect=chart.getBoundingClientRect();live=false;liveInput.checked=false;at=start()+(end()-start())*Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width));render();};
    const editbar=el('div','mr-editbar'),draw=button('Draw suggested route',()=>{editing=!editing;draw.classList.toggle('on',editing);canvas.style.cursor=editing?'crosshair':'default';});
    const floor=el('input');floor.type='number';floor.step='10';floor.value='0';floor.setAttribute('aria-label','Suggested route floor height');
    const name=el('input');name.type='text';name.placeholder='Route name';name.setAttribute('aria-label','Suggested route name');
    const floorLabel=el('label',null,'Route floor Y');floorLabel.append(floor);
    const save=button('Validate & save',saveSuggestion),clear=button('Clear',()=>{drawn=[];validation.textContent='';render();});
    editbar.append(draw,floorLabel,name,clear,save);const validation=el('div','mr-validation','Drag to draw; drag a point to adjust. Suggestions are checked against this exact geometry before use.');
    const teachbar=el('div','mr-teachbar'),teachTitle=el('strong',null,'Teach from a recorded human run'),selection=el('span','mr-selection'),assist=el('span','mr-assistance');
    const markStart=button('Mark start',()=>{fromMark=samples[sampleIndex(samples,at)]?.seq??null;if(toMark!=null&&fromMark>=toMark)toMark=null;render();}),markEnd=button('Mark end',()=>{toMark=samples[sampleIndex(samples,at)]?.seq??null;if(fromMark!=null&&fromMark>=toMark)fromMark=null;render();});
    const teach=button('Teach this route / have bot practice',teachRoute);teach.classList.add('mr-teach');
    teachbar.append(teachTitle,assist,selection,markStart,markEnd,button('Use entire run',()=>{fromMark=toMark=null;render();}),teach);
    const teachingNote=el('div','mr-teaching-note'),demonstrations=el('div','mr-demonstrations');
    const sessionbar=el('div','mr-sessionbar'),sessionTarget=select(),sessionNote=el('span','mr-session-note','Saved routes can be practiced when a matching game session is running.');
    sessionTarget.className='mr-session-select';sessionTarget.setAttribute('aria-label','Session for route practice');sessionTarget.add(new Option('Choose a matching live session',''));
    sessionTarget.onchange=()=>renderDemonstrations();sessionbar.append(sessionTarget,button('Find live sessions',findSessions),sessionNote);
    const eventTitle=el('small','mut','Recorded events'),eventList=el('div','mr-events');center.append(mapWrap,controls,kpis,chart,chartKey,teachbar,teachingNote,sessionbar,demonstrations,editbar,validation,eventTitle,eventList);
    side.append(el('h3',null,'Tracked state & provenance'));const sections=new Map();
    for(const key of ['Player','All players','Assistance & teaching','Clock','Plan','Enemies','Bonuses','Mines','Inputs & prompt','Live diagnostics','Run review','Round learning','Navigation & mine learning','Vector evidence','Source IDs']){
      const detail=el('details'),summary=el('summary',null,key),content=el('div');detail.append(summary,content);detail.open=['Player','Clock'].includes(key);detail.ontoggle=()=>renderSide(true);side.append(detail);sections.set(key,{detail,content});
    }
    side.append(button('Inspect complete reviewer payload',()=>inspect('Complete reviewer payload',{run:current,frame:frame(),frame_source:live&&liveFrame?liveSource:{source_id:current?.source_id,recorded:true},notebook:data?.notebook,review:current?.review,provenance:data?.provenance},'Recorded and current live sources are identified separately')));
    layout.append(list,center,side);const empty=el('div','mr-empty');empty.hidden=true;host.append(heading,filters,error,empty,layout);
    const dialog=el('dialog','mr-dialog'),dialogTitle=el('h3'),dialogSource=el('p'),raw=el('pre');dialog.append(dialogTitle,dialogSource,raw,button('Close',()=>dialog.close()));host.append(dialog);
    function inspect(label,value,source){text(dialogTitle,label);text(dialogSource,source);raw.textContent=JSON.stringify(value,null,2);dialog.showModal();}
    function fail(err){if(dead)return;error.hidden=false;error.textContent=String(err?.message||err);}
    function start(){return samples[0]?.at||0;}function end(){return samples[samples.length-1]?.at||start();}function rawFrame(){return live&&liveFrame?liveFrame:playbackFrame(samples,at)||{};}function frame(){const f=rawFrame();return {...f,player:playerOf(f,player.value)};}
    function playerColor(p){return p.control==='human'?'#50d9e8':p.control==='bot'?'#b19bff':'#b7c1cd';}
    function updatePlayers(){const choices=new Map();for(const s of samples)for(const p of playersOf(s.frame))choices.set(p.id,p);for(const p of playersOf(liveFrame))choices.set(p.id,p);
      const rows=[...choices.values()].map(p=>[p.id,`${p.id.toUpperCase()} · ${p.control==='unknown'?'control unknown':p.control}`]),key=JSON.stringify(rows);if(key!==playerChoices){playerChoices=key;options(player,rows,player.value||rows.find(r=>r[1].includes('human'))?.[0]);}}
    function selectedSamples(){const a=fromMark??samples[0]?.seq,b=toMark??samples.at(-1)?.seq;return samples.filter(s=>s.seq>=a&&s.seq<=b);}
    function options(input,rows,selected){input.replaceChildren();rows.forEach(([value,label])=>input.add(new Option(label,value)));if(rows.some(([v])=>v===selected))input.value=selected;}
    function applyFacets(){const g=games.find(g=>g.id===game.value);options(stage,[['','All recorded stages'],...(g?.stages||[]).map(s=>[s.id,`${s.name} · ${s.id.slice(-8)}`])],stage.value);options(character,[['','All characters'],...(g?.characters||[]).map(c=>[c,c])],character.value);}
    game.onchange=()=>{applyFacets();refresh(true);};for(const input of [stage,character,count])input.onchange=()=>refresh(true);
    liveInput.onchange=()=>{live=liveInput.checked;if(live){playing=false;text(play,'Play');if(runs[0])load(runs[0]);}};
    async function refresh(reset=false){
      if(dead||busy)return;busy=true;const token=revision;
      try{
        error.hidden=true;
        if(reset||!games.length){const catalog=await api(BASE+'/catalog');if(dead||token!==revision)return;games=catalog.games||[];const selected=game.value;options(game,games.map(g=>[g.id,`${g.name} · ${g.visible_runs} runs`]),selected);applyFacets();}
        if(!game.value){empty.hidden=false;text(empty,'No recorded Mercenaries runs yet. Saved atlas and round reviews will appear here automatically.');layout.hidden=true;text(status,'No saved runs');return;}
        const query=new URLSearchParams({title:game.value,stage:stage.value,character:character.value,limit:count.value,paths:'true'});
        const response=await api(BASE+'/runs?'+query);if(dead||token!==revision)return;runs=response.runs||[];
        list.replaceChildren(el('div','mr-list-title',`${runs.length} recorded run${runs.length===1?'':'s'}`));
        for(const run of runs){const b=button('',()=>{live=false;liveInput.checked=false;load(run);});b.className='mr-run'+(run.id===current?.id?' on':'');b.dataset.run=run.id;
          b.append(el('strong',null,run.character),el('small',null,run.stage),el('small','mr-run-assistance',assistanceLabel(run.assistance)),el('small',run.active?'mr-active':null,run.active?'Live · sampled state':`${run.outcome||'Unknown outcome'} · ${new Date(run.started*1000).toLocaleString()}`));list.append(b);}
        empty.hidden=!!runs.length;layout.hidden=!runs.length;if(!runs.length){text(empty,'No runs match these filters.');return;}
        if(!current||reset||!runs.some(r=>r.id===current.id)||(live&&runs[0].id!==current.id))await load(runs[0]);else{current={...current,...runs.find(r=>r.id===current.id)};background=null;}
      }catch(err){fail(err);}finally{busy=false;}
    }
    async function load(run){
      const token=++revision;playing=false;text(play,'Play');text(status,'Loading run…');drawn=[];fromMark=toMark=null;playerChoices='';sessions=[];options(sessionTarget,[['','Choose a matching live session']],'');zoom=1;pan=[0,0];background=null;current=run;data=null;samples=[];events=[];liveFrame=liveStats=liveSource=null;
      text(sessionNote,'Saved routes can be practiced when a matching game session is running.');
      for(const item of list.querySelectorAll('[data-run]'))item.classList.toggle('on',item.dataset.run===run.id);
      try{
        let after=-1;
        do{const result=await api(BASE+'/round?'+new URLSearchParams({title:run.title,id:run.id,after}));if(dead||token!==revision)return;data=result;samples=appendSamples(samples,result.samples||[]);events=result.events||[];after=result.next_after;}while(data.more);
        current=data.run;updatePlayers();at=live?end():start();floor.value=String(Math.round(frame().player?.pos?.[1]||0));background=null;renderEvents();renderDemonstrations();renderSide(true);render();
        text(status,current.active?'Live run · recorded samples':'Recorded run');status.classList.toggle('live',current.active&&live);
      }catch(err){if(token===revision)fail(err);}
    }
    async function liveTick(){
      if(dead||doc.hidden||!visible()||pollBusy)return;pollBusy=true;
      try{
      if(live&&current?.active&&!busy){const token=revision;try{let more=true;while(more){const result=await api(BASE+'/round?'+new URLSearchParams({title:current.title,id:current.id,after:samples.at(-1)?.seq??-1}));if(dead||token!==revision)return;data=result;current=result.run;samples=appendSamples(samples,result.samples||[]);events=result.events||[];more=result.more;}updatePlayers();at=end();background=null;renderEvents();renderDemonstrations();render();text(status,current.active?'Live · '+new Date().toLocaleTimeString():'Run finalized');}catch(err){fail(err);}}
      if(Date.now()-lastPoll>12000){lastPoll=Date.now();await refresh(false);}
      }finally{pollBusy=false;}
    }
    async function liveFeed(){
      if(dead||doc.hidden||!visible()||!live||!current?.active||liveBusy)return;liveBusy=true;const token=revision;
      try{const result=await api(BASE+'/live?'+new URLSearchParams({title:current.title,id:current.id}));if(dead||token!==revision)return;
        liveFrame=result.live?result.frame:null;liveStats=result.live?result.stats:null;liveSource=result.provenance;updatePlayers();
        if(result.live){text(status,`Live RAM · ${result.frame.age_s??'?'}s old`);status.classList.add('live');}
        else{text(status,'Saved samples · '+result.reason);status.classList.remove('live');}
      }catch(err){if(!dead&&token===revision){liveFrame=null;fail(err);}}finally{liveBusy=false;}
    }
    function renderEvents(){eventList.replaceChildren();for(const event of events.slice(-120).reverse()){const b=button(`${clock(event.at-start())}  ${event.kind.replaceAll('_',' ')}`,()=>{at=event.at;live=false;liveInput.checked=false;render();inspect(event.kind,event,`Recorded event seq ${event.seq} · ${current?.source_id}`);});b.className='mr-event';eventList.append(b);}}
    function renderSide(force=false){
      if(!force&&Date.now()-lastSide<400)return;lastSide=Date.now();const f=frame(),s=samples[sampleIndex(samples,at)]||{};
      const groups={'Player':f.player,'All players':playersOf(f),'Assistance & teaching':{sample_assistance:f.assistance,run_assistance:current?.assistance,demonstrations:(data?.suggestions||[]).filter(r=>r.kind==='recorded_demonstration')},'Clock':f.clock,'Plan':f.plan,'Enemies':f.enemies,'Bonuses':f.bonuses,'Mines':f.mines,'Inputs & prompt':{inputs:s.inputs,input_provenance:f.input_provenance,prompt:s.prompt},'Run review':current?.review,'Round learning':data?.notebook?.observed,
        'Navigation & mine learning':data?.navigation_learning,'Vector evidence':data?.notebook?{performance_features:data.notebook.vector,feature_definitions:data.notebook.vector_features,vector_kind:data.notebook.vector_kind,source_id:data.notebook.source_id,knowledge_delivered:data.notebook.knowledge_delivered,...data?.knowledge}:null,
        'Live diagnostics':liveStats,'Source IDs':{atlas:current?.source_id,notebook:data?.notebook?.source_id,geometry:current?.geometry,...data?.provenance,live_frame:liveSource}};
      for(const [key,{detail,content}] of sections){if(!detail.open&&!force)continue;content.replaceChildren();const value=groups[key];if(value==null){content.append(el('p','mut','Not recorded'));continue;}
        const rows=Array.isArray(value)?value.map((v,i)=>[String(i),v]):typeof value==='object'?Object.entries(value):[['value',value]];
        let source=`${current?.source_id} · recorded sample ${s.seq??'none'} at ${s.at??'unknown'}`;
        if((live&&liveFrame&&['Player','Clock','Plan','Enemies','Bonuses','Mines'].includes(key))||key==='Live diagnostics')source=`Live RAM publisher / telemetry · frame ${liveFrame?.seq??'unknown'} at ${liveFrame?.t??'unknown'} · not a durable sample`;
        else if(['Round learning','Vector evidence'].includes(key))source=data?.notebook?.source_id||'No matching Notebook source';
        else if(key==='Navigation & mine learning')source=`${data?.navigation_learning?.source_id||'No learning source'} · current aggregate, not historical round state`;
        for(const [label,v] of rows){const b=el('button','mr-param'),a=el('span',null,label),n=el('b',null,typeof v==='object'&&v!==null?(Array.isArray(v)?`${v.length} values`:`${Object.keys(v).length} fields`):String(v??'—'));b.append(a,n);b.onclick=()=>inspect(`${key} · ${label}`,v,`${source} · ${key}.${label}`);content.append(b);}}
    }
    function size(node){const rect=node.getBoundingClientRect(),dpr=Math.min(2,root.devicePixelRatio||1),w=Math.max(1,Math.round(rect.width*dpr)),h=Math.max(1,Math.round(rect.height*dpr));if(node.width!==w||node.height!==h){node.width=w;node.height=h;background=null;}return {w,h,dpr};}
    function path(c,points,color,width=2){c.beginPath();let started=false;for(const p of points){if(!xyz(p)){started=false;continue;}const [x,y]=mapTransform.point(p);if(!started)c.moveTo(x,y);else c.lineTo(x,y);started=true;}c.strokeStyle=color;c.lineWidth=width;c.stroke();}
    function staticMap(w,h){const cache=doc.createElement('canvas');cache.width=w;cache.height=h;const c=cache.getContext('2d'),geometry=data?.geometry||{},points=geometry.points||[],used=geometryPoints(geometry);mapTransform=transform(used.length?used:samples.map(s=>s.frame?.player?.pos),w,h,zoom,pan);c.fillStyle='#101923';c.fillRect(0,0,w,h);
      for(const triangle of geometry.triangles||[]){const vertices=triangle.map(i=>points[i]);if(!vertices.every(xyz))continue;c.beginPath();vertices.forEach((p,i)=>{const [x,y]=mapTransform.point(p);i?c.lineTo(x,y):c.moveTo(x,y);});c.closePath();c.fillStyle='#1b2c3b';c.fill();}
      for(const [,a,b] of geometry.boundaries||[])if(points[a]&&points[b])path(c,[points[a],points[b]],'#5b6d80',1);
      const overlay=sameGeometry(runs,current);overlay.forEach((run,index)=>{const tracks=run.paths?.length?run.paths:[{control:'unknown',path:run.path||[]}];for(const track of tracks)path(c,track.path.flatMap(p=>p.break?[null,p.pos]:[p.pos]),playerColor(track)+(run.id===current?.id?'90':'38'),run.id===current?.id?2:1);});
      for(const suggestion of data?.suggestions||[]){c.setLineDash([6,5]);path(c,suggestion.points||[],suggestion.bot_eligible?'#96c79788':'#d8ad7188',2);c.setLineDash([]);}return cache;}
    function marker(c,pos,color,r,label,hp,max){if(!xyz(pos))return;const [x,y]=mapTransform.point(pos);c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.fillStyle=color;c.fill();if(label){c.fillStyle='#e5eef5';c.font='11px system-ui';c.fillText(label,x+8,y-7);}if(finite(hp)&&finite(max)&&max>0){c.fillStyle='#131a23';c.fillRect(x-12,y+9,24,3);c.fillStyle=color;c.fillRect(x-12,y+9,24*Math.max(0,Math.min(1,hp/max)),3);}}
    function render(){
      if(dead)return;const {w,h}=size(canvas);if(!background)background=staticMap(w,h);ctx.drawImage(background,0,0);const f=frame();
      for(const b of f.bonuses||[])if(!b.taken)marker(ctx,b.pos,b.kind==='time'?'#f3cb70':'#b19bff',5);
      for(const mine of f.mines||[])marker(ctx,mine.pos,'#82d89d',4);
      for(const e of f.enemies||[])marker(ctx,e.pos,'#ff8282',4,String(e.id),e.hp,e.hp_max);
      const p=f.player;for(const actor of playersOf(f))marker(ctx,actor.pos,playerColor(actor),actor.id===player.value?7:5,`${actor.id.toUpperCase()} ${actor.control} · HP ${actor.hp??'?'}`,actor.hp,actor.hp_max);
      if(p&&xyz(p.pos)&&finite(p.facing)){const [x,y]=mapTransform.point(p.pos);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+Math.sin(p.facing)*18,y-Math.cos(p.facing)*18);ctx.strokeStyle='#f0fcff';ctx.lineWidth=2;ctx.stroke();}
      if(fromMark!=null||toMark!=null)path(ctx,selectedSamples().map(s=>playerOf(s.frame,player.value)?.pos),'#d8f9ff',4);
      for(const event of events)if(event.kind==='checkpoint_acquired'&&event.at<=at&&xyz(event.data?.pos)){const [x,y]=mapTransform.point(event.data.pos);ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);ctx.strokeStyle='#f3cb70';ctx.lineWidth=2;ctx.stroke();}
      if(drawn.length){path(ctx,drawn,'#c4a4ff',3);drawn.forEach(p=>marker(ctx,p,'#dfccff',4));}
      const overlay=sameGeometry(runs,current);text(mapNote,data?.geometry?`${current?.stage||''} · ${overlay.length} paths on this geometry${runs.length>overlay.length?` · ${runs.length-overlay.length} other geometries excluded`:''}`:'No spatial samples or measured map recorded for this run');
      text(values.Score,f.clock?.score);text(values.Combo,f.clock?.combo);text(values.HP,p?`${p.hp??'?'} / ${p.hp_max??'?'}`:null);text(values.Clock,f.clock?.left==null?null:clock(f.clock.left));text(elapsed,`${clock(at-start())} / ${clock(end()-start())}`);seek.value=String(end()>start()?Math.round(1000*(at-start())/(end()-start())):0);
      const chosen=selectedSamples(),human=chosen.length>=2&&chosen.every(s=>{const p=playerOf(s.frame,player.value);return p?.control==='human'&&p.provenance?.native_actor_verified===true&&p.provenance?.control_source==='operator_assignment_and_bot_input_fence';});
      text(selection,chosen.length?`${player.value.toUpperCase()} · ${clock(chosen[0].at-start())} → ${clock(chosen.at(-1).at-start())} · ${chosen.length} samples`:'No recorded selection');
      const context=rangeAssistance(chosen);text(assist,'Selection: '+assistanceLabel(context));assist.dataset.classification=context.classification;
      text(teachingNote,human?'The selected recorded positions will be checked against this exact mode and geometry. The bot keeps its own goals, threat checks and live traversal prompts.':'Select a recorded human player to teach a route. Older traces with unknown controller ownership remain available for review.');
      if(data?.geometry?.geometry_available===false)text(mapNote,`${current?.stage||''} - native coordinate paths only; walls and collision geometry unknown. ${data.geometry.units_per_m||'?'} native units/metre.`);
      teach.disabled=teachBusy||!human||!current?.mode||!measuredGeometry(data);markStart.disabled=markEnd.disabled=!samples.length;
      save.disabled=saveBusy||drawn.length<2||!measuredGeometry(data);draw.disabled=!measuredGeometry(data);renderChart();renderSide();
    }
    function renderChart(){const {w,h}=size(chart),c=chart.getContext('2d');c.clearRect(0,0,w,h);if(samples.length<2)return;const duration=Math.max(.001,end()-start());
      if(fromMark!=null||toMark!=null){const selected=selectedSamples();if(selected.length){c.fillStyle='#50d9e820';c.fillRect((selected[0].at-start())/duration*w,0,(selected.at(-1).at-selected[0].at)/duration*w,h);}}
      for(const [read,color] of [[s=>s.frame?.clock?.score,'#50d9e8'],[s=>playerOf(s.frame,player.value)?.hp,'#ff8282'],[s=>s.frame?.clock?.combo,'#f3cb70']]){const nums=samples.map(read).filter(finite),max=Math.max(1,...nums);c.beginPath();let on=false;for(const s of samples){const value=read(s);if(!finite(value)){on=false;continue;}const x=(s.at-start())/duration*w,y=h-10-value/max*(h-20);if(on)c.lineTo(x,y);else c.moveTo(x,y);on=true;}c.strokeStyle=color;c.lineWidth=1.5;c.stroke();}
      const x=(at-start())/duration*w;c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.strokeStyle='#aab5c6';c.lineWidth=1;c.stroke();}
    function pointAt(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];}
    canvas.title='Wheel to zoom; drag to pan. Enable Draw suggested route to add or drag route points.';
    canvas.onpointerdown=e=>{if(!mapTransform)return;const [x,y]=pointAt(e);if(!editing){drag={from:[x,y],pan:[...pan]};try{canvas.setPointerCapture(e.pointerId);}catch{}return;}let near=-1,best=14*(root.devicePixelRatio||1);drawn.forEach((p,i)=>{const q=mapTransform.point(p),d=Math.hypot(x-q[0],y-q[1]);if(d<best){best=d;near=i;}});drag=near>=0?near:'draw';if(drag==='draw'){if(drawn.length>=256)return;drawn.push(mapTransform.world(x,y,Number(floor.value)));}try{canvas.setPointerCapture(e.pointerId);}catch{}render();};
    canvas.onpointermove=e=>{if(drag==null||!mapTransform)return;const [x,y]=pointAt(e);if(typeof drag==='object'){pan=[drag.pan[0]+x-drag.from[0],drag.pan[1]+y-drag.from[1]];background=null;render();return;}const point=mapTransform.world(x,y,Number(floor.value));if(drag==='draw'){const previous=mapTransform.point(drawn.at(-1));if(Math.hypot(x-previous[0],y-previous[1])>=18&&drawn.length<256)drawn.push(point);}else drawn[drag]=point;render();};
    canvas.onpointerup=canvas.onpointercancel=()=>{drag=null;};canvas.onwheel=e=>{if(editing)return;e.preventDefault();zoom=Math.max(.6,Math.min(6,zoom*(e.deltaY<0?1.1:.9)));background=null;render();};
    function renderDemonstrations(){
      demonstrations.replaceChildren();
      for(const row of (data?.suggestions||[]).filter(r=>r.kind==='recorded_demonstration')){
        const card=el('div','mr-demonstration'),info=el('div'),source=row.source||{};
        info.append(el('strong',null,row.name),el('small',null,`${source.player_id?.toUpperCase()||'?'} human · ${assistanceLabel(row.assistance)} · ${row.adopted?'Adopted for practice':row.bot_eligible?'Validated, not adopted':'Draft: traversal or floor evidence needed'}`));
        const practice=button(row.adopted?'Stop practicing':'Have bot practice',()=>adoptRoute(row));practice.disabled=!row.bot_eligible||adoptionBusy.has(row.id);
        const use=button('Use in selected session',()=>bindRoute(row));use.className+=' mr-bind-route';use.disabled=!row.adopted||!row.bot_eligible||!sessionTarget.value||binding;
        card.append(info,practice,use,button('Evidence',()=>inspect('Recorded demonstration',row,`${source.round_source_id} · samples ${source.start_seq}–${source.end_seq} · recorded positions, no controller replay`)));demonstrations.append(card);
      }
    }
    function eligibleSession(s,title){return s&&s.state==='running'&&!s.stopping&&typeof s.session_id==='string'&&s.session_id.includes('-')
      &&(title==='BLUS30491'&&s.game_id==='e7ca89bbeb67360d'&&s.adapter==='rpcs3'||title==='BH6'&&s.game_id==='0871eee3b68cdea3'&&s.adapter==='xenia');}
    async function findSessions(){
      if(sessionBusy||!current)return;sessionBusy=true;const token=revision,title=current.title;
      try{const rows=await api('/api/sessions?include_ended=false',undefined,'GET',15000);if(dead||token!==revision)return;
        sessions=(Array.isArray(rows)?rows:[]).filter(s=>eligibleSession(s,title));options(sessionTarget,[['','Choose a matching live session'],...sessions.map(s=>[s.session_id,`${s.detail?.worker_name||s.pc||s.session_id.split('-')[0]} · ${s.session_id.slice(-8)}`])],sessionTarget.value);
        text(sessionNote,sessions.length?'Choose the exact live instance, then use a saved route.':'No matching live session. Your saved demonstrations are retained.');renderDemonstrations();
      }catch(err){if(!dead&&token===revision)fail(err);}finally{sessionBusy=false;}
    }
    async function bindRoute(row){
      if(binding||!row.adopted||!row.bot_eligible||!sessionTarget.value)return;
      const sid=sessionTarget.value,session=sessions.find(s=>s.session_id===sid),token=revision,title=current?.title;
      if(!eligibleSession(session,title))return;binding=true;renderDemonstrations();
      const matches=()=>!dead&&token===revision&&current?.title===title;
      async function job(op,extra={}){
        let result=await api('/api/jobs',{tool:'mercs_team',agent_use:false,require_worker:session.worker_id||sid.split('-')[0],input:{session_id:sid,op,...extra}},'POST',15000);
        const deadline=Date.now()+30000;
        while(['queued','running'].includes(result?.state)){
          if(!result.id||Date.now()>deadline)throw Error('Route selection is still pending; check the session team controls.');
          await new Promise(resolve=>root.setTimeout(resolve,300));result=await api('/api/jobs/'+encodeURIComponent(result.id),undefined,'GET',15000);
        }
        if(result?.state!=='succeeded')throw Error(result?.error?.message||'The session did not accept the route selection.');
        return result.output?.result;
      }
      try{
        const rows=await api('/api/sessions?include_ended=false',undefined,'GET',15000),fresh=(Array.isArray(rows)?rows:[]).find(s=>s.session_id===sid);
        if(!eligibleSession(fresh,title)||fresh.adapter!==session.adapter)throw Error('This exact session has ended or changed. Find live sessions again.');
        const active=await api('/api/jobs?state=queued,running&limit=500',undefined,'GET',15000);
        if((Array.isArray(active)?active:[]).some(j=>['mercs_team','re5_mods'].includes(j.tool)&&j.input?.session_id===sid))throw Error('A game-control job is already pending for this session. Try again after it finishes.');
        const saved=await job('configure',{selected_route_id:row.id}),freshStatus=await job('status');
        if(saved?.configuration_verified!==true||freshStatus?.status?.config?.selected_route_id!==row.id)throw Error('The selected demonstration was not confirmed by fresh session readback.');
        if(matches())text(sessionNote,`Selected for ${sid.slice(-8)} · ${row.name}. Practice follows the current team role and safety checks.`);
      }catch(err){if(matches())fail(err);}finally{binding=false;if(!dead)renderDemonstrations();}
    }
    async function teachRoute(){
      const chosen=selectedSamples();if(teachBusy||!current||!data?.geometry||chosen.length<2)return;
      const token=revision,runId=current.id,title=current.title,geometry=current.geometry;
      const matches=()=>!dead&&revision===token&&current?.id===runId&&current?.title===title&&current?.geometry===geometry;
      const body={title,round_id:runId,player_id:player.value,start_seq:chosen[0].seq,end_seq:chosen.at(-1).seq,name:name.value||'Recorded human route',adopt:true};
      teachBusy=true;teach.disabled=true;
      try{const row=await api(BASE+'/demonstrations',body);if(!matches())return;
        data.suggestions=[row,...(data.suggestions||[])];background=null;renderDemonstrations();
        text(teachingNote,row.adopted?'Route adopted for practice when the bot has a matching mode, geometry and applicable goal.':'Saved as a draft. Unsupported crossings require recorded native traversal evidence before practice.');
        inspect('Recorded route validation',row,`${row.source?.round_source_id} · exact recorded human player and sample range`);
      }catch(err){if(matches())fail(err);}finally{teachBusy=false;if(!dead)render();}
    }
    async function adoptRoute(row){
      if(adoptionBusy.has(row.id))return;const token=revision,scope=data;adoptionBusy.add(row.id);renderDemonstrations();
      try{const saved=await api(BASE+'/demonstrations/'+encodeURIComponent(row.id)+'/adopt',{adopted:!row.adopted});if(dead||token!==revision||scope!==data)return;
        data.suggestions=data.suggestions.map(r=>r.id===saved.id?saved:r);background=null;
      }catch(err){if(!dead&&token===revision)fail(err);}finally{adoptionBusy.delete(row.id);if(!dead)renderDemonstrations();}
    }
    async function saveSuggestion(){
      if(saveBusy||!current||drawn.length<2||!data?.geometry)return;
      const token=revision,runId=current.id,title=current.title,geometry=current.geometry;
      const matches=()=>!dead&&revision===token&&current?.id===runId&&current?.title===title&&current?.geometry===geometry;
      const body={title,geometry,name:name.value,points:drawn.map(p=>[...p])};
      saveBusy=true;save.disabled=true;
      try{
        const saved=await api(BASE+'/suggestions',body);
        // Saving the previous run remains legitimate. Its response must never
        // append an old-floor route or clear a drawing on the newly selected run.
        if(!matches())return;
        data.suggestions.unshift(saved);drawn=[];background=null;
        text(validation,`${saved.bot_eligible?'Validated floor suggestion':'Saved as draft'} · ${saved.validation.map(v=>v.reason).filter((v,i,a)=>a.indexOf(v)===i).join('; ')}`);
        inspect('Route validation',saved,'Exact title and geometry · live hazards still checked by navigation');
      }catch(err){if(matches())fail(err);}finally{saveBusy=false;if(!dead)render();}
    }
    function animate(now){if(dead)return;if(playing&&samples.length){at=Math.min(end(),at+Math.min(.25,(now-lastRaf)/1000)*speed);if(at>=end()){playing=false;text(play,'Play');}}lastRaf=now;if(visible()&&!doc.hidden)render();raf=root.requestAnimationFrame(animate);}
    const resize=typeof root.ResizeObserver==='function'?new root.ResizeObserver(()=>{background=null;render();}):null;resize?.observe(mapWrap);
    refresh(true);raf=root.requestAnimationFrame(animate);poll=root.setInterval(()=>liveTick(),2000);feed=root.setInterval(()=>liveFeed(),500);
    return {dispose(){dead=true;revision++;root.clearInterval(poll);root.clearInterval(feed);root.cancelAnimationFrame(raf);resize?.disconnect();dialog.remove();host.replaceChildren();},refresh,inspect};
  }
  const exported={mount,sampleIndex,playbackFrame,sameGeometry,appendSamples,geometryPoints,transform,clock,playersOf,playerOf,assistanceLabel,rangeAssistance,measuredGeometry};
  if(typeof module==='object'&&module.exports)module.exports=exported;else root.GBoxMercsReviewer=exported;
})(typeof window!=='undefined'?window:globalThis);
