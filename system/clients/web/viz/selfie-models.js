// Models grouped by the exact source image; no face matching or person-name deduplication.
(function(root){
  'use strict';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  const path=g=>'/api/photo-skins/collections/'+encodeURIComponent(g.photo)+'/models/';
  function filePath(g,m,file='') {return path(g)+encodeURIComponent(m.slug)+'/download'+(file?'?file='+encodeURIComponent(file):'');}
  function filter(groups,state={}) {
    const q=(state.q||'').trim().toLocaleLowerCase();
    return groups.filter(g=>!state.photo||g.photo===state.photo).map(g=>{
      const all=(g.label+' '+g.tag).toLocaleLowerCase().includes(q);
      return {...g,models:g.models.filter(m=>all||[m.name,m.slug,m.source?.game_title,...m.fitted_models.map(f=>f.name)].join(' ').toLocaleLowerCase().includes(q))};
    }).filter(g=>g.models.length);
  }
  function cards(groups,url=u=>u) {
    const actions=(g,m,file='')=>`<div class="bar"><button class="act" data-sm-act="inspect" data-sm-photo="${esc(g.photo)}" data-sm-model="${esc(m.slug)}" data-sm-file="${esc(file)}">Analyze / 3D</button><button class="act" data-sm-act="blender" data-sm-photo="${esc(g.photo)}" data-sm-model="${esc(m.slug)}" data-sm-file="${esc(file)}">Export to Blender</button><a class="act" href="${esc(url(filePath(g,m,file)))}" download>Download GLB</a></div>`;
    return groups.map(g=>`<section class="sm-group" data-sm-group="${esc(g.photo)}"><header class="sm-heading"><img src="${esc(url(g.url))}" alt="Source image for ${esc(g.label)}"><div><h3>${esc(g.label)}</h3><span class="pill" title="${esc(g.tag)}">selfie:${esc(g.photo.slice(0,8))}</span><p class="mut">${g.models.length} model(s) · ${esc(g.source_kind)}</p><label>Image tag name <input data-sm-label="${esc(g.photo)}" maxlength="80" value="${esc(g.label)}"></label> <button class="act" data-sm-act="rename" data-sm-photo="${esc(g.photo)}">Save name</button></div></header><div class="sm-grid">${g.models.map(m=>`<article class="sm-model"><img loading="lazy" src="${esc(url(m.preview_url))}" alt="${esc(m.name)}"><h4>${esc(m.name)}</h4><p class="mut">${esc(m.source?.game_title||'Custom model')}</p><p class="mut">${esc(m.verification?.reason||'Model asset; native gameplay verification is separate.')}</p>${actions(g,m)}${m.fitted_models.length?`<details><summary>${m.fitted_models.length} fitted model(s)</summary>${m.fitted_models.map(f=>`<div class="sm-fit"><b>${esc(f.name)}</b> <small>${(f.bytes/1024).toFixed(0)} KiB</small>${actions(g,m,f.file)}</div>`).join('')}</details>`:''}</article>`).join('')}</div></section>`).join('')||'<p class="mut">No selfie models match. Create and accept a Photo / selfie skin from a model’s Fit &amp; textures editor.</p>';
  }
  const CSS=`.sm-heading{position:static;z-index:auto;display:flex;gap:16px;align-items:center;padding:14px;background:var(--card,#1f1f25);border-radius:8px}.sm-heading>img{width:90px;height:110px;object-fit:contain;background:#0004;border-radius:5px}.sm-heading h3{margin:0 0 6px}.sm-heading p{margin:5px 0}.sm-group{margin-bottom:24px}.sm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:12px}.sm-model{padding:12px;border:1px solid var(--line,#444);border-radius:8px;min-width:0}.sm-model>img{width:100%;height:190px;object-fit:contain;background:#0002}.sm-model h4{margin:8px 0}.sm-model .bar{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.sm-model a{color:inherit;text-decoration:none;border:1px solid var(--line,#444);padding:5px 8px;border-radius:4px}.sm-fit{padding:10px 0;border-bottom:1px solid var(--line,#444)}`;
  function mount(host,io,state={}) {
    let dead=false,groups=[],loading=false;
    host.innerHTML=`<style>${CSS}</style><div class="bar"><input type="search" data-sm-search placeholder="Search selfie, model or game" aria-label="Search selfie models"><select data-sm-select aria-label="Source selfie"><option value="">All selfies</option></select><button class="act" data-sm-refresh>Refresh</button><span class="mut" data-sm-count></span></div><p data-sm-status role="status" aria-live="polite"></p><div data-sm-groups></div>`;
    const q=s=>host.querySelector(s),note=t=>{if(!dead)q('[data-sm-status]').textContent=t;};
    q('[data-sm-search]').value=state.q||'';
    function paint(){if(dead)return;const rows=filter(groups,state);q('[data-sm-groups]').innerHTML=cards(rows,io.url);q('[data-sm-count]').textContent=rows.reduce((n,g)=>n+g.models.length,0)+' models';
      if(io.editFace)for(const section of host.querySelectorAll('[data-sm-group]')){
        const button=document.createElement('button');button.className='act';button.dataset.smAct='face';button.dataset.smPhoto=section.dataset.smGroup;
        button.textContent='Liquify / lattice face editor';section.querySelector('.sm-heading>div').append(button);
      }
    }
    async function refresh(){if(loading||dead)return;loading=true;try{groups=await io.api('/api/photo-skins/collections');if(dead)return;
      q('[data-sm-select]').innerHTML='<option value="">All selfies</option>'+groups.map(g=>`<option value="${esc(g.photo)}">${esc(g.label)}</option>`).join('');
      if(!groups.some(g=>g.photo===state.photo))state.photo='';q('[data-sm-select]').value=state.photo||'';paint();note('');
    }catch(e){note('Selfie models could not load: '+e.message);}finally{loading=false;}}
    q('[data-sm-search]').oninput=e=>{state.q=e.target.value;paint();};q('[data-sm-select]').onchange=e=>{state.photo=e.target.value;paint();};q('[data-sm-refresh]').onclick=refresh;
    host.onclick=async e=>{const b=e.target.closest('[data-sm-act]');if(!b)return;const g=groups.find(g=>g.photo===b.dataset.smPhoto);if(!g)return;
      const m=g.models.find(m=>m.slug===b.dataset.smModel),file=b.dataset.smFile||'';b.disabled=true;
      try{if(b.dataset.smAct==='face'){await io.editFace?.(g.photo);}
        else if(b.dataset.smAct==='rename'){const label=q(`[data-sm-label="${g.photo}"]`).value.trim();if(!label)throw Error('Enter an image tag name');await io.api('/api/photo-skins/photos/'+g.photo+'/label',{label});await refresh();}
        else if(m&&b.dataset.smAct==='inspect'){await io.openModel({slug:m.slug,name:file?m.name+' · '+file:m.name,photo:g.photo,modelFile:file||m.model,modelUrl:filePath(g,m,file),examine:true});}
        else if(m&&b.dataset.smAct==='blender'){note('Preparing textured model for Blender…');const result=await io.api(path(g)+encodeURIComponent(m.slug)+'/export'+(file?'?file='+encodeURIComponent(file):''),{});if(!dead){await io.blender({artifact:result.sha256});note('Copied to Blender. Press Ctrl+V in its 3D viewport.');}}
      }catch(err){note(err.message);}finally{b.disabled=false;}};
    const ready=refresh(),timer=setInterval(()=>{if(!host.contains(host.ownerDocument.activeElement))refresh();},15000);
    return {ready,refresh,dispose(){dead=true;clearInterval(timer);host.onclick=null;}};
  }
  root.GBoxSelfieModels={filter,cards,filePath,mount,CSS};if(typeof module==='object'&&module.exports)module.exports=root.GBoxSelfieModels;
})(typeof window==='undefined'?globalThis:window);
