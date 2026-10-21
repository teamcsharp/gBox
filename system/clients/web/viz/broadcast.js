/* Broadcast (docs/broadcast.md): what gBox puts on air for Pine Box and any media source (OBS, VLC, ffmpeg).
   Operator 2026-10-20: "I need pine box to be able to connect to the active gbox feed of any instance of gbox on the
   network showing gameplay ... stable streaming video via pine box as a media source."
   - watching(sid): the app tells the control plane which game it shows (POST /api/broadcast/watching), on every change
     and once a minute while the window is visible; in auto the program follows it.
   - button(sid) / mount(head, {sid, api}): the session header's On air button. Pressed: this game is on air. Click:
     put this game on air (pinned), or, when it is pinned already, give the program back to auto.
   - panelHTML() / mountPanel(el, {api}): the Sessions list's Broadcast bar: what is on air and why, Auto, the program's
     picture, and the media-source links (broadcast tokens: make one, see its URLs once, revoke it).
   Pure helpers (state, line, links) are what tests/test_broadcast_control.cjs drives. No framework. */
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const HEARTBEAT_MS = 60000;
  const POLL_MS = 5000;
  const ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round"><circle cx="12" cy="12" r="2"/><path d="M8.5 15.5a5 5 0 0 1 0-7M15.5 8.5a5 5 0 0 1 0 7"/>' +
    '<path d="M5.6 18.4a9 9 0 0 1 0-12.8M18.4 5.6a9 9 0 0 1 0 12.8"/></svg>';
  const CSS = `#session-head #onairbtn[aria-pressed=true]{border-color:var(--bad,#ff6b6b);color:var(--bad,#ff6b6b)}
    #broadcast-panel{border:1px solid var(--line,#2c2c34);border-radius:8px;padding:8px 10px;margin:0 0 12px;display:grid;gap:8px}
    #broadcast-panel .bc-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    #broadcast-panel .bc-dot{width:9px;height:9px;border-radius:50%;background:var(--mut,#9a9aa6);flex:none}
    #broadcast-panel .bc-dot.live{background:var(--bad,#ff6b6b)}
    #broadcast-panel img{width:160px;height:90px;object-fit:contain;background:#000;border-radius:4px;flex:none}
    #broadcast-panel code{font-size:11px;word-break:break-all}
    #broadcast-panel table{font-size:12px;border-collapse:collapse} #broadcast-panel td{padding:2px 8px 2px 0}`;

  // --- pure ---------------------------------------------------------------------------------------------------------
  // The On air button for session `sid`, from GET /api/broadcast's program: { pressed, label, title, next } where next is
  // what a click POSTs to /api/broadcast/program.
  function state(program, sid) {
    const p = program || {};
    const onAir = !!sid && p.session_id === sid;
    const pinned = p.mode === "session" && p.target === sid;
    if (pinned) return { pressed: true, label: "On air (pinned)", next: { session_id: "auto" },
      title: "This game is pinned on the broadcast program. Click: back to auto (the program follows the game you watch)." };
    if (onAir) return { pressed: true, label: "On air", next: { session_id: sid },
      title: `On the broadcast program (${p.why || "auto"}). Click: pin it so it stays on air whatever you watch.` };
    const now = p.title ? `${p.title}${p.pc ? " on " + p.pc : ""}` : "nothing";
    return { pressed: false, label: "Put on air", next: { session_id: sid },
      title: `Put this game on the broadcast program (Pine Box). On air now: ${now}.` };
  }

  // The Broadcast bar's sentence about the program (pure).
  function line(program) {
    const p = program || {};
    const mode = p.mode === "session" ? "pinned" : p.mode === "pc" ? `pinned to ${p.target}` : "auto";
    if (!p.session_id) return `Nothing on air · ${p.why || "no game is running"} · ${mode}`;
    const what = `${p.title || p.session_id}${p.pc ? " on " + p.pc : ""}`;
    const pic = p.state === "slate" ? " · waiting for its picture" : p.state === "hold" ? " · holding the last picture" : "";
    return `On air: ${what}${pic} · ${p.why || mode}`;
  }

  // The URLs a new broadcast token answers with, as rows for the panel (pure): [{ where, format, url }].
  function links(created) {
    const out = [];
    for (const [where, urls] of Object.entries((created && created.program) || {}))
      for (const fmt of ["mjpeg", "ts", "hls", "jpeg"]) if (urls[fmt]) out.push({ where, format: fmt, url: urls[fmt] });
    for (const [where, url] of Object.entries((created && created.feeds) || {})) out.push({ where, format: "feeds", url });
    return out;
  }

  const ago = s => s == null ? "never" : s < 90 ? `${Math.round(s)} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago`
    : s < 172800 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;

  // --- watching heartbeat ------------------------------------------------------------------------------------------
  const W = { sid: undefined, sent: 0, timer: null, api: null, doc: null };
  function send() {
    if (!W.api) return;
    W.sent = Date.now();
    Promise.resolve(W.api("/api/broadcast/watching", { session_id: W.sid || null })).catch(() => {});   // old server: no route
  }
  function watching(sid, io) {
    W.api = (io && io.api) || W.api;
    W.doc = (io && io.doc) || W.doc || root.document;
    const changed = (sid || null) !== (W.sid === undefined ? undefined : W.sid || null);
    W.sid = sid || null;
    if (changed) send();
    if (!W.timer && root.setInterval) {
      W.timer = root.setInterval(() => {
        if (!W.sid || (W.doc && W.doc.hidden)) return;           // a hidden app is not watching
        if (Date.now() - W.sent >= HEARTBEAT_MS - 1000) send();
      }, HEARTBEAT_MS);
    }
  }

  // --- the session header's button --------------------------------------------------------------------------------
  function style(doc) {
    if (doc && doc.head && !doc.getElementById("broadcast-css")) {
      const st = doc.createElement("style"); st.id = "broadcast-css"; st.textContent = CSS; doc.head.append(st);
    }
  }
  function button(sid) {
    return `<button class="act" id="onairbtn" data-sid="${ESC(sid)}" style="padding:5px 7px;line-height:0" aria-pressed="false" ` +
      `aria-label="Put on air" title="Broadcast: put this game on the program Pine Box shows">${ICON}</button>`;
  }
  let header = null;
  function mount(head, io) {
    header?.stop();
    const doc = head && head.ownerDocument, btn = doc && doc.getElementById("onairbtn");
    if (!btn) return (header = null);
    style(doc);
    let program = null, stopped = false, timer = null;
    const paint = () => {
      const s = state(program, io.sid);
      btn.setAttribute("aria-pressed", String(s.pressed)); btn.setAttribute("aria-label", s.label); btn.title = s.title;
    };
    const poll = async () => {
      try { program = (await io.api("/api/broadcast")).program; } catch { program = null; }
      if (!stopped) paint();
    };
    btn.onclick = async () => {
      btn.disabled = true;
      try { program = (await io.api("/api/broadcast/program", state(program, io.sid).next)).program; paint(); }
      catch (e) { btn.title = `Could not switch the broadcast: ${e.message || e}`; }
      finally { btn.disabled = false; }
    };
    poll();
    timer = root.setInterval ? root.setInterval(poll, POLL_MS) : null;
    header = { stop() { stopped = true; if (timer) root.clearInterval(timer); }, poll };
    return header;
  }

  // --- the Sessions list's Broadcast bar ------------------------------------------------------------------------------
  function panelHTML() {
    return `<section id="broadcast-panel" aria-label="Broadcast"><div class="bc-row"><span class="bc-dot" id="bc-dot"></span>
      <b>Broadcast</b><span id="bc-line" class="mut">Checking what is on air…</span>
      <button class="act" id="bc-auto" type="button" title="The program follows the game you watch">Auto</button>
      <button class="act" id="bc-links" type="button" aria-expanded="false" title="Links for Pine Box, OBS or VLC (broadcast tokens)">Media-source links</button></div>
      <div class="bc-row"><img id="bc-pic" alt="The broadcast program"><span class="mut" style="font-size:12px">The program: the game you watch here,
      or the one you put on air (the On air button in a game's header). MJPEG, MPEG-TS and HLS; see docs/broadcast.md.</span></div>
      <div id="bc-tokens" hidden></div></section>`;
  }
  let panel = null;
  function mountPanel(el, io) {
    panel?.stop();
    if (!el) return (panel = null);
    const doc = el.ownerDocument;
    style(doc);
    const $ = id => doc.getElementById(id);
    let stopped = false, timer = null, picUrl = null;
    const fetchPic = async () => {                                 // the main token stays in a header, never in a URL
      if (!io.fetch) return;
      try {
        const r = await io.fetch("/api/broadcast/program.jpg");
        if (!r.ok) return;
        const url = root.URL.createObjectURL(await r.blob());
        if (picUrl) root.URL.revokeObjectURL(picUrl);
        picUrl = url; if ($("bc-pic")) $("bc-pic").src = url;
      } catch {}
    };
    const poll = async () => {
      let st = null;
      try { st = await io.api("/api/broadcast"); } catch (e) { if ($("bc-line")) $("bc-line").textContent = `Broadcast unavailable: ${e.message || e}`; return; }
      if (stopped) return;
      const p = st.program || {};
      $("bc-line").textContent = line(p);
      $("bc-dot").classList.toggle("live", !!p.session_id && p.state === "live");
      $("bc-auto").disabled = p.mode === "auto";
      fetchPic();
    };
    const tokens = async (created) => {
      let rows = [];
      try { rows = await io.api("/api/broadcast/tokens"); } catch (e) { $("bc-tokens").innerHTML = `<p class="bad">${ESC(e.message || e)}</p>`; return; }
      const fresh = created ? `<p><b>${ESC(created.name)}</b>: copy these now, the token is not shown again.</p>
        <table>${links(created).map(l => `<tr><td class="mut">${ESC(l.where)}</td><td>${ESC(l.format)}</td><td><code>${ESC(l.url)}</code></td></tr>`).join("")}</table>` : "";
      $("bc-tokens").innerHTML = `${fresh}<div class="bc-row"><input id="bc-name" type="text" placeholder="Name, e.g. Pine Box" style="width:180px">
        <label style="display:flex;gap:4px;align-items:center;margin:0"><input id="bc-control" type="checkbox"> may switch the program</label>
        <button class="act pri" id="bc-new" type="button">Make a link</button></div>
        <table>${rows.map(r => `<tr><td>${ESC(r.name)}</td><td class="mut">${ESC(r.scope)}</td>
          <td class="mut">${r.revoked ? "revoked" : "used " + ago(r.last_used ? Date.now() / 1000 - r.last_used : null)}</td>
          <td>${r.revoked ? "" : `<button class="act" data-revoke="${ESC(r.id)}" type="button">Revoke</button>`}</td></tr>`).join("")}</table>`;
      $("bc-new").onclick = async () => {
        try { tokens(await io.api("/api/broadcast/tokens", { name: $("bc-name").value || "media source", scope: $("bc-control").checked ? "control" : "view" })); }
        catch (e) { $("bc-tokens").insertAdjacentHTML("afterbegin", `<p class="bad">${ESC(e.message || e)}</p>`); }
      };
      $("bc-tokens").querySelectorAll("[data-revoke]").forEach(b => {
        b.onclick = async () => { try { await io.api(`/api/broadcast/tokens/${encodeURIComponent(b.dataset.revoke)}`, undefined, "DELETE"); } catch {} tokens(); };
      });
    };
    $("bc-auto").onclick = async () => { try { await io.api("/api/broadcast/program", { session_id: "auto" }); } catch {} poll(); };
    $("bc-links").onclick = () => {
      const box = $("bc-tokens"), open = box.hidden;
      box.hidden = !open; $("bc-links").setAttribute("aria-expanded", String(open));
      if (open) tokens();
    };
    poll();
    timer = root.setInterval ? root.setInterval(poll, POLL_MS) : null;
    panel = { stop() { stopped = true; if (timer) root.clearInterval(timer); if (picUrl) root.URL.revokeObjectURL(picUrl); }, poll, tokens };
    return panel;
  }

  const api = { state, line, links, watching, button, mount, panelHTML, mountPanel, HEARTBEAT_MS, _W: W };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxBroadcast = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
