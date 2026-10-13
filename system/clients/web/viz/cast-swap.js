// "Replace entire cast with..." (gbox/cast_swap.py): right-click a game -> pick a source game or group (Wrestlers,
// Jet Grind Radio, SA2, ...) and a mapping -> the planned assignments (target slot -> donor thumbnail), each editable ->
// build ONE mod (characters op=cast_swap on the Spark) -> the per-slot built / failed report.
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

  function formHTML(title, sources) {
    return `<h4 style="margin:0 0 6px">Replace the entire cast of ${ESC(title)}</h4>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">With <select data-cs="source" style="flex:1;min-width:0">${sourceOptions(sources)}</select></label>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">Mapping <select data-cs="mapping" style="flex:1;min-width:0">${MAPPINGS.map(([v, l]) => `<option value="${v}">${ESC(l)}</option>`).join("")}</select></label>
      <label style="display:flex;gap:6px;align-items:center;margin:4px 0">Slots <select data-cs="slots" style="flex:1;min-width:0">${SLOT_SETS.map(([v, l]) => `<option value="${v}">${ESC(l)}</option>`).join("")}</select>
        Seed <input data-cs="seed" size="6" placeholder="any"></label>
      <div style="display:flex;gap:6px;margin:6px 0"><button class="act" data-cs-go="plan" type="button">Plan the cast</button>
        <button class="act pri" data-cs-go="build" type="button" disabled>Build one mod</button>
        <button class="act" data-cs-go="close" type="button" style="margin-left:auto">Close</button></div>
      <div data-cs="status" class="mut" style="font-size:12px;white-space:pre-wrap"></div><div data-cs="plan"></div>`;
  }

  // the plan as rows: target slot -> donor thumbnail + a picker of every eligible donor ("(leave as it is)" drops it)
  function planHTML(plan, img = u => u) {
    const donors = plan.donors || [];
    const pick = (row) => `<select data-cs-slot="${ESC(row.slot)}" style="max-width:150px">${donors.map(d =>
      `<option value="${ESC(d.slug)}"${d.slug === row.character ? " selected" : ""}>${ESC(d.name)}${d.stale ? " (re-extract)" : ""}</option>`).join("")}
      <option value="">(leave as it is)</option></select>`;
    const rows = (plan.assignments || []).map(r => `<tr data-row="${ESC(r.slot)}"><td title="${ESC(r.slot)}">${ESC(r.slot_name || r.slot)}</td>
      <td>${r.preview_url ? `<img alt="" loading="lazy" src="${ESC(img(r.preview_url))}" style="width:34px;height:34px;object-fit:contain">` : ""}</td>
      <td>${pick(r)}<div class="mut" style="font-size:10.5px">${ESC(r.why || "")}</div></td>
      <td><button type="button" class="act" data-cs-rt="${ESC(r.slot)}" title="Retarget editor: how this donor is scaled and proportioned into this slot">✎</button></td></tr>`).join("");
    const skipped = (plan.skipped || []).map(s => `<li>${ESC(s.slot)}: ${ESC(s.reason)}</li>`).join("");
    const refused = (plan.refused || []).map(s => `<li>${ESC(s.name || s.slug)}: ${ESC(s.reason)}</li>`).join("");
    const fresh = (plan.refreshed || []).map(s => `<li>${ESC(s.name || s.slug)}: ${ESC(s.status)}</li>`).join("");
    return `<div class="mut" style="font-size:12px;margin:4px 0">${ESC(plan.message || "")}${plan.how ? " · " + ESC(plan.how) : ""}</div>
      <table data-cs="rows" style="width:100%;font-size:12px;border-collapse:collapse"><tbody>${rows}</tbody></table>
      ${skipped ? `<details><summary>Left as they are (${(plan.skipped || []).length})</summary><ul>${skipped}</ul></details>` : ""}
      ${refused ? `<details><summary>Refused donors (${(plan.refused || []).length})</summary><ul>${refused}</ul></details>` : ""}
      ${fresh ? `<details open><summary>Re-extracted before the build (${(plan.refreshed || []).length})</summary><ul>${fresh}</ul></details>` : ""}`;
  }

  // [{slot, character}] for every row the operator changed
  function edits(plan, picks) {
    const was = Object.fromEntries((plan.assignments || []).map(r => [r.slot, r.character]));
    return Object.entries(picks || {}).filter(([slot, slug]) => slot in was && was[slot] !== slug)
      .map(([slot, character]) => ({ slot, character }));
  }

  // every planned row as reviewed (picks override): the build re-plans with the same seed and pins each row, so it
  // builds exactly what was shown even when a donor is re-extracted first
  function reviewed(plan, picks) {
    return (plan.assignments || []).map(r => ({ slot: r.slot,
      character: picks && Object.prototype.hasOwnProperty.call(picks, r.slot) ? picks[r.slot] : r.character }));
  }

  function reportHTML(res) {
    const rows = (res.report || []).map(r => `<tr><td>${ESC(r.slot_name || r.slot)}</td><td>${ESC(r.donor || "")}</td>
      <td style="color:var(${r.status === "built" ? "--ok" : r.status === "skipped" ? "--mut" : "--bad"})">${ESC(r.status)}</td>
      <td class="mut">${ESC(r.reason || "")}</td></tr>`).join("");
    return `<div style="margin:4px 0;font-size:12px"><b>${ESC(res.status)}</b>${res.mod ? ` · mod <code>${ESC(res.mod)}</code>` : ""} · ${ESC(res.message || "")}</div>
      <table style="width:100%;font-size:12px;border-collapse:collapse"><tbody>${rows}</tbody></table>`;
  }

  // io: api(path, body?) -> data (throws on error), render(part, html), status(text), enable(name, on), img(url),
  //     delay(ms), onBuilt(result)
  function controller(io, game) {
    const wait = io.delay || (ms => new Promise(r => setTimeout(r, ms)));
    const st = { plan: null, form: null };
    async function sources() {
      io.status("Loading the collection…");
      const r = await io.api(`/api/cast_swap/sources?game_id=${encodeURIComponent(game.gid)}`);
      io.render("form", formHTML(game.title, r.sources || []));
      io.status(r.sources?.length ? `${(r.slots || []).length || "The"} replaceable slots; pick who replaces them.`
        : "Nothing in the collection to cast yet: extract a game's characters first.");
      return r;
    }
    async function plan(form, assignments = []) {
      st.form = form; io.enable("build", false); io.status("Planning…");
      const p = await io.api("/api/cast_swap/plan", { game_id: game.gid, source: form.source, mapping: form.mapping,
                                                      seed: form.seed || "", slots: form.slots || "all", assignments });
      st.plan = p;
      io.render("plan", p.assignments?.length ? planHTML(p, io.img || (u => u)) : "");
      io.status(p.assignments?.length ? `${p.assignments.length} slots planned. Change any donor, then build.` : (p.message || p.status));
      io.enable("build", !!p.assignments?.length);
      return p;
    }
    async function build(picks) {
      if (!st.plan) throw new Error("plan first");
      const f = st.form, changed = edits(st.plan, picks).length;
      io.enable("build", false); io.status(`Queued on the Spark${changed ? ` (${changed} rows changed by you)` : ""}…`);
      let j = await io.api("/api/jobs", { tool: "characters", require_os: "linux", input: { op: "cast_swap",
        target_game: game.gid, source: f.source, mapping: f.mapping, seed: f.seed || "", slots: f.slots || "all",
        assignments: reviewed(st.plan, picks), launch: false } });
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
    return { sources, plan, build, state: st };
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
    const ui = Object.assign({}, io, {
      render: (part, html) => { if (part === "form") { q('[data-cs-part="form"]').innerHTML = html; } else { const p = q('[data-cs="plan"]'); if (p) p.innerHTML = html; } },
      status: t => { const s = q('[data-cs="status"]'); if (s) s.textContent = t; },
      enable: (name, on) => { const b = q(`[data-cs-go="${name}"]`); if (b) b.disabled = !on; },
    });
    const c = controller(ui, game);
    const form = () => ({ source: q('[data-cs="source"]').value, mapping: q('[data-cs="mapping"]').value,
                          slots: q('[data-cs="slots"]').value, seed: q('[data-cs="seed"]').value.trim() });
    const picks = () => Object.fromEntries([...el.querySelectorAll("[data-cs-slot]")].map(s => [s.dataset.csSlot, s.value]));
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
      if (b.dataset.csGo === "close") { el.remove(); return; }
      try { if (b.dataset.csGo === "plan") await c.plan(form()); else await c.build(picks()); }
      catch (err) { ui.status("✗ " + String(err.message || err).slice(0, 300)); }
    };
    el.onchange = e => {                                     // a changed donor: its thumbnail follows
      const s = e.target.closest("[data-cs-slot]"); if (!s) return;
      const d = (c.state.plan?.donors || []).find(x => x.slug === s.value), im = s.closest("tr")?.querySelector("img");
      if (im && d) im.src = (io.img || (u => u))(d.preview_url);
    };
    c.sources().catch(err => ui.status("✗ " + String(err.message || err).slice(0, 300)));
    return { el, controller: c };
  }

  const api = { sourceOptions, formHTML, planHTML, edits, reviewed, reportHTML, controller, open, MAPPINGS, SLOT_SETS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxCastSwap = api;
})(typeof window !== "undefined" ? window : globalThis);
