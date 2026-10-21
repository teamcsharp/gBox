// The library's right-click game menu (#gmenu): boot setup (play-as character, boot mod, switches kept on, start slot),
// Play, "🤖 Bot demo on <PC>" for every online PC (io.pcs(), viz/bot-demo.js; data-go="bot:<PC>"), Models, cover art,
// "Replace entire cast with…", model collection.
// #1562: it opens in the frame of the right-click from what the client already has. It used to wait for this game's
// mods AND the whole character library (928 KB, 1 s warm and 12 s cold on the Spark's disk; a Spark restart made the
// reads retry for 30 s; a hung read kept it waiting forever) before it drew anything but its title. Now the character
// library is cached (prefetched with the Library, revalidated in the background), each game's mods are cached, and a
// section still waiting on the server says "loading…" and fills in, or says why not with a Retry, when the answer comes.
// Each section is built on its own: one that throws is replaced by a line saying so and the rest (Play) still opens.
// Plain functions + a controller over a tiny DOM surface, so node tests drive it (tests/test_game_menu.cjs).
// "Special builds ▸/▾" (tests/test_special_builds_menu.cjs): a collapsible section (open / closed remembered per user in
// localStorage) listing the builds made to test or confirm the operator's requests, cast swaps, character swaps and
// the rest (GET /api/games/{id}/special_builds, gbox/special_builds.py). Drawn at once with placeholder rows, filled when
// the answer comes; each build: Quick launch (this PC) + an options submenu (Play on <PC>, saved moment, debugger,
// ✎ Rename… (inline: Enter saves, Esc cancels, empty restores), ★ favorite, Open in Mods page, Open request #n, Rebuild),
// the operator's ★ builds in a Favorites group at the top (#1656), and "Rebuild all confirmation builds" on top (Spark jobs, followed in
// the process pop-up). mountSpecial() puts the same section into another menu (the desktop app's game chip menu).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const CHARS_TTL = 30000, MODS_TTL = 15000, PREFETCH_TTL = 300000;   // revalidate in the background when older than this
  const CHARS_TIMEOUT = 60000, MODS_TIMEOUT = 10000;         // a read that never answers turns into "didn't load · Retry"
  const SPECIAL_TTL = 15000, SPECIAL_TIMEOUT = 10000, SPECIAL_KEY = "gbox_special_builds_open";
  const SPECIAL_GROUPS = [["confirmation", "Confirmation builds"], ["cast", "Cast swaps"], ["character", "Character swaps"], ["other", "Other"]];
  const cache = { chars: null, charsAt: 0, charsPending: null, mods: new Map(), special: new Map() };   // mods / special: gid -> { list, at, pending }
  const now = () => Date.now();

  function deadline(promise, ms, what) {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error(`${what} did not answer in ${Math.round(ms / 1000)} s`)), ms);
      if (t && typeof t.unref === "function") t.unref();
      Promise.resolve(promise).then(v => { clearTimeout(t); resolve(v); }, e => { clearTimeout(t); reject(e); });
    });
  }
  // The whole character library (no game_id: each entry carries its per-game targets, so one read serves every game).
  function loadChars(io, force, ttl = CHARS_TTL) {
    if (cache.charsPending) return cache.charsPending;
    if (!force && cache.chars && now() - cache.charsAt < ttl) return Promise.resolve(cache.chars);
    let call; try { call = io.api("/api/characters"); } catch (err) { call = Promise.reject(err); }
    const p = deadline(call, io.charsTimeout || CHARS_TIMEOUT, "The character library")
      .then(list => { if (!Array.isArray(list)) throw new Error("unexpected answer"); cache.chars = list; cache.charsAt = now(); return list; })
      .finally(() => { if (cache.charsPending === p) cache.charsPending = null; });
    cache.charsPending = p;
    return p;
  }
  function loadMods(io, gid, force) {
    const c = cache.mods.get(gid) || {};
    if (c.pending) return c.pending;
    if (!force && c.list && now() - c.at < MODS_TTL) return Promise.resolve(c.list);
    let call; try { call = io.api(`/api/mods?game_id=${encodeURIComponent(gid)}`); } catch (err) { call = Promise.reject(err); }
    const p = deadline(call, io.modsTimeout || MODS_TIMEOUT, "This game's mods")
      .then(list => { if (!Array.isArray(list)) throw new Error("unexpected answer"); cache.mods.set(gid, { list, at: now() }); return list; })
      .finally(() => { const e = cache.mods.get(gid); if (e && e.pending === p) delete e.pending; });
    cache.mods.set(gid, { ...c, pending: p });
    return p;
  }
  // this game's special builds (the server answers from its built-mods index in memory)
  function loadSpecial(io, gid, force) {
    const c = cache.special.get(gid) || {};
    if (c.pending) return c.pending;
    if (!force && c.list && now() - c.at < SPECIAL_TTL) return Promise.resolve(c.list);
    let call; try { call = io.api(`/api/games/${encodeURIComponent(gid)}/special_builds`); } catch (err) { call = Promise.reject(err); }
    const p = deadline(call, io.specialTimeout || SPECIAL_TIMEOUT, "The special builds")
      .then(r => { if (!r || !Array.isArray(r.groups)) throw new Error("unexpected answer"); cache.special.set(gid, { list: r, at: now() }); return r; })
      .finally(() => { const e = cache.special.get(gid); if (e && e.pending === p) delete e.pending; });
    cache.special.set(gid, { ...c, pending: p });
    return p;
  }
  // open / closed, per user: io.special = { get, set } when the host keeps it, else localStorage (gbox_special_builds_open[:user])
  const specialKey = io => SPECIAL_KEY + (io.user ? ":" + io.user : "");
  function specialOpenGet(io) {
    try {
      if (io.special && io.special.get) return !!io.special.get();
      const s = io.storage || root.localStorage; return !!s && s.getItem(specialKey(io)) === "1";
    } catch { return false; }
  }
  function specialOpenSet(io, on) {
    try {
      if (io.special && io.special.set) return io.special.set(!!on);
      const s = io.storage || root.localStorage; if (s) s.setItem(specialKey(io), on ? "1" : "0");
    } catch {}
  }
  // ---- the "Special builds" section, from st = { gid, special (the answer) | null, specialErr, specialOpen, sbOpts
  //      (the build whose options are open), sbBusy, sbStatus, worker } ----
  const sbBuilds = sp => (sp && Array.isArray(sp.groups) ? sp.groups : []).flatMap(g => Array.isArray(g.builds) ? g.builds : []);
  const sbFind = (st, key) => sbBuilds(st.special).find(b => b.key === key);
  const sbDefault = b => (b.launch_options || []).find(o => o.default) || (b.launch_options || [])[0];
  // a favorited confirmation build sits in Favorites (home: "confirmation"); "Rebuild all" still counts it
  const sbConfirm = sp => sbBuilds(sp).filter(b => b.rebuild_recipe && ((b.home || "") === "confirmation"
    || (!b.home && ((sp.groups || []).find(g => g.key === "confirmation")?.builds || []).includes(b))));
  const buildPath = (b, gid) => `/api/builds/${encodeURIComponent(b.game_id || gid)}/${encodeURIComponent(b.name)}`;
  function sbOptLabel(o, st) {
    if (o.target === "here" && !o.moment && !o.debug) return `Play on this PC${st.worker ? ` (${st.worker})` : ""}`;
    return o.label || o.id;
  }
  function sbOptions(b, st) {
    const btn = (attrs, text, title = "") => `<button class="act" type="button" role="menuitem" ${attrs}${title ? ` title="${ESC(title)}"` : ""} style="display:block;width:100%;text-align:left;margin-top:3px">${text}</button>`;
    const k = `data-key="${ESC(b.key)}"`;
    return `<div class="gm-sbo" role="menu" data-gm-sbo="${ESC(b.key)}" style="margin:4px 0 6px 10px;padding-left:6px;border-left:2px solid var(--line,#444)">` +
      (b.launch_options || []).map(o => btn(`data-gm-sb="launch" ${k} data-opt="${ESC(o.id)}"`, `▶ ${ESC(sbOptLabel(o, st))}`)).join("") +
      btn(`data-gm-sb="rename" ${k}`, "✎ Rename…", "Give this build your own name (the folder keeps its name)") +
      btn(`data-gm-sb="fav" ${k}`, b.favorite ? "☆ Remove from favorites" : "★ Add to favorites", "Favorites head this menu, list first on the Mods page and in Builds, and are never evicted") +
      btn(`data-gm-sb="report" ${k}`, "⚑ Report a problem…", "File a report: it doesn't show the expected change, looks broken, crashes…") +
      btn(`data-gm-sb="delete" ${k}`, "🗑 Delete…", "Delete this build (asks first: everywhere or only this PC)") +
      btn(`data-gm-sb="mods" ${k}`, "Open in Mods page") +
      (b.tickets || []).map(t => btn(`data-gm-sb="request" ${k} data-n="${ESC(t.number)}"`, `Open request #${ESC(t.number)}${t.title ? " · " + ESC(t.title) : ""}`)).join("") +
      (b.rebuild_recipe ? btn(`data-gm-sb="rebuild" ${k}`, "⟳ Rebuild", "Build it again on the Spark from its recipe (never launches)")
        : `<div class="mut" style="font-size:11px;margin-top:3px">No rebuild recipe: ${ESC(b.recipe_missing || "none recorded")}</div>`) + `</div>`;
  }
  // What this changes (one line, its badge) and "Reported #N" (viz/build-actions.js; plain text without it)
  const BA = () => root.GBoxBuildActions || (typeof module === "object" && module.exports ? require("./build-actions.js") : null);
  function sbWhat(b) {
    const w = b.what;
    if (!w) return "";
    const rep = b.reported && b.reported.number ? ` <span class="gm-rep" style="font-size:10.5px;padding:0 5px;border-radius:8px;background:#5a3f8a;color:#fff">Reported #${ESC(b.reported.number)}</span>` : "";
    const line = (w.badge ? `<b style="color:${w.status === "no_changes" ? "#e88" : "#bbb"}">${ESC(w.badge)}</b> ` : "") + ESC((w.lines || [])[0] || "")
      + (w.inferred ? ' <i class="mut">(inferred)</i>' : "");
    return `<div class="gm-what" style="font-size:11px;border-left:2px solid ${w.status === "no_changes" ? "#c0503a" : w.status === "inferred" ? "#c9a43a" : "var(--acc,#7c96ff)"};padding-left:5px;margin:2px 0"
      title="${ESC([...(w.lines || []), w.where ? "Where to look in game: " + w.where : ""].filter(Boolean).join("\n"))}">${line}${rep}${w.where ? `<div class="mut">Where to look: ${ESC(w.where)}</div>` : ""}</div>`;
  }
  function sbRow(b, st) {
    const d = sbDefault(b), open = st.sbOpts === b.key;
    const tickets = (b.tickets || []).map(t => `<span class="mut" title="${ESC(t.title || "")}">#${ESC(t.number)}${t.title ? " " + ESC(t.title) : ""}</span>`).join(" · ");
    const name = st.sbRenaming === b.key
      ? `<input data-gm-sbrename="${ESC(b.key)}" value="${ESC(b.mod_title || b.name)}" maxlength="120" aria-label="Build name" placeholder="${ESC(b.original_title || b.name)}" title="Enter saves · Esc cancels · empty restores the original name" style="flex:1;min-width:0;font:inherit" data-nomic>`
      : `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${ESC(b.display_name && b.original_title ? `${b.mod_title} (was “${b.original_title}”, folder ${b.name})` : b.name)}">${b.favorite ? '<span class="gm-fav" title="Favorite">★</span> ' : ""}${ESC(b.mod_title || b.name)}</span>`;
    return `<div class="gm-sbr" data-gm-sbkey="${ESC(b.key)}" style="margin:3px 0">
      <div style="display:flex;gap:4px;align-items:center">${name}
      <button class="act pri" type="button" data-gm-sb="quick" data-key="${ESC(b.key)}" title="Quick launch: ${ESC(d ? sbOptLabel(d, st) : "")}" ${d ? "" : "disabled"}>▶</button>
      <button class="act" type="button" data-gm-sb="opts" data-key="${ESC(b.key)}" aria-haspopup="menu" aria-expanded="${open}" title="Options">⋯</button></div>
      ${tickets ? `<div style="font-size:11px">${tickets}</div>` : ""}${sbWhat(b)}${b.summary ? `<div class="mut" style="font-size:11px">${ESC(b.summary)}</div>` : ""}
      ${open ? sbOptions(b, st) : ""}</div>`;
  }
  function specialHTML(st) {
    const sp = st.special, open = !!st.specialOpen, total = sp ? (sp.total ?? sbBuilds(sp).length) : null;
    const head = `<button class="act" type="button" data-gm-sb="toggle" aria-expanded="${open}" style="width:100%;text-align:left">Special builds ${open ? "▾" : "▸"}${total != null ? ` <span class="mut">(${total})</span>` : ' <span class="mut" data-gm-loading="special-count">…</span>'}</button>`;
    if (!open) return `<div class="gms gm-sb">${head}</div>`;
    const conf = sbConfirm(sp);
    const top = `<div class="gm-sbtop" style="margin:6px 0"><button class="act" type="button" data-gm-sb="rebuild-all" style="width:100%" ${!sp || !conf.length || st.sbBusy ? "disabled" : ""}
      title="Every confirmation build built again on the Spark from its recipe (never launched); progress in the process pop-up">⟳ Rebuild all confirmation builds${sp ? ` (${conf.length})` : ""}</button>
      <div class="mut" data-gm-sb-status style="font-size:11px">${ESC(st.sbStatus || "")}</div></div>`;
    let body;
    if (!sp) body = st.specialErr ? failed("special", "Special builds didn't load: " + st.specialErr)
      : SPECIAL_GROUPS.map(([k, label]) => `<div class="gm-sbg" data-gm-sbg="${k}"><b style="font-size:12px">${label}</b>
        <div class="mut gm-sbph" data-gm-loading="special" style="font-size:11px">loading…</div></div>`).join("");
    else body = sp.groups.map(g => `<div class="gm-sbg" data-gm-sbg="${ESC(g.key)}"><b style="font-size:12px">${ESC(g.label)}</b> <span class="mut">${(g.builds || []).length}</span>
        ${(g.builds || []).length ? g.builds.map(b => sbRow(b, st)).join("") : '<div class="mut" style="font-size:11px">none</div>'}</div>`).join("");
    return `<div class="gms gm-sb">${head}${top}${body}</div>`;
  }
  // The section's actions, shared by the game menu and mountSpecial: io = { api, launch?(gid, {mod, node, debug, slot,
  // option, build}), openMods?(gid, build), openRequest?(ticket, build), progress?(jobs) (the process pop-up), worker,
  // close? } -> { fetch(force), click(target) -> handled? }
  function specialActions(io, st, repaint, close) {
    const gid = st.gid;
    const fetch = force => loadSpecial(io, gid, force).then(r => { st.special = r; st.specialErr = null; repaint(); },
      err => { st.specialErr = String(err && err.message || err); if (!st.special) repaint(); });
    async function launch(b, o) {
      if (!b || !o) return;
      close();
      const node = o.target === "here" ? (io.worker || "auto") : o.node;
      const x = { mod: b.name, node, debug: !!o.debug, slot: o.moment && o.state_slot != null ? o.state_slot : "", option: o, build: b };
      if (io.launch) return io.launch(gid, x);
      const path = String(o.call?.path || "").replace(/([?&])node=[^&]*/, `$1node=${encodeURIComponent(node)}`);
      return io.api(path, {});
    }
    async function rebuild(body, what) {
      st.sbBusy = true; st.sbStatus = `queueing ${what} on the Spark…`; repaint();
      try {
        const r = await io.api(`/api/games/${encodeURIComponent(gid)}/special_builds/rebuild`, body);
        const jobs = (r && r.jobs) || [], skipped = (r && r.skipped) || [];
        st.sbStatus = (jobs.length ? `✓ ${jobs.length} rebuild${jobs.length === 1 ? "" : "s"} queued on the Spark (${jobs.map(j => j.job_id).join(", ")}): progress in the pop-up`
          : "✗ nothing queued") + (skipped.length ? ` · ${skipped.length} skipped: ${skipped.map(s => s.reason).slice(0, 2).join("; ")}` : "");
        if (jobs.length && io.progress) {
          try { io.progress(jobs.map(j => ({ id: j.job_id, tool: j.tool || "characters", input: j.input || {}, state: j.state || "queued",
                                             progress: { pct: 0, msg: `rebuild ${j.label || j.key}`, ts: Date.now() / 1000 } }))); } catch {}
        }
        return r;
      } catch (err) { st.sbStatus = "✗ " + String(err && err.message || err).slice(0, 160); }
      finally { st.sbBusy = false; repaint(); }
    }
    // ✎ Rename… (the same PATCH as the Builds view and the Mods cards) and ★ favorites: the menu regroups from the server
    const changed = () => { cache.mods.delete(gid); return fetch(true); };
    async function rename(b, value) {
      st.sbRenaming = null;
      const v = String(value ?? "").trim();
      if (!b || v === (b.display_name || "") || (!b.display_name && v === (b.mod_title || b.name))) { repaint(); return; }
      try {
        const r = await io.api(buildPath(b, gid), { display_name: v }, "PATCH");
        b.display_name = r.display_name; b.mod_title = r.label;
        st.sbStatus = v ? `✓ renamed “${r.label}” (the folder stays ${b.name})` : `✓ original name restored: ${r.label}`;
        repaint(); await changed();
      } catch (err) { st.sbStatus = "✗ rename failed: " + String(err && err.message || err).slice(0, 160); repaint(); }
    }
    async function favorite(b) {
      if (!b) return;
      const on = !b.favorite;
      try {
        await io.api(buildPath(b, gid) + "/favorite", { favorite: on }, "PUT");
        b.favorite = on; st.sbOpts = null;
        st.sbStatus = on ? `★ ${b.mod_title || b.name} is a favorite` : `☆ ${b.mod_title || b.name} removed from favorites`;
        repaint(); await changed();
      } catch (err) { st.sbStatus = "✗ " + String(err && err.message || err).slice(0, 160); repaint(); }
    }
    // ⚑ Report / 🗑 Delete: the shared dialogs (viz/build-actions.js; io.buildActions in tests)
    const dialogs = () => io.buildActions || BA();
    const dialogEnv = () => ({ document: io.document || root.document, api: io.api, here: io.worker || "" });
    async function report(b) {
      try {
        const r = await dialogs().open("report", { ...b, game_id: b.game_id || gid }, dialogEnv());
        if (!r) return null;
        b.reported = { number: r.number, id: r.id };
        st.sbStatus = `⚑ ${b.mod_title || b.name}: report filed as request #${r.number}`;
        repaint(); await changed();
        return r;
      } catch (err) { st.sbStatus = "✗ " + String(err && err.message || err).slice(0, 160); repaint(); return null; }
    }
    async function remove(b) {
      try {
        let full = { ...b, game_id: b.game_id || gid };
        try {                                              // where it lives (the Spark, this PC, other PCs) for the dialog
          const got = await io.api(`/api/builds?game_id=${encodeURIComponent(full.game_id)}&q=${encodeURIComponent(b.name)}`);
          const row = ((got && got.items) || []).find(x => x.key === b.key);
          if (row) full = { ...full, where: row.where, size: row.size, own_size: row.own_size, game_title: row.game_title };
        } catch {}
        const r = await dialogs().open("delete", full, dialogEnv());
        if (!r) return null;
        st.sbStatus = "🗑 " + dialogs().deleteResultText(full, r);
        repaint(); await changed();
        return r;
      } catch (err) { st.sbStatus = "✗ " + String(err && err.message || err).slice(0, 160); repaint(); return null; }
    }
    // Enter saves, Esc cancels (the rename field of a Special builds row) -> handled?
    function key(ev) {
      const inp = ev && ev.target && ev.target.closest && ev.target.closest("[data-gm-sbrename]");
      if (!inp) return false;
      if (ev.key === "Enter") { ev.preventDefault && ev.preventDefault(); rename(sbFind(st, inp.dataset.gmSbrename), inp.value); }
      else if (ev.key === "Escape") { ev.preventDefault && ev.preventDefault(); ev.stopPropagation && ev.stopPropagation(); st.sbRenaming = null; repaint(); }
      return true;
    }
    function click(t) {
      const at = s => t && t.closest && t.closest(s);
      if (at("[data-gm-sbrename]")) return true;             // clicks inside the rename field stay in it
      const again = at("[data-gm-retry]");
      if (again && again.dataset.gmRetry === "special") { st.specialErr = null; repaint(); fetch(true); return true; }
      const a = at("[data-gm-sb]"); if (!a) return false;
      const act = a.dataset.gmSb, b = a.dataset.key ? sbFind(st, a.dataset.key) : null;
      if (act === "toggle") { st.specialOpen = !st.specialOpen; specialOpenSet(io, st.specialOpen); repaint(); }
      else if (act === "opts") { st.sbOpts = st.sbOpts === a.dataset.key ? null : a.dataset.key; repaint(); }
      else if (act === "quick") launch(b, b && sbDefault(b));
      else if (act === "launch") launch(b, b && (b.launch_options || []).find(o => o.id === a.dataset.opt));
      else if (act === "rename" && b) {
        st.sbRenaming = b.key; st.sbOpts = null; repaint();
        const scope = st.host || io.el, inp = scope && scope.querySelector && scope.querySelector(`[data-gm-sbrename]`);
        if (inp) { try { inp.focus(); inp.select && inp.select(); } catch {} }
      }
      else if (act === "fav") favorite(b);
      else if ((act === "report" || act === "delete") && b) { st.sbOpts = null; repaint(); (act === "report" ? report : remove)(b); }
      else if (act === "mods") { close(); io.openMods && io.openMods(gid, b); }
      else if (act === "request") { close(); const n = a.dataset.n; io.openRequest && io.openRequest((b?.tickets || []).find(x => String(x.number) === String(n)) || { number: +n }, b); }
      else if (act === "rebuild" && b?.rebuild_recipe) rebuild({ recipes: [b.rebuild_recipe] }, b.mod_title || b.name);
      else if (act === "rebuild-all") rebuild({ recipes: "all", group: "confirmation" }, "every confirmation build");
      return true;
    }
    return { fetch, click, key, launch, rebuild, rename, favorite, report, remove };
  }
  // The section on its own, in another menu (the desktop app's game chip menu): host = an element; io as above
  function mountSpecial(io, host, { gid, title = "" }) {
    const st = { gid, title, worker: io.worker || "", special: cache.special.get(gid)?.list || null, specialErr: null,
                 specialOpen: specialOpenGet(io), sbOpts: null, sbBusy: false, sbStatus: "", sbRenaming: null, host };
    const repaint = () => { try { host.innerHTML = specialHTML(st); } catch (err) { host.innerHTML = `<p class="mut">Special builds could not be shown: ${ESC(String(err && err.message || err).slice(0, 120))}</p>`; }
                            if (io.refit) { try { io.refit(host); } catch {} } };
    const acts = specialActions(io, st, repaint, () => { try { io.close && io.close(); } catch {} });
    repaint();
    host.onclick = ev => { if (acts.click(ev.target)) { ev.stopPropagation && ev.stopPropagation(); } };
    host.onkeydown = ev => { acts.key(ev); };
    const settled = acts.fetch(false);
    return { host, state: st, settled, actions: acts, repaint };
  }
  // Warm the character library while the Library shows, so the first right-click already has it (every library redraw
  // calls this; a copy younger than 5 minutes is kept, opening the menu revalidates after 30 s).
  function prefetch(io) { return loadChars(io, false, PREFETCH_TTL).catch(() => null); }

  // ---- what the menu shows, from the data at hand ----
  const readyOf = (ch, gid) => Array.isArray(ch.ready) ? ch.ready
    : (((ch.targets || {})[gid]) || []).filter(t => t && t.mod && !t.needs_rebuild);
  const readyTarget = (ch, gid) => { const r = readyOf(ch, gid); return r.find(t => (t.slot || "player") === "player") || r[0]; };
  const readyMod = (ch, gid) => readyTarget(ch, gid)?.mod;
  const launchOf = m => ((m.calls || []).find(x => x.tool === "@launch") || {}).input?.mod;
  const isLaunch = m => (m.calls || []).some(x => x.tool === "@launch");
  function derive(st) {
    const b = st.boot, gid = st.gid;
    const chars = Array.isArray(st.chars) ? st.chars : [], mods = Array.isArray(st.mods) ? st.mods : [];
    const ready = chars.filter(ch => readyMod(ch, gid)), other = chars.filter(ch => !readyMod(ch, gid) && !ch.variant_of);
    const charMods = new Set(ready.map(ch => readyMod(ch, gid)));
    const disc = mods.filter(m => isLaunch(m) && !charMods.has(launchOf(m)))          // ★ builds first (stable)
      .map((m, i) => [m, i]).sort((a, b) => (+!!b[0].favorite - +!!a[0].favorite) || a[1] - b[1]).map(x => x[0]);
    const patch = mods.filter(m => !isLaunch(m));
    const selectedChar = ready.find(ch => ch.slug === b.character && readyMod(ch, gid) === b.disc)
      || (!b.character && b.disc ? ready.find(ch => readyMod(ch, gid) === b.disc) : null);
    return { ready, other, disc, patch, selectedChar };
  }
  const EMPTY = { ready: [], other: [], disc: [], patch: [], selectedChar: null };
  const characterNote = (name, slot) => slot && slot !== "player"
    ? `${name} selected: choose ${slot} on the game's character selection screen.` : `${name} selected: every Play of this game uses them.`;
  const retry = what => `<button class="act" type="button" data-gm-retry="${what}" style="margin-left:6px">Retry</button>`;
  const failed = (what, err) => `<p class="mut" data-gm-failed="${what}" style="font-size:11px">✗ ${ESC(String(err).slice(0, 160))}${retry(what)}</p>`;

  function tile(st, d, slug, name, img, mod = "", slot = "") {
    const on = d.selectedChar?.slug === slug || (!slug && !st.boot.disc);
    return `<label title="${ESC(name)}"><input type="radio" name="gmc" value="${ESC(slug)}" data-disc="${ESC(mod)}" data-character-slot="${ESC(slot)}" ${on ? "checked" : ""}>` +
      `${img ? `<img loading="lazy" alt="" src="${ESC(st.img ? st.img(img) : img)}">` : `<span class="nf">🎮</span>`}${ESC(name)}</label>`;
  }
  const SECTIONS = {
    head: st => `<h4>${ESC(st.title)}</h4>`,
    actions: () => `<button class="act" data-models type="button" style="width:100%;margin-bottom:8px">Models · view, assign, export</button>
    <button class="act" data-assets type="button" style="width:100%;margin-bottom:8px">Extract game assets...</button>
    <button class="act" data-cover type="button" style="width:100%;margin-bottom:8px">Attach game cover (online)</button>
    <button class="act" data-cast type="button" style="width:100%;margin-bottom:8px" title="Every character of this game replaced by another game's cast (or a group: Wrestlers…), one mod">Replace entire cast with…</button>`,
    chars: (st, d) => {
      const gid = st.gid, loading = !Array.isArray(st.chars);
      const note = st.note != null ? st.note : d.selectedChar ? characterNote(d.selectedChar.name, readyTarget(d.selectedChar, gid)?.slot) : "";
      return `<div class="gms"><b>Play as (saved: every Play uses it)</b>
      <div class="gmch">${tile(st, d, "", "Original", "")}${d.ready.map(ch => tile(st, d, ch.slug, ch.name, ch.preview_url, readyMod(ch, gid), readyTarget(ch, gid)?.slot)).join("")}</div>
      ${loading ? (st.charsErr ? failed("chars", "Characters didn't load: " + st.charsErr) : '<p class="mut" data-gm-loading="chars" style="font-size:11px">loading characters…</p>')
        : d.other.length ? `<label><select id="gmbuild" ${st.building ? "disabled" : ""}><option value="">+ another character for this game…</option>${d.other.map(ch => `<option value="${ESC(ch.slug)}">${ESC(ch.name)}${ch.source?.game_title ? " · " + ESC(ch.source.game_title) : ""}</option>`).join("")}</select></label>` : ""}
      <div id="gmst" class="mut" style="font-size:11px">${ESC(note)}</div></div>`;
    },
    mods: (st, d) => {
      const b = st.boot, kept = st.kept, loading = !Array.isArray(st.mods);
      const saved = loading && b.disc ? `<label><input type="radio" name="gmd" value="${ESC(b.disc)}" checked> ${ESC(b.disc)}</label>` : "";
      return `<div class="gms"><b>Boot with a mod</b>
      <label><input type="radio" name="gmd" value="" ${!b.disc ? "checked" : ""}> Original game</label>${saved}
      ${d.disc.map(m => `<label><input type="radio" name="gmd" value="${ESC(launchOf(m))}" ${b.disc === launchOf(m) ? "checked" : ""}> ${m.favorite ? "★ " : ""}${ESC(m.display_name || m.title)}</label>`).join("")}
      ${d.patch.length ? `<div class="mut" style="margin-top:6px">Switched on once the game is running:</div>` +
        d.patch.map(m => `<label><input type="checkbox" data-keep="${ESC(m.id)}" ${kept.includes(m.id) ? "checked" : ""}> ${ESC(m.title)}</label>`).join("") : ""}
      ${loading ? (st.modsErr ? failed("mods", "Mods didn't load: " + st.modsErr) : '<p class="mut" data-gm-loading="mods">loading mods…</p>')
        : !st.mods.length ? '<p class="mut">No mods for this game yet: ask gBox for one while playing.</p>' : ""}</div>`;
    },
    special: st => specialHTML(st),
    collect: () => `<div class="gms"><b>Model collection</b>
      <button id="gmcollect" type="button">Extract this game's character models in the background</button>
      <div id="gmcollectstatus" class="mut" style="font-size:11px;margin-top:5px">Runs on Spark; track progress in Tasks. The game does not need to run here.</div></div>`,
    slot: st => `<div class="gms"><b>Start from</b><label>Save state <select id="gmslot"><option value="">the beginning (no state)</option>
      ${[...Array(10).keys()].map(i => `<option value="${i}" ${String(st.boot.slot) === String(i) ? "selected" : ""}>slot ${i}</option>`).join("")}</select></label>
      <div class="mut" style="font-size:11px">F2 saves to the current slot in game; Shift/Ctrl+F2 change the slot.</div></div>`,
    play: st => `<div class="gmb"><button class="act pri" data-go="">▶ Play</button>${st.worker ? '<button class="act" data-go="linux">Play on Spark</button>' : ""}
      <button class="act" data-go="plain" title="Ignore the boot setup this once">Play original</button>
      ${botDemoButtons(st)}</div>`,
  };
  // "🤖 Bot demo on <PC>" for every online PC, the one you are on included (viz/bot-demo.js; io.pcs() gives the PCs).
  // Without the list (a host that passes none): the Spark, as before ("autoplay" = node linux with autoplay on).
  function botDemoButtons(st) {
    const list = Array.isArray(st.pcs) ? st.pcs : null;
    if (!list || !list.length) return `<button class="act" data-go="autoplay" title="The Spark plays this game by itself (your style, its hacks, straight into gameplay) and streams it here">🤖 Bot demo on the Spark</button>`;
    return list.map(p => `<button class="act" data-go="bot:${ESC(p.name)}" title="${ESC(p.name)} plays this game by itself from boot (its playbook, your style, straight into gameplay)${p.here ? "; on this PC the bot waits while you type" : ""}">${ESC(p.label || "🤖 Bot demo on " + p.name)}</button>`).join("");
  }
  const ORDER = ["head", "actions", "chars", "mods", "special", "collect", "slot", "play"];
  const LABEL = { head: "The title", actions: "Models / cover / cast", chars: "Play as", mods: "Boot with a mod", special: "Special builds",
                  collect: "Model collection", slot: "Start from", play: "Play" };
  // one section; a builder that throws becomes a line saying so, never a menu that doesn't open
  function section(name, st, d) {
    let body;
    try { body = SECTIONS[name](st, d); }
    catch (err) {
      (st.errors || (st.errors = [])).push({ section: name, error: String(err && err.message || err) });
      body = `<p class="mut" data-gm-broken="${name}" style="font-size:11px">${ESC(LABEL[name] || name)} could not be shown: ${ESC(String(err && err.message || err).slice(0, 120))}</p>`;
    }
    return `<div data-gm="${name}">${body}</div>`;
  }
  function safeDerive(st) {
    try { return derive(st); }
    catch (err) { (st.errors || (st.errors = [])).push({ section: "data", error: String(err && err.message || err) }); return EMPTY; }
  }
  function html(st) { const d = safeDerive(st); return ORDER.map(n => section(n, st, d)).join(""); }

  // ---- the controller: io = { el, api, img, worker, boot:{get,set}, keep:{get,set}, badge, place, refit, models, cover,
  //      cast, play, sleep } ----
  function open(io, { gid, title = "", card = null, x = 0, y = 0 }) {
    const el = io.el;
    const gen = el._gmGen = (el._gmGen || 0) + 1;            // a newer right-click owns the menu: older answers are dropped
    const current = () => el._gmGen === gen;
    const read = (f, fb) => { try { return f(); } catch { return fb; } };
    const cachedMods = cache.mods.get(gid);
    const st = { gid, title, worker: io.worker || "", img: io.img, pcs: read(() => io.pcs ? io.pcs() : null, null),
                 boot: read(() => io.boot.get(gid), { disc: "", slot: "", character: "" }),
                 kept: read(() => io.keep.get(gid), []), chars: cache.chars, charsErr: null, mods: cachedMods?.list || null, modsErr: null,
                 special: cache.special.get(gid)?.list || null, specialErr: null, specialOpen: specialOpenGet(io), sbOpts: null, sbBusy: false, sbStatus: "",
                 note: null, building: null, errors: [], painted: {} };
    const close = () => el.classList.remove("on");
    const paint = names => {
      if (!current()) return;
      st.boot = read(() => io.boot.get(gid), st.boot); st.kept = read(() => io.keep.get(gid), st.kept);
      const d = safeDerive(st);
      const fresh = {}; for (const n of ORDER) if (!names || names.includes(n)) fresh[n] = section(n, st, d);
      const changed = Object.keys(fresh).filter(n => fresh[n] !== st.painted[n]);
      if (!changed.length) return;
      let whole = !names;
      if (!whole) for (const n of changed) {
        const s = el.querySelector && el.querySelector(`[data-gm="${n}"]`);
        if (s) s.outerHTML = fresh[n]; else { whole = true; break; }
      }
      Object.assign(st.painted, fresh);
      if (whole) { for (const n of ORDER) if (!(n in fresh)) st.painted[n] = section(n, st, d); el.innerHTML = ORDER.map(n => st.painted[n]).join(""); }
      if (names && io.refit) { try { io.refit(el); } catch {} }
    };
    try { paint(); }
    catch (err) {                                             // never preventDefault without a menu: the bare minimum still plays
      el.innerHTML = `<h4>${ESC(title)}</h4><p class="mut">${ESC(String(err && err.message || err).slice(0, 120))}</p>` + SECTIONS.play(st);
    }
    el.classList.add("on");
    try { io.place && io.place(el, x, y); } catch {}

    const save = (disc = st.boot.disc, character = st.boot.character) => {
      const slotEl = el.querySelector && el.querySelector("#gmslot");
      st.boot = { disc, character, slot: slotEl ? slotEl.value : st.boot.slot || "" };
      try { io.boot.set(gid, st.boot); io.badge && io.badge(gid); } catch {}
    };
    const setNote = text => { st.note = text; const n = el.querySelector && el.querySelector("#gmst"); if (n) n.textContent = text; };
    const fetchChars = force => loadChars(io, force).then(list => { st.chars = list; st.charsErr = null; paint(["chars", "mods"]); },
      err => { st.charsErr = String(err && err.message || err); if (!Array.isArray(st.chars)) paint(["chars"]); });
    const fetchMods = force => loadMods(io, gid, force).then(list => { st.mods = list; st.modsErr = null; paint(["mods"]); },
      err => { st.modsErr = String(err && err.message || err); if (!Array.isArray(st.mods)) paint(["mods"]); });
    const special = specialActions(io, st, () => paint(["special"]), close);
    const settled = Promise.all([fetchChars(false), fetchMods(false), special.fetch(false)]);

    el.onchange = async ev => {
      const t = ev.target; if (!current()) return;
      const d = safeDerive(st);
      if (t.dataset && t.dataset.keep) { try { io.keep.set(gid, t.dataset.keep, t.checked); io.badge && io.badge(gid); } catch {} st.kept = read(() => io.keep.get(gid), st.kept); return; }
      if (t.name === "gmc") {
        (el.querySelectorAll ? el.querySelectorAll('input[name="gmd"]') : []).forEach(r => { r.checked = r.value === t.dataset.disc; });
        const ch = d.ready.find(c => c.slug === t.value);
        setNote(t.value ? characterNote(ch?.name || t.closest?.("label")?.textContent || t.value, t.dataset.characterSlot) : "Original game selected.");
        return save(t.dataset.disc, t.value);
      }
      if (t.name === "gmd") {
        (el.querySelectorAll ? el.querySelectorAll('input[name="gmc"]') : []).forEach(r => { r.checked = !r.value && !t.value; });
        setNote(t.value ? "Boot mod selected." : "Original game selected.");
        return save(t.value, "");
      }
      if (t.id === "gmslot") return save();
      if (t.id === "gmbuild" && t.value) {                     // build this character for this game (no launch), then select it
        const ch = d.other.find(x => x.slug === t.value); if (!ch) return;
        t.disabled = true; st.building = ch.slug; setNote(`building ${ch.name} for this game…`);
        try {
          let j = await io.api("/api/jobs", { tool: "characters", input: { op: "use", character: ch.slug, game_id: gid, launch: false }, require_os: "linux" });
          while (/queued|running/.test(j.state)) { await (io.sleep || (ms => new Promise(z => setTimeout(z, ms))))(1200); j = await io.api("/api/jobs/" + j.id); if (j.progress?.msg) setNote(j.progress.msg); }
          const r = j.output?.result || {};
          if (j.state !== "succeeded") throw new Error(j.error || j.state);
          if (!r.mod || /missing|overlay|failed/.test(r.status || "")) { setNote(r.message || `No in-game swap for this game yet${r.request?.number ? ` (request #${r.request.number})` : ""}: while playing, "Use in this game" draws ${ch.name} over the player instead.`); return; }
          const target = { mod: r.mod, slot: r.slot || "player" };          // the cached library learns the new target at once
          ch.targets = { ...(ch.targets || {}), [gid]: [...((ch.targets || {})[gid] || []), target] };
          if (Array.isArray(ch.ready)) ch.ready.push(target);
          save(r.mod, ch.slug); st.note = `✓ ${characterNote(ch.name, target.slot)}`;
        } catch (err) { st.note = "✗ " + String(err && err.message || err).slice(0, 160); }
        finally { st.building = null; paint(["chars", "mods"]); setNote(st.note); }
      }
    };
    el.onclick = async ev => {
      if (!current()) return;
      const at = s => ev.target.closest && ev.target.closest(s);
      if (at("[data-models]")) { close(); io.models(gid, title); return; }
      if (at("[data-assets]")) { close(); if (io.assets) io.assets(gid, title); else io.models(gid, title); return; }
      if (at("[data-cover]")) { io.cover(gid, card, at("[data-cover]")); return; }
      if (at("[data-cast]")) { close(); io.cast(gid, title); return; }
      if (special.click(ev.target)) return;                  // Special builds: toggle, options, launch, rebuild, Retry
      const again = at("[data-gm-retry]");
      if (again) {
        if (again.dataset.gmRetry === "chars") { st.charsErr = null; paint(["chars"]); fetchChars(true); }
        else { st.modsErr = null; paint(["mods"]); fetchMods(true); }
        return;
      }
      const collect = at("#gmcollect");
      if (collect) {
        const status = el.querySelector("#gmcollectstatus");
        collect.disabled = true; if (status) status.textContent = "Submitting extraction task…";
        try {
          const job = await io.api("/api/jobs", { tool: "characters", input: { op: "collect", game_id: gid }, require_os: "linux" });
          if (status) status.textContent = `Task ${job.id} queued on Spark. Open Tasks for progress, logs, and cancellation.`;
        } catch (err) { collect.disabled = false; if (status) status.textContent = `Could not queue extraction: ${err.message}`; }
        return;
      }
      const g = at("[data-go]"); if (!g) return;
      close(); io.play(gid, g.dataset.go);
    };
    el.onkeydown = ev => { if (current()) special.key(ev); };   // Special builds ✎ Rename: Enter saves, Esc cancels
    return { el, state: st, settled, paint, special };
  }

  // Keep a fixed menu inside the window: flip above the pointer when it would run past the bottom, clamp to the edges,
  // scroll inside when taller than the window. Pure: the clients' refitMenu applies it.
  function fit(x, y, w, h, vw, vh, pad = 8, minTop = pad) {
    let maxHeight = null;
    const room = Math.max(40, vh - pad - minTop);
    if (h > room) { h = room; maxHeight = h; }
    const top = y + h > vh - pad ? (y - h >= minTop ? y - h : vh - pad - h) : y;
    return { left: Math.max(pad, Math.min(x, vw - w - pad)), top: Math.max(minTop, top), maxHeight };
  }

  const api = { open, html, section, derive, fit, prefetch, loadChars, loadMods, loadSpecial, specialHTML, mountSpecial,
                specialOpenGet, specialOpenSet, readyOf, ORDER, SECTIONS, SPECIAL_KEY,
                _reset() { cache.chars = null; cache.charsAt = 0; cache.charsPending = null; cache.mods.clear(); cache.special.clear(); }, _cache: cache };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxGameMenu = api;
})(typeof window !== "undefined" ? window : globalThis);
