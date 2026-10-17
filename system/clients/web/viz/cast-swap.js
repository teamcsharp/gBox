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
      <label style="display:flex;gap:6px;align-items:center;margin:6px 0">Find a donor title <input data-cs="title-search" type="search" placeholder="Search all your games" style="flex:1;min-width:0" autocomplete="off"></label>
      <div data-cs="title-results" aria-live="polite"></div>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">Mapping <select data-cs="mapping" style="flex:1;min-width:0">${MAPPINGS.map(([v, l]) => `<option value="${v}">${ESC(l)}</option>`).join("")}</select></label>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">Slots <select data-cs="slots" style="flex:1;min-width:0">${slotSets.map(([v, l]) => `<option value="${v}">${ESC(l)}</option>`).join("")}</select>
        <span data-cs-seed-control>Seed <input data-cs="seed" size="6" placeholder="any"></span></label>
      <div style="display:flex;gap:6px;margin:6px 0"><button class="act" data-cs-go="plan" type="button">Plan the cast</button>
        <button class="act pri" data-cs-go="build" type="button" disabled>Build one mod</button>
        <button class="act pri" data-cs-go="request" type="button" hidden>Request this build</button>
        <button class="act" data-cs-go="close" type="button" style="margin-left:auto">Close</button></div>
      <div data-cs="status" class="mut" style="font-size:12px;white-space:pre-wrap" role="status" aria-live="polite"></div><div data-cs="chart"></div><div data-cs="plan"></div>
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
  const stable = value => JSON.stringify(canonical(value));
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
    return value;
  }
  function chartRows(roster, rows = []) {
    const targets = roster?.targets || [], donors = new Set((roster?.donors || []).map(d => d.slug));
    const byId = new Map();
    for (const row of rows) {
      if (!row || byId.has(row.target_id)) throw new Error('Each original character needs one mapping row.');
      if (row.character && !donors.has(row.character)) throw new Error('A replacement is outside the selected donor roster.');
      byId.set(row.target_id, row.character || '');
    }
    if ([...byId.keys()].some(id => !targets.some(t => t.id === id))) throw new Error('A mapping belongs to a different target roster.');
    return targets.map(t => ({target_id: t.id, slot: t.slot || null, character: byId.get(t.id) || ''}));
  }
  const nativeRows = rows => rows.filter(row => row.slot).map(({slot, character}) => ({slot, character}))
    .sort((a,b) => a.slot.localeCompare(b.slot));
  function chartSnapshot(roster, rows) {
    const reference = card => Object.fromEntries(['id', 'slot', 'slug', 'name', 'source_game_id', 'kind'].filter(k => card[k] != null).map(k => [k, card[k]]));
    const selected = new Set(rows.map(row => row.character).filter(Boolean));
    return {version: 1, target_game_id: roster.game.game_id, source: roster.source.key,
      targets: roster.targets.map(reference).sort((a,b) => a.id.localeCompare(b.id)),
      donors: roster.donors.filter(card => selected.has(card.slug)).map(reference).sort((a,b) => a.id.localeCompare(b.id)),
      connections: chartRows(roster, rows).sort((a,b) => a.target_id.localeCompare(b.target_id))};
  }
  function nativeChartReady(roster, rows) {
    const donors = new Map((roster?.donors || []).map(d => [d.slug, d]));
    return roster?.capability?.combined_writer === true && rows.some(r => r.character) &&
      rows.every(r => !r.character || (r.slot && roster.targets.find(t => t.id === r.target_id)?.buildable === true && donors.get(r.character)?.ready === true));
  }
  function nativePlanMatches(rows, plan) {
    const pairs = values => values.filter(row => row.character).map(({slot, character}) => ({slot, character}))
      .sort((a,b) => a.slot.localeCompare(b.slot));
    return plan.status === 'planned' && stable(pairs(nativeRows(rows))) === stable(pairs(plan.assignments || []));
  }
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
    const st = { plan: null, form: null, sources: [], requestAllowed: false, request: null, pendingRequest: null,
      roster: null, chartRows: null, reviewedChart: null, chartTouched: false };
    let rosterVersion = 0, planVersion = 0, disposed = false;
    let intents = [];
    const storageKey = `gbox_cast_build_requests_${game.gid}`;
    const storage = () => io.storage || root.sessionStorage;
    try { const saved = JSON.parse(storage()?.getItem(storageKey) || "[]"); if (Array.isArray(saved)) intents = saved; } catch {}
    const allowRequest = on => { st.requestAllowed = on; io.requestable?.(on); io.enable("request", on && !st.pendingRequest); };
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
      const version = ++planVersion;
      if (st.roster && (st.roster.source.key !== form.source || (st.roster.requested_scope || 'all') !== (form.slots || 'all')))
        throw new Error('Load the selected donor roster and scope before reviewing.');
      if (st.roster && st.chartTouched) assignments = nativeRows(chartRows(st.roster, st.chartRows || []));
      st.form = form; io.enable("build", false); io.status("Planning…");
      const p = await io.api("/api/cast_swap/plan", { game_id: game.gid, source: form.source, mapping: form.mapping,
                                                      seed: form.seed || "", slots: form.slots || "all", assignments });
      if (disposed || version !== planVersion) return null;
      if (st.roster && !st.chartTouched && p.assignments?.length) {
        const bySlot = new Map(p.assignments.map(row => [row.slot, row.character]));
        st.chartRows = chartRows(st.roster, st.roster.targets.map(target => ({target_id: target.id, character: bySlot.get(target.slot) || ''})));
      }
      st.plan = p;
      const ready = !st.roster || (nativeChartReady(st.roster, st.chartRows || []) && nativePlanMatches(st.chartRows || [], p));
      st.reviewedChart = st.roster && ready ? stable(st.chartRows) : null;
      allowRequest(["unsupported", "unsupported_cast"].includes(p.status) || !ready);
      io.render("plan", p.assignments?.length ? planHTML(p, io.img || (u => u)) : "");
      io.status(st.roster ? !st.chartRows.some(row => row.character) ? 'Connect original characters to replacements, or shuffle the cast, then review.' :
        ready ? `${st.chartRows.filter(row => row.character).length} connections reviewed. Build the mapped cast when ready.` :
        'Your connections are preserved. This mapping needs extraction or native cast support; submit the mapped build request to continue.' :
        p.assignments?.length ? `${p.assignments.length} slots planned. Change any donor, then build.` : (p.message || p.status));
      io.enable("build", ready && p.status === 'planned' && !!p.assignments?.length);
      return p;
    }
    async function roster(form) {
      const version = ++rosterVersion; planVersion++;
      st.plan = null; st.roster = null; st.chartRows = null; st.reviewedChart = null; st.chartTouched = false; st.form = form;
      io.enable('build', false); allowRequest(false);
      const r = await io.api(`/api/cast_swap/roster?game_id=${encodeURIComponent(game.gid)}&source=${encodeURIComponent(form.source || '')}&slots=${encodeURIComponent(form.slots || 'all')}`);
      if (disposed || version !== rosterVersion) return null;
      if (r?.game?.game_id !== game.gid || r?.source?.key !== (form.source || '') ||
          (r?.requested_scope || 'all') !== (form.slots || 'all') || !Array.isArray(r.targets) || !Array.isArray(r.donors))
        throw new Error('Received a roster for a different game or donor source.');
      st.roster = r; st.chartRows = chartRows(r, []);
      allowRequest(r.capability?.status !== 'ready');
      return r;
    }
    function updateChart(rows, initial = false) {
      if (!st.roster) throw new Error('Load the cast rosters first.');
      st.chartRows = chartRows(st.roster, rows); st.plan = null; st.reviewedChart = null; planVersion++;
      if (!initial) st.chartTouched = true;
      io.enable('build', false); allowRequest(!nativeChartReady(st.roster, st.chartRows));
      return st.chartRows;
    }
    function request(form) {
      if (!st.requestAllowed) return Promise.reject(new Error("Plan the supported cast and review its assignments before building."));
      if (!form.source) return Promise.reject(new Error("Choose the source characters first."));
      const source = st.sources.find(s => s.key === form.source), label = source?.label || form.source;
      const scope = form.slots || "all", mapping = form.mapping || "auto", seed = form.seed || "";
      const body = { kind: "build", recipe: "agent", session_id: game.session_id || "",
        description: `${scope === "all" ? "Replace the entire cast" : `Replace the ${scope} characters`} of ${game.title} with ${label}. ` +
          `Use the extracted donor source ${form.source}, mapping ${mapping}${seed ? `, seed ${seed}` : ""}. ` +
          "Implement and test any missing native reader and combined character writer; do not substitute an overlay or a single-player replacement. Publish one playable mod build after separate gameplay verification.",
        mapping: { source: form.source, source_label: label, mapping, slots: scope, seed } };
      if (st.roster) {
        if (st.roster.source.key !== form.source || (st.roster.requested_scope || 'all') !== (form.slots || 'all'))
          return Promise.reject(new Error('Load the selected donor roster and scope first.'));
        const rows = chartRows(st.roster, st.chartRows || []);
        if (rows.length && st.roster.donors.length && !rows.some(r => r.character))
          return Promise.reject(new Error('Connect at least one replacement before requesting this build.'));
        body.mapping.assignments = nativeRows(rows);
        body.mapping.cast_chart = chartSnapshot(st.roster, rows);
        body.description = body.description.replace('Use the extracted donor source', 'Use the selected donor source');
        body.description += ' Preserve every reviewed cast_chart connection exactly. Its empty characters stay unchanged. ' +
          'A null slot is a named roster reference requiring native slot discovery, never an instruction to reuse the player slot. ' +
          'Do not randomize reviewed choices. If no roster is available, extract the exact titles and complete the requested mapping first.';
      }
      if (JSON.stringify(body.mapping).length > 96000) return Promise.reject(new Error('This mapping exceeds the saved profile limit. Choose a smaller cast scope.'));
      const signature = stable(body);
      if (st.pendingRequest) return st.pendingSignature === signature ? st.pendingRequest :
        Promise.reject(new Error('A different mapping is still being saved. Wait for its request number, then submit this mapping.'));
      let intent = intents.find(i => i.signature === signature);
      if (!intent) {
        intent = { signature, clientId: (io.uuid || uuid)() }; intents = [...intents.slice(-19), intent];
        try { storage()?.setItem(storageKey, JSON.stringify(intents)); } catch {}
      }
      io.enable("request", false); io.status("Checking and saving the build request…");
      io.saving?.(true); st.pendingSignature = signature;
      const path = `/api/games/${encodeURIComponent(game.gid)}/build-requests`;
      st.pendingRequest = (async () => {
        const existing = await io.api(path);
        const previous = (existing.items || []).find(r => body.mapping.cast_chart ?
          /^(open|in_progress|blocked)$/.test(r.status || '') && r.kind === 'build' && !r.photo && !r.base_mod &&
            (!r.projection_scope || r.projection_scope === 'gameplay') && stable(r.mapping) === stable(body.mapping) : samePendingCast(r, form));
        const row = previous || await io.api(path, { ...body, client_id: intent.clientId });
        st.request = row; io.render("request", requestHTML(row)); io.render("request-detail", "");
        io.status(`Request #${row.number} ${previous ? "already saved" : "saved"}. ${row.dispatch_error ? "Dispatch needs attention; your request is retained." : "Follow its progress below. No playable build is being claimed yet."}`);
        return row;
      })().catch(error => { io.status(`Request could not be confirmed: ${error.message}. Retry uses the same request ID.`); throw error; })
        .finally(() => { st.pendingRequest = null; st.pendingSignature = null; io.saving?.(false); io.enable("request", st.requestAllowed); });
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
      if (st.roster && (!nativeChartReady(st.roster, st.chartRows || []) || st.reviewedChart !== stable(st.chartRows) || st.plan.status !== 'planned'))
        throw new Error('Review the current native mapping before building. Missing cast support needs an engineering request.');
      const f = st.form, changed = edits(st.plan, picks, marks).length,
        rows = st.roster ? nativeRows(st.chartRows) : reviewed(st.plan, picks, marks);
      if (!rows.some(r => r.character)) { io.status("Tick at least one character to replace."); return null; }
      io.enable("build", false); io.status(`Queued on the Spark${changed ? ` (${changed} rows changed by you)` : ""}…`);
      let j = await io.api("/api/jobs", { tool: "characters", require_os: "linux", input: { op: "cast_swap",
        target_game: game.gid, source: f.source, mapping: f.mapping, seed: f.seed || "", slots: f.slots || "all",
        assignments: rows, launch: false } });
      while (/queued|running/.test(j.state)) {
        if (disposed) return j;
        await wait(1500);
        if (disposed) return j;
        j = await io.api("/api/jobs/" + j.id);
        if (j.progress?.msg) io.status(j.progress.msg);
      }
      if (disposed) return j;
      if (j.state !== "succeeded") { io.status("✗ " + (j.error || j.state)); io.enable("build", true); return j; }
      const res = j.output?.result || {};
      io.render("plan", reportHTML(res));
      io.status(res.mod ? `✓ ${res.message}. Boot it from the game's menu ("Boot with a mod": ${res.mod}).`
        : `✗ ${res.message || res.status}`);
      if (res.mod && io.onBuilt) io.onBuilt(res);
      return res;
    }
    return { sources, plan, roster, updateChart, build, request, refreshRequest, state: st,
      dispose() { disposed = true; rosterVersion++; planVersion++; } };
  }

  // the browser binding: a dialog under <body> wired to the controller
  function open(doc, io, game) {
    const previous = doc.getElementById('castdlg');
    if (typeof previous?.gboxCastClose === 'function') previous.gboxCastClose(); else previous?.remove();
    const el = doc.createElement("div");
    el.id = "castdlg"; el.setAttribute("role", "dialog");
    el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', 'Map replacement cast');
    el.style.cssText = "position:fixed;left:50%;top:3vh;transform:translateX(-50%);z-index:97;width:min(1180px,calc(100vw - 24px));" +
      "max-height:94vh;overflow:auto;box-sizing:border-box;background:var(--bg,#17191f);color:var(--fg,#eee);border:1px solid var(--line,#444);" +
      "border-radius:10px;padding:10px 12px;box-shadow:0 10px 30px #000a;font-size:13px";
    el.innerHTML = '<div data-cs-part="form"></div>';
    doc.body.append(el);
    const q = s => el.querySelector(s);
    let closed = false, requestTimer = null, mapper = null, chartVersion = 0, titleVersion = 0, searchTimer = null,
      mapperForm = null, titleHits = [], applyingPlan = false, savingForm = null;
    const inspectors = new Set();
    const frozen = new Map();
    const close = () => { if (closed) return; if (mapper) saveDraft(mapper.getAssignments()); closed = true; chartVersion++; titleVersion++; clearInterval(requestTimer); clearTimeout(searchTimer);
      mapper?.dispose(); c.dispose(); for (const inspector of inspectors) inspector.close?.(); el.remove(); };
    const ui = Object.assign({}, io, {
      render: (part, html) => { if (closed) return; if (part === "form") { q('[data-cs-part="form"]').innerHTML = html; } else { const p = q(`[data-cs="${part}"]`); if (p) p.innerHTML = part === 'plan' && mapper && html ? `<details><summary>Mapping details</summary><fieldset disabled style="border:0;padding:0;margin:0">${html}</fieldset></details>` : html; } },
      status: t => { if (closed) return; const s = q('[data-cs="status"]'); if (s) s.textContent = t; },
      enable: (name, on) => { if (closed) return; const b = q(`[data-cs-go="${name}"]`); if (b) b.disabled = !on; },
      requestable: on => { if (closed) return; const b = q('[data-cs-go="request"]'); if (b) b.hidden = !on; },
      saving: on => {
        if (closed) return;
        savingForm = on ? form() : null;
        const chart = q('[data-cs="chart"]'); if (chart) chart.inert = on;
        if (on) {
          for (const control of el.querySelectorAll('[data-cs="source"], [data-cs="mapping"], [data-cs="slots"], [data-cs="seed"], [data-cs="title-search"], [data-cs-title]')) {
            frozen.set(control, control.disabled); control.disabled = true;
          }
        } else { for (const [control, disabled] of frozen) control.disabled = disabled; frozen.clear(); }
      },
    });
    const c = controller(ui, game);
    el.gboxCastClose = close;
    const form = () => ({ source: q('[data-cs="source"]').value, mapping: q('[data-cs="mapping"]').value,
                          slots: q('[data-cs="slots"]').value, seed: (q('[data-cs="chart"] [data-seed]') || q('[data-cs="seed"]')).value.trim() });
    const storage = () => io.storage || root.sessionStorage;
    const draftKey = f => `gbox_cast_chart_v1:${game.gid}:${f.source}:${f.slots}`;
    function saveDraft(rows, f = mapperForm) { if (!f) return; try { storage()?.setItem(draftKey(f), JSON.stringify(mapper?.getDraft?.() || {version: 1, rows, seed: f.seed})); } catch {} }
    async function inspectCard(card) {
      if (!card.slug || !card.model_url || !io.inspect) { ui.status('This character needs an extracted 3D model before inspection.'); return; }
      const popup = await io.inspect({slug: card.slug, name: card.name, gid: card.slot ? game.gid : '', title: game.title,
        slot: card.slot || 'unassigned', modelUrl: card.model_url});
      if (closed) popup?.close?.(); else if (popup) inspectors.add(popup);
    }
    async function loadChart() {
      if (closed || !root.GBoxCastMapper) return null;
      if (c.state.pendingRequest) { ui.status('Wait for the current request to finish saving.'); return null; }
      if (mapper) saveDraft(mapper.getAssignments());
      const version = ++chartVersion, f = form(), host = q('[data-cs="chart"]');
      q('[data-cs="seed"]').value = f.seed;
      mapper?.dispose(); mapper = null; mapperForm = null;
      host.textContent = 'Loading both character rosters…'; ui.render('plan', '');
      const roster = await c.roster(f);
      if (closed || version !== chartVersion || !roster) return null;
      mapperForm = f; let initializing = true, saved;
      try { const raw = storage()?.getItem(draftKey(f)); if (raw) saved = JSON.parse(raw); } catch {}
      host.replaceChildren();
      mapper = root.GBoxCastMapper.mount(host, roster, {img: io.img, inspect: io.inspect ? inspectCard : undefined,
        onChange: rows => {
          if (closed || version !== chartVersion) return;
          saveDraft(rows, f);
          if (applyingPlan) return;
          c.updateChart(rows, initializing); ui.render('plan', '');
          if (!initializing) ui.status(`${rows.filter(r => r.character).length} connections. Review the mapping, then build or request its missing support.`);
        }});
      const seedInput = host.querySelector('[data-seed]'); if (seedInput) seedInput.value = f.seed;
      const outerSeed = q('[data-cs-seed-control]'); if (outerSeed) outerSeed.hidden = true;
      const hasDraft = Array.isArray(saved) || (saved?.version === 1 && Array.isArray(saved.rows));
      if (Array.isArray(saved)) mapper.setAssignments(saved);
      else if (hasDraft) mapper.restoreDraft(saved);
      c.updateChart(mapper.getAssignments(), !hasDraft);
      await mapper.ready; initializing = false;
      if (closed || version !== chartVersion) return null;
      const review = q('[data-cs-go="plan"]'); if (review) review.textContent = 'Review mapping';
      const build = q('[data-cs-go="build"]'); if (build) build.textContent = 'Build mapped cast';
      const request = q('[data-cs-go="request"]'); if (request) request.textContent = 'Request mapped build';
      ui.status(`${roster.targets.length} original characters · ${roster.donors.length} replacements. ` +
        (roster.capability?.blocking_reasons || []).join('. '));
      return roster;
    }
    function refreshChart() { return loadChart().catch(error => { if (!closed) ui.status('Roster unavailable: ' + String(error.message || error)); }); }
    const picks = () => Object.fromEntries([...el.querySelectorAll("[data-cs-slot]")].map(s => [s.dataset.csSlot, s.value]));
    const marks = () => Object.fromEntries([...el.querySelectorAll("[data-cs-mark]")].map(m => [m.dataset.csMark, m.checked]));
    const counted = () => { const m = Object.values(marks()), n = q('[data-cs="marked"]');
                            if (n) n.textContent = `${m.filter(Boolean).length} of ${m.length} marked`; };
    const thumb = s => { const d = (c.state.plan?.donors || []).find(x => x.slug === s.value), im = s.closest("tr")?.querySelector("img");
                         if (im && d) im.src = (io.img || (u => u))(d.preview_url); };
    el.onclick = async e => {
      const title = e.target.closest('[data-cs-title]');
      if (title && title.dataset.csTitle !== undefined) {
        if (c.state.pendingRequest) { ui.status('Wait for the current request to finish saving.'); return; }
        const hit = titleHits[Number(title.dataset.csTitle)]; if (!hit) return;
        const select = q('[data-cs="source"]');
        if (![...select.options].some(option => option.value === hit.game_id)) {
          const option = doc.createElement('option'); option.value = hit.game_id; option.textContent = hit.title;
          select.appendChild(option);
        }
        if (!c.state.sources.some(source => source.key === hit.game_id)) c.state.sources.push({key: hit.game_id, label: hit.title, kind: 'game', count: 0});
        select.value = hit.game_id; q('[data-cs="title-search"]').value = hit.title;
        titleVersion++; q('[data-cs="title-results"]').replaceChildren();
        await refreshChart(); return;
      }
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
        if (b.dataset.csGo === "plan") {
          if (root.GBoxCastMapper && !mapper) { await refreshChart(); if (!mapper) return; }
          if (mapper && !c.state.chartTouched && form().mapping === 'random' && !mapper.getAssignments().some(row => row.character)) mapper.shuffle(form().seed);
          const p = await c.plan(form());
          if (p && mapper && c.state.chartRows && stable(mapper.getAssignments()) !== stable(c.state.chartRows)) {
            applyingPlan = true; try { mapper.setAssignments(c.state.chartRows); } finally { applyingPlan = false; }
          }
        }
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
    el.oninput = event => {
      const input = event.target.closest('[data-cs="title-search"]'); if (!input) return;
      clearTimeout(searchTimer); const version = ++titleVersion, query = input.value.trim(), result = q('[data-cs="title-results"]');
      if (query.length < 2) { result.textContent = ''; return; }
      result.textContent = 'Searching your titles…';
      searchTimer = setTimeout(async () => {
        try {
          const response = await io.api('/api/home/games?q=' + encodeURIComponent(query) + '&limit=12');
          if (closed || version !== titleVersion) return;
          titleHits = (response.items || []).filter(game => game.game_id && game.title);
          result.innerHTML = titleHits.length ? titleHits.map((game, index) => `<button class="act" type="button" data-cs-title="${index}" style="margin:3px;text-align:left">${ESC(game.title)} <small>${ESC(game.system || game.platform || '')}</small></button>`).join('') : 'No matching titles in your catalog.';
        } catch (error) { if (!closed && version === titleVersion) result.textContent = 'Title search failed: ' + String(error.message || error); }
      }, 250);
    };
    el.onkeydown = event => { if (event.key === 'Escape') { event.preventDefault?.(); close(); } };
    el.onchange = e => {                                     // a changed donor: its thumbnail follows; a tick: the count
      if (c.state.pendingRequest && savingForm) {
        const field = e.target.closest('[data-cs="source"], [data-cs="slots"], [data-cs="mapping"], [data-cs="seed"]');
        if (field) field.value = savingForm[field.dataset.cs] || '';
        const seed = e.target.closest('[data-cs="chart"] [data-seed]'); if (seed) seed.value = savingForm.seed;
        if (field || seed) { ui.status('The current mapping is still being saved.'); return; }
      }
      if (root.GBoxCastMapper && e.target.closest('[data-cs="source"], [data-cs="slots"]')) { refreshChart(); return; }
      if (mapper && e.target.closest('[data-cs="mapping"], [data-cs="seed"], [data-cs="chart"] [data-seed]')) { c.updateChart(mapper.getAssignments()); saveDraft(mapper.getAssignments()); return; }
      if (e.target.closest("[data-cs-mark]")) { counted(); return; }
      const s = e.target.closest("[data-cs-slot]"); if (s) thumb(s);
    };
    c.sources().then(() => { if (!closed) return refreshChart(); }).catch(err => ui.status("✗ " + String(err.message || err).slice(0, 300)));
    return { el, controller: c, close };
  }

  const api = { sourceOptions, formHTML, planHTML, edits, reviewed, deal, chartRows, chartSnapshot, nativeChartReady, nativePlanMatches, reportHTML, requestHTML, samePendingCast, controller, open, MAPPINGS, SLOT_SETS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxCastSwap = api;
})(typeof window !== "undefined" ? window : globalThis);
