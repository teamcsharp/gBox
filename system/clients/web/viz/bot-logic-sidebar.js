// Live PiP controls reuse re5_mods jobs for RE5 / RE6 Switch. Each request and response stays bound to the displayed
// session and its PC. Behavior settings are saved by bot_logic; mod values come from live status.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const RE5 = root.GBoxRE5Modifiers || (typeof require === "function" ? require("./re5-modifiers.js") : null);
  const RE6 = root.GBoxRE6Modifiers || (typeof require === "function" ? require("./re6-modifiers.js") : null);
  const TITLES = { "52d15709be0fda1a": "re5", "115f9cdbba115432": "re6" };
  const workerOf = s => s?.worker_id || s?.worker || String(s?.session_id || "").split("-")[0];
  const pcOf = s => String(s?.detail?.worker_name || s?.pc || workerOf(s) || "");
  function eligible(s) {
    return !!TITLES[s?.game_id] && ["citron", "eden"].includes(s.adapter) && s.state === "running"
      && !s.warm && !s.stopping && s.worker_online !== false && typeof s.session_id === "string" && s.session_id.includes("-");
  }
  function definitions(title) {
    // turning and aiming speed (operator 2026-10-28: "He is getting decimated by trying to swing around the gun all slow")
    if (title === "re5") return (RE5?.DEFINITIONS || [])
      .map(d => ({ ...d, kind: d.multiplier ? "float" : "bool", ...(d.op === "fire_rate" ? { min: 1, max: 80, step: 1 } : {}),
        ...(d.op === "turn_speed" ? { min: 1, max: 10, step: 0.5 } : {}) }));
    if (title === "re6") return [...(RE6?.TOGGLES || []).map(d => ({ ...d, kind: "bool" })),
      ...(RE6?.MULTIPLIERS || []).map(d => ({ ...d, kind: "float", step: 0.5 }))];
    return [];
  }
  const modValue = (status, d) => d.read ? d.read(status) : status?.[d.field];
  function available(title, status, d) {
    const v = modValue(status, d);
    return !!status && (title !== "re5" || RE5.capability(status, d.op).available)
      && (d.kind === "bool" ? typeof v === "boolean" : typeof v === "number" && Number.isFinite(v));
  }
  const CSS = `#bot-logic-tab{position:fixed;right:0;top:50%;transform:translateY(-50%);z-index:120;display:none;width:22px;
    height:56px;border:1px solid #666;border-right:0;border-radius:6px 0 0 6px;background:#101014dc;color:#fff;cursor:pointer;
    font:16px system-ui;opacity:0;transition:opacity .15s;-webkit-app-region:no-drag}
  body.gbox-compact #bot-logic-tab.ready{display:block}
  body.gbox-compact #bot-logic-tab.ready{opacity:.55}
  body.gbox-compact #bot-logic-tab.ready:hover,#bot-logic-tab.open{opacity:1}
  #bot-logic-tab.open{right:min(320px,85vw)}
  #bot-logic-panel{position:fixed;top:28px;right:0;bottom:0;width:min(320px,85vw);z-index:119;background:#101014f2;color:#ddd;
    font:11px system-ui;overflow:auto;padding:8px 10px;box-sizing:border-box;transform:translateX(105%);transition:transform .2s;
    border-left:1px solid #444;-webkit-app-region:no-drag}
  #bot-logic-panel.open{transform:none}
  #bot-logic-panel .bl-head{display:flex;align-items:center;justify-content:space-between;gap:6px;margin:4px 0 6px}
  #bot-logic-panel .bl-head h3{margin:0;white-space:nowrap}
  #bot-logic-panel select{min-width:0;max-width:170px;flex:1;background:#18181d;color:#fff;border:1px solid #ffd166;
    border-radius:3px;font:11px system-ui;padding:2px}
  #bot-logic-panel .bl-ok{color:#b7e4a0;min-height:14px;margin:5px 0}
  #bot-logic-panel h3{margin:4px 0 6px;font-size:12px}#bot-logic-panel h4{margin:10px 0 4px;font-size:11px;color:#9cf}
  #bot-logic-panel .bl-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 6px;align-items:center;margin:3px 0}
  #bot-logic-panel .bl-row small{grid-column:1/-1;color:#999}#bot-logic-panel input[type=range]{grid-column:1/-1;width:100%;box-sizing:border-box;margin:0}
  #bot-logic-panel .bl-set{color:#ffd166}#bot-logic-panel .bl-msg{color:#ffadad;min-height:14px;margin:5px 0}
  #bot-logic-panel .bl-target{color:#aaa;margin:3px 0 6px}#bot-logic-panel fieldset{border:0;padding:0;margin:0;min-width:0}
  #bot-logic-panel input[type=number]{width:64px;background:#18181d;color:#fff;border:1px solid #666;border-radius:3px}
  #bot-logic-panel input:disabled,#bot-logic-panel button:disabled{opacity:.5;cursor:default}
  #bot-logic-panel .bl-note{color:#aaa;font-size:10px}
  #bot-logic-panel button{border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;font:11px system-ui}`;

  function html(view, message = "", state = {}) {
    const scope = `data-bl-scope="${ESC(state.scope || "")}"`;
    const locked = !!(state.busy || state.pending || state.stale), title = state.title || view?.title;
    const mods = definitions(title).map(d => {
      const ok = available(title, state.status, d), value = modValue(state.status, d);
      const disabled = locked || !ok ? " disabled" : "";
      const reason = !ok && title === "re5" ? RE5.capability(state.status, d.op).reason : "";
      const input = d.kind === "bool"
        ? `<input type="checkbox" data-bl-mod="${ESC(d.op)}"${value === true ? " checked" : ""} ${scope}${disabled}>`
        : `<input type="number" data-bl-mod="${ESC(d.op)}" min="${d.min}" max="${d.max}" step="${d.step}" value="${ok ? value : ""}" aria-label="${ESC(d.label)} multiplier" ${scope}${disabled}>`;
      return `<label class="bl-row"><span>${ESC(d.label)}${d.kind === "float" ? " ×" : ""}</span>${input}`
        + (reason ? `<small>${ESC(reason)}</small>` : "") + `</label>`;
    }).join("");
    const groups = {};
    for (const k of view?.knobs || []) (groups[k.group] = groups[k.group] || []).push(k);
    const rows = Object.entries(groups).map(([g, ks]) => `<h4>${ESC(g)}</h4>` + ks.map(k => {
      const mark = k.set ? ' <span class="bl-set" title="Your setting (saved)">*</span>' : "";
      const tip = ESC(k.help || "");
      if (k.kind === "bool")
        return `<label class="bl-row" title="${tip}"><span>${ESC(k.label)}${mark}</span><input type="checkbox" data-bl="${ESC(k.name)}"${k.value ? " checked" : ""} ${scope}></label>`;
      return `<div class="bl-row" title="${tip}"><span>${ESC(k.label)}${mark}</span><output data-bl-out="${ESC(k.name)}">${ESC(k.value)}</output>`
        + `<input type="range" data-bl="${ESC(k.name)}" min="${k.min}" max="${k.max}" step="${k.step}" value="${ESC(k.value)}" aria-label="${ESC(k.label)}" ${scope}>`
        + (k.help ? `<small>${tip}</small>` : "") + `</div>`;
    }).join("")).join("");
    // the weapon he fights with (operator 2026-10-28: "At the top of the live controls ... a drop down ... every weapon in
    // the game in order of the most powerful to the least powerful ... that weapon is instantly equipped")
    const weapons = Array.isArray(view?.weapons) ? view.weapons : [];
    const current = view?.weapon_current;
    const pick = weapons.length
      ? `<select data-bl-weapon ${scope} aria-label="Equip a weapon" title="Every weapon, most powerful first: the bot fights with the one you pick"${locked ? " disabled" : ""}>`
        + `<option value="">Equip a weapon…</option>`
        + weapons.map(w => `<option value="${ESC(w.id)}"${w.id === current ? " selected" : ""}>${ESC(w.name)}${w.loaded ? " · in hand now" : ""}</option>`).join("")
        + `</select>` : "";
    return `<div class="bl-head"><h3>Live controls · ${ESC(String(title || "").toUpperCase())}</h3>${pick}</div>`
      + (state.pc ? `<p class="bl-target">${ESC(state.pc)} · the game shown in this PiP</p>` : "")
      + `<p class="${state.ok && message ? "bl-ok" : "bl-msg"}" role="status">${ESC(message || (state.busy ? "Reading or applying settings…" : ""))}</p>`
      + `<button type="button" data-bl-refresh ${scope}${state.busy ? " disabled" : ""}>Refresh current settings</button>`
      + (mods ? `<h4>Live mods</h4>${mods}<p class="bl-note">Fire rate is a multiplier; 1× restores the game's rate. Actual shots per second vary.</p>` : "")
      + `<fieldset${locked || !view ? " disabled" : ""}>${rows}`
      + `<p><button type="button" data-bl-reset ${scope}>Reset behavior to the bot's defaults</button></p></fieldset>`;
  }

  function create({ api, current, delay = ms => new Promise(r => setTimeout(r, ms)), doc = root.document, compactOnly = true }) {
    let tab = null, panel = null, style = null, target = null, open = false, generation = 0, disposed = false;
    const empty = () => ({ view: null, status: null, busy: false, pending: null, stale: true, message: "" });
    let state = empty();
    function ensure() {
      if (tab || !doc) return;
      style = doc.createElement("style"); style.textContent = CSS; doc.head.append(style);
      tab = doc.createElement("button"); tab.id = "bot-logic-tab"; tab.type = "button"; tab.textContent = "‹";
      tab.title = "Live controls: fire rate, mods and bot behavior"; tab.onclick = () => toggle();
      panel = doc.createElement("aside"); panel.id = "bot-logic-panel"; panel.setAttribute("aria-label", "Live MercMode controls");
      panel.addEventListener("change", e => {
        const el = e.target, data = el?.dataset || {}, value = el?.type === "checkbox" ? el.checked : el?.value;
        if (data.bl) set(data.bl, value, data.blScope);
        if (data.blMod) setMod(data.blMod, value, data.blScope);
        if ("blWeapon" in data && value !== "") equip(Number(value), data.blScope);
      });
      panel.addEventListener("input", e => { const n = e.target?.dataset?.bl; const o = n && panel.querySelector(`[data-bl-out="${n}"]`); if (o) o.textContent = e.target.value; });
      panel.addEventListener("click", e => {
        const data = e.target?.dataset || {};
        if (data.blScope !== target?.scope) return;
        if ("blReset" in data) reset(data.blScope);
        if ("blRefresh" in data) refresh();
      });
      doc.body.append(tab, panel);
    }
    let shown = null;                                    // the PiP's session id when it has no live settings yet
    function paint() {
      if (panel) panel.innerHTML = target ? html(state.view, state.message, { ...state, ...target })
        : `<h3>Bot logic</h3><p class="bl-msg">This game has no live bot settings or mods in gBox yet; they appear here as `
          + `each game is modded (Ghidra hooks, mods, character swappers). RE5 and RE6 on Switch have them now.</p>`;
      if (tab) tab.textContent = open ? "›" : "‹";
    }
    function alive(bound) {
      if (disposed || target !== bound || current && current() !== bound.sid) throw new Error("The displayed game changed. Refresh its controls.");
    }
    async function validate(bound) {
      alive(bound);
      const rows = await api("/api/sessions?include_ended=false", undefined, "GET");
      alive(bound);
      const row = Array.isArray(rows) && rows.find(s => s.session_id === bound.sid);
      if (!eligible(row) || row.game_id !== bound.gameId || row.adapter !== bound.adapter
          || workerOf(row) !== bound.worker || pcOf(row) !== bound.pc)
        throw new Error("This session ended, paused or moved. Open the active game's controls.");
    }
    async function finish(j, bound, s) {
      for (let i = 0; i < 200 && ["queued", "running"].includes(j?.state); i++) {
        if (!j.id) throw new Error("The server returned no job ID.");
        s.pending = j.id;
        await delay(i < 10 ? 100 : 600); alive(bound);
        j = await api("/api/jobs/" + encodeURIComponent(j.id), undefined, "GET"); alive(bound);
      }
      if (["queued", "running"].includes(j?.state)) throw new Error("The change is still running. Refresh to check its result before changing more settings.");
      s.pending = null;
      if (j?.state !== "succeeded") throw new Error(j?.error?.message || j?.error || "The control job did not succeed.");
      const result = j.output?.result;
      if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("The server returned no settings.");
      return result;
    }
    async function job(bound, s, op, extra = {}) {
      alive(bound);
      const j = await api("/api/jobs", { tool: "re5_mods", agent_use: false, require_worker: bound.worker,
        input: { session_id: bound.sid, op, ...extra } }, "POST");
      alive(bound);
      return finish(j, bound, s);
    }
    function verified(out) { if (out?.verified !== true) throw new Error(out?.reason || "The worker could not verify this change. Refresh current settings."); }
    function logic(out, bound) {
      verified(out);
      if (out.title !== bound.title || !Array.isArray(out.knobs)) throw new Error("The settings do not match the displayed game.");
      return out;
    }
    function mods(out) {
      if (out.verified === false) throw new Error(out.reason || "The worker could not read current mod settings.");
      const st = out.status || out;
      if (!st || typeof st !== "object" || typeof st.fire_rate_x !== "number" || !Number.isFinite(st.fire_rate_x))
        throw new Error(out.reason || "The worker returned no current mod settings.");
      return st;
    }
    async function act(work, scope = target?.scope, reading = false) {
      const bound = target, s = state;
      if (!bound || scope !== bound.scope || s.busy) return false;
      if (!reading && (s.stale || s.pending)) { s.message = "Refresh current settings before changing controls."; paint(); return false; }
      s.busy = true; s.message = ""; s.ok = false; paint();
      try { await validate(bound); await work(bound, s); await validate(bound); return true; }
      catch (e) { if (target === bound) { s.message = e.message || String(e); s.stale = true; } return false; }
      finally { if (target === bound) { s.busy = false; paint(); } }
    }
    function refresh() {
      return act(async (bound, s) => {
        if (s.pending) await finish(await api("/api/jobs/" + encodeURIComponent(s.pending), undefined, "GET"), bound, s);
        const out = await job(bound, s, "live_controls");
        s.view = logic(out.view, bound);
        s.status = mods(out.status);
        s.stale = false;
      }, target?.scope, true);
    }
    function valueFor(d, value) {
      if (d.kind === "bool") {
        if (typeof value !== "boolean") throw new Error(`${d.label} needs an on/off value.`);
        return value;
      }
      const n = typeof value === "number" || typeof value === "string" && value.trim() ? Number(value) : NaN;
      if (!Number.isFinite(n) || n < d.min || n > d.max || d.kind === "int" && !Number.isInteger(n))
        throw new Error(`${d.label} must be ${d.min}–${d.max}${d.kind === "int" ? " (whole numbers)" : ""}.`);
      return n;
    }
    function confirmValue(d, actual, wanted) {
      if (typeof actual !== typeof wanted || (typeof wanted === "number" ? !Number.isFinite(actual) || Math.abs(actual - wanted) > 0.0001 : actual !== wanted))
        throw new Error(`${d.label} was not confirmed by the current settings. Refresh to check its value.`);
    }
    function set(name, value, scope = target?.scope) {
      return act(async (bound, s) => {
        const d = s.view?.knobs.find(k => k.name === name);
        if (!d) throw new Error("That behavior control is unavailable.");
        const v = valueFor(d, value);
        s.view = logic(await job(bound, s, "bot_logic", { values: { [name]: v } }), bound);
        confirmValue(d, s.view.knobs.find(k => k.name === name)?.value, v);
      }, scope);
    }
    function setMod(op, value, scope = target?.scope) {
      return act(async (bound, s) => {
        const d = definitions(bound.title).find(row => row.op === op);
        if (!d || !available(bound.title, s.status, d)) throw new Error("That mod is unavailable for the current game.");
        const v = valueFor(d, value), extra = d.kind === "bool" ? { on: v } : { multiplier: v, on: v !== 1 };
        const out = await job(bound, s, op, extra);
        verified(out);
        await validate(bound);
        s.status = mods(out.status || await job(bound, s, "status"));
        confirmValue(d, modValue(s.status, d), v);
      }, scope);
    }
    function equip(id, scope = target?.scope) {
      return act(async (bound, s) => {
        const w = (s.view?.weapons || []).find(x => x.id === id);
        if (!w) throw new Error("That weapon is not in this game's list.");
        s.view = logic(await job(bound, s, "bot_logic", { weapon: id }), bound);
        const r = s.view.weapon_result || {};
        if (r.verified !== true) throw new Error(r.reason || `${w.name} could not be equipped. Refresh current settings.`);
        s.message = r.note || `${w.name} equipped.`; s.ok = true;
      }, scope);
    }
    const reset = (scope = target?.scope) => act(async (bound, s) => {
      s.view = logic(await job(bound, s, "bot_logic", { reset: true }), bound);
    }, scope);
    function toggle(force) {
      if (disposed) return;
      open = force ?? !open;
      panel?.classList.toggle("open", open); tab?.classList.toggle("open", open);
      paint();
      if (open && !state.view) return refresh();
    }
    let lookedUp = null;                                 // the sid whose live session row was fetched (once per sid)
    function lookup(nextState) {
      // the PiP's own session record can be stale after a MercMode handover or lack the adapter / state fields
      // (2026-10-28: the operator never saw the arrow): the Spark's live session row for the shown sid decides instead
      const sid = nextState.sid;
      if (!api || lookedUp === sid) return;
      lookedUp = sid;
      Promise.resolve(api("/api/sessions?live=1", undefined, "GET")).then(data => {
        const rows = Array.isArray(data) ? data : (data && Array.isArray(data.sessions) ? data.sessions : []);
        const row = rows.find(r => r && r.session_id === sid);
        if (row && eligible(row)) update({ ...nextState, session: row });
      }).catch(() => { if (lookedUp === sid) lookedUp = null; });
    }
    function update(nextState) {
      if (disposed) return;
      ensure();
      const session = nextState?.session;
      const next = nextState?.on && nextState.sid === session?.session_id && eligible(session) ? session : null;
      if (!next && nextState?.on && typeof nextState.sid === "string") lookup(nextState);
      const same = next && target && next.session_id === target.sid && next.game_id === target.gameId
        && next.adapter === target.adapter && workerOf(next) === target.worker && pcOf(next) === target.pc;
      if (!same && (target || next)) {
        target = next ? { sid: next.session_id, worker: workerOf(next), gameId: next.game_id, adapter: next.adapter,
          title: TITLES[next.game_id], pc: pcOf(next), scope: String(++generation) } : null;
        state = empty(); paint();
        if (open && target) refresh();
      }
      // the tab is MercMode's (operator 2026-10-28: "the tab is a mercmode tab. Not just 5 and 6"): on for whatever game
      // the PiP shows; one without live settings says so when opened
      shown = nextState?.on ? (typeof nextState.sid === "string" ? nextState.sid : "pip") : null;   // always in the PiP
      tab?.classList.toggle("ready", !!(target || shown));
      if (tab && !compactOnly) tab.style.display = target || shown ? "block" : "none";
      if (tab && !compactOnly) tab.style.opacity = "1";
      if (!target && !shown && open) toggle(false);
    }
    function dispose() {
      disposed = true; target = null; shown = null; open = false; generation++;
      tab?.remove(); panel?.remove(); style?.remove();
      tab = panel = style = null;
    }
    return { update, toggle, set, setMod, equip, reset, refresh, dispose, state: () => ({ ...state, ...target, open }) };
  }
  const api = { create, html, eligible, definitions };
  root.GBoxBotLogicSidebar = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
