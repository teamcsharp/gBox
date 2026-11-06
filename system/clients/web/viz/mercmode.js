(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.GBoxMercMode=api;})(globalThis,function(){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // bot+bot split screen on RE5 / RE6 Switch (operator 2026-10-27: "the ratio of co-op matches to single player matches
  // six to one"): each turn draws co-op or solo by this co-op : solo ratio (gbox/mercmode.py draw_coop). RE6's co-op is
  // No Mercy split screen; RE5's is Mercenaries United's split screen, RE5's No Mercy being single-player only
  const COOP_RATIOS=['off','1:1','2:1','3:1','4:1','5:1','6:1','8:1','10:1','only'];
  const SWITCH_GAMES={'52d15709be0fda1a':'RE5','115f9cdbba115432':'RE6'};
  const coopLabel=r=>r==='off'?'Off (solo turns only)':r==='only'?'Co-op only':`${r} co-op to solo`;
  const coopSelect=(attr,value)=>`<select ${attr} aria-label="Bot+bot split-screen turns">${COOP_RATIOS.map(r=>`<option value="${r}" ${r===(COOP_RATIOS.includes(value)?value:'off')?'selected':''}>${coopLabel(r)}</option>`).join('')}</select>`;
  const COOP_NOTE='RE6 plays No Mercy in split screen; RE5 plays Mercenaries United in split screen (its No Mercy is single-player only).';
  // --- dispatch (operator 2026-10-27: "i want to be able to dispatch autoplay titles happening on different instance of
  // gbox from gbox. So the first request is to play mercenaries 3d on that computer pip mode"): a title, the PC it runs on,
  // Start / Stop, and "Show in PiP on that PC" (that PC's app shows its own run, gbox/mercmode.py DISPATCH) ---
  const OPERATOR_PCS=['jaybuiltfinale'];       // the operator's own PC: listed, never chosen for them (gbox/mercmode.py)
  const isOperatorPc=h=>!!h?.operator_pc||OPERATOR_PCS.includes(String(h?.name||'').toLowerCase());
  const clip=(text,n)=>{text=String(text||'');return text.length>n?text.slice(0,n-1)+'…':text;};
  // every title some PC lists, the ones an online PC can play first
  function titleChoices(data){
    const seen=new Map();
    for(const h of data?.hosts||[])for(const t of h.titles||[]){
      const row=seen.get(t.title)||{title:t.title,name:t.name||t.title,playable:false};
      row.playable=row.playable||!!(t.playable&&h.online);seen.set(t.title,row);
    }
    return [...seen.values()].sort((a,b)=>Number(b.playable)-Number(a.playable));
  }
  // the PCs for one title: [{name, ok, reason, operator}] - ok = online and that PC can play it (its copy, its driver)
  function runOn(data,title){
    return (data?.hosts||[]).map(h=>{
      const t=(h.titles||[]).find(x=>x.title===title);
      const reason=!h.online?'offline':!t?'not listed on this PC':t.playable?'':(t.reason||'unavailable');
      return {name:h.name,ok:!reason,reason,operator:isOperatorPc(h)};
    });
  }
  // the PC preselected: the one chosen before if it can still play it, else the first able PC that is not the operator's
  function defaultHost(choices,chosen){
    return (choices.find(c=>c.ok&&c.name===chosen)||choices.find(c=>c.ok&&!c.operator)||{}).name||'';
  }
  function dispatchHTML(data,state={}){
    const titles=titleChoices(data);
    if(!titles.length)return '';
    const title=(titles.find(t=>t.title===state.title)||titles.find(t=>t.playable)||titles[0]).title;
    const name=(titles.find(t=>t.title===title)||{}).name||title;
    const choices=runOn(data,title),host=defaultHost(choices,state.host);
    const row=(data.hosts||[]).find(h=>h.name===host);
    const rounds=Math.max(1,Math.min(20,Math.round(Number(state.rounds??row?.settings?.rounds_per_title))||1));
    const why=choices.filter(c=>!c.ok).map(c=>`${escape(c.name)}: ${escape(c.reason)}`).join(' · ');
    return `<fieldset class="mm-dispatch" data-dispatch><legend>Run autoplay on a PC</legend>`+
      `<label>Title <select data-dispatch-title aria-label="Title">${titles.map(t=>`<option value="${escape(t.title)}"${t.title===title?' selected':''}>${escape(t.name)}${t.playable?'':' · unavailable'}</option>`).join('')}</select></label> `+
      `<label>Run on <select data-dispatch-host aria-label="PC to run it on">${host?'':'<option value="" selected>No PC can play it now</option>'}${choices.map(c=>`<option value="${escape(c.name)}"${c.name===host?' selected':''}${c.ok?'':' disabled'}>${escape(c.name)}${c.operator?' (your PC)':''}${c.ok?'':` · ${escape(clip(c.reason,70))}`}</option>`).join('')}</select></label> `+
      `<label>Rounds per title <input type="number" data-dispatch-rounds min="1" max="20" value="${rounds}" style="width:4em"></label> `+
      `<label><input type="checkbox" data-dispatch-pip ${state.pip===false?'':'checked'}> Show in PiP on that PC</label>`+
      `<p><button type="button" data-dispatch-start ${host?'':'disabled'}>Start</button> <button type="button" data-dispatch-stop ${row&&(row.current_run||row.settings?.enabled)?'':'disabled'}>Stop</button></p>`+
      (host?'':`<p><small>No online PC can play ${escape(name)} now. ${why}</small></p>`)+`</fieldset>`;
  }
  function readDispatch(root){
    const q=sel=>root?.querySelector?.(sel);
    return {title:q('[data-dispatch-title]')?.value||'',host:q('[data-dispatch-host]')?.value||'',
      rounds:Number(q('[data-dispatch-rounds]')?.value)||1,pip:q('[data-dispatch-pip]')?.checked!==false};
  }
  // Start: that title alone on that PC (switching now when it plays another title there); Stop: MercMode off there and its
  // MercMode game closed. The server checks the PC again (its copy of the game, its driver, the operator's own PC).
  async function dispatchAction(api,data,{action,host,title,rounds,pip}){
    const row=(data?.hosts||[]).find(h=>h.name===host);
    if(!row)throw Error('Choose the PC to run it on.');
    if(action==='stop'){await api('/api/mercmode',{host,command:'stop'});return `MercMode stopped on ${host}.`;}
    if(action!=='start')throw Error('Unknown dispatch action');
    const t=(row.titles||[]).find(x=>x.title===title);
    if(!row.online)throw Error(`${host} is offline.`);
    if(!t)throw Error(`${host} does not list that title.`);
    if(!t.playable)throw Error(`${t.name} is not playable on ${host}: ${t.reason||'unavailable'}`);
    const playing=row.current_run?.mercmode?.title;
    const command=playing&&playing!==title?'switch':'start';
    const n=Math.max(1,Math.min(20,Math.round(Number(rounds))||1));
    await api('/api/mercmode',{host,command,title,titles:[title],rounds_per_title:n,pip:!!pip});
    return `${command==='switch'?'Switching to':'Starting'} ${t.name} on ${host}${pip?'; that PC shows it in its PiP':''}.`;
  }
  // one PC's current run, the app's dispatch there and what its scheduler waits for, with Watch (my PiP) and Stop
  function runHTML(host,watch){
    const run=host.current_run,d=host.dispatch;
    const live=run?.session_id&&['playing','starting'].includes(run.phase);
    const parts=[];
    if(run)parts.push(`<b>${escape(run.phase)}: ${escape(run.title||run.game_id||'a game')}</b>${run.mercmode?` · ${Number(run.mercmode_rounds)||0} verified rounds. ${host.settings?.enabled?'Next title follows the native round end.':'Autobot stays in this game; title rotation is off.'}`:''}`);
    else parts.push('<b>Nothing playing</b>');
    if(d?.command)parts.push(`<small>Dispatched: ${escape(d.command)}${d.title?' '+escape(TITLE_NAMES[d.title]||d.title):''}${d.pip?' · PiP on this PC':''}${d.applied===false?' · on its way to this PC':''}${d.lapsed?` · ${escape(d.lapsed)}`:''}</small>`);
    if(host.scheduler_note&&!(run&&run.phase==='playing'))parts.push(`<small>Scheduler: ${escape(host.scheduler_note)}</small>`);
    return `<p class="mm-run" data-mm-run>${parts.join(' ')} ${watch&&live?`<button type="button" data-watch="${escape(run.session_id)}">Watch</button>`:''}`+
      `${run||host.settings?.enabled?` <button type="button" data-host-stop>Stop</button>`:''}</p>`;
  }
  function render(data,options={}){
    return `<div class="gbox-mercmode"><h3>MercMode</h3><p>Finish each round before switching games. Random characters and stages use each title’s verified controls. Your gameplay modifiers stay selected.</p>`+
      dispatchHTML(data,options.dispatch||{})+
      (data.hosts||[]).map(host=>`<fieldset data-host="${escape(host.name)}" data-worker="${escape(host.id)}"><legend>${escape(host.name)} · ${host.online?'online':'offline'}</legend>
        ${runHTML(host,!!options.watch)}
        <label><input type="checkbox" data-enabled ${host.settings?.enabled?'checked':''}> MercMode on this PC</label><p><small>Turning this off keeps the current game and autobot playing Mercenaries; only cross-title rotation stops.</small></p>
        <label style="display:block"><input type="checkbox" data-presentation ${host.settings?.presentation_priority?'checked':''}> Continuous presentation: start despite busy CPU/GPU</label>
        ${host.scheduler_owner==='local'?`<p><small>This PC runs its own scheduler, including while disconnected. ${host.settings_source==='unobserved_local_scheduler'?'Local settings have not yet been observed. ':''}${host.command?.job?`Requested setting: ${escape(host.desired_settings?.enabled?'on':'off')} · ${escape(host.command.state||'queued')}${host.command.error?` · ${escape(host.command.error)}`:''}.`:''}</small></p>`:''}
        <div>${(host.titles||[]).map(title=>`<label style="display:block"><input type="checkbox" data-title="${escape(title.title)}" ${(host.settings?.titles||[]).includes(title.title)?'checked':''}> ${escape(title.name)}${title.playable?'':' · unavailable'}</label>${!title.playable?`<p><small>${escape(title.reason)}</small></p>`:''}`).join('')}</div>
        <label>Rounds before switching <input type="number" data-rounds min="1" max="20" value="${Number(host.settings?.rounds_per_title)||1}" style="width:4em"></label>
        <label style="display:block"><input type="checkbox" data-stalemate ${host.settings?.stalemate_cut===false?'':'checked'}> Stalemate: no enemy for 15 s with time left, the bot cuts the clock to <input type="number" data-stalemate-s min="1" max="60" value="${stalemateSeconds(host.settings)}" style="width:4em"> s</label>
        <label style="display:block">Bot+bot split-screen turns on RE5 / RE6 Switch ${coopSelect('data-coop',host.settings?.coop_ratio)}</label><p><small>${COOP_NOTE}</small></p>
        ${queueHTML(host,data.catalog)}
        <p><button type="button" data-save>Save this PC</button> <button type="button" data-prepare ${host.online?'':'disabled'}>Check cached assets</button>
        ${host.current_run?.mercmode?`<button type="button" data-stay="${escape(host.current_run.session_id)}">Stay in this game (autobot)</button>`:''}
        ${host.adoptable_solo_session&&!host.current_run?`<button type="button" data-adopt="${escape(host.adoptable_solo_session)}" ${host.settings?.enabled?'':'disabled'}>Use current solo bot</button>`:''}</p>
        <small>RE5 retains installed data and shader caches. RPCS3 still boots through its menus; instant saved-state loading is unavailable.</small>
        ${host.history?.last_round?`<p>Last verified round: ${escape(host.history.last_round.map_id)} · ${escape(host.history.last_round.character||'character not decoded')} · ${escape(host.history.last_round.witness?.screen)}</p>`:''}
        ${host.preparation?.checked_at?`<p>Cached assets checked ${escape(new Date(host.preparation.checked_at*1000).toLocaleString())}. ${host.preparation.rpcs3?.re5_installed_data_present?'RE5 installed data found.':'RE5 installed data not found in this runtime.'}</p>`:''}
      </fieldset>`).join('')+
      (data.experience_coverage?.length?`<details><summary>Mercenaries coverage targets</summary><p>Each edition needs its own verified game driver. Availability on this PC is listed above.</p>${data.experience_coverage.map(row=>`<p><b>${escape(row.name)}</b> · ${row.state==='verified_adapter_available'?'adapter available; host checks apply':'native driver required'}<br><small>${escape(row.reason)}</small></p>`).join('')}</details>`:'')+
      `<p data-status role="status"></p></div>`;
  }
  function mount(options){
    const target=options.root,api=options.api,watch=typeof options.watch==='function'?options.watch:null;
    if(!target||typeof api!=='function')throw Error('MercMode needs a root element and authenticated API');
    let disposed=false,timer=null,last=null,chosen={};
    async function refresh(){
      const data=await api('/api/mercmode');
      if(disposed)return data;
      last=data;
      target.innerHTML=render(data,{watch,dispatch:chosen});
      for(const field of target.querySelectorAll?.('[data-host]')||[]){
        const host=(data.hosts||[]).find(h=>h.name===field.dataset.host),q=field.querySelector('[data-mm-queue]');
        if(host&&q)wireQueue(q,{api,host,catalog:data.catalog,done:message=>{showStatus(message);refresh().catch(showError);},fail:showError});
      }
      return data;
    }
    // a title or PC chosen in "Run on": the PC list follows the title (only PCs that can play it are selectable)
    function change(event){
      const form=event.target?.closest?.('[data-dispatch]');
      if(!form||!last)return;
      chosen={...chosen,...readDispatch(form)};
      if(event.target.hasAttribute?.('data-dispatch-title'))form.outerHTML=dispatchHTML(last,chosen);
    }
    async function click(event){
      const button=event.target.closest?.('button');
      const action=button?.hasAttribute?.('data-dispatch-start')?'start':button?.hasAttribute?.('data-dispatch-stop')?'stop':null;
      if(action){                              // "Run on": Start / Stop that title on that PC
        const form=button.closest('[data-dispatch]');
        button.disabled=true;
        try{chosen={...chosen,...readDispatch(form)};showStatus(await dispatchAction(api,last,{action,...chosen}));await refresh();}
        catch(error){showError(error);}finally{if(button.isConnected)button.disabled=false;}
        return;
      }
      const host=button?.closest('[data-host]');
      if(!button||!host||(button.getAttributeNames?.()||[]).some(n=>n.startsWith('data-mm-')))return;    // queue buttons have their own handlers
      if(button.hasAttribute('data-watch')){   // that PC's run in my PiP
        try{await watch?.(button.dataset.watch,host.dataset.host);showStatus(`Watching ${host.dataset.host}'s game in your PiP.`);}
        catch(error){showError(error);}
        return;
      }
      button.disabled=true;
      try{
        if(button.hasAttribute('data-host-stop')){
          showStatus(await dispatchAction(api,last,{action:'stop',host:host.dataset.host}));await refresh();
        }else if(button.hasAttribute('data-save')){
          const titles=[...host.querySelectorAll('[data-title]:checked')].map(x=>x.dataset.title);
          const stalemate=host.querySelector('[data-stalemate]'),stalemateS=host.querySelector('[data-stalemate-s]');
          await api('/api/mercmode',{host:host.dataset.host,enabled:host.querySelector('[data-enabled]').checked,
            presentation_priority:host.querySelector('[data-presentation]').checked,
            titles,rounds_per_title:Number(host.querySelector('[data-rounds]').value),
            ...(stalemate&&stalemateS?{stalemate_cut:!!stalemate.checked,stalemate_cut_s:stalemateSeconds({stalemate_cut_s:stalemateS.value})}:{}),
            ...(COOP_RATIOS.includes(host.querySelector('[data-coop]')?.value)?{coop_ratio:host.querySelector('[data-coop]').value}:{})});
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
    function showError(error){showStatus(error.message||String(error));}
    function showStatus(text){const status=target.querySelector('[data-status]');if(status)status.textContent=text;}
    target.addEventListener('click',click);
    target.addEventListener('change',change);
    const ready=refresh().catch(error=>{if(!disposed)target.textContent='MercMode: '+error.message;throw error;});
    return {ready,refresh,dispose(){disposed=true;clearTimeout(timer);target.removeEventListener('click',click);target.removeEventListener('change',change);}};
  }
  async function stay(api,sid){
    if(!sid)throw Error('Select the current MercMode game first.');
    const data=await api('/api/mercmode');
    const host=(data.hosts||[]).find(h=>h.current_run?.session_id===sid&&h.current_run?.mercmode);
    if(!host)throw Error('This displayed session is no longer the current MercMode game.');
    await api('/api/mercmode',{host:host.name,enabled:false});
    return host.name;
  }
  // the bots' stalemate rule (gbox.mercs.stalemate; operator 2026-10-26): no enemy for 15 s with time on the clock ->
  // the clock is cut to stalemate_cut_s (1..60, default 5) once per round. Saved per host; a launch carries it to the bot.
  const STALEMATE={min:1,max:60,default:5};
  function stalemateSeconds(settings){
    const n=Math.round(Number(settings?.stalemate_cut_s));
    return Number.isFinite(n)&&n>=STALEMATE.min&&n<=STALEMATE.max?n:STALEMATE.default;
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
  // --- the DJ queue: what plays next (title, mode, character, stage; blank = random) and the queue ahead ---
  const TITLE_NAMES={re4:'Resident Evil 4',re5:'Resident Evil 5',re6:'Resident Evil 6',re3:'Resident Evil 3',
    merc3d:'Resident Evil: The Mercenaries 3D'};
  function describe(entry,catalog){
    const known=catalog?.[entry.title],stage=entry.stage==null?'random stage':(known?.stages?.[entry.stage]||`stage ${entry.stage}`);
    return [TITLE_NAMES[entry.title]||entry.title,entry.mode||(known&&Object.keys(known.modes).length>1?'random mode':null),
      entry.character||'random character',stage].filter(Boolean).join(' · ');
  }
  function formOptions(catalog,title,mode){
    const known=catalog?.[title]||{modes:{},stages:[]},modes=Object.keys(known.modes);
    const roster=mode&&known.modes[mode]?known.modes[mode]:[...new Set(Object.values(known.modes).flat())];
    const opt=(value,label,selected)=>`<option value="${escape(value)}"${selected?' selected':''}>${escape(label)}</option>`;
    return {modes:opt('','Random mode')+modes.map(m=>opt(m,m==='reunion'?'Reunion':m==='mercenaries'?'The Mercenaries':m,m===mode)).join(''),
      characters:opt('','Random character')+roster.map(c=>opt(c,c)).join(''),
      stages:opt('','Random stage')+(known.stages||[]).map((n,i)=>opt(String(i),n)).join('')};
  }
  function queueHTML(host,catalog){
    const queue=host?.settings?.queue||[],playable=(host?.titles||[]).filter(t=>t.playable||catalog?.[t.title]);
    const now=host?.current_run?.mercmode?`${escape(host.current_run.title)}${host.now_playing?.character?` · ${escape(host.now_playing.character)}`:''}${host.now_playing?.stage?` · ${escape(host.now_playing.stage)}`:''}`:'';
    const first=playable[0]?.title||'re4',opts=formOptions(catalog,first,'');
    return `<div class="mm-queue" data-mm-queue><b>Now playing</b> <small>${now||'nothing yet'}</small>`+
      `<b>Up next</b>${queue.length?`<ol>${queue.map((e,i)=>`<li>${escape(describe(e,catalog))} <button type="button" data-mm-unqueue="${i}" aria-label="Remove from the queue">✕</button></li>`).join('')}</ol>`:'<small>Random rotation (queue a round to choose it).</small>'}`+
      `<div class="mm-queue-form"><select data-mm-q-title aria-label="Game">${playable.map(t=>`<option value="${escape(t.title)}">${escape(t.name)}</option>`).join('')}</select>`+
      `<select data-mm-q-mode aria-label="Mode">${opts.modes}</select><select data-mm-q-character aria-label="Character">${opts.characters}</select>`+
      `<select data-mm-q-stage aria-label="Stage">${opts.stages}</select>`+
      `<button type="button" data-mm-queue-next>Play next</button> <button type="button" data-mm-queue-add>Add to queue</button>`+
      `${queue.length?' <button type="button" data-mm-queue-clear>Clear queue</button>':''}</div></div>`;
  }
  function readForm(root){
    const v=sel=>root.querySelector(sel)?.value||'';
    const stage=v('[data-mm-q-stage]');
    return {title:v('[data-mm-q-title]'),mode:v('[data-mm-q-mode]')||null,character:v('[data-mm-q-character]')||null,
      stage:stage===''?null:Number(stage)};
  }
  function refreshForm(root,catalog){
    const title=root.querySelector('[data-mm-q-title]')?.value,mode=root.querySelector('[data-mm-q-mode]')?.value||'';
    const keep=root.querySelector('[data-mm-q-mode]')?.dataset.title===title;
    const opts=formOptions(catalog,title,keep?mode:'');
    const m=root.querySelector('[data-mm-q-mode]'),c=root.querySelector('[data-mm-q-character]'),st=root.querySelector('[data-mm-q-stage]');
    if(m&&!keep){m.innerHTML=opts.modes;m.dataset.title=title;}
    if(c){const was=c.value;c.innerHTML=opts.characters;if([...c.options].some(o=>o.value===was))c.value=was;}
    if(st&&!keep)st.innerHTML=opts.stages;
  }
  async function queueAction(api,host,action,value){
    if(!host?.name)throw Error('No gBox PC owns this game.');
    const queue=[...(host.settings?.queue||[])];
    if(action==='next')queue.unshift(value);
    else if(action==='add')queue.push(value);
    else if(action==='remove')queue.splice(Number(value),1);
    else if(action==='clear')queue.length=0;
    else throw Error('Unknown queue action');
    await api('/api/mercmode',{host:host.name,queue});
    return action==='clear'?'Queue cleared: random rotation.':action==='remove'?'Removed from the queue.':
      `${action==='next'?'Up next':'Queued'}: ${describe(value,null)}${host.settings?.enabled?'':' · turn MercMode on to play it'}`;
  }
  function wireQueue(root,{api,host,catalog,done,fail}){
    const run=async(action,value)=>{try{done(await queueAction(api,host,action,value));}catch(error){fail(error);}};
    root.querySelector('[data-mm-q-title]')?.addEventListener('change',()=>refreshForm(root,catalog));
    root.querySelector('[data-mm-q-mode]')?.addEventListener('change',()=>{
      const m=root.querySelector('[data-mm-q-mode]');m.dataset.title=root.querySelector('[data-mm-q-title]')?.value;refreshForm(root,catalog);});
    root.querySelector('[data-mm-queue-next]')?.addEventListener('click',e=>{e.stopPropagation();run('next',readForm(root));});
    root.querySelector('[data-mm-queue-add]')?.addEventListener('click',e=>{e.stopPropagation();run('add',readForm(root));});
    root.querySelector('[data-mm-queue-clear]')?.addEventListener('click',e=>{e.stopPropagation();run('clear');});
    root.querySelectorAll('[data-mm-unqueue]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();run('remove',b.dataset.mmUnqueue);}));
    const m=root.querySelector('[data-mm-q-mode]');if(m)m.dataset.title=root.querySelector('[data-mm-q-title]')?.value||'';
  }
  // Character / zombie slot swaps (RE5 Switch): the archives the panel's buttons move a model group between. The
  // model group is the archive's first `\model\` entry (gbox.mt_arc), so only the archives are named here.
  const SWAP = {
    // the whole RE5 cast, as its character select offers it across both pages: a round played on any of them can be
    // swapped, and any of them can donate a skin
    slots: {chris: 'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc',
            sheva: 'nativeNXx64/ImgNX/Archive/uPl01ShebaNormal.arc',
            jill: 'nativeNXx64/ImgNX/Archive/uPl02JillCos1.arc',
            wesker: 'nativeNXx64/ImgNX/Archive/uPl03WeskerCos1.arc',
            josh: 'nativeNXx64/ImgNX/Archive/uPl04Josh.arc',
            excella: 'nativeNXx64/ImgNX/Archive/uPl05ExcellaNormal.arc',
            barry: 'nativeNXx64/ImgNX/Archive/uPl06BarryNormal.arc',
            rebecca: 'nativeNXx64/ImgNX/Archive/uPl07RebeccaNormal.arc',
            // Enemies are not interchangeable with characters: a body map must share the slot's tag (dimensions and
            // format) or gbox.skin_swap refuses it. uEm20's em2000_01body does not match Chris, so it is refused; uEm6c
            // and uEm71 (body em6c00_00) carry a base map and mask of Chris's exact format, so those swap cleanly.
            zombie: 'nativeNXx64/ImgNX/Archive/uEm6c.arc',
            zombie2: 'nativeNXx64/ImgNX/Archive/uEm71.arc'},
    plain: {chris: 'nativeNXx64/ImgNX/Archive/uPl00ChrisPlain.arc',
            sheva: 'nativeNXx64/ImgNX/Archive/uPl01ShebaPlain.arc',
            jill: 'nativeNXx64/ImgNX/Archive/uPl02JillCos1.arc'},
    plain: {chris: 'nativeNXx64/ImgNX/Archive/uPl00ChrisPlain.arc',
            sheva: 'nativeNXx64/ImgNX/Archive/uPl01ShebaPlain.arc',
            jill: 'nativeNXx64/ImgNX/Archive/uPl02JillCos1.arc'},
    // the objects that appear while a round plays: the mine placed, the mine2/grenade thrown (their texture groups are
    // wp0600, wp0700 and om4e00), swapped with the same rule as a character's skin
    objects: {mine: 'nativeNXx64/ImgNX/Archive/uWp06.arc',
              mine2: 'nativeNXx64/ImgNX/Archive/uWp07.arc',
              grenade: 'nativeNXx64/ImgNX/Archive/uWp0a.arc'},
  };
  // A game id to the decrypt lab's title key (the swap API addresses a title by that key).
  const LAB_TITLES = {'52d15709be0fda1a': 're5_switch', '115f9cdbba115432': 're6_switch',
                      '270a15eb98dab4d7': 're4_switch'};
  function labTitleFor(gameId){ return LAB_TITLES[String(gameId||'')] || null; }
  function swapOptions(map, selected){
    return Object.keys(map).map(k=>`<option value="${escape(k)}"${k===selected?' selected':''}>${escape(k)}</option>`).join('');
  }
  function swapHTML(){
    return `<div class="pip-mm-swaps"><small>Characters &amp; zombies · applies at the next boot</small>`+
      `<label>Slot <select data-mm-swap-slot>${swapOptions(SWAP.slots,'chris')}</select></label>`+
      `<label>Donor <select data-mm-swap-donor>${swapOptions(SWAP.slots,'jill')}</select></label>`+
      `<span class="pip-mm-swap-buttons">`+
      `<button type="button" data-mm-swap="clothes">Swap clothes</button>`+
      `<button type="button" data-mm-swap="plain">Plain (remove clothes)</button>`+
      `<button type="button" data-mm-swap="to-zombie">Character → zombie</button>`+
      `<button type="button" data-mm-swap="from-cast">Zombies → cast</button>`+
      `</span><label class="pip-mm-retag"><input type="checkbox" data-mm-retag> Allow a skin of another size `+
      `(retags the slot's texture; off by default)</label></div>`;
  }
  function wireSwaps(root,{api,title,sessionId,done,fail}){
    const APPLY = 'mercmode-swap';            // every panel swap writes this build; apply_live boots it in place
    // which pairs a donor actually moves (gbox.skin_swap refuses maps of a different size or format), so the panel
    // can strike out a donor instead of letting a click end in a refusal
    let matrix = null;
    if (title) api('/api/decrypt-lab/swap-matrix?title=' + encodeURIComponent(title)).then((m) => {
      matrix = m || null;
      markDonors();
    }).catch(() => {});
    const refused = (slotKey, donorKey) => {
      if (!matrix) return false;
      const row = (matrix.pairs || {})[slotKey + '|' + donorKey];
      return row ? !row.ok : false;
    };
    function markDonors(){
      const slot = root.querySelector('[data-mm-swap-slot]')?.value;
      const donor = root.querySelector('[data-mm-swap-donor]');
      if (!matrix || !slot || !donor) return;
      [...donor.options].forEach((o) => {
        const row = (matrix.pairs || {})[slot + '|' + o.value];
        const ok = !row || row.ok;
        o.disabled = !ok;
        o.textContent = o.value + (ok ? '' : ' (format mismatch)');
      });
    }
    root.querySelector('[data-mm-swap-slot]')?.addEventListener('change', markDonors);
    const applyNow = async(session)=>{
      // Eden layers mods only at boot, so a live swap is the title restarting in this same session (gbox.switch_mods
      // apply_live): the operator sees the new skin without ending the round's session
      const worker=String(session).split('-')[0];
      let job=await api('/api/jobs',{tool:'switch_mods',require_worker:worker,
        input:{op:'apply_live',session_id:session,build:APPLY}});
      for(let i=0;i<200&&['queued','running','assigned'].includes(job?.state);i++){
        await new Promise(r=>setTimeout(r,1500));
        job=await api('/api/jobs/'+encodeURIComponent(job.id),undefined,'GET');
      }
      if(job?.state!=='succeeded')throw Error(job?.error?.message||job?.error||job?.state||'the restart did not finish');
      return job;
    };
    // A retagged swap moves a skin whose dimensions differ from the slot's, letting the tag travel with the donor's
    // data (gbox.skin_swap follow_tag). Measured 2026-11-05: such a build boots, renders and plays rounds, so a
    // complete character <-> enemy reskin is reachable without a texture encoder; it is off by default because the
    // engine was written for the slot's own size, and it is the operator's call.
    const retag = () => !!root.querySelector('[data-mm-retag]')?.checked;
    const run=async(kind)=>{
      const slotKey=root.querySelector('[data-mm-swap-slot]')?.value||'chris';
      const donorKey=root.querySelector('[data-mm-swap-donor]')?.value||'jill';
      const slot=SWAP.slots[slotKey], donor=SWAP.slots[donorKey];
      if(!slot||!donor)throw Error('Choose a slot and a donor.');
      if(kind!=='plain' && !retag() && refused(slotKey,donorKey))
        throw Error(`${slotKey} and ${donorKey} do not share a texture format: pick another donor, or allow a skin of another size.`);
      if(kind==='plain')
        // clothes removed for real: the character's body skin maps are painted over its clothing groups
        return api('/api/decrypt-lab/strip-clothes',{title,arc_path:slot,build:APPLY});
      let arc=slot, from=donor;
      if(kind==='to-zombie'){arc=slot;from=SWAP.slots.zombie;}
      else if(kind==='from-cast'){arc=SWAP.slots.zombie;from=slot;}
      if(!from)throw Error('That swap has no donor archive.');
      return api('/api/decrypt-lab/model-swap',{title,arc_path:arc,donor_arc:from,build:APPLY,
        ...(retag()?{tag_follow:true}:{})});
    };
    root.querySelectorAll('[data-mm-swap]').forEach(b=>b.addEventListener('click',async e=>{
      e.stopPropagation();
      try{
        const r=await run(b.dataset.mmSwap);
        let live='';
        if(sessionId){
          try{await applyNow(sessionId);live=' · applied now: the title restarted in this session';}
          catch(err){live=` · built, but the live restart failed: ${err.message}`;}
        }
        const kept = (r.maps || []).find((m) => String(m).startsWith('kept:'));
        const extent = kept ? ` (partial: ${String(kept).slice(5)} kept)` : '';
        done(b.dataset.mmSwap==='plain'
          ? `Clothes removed: ${r.replaced?.length||0} clothing map(s) repainted with ${r.body_group}'s skin${live||' (applies at the next boot)'}`
          : `${b.textContent}: ${r.slot} ← ${r.donor}${extent}${live||' (applies at the next boot)'}`);
      }
      catch(error){fail(error);}
    }));
    root.querySelector('[data-mm-obj-swap]')?.addEventListener('click',async e=>{
      e.stopPropagation();
      try{
        const slot=SWAP.objects[root.querySelector('[data-mm-obj-slot]')?.value||'mine'];
        const donor=SWAP.objects[root.querySelector('[data-mm-obj-donor]')?.value||'grenade'];
        if(!slot||!donor||slot===donor)throw Error('Choose two different objects.');
        // texture-only: a donor MESH breaks the title's load (measured 2026-11-05: the object build sat at
        // screen=loading for 5+ minutes while a skin build reached playing and advanced rounds), so the panel never
        // asks for with_mesh. The API still offers it for experiments.
        const r=await api('/api/decrypt-lab/model-swap',{title,arc_path:slot,donor_arc:donor,build:APPLY});
        let live='';
        if(sessionId){
          try{await applyNow(sessionId);live=' · applied now: the title restarted in this session';}
          catch(err){live=` · built, but the live restart failed: ${err.message}`;}
        }
        done(`${r.slot} now looks like ${r.donor}${live||' (applies at the next boot)'}`);
      }
      catch(error){fail(error);}
    });
    root.querySelector('[data-mm-zombie]')?.addEventListener('click',async e=>{
      e.stopPropagation();
      try{
        // both directions in one build: the player arc takes the enemy's skin, the enemy arc takes the cast's
        const player=SWAP.slots[root.querySelector('[data-mm-swap-slot]')?.value||'chris'];
        const enemy=SWAP.slots.zombie;
        const a=await api('/api/decrypt-lab/model-swap',{title,arc_path:player,donor_arc:enemy,build:APPLY,
          ...(retag()?{tag_follow:true}:{})});
        const b=await api('/api/decrypt-lab/model-swap',{title,arc_path:enemy,donor_arc:player,build:APPLY,
          ...(retag()?{tag_follow:true}:{})});
        let live='';
        if(sessionId){
          try{await applyNow(sessionId);live=' · applied now: the title restarted in this session';}
          catch(err){live=` · built, but the live restart failed: ${err.message}`;}
        }
        done(`Zombie round: you as ${a.donor} (${a.slot}) and the enemies as ${b.donor} (${b.slot})`+
             `${live||' (applies at the next boot)'}`);
      }
      catch(error){fail(error);}
    });
  }
  function objectsHTML(){
    return `<div class="pip-mm-objects"><small>Mines &amp; grenades · what appears when one is placed or thrown</small>`+
      `<label>Object <select data-mm-obj-slot>${swapOptions(SWAP.objects,'mine')}</select></label>`+
      `<label>Looks like <select data-mm-obj-donor>${swapOptions(SWAP.objects,'grenade')}</select></label>`+
      `<span class="pip-mm-swap-buttons"><button type="button" data-mm-obj-swap="swap">Swap the object</button></span></div>`+
      // The requested zombie scenario, as far as the asset layer honestly reaches: the player wears a zombie's skin
      // and the enemies wear the cast's. A zombie MESH for the player would move the skeleton (and a donor mesh stops
      // the title loading - measured), so this is both skin swaps at once, not a new game mode.
      `<div class="pip-mm-zombie"><small>Zombie round · the player as a zombie against the cast</small>`+
      `<span class="pip-mm-swap-buttons"><button type="button" data-mm-zombie="1">Player &#8594; zombie, enemies &#8594; cast</button></span></div>`;
  }
  function menuHTML(host,open=false,catalog=null,session=null){
    if(!host)return `<div class="pip-mercmode"><small>MercMode: no gBox PC owns this game.</small></div>`;
    const on=!!host.settings?.enabled,chosen=host.settings?.titles||[];
    const label=on?'🔁 MercMode: rotating titles · click to stay in this game':'▶ MercMode: play across titles · click to turn on';
    const titles=(host.titles||[]).map(t=>`<label${t.playable?'':' class="pip-mercmode-off"'}><input type="checkbox" data-mm-title="${escape(t.title)}" ${chosen.includes(t.title)?'checked':''} ${t.playable?'':'disabled'}> ${escape(t.name)}${t.playable?'':` <small>· unavailable: ${escape(t.reason||'')}</small>`}</label>`).join('');
    return `<div class="pip-mercmode" data-mm-host="${escape(host.name)}"><div class="pip-mercmode-row"><button type="button" data-mm-toggle aria-pressed="${on}">${label}</button><button type="button" data-mm-arrow aria-expanded="${open}" aria-label="Choose the titles MercMode rotates through">${open?'▾':'▸'}</button></div>`+
      `<div class="pip-mercmode-titles"${open?'':' hidden'}>${titles}<label>Rounds before switching <input type="number" data-mm-rounds min="1" max="20" value="${Number(host.settings?.rounds_per_title)||1}"></label>`+
      `<span class="pip-mm-rounds-quick">${[5,10,20].map(n=>`<button type="button" data-mm-rounds-pick="${n}"${Number(host.settings?.rounds_per_title)===n?' aria-pressed="true"':''}>${n}</button>`).join('')}</span>`+
      `<label class="pip-mm-stalemate"><input type="checkbox" data-mm-stalemate ${host.settings?.stalemate_cut===false?'':'checked'}> Stalemate: no enemy for 15 s, cut the clock to <input type="number" data-mm-stalemate-s min="${STALEMATE.min}" max="${STALEMATE.max}" value="${stalemateSeconds(host.settings)}"> s</label>`+
      `<label class="pip-mm-coop">Bot+bot split screen (Switch RE5 / RE6) ${coopSelect('data-mm-coop',host.settings?.coop_ratio)}</label>`+
      `<label class="pip-mm-skin"><input type="checkbox" data-mm-skin-swap ${host.settings?.skin_swap==='random'?'checked':''}> 🎭 Random skin swap: each round plays one character with another's model (Switch RE5)</label>`+
      (SWITCH_GAMES[session?.game_id]?`<button type="button" data-mm-play-bot title="You play Player 1, the bot plays Player 2 in split screen. The title restarts in this session with Player 2 connected.">🎮 Play with bot (${SWITCH_GAMES[session.game_id]} split screen)</button>`:'')+
      `${host.current_run?.mercmode?`<small>${escape(host.current_run.phase)}: ${escape(host.current_run.title)} · ${Number(host.current_run.mercmode_rounds)||0} verified rounds</small>`:''}${queueHTML(host,catalog)}${swapHTML()}${objectsHTML()}</div></div>`;
  }
  // "Play with bot" (operator 2026-10-27): the operator as Player 1, the bot as Player 2 in this exact Switch session -
  // the team role, Player 2 connected by an in-place title restart, then the autobot; each step a job confirmed in turn
  async function jobRun(api,tool,input){
    const worker=String(input.session_id).split('-')[0];
    let job=await api('/api/jobs',{tool,agent_use:false,require_worker:worker,input});
    for(let i=0;i<300&&['queued','running','assigned'].includes(job?.state);i++){
      await new Promise(r=>setTimeout(r,500));
      job=await api('/api/jobs/'+encodeURIComponent(job.id),undefined,'GET');
    }
    if(job?.state!=='succeeded')throw Error(`${tool}: ${job?.error?.message||job?.error||job?.state||'no answer'}`);
    return job.output?.result||{};
  }
  async function playWithBot(api,value){
    const sid=value?.session_id;
    if(!SWITCH_GAMES[value?.game_id]||typeof sid!=='string'||!sid.includes('-'))throw Error('Play with bot needs an RE5 or RE6 Switch session.');
    await jobRun(api,'mercs_team',{session_id:sid,op:'configure',role:'teammate_p2'});
    await jobRun(api,'mercs_team',{session_id:sid,op:'prepare_player2',restart:true});
    await jobRun(api,'autoplay',{session_id:sid,op:'start',mode:'auto',continuous:true});
    return 'Player 2 connected: the title restarts in this session. Choose split screen (RE6 No Mercy > SPLIT, RE5 Mercenaries United > SPLIT-SCREEN); the bot joins as Player 2.';
  }
  async function menuAction(api,host,action,value){
    if(!host?.name)throw Error('No gBox PC owns this game.');
    if(action==='toggle'){
      const enabled=!host.settings?.enabled;
      await api('/api/mercmode',{host:host.name,enabled});
      return enabled?'MercMode on: the next native round end switches titles.':'MercMode rotation off. Autobot continues in this game.';
    }
    if(action==='skin-swap'){
      const on=!!value?.checked;
      await api('/api/mercmode',{host:host.name,skin_swap:on?'random':'off'});
      return on?"Random skin swaps on: every round plays one character with another character's model."
               :'Skin swaps off: rounds play the title as it is.';
    }
    if(action==='title'){      const chosen=new Set(host.settings?.titles||[]);
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
    if(action==='stalemate'){
      const enabled=value?.enabled===undefined?host.settings?.stalemate_cut!==false:!!value.enabled;
      const seconds=stalemateSeconds({stalemate_cut_s:value?.seconds===undefined?host.settings?.stalemate_cut_s:value.seconds});
      await api('/api/mercmode',{host:host.name,stalemate_cut:enabled,stalemate_cut_s:seconds});
      return enabled?`Stalemate rule on: no enemy for 15 s, the bot cuts the clock to ${seconds} s (from the next launch)`
        :'Stalemate rule off: the bot leaves the clock alone (from the next launch)';
    }
    if(action==='coop'){                // bot+bot split screen on the Switch editions: co-op : solo turns, off by default
      if(!COOP_RATIOS.includes(value))throw Error('Choose a co-op ratio from the list.');
      await api('/api/mercmode',{host:host.name,coop_ratio:value});
      return value==='off'?'Switch RE5 / RE6 turns play solo (from the next launch)'
        :value==='only'?'Every Switch RE5 / RE6 turn plays split screen with bots on both players (from the next launch)'
        :`Switch RE5 / RE6 turns: ${value} co-op to solo (from the next launch)`;
    }
    if(action==='play_with_bot')return playWithBot(api,value);
    throw Error('Unknown MercMode action');
  }
  // --- between titles: what the PiP shows while the next game boots in the background ---
  // A warm switch (run.warm_from: the next title was kept in memory and, prepared, is resumed on the first frame of its
  // round) has a live game from the first moment: no loading screen, the PiP follows the new session as soon as its
  // bot is running (operator 2026-10-26: "I need it to be a seamless swap for these titles. I hate waiting").
  // Is this viewer surely watching MercMode on that PC? Its run's game, a game of its warm pool, the run before, or a
  // session of an earlier start of the PC's worker (a service restart ended it). Anything else may be the operator's own
  // game there: the PiP moves only when that session has ended (the caller sees the running list, this status does not)
  function watching(host,sid){
    const run=host?.current_run||{};
    if(!sid||!host?.id)return true;
    if(sid===run.session_id||sid===run.mercmode_predecessor?.session_id)return true;
    if((host.warm||[]).some(w=>w&&w.session_id===sid))return true;
    return !String(sid).startsWith(host.id+'-');
  }
  function transition(host,sid,now=Date.now()/1000){
    const run=host?.current_run;
    if(!host?.settings?.enabled||!run?.mercmode)return {show:false};
    // the run is live on another session: the viewer goes to it - never a loading screen over a running game (operator
    // 2026-10-26: "so why is still here? i just want mercenaries perpetual" - after a service restart the PiP kept the
    // dead session and showed "Loading Resident Evil 5..." for 13 minutes while RE5 played)
    if(run.phase==='playing'&&run.session_id&&run.session_id!==sid)
      return watching(host,sid)?{show:false,follow:run.session_id}:{show:false,follow:run.session_id,only_if_ended:true};
    if(run.warm_from&&run.session_id)return {show:false,warm:true};
    const since=t=>Math.max(0,now-(Number(t)||now));
    let progress=null;
    if(run.phase==='launching')progress=8+Math.min(52,52*since(run.started)/90);
    else if(run.phase==='starting')progress=65+Math.min(20,20*since(run.up||run.started)/30);
    if(progress===null)return {show:false};
    return {show:true,phase:run.phase,title:run.title||'',progress:Math.round(progress),
      text:`Loading ${run.title||'the next title'}…`,sub:'MercMode is switching titles; the next game boots in the background.'};
  }
  // --- "pip mode" on a PC whose own MercMode / autoplay runs locally (operator 2026-10-27, i9-NUC: "on the i9 nuc replace
  // the stream in the pip with the mercenaries 3d playing as an instance in the pip window"; "in the pip, I want mercenaries
  // 3d looping in the window going through rounds showing the bot"): the PiP shows this PC's own game window, follows its
  // run through every title switch, and goes back to the game it showed before (the Spark's stream) when the local run
  // stops. A dispatch with "Show in PiP on that PC" (hosts[].dispatch.pip) also opens a closed PiP for it, once.
  //   host: this PC's row from its own scheduler's GET /api/mercmode
  //   view: {shown: the PiP's session or null, running: that session still runs, last: what this follower put in the PiP,
  //          away: the operator moved the PiP off this PC's run, handled / closed: dispatch ids already acted on}
  //   -> {action: none | wait | enter | follow | away | closed | return | restore, sid?, from?, id?, remember?}
  // Never over this PC's own other game (the operator playing here); the operator's choice of another game or a closed
  // PiP stands until this PC's MercMode stops or a new dispatch comes.
  function pipOwnRun(host,view={}){
    const run=host?.current_run||null,shown=view.shown||null;
    const sid=run?.session_id&&run.phase==='playing'&&!run.handover?run.session_id:null;
    const d=host?.dispatch||null,wants=!!(d?.pip&&d.id&&['start','switch'].includes(d.command)&&!d.lapsed);
    if(!sid){
      // this PC's run stopped (not between titles): the PiP goes back to what it showed before, or gives the window back
      if(!run&&shown&&shown===view.last&&!view.running)return {action:view.returnTo?'return':'restore',from:shown};
      return {action:run?'wait':'none'};
    }
    if(shown===sid)return {action:'none'};
    if(view.away)return {action:'none'};
    if(view.last===sid)return {action:shown?'away':'closed',id:d?.id};      // moved off it / closed while it plays: by the operator
    if(!shown){
      if(wants&&view.handled!==d.id&&view.closed!==d.id)return {action:'enter',sid,id:d.id};
      return {action:'none'};
    }
    // the PiP shows another game: another PC's (the Spark's stream) or one of this PC's MercMode games (the title before,
    // a parked one, the one this follower showed) moves to this PC's current game; this PC's own other game stays
    const here=!!host.id&&String(shown).startsWith(host.id+'-');
    const ours=shown===view.last||shown===run.mercmode_predecessor?.session_id||(host.warm||[]).some(w=>w?.session_id===shown);
    if(ours||!here)return {action:'follow',from:shown,sid,id:d?.id,remember:!here&&!ours};
    return {action:'none'};
  }
  return {render,mount,stay,hostFor,menuHTML,menuAction,transition,queueHTML,queueAction,formOptions,readForm,wireQueue,wireSwaps,labTitleFor,describe,
    STALEMATE,stalemateSeconds,titleChoices,runOn,defaultHost,dispatchHTML,readDispatch,dispatchAction,runHTML,pipOwnRun};
});
