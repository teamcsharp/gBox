/* Which game sessions can be watched (#2858; operator 2026-10-20: "make sure that gBox isn't listing sessions for me to
   connect to that don't actually exist ... it didn't bring anything up"). A running session is live when the PC that
   runs it is online under the worker id that started it (a worker that restarted under a new id ended its games) and a
   picture of it came recently (GET /api/sessions last_frame_age): the Spark stream's frames, or the stills a Windows
   worker posts of a native game while its screen shows it (workers with session_stills). A native game on a worker
   without stills is watched through that PC's screen (desktop_stream) and the Sessions view checks the picture there.
   judge() is pure; the header icons, the Sessions list and the session view all ask it. A session that is not live is
   never an empty view: html() says why where the picture goes, with Retry / Stop / Relaunch in a bar under it, and
   mount() shows the game the moment a picture comes (onLive). */
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const STALE_S = 15;            // no picture for longer: the game is not on its screen, or its stream stopped
  const GRACE_S = 30;            // a game this new may still be booting: no picture yet is not news
  const dur = s => s < 120 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`;

  // { live, kind, pc, text (the short marker), why (what the view says), age }. kind: live | starting | screen (a native
  // game watched through its PC's screen) | unknown (the PCs are not loaded: say nothing) | stale | offline | gone |
  // noscreen | ended.
  function judge(s, workers, now = Date.now() / 1000) {
    const wid = String(s?.session_id || "").split("-")[0];
    const w = Array.isArray(workers) ? workers.find(x => x.id === wid) : null;
    const pc = s?.detail?.worker_name || w?.name || "the other PC";
    const out = (live, kind, text = "", why = "", age = null) => ({ live, kind, pc, text, why, age });
    if (!s || s.state !== "running") return out(false, "ended", "ended", "This session has ended.");
    const offline = () => out(false, "offline", `${pc} is offline`,
      `${pc}'s gBox worker stopped answering, so there is no picture of this game. It shows here again as soon as ${pc} is back.`);
    if (s.worker_online === false) return offline();           // the server flagged its PC offline (#2870), whatever the PC list says
    if (!Array.isArray(workers) || !workers.length) return out(true, "unknown");
    if (!w) return out(false, "gone", `${pc} is no longer connected`,
      `The gBox worker that started this game on ${pc} is gone (it restarted or was removed), so there is nothing to show. Relaunch the game to play it again.`);
    if (!w.online) return offline();
    const native = !!s.detail?.local_window, features = w.features || [];
    if (native && !features.includes("session_stills"))
      return features.includes("desktop_stream") ? out(true, "screen") : out(false, "noscreen", `${pc} can't share its screen`,
        `This game runs in its own window on ${pc}, and that PC's gBox worker can't share its screen (it needs a gBox update).`);
    const where = native ? `${pc} hasn't shown this game on its screen` : `The game stream from ${pc} hasn't sent a picture`;
    const maybe = native ? ": it may be minimized, covered or closed there, or that screen may be asleep." : ".";
    const age = s.last_frame_age;
    if (age == null) {
      const since = Math.max(0, now - (s.started || now));
      return since < GRACE_S ? out(true, "starting")
        : out(false, "stale", `no picture from ${pc} yet`, `${where} since it started ${dur(since)} ago${maybe}`);
    }
    if (age > STALE_S) return out(false, "stale", `no picture from ${pc} for ${dur(age)}`, `${where} for ${dur(age)}${maybe}`, age);
    return out(true, "live", "", "", age);
  }

  const CSS = `#no-picture { position:relative; overflow:hidden; }
    #no-picture img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; opacity:.28; filter:grayscale(1); }
    #no-picture .np-why { position:absolute; inset:0; display:grid; place-content:center; justify-items:center; gap:6px; padding:24px;
      text-align:center; }
    #no-picture .np-why b { font-size:16px; } #no-picture .np-why p { margin:0; max-width:560px; font-size:13px; }
    #no-picture-bar { flex:none; display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:6px; padding:6px 8px;
      border:1px solid var(--line); border-radius:8px; background:var(--card); }
    #no-picture-meta { flex:1; min-width:160px; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }`;
  // The picture area and its bar for a session that is not live (pure). o: { sid, verdict, title, auth ("token=…"),
  // online (its PC answers: Stop and Relaunch work there) }
  function html(o) {
    const v = o.verdict, last = `/api/sessions/${encodeURIComponent(o.sid)}/frame.jpg?${o.auth || ""}`;
    return `<style id="no-picture-css">${CSS}</style>
      <div id="no-picture" class="screen" data-session="${ESC(o.sid)}" data-kind="${ESC(v.kind)}">
        <img id="no-picture-last" alt="" data-base="${ESC(last)}" src="${ESC(last)}" onerror="this.hidden=true">
        <div class="np-why" role="status"><b id="no-picture-title">${ESC(v.text.charAt(0).toUpperCase() + v.text.slice(1))}</b>
          <p id="no-picture-why">${ESC(v.why)}</p>
          <p class="mut">gBox keeps checking: the game shows here as soon as a picture of it comes.</p></div></div>
      <div id="no-picture-bar" role="toolbar" aria-label="${ESC(`${o.title || "Game"}: no picture`)}">
        <span id="no-picture-meta" class="mut">Checking ${ESC(v.pc)}…</span>
        <button class="act" type="button" data-live-action="retry" title="Check for a picture again now">Retry</button>
        <button class="act" type="button" data-live-action="stop" style="color:var(--bad)" title="${ESC(o.online ? `Stop the game on ${v.pc}` : `Stop the game on ${v.pc} as soon as it is back`)}">Stop</button>
        <button class="act pri" type="button" data-live-action="relaunch" title="${ESC(o.online ? `Start this game again on ${v.pc}: same game and build` : "Start this game again where you play: same game and build")}">Relaunch</button>
      </div>`;
  }

  let current = null;
  // Keeps the not-live view honest: checks every few seconds (Retry: now), says what it found, and calls onLive() once a
  // picture of the game comes (or the session ends) so the shell can show it. o: { sid, api(path), onLive(), stop(button),
  // relaunch(button), setTimer, clearTimer, now }. Returns { stop }.
  function mount(doc, o) {
    current?.stop();
    const box = doc.getElementById("no-picture");
    if (!box) return (current = null);
    const bar = doc.getElementById("no-picture-bar"), meta = doc.getElementById("no-picture-meta");
    const title = doc.getElementById("no-picture-title"), why = doc.getElementById("no-picture-why");
    const last = doc.getElementById("no-picture-last");
    const setTimer = o.setTimer || setTimeout, clearTimer = o.clearTimer || clearTimeout, now = o.now || Date.now;
    let timer = null, stopped = false, busy = false, done = false, lastAt = now();
    const live = () => !stopped && !done && box.isConnected;
    async function check() {
      clearTimer(timer); timer = null;
      if (!live()) return stop();
      if (busy) return;
      busy = true;
      try {
        const [sessions, workers] = await Promise.all([o.api("/api/sessions?include_ended=false"), o.api("/api/workers")]);
        if (!live()) return;
        const s = (sessions || []).find(x => x.session_id === o.sid) || { session_id: o.sid, state: "ended" };
        const v = judge(s, workers, now() / 1000);
        if (v.live || v.kind === "ended") { done = true; return o.onLive(v); }
        box.dataset.kind = v.kind;
        title.textContent = v.text.charAt(0).toUpperCase() + v.text.slice(1);
        why.textContent = v.why;
        meta.textContent = `Checked ${v.pc} at ${new Date(now()).toLocaleTimeString()}`;
        if (now() - lastAt > 15000 && last) {                          // the newest picture there is, dimmed
          lastAt = now(); last.hidden = false;
          last.src = last.dataset.base + (last.dataset.base.includes("?") ? "&" : "?") + "t=" + lastAt;
        }
      } catch (e) { if (live()) meta.textContent = `Couldn't check: ${e.message}`; }
      finally { busy = false; }
      if (live()) timer = setTimer(check, 3000);
    }
    bar.addEventListener("click", e => {
      const b = e.target.closest("[data-live-action]");
      if (!b || b.disabled) return;
      if (b.dataset.liveAction === "retry") { meta.textContent = "Checking…"; return check(); }
      if (b.dataset.liveAction === "stop") return o.stop(b);
      if (b.dataset.liveAction === "relaunch") return o.relaunch(b);
    });
    function stop() { stopped = true; clearTimer(timer); timer = null; if (current === ctl) current = null; }
    const ctl = { stop, check };
    current = ctl;
    timer = setTimer(check, 1000);
    return ctl;
  }

  root.GBoxSessionLive = { judge, html, mount, STALE_S, GRACE_S };
  if (typeof module !== "undefined" && module.exports) module.exports = root.GBoxSessionLive;
})(globalThis);
