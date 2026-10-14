// Mods gallery: every modded build the Spark made (GET /api/mods/built: each writer's mod folder in the cache, joined
// with its mod card), newest first, filterable by game and writer, searchable. Each card shows the build's preview
// pictures (in-game shots, the writer's previews, the donors' collection previews) as a carousel - a click opens the
// texture pop-up to zoom - what changed (donor -> slot, the per-slot report of a cast swap), verified / unverified,
// and Play (this PC or a chosen PC, the mod cards' @launch path), Play from saved moment, Open request and Screenshot
// after launch (get_frame of the running game -> the mod card's in-game shots; the rules for a game already running are
// clients/web/viz/build-shot.js: this exact build = capture now, another build = ask, nothing = launch then capture).
// #1656: a card's name renames in place (click it or ✎; Enter saves, Esc cancels, empty restores the writer's title:
// PATCH /api/builds/{game}/{name}, a display name only, the folder never changes) and ☆/★ stars it (PUT .../favorite:
// favorites list first, a ★ Favorites filter, the game's Special builds show them on top). ⋯ or a right-click on the card
// opens its options (Rename…, favorite, restore the original name, Play).
// #1639: the download icon in the picture's top-right corner (viz/build-local.js): on this PC (filled check) / not on this
// PC (arrow: a click downloads it into this PC's cache, never launching it) / downloading (a ring with the percent);
// right-click or ▾: Download to this PC, Export… (same format as the original by default), Open folder, Delete from this PC.
// The server answers from its index of the build folders: while it is still indexing (`indexing`) or walking folder
// sizes (`sizing`: folders left, size null on those cards) the view says so and polls faster through the shared cached
// read, so sizes appear as they arrive; Refresh asks for an incremental pass (POST /api/mods/built/refresh).
// Shared by the desktop shell's Mods view and the web client's Mods tab; plain functions + a controller that renders
// HTML strings into a host element, so node tests drive it without a browser (tests/test_mods_gallery.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const BS = root.GBoxBuildShot || (typeof require === "function" ? require("./build-shot.js") : null);
  const PAGE = 24;
  // What this changes / Delete / Report (viz/build-actions.js; loaded before this file, or required by node tests)
  const BA = () => root.GBoxBuildActions || (typeof module === "object" && module.exports ? require("./build-actions.js") : null);
  // On this PC: the download icon, its menu and the Export dialog (viz/build-local.js; loaded before this file, or required by node tests)
  const BL = () => root.GBoxBuildLocal || (typeof module === "object" && module.exports ? require("./build-local.js") : null);
  const TICK = 5000;                                         // poll tick (ms); a fetch happens only when the read is stale

  // kind: "" every build | "showcase" the Sonic showcase test builds (gbox/sonic_showcase.py) | "other" everything else;
  // favorites (★) first, then newest; fav: only the favorites
  function filterMods(items, { game = "", writer = "", q = "", kind = "", fav = false, sort = "newest", played = "", localKeys = new Set() } = {}) {
    const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    const hay = m => [m.name, m.game_id, m.title, m.mod_title, m.original_title, m.writer, ...(m.changes || []).map(r => `${r.donor} ${r.slot}`),
      ...(m.tickets || []).map(t => `#${t.number} ${t.title || ""}`)].join(" ").toLowerCase();
    return (items || []).filter(m => (!game || m.game_id === game) && (!writer || m.writer === writer) && (!fav || m.favorite)
        && (!kind || (kind === "showcase") === !!m.showcase) && words.every(w => hay(m).includes(w))
        && (!played || (played === "unplayed" ? m.play_count === 0 : m.play_count > 0)))
      .sort((a, b) => {
        const newest = (b.built || 0) - (a.built || 0) || String(a.key).localeCompare(String(b.key));
        if(sort==='local')return (+!localKeys.has(a.key)-+!localKeys.has(b.key))||newest;
        if (sort === "favorites") return (+!!b.favorite - +!!a.favorite) || newest;
        if (sort === "oldest") return (a.built || 0) - (b.built || 0) || newest;
        if (sort === "unplayed") return (+!!a.play_count - +!!b.play_count) || newest;
        if (sort === "plays") return (b.play_count || 0) - (a.play_count || 0) || newest;
        if (sort === "recent") return (b.last_played || 0) - (a.last_played || 0) || newest;
        if (sort === "name") return String(a.mod_title || a.name).localeCompare(String(b.mod_title || b.name)) || newest;
        return newest;
      });
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
             writers: [...writers.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([writer, count]) => ({ writer, count })),
             showcase: (items || []).filter(m => m.showcase).length, favorites };
  }
  // the build's own endpoints (gbox/builds.py): PATCH {display_name} renames, PUT {favorite} stars
  const buildPath = m => `/api/builds/${encodeURIComponent(m.game_id)}/${encodeURIComponent(m.name)}`;

  // in-game shots first (what the build looks like running: card shots, then frames captured from sessions of the build),
  // then the writer's previews, then the donors
  function imagesOf(m, url = u => u) {
    return [...(m.shots || []).map(s => ({ src: url(s.url), name: `${m.mod_title}: in-game shot`, kind: "shot" })),
            ...(m.frames || []).map(f => ({ src: url(f.url), name: `${m.mod_title}: ${f.source || "frame"} (session ${String(f.session_id || "").slice(0, 8)})`, kind: "shot" })),
            ...(m.images || []).map(i => ({ src: url(i.url), name: `${m.mod_title}: ${i.name}`, kind: "build" })),
            ...(m.fit_previews || []).map(p => ({ src: url(p.url), name: `${m.mod_title}: ${p.label || p.slot} (fitting)`, kind: "fit" })),
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
    return `<ul class="mg-ch">${rows.map(r => `<li${r.reason ? ` title="${ESC(r.reason)}"` : ""}><b>${String(r.donor || "").split(",").map(s => s.trim()).filter(Boolean).map(slug => `<button type="button" class="mg-character" data-mg="character" data-slug="${ESC(slug)}" data-slot="${ESC(r.slot || "player")}" title="View ${ESC(slug)} in 3D, export to Blender, examine or retarget">${ESC(slug)}</button>`).join(", ") || "?"}</b> <button type="button" class="mg-character" data-mg="mapping" data-slug="${ESC(String(r.donor||'').split(',')[0].trim())}" data-slot="${ESC(r.slot||'player')}" title="Inspect this character mapping, proportions and recorded reduction">→ ${ESC(r.slot || "?")}</button>`
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
  const starHTML = m => `<button class="mg-ico mg-star${m.favorite ? " on" : ""}" type="button" data-mg="fav" aria-pressed="${!!m.favorite}" title="${m.favorite ? "Remove from favorites" : "Add to favorites: filter with ★ Favorites, at the top of the game's Special builds, never evicted"}" aria-label="Favorite">${m.favorite ? "★" : "☆"}</button>`;
  // the card's options (⋯ or right-click): Rename…, favorite, Play, restore the original name
  function menuHTML(m) {
    const item = (act, text, title = "") => `<button class="act" type="button" role="menuitem" data-mg="${act}"${title ? ` title="${ESC(title)}"` : ""}>${text}</button>`;
    return `<div class="mg-menu" role="menu" data-mg-menu="${ESC(m.key)}">${item("rename", "✎ Rename…", "Give this build your own name (the folder keeps its name)")}`
      + item("fav", m.favorite ? "☆ Remove from favorites" : "★ Add to favorites")
      + (m.display_name ? item("unname", `↺ Restore “${ESC(m.original_title || m.name)}”`) : "")
      + item("play", "▶ Play") + item("report", "⚑ Report a problem…", "File a report: it doesn't do what it should")
      + item("delete", "🗑 Delete…", "Delete this build (asks first: everywhere or only this PC)") + "</div>";
  }

  // the launch failure ticket of this build (gbox/launch_failures.py, docs/launch-failure-reports.md)
  function reportText(r) {
    if (!r || !r.number) return "";
    return r.verified ? `Fixed, verified (#${r.number})` : `Reported as #${r.number}, being investigated`;
  }
  function reportHTML(r) {
    const said = reportText(r);
    if (!said) return "";
    const why = [r.label, r.count > 1 ? `${r.count} failures` : "", r.status ? `request ${String(r.status).replace("_", " ")}` : ""].filter(Boolean).join(" · ");
    return `<div class="mg-lfr"><button class="act mg-lf ${r.verified ? "mg-lf-ok" : "mg-lf-bad"}" type="button" data-mg="request" data-n="${ESC(r.number)}"
      title="${ESC("Open request #" + r.number + (why ? ": " + why : ""))}">${r.verified ? "✓" : "⚠"} ${ESC(said)}</button></div>`;
  }

  // the ⚑ build report filed on this build (#1656: POST /api/builds/{game}/{name}/report), next to the launch failure
  // ticket in one badge row: "⚠ Reported as #12, being investigated" (launch failure) · "⚑ Build report #14"
  function buildReportHTML(r) {
    if (!r || !r.number) return "";
    return `<button class="act mg-lf mg-br" type="button" data-mg="request" data-n="${ESC(r.number)}"
      title="${ESC(`Open request #${r.number}: the build report you filed (it doesn't do what it should)`)}">⚑ Build report #${ESC(r.number)}</button>`;
  }
  function reportsHTML(lfr, rep) {
    const a = reportHTML(lfr), b = buildReportHTML(rep);
    if (!b) return a;
    return `<div class="mg-lfr">${a ? a.replace(/^<div class="mg-lfr">/, "").replace(/<\/div>$/, "") : ""}${b}</div>`;
  }

  // dl / dlMenu: the download icon (top-right of the picture) and its open menu (viz/build-local.js), "" without a PC view
  function cardHTML(m, { url = u => u, idx = 0, now, renaming = false, menu = false, note = "", choice = null, dl = "", dlMenu = "", localState = null } = {}) {
    const imgs = imagesOf(m, url), i = imgs.length ? ((idx % imgs.length) + imgs.length) % imgs.length : 0, cur = imgs[i];
    const lfr = m.launch_report && m.launch_report.number ? m.launch_report : null;
    const tickets = (m.tickets || []).filter(t => (!lfr || String(t.number) !== String(lfr.number))
      && (!m.reported || String(t.number) !== String(m.reported.number)));
    return `<article class="mg-card${m.favorite ? " mg-fav" : ""}${m.broken ? " mg-broken" : ""}" data-key="${ESC(m.key)}">${menu ? menuHTML(m) : ""}${dlMenu ? `<div class="mg-dlm">${dlMenu}</div>` : ""}
      <div class="mg-pic">${cur ? `<img class="mg-img" loading="lazy" decoding="async" alt="${ESC(cur.name)}" data-i="${i}" src="${ESC(cur.src)}">
        ${imgs.length > 1 ? `<button class="mg-nav" data-mg="prev" type="button" title="Previous picture">‹</button><button class="mg-nav" data-mg="next" type="button" title="Next picture">›</button>` : ""}
        <span class="mg-count">${cur.kind === "shot" ? "in-game · " : cur.kind === "donor" ? "donor · " : ""}${i + 1} / ${imgs.length}</span>`
        : `<div class="mg-none">No pictures yet: Screenshot after launch adds one</div>`}${dl ? `<div class="mg-dl">${dl}</div>` : ""}${localState?.state==='busy'?`<div class="mg-download-progress" role="progressbar" aria-label="Build download" aria-orientation="vertical" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${localState.pct}" title="Downloading ${localState.pct}%"><i style="height:${localState.pct}%"></i></div>`:''}</div>
      <div class="mg-body">
        ${localState?.state==='here'?`<button type="button" class="mg-broken-toggle" data-mg="broken" aria-label="${m.broken ? "View broken build investigation" : "Mark build broken"}" aria-pressed="${!!m.broken}" title="${m.broken ? "View investigation" : "Mark broken, investigate, then delete"}">&#9888;</button>`:''}
        ${m.broken ? `<div class="mg-broken-status" role="status">Broken · ${ESC(({queued:"queued for review",preserving:"preserving evidence",preserved:"removed from PC · under review",blocked:"cleanup needs attention"})[m.broken.state] || m.broken.state)}${m.broken.number ? ` · #${ESC(m.broken.number)}` : ""}${m.broken.error ? `<div>${ESC(m.broken.error)}</div>` : ""}</div>` : ""}
        <div class="mg-h"><span class="mg-tt">${starHTML(m)}${titleHTML(m, renaming)}</span>
          <span class="mg-hr"><span class="mg-badge ${m.verified ? "mg-ok" : "mg-unv"}">${m.verified ? "verified" : "unverified"}</span><button class="mg-ico" type="button" data-mg="menu" aria-haspopup="menu" aria-expanded="${!!menu}" title="Options (or right-click the card)" aria-label="Options">⋯</button></span></div>
        ${m.display_name && m.original_title && m.original_title !== m.display_name ? `<div class="mg-was mut">was “${ESC(m.original_title)}”</div>` : ""}
        <div class="mg-sub"><span class="mg-chip" data-mg-game="${ESC(m.game_id)}">${ESC(m.title || m.game_id)}</span>
          <span class="mg-chip" data-mg-writer="${ESC(m.writer)}">${ESC(m.writer)}</span>${m.cast ? '<span class="mg-chip">cast swap</span>' : ""}${m.showcase ? '<span class="mg-chip mg-sonic" data-mg-kind="showcase" title="A Sonic showcase test build (Settings &gt; Sonic showcase)">Sonic showcase</span>' : ""}</div>
        ${BA()?.whatHTML(m.what) || ""}
        ${m.unlocks ? `<div class="mg-unlock-status"><span class="mg-chip">${ESC(m.unlocks.label)}</span>${m.unlocks.number ? `<button class="act" type="button" data-mg="unlock-ticket">#${ESC(m.unlocks.number)}</button>` : ""}</div>` : ""}
        <div class="mg-plays" title="Recorded player launches; failed starts and automated tests are excluded"><span>${m.play_count == null ? "Play count unavailable" : `${m.play_count} ${m.play_count === 1 ? "play" : "plays"}`}</span>${m.play_count === 0 ? ' <span class="mg-chip mg-unplayed">unplayed</span>' : ""}</div>
        ${changesHTML(m)}
        <div class="mg-meta mut">${ESC(m.name)} · built ${ESC(fmtAge(m.built, now))} · ${sizeHTML(m)}
          · <span class="mg-launch${m.last_launch && /failed|cancelled/.test(m.last_launch.state) ? " mg-bad" : ""}">${ESC(launchText(m.last_launch, now))}</span></div>
        ${reportsHTML(lfr, m.reported)}
        ${tickets.length ? `<div class="mg-tk">${tickets.map(t => `<button class="act mg-req" type="button" data-mg="request" data-n="${t.number}" title="${ESC(t.title || "Open request #" + t.number)}">Open request #${t.number}${t.status ? " · " + ESC(t.status.replace("_", " ")) : ""}</button>`).join("")}</div>` : ""}
        <div class="mg-btns"><button class="act pri" type="button" data-mg="play"${m.broken ? " disabled" : ""}>Play</button>
          ${m.state_slot != null && m.card_id && !m.broken ? `<button class="act" type="button" data-mg="moment" title="Launch and load the saved moment (slot ${ESC(m.state_slot)})">Play from saved moment</button>` : ""}
          <button class="act" type="button" data-mg="shot" title="This build running now: capture a frame of it. Another build of the game running: you choose. Nothing running: launch it, then capture. The frame joins this mod's pictures (its thumbnail when it has none)"${m.card_id && !m.broken ? "" : " disabled"}>Screenshot after launch</button>
          <span class="mg-msg mut">${ESC(note)}</span>
          <span class="mg-acts"><button class="act" type="button" data-mg="report" title="Report a problem with this build: it doesn't show the expected change, looks broken, crashes…">⚑ Report</button><button class="act mg-del" type="button" data-mg="delete" title="Delete this build (asks first: everywhere or only this PC)" aria-label="Delete">🗑</button></span></div>${choice && BS ? BS.choiceHTML(choice, "data-mg") : ""}</div></article>`;
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
      <details class="mg-sort"><summary title="Filter and sort mods" aria-label="Filter and sort mods"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 4h18l-7 8v7l-4 2V12z"/></svg></summary><div class="mg-sort-menu">
        <label>Sort by <select data-mg-f="sort">${[["newest","Newest builds first"],["local","On selected PC first"],["oldest","Oldest builds first"],["favorites","Favorites first"],["unplayed","Unplayed first"],["plays","Most played"],["recent","Recently played"],["name","Name A–Z"]].map(([k,l])=>opt(k,l,st.sort || "newest")).join("")}</select></label>
        <label>Show <select data-mg-f="played">${opt("","All play counts",st.played || "")}${opt("unplayed","Unplayed only",st.played || "")}${opt("played","Played only",st.played || "")}</select></label></div></details>
      <input type="search" data-mg-f="q" placeholder="Search mod, game, donor, slot, #request" value="${ESC(st.q)}">
      <select data-mg-f="game">${opt("", "All games", st.game)}${f.games.map(g => opt(g.game_id, `${g.title} (${g.count})`, st.game)).join("")}</select>
      <select data-mg-f="writer">${opt("", "All writers", st.writer)}${f.writers.map(w => opt(w.writer, `${w.writer} (${w.count})`, st.writer)).join("")}</select>
      <label class="mg-favf" title="Only the builds you starred (★)"><input type="checkbox" data-mg-f="fav"${st.fav ? " checked" : ""}> ★ Favorites${f.favorites ? ` (${f.favorites})` : ""}</label>
      <select data-mg-f="kind" title="Sonic showcase: the background test builds with the Sonic Adventure cast">${opt("", "All builds", st.kind || "")}${opt("showcase", `Sonic showcase (${f.showcase || 0})`, st.kind || "")}${opt("other", "Other builds", st.kind || "")}</select>
      <label class="mut">Play on <select data-mg-f="node">${opt("", "This PC", st.node)}${nodes.map(n => opt(n.name, `${n.name} (${n.os})`, st.node)).join("")}</select></label>
      <button class="act" type="button" data-mg="refresh" title="Rescan the build folders">Refresh</button><span class="mut" data-mg-sum></span></div>
      <div data-mg-live-controls></div><div class="mg-grid" data-mg-grid></div><div data-mg-more></div>`;
  }

  const CSS = `.mg-sort{position:relative}.mg-sort summary{list-style:none;cursor:pointer;padding:6px;border:1px solid var(--line,#444);border-radius:5px;display:flex}.mg-sort summary::-webkit-details-marker{display:none}
    .mg-sort-menu{position:absolute;left:0;top:34px;z-index:8;min-width:225px;padding:12px;background:var(--bg,#16161a);border:1px solid var(--line,#444);border-radius:8px;box-shadow:0 8px 24px #000a}.mg-sort-menu label{display:flex;flex-direction:column;gap:5px;margin-bottom:8px}
    .mg-character{font:inherit;font-weight:600;color:var(--acc,#a2b5ff);background:none;border:0;border-bottom:1px dotted currentColor;padding:0;cursor:pointer}.mg-character:hover{color:#fff}.mg-plays{font-size:12px;color:#bfc7db}.mg-unplayed{color:#d4c9ff;border-color:#8472b8}
    .mg-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px}.mg-bar input[type=search]{flex:1;min-width:180px}
    .mg-broken-toggle{position:absolute;top:6px;left:6px;z-index:3;border:1px solid #cf796c;border-radius:6px;background:#241a1a;color:#ffbdab;font-size:18px;cursor:pointer;padding:3px 7px}
    .mg-download-progress{position:absolute;top:0;bottom:0;right:0;width:9px;background:#263043;z-index:2;pointer-events:none}.mg-download-progress i{position:absolute;bottom:0;left:0;right:0;background:#7ba6ff;box-shadow:0 0 8px #80adff;transition:height .3s}
    .mg-broken{border-color:#b85d50!important}.mg-broken-status{background:#612c27;color:#fff1e9;padding:6px 8px;border-radius:4px;font-weight:600}
    .mg-broken button:disabled{opacity:.45;cursor:not-allowed}
    .mg-broken::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:2;opacity:.12;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='170' height='170'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.9'/%3E%3C/svg%3E"),repeating-linear-gradient(0deg,transparent 0 2px,#000 2px 4px);animation:mg-static 1.2s steps(3,end) infinite}
    @keyframes mg-static{0%{background-position:0 0}50%{background-position:45px -30px}100%{background-position:-20px 50px}}
    @media(prefers-reduced-motion:reduce){.mg-broken::after{animation:none}}
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
    .mg-menu .act{text-align:left}.mg-acts{margin-left:auto;display:flex;gap:4px}.mg-del:hover{background:#7a2b2b;color:#fff}
    .mg-lfr{display:flex}.mg-lfr .mg-lf{font-size:12px;font-weight:600;border-radius:9px;padding:2px 9px;color:#fff}.mg-lfr .mg-lf.mg-lf-bad{background:#7a2b2b;border-color:#c0504d}.mg-lfr .mg-lf.mg-lf-ok{background:#1f6f3f;border-color:#2f9a5a}
    .mg-lfr{gap:6px;flex-wrap:wrap}.mg-lfr .mg-lf.mg-br{background:#5a3f8a;border-color:#7d5cc0}
    .mg-dl{position:absolute;top:6px;right:6px;z-index:2}.mg-dlm{position:absolute;z-index:6;top:38px;right:6px}
    ${BS ? BS.CSS : ""}${BL() ? BL().CSS : ""}`;

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // the controller: one host element, env = { api(path, body?) -> data (throws), url(path) -> loadable URL,
  //   openImages(list, i, [x, y]), poll (GBoxLivePoll), here (this PC's worker name), visible() -> bool,
  //   play?(mod, {node, moment}), openRequest?(ticket), toast?(text), wait?(ms) }
  function mount(host, env) {
    const st = { q: env.q || "", game: env.game || "", writer: "", kind: env.kind || "", node: "", fav: !!env.fav, sort: "newest", played: "", page: 1, idx: new Map(), data: null,
                 nodes: [], sig: "", renaming: null, menu: null, notes: new Map(),
                 choice: new Map() };                        // card key -> the screenshot choice it offers (another build runs)
    const poll = env.poll || root.GBoxLivePoll;
    const read = poll ? poll.cachedRead(() => env.api("/api/mods/built").then(data => ({ ok: true, data }), e => ({ ok: false, error: e.message })), { ttl: 15000 })
      : { get: () => env.api("/api/mods/built").then(data => ({ ok: true, data }), e => ({ ok: false, error: e.message })), invalidate() {} };
    const wait = env.wait || sleep, toast = env.toast || (() => {});
    const url = env.url || (u => u);
    let timer = null, built = false, liveControls = null;
    // the download icon: this PC's copy of each build (GET /api/builds/local), downloads / exports running from here
    const locals=new Map();let local=null,stopped=false;
    function selectLocal(){
      const target=st.node||env.here||'';
      if(!BL()||!target||target==='auto'){local=null;return null;}
      if(!locals.has(target)){
        const instance=BL().create({...env,here:target},{redraw:()=>{if(!stopped&&local===instance&&!st.renaming)draw();},note:(b,t)=>{if(local===instance)note(b.key,t);},toast});
        locals.set(target,instance);
      }
      return local=locals.get(target);
    }
    selectLocal();

    function shell() {
      liveControls?.dispose();
      const f = facets(st.data?.items || []);
      host.innerHTML = `<style>${CSS}${BA()?.WHAT_CSS || ""}</style>` + toolbarHTML(st, f, st.nodes);
      const liveHost=host.querySelector('[data-mg-live-controls]');
      if(liveHost && root.GBoxLiveControls) liveControls=root.GBoxLiveControls.mount(liveHost,{api:env.api,pso:root.GBoxPSO,wait:env.wait},{game:st.game});
      built = true;
    }
    function shown() { return filterMods(st.data?.items || [], {...st,localKeys:new Set((st.data?.items||[]).filter(m=>local?.state(m).state==='here').map(m=>m.key))}); }
    function draw() {
      if (!built) shell();
      liveControls?.setGame(st.game);
      const list = shown(), page = list.slice(0, st.page * PAGE), more = list.length - page.length;
      const grid = host.querySelector("[data-mg-grid]"), sum = host.querySelector("[data-mg-sum]"), moreEl = host.querySelector("[data-mg-more]");
      if (grid) grid.innerHTML = page.map(m => cardHTML(m, { url, idx: st.idx.get(m.key) || 0, renaming: st.renaming === m.key, menu: st.menu === m.key,
                                                                note: st.notes.get(m.key) || "", choice: st.choice.get(m.key),
                                                                dl: local ? local.iconHTML(m) : "", dlMenu: local ? local.menuHTML(m) : "",localState:local?.state(m) })).join("")
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
    // Screenshot after launch (build-shot.js): this build running = capture now; another build of the game running =
    // the card asks (capture from that build / switch to this one); nothing running = launch (never a swap), capture.
    // -> the session the frame came from, or null while the card waits for the operator's choice
    async function screenshot(m, card, choice = "") {
      if (!m.card_id) throw new Error("this build has no mod card yet: refresh");
      const offered = st.choice.get(m.key);
      const r = await BS.run({ api: env.api, wait, msg: t => msg(card, t), items: () => st.data?.items || [],
        // nothing of this game runs: start it with swap off, so a game started meanwhile is never swapped silently
        launch: async b => jobDone(await env.api("/api/jobs", { tool: "@launch", input: { game_id: b.game_id, mod: b.name, node: nodeOf(), swap: false } }),
          "launch") }, m, { choice, expect: offered?.session_id });
      if (r.choice) {
        st.choice.set(m.key, r.choice); draw();
        msg(host.querySelector?.(`.mg-card[data-key="${String(m.key).replace(/"/g, '\\"')}"]`) || card,
          r.stale ? "The running game changed: choose again" : "Another build of this game is running: choose below");
        return null;
      }
      st.choice.delete(m.key);
      read.invalidate(); await env.api("/api/mods/built?fresh=true").catch(() => null);
      st.sig = ""; await load(0);
      if (!st.sig) draw();
      toast(`${r.into}: in-game picture added`);
      return r.session_id;
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

    // ⚑ Report / 🗑 Delete: the shared dialogs (viz/build-actions.js); env.buildActions replaces them in tests
    const dialogs = () => env.buildActions || BA();
    const dialogEnv = () => ({ document: env.document || root.document, api: env.api, here: st.node || (env.here && env.here !== "auto" ? env.here : "") });
    async function report(m) {
      const r = await dialogs().open("report", m, dialogEnv());
      if (!r) return null;
      m.reported = { number: r.number, id: r.id };
      note(m.key, `⚑ Reported: request #${r.number}`);
      read.invalidate(); st.sig = ""; draw();
      toast(`${m.mod_title || m.name}: report filed as request #${r.number}`);
      return r;
    }
    async function markBroken(m, card) {
      if(local?.state(m).state!=='here'){toast('Download this build to the selected PC before marking its copy broken.');return;}
      if (m.broken?.number) {
        const ticket = {number:m.broken.number, id:m.broken.request_id};
        return openRequest(ticket.number, {...m,tickets:[...(m.tickets || []),ticket]}, card);
      }
      const r = await dialogs().open("broken", m, dialogEnv());
      if (!r) return null;
      m.broken = r; m.reported = { number: r.number, id: r.request_id };
      read.invalidate(); st.sig = ""; draw();
      toast(`Broken build queued for investigation #${r.number}; files removed after verified preservation`);
      return r;
    }
    async function remove(m) {
      let b = m;
      try {                                                  // where it lives (the Spark, this PC, other PCs) for the dialog
        const got = await env.api(`/api/builds?game_id=${encodeURIComponent(m.game_id)}&q=${encodeURIComponent(m.name)}`);
        const row = (got?.items || []).find(x => x.key === m.key);
        if (row) b = { ...m, where: row.where, size: m.size ?? row.size, own_size: m.own_size ?? row.own_size };
      } catch {}
      const r = await dialogs().open("delete", b, dialogEnv());
      if (!r) return null;
      const text = dialogs().deleteResultText(b, r);
      if (r.scope === "all" && st.data) st.data.items = st.data.items.filter(x => x.key !== m.key);
      else note(m.key, text);
      read.invalidate(); st.sig = ""; built = false; draw();
      toast(text);
      return r;
    }

    async function onClick(e) {
      const t = e.target, card = t.closest?.(".mg-card"), m = card && find(card.dataset.key);
      const act = t.closest?.("[data-mg]")?.dataset.mg;
      if (t.closest?.("[data-mg-rename]")) return;          // clicks inside the rename field stay in it
      if (local && t.closest?.("[data-bl]")) {               // the download icon and its menu (viz/build-local.js)
        if (st.menu) st.menu = null;
        await local.onClick(e, m || find(t.closest?.("[data-bl-menu]")?.dataset?.blMenu));
        return;
      }
      if (local?.menu && !t.closest?.("[data-bl-menu]")) { local.menu = null; draw(); if (!act) return; }
      if (st.menu && act !== "menu" && !t.closest?.("[data-mg-menu]")) { st.menu = null; draw(); if (!act) return; }
      if (act === "more") { st.page++; draw(); return; }
      if (act === "refresh") { try { await env.api("/api/mods/built/refresh", {}); } catch {} read.invalidate(); st.sig = ""; await load(0); return; }
      const chipG = t.closest?.("[data-mg-game]"), chipW = t.closest?.("[data-mg-writer]"), chipK = t.closest?.("[data-mg-kind]");
      if (chipK) { st.kind = chipK.dataset.mgKind; st.page = 1; built = false; draw(); return; }
      if (chipG || chipW) { if (chipG) st.game = chipG.dataset.mgGame; else st.writer = chipW.dataset.mgWriter; st.page = 1; built = false; draw(); return; }
      if (!m) return;
      if (act === "character") {
        const b = t.closest("[data-slug]");
        return env.openCharacter?.({slug:b.dataset.slug, name:b.dataset.slug, gid:m.game_id, slot:b.dataset.slot});
      }
      if(act==='mapping'){
        const button=t.closest('[data-slug]');
        return env.openMapping?.({slug:button.dataset.slug,gid:m.game_id,title:m.title,slot:button.dataset.slot,build_name:m.name});
      }
      if (act === "unlock-ticket") return openRequest(m.unlocks.number, {...m,tickets:[...(m.tickets || []),{number:m.unlocks.number,id:m.unlocks.request_id}]}, card);
      if (act === "broken") return markBroken(m, card);
      if (m.broken && ["play", "moment", "shot"].includes(act)) { toast("This build is broken and queued for investigation"); return; }
      if (act === "rename") { e.preventDefault?.(); startRename(m); return; }
      if (act === "fav") { e.preventDefault?.(); await favorite(m); return; }
      if (act === "menu") { st.menu = st.menu === m.key ? null : m.key; draw(); return; }
      if (act === "unname") { st.menu = null; await rename(m.key, ""); return; }
      if (act === "report" || act === "delete") { if (st.menu) { st.menu = null; draw(); } return act === "report" ? report(m) : remove(m); }
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
        } else if (act === "shot-running" || act === "shot-switch") {     // the second, explicit click of a choice
          if (btn) btn.disabled = true;
          await screenshot(m, card, act === "shot-running" ? "running" : "switch");
        } else if (act === "shot-cancel") {
          st.choice.delete(m.key); draw(); msg(host.querySelector?.(`.mg-card[data-key="${String(m.key).replace(/"/g, '\\"')}"]`) || card, "Nothing changed");
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
    async function onInput(e) {
      const f = e.target?.dataset?.mgF; if (!f) return;
      const value=e.target.type === "checkbox" ? !!e.target.checked : e.target.value;
      if(st[f]===value)return;
      st[f]=value;st.page=1;
      if(f==='node'){
        st.sort='local';const control=host.querySelector('[data-mg-f="sort"]');if(control)control.value=st.sort;
        const current=selectLocal();draw();await current?.refresh(0);if(!stopped&&local===current)draw();return;
      }
      draw();
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
      if (e.key === "Escape" && local?.menu) local.close();
    }
    function onFocusOut(e) {                                 // leaving the field keeps what was typed (as the Builds view does)
      const inp = e.target?.closest?.("[data-mg-rename]");
      if (inp && st.renaming === inp.dataset.mgRename) rename(inp.dataset.mgRename, inp.value);
    }
    // right-click a card: its options (Rename…, favorite, Play); runs before the app's "file a request" menu
    function onContext(e) {
      const card = e.target?.closest?.(".mg-card"); if (!card || e.target.closest?.("input, textarea")) return;
      if (local && local.onContext(e, find(card.dataset.key))) { st.menu = null; return; }   // right-click the icon: its menu
      e.preventDefault?.(); e.stopPropagation?.();
      if (local) local.menu = null;
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
      await nodes(); await local?.refresh(); await load(0);
      if (!built) draw();
      timer = setInterval(tick, TICK);
      return api;
    }
    // one cached read per tick at most: every few seconds while the index is still working, else every 30 s
    function busy() { return !!(st.data && (st.data.indexing || st.data.sizing)); }
    async function tick() {
      if (env.visible && !env.visible()) return;
      if (local) {                                           // this PC's copies: a fresh list every 20 s at most
        const before = JSON.stringify(local.local);
        await local.refresh(20000);
        if (JSON.stringify(local.local) !== before && !st.renaming) draw();
      }
      return load(busy() ? TICK - 500 : 30000);
    }
    function stop() {
      liveControls?.dispose();
      stopped=true;
      clearInterval(timer);
      for (const [ev, fn] of [["click", onClick], ["input", onInput], ["change", onInput], ["keydown", onKey], ["focusout", onFocusOut], ["contextmenu", onContext]])
        host.removeEventListener?.(ev, fn);
    }
    // show one build / request: the game menu's "Open in Mods page" (search + game filter set, the toolbar redrawn)
    function focus({ q, game } = {}) { if (q != null) st.q = String(q); if (game != null) st.game = String(game); st.page = 1; built = false; draw(); }
    const api = { st, local, load, draw, stop, start, play, screenshot, onClick, onInput, onKey, onFocusOut, onContext, rename, favorite, report, remove, tick, busy, focus, ready: null };
    api.ready = start();
    return api;
  }

  const api = { filterMods, facets, imagesOf, cardHTML, titleHTML, menuHTML, buildPath, toolbarHTML, changesHTML, requestHTML,
                fmtSize, fmtAge, launchText, reportText, reportHTML, reportsHTML, summaryText, mount, PAGE, TICK };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxModsGallery = api;
})(typeof window !== "undefined" ? window : globalThis);
