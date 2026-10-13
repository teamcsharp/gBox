/* Pick whip (live picker / eyedropper, docs/live-picker.md): the shared half of the desktop app's eyedropper + right-click
   character menu and the web viewer's pick overlay.
   - preselection: the thing under the cursor gets an outline (backend silhouette / mask / entity bounds when the picker has
     them, else the colour region at the projected entity, else a box around its screen position) and a label;
     hover requests are latest-wins (one in flight), the outline eases toward its target, the game is never blocked
   - pause hold: the game pauses while the pick whip is open (POST /api/pickwhip/{sid}/hold, gbox/pickwhip.py); the
     server's lease watchdog resumes it when the client goes away
   - tools with graceful degradation: pick_identify -> pick_preview, pick_replace live -> build -> the existing
     characters live_use / rebuild request paths, pick_name (local LLM) -> the picker's own evidence
   - the mini console: small floating panels next to the pick, one per task, streaming job progress and fit events
   Shared verbatim by the web shell (/viz/pick-whip.js) and the desktop app (../web/viz/pick-whip.js). */
(function (root, factory) {
  const lib = factory(root);
  if (typeof module === "object" && module.exports) module.exports = lib;
  else root.GBoxPickWhip = lib;
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const PICTURE = 4 / 3;                                   // the picker projects into a 4:3 picture centred in the window
  const clamp01 = v => Math.max(0, Math.min(1, v));

  // ---- settings (per viewer) ----------------------------------------------------------------------------------------
  const DEFAULTS = { pause: true, rclick: true, cloud: false, name: true };
  function settings(store) {
    let s = {};
    try { s = JSON.parse((store || env.localStorage)?.getItem("gbox_pickwhip") || "{}") || {}; } catch {}
    return Object.assign({}, DEFAULTS, s);
  }
  function saveSettings(patch, store) {
    const s = Object.assign(settings(store), patch);
    try { (store || env.localStorage)?.setItem("gbox_pickwhip", JSON.stringify(s)); } catch {}
    return s;
  }

  // ---- geometry: window fractions <-> the picker's 4:3 picture -------------------------------------------------------
  function windowToPicture(p, aspect) {
    let [x, y] = p;
    if (aspect > PICTURE) { const w = PICTURE / aspect; x = (x - (1 - w) / 2) / w; }
    else if (aspect < PICTURE) { const h = aspect / PICTURE; y = (y - (1 - h) / 2) / h; }
    return [x, y];
  }
  function pictureToWindow(p, aspect) {
    let [x, y] = p;
    if (aspect > PICTURE) { const w = PICTURE / aspect; x = x * w + (1 - w) / 2; }
    else if (aspect < PICTURE) { const h = aspect / PICTURE; y = y * h + (1 - h) / 2; }
    return [x, y];
  }
  const clampBox = b => [clamp01(Math.min(b[0], b[2])), clamp01(Math.min(b[1], b[3])), clamp01(Math.max(b[0], b[2])), clamp01(Math.max(b[1], b[3]))];
  const boxArea = b => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const boxContains = (b, p, pad = 0) => p[0] >= b[0] - pad && p[0] <= b[2] + pad && p[1] >= b[1] - pad && p[1] <= b[3] + pad;
  function bboxOf(pts) {
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    return clampBox([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
  }
  const regionUsable = r => !!(r && r.box && boxArea(r.box) > 0.0004 && boxArea(r.box) < 0.5);

  // colour flood fill on a small copy of the frozen frame (the pre-selection when the picker knows nothing about the game)
  function floodRegion(px, W, H, at, tol = 34) {
    const d = px.data || px, x0 = Math.min(W - 1, Math.max(0, Math.floor(at[0] * W))), y0 = Math.min(H - 1, Math.max(0, Math.floor(at[1] * H)));
    const i0 = (y0 * W + x0) * 4, ref = [d[i0], d[i0 + 1], d[i0 + 2]], t2 = tol * tol * 3;
    const mask = new Uint8Array(W * H), st = [y0 * W + x0]; mask[st[0]] = 1;
    let n = 0, bx0 = x0, by0 = y0, bx1 = x0, by1 = y0;
    while (st.length && n < W * H * 0.45) {
      const p = st.pop(), x = p % W, y = (p / W) | 0; n++;
      if (x < bx0) bx0 = x; if (x > bx1) bx1 = x; if (y < by0) by0 = y; if (y > by1) by1 = y;
      for (const q of [x > 0 ? p - 1 : -1, x < W - 1 ? p + 1 : -1, y > 0 ? p - W : -1, y < H - 1 ? p + W : -1]) {
        if (q < 0 || mask[q]) continue;
        const j = q * 4, dr = d[j] - ref[0], dg = d[j + 1] - ref[1], db = d[j + 2] - ref[2];
        if (dr * dr + dg * dg + db * db < t2) { mask[q] = 1; st.push(q); }
      }
    }
    return { mask, W, H, n, ref, at: [x0, y0], box: [bx0 / W, by0 / H, (bx1 + 1) / W, (by1 + 1) / H] };
  }

  function decodeMask(m) {                                  // backend mask: {w, h, b64 | data}: one byte per pixel, nonzero = inside
    let bytes = m.data;
    if (!bytes && m.b64) {
      const bin = typeof env.atob === "function" ? env.atob(m.b64) : Buffer.from(m.b64, "base64").toString("binary");
      bytes = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    }
    const out = new Uint8Array(m.w * m.h);
    for (let i = 0; i < out.length; i++) out[i] = bytes[i] ? 1 : 0;
    return out;
  }
  function maskBox(mask, W, H) {
    let x0 = W, y0 = H, x1 = -1, y1 = -1;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (mask[y * W + x]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    return x1 < 0 ? null : [x0 / W, y0 / H, (x1 + 1) / W, (y1 + 1) / H];
  }

  // The silhouette outline of a mask: the edges between inside and outside cells, merged into runs ([x0, y0, x1, y1] in
  // mask cells). clip (window fractions) keeps only cells inside the entity's box: the colour region cut to the character.
  function maskEdges(mask, W, H, clip) {
    const cx0 = clip ? Math.floor(clip[0] * W) : 0, cy0 = clip ? Math.floor(clip[1] * H) : 0;
    const cx1 = clip ? Math.ceil(clip[2] * W) : W, cy1 = clip ? Math.ceil(clip[3] * H) : H;
    const inside = (x, y) => x >= cx0 && x < cx1 && y >= cy0 && y < cy1 && x >= 0 && y >= 0 && x < W && y < H && !!mask[y * W + x];
    const segs = [];
    for (let y = cy0; y <= cy1; y++) {                       // horizontal edges (between row y-1 and row y)
      let run = -1;
      for (let x = cx0; x <= cx1; x++) {
        const edge = x < cx1 && inside(x, y - 1) !== inside(x, y);
        if (edge && run < 0) run = x;
        if (!edge && run >= 0) { segs.push([run, y, x, y]); run = -1; }
      }
    }
    for (let x = cx0; x <= cx1; x++) {                       // vertical edges (between column x-1 and column x)
      let run = -1;
      for (let y = cy0; y <= cy1; y++) {
        const edge = y < cy1 && inside(x - 1, y) !== inside(x, y);
        if (edge && run < 0) run = y;
        if (!edge && run >= 0) { segs.push([x, run, x, y]); run = -1; }
      }
    }
    return segs;
  }

  // What to outline: the best shape the evidence supports, in window fractions.
  //  polygon  backend outline/silhouette (screen-space mesh projection)  mask  backend mask
  //  bounds   the entity's projected bounds (+ the colour region inside them)  region  colour region at the entity
  //  point    a character-sized box around the projected position             (null: nothing to show)
  // Entity-probe picks (gbox/entity_probe.py) give screen / screen_box in pixels of the picker's frame (640x480 unless
  // the result says otherwise): those are scaled to fractions first.
  function pickFrame(res) {
    if (Array.isArray(res.frame) && res.frame[0] > 0 && res.frame[1] > 0) return res.frame;
    const c = res.click, px = res.click_px;
    if (Array.isArray(c) && Array.isArray(px) && c[0] > 0.01 && c[1] > 0.01) return [px[0] / c[0], px[1] / c[1]];
    return [640, 480];
  }
  function outlineOf(preview, region, aspect = PICTURE) {
    const res = preview || {}, ent = (res.entity && typeof res.entity === "object") ? res.entity : {};
    const pk = (res.picked && typeof res.picked === "object") ? res.picked : {};
    const win = (res.space || ent.space) === "window";
    const frame = pickFrame(res);
    const frac = v => Array.isArray(v) && v.some(n => Math.abs(n) > 1.5) ? v.map((n, i) => n / frame[i % 2]) : v;
    const toWin = p => win ? [p[0], p[1]] : pictureToWindow(p, aspect);
    const poly = res.outline || res.silhouette || ent.outline || ent.silhouette;
    if (Array.isArray(poly) && poly.length >= 3) {
      const pts = poly.map(toWin);
      return { kind: "polygon", poly: pts, box: bboxOf(pts), source: "projected mesh outline" };
    }
    const m = res.mask || ent.mask;
    if (m && m.w && m.h && (m.b64 || m.data)) {
      const mask = decodeMask(m), mb = maskBox(mask, m.w, m.h);
      if (mb) {
        const box = win ? mb : clampBox([...toWin([mb[0], mb[1]]), ...toWin([mb[2], mb[3]])]);
        return { kind: "mask", mask, W: m.w, H: m.h, box, maskSpace: win ? "window" : "picture", source: "entity mask" };
      }
    }
    const b = frac(res.bounds || res.screen_box || ent.bounds || ent.screen_box || pk.screen_box);
    if (Array.isArray(b) && b.length === 4 && b.every(Number.isFinite)) {
      const box = clampBox([...toWin([b[0], b[1]]), ...toWin([b[2], b[3]])]);
      const reg = regionUsable(region) && boxArea(box) > 0 ? region : null;
      return { kind: "bounds", box, region: reg, source: "entity bounds" };
    }
    const sp = frac(res.screen || ent.screen || pk.screen);
    if (Array.isArray(sp) && sp.length >= 2 && sp.every(Number.isFinite)) {
      const p = toWin(sp);
      if (regionUsable(region) && boxContains(region.box, p, 0.04))
        return { kind: "region", box: region.box, region, anchor: p, source: "colour region at the entity" };
      return { kind: "point", box: clampBox([p[0] - 0.06, p[1] - 0.17, p[0] + 0.06, p[1] + 0.13]), anchor: p, source: "projected entity position" };
    }
    if (regionUsable(region)) return { kind: "region", box: region.box, region, source: "colour region" };
    return null;
  }

  // the outline eases toward its target (no jumps while the cursor moves); k: 0..1 per frame
  function easeBox(cur, target, dtMs, tauMs = 70) {
    if (!cur) return target.slice();
    const k = 1 - Math.exp(-Math.max(0, dtMs) / tauMs);
    return cur.map((v, i) => v + (target[i] - v) * k);
  }

  // ---- labels ------------------------------------------------------------------------------------------------------------
  function modelText(m) {
    if (!m) return "";
    if (Array.isArray(m)) return m.filter(Boolean).join(" / ");
    if (typeof m === "object") return m.name || m.file || m.path || "";
    return String(m);
  }
  // name, model, slot from whatever is known: the local model's answer > pick_identify > pick_preview
  function labelOf(preview, ident, named) {
    const p = (preview && preview.picked) || {}, i = ident || {}, ie = (i.entity && typeof i.entity === "object") ? i.entity : {}, n = named || {};
    const name = n.name || i.name || ie.name || p.name || p.class || ie.class || "";
    const model = n.model || modelText(i.model) || modelText(ie.model) || modelText(preview && preview.model);
    const slot = n.slot || i.slot || ie.slot || p.slot || "";
    const kind = n.kind || i.kind || ie.kind || p.kind || "";
    const id = p.entity_id ?? ie.entity_id ?? ie.id;
    const ram = p.ptr || ie.ptr || (Array.isArray(i.ram) ? (i.ram[0] && (i.ram[0].address || i.ram[0])) : i.ram) || "";
    const via = n.route ? (n.route === "evidence" ? "picker evidence" : `${n.llm_model || "model"} (${n.route})`) : (ident ? "pick_identify" : preview ? "pick_preview" : "");
    return { name: String(name || "something"), model: String(model || ""), slot: String(slot || ""), kind: String(kind || ""),
      id: id == null ? "" : String(id), ram: String(ram || ""), via, known: !!name };
  }
  const labelHTML = l => `<b>${ESC(l.name)}</b>${l.kind ? ` <i>${ESC(l.kind)}</i>` : ""}` +
    `${l.model || l.slot ? `<span>${[l.model && "model " + l.model, l.slot && "slot " + l.slot].filter(Boolean).map(ESC).join(" · ")}</span>` : ""}`;

  // ---- hover: latest wins, one request in flight, stale answers dropped ----------------------------------------------
  function createHover({ request, apply, minMs = 120, now = () => Date.now(), later = (f, ms) => setTimeout(f, ms) }) {
    let pending = null, busy = false, seq = 0, shown = 0, last = 0, timer = null, dead = false;
    async function run() {
      timer = null;
      if (busy || !pending || dead) return;
      const wait = minMs - (now() - last);
      if (wait > 0) { timer = later(run, wait); return; }
      const at = pending, my = ++seq; pending = null; busy = true; last = now();
      try {
        const r = await request(at);
        if (!dead && my > shown && !pending) { shown = my; apply(r, at); }
        else if (!dead && my > shown && pending) shown = my;        // the cursor moved on: the next answer paints
      } catch { /* hover never throws at the operator */ }
      finally { busy = false; if (pending && !timer && !dead) run(); }
    }
    return {
      move(at) { pending = at; if (!busy && !timer) run(); },
      stop() { dead = true; pending = null; },
      get busy() { return busy; },
    };
  }

  // ---- jobs ----------------------------------------------------------------------------------------------------------
  // io.api(path, body?) resolves with the answer's data and rejects with an Error (the desktop wraps gbox.api, the web
  // shell's api() already works this way). A tool the control plane doesn't know yet answers 404 "unknown tool".
  const missingTool = e => /unknown tool|404/i.test(String((e && e.message) || e || ""));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function startJob(io, tool, input, extra = {}) {
    try { return await io.api("/api/jobs", Object.assign({ tool, input }, extra)); }
    catch (e) { if (missingTool(e)) { const err = new Error(`${tool} is not available on this gBox yet`); err.missing = true; err.tool = tool; throw err; } throw e; }
  }
  async function waitJob(io, job, { onUpdate, ms = 400, max = 3000, wait = io.sleep || sleep } = {}) {
    let j = job;
    if (onUpdate) onUpdate(j);
    for (let i = 0; i < max && j && ["queued", "running"].includes(j.state); i++) {
      await wait(ms);
      try { j = await io.api("/api/jobs/" + j.id); } catch { continue; }    // a lost poll is retried, never fatal
      if (onUpdate) onUpdate(j);
    }
    return j;
  }
  const jobResult = j => (j && j.output && (j.output.result || j.output)) || {};
  const sessionWorker = sid => String(sid || "").split("-")[0];

  async function runTool(io, tool, input, opts = {}) {
    const extra = opts.extra || (input.session_id ? { require_worker: sessionWorker(input.session_id) } : {});
    const job = await startJob(io, tool, input, extra);
    if (opts.onJob) opts.onJob(job, tool);
    const j = await waitJob(io, job, opts);
    return { job: j, result: jobResult(j), ok: j.state === "succeeded" };
  }

  // Identify: pick_identify (entity, model, RAM, Ghidra/REA evidence, slot) when the control plane has it, else pick_preview.
  async function identify(io, { sid, x, y, aspect = PICTURE, onJob, onUpdate, deep = true, log = () => {} }) {
    const input = { session_id: sid, x: +(+x).toFixed(4), y: +(+y).toFixed(4) };
    if (deep) {
      try {
        const r = await runTool(io, "pick_identify", input, { onJob, onUpdate });
        if (r.ok) return { source: "pick_identify", result: r.result, job: r.job };
        if (r.job && r.job.error) log(`pick_identify: ${r.job.error}`);
      } catch (e) { if (!e.missing) throw e; log("pick_identify is not on this gBox yet: using pick_preview"); }
    }
    const r = await runTool(io, "pick_preview", Object.assign({ window_aspect: aspect }, input), { onJob, onUpdate });
    if (!r.ok) throw new Error((r.job && r.job.error) || "pick_preview failed");
    return { source: "pick_preview", result: r.result, job: r.job };
  }

  // Name it with the local model the app is set to (the header), tool calls for pick_preview / pick_identify; runs on
  // the Spark next to the model (require_os linux). null when the tool isn't there yet.
  async function nameLocal(io, { sid, x, y, aspect = PICTURE, evidence, model, image, allowCloud = false, onJob, onUpdate }) {
    try {
      const r = await runTool(io, "pick_name", { target_session: sid, x, y, window_aspect: aspect, evidence: evidence || {},
        image_b64: image || "", model: model || "", allow_cloud: !!allowCloud }, { extra: { require_os: "linux" }, onJob, onUpdate });
      return r.ok ? r.result : null;
    } catch (e) { if (e.missing) return null; throw e; }
  }

  const FAILED = /unsupported|failed|error|not_in_collection|missing|blocked|reverted|no writer/i;
  // Replace: pick_replace live -> pick_replace build; before pick_replace exists: fallbackLive (characters live_use) and
  // fallbackBuild (the rebuild request). steps says what was tried, for the console and the failure report.
  async function replace(io, { sid, pick, character, x, y, onJob, onUpdate, fallbackLive, fallbackBuild, log = () => {} }) {
    const steps = [];
    const attempt = async mode => {
      const r = await runTool(io, "pick_replace", { session_id: sid, pick: pick || { x, y }, character, mode }, { onJob, onUpdate });
      const status = String(r.result.status || "");
      const ok = r.ok && !FAILED.test(status);
      steps.push({ via: "pick_replace", mode, ok, status: status || r.job.state, error: r.job.error || "" });
      return Object.assign({}, r, { mode, ok, via: "pick_replace" });   // ok = the job succeeded AND the swap took
    };
    let live;
    try { live = await attempt("live"); }
    catch (e) {
      if (!e.missing) throw e;
      log("pick_replace is not on this gBox yet: trying the character live swap");
      if (fallbackLive) {
        try {
          const res = await fallbackLive();
          const ok = !FAILED.test(String(res && res.status || "")) && !(res && res.error);
          steps.push({ via: "characters live_use", mode: "live", ok, status: (res && (res.status || res.message)) || "" });
          if (ok) return { mode: "live", ok: true, via: "characters live_use", result: res, steps };
        } catch (err) { steps.push({ via: "characters live_use", mode: "live", ok: false, error: err.message }); }
      }
      log("live swap unavailable here: asking for a build");
      const res = fallbackBuild ? await fallbackBuild(steps) : null;
      steps.push({ via: "rebuild request", mode: "build", ok: !!res, status: res ? "requested" : "not available" });
      return { mode: "build", ok: !!res, via: "rebuild request", result: res, steps };
    }
    if (live.ok) return Object.assign(live, { steps });
    log(`live replacement ${live.job.state === "succeeded" ? live.result.status || "did not take" : "failed"}: building instead`);
    const built = await attempt("build");
    if (built.ok) return Object.assign(built, { steps });
    const res = fallbackBuild ? await fallbackBuild(steps) : null;
    if (res) steps.push({ via: "rebuild request", mode: "build", ok: true, status: "requested" });
    return Object.assign(built, { ok: !!res, steps, request: res });
  }

  // ---- the character browser: who can replace this, best first ---------------------------------------------------------
  const VEHICLE = /vehicle|car|kart|bike|ship/i;
  function rankCharacters(chars, { gid = "", kind = "" } = {}) {
    const wantVehicle = VEHICLE.test(kind);
    const rows = [];
    for (const c of chars || []) {
      if (!c || !c.slug) continue;
      const ck = String(c.kind || "character");
      if (wantVehicle !== VEHICLE.test(ck)) continue;                  // a vehicle for a vehicle, a body for a body
      if (!wantVehicle && !/character|player|npc|enemy|creature|fighter/i.test(ck)) continue;
      const ready = (c.ready || []).length > 0;
      const fitted = gid && c.targets && (c.targets[gid] || []).length > 0;
      const tier = ready ? 0 : fitted ? 1 : c.model ? 2 : 3;
      rows.push({ c, tier, note: ["ready in this game", "fitted before (rebuilds)", "builds for this game", "no model yet"][tier] });
    }
    rows.sort((a, b) => a.tier - b.tier || String(a.c.name).localeCompare(String(b.c.name)));
    return rows;
  }

  // ---- the menu ------------------------------------------------------------------------------------------------------
  function menuItems({ label, asset, canBlender = true, extra = [] } = {}) {
    const who = label && label.known ? label.name : "this character";
    return [
      { id: "replace", icon: "⇄", text: `Replace ${who} with…`, hint: "live when the game allows it, else a build" },
      { id: "copy", icon: "⧉", text: "Copy to clipboard", hint: asset ? "model + identification" : "identification (extracts the model when it can)" },
      { id: "blender", icon: "⬈", text: "Copy to Blender", hint: "Ctrl+V in a Blender 3D viewport", disabled: !canBlender },
      { id: "retarget", icon: "✎", text: "Open retarget editor…", hint: "how a donor fits this slot" },
      { id: "identify", icon: "⌕", text: "Identify", hint: "model, RAM, Ghidra/REA evidence, slot" },
      { id: "export", icon: "⇪", text: "Export to Blender (round trip)", hint: "gBox add-on: Ctrl+Shift+V, edit, Send to gBox" },
      { id: "assets", icon: "▤", text: "Show in Assets", hint: "" },
    ].concat(extra);
  }

  // ---- console lines from a job: progress log, fit events, the end --------------------------------------------------
  function fitLines(job) {
    const f = job && job.fitting;
    if (!f || !f.models || !Array.isArray(f.order)) return [];
    return f.order.filter(k => f.models[k]).map(k => {
      const m = f.models[k], st = m.stages || {}, names = Object.keys(st);
      const cur = m.current || names[names.length - 1] || "";
      const s = st[cur] || {};
      return `◆ ${m.label || k}: ${cur || "queued"} ${s.state || m.state || ""}`.trim();
    });
  }
  function consoleLines(job, max = 10) {
    if (!job) return [];
    const log = (job.progress_log || []).filter(Boolean).map(String);
    const msg = job.progress && job.progress.msg;
    if (msg && log[log.length - 1] !== msg) log.push(String(msg));
    const out = log.slice(-max).concat(fitLines(job).slice(-4));
    if (job.state === "failed" || job.state === "rejected" || job.state === "cancelled") out.push(`✗ ${job.error || job.state}`);
    else if (job.state === "succeeded") {
      const r = jobResult(job);
      out.push(`✓ ${String(r.message || r.status || (r.name ? "named: " + r.name : "") || (r.picked ? "found " + (r.picked.class || r.picked.kind) : "") || "done").slice(0, 200)}`);
    }
    return out;
  }
  const jobPct = j => j && j.state === "succeeded" ? 100 : Math.max(0, Math.min(100, +((j && j.progress && j.progress.pct) || 0)));

  // ---- DOM: css, outline painter, menu, browser, console -----------------------------------------------------------
  const CSS = `
  .pw-label { position:fixed; z-index:96; pointer-events:none; background:#101318e6; color:#e8ecff; border:1px solid #7c96ff;
    border-radius:6px; padding:3px 8px; font:12px/1.35 system-ui,sans-serif; max-width:300px; box-shadow:0 4px 14px #0008;
    transition:left .08s linear, top .08s linear; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
  .pw-label b { color:#fff } .pw-label i { color:#9fb3ff; font-style:normal; margin-left:4px } .pw-label span { display:block; color:#aab3cc; font-size:11px }
  .pw-label em { display:block; color:#7f8aa8; font-size:10px; font-style:normal }
  #pwmenu { position:fixed; z-index:98; min-width:250px; max-width:340px; background:var(--bg,#16171c); color:var(--fg,#e8e8ee);
    border:1px solid var(--line,#333); border-radius:8px; padding:6px; box-shadow:0 10px 30px #000a; font:13px system-ui,sans-serif }
  #pwmenu .pw-head { padding:4px 6px 6px; border-bottom:1px solid var(--line,#333); margin-bottom:4px }
  #pwmenu .pw-head .mut, #pwmenu small { color:var(--mut,#999); font-size:11px }
  #pwmenu button { display:flex; gap:8px; align-items:baseline; width:100%; text-align:left; background:none; border:0; color:inherit;
    padding:5px 6px; border-radius:5px; cursor:pointer; font:inherit }
  #pwmenu button:hover, #pwmenu button:focus { background:var(--card,#23252c); outline:none }
  #pwmenu button[disabled] { opacity:.45; cursor:default }
  #pwmenu button > span:first-child { width:16px; text-align:center; flex:none }
  #pwmenu button small { margin-left:auto; padding-left:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:140px }
  #pwmenu hr { border:0; border-top:1px solid var(--line,#333); margin:4px 0 }
  #pwmenu .pw-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; max-height:340px; overflow:auto; margin-top:6px }
  #pwmenu .pw-grid button { flex-direction:column; align-items:stretch; padding:4px; border:1px solid var(--line,#333) }
  #pwmenu .pw-grid img { width:100%; aspect-ratio:1; object-fit:contain; background:#26282f; border-radius:4px }
  #pwmenu .pw-grid small { margin:0; max-width:none; white-space:normal; font-size:10px; color:var(--mut,#999) }
  #pwmenu .pw-grid .t0 { border-color:#3fb950 } #pwmenu .pw-grid .t3 { opacity:.5 }
  #pwmenu input[type=search] { width:100%; box-sizing:border-box; margin-top:6px }
  #pwcon { position:fixed; z-index:97; width:300px; display:flex; flex-direction:column; gap:6px; font:11px/1.35 ui-monospace,Consolas,monospace }
  #pwcon .pwc { background:#0d0f14ee; color:#d8deea; border:1px solid #2c3242; border-radius:7px; box-shadow:0 6px 18px #0009; overflow:hidden }
  #pwcon .pwc-h { display:flex; gap:6px; align-items:center; padding:4px 6px; background:#161a24; cursor:move; font:12px system-ui,sans-serif }
  #pwcon .pwc-h b { flex:1; overflow:hidden; white-space:nowrap; text-overflow:ellipsis }
  #pwcon .pwc-h button { background:none; border:0; color:#aab3cc; cursor:pointer; padding:0 3px; font:inherit }
  #pwcon .pwc-s { font-size:10px; padding:1px 5px; border-radius:8px; background:#2c3242 }
  #pwcon .pwc[data-state=succeeded] .pwc-s { background:#1f5130 } #pwcon .pwc[data-state=failed] .pwc-s { background:#6b1f24 }
  #pwcon .pwc-bar { height:2px; background:#7c96ff; transition:width .3s }
  #pwcon pre { margin:0; padding:5px 7px; max-height:150px; overflow:auto; white-space:pre-wrap; word-break:break-word }
  #pwcon .pwc.min pre { display:none }`;
  function ensureCss(doc) {
    if (!doc || doc.getElementById("pw-css")) return;
    const s = doc.createElement("style"); s.id = "pw-css"; s.textContent = CSS; doc.head.append(s);
  }

  // paint the outline over a canvas (the frozen frame is already drawn); w,h = canvas pixels
  function paintOutline(c, o, box, w, h, { color = "#7c96ff", t = 0, aspect = PICTURE } = {}) {
    if (!o || !box) return;
    const lw = Math.max(2, w / 360);
    c.save();
    c.fillStyle = "rgba(0,0,0,0.28)";                         // dim everything but the character
    c.beginPath(); c.rect(0, 0, w, h);
    c.rect(box[0] * w, box[1] * h, (box[2] - box[0]) * w, (box[3] - box[1]) * h); c.fill("evenodd");
    c.strokeStyle = color; c.lineWidth = lw; c.shadowColor = color; c.shadowBlur = 8;
    const reg = o.kind === "mask" ? { mask: o.mask, W: o.W, H: o.H } : o.region;
    if (o.kind === "polygon") {
      c.beginPath(); o.poly.forEach((p, i) => i ? c.lineTo(p[0] * w, p[1] * h) : c.moveTo(p[0] * w, p[1] * h)); c.closePath(); c.stroke();
    } else if (reg && reg.mask) {
      const segs = maskEdges(reg.mask, reg.W, reg.H, o.kind === "mask" ? null : box);
      const map = o.maskSpace === "picture" ? (x, y) => pictureToWindow([x / reg.W, y / reg.H], aspect) : (x, y) => [x / reg.W, y / reg.H];
      c.beginPath();
      for (const [x0, y0, x1, y1] of segs) { const a = map(x0, y0), b = map(x1, y1); c.moveTo(a[0] * w, a[1] * h); c.lineTo(b[0] * w, b[1] * h); }
      c.stroke();
    }
    if (o.kind !== "polygon" && o.kind !== "mask") {          // corner brackets: the box the silhouette is cut to
      const x0 = box[0] * w, y0 = box[1] * h, x1 = box[2] * w, y1 = box[3] * h, k = Math.min(18, (x1 - x0) / 3, (y1 - y0) / 3);
      c.setLineDash(reg ? [] : [6, 4]); c.lineDashOffset = -t / 40;
      c.beginPath();
      for (const [x, y, dx, dy] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) {
        c.moveTo(x + dx * k, y); c.lineTo(x, y); c.lineTo(x, y + dy * k);
      }
      if (!reg) c.rect(x0, y0, x1 - x0, y1 - y0);
      c.stroke();
    }
    c.restore();
  }

  function placeLabel(doc, el, rect, box, l) {               // rect = the game picture on screen (px); box = window fractions
    if (!l) { el.style.display = "none"; return; }
    el.innerHTML = labelHTML(l) + (l.via ? `<em>${ESC(l.via)}</em>` : "");
    el.style.display = "block";
    const x = rect.x + box[0] * rect.w, y = rect.y + box[1] * rect.h - 6;
    const vw = (doc.defaultView || env).innerWidth || 1e4;
    el.style.left = Math.max(4, Math.min(vw - 310, x)) + "px";
    el.style.top = Math.max(4, y - (el.offsetHeight || 34)) + "px";
  }

  function openMenu(doc, { x, y, head, items, onPick, place }) {
    ensureCss(doc);
    let m = doc.getElementById("pwmenu");
    if (!m) { m = doc.createElement("div"); m.id = "pwmenu"; m.setAttribute("role", "menu"); doc.body.append(m); }
    m.innerHTML = `<div class="pw-head">${head || ""}</div>` + items.map(it => it === "-" ? "<hr>" :
      `<button role="menuitem" data-pw="${ESC(it.id)}"${it.disabled ? " disabled" : ""}${it.hint ? ` title="${ESC(it.hint)}"` : ""}><span>${ESC(it.icon || "")}</span>${ESC(it.text)}${it.small ? `<small>${ESC(it.small)}</small>` : ""}</button>`).join("");
    m.style.display = "block"; m.style.left = x + "px"; m.style.top = y + "px";
    if (place) place(m, x, y);
    m.onclick = e => { const b = e.target.closest && e.target.closest("button[data-pw]"); if (b && !b.disabled) onPick(b.dataset.pw, b, m); };
    return m;
  }
  function setMenuHead(doc, html) { const h = doc.getElementById("pwmenu")?.querySelector(".pw-head"); if (h) h.innerHTML = html; }
  function closeMenu(doc) { const m = doc.getElementById("pwmenu"); if (m) { m.style.display = "none"; m.innerHTML = ""; } }

  // the character browser inside the menu: previews, compatibility tiers, a filter box
  function browser(m, { title, rows, img, onPick }) {
    const draw = q => {
      const shown = rows.filter(r => !q || `${r.c.name} ${r.c.slug} ${(r.c.source || {}).game_title || ""}`.toLowerCase().includes(q));
      grid.innerHTML = shown.map(r => `<button class="t${r.tier}" data-slug="${ESC(r.c.slug)}" title="${ESC(r.c.name)} · ${ESC(r.note)}${r.c.source?.game_title ? " · from " + ESC(r.c.source.game_title) : ""}"${r.tier === 3 ? " disabled" : ""}>` +
        `<img alt="" loading="lazy" src="${ESC(img(r.c))}"><span>${ESC(r.c.name)}</span><small>${ESC(r.note)}</small></button>`).join("")
        || `<p class="mut">No compatible characters${q ? " match" : " in the collection yet"}.</p>`;
    };
    m.innerHTML = `<div class="pw-head"><b>${ESC(title)}</b><div class="mut">${rows.length} compatible · best fits first</div>` +
      `<input type="search" placeholder="Filter characters…" aria-label="Filter characters"></div><div class="pw-grid"></div>`;
    const grid = m.querySelector(".pw-grid"), q = m.querySelector("input");
    q.oninput = () => draw(q.value.trim().toLowerCase());
    m.onclick = e => { const b = e.target.closest && e.target.closest(".pw-grid button[data-slug]"); if (!b || b.disabled) return;
      const r = rows.find(x => x.c.slug === b.dataset.slug); if (r) onPick(r.c, r); };
    draw("");
    setTimeout(() => { try { q.focus(); } catch {} }, 0);
  }

  // mini console: one small panel per task, stacked next to the picked character
  function createConsole(doc, { drag } = {}) {
    ensureCss(doc);
    const panels = new Map();
    let box = doc.getElementById("pwcon");
    if (!box) { box = doc.createElement("div"); box.id = "pwcon"; box.setAttribute("aria-live", "polite"); doc.body.append(box); if (drag) drag(box); }
    function anchor(x, y) {
      const vw = (doc.defaultView || env).innerWidth || 1e4, vh = (doc.defaultView || env).innerHeight || 1e4;
      box.style.left = Math.max(6, Math.min(vw - 306, x)) + "px"; box.style.top = Math.max(40, Math.min(vh - 120, y)) + "px";
    }
    function open(id, title) {
      let p = panels.get(id);
      if (!p) {
        const el = doc.createElement("div"); el.className = "pwc"; el.dataset.id = id; el.dataset.state = "queued";
        el.innerHTML = `<div class="pwc-h"><b></b><span class="pwc-s">queued</span><button data-c="min" title="Collapse">▾</button><button data-c="x" title="Close">✕</button></div><div class="pwc-bar" style="width:0"></div><pre></pre>`;
        el.querySelector("b").textContent = title;
        el.onclick = e => { const c = e.target.dataset && e.target.dataset.c; if (c === "min") el.classList.toggle("min"); if (c === "x") close(id); };
        box.append(el);
        p = { el, lines: [], job: null, extra: [] };
        panels.set(id, p);
      }
      const h = {
        id,
        log(text) { p.lines.push(String(text)); paint(); return h; },
        update(job) { p.job = job; paint(); return h; },
        lines(arr) { p.extra = (arr || []).map(String); paint(true); return h; },  // a live view (e.g. the chat agent's last steps)
        done(ok, text) { if (text) p.lines.push((ok ? "✓ " : "✗ ") + text); p.el.dataset.state = ok ? "succeeded" : "failed";
          p.el.querySelector(".pwc-s").textContent = ok ? "done" : "failed"; p.el.querySelector(".pwc-bar").style.width = "100%"; paint(true); return h; },
        title(t) { p.el.querySelector("b").textContent = t; return h; },
        collapse(on = true) { p.el.classList.toggle("min", on); return h; },
      };
      function paint(keepState) {
        const j = p.job, lines = (j ? consoleLines(j) : []).concat(p.lines, p.extra).slice(-14);
        const pre = p.el.querySelector("pre"); pre.textContent = lines.join("\n"); pre.scrollTop = pre.scrollHeight;
        if (j && !keepState) {
          p.el.dataset.state = j.state; p.el.querySelector(".pwc-s").textContent = j.state === "running" ? `${Math.round(jobPct(j))}%` : j.state;
          p.el.querySelector(".pwc-bar").style.width = jobPct(j) + "%";
        }
      }
      return h;
    }
    function close(id) { const p = panels.get(id); if (p) { p.el.remove(); panels.delete(id); } }
    return { open, close, anchor, get size() { return panels.size; }, el: box };
  }

  // ---- pause hold ------------------------------------------------------------------------------------------------------
  // acquire() pauses (once per session, ref-counted across the eyedropper and the menu), renews the lease while held,
  // release() resumes. Without the hold route (an older control plane) it falls back to plain session_op pause/resume.
  // maxMs: a hold never outlives this (a leaked reference must not keep a game paused forever): renewals stop and the
  // game is resumed.
  function createHold({ api, holder, ttlS = 20, renewMs = 5000, maxMs = 15 * 60 * 1000, enabled = () => true, sessionOp = null,
                        every = (f, ms) => setInterval(f, ms), stop = t => clearInterval(t), now = () => Date.now() }) {
    const held = new Map();                                     // sid -> {n, timer, mode, owned, since}
    const url = sid => `/api/pickwhip/${encodeURIComponent(sid)}/hold`;
    async function acquire(sid) {
      if (!sid || !enabled()) return { skipped: true };
      let h = held.get(sid);
      if (h) { h.n++; return { paused: true, owned: h.owned, shared: true }; }
      h = { n: 1, timer: null, mode: "hold", owned: false, since: now() };
      held.set(sid, h);
      try {
        const r = await api(url(sid), { op: "pause", holder, ttl_s: ttlS });
        h.owned = !!r.owned;
        if (held.get(sid) !== h) {                              // released while the pause was on its way: undo it now
          await api(url(sid), { op: "release", holder }).catch(() => {});
          return { paused: false, released: true };
        }
        h.timer = every(() => {
          if (now() - h.since > maxMs) return release(sid, true);
          api(url(sid), { op: "renew", holder, ttl_s: ttlS }).catch(() => {});
        }, renewMs);
        return { paused: true, owned: h.owned, via: r.via };
      } catch (e) {
        if (/404|not found/i.test(String(e.message || e)) && sessionOp) {
          h.mode = "op";
          try {
            await sessionOp(sid, "pause"); h.owned = true;
            if (held.get(sid) !== h) { await sessionOp(sid, "resume").catch(() => {}); return { paused: false, released: true }; }
            return { paused: true, owned: true, via: "session_op" };
          }
          catch (err) { if (held.get(sid) === h) held.delete(sid); return { paused: false, error: err.message }; }
        }
        if (held.get(sid) === h) held.delete(sid);
        return { paused: false, error: String(e.message || e) };
      }
    }
    async function release(sid, all = false) {
      const h = held.get(sid); if (!h) return { resumed: false };
      h.n = all ? 0 : h.n - 1;
      if (h.n > 0) return { resumed: false, shared: true };
      held.delete(sid); if (h.timer) stop(h.timer);
      if (!h.timer && !h.owned && h.mode === "hold") return { resumed: false, pending: true };   // acquire() undoes it on arrival
      try {
        if (h.mode === "op") { if (h.owned && sessionOp) await sessionOp(sid, "resume"); return { resumed: h.owned }; }
        const r = await api(url(sid), { op: "release", holder });
        return { resumed: !!r.resumed };
      } catch (e) { return { resumed: false, error: String(e.message || e) }; }
    }
    function releaseAll() { return Promise.all([...held.keys()].map(sid => release(sid, true))); }
    return { acquire, release, releaseAll, held: sid => held.has(sid), get count() { return held.size; } };
  }

  // ---- the web viewer's overlay (streamed game picture: img#scr) ---------------------------------------------------
  // io: { api, sid(), img(c) (preview url), toast(t), drag(el), place(el, x, y), blenderCopy(input), clipboard(text),
  //       retarget(o), assets(q), chatModel() }
  function mountOverlay(doc, io) {
    ensureCss(doc);
    const W = doc.defaultView || env, S = { on: false, frame: null, region: null, outline: null, target: null, cur: null, label: null, raf: 0, sid: "" };
    const holder = "web-" + Math.random().toString(36).slice(2, 8);
    const hold = createHold({ api: io.api, holder, enabled: () => settings().pause,
      sessionOp: io.sessionOp || null });
    const con = createConsole(doc, { drag: io.drag });
    const label = doc.createElement("div"); label.className = "pw-label"; label.style.display = "none"; doc.body.append(label);
    const cv = doc.createElement("canvas"); cv.id = "pwcanvas";
    Object.assign(cv.style, { position: "fixed", zIndex: 95, cursor: "crosshair", display: "none" }); doc.body.append(cv);
    const scr = () => doc.getElementById("scr");
    const rectOf = el => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; };
    const hover = createHover({
      request: at => runTool(io, "pick_preview", { session_id: S.sid, x: at[0], y: at[1], window_aspect: S.rect.w / S.rect.h }, { ms: 200, max: 50 }).then(r => r.result),
      apply: (res, at) => { S.preview = res; S.target = outlineOf(res, S.region, S.rect.w / S.rect.h); S.label = res && res.picked ? labelOf(res) : null; },
    });
    function frame() {
      S.raf = 0; if (!S.on) return;
      const el = scr(); if (!el) return stop();              // the session view went away: close (and resume)
      const r = rectOf(el);
      if (Math.abs(r.x - S.rect.x) + Math.abs(r.y - S.rect.y) + Math.abs(r.w - S.rect.w) + Math.abs(r.h - S.rect.h) > 1) {   // scrolled / resized
        S.rect = r; Object.assign(cv.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
      }
      const now = performance.now(), dt = now - (S.t || now); S.t = now;
      const c = cv.getContext("2d");
      if (S.frame) c.drawImage(S.frame, 0, 0, cv.width, cv.height); else c.clearRect(0, 0, cv.width, cv.height);
      const tgt = S.target || (S.region && outlineOf(null, S.region));
      if (tgt) { S.cur = easeBox(S.cur, tgt.box, dt); paintOutline(c, tgt, S.cur, cv.width, cv.height, { t: now, aspect: S.rect.w / S.rect.h }); }
      placeLabel(doc, label, S.rect, S.cur || [0, 0, 0, 0], tgt ? S.label || (S.region ? { name: "colour region", model: "", slot: "", kind: "", via: "no entity data here" } : null) : null);
      S.raf = W.requestAnimationFrame(frame);
    }
    async function start() {
      const el = scr(); if (S.on) return;
      if (!el) { io.toast?.("The pick whip works on the streamed game picture here; in the desktop app press Ctrl+I or right-click the game"); return; }
      S.sid = el.dataset.sid || (io.sid && io.sid()); if (!S.sid) return;
      S.on = true; S.rect = rectOf(el);
      Object.assign(cv.style, { left: S.rect.x + "px", top: S.rect.y + "px", width: S.rect.w + "px", height: S.rect.h + "px", display: "block" });
      cv.width = Math.round(S.rect.w); cv.height = Math.round(S.rect.h);
      hold.acquire(S.sid).then(r => { if (r.error) io.toast?.("⚠ could not pause: " + r.error); });
      try {                                                  // freeze the picture (same-origin MJPEG: readable pixels)
        const f = doc.createElement("canvas"); f.width = el.naturalWidth || cv.width; f.height = el.naturalHeight || cv.height;
        f.getContext("2d").drawImage(el, 0, 0, f.width, f.height); S.frame = f;
        const sm = doc.createElement("canvas"); sm.width = 240; sm.height = Math.max(1, Math.round(240 * f.height / f.width));
        sm.getContext("2d").drawImage(f, 0, 0, sm.width, sm.height); S.small = { px: sm.getContext("2d").getImageData(0, 0, sm.width, sm.height), W: sm.width, H: sm.height };
      } catch { S.frame = null; S.small = null; }
      io.toast?.("Pick whip: hover a character · right-click for actions · Esc to close");
      frame();
    }
    function stop() {
      if (!S.on) return; S.on = false; cv.style.display = "none"; label.style.display = "none";
      if (S.raf) W.cancelAnimationFrame(S.raf); S.raf = 0; S.target = S.cur = S.region = null;
      closeMenu(doc); hold.release(S.sid);
    }
    cv.addEventListener("pointermove", e => {
      const at = [(e.clientX - S.rect.x) / S.rect.w, (e.clientY - S.rect.y) / S.rect.h];
      S.region = S.small ? floodRegion(S.small.px, S.small.W, S.small.H, at) : null;
      if (!S.target && S.region) S.target = outlineOf(null, S.region);
      hover.move(at);
    });
    cv.addEventListener("contextmenu", e => { e.preventDefault(); e.stopPropagation(); menuAt(e.clientX, e.clientY); });
    cv.addEventListener("click", e => menuAt(e.clientX, e.clientY));
    doc.addEventListener("keydown", e => { if (e.key === "Escape" && S.on) stop(); });
    W.addEventListener("pagehide", () => hold.releaseAll());
    async function menuAt(cx, cy) {
      const el = scr(); if (!el) return;
      const cold = !S.on;                                     // a right-click on the playing game: the menu's own pause
      if (cold) await start();
      if (!S.on) return;
      const at = [(cx - S.rect.x) / S.rect.w, (cy - S.rect.y) / S.rect.h];
      return characterMenu(doc, io, { sid: S.sid, at, aspect: S.rect.w / S.rect.h, x: cx, y: cy, preview: S.preview, con, gid: el.closest("[data-gid]")?.dataset.gid || io.gid?.() || "",
        anchor: [S.rect.x + (S.cur ? S.cur[2] : at[0]) * S.rect.w + 12, S.rect.y + (S.cur ? S.cur[1] : at[1]) * S.rect.h],
        onClose: () => { if (cold) stop(); } });          // closing that menu resumes the game; ⌖ keeps picking open
    }
    return { start, stop, toggle: () => S.on ? stop() : start(), menuAt, get on() { return S.on; }, hold, console: con };
  }

  // ---- the character menu (desktop + web) -------------------------------------------------------------------------
  // o: { sid, at: [x, y] window fractions, aspect, x, y (screen px), preview?, con, gid, anchor: [px, py] for the console,
  //      extra: more menu items, onExtra(id), onClose() }
  // io: { api, img(c), toast, place, blenderCopy(input) -> result, clipboard(text), retarget({slug, name, gid, slot}),
  //       assets(q), chatModel() -> {name, vision}, fallbackLive({character}), fallbackBuild({character, steps}), crop() -> b64 }
  function characterMenu(doc, io, o) {
    const st = { preview: o.preview || null, ident: null, named: null, asset: null };
    const lbl = () => labelOf(st.preview, st.ident, st.named);
    const head = () => { const l = lbl(); return `${labelHTML(l)}<div class="mut">${l.via ? "via " + ESC(l.via) : "looking…"}${l.ram ? " · RAM " + ESC(l.ram) : ""}${l.id ? " · id " + ESC(l.id) : ""}</div>`; };
    const s = settings();
    const items = () => menuItems({ label: lbl(), asset: st.asset, canBlender: !!io.blenderCopy, extra: ["-",
      { id: "pause", icon: "⏸", text: `Pause while picking: ${settings().pause ? "on" : "off"}` },
      { id: "cloud", icon: "☁", text: `Cloud naming: ${settings().cloud ? "allowed" : "off (local only)"}` }].concat(o.extra || []) });
    const con = o.con || createConsole(doc, { drag: io.drag });
    if (o.anchor) con.anchor(o.anchor[0], o.anchor[1]);
    const task = (id, title) => con.open(`${id}-${Date.now().toString(36)}`, title);
    const track = h => ({ onUpdate: j => h.update(j) });
    const pickArgs = { session_id: o.sid, x: +o.at[0].toFixed(4), y: +o.at[1].toFixed(4), window_aspect: o.aspect };
    const render = () => openMenu(doc, { x: o.x, y: o.y, head: head(), items: items(), place: io.place, onPick });
    render();
    let open = true;
    const dismiss = why => { if (!open) return; open = false; doc.removeEventListener("mousedown", outside, true);
      doc.removeEventListener("keydown", esc, true); closeMenu(doc); o.onClose && o.onClose(why); };
    const outside = e => { const m = doc.getElementById("pwmenu"); if (m && !(e.target && m.contains(e.target))) dismiss("dismiss"); };
    const esc = e => { if (e.key === "Escape") dismiss("escape"); };
    doc.addEventListener("mousedown", outside, true); doc.addEventListener("keydown", esc, true);

    // fast first look (pick_preview), then the local model's name for it when the picker only knows a class
    (async () => {
      if (!st.preview) {
        try { st.preview = (await runTool(io, "pick_preview", pickArgs, { ms: 200, max: 60 })).result; } catch {}
        if (open) setMenuHead(doc, head());                  // (a newer menu may own #pwmenu by now)
      }
      if (s.name && st.preview && st.preview.picked) {
        const m = (io.chatModel && io.chatModel()) || {};
        const h = task("name", `Naming with ${m.name || "the local model"}`);
        try {
          st.named = await nameLocal(io, { sid: o.sid, x: o.at[0], y: o.at[1], aspect: o.aspect, evidence: st.preview, model: m.name,
            image: m.vision && io.crop ? await io.crop() : "", allowCloud: settings().cloud, onUpdate: j => h.update(j) });
          if (st.named) { h.done(true, `${st.named.name} (${st.named.route === "evidence" ? "picker evidence" : st.named.llm_model + ", " + st.named.route})`); if (open) setMenuHead(doc, head()); }
          else { h.done(true, "pick_name is not on this gBox yet: showing the picker's evidence"); h.collapse(); }
        } catch (e) { h.done(false, e.message); }
      }
    })();

    async function assetOf(h) {                              // the model as an asset package: known, or extracted now
      if (st.asset) return st.asset;
      const known = (st.ident && (st.ident.package || (st.ident.collection && st.ident.collection.slug && { character: st.ident.collection.slug })))
        || (st.preview && st.preview.package);
      if (known) return (st.asset = typeof known === "string" ? { package: known } : known);
      h.log("extracting the model (pick)…");
      const r = await runTool(io, "pick", pickArgs, track(h));
      if (r.ok && r.result.package) return (st.asset = { package: r.result.package });
      h.log(r.result.asset_note || r.result.asset_error || r.result.note || (r.job && r.job.error) || "no model for this entity yet");
      return null;
    }
    async function toClipboard(a, meta) {                    // gBox clipboard (the Blender add-on's paste): a GLB artifact
      if (a.package) return io.api(`/api/uap/${encodeURIComponent(a.package)}/clipboard`, {});
      return null;
    }

    async function onPick(id) {
      const l = lbl(), who = l.known ? l.name : "the character";
      if (id === "pause") { saveSettings({ pause: !settings().pause }); return render(); }
      if (id === "cloud") { saveSettings({ cloud: !settings().cloud }); return render(); }
      if (o.extra && o.extra.some(x => x.id === id)) { dismiss(id); return o.onExtra && o.onExtra(id); }
      if (id === "replace" || id === "retarget") {
        const m = doc.getElementById("pwmenu");
        m.innerHTML = `<div class="pw-head"><b>${id === "replace" ? `Replace ${ESC(who)} with…` : "Retarget which donor?"}</b><div class="mut">loading the collection…</div></div>`;
        let chars = [];
        try { chars = await io.api("/api/characters" + (o.gid ? "?game_id=" + encodeURIComponent(o.gid) : "")); } catch (e) { io.toast?.("⚠ characters: " + e.message); }
        const rows = rankCharacters(chars, { gid: o.gid, kind: l.kind });
        return browser(m, { title: id === "replace" ? `Replace ${who} with…` : `Retarget into ${l.slot || "this slot"}…`, rows, img: io.img,
          onPick: c => { dismiss("picked"); return id === "replace" ? doReplace(c, l) :
            io.retarget && io.retarget({ slug: c.slug, name: c.name, gid: o.gid, slot: l.slot || "player" }); } });
      }
      dismiss(id);
      if (id === "identify") {
        const h = task("identify", `Identify ${who}`);
        try {
          const r = await identify(io, { sid: o.sid, x: o.at[0], y: o.at[1], aspect: o.aspect, onUpdate: j => h.update(j), log: t => h.log(t) });
          if (r.source === "pick_identify") st.ident = r.result; else st.preview = r.result;
          const n = lbl();
          h.done(true, `${n.name}${n.model ? " · model " + n.model : ""}${n.slot ? " · slot " + n.slot : ""}${n.ram ? " · RAM " + n.ram : ""} (${r.source})`);
          const ev = (st.ident && (st.ident.evidence || st.ident.ghidra || st.ident.rea)) || (st.preview && st.preview.evidence);
          if (ev) h.log("evidence: " + JSON.stringify(ev).slice(0, 400));
        } catch (e) { h.done(false, e.message); }
        return;
      }
      if (id === "copy") {
        const h = task("copy", `Copy ${who}`);
        const text = `${l.name}${l.kind ? " (" + l.kind + ")" : ""}${l.model ? "\nmodel: " + l.model : ""}${l.slot ? "\nslot: " + l.slot : ""}${l.ram ? "\nRAM: " + l.ram : ""}${l.id ? "\nentity: " + l.id : ""}`;
        try { await io.clipboard?.(text); h.log("identification copied as text"); } catch {}
        try {
          const a = await assetOf(h);
          if (a && a.package) { await toClipboard(a); h.done(true, `${a.package} is on the gBox clipboard (Blender add-on: Ctrl+Shift+V)`); }
          else if (a && a.character) { h.done(true, `collection character ${a.character}: use Copy to Blender for its model`); }
          else h.done(true, "text copied; no model to put on the clipboard yet");
        } catch (e) { h.done(false, e.message); }
        return;
      }
      if (id === "blender" || id === "export") {
        const h = task(id, `${id === "blender" ? "Copy" : "Export"} ${who} to Blender`);
        try {
          const a = await assetOf(h);
          if (!a) { h.done(false, "no model for this entity yet: Identify it, or ask gBox to extract it from the disc"); return; }
          if (id === "blender") {
            let input = a.character ? { character: a.character } : null;
            if (!input) { const clip = await toClipboard(a); input = { artifact: clip.sha256 }; }
            h.log("writing Blender's clipboard on this PC…");
            const r = await io.blenderCopy(input, h);
            h.done(true, `on Blender's clipboard${r && r.host ? " on " + r.host : ""}: hover a 3D viewport, Ctrl+V`);
          } else {
            const clip = a.package ? await toClipboard(a) : null;
            if (clip) await io.api("/api/clipboard", { kind: "gltf", name: clip.name || a.package, artifact: clip.sha256,
              meta: { package: a.package, session_id: o.sid, game_id: o.gid, slot: l.slot, name: l.name, model: l.model, pick: { x: o.at[0], y: o.at[1] }, round_trip: true } });
            h.done(!!clip, clip ? "in Blender: Ctrl+Shift+V (gBox add-on), edit, then Send to gBox: it comes back to this slot"
              : `collection character ${a.character}: open it from the add-on's collection list`);
          }
        } catch (e) { h.done(false, e.message); }
        return;
      }
      if (id === "assets") { io.assets && io.assets(l.model || l.name); return; }
    }

    async function doReplace(c, l) {
      const h = task("replace", `Replace ${l.known ? l.name : "character"} → ${c.name}`);
      h.log(`donor ${c.slug}${l.slot ? " · slot " + l.slot : ""}`);
      try {
        const r = await replace(io, { sid: o.sid, character: c.slug, x: pickArgs.x, y: pickArgs.y,
          pick: { x: pickArgs.x, y: pickArgs.y, window_aspect: o.aspect, entity: st.ident || (st.preview && st.preview.picked) || null, slot: l.slot || "" },
          onUpdate: j => h.update(j), log: t => h.log(t),
          fallbackLive: io.fallbackLive ? () => io.fallbackLive({ character: c.slug, name: c.name, x: pickArgs.x, y: pickArgs.y }) : null,
          fallbackBuild: io.fallbackBuild ? steps => io.fallbackBuild({ character: c.slug, name: c.name, target: l.name, kind: l.kind, slot: l.slot, x: pickArgs.x, y: pickArgs.y, steps }) : null });
        h.done(r.ok, r.ok ? `${c.name}: ${r.mode === "live" ? "replaced live" : "build requested"} (${r.via})`
          : `could not replace: ${(r.steps || []).map(s => `${s.via} ${s.mode}: ${s.error || s.status}`).join("; ")}`);
      } catch (e) { h.done(false, e.message); }
    }
    return { state: st, onPick, render, dismiss };
  }

  return { settings, saveSettings, windowToPicture, pictureToWindow, clampBox, floodRegion, decodeMask, maskBox, maskEdges, outlineOf,
    easeBox, labelOf, labelHTML, createHover, missingTool, startJob, waitJob, runTool, identify, nameLocal, replace, rankCharacters,
    menuItems, consoleLines, fitLines, ensureCss, paintOutline, placeLabel, openMenu, setMenuHead, closeMenu, browser, createConsole,
    createHold, mountOverlay, characterMenu, PICTURE };
});
