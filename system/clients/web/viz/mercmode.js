(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.GBoxMercMode=api;})(globalThis,function(){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(data){
    return `<div class="gbox-mercmode"><h3>MercMode</h3><p>Finish each round before switching games. Random characters and stages use each title’s verified controls. Your gameplay modifiers stay selected.</p>`+
      (data.hosts||[]).map(host=>`<fieldset data-host="${escape(host.name)}" data-worker="${escape(host.id)}"><legend>${escape(host.name)} · ${host.online?'online':'offline'}</legend>
        <label><input type="checkbox" data-enabled ${host.settings?.enabled?'checked':''}> MercMode on this PC</label><p><small>Turning this off keeps the current game and autobot playing Mercenaries; only cross-title rotation stops.</small></p>
        <label style="display:block"><input type="checkbox" data-presentation ${host.settings?.presentation_priority?'checked':''}> Continuous presentation: start despite busy CPU/GPU</label>
        ${host.scheduler_owner==='local'?`<p><small>This PC runs its own scheduler, including while disconnected. ${host.settings_source==='unobserved_local_scheduler'?'Local settings have not yet been observed. ':''}${host.command?.job?`Requested setting: ${escape(host.desired_settings?.enabled?'on':'off')} · ${escape(host.command.state||'queued')}${host.command.error?` · ${escape(host.command.error)}`:''}.`:''}</small></p>`:''}
        <div>${(host.titles||[]).map(title=>`<label style="display:block"><input type="checkbox" data-title="${escape(title.title)}" ${(host.settings?.titles||[]).includes(title.title)?'checked':''}> ${escape(title.name)}${title.playable?'':' · unavailable'}</label>${!title.playable?`<p><small>${escape(title.reason)}</small></p>`:''}`).join('')}</div>
        <label>Rounds before switching <input type="number" data-rounds min="1" max="20" value="${Number(host.settings?.rounds_per_title)||1}" style="width:4em"></label>
        <p><button type="button" data-save>Save this PC</button> <button type="button" data-prepare ${host.online?'':'disabled'}>Check cached assets</button>
        ${host.current_run?.mercmode?`<button type="button" data-stay="${escape(host.current_run.session_id)}">Stay in this game (autobot)</button>`:''}
        ${host.adoptable_solo_session&&!host.current_run?`<button type="button" data-adopt="${escape(host.adoptable_solo_session)}" ${host.settings?.enabled?'':'disabled'}>Use current solo bot</button>`:''}</p>
        ${host.current_run?.mercmode?`<p><b>${escape(host.current_run.phase)}: ${escape(host.current_run.title)}</b> · ${Number(host.current_run.mercmode_rounds)||0} verified rounds. ${host.settings?.enabled?'Next title follows the native round end.':'Autobot stays in this game; title rotation is off.'}</p>`:''}
        <small>RE5 retains installed data and shader caches. RPCS3 still boots through its menus; instant saved-state loading is unavailable.</small>
        ${host.history?.last_round?`<p>Last verified round: ${escape(host.history.last_round.map_id)} · ${escape(host.history.last_round.character||'character not decoded')} · ${escape(host.history.last_round.witness?.screen)}</p>`:''}
        ${host.preparation?.checked_at?`<p>Cached assets checked ${escape(new Date(host.preparation.checked_at*1000).toLocaleString())}. ${host.preparation.rpcs3?.re5_installed_data_present?'RE5 installed data found.':'RE5 installed data not found in this runtime.'}</p>`:''}
      </fieldset>`).join('')+
      (data.experience_coverage?.length?`<details><summary>Mercenaries coverage targets</summary><p>Each edition needs its own verified game driver. Availability on this PC is listed above.</p>${data.experience_coverage.map(row=>`<p><b>${escape(row.name)}</b> · ${row.state==='verified_adapter_available'?'adapter available; host checks apply':'native driver required'}<br><small>${escape(row.reason)}</small></p>`).join('')}</details>`:'')+
      `<p data-status role="status"></p></div>`;
  }
  function mount(options){
    const target=options.root,api=options.api;
    if(!target||typeof api!=='function')throw Error('MercMode needs a root element and authenticated API');
    let disposed=false,timer=null;
    async function refresh(){
      const data=await api('/api/mercmode');
      if(!disposed)target.innerHTML=render(data);
      return data;
    }
    async function click(event){
      const button=event.target.closest?.('button'),host=button?.closest('[data-host]');
      if(!button||!host)return;
      button.disabled=true;
      try{
        if(button.hasAttribute('data-save')){
          const titles=[...host.querySelectorAll('[data-title]:checked')].map(x=>x.dataset.title);
          await api('/api/mercmode',{host:host.dataset.host,enabled:host.querySelector('[data-enabled]').checked,
            presentation_priority:host.querySelector('[data-presentation]').checked,
            titles,rounds_per_title:Number(host.querySelector('[data-rounds]').value)});
          await refresh();
        }else if(button.hasAttribute('data-stay')){
          await stay(api,button.dataset.stay);await refresh();
        }else if(button.hasAttribute('data-adopt')){
          await api('/api/mercmode/adopt',{host:host.dataset.host,session_id:button.dataset.adopt});
          await refresh();
        }else if(button.hasAttribute('data-prepare')){
          await api('/api/mercmode/prepare',{worker_id:host.dataset.worker});
          const status=target.querySelector('[data-status]');if(status)status.textContent='Checking existing cached assets on '+host.dataset.host+'. No game is launched.';
          timer=setTimeout(()=>refresh().catch(showError),3000);
        }
      }catch(error){showError(error);}finally{if(button.isConnected)button.disabled=false;}
    }
    function showError(error){const status=target.querySelector('[data-status]');if(status)status.textContent=error.message||String(error);}
    target.addEventListener('click',click);
    const ready=refresh().catch(error=>{if(!disposed)target.textContent='MercMode: '+error.message;throw error;});
    return {ready,refresh,dispose(){disposed=true;clearTimeout(timer);target.removeEventListener('click',click);}};
  }
  async function stay(api,sid){
    if(!sid)throw Error('Select the current MercMode game first.');
    const data=await api('/api/mercmode');
    const host=(data.hosts||[]).find(h=>h.current_run?.session_id===sid&&h.current_run?.mercmode);
    if(!host)throw Error('This displayed session is no longer the current MercMode game.');
    await api('/api/mercmode',{host:host.name,enabled:false});
    return host.name;
  }
  return {render,mount,stay};
});
