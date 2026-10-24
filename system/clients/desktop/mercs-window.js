(function(root){
  'use strict';
  function mount(doc,bridge,{reviewer=root.GBoxMercsReviewer,tactical=root.GBoxTacticalMap,setTimer=root.setInterval,clearTimer=root.clearInterval}={}){
    const $=id=>doc.getElementById(id);let state=null,dead=false,map=null,review=null,busy=false,revision=0;
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
        const selected=state.sid,choices=(Array.isArray(rows)?rows:[]).filter(s=>s.state==='running');
        $('sessions').replaceChildren();const option=(value,label)=>{const o=doc.createElement('option');o.value=value;o.textContent=label;$('sessions').append(o);};
        option('','Choose a live session');for(const row of choices)option(row.session_id,`${row.title||row.game_id} · ${row.detail?.worker_name||row.session_id.slice(0,8)}`);
        if(selected&&!choices.some(s=>s.session_id===selected))option(selected,'Saved session · waiting to reconnect');
        $('sessions').value=selected||'';message(choices.length?`${choices.length} live session${choices.length===1?'':'s'}`:'No live sessions. Recorded runs remain available.');
      }catch(error){if(token===revision)message(error.message||'This server is reconnecting.');}finally{busy=false;}
    }
    function adopt(value){if(dead)return;revision++;state={...value};$('authority').textContent=state.origin;
      $('top').checked=!!state.top;mapFor(state.sid);mode(state.mode);sessions();}
    $('live-tab').onclick=()=>mode('map');$('review-tab').onclick=()=>mode('reviewer');$('refresh').onclick=sessions;
    $('sessions').onchange=()=>{state.sid=$('sessions').value||null;mapFor(state.sid);};
    $('top').onchange=async()=>{try{$('top').checked=await bridge.alwaysOnTop($('top').checked);}catch(error){message(error.message);}};
    const unsubscribe=bridge.onScope(adopt);const ready=bridge.info().then(adopt).catch(error=>message(error.message));
    const timer=setTimer(()=>sessions(),5000);
    return {ready,sessions,adopt,dispose(){dead=true;revision++;clearTimer(timer);unsubscribe?.();map?.stop();tactical?.detach?.();review?.dispose();}};
  }
  const api={mount};if(typeof module==='object'&&module.exports)module.exports=api;else{root.GBoxMercsWindow=api;const control=mount(root.document,root.mercsWindow);root.addEventListener('pagehide',()=>control.dispose(),{once:true});}
})(typeof window!=='undefined'?window:globalThis);
