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
      const weapon = row.op === 'equip_primary', ring = row.op === 'grenade_ring', ammo = row.op === 'set_infinite_ammo';
      if (row.state === 'confirmed') {
        if (ammo) return typeof row.result?.enabled==='boolean' ? `Infinite ammo ${row.result.enabled?'on':'off'} confirmed.` : 'Infinite ammo change reported; waiting for live state.';
        if (weapon) return `${row.result?.weapon || 'Primary weapon'} equipped. Held as primary for three minutes.`;
        if (ring) return `${ringKindLabel(row.result?.kind)} ring detonated (${row.result?.detonated ?? row.result?.requested ?? ''} grenades).`;
        return 'Flashbang detonated.';
      }
      const what = weapon ? 'Weapon selection' : ring ? 'Grenade ring' : ammo ? 'Infinite ammo' : 'Flashbang';
      return `${what} ${row.state}: ${row.result?.reason || row.reason || 'no confirmed effect'}`;
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
          pending.delete(id); notify(`${row.op === 'equip_primary' ? 'Weapon selection' : row.op==='set_infinite_ammo'?'Infinite ammo':row.op==='grenade_ring'?'Grenade ring':'Flashbang'} receipt unavailable. The request will not be repeated.`, {id,op:row.op,sid:row.sid,state:'uncertain'});
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
      grenadeRing:(sid,kind)=>send(sid,'grenade_ring',{kind:kind||'flash'}),
      setInfiniteAmmo:(sid,enabled)=>{if(typeof enabled!=='boolean')return Promise.reject(Error('Infinite ammo needs an explicit on/off value.'));return send(sid,'set_infinite_ammo',{enabled});},
      poll, dispose() { dead=true; if(timer)cancel(timer); pending.clear(); }};
  }
  // The grenade ring produces native blasts around the player. The type is
  // chosen beside the button. Each live worker advertises its verified types; older workers default to flash.
  const RING_KIND_KEY='gbox.merc.ringKind.v1';
  const RING_KINDS=[{kind:'flash',label:'Flash',available:true},
    {kind:'hand',label:'Hand',available:false,reason:'Hand-grenade ring not yet verified on this build.'},
    {kind:'incendiary',label:'Incendiary',available:false,reason:'Incendiary-grenade ring not yet verified on this build.'}];
  function ringKindLabel(kind){return (RING_KINDS.find(k=>k.kind===kind)||RING_KINDS[0]).label;}
  function ringKindOptions(report){
    const rows=report?.options?.grenade_kinds;
    const live=!report||(report.available===true&&report.capabilities?.includes('grenade_ring'));
    return RING_KINDS.map(base=>{
      const row=Array.isArray(rows)?rows.find(r=>r?.kind===base.kind):base;
      return {...base,available:!!live&&row?.available===true,
        reason:!live?'The live worker is unavailable.':row?.reason||(row?.available===true?'':'This grenade type is not reported as available.')};
    });
  }
  function readRingKind(storage,choices=RING_KINDS){
    try{const v=storage?.getItem(RING_KIND_KEY); if(choices.some(k=>k.kind===v && k.available))return v;}catch{}
    return choices.find(k=>k.available)?.kind||'flash';
  }
  const ringIcon='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="3.5" r="1.4" fill="currentColor" stroke="none"/><circle cx="20.5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="20.5" r="1.4" fill="currentColor" stroke="none"/><circle cx="3.5" cy="12" r="1.4" fill="currentColor" stroke="none"/></svg>';
  // ringButton fires the ring with the chosen kind; kindButton opens a small chooser (flash preselected, the
  // unverified types disabled). The chosen kind is remembered per viewer like the flash shortcut.
  function bindRing(ringButton,{ring,api,sid,enabled=()=>true,storage,kindButton}={}){
    const doc=ringButton.ownerDocument,win=doc.defaultView;
    if(storage===undefined)try{storage=win.localStorage;}catch{}
    let choices=ringKindOptions(null),kind=readRingKind(storage),menu=null,dead=false,last='',sequence=0,readSequence=0;
    const selected=()=>typeof sid==='function'?sid():sid;
    let scope=selected();
    function sync(){if(scope!==selected()){scope=selected();choices=ringKindOptions(null);kind=readRingKind(storage);last='';close();paint();}}
    const active=()=>{sync();return !dead && enabled() && selected() && ringButton.isConnected;};
    async function load(session){
      if(!api)return choices;
      const seq=++readSequence;
      try{
        const report=await api(`/api/sessions/${encodeURIComponent(session)}/interventions`);
        if(dead||session!==selected())return null;
        const rows=ringKindOptions(report);
        if(seq===readSequence){choices=rows;kind=storage?readRingKind(storage,choices):choices.some(r=>r.kind===kind&&r.available)?kind:readRingKind(null,choices);paint();}
        return rows;
      }catch(error){
        if(dead||session!==selected())return null;
        const rows=ringKindOptions({available:false});
        if(seq===readSequence){choices=rows;last=error.message||'Grenade capabilities could not be read.';paint();}
        return rows;
      }
    }
    function paint(){
      ringButton.title=`Grenade ring (${ringKindLabel(kind)}): native blasts around the player.${last?'\n'+last:''}`;
      ringButton.setAttribute('aria-label',`Grenade ring (${ringKindLabel(kind)})`);
      if(kindButton){kindButton.textContent=ringKindLabel(kind);kindButton.title='Choose the grenade type for the ring';
        kindButton.setAttribute('aria-label',`Grenade ring type: ${ringKindLabel(kind)}`);}
    }
    function receipt(text,row){if(dead || (row?.sid && row.sid!==selected()))return;last=text;ringButton.dataset.ringState=row?.state||'unavailable';paint();}
    function fire(event){
      event?.preventDefault();event?.stopPropagation();
      if(!active())return;
      const session=selected(),seq=++sequence,k=kind;
      receipt('Request sent.',{state:'sending'});
      Promise.resolve().then(async()=>{
        const rows=await load(session);
        if(!rows||session!==selected()||!active())return;
        const row=rows.find(row=>row.kind===k);
        if(!row?.available)throw Error(row?.reason||'This grenade type is not available.');
        return ring(session,k);
      }).then(out=>{
        if(seq===sequence && session===selected() && out?.request)
          receipt(out.request.reason||'',{...out.request,sid:session});
      }).catch(error=>{if(seq===sequence && session===selected())receipt(error.message,{state:'unavailable',sid:session});});
    }
    function close(){menu?.remove();menu=null;kindButton?.setAttribute('aria-expanded','false');}
    function save(value){kind=value;try{storage?.setItem(RING_KIND_KEY,value);}catch{}last='';paint();close();}
    async function chooser(event){
      event?.preventDefault();event?.stopPropagation();close();if(!active())return;
      const session=selected();
      menu=doc.createElement('div');menu.className='ring-kind-menu';menu.setAttribute('role','menu');
      Object.assign(menu.style,{position:'fixed',zIndex:'10000',background:'#1d1d22',color:'#eee',border:'1px solid #666',borderRadius:'6px',padding:'6px',minWidth:'180px',font:'13px sans-serif',webkitAppRegion:'no-drag'});
      const target=menu;
      doc.body.append(menu);
      const loading=doc.createElement('div');loading.textContent='Reading grenade types...';menu.append(loading);
      place();
      if(!await load(session)||dead||target!==menu||session!==selected())return;
      loading.remove();
      for(const row of choices){
        const item=doc.createElement('button');item.type='button';item.setAttribute('role','menuitemradio');
        item.setAttribute('aria-checked',String(row.kind===kind));item.disabled=!row.available;
        item.textContent=row.label+(row.available?'':' (unavailable)');
        item.title=row.reason||'';
        Object.assign(item.style,{display:'block',width:'100%',textAlign:'left',padding:'6px',background:row.kind===kind?'#263647':'transparent',color:row.available?'#fff':'#888',border:'0',cursor:row.available?'pointer':'default'});
        if(row.available)item.onclick=e=>{e.stopPropagation();save(row.kind);};
        menu.append(item);
      }
      place();kindButton?.setAttribute('aria-expanded','true');menu.querySelector('button:not(:disabled)')?.focus();
    }
    function place(){
      const anchor=(kindButton||ringButton).getBoundingClientRect();
      menu.style.left=Math.max(4,Math.min(anchor.left,win.innerWidth-menu.offsetWidth-4))+'px';
      menu.style.top=Math.max(4,Math.min(anchor.bottom+4,win.innerHeight-menu.offsetHeight-4))+'px';
    }
    function outside(e){if(menu && !menu.contains(e.target) && e.target!==kindButton && !kindButton?.contains(e.target))close();}
    function refreshed(){sync();kind=readRingKind(storage,choices);paint();}
    ringButton.addEventListener('click',fire);ringButton.addEventListener('contextmenu',chooser);
    if(kindButton){kindButton.setAttribute('aria-haspopup','menu');kindButton.addEventListener('click',chooser);}
    win.addEventListener('storage',refreshed);doc.addEventListener('pointerdown',outside,true);paint();
    return {receipt,dispose(){dead=true;close();ringButton.removeEventListener('click',fire);ringButton.removeEventListener('contextmenu',chooser);
      if(kindButton)kindButton.removeEventListener('click',chooser);win.removeEventListener('storage',refreshed);doc.removeEventListener('pointerdown',outside,true);}};
  }
  const ammoIcon='<svg width="22" height="16" viewBox="0 0 28 20" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" aria-hidden="true"><path d="M14 10C10 4 7 3 4 5s-3 7 0 10 7 0 10-5 7-7 10-5 3 7 0 10-7 0-10-5Z"/></svg>';
  function ammoView(report,operation,error='') {
    const value=report?.options?.infinite_ammo,live=report?.available===true,known=live&&typeof value?.enabled==='boolean';
    const available=live&&report?.capabilities?.includes('set_infinite_ammo')&&value?.available===true;
    const state=operation?'pending':error?'error':known?'confirmed':report?'unknown':'loading';
    const label=operation?(operation.enabled?'Turning on...':'Turning off...'):known?(value.enabled?'On':'Off'):'Unknown';
    return {state,label,enabled:known?value.enabled:null,disabled:!!operation||!available||!known,
      reason:error||(operation?'Waiting for verified game state.':value?.reason||(!report?'Reading infinite-ammo state...':
        !live?'Live ammo status is unavailable; the last value is not current.':!available?'No verified infinite-ammo control is reported for this session.':!known?'Infinite-ammo state has not been verified.':''))};
  }
  function createAmmoControl({send,sid,changed=()=>{},now=Date.now}) {
    const selected=()=>typeof sid==='function'?sid():sid;
    let session=selected(),report=null,operation=null,error='',dead=false;
    function sync(){if(session!==selected()){session=selected();report=null;operation=null;error='';}}
    function snapshot(){sync();return ammoView(report,operation,error);}
    const emit=()=>{if(!dead)changed(snapshot());};
    function observe(next){sync();if(dead)return;report=next;
      if(operation?.awaiting&&next?.available===true&&next?.options?.infinite_ammo?.enabled===operation.enabled){operation=null;error='';}
      else if(operation?.awaiting&&now()-operation.at>15000){operation=null;error='Ammo change has no verified readback. No request was repeated.';}
      emit();
    }
    function receipt(row){sync();if(dead||!operation||row?.sid!==session||row.op!=='set_infinite_ammo'||(operation.id&&row.id!==operation.id))return;
      if(!terminal.has(row.state))return;
      if(row.state==='confirmed'){
        if(typeof row.result?.enabled==='boolean'&&row.result.enabled===operation.enabled){
          report={...report,options:{...report?.options,infinite_ammo:{...report?.options?.infinite_ammo,enabled:row.result.enabled}}};operation=null;error='';
        }else if(typeof row.result?.enabled==='boolean'){
          report={...report,options:{...report?.options,infinite_ammo:{...report?.options?.infinite_ammo,enabled:row.result.enabled}}};
          operation=null;error='Native readback did not match the requested ammo setting.';
        }else{operation.awaiting=true;operation.id=row.id;}
      }else{operation=null;error=row.result?.reason||row.reason||`Ammo change ${row.state}; no confirmed effect.`;}
      emit();
    }
    async function toggle(){sync();const view=snapshot();if(dead||!session||view.disabled)return;
      const captured=session,own={enabled:!view.enabled,id:null,at:now()};operation=own;error='';emit();
      try{const out=await send(captured,own.enabled);sync();if(dead||session!==captured||operation!==own)return;
        if(!out?.request?.id)throw Error('Invalid ammo change receipt.');
        own.id=out.request.id;receipt({...out.request,op:'set_infinite_ammo',sid:captured});
      }catch(cause){sync();if(!dead&&session===captured&&operation===own){operation=null;error=`Ammo change not confirmed: ${cause.message||'request failed'}. It will not be repeated automatically.`;emit();}}
    }
    return {observe,receipt,toggle,snapshot,dispose(){dead=true;operation=null;}};
  }
  const gunIcon='<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M2 5h19v5h-7l-1 3H9l-2 7H3l3-10H2V5zm8 5-.5 1.5h2L12 10h-2z"/><path d="M4 3h2v2H4zm13 0h2v2h-2z"/></svg>';
  const damageValue=row=>typeof row.damage==='number' && Number.isFinite(row.damage) && row.damage>=0 ? row.damage : null;
  function sortedWeapons(rows) {
    return (rows||[]).filter(r=>Number.isInteger(r.item) && typeof r.weapon==='string').slice().sort((a,b)=>{
      const x=damageValue(a), y=damageValue(b);
      return (x===null)-(y===null) || (y||0)-(x||0) || a.weapon.localeCompare(b.weapon);
    });
  }
  // The picker belongs to the displayed session, never the stream transport.
  // Opening is synchronous; selection posts once and closes without a dialog.
  function bindWeapon(button,{api,equipPrimary,sid,enabled=()=>true,onOpen=()=>{}}) {
    const doc=button.ownerDocument,win=doc.defaultView;
    let menu=null,menuSid=null,dead=false,revision=0,last='',selectedSid=null,refreshTimer=null,paintAmmo=null;
    const ammoClient=create({api,notify:(_text,row)=>ammoControl.receipt(row)});
    const ammoControl=createAmmoControl({send:ammoClient.setInfiniteAmmo,sid,changed:view=>paintAmmo?.(view)});
    const selected=()=>typeof sid==='function'?sid():sid;
    const active=()=>!dead && enabled() && selected() && button.isConnected;
    button.innerHTML=gunIcon;button.setAttribute('aria-haspopup','dialog');
    function paint(){button.title='Choose any weapon. Equip now and keep it for three minutes.'+(last?'\n'+last:'');button.setAttribute('aria-label','Choose primary weapon');}
    function close(){++revision;if(refreshTimer)win.clearTimeout(refreshTimer);refreshTimer=null;paintAmmo=null;menu?.remove();menu=null;menuSid=null;button.setAttribute('aria-expanded','false');onOpen(false);}
    function update(){if(selectedSid!==selected() || !active()){last='';selectedSid=selected();close();delete button.dataset.weaponState;paint();}}
    function receipt(text,row){if(dead || (row?.sid && row.sid!==selected()))return;selectedSid=selected();last=text;button.dataset.weaponState=row?.state||'unavailable';paint();}
    function position(){if(!menu)return;const r=button.getBoundingClientRect();menu.style.left=Math.max(4,Math.min(r.right-menu.offsetWidth,win.innerWidth-menu.offsetWidth-4))+'px';menu.style.top=Math.max(4,Math.min(r.bottom+4,win.innerHeight-menu.offsetHeight-4))+'px';}
    async function open(event){
      event?.preventDefault();event?.stopPropagation();update();
      if(menu){close();return;}if(!active())return;
      const session=selected(),version=++revision;menuSid=session;
      menu=doc.createElement('div');menu.className='merc-weapon-menu';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','Choose primary weapon');
      Object.assign(menu.style,{position:'fixed',zIndex:'10000',width:'350px',maxWidth:'calc(100vw - 8px)',maxHeight:'calc(100vh - 40px)',boxSizing:'border-box',display:'flex',flexDirection:'column',gap:'8px',background:'#1d1d22',color:'#eee',border:'1px solid #666',borderRadius:'7px',padding:'10px',font:'13px sans-serif',webkitAppRegion:'no-drag',boxShadow:'0 6px 24px #0008'});
      const title=doc.createElement('strong');title.textContent='Choose weapon · hold for 3:00';
      const heading=doc.createElement('div');Object.assign(heading.style,{display:'flex',alignItems:'center',justifyContent:'space-between',gap:'8px',flexWrap:'wrap'});
      const ammo=doc.createElement('button');ammo.type='button';ammo.dataset.infiniteAmmo='';
      const ammoLabel=doc.createElement('span');ammo.innerHTML=ammoIcon;ammo.append(ammoLabel);
      Object.assign(ammo.style,{display:'inline-flex',alignItems:'center',gap:'5px',flexShrink:'0',border:'1px solid #69798a',borderRadius:'5px',padding:'5px 8px',background:'#25313f',color:'#eef5ff',cursor:'pointer'});
      heading.append(title,ammo);
      const ammoStatus=doc.createElement('div');ammoStatus.dataset.ammoStatus='';ammoStatus.setAttribute('role','status');Object.assign(ammoStatus.style,{fontSize:'12px',color:'#bbb'});
      const info=doc.createElement('div');info.textContent='Highest damage first';info.style.color='#bbb';
      const search=doc.createElement('input');search.type='search';search.placeholder='Find a weapon';search.setAttribute('aria-label','Find a weapon');
      Object.assign(search.style,{boxSizing:'border-box',width:'100%',padding:'7px',background:'#111',color:'#fff',border:'1px solid #666',borderRadius:'4px'});
      const status=doc.createElement('div');status.setAttribute('role','status');status.textContent='Loading weapons…';
      const list=doc.createElement('div');list.setAttribute('role','group');list.setAttribute('aria-label','Weapons, highest damage first');Object.assign(list.style,{overflowY:'auto',minHeight:'0',overscrollBehavior:'contain'});
      menu.append(heading,ammoStatus,info,search,status,list);doc.body.append(menu);button.setAttribute('aria-expanded','true');onOpen(true);position();search.focus();
      let state=null,signature=null;
      const current=()=>!dead && menu && menuSid===session && session===selected() && version===revision && active();
      paintAmmo=view=>{if(!current())return;ammoLabel.textContent=view.label;ammo.dataset.state=view.state;ammo.disabled=view.disabled;
        ammo.setAttribute('aria-label',`Infinite ammo: ${view.label}${view.enabled===null?'':`. Turn ${view.enabled?'off':'on'}`}`);
        ammo.setAttribute('aria-pressed',view.enabled===null?'mixed':String(view.enabled));ammo.setAttribute('aria-busy',String(view.state==='pending'));
        ammo.title=`Infinite ammo: ${view.label}. ${view.reason}`;ammo.style.borderColor=view.state==='error'?'#dc8e72':view.enabled===true?'#70c698':'#69798a';
        ammo.style.background=view.enabled===true?'#1d4332':'#25313f';ammo.style.cursor=view.disabled?'default':'pointer';
        ammoStatus.textContent=view.reason;ammoStatus.style.color=view.state==='error'?'#ffb49b':'#bbb';};
      ammo.onclick=e=>{e.preventDefault();e.stopPropagation();if(current())ammoControl.toggle();else update();};
      ammoControl.observe(null);
      paintAmmo(ammoControl.snapshot());
      function render(){
        const focus=doc.activeElement?.dataset?.weaponItem,scroll=list.scrollTop;
        list.replaceChildren();
        const available=state.available && (state.capabilities||[]).includes('equip_primary');
        const rows=sortedWeapons(state.options?.weapons),query=search.value.trim().toLocaleLowerCase();
        info.textContent=rows.some(r=>r.damage_basis==='live_level0_firepower')?'Highest damage first · gun firepower at level 0':'Highest damage first';
        const lock=state.options?.primary_weapon;
        if(lock?.locked===true&&Number.isFinite(lock.lock_remaining_s)&&lock.lock_remaining_s>=0){const seconds=Math.ceil(lock.lock_remaining_s);info.textContent+=` | ${lock.weapon||'Selected weapon'} locked ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
        info.title='Gun values include live damage mods. Reference values are unmodified base damage. Actual hits depend on distance, target and ammunition.';
        status.textContent=available ? (rows.length?'':'No weapons reported for this session.') : state.reason||'Live weapon replacement is unavailable for this session.';
        for(const row of rows.filter(r=>!query || r.weapon.toLocaleLowerCase().includes(query))){
          const item=doc.createElement('button');item.type='button';item.dataset.weaponItem=String(row.item);item.disabled=!available || row.available===false;
          const equipped=row.equipped===true || state.options?.current_weapon===row.item;
          item.setAttribute('aria-pressed',String(equipped));
          Object.assign(item.style,{display:'block',width:'100%',textAlign:'left',padding:'9px 8px',margin:'0 0 3px',border:'1px solid '+(equipped?'#75baff':'transparent'),borderRadius:'4px',background:equipped?'#263647':'#292a30',color:item.disabled?'#aaa':'#fff',cursor:item.disabled?'default':'pointer'});
          const name=doc.createElement('div');name.textContent=row.weapon;name.style.fontWeight='600';
          const detail=doc.createElement('div');detail.style.cssText='font-size:11px;color:#bbb;margin-top:3px';
          const damage=damageValue(row);
          detail.textContent=[damage===null?'Damage varies / unmeasured':`Damage ${damage.toLocaleString()}${row.damage_basis==='reference_base_damage'?' (reference)':''}`,equipped?'Equipped · In inventory':row.in_inventory===true?'In inventory':row.in_inventory===false?'Not in inventory':'Inventory not reported',row.available===false?row.reason||'Unavailable now':''].filter(Boolean).join(' · ');
          item.append(name,detail);list.append(item);
          item.onclick=e=>{
            e.preventDefault();e.stopPropagation();if(!current() || item.disabled){update();return;}
            close();receipt(`Equipping ${row.weapon}…`,{state:'sending',sid:session});
            Promise.resolve().then(()=>equipPrimary(session,row.item)).catch(error=>receipt(error.message,{state:'unavailable',sid:session}));
          };
        }
        if(query && !list.childElementCount && rows.length)status.textContent='No matching weapons.';
        list.scrollTop=scroll;
        if(focus)list.querySelector(`[data-weapon-item="${Number(focus)}"]`)?.focus({preventScroll:true});
        position();
      }
      search.oninput=()=>{if(state && current())render();};
      async function refresh(){
        try{const next=await api(`/api/sessions/${encodeURIComponent(session)}/interventions`);if(!current()){update();return;}
          const changed=JSON.stringify([next.available,next.capabilities,next.options,next.reason]);state=next;ammoControl.observe(next);
          if(changed!==signature){signature=changed;render();}}
        catch(error){if(current()){status.textContent=error.message;ammoControl.observe({options:{infinite_ammo:{available:false,enabled:null,reason:'Infinite-ammo status refresh failed. '+error.message}},capabilities:[]});}}
        if(current())refreshTimer=win.setTimeout(refresh,1500);
      }
      await refresh();
    }
    function outside(e){if(menu && !menu.contains(e.target) && !button.contains(e.target))close();}
    function key(e){if(!menu)return;if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close();button.focus();return;}
      if(!menu.contains(e.target))return;
      // Menu typing/navigation must not become remote controller presses.
      e.stopPropagation();
      if(e.type==='keydown' && ['ArrowDown','ArrowUp','Home','End'].includes(e.key) && e.target.tagName!=='INPUT'){
        e.preventDefault();const rows=[...menu.querySelectorAll('[data-weapon-item]:not(:disabled)')],at=rows.indexOf(doc.activeElement);
        rows[e.key==='Home'?0:e.key==='End'?rows.length-1:(at+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length]?.focus();
      }
    }
    button.addEventListener('click',open);doc.addEventListener('pointerdown',outside,true);
    doc.addEventListener('keydown',key);doc.addEventListener('keyup',key);win.addEventListener('resize',position);paint();
    return {receipt,update,close,dispose(){dead=true;ammoControl.dispose();ammoClient.dispose();close();button.removeEventListener('click',open);doc.removeEventListener('pointerdown',outside,true);doc.removeEventListener('keydown',key);doc.removeEventListener('keyup',key);win.removeEventListener('resize',position);}};
  }
  const replayIcon='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20 8a8 8 0 0 0-13-3L3 9m0-6v6h6M4 16a8 8 0 0 0 13 3l4-4m0 6v-6h-6"/></svg>';
  const stageIcon='<svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="m2 4 4 5 4-5z" fill="currentColor"/></svg>';

  // Percentages are a draft until the worker returns its saved configuration.
  function stageWeights(rows, changedId=null, requested=null) {
    const next=rows.map(row=>({...row,weight:row.enabled?Math.max(0,Number(row.weight)||0):0}));
    const enabled=next.filter(row=>row.enabled);
    if(!enabled.length)throw Error('Include at least one stage.');
    const changed=enabled.find(row=>row.id===changedId);
    if(changed && requested!==null){
      changed.weight=enabled.length===1?100:Math.max(0,Math.min(100,Number(requested)||0));
      const rest=enabled.filter(row=>row!==changed),total=rest.reduce((sum,row)=>sum+row.weight,0),remaining=100-changed.weight;
      for(const row of rest)row.weight=total?remaining*row.weight/total:remaining/rest.length;
    }else{
      const total=enabled.reduce((sum,row)=>sum+row.weight,0);
      for(const row of enabled)row.weight=total?100*row.weight/total:100/enabled.length;
    }
    // Largest remainders give readable hundredths and an exact 100.00% total.
    const units=enabled.map(row=>({row,value:Math.floor(row.weight*100+1e-7),fraction:row.weight*100-Math.floor(row.weight*100+1e-7)}));
    let remaining=10000-units.reduce((sum,row)=>sum+row.value,0);
    const order=[...units].sort((a,b)=>b.fraction-a.fraction||a.row.id-b.row.id);
    for(let i=0;remaining>0;i++,remaining--)order[i%order.length].value++;
    for(const row of units)row.row.weight=row.value/100;
    return next;
  }

  function roundReport(value, session) {
    if(!value || value.session_id!==session || typeof value.available!=='boolean')throw Error('Invalid icon panel status for this session.');
    if(value.available && (!Array.isArray(value.stages) || !value.stages.length ||
        value.stages.some(row=>!Number.isInteger(row.id)||typeof row.name!=='string'||typeof row.enabled!=='boolean'||
          !Number.isFinite(row.weight)||row.weight<0||row.weight>100)||
        new Set(value.stages.map(row=>row.id)).size!==value.stages.length || typeof value.loop?.enabled!=='boolean'))
      throw Error('Stage preferences could not be verified.');
    if(value.available && value.current_stage!==null && value.current_stage!==undefined && !Number.isInteger(value.current_stage))
      throw Error('Current stage could not be verified.');
    const quick=value.quick_attack;
    if(quick?.available===true && (typeof quick.enabled!=='boolean'||!Number.isInteger(quick.count)||quick.count<1||quick.count>8||!Number.isFinite(quick.interval_s)||quick.interval_s<8||quick.interval_s>120))
      throw Error('Quick attack preferences could not be verified.');
    return value;
  }

  function createRoundControls({api,sid,changed=()=>{},uuid=()=>root.crypto.randomUUID()}) {
    let report=null,error='',message='',pending=null,dead=false,bound=null,readSequence=0,epoch=0;
    const selected=()=>typeof sid==='function'?sid():sid;
    function sync(){const next=selected();if(next!==bound){bound=next;report=null;error='';message='';pending=null;readSequence++;epoch++;}return bound;}
    function snapshot(){sync();return {sid:bound,report,error,message,pending:pending?{...pending}:null};}
    function emit(){changed(snapshot());}
    function accept(value,session){
      report=roundReport(value,session);
      const receipts=[value.receipt,...(Array.isArray(value.receipts)?value.receipts:[])].filter(Boolean);
      const match=pending && receipts.find(row=>row.request_id===pending.id && ['queued','applied','rejected'].includes(row.status));
      if(match){if(match.status==='rejected'){error=match.error||match.reason||'The worker rejected this request.';message='Request rejected: '+error;}
        else{message=pending.op==='replay'?'Next-round preference '+match.status+'.':'Preferences '+match.status+'.';error='';}pending=null;}
      return match?.status;
    }
    async function refresh(){
      const session=sync(),version=epoch,sequence=++readSequence;if(dead||!session)return;
      try{const value=await api(`/api/sessions/${encodeURIComponent(session)}/rpc`,{op:'merc_round_controls',args:{op:'status'}});
        if(dead||version!==epoch||session!==selected()||sequence!==readSequence)return;
        const receiptStatus=accept(value,session);if(!pending&&receiptStatus!=='rejected')error='';emit();return report;
      }catch(exc){if(!dead&&version===epoch&&session===selected()&&sequence===readSequence){error=exc.message||'Icon panel status could not be read.';emit();}}
    }
    async function mutate(op,args){
      const session=sync();if(dead||!session)throw Error('No active game selected.');
      if(pending)throw Error('The previous request is still pending. Refresh its status before another change.');
      if(report?.available!==true)throw Error(report?.reason||'Round controls are unavailable for this session.');
      const id=uuid(),version=epoch;pending={id,op,state:'sending'};error='';message='Sending request...';readSequence++;emit();
      try{const value=await api(`/api/sessions/${encodeURIComponent(session)}/rpc`,{op:'merc_round_controls',args:{op,request_id:id,...args}});
        if(dead||version!==epoch||session!==selected())return;
        if(pending?.id!==id)return report;
        readSequence++;accept(value,session);
        if(pending){pending.state='uncertain';error='No matching receipt returned. Refresh status; this request will not be repeated.';}
        emit();return report;
      }catch(exc){if(dead||version!==epoch||session!==selected())return;
        if(pending?.id!==id)return report;
        pending.state='uncertain';error=(exc.message||'Request outcome unknown.')+' Refresh status; this request will not be repeated.';emit();}
    }
    return {snapshot,refresh,update(){sync();emit();},
      replay(){return mutate('replay',{mode:'once'});},
      loop(enabled){if(typeof enabled!=='boolean')return Promise.reject(Error('Loop requires an explicit on/off value.'));return mutate('replay',{mode:'loop',enabled});},
      stages(rows){let normalized;try{normalized=stageWeights(rows);}catch(error){return Promise.reject(error);}
        return mutate('stages',{stages:normalized.map(({id,enabled,weight})=>({id,enabled,weight}))});},
      reset(){return mutate('stages',{reset:true});},
      quickAttack(value){if(typeof value.enabled!=='boolean'||!Number.isInteger(value.count)||value.count<1||value.count>8||!Number.isFinite(value.interval_s)||value.interval_s<8||value.interval_s>120)
        return Promise.reject(Error('Quick attacks need 1-8 attacks and an interval of 8-120 seconds.'));
        if(report?.quick_attack?.available!==true)return Promise.reject(Error('Quick attacks are unavailable for this title.'));
        return mutate('quick_attack',{enabled:value.enabled,count:value.count,interval_s:value.interval_s});},
      dispose(){dead=true;epoch++;pending=null;}
    };
  }

  function bindReplayGesture(button,{replay,loop,enabled=()=>true,identity=()=>null,schedule=(fn,ms)=>root.setTimeout(fn,ms),cancel=id=>root.clearTimeout(id)}) {
    let timer=null,point=null,suppress=false,disposed=false,gestureIdentity,hasPointer=false;
    function clear(){if(timer!==null)cancel(timer);timer=null;}
    function down(event){if(event.button!==undefined&&event.button!==0)return;clear();suppress=false;
      if(disposed||!enabled())return;gestureIdentity=identity();hasPointer=true;point={x:event.clientX,y:event.clientY};
      if(!event.ctrlKey)timer=schedule(()=>{timer=null;if(!disposed&&enabled()&&gestureIdentity===identity()){suppress=true;loop();}},600);}
    function move(event){if(point&&Number.isFinite(event.clientX)&&Math.hypot(event.clientX-point.x,event.clientY-point.y)>8)clear();}
    function up(){clear();point=null;}
    function abort(){up();suppress=false;}
    function click(event){event.preventDefault();event.stopPropagation();clear();
      if(disposed||!enabled())return;
      if(event.detail!==0&&hasPointer&&gestureIdentity!==identity()){hasPointer=false;suppress=false;return;}hasPointer=false;
      if(suppress && event.detail!==0){suppress=false;return;}suppress=false;
      if(event.ctrlKey)loop();else replay();}
    function context(event){event.preventDefault();event.stopPropagation();}
    const handlers={pointerdown:down,pointermove:move,pointerup:up,pointercancel:abort,pointerleave:up,click,contextmenu:context};
    for(const [name,fn] of Object.entries(handlers))button.addEventListener(name,fn);
    return {cancelPending(){clear();point=null;suppress=true;},dispose(){disposed=true;clear();for(const [name,fn] of Object.entries(handlers))button.removeEventListener(name,fn);}};
  }

  function bindIconPanel(button,{api,sid,enabled=()=>true,menuButton,onOpen=()=>{}}) {
    const doc=button.ownerDocument,win=doc.defaultView||root;
    let dead=false,menu=null,timer=null,bound=null,menuSid=null,draft=null,dirty=false,localError='',nodes=null,gesture=null,gestureEpoch=0;
    const selected=()=>typeof sid==='function'?sid():sid;
    const active=()=>!dead&&enabled()&&!!selected();
    const stopEvent=e=>{e?.preventDefault();e?.stopPropagation();};
    const styleCheck=(label,input)=>{Object.assign(label.style,{display:'inline-flex',alignItems:'center',gap:'6px',margin:'0',minWidth:'0',font:'inherit',color:'inherit'});Object.assign(input.style,{width:'auto',flex:'0 0 auto',margin:'0'});};
    const styleButton=el=>Object.assign(el.style,{border:'1px solid #647081',borderRadius:'4px',background:'#26313e',color:'#f1f5f9',padding:'5px 8px',cursor:'pointer'});
    button.type='button';button.innerHTML=replayIcon;button.dataset.roundReplay='';
    menuButton.type='button';menuButton.innerHTML=stageIcon;menuButton.dataset.stagePreferences='';
    menuButton.setAttribute('aria-label','Stage choices and quick attacks');menuButton.setAttribute('aria-haspopup','dialog');
    button.style.touchAction='manipulation';button.style.flexShrink='0';menuButton.style.flexShrink='0';
    const state=createRoundControls({api,sid,changed:paint});
    function close(){if(menu){menu.remove();menu=null;nodes=null;menuSid=null;draft=null;dirty=false;onOpen(false);}menuButton.setAttribute('aria-expanded','false');}
    function position(){if(!menu)return;const r=menuButton.getBoundingClientRect();menu.style.left=Math.max(4,Math.min(r.right-menu.offsetWidth,win.innerWidth-menu.offsetWidth-4))+'px';menu.style.top=Math.max(4,Math.min(r.bottom+4,win.innerHeight-menu.offsetHeight-4))+'px';}
    function failure(error){localError=error.message||String(error);paint(state.snapshot());}
    async function action(fn){const session=selected();localError='';try{await fn();}catch(error){if(session===selected())failure(error);}if(!dead)paint(state.snapshot());}
    function paint(view){
      if(dead)return;
      if(bound!==selected()){bound=selected();gestureEpoch++;gesture?.cancelPending();close();localError='';}
      const report=view.report,busy=!!view.pending,available=active()&&report?.available===true;
      button.disabled=!available||busy;menuButton.disabled=!active();
      const looping=report?.loop?.enabled===true;
      button.setAttribute('aria-pressed',String(looping));button.setAttribute('aria-busy',String(busy));
      button.dataset.roundState=busy?'pending':view.error?'error':looping?'loop':report?.replay_pending?'queued':available?'ready':'unavailable';
      button.style.color=localError||view.error?'#ffb49b':looping?'#9dd8ff':report?.replay_pending?'#f4ce7a':'';
      button.style.borderColor=localError||view.error?'#dc8e72':busy?'#d4bb70':looping?'#85bce8':'';
      const loopStage=report?.stages?.find(row=>row.id===report.loop?.stage_id)?.name||'the selected stage';
      const status=localError||view.error||report?.reason||(!available?'Reading round controls...':busy?'Request pending':looping?`Looping ${loopStage} at round boundaries`:report?.replay_pending?'Same stage queued for the next round':view.message);
      button.title=`Replay this stage next round with a different character. Ctrl-click or hold to ${looping?'stop':'start'} looping. ${status||''}`;
      button.setAttribute('aria-label',looping?`Stage loop on: ${loopStage}. Click to replay; Ctrl-click or hold to stop loop`:'Replay stage next round with a different character; Ctrl-click or hold to loop');
      menuButton.title='Stage choices, weights and quick attacks';
      if(!menu||menuSid!==selected())return;
      nodes.status.textContent=status||'Changes apply at the next round boundary.';nodes.status.style.color=localError||view.error?'#ffb49b':'#c9d1db';
      nodes.heading.textContent=report?.title?`${report.title} stages`:'Stage preferences';
      nodes.current.textContent=report?.current_stage===null||report?.current_stage===undefined?'Current stage not yet verified.':`Current stage: ${report.stages?.find(row=>row.id===report.current_stage)?.name||report.current_stage}`;
      nodes.loop.checked=looping;nodes.loopText.textContent=looping?` Loop ${loopStage} after each round`:' Loop the current stage each round';nodes.loop.disabled=!available||busy;nodes.refresh.disabled=busy&&view.pending?.state==='sending';
      if(!report?.stages){nodes.list.replaceChildren();return;}
      if(!dirty){draft=report.stages.map(row=>({...row}));}
      const signature=JSON.stringify(draft.map(row=>[row.id,row.name]));
      if(signature!==nodes.signature){nodes.signature=signature;nodes.list.replaceChildren();nodes.rows=new Map();const owner=menu;
        for(const row of draft){const wrap=doc.createElement('div');Object.assign(wrap.style,{display:'grid',gridTemplateColumns:'minmax(0,1.1fr) minmax(0,1fr) 48px',gap:'6px',alignItems:'center',padding:'6px 0'});
          const label=doc.createElement('label'),check=doc.createElement('input');check.type='checkbox';const name=doc.createElement('span');name.textContent=row.name;name.style.overflowWrap='anywhere';label.append(check,name);styleCheck(label,check);
          const slider=doc.createElement('input');slider.type='range';slider.min='0';slider.max='100';slider.step='1';slider.setAttribute('aria-label',`${row.name} stage probability`);Object.assign(slider.style,{width:'100%',minWidth:'0',margin:'0'});
          const amount=doc.createElement('output');amount.style.textAlign='right';wrap.append(label,slider,amount);nodes.list.append(wrap);nodes.rows.set(row.id,{check,slider,amount});
          check.onchange=()=>{if(menu!==owner)return;edit(()=>{const next=draft.map(r=>r.id===row.id?{...r,enabled:check.checked,weight:check.checked?(r.weight||100/draft.length):0}:r);return stageWeights(next);});};
          slider.oninput=()=>{if(menu===owner)edit(()=>stageWeights(draft,row.id,Number(slider.value)));};
        }
      }
      for(const row of draft){const item=nodes.rows.get(row.id);item.check.checked=row.enabled;item.check.disabled=!available||busy;item.slider.disabled=!available||busy||!row.enabled;item.slider.value=String(row.weight);item.amount.textContent=row.weight.toFixed(2).replace(/\.00$/,'')+'%';}
      nodes.apply.disabled=!available||busy||!dirty;nodes.invert.disabled=!available||busy;nodes.reset.disabled=!available||busy;nodes.unsaved.textContent=dirty?'Unsaved stage choices. Total: 100%.':'';
      const quick=report.quick_attack;nodes.quick.hidden=!quick?.available;
      if(quick?.available){if(doc.activeElement!==nodes.count)nodes.count.value=String(quick.count);if(doc.activeElement!==nodes.interval)nodes.interval.value=String(quick.interval_s);nodes.quickOn.checked=quick.enabled===true;
        nodes.intervalText.textContent=`Every ${Number(nodes.interval.value)} seconds`;
        nodes.quickOn.disabled=nodes.count.disabled=nodes.interval.disabled=!available||busy;}
      position();
    }
    function edit(fn){if(!menu||menuSid!==selected()||!active())return;try{draft=fn();dirty=true;localError='';}catch(error){localError=error.message;}paint(state.snapshot());}
    function toggleLoop(){const report=state.snapshot().report;if(report?.available)action(()=>state.loop(!report.loop.enabled));}
    gesture=bindReplayGesture(button,{identity:()=>selected()+':'+gestureEpoch,enabled:()=>active()&&!button.disabled,replay:()=>action(()=>state.replay()),loop:toggleLoop});
    function quickSave(){return action(()=>state.quickAttack({enabled:nodes.quickOn.checked,count:Number(nodes.count.value),interval_s:Number(nodes.interval.value)}));}
    function open(event){stopEvent(event);if(menu){close();return;}if(!active())return;menuSid=selected();
      menu=doc.createElement('div');menu.className='merc-round-menu';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','Icon panel stage preferences');
      const owned=menu,session=menuSid,isCurrent=()=>menu===owned&&menuSid===session&&session===selected()&&active();
      Object.assign(menu.style,{position:'fixed',zIndex:'10000',width:'390px',maxWidth:'calc(100vw - 8px)',maxHeight:'calc(100vh - 36px)',overflowY:'auto',boxSizing:'border-box',background:'#1b2027',color:'#edf1f5',border:'1px solid #627083',borderRadius:'7px',padding:'10px',font:'12px system-ui',webkitAppRegion:'no-drag',boxShadow:'0 6px 24px #0009'});
      const heading=doc.createElement('strong'),current=doc.createElement('div'),note=doc.createElement('p'),status=doc.createElement('div');status.setAttribute('role','status');note.textContent='Replay uses a different character on the same stage next round. Stage preferences never reset the current fight.';note.style.color='#c0cad6';
      const loopLabel=doc.createElement('label'),loop=doc.createElement('input'),loopText=doc.createElement('span');loop.type='checkbox';loopText.textContent=' Loop the current stage each round';loopLabel.append(loop,loopText);styleCheck(loopLabel,loop);loopLabel.style.margin='8px 0';loop.onchange=()=>{if(isCurrent())return action(()=>state.loop(loop.checked));};
      const list=doc.createElement('div');list.setAttribute('role','group');list.setAttribute('aria-label','Included stages and selection probabilities');
      const actions=doc.createElement('div');Object.assign(actions.style,{display:'flex',gap:'6px',flexWrap:'wrap',margin:'8px 0'});
      const invert=doc.createElement('button'),reset=doc.createElement('button'),apply=doc.createElement('button'),refresh=doc.createElement('button');
      for(const [el,text] of [[invert,'Invert'],[reset,'Reset defaults'],[apply,'Apply stages'],[refresh,'Refresh']]){el.type='button';el.textContent=text;styleButton(el);actions.append(el);}
      invert.onclick=()=>{if(isCurrent())edit(()=>stageWeights(draft.map(row=>({...row,enabled:!row.enabled,weight:row.enabled?0:1}))));};
      reset.onclick=()=>{if(isCurrent())return action(async()=>{await state.reset();if(isCurrent()&&!state.snapshot().pending&&!state.snapshot().error){dirty=false;draft=null;}});};
      apply.onclick=()=>{if(isCurrent())return action(async()=>{await state.stages(draft);if(isCurrent()&&!state.snapshot().pending&&!state.snapshot().error){dirty=false;draft=null;}});};refresh.onclick=()=>{if(isCurrent())return state.refresh();};
      const unsaved=doc.createElement('div');unsaved.style.color='#edcf8c';
      const quick=doc.createElement('fieldset');quick.style.margin='10px 0 0';const legend=doc.createElement('legend');legend.textContent='RE6 quick attacks';quick.append(legend);
      const quickLabel=doc.createElement('label'),quickOn=doc.createElement('input');quickOn.type='checkbox';quickLabel.append(quickOn,doc.createTextNode('Enable quick attacks'));styleCheck(quickLabel,quickOn);quick.append(quickLabel);
      const countLabel=doc.createElement('label');countLabel.textContent=' Attacks per burst ';const count=doc.createElement('select');count.setAttribute('aria-label','Quick attacks per burst');for(let i=1;i<=8;i++){const option=doc.createElement('option');option.value=String(i);option.textContent=String(i);count.append(option);}count.value='4';countLabel.append(count);Object.assign(countLabel.style,{display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:'6px',margin:'8px 0',font:'inherit',color:'inherit'});count.style.width='60px';quick.append(countLabel);
      const intervalLabel=doc.createElement('label'),interval=doc.createElement('input'),intervalText=doc.createElement('span');interval.type='range';interval.min='8';interval.max='120';interval.step='1';interval.value='24';interval.setAttribute('aria-label','Quick attack interval in seconds');interval.style.width='100%';intervalLabel.append(intervalText,interval);quick.append(intervalLabel);interval.oninput=()=>{intervalText.textContent=`Every ${interval.value} seconds`;};interval.onchange=count.onchange=quickOn.onchange=()=>{if(isCurrent())return quickSave();};
      nodes={heading,current,status,loop,loopText,list,apply,invert,reset,refresh,unsaved,quick,quickOn,count,interval,intervalText,rows:new Map(),signature:null};
      menu.append(heading,current,note,loopLabel,list,unsaved,actions,quick,status);doc.body.append(menu);menuButton.setAttribute('aria-expanded','true');onOpen(true);paint(state.snapshot());position();menu.tabIndex=-1;menu.focus({preventScroll:true});state.refresh();
    }
    function outside(event){if(menu&&!menu.contains(event.target)&&!button.contains(event.target)&&!menuButton.contains(event.target))close();}
    function key(event){if(!menu)return;if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();menuButton.focus();return;}if(menu.contains(event.target))event.stopPropagation();}
    async function poll(){timer=null;if(dead)return;if(active())await state.refresh();if(!dead)timer=win.setTimeout(poll,5000);}
    menuButton.addEventListener('click',open);doc.addEventListener('pointerdown',outside,true);doc.addEventListener('keydown',key);doc.addEventListener('keyup',key);win.addEventListener('resize',position);
    paint(state.snapshot());poll();
    return {close,update(){const next=selected(),changed=next!==bound;state.update();if(!active())close();if(changed&&active())state.refresh();},dispose(){dead=true;close();gesture.dispose();state.dispose();if(timer!==null)win.clearTimeout(timer);menuButton.removeEventListener('click',open);doc.removeEventListener('pointerdown',outside,true);doc.removeEventListener('keydown',key);doc.removeEventListener('keyup',key);win.removeEventListener('resize',position);}};
  }

  function mount(host, options) {
    const doc = host.ownerDocument, bar = doc.createElement('div'); bar.className = 'stream-interventions';
    bar.setAttribute('role','toolbar');bar.setAttribute('aria-label','Icon panel');
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
    let flashControl,weaponControl,ringControl,iconPanel;
    const client = create({...options, notify(text,row) {
      if(row.op==='flash_now')flashControl?.receipt(text,row);
      else if(row.op==='equip_primary')weaponControl?.receipt(text,row);
      else if(row.op==='grenade_ring')ringControl?.receipt(text,row);
      else {status.textContent=text; options.notify?.(text,row);}
      options.onReceipt?.(row);
    }});
    const replay = doc.createElement('button'), stages = doc.createElement('button');bar.insertBefore(replay,button);bar.insertBefore(stages,button);
    iconPanel=bindIconPanel(replay,{api:options.api,sid:selected,enabled:()=>!disposed,menuButton:stages});
    const weapon = doc.createElement('button'); weapon.type='button';bar.insertBefore(weapon,status);
    weaponControl=bindWeapon(weapon,{api:options.api,equipPrimary:client.equipPrimary,sid:selected,enabled:()=>!disposed});
    flashControl=bindFlash(button,{flash:client.flash,sid:selected,enabled:()=>!disposed});
    // The grenade ring sits beside the flash button, with its own small type chooser.
    const ring = doc.createElement('button'); ring.type='button'; ring.innerHTML=ringIcon;
    const ringKind = doc.createElement('button'); ringKind.type='button'; ringKind.className='ring-kind';
    bar.insertBefore(ring,status); bar.insertBefore(ringKind,status);
    ringControl=bindRing(ring,{api:options.api,ring:client.grenadeRing,sid:selected,enabled:()=>!disposed,kindButton:ringKind});
    return {dispose() {disposed=true;iconPanel.dispose();flashControl.dispose();weaponControl.dispose();ringControl.dispose();client.dispose();sidebar?.dispose();if(activeSidebar===sidebar)activeSidebar=null;bar.remove();}, client};
  }
  const out = {create,mount,bindFlash,bindWeapon,bindRing,bindIconPanel,bindReplayGesture,createRoundControls,stageWeights,roundReport,ammoView,createAmmoControl,sortedWeapons,RING_KINDS,ringKindLabel,readRingKind,ringKindOptions}; root.GBoxStreamInterventions=out;
  if(typeof module==='object' && module.exports)module.exports=out;
})(typeof globalThis==='object'?globalThis:this);
