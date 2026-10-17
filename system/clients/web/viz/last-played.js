// "Reload the game you had up" pop-up (GET /api/last_played, gbox/last_played.py). When the operator's game ends -
// emulator window closed, Stop, a crash, a failed relaunch, the worker or the app restarting - the web shell (which the
// desktop app embeds) offers: Reload <title> (<mod>) on the same PC, Reload with your last moment (when gBox saved
// one: its picture and age), or Dismiss; "Don't ask again for this game" mutes that game. Shown again on the next
// start until something is launched or it is dismissed. It never stops a running game: the server answers no entry
// while one runs, and the reload job refuses a PC that is busy with another game.
// Plain functions + a controller over one host element, so node tests drive it (tests/test_last_played.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const POLL = 5000;

  function ago(ts, now = Date.now() / 1000) {
    if (!ts) return "";
    const s = Math.max(0, now - ts);
    return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
  }
  const label = e => `${e.title}${e.mod ? ` (${e.mod})` : ""}`;

  function html(e, { url = u => u, now, busy = "", error = "" } = {}) {
    if (!e) return "";
    // A rolling deployment can still serve the legacy backend's generic-code-1
    // "crash" reason. That value alone never establishes an unexpected exit.
    const reason = e.reason || {};
    const r = reason.kind === 'crash' && /^The emulator quit unexpectedly \(exit code 1\)\.$/.test(reason.text || '')
      ? {kind:'ended',crash:false,text:'The emulator closed.'} : reason;
    const m = e.moment;
    const bad = r.crash ? " lp-bad" : "";
    return `<div class="lp-back" data-lp-sid="${ESC(e.session_id)}"><div class="lp-box${bad}" role="dialog" aria-modal="true" aria-labelledby="lp-h">
      <div class="lp-h" id="lp-h">${r.crash ? "⚠ " : ""}${ESC(e.title)} ended</div>
      <div class="lp-why${bad}">${ESC(r.text || "The game ended.")}${e.report?.id ? ` <a href="#" data-lp="report" data-id="${ESC(e.report.id)}">${r.crash ? "Report" : "Related report"} #${ESC(e.report.number ?? "")}${e.report.status ? " · " + ESC(String(e.report.status).replace("_", " ")) : ""}</a>` : ""}</div>
      <div class="lp-sub mut">${e.mod ? `Build ${ESC(e.mod)} · ` : "Original game · "}on ${ESC(e.node)}${e.node_online ? "" : " (offline right now)"}${e.ended ? " · ended " + ESC(ago(e.ended, now)) : ""}</div>
      ${m ? `<div class="lp-moment">${m.frame_url ? `<img alt="Your last moment" src="${ESC(url(m.frame_url))}">` : `<div class="lp-noimg">no picture of the moment</div>`}
        <div><b>Your last moment</b><div class="mut">saved ${ESC(ago(m.ts, now) || "before the end")}</div></div></div>` : ""}
      <div class="lp-btns">
        <button class="act pri" type="button" data-lp="reload"${busy || !e.node_online ? " disabled" : ""}>Reload ${ESC(label(e))}</button>
        ${m ? `<button class="act pri" type="button" data-lp="moment"${busy || !e.node_online ? " disabled" : ""}>Reload with your last moment (${ESC(ago(m.ts, now) || "saved")})</button>` : ""}
        <button class="act" type="button" data-lp="dismiss"${busy ? " disabled" : ""}>Dismiss</button></div>
      <label class="lp-mute mut"><input type="checkbox" data-lp="mute"> Don't ask again for this game</label>
      ${busy ? `<div class="lp-busy">${ESC(busy)}</div>` : ""}${error ? `<div class="lp-err" role="alert">⚠ ${ESC(error)}</div>` : ""}</div></div>`;
  }

  const CSS = `.lp-back{position:fixed;inset:0;background:#0008;z-index:9998;display:flex;align-items:center;justify-content:center;padding:16px}
    .lp-box{background:var(--card,#1f1f25);color:var(--fg,#e8e8ee);border:1px solid var(--line,#2c2c34);border-radius:10px;padding:16px 18px;width:min(520px,100%);box-shadow:0 10px 40px #000a;font-size:14px;
      max-height:100%;overflow:auto;overscroll-behavior:contain;overflow-wrap:anywhere;box-sizing:border-box}
    .lp-box.lp-bad{border-color:var(--bad,#ff6b6b)}.lp-h{font-size:17px;font-weight:600;margin-bottom:4px}.lp-why{margin:4px 0}.lp-why.lp-bad{color:var(--bad,#ff6b6b)}
    .lp-why a{color:var(--acc,#7c96ff)}.lp-sub{font-size:12px;margin-bottom:10px}.lp-moment{display:flex;gap:10px;align-items:center;margin:8px 0 12px}
    .lp-moment img,.lp-noimg{width:160px;height:120px;object-fit:cover;border-radius:6px;background:#000}.lp-noimg{display:flex;align-items:center;justify-content:center;font-size:11px;color:#888}
    .lp-btns{display:flex;flex-direction:column;gap:6px}.lp-btns .act{text-align:left}.lp-mute{display:flex;gap:6px;align-items:center;font-size:12px;margin-top:10px}
    .lp-busy{margin-top:8px;color:var(--acc,#7c96ff)}.lp-err{margin-top:8px;color:var(--bad,#ff6b6b);font-weight:600}`;

  // env = { api(path, body?) -> data (throws), host (element the pop-up goes in), url?(path), wait?(ms), now?(),
  //         onReloaded?(sid), openReport?(id), visible?(), top?() -> the shell's header bottom in px (the box stays below it,
  //         inside the window, and scrolls inside itself when taller than the room left; laid out again on resize) }
  function mount(env) {
    const st = { entry: null, busy: "", error: "", shownFor: null, closed: new Set(), timer: null };
    const wait = env.wait || (ms => new Promise(r => setTimeout(r, ms)));
    const box = () => env.host.querySelector?.(".lp-back");
    function draw() {
      const old = box(); if (old) old.remove?.();
      if (!st.entry || st.closed.has(st.entry.session_id)) return;
      if (!env.host.querySelector?.("#lp-css")) env.host.insertAdjacentHTML("beforeend", `<style id="lp-css">${CSS}</style>`);
      env.host.insertAdjacentHTML("beforeend", html(st.entry, { url: env.url, now: env.now?.(), busy: st.busy, error: st.error }));
      place();
    }
    function place() {
      const b = box(); if (!b || !b.style) return;
      let top = 0; try { top = Math.max(0, +(env.top?.() || 0) || 0); } catch { top = 0; }
      b.style.paddingTop = (top + 16) + "px";
    }
    const view = env.host.ownerDocument?.defaultView;
    view?.addEventListener?.("resize", place);
    async function check() {
      if (st.busy || (env.visible && !env.visible())) return st.entry;
      let r; try { r = await env.api("/api/last_played"); } catch { return st.entry; }
      const e = r?.entry || null;
      if (JSON.stringify(e) !== JSON.stringify(st.entry)) { st.entry = e; st.error = ""; draw(); }
      return st.entry;
    }
    async function dismiss(mute) {
      const e = st.entry; if (!e) return;
      st.closed.add(e.session_id); draw();
      await env.api("/api/last_played/dismiss", { session_id: e.session_id, never_for_game: !!mute }).catch(() => {});
    }
    async function reload(moment) {
      const e = st.entry; if (!e || st.busy) return;
      st.busy = moment ? "Starting the game and loading your moment…" : "Starting the game…"; st.error = ""; draw();
      try {
        let j = await env.api("/api/last_played/reload", { session_id: e.session_id, moment: !!moment });
        while (j && ["queued", "running"].includes(j.state)) {
          await wait(700); j = await env.api("/api/jobs/" + j.id);
          if (j?.progress?.msg && j.progress.msg !== st.busy) { st.busy = j.progress.msg; draw(); }
        }
        if (!j || j.state !== "succeeded") throw new Error(j?.error || j?.state || "no answer");
        st.busy = ""; st.closed.add(e.session_id); draw();
        const out = j.output || {};
        env.onReloaded?.(out.session_id, out);
        return out;
      } catch (err) { st.busy = ""; st.error = "Reload failed: " + (err?.message || err); draw(); }
    }
    async function onClick(ev) {
      const a = ev.target?.closest?.("[data-lp]")?.dataset?.lp;
      if (!a || !box()) return;
      if (a === "report") { ev.preventDefault?.(); return env.openReport?.(ev.target.closest("[data-lp]").dataset.id); }
      if (a === "mute") return;
      const mute = !!box().querySelector?.('[data-lp="mute"]')?.checked;
      if (a === "dismiss") return dismiss(mute);
      if (a === "reload" || a === "moment") { if (mute) env.api("/api/last_played/dismiss", { session_id: st.entry.session_id, never_for_game: true, keep: true }).catch(() => {}); return reload(a === "moment"); }
    }
    env.host.addEventListener?.("click", onClick);
    const ready = check();
    st.timer = setInterval(check, env.poll || POLL);
    st.timer?.unref?.();                                     // node (tests): never keeps the process alive
    function stop() { clearInterval(st.timer); env.host.removeEventListener?.("click", onClick); view?.removeEventListener?.("resize", place); }
    return { st, check, reload, dismiss, onClick, draw, place, stop, ready };
  }

  const api = { html, mount, ago, CSS, POLL };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxLastPlayed = api;
})(typeof window !== "undefined" ? window : globalThis);
