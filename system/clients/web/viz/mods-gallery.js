// Mods gallery: every modded build the Spark made (GET /api/mods/built: each writer's mod folder in the cache, joined
// with its mod card), newest first, filterable by game and writer, searchable. Each card shows the build's preview
// pictures (in-game shots, the writer's previews, the donors' collection previews) as a carousel - a click opens the
// texture pop-up to zoom - what changed (donor -> slot, the per-slot report of a cast swap), verified / unverified,
// and Play (this PC or a chosen PC, the mod cards' @launch path), Play from saved moment, Open request and Screenshot
// after launch (get_frame of the running game -> the mod card's in-game shots).
// #1656: a card's name renames in place (click it or ✎; Enter saves, Esc cancels, empty restores the writer's title:
// PATCH /api/builds/{game}/{name}, a display name only, the folder never changes) and ☆/★ stars it (PUT .../favorite:
// favorites list first, a ★ Favorites filter, the game's Special builds show them on top). ⋯ or a right-click on the card
// opens its options (Rename…, favorite, restore the original name, Play).
// The server answers from its index of the build folders: while it is still indexing (`indexing`) or walking folder
// sizes (`sizing`: folders left, size null on those cards) the view says so and polls faster through the shared cached
// read, so sizes appear as they arrive; Refresh asks for an incremental pass (POST /api/mods/built/refresh).
// Shared by the desktop shell's Mods view and the web client's Mods tab; plain functions + a controller that renders
// HTML strings into a host element, so node tests drive it without a browser (tests/test_mods_gallery.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const PAGE = 24;
  const TICK = 5000;                                         // poll tick (ms); a fetch happens only when the read is stale

  // favorites (★) first, then newest; fav: only the favorites
  function filterMods(items, { game = "", writer = "", q = "", fav = false } = {}) {
    const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    const hay = m => [m.name, m.game_id, m.title, m.mod_title, m.original_title, m.writer, ...(m.changes || []).map(r => `${r.donor} ${r.slot}`),
      ...(m.tickets || []).map(t => `#${t.number} ${t.title || ""}`)].join(" ").toLowerCase();
    return (items || []).filter(m => (!game || m.game_id === game) && (!writer || m.writer === writer) && (!fav || m.favorite) && words.every(w => hay(m).includes(w)))
      .sort((a, b) => (+!!b.favorite - +!!a.favorite) || (b.built || 0) - (a.built || 0));
  }

  function facets(items) {
    const games = new Map(), writers = new Map();
    let favorites = 0;
    for (const m of items || []) {
      const g = games.get(m.game_id) || { game_id: m.game_id, title: m.title || m.game_id, count: 0 };
      g.count++; games.set(m.game_id, g);
      writers.set(m.writer, (writers.get(m.writer) || 0) + 1);
      if (m.favorite) favorites++;
    }
    return { games: [...games.values()].sort((a, b) => a.title.localeCompare(b.title)),
             writers: [...writers.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([writer, count]) => ({ writer, count })), favorites };
  }
  // the build's own endpoints (gbox/builds.py): PATCH {display_name} renames, PUT {favorite} stars
  const buildPath = m => `/api/builds/${encodeURIComponent(m.game_id)}/${encodeURIComponent(m.name)}`;

  // in-game shots first (what the build looks like running: card shots, then frames captured from sessions of the build),
  // then the writer's previews, then the donors
  function imagesOf(m, url = u => u) {
    return [...(m.shots || []).map(s => ({ src: url(s.url), name: `${m.mod_title}: in-game shot`, kind: "shot" })),
            ...(m.frames || []).map(f => ({ src: url(f.url), name: `${m.mod_title}: ${f.source || "frame"} (session ${String(f.session_id || "").slice(0, 8)})`, kind: "shot" })),
            ...(m.images || []).map(i => ({ src: url(i.url), name: `${m.mod_title}: ${i.name}`, kind: "build" })),
            ...(m.donor_previews || []).map(d => ({ src: url(d.url), name: `Donor ${d.slug} (collection preview)`, kind: "donor" }))];
  }

  const fmtSize = n => !n ? "0 B" : n >= 2 ** 30 ? (n / 2 ** 30).toFixed(2) + " GB" : n >= 2 ** 20 ? (n / 2 ** 20).toFixed(1) + " MB"
    : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B";
  // a folder the server has not walked yet (size null) says so instead of "0 B"
  const sizeHTML = m => m.size == null ? '<span class="mg-sizing">size: indexing…</span>'
    : ESC(fmtSize(m.own_size || m.size)) + (m.own_size && m.size > m.own_size ? ` (${ESC(fmtSize(m.size))} with shared files)` : "");
  // the toolbar summary: shown / all builds, the cache folder, and what the index is still doing
  function summaryText(n, d) {
    if (!d) return "";
    const busy = d.indexing ? "indexing…" : d.sizing ? `indexing… (${d.sizing} folder size${d.sizing === 1 ? "" : "s"} to go)` : "";
    return `${n} of ${d.items.length} builds${d.cache_dir ? " · " + d.cache_dir : ""}${busy ? " · " + busy : ""}`;
  }
  function fmtAge(ts, now = Date.now() / 1000) {
    if (!ts) return "unknown time";
    const s = Math.max(0, now - ts);
    return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
  }
  function launchText(l, now) {
    if (!l) return "never launched";
    if (l.state === "failed" || l.state === "cancelled") return `last launch ${l.state}${l.error ? ": " + l.error : ""}`;
    return `last launched ${fmtAge(l.ts, now)} (${l.state || "?"}${l.exit ? ", " + l.exit : ""})`;
  }

  function changesHTML(m) {
    const rows = m.changes || [];
    if (!rows.length) return '<div class="mg-ch mut">No donor / slot record in this build\'s marker.</div>';
    return `<ul class="mg-ch">${rows.map(r => `<li${r.reason ? ` title="${ESC(r.reason)}"` : ""}><b>${ESC(r.donor || "?")}</b> → ${ESC(r.slot || "?")}`
      + (r.status ? ` <span class="mg-st mg-${ESC(r.status)}">${ESC(r.status)}</span>` : "")
      + (r.reason ? ` <span class="mut">${ESC(r.reason)}</span>` : "") + "</li>").join("")}</ul>`;
  }

  // the card's name: click it (or ✎) to rename inline; Enter saves, Esc cancels, empty restores the writer's title.
  // data-nomic: the web shell wraps text fields with a dictation button, which moves (and so blurs) the field
  function titleHTML(m, renaming) {
    if (renaming) return `<input class="mg-rename" data-mg-rename="${ESC(m.key)}" value="${ESC(m.mod_title || m.name)}" maxlength="120" aria-label="Build name"
      placeholder="${ESC(m.original_title || m.name)}" title="Enter saves · Esc cancels · empty restores “${ESC(m.original_title || m.name)}”" data-nomic>`;
    return `<b class="mg-title" data-mg="rename" role="button" tabindex="0" title="Click to rename · folder ${ESC(m.name)}${m.display_name && m.original_title ? ` · was “${ESC(m.original_title)}”` : ""}">${ESC(m.mod_title || m.name)}</b>`
      + `<button class="mg-ico" type="button" data-mg="rename" title="Rename this build (the folder keeps its name)" aria-label="Rename">✎</button>`;
  }
  const starHTML = m => `<button class="mg-ico mg-star${m.favorite ? " on" : ""}" type="button" data-mg="fav" aria-pressed="${!!m.favorite}" title="${m.favorite ? "Remove from favorites" : "Add to favorites: listed first, at the top of the game's Special builds, never evicted"}" aria-label="Favorite">${m.favorite ? "★" : "☆"}</button>`;
  // the card's options (⋯ or right-click): Rename…, favorite, Play, restore the original name
  function menuHTML(m) {
    const item = (act, text, title = "") => `<button class="act" type="button" role="menuitem" data-mg="${act}"${title ? ` title="${ESC(title)}"` : ""}>${text}</button>`;
    return `<div class="mg-menu" role="menu" data-mg-menu="${ESC(m.key)}">${item("rename", "✎ Rename…", "Give this build your own name (the folder keeps its name)")}`
      + item("fav", m.favorite ? "☆ Remove from favorites" : "★ Add to favorites")
      + (m.display_name ? item("unname", `↺ Restore “${ESC(m.original_title || m.name)}”`) : "")
      + item("play", "▶ Play") + "</div>";
  }

  function cardHTML(m, { url = u => u, idx = 0, now, renaming = false, menu = false, note = "" } = {}) {
    const imgs = imagesOf(m, url), i = imgs.length ? ((idx % imgs.length) + imgs.length) % imgs.length : 0, cur = imgs[i];
    const tickets = m.tickets || [];
    return `<article class="mg-card${m.favorite ? " mg-fav" : ""}" data-key="${ESC(m.key)}">${menu ? menuHTML(m) : ""}
      <div class="mg-pic">${cur ? `<img class="mg-img" loading="lazy" decoding="async" alt="${ESC(cur.name)}" data-i="${i}" src="${ESC(cur.src)}">
        ${imgs.length > 1 ? `<button class="mg-nav" data-mg="prev" type="button" title="Previous picture">‹</button><button class="mg-nav" data-mg="next" type="button" title="Next picture">›</button>` : ""}
        <span class="mg-count">${cur.kind === "shot" ? "in-game · " : cur.kind === "donor" ? "donor · " : ""}${i + 1} / ${imgs.length}</span>`
        : `<div class="mg-none">No pictures yet: Screenshot after launch adds one</div>`}</div>
      <div class="mg-body">
        <div class="mg-h"><span class="mg-tt">${starHTML(m)}${titleHTML(m, renaming)}</span>
          <span class="mg-hr"><span class="mg-badge ${m.verified ? "mg-ok" : "mg-unv"}">${m.verified ? "verified" : "unverified"}</span><button class="mg-ico" type="button" data-mg="menu" aria-haspopup="menu" aria-expanded="${!!menu}" title="Options (or right-click the card)" aria-label="Options">⋯</button></span></div>
        ${m.display_name && m.original_title && m.original_title !== m.display_name ? `<div class="mg-was mut">was “${ESC(m.original_title)}”</div>` : ""}
        <div class="mg-sub"><span class="mg-chip" data-mg-game="${ESC(m.game_id)}">${ESC(m.title || m.game_id)}</span>
          <span class="mg-chip" data-mg-writer="${ESC(m.writer)}">${ESC(m.writer)}</span>${m.cast ? '<span class="mg-chip">cast swap</span>' : ""}</div>
        ${changesHTML(m)}
        <div class="mg-meta mut">${ESC(m.name)} · built ${ESC(fmtAge(m.built, now))} · ${sizeHTML(m)}
          · <span class="mg-launch${m.last_launch && /failed|cancelled/.test(m.last_launch.state) ? " mg-bad" : ""}">${ESC(launchText(m.last_launch, now))}</span></div>
        ${tickets.length ? `<div class="mg-tk">${tickets.map(t => `<button class="act mg-req" type="button" data-mg="request" data-n="${t.number}" title="${ESC(t.title || "Open request #" + t.number)}">Open request #${t.number}${t.status ? " · " + ESC(t.status.replace("_", " ")) : ""}</button>`).join("")}</div>` : ""}
        <div class="mg-btns"><button class="act pri" type="button" data-mg="play">Play</button>
          ${m.state_slot != null && m.card_id ? `<button class="act" type="button" data-mg="moment" title="Launch and load the saved moment (slot ${ESC(m.state_slot)})">Play from saved moment</button>` : ""}
          <button class="act" type="button" data-mg="shot" title="Once the mod is running, capture a frame and add it to this mod's pictures"${m.card_id ? "" : " disabled"}>Screenshot after launch</button>
          <span class="mg-msg mut">${ESC(note)}</span></div></div></article>`;
  }

  // a request's thread (GET /api/requests/{id}) shown under the card when the client has no inbox view of its own
  function requestHTML(x) {
    const msgs = (x.messages || []).slice(-6);
    return `<div class="mg-rq"><div class="mg-h"><b>#${ESC(x.number)} ${ESC(x.title)}</b><button class="act" type="button" data-mg="reqclose" title="Close">✕</button></div>
      <div class="mut">${ESC(String(x.status || "").replace("_", " "))}${x.created ? " · " + ESC(new Date(x.created * 1000).toLocaleString()) : ""}</div>
      ${msgs.map(mm => `<div class="mg-rqm"><b>${mm.author === "agent" ? "Agent" : "You"}</b> ${ESC(String(mm.text || "").slice(0, 600))}</div>`).join("")}</div>`;
  }

  function toolbarHTML(st, f, nodes = []) {
    const opt = (v, l, sel) => `<option value="${ESC(v)}"${v === sel ? " selected" : ""}>${ESC(l)}</option>`;
    return `<div class="mg-bar"><h2 style="margin:0">Mods</h2>
      <input type="search" data-mg-f="q" placeholder="Search mod, game, donor, slot, #request" value="${ESC(st.q)}">
      <select data-mg-f="game">${opt("", "All games", st.game)}${f.games.map(g => opt(g.game_id, `${g.title} (${g.count})`, st.game)).join("")}</select>
      <select data-mg-f="writer">${opt("", "All writers", st.writer)}${f.writers.map(w => opt(w.writer, `${w.writer} (${w.count})`, st.writer)).join("")}</select>
      <label class="mg-favf" title="Only the builds you starred (★)"><input type="checkbox" data-mg-f="fav"${st.fav ? " checked" : ""}> ★ Favorites${f.favorites ? ` (${f.favorites})` : ""}</label>
      <label class="mut">Play on <select data-mg-f="node">${opt("", "This PC", st.node)}${nodes.map(n => opt(n.name, `${n.name} (${n.os})`, st.node)).join("")}</select></label>
      <button class="act" type="button" data-mg="refresh" title="Rescan the build folders">Refresh</button><span class="mut" data-mg-sum></span></div>
      <div class="mg-grid" data-mg-grid></div><div data-mg-more></div>`;
  }

  const CSS = `.mg-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px}.mg-bar input[type=search]{flex:1;min-width:180px}
    .mg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
    .mg-card{border:1px solid var(--line,#333);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;background:var(--panel,transparent)}
    .mg-pic{position:relative;height:190px;background:#111;display:flex;align-items:center;justify-content:center}
    .mg-pic img{max-width:100%;max-height:100%;object-fit:contain;cursor:zoom-in;image-rendering:auto}
    .mg-nav{position:absolute;top:50%;transform:translateY(-50%);background:#000a;color:#fff;border:0;border-radius:4px;font-size:20px;padding:2px 8px;cursor:pointer}
    .mg-nav[data-mg=prev]{left:6px}.mg-nav[data-mg=next]{right:6px}
    .mg-count{position:absolute;right:6px;bottom:6px;background:#000a;color:#ddd;font-size:11px;padding:1px 6px;border-radius:3px}
    .mg-none{color:#888;font-size:12px;padding:20px;text-align:center}.mg-body{padding:8px 10px;display:flex;flex-direction:column;gap:5px;font-size:13px}
    .mg-h{display:flex;gap:6px;align-items:flex-start;justify-content:space-between}.mg-h b{overflow-wrap:anywhere}
    .mg-badge{font-size:11px;padding:1px 6px;border-radius:9px;white-space:nowrap}.mg-ok{background:#1f6f3f;color:#fff}.mg-unv{background:#6f5a1f;color:#fff}
    .mg-sub{display:flex;gap:4px;flex-wrap:wrap}.mg-chip{font-size:11px;border:1px solid var(--line,#444);border-radius:9px;padding:0 6px;cursor:pointer}
    .mg-ch{margin:0;padding-left:16px;max-height:110px;overflow:auto;font-size:12px}.mg-st{font-size:10.5px;padding:0 5px;border-radius:7px;background:#444;color:#fff}
    .mg-st.mg-built{background:#1f6f3f}.mg-st.mg-failed{background:#7a2b2b}.mg-st.mg-partial,.mg-st.mg-skipped{background:#6f5a1f}
    .mg-rq{border-top:1px solid var(--line,#333);padding-top:5px;font-size:12px;max-height:220px;overflow:auto}.mg-rqm{margin:4px 0;white-space:pre-wrap}
    .mg-meta{font-size:11.5px}.mg-sizing{font-style:italic}.mg-bad{color:#e66}.mg-btns,.mg-tk{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.mg-msg{font-size:11.5px}
    .mg-card{position:relative}.mg-card.mg-fav{border-color:#c9a43a}.mg-tt{display:flex;gap:2px;align-items:flex-start;min-width:0;flex:1}.mg-hr{display:flex;gap:4px;align-items:center}
    .mg-title{cursor:text;border-radius:3px;padding:0 2px}.mg-title:hover{background:#ffffff14}.mg-rename{flex:1;min-width:0;font:inherit;font-weight:600}
    .mg-ico{background:none;border:0;color:inherit;cursor:pointer;padding:0 3px;font-size:13px;opacity:.65;line-height:1.4}.mg-ico:hover{opacity:1}
    .mg-star{font-size:15px;color:#c9a43a;opacity:.8}.mg-star.on{opacity:1}.mg-was{font-size:11px;margin-top:-3px}
    .mg-favf{display:flex;gap:4px;align-items:center;font-size:12.5px;white-space:nowrap}
    .mg-menu{position:absolute;z-index:5;top:8px;right:8px;display:flex;flex-direction:column;gap:3px;padding:6px;border:1px solid var(--line,#444);border-radius:8px;background:var(--bg,#16161a);box-shadow:0 8px 24px #000a;min-width:190px}
    .mg-menu .act{text-align:left}`;

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // the controller: one host element, env = { api(path, body?) -> data (throws), url(path) -> loadable URL,
  //   openImages(list, i, [x, y]), poll (GBoxLivePoll), here (this PC's worker name), visible() -> bool,
  //   play?(mod, {node, moment}), openRequest?(ticket), toast?(text), wait?(ms) }
  function mount(host, env) {
    const st = { q: env.q || "", game: env.game || "", writer: "", node: "", fav: !!env.fav, page: 1, idx: new Map(), data: null, nodes: [], sig: "",
                 renaming: null, menu: null, notes: new Map() };
    const poll = env.poll || root.GBoxLivePoll;
    const read = poll ? poll.cachedRead(() => env.api("/api/mods/built").then(data => ({ ok: true, data }), e => ({ ok: false, error: e.message })), { ttl: 15000 })
      : { get: () => env.api("/api/mods/built").then(data => ({ ok: true, data }), e => ({ ok: false, error: e.message })), invalidate() {} };
    const wait = env.wait || sleep, toast = env.toast || (() => {});
    const url = env.url || (u => u);
    let timer = null, built = false;

    function shell() {
      const f = facets(st.data?.items || []);
      host.innerHTML = `<style>${CSS}</style>` + toolbarHTML(st, f, st.nodes);
      built = true;
    }
    function shown() { return filterMods(st.data?.items || [], st); }
    function draw() {
      if (!built) shell();
      const list = shown(), page = list.slice(0, st.page * PAGE), more = list.length - page.length;
      const grid = host.querySelector("[data-mg-grid]"), sum = host.querySelector("[data-mg-sum]"), moreEl = host.querySelector("[data-mg-more]");
      if (grid) grid.innerHTML = page.map(m => cardHTML(m, { url, idx: st.idx.get(m.key) || 0, renaming: st.renaming === m.key, menu: st.menu === m.key,
                                                                note: st.notes.get(m.key) || "" })).join("")
        || `<p class="mut">${st.data ? (st.data.items.length ? (st.fav && !st.data.items.some(m => m.favorite) ? "No favorites yet: ☆ on a card stars it." : "No built mod matches these filters.") : st.data.indexing ? "Indexing the built mods…" : "No built mods in the cache yet.") : "Loading built mods…"}</p>`;
      if (st.renaming) { const inp = grid?.querySelector?.("[data-mg-rename]"); try { inp?.focus?.(); inp?.select?.(); } catch {} }
      if (sum) sum.textContent = summaryText(list.length, st.data);
      if (moreEl) moreEl.innerHTML = more > 0 ? `<button class="act" type="button" data-mg="more" style="width:100%;margin:10px 0">Show ${Math.min(more, PAGE)} more (${more} not shown)</button>` : "";
    }
    async function load(maxAge) {
      const r = await read.get(maxAge);
      if (!r || !r.ok) { if (!st.data) { if (!built) shell(); const g = host.querySelector("[data-mg-grid]"); if (g) g.innerHTML = `<p class="bad">${ESC(r?.error || "Could not read the built mods")}</p>`; } return st; }
      const sig = JSON.stringify([r.data.items, !!r.data.indexing, r.data.sizing || 0]);
      if (sig === st.sig) return st;                         // unchanged: keep the carousels and scroll where they are
      const refacet = !st.data || JSON.stringify(facets(st.data.items)) !== JSON.stringify(facets(r.data.items || []));
      st.data = { items: r.data.items || [], cache_dir: r.data.cache_dir, indexing: !!r.data.indexing, sizing: r.data.sizing || 0 };
      st.sig = sig;
      if (st.renaming) return st;                           // never redraw under the operator's typing (the rename field)
      const typing = host.contains?.(root.document?.activeElement) && root.document.activeElement.matches?.("input, select");
      if (refacet && !typing) built = false;                 // new game / writer options; never under the operator's cursor
      draw();
      return st;
    }
    async function nodes() {
      try { const ws = await env.api("/api/workers"); st.nodes = (ws || []).filter(w => w.online).map(w => ({ name: w.name, os: w.os })); built = false; } catch {}
    }
    const find = key => (st.data?.items || []).find(m => m.key === key);
    const nodeOf = () => st.node || env.here || "auto";
    const msg = (card, text) => { const el = card?.querySelector?.(".mg-msg"); if (el) el.textContent = text; };

    async function jobDone(j, what, max = 900) {
      for (let i = 0; i < max && j && ["queued", "running"].includes(j.state); i++) { await wait(1000); j = await env.api("/api/jobs/" + j.id); }
      if (!j || j.state !== "succeeded") throw new Error(`${what}: ${j?.error || j?.state || "no answer"}`);
      return j;
    }
    // default Play: the mod cards' launch path (@launch: swaps into the running game on that PC, else starts it there)
    async function play(m, { node, moment }) {
      if (env.play) return env.play(m, { node, moment });
      const j = await jobDone(await env.api("/api/jobs", { tool: "@launch", input: { game_id: m.game_id, mod: m.name, node } }), "launch");
      const sid = j.output?.session_id;
      if (moment && m.state_slot != null && sid) {
        await wait(8000);                                    // let the core boot before loading a state
        await jobDone(await env.api("/api/jobs", { tool: "session_op", input: { session_id: sid, op: "load_state", args: { slot: m.state_slot } },
          require_worker: sid.split("-")[0] }), "load the saved moment");
      }
      return sid;
    }
    async function runningSession(m) {
      const ss = await env.api("/api/sessions?include_ended=false").catch(() => []);
      return (ss || []).filter(s => s.state === "running" && s.game_id === m.game_id && (s.collection_mod || s.mod) === m.name)
        .sort((a, b) => (b.started || 0) - (a.started || 0))[0] || null;
    }
    async function screenshot(m, card) {
      if (!m.card_id) throw new Error("this build has no mod card yet: refresh");
      let s = await runningSession(m);
      if (!s) {
        msg(card, "Launching the mod…");
        await play(m, { node: nodeOf(), moment: false });
        for (let i = 0; i < 90 && !(s = await runningSession(m)); i++) await wait(2000);
        if (!s) throw new Error("the mod did not start a game session");
        msg(card, "Running: waiting for the picture to settle…");
        await wait(12000);
      }
      msg(card, "Capturing a frame…");
      await env.api(`/api/mods/${encodeURIComponent(m.card_id)}/thumb?append=true&session_id=${encodeURIComponent(s.session_id)}`, {});
      read.invalidate(); await env.api("/api/mods/built?fresh=true").catch(() => null);
      st.sig = ""; await load(0);
      return s.session_id;
    }
    async function openRequest(n, m, card) {
      const t = (m.tickets || []).find(x => String(x.number) === String(n)) || { number: +n };
      if (env.openRequest) return env.openRequest(t, m);
      if (!t.id) { msg(card, `Request #${t.number} is not in the inbox`); return; }
      const x = await env.api(`/api/requests/${encodeURIComponent(t.id)}`);       // the thread, inline under the card
      let box = card?.querySelector?.(".mg-reqview");
      if (!box && card?.querySelector?.(".mg-body")) {
        card.querySelector(".mg-body").insertAdjacentHTML("beforeend", '<div class="mg-reqview"></div>');
        box = card.querySelector(".mg-reqview");
      }
      if (box) box.innerHTML = requestHTML(x);
      return x;
    }

    // ✎ rename (PATCH /api/builds/{game}/{name}: a display name, the folder never changes; "" restores the writer's
    // title) and ★ favorites (PUT .../favorite): the card changes at once, the next read brings the server's view
    let renameBusy = false;
    const note = (key, text) => { if (text) st.notes.set(key, text); else st.notes.delete(key); };
    const startRename = m => { st.menu = null; st.renaming = m.key; draw(); };
    async function rename(key, value) {
      const m = find(key); if (!m || renameBusy) return;
      st.renaming = null;
      const v = String(value ?? "").trim();
      if (v === (m.display_name || "") || (!m.display_name && v === (m.mod_title || m.name))) { draw(); return; }
      renameBusy = true;
      try {
        const r = await env.api(buildPath(m), { display_name: v }, "PATCH");
        m.display_name = r.display_name; m.mod_title = r.label;
        note(key, v ? `Renamed (the folder stays ${m.name})` : `Original name restored: ${r.label}`);
        read.invalidate(); st.sig = "";
        toast(v ? `Renamed: ${r.label}` : `${r.label}: original name restored`);
      } catch (err) { note(key, "⚠ rename failed: " + (err?.message || err)); }
      finally { renameBusy = false; }
      draw();
      return m;
    }
    async function favorite(m, on = !m.favorite) {
      st.menu = null;
      try {
        await env.api(buildPath(m) + "/favorite", { favorite: on }, "PUT");
        m.favorite = on; note(m.key, on ? "★ Favorite: listed first and kept" : "Removed from favorites");
        read.invalidate(); st.sig = ""; built = false;      // the toolbar's ★ Favorites count changes
      } catch (err) { note(m.key, "⚠ " + (err?.message || err)); }
      draw();
      return m;
    }

    async function onClick(e) {
      const t = e.target, card = t.closest?.(".mg-card"), m = card && find(card.dataset.key);
      const act = t.closest?.("[data-mg]")?.dataset.mg;
      if (t.closest?.("[data-mg-rename]")) return;          // clicks inside the rename field stay in it
      if (st.menu && act !== "menu" && !t.closest?.("[data-mg-menu]")) { st.menu = null; draw(); if (!act) return; }
      if (act === "more") { st.page++; draw(); return; }
      if (act === "refresh") { try { await env.api("/api/mods/built/refresh", {}); } catch {} read.invalidate(); st.sig = ""; await load(0); return; }
      const chipG = t.closest?.("[data-mg-game]"), chipW = t.closest?.("[data-mg-writer]");
      if (chipG || chipW) { if (chipG) st.game = chipG.dataset.mgGame; else st.writer = chipW.dataset.mgWriter; st.page = 1; built = false; draw(); return; }
      if (!m) return;
      if (act === "rename") { e.preventDefault?.(); startRename(m); return; }
      if (act === "fav") { e.preventDefault?.(); await favorite(m); return; }
      if (act === "menu") { st.menu = st.menu === m.key ? null : m.key; draw(); return; }
      if (act === "unname") { st.menu = null; await rename(m.key, ""); return; }
      if (act === "play" && t.closest?.("[data-mg-menu]")) {  // ▶ Play in the options: the card's own Play button
        st.menu = null; draw();
        const b = host.querySelector?.(`.mg-card[data-key="${String(m.key).replace(/"/g, '\\"')}"] .mg-btns [data-mg="play"]`);
        return b ? onClick({ target: b, preventDefault() {}, stopPropagation() {} }) : undefined;
      }
      const imgs = imagesOf(m, url);
      if (act === "prev" || act === "next") { st.idx.set(m.key, (st.idx.get(m.key) || 0) + (act === "next" ? 1 : -1)); draw(); return; }
      if (t.closest?.(".mg-img")) {
        e.preventDefault?.(); e.stopPropagation?.();
        const i = imgs.length ? (((st.idx.get(m.key) || 0) % imgs.length) + imgs.length) % imgs.length : 0;
        env.openImages?.(imgs.map(x => ({ src: x.src, name: x.name })), i, [e.clientX || 0, e.clientY || 0]);
        return;
      }
      const btn = t.closest?.("button");
      try {
        if (act === "play" || act === "moment") {
          if (btn) btn.disabled = true;
          msg(card, act === "moment" ? "Launching and loading the saved moment…" : `Launching on ${st.node || "this PC"}…`);
          await play(m, { node: nodeOf(), moment: act === "moment" });
          msg(card, "Launched"); read.invalidate();
        } else if (act === "shot") {
          if (btn) btn.disabled = true;
          await screenshot(m, card);
          toast(`${m.mod_title}: in-game picture added`);
        } else if (act === "request") {
          await openRequest(t.closest("[data-n]").dataset.n, m, card);
        } else if (act === "reqclose") {
          const box = card.querySelector?.(".mg-reqview"); if (box) box.remove?.();
        }
      } catch (err) {
        msg(host.querySelector?.(`.mg-card[data-key="${String(m.key).replace(/"/g, '\\"')}"]`) || card, "⚠ " + (err?.message || err));
        toast("⚠ " + (err?.message || err));
      } finally { if (btn) btn.disabled = act === "shot" && !m.card_id; }
    }
    function onInput(e) {
      const f = e.target?.dataset?.mgF; if (!f) return;
      st[f] = e.target.type === "checkbox" ? !!e.target.checked : e.target.value; if (f !== "node") { st.page = 1; draw(); }
    }
    // the rename field: Enter saves, Esc cancels; the title (a button) renames on Enter; Esc closes the options menu
    function onKey(e) {
      const inp = e.target?.closest?.("[data-mg-rename]");
      if (inp) {
        if (e.key === "Enter") { e.preventDefault?.(); rename(inp.dataset.mgRename, inp.value); }
        else if (e.key === "Escape") { e.preventDefault?.(); e.stopPropagation?.(); st.renaming = null; draw(); }
        return;
      }
      const ttl = e.target?.closest?.(".mg-title"), card = e.target?.closest?.(".mg-card");
      if (ttl && card && (e.key === "Enter" || e.key === "F2")) { e.preventDefault?.(); const m = find(card.dataset.key); if (m) startRename(m); return; }
      if (e.key === "Escape" && st.menu) { st.menu = null; draw(); }
    }
    function onFocusOut(e) {                                 // leaving the field keeps what was typed (as the Builds view does)
      const inp = e.target?.closest?.("[data-mg-rename]");
      if (inp && st.renaming === inp.dataset.mgRename) rename(inp.dataset.mgRename, inp.value);
    }
    // right-click a card: its options (Rename…, favorite, Play); runs before the app's "file a request" menu
    function onContext(e) {
      const card = e.target?.closest?.(".mg-card"); if (!card || e.target.closest?.("input, textarea")) return;
      e.preventDefault?.(); e.stopPropagation?.();
      st.menu = card.dataset.key; draw();
    }
    host.addEventListener("click", onClick);
    host.addEventListener("input", onInput);
    host.addEventListener("change", onInput);
    host.addEventListener("keydown", onKey);
    host.addEventListener("focusout", onFocusOut);
    host.addEventListener("contextmenu", onContext);
    async function start() {
      shell(); draw();
      await nodes(); await load(0);
      if (!built) draw();
      timer = setInterval(tick, TICK);
      return api;
    }
    // one cached read per tick at most: every few seconds while the index is still working, else every 30 s
    function busy() { return !!(st.data && (st.data.indexing || st.data.sizing)); }
    function tick() { if (!env.visible || env.visible()) return load(busy() ? TICK - 500 : 30000); }
    function stop() {
      clearInterval(timer);
      for (const [ev, fn] of [["click", onClick], ["input", onInput], ["change", onInput], ["keydown", onKey], ["focusout", onFocusOut], ["contextmenu", onContext]])
        host.removeEventListener?.(ev, fn);
    }
    // show one build / request: the game menu's "Open in Mods page" (search + game filter set, the toolbar redrawn)
    function focus({ q, game } = {}) { if (q != null) st.q = String(q); if (game != null) st.game = String(game); st.page = 1; built = false; draw(); }
    const api = { st, load, draw, stop, start, play, screenshot, onClick, onInput, onKey, onFocusOut, onContext, rename, favorite, tick, busy, focus, ready: null };
    api.ready = start();
    return api;
  }

  const api = { filterMods, facets, imagesOf, cardHTML, titleHTML, menuHTML, buildPath, toolbarHTML, changesHTML, requestHTML, fmtSize, fmtAge, launchText, summaryText, mount, PAGE, TICK };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxModsGallery = api;
})(typeof window !== "undefined" ? window : globalThis);
