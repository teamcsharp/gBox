/* Search and inspect actual recorded evidence; never synthesize a replay claim. */
(function(root){
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function html(d){
    return `<h2>Gameplay memory</h2><p>${d.runs?.length||0} recent runs · ${d.events||0} observations</p>
      <p class="mut">${esc(d.vector_kind)}. Controller observations are not a TAS. Native recordings require replay validation.</p>
      <form data-memory-search><input name="q" placeholder="Search runs, equipment changes, or notes" maxlength="2000"><button>Search</button></form>
      <p class="mut">${esc(d.error||d.demonstrations?.reason||'')}</p>
      <div data-memory-matches>${(d.matches||[]).map(m=>`<button data-run="${esc(m.run_id)}">${esc(m.summary.slice(0,180))}</button>`).join('')}</div>
      <div style="max-height:280px;overflow:auto;margin-top:10px">${(d.runs||[]).map(r=>`<button data-run="${esc(r.id)}" style="display:block;width:100%;text-align:left;margin:4px 0"><b>${esc(r.title||r.game_id)}</b> · ${esc(r.mod||'base game')}<br>${esc(r.replay_status)} · ${esc(new Date(r.updated*1000).toLocaleString())}</button>`).join('')||'<p>No gameplay has been captured yet. Supported new RetroArch launches can record native input; existing sessions are not restarted.</p>'}</div>
      <details><summary>Master archive on Spark</summary><code style="overflow-wrap:anywhere">${esc(d.file)}</code><p>Old runs are retained when storage fills. Native files have a separate 64 GiB archive limit.</p></details>
      <div data-memory-run></div>`;
  }
  function mount(el,{api}){
    let sid='',after=0,stopped=false;
    async function load(q=''){
      try{
        const d=await api('/api/gameplay-memory?q='+encodeURIComponent(q));if(stopped)return;
        el.innerHTML=html(d);
        for(const r of d.runs||[]){
          if(!r.observed_demo?.ready)continue;
          const button=[...el.querySelectorAll('[data-run]')].find(b=>b.dataset.run===r.id);
          if(button)button.insertAdjacentHTML('afterend',`<div><button data-demo="${esc(r.id)}">Play observed demo</button> <button data-demo-loop="${esc(r.id)}">Loop</button> <button data-demo-idle="${esc(r.id)}" data-enabled="${!!r.observed_demo.idle_enabled}">${r.observed_demo.idle_enabled?'Disable idle screensaver':'Use as idle screensaver'}</button><small style="display:block">Separate idle PC; approximate inputs, recorded mods and state restores.</small></div>`);
        }
        el.insertAdjacentHTML('beforeend','<p data-demo-status role="status"></p>');
      }
      catch(e){el.textContent='Gameplay memory unavailable: '+e.message;}
    }
    async function page(id,more=false){
      try{
        if(!more){sid=id;after=0;el.querySelector('[data-memory-run]').innerHTML='<h3>Run timeline</h3><div data-events style="max-height:320px;overflow:auto"></div><button data-more>More events</button><form data-note><input name="text" maxlength="2000" required placeholder="Describe a level, equipment change, or test goal"><button>Add note</button></form><p data-note-status></p>';}
        const d=await api('/api/gameplay-memory/runs/'+encodeURIComponent(id)+'?after='+after);
        if(stopped||sid!==id)return;
        const box=el.querySelector('[data-events]');
        for(const e of d.events||[]){after=Math.max(after,e.id);box.insertAdjacentHTML('beforeend',`<details><summary>${esc(new Date(e.at*1000).toLocaleTimeString())} · ${esc(e.kind)}</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(e.payload,null,2))}</pre></details>`);}
        el.querySelector('[data-more]').disabled=(d.events||[]).length<100;
      }catch(e){const box=el.querySelector('[data-memory-run]');if(box)box.textContent=e.message;}
    }
    async function click(e){
      const run=e.target.closest('[data-run]');if(run)page(run.dataset.run);if(e.target.closest('[data-more]'))page(sid,true);
      const demo=e.target.closest('[data-demo],[data-demo-loop],[data-demo-idle]');if(!demo)return;
      const id=demo.dataset.demo||demo.dataset.demoLoop||demo.dataset.demoIdle;
      const status=el.querySelector('[data-demo-status]');demo.disabled=true;
      try{
        const idle=demo.hasAttribute('data-demo-idle');
        const enable=demo.dataset.enabled!=='true';
        const result=await api('/api/gameplay-memory/runs/'+encodeURIComponent(id)+'/demo/'+(idle?'idle':'play'),idle?{enabled:enable}:{loop:demo.hasAttribute('data-demo-loop')});
        if(idle){demo.dataset.enabled=String(enable);demo.textContent=enable?'Disable idle screensaver':'Use as idle screensaver';}
        status.textContent=idle?(enable?'Idle demonstrations enabled for this run on separate available PCs after a completed test replay.':'Idle demonstrations disabled for this run.'):'Observed demo queued: '+(result.id||result.job_id||'waiting for an idle PC');
      }catch(err){status.textContent=err.message;}finally{demo.disabled=false;}
    }
    async function submit(e){
      if(e.target.matches('[data-memory-search]')){e.preventDefault();load(new FormData(e.target).get('q'));}
      if(e.target.matches('[data-note]')){
        e.preventDefault();const msg=el.querySelector('[data-note-status]');
        try{await api('/api/gameplay-memory/runs/'+encodeURIComponent(sid)+'/note',{text:new FormData(e.target).get('text')});msg.textContent='Note saved. This annotation is not automatic gameplay verification.';}
        catch(err){msg.textContent=err.message;}
      }
    }
    el.addEventListener('click',click);el.addEventListener('submit',submit);
    return {load,stop(){stopped=true;el.removeEventListener('click',click);el.removeEventListener('submit',submit);}};
  }
  root.GBoxGameplayMemory={html,mount};
  if(typeof module!=='undefined')module.exports=root.GBoxGameplayMemory;
})(typeof window==='undefined'?globalThis:window);
