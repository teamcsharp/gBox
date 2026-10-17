/* Explicit per-title native asset jobs. Opening this window only reads catalog/worker metadata. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.GBoxGameAssets=factory();
})(typeof window!=='undefined'?window:globalThis,function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  const array=v=>Array.isArray(v)?v:[];
  const object=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:{};
  const text=v=>typeof v==='string'?v:'';
  const terminal=s=>['succeeded','failed','rejected','cancelled','canceled'].includes(s);
  const bytes=v=>Number.isFinite(Number(v))?Number(v):0;
  const size=v=>bytes(v)<1048576?`${Math.ceil(bytes(v)/1024)} KB`:`${(bytes(v)/1048576).toFixed(1)} MB`;
  function workers(value){
    return array(Array.isArray(value)?value:object(value).workers).filter(w=>w&&w.online===true&&w.os==='windows'&&w.id)
      .map(w=>({id:String(w.id),name:String(w.name||w.id)}));
  }
  function inventory(value){
    value=object(value);
    return {...value,summary:object(value.summary),readiness:object(value.readiness),issues:array(value.issues),
      assets:array(value.assets).filter(a=>a&&typeof a.path==='string').map(a=>({...a,members:array(a.members)}))};
  }
  function artifacts(value){
    return array(value).filter(a=>a&&/^[a-f0-9]{64}$/.test(a.sha256||'')).map(a=>({
      sha256:a.sha256,name:String(a.name||a.sha256.slice(0,12)),size:bytes(a.size)}));
  }
  function createController(io){
    if(!io.gid||typeof io.api!=='function')throw Error('A title and API connection are required.');
    const st={gid:io.gid,title:io.title||io.gid,game:null,workers:[],worker:'',loading:true,busy:false,
      job:null,op:'',result:null,inventory:null,index:null,artifacts:[],paths:new Set(),members:new Map(),
      error:'',status:'Loading title and Windows PCs...',pollError:false,closed:false};
    let timer=null,wake=null,epoch=0,polling=false,cancelling=false,followVersion=0;
    const emit=()=>{if(!st.closed)io.render?.(st);};
    const supported=()=>st.game?.launch?.kind==='savemgo_bundle';
    const selectedWorker=()=>st.workers.find(w=>w.id===st.worker);
    const clearSelection=()=>{st.paths.clear();st.members.clear();};
    function selectWorker(id){
      if(st.closed||st.busy||!st.workers.some(w=>w.id===id))return false;
      st.worker=id;st.inventory=null;st.index=null;st.result=null;st.artifacts=[];st.job=null;st.pollError=false;st.error='';
      st.status='Choose Inspect native assets for this PC.';clearSelection();emit();return true;
    }
    async function load(){
      if(st.closed||st.busy)return;
      const token=++epoch;st.loading=true;st.error='';emit();
      const answers=await Promise.allSettled([io.api('/api/catalog/'+encodeURIComponent(io.gid)),io.api('/api/workers')]);
      if(st.closed||token!==epoch)return;
      const oldWorker=st.worker,oldSource=st.game?.launch?.source_fingerprint;
      if(answers[0].status==='fulfilled'&&answers[0].value?.game_id===io.gid){
        st.game=answers[0].value;st.title=st.game.title||st.title;
      }else{st.game=null;st.error='Could not load this title: '+String(answers[0].reason?.message||'catalog identity differs');}
      if(answers[1].status==='fulfilled'){
        st.workers=workers(answers[1].value);
        st.worker=st.workers.find(w=>w.id===st.worker)?.id||st.workers.find(w=>w.id===io.worker||w.name===io.worker)?.id||st.workers[0]?.id||'';
      }else{st.workers=[];st.worker='';st.error+=(st.error?'\n':'')+'Could not load Windows PCs: '+String(answers[1].reason?.message||answers[1].reason);}
      if(oldWorker!==st.worker||oldSource!==st.game?.launch?.source_fingerprint){st.inventory=null;st.index=null;st.result=null;st.artifacts=[];st.job=null;clearSelection();}
      st.loading=false;st.status=supported()?'Choose a PC, then Inspect native assets. Inspection may prepare the owned package locally.':
        'No verified all-asset reader is available for this title. Character model extraction remains available in Models.';
      emit();
    }
    const delay=()=>new Promise(resolve=>{wake=resolve;timer=setTimeout(()=>{timer=null;wake=null;resolve();},io.pollMs??1000);});
    async function downloads(job){
      let found=artifacts(job.artifacts);
      if(job.receipt_id){
        try{const receipt=await io.api('/api/receipts/'+encodeURIComponent(job.receipt_id));found=artifacts(receipt?.artifacts);}
        catch{if(!st.closed&&st.job?.id===job.id)st.status+=' Download links unavailable; reopen this job in Tasks.';}
      }
      const report=job.output?.report_sha256;
      if(/^[a-f0-9]{64}$/.test(report||'')&&!found.some(a=>a.sha256===report))found.push({sha256:report,name:'savemgo-assets.json',size:0});
      if(!st.closed&&st.job?.id===job.id){st.artifacts=found;emit();}
    }
    async function follow(first){
      if(polling||st.closed)return;
      const version=++followVersion;polling=true;st.pollError=false;
      try{
        let job=first;
        while(!st.closed){
          if(!job)job=await io.api('/api/jobs/'+encodeURIComponent(st.job.id));
          if(st.closed)return;
          if(!job||job.id!==st.job.id)throw Error('The job response identity differs.');
          const pct=Number(job.progress?.pct),progress=Number.isFinite(pct)?` ${Math.max(0,Math.min(100,pct)).toFixed(1)}%`:'';
          st.job=job;st.status=`${job.state||'queued'}${progress}: ${job.progress?.msg||st.op}`;emit();
          if(terminal(job.state)){
            st.busy=false;polling=false;
            if(job.state==='succeeded'){
              st.result=object(job.output?.result);
              if(st.op==='inventory'){st.inventory=inventory(st.result);st.index=null;clearSelection();}
              if(st.op==='index')st.index={...st.result,members:array(st.result.members).filter(m=>m&&typeof m.name==='string')};
              st.status=st.op==='export'?'Native assets exported on the selected PC. Model and texture conversion is separate.':'Native asset '+(st.op==='index'?'archive index':'inventory')+' ready.';
            }else st.error=String(job.error||'Job '+job.state);
            emit();await downloads(job);return;
          }
          await delay();job=null;
        }
      }catch(error){
        if(!st.closed){st.error='Could not read job status: '+String(error?.message||error);st.pollError=true;emit();}
      }finally{if(version===followVersion)polling=false;}
    }
    async function run(op,archivePath='',all=false){
      if(st.closed||st.busy||st.loading)return false;
      if(!supported()){st.error='This title has no verified native asset reader.';emit();return false;}
      if(!['inventory','index','export'].includes(op))return false;
      if(op==='index'&&!st.inventory?.assets.some(a=>a.path===archivePath&&/\.(dar|qar)$/i.test(a.path)))return false;
      if(op==='export'&&!all&&!st.paths.size&&!st.members.size)return false;
      const chosen=selectedWorker();
      if(!chosen){st.error='Select an online Windows PC.';emit();return false;}
      st.busy=true;st.error='';st.result=null;st.artifacts=[];st.op=op;st.job=null;st.status='Checking the selected PC...';emit();
      try{
        const available=workers(await io.api('/api/workers'));
        if(st.closed)return false;
        st.workers=available;
        if(!available.some(w=>w.id===chosen.id))throw Error('The selected Windows PC is offline. Choose another PC.');
        const input={game:st.game,op,paths:op==='export'?(all?['*']:[...st.paths]):[],members:op==='export'&&!all?[...st.members.values()]:[],archive_path:op==='index'?archivePath:''};
        const job=await io.api('/api/jobs',{tool:'savemgo_assets',input,require_worker:chosen.id,require_os:'windows'});
        if(!job?.id)throw Error('No job identifier was returned. Check Tasks before retrying.');
        st.job=job;try{io.onJob?.(job);}catch{}if(st.closed)return job;
        await follow(job);return job;
      }catch(error){if(!st.closed){st.busy=false;st.error=String(error?.message||error);emit();}return false;}
      finally{if(!st.job&&!st.closed){st.busy=false;emit();}}
    }
    function select(path,on,archive=''){
      if(st.closed||st.busy)return;
      if(archive){
        if(st.index?.path!==archive||!st.index.members.some(m=>m.name===path))return;
        const key=JSON.stringify([archive,path]);on?st.members.set(key,{archive,name:path}):st.members.delete(key);
      }else{
        if(!st.inventory?.assets.some(a=>a.path===path))return;
        on?st.paths.add(path):st.paths.delete(path);
      }
      emit();
    }
    async function cancel(){
      if(st.closed||!st.job||terminal(st.job.state)||cancelling)return;
      const id=st.job.id;cancelling=true;st.error='';st.status='Requesting job cancellation...';emit();
      try{await io.api('/api/jobs/'+encodeURIComponent(id)+'/cancel',{});if(st.pollError&&!st.closed&&st.job?.id===id)follow();}
      catch(error){if(!st.closed&&st.job?.id===id)st.error='Cancellation failed: '+String(error?.message||error);}
      finally{cancelling=false;emit();}
    }
    function close(){st.closed=true;epoch++;if(timer!==null)clearTimeout(timer);timer=null;wake?.();wake=null;}
    return {state:st,supported,load,run,select,selectWorker,cancel,close,
      exportAll:()=>{if(st.closed||st.busy||!st.inventory)return false;clearSelection();return run('export','',true);},
      retry:()=>{st.error='';return follow();},clear:()=>{if(!st.busy){clearSelection();emit();}}};
  }
  function open(options){
    const doc=options.document||globalThis.document,previous=doc.activeElement;
    doc.querySelector('.gbox-game-assets')?.gboxClose?.();
    const d=doc.createElement('dialog');d.className='gbox-game-assets';d.setAttribute('aria-labelledby','ga-title');
    d.innerHTML=`<style>
      .gbox-game-assets{box-sizing:border-box;width:min(1100px,96vw);max-height:94vh;overflow:hidden;padding:16px;border:1px solid #505a70;border-radius:10px;background:#171d28;color:#edf1fa;font:14px system-ui;color-scheme:dark}.gbox-game-assets[open]{display:flex;flex-direction:column;gap:10px}.gbox-game-assets::backdrop{background:#000b}.gbox-game-assets header,.ga-controls,.ga-tabs,.ga-footer{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.gbox-game-assets h2{font-size:20px;margin:0;flex:1}.gbox-game-assets button,.gbox-game-assets select,.gbox-game-assets input{font:inherit;color:inherit;background:#263044;border:1px solid #536079;border-radius:5px;padding:7px}.gbox-game-assets button:disabled{opacity:.45}.gbox-game-assets [hidden]{display:none!important}.ga-game,.ga-note,.ga-status,.ga-result{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.ga-game{color:#c3cce1}.ga-note{font-size:12px;color:#c4ccdf}.ga-status{max-height:72px;overflow:auto}.ga-error{color:#ffb6b6}.ga-table{overflow:auto;min-height:100px;max-height:48vh;border:1px solid #46516a}.ga-table table{width:100%;border-collapse:collapse}.ga-table th,.ga-table td{text-align:left;border-bottom:1px solid #36415a;padding:7px;font-size:12px;overflow-wrap:anywhere}.ga-table th{position:sticky;top:0;background:#202a3a}.ga-table td:nth-child(2){max-width:560px}.ga-filter{flex:1;min-width:180px}.ga-links a{display:inline-block;margin-right:12px;color:#b2c6ff}.ga-result{font-size:12px;max-height:100px;overflow:auto}.ga-footer small{flex:1;color:#bdc7db}@media(max-width:600px){.gbox-game-assets{padding:10px}.ga-controls label{width:100%}.ga-table th,.ga-table td{padding:5px}.ga-table{max-height:38vh}}
      .gbox-game-assets[open]>*{flex-shrink:0}.gbox-game-assets .ga-table{flex-shrink:1;min-height:80px}.gbox-game-assets .ga-table table{color:inherit}.gbox-game-assets .ga-status{min-height:20px}.gbox-game-assets .ga-footer small{flex-basis:100%}
      @media(max-height:700px){.gbox-game-assets{padding:10px;font-size:12px}.gbox-game-assets[open]{gap:6px}.gbox-game-assets button,.gbox-game-assets input,.gbox-game-assets select{padding:5px}.gbox-game-assets .ga-note{font-size:11px}.gbox-game-assets .ga-status{min-height:16px;max-height:32px}.gbox-game-assets .ga-result{max-height:36px}.gbox-game-assets .ga-table{min-height:70px;max-height:32vh}}
      </style><header><h2 id="ga-title">Game assets</h2><button type="button" data-ga-close aria-label="Close asset window">Close</button></header>
      <p class="ga-game" data-ga-game></p><p class="ga-note" data-ga-scope-note></p>
      <div class="ga-controls"><label>Windows PC <select data-ga-worker aria-label="Extraction PC"></select></label><button data-ga-inspect type="button">Inspect native assets</button><button data-ga-refresh type="button">Refresh PCs</button><button data-ga-models type="button">Character models</button></div>
      <p class="ga-status" data-ga-status role="status" aria-live="polite"></p><p class="ga-note" data-ga-readiness></p>
      <div class="ga-tabs"><button data-ga-files type="button">Native files</button><button data-ga-members type="button" disabled>Archive members</button><input class="ga-filter" data-ga-filter type="search" placeholder="Filter paths or asset types" aria-label="Filter native assets"></div>
      <div class="ga-table"><table><thead><tr><th>Select</th><th>Native asset path</th><th>Type / size</th><th>Action</th></tr></thead><tbody data-ga-rows></tbody></table></div>
      <div class="ga-controls"><button data-ga-prev type="button">Previous</button><span data-ga-page></span><button data-ga-next type="button">Next</button><span data-ga-count></span><button data-ga-clear type="button">Clear selection</button></div>
      <p class="ga-result" data-ga-result></p><div class="ga-links" data-ga-links></div>
      <footer class="ga-footer"><button data-ga-export type="button">Extract selected native assets</button><button data-ga-all type="button">Extract all native resources</button><button data-ga-cancel type="button" disabled>Cancel job</button><button data-ga-retry type="button" hidden>Retry job status</button><small>Conversion to GLB/PNG and cross-game reimport are pending.</small></footer>`;
    const q=s=>d.querySelector(s);let page=0,mode='files',rows=[];
    const ctl=createController({...options,render:render});
    function render(st){
      q('[data-ga-game]').textContent=st.title;
      q('[data-ga-scope-note]').textContent='Native game files and archive members are separate from converted models and textures. '+(ctl.supported()?'First use on a PC may prepare the full 8.85 GB SaveMGO package. Large exports remain on the selected PC. ':'')+'Closing this window leaves submitted jobs in Tasks.';
      q('[data-ga-worker]').innerHTML=st.workers.length?st.workers.map(w=>`<option value="${esc(w.id)}">${esc(w.name)}</option>`).join(''):'<option value="">No online Windows PC</option>';
      q('[data-ga-worker]').value=st.worker;q('[data-ga-worker]').disabled=st.busy||st.loading;
      q('[data-ga-inspect]').disabled=st.busy||st.loading||!ctl.supported()||!st.worker;
      q('[data-ga-refresh]').disabled=st.busy||st.loading;
      q('[data-ga-status]').textContent=[st.status,st.job?'Job '+st.job.id:'',st.error].filter(Boolean).join('\n');
      q('[data-ga-status]').classList.toggle('ga-error',!!st.error);
      q('[data-ga-readiness]').textContent=ctl.supported()?'Native export available. Model, texture and environment conversion: pending. Cross-game replacement: not verified.':'No verified all-asset reader for this title. Use Character models for existing model workflows.';
      q('[data-ga-models]').hidden=typeof options.models!=='function';
      q('[data-ga-members]').disabled=!st.index;q('[data-ga-members]').textContent='Archive members'+(st.index?' ('+st.index.members.length+')':'');
      if(mode==='members'&&!st.index)mode='files';
      const filter=q('[data-ga-filter]').value.toLowerCase();
      rows=(mode==='members'?array(st.index?.members):array(st.inventory?.assets)).filter(r=>[r.path,r.name,r.kind,r.format].join(' ').toLowerCase().includes(filter));
      const pages=Math.max(1,Math.ceil(rows.length/100));page=Math.min(page,pages-1);
      const table=q('.ga-table'),scroll=table.scrollTop;
      q('[data-ga-rows]').innerHTML=rows.slice(page*100,page*100+100).map((r,i)=>{
        const name=mode==='members'?r.name:r.path,chosen=mode==='members'?st.members.has(JSON.stringify([st.index.path,name])):st.paths.has(name);
        return `<tr><td><input type="checkbox" data-ga-select="${i+page*100}" aria-label="Select ${esc(name)}" ${chosen?'checked':''} ${st.busy?'disabled':''}></td><td>${esc(name)}</td><td>${esc(r.kind||r.format||'native')} / ${size(r.size)}</td><td>${mode==='files'&&/\.(dar|qar)$/i.test(name)?`<button type="button" data-ga-index="${i+page*100}" ${st.busy?'disabled':''}>Inspect members</button>`:'Native only'}</td></tr>`;
      }).join('')||'<tr><td colspan="4">'+(st.inventory?'No matching native assets.':'Inspect this title to list its native resources.')+'</td></tr>';
      table.scrollTop=scroll;q('[data-ga-page]').textContent=`Page ${page+1} / ${pages} - ${rows.length} assets`;
      q('[data-ga-prev]').disabled=page<=0;q('[data-ga-next]').disabled=page>=pages-1;
      const count=st.paths.size+st.members.size;q('[data-ga-count]').textContent=count+' selected';
      q('[data-ga-clear]').disabled=st.busy||!count;q('[data-ga-export]').disabled=st.busy||!count||!ctl.supported();
      q('[data-ga-all]').disabled=st.busy||!st.inventory||!ctl.supported()||!st.worker;
      q('[data-ga-cancel]').disabled=!st.job||terminal(st.job.state);q('[data-ga-retry]').hidden=!st.pollError;
      const result=st.result;
      q('[data-ga-result]').textContent=result?.state==='exported'?`Native export: ${result.directory||'local output'}\nWorker: ${result.worker||st.workers.find(w=>w.id===st.worker)?.name||st.worker}\n${array(result.files).length} files, ${size(result.bytes)}. ${result.download?'Download available below.':'Large/local output remains on this PC.'}`:
        st.inventory?`${st.inventory.summary.files??st.inventory.assets.length} native files, ${size(st.inventory.summary.bytes)}.`+(st.inventory.issues.length?'\n'+st.inventory.issues.slice(0,5).map(i=>String(i.reason||i)).join('\n'):''):'';
      q('[data-ga-links]').innerHTML=st.artifacts.map(a=>`<a target="_blank" rel="noopener" href="${esc((options.media||((u)=>u))('/api/artifacts/'+a.sha256))}">${esc(a.name)}${a.size?' ('+size(a.size)+')':''}</a>`).join('');
      q('[data-ga-links]').hidden=!st.artifacts.length;
    }
    function close(){if(ctl.state.closed)return;ctl.close();if(d.open)d.close();d.remove();previous?.focus?.();}
    d.gboxClose=close;d.addEventListener('cancel',e=>{e.preventDefault();close();});d.addEventListener('close',close);
    q('[data-ga-close]').onclick=close;q('[data-ga-inspect]').onclick=()=>{page=0;mode='files';ctl.run('inventory');};
    q('[data-ga-refresh]').onclick=()=>ctl.load();q('[data-ga-worker]').onchange=e=>{page=0;ctl.selectWorker(e.target.value);};
    q('[data-ga-models]').onclick=()=>{close();options.models?.(options.gid,ctl.state.title);};
    q('[data-ga-filter]').oninput=()=>{page=0;render(ctl.state);};
    q('[data-ga-files]').onclick=()=>{mode='files';page=0;render(ctl.state);};q('[data-ga-members]').onclick=()=>{mode='members';page=0;render(ctl.state);};
    q('[data-ga-prev]').onclick=()=>{page--;render(ctl.state);};q('[data-ga-next]').onclick=()=>{page++;render(ctl.state);};
    q('[data-ga-rows]').onchange=e=>{const n=e.target.dataset.gaSelect;if(n===undefined||!rows[+n])return;const row=rows[+n];ctl.select(mode==='members'?row.name:row.path,e.target.checked,mode==='members'?ctl.state.index.path:'');};
    q('[data-ga-rows]').onclick=async e=>{const b=e.target.closest('[data-ga-index]');if(!b)return;const row=rows[+b.dataset.gaIndex];if(!row)return;await ctl.run('index',row.path);if(!ctl.state.closed&&ctl.state.index?.path===row.path){mode='members';page=0;render(ctl.state);}};
    q('[data-ga-clear]').onclick=()=>ctl.clear();q('[data-ga-export]').onclick=()=>ctl.run('export');q('[data-ga-all]').onclick=()=>ctl.exportAll();q('[data-ga-cancel]').onclick=()=>ctl.cancel();q('[data-ga-retry]').onclick=()=>ctl.retry();
    doc.body.appendChild(d);d.showModal();render(ctl.state);const ready=ctl.load();
    return {element:d,close,controller:ctl,ready};
  }
  return {open,createController,workers,inventory,artifacts};
});
