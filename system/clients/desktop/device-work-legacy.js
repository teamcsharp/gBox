/* Read-only compatibility for servers that have not activated device-work yet. */
(function(root){
  'use strict';
  const requestCache=new Map();
  const deviceId=provider=>provider==='gbox-sparkDeux'?'sparkDeux':provider==='gbox-lilspark'?'lilspark':!provider||['custom','local','ollama','vllm'].includes(provider)?'unknown':'provider:'+provider;
  const missing=r=>!r?.ok&&(r?.status===404||/^404\b/.test(String(r?.error||'')));
  function snapshot(p,windowKey,requests={}) {
    const now=Number(p.generated_at),start=Number(p.window_start);
    if(!Number.isFinite(now)||!Number.isFinite(start)||!Array.isArray(p.providers)||!Array.isArray(p.runs))throw new Error('Legacy activity response is incomplete');
    const devices=p.providers.map(x=>({id:deviceId(x.provider),name:deviceId(x.provider)==='sparkDeux'?'Spark2':x.provider,provider:x.provider,
      models_seen:(p.routes||[]).filter(r=>r.provider===x.provider).map(r=>r.model),
      metrics:{active_runs:x.runs_running??null,ended_runs:x.runs_completed==null||x.runs_failed==null?null:x.runs_completed+x.runs_failed,
        failed_runs:x.runs_failed??null,calls_ok:x.calls_ok??null,calls_failed:x.calls_failed??null,tokens_total:x.tokens??null,
        tokens_in:null,tokens_out:null,wall_s:null,peak_concurrency:null,prs_opened:null,prs_merged:null,requests_resolved:null}}));
    const unique=new Map();for(const d of devices){if(unique.has(d.id)){d.id='provider:'+d.provider;}unique.set(d.id,d);}
    const runs=p.runs.map(r=>{
      const rid=/^gBox queue inbox ([0-9a-f]{16})\b/.exec(r.name||'')?.[1],ticket=rid&&requests[rid];
      const proved=r.attribution==='log';
      return {id:'legacy:'+r.session_id,device_id:proved?deviceId(r.provider):'unknown',title:ticket?'#'+ticket.number+': '+ticket.title:r.name||'Recorded run',
        state:r.status,started:r.start,finished:null,current_action:r.error||'Current tool action is unavailable from this server version.',
        log_available:false,tickets:ticket?[{id:rid,number:ticket.number,title:ticket.title,status:ticket.status}]:[],outcomes:[],
        attribution:{source:proved?'recorded_provider_log':'unknown',scope:'Limited server compatibility view. Historical completion and exact run-log links are unavailable.'}};
    });
    for(const r of runs)if(!unique.has(r.device_id))unique.set(r.device_id,{id:r.device_id,name:r.device_id,metrics:{}});
    return {generated_at:now,window:{key:windowKey,label:p.window_label||windowKey,start,end:now},devices:[...unique.values()],runs,
      coverage:{partial:true,notice:`Live activity is available. The server update is pending: this compatibility view contains ${runs.length} recent runs; completion evidence is unavailable, not zero.`,
        notes:[`The older server returned ${runs.length} of ${p.runs_total??'unknown'} recorded runs. Its provider totals can include active runs missing from this recent list.`,
          'Device labels use recorded named providers. Model names and the currently selected model are not proof of device contribution.',
          'Finish times, exact concurrency peaks, PR outcomes and request completion attribution require the pending server update.']}};
  }
  async function read(api,windowKey){
    const reply=await api('/api/hermes/providers?window='+encodeURIComponent(windowKey));
    if(!reply?.ok)throw new Error(reply?.error||'Existing activity data is unavailable');
    const ids=[...new Set((reply.data?.runs||[]).map(r=>/^gBox queue inbox ([0-9a-f]{16})\b/.exec(r.name||'')?.[1]).filter(Boolean))];
    let next=0;const requests={};
    await Promise.all(Array.from({length:Math.min(3,ids.length)},async()=>{
      for(let i=next++;i<ids.length;i=next++){
        const id=ids[i],cached=requestCache.get(id);
        if(cached&&Date.now()-cached.at<60000){requests[id]=cached.value;continue;}
        try{const r=await api('/api/requests/'+id);if(r?.ok&&r.data?.id===id){const value={id,number:r.data.number,title:r.data.title,status:r.data.status};requests[id]=value;requestCache.set(id,{at:Date.now(),value});}}catch{}
      }
    }));
    return {ok:true,data:snapshot(reply.data,windowKey,requests)};
  }
  const api={snapshot,read,missing,deviceId};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.GBoxDeviceWorkLegacy=api;
})(typeof window==='undefined'?globalThis:window);
