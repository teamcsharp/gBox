(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.GBoxWindowsSsh=api;})(typeof globalThis!=='undefined'?globalThis:this,()=>{
  function describe(state={}) {
    const labels={unknown:'SSH status unavailable',unsupported:'Windows OpenSSH management is available on Windows only',
      not_installed:'OpenSSH Server is not installed',stopped:'OpenSSH Server is stopped',
      custom_installation:'A custom SSH service is installed; gBox will preserve it',
      running:'SSH is running; local TCP port 22 is reachable',
      unreachable:'SSH is running, but local TCP port 22 is not reachable'};
    const rule=state.firewall==='scoped'?'gBox firewall: local subnet, Private and Domain networks.':
      state.firewall==='unknown'?'Firewall status could not be read.':
      state.firewall==='name_conflict'?'The gBox firewall rule name is already in use.':
      state.supported?'The gBox LAN firewall rule needs setup.':'';
    return [labels[state.state]||labels.unknown,rule,state.message||''].filter(Boolean).join(' ');
  }
  function badge(state={}) {
    if(state.busy)return 'SSH: Setup';
    if(state.uncertain)return 'SSH: Check';
    if(state.setup_result==='failure'||state.status_error||state.ui_error)return 'SSH: Error';
    if(state.state==='running')return 'SSH: On';
    if(['stopped','not_installed'].includes(state.state))return 'Enable SSH';
    if(state.state==='unreachable')return 'SSH: Unreachable';
    if(state.state==='custom_installation')return 'SSH: Custom';
    return 'SSH: Check';
  }
  function failure(error,operation='status') {
    const text=String(error?.message||error||'');
    if(error?.code==='missing_bridge'||/is not a function/.test(text))return {error_kind:'missing_bridge',restart_needed:true,
      message:'This window has SSH controls but its desktop bridge is older or missing. Restart the full gBox app to load matching SSH controls.'};
    if(/No handler registered|No handler for/.test(text))return {error_kind:'missing_handler',restart_needed:true,
      message:'The running gBox backend has no SSH handler. Restart the full app; reloading only this page cannot install the handler.'};
    if(/Only the local gBox|Only the gBox app|main frame|manage Windows SSH/.test(text))return {error_kind:'window_rejected',restart_needed:true,
      message:'The SSH backend rejected this window identity. Restart the full gBox app to load its matching local window and bridge.'};
    return {error_kind:operation==='status'?'status_request_failed':'setup_reply_failed',restart_needed:false,
      message:operation==='status'?'The SSH status request failed before Windows returned a result. On Windows, you can explicitly try Force enable SSH (Administrator).':
        'SSH setup was requested but its reply could not be confirmed. Windows may still be working; another setup request is blocked.'};
  }
  async function restartGuidance(io) {
    const manual='Quit the full gBox app and start it again on this PC. This closes games hosted by this PC; remote sessions keep running. Refreshing only the page cannot load missing backend handlers.';
    if(typeof io.clientUpdate!=='function')return {reason:'This running app has no local updater bridge. '+manual};
    const update=await io.clientUpdate();
    const detail=typeof update?.detail==='string'?update.detail:'';
    const outcome=update?.state==='updated'?'Local app files updated.':update?.state==='current'?'Local app files are current.':
      ['waiting','skipped','failed'].includes(update?.state)?'The local update did not complete.':'The local update result could not be confirmed.';
    return {reason:[outcome,detail,manual].filter(Boolean).join(' ')};
  }
  const quickStyle=`<style>
    #ssh-access-button {position:fixed;top:4px;right:150px;z-index:112;display:flex;align-items:center;gap:6px;
      height:28px;max-width:calc(100vw - 16px);box-sizing:border-box;padding:3px 10px;border:1px solid #8395ac;border-radius:6px;background:#213349;color:#edf5ff;
      font:12px system-ui;white-space:nowrap;cursor:pointer;-webkit-app-region:no-drag;}
    #ssh-access-button [data-ssh-caption] {min-width:0;overflow:hidden;text-overflow:ellipsis;}
    #ssh-access-button svg {width:16px;height:16px;flex:none;}
    #ssh-access-button[data-state=running] {background:#17382c;border-color:#499c78;}
    #ssh-access-button[data-attention=true] {background:#49351d;border-color:#bc965d;}
    #ssh-access-button:focus-visible,#ssh-access-popover button:focus-visible {outline:2px solid #8abbff;outline-offset:2px;}
    #ssh-access-button[hidden],#ssh-access-popover[hidden] {display:none!important;}
    #ssh-access-popover {position:fixed;top:40px;right:150px;z-index:113;width:min(380px,calc(100vw - 16px));
      max-height:calc(100vh - 56px);box-sizing:border-box;overflow:auto;padding:14px;border:1px solid #586a82;
      border-radius:10px;background:#181d26;color:#edf5ff;box-shadow:0 10px 36px #0009;font:13px/1.45 system-ui;
      -webkit-app-region:no-drag;}
    #ssh-access-popover h2 {font-size:16px;margin:0 28px 8px 0;}
    #ssh-access-popover p {margin:8px 0;}
    #ssh-access-popover .mut {color:#c0cad8;}
    #ssh-access-popover button {font:inherit;cursor:pointer;border:1px solid #71849e;border-radius:5px;padding:5px 9px;background:#263a54;color:#edf5ff;}
    #ssh-access-popover button:disabled {opacity:.55;cursor:default;}
    #ssh-access-popover [data-ssh-close] {float:right;margin:-4px -4px 0 4px;}
    #ssh-access-popover label {display:block;}
    #ssh-access-popover input {width:auto;}
    #ssh-access-popover [data-ssh-status] {padding:8px;border-radius:5px;background:#10151d;}
    @media(max-width:1500px) {
      #ssh-access-button {top:88px;right:12px;}
      #ssh-access-popover {top:124px;right:12px;max-height:calc(100vh - 136px);}
    }
    body.gbox-compact #ssh-access-button,body.ssh-mini #ssh-access-button {top:38px;right:8px;bottom:auto;}
    body.gbox-compact #ssh-access-popover,body.ssh-mini #ssh-access-popover {top:74px;right:8px;bottom:auto;max-height:calc(100vh - 82px);}
    @media(max-height:220px) {
      body.gbox-compact #ssh-access-popover,body.ssh-mini #ssh-access-popover {top:4px;right:4px;width:calc(100vw - 8px);max-height:calc(100vh - 8px);}
    }
  </style>`;
  function mount(host,io,{button,popup,restart,restartLabel='Check update / restart instructions'}={}) {
    let state={},working=false,refreshing=false;
    const content='<h2>SSH access to this PC</h2><p class="mut">Enable Windows OpenSSH Server for remote administration with your existing Windows account or SSH keys. gBox does not change passwords, authorized keys, or SSH authentication settings.</p>'+
      '<label><span><input type="checkbox" data-ssh-auto> Enable / start SSH when gBox opens</span></label>'+
      '<p class="mut">This preference saves immediately. Setup can show a Windows administrator prompt. The service remains running when gBox closes.</p>'+
      '<button class="act" data-ssh-enable>Enable SSH on this PC</button> <button class="act" data-ssh-refresh>Refresh status</button>'+
      '<p><button class="act" data-ssh-force hidden>Force enable SSH (Administrator)</button></p>'+
      '<p class="mut" data-ssh-force-help hidden>This explicitly runs the standard Windows setup even when status cannot be read. It keeps existing SSH authentication and custom-server safeguards. A pending or uncertain setup cannot be repeated.</p>'+
      '<p><button class="act" data-ssh-restart hidden></button></p>'+
      '<p class="mut" data-ssh-restart-help hidden>A full quit and start is needed. This button checks for local app updates and shows instructions; it never restarts gBox or stops games for you.</p>'+
      '<p class="mut" data-ssh-status role="status">Reading Windows SSH status…</p>'+
      '<p class="mut">gBox allows TCP 22 from the local subnet on Private and Domain networks. Existing firewall rules are preserved; they may allow other access. A reachable local port does not verify remote login or LAN connectivity.</p>';
    const views=host?[host]:[];
    if(host)host.innerHTML=quickStyle+content;
    if(popup){popup.innerHTML=quickStyle+'<button type="button" data-ssh-close aria-label="Close SSH controls">Close</button>'+content;views.push(popup);popup.hidden=true;}
    const each=(selector,fn)=>views.forEach(view=>fn(view.querySelector(selector)));
    const setupReady=()=>!working&&!state.busy&&!state.uncertain&&!state.restart_needed&&state.supported===true&&typeof io.sshEnable==='function'&&state.state!=='custom_installation';
    const canEnable=()=>setupReady()&&state.state!=='unknown';
    const canForce=()=>setupReady()&&state.state==='unknown';
    function close(){if(popup)popup.hidden=true;button?.setAttribute('aria-expanded','false');button?.focus();}
    if(button){
      button.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="8" cy="8" r="5"/><path d="m12 12 9 9m-5-5 3-3m-6 0 3-3"/></svg><span data-ssh-caption>SSH: Check</span>';
      button.setAttribute('aria-controls','ssh-access-popover');button.setAttribute('aria-expanded','false');
      button.onclick=()=>{if(!popup)return;
        const start=canEnable()&&['stopped','not_installed'].includes(state.state);
        popup.hidden=start?false:!popup.hidden;button.setAttribute('aria-expanded',String(!popup.hidden));
        if(!popup.hidden){popup.querySelector('[data-ssh-close]').focus();return start?enable():refresh();}};
    }
    if(popup){popup.querySelector('[data-ssh-close]').onclick=close;
      popup.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}});}

    function paint(next=state) {
      state=next;
      each('[data-ssh-status]',el=>{el.textContent=describe(state);});
      each('[data-ssh-auto]',el=>{el.checked=state.auto_start===true;el.disabled=working||state.busy||state.restart_needed||state.supported!==true||typeof io.sshPreference!=='function';});
      each('[data-ssh-enable]',el=>{el.disabled=!canEnable();});
      each('[data-ssh-refresh]',el=>{el.disabled=refreshing;});
      each('[data-ssh-force]',el=>{el.hidden=state.state!=='unknown';el.disabled=!canForce();});
      each('[data-ssh-force-help]',el=>{el.hidden=state.state!=='unknown';});
      each('[data-ssh-restart]',el=>{el.textContent=restartLabel;el.hidden=!state.restart_needed;el.disabled=working||state.busy||state.uncertain||typeof restart!=='function';});
      each('[data-ssh-restart-help]',el=>{el.hidden=!state.restart_needed;});
      if(button){button.hidden=state.supported===false;button.querySelector('[data-ssh-caption]').textContent=badge({...state,busy:working||state.busy});
        button.dataset.state=state.state||'unknown';button.dataset.attention=String(state.setup_result==='failure'||!!state.status_error||!!state.ui_error||!!state.uncertain||state.state==='unreachable');
        button.title=(canEnable()&&['stopped','not_installed'].includes(state.state)?'Enable SSH on this PC. Windows may ask for administrator approval. ':'SSH on this PC only. ')+describe(state)+' Open SSH controls and the app-start preference.';}
    }
    async function refresh() {
      if(refreshing)return;refreshing=true;paint();
      try {
        if(typeof io.sshStatus!=='function')throw Object.assign(Error('missing bridge'),{code:'missing_bridge'});
        const reply=await io.sshStatus();
        if(!reply||typeof reply.supported!=='boolean'||typeof reply.state!=='string')throw Error('Invalid SSH status reply');
        paint(reply);
      }catch(error){
        const supported=io.sshPlatform==='win32'?true:state.supported;let detail=failure(error);
        if(supported!==true&&!detail.restart_needed)detail={error_kind:'platform_unconfirmed',restart_needed:true,
          message:'The SSH request failed before this app could confirm its Windows backend. Check updates, then fully quit and start gBox on this PC. Force setup needs a confirmed Windows backend.'};
        paint({...state,supported,state:'unknown',ui_error:true,...detail});
      }
      finally {refreshing=false;paint();}
    }
    each('[data-ssh-auto]',el=>{el.onchange=async()=>{
      if(working||state.busy||state.restart_needed||state.supported!==true||typeof io.sshPreference!=='function')return;
      const value=el.checked;working=true;paint();
      try {paint(await io.sshPreference(value));}catch{paint({...state,ui_error:true,message:'The SSH startup preference could not be saved.'});}
      finally{working=false;paint();}
    };});
    async function enable(force=false){
      if(!(force?canForce():canEnable()))return;working=true;paint({...state,message:'Waiting for Windows elevation or setup...'});
      try {paint(await io.sshEnable());}catch(error){const detail=failure(error,'setup');paint({...state,uncertain:!detail.restart_needed,ui_error:true,...detail});}
      finally{working=false;paint();}
    }
    each('[data-ssh-enable]',el=>{el.onclick=()=>enable(false);});
    each('[data-ssh-force]',el=>{el.onclick=()=>enable(true);});
    each('[data-ssh-restart]',el=>{el.onclick=async()=>{
      if(working||state.busy||state.uncertain||!state.restart_needed||typeof restart!=='function')return;
      working=true;paint();
      try {const result=await restart();paint({...state,message:result?.reason||'Quit the full gBox app and start it again on this PC to load the installed backend.'});}
      catch{paint({...state,message:'The local app update check failed. Quit the full app and start it again on this PC; refreshing only the page is insufficient.'});}
      finally{working=false;paint();}
    };});
    each('[data-ssh-refresh]',el=>{el.onclick=refresh;});
    io.onSshChanged?.(paint);
    refresh();
    return {refresh};
  }
  return {describe,badge,failure,restartGuidance,mount};
});
