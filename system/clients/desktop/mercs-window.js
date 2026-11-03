(function(root){
  'use strict';
  const SID=/^[A-Za-z0-9_-]{1,96}$/;
  const current=root.GBoxMercsCurrent?.current || (typeof require==='function' ? require('../web/viz/mercs-current.js').current : ()=>null);
  function rotation(from,to){
    const r=from?.mercmode_rotation;
    return r?.v===1&&r.source==='native_terminal_reader'&&/^[a-f0-9]{32}$/.test(r.round_id||'')
      &&typeof r.worker_id==='string'&&r.worker_id.length>0&&typeof from?.session_id==='string'&&typeof to?.session_id==='string'
      &&typeof (r.source_worker_id??r.worker_id)==='string'&&(r.source_worker_id??r.worker_id).length>0
      &&from.session_id.startsWith((r.source_worker_id??r.worker_id)+'-')&&to.session_id.startsWith(r.worker_id+'-')
      &&r.from_game===from.game_id&&r.to_game===to.game_id&&r.successor_session_id===to.session_id;
  }
  async function replacement(sid,choices,read,current=()=>true,expectedGame=null){
    const valid=value=>typeof value==='string'&&SID.test(value),seen=new Set();
    if(!valid(sid)||!current())return null;
    const history=await read('/api/sessions?include_ended=true&limit=60');
    if(!current()||!Array.isArray(history))return null;
    const byId=new Map(history.slice(0,60).filter(row=>row&&valid(row.session_id)).map(row=>[row.session_id,row]));
    let game=expectedGame;
    for(let hop=0;hop<8;hop++){
      if(!current()||seen.has(sid))return null;seen.add(sid);
      const row=byId.get(sid);
      if(!row||row.session_id!==sid||typeof row.state!=='string'||row.state==='running'
          ||typeof row.game_id!=='string'||!row.game_id||row.game_id.length>256)return null;
      if(game===null)game=row.game_id;
      if(row.game_id!==game||!valid(row.replaced_by)||seen.has(row.replaced_by))return null;
      const live=choices.find(item=>item.session_id===row.replaced_by&&item.state==='running'&&!item.stopping);
      if(live)return live.game_id===game||rotation(row,live)?live:null;
      const next=byId.get(row.replaced_by);
      if(next&&next.game_id!==game){if(!rotation(row,next))return null;game=next.game_id;}
      sid=row.replaced_by;
    }
    return null;
  }
  // PSO (Dolphin) sessions get the RAM-derived PSO co-op map; every other hooked title keeps the
  // tactical map. The renderer is chosen per session by title - via the GBoxLiveMaps provider registry
  // when loaded (extensible: new titles register their own renderer), else a local PSO title check.
  const isPso=row=>{const t=String((row&&(row.title||row.game_id))||'');return /phantasy star online/i.test(t)||/^GP[OS]/i.test(String((row&&row.game_id)||''))||/\bpso\b/i.test(t);};
  function mount(doc,bridge,{reviewer=root.GBoxMercsReviewer,tactical=root.GBoxTacticalMap,pso=root.GBoxPsoMap,registry=root.GBoxLiveMaps,setTimer=root.setInterval,clearTimer=root.clearInterval}={}){
    const $=id=>doc.getElementById(id);let state=null,dead=false,map=null,review=null,busy=false,revision=0,anchor=null;
    const titles=new Map();let mapSid=null,mapKind=null;                 // the session row titles + the mounted renderer
    const api=(path,body,method)=>bridge.api(path,body,method);
    const message=value=>{$('status').textContent=value||'';};
    const renderers={mercs:tactical,pso};
    function sessionRow(sid){return sid?{session_id:sid,title:titles.get(sid)||''}:null;}
    function kindFor(row){                                               // -> 'pso' | 'mercs' (a renderer we have)
      let id=null;try{id=registry&&typeof registry.classify==='function'?registry.classify(row):null;}catch(e){id=null;}
      if(!id)id=(pso&&isPso(row))?'pso':'mercs';
      return renderers[id]?id:'mercs';
    }
    function mapFor(sid){
      const kind=sid?kindFor(sessionRow(sid)):null;
      if(sid===mapSid&&kind===mapKind&&map)return;                       // already showing the right map for this session
      map?.stop();map=null;tactical?.detach?.();pso?.detach?.();$('map').replaceChildren();
      mapSid=sid;mapKind=kind;
      const rend=kind?renderers[kind]:null;
      $('map-note').hidden=false;
      $('map-note').textContent=!sid?'Choose a session to watch its measured map. Gameplay continues in its own window.'
        :kind==='pso'?'Live PSO map - both players, motion trails, the MOVING/STUCK banner and the run plan. Double-click an open spot to send P1; click a gate to open it; Resume autonomous when idle.'
        :'Hover to hold the map; wheel to zoom; drag to pan. Click a bonus or recovery item to request collection.';
      if(!sid||!rend)return;
      $('map').innerHTML=rend.html(sid);map=rend.mount(doc,{sid,api});
    }
    function mode(value){if(!state)return;state.mode=value==='map'?'map':'reviewer';const live=state.mode==='map';
      $('live-view').hidden=!live;$('review-view').hidden=live;
      $('live-tab').setAttribute('aria-pressed',String(live));$('review-tab').setAttribute('aria-pressed',String(!live));
      if(live){if(!map&&state.sid)mapFor(state.sid);}
      else if(!review&&reviewer)review=reviewer.mount($('reviewer'),{api,visible:()=>!dead&&state.mode==='reviewer'});
    }
    async function sessions(){if(dead||busy||!state)return;busy=true;const token=revision;
      try{const rows=await api('/api/sessions?include_ended=false');if(dead||token!==revision)return;
        let selected=state.sid;const choices=(Array.isArray(rows)?rows:[]).filter(s=>s&&s.state==='running');
        for(const row of choices)titles.set(row.session_id,row.title||row.game_id||'');
        const rotationState=await api('/api/mercmode').catch(()=>null);
        if(dead||token!==revision)return;
        const playing=current(selected,choices,rotationState?.hosts);
        if(playing&&playing.session_id!==selected){state.sid=selected=playing.session_id;anchor={sid:selected,game:playing.game_id};mapFor(selected);}
        const selectedRow=choices.find(s=>s.session_id===selected);
        if(selectedRow){anchor={sid:selected,game:selectedRow.game_id};mapFor(selected);}   // title now known: pick PSO vs tactical (no-op if already right)
        else if(selected){
          const next=await replacement(selected,choices,api,()=>!dead&&token===revision&&state.sid===selected,
                                       anchor?.sid===selected?anchor.game:null);
          if(dead||token!==revision||state.sid!==selected)return;
          if(next){state.sid=selected=next.session_id;anchor={sid:selected,game:next.game_id};revision++;mapFor(selected);}
        }
        $('sessions').replaceChildren();const option=(value,label)=>{const o=doc.createElement('option');o.value=value;o.textContent=label;$('sessions').append(o);};
        option('','Choose a live session');for(const row of choices)option(row.session_id,`${row.title||row.game_id} · ${row.detail?.worker_name||row.session_id.slice(0,8)}`);
        if(selected&&!choices.some(s=>s.session_id===selected))option(selected,'Saved session · waiting to reconnect');
        $('sessions').value=selected||'';message(choices.length?`${choices.length} live session${choices.length===1?'':'s'}`:'No live sessions. Recorded runs remain available.');
      }catch(error){if(token===revision)message(error.message||'This server is reconnecting.');}finally{busy=false;}
    }
    function adopt(value){if(dead)return;revision++;anchor=null;state={...value};$('authority').textContent=state.origin;
      $('top').checked=!!state.top;mapFor(state.sid);mode(state.mode);sessions();}
    $('live-tab').onclick=()=>mode('map');$('review-tab').onclick=()=>mode('reviewer');$('refresh').onclick=sessions;
    $('sessions').onchange=()=>{revision++;anchor=null;state.sid=$('sessions').value||null;mapFor(state.sid);};
    $('top').onchange=async()=>{try{$('top').checked=await bridge.alwaysOnTop($('top').checked);}catch(error){message(error.message);}};
    const unsubscribe=bridge.onScope(adopt);const ready=bridge.info().then(adopt).catch(error=>message(error.message));
    const timer=setTimer(()=>sessions(),5000);
    return {ready,sessions,adopt,dispose(){dead=true;revision++;clearTimer(timer);unsubscribe?.();map?.stop();tactical?.detach?.();pso?.detach?.();review?.dispose();}};
  }
  const api={mount,replacement,rotation};if(typeof module==='object'&&module.exports)module.exports=api;else{root.GBoxMercsWindow=api;const control=mount(root.document,root.mercsWindow);root.addEventListener('pagehide',()=>control.dispose(),{once:true});}
})(typeof window!=='undefined'?window:globalThis);
