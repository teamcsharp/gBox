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
    return items.filter(i => (!category || i.cat === category) && (!q || `${i.name} ${i.display_name || ''} ${i.family_name || ''} ${i.variant_name || ''} ${i.code}`.toLowerCase().includes(q))
      && (!rare || i.rare) && (!characterClass || !i.classes || i.classes.includes(characterClass)))
      .sort((a, b) => (b.stars || 0) - (a.stars || 0) || (a.family_name || a.name).localeCompare(b.family_name || b.name) || a.code.localeCompare(b.code));
  }
  function groupItems(items) {
    const groups = new Map();
    for (const item of items) {
      const key = item.family_key || `${item.cat}:${item.name.toLowerCase()}`;
      if (!groups.has(key)) groups.set(key, {key, name:item.family_name || item.name, items:[]});
      groups.get(key).items.push(item);
    }
    return [...groups.values()];
  }
  function weaponChoices(items, player, nativeStatus) {
    if (player?.available !== true || player?.verified !== true || typeof nativeStatus?.equip_any !== 'boolean') return [];
    const any = nativeStatus.equip_any === true;
    const cls = player.class_verified === true && typeof player.character_class === 'string' ? player.character_class : null;
    if (!any && !cls) return [];
    const codes = new Set();
    return items.filter(item => {
      if (item?.cat !== 'Weapons' || !/^00[0-9a-f]{4}$/.test(item.code || '') || codes.has(item.code) ||
          (!any && (!Array.isArray(item.classes) || !item.classes.includes(cls)))) return false;
      codes.add(item.code); return true;
    }).sort((a,b) => String(a.display_name || a.name || a.code).localeCompare(String(b.display_name || b.name || b.code)) || a.code.localeCompare(b.code));
  }
  function equipmentConfirmed(receipt, playerIndex) {
    return receipt?.verified === true && receipt.player_index === playerIndex && Number.isInteger(receipt.item_id) && receipt.item_id >= 0 && receipt.item_id <= 0xffffffff;
  }
  function speedCaption(status, elapsedMs = 0) {
    const requested = status?.requested || 1, prefix = `Requested ${requested}x; `;
    if (status?.paused) return prefix + 'paused. No current speed measurement.';
    if (status?.changing) return prefix + 'changing speed. No current speed measurement.';
    const measured = status?.measurement_verified === true && status?.known === true &&
      status?.measurement_source === 'native_game_clock' && Number.isFinite(elapsedMs) && elapsedMs >= 0 &&
      Number.isFinite(status.valid_for_ms) && status.valid_for_ms > 0 && status.valid_for_ms <= 2000 &&
      [status.actual,status.lower,status.upper].every(Number.isFinite) &&
      0 < status.lower && status.lower <= status.actual && status.actual <= status.upper && status.upper <= 12 &&
      (status.upper-status.lower)/status.actual <= .05;
    if (measured) {
      const rate = value => String(+value.toFixed(2));
      if (elapsedMs >= status.valid_for_ms) return prefix + `last measured ${rate(status.actual)}x (stale). No current speed measurement.`;
      return prefix + `measured ${rate(status.actual)}x (range ${rate(status.lower)}–${rate(status.upper)}x, native game clock).`;
    }
    return prefix + (status?.known === false ? 'speed setting unconfirmed. ' : '') + 'Actual game speed has not been measured recently.';
  }
  function commandSender(io, sid, current, bounded, monotonic = () => globalThis.performance.now()) {
    return async (op, args = {}, playerIndex = 0) => {
      if (!current()) throw new Error('The PSO session panel has changed; no command was sent.');
      const bytes = new Uint8Array(16); globalThis.crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const h = [...bytes].map(v => v.toString(16).padStart(2, '0')).join('');
      const command_id = `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
      // Use this authority's time, never the desktop wall clock. A unique GET
      // avoids cached health responses; uncertain/slow reads cannot authorize a write.
      const started = monotonic();
      if (!Number.isFinite(started)) throw new Error('PSO clock verification is unavailable; no command was sent.');
      const clock = await bounded(io.api(`/api/health?_pso_clock=${command_id}`),
        'PSO server time could not be verified; no command was sent. Please try again.', 4000);
      const received = monotonic();
      if (clock?.ok !== true || !Number.isFinite(clock.time) || clock.time <= 0 ||
          !Number.isFinite(received) || received < started || received - started > 4000)
        throw new Error('PSO server time was unavailable or stale; no command was sent.');
      if (!current()) throw new Error('The PSO session panel has changed; no command was sent.');
      const sending = monotonic();
      if (!Number.isFinite(sending) || sending < received || sending - received > 1000)
        throw new Error('PSO server time became stale; no command was sent.');
      // The eight seconds start at the server's sample, conservatively excluding
      // transit time. A timeout is never retried: the game may have applied it.
      return bounded(io.api(`/api/sessions/${encodeURIComponent(sid)}/rpc`, {op: 'pso_controls',
        args: {command_id, expires: clock.time + 8, input: {session_id: sid, op, ...args, player_index:playerIndex}}}),
        'PSO did not answer in time. The outcome may be unknown; no action was retried. Use Reconnect PSO controls to diagnose the connection.',
        op==='autoplay_speed'?55000:12000);
    };
  }
  function mount(host, io, session) {
    const sid = session.sid, token = {};
    let selectedPlayer = 0;
    const timeouts = new Set();
    function bounded(promise, message, ms = 12000) {
      let timer;
      return Promise.race([promise, new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);timeouts.add(timer);})])
        .finally(()=>{clearTimeout(timer);timeouts.delete(timer);});
    }
    host._psoMount = token;
    const current = () => host.isConnected && host._psoMount === token;
    const sendCommand = commandSender(io, sid, current, bounded);
    const command = (op, args = {}, playerIndex = selectedPlayer) => sendCommand(op, args, playerIndex);
    host.dataset.psoSid = sid;
    let cap, items = [], busy = false, ready = false, prefsReady = false, loading = false, checking = false, recovering = false, loadId = 0, selected = new Set();
    let magId = null, magTimer = null, modeTimer = null, magPatch = {};
    let speedState = null, speedAt = 0, speedVersion = 0, speedExpiry = null;
    let lootTimer = null, lootDirty = false, lootDraft = null, selectionTouched = false, bossesReady = false, lastTravel = '';
    let groupLimit = 80, loadout = null, planning = false, planId = 0, enemyPoolCodes = [];
    let buddyPlayers = [], buddyNative = null;
    const buddyMessages = ['', ''];
    const expanded = new Set();
    const q = sel => host.querySelector(sel);
    host.innerHTML = `<style>
      .pso-controls {font-size:12px;min-width:0}.pso-controls fieldset{border:1px solid var(--line,#35353f);border-radius:6px;margin:8px 0;padding:8px;min-width:0}
      .pso-controls legend{font-weight:600}.pso-controls label{display:flex;align-items:center;gap:6px;margin:6px 0}.pso-controls input[type=range]{min-width:50px;flex:1}
      .pso-controls input[type=search],.pso-controls select{max-width:100%;min-width:0}.pso-controls .pso-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
      .pso-controls .pso-items{max-height:240px;overflow:auto;border-top:1px solid var(--line,#35353f);margin:6px 0}
      .pso-controls .pso-item{display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid var(--line,#35353f)}
      .pso-controls .pso-item span{flex:1;overflow-wrap:anywhere}.pso-controls small{color:var(--mut,#aaa);display:block;font-size:11px}
      .pso-controls .pso-thumb{width:48px;height:48px;object-fit:contain;flex:none;background:#11151d;border-radius:4px}
      .pso-controls .pso-family{border-bottom:1px solid var(--line,#35353f)}.pso-controls .pso-family summary{cursor:pointer;padding:6px 0;list-style-position:inside}
      .pso-controls .pso-family summary img{vertical-align:middle;margin-right:5px}.pso-controls .pso-variants{padding-left:10px;border-left:2px solid var(--line,#35353f)}
      .pso-controls .pso-reference{font-size:10px}.pso-controls textarea{width:100%;box-sizing:border-box;resize:vertical;min-height:68px}
      .pso-controls .pso-plan{max-height:220px;overflow:auto}.pso-controls .pso-plan ol{padding-left:22px}
      .pso-controls .pso-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.pso-controls .pso-stat input{width:64px}
      .pso-controls [role=status]{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}.pso-controls button{cursor:pointer}
      .pso-controls .pso-buddy{padding:8px 0;border-top:1px solid var(--line,#35353f)}.pso-controls .pso-buddy:first-of-type{border-top:0}
      .pso-controls .pso-buddy select{width:100%;box-sizing:border-box}.pso-controls .pso-buddy label{display:block;margin:0 0 6px}
      .pso-controls .pso-buddy .pso-row{margin-top:6px}.pso-controls .pso-buddy [role=status]{margin:5px 0 0;font-size:11px}
    </style><div class="pso-controls">
      <div class="pso-row" style="justify-content:space-between;flex-wrap:nowrap;align-items:flex-start"><p class="mut" data-profile style="flex:1;min-width:0;margin:6px 0">Checking the running game's version…</p>
        <button type="button" class="act" data-rehook title="Troubleshoot and reconnect PSO controls without restarting the game" aria-label="Reconnect PSO controls" style="flex:none">&#8635;</button></div>
      <div data-rehook-report role="status" aria-live="polite"></div>
      <fieldset data-buddy-weapons><legend>Buddy weapons</legend>
        ${[0,1].map(index=>`<div class="pso-buddy" data-buddy="${index}">
          <label><strong>Player ${index+1}</strong> weapon
          <select data-buddy-weapon="${index}" aria-label="Player ${index+1} weapon" disabled><option value="">Checking native equipment controls...</option></select></label>
          <div class="pso-row"><button type="button" class="act" data-buddy-equip="${index}" disabled>Equip</button>
          <button type="button" class="act" data-buddy-random="${index}" disabled>Random weapon now</button></div>
          <p role="status" aria-live="polite" data-buddy-status="${index}">Checking player ${index+1}...</p>
        </div>`).join('')}
        <button type="button" class="act" data-buddy-refresh>Refresh weapon controls</button>
        <small>Each row changes only that player. The game must confirm the equipment change. Needs one free inventory slot; existing items are retained.</small>
      </fieldset>
      <label>Advanced equipment player <select data-player aria-label="Equipment player"><option value="0">Player 1</option></select></label>
      <small data-player-note>Native equipment actions use the verified selected player.</small>
      <fieldset data-speed-panel disabled hidden><legend>Autoplay speed</legend>
        <label>Requested speed <input type="range" data-speed min="0" max="4" step="1" value="0"><output data-speed-value>1x</output></label>
        <small data-speed-note>Dedicated co-op run only. Actual game speed has not been measured.</small>
      </fieldset>
      <fieldset data-controls disabled><legend>Item database</legend>
        <input type="search" data-search placeholder="Search the disc's item database" aria-label="Search PSO items">
        <div class="pso-row"><select data-category aria-label="Item category">${["Weapons", "Armor", "Mags", "Tools"].map(x => `<option>${x}</option>`).join("")}</select>
        <label><input type="checkbox" data-rare> Rares only</label></div>
        <label>Class <select data-class aria-label="Character class"><option value="">Choose your class</option></select></label>
        <div class="pso-items" data-items></div><small data-total></small>
        <button class="act" data-more hidden>Show more weapon groups</button>
        <small>Expand a weapon to choose its individual specials or variants. Wiki pictures are references; names, codes and stats are read from your disc.</small>
      </fieldset>
      <fieldset data-loadouts disabled><legend>Researched weapon lists and builds</legend>
        <label>List <select data-loadout-preset aria-label="Researched weapon list">
          <option value="community">Community powerful weapons</option><option value="hunter">Hunter damage and utility</option>
          <option value="ranger">Ranger damage and utility</option><option value="force">Force technique and support</option>
          <option value="atp">Highest maximum-grind ATP</option><option value="import">Import a researched list</option>
        </select></label>
        <div data-loadout-import hidden><label>One exact item name or code per line<textarea data-loadout-names aria-label="Imported weapon names"></textarea></label>
          <label>Source article <input type="url" data-loadout-source placeholder="https://…" aria-label="Research source URL"></label></div>
        <div class="pso-row"><button class="act" data-loadout-preview>Preview list</button><button class="act pri" data-loadout-drop disabled>Drop list</button></div>
        <small>Uses Count and Class below/above, drops one of each resolved item, and excludes unavailable or class-incompatible items. No universal strongest-weapon order is assumed.</small>
        <div class="pso-plan" data-loadout-result aria-live="polite"></div>
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
        <label><input type="checkbox" data-always-hit> Default: attacks never miss</label>
        <small data-accuracy-note>Bypasses the accuracy miss roll for your attacks on supported revisions. Range, target contact and invulnerability still apply.</small>
        <small data-preferences>Shared default for supported current and future builds on your PCs. This does not enable patches on an unsupported revision.</small>
      </fieldset>
      <fieldset data-live disabled><legend>Live equipment and stats</legend>
        <div class="pso-row"><button class="act" data-inventory>Refresh equipment</button><button class="act" data-equip-selected disabled>Equip selected item</button></div><div data-inventory-list></div>
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
      const buddyBusy = busy || checking || loading || recovering;
      q('[data-buddy-refresh]').disabled = buddyBusy || !ready;
      for (const index of [0,1]) {
        const choices = weaponChoices(items, buddyPlayers.find(p=>p.index===index), buddyNative);
        q(`[data-buddy-weapon="${index}"]`).disabled = buddyBusy || !choices.length;
        q(`[data-buddy-equip="${index}"]`).disabled = buddyBusy || !choices.some(item=>item.code===q(`[data-buddy-weapon="${index}"]`).value);
        q(`[data-buddy-random="${index}"]`).disabled = buddyBusy || !choices.length;
      }
      q('[data-player]').disabled=busy || checking || loading || recovering;
      q('[data-speed-panel]').hidden=!cap?.features?.autoplay_speed;
      q('[data-speed-panel]').disabled=busy || checking || !cap?.features?.autoplay_speed;
      q("[data-controls]").disabled = !ready;
      q('[data-loadouts]').disabled = !ready || planning || busy || checking;
      q('[data-loadout-drop]').disabled = !loadout?.codes?.length || planning || busy || checking || !cap?.supported || cap?.features?.floor_spawn===false;
      q("[data-spawn]").disabled = busy || checking || !ready || !cap?.supported;
      q("[data-live]").disabled = busy || checking || !cap?.supported;
      q("[data-defaults]").disabled = busy || checking || !prefsReady || selectedPlayer!==0;
      q("[data-retry]").disabled = busy || loading || recovering;
      q('[data-rehook]').disabled = busy || recovering;
      q('[data-rehook]').textContent = recovering ? '…' : '↻';
      q('[data-rehook]').setAttribute('aria-busy',String(recovering));
      q('[data-always-hit]').disabled = busy || checking || !prefsReady || !cap?.features?.always_hit;
      q("[data-drop]").disabled = busy || checking || !ready || !cap?.supported || !selected.size || cap?.features?.floor_spawn===false;
      q("[data-random]").disabled = busy || checking || !ready || !cap?.supported || !q("[data-class]").value || cap?.features?.floor_rares===false;
      // Browsing is independent of revision support for native actions.
      q("[data-clear]").disabled = busy || checking || !ready || !cap?.supported || cap?.features?.floor_clear===false;
      q("[data-give]").disabled = busy || checking || !ready || !cap?.supported || selected.size !== 1;
      q('[data-equip-selected]').disabled=busy || checking || !ready || !cap?.supported || !cap?.features?.equip || selected.size!==1;
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
      if (!cap?.supported && !(op==='autoplay_speed' && cap?.features?.autoplay_speed)) { say(cap?.reason || "Live actions are not available for this game revision."); return; }
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
    function renderBuddyWeapons() {
      if (!current()) return;
      for (const index of [0,1]) {
        const player = buddyPlayers.find(p=>p.index===index), select = q(`[data-buddy-weapon="${index}"]`), previous = select.value;
        const choices = weaponChoices(items, player, buddyNative);
        select.innerHTML = '<option value="">Choose a weapon</option>' + choices.map(item=>`<option value="${esc(item.code)}">${esc(item.display_name || item.name || item.code)} (${esc(item.code)})</option>`).join('');
        if (choices.some(item=>item.code===previous)) select.value = previous;
        let reason = player?.reason || `Player ${index+1} is not active or has not passed native verification.`;
        if (player?.available === true && player?.verified === true) reason = buddyNative === null
          ? 'Native equipment status is unknown. Refresh weapon controls.'
          : !choices.length ? 'Equip any is off and this player\'s class compatibility is not verified.'
          : buddyNative.equip_any ? `${choices.length} weapons. Native Equip any is on.` : `${choices.length} weapons for verified ${player.character_class}.`;
        q(`[data-buddy-status="${index}"]`).textContent = buddyMessages[index] || reason;
      }
      enabled();
    }
    async function refreshBuddyWeapons(known = null) {
      if (!current() || busy || checking || loading || recovering || !ready) return;
      busy = true; buddyNative = null; buddyMessages.fill(''); enabled();
      try {
        const report = known || await command('capabilities', {}, 0);
        if (!current()) return;
        buddyPlayers = Array.isArray(report?.players) ? report.players : [];
        const player = buddyPlayers.find(p=>(p.index===0 || p.index===1) && p.available===true && p.verified===true);
        if (report.version === 'gc' && player) {
          const status = await command('status', {}, player.index);
          if (!current()) return;
          if (typeof status?.equip_any !== 'boolean') throw Error('Native equipment status was not confirmed.');
          buddyNative = status;
        }
      } catch(error) { if (current()) buddyMessages.fill(error.message || 'Could not read native equipment status.'); }
      finally { busy=false; renderBuddyWeapons(); }
    }
    async function equipBuddy(index, random = false) {
      if (!current() || busy || checking || loading || recovering) return;
      let choices = weaponChoices(items, buddyPlayers.find(p=>p.index===index), buddyNative);
      const wanted = q(`[data-buddy-weapon="${index}"]`).value;
      if (!choices.length || (!random && !choices.some(item=>item.code===wanted))) return;
      busy=true;buddyMessages[index]=`Checking player ${index+1} before equipping...`;renderBuddyWeapons();
      try {
        const report = await command('capabilities', {}, index);
        if (!current()) return;
        buddyPlayers=Array.isArray(report?.players) ? report.players : [];
        const player = report?.players?.find(p=>p.index===index);
        if (report.version !== 'gc' || report.player_index !== index || !report.supported || player?.verified !== true || player?.available !== true)
          throw Error(player?.reason || report.reason || `Player ${index+1} is no longer verified. Refresh weapon controls.`);
        const status = await command('status', {}, index);
        if (!current()) return;
        buddyNative = typeof status?.equip_any === 'boolean' ? status : null;
        choices = weaponChoices(items, player, buddyNative);
        const item = random ? choices[Math.floor(Math.random()*choices.length)] : choices.find(item=>item.code===wanted);
        if (!item) throw Error('Current native equipment permissions changed; no weapon was assigned. Refresh weapon controls.');
        buddyMessages[index]=`Equipping ${item.display_name || item.name} for player ${index+1}...`;renderBuddyWeapons();
        const result=await command('equip', {code:item.code}, index);
        if (!current()) return;
        if (!equipmentConfirmed(result,index)) throw Error(`Not confirmed for player ${index+1}. ${result?.message || 'Refresh equipment before retrying.'}`);
        q(`[data-buddy-weapon="${index}"]`).value=item.code;
        buddyMessages[index]=`Verified: ${item.display_name || item.name} equipped on player ${index+1}.`;
      } catch(error) { if(current()) buddyMessages[index]=error.message || 'The equipment outcome is unknown. No action was retried.'; }
      finally { busy=false;renderBuddyWeapons(); }
    }
    q('[data-buddy-refresh]').onclick=()=>refreshBuddyWeapons();
    for (const index of [0,1]) {
      q(`[data-buddy-weapon="${index}"]`).onchange=()=>enabled();
      q(`[data-buddy-equip="${index}"]`).onclick=()=>equipBuddy(index);
      q(`[data-buddy-random="${index}"]`).onclick=()=>equipBuddy(index,true);
    }
    function render() {
      if (!current()) return;
      const scroller=q('[data-items]'),scrollTop=scroller.scrollTop;
      scroller.querySelectorAll('[data-family]').forEach(el=>{el.open?expanded.add(el.dataset.family):expanded.delete(el.dataset.family);});
      const rows = filterItems(items, { query: q("[data-search]").value, category: q("[data-category]").value,
        rare: q("[data-rare]").checked, characterClass: q("[data-class]").value });
      const groups = groupItems(rows);
      q("[data-total]").textContent = `${rows.length} matches · ${groups.length} weapon/item groups · ${selected.size} selected (up to 20)`;
      const picture = i => i.thumbnail_url && /^https:\/\/wiki\.pioneer2\.net\/images\//.test(i.thumbnail_url)
        ? `<img class="pso-thumb" loading="lazy" referrerpolicy="no-referrer" alt="${esc(i.family_name || i.name)} reference" src="${esc(i.thumbnail_url)}">` : '';
      const reference = i => i.reference_url && /^https:\/\/wiki\.pioneer2\.net\/w\//.test(i.reference_url)
        ? `<a class="pso-reference" href="${esc(i.reference_url)}" target="_blank" rel="noopener noreferrer" title="${esc(i.reference_note || '')}">Wiki reference ↗</a>` : '';
      const row = (i, variant=false) => `<label class="pso-item"><input type="checkbox" data-code="${esc(i.code)}" ${selected.has(i.code) ? 'checked' : ''}>
        ${variant ? '' : picture(i)}<span>${esc(variant ? i.variant_name || i.code : i.display_name || i.name)}
        <small>${i.stars} stars · ${esc(i.code)}${i.max_grind != null ? ` · grind +${i.max_grind}` : ''}
        ${i.atp_required != null ? ` · ATP ${i.atp_required} / MST ${i.mst_required} / ATA ${i.ata_required}` : ''}</small>${variant ? '' : reference(i)}</span></label>`;
      q('[data-items]').innerHTML = groups.slice(0,groupLimit).map(g => g.items.length===1 ? row(g.items[0]) :
        `<details class="pso-family" data-family="${esc(g.key)}" ${expanded.has(g.key) ? 'open' : ''}>
          <summary>${picture(g.items[0])}<strong>${esc(g.name)}</strong><small>${g.items.length} variants · ${g.items.filter(i=>selected.has(i.code)).length} selected</small></summary>
          ${reference(g.items[0])}<div class="pso-variants">${g.items.map(i=>row(i,true)).join('')}</div></details>`).join('') || 'No matching items.';
      q('[data-items]').querySelectorAll('img').forEach(img=>{img.onerror=()=>{img.hidden=true;};});
      scroller.scrollTop=scrollTop;
      q('[data-more]').hidden=groups.length<=groupLimit;
      const pool=q('[data-enemy-on]').checked ? enemyPoolCodes : [...selected];
      q('[data-enemy-pool]').textContent=pool.length ? `Enemy pool: ${pool.map(c=>items.find(i=>i.code===c)?.display_name||items.find(i=>i.code===c)?.name||c).join(', ')}` : 'Choose up to 20 items in the database above.';
      enabled();
    }
    function invalidatePlan(){++planId;loadout=null;q('[data-loadout-result]').textContent='';enabled();}
    for (const attr of ["search", "category", "rare", "class"]) q(`[data-${attr}]`).addEventListener(attr === "search" ? "input" : "change", ()=>{groupLimit=80;if(attr==='class')invalidatePlan();render();});
    q('[data-items]').addEventListener('toggle',e=>{const key=e.target.dataset.family;if(key)e.target.open?expanded.add(key):expanded.delete(key);},true);
    q('[data-more]').onclick=()=>{groupLimit+=80;render();};
    for (const attr of ["count", "radius"]) q(`[data-${attr}]`).oninput = () => {q(`[data-${attr}-value]`).value = q(`[data-${attr}]`).value;if(attr==='count')invalidatePlan();};
    q("[data-items]").onchange = e => {
      const code = e.target.dataset.code; if (!code) return;
      if (e.target.checked && selected.size >= 20) { e.target.checked = false; say("Select up to 20 items per drop."); return; }
      selectionTouched = true;
      e.target.checked ? selected.add(code) : selected.delete(code); render();
      if(q('[data-enemy-on]').checked) scheduleLoot();
    };
    function scheduleLoot(useSelection=true) {
      // Keep the intended enemy policy independent of manual drop checkmarks.
      // A successful drop may clear them while this debounced request is waiting.
      lootDraft={on:q('[data-enemy-on]').checked,codes:selected.size || useSelection ? [...selected] : [...enemyPoolCodes],max_grind:q('[data-grind]').checked};
      lootDirty=true;clearTimeout(lootTimer);lootTimer=setTimeout(applyLoot,350);
    }
    async function applyLoot() {
      if(!current() || !lootDirty || !prefsReady || !cap?.features?.enemy_drops)return;
      if(busy || checking){lootTimer=setTimeout(applyLoot,150);return;}
      lootDirty=false;
      const {on,codes,max_grind}=lootDraft;
      if(on && !codes.length){q('[data-enemy-on]').checked=false;say('Select items before enabling enemy drops.');}
      const want=on && !!codes.length;
      busy=true;enabled();
      try {await io.api('/api/pso/preferences',{enemy_drops:want,enemy_codes:codes,enemy_max_grind:max_grind});}
      catch(error){say('Enemy drop settings were not saved: '+error.message);busy=false;enabled();return;}
      enemyPoolCodes=want ? codes : [];busy=false;render();
      if(current())await run('enemy_drops',{on:want,codes,max_grind});
    }
    q('[data-enemy-on]').onchange=()=>scheduleLoot(false);
    q('[data-grind]').onchange=()=>{if(q('[data-enemy-on]').checked)scheduleLoot(false);};
    q('[data-walk]').onchange=async e=>{
      if(busy || checking || !prefsReady)return;
      const on=e.target.checked;busy=true;enabled();
      try {await io.api('/api/pso/preferences',{walk_through:on});}
      catch(error){e.target.checked=!on;say(error.message);busy=false;enabled();return;}
      busy=false;if(current())await run('walk_through',{on});
    };
    q('[data-boss-warp]').onclick=()=>run('boss_warp',{target:q('[data-boss]').value});
    const spawnArgs = () => ({ count: +q("[data-count]").value, radius: +q("[data-radius]").value, max_grind: q("[data-grind]").checked });
    q("[data-drop]").onclick = async() => {
      const dropped=[...selected],r=await run('floor_spawn',{...spawnArgs(),codes:dropped});
      if(r?.verified===true && current()){dropped.forEach(c=>selected.delete(c));selectionTouched=true;render();}
    };
    q('[data-loadout-preset]').onchange=()=>{q('[data-loadout-import]').hidden=q('[data-loadout-preset]').value!=='import';invalidatePlan();};
    for(const attr of ['names','source'])q(`[data-loadout-${attr}]`).oninput=invalidatePlan;
    q('[data-loadout-preview]').onclick=async()=>{
      if(planning || busy || checking || !ready)return;
      const attempt=++planId;
      planning=true;loadout=null;enabled();q('[data-loadout-result]').textContent='Resolving against this disc and character class…';
      const preset=q('[data-loadout-preset]').value;
      const input={version:cap.version,preset:preset==='import'?'community':preset,character_class:q('[data-class]').value,count:+q('[data-count]').value};
      if(preset==='import'){
        input.names=q('[data-loadout-names]').value.split(/\n/).map(s=>s.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(Boolean);
        input.source_urls=q('[data-loadout-source]').value.trim() ? [q('[data-loadout-source]').value.trim()] : [];
        if(!input.names.length){planning=false;enabled();q('[data-loadout-result]').textContent='Enter at least one researched item name.';return;}
      }
      try{
        const result=await bounded(io.api('/api/pso/loadouts/plan',input),'List preview timed out. No items were dropped.');
        if(!current() || attempt!==planId)return;
        if(!Array.isArray(result.items)||!Array.isArray(result.codes)||result.codes.length>20)throw Error('Invalid researched list response');
        loadout=result;
        q('[data-loadout-result]').innerHTML=`<strong>${esc(result.label)}</strong><ol>${result.items.map(i=>`<li>${esc(i.display_name||i.name)}<small>${esc(i.code)}${i.max_grind_atp!=null?' · max-grind ATP '+i.max_grind_atp:''}</small></li>`).join('')}</ol><small>${esc(result.note)}</small>
          ${(result.warnings||[]).map(w=>`<p>${esc(w)}</p>`).join('')}<small>${(result.sources||[]).filter(u=>/^https:\/\//.test(u)).map((u,n)=>`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Source ${n+1} ↗</a>`).join(' · ')}</small>`;
      }catch(error){if(current() && attempt===planId)q('[data-loadout-result]').textContent=error.message;}
      finally{planning=false;enabled();}
    };
    q('[data-loadout-drop]').onclick=async()=>{
      if(!loadout?.codes?.length)return;
      const codes=[...loadout.codes],r=await run('floor_spawn',{...spawnArgs(),count:codes.length,codes});
      if(r?.verified===true && current()){codes.forEach(c=>selected.delete(c));selectionTouched=true;render();}
    };
    q("[data-random]").onclick = () => run("floor_rares", { ...spawnArgs(), character_class: q("[data-class]").value, highest: q("[data-highest]").checked });
    q("[data-clear]").onclick = () => run("floor_clear", { on: false });
    q("[data-give]").onclick = () => run("give", {code: [...selected][0], count: +q('[data-count]').value});
    q('[data-equip-selected]').onclick=()=>run('equip',{code:[...selected][0]});
    const speedChoices=[1,2,4,8,10];
    function showSpeed(status, started = performance.now(), updateSlider = false) {
      if (!current()) return;
      clearTimeout(speedExpiry);
      speedState = status; speedAt = started;
      const elapsed = Math.max(0,performance.now()-started);
      q('[data-speed-note]').textContent=speedCaption(status,elapsed);
      if (updateSlider) {
        const requested=status?.requested || 1;
        q('[data-speed]').value=String(Math.max(0,speedChoices.indexOf(requested)));
        q('[data-speed-value]').value=requested+'x';
      }
      if (status?.measurement_verified && Number.isFinite(status.valid_for_ms) && elapsed < status.valid_for_ms) {
        speedExpiry=setTimeout(()=>{if(current())q('[data-speed-note]').textContent=speedCaption(speedState,performance.now()-speedAt);},Math.min(2000,status.valid_for_ms-elapsed)+1);
      }
    }
    q('[data-speed]').oninput=()=>q('[data-speed-value]').value=speedChoices[+q('[data-speed]').value]+'x';
    q('[data-speed]').onchange=async()=>{
      ++speedVersion;
      const requested=speedChoices[+q('[data-speed]').value];
      showSpeed({requested,changing:true});
      const result=await run('autoplay_speed',{multiplier:requested});
      // A hotkey receipt is never a measurement, even if a caller labels it verified.
      if(current())showSpeed({requested:result?.requested || requested,known:result?.input_delivered===true});
    };
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
      q("[data-inventory-list]").innerHTML = (r.inventory || []).filter(i => /^(00|02|0101|0102)/.test(i.code)).map(i =>
        `<div class="pso-row"><span>${esc(i.name)}${i.equipped ? " · equipped" : ""}</span>
        ${cap?.features?.equip && Number.isInteger(i.id) ? `<button class="act" data-equip-id="${i.id}">Equip</button>` : ''}
        ${i.code.startsWith('00') && cap?.features?.multi_equip!==false ? `<button class="act" data-multi="${i.slot}" data-on="true">Stack equip</button><button class="act" data-multi="${i.slot}" data-on="false">Unstack</button>` : ''}</div>`).join("") || "No equipment in inventory.";
    };
    q("[data-inventory-list]").onclick = e => {
      const item=e.target.closest('[data-equip-id]');if(item){run('equip',{item_id:+item.dataset.equipId});return;}
      const b = e.target.closest("[data-multi]"); if (b) run("multi_equip", { target: b.dataset.multi, on: b.dataset.on === "true" });
    };
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
      const player=selectedPlayer,version=speedVersion,started=performance.now();
      try {const r=await command('modes');if(current() && player===selectedPlayer){
        showModes(r.randomized);
        if(version===speedVersion && cap?.features?.autoplay_speed)showSpeed(r.autoplay_speed,started);
        if(r.travel && r.travel.message!==lastTravel){lastTravel=r.travel.message;say(lastTravel);}
      }}catch(error){if(player===selectedPlayer)say(error.message);}
    },5000);
    async function load(knownCap = null, notice = '') {
      if (!current() || busy || loading || recovering) return;
      const attempt = ++loadId;
      ++speedVersion;showSpeed(null);
      invalidatePlan();
      loading = true; checking = true; cap = null; prefsReady = false; buddyPlayers=[];buddyNative=null;buddyMessages.fill('');renderBuddyWeapons();enabled();
      q("[data-equip]").indeterminate = true;
      const fresh = () => current() && attempt === loadId;
      try {
        const speedStarted=performance.now();
        const result = knownCap || await command("capabilities");
        if (!fresh()) return;
        cap = result;
        const players=Array.isArray(cap.players) ? cap.players : [{index:0,label:'Player 1',available:true,verified:cap.supported}];
        q('[data-player]').innerHTML=players.map(p=>`<option value="${p.index}" ${!p.available?'disabled':''}>${esc(p.label)}${p.verified?'':' (not verified)'}</option>`).join('');
        q('[data-player]').value=String(selectedPlayer);
        q('[data-player-note]').textContent=cap.selection_note || 'Live controls target player 1 on this edition.';
        // A reconnect result was collected earlier; its transport age is unknown.
        showSpeed(knownCap ? {...cap.autoplay_speed,measurement_verified:false,achieved_verified:false} : cap.autoplay_speed,speedStarted,true);
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
          Promise.resolve().then(() => bounded(io.api("/api/pso/items?version=" + cap.version),'Item database timed out. Use Retry loading.')).then(catalog => {
            if (!fresh()) return;
            if (!Array.isArray(catalog)) throw new Error("Invalid item database");
            items = catalog; ready = true; render();
          }).catch(() => { if (fresh()) messages.push("Item database unavailable. Prepare the owned disc or retry loading."); }),
          Promise.resolve().then(() => bounded(io.api("/api/pso/preferences"),'PSO preferences timed out. Use Retry loading.')).then(prefs => {
            if (!fresh()) return;
            if (typeof prefs?.equip_any !== 'boolean') throw new Error("Invalid equipment default");
            prefsReady = true; q("[data-equip]").indeterminate = false; q("[data-equip]").checked = prefs.equip_any;
            q('[data-always-hit]').checked=prefs.always_hit!==false;
            q('[data-accuracy-note]').textContent=cap.features?.always_hit ? 'Bypasses your attack accuracy miss roll. Range, target contact and invulnerability still apply.' : 'The always-hit patch needs verification for this game revision.';
            q('[data-scape]').checked=!!prefs.permanent_scape;q('[data-legendary]').checked=!!prefs.legendary;
            q('[data-enemy-on]').checked=!!prefs.enemy_drops;q('[data-walk]').checked=!!prefs.walk_through;
            enemyPoolCodes=Array.isArray(prefs.enemy_codes)?prefs.enemy_codes.slice(0,20):[];
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
        say([notice,ready ? cap.supported ? "Choose items to drop, or choose your class and scatter rares."
          : `Item database available. ${cap.reason}` : "", ...messages].filter(Boolean).join(" "));
      } catch (e) { if (fresh()) {q('[data-profile]').textContent='PSO controls not connected';say(e.message || "Could not check this game's live controls. Use Reconnect PSO controls.");} }
      finally { if (fresh()) { loading = false; checking = false; enabled(); if(ready && cap)await refreshBuddyWeapons(cap); } }
    }
    q('[data-rehook]').onclick = async()=>{
      if(!current() || busy || recovering)return;
      selectedPlayer=0;++loadId;loading=false;checking=true;recovering=true;cap=null;bossesReady=false;enabled();
      const report=q('[data-rehook-report]');report.textContent='Reconnecting to this emulator and checking the native mod hook…';
      try{
        const result=await command('rehook');if(!current())return;
        report.textContent=[...(result.steps||[]).map(s=>s.message),result.message].filter(Boolean).join('\n');
        checking=false;recovering=false;
        if(result.capabilities){
          const next=result.ready ? result.capabilities : {...result.capabilities,supported:false,features:{},reason:result.message};
          await load(next,result.message);
        }else{cap=null;q('[data-profile]').textContent='PSO controls not connected';say(result.message);}
      }catch(error){if(current()){q('[data-profile]').textContent='PSO reconnect did not finish';report.textContent=error.message;say(error.message);}}
      finally{if(current()){checking=false;recovering=false;enabled();}}
    };
    q('[data-always-hit]').onchange=async e=>{
      if(!current()||busy||checking||!prefsReady||!cap?.features?.always_hit)return;
      const on=e.target.checked;busy=true;enabled();
      try{await bounded(io.api('/api/pso/preferences',{always_hit:on}),'Could not confirm the always-hit preference. Retry loading to check it.');}
      catch(error){if(current()){e.target.checked=!on;say(error.message);}busy=false;enabled();return;}
      busy=false;if(current())await run('always_hit',{on});enabled();
    };
    q('[data-player]').onchange=()=>{
      if(busy || checking || loading)return;
      selectedPlayer=+q('[data-player]').value;
      clearTimeout(magTimer);clearTimeout(lootTimer);magPatch={};magId=null;lootDirty=false;
      q('[data-inventory-list]').textContent='';q('[data-mag-summary]').textContent='Refresh the selected player\'s equipped MAG.';
      q('[data-mode-state]').textContent='Refresh the selected player\'s equipment mode.';
      q('[data-class]').value='';load();
    };
    q("[data-retry]").onclick = ()=>load();
    load();
    return { dispose() { for(const t of timeouts)clearTimeout(t);timeouts.clear();clearTimeout(speedExpiry);clearTimeout(lootTimer);clearTimeout(magTimer);clearInterval(modeTimer);if (host._psoMount === token) { host._psoMount = null; host.dataset.psoSid = ""; } } };
  }
  return { mount, isPSO, filterItems, groupItems, speedCaption, weaponChoices, equipmentConfirmed, commandSender };
});
