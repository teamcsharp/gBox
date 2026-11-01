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
  function mount(host,io,{button,popup}={}) {
    let state={},working=false,refreshing=false;
    const content='<h2>SSH access to this PC</h2><p class="mut">Enable Windows OpenSSH Server for remote administration with your existing Windows account or SSH keys. gBox does not change passwords, authorized keys, or SSH authentication settings.</p>'+
      '<label><span><input type="checkbox" data-ssh-auto> Enable / start SSH when gBox opens</span></label>'+
      '<p class="mut">This preference saves immediately. Setup can show a Windows administrator prompt. The service remains running when gBox closes.</p>'+
      '<button class="act" data-ssh-enable>Enable SSH on this PC</button> <button class="act" data-ssh-refresh>Refresh status</button>'+
      '<p class="mut" data-ssh-status role="status">Reading Windows SSH status…</p>'+
      '<p class="mut">gBox allows TCP 22 from the local subnet on Private and Domain networks. Existing firewall rules are preserved; they may allow other access. A reachable local port does not verify remote login or LAN connectivity.</p>';
    const views=host?[host]:[];
    if(host)host.innerHTML=quickStyle+content;
    if(popup){popup.innerHTML=quickStyle+'<button type="button" data-ssh-close aria-label="Close SSH controls">Close</button>'+content;views.push(popup);popup.hidden=true;}
    const each=(selector,fn)=>views.forEach(view=>fn(view.querySelector(selector)));
    const canEnable=()=>!working&&!state.busy&&!state.uncertain&&state.supported===true&&state.state!=='custom_installation';
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
      each('[data-ssh-auto]',el=>{el.checked=state.auto_start===true;el.disabled=working||state.busy||state.supported!==true;});
      each('[data-ssh-enable]',el=>{el.disabled=!canEnable();});
      each('[data-ssh-refresh]',el=>{el.disabled=refreshing;});
      if(button){button.hidden=state.supported===false;button.querySelector('[data-ssh-caption]').textContent=badge({...state,busy:working||state.busy});
        button.dataset.state=state.state||'unknown';button.dataset.attention=String(state.setup_result==='failure'||!!state.status_error||!!state.ui_error||!!state.uncertain||state.state==='unreachable');
        button.title=(canEnable()&&['stopped','not_installed'].includes(state.state)?'Enable SSH on this PC. Windows may ask for administrator approval. ':'SSH on this PC only. ')+describe(state)+' Open SSH controls and the app-start preference.';}
    }
    async function refresh() {
      if(refreshing)return;refreshing=true;paint();
      try {paint(await io.sshStatus());}catch{paint({...state,state:'unknown',ui_error:true,message:'SSH status could not be read.'});}
      finally {refreshing=false;paint();}
    }
    each('[data-ssh-auto]',el=>{el.onchange=async()=>{
      if(working||state.busy||state.supported!==true)return;
      const value=el.checked;working=true;paint();
      try {paint(await io.sshPreference(value));}catch{paint({...state,ui_error:true,message:'The SSH startup preference could not be saved.'});}
      finally{working=false;paint();}
    };});
    async function enable(){
      if(!canEnable())return;working=true;paint({...state,message:'Waiting for Windows elevation or setup...'});
      try {paint(await io.sshEnable());}catch{paint({...state,uncertain:true,ui_error:true,message:'SSH setup could not be confirmed. Refresh status before retrying.'});}
      finally{working=false;paint();}
    }
    each('[data-ssh-enable]',el=>{el.onclick=enable;});
    each('[data-ssh-refresh]',el=>{el.onclick=refresh;});
    io.onSshChanged?.(paint);
    refresh();
    return {refresh};
  }
  return {describe,badge,mount};
});
