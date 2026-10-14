/* Exact saved mesh geometry, measured limits and operator feedback. No gameplay claim. */
(function(root){
  'use strict';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  let active=null;
  const workspaceJobs=new Map();
  async function workspace(input,env,host){
    const key=JSON.stringify(input),doc=host.ownerDocument;
    host.textContent='Preparing editable Blender workspace...';
    let id=workspaceJobs.get(key);
    if(!id){const job=await env.api('/api/jobs',{tool:'mesh_workspace',input},'POST');id=job.id;workspaceJobs.set(key,id);}
    for(let attempt=0;attempt<450;attempt++){
      if(!host.isConnected)return;
      const job=await env.api('/api/jobs/'+encodeURIComponent(id));
      if(job.state==='succeeded'){
        const result=job.output?.result;
        if(!/^[0-9a-f]{64}$/.test(result?.sha256||''))throw Error('Workspace job returned no downloadable .blend');
        const link=doc.createElement('a');link.textContent='Download editable .blend';link.download='geometry-review.blend';link.href=env.assetUrl('/api/artifacts/'+result.sha256);
        host.replaceChildren(link);host.append(' - edit the donor and return a variant; original preserved.');return;
      }
      if(!['queued','running'].includes(job.state)){workspaceJobs.delete(key);throw Error('Blender workspace '+job.state+': '+(job.error||'No model changed.'));}
      await new Promise(resolve=>root.setTimeout(resolve,2000));
    }
    throw Error('Workspace is still queued or running. Reopen this control to follow the same job; no duplicate was submitted.');
  }
  async function open(jobId,key,env){
    if(active)active.close();
    const doc=env.document||root.document,previous=doc.activeElement;
    const modal=doc.createElement('div');modal.className='gbox-mesh-review';
    modal.innerHTML=`<style>.gbox-mesh-review{position:fixed;inset:0;z-index:2147483000;background:#000b;display:grid;place-items:center;color:#eee;font:14px system-ui}.gmr-box{background:#171a22;border:1px solid #69768d;border-radius:12px;padding:18px;width:min(1150px,96vw);max-height:94vh;overflow:auto;box-sizing:border-box}.gmr-top{display:flex;gap:12px;align-items:center}.gmr-top h2{flex:1;margin:0}.gmr-pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}.gmr-view{height:38vh;min-height:180px;background:#101218}.gmr-box button,.gmr-box select,.gmr-box textarea{font:inherit;padding:7px;color:inherit;background:#252b39;border:1px solid #65718a;border-radius:5px}.gmr-box textarea{width:100%;box-sizing:border-box;min-height:75px}.gmr-actions{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}.gmr-box pre{white-space:pre-wrap;color:#b4c8e7}.gmr-box .mut{color:#bac4d6}.gmr-status{min-height:22px}@media(max-width:650px){.gmr-pair{grid-template-columns:1fr}.gmr-view{height:28vh}}</style>
      <section class="gmr-box" role="dialog" aria-modal="true" aria-label="Review mesh reduction"><div class="gmr-top"><h2>Review mesh reduction</h2><button data-close>Close</button></div>
      <p><label>Model <select data-model></select></label></p><p class="mut" data-description>Loading saved fitting stages…</p>
      <div class="gmr-pair"><section><b data-before>Before reduction</b><div class="gmr-view" data-view-before></div></section><section><b data-after>After reduction</b><div class="gmr-view" data-view-after></div></section></div>
      <details><summary>Why was reduction needed? Measured limits</summary><pre data-limits></pre></details><p class="mut">Before shows the fitted mesh before reduction. Colours distinguish geometry; these views do not verify textures, animation or gameplay. Drag to orbit; scroll to zoom.</p>
      <label>What went wrong?<textarea data-note maxlength="4000" placeholder="For example: the eye surface disappeared; the chest opened up. Mark the affected areas in the comparison."></textarea></label>
      <p><label><input data-original type="checkbox" checked> Preserve the original mesh wherever possible</label></p>
      <div class="gmr-actions"><button data-mark disabled>Mark problems on this view…</button><button data-submit>Submit note</button><button data-workspace>Editable Blender workspace</button></div><p data-workspace-status></p><p class="gmr-status" role="status"></p></section>`;
    doc.body.append(modal);
    const q=s=>modal.querySelector(s),views=[],notes=new Map();let closed=false,sequence=0,rows=[],current=null,busy=false,syncing=false;
    const disposeViews=()=>{views.forEach(v=>v?.dispose());views.length=0;};
    const close=()=>{if(closed)return;closed=true;sequence++;disposeViews();modal.remove();doc.removeEventListener('keydown',keyboard,true);if(active?.close===close)active=null;previous?.focus?.();};
    const keyboard=e=>{if(e.key==='Escape'&&!doc.querySelector('.bri-modal')){e.preventDefault();close();}};
    active={close};doc.addEventListener('keydown',keyboard,true);q('[data-close]').onclick=close;
    const status=s=>q('[role=status]').textContent=s;
    q('[data-workspace]').onclick=async()=>{
      if(!current)return;const button=q('[data-workspace]');button.disabled=true;
      try{await workspace({source_job:jobId,model:current.key},env,q('[data-workspace-status]'));}
      catch(e){q('[data-workspace-status]').textContent=e.message;}
      finally{button.disabled=false;}
    };
    async function send(note,evidence){
      if(!note.trim())throw Error('Describe the mesh problem before submitting.');
      const selected=current.key;q('[data-model]').disabled=true;
      let result;
      try{result=await env.api(`/api/jobs/${encodeURIComponent(jobId)}/fitting/review`,{
        model:selected,note,prefer_original:q('[data-original]').checked,...(evidence?{evidence}:{})},'POST');}
      finally{q('[data-model]').disabled=false;}
      notes.set(selected,note);if(current?.key===selected)q('[data-note]').value=note;
      status(`Report #${result.number||result.id} saved. Future builds must review this feedback.`);return result;
    }
    q('[data-submit]').onclick=async()=>{if(busy||!current)return;busy=true;q('[data-submit]').disabled=true;
      try{await send(q('[data-note]').value);}catch(e){status(e.message);}finally{busy=false;q('[data-submit]').disabled=false;}};
    async function capture(){
      const images=await Promise.all(views.map(v=>new Promise((yes,no)=>{const image=new root.Image();image.onload=()=>yes(image);image.onerror=()=>no(Error('Could not capture the model view'));image.src=v.snapshot();})));
      const canvas=doc.createElement('canvas');canvas.width=1600;canvas.height=850;
      const ctx=canvas.getContext('2d');ctx.fillStyle='#111720';ctx.fillRect(0,0,1600,850);ctx.fillStyle='#fff';ctx.font='22px system-ui';
      ctx.fillText(`Mesh comparison: ${current.label}`,20,32);ctx.font='18px system-ui';
      images.forEach((image,i)=>{ctx.fillText(i===0?q('[data-before]').textContent:q('[data-after]').textContent,i*800+20,65);
        const scale=Math.min(780/image.width,730/image.height);const w=image.width*scale,h=image.height*scale;
        ctx.drawImage(image,i*800+(800-w)/2,80+(730-h)/2,w,h);});
      ctx.fillText('Saved mesh comparison; not gameplay evidence',20,835);
      return {image_b64:canvas.toDataURL('image/png').split(',')[1]};
    }
    q('[data-mark]').onclick=async()=>{
      if(busy||!views[0]||!views[1]||!root.GBoxBuildReportImage)return;
      try{await root.GBoxBuildReportImage.open({game_title:'Mesh reduction review',name:current.label},
        {document:doc,capture,initialNote:q('[data-note]').value,heading:'Mark mesh reduction problems',instructions:'Draw boxes or arrows on the before/after views. Numbers match your note. These are mesh previews, not gameplay.',
         submit:async({note,evidence})=>send(note,evidence)});}catch(e){status(e.message);}
    };
    async function select(){
      const mine=++sequence;disposeViews();q('[data-mark]').disabled=true;
      current=rows.find(r=>r.key===q('[data-model]').value);if(!current)return;
      q('[data-note]').value=notes.get(current.key)||'';
      const pair=current.comparison;
      q('[data-before]').textContent='Before reduction';q('[data-after]').textContent='After reduction';
      if(!pair){q('[data-description]').textContent='No exact before/after pair was saved for this older fit, or its temporary files expired. You can still submit a note.';q('[data-limits]').textContent=JSON.stringify(current.stages||{},null,2);return;}
      const d=pair.data||{};q('[data-description]').textContent=d.reason||'Saved mesh comparison';
      q('[data-before]').textContent=`Before: ${d.source_triangles??'?'} triangles`;
      q('[data-after]').textContent=`After: ${d.result_triangles??'?'} triangles`;
      q('[data-limits]').textContent='Measured limits and allocation attempts\n'+JSON.stringify(d.limits||{},null,2);
      status('Loading exact saved mesh geometry…');
      try{
        const module=await env.loadViewer();
        await Promise.all(['before','after'].map(async(side,i)=>{
          const viewer=await module.createCharacterViewer(q('[data-view-'+side+']'),env.assetUrl(pair[side]),{autoRotate:false,distance:1.55,
            onViewChange:pose=>{if(syncing)return;syncing=true;try{views[1-i]?.setView?.(pose);}finally{syncing=false;}}});
          if(closed||mine!==sequence){viewer.dispose();return;}views[i]=viewer;
        }));
        if(!closed&&mine===sequence){q('[data-mark]').disabled=!views[0]||!views[1];status('Orbit or zoom to inspect; mark the damaged areas or submit a note.');}
      }catch(e){if(!closed&&mine===sequence)status('Preview unavailable: '+e.message+'. Your note can still be submitted.');}
    }
    q('[data-model]').onchange=()=>{if(current)notes.set(current.key,q('[data-note]').value);select();};
    try{
      const result=await env.api(`/api/jobs/${encodeURIComponent(jobId)}/fitting/review`);
      if(closed)return;rows=result.models||[];
      q('[data-model]').innerHTML=rows.map(r=>`<option value="${esc(r.key)}">${esc(r.label)}</option>`).join('');
      if(rows.some(r=>r.key===key))q('[data-model]').value=key;
      await select();
      if(!rows.length)status('This job has no saved model fitting stages.');
    }catch(e){if(!closed)status(e.message);}
    return {close};
  }
  root.GBoxDecimationReview={open,workspace};
  root.addEventListener?.('pagehide',()=>active?.close());
})(globalThis);
