// The gBox live "task map" provider registry: pick the right live-map renderer for a session by its
// title/adapter, so the general map dashboard (clients/desktop/mercs-window) can show EVERY hooked &
// mapped title - PSO (Dolphin) -> the RAM-derived PSO co-op map, Mercenaries/RE titles -> the tactical
// map, and (future) any other hooked title -> its own renderer or a generic top-down position view.
//
// A provider is a thin, title-matched adapter over an existing map module:
//   { id, label, match(session)->bool, note(sid)->string,
//     available()->bool, html(sid)->string, mount(doc,{sid,api})->ctl({stop()}), detach() }
// Registration order is "most specific first" (later registrations are tried first); the first
// provider whose match() is true wins, else the fallback (the tactical map, preserving today's
// behaviour). New hooked titles plug in with GBoxLiveMaps.register({...}) - no viewer changes.
//
// classify(session) returns just the winning provider id, which the single-pane desktop viewer uses
// to choose between its INJECTED renderers (so it stays unit-testable without the globals); pick()
// returns the whole provider, which the concurrent multi-pane layout uses to mount directly.
(function (root) {
  "use strict";
  const providers = [];
  function register(p) {
    if (p && typeof p.match === "function" && typeof p.id === "string") providers.unshift(p);
    return p;
  }
  function pick(session) {
    const s = session || {};
    for (const p of providers) { try { if (p.match(s)) return p; } catch (e) { /* skip a bad matcher */ } }
    return fallback;
  }
  function classify(session) { const p = pick(session); return p && p.id; }
  function list() { return providers.slice(); }

  const titleOf = s => String((s && (s.title || s.game_id)) || "");
  const gameOf = s => String((s && s.game_id) || "");
  // PSO: by title (robust across emulators) or the GameCube PSO disc ids (GPO*/GPS*). NOT "any Dolphin".
  const isPso = s => /phantasy star online/i.test(titleOf(s)) || /^GP[OS]/i.test(gameOf(s)) || /\bpso\b/i.test(titleOf(s));

  const pso = {
    id: "pso", label: "PSO map", match: isPso,
    available: () => !!root.GBoxPsoMap,
    note: () => "Live PSO map - both players, motion trails, the MOVING/STUCK banner and the run plan. " +
      "Double-click an open spot to send P1; click a gate to open it; Resume autonomous when idle.",
    html: sid => (root.GBoxPsoMap ? root.GBoxPsoMap.html(sid) : ""),
    mount: (doc, ctx) => (root.GBoxPsoMap ? root.GBoxPsoMap.mount(doc, ctx) : null),
    detach: () => root.GBoxPsoMap && root.GBoxPsoMap.detach && root.GBoxPsoMap.detach(),
  };
  // Mercenaries / Resident Evil titles -> the existing tactical map (only these; other titles fall
  // through to the generic view rather than a blank tactical map).
  const isMercs = s => /resident evil|mercenar/i.test(titleOf(s)) || /\bRE[456]\b/i.test(gameOf(s)) || /^(BL|BC|NP)[A-Z]{2}\d/.test(gameOf(s));
  const mercs = {
    id: "mercs", label: "Tactical map", match: isMercs,
    available: () => !!root.GBoxTacticalMap,
    note: () => "Hover to hold the map; wheel to zoom; drag to pan. Click a bonus or recovery item to request collection.",
    html: sid => (root.GBoxTacticalMap ? root.GBoxTacticalMap.html(sid) : ""),
    mount: (doc, ctx) => (root.GBoxTacticalMap ? root.GBoxTacticalMap.mount(doc, ctx) : null),
    detach: () => root.GBoxTacticalMap && root.GBoxTacticalMap.detach && root.GBoxTacticalMap.detach(),
  };
  // Generic top-down view for any OTHER hooked/mapped title (positions + motion from telemetry) -
  // the universal fallback, so a new title shows something immediately instead of a blank pane.
  const generic = {
    id: "generic", label: "Live map", match: () => true,
    available: () => !!root.GBoxGenericMap,
    note: () => "Generic top-down view (positions + motion) — no bespoke map for this title yet.",
    html: sid => (root.GBoxGenericMap ? root.GBoxGenericMap.html(sid) : ""),
    mount: (doc, ctx) => (root.GBoxGenericMap ? root.GBoxGenericMap.mount(doc, ctx) : null),
    detach: () => root.GBoxGenericMap && root.GBoxGenericMap.detach && root.GBoxGenericMap.detach(),
  };
  const fallback = generic;           // every unmatched title gets the generic view
  register(generic);                  // registered too, so it also wins as the last matcher
  register(mercs);                    // RE / Mercenaries -> tactical map
  register(pso);                      // PSO (Dolphin) -> the PSO co-op map (checked first: most specific)

  const api = { register, pick, classify, list, isPso, isMercs, builtins: { pso, mercs, generic }, fallback };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxLiveMaps = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
