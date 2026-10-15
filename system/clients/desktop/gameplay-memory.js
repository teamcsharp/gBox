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
      try{const d=await api('/api/gameplay-memory?q='+encodeURIComponent(q));if(!stopped)el.innerHTML=html(d);}
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
    function click(e){const run=e.target.closest('[data-run]');if(run)page(run.dataset.run);if(e.target.closest('[data-more]'))page(sid,true);}
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
