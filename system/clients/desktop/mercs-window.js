(function(root){
  'use strict';
  const SID=/^[A-Za-z0-9_-]{1,96}$/;
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
      if(live)return live.game_id===game?live:null;
      sid=row.replaced_by;
    }
    return null;
  }
  function mount(doc,bridge,{reviewer=root.GBoxMercsReviewer,tactical=root.GBoxTacticalMap,setTimer=root.setInterval,clearTimer=root.clearInterval}={}){
    const $=id=>doc.getElementById(id);let state=null,dead=false,map=null,review=null,busy=false,revision=0,anchor=null;
    const api=(path,body,method)=>bridge.api(path,body,method);
    const message=value=>{$('status').textContent=value||'';};
    function mapFor(sid){map?.stop();map=null;tactical?.detach?.();$('map').replaceChildren();
      $('map-note').hidden=false;$('map-note').textContent=sid?'Waiting for measured game state. No controller input is sent.':'Choose a session to watch its measured map. Gameplay continues in its own window.';
      if(!sid||!tactical)return;
      $('map').innerHTML=tactical.html(sid);map=tactical.mount(doc,{sid,api});
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
        const selectedRow=choices.find(s=>s.session_id===selected);
        if(selectedRow)anchor={sid:selected,game:selectedRow.game_id};
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
    return {ready,sessions,adopt,dispose(){dead=true;revision++;clearTimer(timer);unsubscribe?.();map?.stop();tactical?.detach?.();review?.dispose();}};
  }
  const api={mount,replacement};if(typeof module==='object'&&module.exports)module.exports=api;else{root.GBoxMercsWindow=api;const control=mount(root.document,root.mercsWindow);root.addEventListener('pagehide',()=>control.dispose(),{once:true});}
})(typeof window!=='undefined'?window:globalThis);
