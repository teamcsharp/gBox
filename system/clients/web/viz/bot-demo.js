// Bot demos on any PC (operator 2026-10-20: "I want to be able to launch bot demos and watch them even from PCs I am
// active at ... launch bot demos on computers that even I am on and be able to chat about the gameplay"). Every launch
// menu offers "🤖 Bot demo on <PC>" for each online PC, the one you are on included: the library cards, the library
// right-click menu (viz/game-menu.js), the Sessions header, and in the desktop app the docked game's right-click menu
// and a conversation's game chip. A bot demo is your own launch with autoplay on
// (POST /api/games/{id}/launch?node=<PC>&autoplay=true): no background admission (it is not an agent's job), the
// game's playbook takes it from boot into gameplay (RE4: title -> The Mercenaries -> a round), and the session is marked
// a bot demo (GET /api/sessions bot_demo): the Sessions header says "🤖 Bot demo", keeps Stop and the coach box. On a PC
// you are using, the bot never takes your keyboard (gbox.adapters.polite_verdict): it waits while you type.
// Plain functions over a tiny DOM surface, so node tests drive it (tests/test_bot_demo.cjs).
//   GBoxBotDemo.pcs(workers, here)           -> [{name, os, here, label}] online PCs: this one, the Spark, the rest
//   GBoxBotDemo.itemsHTML(pcs, cls)          -> the menu's buttons, each data-bot-demo="<PC name>"
//   GBoxBotDemo.badgeHTML(session, tel)      -> the Sessions header's "🤖 Bot demo" chip ('' for any other session)
//   GBoxBotDemo.buttonHTML(gid)              -> the header's / a card's "🤖 Demo ▾" button (data-bot-demo-open)
//   GBoxBotDemo.open(doc, {x, y, gid, title, pcs, launch})   a small menu at x, y; a pick calls launch(gid, pc)
//   GBoxBotDemo.launchPath(gid, pc, mod)     -> the launch URL a bot demo posts
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const isSpark = w => (w.os || "") === "linux";

  function pcs(workers, here) {
    const on = (Array.isArray(workers) ? workers : []).filter(w => w && w.name && w.online !== false);
    const seen = new Set(), out = [];
    for (const w of on) {
      if (seen.has(w.name)) continue;
      seen.add(w.name);
      const mine = !!here && w.name === here;
      out.push({ name: w.name, os: w.os || "", here: mine,
                 label: `🤖 Bot demo on ${w.name}${mine ? " (this PC)" : isSpark(w) ? " (the Spark)" : ""}` });
    }
    const rank = p => p.here ? 0 : p.os === "linux" ? 1 : 2;
    return out.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }

  function itemsHTML(list, cls = "act") {
    if (!list || !list.length) return `<div class="mut" style="font-size:11px">No PC is online for a bot demo.</div>`;
    return list.map(p => `<button class="${ESC(cls)}" type="button" role="menuitem" data-bot-demo="${ESC(p.name)}" `
      + `title="${ESC(`${p.name} plays this game by itself from boot (its playbook, your style, straight into gameplay)`
      + `${p.here ? ": here, on the PC you are using; the bot waits while you type" : ""}. Your launch: it never waits for an idle PC. Stop ends it.`)}">`
      + `${ESC(p.label)}</button>`).join("");
  }

  // the Sessions header: this session is a bot demo (launched with autoplay on), with what autoplay is doing now
  function badgeHTML(s, tel) {
    if (!s || !(s.bot_demo || (tel && tel.demo))) return "";
    const doing = tel && tel.running ? (tel.mission || tel.mode || "playing") : tel && tel.mode ? "autoplay stopped" : "starting";
    return `<span class="bot-demo-badge" data-bot-demo-badge title="A bot demo: autoplay plays this game by itself (${ESC(doing)}). `
      + `Touch your pad to take over; Stop ends it. Coach it in the box beside: each note goes to the agents with this moment."`
      + ` style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:12px;`
      + `background:#2c3a5c;color:#cfe0ff;white-space:nowrap">🤖 Bot demo</span>`;
  }

  function buttonHTML(gid, label = "🤖 Demo ▾") {
    return `<button class="act" type="button" data-bot-demo-open="${ESC(gid)}" aria-haspopup="menu" `
      + `title="Bot demo on a PC: it plays this game by itself from boot (any PC, the one you are on included)">${ESC(label)}</button>`;
  }

  function launchPath(gid, pc, mod = "") {
    return `/api/games/${encodeURIComponent(gid)}/launch?node=${encodeURIComponent(pc)}&autoplay=true`
      + (mod ? `&mod=${encodeURIComponent(mod)}` : "");
  }

  // a small menu of PCs at x, y (fixed); a pick calls launch(gid, pc). Closes on a pick, Escape or a click outside.
  function open(doc, { x = 0, y = 0, gid, title = "", pcs: list = [], launch, place } = {}) {
    let m = doc.getElementById("bot-demo-menu");
    if (!m) {
      m = doc.createElement("div"); m.id = "bot-demo-menu"; m.setAttribute("role", "menu");
      m.style.cssText = "position:fixed;z-index:120;background:var(--bg,#111);border:1px solid var(--line,#444);border-radius:8px;"
        + "padding:6px;box-shadow:0 10px 30px #000a;min-width:220px;display:none;flex-direction:column;gap:4px;font-size:13px";
      doc.body.append(m);
    }
    m.innerHTML = `<div class="mut" style="font-size:11px;padding:0 2px 2px">${ESC(title ? title + ": " : "")}bot demo on…</div>` + itemsHTML(list);
    m.style.display = "flex";
    if (place) { try { place(m, x, y); } catch { m.style.left = x + "px"; m.style.top = y + "px"; } }
    else { m.style.left = x + "px"; m.style.top = y + "px"; }
    const close = () => { m.style.display = "none"; doc.removeEventListener("mousedown", outside, true); doc.removeEventListener("keydown", esc, true); };
    const outside = e => { if (!m.contains(e.target)) close(); };
    const esc = e => { if (e.key === "Escape") close(); };
    setTimeout(() => { doc.addEventListener("mousedown", outside, true); doc.addEventListener("keydown", esc, true); }, 0);
    m.onclick = e => {
      const b = e.target.closest && e.target.closest("[data-bot-demo]");
      if (!b) return;
      close();
      if (launch) launch(gid, b.dataset.botDemo);
    };
    return { el: m, close };
  }

  const api = { pcs, itemsHTML, badgeHTML, buttonHTML, launchPath, open };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxBotDemo = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
