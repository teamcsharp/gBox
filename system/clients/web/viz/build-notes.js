// Build notifications in the header bell tray (gbox/build_notify.py over GET /api/notify): every build the Spark
// finishes, every failed build and every character collect posts an entry ({auto: "build", kind: build | error |
// collect, items: [...]}); a pass that queued many jobs is one entry with the list.
//   build   - the thumbnail (a frame of the build running > fitting preview > build preview > donor > box art, served by
//             /api/notify/{id}/thumb), the title + summary, the time, Play (this PC, through the same launch path the
//             Mods page and Special builds use, so the mod is staged / fetched), a small ▾ with the other launch options
//             (other PCs, saved moment, the Spark debugger) and Open in Mods.
//   error   - the reason, Open request, Retry build (when the job left a rebuild recipe).
//   collect - "N characters collected from <game>", Open models.
// New entries also show a toast with Play (and, in the desktop app, an OS notification over the GBOX: bridge). The toast
// is a card in the shell's toast stack (viz/toast-stack.js): below the measured header, newest first, inside the window.
// Plain functions returning HTML strings + a click dispatcher over an io object, so node tests drive them without a
// DOM (tests/test_build_notes.cjs). Older notifications (title / text / session_id) render as before.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const TOAST_MS = 12000;

  const isAuto = n => !!n && n.auto === "build";
  const itemsOf = n => (isAuto(n) && Array.isArray(n.items) && n.items.length ? n.items : []);
  const unread = notes => (notes || []).filter(n => !n.read).length;
  const timeText = ts => ts ? new Date(ts * 1000).toLocaleTimeString() : "";
  const defaultOpt = it => (it.launch || []).find(o => o.default) || (it.launch || [])[0] || null;
  function optLabel(o, here) {
    if (o.target === "here" && !o.moment && !o.debug) return `Play on this PC${here ? ` (${here})` : ""}`;
    return o.label || o.id;
  }
  // a launch option -> the game menu's launch request: {mod, node, debug, slot, option, build}; "here" = this PC's worker
  function launchArgs(it, o, here) {
    if (!it || !o) return null;
    const node = o.target === "here" ? (here || "auto") : o.node;
    return { gid: it.game_id, x: { mod: it.mod, node, debug: !!o.debug, slot: o.moment && o.state_slot != null ? o.state_slot : "",
      option: o, build: { name: it.mod, mod_title: it.mod_title, card_id: it.card_id, state_slot: it.state_slot } } };
  }
  const SRC = { capture: "a frame of the build running", fitting: "the fitting preview", preview: "the build's preview",
                donor: "the donor's collection preview", boxart: "the game's box art" };

  function thumbHTML(it, url) {
    if (!it.thumbnail) return "";
    return `<img class="bn-thumb" alt="" loading="lazy" src="${ESC(url(it.thumbnail))}" title="${ESC(SRC[it.thumbnail_source] || "")}"
      onerror="this.style.visibility='hidden'">`;
  }
  // one build / error / collect of an entry: its buttons (data-bn) carry the entry id and the item index
  function itemButtons(n, it, i, st, here) {
    const at = `data-id="${ESC(n.id)}" data-i="${i}"`, key = `${n.id}:${i}`, msg = (st.msg || {})[key];
    let b = "";
    if (it.kind === "build") {
      const d = defaultOpt(it), more = (it.launch || []).filter(o => o !== d), open = st.open === key;
      b += d ? `<button class="act pri bn-play" type="button" data-bn="play" ${at} title="${ESC(optLabel(d, here))}">▶ Play</button>` : "";
      b += more.length ? `<button class="act bn-more" type="button" data-bn="opts" ${at} aria-haspopup="menu" aria-expanded="${open}" title="Other ways to launch it">▾</button>` : "";
      b += it.mod ? `<button class="act" type="button" data-bn="mods" ${at}>Open in Mods</button>` : "";
      if (open) b += `<div class="bn-opts" role="menu">` + more.map(o => `<button class="act" type="button" role="menuitem" data-bn="launch" ${at}
        data-opt="${ESC(o.id)}">▶ ${ESC(optLabel(o, here))}</button>`).join("") + `</div>`;
    } else if (it.kind === "error") {
      b += it.request_id ? `<button class="act" type="button" data-bn="request" ${at}>Open request</button>` : "";
      b += it.tool === "rom_export" ? `<button class="act" type="button" data-bn="export" ${at}>Review export</button>` : it.retry ? `<button class="act" type="button" data-bn="retry" ${at} title="Build it again on the Spark from its recipe (never launches)">⟳ Retry build</button>` : "";
    } else if (it.kind === "collect" && it.game_id) {
      b += `<button class="act" type="button" data-bn="models" ${at}>Open models</button>`;
    }
    return (b ? `<div class="bn-btns">${b}</div>` : "") + (msg ? `<div class="bn-msg mut">${ESC(msg)}</div>` : "");
  }
  function itemLine(it) {
    const name = it.mod_title || it.mod || (it.kind === "collect" ? it.game_title || it.game_id : `${it.tool || "build"} ${it.op || ""}`.trim());
    const text = it.kind === "error" ? it.error || it.summary : it.summary;
    return `<b class="bn-name">${it.kind === "error" ? "✗ " : ""}${ESC(name)}</b>${it.game_title && it.kind !== "collect" ? `<span class="mut bn-game">${ESC(it.game_title)}</span>` : ""}
      ${text ? `<span class="bn-sum${it.kind === "error" ? " bn-bad" : ""}">${ESC(text)}</span>` : ""}`;
  }
  // the whole entry: one item -> thumbnail + title + text + buttons; many -> the headline, then one row per item
  function noteHTML(n, opts = {}) {
    const url = opts.url || (u => u), st = opts.state || {}, here = opts.here || "";
    const cls = `tnote${n.read ? "" : " unread"}`;
    if (!isAuto(n)) return `<div class="${cls}" data-id="${ESC(n.id)}" data-sid="${ESC(n.session_id || "")}">
      <b>${ESC(n.title)}</b><span>${ESC(n.text || "")}</span><time>${ESC(timeText(n.ts))}</time></div>`;
    const items = itemsOf(n), one = items.length === 1;
    const head = `<div class="bn-head"><b>${ESC(n.title)}</b><time>${ESC(timeText(n.ts))}</time></div>`;
    if (one) {
      const it = items[0];
      return `<div class="${cls} bnote bn-${ESC(it.kind)}" data-id="${ESC(n.id)}" data-sid="" data-auto="build">
        <div class="bn-row">${thumbHTML(it, url)}<div class="bn-main">${head}
          ${it.kind === "error" ? `<span class="bn-sum bn-bad">${ESC(it.error || n.text || "")}</span>` : `<span class="bn-sum">${ESC(n.text || "")}</span>`}
          ${itemButtons(n, it, 0, st, here)}</div></div></div>`;
    }
    return `<div class="${cls} bnote bn-group bn-${ESC(n.kind)}" data-id="${ESC(n.id)}" data-sid="" data-auto="build">${head}
      <span class="bn-sum mut">${ESC(n.text || "")}</span>
      ${items.map((it, i) => `<div class="bn-row bn-item">${thumbHTML(it, url)}<div class="bn-main">${itemLine(it)}${itemButtons(n, it, i, st, here)}</div></div>`).join("")}</div>`;
  }
  function trayHTML(notes, opts = {}) {
    const list = (notes || []).slice(0, opts.max || 20);
    if (!list.length) return '<p class="mut" style="padding:10px">No notifications yet.</p>';
    const n = unread(notes);
    return (n ? `<div class="bn-top"><span class="mut">${n} unread</span><button class="act" type="button" data-bn="readall">Mark all read</button></div>` : "")
      + list.map(x => noteHTML(x, opts)).join("");
  }
  // entries to announce: build entries not seen yet (or grown since) and unread; seen: Set of "id:count" (null = first
  // read of the page: remember everything, announce nothing)
  function fresh(notes, seen) {
    const out = [];
    for (const n of notes || []) {
      if (!isAuto(n)) continue;
      const k = `${n.id}:${n.count || itemsOf(n).length}`;
      if (seen && !seen.has(k) && !n.read) out.push(n);
      if (seen) seen.add(k);
    }
    return out;
  }
  function seenOf(notes) { const s = new Set(); fresh(notes, s); return s; }
  function toastHTML(n, opts = {}) {
    const url = opts.url || (u => u), it = itemsOf(n)[0] || {}, d = it.kind === "build" ? defaultOpt(it) : null;
    return `<div class="bn-toast${n.kind === "error" ? " bn-bad-card" : ""}" data-id="${ESC(n.id)}" role="status">${thumbHTML(it, url)}<div class="bn-main">
      <b>${ESC(n.title)}</b><span class="bn-sum${n.kind === "error" ? " bn-bad" : ""}">${ESC(n.text || "")}</span>
      <div class="bn-btns">${d && itemsOf(n).length === 1 ? `<button class="act pri" type="button" data-bn="play" data-id="${ESC(n.id)}" data-i="0">▶ Play</button>` : ""}
      <button class="act" type="button" data-bn="show" data-id="${ESC(n.id)}">Show</button>
      <button class="act" type="button" data-bn="dismiss" data-id="${ESC(n.id)}" title="Dismiss">✕</button></div></div></div>`;
  }
  // what the desktop shell / the browser shows as an OS notification
  function osNote(n) {
    const it = itemsOf(n)[0] || {};
    return { ev: "buildnote", id: n.id, title: String(n.title || "gBox"), body: String(n.text || "").slice(0, 240),
             kind: n.kind || "", thumbnail: it.thumbnail || "" };
  }

  // clicks inside the tray / toast: io = { api(path, body?) -> data, notes() -> the entries shown, state: {open, msg},
  //   here (this PC's worker), launch(gid, x) (the game menu's launch: play() with the mod), openMods(gid, mod),
  //   openRequest({id}), openModels(gid, title), repaint(), close(), showTray(), dismiss(id) } -> handled (bool or promise)
  function click(target, io) {
    const b = target && target.closest && target.closest("[data-bn]");
    if (!b) return false;
    const act = b.dataset.bn, id = b.dataset.id, i = +(b.dataset.i || 0), st = io.state || (io.state = {});
    if (act === "readall") { Promise.resolve(io.api("/api/notify/read_all", {})).catch(() => {}).then(() => io.repaint && io.repaint(true)); return true; }
    const n = (io.notes() || []).find(x => x.id === id);
    if (act === "dismiss") { io.dismiss && io.dismiss(id); return true; }
    if (act === "show") { io.dismiss && io.dismiss(id); io.showTray && io.showTray(); return true; }
    if (!n) return true;
    const it = itemsOf(n)[i] || {}, key = `${id}:${i}`;
    const read = () => { if (!n.read) { n.read = true; Promise.resolve(io.api(`/api/notify/${encodeURIComponent(id)}/read`, {})).catch(() => {}); } };
    const say = t => { (st.msg || (st.msg = {}))[key] = t; io.repaint && io.repaint(); };
    if (act === "opts") { st.open = st.open === key ? null : key; io.repaint && io.repaint(); return true; }
    if (act === "play" || act === "launch") {
      const o = act === "play" ? defaultOpt(it) : (it.launch || []).find(x => x.id === b.dataset.opt);
      const a = launchArgs(it, o, io.here);
      if (!a) return true;
      read(); st.open = null; io.dismiss && io.dismiss(id); io.close && io.close();
      return Promise.resolve(io.launch(a.gid, a.x)).catch(err => say("✗ " + String(err && err.message || err).slice(0, 160)));
    }
    if (act === "mods") { read(); io.close && io.close(); io.openMods && io.openMods(it.game_id, it.mod); return true; }
    if (act === "request") { read(); io.close && io.close(); io.openRequest && io.openRequest({ id: it.request_id }); return true; }
    if (act === "models") { read(); io.close && io.close(); io.openModels && io.openModels(it.game_id, it.game_title || ""); return true; }
    if (act === "export") {
      read(); io.close && io.close();
      return Promise.resolve(io.repairExport ? io.repairExport(it) : io.openMods && io.openMods(it.game_id, ""))
        .catch(err => say(String(err && err.message || err)));
    }
    if (act === "retry") {
      if (!it.retry) return true;
      read(); say("queueing the rebuild on the Spark…");
      const r = it.retry, body = { tool: r.tool, input: r.input, ...(r.require_os ? { require_os: r.require_os } : {}) };
      return Promise.resolve(io.api("/api/jobs", body)).then(j => say(j && j.state === "rejected" ? `✗ ${j.error || "rejected"}`
        : `✓ rebuild queued (job ${j && j.id}): a notification follows when it finishes`), err => say("✗ " + String(err && err.message || err).slice(0, 160)));
    }
    return false;
  }

  const CSS = `.bnote{cursor:default}.bn-row{display:flex;gap:8px;align-items:flex-start}.bn-main{display:grid;gap:2px;min-width:0;flex:1}
    .bn-thumb{width:72px;height:54px;object-fit:cover;border-radius:5px;background:#111;flex:none}
    .bn-head{display:flex;gap:6px;justify-content:space-between;align-items:baseline}.bn-head time{flex:none}
    .bn-sum{color:var(--mut);overflow-wrap:anywhere}.bn-bad{color:var(--bad,#ff6b6b)}.bn-game{font-size:11px}
    .bn-btns{display:flex;gap:4px;flex-wrap:wrap;margin-top:3px}.bn-btns .act{font-size:11.5px;padding:2px 7px}
    .bn-opts{display:flex;flex-direction:column;gap:2px;width:100%;margin-top:2px}.bn-opts .act{text-align:left}
    .bn-item{padding-top:6px;margin-top:4px;border-top:1px dashed var(--line)}.bn-msg{font-size:11px}
    .bn-top{display:flex;justify-content:space-between;align-items:center;padding:6px 10px;border-bottom:1px solid var(--line);font-size:12px}
    .bn-toast{display:flex;gap:8px;padding:10px;background:var(--bg);border:1px solid var(--acc);border-radius:10px;
      box-shadow:0 6px 18px #0009;font-size:12.5px;line-height:1.4;min-width:0}
    .bn-toast.bn-bad-card{border-color:var(--bad,#ff6b6b)}.bn-toast b{overflow-wrap:anywhere;white-space:normal}`;

  const api = { isAuto, itemsOf, unread, defaultOpt, optLabel, launchArgs, noteHTML, trayHTML, fresh, seenOf, toastHTML, osNote, click,
                CSS, TOAST_MS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxBuildNotes = api;
})(typeof window !== "undefined" ? window : globalThis);
