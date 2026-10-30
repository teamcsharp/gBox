// Shared by desktop PiP, web viewers, and embedders. One UUID per click;
// polling confirms effects without touching the video source or reconnecting it.
(function(root) {
  'use strict';
  const terminal = new Set(['confirmed', 'failed', 'unavailable', 'expired', 'uncertain']);
  let activeSidebar = null;
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
              notify(message({...row, op:row.op || own.op}), row);
            }
          } catch { /* Receipt lookup may retry. The effect request never does. */ }
        }
        for (const [id, row] of pending) if (now() - row.at > 15000) {
          pending.delete(id); notify(`${row.op === 'equip_primary' ? 'Weapon selection' : 'Flashbang'} receipt unavailable. The request will not be repeated.`, {id, state:'uncertain'});
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
      if (terminal.has(row.state)) notify(message({...row,op}), row);
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
    const client = create({...options, notify(text,row) {status.textContent=text; options.notify?.(text,row);}});
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
    button.onclick = () => client.flash(typeof options.sid==='function'?options.sid():options.sid)
      .catch(error => {status.textContent=error.message;});
    return {dispose() {disposed=true;client.dispose();sidebar?.dispose();if(activeSidebar===sidebar)activeSidebar=null;bar.remove();}, client};
  }
  const out = {create,mount}; root.GBoxStreamInterventions=out;
  if(typeof module==='object' && module.exports)module.exports=out;
})(typeof globalThis==='object'?globalThis:this);
