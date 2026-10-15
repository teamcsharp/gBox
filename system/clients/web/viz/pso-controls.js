/* Shared PSO panel: desktop item window and web session sidebar. All writes stay pinned to the selected session. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.GBoxPSO = factory();
})(typeof window === "undefined" ? globalThis : window, function () {
  "use strict";
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isPSO = title => /phantasy\s*star\s*online/i.test(title || "") && !/episode\s*(iii|3)/i.test(title || "");
  function filterItems(items, { query = "", category = "Weapons", rare = false, characterClass = "" } = {}) {
    const q = query.trim().toLowerCase();
    return items.filter(i => (!category || i.cat === category) && (!q || `${i.name} ${i.code}`.toLowerCase().includes(q))
      && (!rare || i.rare) && (!characterClass || !i.classes || i.classes.includes(characterClass)))
      .sort((a, b) => (b.stars || 0) - (a.stars || 0) || a.name.localeCompare(b.name));
  }
  function mount(host, io, session) {
    const sid = session.sid, token = {};
    const command = (op, args = {}) => {
      const bytes = new Uint8Array(16); globalThis.crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const h = [...bytes].map(v => v.toString(16).padStart(2, '0')).join('');
      const command_id = `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
      // A timeout is never retried: the game may already have applied this exact command.
      return io.api(`/api/sessions/${encodeURIComponent(sid)}/rpc`, {op: 'pso_controls',
        args: {command_id, expires: Date.now()/1000 + 8, input: {session_id: sid, op, ...args}}});
    };
    host._psoMount = token;
    const current = () => host.isConnected && host._psoMount === token;
    host.dataset.psoSid = sid;
    let cap, items = [], busy = false, ready = false, prefsReady = false, loading = false, checking = false, loadId = 0, selected = new Set();
    let magId = null, magTimer = null, modeTimer = null, magPatch = {};
    let lootTimer = null, lootDirty = false, selectionTouched = false, bossesReady = false, lastTravel = '';
    const q = sel => host.querySelector(sel);
    host.innerHTML = `<style>
      .pso-controls {font-size:12px;min-width:0}.pso-controls fieldset{border:1px solid var(--line,#35353f);border-radius:6px;margin:8px 0;padding:8px;min-width:0}
      .pso-controls legend{font-weight:600}.pso-controls label{display:flex;align-items:center;gap:6px;margin:6px 0}.pso-controls input[type=range]{min-width:50px;flex:1}
      .pso-controls input[type=search],.pso-controls select{max-width:100%;min-width:0}.pso-controls .pso-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
      .pso-controls .pso-items{max-height:240px;overflow:auto;border-top:1px solid var(--line,#35353f);margin:6px 0}
      .pso-controls .pso-item{display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid var(--line,#35353f)}
      .pso-controls .pso-item span{flex:1;overflow-wrap:anywhere}.pso-controls small{color:var(--mut,#aaa);display:block;font-size:11px}
      .pso-controls .pso-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.pso-controls .pso-stat input{width:64px}
      .pso-controls [role=status]{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}.pso-controls button{cursor:pointer}
    </style><div class="pso-controls">
      <p class="mut" data-profile>Checking the running game's version…</p>
      <fieldset data-controls disabled><legend>Item database</legend>
        <input type="search" data-search placeholder="Search the disc's item database" aria-label="Search PSO items">
        <div class="pso-row"><select data-category aria-label="Item category">${["Weapons", "Armor", "Mags", "Tools"].map(x => `<option>${x}</option>`).join("")}</select>
        <label><input type="checkbox" data-rare> Rares only</label></div>
        <label>Class <select data-class aria-label="Character class"><option value="">Choose your class</option></select></label>
        <div class="pso-items" data-items></div><small data-total></small>
      </fieldset>
      <p data-live-reason></p>
      <fieldset data-spawn disabled><legend>Items on the ground</legend>
        <label>Count <input type="range" data-count min="1" max="20" value="10"><output data-count-value>10</output></label>
        <label>Spread <input type="range" data-radius min="5" max="100" value="18"><output data-radius-value>18</output></label>
        <label><input type="checkbox" data-grind checked> Maximum weapon grind</label>
        <label><input type="checkbox" data-highest checked> Highest rarity tier for my class</label>
        <div class="pso-row"><button class="act" data-drop disabled>Drop selected</button><button class="act pri" data-random disabled>Scatter class rares</button>
          <button class="act" data-clear>Clear gBox drops</button><button class="act" data-give>Add selected to inventory</button></div>
        <small>Selected items drop beside you now. Class rares use the disc's class flags and star ratings. Stat requirements are separate from class eligibility.</small>
      </fieldset>
      <fieldset data-enemy disabled><legend>Enemy drops</legend>
        <label><input type="checkbox" data-enemy-on> Enemies drop selected items</label>
        <small data-enemy-pool>Choose up to 20 items in the database above.</small>
        <small>Changes to your selection and Maximum weapon grind apply while enabled. One item per enemy drop event, cycling through your pool. Boxes stay unchanged. Count and Spread above are for manual scattering.</small>
        <small>Saved for supported current and future custom builds.</small>
      </fieldset>
      <fieldset data-travel disabled><legend>Doors and boss travel</legend>
        <label><input type="checkbox" data-walk> Walk through doors, obstacles and laser barriers</label>
        <small>Collision bypass, saved for supported custom builds. Turn off to restore normal collision. Stay on the map; this does not grant invulnerability.</small>
        <label>Boss <select data-boss aria-label="Boss destination"><option value="">Loading current episode…</option></select></label>
        <button class="act" data-boss-warp disabled>Teleport straight to boss</button>
        <small>Uses the game's area-loading path in your current episode. Changes the area immediately; difficulty and inventory are retained.</small>
      </fieldset>
      <fieldset data-defaults disabled><legend>Equipment default</legend>
        <label><input type="checkbox" data-equip> Default: equip any weapon</label>
        <small data-preferences>Shared default for supported current and future builds on your PCs. This does not enable patches on an unsupported revision.</small>
      </fieldset>
      <fieldset data-live disabled><legend>Live equipment and stats</legend>
        <div class="pso-row"><button class="act" data-inventory>Refresh equipment</button></div><div data-inventory-list></div>
        <small data-multi-note></small><div class="pso-stats">${["atp", "mst", "evp", "hp", "dfp", "ata", "lck"].map(x =>
          `<label class="pso-stat" data-stat="${x}" title="Right-click to edit ${x.toUpperCase()}">${x.toUpperCase()} <input type="number" min="0" max="9999" value="900" aria-label="${x.toUpperCase()}"><button class="act" data-set="${x}">Set</button></label>`).join("")}</div>
        <small>Right-click a stat to focus its live editor. Values are bounded by the game's native stat format (0–9999).</small>
      </fieldset>
      <fieldset data-survival disabled><legend>Survival and difficulty</legend>
        <label><input type="checkbox" data-scape> Permanent Scape Doll</label>
        <button class="act" data-revive>Revive now</button>
        <small>Offline native auto-revival without consuming a Doll or using an inventory slot. Saved as a default for supported GameCube builds.</small>
        <label><input type="checkbox" data-legendary> Legendary: start in Ultimate</label>
        <small>Uses the next offline game's Ultimate difficulty. Return to the game's difficulty selection or relaunch; a loaded area's enemies are unchanged.</small>
      </fieldset>
      <fieldset data-randomized disabled><legend>Randomized</legend>
        <label><input type="checkbox" data-randomized-on> Cycle equipped rares</label>
        <label>Every <input type="range" data-interval min="5" max="300" step="5" value="15"><output data-interval-value>15 s</output></label>
        <div class="pso-row">${['weapon','armor','shield','mag'].map(k=>`<label><input type="checkbox" data-random-kind="${k}" ${k==='weapon'?'checked':''}> ${k}</label>`).join('')}</div>
        <button class="act" data-apply-randomized>Apply Randomized settings</button>
        <small data-mode-state>Stopped. Choose your class above. Needs one free inventory slot; retains your original equipment and removes only its own previous generated gear.</small>
      </fieldset>
      <fieldset data-mag disabled><legend>Equipped MAG</legend>
        <button class="act" data-read-mag>Read equipped MAG</button><small data-mag-summary>Equip a MAG, then read its current properties.</small>
        <fieldset data-mag-values disabled><legend>Live properties</legend>
          ${['def','pow','dex','mind','iq','synchro','color'].map(k=>`<label>${k.toUpperCase()} <input type="number" data-mag-property="${k}" min="0" max="${k==='synchro'?120:k==='color'?18:200}" step="${['def','pow','dex','mind'].includes(k)?'.01':'1'}" value="0"></label>`).join('')}
          <label>Evolution form <select data-mag-property="form" aria-label="MAG evolution form"></select></label>
          <small>Changes apply after you finish adjusting. Total stat level is limited to 200. Native evolution/food rules still apply; Photon Blasts are retained.</small>
          <label>Food <select data-mag-food>${[['030000','Monomate'],['030001','Dimate'],['030002','Trimate'],['030100','Monofluid'],['030101','Difluid'],['030102','Trifluid'],['030300','Antidote'],['030400','Antiparalysis'],['030500','Sol Atomizer'],['030600','Moon Atomizer'],['030700','Star Atomizer']].map(([v,n])=>`<option value="${v}">${n}</option>`).join('')}</select></label>
          <button class="act" data-feed-mag>Feed MAG</button><small>Panel feeding applies native food effects and evolution without consuming inventory food.</small>
        </fieldset>
      </fieldset>
      <p role="status" aria-live="polite" data-status>Loading PSO controls…</p>
      <button type="button" class="act" data-retry>Retry loading</button>
      <details><summary>Character, NPC and area support</summary><div data-pending></div>
        <small>Imported wardrobe cycling, NPC replacement/movement, teleporter unlocks, and automatic Ghidra parameter identification still need native implementation and gameplay verification.</small></details>
    </div>`;
    const say = text => { if (current()) q("[data-status]").textContent = text; };
    function enabled() {
      if (!current()) return;
      q("[data-controls]").disabled = !ready;
      q("[data-spawn]").disabled = busy || checking || !ready || !cap?.supported;
      q("[data-live]").disabled = busy || checking || !cap?.supported;
      q("[data-defaults]").disabled = busy || checking || !prefsReady;
      q("[data-retry]").disabled = busy || loading;
      q("[data-drop]").disabled = busy || checking || !ready || !cap?.supported || !selected.size;
      q("[data-random]").disabled = busy || checking || !ready || !cap?.supported || !q("[data-class]").value;
      // Browsing is independent of revision support for native actions.
      q("[data-clear]").disabled = busy || checking || !ready || !cap?.supported;
      q("[data-give]").disabled = busy || checking || !ready || !cap?.supported || selected.size !== 1;
      for (const [name,feature] of [['survival','survival'],['randomized','randomized'],['mag','mag']])
        q(`[data-${name}]`).disabled=busy || checking || !cap?.supported || !cap?.features?.[feature];
      q('[data-scape]').disabled=!prefsReady;
      q('[data-legendary]').disabled=!prefsReady;
      q('[data-mag-values]').disabled=magId===null;
      q('[data-enemy]').disabled=busy || checking || !ready || !prefsReady || !cap?.features?.enemy_drops;
      q('[data-travel]').disabled=busy || checking || !cap?.supported;
      q('[data-walk]').disabled=!prefsReady || !cap?.features?.walk_through;
      q('[data-boss-warp]').disabled=busy || checking || !bossesReady || !cap?.features?.boss_warp;
    }
    async function run(op, args = {}) {
      if (!current() || busy || checking) return;
      if (!cap?.supported) { say(cap?.reason || "Live actions are not available for this game revision."); return; }
      busy = true; enabled(); say("Applying " + op.replace(/_/g, " ") + "…");
      try {
        const r = await command(op, args);
        if (r.verified === false) throw new Error(r.message || (r.spawned != null
          ? `Only ${r.spawned} / ${r.codes.length} floor items were verified. Check the ground before retrying.`
          : "The game did not verify this change."));
        if (current()) {
          say(r.spawned != null ? `${r.spawned} / ${r.codes.length} items created on the ground.`
            : r.removed != null ? `Removed ${r.removed} gBox floor items.`
            : r.shown_now != null ? `${r.stat.toUpperCase()}: ${r.shown_now}`
            : r.created != null ? `${r.created} items added to inventory.`
            : r.message || `${op.replace(/_/g, " ")} applied.`);
          if (r.elapsed_ms != null) q('[data-status]').textContent += ` (${Math.round(r.elapsed_ms)} ms on worker)`;
        }
        return r;
      } catch (e) { say(e.message); return null; }
      finally { busy = false; enabled(); }
    }
    function render() {
      if (!current()) return;
      const rows = filterItems(items, { query: q("[data-search]").value, category: q("[data-category]").value,
        rare: q("[data-rare]").checked, characterClass: q("[data-class]").value });
      q("[data-total]").textContent = `${rows.length} matches · ${selected.size} selected (up to 20)`;
      q("[data-items]").innerHTML = rows.slice(0, 160).map(i => `<label class="pso-item"><input type="checkbox" data-code="${esc(i.code)}" ${selected.has(i.code) ? "checked" : ""}>
        <span>${esc(i.name)}<small>${i.stars} stars · ${esc(i.code)}${i.max_grind != null ? ` · grind +${i.max_grind}` : ""}
        ${i.atp_required != null ? ` · ATP ${i.atp_required} / MST ${i.mst_required} / ATA ${i.ata_required}` : ""}</small></span></label>`).join("") || "No matching items.";
      q('[data-enemy-pool]').textContent=selected.size ? `Enemy pool: ${[...selected].map(c=>items.find(i=>i.code===c)?.name||c).join(', ')}` : 'Choose up to 20 items in the database above.';
      enabled();
    }
    for (const attr of ["search", "category", "rare", "class"]) q(`[data-${attr}]`).addEventListener(attr === "search" ? "input" : "change", render);
    for (const attr of ["count", "radius"]) q(`[data-${attr}]`).oninput = () => q(`[data-${attr}-value]`).value = q(`[data-${attr}]`).value;
    q("[data-items]").onchange = e => {
      const code = e.target.dataset.code; if (!code) return;
      if (e.target.checked && selected.size >= 20) { e.target.checked = false; say("Select up to 20 items per drop."); return; }
      selectionTouched = true;
      e.target.checked ? selected.add(code) : selected.delete(code); render();
      if(q('[data-enemy-on]').checked) scheduleLoot();
    };
    function scheduleLoot() {
      lootDirty=true;clearTimeout(lootTimer);lootTimer=setTimeout(applyLoot,350);
    }
    async function applyLoot() {
      if(!current() || !lootDirty || !prefsReady || !cap?.features?.enemy_drops)return;
      if(busy || checking){lootTimer=setTimeout(applyLoot,150);return;}
      lootDirty=false;
      const on=q('[data-enemy-on]').checked;
      if(on && !selected.size){q('[data-enemy-on]').checked=false;say('Select items before enabling enemy drops.');}
      const want=on && !!selected.size,codes=[...selected],max_grind=q('[data-grind]').checked;
      busy=true;enabled();
      try {await io.api('/api/pso/preferences',{enemy_drops:want,enemy_codes:codes,enemy_max_grind:max_grind});}
      catch(error){say('Enemy drop settings were not saved: '+error.message);busy=false;enabled();return;}
      busy=false;
      if(current())await run('enemy_drops',{on:want,codes,max_grind});
    }
    q('[data-enemy-on]').onchange=scheduleLoot;
    q('[data-grind]').onchange=()=>{if(q('[data-enemy-on]').checked)scheduleLoot();};
    q('[data-walk]').onchange=async e=>{
      if(busy || checking || !prefsReady)return;
      const on=e.target.checked;busy=true;enabled();
      try {await io.api('/api/pso/preferences',{walk_through:on});}
      catch(error){e.target.checked=!on;say(error.message);busy=false;enabled();return;}
      busy=false;if(current())await run('walk_through',{on});
    };
    q('[data-boss-warp]').onclick=()=>run('boss_warp',{target:q('[data-boss]').value});
    const spawnArgs = () => ({ count: +q("[data-count]").value, radius: +q("[data-radius]").value, max_grind: q("[data-grind]").checked });
    q("[data-drop]").onclick = () => run("floor_spawn", { ...spawnArgs(), codes: [...selected] });
    q("[data-random]").onclick = () => run("floor_rares", { ...spawnArgs(), character_class: q("[data-class]").value, highest: q("[data-highest]").checked });
    q("[data-clear]").onclick = () => run("floor_clear", { on: false });
    q("[data-give]").onclick = () => run("give", {code: [...selected][0], count: +q('[data-count]').value});
    q("[data-equip]").onchange = async e => {
      if (!current() || busy || checking || !prefsReady) return;
      const on = e.target.checked; busy = true; enabled();
      try { await io.api("/api/pso/preferences", { equip_any: on }); }
      catch (err) { e.target.checked = !on; say("Could not save the equipment default. Retry loading after the backend refresh."); busy = false; enabled(); return; }
      busy = false;
      if (!current()) return;
      if (cap?.supported) await run("equip_any", { on });
      else say("Equipment default saved for supported builds. It cannot be applied to this GameCube revision yet.");
      enabled();
    };
    q("[data-inventory]").onclick = async () => {
      const r = await run("list"); if (!r || !current()) return;
      q("[data-inventory-list]").innerHTML = (r.inventory || []).filter(i => i.code.startsWith("00")).map(i =>
        `<div class="pso-row"><span>${esc(i.name)}${i.equipped ? " · equipped" : ""}</span>
        <button class="act" data-multi="${i.slot}" data-on="true">Stack equip</button><button class="act" data-multi="${i.slot}" data-on="false">Unstack</button></div>`).join("") || "No weapons in inventory.";
    };
    q("[data-inventory-list]").onclick = e => { const b = e.target.closest("[data-multi]"); if (b) run("multi_equip", { target: b.dataset.multi, on: b.dataset.on === "true" }); };
    q("[data-live]").addEventListener("click", e => { const b = e.target.closest("[data-set]"); if (!b) return;
      const input = b.parentElement.querySelector("input"), value = +input.value;
      if (!Number.isInteger(value) || value < 0 || value > 9999) return say("Enter a whole number from 0 to 9999.");
      run("stat", { name: b.dataset.set, value });
    });
    q("[data-live]").oncontextmenu = e => { const row = e.target.closest("[data-stat]"); if (!row) return;
      e.preventDefault(); const input = row.querySelector("input"); input.focus(); input.select(); };
    function showMag(result) {
      if (!result?.mag || !current()) return;
      const m=result.mag;magId=m.id;
      q('[data-mag-summary]').textContent=`Level ${m.level} · evolution stage ${m.stage} · item ${m.id}`;
      q('[data-mag-property="form"]').innerHTML=items.filter(i=>i.cat==='Mags'&&parseInt(i.code.slice(2,4),16)<=66)
        .map(i=>`<option value="${parseInt(i.code.slice(2,4),16)}">${esc(i.name)}</option>`).join('');
      host.querySelectorAll('[data-mag-property]').forEach(el=>{el.value=m[el.dataset.magProperty];});enabled();
    }
    async function flushMag() {
      clearTimeout(magTimer);
      if (!current() || magId===null || !Object.keys(magPatch).length) return;
      if (busy) {magTimer=setTimeout(flushMag,150);return;}
      const properties=magPatch;magPatch={};
      showMag(await run('mag_set',{item_id:magId,properties}));
    }
    q('[data-mag-values]').addEventListener('input',e=>{
      const name=e.target.dataset.magProperty;if(!name)return;
      if (!e.target.checkValidity()) return;
      magPatch[name]=+e.target.value;clearTimeout(magTimer);magTimer=setTimeout(flushMag,350);
    });
    q('[data-read-mag]').onclick=async()=>{magPatch={};clearTimeout(magTimer);showMag(await run('mag'));};
    q('[data-feed-mag]').onclick=async()=>{await flushMag();if(Object.keys(magPatch).length)return;showMag(await run('mag_feed',{item_id:magId,code:q('[data-mag-food]').value}));};
    q('[data-revive]').onclick=()=>run('revive');
    for (const [attr,name] of [['scape','permanent_scape'],['legendary','legendary']]) q(`[data-${attr}]`).onchange=async e=>{
      const on=e.target.checked;
      try {await io.api('/api/pso/preferences',{[name]:on});}
      catch(error){e.target.checked=!on;say(error.message);return;}
      const result=await run(name==='permanent_scape'?'survival':'legendary',{on});
      if(name==='legendary'&&result)say(on?'Legendary default saved. Return to difficulty selection or relaunch to start Ultimate; the loaded area is unchanged.':'Normal difficulty selection restored.');
    };
    const randomizedArgs=()=>({on:q('[data-randomized-on]').checked,interval:+q('[data-interval]').value,
      categories:[...host.querySelectorAll('[data-random-kind]:checked')].map(el=>el.dataset.randomKind),character_class:q('[data-class]').value});
    const showModes=r=>{if(r&&current()){
      q('[data-mode-state]').textContent=`${r.on?'Running':'Stopped'} · ${r.cycles||0} cycles · ${r.message||''}`;
      q('[data-randomized-on]').checked=!!r.on;
    }};
    q('[data-apply-randomized]').onclick=async()=>showModes(await run('randomized',randomizedArgs()));
    q('[data-randomized-on]').onchange=()=>q('[data-apply-randomized]').click();
    q('[data-interval]').oninput=()=>q('[data-interval-value]').value=q('[data-interval]').value+' s';
    q('[data-interval]').onchange=()=>{if(q('[data-randomized-on]').checked)q('[data-apply-randomized]').click();};
    modeTimer=setInterval(async()=>{
      if(!current()||busy||checking||!cap?.features?.randomized)return;
      try {const r=await command('modes');if(current()){showModes(r.randomized);if(r.travel && r.travel.message!==lastTravel){lastTravel=r.travel.message;say(lastTravel);}}}catch(error){say(error.message);}
    },5000);
    async function load() {
      if (!current() || busy || loading) return;
      const attempt = ++loadId;
      loading = true; checking = true; cap = null; prefsReady = false; enabled();
      q("[data-equip]").indeterminate = true;
      const fresh = () => current() && attempt === loadId;
      try {
        const result = await command("capabilities");
        if (!fresh()) return;
        cap = result;
        checking = false; enabled();
        q("[data-profile]").textContent = cap.supported ? `${cap.label || 'Dreamcast US Ver. 2'} · offline live controls` : cap.reason;
        q("[data-live-reason]").textContent = cap.supported ? "" : "You can browse and select items below. Dropping items, editing stats and changing equipment in this running game require a verified patch: " + cap.reason;
        q("[data-class]").innerHTML = '<option value="">Choose your class</option>' + cap.classes.map(c => `<option>${esc(c)}</option>`).join("");
        if (cap.character_class) q("[data-class]").value = cap.character_class;
        q("[data-multi-note]").textContent = cap.multi_equip_note;
        q("[data-pending]").innerHTML = Object.values(cap.pending).map(x => `<p>${esc(x)}</p>`).join("");
        const messages = [];
        await Promise.all([
          Promise.resolve().then(async()=>{
            if(!cap.features?.boss_warp)return;
            const r=await command('bosses');if(!fresh())return;
            q('[data-boss]').innerHTML=r.bosses.map(b=>`<option value="${esc(b.id)}">${esc(b.name)}</option>`).join('');
            if(r.default)q('[data-boss]').value=r.default;
            bossesReady=!!r.bosses.length;enabled();
          }).catch(error=>{if(fresh())q('[data-boss]').innerHTML='<option value="">Boss destinations unavailable</option>';}),
          Promise.resolve().then(() => io.api("/api/pso/items?version=" + cap.version)).then(catalog => {
            if (!fresh()) return;
            if (!Array.isArray(catalog)) throw new Error("Invalid item database");
            items = catalog; ready = true; render();
          }).catch(() => { if (fresh()) messages.push("Item database unavailable. Prepare the owned disc or retry loading."); }),
          Promise.resolve().then(() => io.api("/api/pso/preferences")).then(prefs => {
            if (!fresh()) return;
            if (typeof prefs?.equip_any !== 'boolean') throw new Error("Invalid equipment default");
            prefsReady = true; q("[data-equip]").indeterminate = false; q("[data-equip]").checked = prefs.equip_any;
            q('[data-scape]').checked=!!prefs.permanent_scape;q('[data-legendary]').checked=!!prefs.legendary;
            q('[data-enemy-on]').checked=!!prefs.enemy_drops;q('[data-walk]').checked=!!prefs.walk_through;
            if(!selectionTouched && Array.isArray(prefs.enemy_codes))selected=new Set(prefs.enemy_codes.slice(0,20));
            if(typeof prefs.enemy_max_grind==='boolean')q('[data-grind]').checked=prefs.enemy_max_grind;
            render();
            q("[data-preferences]").textContent = "Shared default for supported current and future builds. Unsupported revisions still need their own verified patch.";
            enabled();
          }).catch(() => { if (fresh()) {
            q("[data-preferences]").textContent = "Shared equipment settings are unavailable; a backend update may be pending. Item browsing and supported live controls work independently.";
            messages.push("Equipment default unavailable; retry after the backend refresh.");
          } })
        ]);
        if (!fresh()) return;
        say([ready ? cap.supported ? "Choose items to drop, or choose your class and scatter rares."
          : `Item database available. ${cap.reason}` : "", ...messages].filter(Boolean).join(" "));
      } catch (e) { if (fresh()) say(e.message || "Could not check this game's live controls. Retry loading when the worker is available."); }
      finally { if (fresh()) { loading = false; checking = false; enabled(); } }
    }
    q("[data-retry]").onclick = load;
    load();
    return { dispose() { clearTimeout(lootTimer);clearTimeout(magTimer);clearInterval(modeTimer);if (host._psoMount === token) { host._psoMount = null; host.dataset.psoSid = ""; } } };
  }
  return { mount, isPSO, filterItems };
});
