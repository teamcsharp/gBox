// RE4 (GameCube, Dolphin) enemy-spawn slider: 1x..4x on the existing re_mods spawn_multiplier op.
// 1x reverts (on=false); 2x-4x send count=N, on=true. The backend op itself keeps its 2..8 bounds.
(function (root) {
  "use strict";
  const MIN = 1, MAX = 4;
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  function clamp(v) {
    const n = Math.round(Number(v));
    return Number.isFinite(n) ? Math.max(MIN, Math.min(MAX, n)) : MIN;
  }
  function input(value) {
    const n = clamp(value);
    return n <= 1 ? { op: "spawn_multiplier", on: false } : { op: "spawn_multiplier", count: n, on: true };
  }
  function eligible(session) {
    const title = String(session?.title || session?.name || "");
    return !!session && session.state === "running" && !session.stopping && session.adapter === "dolphin"
      && typeof session.session_id === "string" && session.session_id.includes("-")
      && /resident evil 4/i.test(title) && !/2023|remake|ps2|wii|ps4|ps5/i.test(title);
  }
  function html(state = {}) {
    const v = clamp(state.value ?? 1);
    return `<div class="re4-spawn-row"><label for="re4-spawn">Enemy spawn multiplier <b data-re4-spawn-val>×${v}</b></label>`
      + `<input id="re4-spawn" type="range" min="${MIN}" max="${MAX}" step="1" value="${v}" data-re4-spawn ${state.busy ? "disabled" : ""}>`
      + `<p class="re4-spawn-msg${state.error ? " re4-spawn-error" : ""}" role="status" aria-live="polite">${ESC(state.message || "1× = normal; 2×–4× clones each spawned enemy.")}</p></div>`;
  }
  function create({ session, api, render = () => {} }) {
    const sid = session?.session_id, worker = String(sid || "").split("-")[0];
    const state = { value: 1, busy: false, error: false, message: "" };
    let disposed = false;
    const paint = () => { if (!disposed) render({ ...state }); };
    async function set(raw) {
      if (state.busy || disposed) return;
      if (!eligible(session)) { state.error = true; state.message = "Open a running RE4 GameCube session."; paint(); return; }
      const value = clamp(raw);
      state.busy = true; state.error = false; state.message = "Applying…"; paint();
      try {
        let job = await api("/api/jobs", { tool: "re_mods", agent_use: false, require_worker: worker,
          input: { session_id: sid, ...input(value) } }, "POST", 15000);
        for (let i = 0; i < 100 && ["queued", "running"].includes(job?.state) && job.id; i++)
          job = await api("/api/jobs/" + encodeURIComponent(job.id), undefined, "GET", 15000);
        if (job?.state !== "succeeded") throw new Error(job?.error?.message || job?.error || "Spawn job did not succeed.");
        state.value = value; state.message = value === 1 ? "Normal spawns restored." : `Spawn multiplier ×${value} applied.`;
      } catch (e) { state.error = true; state.message = e.message; }
      finally { state.busy = false; paint(); }
    }
    return { set, state: () => ({ ...state }), stop: () => { disposed = true; } };
  }
  function mount(host, options) {
    if (!host) return null;
    const ctl = create({ ...options, render: s => { host.innerHTML = html(s); } });
    host.innerHTML = html(ctl.state());
    host.onchange = e => { const el = e.target.closest?.("[data-re4-spawn]"); if (el && !el.disabled) ctl.set(el.value); };
    return ctl;
  }
  const api = { MIN, MAX, clamp, input, eligible, html, create, mount,
    sectionHTML: () => `<section class="re4-spawn" aria-label="RE4 spawn multiplier" style="border-top:1px solid var(--line,#444);margin-top:5px;padding:9px 4px 2px;font-size:13px"></section>` };
  root.GBoxRE4Spawn = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
