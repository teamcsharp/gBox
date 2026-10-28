// Session-scoped RE6 (Switch) modifiers: the weapon the bot fights with (operator 2026-10-27 18:00: "a dropdown list of all
// the weapons in the game and i am able to have them instantly use that weapon to battle in the round") and the RE6
// Switch mods. Every change is an operator job (tool re5_mods, routed to gbox.mercs.titles.re6_switch_mods for an RE6
// Switch session), followed by a fresh status read; nothing flips optimistically. A gun loaded this round is switched to
// at once (the game's own weapon switch); one that is not goes into every loadout for the next round, and the panel says
// so. The RE5 panel's Team and training controls (split screen) mount below, as before.
(function (root) {
  "use strict";
  const RE6_SWITCH = "115f9cdbba115432", ADAPTERS = ["citron", "eden"];
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const RE5 = root.GBoxRE5Modifiers || (typeof require === "function" ? (() => { try { return require("./re5-modifiers.js"); } catch { return null; } })() : null);
  const TOGGLES = [
    { op: "infinite_ammo", label: "Infinite ammo", field: "infinite_ammo" },
    { op: "infinite_tablets", label: "Infinite tablets", field: "infinite_tablets" },
    { op: "infinite_stamina", label: "Infinite stamina (combat gauge)", field: "infinite_stamina" },
    { op: "infinite_grenades", label: "Infinite grenades and remote bombs", field: "infinite_grenades" },
    { op: "auto_qte", label: "The game's QTE assist", field: "auto_qte" },
    { op: "kill_time", label: "Time added per kill", field: "kill_time_on" },
  ];
  const MULTIPLIERS = [
    { op: "fire_rate", label: "Fire rate", field: "fire_rate_x", min: 1, max: 80 },
    { op: "magnum_speed", label: "Magnum fire and recoil speed", field: "magnum_speed_x", min: 1, max: 6 },
    { op: "throw_speed", label: "Grenade throw speed", field: "throw_speed_x", min: 1, max: 20 },
    { op: "quick_attack", label: "Quick attack speed", field: "quick_attack_x", min: 1, max: 10 },
    { op: "down_fire", label: "Fire rate while down", field: "down_fire_x", min: 1, max: 10 },
  ];
  const BOT = [
    { key: "aim_lock", label: "RAM aim lock" },
    { key: "nades", label: "Grenades (flash, hand, incendiary)" },
    { key: "flash", label: "Flash grenades" },
    { key: "bomb_drop", label: "Drop a bomb when surrounded" },
  ];
  const CSS = `.re6-modifiers fieldset{border:1px solid var(--line,#444);border-radius:6px;margin:6px 0;padding:6px}
.re6-modifiers label{display:flex;gap:6px;align-items:center;margin:3px 0}.re6-mod-sub{opacity:.75;font-size:12px;margin:3px 0}
.re6-modifiers select{max-width:100%}`;

  function eligible(session) {
    return session?.game_id === RE6_SWITCH && ADAPTERS.includes(session.adapter) && session.state === "running"
      && !session.stopping && typeof session.session_id === "string" && session.session_id.includes("-");
  }
  function weaponLabel(w) {
    return `${w.name} (${w.kind})${w.loaded ? " - loaded" : " - next round"}`;
  }
  function html(state = {}) {
    const st = state.status || {}, locked = !!(state.busy || state.pending || !state.status);
    const dis = locked ? "disabled" : "";
    const weapons = (state.weapons || []).filter(w => w.kind !== "melee" || w.loaded);
    const want = st.bot?.want_weapon;
    const options = weapons.map(w => `<option value="${w.id}" ${w.loaded && w.wheel_index === want ? "selected" : ""}>${ESC(weaponLabel(w))}</option>`).join("");
    const weapon = `<fieldset ${dis}><legend>Weapon in his hands</legend>`
      + `<label><select data-re6-weapon aria-label="Weapon">${options || "<option>Weapons unavailable</option>"}</select>`
      + `<button type="button" class="act" data-re6-weapon-use>Use now</button></label>`
      + `<p class="re6-mod-sub">A loaded gun is switched to at once; any other goes into the next round's loadout.`
      + `${st.next_weapon ? " Next round: " + ESC(st.next_weapon) + "." : ""}</p>`
      + (state.weaponNote ? `<p class="re6-mod-sub" data-re6-weapon-note>${ESC(state.weaponNote)}</p>` : "") + `</fieldset>`;
    const toggles = `<fieldset ${dis}><legend>Mods</legend>` + TOGGLES.map(t =>
      `<label><input type="checkbox" data-re6-mod="${t.op}" ${st[t.field] ? "checked" : ""}> ${ESC(t.label)}</label>`).join("")
      + MULTIPLIERS.map(m => {
        const v = Number(st[m.field] ?? 1);
        return `<label>${ESC(m.label)} <input type="number" data-re6-x="${m.op}" min="${m.min}" max="${m.max}" step="0.5" value="${Number.isFinite(v) ? v : 1}"> times</label>`;
      }).join("") + `</fieldset>`;
    const bot = `<fieldset ${dis}><legend>The bot</legend>` + BOT.map(b =>
      `<label><input type="checkbox" data-re6-bot="${b.key}" ${st.bot?.[b.key] ? "checked" : ""}> ${ESC(b.label)}</label>`).join("") + `</fieldset>`;
    const msg = state.message ? `<p class="re6-mod-sub" data-re6-message>${ESC(state.message)}</p>` : "";
    return weapon + toggles + bot + msg + `<button type="button" class="act" data-re6-refresh ${dis}>Refresh</button>`;
  }
  function create({ session, api, render = () => {}, delay = ms => new Promise(r => setTimeout(r, ms)), now = Date.now }) {
    const sid = session.session_id, worker = session.worker_id || session.worker || undefined;
    const state = { status: null, weapons: [], busy: false, pending: null, message: "", weaponNote: "" };
    let stopped = false;
    const paint = () => { if (!stopped) render(state); };
    async function finish(job) {
      const deadline = now() + 120000;
      while (["queued", "running"].includes(job?.state)) {
        state.pending = job.id;
        if (now() >= deadline) throw new Error("The modifier job is still running. Refresh to check its result.");
        await delay(600);
        job = await api("/api/jobs/" + encodeURIComponent(job.id), undefined, "GET", 15000);
      }
      state.pending = null;
      if (job?.state !== "succeeded") throw new Error(job?.error?.message || job?.error || "Modifier job did not succeed.");
      const result = job.output?.result;
      if (!result || typeof result !== "object") throw new Error("Server returned no modifier result.");
      return result;
    }
    async function job(op, extra = {}) {
      const submitted = await api("/api/jobs", { tool: "re5_mods", agent_use: false, require_worker: worker,
        input: { session_id: sid, op, ...extra } }, "POST", 15000);
      return finish(submitted);
    }
    async function read() {
      const status = await job("status");
      state.status = status.status && typeof status.status === "object" ? status.status : status;
      const list = await job("weapons");
      state.weapons = Array.isArray(list.weapons) ? list.weapons : [];
    }
    async function act(work, done) {
      if (state.busy || stopped) return;
      state.busy = true; state.message = ""; paint();
      try { const out = await work(); if (done) done(out); await read(); }
      catch (error) { state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    return {
      state: () => state,
      refresh: () => act(async () => null),
      useWeapon: id => act(() => job("live_weapon", { weapon: Number(id) }), out => {
        state.weaponNote = out.loaded ? `${out.weapon}: switching to it now.` : `${out.weapon}: not loaded this round - it comes in the next round.`;
      }),
      toggle: (op, on) => act(() => job(op, { on: !!on })),
      multiplier: (op, value) => act(() => job(op, { multiplier: Number(value), on: Number(value) > 1 })),
      bot: (key, on) => act(() => job("bot_options", { [key]: !!on })),
      stop: () => { stopped = true; },
    };
  }
  function mount(host, options) {
    if (!host) return null;
    const mods = host.querySelector("[data-re6-mods]") || host;
    const ctl = create({ ...options, render: state => { mods.innerHTML = html(state); } });
    mods.innerHTML = html(ctl.state());
    mods.onclick = event => {
      if (event.target.closest?.("[data-re6-weapon-use]") && !event.target.disabled)
        ctl.useWeapon(mods.querySelector("[data-re6-weapon]")?.value);
      if (event.target.closest?.("[data-re6-refresh]") && !event.target.disabled) ctl.refresh();
    };
    mods.onchange = event => {
      const t = event.target;
      if (t.matches?.("[data-re6-mod]")) { const want = t.checked; t.checked = !want; ctl.toggle(t.dataset.re6Mod, want); }
      else if (t.matches?.("[data-re6-x]")) ctl.multiplier(t.dataset.re6X, t.value);
      else if (t.matches?.("[data-re6-bot]")) { const want = t.checked; t.checked = !want; ctl.bot(t.dataset.re6Bot, want); }
    };
    const teamHost = host.querySelector?.("[data-re6-team]");
    const team = teamHost && RE5?.panelEligible?.(options.session) ? RE5.mount(teamHost, options) : null;
    const stop = ctl.stop;
    ctl.stop = () => { stop(); team?.stop?.(); };
    ctl.refresh();
    return ctl;
  }
  const api = { RE6_SWITCH, TOGGLES, MULTIPLIERS, BOT, eligible, html, create, mount, weaponLabel,
    sectionHTML: () => `<style>${CSS}</style><section class="re6-modifiers" aria-label="RE6 modifiers"><div data-re6-mods></div>`
      + `<div class="re5-modifiers" data-re6-team></div></section>` };
  root.GBoxRE6Modifiers = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
