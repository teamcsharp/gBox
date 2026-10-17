/* Choose a cover from paged image search. Remote previews stay behind gBox's media proxy. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.GBoxCoverPicker=factory();
})(typeof window!=='undefined'?window:globalThis,function(){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  const PAGE_SIZE=9;
  const sourceName=value=>value==='vimm'?"Vimm's Lair":'Web';
  function defaultQuery(title){
    return String(title||'').replace(/\s*\((?:USA|US|Europe|Japan|World|Asia|Australia|Korea|China|Taiwan|Brazil|Canada|France|Germany|Italy|Spain|Rev(?:ision)?\s+[^)]+)\)/gi,'').replace(/\s+/g,' ').trim()+' cover';
  }
  function remoteURL(value){
    try{const url=new URL(String(value||''));return /^https?:$/.test(url.protocol)&&!url.username&&!url.password?url.href:'';}
    catch{return '';}
  }
  function results(items){
    return (Array.isArray(items)?items:[]).filter(item=>item&&remoteURL(item.url)).slice(0,PAGE_SIZE).map(item=>({
      url:remoteURL(item.url),thumbnail:remoteURL(item.thumbnail)||remoteURL(item.url),
      title:String(item.title||'Cover image'),source_url:remoteURL(item.source_url)||remoteURL(item.url),
      source:String(item.source||'')
    }));
  }
  function open(options){
    const {gid,title,api,onSaved}=options||{};
    if(!gid||typeof api!=='function')throw new Error('A game and gBox API connection are required to choose cover art.');
    const doc=options.document||globalThis.document,previous=doc.activeElement;
    doc.querySelector('.gbox-cover-picker')?.gboxClose?.();
    const d=doc.createElement('dialog');d.className='gbox-cover-picker';
    d.setAttribute('aria-labelledby','gbox-cover-picker-title');
    d.innerHTML=`<style>
      .gbox-cover-picker{box-sizing:border-box;width:min(940px,96vw);max-height:94vh;overflow:hidden;padding:18px;border:1px solid var(--line,#4c5367);border-radius:12px;background:var(--card,#191c25);color:var(--fg,#eef0f7);color-scheme:dark;font:14px system-ui;box-shadow:0 20px 90px #0009}.gbox-cover-picker[open]{display:flex;flex-direction:column}.gbox-cover-picker>*:not(.gbox-cover-picker-results){flex-shrink:0}
      .gbox-cover-picker::backdrop{background:#000b}.gbox-cover-picker h2{font-size:20px;margin:0}.gbox-cover-picker-header{display:flex;align-items:center;gap:12px}.gbox-cover-picker-header h2{flex:1}.gbox-cover-picker-game{margin:6px 0 14px;color:#bac3d5;overflow-wrap:anywhere}
      .gbox-cover-picker button,.gbox-cover-picker input,.gbox-cover-picker select{box-sizing:border-box;font:inherit;color:inherit;border:1px solid #51596d;border-radius:6px;background:#252b39;padding:8px 10px}.gbox-cover-picker button{cursor:pointer}.gbox-cover-picker button:disabled{cursor:default;opacity:.5}.gbox-cover-picker button:focus-visible,.gbox-cover-picker a:focus-visible,.gbox-cover-picker input:focus-visible,.gbox-cover-picker select:focus-visible{outline:2px solid #a8b1ff;outline-offset:2px}
      .gbox-cover-picker-form{display:flex;align-items:end;gap:9px;flex-wrap:wrap}.gbox-cover-picker-form label{display:flex;flex-direction:column;gap:5px}.gbox-cover-picker-query{flex:1;min-width:190px}.gbox-cover-picker-form input{width:100%}.gbox-cover-picker-status{min-height:20px;max-height:70px;overflow:auto;margin:12px 0;white-space:pre-wrap;overflow-wrap:anywhere}.gbox-cover-picker-results{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-auto-rows:max-content;align-content:start;gap:10px;min-height:0;overflow:auto}
      .gbox-cover-picker-result{min-width:0;border:1px solid #42495d;border-radius:8px;padding:6px;background:#121722}.gbox-cover-picker-result[data-selected=true]{border-color:#a9b0ff;box-shadow:0 0 0 1px #a9b0ff}.gbox-cover-picker-result>button{display:flex;flex-direction:column;width:100%;gap:6px;padding:0;border:0;border-radius:4px;background:transparent;text-align:left}.gbox-cover-picker-result img{width:100%;height:118px;object-fit:contain;background:#0d1119;border-radius:4px}.gbox-cover-picker-result strong{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.gbox-cover-picker-source{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:#adb9e7;margin:6px 0 0;text-decoration:none}.gbox-cover-picker-selection{min-height:20px;margin:12px 0;font-size:12px;color:#c3cceb;overflow-wrap:anywhere}
      .gbox-cover-picker-footer{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.gbox-cover-picker-page{flex:1;min-width:90px;text-align:center;color:#bac3d5}.gbox-cover-picker-save{background:#747fe7!important;color:white!important;border-color:#a9b0ff!important}.gbox-cover-picker-error{color:#ffb8b8}.gbox-cover-picker-preview-error{box-sizing:border-box;min-height:125px;width:100%;padding:20px 8px;text-align:center;background:#0d1119;color:#c5cadd;font-size:12px}.gbox-cover-picker-direct{margin:0 0 12px;font-size:12px}.gbox-cover-picker-direct summary{cursor:pointer;color:#c3cceb}.gbox-cover-picker-direct form{display:flex;align-items:end;gap:8px;flex-wrap:wrap;margin:8px 0}.gbox-cover-picker-direct label{display:flex;flex:1;min-width:190px;flex-direction:column;gap:5px}.gbox-cover-picker-direct small{color:#bac3d5}
      @media(max-width:550px){.gbox-cover-picker{padding:12px}.gbox-cover-picker-result img{height:90px}.gbox-cover-picker-results{gap:6px}.gbox-cover-picker-footer button{padding:7px}.gbox-cover-picker-page{min-width:65px}}
      @media(max-height:700px){.gbox-cover-picker{padding:12px}.gbox-cover-picker-result img{height:90px}.gbox-cover-picker-preview-error{min-height:90px}.gbox-cover-picker-results{gap:6px}.gbox-cover-picker-game{margin-bottom:8px}.gbox-cover-picker-status,.gbox-cover-picker-selection{margin:8px 0}.gbox-cover-picker-direct{margin-bottom:8px}}
    </style><header class="gbox-cover-picker-header"><h2 id="gbox-cover-picker-title">Choose cover art</h2><button type="button" data-cover-close aria-label="Close cover picker">&#215;</button></header>
      <p class="gbox-cover-picker-game"></p>
      <form class="gbox-cover-picker-form"><label class="gbox-cover-picker-query">Image search<input name="query" type="search" maxlength="300" required autocomplete="off" placeholder="Game title cover"></label>
      <label>Source<select name="source"><option value="web">Web</option><option value="vimm">Vimm's Lair</option></select></label><button type="submit" data-cover-search>Search</button></form>
      <p class="gbox-cover-picker-status" data-cover-status role="status" aria-live="polite"></p>
      <div class="gbox-cover-picker-results" data-cover-results aria-label="Cover image results"></div>
      <p class="gbox-cover-picker-selection" data-cover-selection>Select an image, then choose Use selected cover.</p>
      <details class="gbox-cover-picker-direct"><summary>Use image URL</summary><form data-cover-url-form><label>Direct image URL<input name="image_url" type="url" maxlength="4096" required placeholder="https://example.com/cover.jpg" autocomplete="off"></label><button type="submit" data-cover-url-save>Use image URL</button></form><small>Paste a direct HTTP or HTTPS image link.</small></details>
      <footer class="gbox-cover-picker-footer"><button type="button" data-cover-prev disabled>&#8592; Previous</button><span class="gbox-cover-picker-page" data-cover-page>Page 1</span><button type="button" data-cover-next disabled>Next &#8594;</button><button type="button" data-cover-cancel>Cancel</button><button type="button" class="gbox-cover-picker-save" data-cover-save disabled>Use selected cover</button></footer>`;
    const q=selector=>d.querySelector(selector),media=options.media||((url)=>url),base='/api/catalog/'+encodeURIComponent(gid)+'/cover';
    q('.gbox-cover-picker-game').textContent=String(title||gid);
    q('[name=query]').value=defaultQuery(title||gid);
    let closed=false,request=0,loading=false,saving=false,items=[],selected=-1,page=1,hasNext=false;
    let committedQuery=q('[name=query]').value,committedSource='web';
    function status(text,error=false){if(closed)return;q('[data-cover-status]').textContent=text;q('[data-cover-status]').classList.toggle('gbox-cover-picker-error',error);}
    function controls(){
      if(closed)return;
      q('[data-cover-prev]').disabled=loading||saving||page<=1;
      q('[data-cover-next]').disabled=loading||saving||!hasNext;
      q('[data-cover-save]').disabled=loading||saving||selected<0;
      q('[data-cover-search]').disabled=saving;
      q('[name=source]').disabled=saving;
      q('[name=query]').disabled=saving;
      q('[name=image_url]').disabled=saving;
      q('[data-cover-url-save]').disabled=saving;
      q('[data-cover-page]').textContent='Page '+page;
      for(const button of d.querySelectorAll('[data-cover-index]'))button.disabled=loading||saving;
    }
    function render(){
      const grid=q('[data-cover-results]');
      grid.innerHTML=items.map((item,index)=>`<article class="gbox-cover-picker-result" data-selected="${index===selected}"><button type="button" data-cover-index="${index}" aria-pressed="${index===selected}" aria-label="Select ${esc(item.title)}"><img alt="${esc(item.title)}" loading="lazy" decoding="async"><span class="gbox-cover-picker-preview-error" data-cover-preview-error hidden>Preview unavailable</span><strong>${esc(item.title)}</strong></button><a class="gbox-cover-picker-source" href="${esc(item.source_url)}" target="_blank" rel="noopener noreferrer">${esc(item.source||sourceName(committedSource))} &#8599;</a></article>`).join('');
      Array.from(grid.querySelectorAll('img')).forEach((image,index)=>{
        const item=items[index];
        let triedOriginal=item.thumbnail===item.url;
        image.onerror=()=>{
          if(!triedOriginal){triedOriginal=true;image.src=media(base+'/preview?url='+encodeURIComponent(item.url));return;}
          image.onerror=null;image.hidden=true;image.parentElement.querySelector('[data-cover-preview-error]').hidden=false;
        };
        image.src=media(base+'/preview?url='+encodeURIComponent(item.thumbnail));
      });
      controls();
    }
    async function search(nextPage=1,query=q('[name=query]').value,source=q('[name=source]').value){
      if(closed||saving)return;
      query=String(query||'').trim();source=source==='vimm'?'vimm':'web';
      if(!query){status('Enter a game title or image search.',true);q('[name=query]').focus();return;}
      const token=++request;loading=true;selected=-1;items=[];hasNext=false;
      page=Math.max(1,Number.parseInt(nextPage,10)||1);committedQuery=query;committedSource=source;
      q('[data-cover-selection]').textContent='Select an image, then choose Use selected cover.';
      q('[data-cover-results]').setAttribute('aria-busy','true');render();status('Searching '+sourceName(source)+' for "'+query+'"...');
      try{
        const result=await api(base+'/search?q='+encodeURIComponent(query)+'&source='+source+'&page='+page+'&page_size='+PAGE_SIZE);
        if(closed||token!==request)return;
        items=results(result?.items);page=Math.max(1,Number.parseInt(result?.page,10)||page);hasNext=!!result?.has_next;
        const warnings=[].concat(result?.warnings||[],result?.warning||[]).filter(Boolean).map(value=>typeof value==='string'?value:String(value.message||value.detail||JSON.stringify(value))).join('\n');
        loading=false;render();status(items.length?`${items.length} image${items.length===1?'':'s'} - ${sourceName(source)} - Page ${page}`:'No images found. Try another search, source, or image URL.'+(warnings?'\n'+warnings:''),!items.length&&!!warnings);
      }catch(error){
        if(closed||token!==request)return;
        loading=false;items=[];hasNext=false;render();status('Could not search for covers: '+String(error?.message||error),true);
      }finally{if(!closed&&token===request){q('[data-cover-results]').setAttribute('aria-busy','false');controls();}}
    }
    const close=()=>{
      if(closed)return;
      closed=true;request++;
      if(d.open)d.close();d.remove();previous?.focus?.();
    };
    d.gboxClose=close;
    d.addEventListener('cancel',event=>{event.preventDefault();close();});
    d.addEventListener('close',close);
    q('[data-cover-close]').onclick=close;q('[data-cover-cancel]').onclick=close;
    q('form').onsubmit=event=>{event.preventDefault();search(1);};
    q('[name=source]').onchange=()=>search(1);
    q('[data-cover-prev]').onclick=()=>search(page-1,committedQuery,committedSource);
    q('[data-cover-next]').onclick=()=>search(page+1,committedQuery,committedSource);
    q('[data-cover-results]').onclick=event=>{
      const button=event.target.closest('[data-cover-index]');if(!button||loading||saving)return;
      selected=Number(button.dataset.coverIndex);
      q('[data-cover-selection]').textContent='Selected: '+items[selected].title;
      for(const item of d.querySelectorAll('[data-cover-index]')){
        const picked=Number(item.dataset.coverIndex)===selected;
        item.setAttribute('aria-pressed',String(picked));item.closest('article').dataset.selected=String(picked);
      }
      controls();
    };
    async function saveCover(item){
      if(closed||saving)return;
      request++;loading=false;saving=true;q('[data-cover-results]').setAttribute('aria-busy','false');controls();status('Saving this cover...');
      try{
        const result=await api(base,{url:item.url,kind:'boxart'});
        // The already submitted save may finish after closing. Refresh its title
        // in either case, but never reopen a dismissed dialog.
        close();
        if(onSaved)await onSaved(result,item);
      }catch(error){if(!closed)status('Could not save this cover: '+String(error?.message||error),true);}
      finally{saving=false;controls();}
    };
    q('[data-cover-save]').onclick=()=>{if(!loading&&selected>=0)return saveCover(items[selected]);};
    q('[name=image_url]').oninvalid=()=>status('Enter a direct HTTP or HTTPS image URL.',true);
    q('[data-cover-url-form]').onsubmit=event=>{
      event.preventDefault();
      const url=remoteURL(q('[name=image_url]').value.trim());
      if(!url){status('Enter a direct HTTP or HTTPS image URL without a username or password.',true);return;}
      saveCover({url,thumbnail:url,title:'Image URL',source_url:url,source:'Direct image URL'});
    };
    doc.body.appendChild(d);d.showModal();q('[name=query]').focus();
    search();
    return {element:d,close,search};
  }
  return {open,results,remoteURL,defaultQuery,PAGE_SIZE};
});
