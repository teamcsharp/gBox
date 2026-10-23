// Session-scoped RE5 modifiers. Every change is an operator job, followed by a fresh server status read.
(function (root) {
  "use strict";
  const GAME = "e7ca89bbeb67360d";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const DEFINITIONS = [
    { op: "unlimited_health", label: "Unlimited life", field: "unlimited_health" },
    { op: "infinite_ammo", label: "Infinite ammo", field: "infinite_ammo" },
    { op: "fire_rate", label: "Rapid fire", field: "fire_rate_x", multiplier: 80 },
    { op: "bullet_damage", label: "High damage", field: "bullet_damage_x", multiplier: 10 },
    { op: "turn_speed", label: "Faster turning and aiming", field: "turn_speed_x", multiplier: 3 },
    // on / off only: the worker keeps its range (default a random 2-5 s per kill), so a toggle never resets it
    { op: "kill_time", label: "Time added per kill", field: "kill_time_on",
      note: status => `Random ${status?.kill_time_range || "2-5"} s per kill` },
  ];
  const UNAVAILABLE = [
    { op: "aimbot", label: "Aimbot" }, { op: "instant_qte", label: "Instant QTE completion" },
    { op: "auto_parry", label: "Auto-parry" }, { op: "knife_knockback", label: "Knife knockback" },
  ];
  function eligible(session) {
    return session?.game_id === GAME && session.state === "running" && !session.stopping
      && session.adapter === "rpcs3" && typeof session.session_id === "string" && session.session_id.includes("-");
  }
  function capability(status, op) {
    const cap = status?.capabilities?.[op];
    const known = op === "random_weapon" || DEFINITIONS.some(row => row.op === op);
    return { available: cap?.available === true,
      reason: cap?.reason || (!cap && known ? "Worker update pending; this control is unavailable." : "") };
  }
  function value(status, definition) {
    if (!definition) return null;
    const raw = status?.[definition.field];
    return definition.multiplier ? (typeof raw === "number" && Number.isFinite(raw) ? raw > 1 : null)
      : typeof raw === "boolean" ? raw : null;
  }
  function rows(state) {
    return DEFINITIONS.map(def => {
      const on = value(state.status, def), cap = capability(state.status, def.op);
      return { ...def, on, ...cap, disabled: state.busy || state.pending || state.weaponPending || state.stale || !cap.available || on === null };
    });
  }
  function html(state = {}) {
    const controls = rows(state).map(row => {
      const raw = state.status?.[row.field];
      const detail = row.reason || (row.on === null ? "State unavailable" : row.multiplier && row.on ? `Current setting: ${row.unit ? raw + row.unit : "×" + raw}`
        : row.note && row.on ? row.note(state.status) : "");
      return `<label class="re5-mod-row"><span>${ESC(row.label)}${detail ? `<small>${ESC(detail)}</small>` : ""}</span>`
        + `<input type="checkbox" data-re5-mod="${row.op}" aria-label="${ESC(row.label)}" `
        + `aria-checked="${row.on === null ? "mixed" : row.on}" ${row.on ? "checked " : ""}${row.disabled ? "disabled" : ""}></label>`;
    }).join("");
    // These hooks have no verified UI action yet, even if a newer worker advertises a future capability.
    const unavailable = UNAVAILABLE.map(row => `<div class="re5-mod-row re5-mod-unavailable"><span>${row.label}`
      + `<small>${ESC(capability(state.status, row.op).reason || "Unavailable: no verified live control")}</small></span>`
      + `<span>Unavailable</span></div>`).join("");
    const random = capability(state.status, "random_weapon"), weapon = state.status?.in_hand?.weapon;
    return `<div class="re5-mod-heading"><b>RE5 modifiers</b><button type="button" class="act" data-re5-refresh `
      + `${state.busy ? "disabled" : ""}>Refresh</button></div><p class="re5-mod-sub">This running session${weapon ? ` · ${ESC(weapon)}` : ""}</p>`
      + controls + `<button class="act re5-mod-random" type="button" data-re5-random `
      + `${state.busy || state.pending || state.weaponPending || state.stale || !random.available ? "disabled" : ""}>Random available weapon</button>`
      + `<p class="re5-mod-sub">${ESC(random.reason || "Equips an eligible gun already in the inventory. Rockets and sniper rifles are excluded.")}</p>`
      + `<details class="re5-mod-extra"><summary>Other requested modifiers</summary>${unavailable}</details>`
      + `<p class="re5-mod-status${state.error ? " re5-mod-error" : ""}" role="${state.error ? "alert" : "status"}" aria-live="polite">`
      + `${ESC(state.message || "Read current settings from the game.")}</p>`;
  }

  function create({ session, api, render = () => {}, delay = ms => new Promise(r => setTimeout(r, ms)), now = Date.now }) {
    const sid = session?.session_id, worker = String(sid || "").split("-")[0];
    let state = { status: null, busy: false, pending: null, weaponPending: null, stale: true, message: "Reading current settings…", error: false };
    let disposed = false;
    const paint = () => { if (!disposed) render({ ...state }); };
    const alive = () => { if (disposed) throw new Error("Modifier panel closed."); };
    async function currentSession() {
      alive();
      if (!eligible(session)) throw new Error("Open a running RE5 RPCS3 session to change modifiers.");
      const sessions = await api("/api/sessions?include_ended=false", undefined, "GET", 15000);
      const current = Array.isArray(sessions) && sessions.find(s => s.session_id === sid);
      if (!eligible(current)) throw new Error("This RE5 session has ended or changed. Reopen its controls.");
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
      const submitted = await api("/api/jobs", { tool: "re5_mods", agent_use: false, require_worker: worker,
        input: { session_id: sid, op, ...extra } }, "POST", 15000);
      return finish(submitted);
    }
    async function read() {
      const result = await job("status");
      if (!result.status || typeof result.status !== "object") throw new Error("Current modifier state is unavailable.");
      state.status = result.status;
      state.weaponPending = result.status.random_weapon_request?.state === "pending" ? result.status.random_weapon_request.id : null;
      state.stale = false;
      return result.status;
    }
    async function preflight() {
      await currentSession();
      if (state.pending) {
        await finish(await api("/api/jobs/" + encodeURIComponent(state.pending), undefined, "GET", 15000));
      }
      // A panel reopened while a previous request is running must not send a second mutation.
      const active = await api("/api/jobs?state=queued,running&limit=500", undefined, "GET", 15000);
      const pending = Array.isArray(active) && active.find(j => j.tool === "re5_mods" && j.input?.session_id === sid);
      if (pending) {
        state.pending = pending.id;
        throw new Error("A modifier job is already running for this session. Refresh to check it.");
      }
    }
    async function refresh() {
      if (state.busy || disposed) return;
      state.busy = true; state.error = false; state.message = "Reading current settings…"; paint();
      try {
        await preflight(); await read();
        state.message = state.weaponPending ? "Weapon switch is still pending. Refresh to check its result."
          : DEFINITIONS.every(def => capability(state.status, def.op).available)
            ? "Settings read from the running game. Choices are kept for this session."
            : "Settings read. Unavailable controls show their status below.";
      } catch (error) { state.stale = true; state.error = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function change(op, wanted) {
      if (state.busy || state.pending || state.weaponPending || state.stale || disposed) return;
      const def = DEFINITIONS.find(row => row.op === op);
      const random = op === "random_weapon";
      const cap = capability(state.status, op);
      if ((!def && !random) || !cap.available || (!random && (typeof wanted !== "boolean" || value(state.status, def) === null))) return;
      state.busy = true; state.error = false; state.message = random ? "Selecting an available weapon…" : "Applying change…"; paint();
      try {
        await preflight();
        const extra = random ? {} : { on: wanted, ...(def.multiplier && wanted ? { multiplier: def.multiplier } : {}) };
        const result = await job(op, extra);
        let confirmed = result.verified === true;
        if (random && result.queued === true) {
          const id = result.request?.id, deadline = now() + 45000;
          if (!id) throw new Error("Server queued no identifiable weapon request.");
          state.weaponPending = id;
          do {
            await read();                              // queue acceptance is never reported as an equipped weapon
            const request = state.status.random_weapon_request;
            if (request?.id === id && request.state === "confirmed") { confirmed = true; break; }
            if (request?.id === id && request.state === "rejected") throw new Error(request.reason || "The bot rejected the weapon switch.");
            if (now() >= deadline) throw new Error("The weapon switch was not confirmed in time. Refresh to check its result.");
            state.weaponPending = id;
            await delay(700);
          } while (true);
        } else await read();                           // only the game's fresh status changes a switch
        if (!confirmed) throw new Error(result.reason || result.note || "The game did not verify this change.");
        if (!random && value(state.status, def) !== wanted) throw new Error("The game did not confirm the requested setting.");
        state.message = random ? `Equipped ${state.status.in_hand?.weapon || "the selected available weapon"}.`
          : `${def.label} ${wanted ? "enabled" : "disabled"}.`;
      } catch (error) {
        state.error = true; state.message = error.message;
        if (!state.pending && !state.weaponPending) state.stale = true;
      } finally { state.busy = false; paint(); }
    }
    return { refresh, change, state: () => ({ ...state }), stop: () => { disposed = true; } };
  }

  const CSS = `.re5-modifiers{border-top:1px solid var(--line,#444);margin-top:5px;padding:9px 4px 2px;min-width:min(300px,calc(100vw - 48px));max-width:400px}
    .re5-mod-heading,.re5-mod-row{display:flex;align-items:center;justify-content:space-between;gap:16px}.re5-mod-heading .act{font-size:11px}
    .re5-mod-row{padding:7px 0;font-size:13px}.re5-mod-row small{display:block;max-width:280px;font-size:11px;color:var(--mut,#aaa);margin-top:3px}
    .re5-mod-row input{accent-color:var(--pri,#8da7ff);width:17px;height:17px;flex:none;cursor:pointer}.re5-mod-row input:disabled{cursor:default;opacity:.55}
    .re5-mod-sub,.re5-mod-status{font-size:11px;line-height:1.45;margin:5px 0;color:var(--mut,#aaa)}.re5-mod-status{max-width:350px;overflow-wrap:anywhere;min-height:16px}
    .re5-mod-error{color:var(--bad,#f99)}.re5-mod-random{width:100%;margin-top:6px}.re5-mod-extra{margin-top:8px;font-size:11px}
    .re5-mod-extra summary{cursor:pointer}.re5-mod-unavailable{font-size:11px}.re5-mod-unavailable>span:last-child{color:var(--mut,#aaa)}
    .re5-modifiers button:disabled{opacity:.55;cursor:default}`;
  function mount(host, options) {
    if (!host) return null;
    const ctl = create({ ...options, render: state => { host.innerHTML = html(state); } });
    host.innerHTML = html(ctl.state());
    host.onchange = event => {
      const input = event.target.closest?.("[data-re5-mod]");
      if (!input || input.disabled) return;
      const wanted = input.checked;
      input.checked = value(ctl.state().status, DEFINITIONS.find(row => row.op === input.dataset.re5Mod)) === true;
      ctl.change(input.dataset.re5Mod, wanted);
    };
    host.onclick = event => {
      if (event.target.closest?.("[data-re5-refresh]") && !event.target.disabled) ctl.refresh();
      if (event.target.closest?.("[data-re5-random]") && !event.target.disabled) ctl.change("random_weapon");
    };
    ctl.refresh();
    return ctl;
  }
  const api = { GAME, DEFINITIONS, eligible, capability, rows, html, create, mount,
    sectionHTML: () => `<style>${CSS}</style><section class="re5-modifiers" aria-label="RE5 modifiers"></section>` };
  root.GBoxRE5Modifiers = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
