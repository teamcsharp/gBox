// The blueprint look switch of the live-mods panels (operator 2026-11-09: "all the levels and assets rendered in this
// UE-blueprint look with a toggle to turn it off and on in the mod panel"). It is a MercMode setting of the PC that
// plays the shown session (gbox/mercmode.py DEFAULT.blueprint_look), read from GET /api/mercmode and set through
// POST /api/mercmode {host, blueprint_look} - the route every other MercMode setting uses (mercmode.js). The scheduler
// plays each queue entry's `<build>-blueprint` companion (switch_mods op=blueprint) while it is on, from the next
// round boundary; nothing changes in the round being played. No framework; node tests drive html() / read() without a
// DOM (tests/test_blueprint_look.cjs); re5-modifiers.js and bot-logic-sidebar.js use it when it is loaded.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const LABEL = "Blueprint look (grid textures on the level)";
  const NOTE = "applies at the next round";
  const ROUTE = "/api/mercmode";
  // the /api/mercmode host row that plays the shown session: its current run's session id first, then the PC's
  // worker id (the session id's prefix), then the PC's name
  function hostFor(data, ids = {}) {
    const hosts = Array.isArray(data?.hosts) ? data.hosts : [];
    const sid = typeof ids.sid === "string" ? ids.sid : "";
    const worker = String(ids.worker || sid.split("-")[0] || "");
    const pc = String(ids.pc || "").toLowerCase();
    return hosts.find(h => sid && h?.current_run?.session_id === sid)
      || hosts.find(h => worker && h?.id === worker)
      || hosts.find(h => pc && String(h?.name || "").toLowerCase() === pc) || null;
  }
  // {host, on, reason}: on is true / false from the PC's settings, null when no PC owns the session
  function read(data, ids = {}) {
    const host = hostFor(data, ids);
    if (!host) return { host: null, on: null, reason: "No gBox PC owns this game; the blueprint look is set per PC." };
    const settings = host.settings && typeof host.settings === "object" ? host.settings : host.desired_settings || {};
    const on = typeof settings.blueprint_look === "boolean" ? settings.blueprint_look
      : typeof host.desired_settings?.blueprint_look === "boolean" ? host.desired_settings.blueprint_look : null;
    return { host: host.name, on, reason: on === null ? `${host.name} runs an older gBox without the blueprint look.` : "" };
  }
  async function fetch(api, ids = {}) {
    return read(await api(ROUTE, undefined, "GET"), ids);
  }
  // sets the PC's setting and reads it back from the route's fresh status
  async function set(api, host, on) {
    if (typeof host !== "string" || !host || typeof on !== "boolean") throw new Error("The blueprint look needs the PC and on or off.");
    const data = await api(ROUTE, { host, blueprint_look: on }, "POST");
    const after = read(data, { pc: host });
    if (after.on !== on) throw new Error(`${host} did not confirm the blueprint look ${on ? "on" : "off"}. Refresh current settings.`);
    return after;
  }
  const message = on => `Blueprint look ${on ? "on" : "off"}: ${on ? "the level and its objects switch to grid textures" : "the level goes back to its own textures"} at the next round.`;
  // state: {on, host, reason, disabled, attr (extra attributes for the input, e.g. the panel's scope), cls}
  function html(state = {}) {
    const on = state.on === true, known = typeof state.on === "boolean" && !!state.host;
    const detail = known ? `${NOTE} · MercMode on ${state.host}` : state.reason || NOTE;
    return `<label class="${ESC(state.cls || "blueprint-look")}" title="${ESC(LABEL)}: ${ESC(NOTE)}"><span>${LABEL}<small>${ESC(detail)}</small></span>`
      + `<input type="checkbox" data-blueprint-look${state.attr ? " " + state.attr : ""} aria-label="${LABEL}" aria-checked="${known ? on : "mixed"}"`
      + `${on ? " checked" : ""}${state.disabled || !known ? " disabled" : ""}></label>`;
  }
  const api = { LABEL, NOTE, ROUTE, hostFor, read, fetch, set, message, html };
  root.GBoxBlueprintLook = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
