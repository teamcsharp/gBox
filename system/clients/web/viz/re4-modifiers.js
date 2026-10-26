// Session-scoped RE4 (GameCube, Dolphin) modifiers on the worker tool re_mods. Every change is an operator job followed
// by a fresh status read; nothing flips optimistically. Same look as re5-modifiers.js (shared re5-mod-* classes).
(function (root) {
  "use strict";
  const GAMES = ["78ab9efa2e310db4", "e42c9b780c07c437"];          // Resident Evil 4 (USA) Disc 1 / Disc 2
  const TOOL = "re_mods";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  // toggles are the tool's patch names (status reports each as "on" / "off"); numeric ops read back from status unless
  // `local`: the game does not report aim speed or the spawn factor, so the panel keeps the last value it verified
  const DEFINITIONS = [
    { op: "unlimited_health", label: "Unlimited life", field: "unlimited_health", kind: "toggle" },
    { op: "infinite_ammo", label: "Infinite ammo", field: "infinite_ammo", kind: "toggle" },
    { op: "combo_freeze", label: "Combo never ends", field: "combo_freeze", kind: "toggle" },
    { op: "merc_timer_freeze", label: "Freeze Mercenaries timer", field: "merc_timer_freeze", kind: "toggle" },
    { op: "grenade_safe", label: "Hand grenades never hurt Leon", field: "grenade_safe", kind: "toggle" },
    { op: "merc_time_bonus", label: "Time per pickup", field: "merc_time_bonus_x", kind: "multiplier", param: "multiplier", min: 1, max: 10, step: 0.5 },
    { op: "combo_time", label: "Combo window", field: "merc_combo_window_x", kind: "multiplier", param: "multiplier", min: 1, max: 10, step: 0.5 },
    { op: "aim_turn_speed", label: "Aim turn speed", field: "aim_turn_speed_x", kind: "multiplier", param: "multiplier", min: 0.5, max: 5, step: 0.25,
      local: true, result: "aim_turn_speed_x" },
    { op: "spawn_multiplier", label: "Enemies", field: "spawn_x", kind: "count", param: "count", min: 1, max: 4, step: 1, local: true, result: "factor" },
  ];
  const ACTIONS = [
    { id: "random", op: "random_loadout", label: "Random weapon now", input: { character: "leon", damage: 99.9, on: true },
      note: "A random gun at 99.9× damage replaces Leon's Mercenaries loadout; it equips about 5 s into the next run." },
    // merc_loadout reset=true is the tool's "game default" loadout; random_loadout on=false would still draw a random gun
    { id: "reset", op: "merc_loadout", label: "Reset weapons", input: { character: "leon", reset: true },
      note: "Back to the game's own Mercenaries loadout for Leon from the next run." },
    { id: "unlock", op: "mercenaries_unlock", label: "Unlock Mercenaries", input: { on: true },
      note: "Every Mercenaries character and stage; the menus rebuild when the title menu opens." },
  ];
  // re_mods raises Unsupported ("re_mods: X is not located in <release> yet", "re_mods: Resident Evil 4 on GameCube / Wii
  // so far") and ValueError("op: status | list | ...") for an op this build cannot do; a transient failure ("the game did
  // not run the request (paused...)") must not retire the control
  const UNSUPPORTED = /not located in|not supported|unsupported|^op: |^re_mods:/i;

  function eligible(session) {
    return !!session && GAMES.includes(session.game_id) && session.state === "running" && !session.stopping
      && session.adapter === "dolphin" && typeof session.session_id === "string" && session.session_id.includes("-");
  }
  function value(status, def) {             // patch_state / grenade_safe_state: "on" | "off" | "unknown (...)" | "mixed"
    const raw = status?.[def?.field];
    return raw === true || raw === "on" ? true : raw === false || raw === "off" ? false : null;
  }
  function amount(state, def) {
    const raw = def.local ? state.applied?.[def.field] : state.status?.[def.field];
    return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  }
  function capability(state, def) {
    const retired = state.unsupported?.[def.op];
    if (retired) return { available: false, reason: retired };
    if (!state.status || typeof state.status !== "object") return { available: false, reason: "" };
    if (def.local) return { available: true, reason: "" };
    if (!(def.field in state.status)) return { available: false, reason: `This game build does not report ${def.field}; not available here.` };
    if (def.kind === "toggle" && value(state.status, def) === null)
      return { available: false, reason: `Unexpected code at the patch site (${state.status[def.field]}); not changing it.` };
    if (def.kind !== "toggle" && amount(state, def) === null) return { available: false, reason: "Current value unavailable." };
    return { available: true, reason: "" };
  }
  function rows(state = {}) {
    const locked = state.busy || state.pending || state.stale;
    return DEFINITIONS.map(def => {
      const cap = capability(state, def);
      return { ...def, on: def.kind === "toggle" ? value(state.status, def) : null,
        value: def.kind === "toggle" ? null : amount(state, def), ...cap, disabled: !!(locked || !cap.available) };
    });
  }
  function actions(state = {}) {
    const locked = state.busy || state.pending || state.stale;
    return ACTIONS.map(act => { const reason = state.unsupported?.[act.op] || ""; return { ...act, reason, disabled: !!(locked || reason) }; });
  }
  // What this game keeps across reloads (operator 2026-10-26: "retain those settings across reloads"): every confirmed
  // change here is saved per game on the control plane (gbox/game_prefs.py) and put back on new sessions; the bots'
  // packages then keep it instead of their defaults. The panel shows the saved value beside the live one.
  function savedText(op, kept) {
    if (!kept || typeof kept !== "object") return "";
    if (op === "loadout") return kept.mode === "random" ? "Random weapon (99.9× damage)" : "The game's own weapons";
    if (op === "mercenaries_unlock") return "Mercenaries unlocked";
    const def = DEFINITIONS.find(row => row.op === op), label = def?.label || op;
    if (def?.kind === "toggle") return `${label} ${kept.on ? "on" : "off"}`;
    if (def?.kind === "count") return kept.on && kept.count > 1 ? `${label} ×${kept.count}` : `${label}: normal`;
    return kept.on ? `${label} ×${kept.multiplier}` : `${label}: the game's own`;
  }
  function savedDiffers(def, kept, state) {
    if (!kept) return false;
    if (def.kind === "toggle") { const live = value(state.status, def); return live !== null && live !== !!kept.on; }
    const live = amount(state, def), want = def.kind === "count" ? (kept.on ? kept.count : 1) : (kept.on ? kept.multiplier : 1);
    return live !== null && typeof want === "number" && Math.abs(live - want) > 0.011;
  }
  function savedState(entry) {
    return entry?.state === "failed" ? `not on this session yet: ${entry.reason || "retrying"}`
      : entry?.state === "applied" ? "applied to this session" : "being applied to this session";
  }
  function savedLine(state) {
    const saved = state.saved;
    if (!saved) return "";
    const names = Object.keys(saved.settings || {});
    if (!names.length) return "Changes confirmed here are kept for this game: they come back after reloads, relaunches and restarts.";
    const failed = names.filter(op => saved.applied?.[op]?.state === "failed");
    const pending = names.filter(op => saved.applied?.[op]?.state !== "applied");
    const tail = saved.receives?.re_mods === false ? " Agent test sessions and paused games keep their own setup."
      : failed.length ? ` Not on this session yet: ${failed.map(op => savedText(op, saved.settings[op])).join(", ")} (${saved.applied[failed[0]].reason || "retrying"}).`
      : pending.length ? " Being applied to this session…" : " Applied to this session.";
    return `Saved for this game: ${names.map(op => savedText(op, saved.settings[op])).filter(Boolean).join(" · ")}.${tail}`;
  }
  function vitals(status) {
    if (!status || typeof status !== "object") return "Waiting for the game's status.";
    const parts = [];
    if (Number.isFinite(status.hp)) parts.push(`HP ${status.hp}`);
    if (status.room) parts.push(`room ${status.room}`);
    if (Number.isFinite(status.merc_seconds_left)) parts.push(`${status.merc_seconds_left} s left`);
    if (Number.isFinite(status.merc_combo)) parts.push(`combo ${status.merc_combo}`);
    return parts.join(" · ") || "No vitals reported.";
  }
  function html(state = {}) {
    const keepNote = row => {
      const kept = state.saved?.settings?.[row.op];
      return kept && savedDiffers(row, kept, state) ? `Saved: ${savedText(row.op, kept)} (${savedState(state.saved.applied?.[row.op])})` : "";
    };
    const controls = rows(state).map(row => {
      if (row.kind === "toggle") {
        const detail = [(!row.available && row.reason) || (row.on === null ? "State unavailable" : ""), keepNote(row)]
          .filter(Boolean).join(" · ");
        return `<label class="re5-mod-row"><span>${ESC(row.label)}${detail ? `<small>${ESC(detail)}</small>` : ""}</span>`
          + `<input type="checkbox" data-re4-mod="${row.op}" aria-label="${ESC(row.label)}" `
          + `aria-checked="${row.on === null ? "mixed" : row.on}" ${row.on ? "checked " : ""}${row.disabled ? "disabled" : ""}></label>`;
      }
      const setting = row.value ?? 1;
      const detail = [(!row.available && row.reason) || (!row.local ? `Current: ×${setting}`
        : row.value === null ? "Not read back from the game; 1 = the game's own." : "Last value set here; the game does not report it."),
        keepNote(row)].filter(Boolean).join(" · ");
      return `<div class="re5-mod-slider"><label>${ESC(row.label)}: <output data-re4-value="${row.op}">×${setting}</output>`
        + `<small class="re4-mod-note">${ESC(detail)}</small>`
        + `<input type="range" data-re4-range="${row.op}" aria-label="${ESC(row.label)} multiplier" min="${row.min}" max="${row.max}" `
        + `step="${row.step}" value="${setting}" ${row.disabled ? "disabled" : ""}></label></div>`;
    }).join("");
    const acts = actions(state);
    const buttons = `<div class="re4-mod-actions">` + acts.map(act => `<button type="button" class="act" data-re4-action="${act.id}" `
      + `title="${ESC(act.reason || act.note)}" ${act.disabled ? "disabled" : ""}>${ESC(act.label)}</button>`).join("") + `</div>`
      + acts.filter(act => act.reason).map(act => `<p class="re5-mod-sub re5-mod-error">${ESC(act.label)}: ${ESC(act.reason)}</p>`).join("")
      + `<p class="re5-mod-sub">Loadout changes apply when the next Mercenaries run starts; unlocks rebuild the menus at the title screen.</p>`;
    return `<div class="re5-mod-heading"><b>RE4 modifiers</b><button type="button" class="act" data-re4-refresh `
      + `${state.busy ? "disabled" : ""}>Refresh</button></div>`
      + `<p class="re5-mod-sub" data-re4-vitals>${ESC(vitals(state.status))}</p>`
      + (state.saved ? `<p class="re5-mod-sub re5-mod-saved" data-re4-saved>${ESC(savedLine(state))}</p>` : "")
      + controls + buttons
      + `<p class="re5-mod-status${state.error ? " re5-mod-error" : ""}" role="${state.error ? "alert" : "status"}" aria-live="polite">`
      + `${ESC(state.message || "Read current settings from the game.")}</p>`;
  }

  function create({ session, api, render = () => {}, delay = ms => new Promise(r => setTimeout(r, ms)), now = Date.now,
                    savedPrefs = null }) {
    const sid = session?.session_id, worker = String(sid || "").split("-")[0];
    const state = { status: null, applied: {}, unsupported: {}, busy: false, pending: null, stale: true,
      message: "Reading current settings…", error: false, saved: null };
    let disposed = false;
    const snapshot = () => ({ ...state, applied: { ...state.applied }, unsupported: { ...state.unsupported } });
    // savedPrefs(): GET /api/sessions/{sid}/game-prefs (gbox/game_prefs.py); a failed read keeps the live values only
    async function loadSaved() {
      if (typeof savedPrefs !== "function" || disposed) return;
      try {
        const v = await savedPrefs();
        state.saved = v && typeof v === "object" && v.panels && typeof v.panels === "object" && !Array.isArray(v)
          ? { settings: v.panels.re_mods || {}, applied: v.applied?.re_mods || {}, receives: v.receives || {} } : null;
      } catch { /* saved settings are extra information; the game's own status still shows */ }
    }
    const paint = () => { if (!disposed) render(snapshot()); };
    const alive = () => { if (disposed) throw new Error("Modifier panel closed."); };
    async function currentSession() {
      alive();
      if (!eligible(session)) throw new Error("Open a running RE4 GameCube session to change game controls.");
      const sessions = await api("/api/sessions?include_ended=false", undefined, "GET", 15000);
      const current = Array.isArray(sessions) && sessions.find(s => s.session_id === sid);
      if (!eligible(current) || current.game_id !== session.game_id) throw new Error("This RE4 session has ended or changed. Reopen its controls.");
      alive();
    }
    async function finish(job) {
      const deadline = now() + 120000;
      while (["queued", "running"].includes(job?.state)) {
        if (!job.id) throw new Error("Server did not return a job ID.");
        state.pending = job.id;
        if (now() >= deadline) throw new Error("The modifier job is still running. Refresh to check its result.");
        await delay(600);
        job = await api("/api/jobs/" + encodeURIComponent(job.id), undefined, "GET", 15000);
      }
      state.pending = null;
      if (job?.state !== "succeeded") throw new Error(job?.error?.message || job?.error || job?.progress?.msg || "Modifier job did not succeed.");
      const result = job.output?.result;
      if (!result || typeof result !== "object") throw new Error("Server returned no modifier result.");
      return result;
    }
    async function job(op, extra = {}) {
      alive();
      const submitted = await api("/api/jobs", { tool: TOOL, agent_use: false, require_worker: worker,
        input: { session_id: sid, op, ...extra } }, "POST", 15000);
      return finish(submitted);
    }
    async function read(saved = true) {
      const result = await job("status");
      if (!result.status || typeof result.status !== "object") throw new Error("Current modifier state is unavailable.");
      state.status = result.status; state.stale = false;
      if (saved) await loadSaved();
      return result.status;
    }
    async function preflight() {
      await currentSession();
      if (state.pending) await finish(await api("/api/jobs/" + encodeURIComponent(state.pending), undefined, "GET", 15000));
      // A panel reopened while a previous request is running must not send a second mutation.
      const active = await api("/api/jobs?state=queued,running&limit=500", undefined, "GET", 15000);
      const pending = Array.isArray(active) && active.find(j => j.tool === TOOL && j.input?.session_id === sid);
      if (pending) {
        state.pending = pending.id;
        throw new Error("A modifier job is already running for this session. Refresh to check it.");
      }
    }
    function failed(op, error) {
      state.error = true; state.message = error.message;
      if (UNSUPPORTED.test(error.message)) state.unsupported[op] = error.message;   // this build cannot do the op: keep it disabled
      if (!state.pending) state.stale = true;
    }
    async function refresh() {
      if (state.busy || disposed) return;
      state.busy = true; state.error = false; state.message = "Reading current settings…"; paint();
      // the saved settings show at once, while the game itself is still being read on its PC
      const saved = loadSaved().then(() => { if (state.busy && !disposed) paint(); });
      try {
        await preflight(); await read(false); await saved;
        const retired = Object.keys(state.unsupported).length;
        state.message = retired ? "Settings read. Controls this game build cannot do stay disabled with the tool's reason."
          : "Settings read from the running game.";
      } catch (error) { state.stale = true; state.error = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function change(op, wanted) {
      const def = DEFINITIONS.find(row => row.op === op && row.kind === "toggle");
      if (!def || typeof wanted !== "boolean" || state.busy || state.pending || state.stale || disposed || !capability(state, def).available) return;
      state.busy = true; state.error = false; state.message = "Applying change…"; paint();
      try {
        await preflight();
        const result = await job(op, { on: wanted });
        await read();                                   // only the game's fresh status changes a switch
        if (result.verified !== true) throw new Error(result.reason || "The game did not verify this change.");
        if (value(state.status, def) !== wanted) throw new Error("The game did not confirm the requested setting.");
        state.message = `${def.label} ${wanted ? "enabled" : "disabled"}.`;
      } catch (error) { failed(op, error); }
      finally { state.busy = false; paint(); }
    }
    async function setValue(op, requested) {
      const def = DEFINITIONS.find(row => row.op === op && row.kind !== "toggle"), number = Number(requested);
      if (!def || !Number.isFinite(number) || number < def.min || number > def.max || def.kind === "count" && !Number.isInteger(number)
          || state.busy || state.pending || state.stale || disposed || !capability(state, def).available) return;
      state.busy = true; state.error = false; state.message = "Applying value…"; paint();
      try {
        await preflight();
        const result = await job(op, def.kind === "count" ? { on: number > 1, count: number } : { on: true, multiplier: number });
        await read();
        const actual = def.local ? result[def.result] : state.status[def.field];
        if (result.verified !== true || typeof actual !== "number" || !Number.isFinite(actual) || Math.abs(actual - number) > 0.011)
          throw new Error(result.reason || "The game did not confirm the requested value.");
        if (def.local) state.applied[def.field] = number;
        state.message = def.kind !== "count" ? `${def.label}: ×${number}.` : number > 1
          ? `Enemies ×${number}: every spawn gets ${number - 1} extra ${number > 2 ? "copies" : "copy"}.` : "Normal enemy spawns restored.";
      } catch (error) { failed(op, error); }
      finally { state.busy = false; paint(); }
    }
    async function action(id) {
      const act = ACTIONS.find(row => row.id === id);
      if (!act || state.busy || state.pending || state.stale || disposed || state.unsupported[act.op]) return;
      state.busy = true; state.error = false; state.message = `${act.label}…`; paint();
      try {
        await preflight();
        const result = await job(act.op, act.input);
        await read();
        if (result.verified !== true) throw new Error(result.reason || `${act.label}: the game did not verify the change.`);
        const names = list => Array.isArray(list) ? list.join(", ") : "";
        state.message = act.id === "random" ? `Next Mercenaries run: ${names(result.picked) || "a random gun"} at 99.9× damage, equipped about 5 s in.`
          : act.id === "reset" ? "Leon's Mercenaries loadout is the game's own again from the next run."
          : `Mercenaries unlocked: ${names(result.unlocked?.characters) || "all characters"}; ${names(result.unlocked?.stages) || "all stages"}. `
            + "Menus rebuild when the title menu opens.";
      } catch (error) { failed(act.op, error); }
      finally { state.busy = false; paint(); }
    }
    return { refresh, change, setValue, action, state: snapshot, stop: () => { disposed = true; } };
  }

  const CSS = `.re4-modifiers{display:block!important;height:auto!important;overflow:visible;border-top:1px solid var(--line,#444);margin-top:5px;padding:9px 4px 2px;min-width:min(300px,calc(100vw - 48px));max-width:400px}
    .re5-mod-heading,.re5-mod-row{display:flex;align-items:center;justify-content:space-between;gap:16px}.re5-mod-heading b{white-space:nowrap}.re5-mod-heading .act{font-size:11px;width:auto!important;flex:none;text-align:center!important}
    .re5-mod-row{padding:7px 0;font-size:13px}.re5-mod-row small{display:block;max-width:280px;font-size:11px;color:var(--mut,#aaa);margin-top:3px}
    .re5-mod-row input{accent-color:var(--pri,#8da7ff);width:17px;height:17px;flex:none;cursor:pointer}.re5-mod-row input:disabled{cursor:default;opacity:.55}
    .re5-mod-sub,.re5-mod-status{font-size:11px;line-height:1.45;margin:5px 0;color:var(--mut,#aaa)}.re5-mod-status{max-width:350px;overflow-wrap:anywhere;min-height:16px}
    .re5-mod-error{color:var(--bad,#f99)}
    .re5-mod-slider{font-size:11px;padding-bottom:5px}.re5-mod-slider label{display:block}.re5-mod-slider input{display:block;width:100%;accent-color:var(--pri,#8da7ff)}
    .re4-mod-note{display:block;font-size:11px;color:var(--mut,#aaa);margin-top:2px}
    .re4-mod-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}.re4-mod-actions .act{width:100%!important;font-size:11px;text-align:center!important;white-space:normal}
    .re4-modifiers button:disabled{opacity:.55;cursor:default}`;
  function mount(host, options) {
    if (!host) return null;
    const ctl = create({ ...options, render: state => { host.innerHTML = html(state); } });
    host.innerHTML = html(ctl.state());
    host.onchange = event => {
      if (event.target.matches?.("[data-re4-range]")) { ctl.setValue(event.target.dataset.re4Range, event.target.value); return; }
      const input = event.target.closest?.("[data-re4-mod]");
      if (!input || input.disabled) return;
      const wanted = input.checked;
      input.checked = value(ctl.state().status, DEFINITIONS.find(row => row.op === input.dataset.re4Mod)) === true;
      ctl.change(input.dataset.re4Mod, wanted);
    };
    host.oninput = event => {
      if (!event.target.matches?.("[data-re4-range]")) return;
      const out = host.querySelector(`[data-re4-value="${event.target.dataset.re4Range}"]`);
      if (out) out.textContent = "×" + event.target.value;
    };
    host.onclick = event => {
      const button = event.target.closest?.("[data-re4-action]");
      if (button && !button.disabled) ctl.action(button.dataset.re4Action);
      if (event.target.closest?.("[data-re4-refresh]") && !event.target.disabled) ctl.refresh();
    };
    ctl.refresh();
    return ctl;
  }
  const api = { GAMES, TOOL, DEFINITIONS, ACTIONS, eligible, value, capability, rows, actions, vitals, html, create, mount,
    savedText, savedLine,
    sectionHTML: () => `<style>${CSS}</style><section class="re4-modifiers" aria-label="RE4 modifiers"></section>` };
  root.GBoxRE4Modifiers = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
