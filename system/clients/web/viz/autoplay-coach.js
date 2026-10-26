// Coach the autoplay (operator 2026-10-20: "During cloud sessions put a text box here where I can type ... and tell it
// things like 'Stop walking into walls', 'that's not an enemy', 'go after the enemy', 'aim at the enemy'"). A one-line
// box in the Sessions header, right of the session id / save icon and left of the ★ ⏸ 🎮 ⌖ ↻ ■ buttons. Enter sends the
// note to POST /api/sessions/{sid}/coach (gbox/coaching.py): it is filed on the game's coaching ticket and its moment is
// captured on the PC running the game (a frame, a save state through gBox's own slot, the main RAM). The status beside
// the box follows those captures until they settle:
//   "Note #3 sent · frame ✓ · state … · RAM ✓"      ✓ attached · ✗ failed · – not taken here · … still capturing
// and a few seconds later folds to "Note #3 ✓" (or "Note #3 · RAM ✗"), so the box keeps its room in a full header; the
// tooltip keeps every detail (ticket, each capture, the RE4 summary). The shell's dictation adds its 🎤 to the box like
// to every text field. The desktop app shows this same header (its Play view embeds the web shell), so the box is there.
//   GBoxAutoplayCoach.html(sid)                  the box's markup for the header
//   GBoxAutoplayCoach.mount(root, {sid, api, onSent})  wires the box inside root; an unsent draft survives a re-render,
//                                                a note still capturing keeps its status when the header is drawn again;
//                                                onSent(answer) after each note is filed (the Sessions page gives a bot
//                                                demo on this PC the keyboard back then). The box shows on every running
//                                                session, so on a bot demo on any PC; each note reaches the agents at once
//                                                (scripts/agent_ledger.py: the inbox hook and `list`)
//   GBoxAutoplayCoach.create({sid, api, render}) the same without a DOM (tests)
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const KINDS = ["frame", "state", "ram"];
  const LABEL = { frame: "frame", state: "state", ram: "RAM" };
  const MARK = { done: "✓", failed: "✗", skipped: "–", pending: "…" };
  const PLACEHOLDER = "Coach the autoplay: stop walking into walls, aim at him…";
  const drafts = new Map();                     // sid -> unsent text
  const recent = new Map();                     // sid -> {out, at}: the latest note, to resume its status after a re-render
  const retries = new Map();                    // sid -> one failed/uncertain submission, retried with the same ID
  const RETRY_KEY = "gbox.coach.uncertain.v1", RETRY_AGE = 86400000;
  function storedRetries(storage, now) {
    try { return JSON.parse(storage?.getItem(RETRY_KEY) || "[]").filter(x =>
      typeof x.sid === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(x.sid) && typeof x.text === "string" && x.text.length <= 2000 &&
      typeof x.clientId === "string" && /^[A-Za-z0-9_-]{8,96}$/.test(x.clientId) && Number.isFinite(x.at) && now >= x.at && now - x.at <= RETRY_AGE).slice(-50); }
    catch { return []; }
  }
  // Instant commands (operator 2026-10-24): the bot acts on these within a second (gbox/mercs/directives.py has the same ids).
  const COMMANDS = [
    ["fight", "Fight them!", "Stop standing there and fight the foes"],
    ["next_area", "Go to the next area", "Leave this goal for the next time bonus / area"],
    ["explore", "Navigate more of the level", "Reset the route and explore"],
    ["hunt", "Go after the enemies", "Seek, find and dispatch them"],
    ["score", "Go for score increases", "Build the combo"],
    ["repetitive", "You are doing a repetitive action", "Stop it and go forward"],
    ["mine", "Drop a mine and flee", "Plant a mine, then leave"],
    ["mine_trail", "Drop mines while leaving the area", "Plant, move on, repeat for 45 s (RE5, mines setting on)"],
    ["missing", "You are missing", "Adjust the aim for this weapon"],
  ];
  const HOLD_MS = 4000;                         // the settled full status stays this long before it folds
  // the status gives way before the box: it shrinks first (ellipsis, full text in its tooltip)
  const CSS = `#session-head .coach{display:inline-flex;align-items:center;gap:6px;flex:1 1 240px;min-width:min(100%,200px);max-width:640px}
    #session-head .coach>input,#session-head .coach>.micwrap{flex:1 1 auto;min-width:min(100%,140px);width:auto}
    #session-head .coach .coach-st{flex:0 4 auto;min-width:0;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #session-head .coach .coach-st:empty{display:none}
    #session-head .coach .coach-st[data-state=error]{color:var(--bad)}
    .coach .coach-cmds{flex:0 0 auto;width:24px;height:23px;padding:0;border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;-webkit-app-region:no-drag}
    .coach-menu{position:fixed;z-index:200;min-width:260px;background:#1d1d22;border:1px solid #555;border-radius:8px;padding:4px;box-shadow:0 8px 24px #0009;-webkit-app-region:no-drag}
    .coach-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:#e8e8ee;padding:6px 10px;border-radius:5px;cursor:pointer;font-size:13px}
    .coach-menu button:hover,.coach-menu button:focus-visible{background:#ffffff1a}.coach-menu small{display:block;color:#aaa;font-size:11px}`;

  function statusText(note, captures) {
    return [`Note #${note ?? "?"} sent`, ...KINDS.map(k => `${LABEL[k]} ${MARK[(captures && captures[k] || {}).state] || MARK.pending}`)]
      .join(" · ");
  }

  // the settled status folded: "Note #3 ✓", "Note #3 ✓ · state –" (not taken here), "Note #3 · RAM ✗" (failed)
  function compactText(note, captures) {
    const of = s => KINDS.filter(k => ((captures || {})[k] || {}).state === s).map(k => `${LABEL[k]} ${MARK[s]}`);
    const failed = of("failed");
    return failed.length ? [`Note #${note ?? "?"}`, ...failed].join(" · ") : [`Note #${note ?? "?"} ✓`, ...of("skipped")].join(" · ");
  }

  // the tooltip: the ticket, each capture's detail and (RE4) the decoded moment
  function detailText(st) {
    const rows = [`Coaching ticket #${st.number ?? "?"}, note ${st.note ?? "?"}`];
    if (st.task_dispatch_unavailable) rows.push("Note saved; automatic task dispatch requires the updated server. Do not resend it.");
    if (st.implementation_number) rows.push(`Implementation task #${st.implementation_number} queued; starts when admitted.`);
    else if (st.change_id) rows.push(`Change ${st.change_id}: ${st.dispatch_state || "open"}${st.dispatch_state === "uncertain" ? "; task creation needs review" : ""}`);
    for (const k of KINDS) {
      const c = (st.captures || {})[k] || {};
      rows.push(`${LABEL[k]}: ${c.state || "pending"}${c.detail ? " - " + c.detail : ""}`);
    }
    for (const [name, item] of Object.entries(st.evidence || {}))
      rows.push(`Report ${name}: ${item.state}${item.detail ? " - " + item.detail : ""}${item.age_s != null ? ` (age ${item.age_s}s)` : ""}`);
    if (st.summary) rows.push(st.summary);
    return rows.join("\n");
  }

  function settled(captures) {
    return KINDS.every(k => ((captures || {})[k] || {}).state !== "pending");
  }

  function noteView(st, compact = false) {
    const uncertain = st.change_id && ["creating", "uncertain"].includes(st.dispatch_state);
    let base = compact ? compactText(st.note, st.captures) : statusText(st.note, st.captures);
    if (st.evidence && Object.keys(st.evidence).length)
      base += ["stream", "map", "moment"].map(k => ` · ${k === "stream" ? "report image" : k} ${MARK[(st.evidence[k] || {}).state] || "?"}`).join("");
    return { text: st.task_dispatch_unavailable ? `Note #${st.note ?? "?"} saved; task dispatch needs server update`
      : uncertain ? `Note #${st.note ?? "?"} saved; task creation unconfirmed`
      : base + (st.implementation_number ? ` · task #${st.implementation_number} queued` : ""),
      title: detailText(st), state: st.task_dispatch_unavailable || uncertain || Object.values(st.evidence || {}).some(x => x.state === "failed")
        ? "error" : settled(st.captures) ? "done" : "pending", compact };
  }

  function create({ sid, api, render, interval = 1500, timeout = 180000, hold = HOLD_MS, now = () => Date.now(),
                    sleep = ms => new Promise(r => setTimeout(r, ms)), idempotent = false,
                    makeId = () => root.crypto?.randomUUID?.() || `coach-${Date.now()}-${Math.random().toString(36).slice(2)}` }) {
    let generation = 0, disposed = false;
    let storage;
    try { storage = root.sessionStorage; } catch {} // sandboxed documents can deny storage
    function keepAttempt(value) {
      if (value) retries.set(sid, value); else retries.delete(sid);
      try {
        const rows = storedRetries(storage, now()).filter(x => x.sid !== sid);
        if (value) rows.push({sid, text: value.text, clientId: value.clientId, at: value.at,
          uncertain: !!value.uncertain, lookupSupported: !!value.lookupSupported, replayBlocked: !!value.replayBlocked});
        storage?.setItem(RETRY_KEY, JSON.stringify(rows.slice(-50)));
      } catch {} // the in-memory identity still protects retries in this view
    }
    const sending = new Map();
    const paint = (gen, view) => { if (!disposed && gen === generation) render(view); };
    const folded = st => noteView(st, true);

    // poll the note's status until every capture settled (or timeout), then fold it; only the newest note paints
    async function follow(out, gen, since = now()) {
      let st = { ...out, summary: out.summary || null };
      while (!settled(st.captures) && !disposed && gen === generation && now() - since < timeout) {
        await sleep(interval);
        if (disposed || gen !== generation) return st;
        try { st = { ...out, ...await api(`/api/sessions/${encodeURIComponent(sid)}/coach/${encodeURIComponent(out.message_id)}`) }; }
        catch (e) {                             // a Wi-Fi blip / Spark restart: the next poll catches up
          if (/^404\b/.test(String(e && e.message))) {
            paint(gen, { text: "Coaching note no longer available", title: String(e.message), state: "error", compact: true });
            return st;
          }
          continue;
        }
        paint(gen, noteView(st));
      }
      if (settled(st.captures) && !disposed && gen === generation) {
        await sleep(hold);
        paint(gen, folded(st));
      } else if (!disposed && gen === generation && now() - since >= timeout) {
        paint(gen, { text: `Note #${st.note ?? "?"} sent · captures still pending`, title: detailText(st), state: "error", compact: true });
      }
      return st;
    }

    async function recover(clientId) {
      let receipt = null;
      for (let i = 0; i < 3 && !disposed; i++) {
        if (i) await sleep(500);
        try { receipt = await api(`/api/sessions/${encodeURIComponent(sid)}/coach/submissions/${encodeURIComponent(clientId)}`); }
        catch (e) { if (/^404\b/.test(String(e?.message))) return null; continue; }
        if (receipt?.session_id !== sid || receipt?.client_id !== clientId) return null;
        if (receipt.state === "saved" && receipt.result?.message_id) return receipt;
        if (!["missing", "pending"].includes(receipt.state)) return null;
      }
      return receipt;
    }

    async function submit(text) {
      const gen = ++generation;
      paint(gen, { text: "Sending note…", title: "", state: "sending" });
      let out;
      const previous = retries.get(sid) || storedRetries(storage, now()).find(x => x.sid === sid);
      const clientId = idempotent ? previous?.text === text ? previous.clientId : makeId() : null;
      const attempt = { ...(previous?.text === text ? previous : {}), text, clientId, at: previous?.text === text ? previous.at : now() };
      if (clientId) keepAttempt(attempt);
      try {
        // An old server ignored retry IDs. After an ambiguous response, never replay a POST to it.
        if (previous?.text === text && previous.uncertain && (previous.replayBlocked || !previous.lookupSupported)) {
          const receipt = await recover(clientId);
          attempt.lookupSupported = !!receipt;
          if (receipt?.state === "saved") out = receipt.result;
          else if (previous.replayBlocked || receipt?.state !== "missing") throw Object.assign(Error("Delivery unconfirmed; check the coaching ticket before resending."), { receiptChecked: true });
        }
        if (!out) {
          // F5 during this POST is also an ambiguous delivery, even before its timeout handler executes.
          if (clientId) keepAttempt({ ...attempt, uncertain: true, replayBlocked: true });
          out = await api(`/api/sessions/${encodeURIComponent(sid)}/coach`, { text, ...(clientId ? { client_id: clientId } : {}) });
        }
      }
      catch (e) {
        const uncertain = !!clientId && !/^(400|401|403|404|422)\b/.test(String(e?.message));
        if (uncertain) {
          const receipt = e.receiptChecked ? null : await recover(clientId);
          attempt.uncertain = true; attempt.lookupSupported ||= !!receipt;
          attempt.replayBlocked = !!previous?.replayBlocked || !receipt;
          keepAttempt(attempt);
          if (receipt?.state === "saved") out = receipt.result;
          else paint(gen, { text: "Delivery unconfirmed; checking the saved note is safe. Do not resend as a new note.",
            title: String(e?.message || e), state: "error" });
        } else {
          if (clientId) keepAttempt(null);
          paint(gen, { text: "✗ Note not sent: " + String(e && e.message || e).slice(0, 160), title: String(e && e.message || e), state: "error" });
        }
        if (!out) throw e;
      }
      if (idempotent && !out.change_id) out = { ...out, task_dispatch_unavailable: true };
      if (retries.get(sid)?.clientId === clientId) keepAttempt(null);
      paint(gen, noteView(out));
      track(out, gen, now());                   // not awaited: the box is free for the next note at once
      return out;
    }

    function send(raw) {
      const text = String(raw ?? "").trim();
      if (!text || disposed) return Promise.resolve(null);
      if (sending.has(text)) return sending.get(text);
      const task = submit(text).finally(() => sending.delete(text));
      sending.set(text, task);
      return task;
    }

    function track(out, gen, at) {
      recent.set(sid, { out, at });
      return follow(out, gen, at).then(st => {
        const r = recent.get(sid);
        if (r && r.out.message_id === out.message_id && st && st.captures)
          recent.set(sid, { out: { ...out, ...st }, at });
        return st;
      });
    }

    // a header drawn again (another view of the same game, the app reloading it): the newest note's status comes back
    // and, while it still captures, keeps updating
    function resume() {
      const r = recent.get(sid);
      if (!r || now() - r.at > timeout) return false;
      const gen = ++generation;
      if (settled(r.out.captures)) { paint(gen, folded(r.out)); return true; }   // settled: its folded line, nothing to poll
      paint(gen, noteView(r.out));
      track(r.out, gen, r.at);
      return true;
    }

    return { send, resume, dispose() { disposed = true; } };
  }

  function html(sid) {
    return `<span class="coach" data-coach data-sid="${ESC(sid)}">` +
      `<button type="button" class="coach-cmds" data-coach-cmds aria-haspopup="menu" aria-expanded="false" ` +
      `aria-label="Instant commands for the bot" title="Instant commands: the bot does it at once">▾</button>` +
      `<input type="text" class="coach-in" maxlength="2000" autocomplete="off" placeholder="${ESC(PLACEHOLDER)}" ` +
      `aria-label="Coach the autoplay (Enter sends the note)" title="Tell the autoplay what to do better. Each note goes to this ` +
      `game's coaching ticket with a frame, a save state (gBox's own slot, never yours) and the game's RAM.">` +
      `<span class="coach-st mut" data-coach-status role="status" aria-live="polite"></span></span>`;
  }

  // the styles go in when the script loads: the shell's dictation wraps the input (🎤) from the box's computed style
  function style(doc) {
    if (doc && doc.head && doc.getElementById && !doc.getElementById("autoplay-coach-css")) {
      const st = doc.createElement("style"); st.id = "autoplay-coach-css"; st.textContent = CSS; doc.head.append(st);
    }
  }

  function mount(host, { sid, api, onSent, onState, ...opts }) {
    style(host && host.ownerDocument);
    const box = host && (host.matches && host.matches("[data-coach]") ? host : host.querySelector("[data-coach]"));
    const input = box && box.querySelector("input"), status = box && box.querySelector("[data-coach-status]");
    if (!input || !status) return null;
    const render = v => {
      status.textContent = v.text || ""; status.title = v.title || ""; status.dataset.state = v.state || "";
      input.readOnly = v.state === "sending";
      if (onState) onState(v);
    };
    const ctl = create({ sid, api, render, ...opts });
    const cmdButton = box.querySelector("[data-coach-cmds]");
    let menu = null, unlisten = null;
    const closeMenu = () => {
      if (unlisten) { unlisten(); unlisten = null; }
      if (menu) { menu.remove(); menu = null; cmdButton?.setAttribute("aria-expanded", "false"); }
    };
    async function command(id) {
      closeMenu();
      const label = (COMMANDS.find(c => c[0] === id) || [])[1] || id;
      render({ state: "sending", text: `${label}…` });
      try {
        const out = await api(`/api/sessions/${encodeURIComponent(sid)}/directive`, { command: id });
        render({ state: "done", text: `${label} · sent`, title: out?.directive?.label || "" });
      } catch (error) { render({ state: "error", text: error.message || "Command not sent", title: error.message || "" }); }
    }
    if (cmdButton) {
      cmdButton.addEventListener("click", e => {
        e.preventDefault(); e.stopPropagation();
        if (menu) { closeMenu(); return; }
        const doc = box.ownerDocument, r = cmdButton.getBoundingClientRect();
        // a menu left by an earlier mount (the PiP re-mounts the box on a stream reconnect) never stays on screen
        if (doc.querySelectorAll) doc.querySelectorAll(".coach-menu").forEach(old => old.remove());
        menu = doc.createElement("div"); menu.className = "coach-menu"; menu.setAttribute("role", "menu");
        menu.innerHTML = COMMANDS.map(([id, label, hint]) =>
          `<button type="button" role="menuitem" data-cmd="${ESC(id)}">${ESC(label)}<small>${ESC(hint)}</small></button>`).join("");
        Object.assign(menu.style, { left: Math.max(4, r.left) + "px", top: r.bottom + 4 + "px" });
        menu.addEventListener("click", ev => { const b = ev.target.closest("[data-cmd]"); if (b) { ev.stopPropagation(); command(b.dataset.cmd); } });
        menu.addEventListener("keydown", ev => { ev.stopPropagation(); if (ev.key === "Escape") { closeMenu(); cmdButton.focus(); } });
        doc.body.append(menu); cmdButton.setAttribute("aria-expanded", "true"); menu.querySelector("button")?.focus();
        // closes on a click anywhere else, on the pointer going to the native game surface (the document loses focus:
        // no DOM click ever arrives from it - operator 2026-10-26: "close dropdowns when i click away. I cant close this
        // now"), on the view being hidden, and on Escape; every path removes its listeners
        const away = ev => { if (menu && !menu.contains(ev.target) && ev.target !== cmdButton) closeMenu(); };
        const win = doc.defaultView;
        doc.addEventListener("mousedown", away, true); doc.addEventListener("pointerdown", away, true);
        if (win && win.addEventListener) win.addEventListener("blur", closeMenu);
        doc.addEventListener("visibilitychange", closeMenu);
        unlisten = () => {
          doc.removeEventListener("mousedown", away, true); doc.removeEventListener("pointerdown", away, true);
          if (win && win.removeEventListener) win.removeEventListener("blur", closeMenu);
          doc.removeEventListener("visibilitychange", closeMenu);
        };
      });
    }
    if (drafts.has(sid)) input.value = drafts.get(sid);
    input.addEventListener("input", () => { if (input.value) drafts.set(sid, input.value); else drafts.delete(sid); });
    input.addEventListener("keydown", e => {
      e.stopPropagation();                      // the operator's words: never a page shortcut or game input
      if (e.key === "Escape") { input.blur(); return; }
      if (e.key !== "Enter" || e.isComposing || e.shiftKey) return;
      e.preventDefault();
      const text = input.value;
      if (!text.trim()) return;
      input.value = ""; drafts.delete(sid);
      ctl.send(text).then(out => { if (out && onSent) { try { onSent(out); } catch {} } },   // e.g. the game gets the keys back
        () => { if (!input.value) { input.value = text; drafts.set(sid, text); } });   // not sent: keep the words
    });
    for (const ev of ["keyup", "keypress"]) input.addEventListener(ev, e => e.stopPropagation());
    ctl.resume();
    return { send: ctl.send, dispose() { closeMenu(); ctl.dispose(); }, input, status, command };
  }

  const api = { html, mount, create, COMMANDS, statusText, compactText, detailText, settled, PLACEHOLDER, HOLD_MS,
                _drafts: drafts, _recent: recent };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxAutoplayCoach = api;
  if (root.document) style(root.document);
})(typeof globalThis !== "undefined" ? globalThis : this);
