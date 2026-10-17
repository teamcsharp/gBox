/* Reported game-tool output only. No guessed steps, memory dumps or extra command retries. */
(function(root, factory) {
  const lib = factory();
  if (typeof module === 'object' && module.exports) module.exports = lib;
  else root.GBoxOperationConsole = lib;
})(typeof window === 'undefined' ? globalThis : window, function() {
  'use strict';
  const TOOLS = new Set(['game_live_controls','pso_mods','pso_inventory','pso_drops','re_mods','re_inventory',
    'gta_mods','ac_mods','zelda','zelda_oot','re6','cheats','poke','read_memory','write_memory','freeze_memory','memory_search',
    'pick_replace','live_link','game_link','characters','mod','script_patch','unreal_script','ghidra_script']);
  const READS = new Set(['capabilities','status','list','get','search','catalog','floor_list','mag','modes','inspect']);
  const LIVE = new Set(['queued','running']);
  function clean(value) {
    return String(value ?? '').replace(/\x1b\[[0-9;]*[A-Za-z]/g,'').replace(/[\x00-\x08\x0b-\x1f]/g,'')
      .replace(/Bearer\s+\S+/gi,'Bearer [redacted]').replace(/((?:token|api[_-]?key|authorization)\s*[=:]\s*)[^\s&,]+/gi,'$1[redacted]').slice(0,600);
  }
  function describe(tool, input = {}) {
    const sid = input.session_id || input.target_session;
    if (!sid || !TOOLS.has(tool) || READS.has(input.op)) return null;
    return {sid, label:clean(`${tool} · ${input.action || input.op || 'apply'}`)};
  }
  function describeRequest(path, body) {
    if (!body) return null;
    if (path === '/api/jobs') return describe(body.tool, body.input);
    if (/\/live-controls\/run$/.test(path) && body.op === 'apply') return describe('game_live_controls',body);
    const match = /^\/api\/sessions\/([^/]+)\/rpc$/.exec(path);
    if (match && body.op === 'pso_controls') return describe('pso_mods',{...body.args?.input,session_id:decodeURIComponent(match[1])});
    return null;
  }
  function resultLines(data) {
    const r = data?.result?.result || data?.result || data || {};
    const lines = [];
    if (r.message || r.note || r.error) lines.push(clean(r.error || r.message || r.note));
    for (const key of ['spawned','removed','created','shown_now','elapsed_ms'])
      if (typeof r[key] === 'number') lines.push(`${key}: ${r[key]}`);
    if (r.verified === true) lines.push('Verified by the game worker.');
    if (r.verified === false) lines.push('Change was not verified. Check the game before retrying.');
    return lines;
  }
  function outcome(data) {
    const r=data?.result?.result || data?.result || data || {};
    return r.error ? 'failed' : r.verified===false ? 'unverified' : 'succeeded';
  }
  async function trace(emit, path, body, run) {
    const info = describeRequest(path,body);
    if (!info) return run();
    const id = `call:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    const notify = value => { try { emit(value); } catch {} };
    notify({id,...info,state:'running',lines:['Command sent; waiting for the worker.']});
    try {
      const data = await run();
      if (data?.id && data?.state) notify({replace:id,job:data});
      else notify({id,...info,state:outcome(data),lines:resultLines(data)});
      return data;
    } catch (error) {
      notify({id,...info,state:'failed',lines:[clean(error.message)]});
      throw error;
    }
  }
  function create({session,render,fetchJob,now=Date.now,every=setInterval,stop=clearInterval} = {}) {
    const entries = new Map(), seen = new Map(), pending = new Set();
    const started = now(); let selected = '', disposed = false, clock, shown=false, pollingBusy=false;
    function context() { return String(session?.() || ''); }
    function paint() {
      if (disposed) return;
      const sid = context(), t = now();
      if (sid !== selected) { selected=sid; entries.clear(); }
      const rows = [];
      for (const [id,e] of entries) {
        const age = e.end == null ? 0 : t-e.end, hold = e.state==='failed' ? 6000 : 3500;
        if (e.end != null && age >= hold+1000) { entries.delete(id); continue; }
        rows.push({id,label:e.label,state:e.state,lines:e.lines,opacity:e.end==null ? 1 : Math.min(1,Math.max(0,1-(age-hold)/1000))});
      }
      if(rows.length||shown) { try{render?.({sid,rows:rows.slice(-4)});}catch{} }
      shown=rows.length>0;
    }
    function ingest(event) {
      if (disposed) return;
      paint();
      if (event?.job) { if(event.replace) entries.delete(event.replace); return observe(event.job); }
      if (!event?.id || event.sid !== selected || !selected) return;
      const prev=entries.get(event.id);
      // Repeated terminal snapshots must not reset the fade or reopen a finished operation.
      if (prev?.end != null) return;
      entries.set(event.id,{id:event.id,sid:selected,label:clean(event.label),state:clean(event.state),
        lines:(event.lines || []).slice(-6).map(clean),end:LIVE.has(event.state) ? null : now()});
      while(entries.size>8) entries.delete(entries.keys().next().value);
      paint();
    }
    function observe(job) {
      if (disposed) return;
      const info=describe(job?.tool,job?.input);
      if (!info || info.sid!==context()) return;
      const stamp=seen.get(job.id);
      if (stamp && !LIVE.has(stamp)) return;
      if (stamp==='running' && job.state==='queued') return;
      if (!stamp && !LIVE.has(job.state) && (job.finished || job.created || 0)*1000 < started) return;
      seen.set(job.id,job.state); while(seen.size>256) seen.delete(seen.keys().next().value);
      const lines=(Array.isArray(job.progress_log)?job.progress_log:[]).slice(-5);
      if(job.progress?.msg && lines.at(-1)!==job.progress.msg) lines.push(job.progress.msg);
      if(!LIVE.has(job.state)) lines.push(...(job.error?[job.error]:resultLines(job.output)));
      ingest({id:'job:'+job.id,...info,state:job.state==='succeeded'?outcome(job.output):job.state,lines});
    }
    async function poll() {
      paint(); if(!fetchJob || disposed || pollingBusy) return;
      pollingBusy=true;
      try { for(const e of [...entries.values()]) if(e.id.startsWith('job:') && LIVE.has(e.state) && !pending.has(e.id)) {
        pending.add(e.id);
        try { const j=await fetchJob(e.id.slice(4)); if(j) observe(j); }
        catch(error) { if(entries.get(e.id)===e) { e.lines=[clean('Status unavailable: '+error.message),'Execution outcome is unknown; the command has not been retried.']; } }
        finally { pending.delete(e.id); }
      } } finally {pollingBusy=false;}
    }
    function audit(rows) {
      for(const row of rows || []) {
        if(row.ts*1000 < started || row.action!=='job.submit') continue;
        const d=row.data || row.detail || {};
        if(describe(d.tool,d.input)) observe({id:row.subject,tool:d.tool,input:d.input,state:'queued',created:row.ts});
      }
    }
    clock=every(()=>{paint();},100);
    const polling=every(()=>{poll();},650);
    return {ingest,observe,audit,poll,request:(path,body,run)=>trace(ingest,path,body,run),
      dispose(){disposed=true;stop(clock);stop(polling);entries.clear();render?.({sid:'',rows:[]});}};
  }
  const CSS = `.gbox-operation-output{position:absolute;left:18px;top:18px;max-width:min(620px,85%);max-height:55%;overflow:hidden;pointer-events:none;z-index:110;color:#e3f8ed;font:12px/1.4 ui-monospace,Consolas,monospace;text-shadow:0 1px 3px #000,0 0 4px #000}
    .gbox-operation-output section{margin:0 0 10px;padding:6px 10px;background:#07110b94;border-left:2px solid #81c9a3;border-radius:3px;white-space:pre-wrap;overflow-wrap:anywhere}
    .gbox-operation-output section[data-state=failed]{border-color:#ff9088;color:#ffd6d3}.gbox-operation-output b{font-weight:600}.gbox-operation-output pre{font:inherit;margin:3px 0 0;white-space:pre-wrap}
    @media(prefers-reduced-motion:reduce){.gbox-operation-output section{transition:none}}`;
  function view(doc,host) {
    const style=doc.createElement('style');style.textContent=CSS;host.append(style);
    const el=doc.createElement('div');el.className='gbox-operation-output';el.setAttribute('aria-live','polite');el.setAttribute('role','log');host.append(el);
    let last='';
    return {draw(frame){const value=JSON.stringify(frame.rows);if(value===last)return;last=value;el.replaceChildren();
      for(const row of frame.rows){const section=doc.createElement('section'),b=doc.createElement('b'),pre=doc.createElement('pre');
        section.dataset.state=row.state;section.style.opacity=String(row.opacity);b.textContent=`${row.label} · ${row.state}`;
        pre.textContent=row.lines.join('\n');section.append(b,pre);el.append(section);}},
      dispose(){el.remove();style.remove();}};
  }
  return {describe,describeRequest,resultLines,trace,create,view,CSS};
});
