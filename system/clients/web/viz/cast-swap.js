// "Replace entire cast with..." (gbox/cast_swap.py): right-click a game -> pick a source game or group (Wrestlers,
// Jet Grind Radio, SA2, ...) and a mapping -> the planned assignments (target slot -> donor thumbnail), each editable ->
// build ONE mod (characters op=cast_swap on the Spark) -> the per-slot built / failed report.
// Each plan row carries a "replace" tick (mark that character for replacement in this build; unticked rows are left as
// they are) and the donor chips choose which characters of the source are dealt at random over the ticked rows in one
// go ("Deal ticked donors": seeded, no donor repeats before every ticked donor is used) (#1385).
// Shared by the web client's game menu (#gmenu) and the desktop shell's game chip menu; plain functions + a controller
// that renders HTML strings, so node tests drive it without a DOM (tests/test_cast_swap_menu.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const MAPPINGS = [["auto", "Auto (lead on the player, body size on the rest)"], ["by_role", "By role / body size"],
                    ["random", "Random (seeded)"]];
  const SLOT_SETS = [["all", "Everyone"], ["main", "Main cast only"], ["enemies", "Enemies only"]];

  function sourceOptions(sources, selected = "") {
    if (!sources || !sources.length) return '<option value="">(nothing in the collection yet)</option>';
    const groups = sources.filter(s => s.kind === "group"), games = sources.filter(s => s.kind !== "group");
    const opt = s => `<option value="${ESC(s.key)}"${s.key === selected ? " selected" : ""}>${ESC(s.label)} (${s.count})</option>`;
    return (groups.length ? `<optgroup label="Groups">${groups.map(opt).join("")}</optgroup>` : "") +
      (games.length ? `<optgroup label="Games">${games.map(opt).join("")}</optgroup>` : "");
  }

  // sets: the target's own slot groups from /api/cast_swap/sources (slot_sets: AUF's campaign, bots, bosses ...),
  // else the generic three
  function formHTML(title, sources, sets) {
    const slotSets = sets && sets.length ? sets : SLOT_SETS;
    return `<h4 style="margin:0 0 6px">Replace the entire cast of ${ESC(title)}</h4>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">With <select data-cs="source" style="flex:1;min-width:0">${sourceOptions(sources)}</select></label>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">Mapping <select data-cs="mapping" style="flex:1;min-width:0">${MAPPINGS.map(([v, l]) => `<option value="${v}">${ESC(l)}</option>`).join("")}</select></label>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">Slots <select data-cs="slots" style="flex:1;min-width:0">${slotSets.map(([v, l]) => `<option value="${v}">${ESC(l)}</option>`).join("")}</select>
        Seed <input data-cs="seed" size="6" placeholder="any"></label>
      <div style="display:flex;gap:6px;margin:6px 0"><button class="act" data-cs-go="plan" type="button">Plan the cast</button>
        <button class="act pri" data-cs-go="build" type="button" disabled>Build one mod</button>
        <button class="act pri" data-cs-go="request" type="button" hidden>Request this build</button>
        <button class="act" data-cs-go="close" type="button" style="margin-left:auto">Close</button></div>
      <div data-cs="status" class="mut" style="font-size:12px;white-space:pre-wrap"></div><div data-cs="plan"></div>
      <div data-cs="request"></div><div data-cs="request-detail"></div>`;
  }

  // the plan as rows: target slot -> donor thumbnail + a picker of every eligible donor ("(leave as it is)" drops it)
  function planHTML(plan, img = u => u) {
    const donors = plan.donors || [];
    const pick = (row) => `<select data-cs-slot="${ESC(row.slot)}" style="max-width:150px">${donors.map(d =>
      `<option value="${ESC(d.slug)}"${d.slug === row.character ? " selected" : ""}>${ESC(d.name)}${d.stale ? " (re-extract)" : ""}</option>`).join("")}
      <option value="">(leave as it is)</option></select>`;
    const rows = (plan.assignments || []).map(r => `<tr data-row="${ESC(r.slot)}"><td><input type="checkbox" data-cs-mark="${ESC(r.slot)}" checked title="Replace this character in the build (untick to leave it as it is)"></td><td title="${ESC(r.slot)}">${ESC(r.slot_name || r.slot)}</td>
      <td>${r.preview_url ? `<img alt="" loading="lazy" src="${ESC(img(r.preview_url))}" style="width:34px;height:34px;object-fit:contain">` : ""}</td>
      <td>${pick(r)}<div class="mut" style="font-size:10.5px">${ESC(r.why || "")}</div></td>
      <td><button type="button" class="act" data-cs-rt="${ESC(r.slot)}" title="Retarget editor: how this donor is scaled and proportioned into this slot">✎</button></td></tr>`).join("");
    const skipped = (plan.skipped || []).map(s => `<li>${ESC(s.slot)}: ${ESC(s.reason)}</li>`).join("");
    const refused = (plan.refused || []).map(s => `<li>${ESC(s.name || s.slug)}: ${ESC(s.reason)}</li>`).join("");
    const fresh = (plan.refreshed || []).map(s => `<li>${ESC(s.name || s.slug)}: ${ESC(s.status)}</li>`).join("");
    const chips = donors.map(d => `<label style="display:inline-flex;gap:3px;align-items:center;margin:1px 6px 1px 0"><input type="checkbox" data-cs-donor="${ESC(d.slug)}" checked>${ESC(d.name)}</label>`).join("");
    const bar = (plan.assignments || []).length ? `<div data-cs="marks" style="font-size:12px;margin:4px 0">
        <div>Donors to deal: ${chips}</div>
        <div style="display:flex;gap:6px;margin:4px 0"><button class="act" type="button" data-cs-go="markall">Tick all</button>
          <button class="act" type="button" data-cs-go="marknone">Tick none</button>
          <button class="act" type="button" data-cs-go="deal" title="Deal the ticked donors at random over every ticked row">Deal ticked donors</button>
          <span data-cs="marked" class="mut" style="align-self:center">${(plan.assignments || []).length} of ${(plan.assignments || []).length} marked</span></div></div>` : "";
    return `<div class="mut" style="font-size:12px;margin:4px 0">${ESC(plan.message || "")}${plan.how ? " · " + ESC(plan.how) : ""}</div>
      ${bar}<table data-cs="rows" style="width:100%;font-size:12px;border-collapse:collapse"><tbody>${rows}</tbody></table>
      ${skipped ? `<details><summary>Left as they are (${(plan.skipped || []).length})</summary><ul>${skipped}</ul></details>` : ""}
      ${refused ? `<details><summary>Refused donors (${(plan.refused || []).length})</summary><ul>${refused}</ul></details>` : ""}
      ${fresh ? `<details open><summary>Re-extracted before the build (${(plan.refreshed || []).length})</summary><ul>${fresh}</ul></details>` : ""}`;
  }

  const has = (o, k) => !!o && Object.prototype.hasOwnProperty.call(o, k);
  // a row's donor as reviewed: an unticked row ("leave as it is") is '', otherwise the picker overrides the plan
  const chosen = (r, picks, marks) => (has(marks, r.slot) && !marks[r.slot]) ? "" : has(picks, r.slot) ? picks[r.slot] : r.character;

  // [{slot, character}] for every row the operator changed (a different donor, or unticked)
  function edits(plan, picks, marks) {
    return (plan.assignments || []).map(r => ({ slot: r.slot, character: chosen(r, picks, marks), was: r.character }))
      .filter(e => e.character !== e.was).map(({ slot, character }) => ({ slot, character }));
  }

  // every planned row as reviewed (picks override, unticked rows ''): the build re-plans with the same seed and pins
  // each row, so it builds exactly what was shown even when a donor is re-extracted first
  function reviewed(plan, picks, marks) {
    return (plan.assignments || []).map(r => ({ slot: r.slot, character: chosen(r, picks, marks) }));
  }

  // a small seeded PRNG (mulberry32 over an FNV-1a hash of the seed): the same seed always deals the same cast
  function rng(seed) {
    let h = 2166136261;
    for (const ch of String(seed ?? "")) h = Math.imul(h ^ ch.codePointAt(0), 16777619) >>> 0;
    return () => { h = (h + 0x6D2B79F5) >>> 0; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1);
                   t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }

  // {slot: donor slug} for the ticked slots, dealt from the ticked donors at random: a seeded shuffle, and no donor
  // repeats before every donor has been used once (more slots than donors -> the deck is reshuffled and dealt again)
  function deal(slots, donors, seed = "") {
    const pool = [...new Set((donors || []).filter(Boolean))], out = {};
    if (!pool.length) return out;
    const rand = rng(`${seed}|${pool.join(",")}`);
    let deck = [];
    for (const slot of slots || []) {
      if (!deck.length) {
        deck = pool.slice();
        for (let i = deck.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [deck[i], deck[j]] = [deck[j], deck[i]]; }
      }
      out[slot] = deck.shift();
    }
    return out;
  }

  function reportHTML(res) {
    const rows = (res.report || []).map(r => `<tr><td>${ESC(r.slot_name || r.slot)}</td><td>${ESC(r.donor || "")}</td>
      <td style="color:var(${r.status === "built" ? "--ok" : r.status === "skipped" ? "--mut" : "--bad"})">${ESC(r.status)}</td>
      <td class="mut">${ESC(r.reason || "")}</td></tr>`).join("");
    return `<div style="margin:4px 0;font-size:12px"><b>${ESC(res.status)}</b>${res.mod ? ` · mod <code>${ESC(res.mod)}</code>` : ""} · ${ESC(res.message || "")}</div>
      <table style="width:100%;font-size:12px;border-collapse:collapse"><tbody>${rows}</tbody></table>`;
  }

  function requestHTML(row) {
    const jobs = [...(row.jobs || [])].reverse();
    const job = jobs.find(j => j.state === "running") || jobs.find(j => j.state === "queued") ||
      jobs.find(j => /^(failed|invalid|rejected|succeeded)$/.test(j.state));
    const state = row.build ? "Build available" : job ? job.state : row.status === "done" ? "Build not published"
      : row.dispatch?.mode === "queue" ? "Engineering queued" : row.status || "open";
    const pct = Math.max(0, Math.min(100, Number(job?.progress?.pct) || 0));
    return `<section style="border-top:1px solid var(--line);margin-top:8px;padding-top:8px;font-size:12px">
      <button class="act" type="button" data-cs-go="request-details">Request #${ESC(row.number)} · View details</button>
      <b>${ESC(state)}</b> <button class="act" type="button" data-cs-go="request-refresh">Refresh</button>
      <p>${row.build ? ESC(row.build.title || row.build.name) : "No playable build has been published yet. You can close this window; the request stays saved."}</p>
      ${job ? `<div>${ESC(job.tool || "Task")}: ${ESC(job.state)}</div>` : ""}
      ${job?.progress ? `<progress max="100" value="${pct}"></progress> ${ESC(job.progress.msg)}` : ""}
      ${job?.admission_wait?.reason ? `<p>${ESC(job.admission_wait.reason)}</p>` : ""}
      ${job?.error ? `<p>${ESC(job.error)}</p>` : ""}
      ${row.dispatch?.mode === "queue" ? "<p>Engineering request queued; it has not been confirmed as actively running.</p>" : ""}
      ${row.dispatch_error ? `<p>Saved; dispatch needs attention: ${ESC(row.dispatch_error)}</p>` : ""}
    </section>`;
  }

  function requestDetailsHTML(row) {
    return `<details open style="font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere"><summary>Request #${ESC(row.number)}</summary>
      <p>${ESC(row.body || row.description)}</p>${(row.messages || []).slice(-6).map(m => `<p><b>${ESC(m.author)}</b>: ${ESC(m.text)}</p>`).join("")}</details>`;
  }

  function uuid() {
    const b = new Uint8Array(16); root.crypto.getRandomValues(b); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    const h = [...b].map(v => v.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }

  // Only an equivalent pending whole-cast request can be reused. Photo mappings, other donor pools and reviewed
  // per-slot assignments are different requests even when their titles mention the same game.
  function samePendingCast(row, form) {
    const m = row.mapping || {};
    return /^(open|in_progress|blocked)$/.test(row.status || "") && row.kind === "build" && !row.photo && !row.base_mod &&
      (!row.projection_scope || row.projection_scope === "gameplay") &&
      (form.slots || "all") === "all" && /\b(?:entire cast|whole cast|every character)\b/i.test(row.description || "") &&
      !/\b(?:faces?|selfies?|photos?|photographs?)\b/i.test(row.description || "") &&
      Object.keys(m).every(k => ["source", "source_label", "mapping", "slots", "seed", "assignments"].includes(k)) &&
      m.source === form.source && (m.mapping || "auto") === (form.mapping || "auto") &&
      (m.slots || "all") === "all" && (m.seed || "") === (form.seed || "") && !(m.assignments || []).length;
  }

  // io: api(path, body?) -> data (throws on error), render(part, html), status(text), enable(name, on), img(url),
  //     delay(ms), onBuilt(result)
  function controller(io, game) {
    const wait = io.delay || (ms => new Promise(r => setTimeout(r, ms)));
    const st = { plan: null, form: null, sources: [], requestAllowed: false, request: null, pendingRequest: null };
    let intents = [];
    const storageKey = `gbox_cast_build_requests_${game.gid}`;
    const storage = () => io.storage || root.sessionStorage;
    try { const saved = JSON.parse(storage()?.getItem(storageKey) || "[]"); if (Array.isArray(saved)) intents = saved; } catch {}
    const allowRequest = on => { st.requestAllowed = on; io.requestable?.(on); io.enable("request", on); };
    async function sources() {
      io.status("Loading the collection…");
      const r = await io.api(`/api/cast_swap/sources?game_id=${encodeURIComponent(game.gid)}`);
      st.sources = r.sources || [];
      io.render("form", formHTML(game.title, r.sources || [], r.slot_sets));
      const unsupported = Array.isArray(r.slots) && !r.slots.length;
      allowRequest(unsupported && !!r.sources?.length);
      io.status(unsupported && r.sources?.length ? "No native character slots are available yet. Choose the donors, then Request this build to research and implement the replacement."
        : r.sources?.length ? `${(r.slots || []).length || "The"} replaceable slots; pick who replaces them.`
        : "Nothing in the collection to cast yet: extract a game's characters first.");
      return r;
    }
    async function plan(form, assignments = []) {
      st.form = form; io.enable("build", false); io.status("Planning…");
      const p = await io.api("/api/cast_swap/plan", { game_id: game.gid, source: form.source, mapping: form.mapping,
                                                      seed: form.seed || "", slots: form.slots || "all", assignments });
      st.plan = p;
      allowRequest(["unsupported", "unsupported_cast"].includes(p.status));
      io.render("plan", p.assignments?.length ? planHTML(p, io.img || (u => u)) : "");
      io.status(p.assignments?.length ? `${p.assignments.length} slots planned. Change any donor, then build.` : (p.message || p.status));
      io.enable("build", !!p.assignments?.length);
      return p;
    }
    function request(form) {
      if (st.pendingRequest) return st.pendingRequest;
      if (!st.requestAllowed) return Promise.reject(new Error("Plan the supported cast and review its assignments before building."));
      if (!form.source) return Promise.reject(new Error("Choose the source characters first."));
      const source = st.sources.find(s => s.key === form.source), label = source?.label || form.source;
      const scope = form.slots || "all", mapping = form.mapping || "auto", seed = form.seed || "";
      const body = { kind: "build", recipe: "agent", session_id: game.session_id || "",
        description: `${scope === "all" ? "Replace the entire cast" : `Replace the ${scope} characters`} of ${game.title} with ${label}. ` +
          `Use the extracted donor source ${form.source}, mapping ${mapping}${seed ? `, seed ${seed}` : ""}. ` +
          "Implement and test any missing native reader and combined character writer; do not substitute an overlay or a single-player replacement. Publish one playable mod build after separate gameplay verification.",
        mapping: { source: form.source, source_label: label, mapping, slots: scope, seed } };
      const signature = JSON.stringify(body);
      let intent = intents.find(i => i.signature === signature);
      if (!intent) {
        intent = { signature, clientId: (io.uuid || uuid)() }; intents = [...intents.slice(-19), intent];
        try { storage()?.setItem(storageKey, JSON.stringify(intents)); } catch {}
      }
      io.enable("request", false); io.status("Checking and saving the build request…");
      const path = `/api/games/${encodeURIComponent(game.gid)}/build-requests`;
      st.pendingRequest = (async () => {
        const existing = await io.api(path);
        const previous = (existing.items || []).find(r => samePendingCast(r, form));
        const row = previous || await io.api(path, { ...body, client_id: intent.clientId });
        st.request = row; io.render("request", requestHTML(row)); io.render("request-detail", "");
        io.status(`Request #${row.number} ${previous ? "already saved" : "saved"}. ${row.dispatch_error ? "Dispatch needs attention; your request is retained." : "Follow its progress below. No playable build is being claimed yet."}`);
        return row;
      })().catch(error => { io.status(`Request could not be confirmed: ${error.message}. Retry uses the same request ID.`); throw error; })
        .finally(() => { st.pendingRequest = null; io.enable("request", st.requestAllowed); });
      return st.pendingRequest;
    }
    async function refreshRequest(details = false) {
      if (!st.request) return null;
      const id = st.request.id;
      if (details) {
        const row = await io.api(`/api/requests/${encodeURIComponent(id)}`);
        if (st.request?.id === id) io.render("request-detail", requestDetailsHTML(row)); return row;
      }
      const res = await io.api(`/api/games/${encodeURIComponent(game.gid)}/build-requests`);
      const row = (res.items || []).find(r => r.id === id);
      if (row && st.request?.id === id) { st.request = row; io.render("request", requestHTML(row)); }
      return row || null;
    }
    async function build(picks, marks) {
      if (!st.plan) throw new Error("plan first");
      const f = st.form, changed = edits(st.plan, picks, marks).length, rows = reviewed(st.plan, picks, marks);
      if (!rows.some(r => r.character)) { io.status("Tick at least one character to replace."); return null; }
      io.enable("build", false); io.status(`Queued on the Spark${changed ? ` (${changed} rows changed by you)` : ""}…`);
      let j = await io.api("/api/jobs", { tool: "characters", require_os: "linux", input: { op: "cast_swap",
        target_game: game.gid, source: f.source, mapping: f.mapping, seed: f.seed || "", slots: f.slots || "all",
        assignments: rows, launch: false } });
      while (/queued|running/.test(j.state)) {
        await wait(1500);
        j = await io.api("/api/jobs/" + j.id);
        if (j.progress?.msg) io.status(j.progress.msg);
      }
      if (j.state !== "succeeded") { io.status("✗ " + (j.error || j.state)); io.enable("build", true); return j; }
      const res = j.output?.result || {};
      io.render("plan", reportHTML(res));
      io.status(res.mod ? `✓ ${res.message}. Boot it from the game's menu ("Boot with a mod": ${res.mod}).`
        : `✗ ${res.message || res.status}`);
      if (res.mod && io.onBuilt) io.onBuilt(res);
      return res;
    }
    return { sources, plan, build, request, refreshRequest, state: st };
  }

  // the browser binding: a dialog under <body> wired to the controller
  function open(doc, io, game) {
    doc.getElementById("castdlg")?.remove();
    const el = doc.createElement("div");
    el.id = "castdlg"; el.setAttribute("role", "dialog");
    el.style.cssText = "position:fixed;left:50%;top:8vh;transform:translateX(-50%);z-index:97;width:min(560px,calc(100vw - 24px));" +
      "max-height:84vh;overflow:auto;box-sizing:border-box;background:var(--bg);color:var(--fg,inherit);border:1px solid var(--line);" +
      "border-radius:10px;padding:10px 12px;box-shadow:0 10px 30px #000a;font-size:13px";
    el.innerHTML = '<div data-cs-part="form"></div>';
    doc.body.append(el);
    const q = s => el.querySelector(s);
    let closed = false, requestTimer = null;
    const close = () => { closed = true; clearInterval(requestTimer); el.remove(); };
    const ui = Object.assign({}, io, {
      render: (part, html) => { if (closed) return; if (part === "form") { q('[data-cs-part="form"]').innerHTML = html; } else { const p = q(`[data-cs="${part}"]`); if (p) p.innerHTML = html; } },
      status: t => { const s = q('[data-cs="status"]'); if (s) s.textContent = t; },
      enable: (name, on) => { const b = q(`[data-cs-go="${name}"]`); if (b) b.disabled = !on; },
      requestable: on => { const b = q('[data-cs-go="request"]'); if (b) b.hidden = !on; },
    });
    const c = controller(ui, game);
    const form = () => ({ source: q('[data-cs="source"]').value, mapping: q('[data-cs="mapping"]').value,
                          slots: q('[data-cs="slots"]').value, seed: q('[data-cs="seed"]').value.trim() });
    const picks = () => Object.fromEntries([...el.querySelectorAll("[data-cs-slot]")].map(s => [s.dataset.csSlot, s.value]));
    const marks = () => Object.fromEntries([...el.querySelectorAll("[data-cs-mark]")].map(m => [m.dataset.csMark, m.checked]));
    const counted = () => { const m = Object.values(marks()), n = q('[data-cs="marked"]');
                            if (n) n.textContent = `${m.filter(Boolean).length} of ${m.length} marked`; };
    const thumb = s => { const d = (c.state.plan?.donors || []).find(x => x.slug === s.value), im = s.closest("tr")?.querySelector("img");
                         if (im && d) im.src = (io.img || (u => u))(d.preview_url); };
    el.onclick = async e => {
      const rt = e.target.closest("[data-cs-rt]");
      if (rt && rt.dataset.csRt !== undefined) {             // ✎ on a plan row: the Retarget editor for that donor + slot
        const slot = rt.dataset.csRt, slug = picks()[slot], d = (c.state.plan?.donors || []).find(x => x.slug === slug);
        if (!slug) { ui.status("Pick a donor for this slot first."); return; }
        const o = { slug, name: d?.name || slug, gid: game.gid, title: game.title, slot };
        if (io.retarget) io.retarget(o); else if (root.GBoxRetargetEditor) root.GBoxRetargetEditor.open(doc, io, o);
        return;
      }
      const b = e.target.closest("[data-cs-go]"); if (!b) return;
      if (b.dataset.csGo === "close") { close(); return; }
      if (b.dataset.csGo === "markall" || b.dataset.csGo === "marknone") {
        el.querySelectorAll("[data-cs-mark]").forEach(m => { m.checked = b.dataset.csGo === "markall"; }); counted(); return;
      }
      if (b.dataset.csGo === "deal") {                       // the ticked donors at random over the ticked rows, in one go
        const on = Object.entries(marks()).filter(([, v]) => v).map(([k]) => k);
        const ds = [...el.querySelectorAll("[data-cs-donor]")].filter(x => x.checked).map(x => x.dataset.csDonor);
        if (!on.length || !ds.length) { ui.status("Tick at least one row and one donor to deal."); return; }
        const dealt = deal(on, ds, `${form().seed}|${Date.now()}`);
        el.querySelectorAll("[data-cs-slot]").forEach(s => { if (dealt[s.dataset.csSlot]) { s.value = dealt[s.dataset.csSlot]; thumb(s); } });
        ui.status(`Dealt ${ds.length} donors over ${on.length} marked characters. Change any row, then build.`); return;
      }
      try {
        if (b.dataset.csGo === "plan") await c.plan(form());
        else if (b.dataset.csGo === "request") {
          await c.request(form());
          if (!closed && !requestTimer) requestTimer = setInterval(() => {
            if (el.isConnected === false) { clearInterval(requestTimer); return; }
            c.refreshRequest().catch(() => {});
          }, 5000);
        } else if (b.dataset.csGo === "request-refresh") await c.refreshRequest();
        else if (b.dataset.csGo === "request-details") await c.refreshRequest(true);
        else await c.build(picks(), marks());
      }
      catch (err) { ui.status("✗ " + String(err.message || err).slice(0, 300)); }
    };
    el.onchange = e => {                                     // a changed donor: its thumbnail follows; a tick: the count
      if (e.target.closest("[data-cs-mark]")) { counted(); return; }
      const s = e.target.closest("[data-cs-slot]"); if (s) thumb(s);
    };
    c.sources().catch(err => ui.status("✗ " + String(err.message || err).slice(0, 300)));
    return { el, controller: c, close };
  }

  const api = { sourceOptions, formHTML, planHTML, edits, reviewed, deal, reportHTML, requestHTML, samePendingCast, controller, open, MAPPINGS, SLOT_SETS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxCastSwap = api;
})(typeof window !== "undefined" ? window : globalThis);
