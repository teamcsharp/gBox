// Titles with available extracted models, independent of the play library.
(function(root){
  'use strict';
  let active;
  function gamesFromModels(models){
    const games=new Map(),seen=new Set();
    for(const model of Array.isArray(models)?models:[]){
      const source=model?.source,gid=source?.game_id;
      if(typeof gid!=='string'||!gid.trim()||typeof model.slug!=='string'||!model.slug||seen.has(model.slug)
        ||typeof model.model!=='string'||!model.model||!Number.isFinite(model.model_bytes)||model.model_bytes<=0)continue;
      seen.add(model.slug);
      const added=Number.isFinite(model.added)&&model.added>0?model.added:null;
      let game=games.get(gid);
      if(!game){game={game_id:gid,title:typeof source.game_title==='string'&&source.game_title.trim()?source.game_title:gid,
        platform:typeof source.platform==='string'?source.platform:'',count:0,added:null};games.set(gid,game);}
      game.count++;
      if(added!==null&&(game.added===null||added>game.added))game.added=added;
    }
    return [...games.values()].sort((a,b)=>(b.added??-1)-(a.added??-1)||a.title.localeCompare(b.title)||a.game_id.localeCompare(b.game_id));
  }
  function open(io,state={}){
    active?.close();
    const previous=document.activeElement,dialog=document.createElement('dialog');
    dialog.className='gml-dialog';dialog.setAttribute('aria-labelledby','gml-title');
    dialog.innerHTML=`<style>
      .gml-dialog{color:var(--fg,#eee);background:var(--bg,#16161a);border:1px solid var(--line,#444);border-radius:12px;width:min(820px,90vw);max-height:85vh;padding:20px;box-sizing:border-box}
      .gml-dialog::backdrop{background:#0009}.gml-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.gml-head h2{margin:0}.gml-search{display:flex;gap:10px;margin:16px 0;flex-wrap:wrap}.gml-search input{flex:1;min-width:150px}.gml-scroll{max-height:52vh;overflow:auto;overscroll-behavior:contain}.gml-rows{display:grid;gap:8px}.gml-game{display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:left;padding:12px;width:100%;color:inherit;background:var(--card,#24242b);border:1px solid var(--line,#444);border-radius:7px;cursor:pointer}.gml-game:hover,.gml-game:focus-visible{border-color:var(--acc,#929bff)}.gml-game small{display:block;margin-top:4px}.gml-game strong{overflow-wrap:anywhere}.gml-more{margin:12px 0;width:100%}
      </style><div class="gml-head"><h2 id="gml-title">Game library · Models</h2><button class="act" data-gml-close aria-label="Close game model library">Close</button></div>
      <p class="mut">Games with extracted models, most recently added first. Choose a title to browse its models.</p><div class="gml-search"><input type="search" aria-label="Search games for models" placeholder="Search extracted games" data-gml-search><select aria-label="Game platform" data-gml-platform><option value="">All platforms</option></select></div>
      <p data-gml-status role="status" aria-live="polite"></p><div class="gml-scroll" tabindex="0" aria-label="Games"><div class="gml-rows"></div><button class="act gml-more" hidden>Load more games</button></div>`;
    document.body.append(dialog);
    const q=s=>dialog.querySelector(s),search=q('[data-gml-search]'),platform=q('[data-gml-platform]'),rows=q('.gml-rows'),scroll=q('.gml-scroll'),more=q('.gml-more'),status=q('[data-gml-status]');
    let dead=false,revision=0,loading=false,offset=0,games=[],filtered=[],failed=false,timer;
    function close(){if(dead)return;dead=true;revision++;clearTimeout(timer);dialog.close();dialog.remove();if(active===ctl)active=null;if(previous?.isConnected)previous.focus();}
    const ctl={close};active=ctl;
    dialog.addEventListener('cancel',e=>{e.preventDefault();close();});q('[data-gml-close]').onclick=close;
    search.value=state.q||'';
    function render(reset=false){
      if(dead||loading||failed)return;
      if(reset){offset=0;rows.replaceChildren();scroll.scrollTop=0;
        const query=(state.q||'').trim().toLocaleLowerCase();
        filtered=games.filter(g=>(!query||g.title.toLocaleLowerCase().includes(query))&&(!state.platform||g.platform===state.platform));}
      for(const game of filtered.slice(offset,offset+100)){
        const button=document.createElement('button');button.className='gml-game';button.type='button';button.dataset.gameId=game.game_id;
        const label=document.createElement('span'),title=document.createElement('strong'),system=document.createElement('small'),action=document.createElement('span');
        title.textContent=game.title;system.className='mut';
        system.textContent=`${game.platform||'Unknown platform'} - ${game.count} model${game.count===1?'':'s'} - ${game.added===null?'Date not recorded':'Latest added '+new Date(game.added*1000).toLocaleString()}`;
        action.textContent='View models';label.append(title,system);button.append(label,action);
        button.onclick=()=>{close();io.openGame(game.game_id,game.title);};rows.append(button);
      }
      offset=Math.min(offset+100,filtered.length);
      status.textContent=filtered.length?`${offset.toLocaleString()} of ${filtered.length.toLocaleString()} extracted games`:
        games.length?'No extracted games match your search.':'No extracted game models yet. Extract models from a game to list it here.';
      more.hidden=offset>=filtered.length;more.disabled=false;more.textContent='Load more games';
    }
    async function load(){
      if(dead||loading)return;
      const current=++revision;loading=true;failed=false;more.hidden=true;status.textContent='Loading extracted games...';
      try{
        const models=await io.api('/api/characters');
        if(dead||current!==revision)return;
        if(!Array.isArray(models))throw new Error('Invalid model library response');
        games=gamesFromModels(models);
        platform.replaceChildren(platform.firstElementChild);
        const names=[...new Set(games.map(g=>g.platform).filter(Boolean))].sort();
        if(state.platform&&!names.includes(state.platform))names.push(state.platform);
        for(const name of names){const option=document.createElement('option');option.value=name;option.textContent=name;platform.append(option);}platform.value=state.platform||'';
        loading=false;render(true);
      }catch(e){if(!dead&&current===revision){failed=true;status.textContent='Extracted games could not load: '+e.message;more.hidden=false;more.disabled=false;more.textContent='Retry loading games';}}
      finally{if(!dead&&current===revision)loading=false;}
    }
    search.oninput=()=>{state.q=search.value;clearTimeout(timer);timer=setTimeout(()=>render(true),200);};
    platform.onchange=()=>{state.platform=platform.value;clearTimeout(timer);render(true);};
    more.onclick=()=>failed?load():render();scroll.onscroll=()=>{if(!more.hidden&&!failed&&scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<160)render();};
    dialog.showModal();search.focus();ctl.ready=load();
    return ctl;
  }
  root.GBoxGameModelLibrary={open,gamesFromModels};
})(typeof window==='undefined'?globalThis:window);
