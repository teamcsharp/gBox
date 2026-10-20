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
//   GBoxAutoplayCoach.mount(root, {sid, api})    wires the box inside root; an unsent draft survives a re-render, and a
//                                                note still capturing keeps its status when the header is drawn again
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
  const HOLD_MS = 4000;                         // the settled full status stays this long before it folds
  // the status gives way before the box: it shrinks first (ellipsis, full text in its tooltip)
  const CSS = `#session-head .coach{display:inline-flex;align-items:center;gap:6px;flex:1 1 240px;min-width:min(100%,200px);max-width:640px}
    #session-head .coach>input,#session-head .coach>.micwrap{flex:1 1 auto;min-width:min(100%,140px);width:auto}
    #session-head .coach .coach-st{flex:0 4 auto;min-width:0;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #session-head .coach .coach-st:empty{display:none}
    #session-head .coach .coach-st[data-state=error]{color:var(--bad)}`;

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
    for (const k of KINDS) {
      const c = (st.captures || {})[k] || {};
      rows.push(`${LABEL[k]}: ${c.state || "pending"}${c.detail ? " - " + c.detail : ""}`);
    }
    if (st.summary) rows.push(st.summary);
    return rows.join("\n");
  }

  function settled(captures) {
    return KINDS.every(k => ((captures || {})[k] || {}).state !== "pending");
  }

  function create({ sid, api, render, interval = 1500, timeout = 180000, hold = HOLD_MS, now = () => Date.now(),
                    sleep = ms => new Promise(r => setTimeout(r, ms)) }) {
    let generation = 0, disposed = false;
    const paint = (gen, view) => { if (!disposed && gen === generation) render(view); };
    const folded = st => ({ text: compactText(st.note, st.captures), title: detailText(st), state: "done", compact: true });

    // poll the note's status until every capture settled (or timeout), then fold it; only the newest note paints
    async function follow(out, gen, since = now()) {
      let st = { note: out.note, number: out.number, captures: out.captures, summary: out.summary || null };
      while (!settled(st.captures) && !disposed && gen === generation && now() - since < timeout) {
        await sleep(interval);
        if (disposed || gen !== generation) return st;
        try { st = await api(`/api/sessions/${encodeURIComponent(sid)}/coach/${encodeURIComponent(out.message_id)}`); }
        catch (e) {                             // a Wi-Fi blip / Spark restart: the next poll catches up
          if (/^404\b/.test(String(e && e.message))) return st;   // the note is gone (its ticket deleted): stop asking
          continue;
        }
        paint(gen, { text: statusText(st.note, st.captures), title: detailText(st), state: settled(st.captures) ? "done" : "pending" });
      }
      if (settled(st.captures) && !disposed && gen === generation) {
        await sleep(hold);
        paint(gen, folded(st));
      }
      return st;
    }

    async function send(raw) {
      const text = String(raw ?? "").trim();
      if (!text) return null;
      const gen = ++generation;
      paint(gen, { text: "Sending note…", title: "", state: "sending" });
      let out;
      try { out = await api(`/api/sessions/${encodeURIComponent(sid)}/coach`, { text }); }
      catch (e) {
        paint(gen, { text: "✗ Note not sent: " + String(e && e.message || e).slice(0, 160), title: String(e && e.message || e), state: "error" });
        throw e;
      }
      paint(gen, { text: statusText(out.note, out.captures), title: detailText(out), state: settled(out.captures) ? "done" : "pending" });
      track(out, gen, now());                   // not awaited: the box is free for the next note at once
      return out;
    }

    function track(out, gen, at) {
      recent.set(sid, { out, at });
      return follow(out, gen, at).then(st => {
        const r = recent.get(sid);
        if (r && r.out.message_id === out.message_id && st && st.captures)
          recent.set(sid, { out: { ...out, captures: st.captures, summary: st.summary }, at });
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
      paint(gen, { text: statusText(r.out.note, r.out.captures), title: detailText(r.out), state: "pending" });
      track(r.out, gen, r.at);
      return true;
    }

    return { send, resume, dispose() { disposed = true; } };
  }

  function html(sid) {
    return `<span class="coach" data-coach data-sid="${ESC(sid)}">` +
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

  function mount(host, { sid, api, ...opts }) {
    style(host && host.ownerDocument);
    const box = host && (host.matches && host.matches("[data-coach]") ? host : host.querySelector("[data-coach]"));
    const input = box && box.querySelector("input"), status = box && box.querySelector("[data-coach-status]");
    if (!input || !status) return null;
    const render = v => { status.textContent = v.text || ""; status.title = v.title || ""; status.dataset.state = v.state || ""; };
    const ctl = create({ sid, api, render, ...opts });
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
      ctl.send(text).catch(() => { if (!input.value) { input.value = text; drafts.set(sid, text); } });   // keep the words
    });
    for (const ev of ["keyup", "keypress"]) input.addEventListener(ev, e => e.stopPropagation());
    ctl.resume();
    return { send: ctl.send, dispose: ctl.dispose, input, status };
  }

  const api = { html, mount, create, statusText, compactText, detailText, settled, PLACEHOLDER, HOLD_MS,
                _drafts: drafts, _recent: recent };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxAutoplayCoach = api;
  if (root.document) style(root.document);
})(typeof globalThis !== "undefined" ? globalThis : this);
