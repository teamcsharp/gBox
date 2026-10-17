/* Read-only device work evidence. No task completion is inferred from token use. */
(function(root) {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = v => v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString();
  const compact = v => v == null ? '—' : Number(v) >= 1e6 ? (Number(v)/1e6).toFixed(1)+'M' : Number(v) >= 1e3 ? (Number(v)/1e3).toFixed(1)+'k' : number(v);
  const duration = v => v == null ? '—' : v < 60 ? Math.max(0,Math.floor(v))+'s' : v < 3600 ? Math.floor(v/60)+'m' : Math.floor(v/3600)+'h '+Math.floor(v%3600/60)+'m';
  const clock = v => new Date(v*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  const timeLabel = (v, dated=false) => dated ? new Date(v*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : clock(v);
  const active = r => ['running','claimed','queued','in_progress','waiting'].includes(r.state);
  const friendly = d => /sparkdeux|spark2/i.test(d?.id+' '+d?.name) ? 'Spark2' : d?.id==='unknown' ? 'Unattributed' : d?.name || d?.id || 'Unknown device';
  const url = value => { try { const u = new URL(value); return ['https:','http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
  const outcomeLabel = o => o.kind === 'pr_reviewed_merge' ? 'PR merged after further changes' : o.kind === 'pr' || /pull_request|pr_/.test(o.kind || '') ? (o.status === 'merged' ? 'PR merged' : 'PR '+(o.status || 'published')) : o.kind === 'request_resolved' ? 'Request resolved' : /request/.test(o.kind || '') ? 'Request '+(o.status || 'updated') : o.title || o.kind || 'Recorded evidence';
  const stateLabel = r => active(r) ? (r.state === 'running' ? 'Running' : r.state.replaceAll('_',' ')) : ['completed','succeeded','done'].includes(r.state) ? 'Run ended' : r.state === 'failed' ? 'Failed' : r.state || 'Unknown';
  function range(data, hours=6) {
    const end = Number(data.window?.end || data.generated_at || Date.now()/1000);
    return {start: Math.max(Number(data.window?.start || end-86400), hours ? end-hours*3600 : 0), end};
  }
  function visibleRuns(data, device, filter='all', query='') {
    const q = query.toLowerCase();
    return (data.runs || []).filter(r => (!device || r.device_id === device)
      && (filter !== 'active' || active(r)) && (filter !== 'results' || (r.outcomes || []).length)
      && (!q || [r.title,r.current_action,...(r.tickets || []).map(t=>t.title)].join(' ').toLowerCase().includes(q)))
      .sort((a,b) => Number(active(b))-Number(active(a)) || Number(b.started || 0)-Number(a.started || 0) || String(a.id).localeCompare(String(b.id)));
  }
  function concurrency(runs, bounds) {
    const changes=new Map();let count=0;
    const change=(at,n)=>changes.set(at,(changes.get(at)||0)+n);
    for(const r of runs) {
      const start=r.started,end=active(r)?Infinity:r.finished;
      if(!Number.isFinite(start) || (!active(r)&&!Number.isFinite(end)) || end<=start || end<=bounds.start || start>bounds.end)continue;
      if(start<=bounds.start)count++;else change(start,1);
      if(end<=bounds.end)change(end,-1);
    }
    const points=[{at:bounds.start,count}];
    for(const [at,delta] of [...changes].sort((a,b)=>a[0]-b[0])){count+=delta;points.push({at,count});}
    if(points.at(-1).at<bounds.end)points.push({at:bounds.end,count});
    return points;
  }
  function graph(runs,bounds) {
    const points=concurrency(runs,bounds), peak=Math.max(0,...points.map(p=>p.count)), max=Math.max(1,peak);
    const x=p=>1000*(p.at-bounds.start)/Math.max(1,bounds.end-bounds.start),y=p=>75-65*p.count/max;
    const line=points.flatMap((p,i)=>i?[`${x(p)},${y(points[i-1])}`,`${x(p)},${y(p)}`]:[`${x(p)},${y(p)}`]).join(' ');
    return `<svg viewBox="0 0 1000 88" preserveAspectRatio="none" role="img" aria-label="Concurrent agent runs over time; observed peak ${peak}">
      <path d="M0 75 H1000 M0 42 H1000 M0 10 H1000" class="dw-grid"/><polygon points="0,75 ${line} 1000,75" class="dw-area"/><polyline points="${line}" class="dw-line"/>
      <text x="4" y="10">${max} runs</text></svg><div class="dw-axis"><span>${esc(timeLabel(bounds.start,bounds.end-bounds.start>=86400))}</span><span>${esc(timeLabel((bounds.start+bounds.end)/2,bounds.end-bounds.start>=86400))}</span><span>${esc(timeLabel(bounds.end,bounds.end-bounds.start>=86400))}</span></div>`;
  }
  function outcome(o,index) {
    const status=o.verified ? 'verified' : 'reported';
    return `<button class="dw-outcome ${status}" type="button" data-outcome="${index}"><span>${esc(outcomeLabel(o))}</span><strong>${esc(o.title || o.url || 'View evidence')}</strong><small>${o.verified ? 'Receipt verified' : 'Reported · attribution unverified'}</small>${o.evidence?.boundary?'<span class="dw-boundary">'+esc(o.evidence.boundary)+'</span>':''}</button>`;
  }
  function row(r,bounds,selected) {
    const span=Math.max(1,bounds.end-bounds.start), start=r.started==null?NaN:Number(r.started), end=active(r) ? bounds.end : r.finished==null?NaN:Number(r.finished);
    const timed=Number.isFinite(start) && Number.isFinite(end) && end>=start;
    const overlaps=timed && end>=bounds.start && start<=bounds.end;
    const left=timed ? Math.max(0,Math.min(100,(start-bounds.start)/span*100)) : 0;
    const width=overlaps ? Math.max(0,Math.min(100,(end-bounds.start)/span*100)-left) : 0;
    const state=active(r)?'active':r.state==='failed'?'failed':'ended';
    const elapsed=timed ? duration(Math.max(0,end-start)) : 'Time unavailable';
    return `<button type="button" class="dw-row ${state}${r.id===selected?' selected':''}" data-run="${esc(r.id)}" aria-pressed="${r.id===selected}">
      <span class="dw-task"><b>${esc(r.title || 'Untitled run')}</b><small>${esc(r.current_action || (active(r)?'No current action recorded':'No final action recorded'))}</small></span>
      <span class="dw-time" title="${timed?esc(new Date(start*1000).toLocaleString()+' → '+(active(r)?'now':new Date(end*1000).toLocaleString())):'Timing not recorded'}">${overlaps?`<i style="left:${left.toFixed(3)}%;width:${width.toFixed(3)}%"></i>`:''}<span>${esc(elapsed)}${timed&&!overlaps?' · outside range':''}</span></span>
      <span class="dw-run-result"><em>${esc(stateLabel(r))}</em><small>${esc((r.outcomes || []).map(outcomeLabel).join(' · ') || 'No linked outcome yet')}</small></span></button>`;
  }
  function mount(host, options) {
    const state={data:null,device:null,selected:null,filter:'all',query:'',hours:6,window:'today',active:false,busy:false,serial:0,error:'',outcomes:[]};
    host.classList.add('dw');
    host.innerHTML=`<header class="dw-heading"><div><div class="dw-eyebrow">DEVICE WORK</div><h2>What is getting done?</h2><p>Concurrent tasks, delivered changes, and the evidence behind them.</p></div><div class="dw-window"><label>Measure over <select data-window aria-label="Measurement window"><option value="today">Today</option><option value="7d">7 days</option></select></label><button type="button" data-refresh>Refresh</button></div></header>
      <div class="dw-notice" role="status" hidden></div><nav class="dw-devices" aria-label="Work device"></nav><div class="dw-metrics"></div>
      <div class="dw-layout"><section class="dw-main" aria-label="Concurrent tasks"><div class="dw-chart-head"><div><h3>Concurrent agent runs</h3><span>Includes model calls, tool use, and waiting.</span></div><label>Graph range <select data-range aria-label="Graph time range"><option value="1">Last hour</option><option value="6" selected>Last 6 hours</option><option value="0">Whole window</option></select></label></div>
      <div class="dw-chart"></div><div class="dw-filters"><label class="dw-search"><span>Find a task</span><input type="search" data-search placeholder="Game, request, or current action" aria-label="Find a task"></label><select data-filter aria-label="Tasks to show"><option value="all">All observed tasks</option><option value="active">Active tasks</option><option value="results">Tasks with outcomes</option></select><span class="dw-count"></span></div>
      <div class="dw-columns"><span>Task / latest recorded action</span><span>Run duration / position in range</span><span>State / outcome</span></div><div class="dw-runs" role="region" aria-label="Concurrent task timeline" tabindex="0"></div></section>
      <aside class="dw-detail" aria-label="Selected task evidence"></aside></div><footer class="dw-foot"></footer>`;
    const $=s=>host.querySelector(s);
    function replace(el,html) {
      if(el.dwHTML===html)return;
      const top=el.scrollTop, focused=el.contains(document.activeElement)?document.activeElement:null;
      const key=focused?.dataset, target=key?['run','device','openRun','request','outcome'].find(k=>key[k]!=null):null;
      const value=target?key[target]:null;
      el.innerHTML=html;el.dwHTML=html;el.scrollTop=top;
      if(target) [...el.querySelectorAll('button')].find(b=>b.dataset[target]===value)?.focus({preventScroll:true});
    }
    function render() {
      const d=state.data;
      $('.dw-notice').hidden=!state.error;
      $('.dw-notice').textContent=state.error;
      if(!d) { $('.dw-runs').textContent=state.error?'Device work evidence is unavailable.':'Loading device work evidence…'; return; }
      const devices=d.devices || [];
      if(!devices.some(x=>x.id===state.device))state.device=(devices.find(x=>friendly(x)==='Spark2') || devices[0])?.id || null;
      const device=devices.find(x=>x.id===state.device), metrics=device?.metrics || {};
      replace($('.dw-devices'),devices.map(x=>`<button type="button" data-device="${esc(x.id)}" aria-pressed="${x.id===state.device}"><span class="dw-device-dot ${Number(x.metrics?.active_runs)>0?'active':''}"></span><strong>${esc(friendly(x))}</strong><small>${number(x.metrics?.active_runs)} active</small></button>`).join(''));
      const cards=[['Active runs',metrics.active_runs,'Currently executing or waiting'],['PRs merged',metrics.prs_merged,'Linked changes merged in this window'],['Requests resolved',metrics.requests_resolved,'Attributed completion evidence'],['Runs ended',metrics.ended_runs,`${number(metrics.failed_runs)} failed · ending is not task acceptance`]];
      replace($('.dw-metrics'),cards.map(([name,val,note])=>`<div><span>${esc(name)}</span><b>${number(val)}</b><small>${esc(note)}</small></div>`).join(''));
      const all=visibleRuns(d,state.device), runs=visibleRuns(d,state.device,state.filter,state.query), bounds=range(d,state.hours);
      if(!runs.some(r=>r.id===state.selected))state.selected=runs[0]?.id || null;
      replace($('.dw-chart'),graph(all,bounds));
      $('.dw-count').textContent=`${runs.length} of ${all.length} observed runs`;
      replace($('.dw-runs'),runs.length?runs.map(r=>row(r,bounds,state.selected)).join(''):'<div class="dw-empty">No tasks match this device and filter.</div>');
      const selected=runs.find(r=>r.id===state.selected);
      const calls=metrics.calls_ok==null || metrics.calls_failed==null?null:Number(metrics.calls_ok)+Number(metrics.calls_failed);
      const callFailure=metrics.calls_failed==null || metrics.calls_ok==null || !calls?'—':(100*Number(metrics.calls_failed)/calls).toFixed(1)+'%';
      const tokens=metrics.tokens_in==null || metrics.tokens_out==null?null:Number(metrics.tokens_in)+Number(metrics.tokens_out);
      const modelLabel=device?.models_seen?.length?'Observed models: '+device.models_seen.join(', '):device?.model?'Current model: '+device.model:'Model not recorded';
      let detail=`<div class="dw-device-title">${esc(friendly(device))}<small>${esc(modelLabel)}</small></div><div class="dw-efficiency"><h3>Efficiency · ${esc(d.window?.label || state.window)}</h3><dl><div><dt>Model calls</dt><dd>${number(calls)}</dd></div><div><dt>Call failure rate</dt><dd>${esc(callFailure)}</dd></div><div><dt>Observed tokens</dt><dd>${compact(tokens)}</dd></div><div><dt>Agent time</dt><dd>${duration(metrics.wall_s)}</dd></div><div><dt>Peak concurrent runs</dt><dd>${number(metrics.peak_concurrency)}</dd></div><div><dt>PRs published</dt><dd>${number(metrics.prs_opened)}</dd></div><div><dt>Avg. successful call</dt><dd>${duration(metrics.mean_call_s)}</dd></div><div><dt>Ended runs with outcomes</dt><dd>${number(metrics.ended_runs_with_delivery)} / ${number(metrics.ended_runs)}</dd></div></dl><p>Agent time adds overlapping runs. Call time includes waiting. Outcomes mean recorded PR publication/merge or request completion; model-call success is not task acceptance.</p></div>`;
      state.outcomes=selected?.outcomes || [];
      if(selected) {
        detail+=`<section class="dw-inspect"><span class="dw-state">${esc(stateLabel(selected))}</span><h3>${esc(selected.title || 'Untitled run')}</h3><p class="dw-action">${esc(selected.current_action || 'No current action recorded.')}</p><div class="dw-attribution">Device evidence: ${esc((selected.attribution?.source || 'Unavailable').replaceAll('_',' '))}${selected.attribution?.scope?'<br>'+esc(selected.attribution.scope):''}${selected.attribution?.note?'<br>'+esc(selected.attribution.note):''}</div><div class="dw-links"><button type="button" data-open-run="${esc(selected.id)}">Open run and tool log</button>${(selected.tickets || []).map(t=>`<button type="button" data-request="${esc(t.id)}">#${esc(t.number || '—')} ${esc(t.title || 'Open request')} · ${esc(t.status || 'unknown')}</button>`).join('')}</div><h4>Linked outcomes</h4>${state.outcomes.length?state.outcomes.map(outcome).join(''):'<p class="dw-empty-result">No linked deliverable has been recorded for this run yet.</p>'}</section>`;
      } else detail+='<p class="dw-empty-result">Select a task to inspect its evidence.</p>';
      replace($('.dw-detail'),detail);
      const notes=Array.isArray(d.coverage?.notes)?d.coverage.notes:[];
      const coverageOpen=$('.dw-foot details')?.open;
      replace($('.dw-foot'),`<span>Updated ${esc(timeLabel(d.generated_at || bounds.end,true))} · ${esc(d.window?.label || state.window)}</span><details${coverageOpen?' open':''}><summary>${esc(d.coverage?.partial?'Partial evidence coverage':'Evidence coverage')}</summary>${notes.map(note=>'<p>'+esc(note)+'</p>').join('')}</details>`);
    }
    async function refresh() {
      if(!state.active || state.busy)return;
      state.busy=true; const serial=state.serial, windowKey=state.window;
      try {
        const r=await options.api('/api/tasks/device-work?window='+encodeURIComponent(windowKey));
        if(!state.active || serial!==state.serial)return;
        if(!r?.ok)throw new Error(r?.error || 'Device evidence endpoint unavailable');
        if(!r.data || !Array.isArray(r.data.devices) || !Array.isArray(r.data.runs))throw new Error('Device evidence response is incomplete');
        state.data=r.data;state.error='';render();options.onUpdated?.(r.data.generated_at);
      } catch(error) {
        if(state.active && serial===state.serial){state.error='Could not refresh device evidence. '+(state.data?'Last successful snapshot is retained. ':'')+error.message;render();}
      } finally {state.busy=false;if(state.active && serial!==state.serial)refresh();}
    }
    host.addEventListener('click',e=>{
      const b=e.target.closest('button');if(!b)return;
      if(b.dataset.device){state.device=b.dataset.device;state.selected=null;render();}
      else if(b.dataset.run){state.selected=b.dataset.run;render();}
      else if(b.hasAttribute('data-refresh'))refresh();
      else if(b.dataset.openRun)options.onRun?.(b.dataset.openRun);
      else if(b.dataset.request)options.onRequest?.(b.dataset.request);
      else if(b.hasAttribute('data-outcome')){const o=state.outcomes[Number(b.dataset.outcome)];if(!o)return;const link=url(o.url);if(link)options.onExternal?.(link);else if(o.request_id)options.onRequest?.(o.request_id);else if(options.onEvidence)options.onEvidence(o);else options.onRun?.(state.selected);}
    });
    $('[data-window]').addEventListener('change',e=>{state.window=e.target.value;state.serial++;state.selected=null;refresh();});
    $('[data-range]').addEventListener('change',e=>{state.hours=Number(e.target.value);render();});
    $('[data-filter]').addEventListener('change',e=>{state.filter=e.target.value;render();});
    $('[data-search]').addEventListener('input',e=>{state.query=e.target.value;render();});
    render();
    return {refresh,setActive(on){state.active=on;state.serial++;if(on)refresh();},state};
  }
  const api={mount,range,visibleRuns,concurrency,graph,row,active,friendly,url,outcomeLabel,stateLabel};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.GBoxDeviceWork=api;
})(typeof window==='undefined'?globalThis:window);
