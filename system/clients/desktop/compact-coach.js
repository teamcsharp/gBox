// The compact window uses the same session coaching endpoint and evidence reports as the full Sessions view.
// The PiP's top bar hides 450 ms after the pointer leaves, so what the operator must see keeps it up (operator 2026-11-10:
// a critique typed here never reached the bot's ticket and nothing said so): a note sending, capturing, waiting in the
// outbox to be sent again, or still unsent in the box; a failure for ERROR_PIN_MS, and a toast (notify) for each
// failure, retry and late delivery, since the bar may be hidden when it happens.
(function (root) {
  "use strict";
  const ERROR_PIN_MS = 12000;
  const BUSY = new Set(["sending", "pending", "queued", "draft"]);
  function isCoachTarget(target) { return !!target?.closest?.("[data-compact-coach]"); }
  function create({ coach, api, show, focusApp = () => {}, gateInput = () => {}, notify = () => {}, now = () => Date.now(),
                    schedule = (fn, ms) => root.setTimeout?.(fn, ms) }) {
    let control = null, sid = null, host = null, focused = false, capturing = false, errorUntil = 0, told = "";
    const pinned = () => focused || capturing || now() < errorUntil;
    const activity = () => show(pinned());
    function tell(view) {
      // one toast per new failure or wait (a retry countdown repaints the same words: told once)
      const key = view.state + ":" + String(view.text || "").replace(/\d+ s\b/, "");
      if ((view.state === "error" || view.state === "queued") && key !== told) { told = key; notify(view.text, view); }
      if (view.state === "done" || view.state === "pending") told = "";
    }
    function dispose() {
      control?.dispose(); control = null;
      if (focused) gateInput(false);
      if (host) { host.onfocusin = null; host.onfocusout = null; host.innerHTML = ""; }
      focused = capturing = false; sid = host = null;
    }
    function update(next, target) {
      if (!next.on || !next.sid || !target) { dispose(); return; }
      if (sid === next.sid && host === target) return;  // aspect/hover redraws must keep the draft and capture watcher
      // words still in the box when MercMode moves the PiP on: they stay, for the game they were typed for
      const left = sid && control?.input && String(control.input.value || "").trim() ? { sid, text: control.input.value } : null;
      dispose(); sid = next.sid; host = target;
      host.innerHTML = coach.html(sid);
      control = coach.mount(host, { sid, api, idempotent: true,
        delivered: text => notify(`Critique delivered: "${String(text).slice(0, 80)}"`, { state: "done" }),
        onState: view => {
          capturing = BUSY.has(view.state);
          if (view.state === "error") { errorUntil = now() + ERROR_PIN_MS; schedule(activity, ERROR_PIN_MS + 50); }
          else if (view.state === "done") errorUntil = 0;
          tell(view);
          activity();
        } });
      if (!control) return;
      control.input.placeholder = "Critique the bot…";
      control.input.setAttribute?.("aria-label", "Critique this game's bot; Enter or ➤ files a report with evidence");
      if (left && control.carry?.(left.sid, left.text)) activity();
      host.onfocusin = () => { focused = true; focusApp(); gateInput(true); activity(); };
      host.onfocusout = event => {
        if (host?.contains?.(event.relatedTarget)) return;
        focused = false; gateInput(false); activity();
      };
    }
    // the ⚠ Flawed button's report: the box's own filing (submission ID, outbox, status), or null without a box
    function report(text) { return control?.report ? control.report(text) : null; }
    return { update, dispose, pinned, report, session: () => sid };
  }
  const api = { create, isCoachTarget, ERROR_PIN_MS };
  root.GBoxCompactCoach = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
