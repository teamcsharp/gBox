// Shared by desktop PiP, web viewers, and embedders. One UUID per click;
// polling confirms effects without touching the video source or reconnecting it.
(function(root) {
  'use strict';
  const terminal = new Set(['confirmed', 'failed', 'unavailable', 'expired', 'uncertain']);
  let activeSidebar = null;
  const KEY = 'gbox.merc.flashShortcut.v1';
  const DEFAULT = {code:'KeyF', key:'F', ctrl:false, alt:false, shift:false, meta:false};
  function shortcut(storage) {
    try {
      const raw=storage?.getItem(KEY); if(raw==null)return {...DEFAULT};
      const v=JSON.parse(raw); if(v===null)return null;
      if(typeof v.code==='string' && /^[A-Za-z][A-Za-z0-9]{0,30}$/.test(v.code) && typeof v.key==='string' && v.key.length<=30 &&
          ['ctrl','alt','shift','meta'].every(k=>typeof v[k]==='boolean'))return v;
    } catch {}
    return {...DEFAULT};
  }
  function keyLabel(v) { return v ? [v.ctrl&&'Ctrl',v.alt&&'Alt',v.shift&&'Shift',v.meta&&'Meta',v.key].filter(Boolean).join('+') : 'Unmapped'; }
  // The visible button owns the shortcut. Capturing it here also prevents a
  // bound key from becoming a controller input. Text editing remains untouched.
  function bindFlash(button, {flash, sid, enabled=()=>true, storage}) {
    const doc=button.ownerDocument, win=doc.defaultView;
    if(storage===undefined)try{storage=win.localStorage;}catch{}
    let binding=shortcut(storage), menu=null, listening=false, dead=false, last='', sequence=0;
    const held=new Set();
    const selected=()=>typeof sid==='function'?sid():sid;
    const active=()=>!dead && enabled() && selected() && button.isConnected && button.getClientRects().length;
    function paint() {
      const label=keyLabel(binding);
      button.title=`Instant flashbang at the player (${label}). Right-click to change or unmap the shortcut.${last?'\n'+last:''}`;
      button.setAttribute('aria-label',`Instant flashbang (${label})`);
      if(binding)button.setAttribute('aria-keyshortcuts',label);else button.removeAttribute('aria-keyshortcuts');
    }
    function receipt(text,row) {
      if(dead || (row?.sid && row.sid!==selected()))return;
      last=text; button.dataset.flashState=row?.state || 'unavailable'; paint();
    }
    function activate(event) {
      event?.preventDefault(); event?.stopPropagation();
      if(!active())return;
      const session=selected(), seq=++sequence;
      receipt('Request sent.',{state:'sending'});
      // Each tap starts its own request immediately, including during a burst.
      Promise.resolve().then(()=>flash(session)).then(out=>{
        if(seq===sequence && session===selected() && out?.request)
          receipt(out.request.reason || '',{...out.request,sid:session});
      }).catch(error=>{
        if(seq===sequence && session===selected())receipt(error.message,{state:'unavailable',sid:session});
      });
    }
    function close() {menu?.remove();menu=null;listening=false;button.setAttribute('aria-expanded','false');}
    function save(value) {
      binding=value;try{storage?.setItem(KEY,JSON.stringify(value));}catch{}
      last='';paint();close();
    }
    const consume=e=>{e.preventDefault();e.stopImmediatePropagation();};
    function key(e) {
      if(dead)return;
      if(e.type==='keyup') {if(held.delete(e.code))consume(e);return;}
      if(menu && e.key==='Escape'){consume(e);close();button.focus();return;}
      if(listening) {
        consume(e);
        if(e.repeat || e.isComposing || !e.code || /^(Shift|Control|Alt|Meta)/.test(e.code))return;
        held.add(e.code);
        save({code:e.code,key:e.key===' '?'Space':e.key.length===1?e.key.toUpperCase():e.key,
          ctrl:e.ctrlKey,alt:e.altKey,shift:e.shiftKey,meta:e.metaKey});return;
      }
      if(!active() || e.isComposing || e.defaultPrevented || e.target?.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],dialog[open],[role="dialog"]'))return;
      if(storage)binding=shortcut(storage);
      if(!binding || e.code!==binding.code || ['ctrl','alt','shift','meta'].some(k=>!!e[k+'Key']!==binding[k]))return;
      consume(e);held.add(e.code);if(!e.repeat)activate();
    }
    function context(e) {
      consume(e);close();if(!active())return;
      if(storage)binding=shortcut(storage);
      menu=doc.createElement('div');menu.className='flash-shortcut-menu';menu.setAttribute('role','menu');
      Object.assign(menu.style,{position:'fixed',zIndex:'10000',background:'#1d1d22',color:'#eee',border:'1px solid #666',borderRadius:'6px',padding:'6px',minWidth:'210px',font:'13px sans-serif',webkitAppRegion:'no-drag'});
      const label=doc.createElement('div');label.textContent=`Flashbang shortcut: ${keyLabel(binding)}`;label.style.padding='6px';menu.append(label);
      for(const [text,fn] of [['Change shortcut',()=>{listening=true;label.textContent='Press a key (Esc cancels)';}],['Unmap shortcut',()=>save(null)],['Reset to F',()=>save({...DEFAULT})]]) {
        const item=doc.createElement('button');item.type='button';item.textContent=text;item.setAttribute('role','menuitem');
        Object.assign(item.style,{display:'block',width:'100%',textAlign:'left',padding:'6px',background:'transparent',color:'inherit',border:'0',cursor:'pointer'});
        item.onclick=e=>{e.stopPropagation();fn();};menu.append(item);
      }
      doc.body.append(menu);const rect=button.getBoundingClientRect();
      menu.style.left=Math.max(4,Math.min(rect.left,win.innerWidth-menu.offsetWidth-4))+'px';
      menu.style.top=Math.max(4,Math.min(rect.bottom+4,win.innerHeight-menu.offsetHeight-4))+'px';
      button.setAttribute('aria-expanded','true');menu.querySelector('button').focus();
    }
    function outside(e){if(menu && !menu.contains(e.target) && !button.contains(e.target))close();}
    function blur(){held.clear();close();}
    function refreshed(){binding=shortcut(storage);paint();}
    button.addEventListener('click',activate);button.addEventListener('contextmenu',context);
    win.addEventListener('keydown',key,true);win.addEventListener('keyup',key,true);
    win.addEventListener('blur',blur);win.addEventListener('storage',refreshed);
    doc.addEventListener('pointerdown',outside,true);paint();
    return {receipt,dispose(){dead=true;close();button.removeEventListener('click',activate);button.removeEventListener('contextmenu',context);
      win.removeEventListener('keydown',key,true);win.removeEventListener('keyup',key,true);win.removeEventListener('blur',blur);
      win.removeEventListener('storage',refreshed);doc.removeEventListener('pointerdown',outside,true);}};
  }
  function create({api, notify = () => {}, uuid = () => root.crypto.randomUUID(), now = Date.now,
                   schedule = root.setTimeout.bind(root), cancel = root.clearTimeout.bind(root)}) {
    const pending = new Map(); let timer = null, dead = false, polling = false;
    function message(row) {
      const weapon = row.op === 'equip_primary';
      if (row.state === 'confirmed') return weapon ?
        `${row.result?.weapon || 'Primary weapon'} equipped. Locked for two minutes; preferred for this match.` : 'Flashbang detonated.';
      return `${weapon ? 'Weapon selection' : 'Flashbang'} ${row.state}: ${row.result?.reason || row.reason || 'no confirmed effect'}`;
    }
    function wake() { if (!dead && !timer && pending.size) timer = schedule(poll, 100); }
    async function poll() {
      timer = null; if (dead || polling) return; polling = true;
      try {
        for (const sid of new Set([...pending.values()].map(r => r.sid))) {
          try {
            const state = await api(`/api/sessions/${encodeURIComponent(sid)}/interventions`);
            if (dead) return;
            for (const row of state.requests || []) {
              const own = pending.get(row.id);
              if (!own || own.sid !== sid || !terminal.has(row.state)) continue;
              pending.delete(row.id);
              const receipt={...row,op:row.op || own.op,sid};
              notify(message(receipt), receipt);
            }
          } catch { /* Receipt lookup may retry. The effect request never does. */ }
        }
        for (const [id, row] of pending) if (now() - row.at > 15000) {
          pending.delete(id); notify(`${row.op === 'equip_primary' ? 'Weapon selection' : 'Flashbang'} receipt unavailable. The request will not be repeated.`, {id,op:row.op,sid:row.sid,state:'uncertain'});
        }
      } finally { polling = false; wake(); }
    }
    async function send(sid, op, args) {
      if (dead || !sid) throw Error('No active game selected.');
      const id = uuid();
      const payload = {op, request_id:id}; if(args)payload.args=args;
      const out = await api(`/api/sessions/${encodeURIComponent(sid)}/interventions`, payload);
      if (dead) return out;
      const row = out.request;
      if (!row || row.id !== id) throw Error('Invalid intervention receipt.');
      if (terminal.has(row.state)) notify(message({...row,op}), {...row,op,sid});
      else { pending.set(id, {sid, op, at:now()}); wake(); }
      return out;
    }
    return {flash:sid=>send(sid,'flash_now'), equipPrimary:(sid,item)=>send(sid,'equip_primary',{item}),
      poll, dispose() { dead=true; if(timer)cancel(timer); pending.clear(); }};
  }
  function mount(host, options) {
    const doc = host.ownerDocument, bar = doc.createElement('div'); bar.className = 'stream-interventions';
    const button = doc.createElement('button'); button.type='button'; button.textContent='⚡ Instant flashbang';
    const status = doc.createElement('span'); status.setAttribute('role','status');
    bar.append(button, status); host.append(bar);
    let sidebar = null, disposed = false, opening = false;
    const selected = () => typeof options.sid==='function' ? options.sid() : options.sid;
    if (root.GBoxBotLogicSidebar) {
      const controls = doc.createElement('button'); controls.type='button'; controls.textContent='Live controls';
      controls.setAttribute('aria-label','Open active game mods and bot behavior'); bar.insertBefore(controls,status);
      controls.onclick = async () => {
        if (opening || disposed) return; opening=true;
        const sid=selected();
        try {
          const rows=await options.api('/api/sessions?include_ended=false');
          if (disposed || sid!==selected()) return;
          const session=rows.find(row=>row.session_id===sid);
          if (!session || session.state!=='running') throw Error('The selected session is no longer running.');
          activeSidebar?.dispose();
          sidebar=root.GBoxBotLogicSidebar.create({api:options.api,current:selected,doc,compactOnly:false});
          activeSidebar=sidebar;
          sidebar.update({on:true,sid,session}); await sidebar.toggle(true);
        } catch(error) { if(!disposed)status.textContent=error.message; }
        finally { opening=false; }
      };
    }
    let flashControl;
    const client = create({...options, notify(text,row) {
      if(row.op==='flash_now')flashControl?.receipt(text,row);
      else {status.textContent=text; options.notify?.(text,row);}
      options.onReceipt?.(row);
    }});
    const weapon = doc.createElement('button'); weapon.type='button'; weapon.textContent='\u{1F52B} Weapon';
    weapon.setAttribute('aria-label','Choose the primary weapon for this match');
    const choices = doc.createElement('select'); choices.hidden=true; choices.setAttribute('aria-label','Primary weapon');
    bar.insertBefore(weapon,status); bar.insertBefore(choices,status);
    let choicesSid=null, loadingWeapons=false;
    weapon.onclick=async()=>{
      if(disposed || loadingWeapons)return;
      if(!choices.hidden){choices.hidden=true;return;}
      const sid=selected(); if(!sid){status.textContent='No active game selected.';return;}
      loadingWeapons=true;
      try {
        const state=await options.api(`/api/sessions/${encodeURIComponent(sid)}/interventions`);
        if(disposed || sid!==selected())return;
        if(!state.available || !(state.capabilities||[]).includes('equip_primary'))
          throw Error(state.reason || 'Live weapon replacement is not available for this session.');
        choices.replaceChildren();
        const prompt=doc.createElement('option');prompt.textContent='Choose a weapon';prompt.value='';prompt.disabled=true;prompt.selected=true;choices.append(prompt);
        for(const row of state.options?.weapons||[]){const option=doc.createElement('option');option.value=String(row.item);option.textContent=row.weapon;choices.append(option);}
        choicesSid=sid;choices.hidden=false;choices.focus();
      } catch(error){if(!disposed)status.textContent=error.message;}
      finally {loadingWeapons=false;}
    };
    choices.onchange=()=>{
      choices.hidden=true;
      if(disposed || choicesSid!==selected() || !choices.value)return;
      client.equipPrimary(choicesSid,Number(choices.value)).catch(error=>{if(!disposed)status.textContent=error.message;});
    };
    flashControl=bindFlash(button,{flash:client.flash,sid:selected,enabled:()=>!disposed});
    return {dispose() {disposed=true;flashControl.dispose();client.dispose();sidebar?.dispose();if(activeSidebar===sidebar)activeSidebar=null;bar.remove();}, client};
  }
  const out = {create,mount,bindFlash}; root.GBoxStreamInterventions=out;
  if(typeof module==='object' && module.exports)module.exports=out;
})(typeof globalThis==='object'?globalThis:this);
