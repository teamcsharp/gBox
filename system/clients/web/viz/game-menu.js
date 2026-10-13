// The library's right-click game menu (#gmenu): boot setup (play-as character, boot mod, switches kept on, start slot),
// Play, Models, cover art, "Replace entire cast with…", model collection.
// #1562: it opens in the frame of the right-click from what the client already has. It used to wait for this game's
// mods AND the whole character library (928 KB, 1 s warm and 12 s cold on the Spark's disk; a Spark restart made the
// reads retry for 30 s; a hung read kept it waiting forever) before it drew anything but its title. Now the character
// library is cached (prefetched with the Library, revalidated in the background), each game's mods are cached, and a
// section still waiting on the server says "loading…" and fills in, or says why not with a Retry, when the answer comes.
// Each section is built on its own: one that throws is replaced by a line saying so and the rest (Play) still opens.
// Plain functions + a controller over a tiny DOM surface, so node tests drive it (tests/test_game_menu.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const CHARS_TTL = 30000, MODS_TTL = 15000, PREFETCH_TTL = 300000;   // revalidate in the background when older than this
  const CHARS_TIMEOUT = 60000, MODS_TIMEOUT = 10000;         // a read that never answers turns into "didn't load · Retry"
  const cache = { chars: null, charsAt: 0, charsPending: null, mods: new Map() };   // mods: gid -> { list, at, pending }
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
    const disc = mods.filter(m => isLaunch(m) && !charMods.has(launchOf(m))), patch = mods.filter(m => !isLaunch(m));
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
      ${d.disc.map(m => `<label><input type="radio" name="gmd" value="${ESC(launchOf(m))}" ${b.disc === launchOf(m) ? "checked" : ""}> ${ESC(m.title)}</label>`).join("")}
      ${d.patch.length ? `<div class="mut" style="margin-top:6px">Switched on once the game is running:</div>` +
        d.patch.map(m => `<label><input type="checkbox" data-keep="${ESC(m.id)}" ${kept.includes(m.id) ? "checked" : ""}> ${ESC(m.title)}</label>`).join("") : ""}
      ${loading ? (st.modsErr ? failed("mods", "Mods didn't load: " + st.modsErr) : '<p class="mut" data-gm-loading="mods">loading mods…</p>')
        : !st.mods.length ? '<p class="mut">No mods for this game yet: ask gBox for one while playing.</p>' : ""}</div>`;
    },
    // Special builds: this game's Sonic showcase record (GET /api/showcase/{gid}, gbox/sonic_showcase.py), shown when the
    // client asks for it (io.showcase) and there is one
    special: st => {
      const s = st.showcase, r = s && s.record;
      if (!r) return "";
      const built = s.mod_exists && r.mod;
      const slots = (r.slots_replaced || []).filter(x => /built|partial/.test(x.status || ""));
      const pics = (r.previews || []).filter(p => p.preview).slice(0, 6);
      const missing = (r.missing || []).slice(0, 4);
      const when = r.built_at ? new Date(r.built_at * 1000).toLocaleString() : "";
      return `<div class="gms"><b>Special builds</b>
      <div class="mut" style="font-size:11px">Sonic showcase · ${ESC(String(r.stage || "pending").replace(/_/g, " "))}${r.build_time ? ` · built in ${Math.round(r.build_time)} s` : ""}${when ? ` · ${ESC(when)}` : ""}</div>
      ${built ? `<label><input type="radio" name="gmd" value="${ESC(r.mod)}" ${st.boot.disc === r.mod ? "checked" : ""}> ${ESC(r.mod)} (${slots.length} slot${slots.length === 1 ? "" : "s"} as Sonic characters)</label>` : ""}
      ${slots.length ? `<div class="mut" style="font-size:11px">${slots.slice(0, 8).map(x => `${ESC(x.donor || x.character)} → ${ESC(x.slot_name || x.slot)}`).join(" · ")}${slots.length > 8 ? " …" : ""}</div>` : ""}
      ${pics.length ? `<div class="gmch">${pics.map(p => `<img loading="lazy" alt="${ESC(p.label || p.slot)}" title="${ESC(p.label || p.slot)}" src="${ESC(st.img ? st.img(p.preview) : p.preview)}" style="max-width:64px;max-height:64px">`).join("")}</div>` : ""}
      ${!built && r.message ? `<div class="mut" style="font-size:11px">${ESC(String(r.message).slice(0, 200))}</div>` : ""}
      ${missing.length ? `<ul class="mut" style="font-size:11px;margin:2px 0;padding-left:16px">${missing.map(m => `<li>${ESC(m)}</li>`).join("")}</ul>` : ""}</div>`;
    },
    collect: () => `<div class="gms"><b>Model collection</b>
      <button id="gmcollect" type="button">Extract this game's character models in the background</button>
      <div id="gmcollectstatus" class="mut" style="font-size:11px;margin-top:5px">Runs on Spark; track progress in Tasks. The game does not need to run here.</div></div>`,
    slot: st => `<div class="gms"><b>Start from</b><label>Save state <select id="gmslot"><option value="">the beginning (no state)</option>
      ${[...Array(10).keys()].map(i => `<option value="${i}" ${String(st.boot.slot) === String(i) ? "selected" : ""}>slot ${i}</option>`).join("")}</select></label>
      <div class="mut" style="font-size:11px">F2 saves to the current slot in game; Shift/Ctrl+F2 change the slot.</div></div>`,
    play: st => `<div class="gmb"><button class="act pri" data-go="">▶ Play</button>${st.worker ? '<button class="act" data-go="linux">Play on Spark</button>' : ""}
      <button class="act" data-go="plain" title="Ignore the boot setup this once">Play original</button></div>`,
  };
  const ORDER = ["head", "actions", "chars", "mods", "special", "collect", "slot", "play"];
  const LABEL = { head: "The title", actions: "Models / cover / cast", chars: "Play as", mods: "Boot with a mod", special: "Special builds", collect: "Model collection",
                  slot: "Start from", play: "Play" };
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
    const st = { gid, title, worker: !!io.worker, img: io.img, boot: read(() => io.boot.get(gid), { disc: "", slot: "", character: "" }),
                 kept: read(() => io.keep.get(gid), []), chars: cache.chars, charsErr: null, mods: cachedMods?.list || null, modsErr: null,
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
    const settled = Promise.all([fetchChars(false), fetchMods(false)]);
    if (io.showcase) {                                        // Special builds: never delays or breaks the rest of the menu
      let call; try { call = io.api(`/api/showcase/${encodeURIComponent(gid)}`); } catch (err) { call = Promise.reject(err); }
      deadline(call, MODS_TIMEOUT, "The showcase record").then(s => { st.showcase = s; paint(["special"]); }, () => {});
    }

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
      if (at("[data-cover]")) { io.cover(gid, card, at("[data-cover]")); return; }
      if (at("[data-cast]")) { close(); io.cast(gid, title); return; }
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
    return { el, state: st, settled, paint };
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

  const api = { open, html, section, derive, fit, prefetch, loadChars, loadMods, readyOf, ORDER, SECTIONS,
                _reset() { cache.chars = null; cache.charsAt = 0; cache.charsPending = null; cache.mods.clear(); }, _cache: cache };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxGameMenu = api;
})(typeof window !== "undefined" ? window : globalThis);
