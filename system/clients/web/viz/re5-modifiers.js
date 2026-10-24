// Session-scoped RE5 modifiers. Every change is an operator job, followed by a fresh server status read.
(function (root) {
  "use strict";
  const GAME = "e7ca89bbeb67360d";
  const RE6 = "0871eee3b68cdea3";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const DEFINITIONS = [
    { op: "unlimited_health", label: "Unlimited life", field: "unlimited_health" },
    { op: "infinite_ammo", label: "Infinite ammo", field: "infinite_ammo" },
    { op: "fire_rate", label: "Fire rate", field: "fire_rate_x", multiplier: 80, min: 0.1, max: 1000, step: 0.1 },
    { op: "bullet_damage", label: "Bullet damage", field: "bullet_damage_x", multiplier: 10, min: 0.1, max: 1000, step: 0.1 },
    { op: "turn_speed", label: "Turning and aiming speed", field: "turn_speed_x", multiplier: 3, min: 0.25, max: 50, step: 0.25 },
    // on / off only: the worker retains the operator's seconds per kill
    { op: "kill_time", label: "Time added per kill", field: "kill_time_on", min: 0.1, max: 30, step: 0.1,
      note: status => `${String(status?.kill_time_range || "10").includes("-") ? "Random " : ""}${status?.kill_time_range || "10"} s per kill` },
  ];
  const UNAVAILABLE = [
    { op: "aimbot", label: "Aimbot" }, { op: "instant_qte", label: "Instant QTE completion" },
    { op: "auto_parry", label: "Auto-parry" }, { op: "knife_knockback", label: "Knife knockback" },
  ];
  function eligible(session) {
    return session?.game_id === GAME && session.state === "running" && !session.stopping
      && session.adapter === "rpcs3" && typeof session.session_id === "string" && session.session_id.includes("-");
  }
  function panelEligible(session) {
    return eligible(session) || session?.game_id === RE6 && session.state === "running" && !session.stopping
      && session.adapter === "xenia" && typeof session.session_id === "string" && session.session_id.includes("-");
  }
  function replacementSession(sid, history, anchor, resolve) {
    const rows = Array.isArray(history) ? history : [], byId = new Map(rows.map(row => [row.session_id, row]));
    const origin = byId.get(sid) || (anchor?.session_id === sid ? anchor : null);
    const pc = row => String(row?.detail?.worker_name || row?.pc || "").toLowerCase();
    const build = row => String(row?.collection_mod || row?.mod_build || row?.mod || "").split("~")[0];
    const matches = row => [GAME, RE6].includes(origin?.game_id) && row?.game_id === origin.game_id && row.adapter === origin.adapter && pc(origin)
      && pc(row) === pc(origin) && build(row) === build(origin);
    if (!origin || !matches(origin) || typeof resolve !== "function") return null;
    let current = origin; const seen = new Set();
    while (current?.replaced_by) {
      if (seen.has(current.session_id)) return null;
      seen.add(current.session_id);
      const next = byId.get(current.replaced_by);
      if (!next) break;
      if (!matches(next)) return null;
      current = next;
    }
    const next = resolve(sid, rows, origin);
    return panelEligible(next) && matches(next) ? next : null;
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
    return definition.multiplier ? (typeof raw === "number" && Number.isFinite(raw) ? raw !== 1 : null)
      : typeof raw === "boolean" ? raw : null;
  }
  function amount(status, definition) {
    const raw = readAmount(status, definition);
    return typeof raw === "number" && Number.isFinite(raw) ? raw : definition.op === "kill_time" ? 10 : definition.multiplier;
  }
  function readAmount(status, definition) {
    if (definition.op !== "kill_time") return status?.[definition.field];
    const raw = status?.kill_time_range;
    return (typeof raw === "number" || typeof raw === "string" && /^\d+(?:\.\d+)?$/.test(raw)) ? Number(raw) : null;
  }
  function rows(state) {
    return DEFINITIONS.map(def => {
      const on = value(state.status, def), cap = capability(state.status, def.op);
      return { ...def, on, ...cap, disabled: state.busy || state.pending || state.weaponPending || state.stale || !cap.available || on === null };
    });
  }
  function html(state = {}) {
    const team = state.team, config = team?.config || {}, teamDisabled = state.busy || state.pending || state.stale || !team;
    const p2 = team?.capabilities?.teammate_p2;
    const teamControls = `<fieldset class="re5-team-controls" ${teamDisabled ? "disabled" : ""}><legend>Team and training</legend>`
      + `<label>Requested bot role<select data-re5-team-role aria-label="Bot player assignment">`
      + `<option value="solo_p1" ${config.role === "solo_p1" ? "selected" : ""}>Autobot Player 1 (solo)</option>`
      + `<option value="teammate_p2" ${config.role === "teammate_p2" ? "selected" : ""}>Player 2: follow and protect human Player 1</option>`
      + `<option value="observe_human" ${config.role === "observe_human" ? "selected" : ""}>Observe human Player 1; no bot input</option></select></label>`
      + `<p class="re5-mod-sub">${ESC(p2?.available ? "Player 2 actor and separate controller verified." : p2?.reason || state.teamError || "Team controls require an updated worker.")}</p>`
      + `<button type="button" class="act" data-re5-team-prepare ${!team?.capabilities?.prepare_player2?.available ? "disabled" : ""}>Prepare Player 2 controller for next launch</button>`
      + `<p class="re5-mod-sub">${ESC(team?.player2_preparation?.reason || "Controller preparation never restarts this game or changes Player 1 controls.")}</p>`
      + `<label>Training profile<select data-re5-team-profile aria-label="Training profile">`
      + `<option value="assisted" ${config.training_profile === "assisted" ? "selected" : ""}>Assisted training: keep current modifiers</option>`
      + `<option value="unmodified_evaluation" ${config.training_profile === "unmodified_evaluation" ? "selected" : ""}>Unmodified evaluation: wait for verification</option></select></label>`
      + `<label><input type="checkbox" data-re5-team-reduce ${config.auto_reduce_mods ? "checked" : ""}> Allow gradual modifier reduction after verified improvement</label>`
      + `<p class="re5-mod-sub">Saving roles preserves current modifiers. Evaluation pauses until original settings are verified. Player 2 never falls back to Player 1.</p>`
      + `<p class="re5-mod-sub">${ESC(config.selected_route_id ? "Selected reviewer demonstration: " + config.selected_route_id : "Select an adopted human route in the run reviewer to teach a route.")}</p>`
      + (config.selected_route_id ? `<button type="button" class="act" data-re5-team-clear-route>Clear selected demonstration</button>` : "")
      + `<p class="re5-mod-sub" data-re5-team-phase>${ESC(team ? "Runtime: " + team.phase + "; controls " + (team.control_player ? "Player " + team.control_player : "paused") : "Runtime state unavailable")}</p>`
      + (team?.evaluation_pending ? `<p class="re5-mod-sub">${ESC(team.capabilities?.unmodified_evaluation?.reason || "Waiting for verified original settings. Selecting this profile does not revert current modifiers.")}</p>` : "")
      + `<button type="button" class="act" data-re5-team-save>Save team and training choices</button></fieldset>`;
    if (state.teamOnly) return `<div class="re5-mod-heading"><b>RE6 team and training</b><button type="button" class="act" data-re5-refresh ${state.busy ? "disabled" : ""}>Refresh</button></div>`
      + teamControls + `<p class="re5-mod-status${state.error ? " re5-mod-error" : ""}" role="status">${ESC(state.message || "Read current team settings.")}</p>`;
    const controls = rows(state).map(row => {
      const raw = state.status?.[row.field];
      const detail = (!row.available && row.reason) || (row.on === null ? "State unavailable" : row.multiplier && row.on ? `Current setting: ${row.unit ? raw + row.unit : "×" + raw}`
        : row.note && row.on ? row.note(state.status) : "");
      const setting = amount(state.status, row), unit = row.op === "kill_time" ? "seconds" : "times";
      const slider = row.min === undefined ? "" : `<div class="re5-mod-slider"><label>${ESC(row.label)}: `
        + `<output data-re5-value="${row.op}">${setting} ${unit}</output>`
        + `<input type="range" data-re5-range="${row.op}" aria-label="${ESC(row.label)} value" min="${row.min}" max="${row.max}" step="${row.step}" value="${setting}" ${row.disabled ? "disabled" : ""}></label></div>`;
      return `<label class="re5-mod-row"><span>${ESC(row.label)}${detail ? `<small>${ESC(detail)}</small>` : ""}</span>`
        + `<input type="checkbox" data-re5-mod="${row.op}" aria-label="${ESC(row.label)}" `
        + `aria-checked="${row.on === null ? "mixed" : row.on}" ${row.on ? "checked " : ""}${row.disabled ? "disabled" : ""}></label>` + slider;
    }).join("");
    // These hooks have no verified UI action yet, even if a newer worker advertises a future capability.
    const unavailable = UNAVAILABLE.map(row => `<div class="re5-mod-row re5-mod-unavailable"><span>${row.label}`
      + `<small>${ESC(capability(state.status, row.op).reason || "Unavailable: no verified live control")}</small></span>`
      + `<span>Unavailable</span></div>`).join("");
    const random = capability(state.status, "random_weapon"), weapon = state.status?.in_hand?.weapon;
    const mine = state.status?.mine_settings, mineCap = capability(state.status, "mines");
    const eggOn = state.status?.rotten_egg_only === true;
    const eggCap = capability(state.status, "rotten_egg_only");
    const eggDisabled = state.busy || state.pending || state.stale || !eggCap.available;
    const eggRate = Number.isFinite(state.status?.egg_rate_x) ? state.status.egg_rate_x : 20;
    const eggControls = `<fieldset class="re5-mine-controls" ${eggDisabled ? "disabled" : ""}><legend>Rotten eggs</legend>`
      + `<label><input type="checkbox" data-re5-eggs-on ${eggOn ? "checked" : ""}> Rotten eggs only</label>`
      + `<label>Requested animation speed: <output data-re5-egg-output>${eggRate} times</output>`
      + `<input style="width:100%" type="range" min="1" max="20" step="1" value="${eggRate}" data-re5-egg-rate aria-label="Rotten egg throw speed"></label>`
      + `<small>Infinite egg stock. Mines pause; time bonuses remain a priority. Turning this off restores an existing gun.</small>`
      + `<p class="re5-mod-sub">Experimental: actual throw cadence and ballistic aim are not yet verified.</p>`
      + `<p class="re5-mod-sub">${ESC(state.status?.egg_status || "Waiting for current egg status.")}</p></fieldset>`;
    const mineDisabled = state.busy || state.pending || state.stale || !mineCap.available || !mine || eggOn;
    const mineControls = `<fieldset class="re5-mine-controls" ${mineDisabled ? "disabled" : ""}><legend>Proximity mines</legend>`
      + `<label><input type="checkbox" data-re5-mines-enabled ${mine?.enabled ? "checked" : ""}> Unlimited mine supply</label>`
      + `<label>Placement interval: <output data-re5-mine-output>${mine?.interval_s ?? 60} seconds</output>`
      + `<input style="width:100%" type="range" min="2" max="300" step="1" value="${mine?.interval_s ?? 60}" data-re5-mine-interval aria-label="Mine placement interval in seconds"></label>`
      + `<label><input type="checkbox" data-re5-mines-only ${mine?.only ? "checked" : ""}> Mines only</label>`
      + `<small>Places mines while travelling and after entrances when there is room. Supply begins next round.</small></fieldset>`;
    const catalog = state.status?.mercs_catalog, next = state.status?.mercs_rotation?.next;
    const modes = catalog?.rosters || {}, stages = catalog?.stages || [];
    const mode = next?.mode || "reunion";
    const rotationControls = catalog ? `<fieldset ${state.busy || state.stale ? "disabled" : ""}><legend>Next Mercenaries round</legend>`
      + `<p class="re5-mod-sub">Random rotation covers both modes, every costume and all eight stages. `
      + `${state.status?.mercs_rotation?.combinations_played || 0}/${state.status?.mercs_rotation?.combinations_total || 144} combinations played.</p>`
      + `<select data-re5-merc-mode aria-label="Mercenaries mode">${Object.keys(modes).map(m => `<option value="${ESC(m)}" ${mode === m ? "selected" : ""}>${m === "reunion" ? "Mercenaries Reunion" : "The Mercenaries"}</option>`).join("")}</select>`
      + `<select data-re5-merc-character aria-label="Character and costume">${(modes[mode] || []).map(c => `<option ${c === next?.character ? "selected" : ""}>${ESC(c)}</option>`).join("")}</select>`
      + `<select data-re5-merc-stage aria-label="Mercenaries stage">${stages.map((s,i) => `<option value="${i}" ${i === next?.stage ? "selected" : ""}>${ESC(s)}</option>`).join("")}</select>`
      + `<button class="act" type="button" data-re5-merc-select>Play this selection next</button></fieldset>` : "";
    return `<div class="re5-mod-heading"><b>RE5 modifiers</b><button type="button" class="act" data-re5-refresh `
      + `${state.busy ? "disabled" : ""}>Refresh</button></div><p class="re5-mod-sub">This running session${weapon ? ` · ${ESC(weapon)}` : ""}</p>`
      + teamControls + controls + rotationControls + eggControls + mineControls + `<button class="act re5-mod-random" type="button" data-re5-random `
      + `${state.busy || state.pending || state.weaponPending || state.stale || !random.available ? "disabled" : ""}>Random available weapon</button>`
      + `<p class="re5-mod-sub">${ESC(random.reason || "Equips an eligible gun already in the inventory. Rockets and sniper rifles are excluded.")}</p>`
      + `<details class="re5-mod-extra"><summary>Other requested modifiers</summary>${unavailable}</details>`
      + `<p class="re5-mod-status${state.error ? " re5-mod-error" : ""}" role="${state.error ? "alert" : "status"}" aria-live="polite">`
      + `${ESC(state.message || "Read current settings from the game.")}</p>`;
  }

  function create({ session, api, render = () => {}, delay = ms => new Promise(r => setTimeout(r, ms)), now = Date.now, teamControls = false }) {
    const sid = session?.session_id, worker = String(sid || "").split("-")[0];
    let state = { status: null, busy: false, pending: null, weaponPending: null, stale: true, message: "Reading current settings…", error: false };
    state.team = null; state.teamOnly = session?.game_id === RE6; state.teamError = "";
    let disposed = false;
    const paint = () => { if (!disposed) render({ ...state }); };
    const alive = () => { if (disposed) throw new Error("Modifier panel closed."); };
    async function currentSession() {
      alive();
      if (!panelEligible(session)) throw new Error("Open a running RE5 or RE6 session to change game controls.");
      const sessions = await api("/api/sessions?include_ended=false", undefined, "GET", 15000);
      const current = Array.isArray(sessions) && sessions.find(s => s.session_id === sid);
      if (!panelEligible(current) || current.game_id !== session.game_id || current.adapter !== session.adapter) throw new Error("This RE5/RE6 session has ended or changed. Reopen its controls.");
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
    async function job(op, extra = {}, tool = "re5_mods") {
      alive();
      const submitted = await api("/api/jobs", { tool, agent_use: false, require_worker: worker,
        input: { session_id: sid, op, ...extra } }, "POST", 15000);
      return finish(submitted);
    }
    async function read() {
      const result = state.teamOnly ? { status: {} } : await job("status");
      if (!result.status || typeof result.status !== "object") throw new Error("Current modifier state is unavailable.");
      state.status = result.status;
      state.weaponPending = result.status.random_weapon_request?.state === "pending" ? result.status.random_weapon_request.id : null;
      state.stale = false;
      if (teamControls) {
        try { await readTeam(); }
        catch (error) { state.team = null; state.teamError = error.message; }
      }
      return result.status;
    }
    async function readTeam() {
      const result = await job("status", {}, "mercs_team");
      if (!result.status?.config || typeof result.status.phase !== "string") throw new Error("Team runtime state is unavailable.");
      state.team = result.status; state.teamError = "";
      return result.status;
    }
    async function preflight() {
      await currentSession();
      if (state.pending) {
        await finish(await api("/api/jobs/" + encodeURIComponent(state.pending), undefined, "GET", 15000));
      }
      // A panel reopened while a previous request is running must not send a second mutation.
      const active = await api("/api/jobs?state=queued,running&limit=500", undefined, "GET", 15000);
      const pending = Array.isArray(active) && active.find(j => (j.tool === "re5_mods" || teamControls && j.tool === "mercs_team") && j.input?.session_id === sid);
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
    async function setMines(interval, enabled, only) {
      if (state.busy || state.pending || state.stale || disposed || !capability(state.status, "mines").available) return;
      interval = Number(interval);
      if (!Number.isFinite(interval) || interval < 2 || interval > 300) return;
      state.busy = true; state.error = false; state.message = "Updating mine placement…"; paint();
      try {
        await preflight();
        const result = await job("mines", { on: Boolean(enabled), multiplier: only ? "only" : interval });
        if (result.verified !== true) throw new Error("Mine settings were not verified.");
        await read();
        state.message = only ? "Mines-only round selected. Supply begins next round."
          : enabled ? `Mines every ${interval} seconds. Supply begins next round.` : "Scheduled mines disabled.";
      } catch (error) { state.error = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function setEggs(enabled, requestedRate) {
      const rate = Number(requestedRate);
      if (state.busy || state.pending || state.weaponPending || state.stale || disposed
          || !capability(state.status, "rotten_egg_only").available || !Number.isFinite(rate) || rate < 1 || rate > 20) return;
      state.busy = true; state.error = false; state.message = "Updating rotten eggs…"; paint();
      try {
        await preflight();
        const result = await job("rotten_egg_only", { on: Boolean(enabled), multiplier: rate });
        await read();
        if (result.verified !== true || state.status.rotten_egg_only !== Boolean(enabled)
            || Math.abs(state.status.egg_rate_x - rate) > .011)
          throw new Error(result.reason || "Egg settings were not confirmed.");
        state.message = enabled ? (state.status.egg_native_equipped ? "Rotten egg equipped. Mines paused. Actual throw cadence unverified."
          : "Eggs only requested. Waiting for native pickup or the next fresh loadout, then equip.")
          : "Eggs only disabled. Returning to an existing gun.";
      } catch (error) { state.error = true; state.stale = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function setMultiplier(op, requested) {
      const def = DEFINITIONS.find(row => row.op === op), number = Number(requested);
      if (!def || def.min === undefined || !Number.isFinite(number) || number < def.min || number > def.max
          || state.busy || state.pending || state.weaponPending || state.stale || disposed
          || !capability(state.status, op).available || value(state.status, def) === null) return;
      state.busy = true; state.error = false; state.message = "Applying value…"; paint();
      try {
        await preflight();
        const result = await job(op, { on: true, multiplier: number });
        await read();
        const actual = readAmount(state.status, def);
        if (result.verified !== true || typeof actual !== "number" || !Number.isFinite(actual)
            || Math.abs(actual - number) > 0.011 || op === "kill_time" && state.status.kill_time_on !== true)
          throw new Error(result.reason || "The game did not confirm the requested value.");
        state.message = `${def.label}: ${number} ${op === "kill_time" ? "seconds per kill" : "times"}.`;
      } catch (error) { state.error = true; state.stale = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function selectMercs(mode, character, stage) {
      if (state.busy || state.pending || state.stale || disposed || !capability(state.status,"mercs_select").available) return;
      state.busy = true; state.error = false; state.message = "Selecting the next round…"; paint();
      try {
        await preflight();
        const result = await job("mercs_select", { mode, character, stage: Number(stage) });
        if (result.verified !== true) throw new Error("The next selection was not verified.");
        await read(); state.message = "Next round selected. Random rotation resumes afterward.";
      } catch (error) { state.error = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function setTeam(patch) {
      if (!teamControls || !state.team || state.busy || state.pending || state.stale || disposed || !patch || typeof patch !== "object") return;
      const allowed = ["role", "training_profile", "auto_reduce_mods", "selected_route_id"];
      if (!Object.keys(patch).length || Object.keys(patch).some(k => !allowed.includes(k))
          || "role" in patch && !["solo_p1", "teammate_p2", "observe_human"].includes(patch.role)
          || "training_profile" in patch && !["assisted", "unmodified_evaluation"].includes(patch.training_profile)
          || "auto_reduce_mods" in patch && typeof patch.auto_reduce_mods !== "boolean"
          || "selected_route_id" in patch && patch.selected_route_id !== null && !/^[a-f0-9]{32}$/.test(patch.selected_route_id)) return;
      state.busy = true; state.error = false; state.message = "Saving team and training choices…"; paint();
      try {
        await preflight();
        const result = await job("configure", patch, "mercs_team");
        await readTeam();
        if (result.configuration_verified !== true || Object.entries(patch).some(([key, val]) => state.team.config[key] !== val))
          throw new Error("Team/training choices were not confirmed by fresh readback.");
        state.message = state.team.phase === "active" ? "Team choices saved. Current modifiers are retained."
          : `Choices saved; runtime ${state.team.phase}. Current modifiers are retained; no Player 1 fallback.`;
      } catch (error) { state.error = true; state.stale = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    async function preparePlayer2() {
      if (!teamControls || !state.team?.capabilities?.prepare_player2?.available || state.busy || state.pending || state.stale || disposed) return;
      state.busy = true; state.error = false; state.message = "Preparing a separate Player 2 controller…"; paint();
      try {
        await preflight(); await job("prepare_player2", {}, "mercs_team"); await readTeam();
        if (!state.team.player2_preparation) throw new Error("Controller preparation was not confirmed.");
        state.message = state.team.player2_preparation.reason || "Controller preparation saved for next launch. This game continues unchanged.";
      } catch (error) { state.error = true; state.stale = true; state.message = error.message; }
      finally { state.busy = false; paint(); }
    }
    return { refresh, change, setMultiplier, setMines, setEggs, selectMercs, setTeam, preparePlayer2, state: () => ({ ...state }), stop: () => { disposed = true; } };
  }

  const CSS = `.re5-modifiers{display:block!important;height:auto!important;overflow:visible;border-top:1px solid var(--line,#444);margin-top:5px;padding:9px 4px 2px;min-width:min(300px,calc(100vw - 48px));max-width:400px}
    .re5-mod-heading,.re5-mod-row{display:flex;align-items:center;justify-content:space-between;gap:16px}.re5-mod-heading b{white-space:nowrap}.re5-mod-heading .act{font-size:11px;width:auto!important;flex:none;text-align:center!important}
    .re5-mod-row{padding:7px 0;font-size:13px}.re5-mod-row small{display:block;max-width:280px;font-size:11px;color:var(--mut,#aaa);margin-top:3px}
    .re5-mod-row input{accent-color:var(--pri,#8da7ff);width:17px;height:17px;flex:none;cursor:pointer}.re5-mod-row input:disabled{cursor:default;opacity:.55}
    .re5-mod-sub,.re5-mod-status{font-size:11px;line-height:1.45;margin:5px 0;color:var(--mut,#aaa)}.re5-mod-status{max-width:350px;overflow-wrap:anywhere;min-height:16px}
    .re5-mod-error{color:var(--bad,#f99)}.re5-mod-random{width:100%;margin-top:6px}.re5-mod-extra{margin-top:8px;font-size:11px}
    .re5-mod-extra summary{cursor:pointer}.re5-mod-unavailable{font-size:11px}.re5-mod-unavailable>span:last-child{color:var(--mut,#aaa)}
    .re5-mod-slider{font-size:11px;padding-bottom:5px}.re5-mod-slider label{display:block}.re5-mod-slider input{display:block;width:100%;accent-color:var(--pri,#8da7ff)}
    .re5-mine-controls,.re5-team-controls{font-size:12px}.re5-mine-controls label,.re5-team-controls label{display:block;margin:6px 0}.re5-modifiers select{display:block;width:100%;margin:5px 0}
    .re5-modifiers button:disabled{opacity:.55;cursor:default}`;
  function mount(host, options) {
    if (!host) return null;
    const ctl = create({ ...options, teamControls: true, render: state => { host.innerHTML = html(state); } });
    host.innerHTML = html(ctl.state());
    host.onchange = event => {
      if (event.target.matches?.("[data-re5-eggs-on], [data-re5-egg-rate]")) {
        ctl.setEggs(host.querySelector("[data-re5-eggs-on]").checked, host.querySelector("[data-re5-egg-rate]").value);
        return;
      }
      if (event.target.matches?.("[data-re5-range]")) {
        ctl.setMultiplier(event.target.dataset.re5Range, event.target.value);
        return;
      }
      if (event.target.matches?.("[data-re5-merc-mode]")) {
        const chars = ctl.state().status?.mercs_catalog?.rosters?.[event.target.value] || [];
        host.querySelector("[data-re5-merc-character]").innerHTML = chars.map(c => `<option>${ESC(c)}</option>`).join("");
        return;
      }
      if (event.target.matches?.("[data-re5-mine-interval], [data-re5-mines-enabled], [data-re5-mines-only]")) {
        ctl.setMines(host.querySelector("[data-re5-mine-interval]").value,
          host.querySelector("[data-re5-mines-enabled]").checked, host.querySelector("[data-re5-mines-only]").checked);
        return;
      }
      const input = event.target.closest?.("[data-re5-mod]");
      if (!input || input.disabled) return;
      const wanted = input.checked;
      input.checked = value(ctl.state().status, DEFINITIONS.find(row => row.op === input.dataset.re5Mod)) === true;
      ctl.change(input.dataset.re5Mod, wanted);
    };
    host.oninput = event => {
      if (event.target.matches?.("[data-re5-egg-rate]")) host.querySelector("[data-re5-egg-output]").textContent = event.target.value + " times";
      if (event.target.matches?.("[data-re5-range]")) {
        const op = event.target.dataset.re5Range;
        host.querySelector(`[data-re5-value="${op}"]`).textContent = event.target.value + (op === "kill_time" ? " seconds" : " times");
      }
      if (event.target.matches?.("[data-re5-mine-interval]")) host.querySelector("[data-re5-mine-output]").textContent = event.target.value + " seconds";
    };
    host.onclick = event => {
      if (event.target.closest?.("[data-re5-team-clear-route]") && !event.target.disabled) ctl.setTeam({ selected_route_id: null });
      if (event.target.closest?.("[data-re5-team-prepare]") && !event.target.disabled) ctl.preparePlayer2();
      if (event.target.closest?.("[data-re5-team-save]") && !event.target.disabled) ctl.setTeam({
        role: host.querySelector("[data-re5-team-role]").value,
        training_profile: host.querySelector("[data-re5-team-profile]").value,
        auto_reduce_mods: host.querySelector("[data-re5-team-reduce]").checked });
      if (event.target.closest?.("[data-re5-merc-select]") && !event.target.disabled) ctl.selectMercs(
        host.querySelector("[data-re5-merc-mode]").value, host.querySelector("[data-re5-merc-character]").value,
        host.querySelector("[data-re5-merc-stage]").value);
      if (event.target.closest?.("[data-re5-refresh]") && !event.target.disabled) ctl.refresh();
      if (event.target.closest?.("[data-re5-random]") && !event.target.disabled) ctl.change("random_weapon");
    };
    ctl.refresh();
    return ctl;
  }
  const api = { GAME, RE6, DEFINITIONS, eligible, panelEligible, replacementSession, capability, rows, html, create, mount,
    sectionHTML: () => `<style>${CSS}</style><section class="re5-modifiers" aria-label="RE5 modifiers"></section>` };
  root.GBoxRE5Modifiers = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
