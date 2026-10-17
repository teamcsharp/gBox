// A catalog picker for model inspection, independent of play-library filters.
(function(root){
  'use strict';
  let active;
  function open(io,state={}){
    active?.close();
    const previous=document.activeElement,dialog=document.createElement('dialog');
    dialog.className='gml-dialog';dialog.setAttribute('aria-labelledby','gml-title');
    dialog.innerHTML=`<style>
      .gml-dialog{color:var(--fg,#eee);background:var(--bg,#16161a);border:1px solid var(--line,#444);border-radius:12px;width:min(820px,90vw);max-height:85vh;padding:20px;box-sizing:border-box}
      .gml-dialog::backdrop{background:#0009}.gml-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.gml-head h2{margin:0}.gml-search{display:flex;gap:10px;margin:16px 0;flex-wrap:wrap}.gml-search input{flex:1;min-width:150px}.gml-scroll{max-height:52vh;overflow:auto;overscroll-behavior:contain}.gml-rows{display:grid;gap:8px}.gml-game{display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:left;padding:12px;width:100%;color:inherit;background:var(--card,#24242b);border:1px solid var(--line,#444);border-radius:7px;cursor:pointer}.gml-game:hover,.gml-game:focus-visible{border-color:var(--acc,#929bff)}.gml-game small{display:block;margin-top:4px}.gml-game strong{overflow-wrap:anywhere}.gml-more{margin:12px 0;width:100%}
      </style><div class="gml-head"><h2 id="gml-title">Game library · Models</h2><button class="act" data-gml-close aria-label="Close game model library">Close</button></div>
      <p class="mut">Choose a title to browse its models.</p><div class="gml-search"><input type="search" aria-label="Search games for models" placeholder="Search all games" data-gml-search><select aria-label="Game platform" data-gml-platform><option value="">All platforms</option></select></div>
      <p data-gml-status role="status" aria-live="polite"></p><div class="gml-scroll" tabindex="0" aria-label="Games"><div class="gml-rows"></div><button class="act gml-more" hidden>Load more games</button></div>`;
    document.body.append(dialog);
    const q=s=>dialog.querySelector(s),search=q('[data-gml-search]'),platform=q('[data-gml-platform]'),rows=q('.gml-rows'),scroll=q('.gml-scroll'),more=q('.gml-more'),status=q('[data-gml-status]');
    let dead=false,revision=0,loading=false,offset=0,total=0,timer;
    function close(){if(dead)return;dead=true;revision++;clearTimeout(timer);dialog.close();dialog.remove();if(active===ctl)active=null;if(previous?.isConnected)previous.focus();}
    const ctl={close};active=ctl;
    dialog.addEventListener('cancel',e=>{e.preventDefault();close();});q('[data-gml-close]').onclick=close;
    search.value=state.q||'';
    async function load(reset=false){
      if(dead||(!reset&&loading))return;
      if(reset){revision++;offset=0;total=0;rows.replaceChildren();}
      const current=revision;loading=true;more.disabled=true;status.textContent='Loading games…';
      try{
        const result=await io.api('/api/catalog?'+new URLSearchParams({q:state.q||'',platform:state.platform||'',sort:'name',offset,limit:100}));
        if(dead||current!==revision)return;
        for(const game of result.items){
          const button=document.createElement('button');button.className='gml-game';button.type='button';
          const label=document.createElement('span'),title=document.createElement('strong'),system=document.createElement('small'),action=document.createElement('span');
          title.textContent=game.title;system.className='mut';system.textContent=game.system||game.platform||'Unknown platform';action.textContent='View models →';
          label.append(title,system);button.append(label,action);button.onclick=()=>{close();io.openGame(game.game_id,game.title);};rows.append(button);
        }
        offset+=result.items.length;total=result.total;
        status.textContent=total?`${offset.toLocaleString()} of ${total.toLocaleString()} games`:'No games match your search.';
        more.hidden=offset>=total||!result.items.length;more.textContent='Load more games';
      }catch(e){if(!dead&&current===revision){status.textContent='Games could not load: '+e.message;more.hidden=false;more.textContent='Retry loading games';}}
      finally{if(!dead&&current===revision){loading=false;more.disabled=false;}}
    }
    search.oninput=()=>{state.q=search.value;clearTimeout(timer);revision++;loading=false;rows.replaceChildren();more.hidden=true;status.textContent='Searching games…';timer=setTimeout(()=>load(true),200);};
    platform.onchange=()=>{state.platform=platform.value;clearTimeout(timer);load(true);};
    more.onclick=()=>load();scroll.onscroll=()=>{if(!more.hidden&&scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<160)load();};
    dialog.showModal();search.focus();ctl.ready=load(true);
    ctl.facets=io.api('/api/catalog/facets').then(f=>{
      if(dead)return;
      const names=Object.keys(f.platforms||{}).filter(p=>p&&p!=='null');if(state.platform&&!names.includes(state.platform))names.push(state.platform);
      for(const p of names.sort()){const option=document.createElement('option');option.value=p;option.textContent=p;platform.append(option);}platform.value=state.platform||'';
    }).catch(()=>{});
    return ctl;
  }
  root.GBoxGameModelLibrary={open};
})(typeof window==='undefined'?globalThis:window);
