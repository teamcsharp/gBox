// The Mercenaries clock control shared by the RE5 (re5-modifiers.js, tool re5_mods) and RE4 (re4-modifiers.js, tool
// re_mods) panels, which the PiP right-click menu and the Sessions view mount. Operator 2026-10-26: "the ability to set
// the time left in the mercenaries timer to a custom time like 5 seconds with a slider to set or add as many as 30
// seconds to the clock or subtract. I want it negative set to subtract time down to 5 seconds by default."
// A slider -30..+30 s (default -30: subtract) with Apply -> op add_time seconds=N; "Set clock to N s" (1..60, default 5)
// -> op set_time seconds=N. The panel owning the host sends the job and confirms from the verified result's
// clock_before / clock_after; this module only renders, reads the inputs and words the result.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const DELTA = { min: -30, max: 30, step: 1, default: -30 };     // seconds added by Apply (negative takes time away)
  const SET = { min: 1, max: 60, default: 5 };                    // "Set clock to N s"
  function delta(value) {                                          // the slider's whole seconds, never 0, else null
    const n = Number(value);
    return Number.isInteger(n) && n !== 0 && n >= DELTA.min && n <= DELTA.max ? n : null;
  }
  function setSeconds(value) {                                     // the clock's new value, else null
    const n = Number(value);
    return Number.isInteger(n) && n >= SET.min && n <= SET.max ? n : null;
  }
  const sign = n => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n);
  const deltaLabel = n => `${sign(Number(n) || 0)} s`;
  const setLabel = n => `Set clock to ${setSeconds(n) ?? SET.default} s`;
  function left(status) {                                          // the seconds left as the game reports them, else null
    const n = status?.merc_seconds_left;
    return typeof n === "number" && Number.isFinite(n) ? Math.round(n) : null;
  }
  // state: { disabled, delta, set, status, reason } - delta / set are the panel's kept drafts (a repaint never loses them)
  function html(state = {}) {
    const off = state.disabled ? "disabled" : "";
    const d = delta(state.delta) ?? DELTA.default, s = setSeconds(state.set) ?? SET.default, secs = left(state.status);
    const line = secs === null ? "Clock not read: no Mercenaries round is up." : `${secs} s left on the clock.`;
    return `<fieldset class="mercs-clock" ${off}><legend>Mercenaries clock</legend>`
      + `<p class="re5-mod-sub" data-clock-left>${ESC(line)}${state.reason ? ` ${ESC(state.reason)}` : ""}</p>`
      + `<label>Add or take time: <output data-clock-delta-out>${ESC(deltaLabel(d))}</output>`
      + `<input type="range" data-clock-delta aria-label="Seconds added to the clock (negative takes time away)" `
      + `min="${DELTA.min}" max="${DELTA.max}" step="${DELTA.step}" value="${d}" ${off}></label>`
      + `<div class="mercs-clock-row"><button type="button" class="act" data-clock-apply ${off}>Apply</button>`
      + `<label>Set to <input type="number" data-clock-set aria-label="Seconds on the clock" min="${SET.min}" max="${SET.max}" step="1" value="${s}" ${off}> s</label>`
      + `<button type="button" class="act" data-clock-set-apply ${off}>${ESC(setLabel(s))}</button></div>`
      + `<small>Apply adds the slider's seconds to the round clock; negative takes them away (the clock never goes under 1 s). `
      + `Set clock ends a stalemate: 5 s by default. The bot cuts a stalemate's clock itself after 15 s without enemies (MercMode settings).</small></fieldset>`;
  }
  function describe(result, fallback = "Clock changed.") {         // the verified result's clock_before / clock_after
    const b = result?.clock_before, a = result?.clock_after;
    if (typeof b === "number" && typeof a === "number" && Number.isFinite(a) && Number.isFinite(b))
      return `Clock ${Math.round(b)} → ${Math.round(a)} s${result.clamped ? " (stopped at 1 s)" : ""}.`;
    return fallback;
  }
  // input events: previews only (labels), never a job; returns the draft the panel should keep, or null
  function onInput(target, host) {
    if (target?.matches?.("[data-clock-delta]")) {
      const out = host.querySelector?.("[data-clock-delta-out]");
      if (out) out.textContent = deltaLabel(target.value);
      return { delta: Number(target.value) };
    }
    if (target?.matches?.("[data-clock-set]")) {
      const button = host.querySelector?.("[data-clock-set-apply]");
      if (button) button.textContent = setLabel(target.value);
      return { set: Number(target.value) };
    }
    return null;
  }
  // click events: Apply -> addTime(slider seconds); Set clock -> setTime(number); true when the click was the clock's
  function onClick(target, host, { addTime, setTime }) {
    const apply = target?.closest?.("[data-clock-apply]");
    if (apply) { if (!apply.disabled) addTime(host.querySelector?.("[data-clock-delta]")?.value); return true; }
    const set = target?.closest?.("[data-clock-set-apply]");
    if (set) { if (!set.disabled) setTime(host.querySelector?.("[data-clock-set]")?.value); return true; }
    return false;
  }
  const CSS = `.mercs-clock{font-size:12px;margin-top:6px}.mercs-clock label{display:block;margin:6px 0}
    .mercs-clock input[type=range]{display:block;width:100%;accent-color:var(--pri,#8da7ff)}
    .mercs-clock-row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.mercs-clock-row label{display:inline-flex;align-items:center;gap:4px;margin:0}
    .mercs-clock-row input[type=number]{width:4em;background:#111;color:#eee;border:1px solid var(--line,#444);border-radius:4px}
    .mercs-clock .act{width:auto!important;font-size:11px;text-align:center!important}.mercs-clock small{display:block;color:var(--mut,#aaa);font-size:11px;margin-top:4px}
    .mercs-clock:disabled{opacity:.6}`;
  const api = { DELTA, SET, delta, setSeconds, deltaLabel, setLabel, left, html, describe, onInput, onClick, CSS };
  root.GBoxMercsClock = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
