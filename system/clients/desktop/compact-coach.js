// The compact window uses the same session coaching endpoint and evidence reports as the full Sessions view.
(function (root) {
  "use strict";
  function isCoachTarget(target) { return !!target?.closest?.("[data-compact-coach]"); }
  function create({ coach, api, show, focusApp = () => {}, gateInput = () => {} }) {
    let control = null, sid = null, host = null, focused = false, capturing = false;
    const pinned = () => focused || capturing;
    const activity = () => show(pinned());
    function dispose() {
      control?.dispose(); control = null;
      if (focused) gateInput(false);
      if (host) { host.onfocusin = null; host.onfocusout = null; host.innerHTML = ""; }
      focused = capturing = false; sid = host = null;
    }
    function update(next, target) {
      if (!next.on || !next.sid || !target) { dispose(); return; }
      if (sid === next.sid && host === target) return;  // aspect/hover redraws must keep the draft and capture watcher
      dispose(); sid = next.sid; host = target;
      host.innerHTML = coach.html(sid);
      control = coach.mount(host, { sid, api, idempotent: true,
        onState: view => { capturing = view.state === "sending" || view.state === "pending"; activity(); } });
      if (!control) return;
      control.input.placeholder = "Critique the bot…";
      control.input.setAttribute?.("aria-label", "Critique this game's bot; Enter files a report with evidence");
      host.onfocusin = () => { focused = true; focusApp(); gateInput(true); activity(); };
      host.onfocusout = event => {
        if (host?.contains?.(event.relatedTarget)) return;
        focused = false; gateInput(false); activity();
      };
    }
    return { update, dispose, pinned, session: () => sid };
  }
  const api = { create, isCoachTarget };
  root.GBoxCompactCoach = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
