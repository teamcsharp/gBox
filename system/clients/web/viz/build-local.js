// Builds on this PC (#1639): the download icon in the top-right corner of every Mods card and Builds row.
//   It shows whether this PC has the build in its own cache: "on this PC" (a filled check: it plays at once, offline),
//   "not on this PC" (a download arrow) or downloading (a ring with the percent). Without a PC behind the view (a plain
//   browser) it is greyed out.
//   Click: download to this PC = POST /api/builds/{game}/{name}/local {op: "download", node}: a build_local job on this
//   PC's worker that stages the build into its cache (gbox.filemods.stage) and never launches it; progress on the icon,
//   a toast when it is done.
//   Right-click (or ▾): Download to this PC · Export… · Open folder · Delete from this PC (the Delete dialog limited to
//   this PC's copy: DELETE scope=node).
//   Export…: the formats (GET .../formats: "Same format as the original" first, then plain, patch only, zip), a folder
//   on this PC (the desktop app's folder picker, or typed), then {op: "export", dest, format} as a build_local job on
//   this PC: progress, the final path and Show in folder.
// Plain functions + create(env, hooks) that a view (mods-gallery.js, builds.js) keeps; node tests drive it with a fake
// document (tests/test_build_local.cjs).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const enc = encodeURIComponent;
  const BA = () => root.GBoxBuildActions || (typeof module === "object" && module.exports ? require("./build-actions.js") : null);
  const path = b => `/api/builds/${enc(b.game_id)}/${enc(b.name)}`;
  const nameOf = b => b.mod_title || b.label || b.name;
  const hereOf = env => env && env.here && env.here !== "auto" ? env.here : "";
  const fmtSize = n => n == null ? "" : n >= 2 ** 30 ? (n / 2 ** 30).toFixed(2) + " GB" : n >= 2 ** 20 ? (n / 2 ** 20).toFixed(1) + " MB"
    : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B";
  const DEST_KEY = "gbox.exportDest";
  const POLL_MS = 1000;
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ---------------------------------------------------------------- the icon
  // here: this PC's worker name; local: {"game/name": {built, staged}} from GET /api/builds/local (else the Builds row's
  // `where` list); job: this build's running download / export {op, pct, msg}; over: what this view just did (downloaded
  // = true, deleted here = false) until this PC's heartbeat says the same
  function stateOf(b, { here = "", local = null, job = null, over = null } = {}) {
    if (!here) return { state: "none" };
    if (job && job.op === "download") return { state: "busy", pct: Math.max(0, Math.min(100, Math.round(job.pct || 0))), msg: job.msg || "" };
    const row = local ? local[b.key] : null;
    const on = over && over.has(b.key) ? over.get(b.key) : local ? !!row : (b.where || []).some(w => w.where === "pc" && w.node === here);
    return { state: on ? "here" : "off", staged: !!row?.staged, exporting: job && job.op === "export" ? job : null };
  }
  const TITLES = {
    here: "On this PC: it plays at once, offline. Click or right-click: Export…, Open folder, Delete from this PC",
    off: "Not on this PC: click to download it here, so it plays instantly, offline (nothing is launched). Right-click: Export… and more",
    busy: "Downloading to this PC",
    none: "Open gBox on your PC to download builds to it",
  };
  const ARROW = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 3v11m0 0-4.5-4.5M12 14l4.5-4.5M5 19h14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const CHECK = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m7.5 12.3 3 3 6-6.3" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const ring = pct => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="3"/><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="${(56.55 * pct / 100).toFixed(2)} 56.55" transform="rotate(-90 12 12)"/></svg>`;
  function iconTitle(s, here = "") {
    if (s.state === "busy") return `${TITLES.busy}${here ? ` (${here})` : ""}: ${s.pct}%${s.msg ? " · " + s.msg : ""}`;
    return TITLES[s.state] + (here && s.state !== "none" ? ` · this PC: ${here}` : "") + (s.staged ? " (a staged copy)" : "");
  }
  function iconHTML(s, { open = false, here = "" } = {}) {
    const dis = s.state === "none" ? " disabled" : "";
    const label = { here: "On this PC", off: "Download to this PC", busy: `Downloading ${s.pct}%`, none: "Download (no PC)" }[s.state];
    return `<span class="bl" data-bl-state="${s.state}"><button class="bl-main bl-${s.state}" type="button" data-bl="main" title="${ESC(iconTitle(s, here))}" aria-label="${ESC(label)}"${dis}>`
      + (s.state === "here" ? CHECK : s.state === "busy" ? ring(s.pct) + `<span class="bl-pct">${s.pct}%</span>` : ARROW)
      + `</button><button class="bl-more" type="button" data-bl="menu" aria-haspopup="menu" aria-expanded="${!!open}" title="On this PC: download, export, open folder, delete" aria-label="This PC options"${dis}>▾</button></span>`;
  }
  // right-click or ▾: what this PC can do with the build
  function menuHTML(b, s, here = "") {
    const item = (act, text, title, off = false) => `<button class="act" type="button" role="menuitem" data-bl="${act}" title="${ESC(title)}"${off ? " disabled" : ""}>${text}</button>`;
    const on = s.state === "here", busy = s.state === "busy";
    const head = on ? `On this PC${here ? ` (${ESC(here)})` : ""}${s.staged ? " · staged copy" : ""}` : busy ? `Downloading… ${s.pct}%` : `Not on this PC${here ? ` (${ESC(here)})` : ""}`;
    return `<div class="bl-menu" role="menu" data-bl-menu="${ESC(b.key)}"><div class="bl-mh">${head}</div>`
      + (on ? "" : item("download", busy ? `⬇ Downloading ${s.pct}%…` : "⬇ Download to this PC", "Copy it into this PC's cache so it plays instantly, offline (nothing is launched)", busy))
      + item("export", "⇪ Export…", "Write this build to a folder you pick on this PC: the same format as the original game file, or plain, patch only, zip" + (on ? "" : " (downloads it first)"))
      + item("open", "📂 Open folder", on ? "Show this build's folder in this PC's cache" : "Not on this PC yet: download it first", !on)
      + item("delete", "🗑 Delete from this PC", on ? "Remove only this PC's copy: the Spark collection and other PCs keep theirs" : "Not on this PC", !on)
      + "</div>";
  }

  // ---------------------------------------------------------------- the calls
  const downloadCall = (b, here) => ({ path: path(b) + "/local", body: { op: "download", node: here } });
  const locateCall = (b, here) => ({ path: path(b) + "/local", body: { op: "locate", node: here } });
  const exportCall = (b, here, dest, format, label) => ({ path: path(b) + "/local",
    body: { op: "export", node: here, dest: String(dest || "").trim(), format: format || "same", label: label || nameOf(b) } });
  const formatsPath = b => path(b) + "/formats";
  // follow a job to its end: onProgress(pct, msg) while it runs; the finished job, or an Error with the job's error
  async function follow(env, jobId, onProgress, { wait = sleep, max = 7200 } = {}) {
    let j = { id: jobId, state: "queued" };
    for (let i = 0; i < max; i++) {
      j = await env.api("/api/jobs/" + enc(jobId));
      if (j?.progress && onProgress) onProgress(j.progress.pct || 0, j.progress.msg || "");
      if (!j || !["queued", "running", "claimed"].includes(j.state)) break;
      if (j.state === "queued" && onProgress && !j.progress) onProgress(0, "Waiting for this PC's worker…");
      await wait(env.pollMs || POLL_MS);
    }
    if (!j || j.state !== "succeeded") throw new Error(j?.error || `the job ${j?.state || "did not answer"}`);
    return j;
  }

  // ---------------------------------------------------------------- the export dialog
  const FALLBACK = [{ id: "same", label: "Same format as the original", default: true }, { id: "plain", label: "Plain image" },
                    { id: "patch", label: "Patch only (BPS / xdelta against your original)" }, { id: "zip", label: "Zip" }];
  function exportDialogHTML(b, f, { dest = "", canPick = false, here = "", format = "" } = {}) {
    const formats = (f && f.formats) || FALLBACK;
    const pick = format || (formats.find(o => o.default) || formats[0]).id;
    const src = f && f.source ? `<tr><th>Original</th><td><code>${ESC(f.source)}</code></td></tr>` : "";
    return `<div class="ba-box bx-box" role="dialog" aria-modal="true" aria-label="Export build"><h3>⇪ Export “${ESC(nameOf(b))}”</h3>
      <table class="ba-facts"><tr><th>Game</th><td>${ESC(f?.game_title || b.game_title || b.title || b.game_id)}</td></tr>${src}
        <tr><th>Build</th><td><code>${ESC(b.name)}</code>${f && f.image ? ` · ${ESC(f.image)}` : ""}</td></tr><tr><th>On</th><td>${ESC(here || "this PC")}</td></tr></table>
      <div class="bx-formats" role="radiogroup" aria-label="Format">${formats.map(o => `<label class="ba-opt bx-opt${o.disabled ? " ba-dis" : ""}" title="${ESC(o.disabled || o.note || "")}">`
        + `<input type="radio" name="bx-format" value="${ESC(o.id)}"${o.id === pick && !o.disabled ? " checked" : ""}${o.disabled ? " disabled" : ""}> <span><span class="bx-t">${ESC(o.label)}${o.default ? ' <span class="bx-def">default</span>' : ""}</span>`
        + `${o.disabled ? `<small class="bx-note">${ESC(o.disabled)}</small>` : o.note ? `<small class="bx-note">${ESC(o.note)}</small>` : ""}</span></label>`).join("")}</div>
      <label class="bx-dest-l">Folder on this PC<span class="bx-dest-row"><input class="bx-dest" data-bx-dest type="text" value="${ESC(dest)}" placeholder="${canPick ? "Choose a folder…" : "e.g. D:\\Games\\Exports"}" spellcheck="false" data-nomic>`
        + (canPick ? `<button class="act" type="button" data-bx="pick">Choose…</button>` : "") + `</span></label>
      <p class="ba-note">The build is written into a new folder named after the game and the build inside the folder you choose, never over your original. The export runs on this PC's worker.</p>
      <div class="bx-run" data-bx-run></div>
      <div class="ba-btns"><button class="act pri" type="button" data-bx="go">⇪ Export</button><button class="act" type="button" data-bx="cancel">Close</button><span class="ba-status" data-bx-status></span></div></div>`;
  }
  function progressHTML(pct, msg) {
    const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
    return `<div class="bx-prog"><div class="bx-bar" role="progressbar" aria-valuenow="${p}" aria-valuemin="0" aria-valuemax="100"><i style="width:${p}%"></i></div><div class="bx-msg">${p}% · ${ESC(msg || "Working…")}</div></div>`;
  }
  function resultHTML(r, { canShow = false } = {}) {
    const files = (r.files || []).slice(0, 6);
    return `<div class="bx-done"><div class="bx-ok">✓ Exported${r.label ? ` · ${ESC(r.label)}` : ""}</div>`
      + `<div class="bx-path"><code data-bx-path>${ESC(r.main || r.dir || "")}</code></div>`
      + (r.notice ? `<div class="bx-notice">⚠ ${ESC(r.notice)}</div>` : "")
      + (files.length ? `<ul class="bx-files">${files.map(f => `<li><code>${ESC(f.path)}</code> <span class="mut">${ESC(fmtSize(f.size))}</span></li>`).join("")}${(r.files || []).length > files.length ? `<li class="mut">…${r.files.length - files.length} more</li>` : ""}</ul>` : "")
      + (canShow ? `<button class="act pri" type="button" data-bx="show">📂 Show in folder</button>` : `<p class="ba-note">Folder: ${ESC(r.dir || "")}</p>`) + "</div>";
  }
  function rememberDest(env, dest) {
    if (env.rememberDest) return env.rememberDest(dest);
    try { root.localStorage?.setItem(DEST_KEY, dest); } catch {}
  }
  function lastDest(env) {
    if (env.lastDest) return env.lastDest() || "";
    try { return root.localStorage?.getItem(DEST_KEY) || ""; } catch { return ""; }
  }

  // openExport(build, env = {document, api, here, pickFolder?(opts) -> path, showInFolder?(path), toast?, wait?})
  // -> the export's result (after Close), or null when closed before an export finished
  function openExport(b, env = {}) {
    const doc = env.document || root.document, here = hereOf(env);
    const wrap = doc.createElement("div");
    wrap.className = "ba-modal bx-modal";
    const style = `<style>${BA()?.CSS || ""}${CSS}</style>`;
    let formats = null, result = null, running = false, closed = false, chosen = "";
    wrap.innerHTML = style + exportDialogHTML(b, null, { dest: lastDest(env), canPick: !!env.pickFolder, here });
    doc.body.appendChild(wrap);
    const q = s => wrap.querySelector(s);
    const status = t => { const s = q("[data-bx-status]"); if (s) s.textContent = t; };
    const run = h => { const s = q("[data-bx-run]"); if (s) s.innerHTML = h; };
    const toast = env.toast || (() => {});
    return new Promise(resolve => {
      const done = () => { if (closed) return; closed = true; try { wrap.remove(); } catch {} resolve(result); };
      env.api(formatsPath(b)).then(f => { formats = f; if (!running && !result && !closed) { const d = q("[data-bx-dest]")?.value; wrap.innerHTML = style + exportDialogHTML(b, f, { dest: d ?? lastDest(env), canPick: !!env.pickFolder, here }); } },
                                   () => {});
      wrap.addEventListener("keydown", e => { if (e.key === "Escape") done(); });
      wrap.addEventListener("change", e => { if (e.target?.name === "bx-format") chosen = e.target.value; });
      wrap.addEventListener("click", async e => {
        const a = e.target?.closest?.("[data-bx]")?.dataset?.bx;
        if (a === "cancel" || e.target === wrap) return done();
        if (a === "pick" && env.pickFolder) {
          const cur = q("[data-bx-dest]")?.value || "";
          try { const p = await env.pickFolder({ title: `Export “${nameOf(b)}” to…`, defaultPath: cur }); if (p) { const i = q("[data-bx-dest]"); if (i) i.value = p; status(""); } }
          catch (err) { status("⚠ " + (err?.message || err)); }
          return;
        }
        if (a === "show" && result) { try { await env.showInFolder?.(result.main || result.dir); } catch (err) { status("⚠ " + (err?.message || err)); } return; }
        if (a !== "go" || running) return;
        if (!here) { status("⚠ No PC behind this view: open gBox on your PC to export there"); return; }
        const dest = String(q("[data-bx-dest]")?.value || "").trim();
        const format = q('input[name="bx-format"]:checked')?.value || chosen || "same";
        if (!dest) { status("⚠ Choose the folder on this PC to export to"); return; }
        const btn = q('[data-bx="go"]');
        running = true; if (btn) btn.disabled = true; status(""); result = null;
        run(progressHTML(0, "Queueing the export on this PC…"));
        try {
          const c = exportCall(b, here, dest, format, nameOf(b));
          const r = await env.api(c.path, c.body, "POST");
          rememberDest(env, dest);
          const j = await follow(env, r.job_id, (pct, msg) => { if (!closed) run(progressHTML(pct, msg)); }, { wait: env.wait || sleep });
          result = j.output?.result || {};
          if (closed) toast(`Exported ${nameOf(b)} to ${result.main || result.dir}`);
          else { run(resultHTML(result, { canShow: !!env.showInFolder })); status(""); const g = q('[data-bx="go"]'); if (g) { g.disabled = false; g.textContent = "⇪ Export again"; } }
          env.onExported?.(b, result);
        } catch (err) {
          const m = String(err?.message || err).slice(0, 400);
          if (closed) toast(`⚠ Export of ${nameOf(b)} failed: ${m}`);
          else { run(""); status("⚠ " + m); if (btn) btn.disabled = false; }
        } finally { running = false; }
      });
    });
  }

  // ---------------------------------------------------------------- one view's state: create(env, {redraw, note, toast})
  // env: {api, here, document?, pickFolder?, showInFolder?, openPath?, wait?, buildActions?}; hooks.redraw() redraws the
  // view, hooks.note(build, text) puts a line under the build
  function create(env, hooks = {}) {
    const L = { local: null, jobs: new Map(), over: new Map(), menu: null, at: 0 };
    const here = () => hereOf(env);
    const redraw = () => hooks.redraw && hooks.redraw();
    const note = (b, t) => hooks.note && hooks.note(b, t);
    const toast = t => (hooks.toast || env.toast || (() => {}))(t);
    const wait = env.wait || sleep;
    L.refresh = async (maxAge = 0) => {
      if (!here()) return null;
      if (L.local && Date.now() - L.at < maxAge) return L.local;
      try {
        const r = await env.api(`/api/builds/local?node=${enc(here())}`);
        if (r && r.builds) {
          L.local = r.builds; L.at = Date.now();
          for (const [k, v] of L.over) if (!!L.local[k] === v) L.over.delete(k);   // the heartbeat caught up
        }
      } catch {}
      return L.local;
    };
    L.state = b => stateOf(b, { here: here(), local: L.local, job: L.jobs.get(b.key), over: L.over });
    L.iconHTML = b => iconHTML(L.state(b), { open: L.menu === b.key, here: here() });
    L.menuHTML = b => L.menu === b.key ? menuHTML(b, L.state(b), here()) : "";
    L.download = async b => {
      if (!here()) { note(b, "Open gBox on your PC to download builds to it"); redraw(); return null; }
      if (L.jobs.get(b.key)?.op === "download") return null;
      L.menu = null;
      L.jobs.set(b.key, { op: "download", pct: 0, msg: "Queued on this PC" }); redraw();
      toast(`Downloading ${nameOf(b)} to this PC…`);
      try {
        const c = downloadCall(b, here());
        const r = await env.api(c.path, c.body, "POST");
        const j = await follow(env, r.job_id, (pct, msg) => { L.jobs.set(b.key, { op: "download", pct, msg }); redraw(); }, { wait });
        const out = j.output?.result || {};
        L.jobs.delete(b.key);
        L.over.set(b.key, true);
        const size = out.size != null ? ` (${fmtSize(out.size)})` : "";
        note(b, `⬇ On this PC${size}: it plays instantly, offline`);
        toast(`${nameOf(b)} is on this PC${size}: it plays instantly, offline`);
        redraw();
        return j;
      } catch (e) {
        L.jobs.delete(b.key);
        const m = String(e?.message || e).slice(0, 300);
        note(b, "⚠ Download failed: " + m); toast(`⚠ ${nameOf(b)}: download failed: ${m}`); redraw();
        return null;
      }
    };
    L.open = async b => {
      L.menu = null; redraw();
      try {
        const c = locateCall(b, here());
        const r = await env.api(c.path, c.body, "POST");
        const j = await follow(env, r.job_id, null, { wait });
        const dir = j.output?.result?.dir;
        if (!dir) { note(b, "Not on this PC (any more): download it again"); L.over.set(b.key, false); redraw(); return null; }
        if (env.openPath) await env.openPath(dir);
        else if (env.showInFolder) await env.showInFolder(dir);
        else { note(b, `Folder on this PC: ${dir}`); redraw(); }
        return dir;
      } catch (e) { note(b, "⚠ " + String(e?.message || e).slice(0, 300)); redraw(); return null; }
    };
    L.remove = async b => {
      L.menu = null; redraw();
      const ba = env.buildActions || BA();
      const where = (b.where || []).some(w => w.node === here()) ? b.where   // the dialog offers "Only this PC" when it lists it
        : [...(b.where || []), { where: "pc", node: here(), label: `${here()} (local copy)` }];
      const r = await ba.open("delete", { ...b, where },
                              { document: env.document || root.document, api: env.api, here: here(), onlyHere: true });
      if (!r) return null;
      L.over.set(b.key, false); L.at = 0;
      const text = ba.deleteResultText(b, r);
      note(b, text); toast(text); redraw();
      return r;
    };
    L.export = b => {
      L.menu = null; redraw();
      return openExport(b, { ...env, here: here(), onExported: (bb, res) => { L.over.set(bb.key, true); note(bb, `⇪ Exported to ${res.main || res.dir}`); redraw(); } });
    };
    // a click inside the icon or its menu: true when handled
    L.onClick = async (e, b) => {
      const a = e.target?.closest?.("[data-bl]")?.dataset?.bl;
      if (!a || !b) return false;
      e.preventDefault?.(); e.stopPropagation?.();
      const s = L.state(b);
      if (a === "main") {
        if (s.state === "off") await L.download(b);
        else if (s.state === "here") { L.menu = L.menu === b.key ? null : b.key; redraw(); }
        return true;
      }
      if (a === "menu") { L.menu = L.menu === b.key ? null : b.key; redraw(); return true; }
      if (a === "download") { await L.download(b); return true; }
      if (a === "export") { await L.export(b); return true; }
      if (a === "open") { await L.open(b); return true; }
      if (a === "delete") { await L.remove(b); return true; }
      return true;
    };
    // a right-click on the icon opens its menu (not the card's / row's own options)
    L.onContext = (e, b) => {
      if (!b || !e.target?.closest?.(".bl, [data-bl-menu]")) return false;
      e.preventDefault?.(); e.stopPropagation?.();
      if (hereOf(env)) { L.menu = b.key; redraw(); }
      return true;
    };
    L.close = () => { if (L.menu) { L.menu = null; redraw(); return true; } return false; };
    return L;
  }

  const CSS = `.bl{display:inline-flex;align-items:stretch;border-radius:8px;background:#000b;box-shadow:0 1px 4px #0008;overflow:hidden;line-height:1}
    .bl button{background:none;border:0;color:#fff;cursor:pointer;padding:4px 6px;display:inline-flex;align-items:center;gap:3px;font-size:11px}
    .bl button:hover:not(:disabled){background:#ffffff22}.bl button:disabled{cursor:default;opacity:.45}.bl-more{padding:4px 4px!important;border-left:1px solid #ffffff22!important;font-size:10px!important}
    .bl-here{color:#3ecf7a!important}.bl-busy{color:#7cc4ff!important}.bl-pct{color:#fff;font-weight:600;font-variant-numeric:tabular-nums}
    .bl-menu{display:flex;flex-direction:column;gap:3px;padding:6px;border:1px solid var(--line,#444);border-radius:8px;background:var(--bg,#16161a);box-shadow:0 8px 24px #000a;min-width:210px;z-index:6}
    .bl-menu .act{text-align:left}.bl-mh{font-size:11.5px;color:#9aa;padding:0 2px 3px;border-bottom:1px solid var(--line,#333);margin-bottom:2px}
    .bx-formats{display:flex;flex-direction:column;gap:2px;margin:6px 0 10px}.bx-opt{align-items:flex-start!important}.bx-opt>span{display:flex;flex-direction:column;align-items:flex-start}
    .bx-note{color:#9aa;font-size:11.5px}.bx-def{display:inline-block;font-size:10.5px;border:1px solid var(--acc,#7c96ff);border-radius:8px;padding:0 5px;margin-left:4px;color:var(--acc,#9fb2ff)}
    .bx-dest-l{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#9aa}.bx-dest-row{display:flex;gap:6px}.bx-dest{flex:1;font:12.5px monospace;min-width:0}
    .bx-prog{margin:8px 0}.bx-bar{height:8px;border-radius:4px;background:#ffffff14;overflow:hidden}.bx-bar i{display:block;height:100%;background:var(--acc,#7c96ff);transition:width .3s}
    .bx-msg{font-size:12px;color:#9aa;margin-top:4px;overflow-wrap:anywhere}.bx-done{margin:8px 0;padding:8px;border:1px solid #2f9a5a;border-radius:8px;background:#1f6f3f22}
    .bx-ok{font-weight:600;color:#7fe0a6}.bx-path code{overflow-wrap:anywhere;font-size:12px}.bx-notice{margin:6px 0;color:#e3c46a;font-size:12px}
    .bx-files{margin:6px 0;padding-left:16px;font-size:11.5px}`;

  const api = { stateOf, iconHTML, iconTitle, menuHTML, exportDialogHTML, progressHTML, resultHTML, downloadCall, locateCall, exportCall,
                formatsPath, follow, openExport, create, hereOf, CSS, TITLES };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxBuildLocal = api;
})(typeof window !== "undefined" ? window : globalThis);
