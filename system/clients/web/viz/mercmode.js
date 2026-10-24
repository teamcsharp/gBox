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
  // --- the picture-in-picture menu (operator 2026-10-24): one toggle between staying in this game and MercMode
  // rotating across titles, and an arrow that opens the titles it rotates through ---
  function hostFor(data,sid,worker){
    const hosts=data?.hosts||[];
    return hosts.find(h=>sid&&h.current_run?.session_id===sid)
      ||hosts.find(h=>sid&&h.current_run?.mercmode_predecessor?.session_id===sid)
      ||hosts.find(h=>sid&&h.id&&String(sid).startsWith(h.id+'-'))
      ||hosts.find(h=>worker&&h.name===worker)||null;
  }
  function menuHTML(host,open=false){
    if(!host)return `<div class="pip-mercmode"><small>MercMode: no gBox PC owns this game.</small></div>`;
    const on=!!host.settings?.enabled,chosen=host.settings?.titles||[];
    const label=on?'🔁 MercMode: rotating titles · click to stay in this game':'▶ MercMode: play across titles · click to turn on';
    const titles=(host.titles||[]).map(t=>`<label${t.playable?'':' class="pip-mercmode-off"'}><input type="checkbox" data-mm-title="${escape(t.title)}" ${chosen.includes(t.title)?'checked':''} ${t.playable?'':'disabled'}> ${escape(t.name)}${t.playable?'':` <small>· unavailable: ${escape(t.reason||'')}</small>`}</label>`).join('');
    return `<div class="pip-mercmode" data-mm-host="${escape(host.name)}"><div class="pip-mercmode-row"><button type="button" data-mm-toggle aria-pressed="${on}">${label}</button><button type="button" data-mm-arrow aria-expanded="${open}" aria-label="Choose the titles MercMode rotates through">${open?'▾':'▸'}</button></div>`+
      `<div class="pip-mercmode-titles"${open?'':' hidden'}>${titles}<label>Rounds before switching <input type="number" data-mm-rounds min="1" max="20" value="${Number(host.settings?.rounds_per_title)||1}"></label>`+
      `${host.current_run?.mercmode?`<small>${escape(host.current_run.phase)}: ${escape(host.current_run.title)} · ${Number(host.current_run.mercmode_rounds)||0} verified rounds</small>`:''}</div></div>`;
  }
  async function menuAction(api,host,action,value){
    if(!host?.name)throw Error('No gBox PC owns this game.');
    if(action==='toggle'){
      const enabled=!host.settings?.enabled;
      await api('/api/mercmode',{host:host.name,enabled});
      return enabled?'MercMode on: the next native round end switches titles.':'MercMode rotation off. Autobot continues in this game.';
    }
    if(action==='title'){
      const chosen=new Set(host.settings?.titles||[]);
      if(value.checked)chosen.add(value.title);else chosen.delete(value.title);
      if(!chosen.size)throw Error('Keep at least one title in the rotation.');
      await api('/api/mercmode',{host:host.name,titles:[...chosen]});
      return `Rotation: ${[...chosen].join(', ')}`;
    }
    if(action==='rounds'){
      const rounds=Math.max(1,Math.min(20,Number(value)||1));
      await api('/api/mercmode',{host:host.name,rounds_per_title:rounds});
      return `${rounds} round${rounds===1?'':'s'} before switching`;
    }
    throw Error('Unknown MercMode action');
  }
  // --- between titles: what the PiP shows while the next game boots in the background ---
  function transition(host,sid,now=Date.now()/1000){
    const run=host?.current_run;
    if(!host?.settings?.enabled||!run?.mercmode)return {show:false};
    const since=t=>Math.max(0,now-(Number(t)||now));
    let progress=null;
    if(run.phase==='launching')progress=8+Math.min(52,52*since(run.started)/90);
    else if(run.phase==='starting')progress=65+Math.min(20,20*since(run.up||run.started)/30);
    else if(run.phase==='playing'&&run.session_id&&run.session_id!==sid)progress=92;
    if(progress===null)return {show:false};
    return {show:true,phase:run.phase,title:run.title||'',progress:Math.round(progress),
      text:`Loading ${run.title||'the next title'}…`,sub:'MercMode is switching titles; the next game boots in the background.'};
  }
  return {render,mount,stay,hostFor,menuHTML,menuAction,transition};
});
