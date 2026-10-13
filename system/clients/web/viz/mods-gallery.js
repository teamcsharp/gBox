// Mods gallery: every modded build the Spark made (GET /api/mods/built: each writer's mod folder in the cache, joined
// with its mod card), newest first, filterable by game and writer, searchable. Each card shows the build's preview
// pictures (in-game shots, the writer's previews, the donors' collection previews) as a carousel - a click opens the
// texture pop-up to zoom - what changed (donor -> slot, the per-slot report of a cast swap), verified / unverified,
// and Play (this PC or a chosen PC, the mod cards' @launch path), Play from saved moment, Open request and Screenshot
// after launch (get_frame of the running game -> the mod card's in-game shots; the rules for a game already running are
// clients/web/viz/build-shot.js: this exact build = capture now, another build = ask, nothing = launch then capture).
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
  const TICK = 5000;                                         // poll tick (ms); a fetch happens only when the read is stale

  function filterMods(items, { game = "", writer = "", q = "" } = {}) {
    const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    const hay = m => [m.name, m.game_id, m.title, m.mod_title, m.original_title, m.writer, ...(m.changes || []).map(r => `${r.donor} ${r.slot}`),
      ...(m.tickets || []).map(t => `#${t.number} ${t.title || ""}`)].join(" ").toLowerCase();
    return (items || []).filter(m => (!game || m.game_id === game) && (!writer || m.writer === writer) && words.every(w => hay(m).includes(w)))
      .sort((a, b) => (b.built || 0) - (a.built || 0));
  }

  function facets(items) {
    const games = new Map(), writers = new Map();
    for (const m of items || []) {
      const g = games.get(m.game_id) || { game_id: m.game_id, title: m.title || m.game_id, count: 0 };
      g.count++; games.set(m.game_id, g);
      writers.set(m.writer, (writers.get(m.writer) || 0) + 1);
    }
    return { games: [...games.values()].sort((a, b) => a.title.localeCompare(b.title)),
             writers: [...writers.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([writer, count]) => ({ writer, count })) };
  }

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

  function cardHTML(m, { url = u => u, idx = 0, now, choice = null } = {}) {
    const imgs = imagesOf(m, url), i = imgs.length ? ((idx % imgs.length) + imgs.length) % imgs.length : 0, cur = imgs[i];
    const lfr = m.launch_report && m.launch_report.number ? m.launch_report : null;
    const tickets = (m.tickets || []).filter(t => !lfr || String(t.number) !== String(lfr.number));
    return `<article class="mg-card" data-key="${ESC(m.key)}">
      <div class="mg-pic">${cur ? `<img class="mg-img" loading="lazy" decoding="async" alt="${ESC(cur.name)}" data-i="${i}" src="${ESC(cur.src)}">
        ${imgs.length > 1 ? `<button class="mg-nav" data-mg="prev" type="button" title="Previous picture">‹</button><button class="mg-nav" data-mg="next" type="button" title="Next picture">›</button>` : ""}
        <span class="mg-count">${cur.kind === "shot" ? "in-game · " : cur.kind === "donor" ? "donor · " : ""}${i + 1} / ${imgs.length}</span>`
        : `<div class="mg-none">No pictures yet: Screenshot after launch adds one</div>`}</div>
      <div class="mg-body">
        <div class="mg-h"><b title="${ESC(m.name)}">${ESC(m.mod_title || m.name)}</b>
          <span class="mg-badge ${m.verified ? "mg-ok" : "mg-unv"}">${m.verified ? "verified" : "unverified"}</span></div>
        <div class="mg-sub"><span class="mg-chip" data-mg-game="${ESC(m.game_id)}">${ESC(m.title || m.game_id)}</span>
          <span class="mg-chip" data-mg-writer="${ESC(m.writer)}">${ESC(m.writer)}</span>${m.cast ? '<span class="mg-chip">cast swap</span>' : ""}</div>
        ${changesHTML(m)}
        <div class="mg-meta mut">${ESC(m.name)} · built ${ESC(fmtAge(m.built, now))} · ${sizeHTML(m)}
          · <span class="mg-launch${m.last_launch && /failed|cancelled/.test(m.last_launch.state) ? " mg-bad" : ""}">${ESC(launchText(m.last_launch, now))}</span></div>
        ${reportHTML(lfr)}
        ${tickets.length ? `<div class="mg-tk">${tickets.map(t => `<button class="act mg-req" type="button" data-mg="request" data-n="${t.number}" title="${ESC(t.title || "Open request #" + t.number)}">Open request #${t.number}${t.status ? " · " + ESC(t.status.replace("_", " ")) : ""}</button>`).join("")}</div>` : ""}
        <div class="mg-btns"><button class="act pri" type="button" data-mg="play">Play</button>
          ${m.state_slot != null && m.card_id ? `<button class="act" type="button" data-mg="moment" title="Launch and load the saved moment (slot ${ESC(m.state_slot)})">Play from saved moment</button>` : ""}
          <button class="act" type="button" data-mg="shot" title="This build running now: capture a frame of it. Another build of the game running: you choose. Nothing running: launch it, then capture. The frame joins this mod's pictures (its thumbnail when it has none)"${m.card_id ? "" : " disabled"}>Screenshot after launch</button>
          <span class="mg-msg mut"></span></div>${choice && BS ? BS.choiceHTML(choice, "data-mg") : ""}</div></article>`;
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
    .mg-lfr{display:flex}.mg-lfr .mg-lf{font-size:12px;font-weight:600;border-radius:9px;padding:2px 9px;color:#fff}.mg-lfr .mg-lf.mg-lf-bad{background:#7a2b2b;border-color:#c0504d}.mg-lfr .mg-lf.mg-lf-ok{background:#1f6f3f;border-color:#2f9a5a}
    ${BS ? BS.CSS : ""}`;

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // the controller: one host element, env = { api(path, body?) -> data (throws), url(path) -> loadable URL,
  //   openImages(list, i, [x, y]), poll (GBoxLivePoll), here (this PC's worker name), visible() -> bool,
  //   play?(mod, {node, moment}), openRequest?(ticket), toast?(text), wait?(ms) }
  function mount(host, env) {
    const st = { q: env.q || "", game: env.game || "", writer: "", node: "", page: 1, idx: new Map(), data: null, nodes: [], sig: "",
                 choice: new Map() };                        // card key -> the screenshot choice it offers (another build runs)
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
      if (grid) grid.innerHTML = page.map(m => cardHTML(m, { url, idx: st.idx.get(m.key) || 0, choice: st.choice.get(m.key) })).join("")
        || `<p class="mut">${st.data ? (st.data.items.length ? "No built mod matches these filters." : st.data.indexing ? "Indexing the built mods…" : "No built mods in the cache yet.") : "Loading built mods…"}</p>`;
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

    async function onClick(e) {
      const t = e.target, card = t.closest?.(".mg-card"), m = card && find(card.dataset.key);
      const act = t.closest?.("[data-mg]")?.dataset.mg;
      if (act === "more") { st.page++; draw(); return; }
      if (act === "refresh") { try { await env.api("/api/mods/built/refresh", {}); } catch {} read.invalidate(); st.sig = ""; await load(0); return; }
      const chipG = t.closest?.("[data-mg-game]"), chipW = t.closest?.("[data-mg-writer]");
      if (chipG || chipW) { if (chipG) st.game = chipG.dataset.mgGame; else st.writer = chipW.dataset.mgWriter; st.page = 1; built = false; draw(); return; }
      if (!m) return;
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
    function onInput(e) {
      const f = e.target?.dataset?.mgF; if (!f) return;
      st[f] = e.target.value; if (f !== "node") { st.page = 1; draw(); }
    }
    host.addEventListener("click", onClick);
    host.addEventListener("input", onInput);
    host.addEventListener("change", onInput);
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
    function stop() { clearInterval(timer); host.removeEventListener?.("click", onClick); host.removeEventListener?.("input", onInput); host.removeEventListener?.("change", onInput); }
    // show one build / request: the game menu's "Open in Mods page" (search + game filter set, the toolbar redrawn)
    function focus({ q, game } = {}) { if (q != null) st.q = String(q); if (game != null) st.game = String(game); st.page = 1; built = false; draw(); }
    const api = { st, load, draw, stop, start, play, screenshot, onClick, onInput, tick, busy, focus, ready: null };
    api.ready = start();
    return api;
  }

  const api = { filterMods, facets, imagesOf, cardHTML, toolbarHTML, changesHTML, requestHTML, fmtSize, fmtAge, launchText, reportText, reportHTML, summaryText, mount, PAGE, TICK };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxModsGallery = api;
})(typeof window !== "undefined" ? window : globalThis);
