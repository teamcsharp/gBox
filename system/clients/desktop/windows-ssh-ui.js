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
  function mount(host,io) {
    let state={},working=false,refreshing=false;
    host.innerHTML='<h2>SSH access to this PC</h2><p class="mut">Enable Windows OpenSSH Server for remote administration with your existing Windows account or SSH keys. gBox does not change passwords, authorized keys, or SSH authentication settings.</p>'+
      '<label><span><input type="checkbox" data-ssh-auto> Enable / start SSH when gBox opens</span></label>'+
      '<p class="mut">This preference saves immediately. Setup can show a Windows administrator prompt. The service remains running when gBox closes.</p>'+
      '<button class="act" data-ssh-enable>Enable / start SSH</button> <button class="act" data-ssh-refresh>Refresh status</button>'+
      '<p class="mut" data-ssh-status role="status">Reading Windows SSH status…</p>'+
      '<p class="mut">gBox allows TCP 22 from the local subnet on Private and Domain networks. Existing firewall rules are preserved; they may allow other access. A reachable local port does not verify remote login or LAN connectivity.</p>';
    const q=s=>host.querySelector(s);
    function paint(next=state) {
      state=next;
      q('[data-ssh-status]').textContent=describe(state);
      q('[data-ssh-auto]').checked=state.auto_start===true;
      q('[data-ssh-auto]').disabled=working||state.supported!==true;
      q('[data-ssh-enable]').disabled=working||state.busy||state.uncertain||state.supported!==true||state.state==='custom_installation';
      q('[data-ssh-refresh]').disabled=refreshing;
    }
    async function refresh() {
      if(refreshing)return;refreshing=true;paint();
      try {paint(await io.sshStatus());}catch{paint({...state,state:'unknown',message:'SSH status could not be read.'});}
      finally {refreshing=false;paint();}
    }
    q('[data-ssh-auto]').onchange=async()=>{
      const value=q('[data-ssh-auto]').checked;working=true;paint();
      try {paint(await io.sshPreference(value));}catch{paint({...state,message:'The SSH startup preference could not be saved.'});}
      finally{working=false;paint();}
    };
    q('[data-ssh-enable]').onclick=async()=>{
      if(working||state.busy)return;working=true;paint({...state,message:'Waiting for Windows elevation or setup…'});
      try {paint(await io.sshEnable());}catch{paint({...state,message:'SSH setup could not be confirmed. Refresh status before retrying.'});}
      finally{working=false;paint();}
    };
    q('[data-ssh-refresh]').onclick=refresh;
    io.onSshChanged?.(paint);
    refresh();
    return {refresh};
  }
  return {describe,mount};
});
