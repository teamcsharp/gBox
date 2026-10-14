const $ = s => document.querySelector(s);
const params = new URLSearchParams(location.hash.slice(1)), token = params.get('token') || '', worker = params.get('worker') || '';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = n => typeof n === 'number' && Number.isFinite(n) ? Math.round(n)+'%' : 'Unknown';
let visual = null, stopped = false, timer;
async function api(path, body) {
  const response = await fetch(path, {method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store',signal:AbortSignal.timeout(8000)});
  if (!response.ok) throw Error('HTTP '+response.status);
  return response.json();
}
const stateFlow = state => `<div class="flow"><span class="${state==='queued'?'now':''}">Queued</span><i>&rarr;</i><span class="${state==='running'?'now':''}">Tool execution</span><i>&rarr;</i><span class="${state==='succeeded'?'now':''}">Tool result</span><i>&rarr;</i><span>Goal verification</span></div>`;
function jobs(rows, empty) {
  return rows.length ? rows.map(j=>`<div class="item"><b>${esc(j.tool)} <small>${esc(j.state)}</small></b>${stateFlow(j.state)}
    ${j.progress?.pct!=null?`<progress value="${Math.max(0,Math.min(100,j.progress.pct))}" max="100"></progress>`:''}
    <p>${esc(j.progress?.msg || j.admission_wait?.reason || j.error || '')}</p>
    ${j.stage_log?.length?`<pre>${esc(j.stage_log.join('\n'))}</pre>`:''}
    <small>Job ${esc(j.id)}${j.parent_request_id?' / Request '+esc(j.parent_request_id):''}${j.receipt_id?' / Receipt '+esc(j.receipt_id):''}</small></div>`).join(''):`<p class="mut">${esc(empty)}</p>`;
}
async function tick() {
  if (stopped) return;
  try {
    const data=await api('/api/background/workers/'+encodeURIComponent(worker)+'/status');
    if(stopped)return;
    const r=data.worker.resources||{}, gpus=r.gpus||[];
    $('#title').textContent=data.worker.name;
    $('#mode').textContent=data.mode+' / '+(data.online?'online':'offline');
    $('#metrics').style.opacity='1';
    $('#notice').textContent=data.idle_reason || data.admission.reason || 'Running the operations below. Goal acceptance remains evidence-based.';
    $('#metrics').innerHTML=[['CPU',pct(r.cpu_percent)],['GPU',gpus.length?gpus.map(g=>pct(g.utilization_percent)).join(' / '):'Unreported'],['RAM',pct(r.memory_percent)],['Admission budget',data.budget_percent+'%'],['Active jobs',data.active.length]].map(([label,value])=>`<div class="metric"><small>${label}</small><strong>${esc(value)}</strong></div>`).join('');
    $('#coordinator').innerHTML=(data.coordinator?.runs||[]).map(run=>`<div class="item"><b>${esc(run.name)} <small>${esc(run.state)}</small></b><p>${esc(run.progress||'')}</p><small>Server run ${esc(run.id)}</small></div>`).join('')||'<p class="mut">No coordinator run is reported.</p>';
    $('#active').innerHTML=jobs(data.active,'No operation is running on this worker.');
    $('#queue').innerHTML=jobs(data.eligible_queue,'No compatible queued job is currently assigned.');
    $('#results').innerHTML=jobs(data.recent_results,'No worker results in the recent history window.');
    $('#capabilities').innerHTML=`<p>${data.capabilities.available} available tools</p>`+Object.entries(data.capabilities.unavailable).map(([name,why])=>`<details><summary>${esc(name)} unavailable</summary><p class="mut">${esc(why)}</p></details>`).join('');
    $('#pause').disabled=!data.background_testing;
    const session=data.sessions.find(s=>s.agent_owned);
    $('#game').hidden=!session;
    if(session){
      const health=await api(`/api/sessions/${encodeURIComponent(session.session_id)}/stream/health`);
      if(stopped)return;
      $('#game-status').textContent=session.title+' / '+(session.mod||'stock')+' / '+(health.state==='running'?(health.age_s==null?'No streamed frame; native gameplay is not visually verified here.':`Last captured frame ${Math.round(health.age_s)} s ago. Gameplay goals require separate verification.`):'Session ended.');
      $('#game-frame').hidden=health.age_s==null || health.age_s>10 || health.state!=='running';
      if(health.age_s!=null && health.age_s<=10 && health.state==='running')$('#game-frame').src=`/api/sessions/${encodeURIComponent(session.session_id)}/frame.jpg?token=${encodeURIComponent(token)}&t=${Date.now()}`;

    }else{$('#game-frame').removeAttribute('src');}
    visual?.push({stationActivity:(r.cpu_percent||0)/100,bass:Math.max(0,...gpus.map(g=>g.utilization_percent||0))/100});
  }catch(error){if(!stopped){visual?.push({stationActivity:0,bass:0});$('#metrics').style.opacity='.5';$('#notice').textContent='Control plane unavailable: '+error.message+'. Displayed measurements are stale. Retrying.';}}
  if(!stopped)timer=setTimeout(tick,4000);
}
$('#pause').onclick=async()=>{try{await api('/api/testing/workers/'+encodeURIComponent(worker),{available:false});parent.postMessage({gboxBackgroundClosed:true},'*');}catch(e){$('#notice').textContent=e.message;}};
addEventListener('wheel',()=>parent.postMessage({gboxBackgroundScroll:true},'*'),{capture:true,passive:true});
for(const name of ['pointerdown','keydown'])addEventListener(name,event=>{
  if(!event.target.closest?.('button,a,input,details'))parent.postMessage({gboxBackgroundInput:true},'*');
},{capture:true,passive:true});
document.addEventListener('visibilitychange',()=>{if(document.hidden)visual?.stop();else visual?.start();});
addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);visual?.dispose();});
// Existing Three.js wave renderer, driven by measured load rather than demo activity.
import('./viz.js').then(async({createViz})=>{visual=await createViz($('#wave'),{mode:'smooth-wave',palette:'PlayStation Blue',quality:'low',provider:'external',maxFps:20});if(stopped)visual.dispose();else if(document.hidden)visual.stop();}).catch(()=>{ $('#wave').hidden=true;$('#visual-status').textContent='3D display unavailable. Live operation data remains visible.'; });
tick();
