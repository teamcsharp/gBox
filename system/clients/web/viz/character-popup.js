// Shared collection-character preview, opened from donor names and library cards.
(function(root){
  'use strict';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  function stats(viewer){
    let meshes=0,vertices=0,triangles=0,bones=0;const textures=new Set();
    viewer.gltf.scene.traverse(o=>{if(o.isBone)bones++;if(!o.isMesh)return;meshes++;
      vertices+=o.geometry?.attributes?.position?.count||0;
      triangles+=(o.geometry?.index?.count||o.geometry?.attributes?.position?.count||0)/3;
      for(const m of [].concat(o.material||[]))for(const v of Object.values(m))if(v?.isTexture)textures.add(v.uuid);
    });
    return {meshes,vertices,triangles:Math.floor(triangles),bones,textures:textures.size};
  }
  async function open(o,env={}){
    const doc=env.document||root.document,prev=doc.activeElement;
    const dialog=doc.createElement('dialog');dialog.className='cp-modal';
    dialog.innerHTML=`<style>.cp-modal{box-sizing:border-box;width:min(850px,95vw);max-height:94vh;overflow:auto;border:1px solid #555;border-radius:12px;background:#17191f;color:#eee;padding:18px;font:14px system-ui}.cp-modal::backdrop{background:#000b}.cp-modal h2{font-size:20px;margin:0 0 6px}.cp-stage{height:min(48vh,450px);background:#16181d;margin:12px 0}.cp-stage img{height:100%;max-width:100%;object-fit:contain}.cp-actions{display:flex;gap:8px;flex-wrap:wrap}.cp-actions button,.cp-actions a{font:inherit;color:#eee;background:#292e41;border:1px solid #59607a;border-radius:5px;padding:7px 10px;text-decoration:none;cursor:pointer}.cp-info,.cp-status{color:#bac3d5}.cp-info{white-space:pre-wrap;margin:10px 0}.cp-actions button:disabled{opacity:.5}</style>
      <h2>${esc(o.name||o.slug)}</h2><div class="cp-source cp-status">Collection model · target slot: ${esc(o.slot||'player')}</div>
      <div class="cp-stage" aria-label="Rotating 3D character model">Loading model…</div>
      <p class="cp-status">Drag to orbit · scroll to zoom · rotates automatically</p>
      <div class="cp-actions"><button type="button" data-cp="blender" disabled>Export to Blender</button><button type="button" data-cp="examine" disabled>Examine</button><button type="button" data-cp="retarget" disabled>Retarget…</button><a data-download hidden>Download model</a><button type="button" data-cp="close">Close</button></div>
      <pre class="cp-info" hidden></pre><p class="cp-status" data-status role="status" aria-live="polite">Loading character…</p>`;
    doc.body.appendChild(dialog);dialog.showModal();
    const q=s=>dialog.querySelector(s),stage=q('.cp-stage'),status=t=>{q('[data-status]').textContent=t;};
    let closed=false,viewer=null,model=null;
    const close=()=>{if(closed)return;closed=true;viewer?.dispose();dialog.close();dialog.remove();prev?.focus?.();};
    dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
    dialog.addEventListener('click',async e=>{
      const b=e.target.closest('[data-cp]');if(!b)return;
      const act=b.dataset.cp;if(act==='close')return close();if(!model)return;
      if(act==='examine'){
        const info=q('.cp-info');info.hidden=!info.hidden;
        info.textContent=`${model.name||o.slug}\nSource: ${model.source?.game_title||'Unknown'}\nFile: ${model.model||'Unavailable'}\n`+
          (viewer?Object.entries(stats(viewer)).map(([k,v])=>`${k}: ${v}`).join('\n'):'3D inspection is unavailable for this file format.');
        return;
      }
      if(act==='retarget') {close();return env.retarget?.({...o,slug:model.slug||o.slug,name:model.name||o.name});}
      if(act==='blender'){
        b.disabled=true;status('Copying the textured model to Blender…');
        try{if(!env.blender)throw new Error('Blender export is unavailable in this client');await env.blender(model.slug||o.slug,o);if(!closed)status('Copied to Blender. Press Ctrl+V in a Blender 3D viewport.');}
        catch(err){if(!closed)status('Blender export failed: '+err.message);}finally{b.disabled=false;}
      }
    });
    try{
      model=await env.api('/api/characters/'+encodeURIComponent(o.slug));if(closed)return;
      if(o.modelFile)model={...model,model:o.modelFile,name:o.name||model.name};
      q('h2').textContent=model.name||o.name||o.slug;
      q('.cp-source').textContent=`Collection model · ${model.source?.game_title||o.slug} · target slot: ${o.slot||'player'}`;
      const base='/api/characters/'+encodeURIComponent(model.slug||o.slug),url=env.url||(u=>u);
      const download=q('[data-download]');download.href=url(o.modelUrl||base+'/model');download.download=String(model.model||o.slug+'.glb').split('/').pop();download.hidden=!model.model;
      q('[data-cp=blender]').disabled=!model.model||!env.blender;
      q('[data-cp=retarget]').disabled=!o.gid||!env.retarget;
      q('[data-cp=examine]').disabled=false;
      if(!/\.(gltf|glb)$/i.test(model.model||''))throw new Error('This collection file has no glTF/GLB model to rotate.');
      const mod=await env.loadViewer();if(closed)return;
      stage.textContent='';
      const loaded=await mod.createCharacterViewer(stage,url(o.modelUrl||base+'/model'),{model:model.model,
        fileUrl:rel=>url(base+'/file/'+String(rel).split('/').map(encodeURIComponent).join('/'))});
      if(closed)loaded.dispose();else{viewer=loaded;status('Model ready. Export to Blender, examine its geometry, or retarget it for this game.');if(o.examine)q('[data-cp=examine]').click();}
    }catch(err){if(!closed){status('3D preview unavailable: '+err.message);stage.textContent='';
      if(model?.model){const im=doc.createElement('img');im.alt=model.name||o.slug;im.src=(env.url||(u=>u))('/api/characters/'+encodeURIComponent(o.slug)+'/preview');stage.appendChild(im);}
    }}
    return {close,element:dialog};
  }
  if(typeof module==='object'&&module.exports)module.exports={open,stats};else root.GBoxCharacterPopup={open,stats};
})(typeof window!=='undefined'?window:globalThis);
