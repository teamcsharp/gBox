// Explicit experimental map review. Candidate jobs cannot modify a donor or launch a game.
(() => {
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  function mount(host,io,{slug,onAccepted,onPreview,onPending=()=>{}}){
    let dead=false,job=null,waiting=false,candidate=null;const key='gboxTextureReview:'+slug;
    host.innerHTML=`<details><summary>Experimental texture enhancement</summary><p>Preview source color maps before importing. Original maps stay intact. Game writers may reduce these to their native texture budget.</p>
      <label><input type="checkbox" data-tr="enabled"> Enable for this import</label><div data-tr="options" hidden>
      <label>Resolution <select data-tr="size"><option value="1024">1K</option><option value="2048">2K</option><option value="4096">4K</option></select></label>
      <label>Processing <select data-tr="backend"><option value="ai">Local AI · ComfyUI queue</option><option value="cpu_ai">Local AI · CPU (configured model)</option><option value="resample">Resize only · no AI</option></select></label>
      <label>Preset <select data-tr="preset"><option value="conservative">Conservative</option><option value="smooth">Smooth transitions</option><option value="detail">Detail / sharpening</option></select></label>
      <div data-tr="selection" style="max-height:180px;overflow:auto"></div><button type="button" class="act" data-tr="prepare">Generate preview</button></div><p data-tr="status" role="status"></p><div data-tr="maps"></div>
      <div data-tr="decision" hidden><div data-tr="character-preview"><p>Compare on the fitted character. This changes only the preview.</p><button type="button" class="act" data-tr="original-model">Original textures</button> <button type="button" class="act" data-tr="candidate-model">Candidate textures</button></div><button type="button" class="act pri" data-tr="accept">Accept and use enhanced donor</button> <button type="button" class="act" data-tr="reject">Reject · keep original</button></div></details>`;
    const q=k=>host.querySelector(`[data-tr="${k}"]`),note=s=>{if(!dead)q('status').textContent=s;};
    const remember=id=>{try{id?sessionStorage.setItem(key,id):sessionStorage.removeItem(key);}catch{}};
    const busy=on=>{for(const b of host.querySelectorAll('button,select'))b.disabled=on;};
    function images(result){
      candidate=result;q('character-preview').hidden=!onPreview;
      q('maps').innerHTML=(result.images||[]).map(m=>`<div><b>${esc(m.map)}</b><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><figure style="margin:0"><img style="width:100%;max-height:220px;object-fit:contain;background:repeating-conic-gradient(#444 0 25%,#666 0 50%) 0/12px 12px" src="${esc(io.url('/api/artifacts/'+m.before))}" alt="Original ${esc(m.map)}"><figcaption>Original · ${m.original_size.join(' × ')}</figcaption></figure><figure style="margin:0"><img style="width:100%;max-height:220px;object-fit:contain;background:repeating-conic-gradient(#444 0 25%,#666 0 50%) 0/12px 12px" src="${esc(io.url('/api/artifacts/'+m.after))}" alt="Enhanced ${esc(m.map)}"><figcaption>Candidate · ${m.size.join(' × ')}</figcaption></figure></div></div>`).join('');
      note((result.settings?.backend==='resample'?'Resize-only preview ready; no AI. ':'AI preview ready. ')+(result.notice||'')+' Accept or reject before rebuilding.');
      q('decision').hidden=false;q('prepare').disabled=true;onPending(true);
    }
    async function follow(id){
      if(waiting)return;waiting=true;job=id;remember(id);onPending(true);busy(true);
      try{
        for(;;){
          const review=await io.api('/api/texture-reviews/'+encodeURIComponent(id));if(dead)return;
          if(review.decision?.state==='accepted'||review.decision?.state==='rejected'){remember(null);job=null;onPending(false);note('This preview was '+review.decision.state+'.');return;}
          if(review.job_state==='succeeded'){busy(false);images(review.result);return;}
          if(!['queued','running'].includes(review.job_state))throw Error('Texture preview '+review.job_state+': '+(review.error||'The original donor is unchanged.'));
          note('Texture preview '+review.job_state+' · '+(review.progress?.msg||id));await new Promise(r=>setTimeout(r,1250));if(dead)return;
        }
      }catch(e){if(!dead){note(e.message);job=null;remember(null);onPending(false);}}
      finally{waiting=false;if(!dead){busy(false);q('prepare').disabled=!!job;}}
    }
    let loaded=false;
    q('enabled').onchange=async()=>{q('options').hidden=!q('enabled').checked;
      if(!q('enabled').checked||loaded)return;busy(true);
      try{const result=await io.api('/api/characters/'+encodeURIComponent(slug)+'/texture-maps');if(dead)return;
        const maps=(result.maps||[]).sort((a,b)=>b.size[0]*b.size[1]-a.size[0]*a.size[1]);
        q('selection').innerHTML='<p>Select the maps to enhance. Unselected maps stay unchanged.</p>'+maps.map((m,i)=>`<label style="display:flex;gap:5px;align-items:center"><input type="checkbox" data-tr-map="${m.index}"${i===0?' checked':''}><img loading="lazy" style="width:36px;height:36px;object-fit:contain" src="${esc(io.url(m.url))}" alt="">${esc(m.name)} · ${m.size.join(' × ')}</label>`).join('');loaded=true;
      }catch(e){note('Could not list maps: '+e.message);}finally{if(!dead)busy(false);}
    };
    q('prepare').onclick=async()=>{
      if(job||waiting)return;busy(true);note('Queuing a texture preview…');
      try{const maps=[...host.querySelectorAll('[data-tr-map]:checked')].map(e=>+e.dataset.trMap);if(!maps.length)throw Error('Select at least one color map.');
        const j=await io.api('/api/characters/'+encodeURIComponent(slug)+'/texture-review',{character:slug,size:+q('size').value,preset:q('preset').value,backend:q('backend').value,maps});await follow(j.id);}
      catch(e){note(e.message);busy(false);}
    };
    async function decide(decision){
      if(!job)return;busy(true);
      try{const result=await io.api('/api/texture-reviews/'+encodeURIComponent(job)+'/decision',{decision});if(dead)return;
        remember(null);job=null;onPending(false);q('decision').hidden=true;
        if(result.state==='accepted'){note('Approved as a new donor. Original preserved.');onAccepted?.(result);}
        else{q('maps').innerHTML='';candidate=null;note('Rejected. Original retained; enhancement was not imported.');
          try{await onPreview?.(null);}catch(error){note('Rejected; no texture was imported. Reopen the editor to restore its preview: '+error.message);}}
      }catch(e){note('Decision was not saved: '+e.message);}
      finally{if(!dead)busy(false);}
    }
    async function preview(value){
      busy(true);try{await onPreview?.(value);if(!dead)note(value?'Showing candidate textures on the fitted character. Not imported; accept or reject.':'Showing original textures. The candidate is still awaiting your decision.');}
      catch(error){note('Character preview unavailable: '+error.message);}finally{if(!dead)busy(false);}
    }
    q('original-model').onclick=()=>preview(null);q('candidate-model').onclick=()=>preview(candidate);
    q('accept').onclick=()=>decide('accept');q('reject').onclick=()=>decide('reject');
    let saved;try{saved=sessionStorage.getItem(key);}catch{}if(saved){host.querySelector('details').open=true;follow(saved);}
    return {dispose(){dead=true;},follow};
  }
  window.GBoxTextureReview={mount};
})();
