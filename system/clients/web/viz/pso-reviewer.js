/* PSO native observations, recorded paths and critical moments. No game writes. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.GBoxPSOReview=factory();
})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const point=p=>p&&finite(p.x)&&finite(p.z);
  function pathSegments(samples,slot,frame){
    const result=[];let segment=[],previous=null;
    for(const sample of samples){
      const p=sample.players?.[slot], map=sample.maps?.find(m=>m.player===+slot);
      const identity=map?.identity;
      const shown=frame.maps?.find(m=>m.player===+slot)?.identity;
      if(!sample.verified||!point(p)||!identity||identity!==shown||sample.episode!==frame.episode||sample.floor!==frame.floor||sample.difficulty!==frame.difficulty){
        if(segment.length)result.push(segment);segment=[];previous=null;continue;
      }
      if(previous&&(sample.elapsed_s-previous.t>12||p.ptr!==previous.ptr||p.room!==previous.room)){
        if(segment.length)result.push(segment);segment=[];
      }
      segment.push([p.x,p.z]);previous={t:sample.elapsed_s,ptr:p.ptr,room:p.room};
    }
    if(segment.length)result.push(segment);
    return result;
  }
  function metrics(samples){
    let transitions=0,damage=0,distance=0,previous=null;
    for(const frame of samples){
      if(previous&&frame.verified&&previous.verified&&frame.episode===previous.episode&&frame.floor===previous.floor&&frame.difficulty===previous.difficulty){
        for(const slot of ['1','2']){
          const a=previous.players?.[slot],b=frame.players?.[slot];
          if(!point(a)||!point(b)||a.ptr!==b.ptr)continue;
          if(a.room!==b.room)transitions++;
          const layout=frame.maps?.find(m=>m.player===+slot)?.identity,oldLayout=previous.maps?.find(m=>m.player===+slot)?.identity;
          if(!layout||layout!==oldLayout)continue;
          if(a.room===b.room&&frame.elapsed_s-previous.elapsed_s<=12)distance+=Math.hypot(b.x-a.x,b.z-a.z);
          if(finite(a.hp)&&finite(b.hp))damage+=Math.max(0,a.hp-b.hp);
        }
      }
      previous=frame;
    }
    return {transitions,damage,distance:Math.round(distance),samples:samples.length};
  }
  function draw(canvas,frame,samples,selected='1'){
    const ctx=canvas.getContext('2d'),width=canvas.clientWidth||720,height=canvas.clientHeight||420;
    const dpr=Math.min(globalThis.devicePixelRatio||1,2);canvas.width=width*dpr;canvas.height=height*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#0a111c';ctx.fillRect(0,0,width,height);
    const focus=frame?.players?.[selected];
    if(!frame?.verified||!point(focus)){ctx.fillStyle='#b6c7df';ctx.fillText('Waiting for verified native player coordinates',24,35);return;}
    const map=frame.maps?.find(m=>m.player===+selected),size=finite(map?.size)?map.size:12;
    const entities=(frame.entities||[]).filter(e=>point(e)&&e.room===focus.room&&Math.abs((e.y||0)-(focus.y||0))<8);
    const points=[[focus.x,focus.z],...entities.map(e=>[e.x,e.z])];
    for(const c of [...(map?.walked||[]),...(map?.floor||[])])points.push([(c[0]+.5)*size,(c[1]+.5)*size]);
    for(const goal of frame.goals||[])if(goal.player===+selected&&point(goal))points.push([goal.x,goal.z]);
    const xs=points.map(p=>p[0]),zs=points.map(p=>p[1]);
    let loX=Math.min(...xs)-25,hiX=Math.max(...xs)+25,loZ=Math.min(...zs)-25,hiZ=Math.max(...zs)+25;
    const scale=Math.min((width-48)/(hiX-loX),(height-48)/(hiZ-loZ));
    const screen=(x,z)=>[24+(x-loX)*scale,height-24-(z-loZ)*scale];
    function cell(c,color){const [x,y]=screen(c[0]*size,(c[1]+1)*size);ctx.fillStyle=color;ctx.fillRect(x,y,size*scale,size*scale);}
    if(map?.geometry_available){for(const c of map.floor||[])cell(c,'#193440');for(const c of map.walls||[])cell(c,'#7a8999');}
    for(const c of map?.walked||[])cell(c,'#163b31');
    ctx.strokeStyle='#ff735f';ctx.lineWidth=3;
    for(const [a,b] of map?.blocked||[]){const [x,y]=screen((a[0]+.5)*size,(a[1]+.5)*size),[xx,yy]=screen((b[0]+.5)*size,(b[1]+.5)*size);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(xx,yy);ctx.stroke();}
    for(const slot of ['1','2']){
      if(frame.maps?.find(m=>m.player===+slot)?.identity!==map?.identity)continue;
      ctx.strokeStyle=slot==='1'?'#5ccaff':'#d6a2ff';ctx.lineWidth=2;
      for(const segment of pathSegments(samples,slot,frame)){ctx.beginPath();segment.forEach((p,i)=>{const [x,y]=screen(...p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}
    }
    for(const e of entities){const [x,y]=screen(e.x,e.z);ctx.fillStyle=e.kind==='enemy'?'#ff6469':e.kind==='gate'?'#f7c758':'#7899aa';ctx.beginPath();ctx.arc(x,y,e.kind==='gate'?5:3,0,Math.PI*2);ctx.fill();}
    for(const goal of frame.goals||[]){if(goal.player!==+selected||!point(goal))continue;const [x,y]=screen(goal.x,goal.z);ctx.strokeStyle='#fff';ctx.strokeRect(x-7,y-7,14,14);}
    for(const [slot,p] of Object.entries(frame.players||{})){
      if(!point(p)||p.room!==focus.room||Math.abs(p.y-focus.y)>=8)continue;
      const [x,y]=screen(p.x,p.z);ctx.fillStyle=slot==='1'?'#5ccaff':'#d6a2ff';ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.fill();ctx.font='bold 12px system-ui';ctx.fillText('P'+slot,x+9,y-6);
    }
    ctx.font='12px system-ui';ctx.fillStyle='#c4d5e7';ctx.fillText(`Room ${focus.room} · same height band · native world units`,16,20);
  }
  function open(io,session){
    const host=document.createElement('div');host.className='pso-review-window';document.body.appendChild(host);
    const control=mount(host,io,session,()=>{control.dispose();host.remove();});return control;
  }
  function mount(host,io,session,onClose=()=>{}){
    const sid=session.sid||session.session_id;let stopped=false,timer=null,mode='live',samples=[],events=[],eventsTruncated=false,frame=null,run=null,loadVersion=0,selected='1';
    host.innerHTML=`<style>
      .pso-review-window{position:fixed;inset:6vh 5vw;z-index:10020;background:#121c2b;color:#e1ebf7;border:1px solid #4a607d;border-radius:12px;box-shadow:0 16px 64px #0009;overflow:auto;font:13px system-ui}
      .pso-review{padding:18px}.pso-review header,.pso-review .pr-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.pso-review header strong{font-size:18px;flex:1}.pso-review button,.pso-review select{background:#263c56;color:#eef6ff;border:1px solid #59718e;padding:7px;border-radius:5px;cursor:pointer}.pso-review canvas{display:block;width:100%;height:42vh;min-height:250px;border:1px solid #2d445f;border-radius:8px;margin:12px 0}.pso-review .pr-muted{color:#a9bed5}.pso-review .pr-columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.pso-review table{border-collapse:collapse;width:100%}.pso-review td,.pso-review th{text-align:left;padding:6px;border-bottom:1px solid #2d4056}.pso-review .pr-events{max-height:200px;overflow:auto}.pso-review .pr-events button{display:block;text-align:left;width:100%;margin:4px 0}.pso-review [data-pr-scrub]{width:100%}.pso-review pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px system-ui}.pso-review [role=status]{min-height:20px;margin:8px 0}@media(max-width:700px){.pso-review .pr-columns{grid-template-columns:1fr}}
      .pso-review,.pso-review *{box-sizing:border-box;min-width:0}.pso-review select{max-width:100%}.pso-review .pr-columns{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}@media(max-width:700px){.pso-review .pr-columns{grid-template-columns:minmax(0,1fr)}}
    </style><section class="pso-review"><header><strong>PSO · map and run reviewer</strong><button data-pr-close aria-label="Close PSO reviewer">Close</button></header>
      <p class="pr-muted">Recorded native observations. Trails show where the buddies moved; red edges mark learned obstructions. Unknown walls and door conditions stay visible as unknown.</p>
      <div class="pr-row"><button data-pr-live>Live map</button><select data-pr-runs aria-label="Recorded PSO run"><option value="">Choose a recorded segment</option></select><button data-pr-refresh>Refresh runs</button><select data-pr-player aria-label="Map focus"><option value="1">Player 1 room</option><option value="2">Player 2 room</option></select><button data-pr-export disabled>Export run crystal</button></div>
      <div role="status" data-pr-status></div><canvas aria-label="PSO observed native map"></canvas><div class="pr-muted">● P1 blue · P2 purple · enemies red · native gates yellow · objects gray · □ intended goal</div>
      <input type="range" data-pr-scrub min="0" max="0" value="0" aria-label="Run playback position" disabled><output data-pr-time></output>
      <div class="pr-columns"><div><h3>Current objective</h3><pre data-pr-objective></pre><p data-pr-geometry class="pr-muted"></p><table><thead><tr><th>Player</th><th>Room</th><th>HP / TP</th></tr></thead><tbody data-pr-players></tbody></table><p data-pr-metrics></p></div>
      <div><h3>Critical moments</h3><p class="pr-muted" data-pr-event-limit></p><div class="pr-events" data-pr-events></div><p class="pr-muted">An empty enemy list does not prove a room is clear. Recorded goals and routes require fresh validation before reuse.</p></div></div></section>`;
    const q=s=>host.querySelector(s),status=text=>{if(!stopped)q('[data-pr-status]').textContent=text;};
    function render(){
      if(stopped||!frame)return;
      draw(q('canvas'),frame,samples,selected);
      q('[data-pr-time]').textContent=`${mode==='live'?'Latest observation':'Playback'} · ${frame.elapsed_s.toFixed(1)}s · Episode ${frame.episode??'?'} / floor ${frame.floor??'?'} / difficulty ${frame.difficulty??'?'}`;
      q('[data-pr-objective]').textContent=[frame.action||'No action reported',...(frame.goals||[]).map(g=>`P${g.player}: ${g.reason||'Observed goal'} → (${g.x.toFixed(1)}, ${g.z.toFixed(1)})`),frame.thought?`Planner: ${frame.thought}`:'',`Door requirements: ${frame.door_requirements?.reason||'unverified'}`].filter(Boolean).join('\n');
      const map=frame.maps?.find(m=>m.player===+selected);
      q('[data-pr-geometry]').textContent=(map?.geometry_reason||'No current layout evidence')+((map?.geometry_truncated||map?.observations_truncated)?' · Display is bounded; some geometry/observations omitted.':'');
      q('[data-pr-players]').innerHTML=Object.entries(frame.players||{}).map(([slot,p])=>`<tr><td>Player ${esc(slot)}</td><td>${esc(p.room)}</td><td>${esc(p.hp??'?')} / ${esc(p.tp??'?')}</td></tr>`).join('');
      const m=metrics(samples);q('[data-pr-metrics]').textContent=`${m.samples} recorded samples · ${m.transitions} player room transitions · ${m.distance} units sampled displacement · ${m.damage} HP loss observed`;
      q('[data-pr-event-limit]').textContent=(events.length>120?'Showing the latest 120 returned events. ':'')+(eventsTruncated?'Event response limit reached; later events remain in the recording database.':'');
      q('[data-pr-events]').innerHTML=events.slice(-120).reverse().map(e=>`<button data-pr-event="${esc(e.at_s)}">${esc(Number(e.at_s).toFixed(1))}s · ${esc(e.message)}</button>`).join('')||'No critical moments recorded yet.';
    }
    async function list(){try{const result=await io.api('/api/pso/reviewer/runs?sid='+encodeURIComponent(sid));if(stopped)return;q('[data-pr-runs]').innerHTML='<option value="">Choose a recorded segment</option>'+result.runs.map(r=>`<option value="${esc(r.id)}">${esc(new Date(r.started*1000).toLocaleString())} · ${r.frames} samples · ${esc(r.id.slice(0,8))}</option>`).join('');if(result.recording_error)status(result.recording_error);}catch(error){status(error.message);}}
    async function poll(){
      if(stopped||mode!=='live')return;const version=loadVersion;
      try{const result=await io.api('/api/pso/reviewer/live/'+encodeURIComponent(sid));if(stopped||version!==loadVersion||mode!=='live')return;
        if(result.frame){frame=result.frame;if(run!==frame.run_id){run=frame.run_id;samples=[];}if(!samples.some(s=>s.seq===frame.seq))samples.push(frame);samples=samples.slice(-1200);events=frame.events||[];eventsTruncated=false;render();}
        status(result.recording_error||(result.frame?(result.live?'Live':'Stale')+` · received ${result.age_s.toFixed(1)}s ago`+(finite(result.source_age_s)?` · source age ${result.source_age_s.toFixed(1)}s`:'')+(result.reason?' · '+result.reason:''):result.reason));
      }catch(error){status('Review unavailable: '+error.message);}finally{if(!stopped&&mode==='live')timer=setTimeout(poll,2500);}
    }
    async function load(id){
      if(!id)return;mode='review';const version=++loadVersion;clearTimeout(timer);status('Loading recorded native samples…');let after=-1,all=[],result;
      try{do{result=await io.api(`/api/pso/reviewer/run/${encodeURIComponent(id)}?after=${after}`);if(stopped||version!==loadVersion)return;all.push(...result.samples);after=result.next_after;}while(result.has_more&&all.length<4096);
        samples=all;events=result.events;eventsTruncated=result.events_truncated===true;run=id;frame=samples[0]||null;q('[data-pr-scrub]').max=Math.max(0,samples.length-1);q('[data-pr-scrub]').value=0;q('[data-pr-scrub]').disabled=!samples.length;q('[data-pr-export]').disabled=false;status('Recorded observation segment · completion is not implied');render();
      }catch(error){status(error.message);}
    }
    q('[data-pr-close]').onclick=onClose;q('[data-pr-refresh]').onclick=list;
    q('[data-pr-runs]').onchange=e=>load(e.target.value);
    q('[data-pr-player]').onchange=e=>{selected=e.target.value;render();};
    q('[data-pr-live]').onclick=()=>{loadVersion++;clearTimeout(timer);mode='live';samples=[];run=null;q('[data-pr-scrub]').disabled=true;q('[data-pr-export]').disabled=true;poll();};
    q('[data-pr-scrub]').oninput=e=>{frame=samples[+e.target.value];render();};
    q('[data-pr-events]').onclick=e=>{const button=e.target.closest('[data-pr-event]');if(!button||mode!=='review')return;const at=+button.dataset.prEvent;let index=samples.findIndex(s=>s.elapsed_s>=at);if(index<0)index=samples.length-1;if(index>=0){q('[data-pr-scrub]').value=index;frame=samples[index];render();}};
    q('[data-pr-export]').onclick=async()=>{try{const data=await io.api('/api/pso/reviewer/crystal/'+encodeURIComponent(run));if(stopped)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`pso-run-${run}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){status(error.message);}};
    const resized=()=>render();globalThis.addEventListener?.('resize',resized);list();poll();
    return {dispose(){stopped=true;loadVersion++;clearTimeout(timer);globalThis.removeEventListener?.('resize',resized);}};
  }
  return {open,mount,pathSegments,metrics,draw};
});
