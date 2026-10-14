// Builds view (top bar "Builds"; gbox/builds.py): every custom / modified build in one list and the build jobs that are
// scheduled or running.
//   Custom builds: the Spark's central collection + each PC's own builds (staged copies deduped), newest first, search,
//   game and kind filters, a thumbnail, display name (double-click or ✎ to rename: stored on the server, never the folder),
//   game, kind, date, size, where it lives, ▶ Launch (this PC) and ▾ the other launch options (gbox.special_builds),
//   ✎ Rename… and ★ favorite (a right-click on the row opens the same options). #1656: ☆/★ on each row, a ★ Favorites
//   filter, favorites first.
//   #1639: the download icon at the right end of each row (viz/build-local.js): on this PC / not on this PC (a click
//   downloads it into this PC's cache, never launching it) / downloading; right-click or ▾: Download to this PC, Export…,
//   Open folder, Delete from this PC.
//   Details ▸ per build: modifications (changed files), characters inserted (slot <- donor, each with two 360° three.js
//   turntables: the donor as fitted, "who they are", and the original character, "who they're replacing"; GLBs load
//   only while the details are open and the viewer is on screen, previews otherwise), codes / cheats / hacks, compile
//   changes, the build recipe, jobs + receipts and verification.
//   Scheduled & running: queued / claimed / running build jobs with worker, progress and ETA; Cancel, Edit (queued:
//   cancel + resubmit with the edited input), Investigate (log tail, receipt, artifacts, fitting events); Details ▸ is a
//   three.js flowchart of the job (queued -> claimed -> stages -> write -> verify -> done, current node animated, failed
//   nodes red).
// Plain functions + a controller rendering HTML strings into a host element (the Mods gallery's pattern), so node tests
// drive it with a stub three.js and a fake IntersectionObserver (tests/test_builds_view.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const BS = root.GBoxBuildShot || (typeof require === "function" ? require("./build-shot.js") : null);   // 📷 rules
  const KINDS = { cast: "cast swap", character: "character swap", file: "file mod", cheats: "cheats", romhack: "ROM hack",
                  compile: "decomp / compile", showcase: "showcase", test: "test", collect: "collect" };
  const TICK = 4000;                                        // scheduled jobs poll (ms) while the view is shown
  // What this changes / Delete / Report (viz/build-actions.js; loaded before this file, or required by node tests)
  const BA = () => root.GBoxBuildActions || (typeof module === "object" && module.exports ? require("./build-actions.js") : null);
  // On this PC: the download icon, its menu and the Export dialog (viz/build-local.js)
  const BL = () => root.GBoxBuildLocal || (typeof module === "object" && module.exports ? require("./build-local.js") : null);
  const LIST_EVERY = 30000;                                 // the build list (5 s while the index is still working)
  const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.160.0/+esm";
  const GLTF_URL = "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js/+esm";
  const SPIN = 2 * Math.PI / 9000;                          // one full turn every 9 s
  const FLOW_COLORS = { done: 0x4fc28b, running: 0x69d6e7, pending: 0x56607a, failed: 0xff6b6b, skipped: 0x8a8f9c };

  // ---------------------------------------------------------------- formatting
  const fmtSize = n => n == null ? "sizing…" : !n ? "0 B" : n >= 2 ** 30 ? (n / 2 ** 30).toFixed(2) + " GB"
    : n >= 2 ** 20 ? (n / 2 ** 20).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B";
  function fmtAge(ts, now = Date.now() / 1000) {
    if (!ts) return "unknown";
    const s = Math.max(0, now - ts);
    return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago`
      : `${Math.round(s / 86400)} days ago`;
  }
  const fmtDate = ts => ts ? new Date(ts * 1000).toLocaleString() : "";
  function fmtEta(s) {
    if (s == null) return "";
    return s < 60 ? `~${Math.max(1, Math.round(s))} s left` : s < 3600 ? `~${Math.round(s / 60)} min left` : `~${(s / 3600).toFixed(1)} h left`;
  }
  const sizeOf = b => b.size == null ? null : (b.own_size || b.size);
  const SORTS = { name: "Name", game: "Game", kind: "Kind", built: "Built", size: "Size", where: "Lives on" };
  const firstDirection = key => key === "built" || key === "size" ? "desc" : "asc";
  const textOrder = (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  function sortValue(b, key) {
    switch (key) {
      case "name": return b.label || b.name || "";
      case "game": return b.game_title || b.game_id || "";
      case "kind": return (b.kinds || [b.kind]).map(k => KINDS[k] || k || "").join(", ");
      case "built": return b.built || null;
      case "size": return b.local_only ? null : sizeOf(b);
      case "where": return (b.where || []).map(w => w.label || "").sort(textOrder).join(", ");
    }
  }
  function compareBuilds(a, b, sort, direction) {
    if (!Object.hasOwn(SORTS, sort)) return (+!!b.favorite - +!!a.favorite) || (b.built || 0) - (a.built || 0);
    const av = sortValue(a, sort), bv = sortValue(b, sort);
    // Unknown dates / sizes stay at the bottom in either direction.
    if (av == null || bv == null) return av == null ? (bv == null ? 0 : 1) : -1;
    const order = typeof av === "number" && typeof bv === "number" ? av - bv : textOrder(av, bv);
    return order * (direction === "desc" ? -1 : 1) || textOrder(a.key || a.name || "", b.key || b.name || "");
  }
  function sortHeadersHTML(st) {
    return '<span></span><span></span>' + Object.entries(SORTS).map(([key, label]) => {
      const active = st.sort === key, next = active ? (st.direction === "asc" ? "desc" : "asc") : firstDirection(key);
      const current = active ? `, sorted ${st.direction === "asc" ? "ascending" : "descending"}` : "";
      return `<button type="button" class="bv-sort${active ? " on" : ""}" data-bv="sort" data-sort="${key}" aria-pressed="${active}" aria-label="${label}${current}. Sort ${next === "asc" ? "ascending" : "descending"}" title="Sort ${label}: ${next === "asc" ? "ascending" : "descending"}">${label}<span aria-hidden="true">${active ? (st.direction === "asc" ? "↑" : "↓") : "↕"}</span></button>`;
    }).join("") + '<span></span>';
  }

  // ---------------------------------------------------------------- filtering
  // favorites (★) first, then newest; fav: only the favorites
  function filterBuilds(items, { q = "", game = "", kind = "", fav = false, sort = "", direction = firstDirection(sort) } = {}) {
    const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    const hay = b => [b.name, b.label, b.original_title, b.game_id, b.game_title, b.writer, ...(b.kinds || []).map(k => KINDS[k] || k),
      ...(b.changes || []).map(r => `${r.donor} ${r.slot}`), ...(b.tickets || []).map(t => `#${t.number}`)].join(" ").toLowerCase();
    return (items || []).filter(b => (!game || b.game_id === game) && (!kind || (b.kinds || [b.kind]).includes(kind)) && (!fav || b.favorite) && words.every(w => hay(b).includes(w)))
      .sort((a, b) => compareBuilds(a, b, sort, direction));
  }
  function facets(items) {
    const games = new Map(), kinds = new Map();
    let favorites = 0;
    for (const b of items || []) {
      const g = games.get(b.game_id) || { game_id: b.game_id, title: b.game_title || b.game_id, count: 0 };
      g.count++; games.set(b.game_id, g);
      for (const k of b.kinds || [b.kind]) kinds.set(k, (kinds.get(k) || 0) + 1);
      if (b.favorite) favorites++;
    }
    return { games: [...games.values()].sort((a, b) => a.title.localeCompare(b.title)),
             kinds: Object.keys(KINDS).filter(k => kinds.has(k)).map(k => ({ kind: k, label: KINDS[k], count: kinds.get(k) })), favorites };
  }
  const buildPath = b => `/api/builds/${encodeURIComponent(b.game_id)}/${encodeURIComponent(b.name)}`;

  // ---------------------------------------------------------------- launching
  const defaultOption = b => (b.launch_options || []).find(o => o.default) || (b.launch_options || [])[0] || null;
  function optLabel(o, here) {
    if (o.target === "here" && !o.moment && !o.debug) return `This PC${here && here !== "auto" ? ` (${here})` : ""}`;
    return o.label || o.id;
  }
  // the request the game menu's Special builds send: node=auto -> this PC's worker for "here" options
  function launchCall(b, o, here) {
    const node = o.target === "here" ? (here || "auto") : o.node;
    const path = String(o.call?.path || "").replace(/([?&])node=[^&]*/, `$1node=${encodeURIComponent(node)}`);
    return { node, path, then: o.call?.then || null,
             x: { mod: b.name, node, debug: !!o.debug, slot: o.moment && o.state_slot != null ? o.state_slot : "", option: o, build: b } };
  }

  // ---------------------------------------------------------------- the build rows
  const chip = (text, cls = "") => `<span class="bv-chip${cls ? " " + cls : ""}">${ESC(text)}</span>`;
  function whereHTML(b) {
    return (b.where || []).map(w => `<span class="bv-where-i${w.where === "pc" && w.online === false ? " bv-off" : ""}" title="${ESC(w.label)}">${ESC(w.label)}</span>`).join("");
  }
  function rowHTML(b, st = {}, env = {}) {
    const url = env.url || (u => u), now = env.now;
    const open = st.open?.has?.(b.key), renaming = st.renaming === b.key, d = defaultOption(b);
    const name = renaming
      ? `<input class="bv-rename" data-bv-rename="${ESC(b.key)}" value="${ESC(b.label)}" maxlength="120" aria-label="Build name" placeholder="${ESC(b.original_title || b.name)}" data-nomic>`
      : `<span class="bv-name" data-bv="name" title="Double-click (or ✎) to rename · folder ${ESC(b.name)}">${ESC(b.label || b.name)}</span><button class="bv-ico" type="button" data-bv="rename" title="Rename this build (the folder keeps its name)" aria-label="Rename">✎</button>`;
    const star = `<button class="bv-ico bv-star${b.favorite ? " on" : ""}" type="button" data-bv="fav" aria-pressed="${!!b.favorite}" title="${b.favorite ? "Remove from favorites" : "Add to favorites: listed first, at the top of the game's Special builds, never evicted"}" aria-label="Favorite">${b.favorite ? "★" : "☆"}</button>`;
    const sub = [b.display_name && b.original_title !== b.display_name ? `was “${b.original_title}”` : "", b.summary || ""].filter(Boolean).join(" · ");
    const msg = st.msg?.get?.(b.key);
    return `<div class="bv-row${open ? " open" : ""}${b.local_only ? " bv-local" : ""}${b.favorite ? " bv-fav" : ""}" data-bv-key="${ESC(b.key)}">
      <button class="bv-tri" type="button" data-bv="toggle" aria-expanded="${open}" title="${open ? "Hide" : "Show"} details">${open ? "▾" : "▸"}</button>
      ${b.image ? `<img class="bv-thumb" loading="lazy" decoding="async" alt="" src="${ESC(url(b.image))}">` : `<div class="bv-thumb bv-nothumb">${ESC((b.game_title || b.game_id || "?").slice(0, 2))}</div>`}
      <div class="bv-main"><div class="bv-nm">${star}${name}</div>${BA()?.whatHTML(b.what, { compact: true }) || ""}<div class="bv-sub mut" title="${ESC(sub)}">${ESC(sub)}</div>${msg ? `<div class="bv-msg">${ESC(msg)}</div>` : ""}</div>
      <div class="bv-game" title="${ESC(b.game_id)}">${ESC(b.game_title || b.game_id)}</div>
      <div class="bv-kinds">${(b.kinds || [b.kind]).map((k, i) => chip(KINDS[k] || k, i ? "" : "bv-k1")).join("")}${b.verified ? chip("verified", "bv-ok") : ""}${BA()?.reportedHTML(b.reported, "bv-chip ba-rep") || ""}</div>
      <div class="bv-date" title="${ESC(fmtDate(b.built))}">${ESC(fmtAge(b.built, now))}</div>
      <div class="bv-size">${b.local_only ? '<span class="mut" title="only on a PC: sized when it reaches the Spark">–</span>' : ESC(fmtSize(sizeOf(b)))}</div>
      <div class="bv-where">${whereHTML(b)}</div>
      <div class="bv-launch"><button class="act pri" type="button" data-bv="launch" ${d ? "" : "disabled"} title="${ESC(d ? optLabel(d, env.here) : "no launch option")}">▶ Launch</button><button class="act" type="button" data-bv="opts" aria-haspopup="menu" aria-expanded="${st.opts === b.key}" title="Launch options">▾</button><button class="act" type="button" data-bv="shot" ${b.card_id ? "" : "disabled"} title="${b.card_id ? "Screenshot: this build running now = a frame of it; another build of the game running = you choose; nothing running = launch, then capture" : "No mod card for this build yet: nothing to add a picture to"}" aria-label="Screenshot">📷</button><button class="act bv-act" type="button" data-bv="report" title="Report a problem with this build: it doesn't show the expected change, looks broken, crashes…" aria-label="Report">⚑</button><button class="act bv-act bv-del" type="button" data-bv="delete" title="Delete this build (asks first: everywhere or only this PC)" aria-label="Delete">🗑</button>${st.local ? `<span class="bv-dl">${st.local.iconHTML(b)}</span>` : ""}</div>
    </div>${st.local?.menu === b.key ? `<div class="bv-dlm">${st.local.menuHTML(b)}</div>` : ""}${st.shot?.get?.(b.key) && BS ? `<div class="bv-shot" data-bv-key="${ESC(b.key)}">${BS.choiceHTML(st.shot.get(b.key), "data-bv")}</div>` : ""}${st.opts === b.key ? optionsHTML(b, env.here) : ""}${open ? `<div class="bv-det" data-bv-det="${ESC(b.key)}">${detailsBody(st.details?.get?.(b.key), env)}</div>` : ""}`;
  }
  // ▾ (or a right-click on the row): the launch options, then ✎ Rename…, ★ favorite, restore the original name
  function optionsHTML(b, here) {
    const k = `data-key="${ESC(b.key)}"`;
    return `<div class="bv-opts" role="menu" data-bv-opts="${ESC(b.key)}">${(b.launch_options || []).map(o =>
      `<button class="act" type="button" role="menuitem" data-bv="launchopt" ${k} data-opt="${ESC(o.id)}">▶ ${ESC(optLabel(o, here))}</button>`).join("")
      || '<span class="mut">No way to launch this build here</span>'}<span class="bv-osep"></span>`
      + `<button class="act" type="button" role="menuitem" data-bv="rename" ${k} title="Give this build your own name (the folder keeps its name)">✎ Rename…</button>`
      + `<button class="act" type="button" role="menuitem" data-bv="fav" ${k}>${b.favorite ? "☆ Remove from favorites" : "★ Add to favorites"}</button>`
      + (b.display_name ? `<button class="act" type="button" role="menuitem" data-bv="unname" ${k}>↺ Restore “${ESC(b.original_title || b.name)}”</button>` : "")
      + `<button class="act" type="button" role="menuitem" data-bv="report" ${k}>⚑ Report a problem…</button>`
      + `<button class="act" type="button" role="menuitem" data-bv="delete" ${k}>🗑 Delete…</button>`
      + `</div>`;
  }
  function detailsBody(entry, env) {
    if (!entry || entry.loading) return '<p class="mut">Loading the build\'s details…</p>';
    if (entry.error) return `<p class="bad">${ESC(entry.error)}</p>`;
    return detailsHTML(entry.data, env);
  }

  // ---------------------------------------------------------------- details
  const pre = v => `<pre class="bv-pre">${ESC(typeof v === "string" ? v : JSON.stringify(v, null, 2))}</pre>`;
  const sect = (title, body, n) => `<section class="bv-sec"><h4>${ESC(title)}${n != null ? ` <span class="mut">${n}</span>` : ""}</h4>${body}</section>`;
  function filesHTML(m) {
    const rows = m?.files || [];
    if (!rows.length) return '<p class="mut">No changed files recorded for this build.</p>';
    return `<table class="bv-tbl"><thead><tr><th>File</th><th>Change</th><th>Size</th><th>Base</th><th>What</th></tr></thead><tbody>${rows.map(r =>
      `<tr><td class="bv-path">${ESC(r.path)}</td><td>${chip(r.change || "?", "bv-ch-" + String(r.change || "").replace(/\W+/g, ""))}</td><td>${r.size != null ? ESC(fmtSize(r.size)) : '<span class="mut">?</span>'}</td>`
      + `<td>${r.base_size != null ? ESC(fmtSize(r.base_size)) : '<span class="mut">–</span>'}</td><td>${ESC(r.what || "")}${(r.patches || []).length ? `<div class="mut">${r.patches.length} byte patch${r.patches.length === 1 ? "" : "es"}: ${r.patches.slice(0, 6).map(p => `0x${Number(p.offset).toString(16)} (+${p.length})`).join(", ")}${r.patches.length > 6 ? " …" : ""}</div>` : ""}</td></tr>`).join("")}</tbody></table>`
      + (m.note ? `<p class="mut">${ESC(m.note)}</p>` : "");
  }
  // one 360° viewer placeholder: the turntable manager fills it with a canvas once the GLB loads (on screen only)
  function turntableHTML(id, glb, img, who, name, note, env) {
    const url = env.url || (u => u);
    return `<figure class="bv-tt" data-bv-tt="${ESC(id)}" data-glb="${ESC(glb || "")}" data-img="${ESC(img || "")}" data-state="${glb ? "idle" : "image"}">
      ${img ? `<img class="bv-tt-img" loading="lazy" alt="${ESC(name)}" src="${ESC(url(img))}">` : `<div class="bv-tt-none">no model</div>`}
      <figcaption><small>${ESC(who)}</small><b>${ESC(name || "?")}</b>${note ? `<span class="mut">${ESC(note)}</span>` : ""}</figcaption></figure>`;
  }
  function charactersHTML(d, env) {
    const rows = d.characters || [];
    if (!rows.length) return '<p class="mut">No characters inserted (no slot ← donor record in this build).</p>';
    return rows.map((r, i) => {
      const donor = r.donor || {}, orig = r.original;
      const tid = `${d.key}|${i}`;
      return `<div class="bv-slot"><div class="bv-slot-h"><b>${ESC(r.slot_name || r.slot)}</b> ← <b>${ESC(donor.name || r.donors?.join(", ") || "?")}</b>`
        + (r.status ? ` ${chip(r.status, "bv-s-" + String(r.status).replace(/\W+/g, ""))}` : "")
        + (r.donor_source ? ` <span class="mut">from ${ESC(r.donor_source)}</span>` : "")
        + (r.reason ? ` <span class="mut">${ESC(r.reason)}</span>` : "") + `</div><div class="bv-pair">`
        + turntableHTML(`${tid}|donor`, r.fitted_url, donor.preview_url, "Who they are", donor.name || r.donors?.[0], r.fitted_from || (donor.missing ? "not in the collection" : ""), env)
        + (orig ? turntableHTML(`${tid}|orig`, orig.model_url, orig.preview_url, "Who they're replacing", orig.name, orig.source ? `in ${orig.source}` : "", env)
          : `<figure class="bv-tt bv-tt-empty"><div class="bv-tt-none">?</div><figcaption><small>Who they're replacing</small><b>${ESC(r.slot_name || r.slot)}</b><span class="mut">${ESC(r.original_note || "not in the collection")}</span></figcaption></figure>`)
        + `</div></div>`;
    }).join("");
  }
  function codesHTML(d) {
    const rows = d.codes || [];
    if (!rows.length) return `<p class="mut">${ESC(d.codes_note || "none recorded")}</p>`;
    return `<ul class="bv-codes">${rows.map(c => `<li>${chip(c.type || "code")} <b>${ESC(c.label || c.desc || c.tool || c.name || "")}</b>`
      + (c.codes ? ` <code>${ESC([].concat(c.codes).join("  "))}</code>` : "")
      + (c.address != null ? ` <code>${ESC(c.address)}${c.value != null ? " = " + ESC(c.value) : ""}</code>` : "")
      + (c.offset != null && c.address == null ? ` <code>@${ESC(c.offset)}</code>` : "")
      + (c.source ? ` <span class="mut">(${ESC(c.source)})</span>` : "") + "</li>").join("")}</ul>`;
  }
  function jobsHTML(d) {
    const jobs = d.jobs || [], rc = d.receipts || [];
    if (!jobs.length && !rc.length) return `<p class="mut">No job recorded for this build${d.job_id ? ` (job ${ESC(d.job_id)} is gone from the store)` : ""}.</p>`;
    return `<ul class="bv-jobs">${jobs.map(j => `<li><button class="act bv-link" type="button" data-bv="jobopen" data-jid="${ESC(j.id)}">job ${ESC(j.id)}</button> ${ESC(j.tool)} ${ESC(j.op || "")} · ${chip(j.state || "?", "bv-js-" + ESC(j.state))}${j.finished ? ` · ${ESC(fmtAge(j.finished))}` : ""}${j.error ? ` <span class="mut">${ESC(String(j.error).slice(0, 160))}</span>` : ""}</li>`).join("")}</ul>`
      + rc.map(r => `<div class="bv-rc">receipt ${ESC(r.id)} · ${r.validation_ok ? chip("validated", "bv-ok") : chip("validation failed", "bv-bad")}${(r.problems || []).length ? ` <span class="mut">${ESC(r.problems.join("; "))}</span>` : ""}`
        + `${(r.artifacts || []).map(a => ` <a class="bv-art" target="_blank" rel="noopener" data-bv-art href="${ESC(a.url)}">${ESC(a.name || a.sha256.slice(0, 8))}</a>`).join("")}</div>`).join("");
  }
  function verificationHTML(v) {
    v = v || {};
    const l = v.launches || [];
    return `<p>${v.verified ? chip("verified in game", "bv-ok") : chip(v.text || "unverified in game until launched", "bv-unv")}</p>`
      + (l.length ? `<ul class="bv-launches">${l.map(s => `<li>${ESC(fmtDate(s.started))} on ${ESC(s.node || "?")} · ${ESC(s.state || "")}${s.exit ? ` · <span class="mut">${ESC(s.exit)}</span>` : ""}</li>`).join("")}</ul>`
        : '<p class="mut">Never launched.</p>')
      + (v.last_launch && /failed|cancelled/.test(v.last_launch.state || "") ? `<p class="bad">last launch ${ESC(v.last_launch.state)}: ${ESC(v.last_launch.error || "")}</p>` : "");
  }
  function detailsHTML(d, env = {}) {
    if (!d) return "";
    if (d.local_only) return `<p class="mut">${ESC(d.note || "This build is only on a PC.")}</p>`;
    const m = d.modifications || {};
    const recipe = d.recipe ? pre(d.recipe) + (d.recipe_recorded ? "" : '<p class="mut">Inferred from the marker (built before recipes were recorded).</p>')
      + `<button class="act" type="button" data-bv="rebuild" data-key="${ESC(d.key)}" title="Build it again on the Spark from this recipe (never launches)">⟳ Rebuild</button>`
      : `<p class="mut">${ESC(d.recipe_note || "no recipe")}</p>`;
    const call = d.build_call ? `<p class="mut">The exact call recorded at build time:</p>${pre(d.build_call)}` : "";
    const where = (d.where || []).map(w => w.label).join(", ");
    return (BA()?.whatHTML(d.what) || "") + `<div class="bv-dhead mut">folder <code>${ESC(d.name)}</code> · ${ESC(d.writer || "?")} · built ${ESC(fmtDate(d.built))}${d.built_on ? ` on ${ESC(d.built_on.host || d.built_on.worker_id || d.built_on.os || "?")}` : ""}${where ? ` · lives on ${ESC(where)}` : ""}</div>`
      + sect("Modifications", filesHTML(m), (m.files || []).length)
      + sect("Characters inserted", (d.cast?.source ? `<p class="mut">cast from ${ESC(d.cast.source)}${d.cast.mapping ? ` · mapping ${ESC(d.cast.mapping)}` : ""}${d.cast.seed ? ` · seed ${ESC(d.cast.seed)}` : ""}</p>` : "") + charactersHTML(d, env), (d.characters || []).length)
      + sect("Codes, cheats & hacks", codesHTML(d), (d.codes || []).length)
      + sect("Compile changes", d.compile ? pre(d.compile) : `<p class="mut">${ESC(d.compile_note || "none")}</p>`)
      + sect("Build recipe", recipe + call)
      + sect("Jobs & receipts", jobsHTML(d) + ((d.tickets || []).length ? `<p>${d.tickets.map(t => `request #${ESC(t.number)}${t.title ? " · " + ESC(t.title) : ""}`).join("; ")}</p>` : ""))
      + sect("Verification", verificationHTML(d.verification));
  }

  // ---------------------------------------------------------------- scheduled jobs
  // the job as a flowchart: queued -> claimed -> its stages (fitting events) or progress steps -> write -> verify -> done
  function flowOf(j) {
    j = j || {};
    const st = j.state || "queued", failed = /^(failed|invalid|rejected)$/.test(st), ok = st === "succeeded";
    const N = (id, label, state, sub = "") => ({ id, label, state, sub });
    const nodes = [N("queued", "queued", st === "queued" ? "running" : "done")];
    nodes.push(N("claimed", j.worker ? `claimed · ${j.worker}` : "claimed",
      st === "queued" ? "pending" : (j.phase === "claimed" ? "running" : (j.started || j.progress || j.finished) ? "done" : failed ? "pending" : "done")));
    const stages = j.stages || [], work = stages.filter(s => s.name !== "write");
    if (work.length) for (const s of work) nodes.push(N("stage:" + s.name, s.name, s.state || "pending", s.total ? `${s.done}/${s.total}` : ""));
    else if ((j.steps || []).length) j.steps.forEach((m, i, a) => nodes.push(N("step:" + i, m, i < a.length - 1 ? "done" : (st === "running" || failed) ? "running" : "done")));
    else nodes.push(N("build", j.category_label || "build", ok ? "done" : st === "running" && j.phase !== "claimed" ? "running" : "pending",
      j.progress && st === "running" ? `${Math.round(j.progress.pct || 0)}%` : ""));
    const w = stages.find(s => s.name === "write");
    nodes.push(N("write", "write", w ? w.state : ok ? "done" : "pending", w && w.total ? `${w.done}/${w.total}` : ""));
    nodes.push(N("verify", "verify", ok ? "done" : st === "invalid" ? "failed" : "pending"));
    nodes.push(N("done", j.phase === "cancelled" ? "cancelled" : failed ? "failed" : "done", ok ? "done" : failed ? "failed" : "pending"));
    if (failed) {                                            // where it stopped: the running node, else the first not reached
      nodes.forEach(n => { if (n.state === "running") n.state = "failed"; });
      if (!nodes.slice(0, -1).some(n => n.state === "failed")) {
        const i = nodes.findIndex(n => n.state === "pending");
        if (i >= 0 && i < nodes.length - 1) nodes[i].state = "failed";
      }
    }
    if (ok) nodes.forEach(n => { if (n.state === "pending" || n.state === "running") n.state = "done"; });
    return { nodes, edges: nodes.slice(1).map((n, i) => [nodes[i].id, n.id]), current: nodes.findIndex(n => n.state === "running"), state: st };
  }
  function flowTextHTML(f) {
    return `<ol class="bv-flowtext">${f.nodes.map(n => `<li class="bv-fn bv-fn-${n.state}">${ESC(n.label)}${n.sub ? ` <span class="mut">${ESC(n.sub)}</span>` : ""}</li>`).join("")}</ol>`;
  }
  const EDIT_SKIP = new Set(["op", "session_id", "launch"]);
  function editableFields(input) {
    const scalars = [], json = [];
    for (const [k, v] of Object.entries(input || {})) {
      if (EDIT_SKIP.has(k)) continue;
      if (v !== null && typeof v === "object") json.push([k, v]); else scalars.push([k, v]);
    }
    return { scalars, json };
  }
  function editorHTML(j) {
    const f = editableFields(j.input);
    const jid = ESC(j.id);
    return `<div class="bv-edit" data-bv-edit="${jid}"><p class="mut">Edit the queued job's input. Saving cancels this job and queues the edited one with the same OS / PC / request pinning.</p>
      ${f.scalars.map(([k, v]) => `<label class="bv-ef"><span>${ESC(k)}</span><input data-bv-ef="${ESC(k)}" data-jid="${jid}" data-type="${typeof v}" value="${ESC(v)}"></label>`).join("")}
      ${f.json.map(([k, v]) => `<label class="bv-ef bv-efj"><span>${ESC(k)} <small class="mut">(JSON)</small></span><textarea data-bv-ej="${ESC(k)}" data-jid="${jid}" rows="${Math.min(10, 2 + JSON.stringify(v, null, 1).split("\n").length)}">${ESC(JSON.stringify(v, null, 1))}</textarea></label>`).join("")}
      <div class="bv-ebtn"><button class="act pri" type="button" data-bv="jsave">Save &amp; requeue</button><button class="act" type="button" data-bv="jeditclose">Cancel edit</button><span class="bv-emsg mut"></span></div></div>`;
  }
  // the form's values -> the edited fields (only what changed); throws on bad JSON
  function readEdits(j, fields) {
    const out = {};
    for (const el of fields) {
      const k = el.dataset.bvEf || el.dataset.bvEj, old = (j.input || {})[k];
      let v = el.value;
      if (el.dataset.bvEj) { try { v = JSON.parse(v); } catch (e) { throw new Error(`${k}: not valid JSON (${e.message})`); } }
      else if (el.dataset.type === "number") { if (v.trim() === "" || isNaN(+v)) throw new Error(`${k}: a number`); v = +v; }
      else if (el.dataset.type === "boolean") v = /^(true|1|yes|on)$/i.test(String(v).trim());
      if (JSON.stringify(v) !== JSON.stringify(old)) out[k] = v;
    }
    return out;
  }
  function investigateHTML(x) {
    if (!x || x.loading) return '<div class="bv-inv mut">Loading the job\'s log, receipt and fitting events…</div>';
    if (x.error) return `<div class="bv-inv bad">${ESC(x.error)}</div>`;
    const d = x.data || {};
    const fit = d.fitting_events?.models ? Object.entries(d.fitting_events.models) : [];
    const res = d.result || {};
    return `<div class="bv-inv"><div class="bv-inv-h"><b>Investigate job ${ESC(d.id)}</b> <span class="mut">${ESC(d.tool)} ${ESC(d.op || "")} · ${ESC(d.state)}${d.result_state ? " → " + ESC(d.result_state) : ""}</span>
        <button class="act" type="button" data-bv="jinvclose" title="Close">✕</button></div>
      ${d.error ? `<p class="bad">${ESC(d.error)}</p>` : ""}
      ${res.status || res.message ? `<p>${chip(res.status || "result")} ${ESC(res.message || "")}${res.mod ? ` · mod <code>${ESC(res.mod)}</code>` : ""}</p>` : ""}
      ${(res.report || []).length ? `<ul class="bv-codes">${res.report.map(r => `<li>${ESC(r.slot_name || r.slot)} ← ${ESC(r.donor || r.character || "?")} ${chip(r.status || "?")}${r.reason ? ` <span class="mut">${ESC(r.reason)}</span>` : ""}</li>`).join("")}</ul>` : ""}
      <h4>Log</h4>${d.log_tail ? pre(d.log_tail.split("\n").slice(-60).join("\n")) : (d.progress_log || []).length ? pre(d.progress_log.join("\n")) : '<p class="mut">No log yet (a running job uploads its log when it ends; its progress messages show here meanwhile).</p>'}
      <h4>Receipt</h4>${d.receipt ? `<p>receipt ${ESC(d.receipt.id)} · ${d.receipt.validation_ok ? chip("validated", "bv-ok") : chip("validation failed", "bv-bad")} ${ESC((d.receipt.problems || []).join("; "))}</p>` : '<p class="mut">No receipt yet.</p>'}
      ${(d.artifacts || []).length ? `<h4>Artifacts</h4><p>${d.artifacts.map(a => `<a class="bv-art" target="_blank" rel="noopener" data-bv-art href="${ESC(a.url)}">${ESC(a.name || a.sha256.slice(0, 8))}</a> <span class="mut">${ESC(fmtSize(a.size))}</span>`).join(" · ")}</p>` : ""}
      ${fit.length ? `<h4>Fitting events</h4><table class="bv-tbl"><thead><tr><th>Model</th><th>State</th><th>Stages</th></tr></thead><tbody>${fit.map(([k, m]) =>
        `<tr><td>${ESC(m.label || k)}</td><td>${chip(m.state || "?", "bv-fn-" + ESC(m.state || ""))}</td><td>${Object.entries(m.stages || {}).map(([s, v]) => `<span class="bv-fn-${ESC(v.state)}">${ESC(s)}</span>`).join(" → ")}</td></tr>`).join("")}</tbody></table>` : ""}</div>`;
  }
  function jobHTML(j, st = {}, env = {}) {
    const open = st.jobOpen?.has?.(j.id), pct = j.progress ? Math.max(0, Math.min(100, j.progress.pct || 0)) : (j.state === "succeeded" ? 100 : 0);
    const finished = !["queued", "running"].includes(j.state);
    const where = j.worker || (j.require_worker ? `pinned to ${j.require_worker}` : j.require_os ? `any ${j.require_os} worker` : "any worker");
    const msg = st.jmsg?.get?.(j.id);
    return `<div class="bv-job${finished ? " bv-done" : ""}" data-bv-jid="${ESC(j.id)}">
      <div class="bv-jrow"><button class="bv-tri" type="button" data-bv="jtoggle" aria-expanded="${open}" title="${open ? "Hide" : "Show"} the flowchart">${open ? "▾" : "▸"}</button>
        <span class="bv-state bv-ph-${ESC(j.phase)}">${ESC(j.phase)}</span>
        <div class="bv-jmain"><b>${ESC(j.label)}</b> ${chip(j.category_label || j.category)}${j.edited_from ? ` <span class="mut">edited from ${ESC(j.edited_from)}</span>` : ""}
          <div class="mut bv-jsub">${ESC(where)} · job ${ESC(j.id)} · ${finished ? `finished ${ESC(fmtAge(j.finished, env.now))}` : `queued ${ESC(fmtAge(j.created, env.now))}`}${j.cancel_requested ? " · cancel requested" : ""}</div>
          ${msg ? `<div class="bv-msg">${ESC(msg)}</div>` : ""}</div>
        <div class="bv-jprog"><div class="bv-bar"><i style="width:${pct}%"></i></div><div class="mut">${j.progress ? `${Math.round(pct)}% · ${ESC(j.progress.msg || "")}` : ESC(finished ? (j.error || j.state) : j.phase === "claimed" ? "starting…" : "waiting for a worker")}${j.eta_s != null ? ` · ${ESC(fmtEta(j.eta_s))}` : ""}</div></div>
        <div class="bv-jbtn">${finished ? "" : `<button class="act" type="button" data-bv="jedit" ${j.editable ? "" : 'disabled title="Only a queued job can be edited"'}>Edit</button><button class="act" type="button" data-bv="jcancel">Cancel</button>`}<button class="act" type="button" data-bv="jinv">Investigate</button></div></div>
      ${st.editing === j.id ? editorHTML(j) : ""}
      ${open ? `<div class="bv-flow" data-bv-flow="${ESC(j.id)}"></div>${flowTextHTML(flowOf(j))}` : ""}
      ${st.inv?.has?.(j.id) ? investigateHTML(st.inv.get(j.id)) : ""}</div>`;
  }
  function scheduledHTML(s, st = {}, env = {}) {
    if (!s) return '<p class="mut">Loading scheduled builds…</p>';
    if (s.error) return `<p class="bad">${ESC(s.error)}</p>`;
    const jobs = s.jobs || [], recent = s.recent || [], known = new Set([...jobs, ...recent].map(j => j.id));
    const other = [...(st.inv?.keys?.() || [])].filter(id => !known.has(id));     // a build's older job opened from its details
    return (jobs.length ? jobs.map(j => jobHTML(j, st, env)).join("") : '<p class="mut">No build is queued or running.</p>')
      + (recent.length ? `<h4 class="bv-recent">Recently finished</h4>${recent.map(j => jobHTML(j, st, env)).join("")}` : "")
      + (other.length ? `<h4 class="bv-recent">Investigating</h4>${other.map(id => `<div class="bv-job" data-bv-jid="${ESC(id)}">${investigateHTML(st.inv.get(id))}</div>`).join("")}` : "");
  }

  function retentionHTML(st, node) {
    if (!node || node === 'auto') return '';
    if (!st.retention) return '<p class="mut">Local build limits are unavailable until this PC reconnects to the updated service.</p>';
    const p = st.retention, value = (st.game && p.games?.[st.game]) || p.default || 3;
    const title = st.game ? (st.data?.items?.find(b => b.game_id === st.game)?.game_title || st.game) : 'Default for all games';
    return `<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0;padding:12px;border:1px solid #383b48;border-radius:8px">
      <label>Keep on ${ESC(node)} · ${ESC(title)} <input type="range" data-bv-keep min="1" max="10" step="1" value="${value}" aria-label="Builds to keep on this PC"></label>
      <strong><output data-bv-keep-value>${value}</output> builds</strong>
      <button class="act" type="button" data-bv="retention-save">Apply limit and clean up</button>
      <small class="mut">Keeps newest local builds. Running builds and saves are protected. Spark copies stay available.</small></div>`;
  }
  function toolbarHTML(st, f) {
    const opt = (v, l, sel) => `<option value="${ESC(v)}"${v === sel ? " selected" : ""}>${ESC(l)}</option>`;
    return `<div class="bv-bar"><h2 style="margin:0">Builds</h2>
      <input type="search" data-bv-f="q" placeholder="Search name, game, donor, slot, kind, #request" value="${ESC(st.q)}">
      <select data-bv-f="game">${opt("", "All games", st.game)}${f.games.map(g => opt(g.game_id, `${g.title} (${g.count})`, st.game)).join("")}</select>
      <select data-bv-f="kind">${opt("", "All kinds", st.kind)}${f.kinds.map(k => opt(k.kind, `${k.label} (${k.count})`, st.kind)).join("")}</select>
      <label class="bv-favf" title="Only the builds you starred (★)"><input type="checkbox" data-bv-f="fav"${st.fav ? " checked" : ""}> ★ Favorites${f.favorites ? ` (${f.favorites})` : ""}</label>
      <button class="act" type="button" data-bv="refresh" title="Re-read the build folders">Refresh</button><span class="mut" data-bv-sum></span></div>
      <div data-bv-retention></div>
      <section class="bv-section bv-builds"><h3>Custom builds <span class="mut" data-bv-count></span></h3>
        <div class="bv-head mut" data-bv-head>${sortHeadersHTML(st)}</div>
        <div data-bv-list></div><div data-bv-more></div></section>
      <section class="bv-section"><h3>Scheduled &amp; running <span class="mut" data-bv-scount></span></h3><div data-bv-sched></div></section>`;
  }

  const CSS = `.bv-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px}.bv-bar input[type=search]{flex:1;min-width:180px}
    .bv-section{margin:0 0 18px}.bv-section h3{margin:6px 0;font-size:15px}
    .bv-head,.bv-row{display:grid;grid-template-columns:22px 56px minmax(160px,2.4fr) minmax(90px,1.1fr) minmax(90px,1fr) 80px 72px minmax(90px,1fr) auto;gap:8px;align-items:center}
    .bv-head{font-size:11px;padding:0 6px}.bv-row{padding:6px;border-bottom:1px solid var(--line,#2a2c33)}.bv-row:hover{background:#ffffff08}.bv-row.open{background:#ffffff0c}
    .bv-sort{display:flex;align-items:center;gap:5px;background:none;border:0;padding:6px 0;color:inherit;font:inherit;text-align:left;cursor:pointer}
    .bv-sort span{opacity:.5}.bv-sort:hover,.bv-sort.on{color:var(--accent,#aab3ff)}.bv-sort.on span{opacity:1}.bv-sort:focus-visible{outline:2px solid var(--accent,#aab3ff);outline-offset:2px}
    @media (min-width:901px){.bv-builds{display:grid;grid-template-columns:22px 56px minmax(160px,2.4fr) minmax(90px,1.1fr) minmax(90px,1fr) 80px 72px minmax(90px,1fr) auto;column-gap:8px}
      .bv-builds>*{grid-column:1/-1}.bv-builds>.bv-head,.bv-builds>[data-bv-list],.bv-builds .bv-row{grid-template-columns:subgrid}
      .bv-builds>[data-bv-list]{display:grid}.bv-builds>[data-bv-list]>*{grid-column:1/-1}}
    .bv-tri{background:none;border:0;color:inherit;cursor:pointer;font-size:14px;padding:0}
    .bv-thumb{width:56px;height:42px;object-fit:cover;border-radius:4px;background:#111}.bv-nothumb{display:flex;align-items:center;justify-content:center;color:#777;font-size:12px;text-transform:uppercase}
    .bv-main{min-width:0}.bv-name{font-weight:600;cursor:text;overflow-wrap:anywhere}.bv-rename{width:100%;font:inherit;font-weight:600}
    .bv-nm{display:flex;gap:2px;align-items:flex-start;min-width:0}.bv-ico{background:none;border:0;color:inherit;cursor:pointer;padding:0 3px;font-size:13px;opacity:.6;line-height:1.4}
    .bv-ico:hover{opacity:1}.bv-star{color:#c9a43a;font-size:15px;opacity:.8}.bv-star.on{opacity:1}.bv-row.bv-fav{box-shadow:inset 3px 0 0 #c9a43a}
    .bv-favf{display:flex;gap:4px;align-items:center;font-size:12.5px;white-space:nowrap}.bv-osep{flex-basis:100%;height:0}
    .bv-sub{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bv-msg{font-size:11.5px;color:var(--acc,#7c96ff)}
    .bv-game,.bv-date,.bv-size{font-size:12px}.bv-kinds,.bv-where{display:flex;gap:3px;flex-wrap:wrap}
    .bv-chip,.bv-where-i{font-size:10.5px;border:1px solid var(--line,#444);border-radius:9px;padding:0 6px;white-space:nowrap}
    .bv-k1{border-color:var(--acc,#7c96ff)}.bv-ok{background:#1f6f3f;color:#fff;border-color:#1f6f3f}.bv-bad,.bv-s-failed{background:#7a2b2b;color:#fff;border-color:#7a2b2b}
    .bv-unv{background:#6f5a1f;color:#fff;border-color:#6f5a1f}.bv-s-built{background:#1f6f3f;color:#fff}.bv-off{opacity:.55}
    .bv-launch{display:flex;gap:2px;white-space:nowrap}.bv-opts{display:flex;flex-wrap:wrap;gap:4px;padding:6px 6px 8px 92px;border-bottom:1px solid var(--line,#2a2c33)}
    .bv-det{padding:8px 10px 14px 34px;border-bottom:1px solid var(--line,#2a2c33);background:#ffffff06}.bv-dhead{font-size:12px;margin-bottom:6px}
    .bv-sec h4{margin:10px 0 4px;font-size:13px}.bv-tbl{border-collapse:collapse;font-size:12px;width:100%}.bv-tbl td,.bv-tbl th{border-bottom:1px solid var(--line,#2a2c33);padding:3px 6px;text-align:left;vertical-align:top}
    .bv-path{font-family:monospace;overflow-wrap:anywhere}.bv-pre{max-height:240px;overflow:auto;font-size:11.5px;background:#0006;padding:6px;border-radius:4px;white-space:pre-wrap}
    .bv-slot{margin:6px 0 10px}.bv-pair{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}
    .bv-tt{position:relative;width:170px;margin:0;border:1px solid var(--line,#333);border-radius:6px;overflow:hidden;background:#111}
    .bv-tt>img,.bv-tt>canvas,.bv-tt-none{display:block;width:170px;height:170px;object-fit:contain}.bv-tt>canvas{position:absolute;top:0;left:0}
    .bv-tt[data-state=loaded]>img{visibility:hidden}.bv-tt-none{display:flex;align-items:center;justify-content:center;color:#666;font-size:12px}
    .bv-tt figcaption{position:relative;padding:4px 6px;font-size:11.5px;display:flex;flex-direction:column;background:#000a}.bv-tt figcaption small{color:#9ab}
    .bv-codes,.bv-jobs,.bv-launches{margin:0;padding-left:18px;font-size:12px}.bv-link{padding:0 4px}.bv-art{margin-right:6px}
    .bv-job{border-bottom:1px solid var(--line,#2a2c33);padding:6px}.bv-job.bv-done{opacity:.85}
    .bv-jrow{display:grid;grid-template-columns:22px 72px minmax(180px,2fr) minmax(140px,1.2fr) auto;gap:8px;align-items:center}
    .bv-state{font-size:11px;text-align:center;border-radius:9px;padding:1px 6px;background:#444;color:#fff}.bv-ph-running{background:#1f5f7a}.bv-ph-claimed{background:#3c4f7a}
    .bv-ph-queued{background:#555}.bv-ph-succeeded{background:#1f6f3f}.bv-ph-failed,.bv-ph-invalid,.bv-ph-rejected{background:#7a2b2b}.bv-ph-cancelled{background:#6f5a1f}
    .bv-jsub{font-size:11.5px}.bv-bar{}.bv-jprog{font-size:11.5px;min-width:0}.bv-jprog .mut{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .bv-jprog .bv-bar{display:block;height:6px;background:#ffffff14;border-radius:3px;overflow:hidden;margin:0 0 3px}.bv-jprog .bv-bar i{display:block;height:100%;background:var(--acc,#7c96ff)}
    .bv-jbtn{display:flex;gap:4px;flex-wrap:wrap}.bv-flow{position:relative;height:220px;margin:8px 0 4px;border-radius:8px;overflow:hidden;background:radial-gradient(ellipse at 32% 8%,#263657 0%,#101a2e 43%,#0b1121 100%)}
    .bv-flow canvas{position:absolute;inset:0;width:100%;height:100%}.bv-flab{position:absolute;inset:0;pointer-events:none}
    .bv-flab span{position:absolute;transform:translate(-50%,0);font-size:10.5px;color:#e9f0ff;white-space:nowrap;text-shadow:0 1px 2px #000}
    .bv-flowtext{display:flex;flex-wrap:wrap;gap:4px;list-style:none;padding:0;margin:4px 0;font-size:11px}.bv-flowtext li{border-radius:9px;padding:0 7px;border:1px solid #444}
    .bv-fn-done{border-color:#4fc28b!important;color:#8fe6b8}.bv-fn-running{border-color:#69d6e7!important;color:#9fefff;font-weight:600}.bv-fn-failed{border-color:#ff6b6b!important;color:#ff9b9b}
    .bv-fn-pending{opacity:.6}.bv-fn-skipped{opacity:.6;text-decoration:line-through}
    .bv-edit,.bv-inv{margin:6px 0 4px 30px;padding:8px;border:1px solid var(--line,#333);border-radius:6px;font-size:12px}
    .bv-ef{display:flex;gap:6px;align-items:flex-start;margin:3px 0}.bv-ef span{min-width:110px}.bv-ef input,.bv-ef textarea{flex:1;font:12px monospace}
    .bv-ebtn{display:flex;gap:6px;align-items:center;margin-top:6px}.bv-inv-h{display:flex;gap:6px;align-items:center;justify-content:space-between}.bv-recent{margin:12px 0 4px}
    .bv-shot{padding:2px 6px 8px 92px;border-bottom:1px solid var(--line,#2a2c33)}${BS ? BS.CSS : ""}${BL() ? BL().CSS : ""}
    .bv-dl{display:inline-flex;margin-left:6px;align-self:center}.bv-dlm{display:flex;justify-content:flex-end;padding:4px 6px 8px;border-bottom:1px solid var(--line,#2a2c33)}
    @media (max-width:900px){.bv-head{display:none}.bv-row{grid-template-columns:22px 56px 1fr;grid-auto-rows:auto}.bv-row>.bv-game,.bv-row>.bv-kinds,.bv-row>.bv-date,.bv-row>.bv-size,.bv-row>.bv-where,.bv-row>.bv-launch{grid-column:3}
      .bv-jrow{grid-template-columns:22px 1fr}.bv-jrow>*:nth-child(n+3){grid-column:1/-1}.bv-det{padding-left:8px}.bv-opts{padding-left:8px}.bv-shot{padding-left:8px}}`;

  // ---------------------------------------------------------------- three.js loading (shared, injectable)
  function threeLoader(env) {
    let p = null;
    return () => p || (p = (env.loadThree ? Promise.resolve().then(env.loadThree) : (async () => ({
      THREE: await import(THREE_URL), GLTFLoader: (await import(GLTF_URL)).GLTFLoader }))()).catch(e => { p = null; throw e; }));
  }
  function disposeObject(o) {
    o?.traverse?.(x => {
      x.geometry?.dispose?.();
      for (const m of [].concat(x.material || [])) { for (const k in m) if (m[k] && m[k].isTexture) m[k].dispose?.(); m.dispose?.(); }
    });
  }

  // ---------------------------------------------------------------- 360° turntables
  // One shared WebGL renderer draws every visible viewer and copies the frame into that viewer's own 2D canvas (no
  // per-viewer WebGL context: a whole cast fits). A viewer loads its GLB the first time it is on screen (an
  // IntersectionObserver), only renders while on screen and is disposed when its details close.
  function createTurntables(env = {}) {
    const doc = env.document || root.document, IO = env.IntersectionObserver === undefined ? root.IntersectionObserver : env.IntersectionObserver;
    const raf = env.raf || (f => (root.requestAnimationFrame ? root.requestAnimationFrame(f) : setTimeout(() => f(Date.now()), 33)));
    const caf = env.caf || (id => (root.cancelAnimationFrame ? root.cancelAnimationFrame(id) : clearTimeout(id)));
    const url = env.url || (u => u), three = env.three || threeLoader(env);
    const views = new Map(), byEl = new Map();
    let io = null, T = null, renderer = null, camera = null, frame = 0;
    const stats = { loads: 0, renders: 0, disposed: 0, renderer: 0 };
    function observer() {
      if (io || !IO) return io;
      io = new IO(entries => {
        for (const e of entries) {
          const v = byEl.get(e.target); if (!v) continue;
          v.visible = !!e.isIntersecting;
          if (v.visible) load(v);
        }
        schedule();
      }, { rootMargin: "120px" });
      return io;
    }
    function adopt(container) {
      const seen = new Set();
      for (const el of container?.querySelectorAll?.("[data-bv-tt]") || []) {
        const id = el.dataset.bvTt; if (!id) continue;
        seen.add(id);
        let v = views.get(id);
        if (!v) { v = { id, glb: el.dataset.glb || "", img: el.dataset.img || "", state: el.dataset.glb ? "idle" : "image", visible: false }; views.set(id, v); }
        if (v.el !== el) {
          if (v.el) { byEl.delete(v.el); io?.unobserve?.(v.el); }
          v.el = el; byEl.set(el, v);
          if (v.canvas) { el.appendChild(v.canvas); el.dataset.state = "loaded"; }
          else if (v.state === "failed") el.dataset.state = "failed";
          if (v.glb) { if (observer()) io.observe(el); else { v.visible = true; load(v); } }
        }
      }
      for (const [id, v] of [...views]) if (!seen.has(id)) dispose(v);
      schedule();
    }
    function load(v) {
      if (v.state !== "idle" || !v.glb) return;
      v.state = "loading"; if (v.el) v.el.dataset.state = "loading";
      stats.loads++;
      three().then(mods => {
        if (v.disposed) return;
        T = mods.THREE;
        const manager = T.LoadingManager ? new T.LoadingManager() : undefined;
        manager?.setURLModifier?.(u => /^(data|blob):/.test(u) || /[?&]token=/.test(u) ? u : url(u));
        const loader = new mods.GLTFLoader(manager);
        loader.load(url(v.glb), gltf => {
          if (v.disposed) { disposeObject(gltf.scene); return; }
          const scene = new T.Scene();
          scene.add(new T.HemisphereLight(0xffffff, 0x405070, 2.2));
          const sun = new T.DirectionalLight(0xffffff, 1.8); sun.position.set(3, 5, 4); scene.add(sun);
          const pivot = new T.Group(); pivot.add(gltf.scene); scene.add(pivot);
          const box = new T.Box3().setFromObject(gltf.scene);
          const c = box.getCenter(new T.Vector3()), size = Math.max(box.getSize(new T.Vector3()).length(), 0.1);
          gltf.scene.position.sub(c);
          v.scene = scene; v.pivot = pivot; v.model = gltf.scene; v.size = size;
          v.canvas = doc.createElement("canvas"); v.canvas.width = 170; v.canvas.height = 170;
          v.canvas.className = "bv-tt-canvas"; v.ctx = v.canvas.getContext?.("2d");
          v.el?.appendChild(v.canvas);
          v.state = "loaded"; if (v.el) v.el.dataset.state = "loaded";
          schedule();
        }, undefined, () => { v.state = "failed"; if (v.el) v.el.dataset.state = "failed"; });
      }).catch(() => { v.state = "failed"; if (v.el) v.el.dataset.state = "failed"; });
    }
    function schedule() {
      if (!frame && [...views.values()].some(v => v.state === "loaded" && v.visible)) frame = raf(draw);
    }
    function draw(t) {
      frame = 0;
      const live = [...views.values()].filter(v => v.state === "loaded" && v.visible);
      if (!live.length || !T) return;
      if (!renderer) {
        renderer = new T.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
        renderer.setPixelRatio?.(1); stats.renderer++;
        camera = new T.PerspectiveCamera(35, 1, 0.01, 1000);
      }
      for (const v of live) {
        const w = v.canvas.width, h = v.canvas.height;
        renderer.setSize(w, h, false);
        v.pivot.rotation.y = ((t || 0) * SPIN) % (2 * Math.PI);
        camera.aspect = w / h; camera.near = v.size / 100; camera.far = v.size * 20;
        camera.position.set(0, v.size * 0.12, v.size * 1.35); camera.lookAt?.(0, 0, 0); camera.updateProjectionMatrix?.();
        renderer.render(v.scene, camera);
        if (v.ctx) { v.ctx.clearRect(0, 0, w, h); v.ctx.drawImage(renderer.domElement, 0, 0, w, h); }
        stats.renders++;
      }
      frame = raf(draw);
    }
    function dispose(v) {
      v.disposed = true;
      if (v.el) { io?.unobserve?.(v.el); byEl.delete(v.el); }
      if (v.model) disposeObject(v.model);
      v.canvas?.remove?.();
      views.delete(v.id); stats.disposed++;
      if (!views.size) shutdown();
    }
    function release(prefix) { for (const v of [...views.values()]) if (!prefix || v.id.startsWith(prefix)) dispose(v); }
    function shutdown() {
      if (frame) { caf(frame); frame = 0; }
      renderer?.dispose?.(); renderer = null; camera = null;
      if (!views.size && io) { io.disconnect?.(); io = null; }
    }
    return { adopt, release, dispose: () => { release(""); shutdown(); }, views, stats, draw };
  }

  // ---------------------------------------------------------------- flowcharts (three.js, the Tasks window's task network style)
  function createFlows(env = {}) {
    const doc = env.document || root.document, three = env.three || threeLoader(env);
    const raf = env.raf || (f => (root.requestAnimationFrame ? root.requestAnimationFrame(f) : setTimeout(() => f(Date.now()), 33)));
    const caf = env.caf || (id => (root.cancelAnimationFrame ? root.cancelAnimationFrame(id) : clearTimeout(id)));
    const flows = new Map();
    function make(jid) {
      const f = { jid, canvas: doc.createElement("canvas"), labels: doc.createElement("div"), data: null, sig: "", nodes: [], disposed: false };
      f.labels.className = "bv-flab";
      three().then(mods => {
        if (f.disposed) return;
        const T = mods.THREE;
        f.T = T;
        f.renderer = new T.WebGLRenderer({ canvas: f.canvas, antialias: true, alpha: true });
        f.renderer.setPixelRatio?.(Math.min(root.devicePixelRatio || 1, 1.75));
        f.scene = new T.Scene(); f.camera = new T.PerspectiveCamera(40, 2.5, 0.1, 100); f.camera.position.set(0, 0.6, 9);
        f.scene.add(new T.AmbientLight(0xb8ceff, 1.25));
        const key = new T.PointLight(0x78bfff, 42); key.position.set(-3, 4, 7); f.scene.add(key);
        f.root = new T.Group(); f.scene.add(f.root);
        if (f.data) build(f);
        f.raf = raf(t => tick(f, t));
      }).catch(() => { f.failed = true; });
      return f;
    }
    function clear(f) {
      f.root?.traverse?.(o => { o.geometry?.dispose?.(); for (const m of [].concat(o.material || [])) m.dispose?.(); });
      f.root?.clear?.(); f.nodes = []; f.sparks = [];
      if (f.labels) f.labels.innerHTML = "";
    }
    function build(f) {
      const T = f.T, flow = f.data; if (!T || !flow) return;
      clear(f);
      const n = flow.nodes.length, span = Math.min(10, 1.35 * (n - 1));
      const mat = (c, glow) => new T.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: glow, metalness: 0.38, roughness: 0.26 });
      flow.nodes.forEach((node, i) => {
        const x = n === 1 ? 0 : -span / 2 + span * i / (n - 1), y = Math.sin(i * 1.3) * 0.35, z = (i % 2) * 0.25;
        const color = FLOW_COLORS[node.state] ?? FLOW_COLORS.pending;
        const mesh = new T.Mesh(node.state === "failed" ? new T.OctahedronGeometry(0.3, 0) : new T.SphereGeometry(0.26, 20, 14), mat(color, node.state === "running" ? 0.6 : 0.25));
        mesh.position.set(x, y, z); f.root.add(mesh);
        const halo = new T.Mesh(new T.TorusGeometry(0.42, 0.016, 8, 48), new T.MeshBasicMaterial({ color, transparent: true, opacity: node.state === "running" ? 0.8 : 0.25 }));
        halo.position.set(x, y, z); f.root.add(halo);
        const label = doc.createElement("span"); label.textContent = node.sub ? `${node.label} · ${node.sub}` : node.label;
        label.className = "bv-fn-" + node.state; f.labels.appendChild(label);
        f.nodes.push({ node, mesh, halo, label, x, y, z, i });
        if (i) {
          const a = f.nodes[i - 1];
          const edgeColor = node.state === "failed" ? FLOW_COLORS.failed : a.node.state === "done" ? 0x79a9e9 : 0x3a4560;
          f.root.add(new T.Line(new T.BufferGeometry().setFromPoints([a.mesh.position, mesh.position]),
            new T.LineBasicMaterial({ color: edgeColor, transparent: true, opacity: 0.55 })));
          if (node.state === "running") {                  // a spark travels into the current node
            const s = new T.Mesh(new T.SphereGeometry(0.05, 8, 6), new T.MeshBasicMaterial({ color: 0xbbeeff }));
            f.root.add(s); f.sparks.push({ mesh: s, from: a.mesh, to: mesh });
          }
        }
      });
    }
    function tick(f, t) {
      if (f.disposed) return;
      const w = f.canvas.clientWidth || 600, h = f.canvas.clientHeight || 220;
      if (f.renderer && (f.w !== w || f.h !== h)) { f.renderer.setSize(w, h, false); f.camera.aspect = w / h; f.camera.updateProjectionMatrix?.(); f.w = w; f.h = h; }
      const s = (t || 0) / 1000;
      for (const n of f.nodes) {
        const pulse = n.node.state === "running" ? 1 + Math.sin(s * 4) * 0.18 : 1;
        n.mesh.scale?.setScalar?.(pulse); n.halo.scale?.setScalar?.(n.node.state === "running" ? 1.1 + Math.sin(s * 2.4) * 0.08 : 1);
        n.mesh.rotation.y = s * (n.node.state === "running" ? 0.9 : 0.15);
        if (n.mesh.position.clone && f.camera) {
          const p = n.mesh.position.clone().project(f.camera);
          n.label.style.left = `${(p.x * 0.5 + 0.5) * w}px`; n.label.style.top = `${(-p.y * 0.5 + 0.5) * h + (n.i % 2 ? -34 : 18)}px`;
        }
      }
      for (const sp of f.sparks || []) { const k = (s * 0.6) % 1; sp.mesh.position.copy?.(sp.from.position); sp.mesh.position.lerp?.(sp.to.position, k); }
      f.renderer?.render(f.scene, f.camera);
      f.raf = raf(tt => tick(f, tt));
    }
    function adopt(container, jobs) {
      const seen = new Set();
      for (const el of container?.querySelectorAll?.("[data-bv-flow]") || []) {
        const jid = el.dataset.bvFlow; if (!jid) continue;
        seen.add(jid);
        const f = flows.get(jid) || make(jid); flows.set(jid, f);
        if (f.host !== el) { el.appendChild(f.canvas); el.appendChild(f.labels); f.host = el; }
        const data = flowOf(jobs?.get?.(jid) || {});
        const sig = JSON.stringify(data.nodes);
        f.data = data;
        if (sig !== f.sig) { f.sig = sig; build(f); }
      }
      for (const [jid, f] of [...flows]) if (!seen.has(jid)) dispose(f);
    }
    function dispose(f) {
      f.disposed = true; if (f.raf) caf(f.raf);
      clear(f); f.renderer?.dispose?.(); f.canvas?.remove?.(); f.labels?.remove?.();
      flows.delete(f.jid);
    }
    return { adopt, dispose: () => { for (const f of [...flows.values()]) dispose(f); }, flows };
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ---------------------------------------------------------------- the controller
  // env = { api(path, body?, method?) -> data (throws), url(path) -> loadable URL, here (this PC's worker name),
  //   visible() -> bool, launch?(gid, x) (the shell's launch + loader), confirm?(text) -> bool, toast?(text),
  //   loadThree?() -> {THREE, GLTFLoader}, IntersectionObserver?, document?, raf?, caf?, now? }
  function mount(host, env) {
    const st = { q: env.q || "", game: env.game || "", kind: env.kind || "", fav: !!env.fav, sort: "", direction: "asc", data: null, sched: null, open: new Set(), details: new Map(),
                 renaming: null, opts: null, msg: new Map(), jobOpen: new Set(), inv: new Map(), editing: null, jmsg: new Map(),
                 listSig: "", schedSig: "", page: 1, shot: new Map() };   // shot: row key -> the 📷 choice it offers
    const PAGE = 60;
    const three = threeLoader(env);
    const tts = createTurntables({ ...env, three }), flows = createFlows({ ...env, three });
    const toast = env.toast || (() => {}), wait = env.wait || sleep;
    let timer = null, built = false, listAt = 0, busyRename = false, localAt = 0;
    // the download icon: this PC's copy of each build, downloads / exports from here (viz/build-local.js)
    st.local = BL() ? BL().create(env, { redraw: () => { if (!st.renaming) drawList(); }, note: (b, t) => st.msg.set(b.key, t), toast: t => toast(t) }) : null;
    const part = sel => host.querySelector(sel);
    const fullItems = () => st.data?.items || [];
    const shown = () => filterBuilds(fullItems(), st);
    const find = key => fullItems().find(b => b.key === key);
    const jobs = () => new Map([...(st.sched?.jobs || []), ...(st.sched?.recent || [])].map(j => [j.id, j]));
    const findJob = id => jobs().get(id);
    st.retention = null;
    function drawRetention() {
      const el = part('[data-bv-retention]');
      if (el) el.innerHTML = retentionHTML(st, env.here);
    }
    async function loadRetention() {
      if (!env.here || env.here === 'auto') return;
      try { st.retention = await env.api('/api/build-retention?node=' + encodeURIComponent(env.here)); }
      catch { st.retention = null; }
      drawRetention();
    }
    async function saveRetention() {
      const input = part('[data-bv-keep]');
      if (!input || !st.retention) return;
      const game = st.game, limit = Number(input.value);
      try {
        const result = await env.api('/api/build-retention', { node: env.here, game_id: game, limit }, 'POST');
        st.retention = result; drawRetention();
        toast(result.queued ? `Keeping the newest ${limit} builds. Older local copies will be removed when this PC is ready.` : result.reason);
      } catch (e) { toast('Build limit could not be saved: ' + e.message); }
    }

    function shell() {
      host.innerHTML = `<style>${CSS}${BA()?.WHAT_CSS || ""}.bv-act{padding-left:6px;padding-right:6px}.bv-del:hover{background:#7a2b2b;color:#fff}.bv-main .ba-what{margin:2px 0}</style>` + toolbarHTML(st, facets(fullItems()));
      built = true;
      drawRetention();
    }
    function drawList() {
      if (!built) shell();
      const list = shown(), page = list.slice(0, st.page * PAGE), more = list.length - page.length;
      const el = part("[data-bv-list]");
      if (el) {
        el.innerHTML = page.map(b => rowHTML(b, st, env)).join("") || `<p class="mut">${st.data ? (fullItems().length ? "No build matches these filters." : st.data.indexing ? "Indexing the builds…" : "No custom builds yet.") : "Loading builds…"}</p>`;
        tts.adopt(el);
      }
      const m = part("[data-bv-more]");
      if (m) m.innerHTML = more > 0 ? `<button class="act" type="button" data-bv="more" style="width:100%;margin:8px 0">Show ${Math.min(more, PAGE)} more (${more} not shown)</button>` : "";
      const c = part("[data-bv-count]"); if (c) c.textContent = st.data ? `${list.length} of ${fullItems().length}` : "";
      const s = part("[data-bv-sum]");
      if (s && st.data) s.textContent = st.data.indexing ? "indexing…" : st.data.sizing ? `sizing ${st.data.sizing} folder${st.data.sizing === 1 ? "" : "s"}…` : "";
      if (st.renaming) { const inp = el?.querySelector?.("[data-bv-rename]"); inp?.focus?.(); inp?.select?.(); }
    }
    function drawSched() {
      if (!built) shell();
      const el = part("[data-bv-sched]");
      if (el) { el.innerHTML = scheduledHTML(st.sched, st, env); flows.adopt(el, jobs()); }
      const c = part("[data-bv-scount]");
      if (c) c.textContent = st.sched && !st.sched.error ? `${st.sched.running || 0} running · ${st.sched.queued || 0} queued` : "";
    }
    async function loadList(force = false) {
      let data;
      try { data = await env.api("/api/builds" + (force ? "?fresh=true" : "")); }
      catch (e) { if (!st.data) { const el = part("[data-bv-list]"); if (el) el.innerHTML = `<p class="bad">${ESC(e.message || e)}</p>`; } return st; }
      listAt = Date.now();
      const sig = JSON.stringify([data.items, !!data.indexing, data.sizing || 0]);
      if (sig === st.listSig) return st;
      const refacet = !st.data || JSON.stringify(facets(st.data.items)) !== JSON.stringify(facets(data.items || []));
      st.data = { items: data.items || [], indexing: !!data.indexing, sizing: data.sizing || 0 };
      st.listSig = sig;
      if (st.renaming) return st;                              // never redraw under the operator's typing
      const typing = host.contains?.(root.document?.activeElement) && root.document.activeElement.matches?.("input, select, textarea");
      if (refacet && !typing) built = false;
      if (!built) { shell(); drawSched(); }
      drawList();
      return st;
    }
    async function loadSched() {
      let s;
      try { s = await env.api("/api/builds/scheduled"); } catch (e) { s = { error: "Scheduled builds didn't load: " + (e.message || e) }; }
      for (const [jid, x] of st.inv) if (!x.loading && findJobIn(s, jid)?.state === "running") investigate(jid, true);
      const sig = JSON.stringify(s && { ...s, at: 0 });
      if (sig === st.schedSig) return st;
      st.sched = s; st.schedSig = sig;
      if (st.editing && findJobIn(s, st.editing)) return st;   // the edit form stays as typed
      drawSched();
      return st;
    }
    const findJobIn = (s, id) => [...(s?.jobs || []), ...(s?.recent || [])].find(j => j.id === id);
    async function openDetails(b) {
      st.details.set(b.key, { loading: true });
      drawList();
      try {
        const d = await env.api(`/api/builds/${encodeURIComponent(b.game_id)}/${encodeURIComponent(b.name)}/details`);
        st.details.set(b.key, { data: d });
      } catch (e) { st.details.set(b.key, { error: "Details didn't load: " + (e.message || e) }); }
      if (st.open.has(b.key)) drawList();
    }
    function toggle(b) {
      if (st.open.has(b.key)) { st.open.delete(b.key); tts.release(b.key + "|"); drawList(); return; }
      st.open.add(b.key);
      return openDetails(b);
    }
    async function launch(b, o) {
      if (!b || !o) return;
      const c = launchCall(b, o, env.here);
      st.opts = null; st.msg.set(b.key, `Launching (${optLabel(o, env.here)})…`); drawList();
      try {
        if (env.launch) await env.launch(b.game_id, c.x);
        else await env.api(c.path, {});
        st.msg.set(b.key, `Launched: ${optLabel(o, env.here)}`);
      } catch (e) { st.msg.set(b.key, "⚠ " + (e.message || e)); toast("⚠ " + (e.message || e)); }
      drawList();
    }
    // 📷 (build-shot.js, the Mods gallery's rules): this build running = a frame now; another build of the game running =
    // the row asks (capture from that build / switch to this one, a second click); nothing running = launch, capture
    async function shot(b, choice = "") {
      if (!b || !BS) return;
      const say = t => { st.msg.set(b.key, t); drawList(); };
      try {
        const r = await BS.run({ api: env.api, wait, msg: say, items: fullItems,
          launch: async x => {                               // never a swap of another session of the game
            let j = await env.api("/api/jobs", { tool: "@launch", input: { game_id: x.game_id, mod: x.name, node: env.here || "auto", swap: false } });
            for (let i = 0; i < 900 && j && ["queued", "running"].includes(j.state); i++) { await wait(1000); j = await env.api("/api/jobs/" + j.id); }
            if (!j || j.state !== "succeeded") throw new Error(`launch: ${j?.error || j?.state || "no answer"}`);
          } }, b, { choice, expect: st.shot.get(b.key)?.session_id });
        if (r.choice) { st.shot.set(b.key, r.choice); say(r.stale ? "The running game changed: choose again" : "Another build of this game is running: choose below"); return r; }
        st.shot.delete(b.key);
        say(`📷 Picture added to ${r.into}'s card`); toast(`${r.into}: in-game picture added`);
        st.listSig = ""; await loadList(true);
        return r;
      } catch (e) { say("⚠ " + (e.message || e)); toast("⚠ " + (e.message || e)); }
    }
    async function rename(key, value) {
      const b = find(key); if (!b || busyRename) return;
      st.renaming = null;
      const v = String(value ?? "").trim();
      if (v === (b.display_name || "") || (!b.display_name && v === b.label)) { drawList(); return; }
      busyRename = true;
      try {
        const r = await env.api(buildPath(b), { display_name: v }, "PATCH");
        b.display_name = r.display_name; b.label = r.label;
        const d = st.details.get(key)?.data; if (d) { d.display_name = r.display_name; d.label = r.label; }
        st.msg.set(key, v ? `Renamed (the folder stays ${b.name})` : `Original name restored: ${r.label}`);
        st.listSig = "";
      } catch (e) { st.msg.set(key, "⚠ rename failed: " + (e.message || e)); }
      finally { busyRename = false; }
      drawList();
    }
    // ⚑ Report / 🗑 Delete: the shared dialogs (viz/build-actions.js); env.buildActions replaces them in tests
    const dialogs = () => env.buildActions || BA();
    const dialogEnv = () => ({ document: env.document || root.document, api: env.api, here: env.here && env.here !== "auto" ? env.here : "" });
    async function report(b) {
      drawList();
      const r = await dialogs().open("report", b, dialogEnv());
      if (!r) return null;
      b.reported = { number: r.number, id: r.id };
      st.msg.set(b.key, `⚑ Reported: request #${r.number}`); st.listSig = "";
      drawList(); toast(`${b.label || b.name}: report filed as request #${r.number}`);
      return r;
    }
    async function remove(b) {
      drawList();
      const r = await dialogs().open("delete", b, dialogEnv());
      if (!r) return null;
      const text = dialogs().deleteResultText(b, r);
      if (r.scope === "all" && st.data) { st.data.items = st.data.items.filter(x => x.key !== b.key); st.open.delete(b.key); built = false; shell(); drawSched(); }
      else st.msg.set(b.key, text);
      st.listSig = ""; drawList(); toast(text);
      return r;
    }
    // ★: PUT /api/builds/{game}/{name}/favorite {favorite} (favorites list first, head the game's Special builds)
    async function favorite(b, on = !b.favorite) {
      st.opts = null;
      try {
        await env.api(buildPath(b) + "/favorite", { favorite: on }, "PUT");
        b.favorite = on; st.listSig = "";
        st.msg.set(b.key, on ? "★ Favorite: listed first and kept" : "Removed from favorites");
        built = false;                                         // the toolbar's ★ Favorites count changes
        if (!st.renaming) { shell(); drawSched(); }
      } catch (e) { st.msg.set(b.key, "⚠ " + (e.message || e)); }
      drawList();
      return b;
    }
    async function rebuild(b) {
      const d = st.details.get(b.key)?.data; if (!d?.recipe) return;
      st.msg.set(b.key, "Queueing the rebuild on the Spark…"); drawList();
      try {
        const r = await env.api(`/api/games/${encodeURIComponent(b.game_id)}/special_builds/rebuild`, { recipes: [d.recipe] });
        st.msg.set(b.key, (r.jobs || []).length ? `Rebuild queued: job ${r.jobs.map(j => j.job_id).join(", ")} (see Scheduled & running)` : `Nothing queued: ${(r.skipped || []).map(s => s.reason).join("; ")}`);
        await loadSched();
      } catch (e) { st.msg.set(b.key, "⚠ " + (e.message || e)); }
      drawList();
    }
    async function investigate(jid, refresh = false) {
      if (!refresh) { st.inv.set(jid, { loading: true }); drawSched(); }
      try { st.inv.set(jid, { data: await env.api(`/api/builds/scheduled/${encodeURIComponent(jid)}`) }); }
      catch (e) { st.inv.set(jid, { error: "Investigation didn't load: " + (e.message || e) }); }
      if (!(st.editing && findJob(st.editing))) drawSched();
    }
    async function cancelJob(j) {
      if (env.confirm && !env.confirm(`Cancel ${j.label}?`)) return;
      try {
        const r = await env.api(`/api/jobs/${encodeURIComponent(j.id)}/cancel`, {});
        st.jmsg.set(j.id, r.cancel_requested ? "Cancel requested: it stops at its next progress report" : "Cancelled");
      } catch (e) { st.jmsg.set(j.id, "⚠ " + (e.message || e)); }
      st.schedSig = ""; await loadSched(); drawSched();
    }
    async function saveEdit(j) {
      const el = part("[data-bv-sched]");
      const fields = [...(el?.querySelectorAll?.(`[data-bv-ef][data-jid="${j.id}"], [data-bv-ej][data-jid="${j.id}"]`) || [])];
      let edits;
      try { edits = readEdits(j, fields); } catch (e) { st.jmsg.set(j.id, "⚠ " + e.message); st.editing = null; drawSched(); st.editing = j.id; return; }
      if (!Object.keys(edits).length) { st.editing = null; st.jmsg.set(j.id, "Nothing changed"); drawSched(); return; }
      try {
        const r = await env.api(`/api/builds/scheduled/${encodeURIComponent(j.id)}/edit`, { input: edits });
        st.editing = null;
        st.jmsg.set(r.job.id, `Edited: replaces job ${j.id} (${Object.keys(edits).join(", ")})`);
        if (st.jobOpen.delete(j.id)) st.jobOpen.add(r.job.id);
      } catch (e) { st.jmsg.set(j.id, "⚠ " + (e.message || e)); }
      st.schedSig = ""; await loadSched(); drawSched();
    }

    async function onClick(e) {
      const t = e.target, a = t.closest?.("[data-bv]"), act = a?.dataset?.bv;
      if (t.closest?.("[data-bv-art]")) return;                 // artifact links open as links
      const rowEl = t.closest?.("[data-bv-key]"), b = rowEl && find(rowEl.dataset.bvKey);
      const jobEl = t.closest?.("[data-bv-jid]"), j = jobEl && findJob(jobEl.dataset.bvJid);
      if (st.local && t.closest?.("[data-bl]")) {               // the download icon and its menu (under the row)
        return st.local.onClick(e, b || find(t.closest?.("[data-bl-menu]")?.dataset?.blMenu));
      }
      if (st.local?.menu && !t.closest?.("[data-bl-menu]")) { st.local.menu = null; drawList(); if (!act) return; }
      if (act === "more") { st.page++; drawList(); return; }
      if (act === "sort" && Object.hasOwn(SORTS, a.dataset.sort)) {
        const key = a.dataset.sort;
        st.direction = st.sort === key ? (st.direction === "asc" ? "desc" : "asc") : firstDirection(key);
        st.sort = key; st.page = 1;
        const head = part('[data-bv-head]'); if (head) head.innerHTML = sortHeadersHTML(st);
        drawList();
        part(`[data-sort="${key}"]`)?.focus?.();
        return;
      }
      if (act === "retention-save") return saveRetention();
      if (act === "refresh") { try { await env.api("/api/mods/built/refresh", {}); } catch {} st.listSig = ""; await loadList(true); await loadSched(); return; }
      if (act === "launchopt") { const bb = find(a.dataset.key); return launch(bb, (bb?.launch_options || []).find(o => o.id === a.dataset.opt)); }
      const bk = b || (a?.dataset?.key ? find(a.dataset.key) : null);   // the options row sits under its build's row
      if (bk && act === "rename") { st.opts = null; st.renaming = bk.key; drawList(); return; }
      if (bk && act === "fav") return favorite(bk);
      if (bk && act === "unname") { st.opts = null; return rename(bk.key, ""); }
      if (bk && act === "report") { st.opts = null; return report(bk); }
      if (bk && act === "delete") { st.opts = null; return remove(bk); }
      if (act === "rebuild") { const bb = find(a.dataset.key); if (bb) return rebuild(bb); return; }
      if (act === "jobopen") { const jid = a.dataset.jid; st.jobOpen.add(jid); await investigate(jid); part("[data-bv-sched]")?.scrollIntoView?.({ behavior: "smooth" }); return; }
      if (act === "jinvclose" && jobEl) { st.inv.delete(jobEl.dataset.bvJid); drawSched(); return; }
      if (b) {
        if (act === "toggle") return toggle(b);
        if (act === "launch") return launch(b, defaultOption(b));
        if (act === "opts") { st.opts = st.opts === b.key ? null : b.key; drawList(); return; }
        if (act === "shot") return shot(b);
        if (act === "shot-running" || act === "shot-switch") return shot(b, act === "shot-running" ? "running" : "switch");
        if (act === "shot-cancel") { st.shot.delete(b.key); st.msg.set(b.key, "Nothing changed"); drawList(); return; }
        return;
      }
      if (j) {
        if (act === "jtoggle") { if (st.jobOpen.has(j.id)) st.jobOpen.delete(j.id); else st.jobOpen.add(j.id); drawSched(); return; }
        if (act === "jcancel") return cancelJob(j);
        if (act === "jedit") { if (!j.editable) return; st.editing = st.editing === j.id ? null : j.id; drawSched(); return; }
        if (act === "jeditclose") { st.editing = null; drawSched(); return; }
        if (act === "jsave") return saveEdit(j);
        if (act === "jinv") { if (st.inv.has(j.id)) { st.inv.delete(j.id); drawSched(); return; } return investigate(j.id); }
      }
    }
    function onDblClick(e) {
      const t = e.target, n = t.closest?.('[data-bv="name"]'), rowEl = t.closest?.("[data-bv-key]");
      if (!n || !rowEl) return;
      e.preventDefault?.();
      st.renaming = rowEl.dataset.bvKey; drawList();
    }
    function onKey(e) {
      const inp = e.target?.closest?.("[data-bv-rename]");
      if (!inp) return;
      if (e.key === "Enter") { e.preventDefault?.(); rename(inp.dataset.bvRename, inp.value); }
      else if (e.key === "Escape") { e.preventDefault?.(); st.renaming = null; drawList(); }
    }
    function onFocusOut(e) {
      const inp = e.target?.closest?.("[data-bv-rename]");
      if (inp && st.renaming === inp.dataset.bvRename) rename(inp.dataset.bvRename, inp.value);
    }
    function onInput(e) {
      if (e.target?.hasAttribute?.('data-bv-keep')) {
        const output = part('[data-bv-keep-value]'); if (output) output.textContent = e.target.value;
        return;
      }
      const f = e.target?.dataset?.bvF; if (!f) return;
      st[f] = e.target.type === "checkbox" ? !!e.target.checked : e.target.value; st.page = 1; drawList();
      if (f === 'game') drawRetention();
    }
    // right-click a build: its options (launch options, Rename…, favorite) under the row
    function onContext(e) {
      const menuEl = e.target?.closest?.("[data-bl-menu]");
      if (st.local && menuEl && st.local.onContext(e, find(menuEl.dataset.blMenu))) return;
      const rowEl = e.target?.closest?.("[data-bv-key]"); if (!rowEl || e.target.closest?.("input, textarea")) return;
      if (st.local && st.local.onContext(e, find(rowEl.dataset.bvKey))) { st.opts = null; return; }   // the icon: its own menu
      e.preventDefault?.(); e.stopPropagation?.();
      if (st.local) st.local.menu = null;
      st.opts = rowEl.dataset.bvKey; drawList();
    }
    host.addEventListener("click", onClick);
    host.addEventListener("contextmenu", onContext);
    host.addEventListener("dblclick", onDblClick);
    host.addEventListener("keydown", onKey);
    host.addEventListener("focusout", onFocusOut);
    host.addEventListener("input", onInput);
    host.addEventListener("change", onInput);
    function busy() { return !!(st.data && (st.data.indexing || st.data.sizing)); }
    async function tick() {
      if (env.visible && !env.visible()) { stop(); return; }   // the view was left: free the viewers and the polls
      const tasks = [loadSched()];
      if (Date.now() - listAt >= (busy() ? 5000 : LIST_EVERY)) tasks.push(loadList());
      if (st.local && Date.now() - localAt >= 20000) {          // this PC's copies (its heartbeat) every 20 s
        localAt = Date.now();
        const before = JSON.stringify(st.local.local);
        tasks.push(st.local.refresh().then(() => { if (JSON.stringify(st.local.local) !== before && !st.renaming) drawList(); }));
      }
      await Promise.all(tasks);
    }
    async function start() {
      shell(); drawList(); drawSched();
      localAt = Date.now();
      await Promise.all([loadList(), loadSched(), st.local?.refresh(), loadRetention()]);
      drawList();
      timer = setInterval(tick, env.tick || TICK);
      return ctl;
    }
    function stop() {
      clearInterval(timer);
      for (const [ev, fn] of [["click", onClick], ["contextmenu", onContext], ["dblclick", onDblClick], ["keydown", onKey], ["focusout", onFocusOut], ["input", onInput], ["change", onInput]])
        host.removeEventListener?.(ev, fn);
      tts.dispose(); flows.dispose();
    }
    function focus({ q, game, kind } = {}) { if (q != null) st.q = String(q); if (game != null) st.game = String(game); if (kind != null) st.kind = String(kind); st.page = 1; built = false; drawList(); drawSched(); }
    const ctl = { st, tts, flows, loadList, loadSched, drawList, drawSched, onClick, onContext, onDblClick, onKey, onFocusOut, onInput, tick, stop, focus, shot,
                  toggle, rename, favorite, report, remove, launch, investigate, ready: null, wait };
    ctl.ready = start();
    return ctl;
  }

  const api = { filterBuilds, facets, rowHTML, optionsHTML, detailsHTML, filesHTML, charactersHTML, codesHTML, turntableHTML, jobHTML,
    scheduledHTML, editorHTML, readEdits, editableFields, investigateHTML, flowOf, flowTextHTML, launchCall, optLabel, defaultOption,
    createTurntables, createFlows, mount, retentionHTML, fmtSize, fmtAge, fmtEta, KINDS, TICK, SPIN };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxBuilds = api;
})(typeof window !== "undefined" ? window : globalThis);
